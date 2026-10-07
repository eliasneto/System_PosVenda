"""Sincronizador do Lado 3 (Relatório EACE) do MIP — usuário pediu "as
mesmas regras de sincronização do RI" (RN-070, a criar em
`business_rules.md` pelo Orquestrador). Reaproveita as mesmas funções de
casamento com o catálogo já usadas pelo Sincronizador do RI
(`apps.ri.services.sincronizar_relatorio_eace_da_planilha`, RN-022) —
`casar_planilha_eace_com_catalogo`/`quantidade_planilha_eace` —, mas lê a
planilha do MIP (`PlanilhaRelatorioEaceMip`, RN-069) e grava em
`EscolaItemRelatorioEaceMip`, por Escola/INEP, nunca em
`RiItemRelatorioEace` (tabela do RI, intocada — as duas fontes de
planilha são independentes, RN-067)."""

import datetime
import io
import logging
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
import zipfile
from collections import Counter
from decimal import Decimal

import openpyxl
from django.conf import settings
from django.core.files.base import ContentFile
# from django.core.mail import EmailMessage  # e-mail do LOTE comentado (pedido do usuario, 2026-09-15)
from django.db import transaction
from django.db.models import DateField, OuterRef, Prefetch, Subquery
from django.utils import timezone

from apps.auditoria.models import Auditoria
from apps.auditoria.services import registrar as auditar
from apps.ri.models import KitPadrao, Ri, RiHistorico
from apps.ri.services import casar_planilha_eace_com_catalogo, quantidade_planilha_eace, trocar_status_com_log

from .models import Escola, EscolaItemRelatorioEaceMip, Lote, NotasFiscaisMip, PlanilhaRelatorioEaceMip

logger = logging.getLogger(__name__)


class RelatorioEaceMipSincronizacaoError(Exception):
    """Erro de negócio ao sincronizar o Lado 3 do MIP — a view converte em
    mensagem para o usuário."""


def _normalizar_cabecalho(valor):
    """Mesma normalização de `importar_nova_base_eace` — maiúsculas, sem
    quebra de linha/espaço duplicado — para comparar cabeçalhos de coluna
    sem depender de formatação exata. Compartilhada com o upload
    (`apps.escolas.forms.PlanilhaRelatorioEaceMipUploadForm`), que valida
    o mesmo critério na hora de aceitar o arquivo."""
    texto = (str(valor) if valor is not None else "").strip().upper()
    return " ".join(texto.split())


def aba_relatorio_eace_mip_com_colunas(workbook):
    """Primeira aba cujo cabeçalho (1ª linha) contém as colunas
    obrigatórias (`PlanilhaRelatorioEaceMip.COLUNAS_OBRIGATORIAS`) —
    nome da aba não é fixo (RN-069). `None` quando nenhuma aba serve."""
    for nome_aba in workbook.sheetnames:
        cabecalho = next(
            workbook[nome_aba].iter_rows(min_row=1, max_row=1, values_only=True), None
        )
        colunas = {_normalizar_cabecalho(valor) for valor in (cabecalho or ())}
        if set(PlanilhaRelatorioEaceMip.COLUNAS_OBRIGATORIAS) <= colunas:
            return nome_aba
    return None


def contar_notas_fiscais_zip(arquivo):
    """Conta as Notas Fiscais (.pdf) de dentro do .zip enviado na tela
    "Administrador > Relatório EACE (MIP)" (RN-XXX, a formalizar pelo
    Orquestrador; pedido do usuário, 2026-09-24) — cada .pdf é 1 Nota
    Fiscal, mesmo que referencie vários INEPs dentro dela (sem relação de
    1 para 1 com `Escola`). Ignora entradas de pasta e o lixo de metadata
    que o Finder/macOS costuma incluir (`__MACOSX/`), para não contar nada
    que não seja de fato uma Nota Fiscal. Compartilhada com o upload
    (`apps.escolas.forms.NotasFiscaisMipUploadForm`), que já validou
    (`zipfile.is_zipfile`) ser um .zip de verdade antes de chamar aqui.
    Irmã de `contar_notas_fiscais_rar` (mesmo critério, pra quem envia o
    arquivo compactado em .rar em vez de .zip, pedido do usuário)."""
    with zipfile.ZipFile(arquivo) as arquivo_zip:
        quantidade = sum(
            1
            for info in arquivo_zip.infolist()
            if not info.is_dir()
            and not info.filename.startswith("__MACOSX/")
            and info.filename.lower().endswith(".pdf")
        )
    arquivo.seek(0)
    return quantidade


def contar_notas_fiscais_rar(arquivo):
    """Mesmo critério de `contar_notas_fiscais_zip`, para quando o
    financeiro devolve o arquivo em .rar em vez de .zip (pedido do
    usuário, 2026-09-24). `rarfile` é importado aqui dentro (não no topo
    do módulo) pelo mesmo motivo do `pdfplumber` em `apps.integracoes.
    eace.extrair_dados_pdf` — não quebrar o `manage.py` inteiro se a lib
    não estiver instalada no servidor; o form (`NotasFiscaisMipUploadForm.
    clean_arquivo`) trata a falta dela como erro de validação, não como
    erro 500. Só lista os nomes dentro do .rar (nunca extrai conteúdo) —
    `rarfile` faz esse parsing do índice em Python puro, sem precisar do
    binário `unrar`/`unar` instalado no servidor (só a extração de
    conteúdo, que este contador nunca faz, precisaria dele)."""
    import rarfile

    with rarfile.RarFile(arquivo) as arquivo_rar:
        quantidade = sum(
            1
            for info in arquivo_rar.infolist()
            if not info.is_dir()
            and not info.filename.startswith("__MACOSX/")
            and info.filename.lower().endswith(".pdf")
        )
    arquivo.seek(0)
    return quantidade


_RE_CODIGO_INEPS_MIP = re.compile(r"C[ÓO]DIGO\s+INEPS?:\s*([\d/;]+)", re.IGNORECASE)


def extrair_ineps_nota_fiscal_mip(texto):
    """Lê o(s) INEP(s) do campo "CÓDIGO INEPS" da Nota Fiscal (NFS-e) do
    processo de faturamento do MIP (RN-XXX, a formalizar pelo
    Orquestrador; pedido do usuário, 2026-09-24) — layout real confirmado
    lendo um PDF de verdade (`doc/LIBERAÇÃO 22 -- PEDIDO 506/*.pdf`):
    "CÓDIGO INEPS: 35439666/19001;35448285/19001;35244764/19001 Serviço
    executado..." — 1 ou mais pares "INEP/Cód. Fornecedor" separados por
    ";" (o texto descritivo que vem depois nunca é dígito/"/"/";", então
    a classe de caracteres da regex para sozinha ali, sem precisar de um
    marcador de fim explícito). Lista vazia quando o rótulo não aparece
    no texto (PDF fora do padrão esperado — o chamador decide o que
    fazer, nunca inventa um INEP)."""
    match = _RE_CODIGO_INEPS_MIP.search(texto)
    if not match:
        return []
    return [par.split("/")[0] for par in match.group(1).split(";") if par.split("/")[0]]


def _extrair_texto_pdf_bytes(conteudo_pdf):
    """Mesmo padrão de `apps.integracoes.eace.extrair_dados_pdf.
    extrair_texto_pdf` (import de `pdfplumber` só aqui dentro — não
    quebra o `manage.py` inteiro se a lib não estiver instalada), mas a
    partir de bytes já em memória (lidos de dentro do .zip/.rar), não de
    um caminho no disco."""
    import pdfplumber

    texto = []
    with pdfplumber.open(io.BytesIO(conteudo_pdf)) as pdf:
        for pagina in pdf.pages:
            conteudo = pagina.extract_text()
            if conteudo:
                texto.append(conteudo)
    return "\n".join(texto)


def _iterar_pdfs_do_arquivo_notas_fiscais(notas_fiscais_mip):
    """Gera (nome, bytes) de cada .pdf de dentro do .zip/.rar ativo de
    Notas Fiscais — mesmo filtro (ignora pasta e lixo `__MACOSX/`) de
    `contar_notas_fiscais_zip`/`contar_notas_fiscais_rar`, mas lendo o
    CONTEÚDO de cada um (não só contando os nomes), pra extrair o(s)
    INEP(s) de dentro do PDF depois.

    Correção 2026-09-24 (bug real reportado pelo usuário, "Failed the
    read enough data: req=... got=0" a partir da 2ª Nota Fiscal
    comprimida de um .rar real): extrair arquivo POR ARQUIVO de dentro de
    um .rar (via `rarfile`, pedindo 1 nome de cada vez ao `unrar`/`unar`)
    tem limitações conhecidas dessas ferramentas com certos .rar reais
    (solid/compressão por bloco) — trocado por uma única extração de TODO
    o .rar para uma pasta temporária (`unar`, sem filtrar por nome nenhum
    — o jeito mais simples e testado de qualquer extrator de arquivo),
    depois só lendo os .pdf resultantes do disco. `.zip` continua puro
    Python (`zipfile`), sem essa limitação — só o .rar depende de
    ferramenta externa."""
    nome_arquivo = notas_fiscais_mip.nome_original.lower()
    arquivo = notas_fiscais_mip.arquivo
    if nome_arquivo.endswith(".zip"):
        with zipfile.ZipFile(arquivo) as arquivo_zip:
            for info in arquivo_zip.infolist():
                if (
                    info.is_dir()
                    or info.filename.startswith("__MACOSX/")
                    or not info.filename.lower().endswith(".pdf")
                ):
                    continue
                yield info.filename, arquivo_zip.read(info.filename)
        return

    if shutil.which("unar") is None:
        raise RelatorioEaceMipSincronizacaoError(
            "Não foi possível extrair o conteúdo do .rar — o servidor não tem a "
            "ferramenta 'unar' instalada (necessária só para .rar; .zip funciona "
            "sem ela). Peça ao DevOps para instalar, ou reenvie o arquivo em .zip."
        )

    with tempfile.TemporaryDirectory() as pasta_extraida:
        resultado = subprocess.run(
            ["unar", "-q", "-f", "-o", pasta_extraida, arquivo.path],
            capture_output=True,
        )
        if resultado.returncode != 0:
            raise RelatorioEaceMipSincronizacaoError(
                "Não foi possível extrair o conteúdo do .rar — 'unar' terminou com "
                f"erro (código {resultado.returncode}): "
                f"{resultado.stderr.decode('utf-8', 'replace').strip() or '(sem detalhe)'}"
            )
        for raiz, _pastas, nomes_arquivo in os.walk(pasta_extraida):
            for nome in nomes_arquivo:
                if not nome.lower().endswith(".pdf"):
                    continue
                with open(os.path.join(raiz, nome), "rb") as pdf_extraido:
                    yield nome, pdf_extraido.read()


def concluir_inep_com_nota_fiscal_mip(escola, usuario=None):
    """Pedido do usuário (2026-09-26; a formalizar pelo Orquestrador em
    business_rules.md): INEP do LOTE que recebe a Nota Fiscal (PDF) vai
    para "Processo Concluído" — com registro no histórico do RI atual. O
    RI continua em "Faturamento RI Concluído" (`Ri.save()`)."""
    if escola.status_mip == Escola.FATURAMENTO_CONCLUIDO:
        return
    status_anterior = escola.get_status_mip_display()
    escola.status_mip = Escola.FATURAMENTO_CONCLUIDO
    escola.save(update_fields=["status_mip"])
    ri_atual = Ri.objects.filter(escola=escola).order_by("-criado_em").first()
    if ri_atual:
        _registrar_log_campo_lote(
            ri_atual, usuario, "Status (MIP)", status_anterior, escola.get_status_mip_display(),
        )


def sincronizar_notas_fiscais_mip_lote_em_andamento():
    """Botão "Sincronizar Notas Fiscais dos INEPs" (RN-XXX, a formalizar
    pelo Orquestrador em business_rules.md; pedido do usuário,
    2026-09-24), tela "Administrador > Relatório EACE (MIP)": lê o .zip/
    .rar ativo de Notas Fiscais (`NotasFiscaisMip`), extrai o(s) INEP(s)
    de dentro de cada PDF (`extrair_ineps_nota_fiscal_mip`) e grava o PDF
    correspondente em cada `Escola` (`Escola.adicionar_ou_substituir_
    nota_fiscal_mip`) — só nos INEPs de um `Lote` "Em Andamento" no
    momento do clique (pedido explícito do usuário: "buscar dentro de
    MIP (LOTE) todos os INEPS que o lote está com status de 'Em
    Andamento'"). Uma Nota que referencia vários INEPs grava o MESMO PDF
    em cada Escola. INEP "Em Andamento" sem Nota Fiscal correspondente no
    arquivo simplesmente não é tocado (mantém o que já tinha, se houver,
    de uma sincronização anterior) — nunca apaga uma Nota Fiscal já
    gravada só porque não achou de novo nesta rodada.

    RN ampliada (bug real reportado pelo usuário, 2026-09-24): um INEP
    rateado (`escola_rateada_relatorio_eace_mip` — mesmo INEP com mais de
    1 Cidade na planilha da EACE) recebe do financeiro mais de 1 Nota
    Fiscal (1 por fração/Cidade) — várias PDFs diferentes dentro do
    mesmo .zip/.rar podem referenciar o MESMO INEP no "CÓDIGO INEPS".
    Antes desta correção, só a última Nota lida para aquele INEP
    sobrevivia (`mapa_inep_para_pdf[inep] = ...` sobrescrevia as
    anteriores); agora todas as Notas encontradas para um INEP são
    gravadas (`mapa_inep_para_pdfs[inep]`, lista) — cada uma vira 1
    `NotaFiscalMip` própria (`adicionar_ou_substituir_nota_fiscal_mip`,
    que só substitui quando o nome do PDF já foi sincronizado antes,
    nunca apaga uma Nota diferente).

    Levanta `RelatorioEaceMipSincronizacaoError` sem nenhum arquivo ativo
    (nada para sincronizar) ou se a extração do .rar falhar por falta do
    binário `unrar`/`unar` no servidor (`_iterar_pdfs_do_arquivo_notas_
    fiscais`)."""
    notas_fiscais_ativa = NotasFiscaisMip.ativa()
    if notas_fiscais_ativa is None:
        raise RelatorioEaceMipSincronizacaoError(
            "Nenhum arquivo de Notas Fiscais foi enviado ainda — envie um .zip/.rar antes de sincronizar."
        )

    mapa_inep_para_pdfs = {}
    total_pdfs_lidos = 0
    total_pdfs_sem_inep_reconhecido = 0
    for nome_pdf, conteudo_pdf in _iterar_pdfs_do_arquivo_notas_fiscais(notas_fiscais_ativa):
        total_pdfs_lidos += 1
        texto = _extrair_texto_pdf_bytes(conteudo_pdf)
        ineps = extrair_ineps_nota_fiscal_mip(texto)
        if not ineps:
            total_pdfs_sem_inep_reconhecido += 1
            logger.warning("Nota Fiscal (MIP) sem 'CÓDIGO INEPS' reconhecível: %s", nome_pdf)
            continue
        for inep in ineps:
            mapa_inep_para_pdfs.setdefault(inep, []).append((nome_pdf, conteudo_pdf))

    escolas_em_andamento = list(Escola.objects.filter(lotes__status=Lote.EM_ANDAMENTO).distinct())
    total_sincronizadas = 0
    for escola in escolas_em_andamento:
        pdfs_correspondentes = mapa_inep_para_pdfs.get(escola.inep)
        if not pdfs_correspondentes:
            continue
        for nome_pdf, conteudo_pdf in pdfs_correspondentes:
            escola.adicionar_ou_substituir_nota_fiscal_mip(conteudo_pdf, nome_pdf.rsplit("/", 1)[-1])
        total_sincronizadas += 1
        concluir_inep_com_nota_fiscal_mip(escola)

    return {
        "total_escolas_em_andamento": len(escolas_em_andamento),
        "total_sincronizadas": total_sincronizadas,
        "total_pdfs_lidos": total_pdfs_lidos,
        "total_pdfs_sem_inep_reconhecido": total_pdfs_sem_inep_reconhecido,
    }


def _texto_cod_fornecedor(valor_bruto):
    """"Cod Fornecedor" vem como número (`int`) no arquivo real (`doc/Base
    MIP.xlsx`), lido pelo `openpyxl` — convertido para texto sem casas
    decimais (`Escola.cod_fornecedor` é `CharField`, mesmo padrão do
    INEP). `""` (nunca inventa) quando o valor está vazio."""
    if valor_bruto in (None, ""):
        return ""
    if isinstance(valor_bruto, float):
        return str(int(valor_bruto))
    return str(valor_bruto).strip()


def _quantidade_relatorio_eace_mip(valor_bruto):
    """"Qtde Produto" vem como número (`int`/`float`) no arquivo real
    (`doc/Base MIP.xlsx`), lido pelo `openpyxl` — diferente do texto bruto
    com vírgula decimal que `quantidade_planilha_eace` (RN-022) espera de
    um `csv.DictReader`. Número já vem pronto, usado direto (célula de
    texto, se algum dia existir, ainda cai na mesma regra de sempre);
    nunca inventa 1 quando o valor é 0/negativo/vazio."""
    if isinstance(valor_bruto, bool):
        return None
    if isinstance(valor_bruto, int):
        return valor_bruto if valor_bruto > 0 else None
    if isinstance(valor_bruto, float):
        quantidade = int(valor_bruto)
        return quantidade if quantidade > 0 else None
    return quantidade_planilha_eace(valor_bruto)


def _parse_data_emissao_acs(valor):
    """Coluna "Data Emissão ACS" vem como texto "dd/mm/aaaa" no arquivo
    real (`doc/Base MIP.xlsx`), não como data — `None` (nunca inventa)
    quando o valor está vazio ou não bate com esse formato."""
    if isinstance(valor, datetime.datetime):
        return valor.date()
    if isinstance(valor, datetime.date):
        return valor
    texto = str(valor).strip() if valor not in (None, "") else ""
    if not texto:
        return None
    try:
        return datetime.datetime.strptime(texto, "%d/%m/%Y").date()
    except ValueError:
        return None


def _agrupar_linhas_relatorio_eace_mip_por_inep(planilha_ativa):
    """Lê o `.xlsx` ativo (RN-069) e agrupa as linhas por INEP (coluna
    "Projeto", 8 dígitos com zero à esquerda — mesma normalização de
    `apps.ri.services._agrupar_linhas_planilha_eace_por_inep`)."""
    with planilha_ativa.arquivo.open("rb") as arquivo:
        workbook = openpyxl.load_workbook(arquivo, read_only=True, data_only=True)
        try:
            nome_aba = aba_relatorio_eace_mip_com_colunas(workbook)
            if nome_aba is None:
                raise RelatorioEaceMipSincronizacaoError(
                    "Nenhuma aba do arquivo ativo tem as colunas obrigatórias: "
                    + ", ".join(PlanilhaRelatorioEaceMip.COLUNAS_OBRIGATORIAS) + "."
                )
            aba = workbook[nome_aba]
            cabecalho = next(aba.iter_rows(min_row=1, max_row=1, values_only=True))
            indice = {_normalizar_cabecalho(valor): posicao for posicao, valor in enumerate(cabecalho)}

            agrupado = {}
            for linha in aba.iter_rows(min_row=2, values_only=True):
                projeto_bruto = linha[indice["PROJETO"]]
                if projeto_bruto in (None, ""):
                    continue
                try:
                    inep = str(int(projeto_bruto)).zfill(8)
                except (TypeError, ValueError):
                    continue
                agrupado.setdefault(inep, []).append({
                    "cod_fornecedor": linha[indice["COD FORNECEDOR"]],
                    "descricao": linha[indice["DESCRIÇÃO DO ITEM"]],
                    "qtde_produto": linha[indice["QTDE PRODUTO"]],
                    "uf": linha[indice["UF"]],
                    "cidade": linha[indice["CIDADE"]],
                    "data_emissao_acs": linha[indice["DATA EMISSÃO ACS"]],
                })
            return agrupado
        finally:
            workbook.close()


def _resumo_item_relatorio_eace_mip(item):
    """Descrição curta de 1 item do Lado 3 do MIP (quantidade, Valor de
    serviço, UF/Cidade, Data Emissão ACS), usada como "antes"/"depois" no
    histórico (pedido do usuário, 2026-09-16) — texto simples, não um
    formato pra ser lido de volta pelo sistema."""
    partes = [f"{item.quantidade} un."]
    if item.valor_servico is not None:
        partes.append(f"R$ {item.valor_servico}")
    if item.uf or item.cidade:
        partes.append(f"{item.uf or '—'}/{item.cidade or '—'}")
    if item.data_emissao_acs:
        partes.append(f"Emissão {item.data_emissao_acs.strftime('%d/%m/%Y')}")
    return " — ".join(partes)


def _registrar_log_relatorio_eace_mip(ri, usuario, campo, valor_anterior, valor_novo):
    """Mesmo padrão de `apps.ri.views._registrar_log_campo`/`apps.escolas.
    views._registrar_log_campo_mip` (RN-008) — duplicado aqui (função
    pequena, `services.py` nunca importa de `views.py`, ver comentário no
    topo do arquivo) para o log do Sincronizador do Lado 3 do MIP (pedido
    do usuário, 2026-09-16)."""
    RiHistorico.objects.create(
        ri=ri,
        tipo=RiHistorico.LOG_CAMPO,
        autor=usuario,
        campo=campo,
        valor_anterior=valor_anterior,
        valor_novo=valor_novo,
    )
    auditar(
        usuario,
        Auditoria.ALTERACAO_CAMPO,
        entidade="Ri",
        entidade_id=ri.pk,
        campo=campo,
        valor_anterior=valor_anterior,
        valor_novo=valor_novo,
    )


def _sincronizar_relatorio_eace_mip_da_escola(escola, linhas, sobrepor=True, usuario=None):
    """1 Escola: mesma regra de casamento Descrição×catálogo do
    Sincronizador do RI (RN-022) — KIT por número de Access Points,
    produto avulso por prefixo da Descrição curta — mas grava o Valor de
    serviço (RN-067), por Escola. A última planilha ativa é sempre a
    fonte de verdade (sem conceito de fase/status do RI para preservar
    lançamento manual, já que aqui não existe lançamento manual, RN-067):
    Descrição confirmada nesta rodada é criada/atualizada; Descrição
    ausente é removida. Mesma regra "só 1 KIT por INEP" do RI (RN-015):
    um novo KIT nunca substitui o já lançado, só protege o existente de
    ser removido.

    `sobrepor=False` (pedido do usuário, 2026-09-16): Escola que já tem
    pelo menos 1 item lançado no Lado 3 é pulada inteira — nem atualiza
    nem remove nada dela; só quem está com o Lado 3 ainda vazio recebe os
    itens desta rodada. Retorna `(mudou, pulado)`.

    `usuario` (pedido do usuário, 2026-09-16): item criado/atualizado/
    excluído nesta chamada gera 1 entrada no histórico do RI atual da
    Escola (`RiHistorico`, mesmo painel compartilhado do RI e do MIP,
    RN-068) com o antes/depois do item e quem rodou a sincronização.
    `usuario=None` (ex.: comando de gestão sem usuário logado) só aplica
    a mudança, sem gerar histórico; Escola sem nenhum RI ainda também não
    gera (não há onde gravar — `RiHistorico` é sempre de 1 RI)."""
    itens_existentes = {item.descricao_item: item for item in escola.itens_relatorio_eace_mip.all()}
    if not sobrepor and itens_existentes:
        return False, True
    kit_existente = next((item for item in itens_existentes.values() if item.eh_kit), None)
    confirmados = set()
    mudou = False
    eventos = []  # (descricao_item, valor_anterior, valor_novo) — vira histórico no final.

    for linha in linhas:
        descricao_planilha = str(linha["descricao"] or "").strip()
        if not descricao_planilha:
            continue

        catalogo, eh_kit = casar_planilha_eace_com_catalogo(descricao_planilha, escola.lote)
        if not catalogo:
            continue

        if eh_kit:
            quantidade = 1  # RN-018: KIT sempre quantidade 1 (kit fechado da escola).
        else:
            quantidade = _quantidade_relatorio_eace_mip(linha["qtde_produto"])
            if quantidade is None:
                continue

        descricao_item = catalogo.descricao_curta or catalogo.descricao
        existente = itens_existentes.get(descricao_item)

        if eh_kit and existente is None and kit_existente is not None:
            # RN-015: já existe outro KIT lançado — esta linha é ignorada,
            # mas o KIT existente fica protegido de remoção no final.
            confirmados.add(kit_existente.descricao_item)
            continue

        uf = str(linha["uf"] or "").strip()
        cidade = str(linha["cidade"] or "").strip()
        data_emissao_acs = _parse_data_emissao_acs(linha["data_emissao_acs"])

        if existente is not None:
            confirmados.add(descricao_item)
            valor_anterior = _resumo_item_relatorio_eace_mip(existente)
            campos_alterados = []
            for campo, valor_novo in (
                ("quantidade", quantidade),
                ("valor_servico", catalogo.valor_servico),
                ("uf", uf),
                ("cidade", cidade),
                ("data_emissao_acs", data_emissao_acs),
            ):
                if getattr(existente, campo) != valor_novo:
                    setattr(existente, campo, valor_novo)
                    campos_alterados.append(campo)
            if campos_alterados:
                existente.save(update_fields=campos_alterados)
                mudou = True
                eventos.append((descricao_item, valor_anterior, _resumo_item_relatorio_eace_mip(existente)))
            continue

        novo = EscolaItemRelatorioEaceMip.objects.create(
            escola=escola,
            descricao_item=descricao_item,
            quantidade=quantidade,
            valor_servico=catalogo.valor_servico,
            eh_kit=eh_kit,
            uf=uf,
            cidade=cidade,
            data_emissao_acs=data_emissao_acs,
        )
        itens_existentes[descricao_item] = novo
        confirmados.add(descricao_item)
        if eh_kit:
            kit_existente = novo
        mudou = True
        eventos.append((descricao_item, "(sem item antes)", _resumo_item_relatorio_eace_mip(novo)))

    for descricao_item, item in itens_existentes.items():
        if descricao_item not in confirmados:
            valor_anterior = _resumo_item_relatorio_eace_mip(item)
            item.delete()
            mudou = True
            eventos.append((descricao_item, valor_anterior, "(removido)"))

    if eventos and usuario is not None:
        ri_atual = escola.ris.order_by("-criado_em").first()
        if ri_atual is not None:
            for descricao_item, valor_anterior, valor_novo in eventos:
                _registrar_log_relatorio_eace_mip(
                    ri_atual, usuario, f"Relatório EACE (MIP) — {descricao_item}", valor_anterior, valor_novo,
                )

    return mudou, False


def escolas_com_lado3_preenchido_no_arquivo_ativo():
    """Quantos INEPs do arquivo ativo (RN-069) já têm pelo menos 1 item
    lançado no Lado 3 (`EscolaItemRelatorioEaceMip`) — usado pela tela
    para decidir se o botão "Sincronizar todos os INEPs" precisa
    perguntar ao usuário se quer sobrepor os dados existentes (pedido do
    usuário, 2026-09-16) antes de rodar de verdade. `0` sem planilha
    ativa, sem nenhum INEP dela batendo com uma Escola já preenchida, ou
    quando o arquivo ativo já teve essa pergunta respondida uma vez
    (`planilha.sincronizacao_confirmada`, pedido do usuário, 2026-09-17
    — sem isso, a própria sincronização preenche o Lado 3 e a pergunta
    voltava a aparecer pra sempre, mesmo depois do usuário já ter
    escolhido).

    `0` também quando o arquivo do registro ativo sumiu do storage (bug
    real reportado pelo usuário, 2026-09-18: `FileNotFoundError` travava a
    tela inteira, sem forma de nem reenviar o arquivo) — mesmo critério de
    "sem planilha para consultar" já usado acima; a tela volta a carregar,
    o usuário reenvia a planilha quando puder."""
    planilha = PlanilhaRelatorioEaceMip.ativa()
    if not planilha or planilha.sincronizacao_confirmada:
        return 0
    try:
        ineps_da_planilha = _agrupar_linhas_relatorio_eace_mip_por_inep(planilha).keys()
    except (FileNotFoundError, OSError):
        logger.error(
            "Arquivo da Planilha EACE (MIP) ativa (id=%s) não encontrado no storage.", planilha.pk
        )
        return 0
    if not ineps_da_planilha:
        return 0
    return (
        Escola.objects.filter(inep__in=ineps_da_planilha, itens_relatorio_eace_mip__isnull=False)
        .distinct()
        .count()
    )


def sincronizar_relatorio_eace_mip_de_todas_as_escolas(sobrepor=True, usuario=None):
    """Botão "Sincronizar todos os INEPs" (Administrador > Relatório EACE
    (MIP)) — aplica `_sincronizar_relatorio_eace_mip_da_escola` a toda
    Escola de uma vez, a partir do arquivo ativo (RN-069). Levanta
    `RelatorioEaceMipSincronizacaoError` só quando não há planilha ativa
    — a view converte em mensagem de erro.

    `sobrepor=False` (pedido do usuário, 2026-09-16): Escola cujo Lado 3
    já tem algum item lançado é pulada inteira, em vez de ter seus itens
    atualizados/removidos — só quem está com o Lado 3 vazio é
    cadastrado nesta rodada. `escolas_com_lado3_preenchido_no_arquivo_
    ativo` (acima) conta antes, pra tela decidir se pergunta essa escolha
    ao usuário.

    `usuario` (pedido do usuário, 2026-09-16): repassado a
    `_sincronizar_relatorio_eace_mip_da_escola` — cada item alterado
    grava, no histórico do RI daquela Escola, o antes/depois e quem
    rodou esta sincronização em lote.

    Pedido do usuário (2026-09-17): ao final desta rodada, marca
    `planilha.sincronizacao_confirmada = True` — a pergunta "sobrepor?"
    (ver `escolas_com_lado3_preenchido_no_arquivo_ativo`) só aparece de
    novo depois de um novo upload (`PlanilhaRelatorioEaceMip.substituir`
    cria um registro novo, com a flag em `False` de novo), nunca só por
    rodar esta sincronização de novo no mesmo arquivo.

    RN-081 (a criar): também grava, em toda Escola, se o INEP apareceu ou
    não na planilha desta rodada (`Escola.encontrado_relatorio_eace_mip`)
    — vira a bolinha verde/vermelha do grid do MIP. Sempre grava (mesmo
    quando `False`), pra refletir sempre o resultado desta sincronização,
    nunca de uma anterior — independente de `sobrepor` (é só uma marca de
    presença, não conteúdo do Lado 3).

    Também grava `Escola.cod_fornecedor` (coluna "Cod Fornecedor" da
    planilha, igual para toda linha do mesmo INEP) — usado junto com o
    INEP para gerar o arquivo Excel pedido pelo usuário. Diferente do
    `encontrado_relatorio_eace_mip`, só é atualizado quando o INEP
    aparece com um valor preenchido: some da planilha numa rodada não
    apaga o código já gravado (mesma filosofia de "nunca apaga dado bom",
    já usada pelo período de `PlanilhaRelatorioEaceMip.substituir`)."""
    planilha = PlanilhaRelatorioEaceMip.ativa()
    if not planilha:
        raise RelatorioEaceMipSincronizacaoError(
            "Nenhum Relatório EACE (MIP) ativo. Envie o arquivo em Administrador > "
            "Relatório EACE (MIP) antes de sincronizar."
        )

    linhas_por_inep = _agrupar_linhas_relatorio_eace_mip_por_inep(planilha)
    # Catálogo não é pré-carregado aqui de propósito: mesmo perfil de
    # consulta do Sincronizador do RI (`casar_planilha_eace_com_catalogo`
    # consulta `KitPadrao.objects` por linha) — "mesmas regras de
    # sincronização do RI" inclui esse comportamento já existente, não só
    # o resultado.
    escolas_atualizadas = 0
    escolas_sem_linha = 0
    escolas_puladas_ja_preenchidas = 0
    for escola in Escola.objects.all():
        linhas = linhas_por_inep.get(escola.inep, [])
        encontrado = bool(linhas)
        campos_alterados = []
        if escola.encontrado_relatorio_eace_mip != encontrado:
            escola.encontrado_relatorio_eace_mip = encontrado
            campos_alterados.append("encontrado_relatorio_eace_mip")
        if encontrado:
            cod_fornecedor = _texto_cod_fornecedor(linhas[0]["cod_fornecedor"])
            if cod_fornecedor and escola.cod_fornecedor != cod_fornecedor:
                escola.cod_fornecedor = cod_fornecedor
                campos_alterados.append("cod_fornecedor")
        if campos_alterados:
            escola.save(update_fields=campos_alterados)
        if not linhas:
            escolas_sem_linha += 1
            continue
        mudou, pulado = _sincronizar_relatorio_eace_mip_da_escola(escola, linhas, sobrepor=sobrepor, usuario=usuario)
        if pulado:
            escolas_puladas_ja_preenchidas += 1
        elif mudou:
            escolas_atualizadas += 1

    if not planilha.sincronizacao_confirmada:
        planilha.sincronizacao_confirmada = True
        planilha.save(update_fields=["sincronizacao_confirmada"])

    return {
        "escolas_atualizadas": escolas_atualizadas,
        "escolas_sem_linha": escolas_sem_linha,
        "escolas_puladas_ja_preenchidas": escolas_puladas_ja_preenchidas,
    }


# ---------------------------------------------------------------------------
# RN-076 (a criar): Valor Total (IXC) do grid do MIP — funções movidas de
# `apps.escolas.views` para cá (2026-09-08) porque são regra de negócio, não
# view, e passaram a ser reaproveitadas também por
# `gerar_planilha_faturamento_implantacao` (abaixo). `views.py` importa as 3
# funções daqui no lugar das definições locais que existiam antes —
# `services.py` nunca importa de `views.py`, então não há ciclo (só
# `views -> services`, sentido único, como já era).
# ---------------------------------------------------------------------------


def _valor_servico(descricao, eh_kit, lote, catalogo):
    """Valor de serviço (`KitPadrao.valor_servico`) do item, resolvido pela
    mesma descrição gravada nele — `None` sem valor inventado quando não há
    correspondência no catálogo (CLAUDE.md §9)."""
    match = KitPadrao.resolver_por_item(descricao, eh_kit=eh_kit, lote=lote, catalogo=catalogo)
    return match.valor_servico if match else None


def _resolver_lado3_relatorio_eace_ri(ri, lote, catalogo):
    """RN-095 (nova, a formalizar pelo Orquestrador em business_rules.md;
    pedido do usuário, 2026-09-12): Dados do Relatório EACE da própria RI
    (`RiItemRelatorioEace`, Lado 3 da tela do RI) exibidos também no Lado
    3 do MIP (`mip_detail_view`) — só para o usuário bater visualmente se
    os dois relatórios batem entre si (o quanto a RI já lançou × o que a
    planilha do MIP trouxe, `_resolver_lado3_relatorio_eace_mip`, abaixo),
    separados por uma linha horizontal no template. Puramente de leitura:
    nunca grava nada em `EscolaItemRelatorioEaceMip`, nunca altera o
    Sincronizador do MIP nem o do RI — RN-067 (as duas fontes nunca se
    misturam de fato) continua valendo, isto é só as duas listas lado a
    lado na mesma tela. Mesmo Valor de serviço resolvido pelo catálogo
    (não o Valor de equipamento gravado no item) — mesmo padrão de
    `_resolver_lado_ixc`, abaixo."""
    if not ri:
        return []
    return [
        {
            "pk": item.pk,
            "descricao": item.descricao_item,
            "quantidade": item.quantidade,
            "valor_servico": _valor_servico(item.descricao_item, item.eh_kit, lote, catalogo),
        }
        for item in ri.itens_relatorio_eace.all()
    ]


def _resolver_lado_ixc(ri, lote, catalogo):
    """2º lado (IXC) do grid do MIP — mesmos itens do RI (`RiItemIxc`), sem
    lançamento próprio nesta tela: lançar/editar continua exclusivo da
    tela do RI (Projeto > Equipamentos), inclusive quando o INEP está com
    `Escola.status_mip == "Em Andamento"` (RN-092) — nesse status o INEP
    volta a aparecer lá normalmente, com o mesmo formulário de sempre.
    `pk` incluído para o template destacar em vermelho os itens
    divergentes do confronto com o Lado 3 (`itens_ixc_divergentes_pks`,
    `apps.escolas.views._comparar_valor_servico_ixc_relatorio_mip`).
    `eh_kit` incluído (pedido do usuário, 2026-09-24) para o template
    decidir quem pode ser excluído pelo MIP — o KIT nunca pode
    (`mip_item_ixc_delete_view`)."""
    if not ri:
        return []
    return [
        {
            "pk": item.pk,
            "descricao": item.descricao_item,
            "quantidade": item.quantidade,
            "valor_servico": _valor_servico(item.descricao_item, item.eh_kit, lote, catalogo),
            "eh_kit": item.eh_kit,
        }
        for item in ri.itens_ixc.all()
    ]


def _resolver_lado3_relatorio_eace_mip(escola):
    """3º lado (Relatório EACE) do MIP — itens lançados pelo Sincronizador
    da planilha do MIP (RN-069/RN-070), por Escola; tabela própria
    (`EscolaItemRelatorioEaceMip`), independente do Lado 3 do RI
    (RN-067). `pk` incluído para o template destacar em vermelho o
    produto divergente do confronto com o Lado IXC
    (`itens_mip_divergentes_pks`, `apps.escolas.views.
    _comparar_valor_servico_ixc_relatorio_mip`). Movida de `views.py` para
    cá em 2026-09-14 (FEAT-044) pelo mesmo motivo das outras funções desta
    seção: passou a ser reaproveitada fora do módulo de views
    (`escolas_elegiveis_lote_mip`, abaixo)."""
    return [
        {
            "pk": item.pk,
            "descricao": item.descricao_item,
            "quantidade": item.quantidade,
            "valor_servico": item.valor_servico,
        }
        for item in escola.itens_relatorio_eace_mip.all()
    ]


def _valor_total_itens(itens):
    """RN-076/RN-077 (a criar): soma quantidade × Valor de serviço de uma
    lista de itens do MIP — mesmo formato de dict usado tanto pelo Lado IXC
    (`_resolver_lado_ixc`, coluna "Valor Total (IXC)") quanto pelo Lado
    Relatório EACE (`_resolver_lado3_relatorio_eace_mip`, acima, coluna
    "Valor Total (EACE)") — chaves "quantidade"/"valor_servico".

    Item sem Valor de serviço (`None` — sem correspondência no catálogo no
    Lado IXC, RN-067; ou não preenchido na planilha de origem no Lado
    Relatório EACE) não entra na soma — nunca inventa valor (CLAUDE.md §9) —
    mas marca o total como incompleto, pro chamador avisar que ele não
    reflete todos os itens lançados. Sem nenhum item, não há total a
    mostrar (`None`, não zero — zero sugeriria um total conferido, não a
    ausência de dado)."""
    if not itens:
        return None, False
    total = Decimal("0.00")
    incompleto = False
    for item in itens:
        if item["valor_servico"] is None:
            incompleto = True
            continue
        total += item["quantidade"] * item["valor_servico"]
    return total, incompleto


def _normalizar_texto_cidade(texto):
    """Mesma normalização usada para comparar a Cidade de 1 grupo de
    rateio com `Lote.municipio`/`Escola.municipio` — sem acento nem caixa
    não importam aqui (RN a formalizar, pedido do usuário, 2026-09-24),
    só o texto bruto (nunca alterado) é que aparece na tela/planilha."""
    sem_acento = unicodedata.normalize("NFKD", (texto or "").strip())
    return "".join(caractere for caractere in sem_acento if not unicodedata.combining(caractere)).casefold()


def _grupos_rateio_relatorio_eace_mip_da_escola(escola):
    """Agrupa os itens do Lado 3 (Relatório EACE) desta Escola pela Cidade
    da planilha de origem (coluna "Cidade", RN-069) — base da detecção de
    rateio (pedido do usuário, 2026-09-24): a planilha da EACE às vezes
    traz o mesmo INEP com linhas de Cidades diferentes (ex.: "Brasília" e
    "Brasília2", a 2ª sendo a fração rateada do mesmo INEP). Ordem de 1ª
    aparição (`EscolaItemRelatorioEaceMip` sem `ordering` próprio cai no
    `pk`, criado na mesma ordem das linhas da planilha,
    `_sincronizar_relatorio_eace_mip_da_escola`). Item sem Cidade
    preenchida entra no grupo "" — nunca descartado, mas nunca conta como
    rateio sozinho (`escola_rateada_relatorio_eace_mip`, abaixo)."""
    grupos = {}
    for item in escola.itens_relatorio_eace_mip.all():
        cidade = (item.cidade or "").strip()
        grupos.setdefault(cidade, []).append(item)
    return grupos


def escola_rateada_relatorio_eace_mip(escola):
    """`True` quando os itens do Lado 3 (EACE) desta Escola vêm de 2 ou
    mais Cidades diferentes e preenchidas (rateio, pedido do usuário
    2026-09-24) — usado pela seta de detalhe no modal "Revisar INEPs do
    LOTE" (`_modal_criar_lote.html`, `apps.escolas.views.mip_inep_view`) e
    pela divisão da planilha de faturamento por Cidade
    (`planilhas_faturamento_implantacao_lote`, abaixo). Cidade não
    preenchida não conta (só 1 Cidade real, sem rateio de verdade)."""
    grupos = _grupos_rateio_relatorio_eace_mip_da_escola(escola)
    return sum(1 for cidade in grupos if cidade) > 1


def rateio_relatorio_eace_mip_da_escola(escola):
    """Detalhe do rateio desta Escola (pedido do usuário, 2026-09-24) — 1
    linha por Cidade preenchida do Lado 3 (EACE), com a soma de
    quantidade × Valor de serviço daquela Cidade (mesma conta de
    `_valor_total_itens`, RN-076/RN-077, mas por grupo de Cidade) — usado
    pela seta de detalhe no modal "Revisar INEPs do LOTE" e pela divisão
    da planilha de faturamento por Cidade. Maior valor primeiro. `[]`
    quando a Escola não está rateada
    (`escola_rateada_relatorio_eace_mip`) — a tela só mostra a seta quando
    há de fato mais de 1 Cidade."""
    if not escola_rateada_relatorio_eace_mip(escola):
        return []
    detalhe = []
    for cidade, itens in _grupos_rateio_relatorio_eace_mip_da_escola(escola).items():
        if not cidade:
            continue
        valor, incompleto = _valor_total_itens(
            [{"quantidade": item.quantidade, "valor_servico": item.valor_servico} for item in itens]
        )
        detalhe.append({"cidade": cidade, "valor": valor, "incompleto": incompleto})
    detalhe.sort(key=lambda linha: linha["valor"] or Decimal("0.00"), reverse=True)
    return detalhe


# ---------------------------------------------------------------------------
# FEAT-044/RN-098 (a formalizar pelo Orquestrador em business_rules.md;
# pedido do usuário, 2026-09-14): "Projeto > MIP (LOTE)" — agrupa, num
# `Lote`, os INEPs do MIP em "Aguardando Validação EACE" com Valor Total
# (IXC) == Valor Total (EACE) (RN-076/RN-077) dentro do filtro Estado +
# Município + Data inicial/final já existente no grid "Projeto > MIP"
# (RN-079/RN-075) — botão "Criar LOTE" ao lado do Total geral (RN-080,
# `apps.escolas.views.mip_lote_criar_view`).
# ---------------------------------------------------------------------------


def escolas_elegiveis_lote_mip(estado, municipio, data_inicio, data_fim, *, exigir_relatorio_eace_mip=True):
    """Base elegível para um LOTE: mesma combinação de filtros do grid do
    MIP — Estado/Município (RN-079, comparados exatos, iguais ao `<select>`
    da tela) e, quando informada, Data de Ativação do RI atual (RN-075,
    `Ri.data_ativacao`, dentro de `[data_inicio, data_fim]`) — restrita
    aos INEPs com `Escola.status_mip == "Aguardando Validação EACE"` e
    cujo Valor Total (IXC) e Valor Total (EACE) (RN-076/RN-077,
    `_valor_total_itens`) sejam os DOIS conhecidos, completos (nenhum
    item sem Valor de serviço) e iguais entre si — pedido explícito do
    usuário ("que o Valor Total (IXC) seja igual ao Valor Total (EACE)").
    Um total incompleto (algum item sem Valor de serviço no catálogo) não
    entra: como o total exibido já não reflete todos os itens lançados,
    comparar IXC × EACE nessa condição arriscaria fechar um LOTE com
    valor que ainda pode mudar — decisão do Dev (2026-09-14, reversível/
    baixo risco, CLAUDE.md §9).

    RN-098 (correção, 2026-09-14 — bug real reportado pelo usuário, INEP
    52171205: filtrou só Estado/Município, sem data, e o LOTE de 1 INEP
    elegível não pôde ser criado): Data início/Data fim passam a ser
    OPCIONAIS e independentes entre si (mesmo critério de "filtro
    aberto" já usado no grid, RN-075) — informar só uma das duas
    restringe só aquela ponta; sem nenhuma das duas, não filtra por data
    nenhuma. Só Estado e Município continuam obrigatórios.

    Sem Estado ou Município, devolve lista vazia (nunca assume um filtro
    que não foi informado, CLAUDE.md §9) — quem chama decide se isso é
    erro (`criar_lote_mip`) ou só "0 elegíveis" (contador do grid,
    `apps.escolas.views.mip_inep_view`)."""
    estado = (estado or "").strip()
    municipio = (municipio or "").strip()
    if not estado or not municipio:
        return []

    ri_atual_qs = Ri.objects.filter(escola=OuterRef("pk")).order_by("-criado_em")
    data_ativacao_ri_atual = Subquery(ri_atual_qs.values("data_ativacao")[:1], output_field=DateField())
    escolas = Escola.objects.annotate(data_ativacao_ri_atual=data_ativacao_ri_atual).filter(
        status_mip=Escola.AGUARDANDO_VALIDACAO_EACE, estado=estado, municipio=municipio,
    )
    if exigir_relatorio_eace_mip:
        # Pedido do usuário (2026-09-30): LOTE só com INEP que veio no
        # Relatório EACE (MIP) — mesmo critério do grid do MIP. A
        # importação em massa desliga (a planilha dela é a própria fonte).
        escolas = escolas.filter(encontrado_relatorio_eace_mip=True)
    if data_inicio:
        escolas = escolas.filter(data_ativacao_ri_atual__gte=data_inicio)
    if data_fim:
        escolas = escolas.filter(data_ativacao_ri_atual__lte=data_fim)
    escolas = escolas.order_by("nome").prefetch_related(
        Prefetch("ris", queryset=Ri.objects.order_by("-criado_em").prefetch_related("itens_ixc")),
        "itens_relatorio_eace_mip",
    )

    catalogo_kits = list(KitPadrao.objects.all())
    elegiveis = []
    for escola in escolas:
        ris_da_escola = list(escola.ris.all())
        ri_atual = ris_da_escola[0] if ris_da_escola else None
        lado2_ixc = _resolver_lado_ixc(ri_atual, escola.lote, catalogo_kits)
        lado3_relatorio_eace_mip = _resolver_lado3_relatorio_eace_mip(escola)
        valor_total_lado2, incompleto2 = _valor_total_itens(lado2_ixc)
        valor_total_lado3, incompleto3 = _valor_total_itens(lado3_relatorio_eace_mip)
        if (
            valor_total_lado2 is not None
            and valor_total_lado3 is not None
            and not incompleto2
            and not incompleto3
            and valor_total_lado2 == valor_total_lado3
        ):
            # Pedido do usuário (2026-09-25): valor total de cada INEP no
            # modal "Revisar INEPs do LOTE" — Valor Total (IXC), o mesmo
            # que o LOTE soma em "Valor Total do LOTE" (aqui já igual ao
            # EACE, pela própria regra de elegibilidade).
            escola.valor_total_lote_mip = valor_total_lado2
            elegiveis.append(escola)
    return elegiveis


class LoteMipError(Exception):
    """Erro de negócio ao criar um LOTE do MIP (`criar_lote_mip`) — a view
    converte em mensagem para o usuário."""


def _registrar_log_campo_lote(ri, usuario, campo, valor_anterior, valor_novo):
    """Mesmo padrão de `apps.ri.views._registrar_log_campo`/
    `apps.escolas.views._registrar_log_campo_mip` (RN-008/RN-092) —
    duplicada aqui (função pequena, evita importar símbolo privado de
    outro módulo) para o log de criação de LOTE (RN-098)."""
    RiHistorico.objects.create(
        ri=ri,
        tipo=RiHistorico.LOG_CAMPO,
        autor=usuario,
        campo=campo,
        valor_anterior=valor_anterior,
        valor_novo=valor_novo,
    )
    auditar(
        usuario,
        Auditoria.ALTERACAO_CAMPO,
        entidade="Ri",
        entidade_id=ri.pk,
        campo=campo,
        valor_anterior=valor_anterior,
        valor_novo=valor_novo,
    )


@transaction.atomic
def criar_lote_mip(estado, municipio, data_inicio, data_fim, usuario, *, escola_ids=None, exigir_relatorio_eace_mip=True):
    """Cria o `Lote` com os INEPs elegíveis (`escolas_elegiveis_lote_mip`,
    acima) do filtro Estado+Município (+ Data início/fim, quando
    informada) — chamada pelo botão "Criar LOTE" da tela "Projeto > MIP"
    (`apps.escolas.views.mip_lote_criar_view`).

    RN-098 (correção, 2026-09-14 — bug real reportado pelo usuário, INEP
    52171205): só Estado e Município são OBRIGATÓRIOS aqui — Data
    início/Data fim viraram opcionais (ver `escolas_elegiveis_lote_mip`),
    mesmo padrão de "filtro aberto" já usado no grid do MIP (RN-075).

    FEAT-050 (a formalizar pelo Orquestrador em business_rules.md;
    pedido do usuário, 2026-09-14): `escola_ids`, quando informado (não
    `None`), restringe o LOTE a só os INEPs elegíveis marcados no modal
    de revisão da tela ("eu possa retirar algum INEP que não deveria
    está indo") — nunca confia cegamente na lista recebida: sempre
    interseta com o resultado de `escolas_elegiveis_lote_mip` (nunca cria
    o LOTE com um INEP que não é de fato elegível, mesmo que o POST tenha
    sido manipulado). `None` (parâmetro omitido) mantém o comportamento
    de sempre — todos os elegíveis entram, usado por quem chama esta
    função fora da tela (ex.: testes).

    Cada INEP elegível ganha `Escola.status_mip = "em_andamento"` ("Em
    Andamento MIP", pedido do usuário 2026-09-26; o LOTE nasce no mesmo
    status) e 2 entradas no histórico do RI atual
    (`RiHistorico`, painel reaproveitado do RI/MIP, RN-008): uma com a
    troca de Status (MIP), outra com o número do LOTE — pedido explícito
    do usuário ("dentro do histórico de cada INEP dentro do LOTE, deve ter
    o status e o numero do LOTE"). Tudo dentro de uma transação — ou o
    LOTE inteiro é criado (com todos os INEPs já na nova situação), ou
    nada é gravado.

    Levanta `LoteMipError` sem criar nada quando falta Estado ou
    Município, quando a data inicial é depois da final (as duas
    informadas), quando nenhum INEP é elegível, ou quando `escola_ids` é
    informado mas nenhum dos IDs recebidos bate com um elegível de
    verdade (ex.: usuário desmarcou todos no modal) — quem chamar
    converte em mensagem para o usuário."""
    estado = (estado or "").strip()
    municipio = (municipio or "").strip()
    if not estado or not municipio:
        raise LoteMipError("Informe Estado e Município para criar o LOTE.")
    if data_inicio and data_fim and data_inicio > data_fim:
        raise LoteMipError("A data inicial não pode ser depois da data final.")

    elegiveis = escolas_elegiveis_lote_mip(
        estado, municipio, data_inicio, data_fim, exigir_relatorio_eace_mip=exigir_relatorio_eace_mip,
    )
    if not elegiveis:
        periodo = f" no período informado" if (data_inicio or data_fim) else ""
        raise LoteMipError(
            f"Nenhum INEP elegível (Aguardando Validação EACE, com Valor Total IXC = EACE) "
            f"para {municipio}/{estado}{periodo}."
        )

    if escola_ids is not None:
        ids_selecionados = {str(pk) for pk in escola_ids}
        escolas = [escola for escola in elegiveis if str(escola.pk) in ids_selecionados]
        if not escolas:
            raise LoteMipError("Nenhum INEP selecionado para o LOTE — marque ao menos 1 na lista.")
    else:
        escolas = elegiveis

    lote = Lote.objects.create(
        estado=estado, municipio=municipio, data_inicio=data_inicio, data_fim=data_fim, criado_por=usuario,
        status=Lote.EM_ANDAMENTO,
    )
    _colocar_escolas_no_lote(lote, escolas, usuario)
    return lote


def _colocar_escolas_no_lote(lote, escolas, usuario):
    """Junta os INEPs ao LOTE: "Em Andamento MIP" + 2 entradas no histórico
    do RI atual (Status (MIP) e número do LOTE) — ver `criar_lote_mip`."""
    lote.escolas.add(*escolas)
    for escola in escolas:
        status_anterior = escola.get_status_mip_display()
        escola.status_mip = Escola.EM_ANDAMENTO
        escola.save(update_fields=["status_mip"])
        ris_da_escola = list(escola.ris.all())
        ri_atual = ris_da_escola[0] if ris_da_escola else None
        if ri_atual:
            _registrar_log_campo_lote(
                ri_atual, usuario, "Status (MIP)", status_anterior, escola.get_status_mip_display(),
            )
            _registrar_log_campo_lote(ri_atual, usuario, "LOTE", "", str(lote))


@transaction.atomic
def desfazer_lote_mip(lote, usuario):
    """FEAT-049 (a formalizar pelo Orquestrador em business_rules.md;
    pedido do usuário, 2026-09-14): desfaz um `Lote` — "hoje eu consigo
    construir um LOTE mas não consigo desfazer". Cada INEP volta para
    `Escola.status_mip = "aguardando_validacao_eace"` (mesmo status que
    tinha antes de entrar no LOTE, RN-098) e ganha 2 entradas no histórico
    do RI atual dele (mesmo padrão de `criar_lote_mip`: Status (MIP) e
    LOTE) — "fica no histórico de cada um essa alteração e o usuário que
    alterou" (pedido explícito do usuário). O `Lote` em si é excluído no
    final — "desfazer" desfaz a própria existência do LOTE (some da tela
    "Projeto > MIP (LOTE)"), não só o status dos INEPs; a Auditoria e o
    RiHistorico de cada INEP continuam registrando que ele existiu e foi
    desfeito, mesmo depois de o registro do `Lote` sumir daqui.

    Só permitido enquanto o LOTE ainda não avançou de verdade -
    `AGUARDANDO_ENCERRAMENTO` - porque a partir de "Em Andamento"/"Em
    Faturamento" o RI de cada INEP já pode ter sido REABERTO de verdade
    (`trocar_status_com_log`, RN-092) e "Processo Concluído" já encerra o
    processo; desfazer dali teria que reverter uma transição real do RI
    (ou um faturamento já dado como concluído), o que o usuário não pediu
    - decisão do Dev (2026-09-14, reversível/baixo risco, CLAUDE.md §9).
    Levanta `LoteMipError` fora desse status - a view converte em mensagem
    para o usuário.

    Pedido do usuário (2026-09-15): `EMAIL_ENVIADO` saiu deste critério
    porque o envio de e-mail do LOTE foi comentado (não é mais alcançado
    por um LOTE novo) - mantido só como valor histórico possível em LOTE
    antigo, sem tratamento especial aqui."""
    # Pedido do usuário (2026-09-26): o LOTE nasce "Em Andamento MIP" —
    # desfazer vale nesse status (e no antigo "Aguardando Encerramento"),
    # enquanto nenhum INEP dele recebeu Nota Fiscal ("Processo Concluído").
    if lote.status not in (Lote.EM_ANDAMENTO, Lote.AGUARDANDO_ENCERRAMENTO):
        raise LoteMipError(
            f'Não é possível desfazer {lote} — já está em "{lote.get_status_display()}".'
        )
    if lote.escolas.filter(status_mip=Escola.FATURAMENTO_CONCLUIDO).exists():
        raise LoteMipError(
            f'Não é possível desfazer {lote} — há INEP em "Processo Concluído" (Nota Fiscal já recebida).'
        )

    identificacao_lote = str(lote)
    for escola in lote.escolas.all():
        status_anterior = escola.get_status_mip_display()
        escola.status_mip = Escola.AGUARDANDO_VALIDACAO_EACE
        escola.save(update_fields=["status_mip"])
        ri_atual = Ri.objects.filter(escola=escola).order_by("-criado_em").first()
        if ri_atual:
            _registrar_log_campo_lote(
                ri_atual, usuario, "Status (MIP)", status_anterior, escola.get_status_mip_display(),
            )
            _registrar_log_campo_lote(ri_atual, usuario, "LOTE", identificacao_lote, "Desfeito")
    lote.delete()


RETIRADO_DO_GRID_MIP = "Retirado da lista (volta se vier numa nova sincronização do Relatório EACE (MIP))"


@transaction.atomic
def retirar_do_grid_mip(escola_ids, usuario):
    """Pedido do usuário (2026-09-30): tira do grid do MIP os INEPs que
    sobraram (não foram para LOTE) — só desmarca "veio no Relatório EACE
    (MIP)" (`encontrado_relatorio_eace_mip`), sem mexer em nenhum outro
    dado; o INEP volta sozinho quando aparecer numa nova sincronização.
    Só age sobre quem está de fato no grid (Aguardando Validação EACE e
    marcado como encontrado) e grava 1 entrada no histórico de cada um.
    Devolve quantos foram retirados."""
    escolas = list(
        Escola.objects.filter(
            pk__in=[pk for pk in escola_ids if str(pk).isdigit()],
            status_mip=Escola.AGUARDANDO_VALIDACAO_EACE,
            encontrado_relatorio_eace_mip=True,
        )
    )
    for escola in escolas:
        escola.encontrado_relatorio_eace_mip = False
        escola.save(update_fields=["encontrado_relatorio_eace_mip"])
        ri_atual = Ri.objects.filter(escola=escola).order_by("-criado_em").first()
        if ri_atual:
            _registrar_log_campo_lote(ri_atual, usuario, "Grid do MIP", "Na lista", RETIRADO_DO_GRID_MIP)
    return len(escolas)


def refletir_status_mip_no_ri(escola, ri, usuario):
    """Pedido do usuário (2026-09-26; a formalizar pelo Orquestrador em
    business_rules.md): INEP no MIP, qualquer Status (MIP), fica no RI como
    "Faturamento RI Concluído" — o Status (MIP) aparece no RI só como
    rótulo. Substitui a regra de 2026-09-25 ("Processo Concluído" gravava
    o RI como "Faturamento Concluído")."""
    if ri and escola.status_mip and ri.status != Ri.FATURAMENTO_RI_CONCLUIDO:
        trocar_status_com_log(ri, Ri.FATURAMENTO_RI_CONCLUIDO, usuario)


@transaction.atomic
def aplicar_status_lote_mip(lote, novo_status, usuario):
    """RN-101: troca o Status do LOTE e o Status (MIP) de TODOS os seus
    INEPs (tudo ou nada), com 1 entrada no histórico de cada INEP. Quem
    chama valida se a troca é permitida (`mip_lote_status_update_view`,
    `importar_lotes_mip_em_massa`)."""
    status_escola_novo = {
        Lote.EM_ANDAMENTO: Escola.EM_ANDAMENTO,
        Lote.EM_FATURAMENTO: Escola.EM_FATURAMENTO_LOTE,
        Lote.FATURAMENTO_CONCLUIDO: Escola.FATURAMENTO_CONCLUIDO,
    }[novo_status]
    for escola in lote.escolas.all():
        status_anterior = escola.get_status_mip_display()
        escola.status_mip = status_escola_novo
        escola.save(update_fields=["status_mip"])
        ri_atual = Ri.objects.filter(escola=escola).order_by("-criado_em").first()
        if ri_atual:
            _registrar_log_campo_lote(
                ri_atual, usuario, "Status (MIP)", status_anterior, escola.get_status_mip_display(),
            )
            refletir_status_mip_no_ri(escola, ri_atual, usuario)
    lote.status = novo_status
    lote.save(update_fields=["status"])


@transaction.atomic
def aplicar_status_lotes_mip_em_massa(lote_ids, novo_status, usuario):
    """Pedido do usuário (2026-09-30): troca o Status de N LOTEs de uma vez
    em "Projeto > MIP (LOTE)" — mesma `aplicar_status_lote_mip` de cada
    LOTE, tudo ou nada. LOTE já em "Processo Concluído" é pulado (mesma
    trava da troca individual, `mip_lote_status_update_view`). Devolve
    `(alterados, pulados)`."""
    alterados, pulados = [], []
    for lote in Lote.objects.filter(pk__in=lote_ids).order_by("pk"):
        if lote.status == Lote.FATURAMENTO_CONCLUIDO:
            pulados.append(lote)
            continue
        aplicar_status_lote_mip(lote, novo_status, usuario)
        alterados.append(lote)
    return alterados, pulados


# ---------------------------------------------------------------------------
# Pedido do usuário (2026-09-29): importação em massa de LOTEs a partir da
# planilha "BASE CONSOLIDADA MIP" (mesmo formato do Relatório EACE do MIP,
# RN-069) — comando `importar_lotes_mip_em_massa`. Decisões do usuário:
# INEP já em LOTE não é tocado; entram os INEPs que passam na regra do
# LOTE (RN-098) e também os que só estavam com o Lado EACE (MIP) vazio,
# com o Valor Total (IXC) igual ao da planilha (Lado EACE preenchido com
# as linhas da própria planilha, mesmo Sincronizador do MIP); LOTE por
# Estado + Município, criado já em "Processo Concluído".
# ---------------------------------------------------------------------------

MOTIVO_IMPORTACAO_INCLUIDO = "incluido"
MOTIVO_IMPORTACAO_JA_EM_LOTE = "ja_em_lote"
MOTIVO_IMPORTACAO_NAO_CADASTRADO = "nao_cadastrado"
MOTIVO_IMPORTACAO_STATUS = "status_mip_nao_elegivel"
MOTIVO_IMPORTACAO_VALOR = "valor_divergente"
# Pedido do usuário (2026-10-07): com `incluir_divergentes`, o INEP que
# ficaria de fora (Status (MIP) não elegível ou valores não batendo) entra
# no LOTE mesmo assim, valendo o valor faturado na planilha — o Lado IXC
# não é alterado e a divergência continua visível no drill-down do LOTE.
MOTIVO_IMPORTACAO_INCLUIDO_VALOR_PLANILHA = "incluido_valor_planilha"


class _DesfazerPreenchimentoLado3(Exception):
    """Interno: desfaz (savepoint) o Lado EACE (MIP) gravado nesta rodada
    quando, mesmo preenchido, o INEP não fica com os valores batendo."""


def _totais_lote_mip(escola, catalogo_kits):
    """Valor Total (IXC) e (EACE) do INEP, `None` quando ausente ou
    incompleto (algum item sem Valor de serviço) — mesma conta de
    `escolas_elegiveis_lote_mip`."""
    ri_atual = Ri.objects.filter(escola=escola).order_by("-criado_em").prefetch_related("itens_ixc").first()
    total_ixc, incompleto_ixc = _valor_total_itens(_resolver_lado_ixc(ri_atual, escola.lote, catalogo_kits))
    total_eace, incompleto_eace = _valor_total_itens(_resolver_lado3_relatorio_eace_mip(escola))
    return (
        None if incompleto_ixc else total_ixc,
        None if incompleto_eace else total_eace,
    )


def _registrar_historico_importacao_em_massa(escola, registro, lote, usuario, nome_arquivo):
    """Pedido do usuário (2026-09-30): 1 entrada no histórico do RI atual
    do INEP dizendo que o processo foi importado em massa — quando, por
    quem, de qual arquivo — e o que mudou (LOTE, Status (MIP), Status do
    RI, equipamentos do Lado EACE (MIP), Município); o que não mudou
    aparece como "sem alteração"."""
    ri_atual = Ri.objects.filter(escola=escola).order_by("-criado_em").first()
    if ri_atual is None:
        return
    escola.refresh_from_db(fields=["status_mip"])

    def mudanca(rotulo, antes, depois):
        if antes == depois:
            return f"- {rotulo}: sem alteração ({depois or '—'})"
        return f"- {rotulo}: {antes or '(vazio)'} → {depois}"

    if registro["lado3_preenchido"]:
        itens = ", ".join(
            f"{item.descricao_item} ({item.quantidade} un.)" for item in escola.itens_relatorio_eace_mip.all()
        )
        linha_equipamentos = f"- Equipamentos (Relatório EACE MIP): incluídos pela planilha — {itens}"
    else:
        linha_equipamentos = "- Equipamentos: sem alteração"
    if registro["motivo"] == MOTIVO_IMPORTACAO_INCLUIDO_VALOR_PLANILHA:
        total_ixc = f"R$ {registro['total_ixc']}" if registro["total_ixc"] is not None else "incompleto/vazio"
        linha_valor = (
            f"- Valor no LOTE: R$ {registro['total_planilha']} faturado na planilha "
            f"(Valor Total IXC: {total_ixc} — divergente, IXC não alterado)"
        )
    else:
        linha_valor = f"- Valor no LOTE: R$ {registro['total_planilha']} faturado na planilha (igual ao IXC)"
    municipio_anterior = registro.get("municipio_anterior")
    nome_usuario = (usuario.get_full_name() or usuario.username) if usuario else "Sistema"
    linhas = [
        f"Processo importado em massa em {timezone.localtime().strftime('%d/%m/%Y %H:%M')} "
        f"por {nome_usuario} (arquivo {nome_arquivo}).",
        "Alterações:",
        f"- LOTE: {lote} ({lote.municipio}/{lote.estado})",
        linha_valor,
        mudanca("Status (MIP)", registro["status_mip_antes"], escola.get_status_mip_display()),
        mudanca("Status do RI", registro["status_ri_antes"], ri_atual.get_status_display()),
        linha_equipamentos,
        mudanca("Município", municipio_anterior or escola.municipio, escola.municipio),
    ]
    RiHistorico.objects.create(
        ri=ri_atual, tipo=RiHistorico.IMPORTACAO_MASSA, autor=usuario, mensagem="\n".join(linhas),
    )


def importar_lotes_mip_em_massa(linhas_por_inep, usuario, *, nome_arquivo, incluir_divergentes=False):
    """`linhas_por_inep`: {INEP (8 dígitos): [linhas]} no formato de
    `_agrupar_linhas_relatorio_eace_mip_por_inep`, com a chave extra
    `valor_liberado` (Decimal, coluna "Valor Liberado ACS"). Grava tudo
    numa transação (quem chama decide se desfaz, ex.: simulação) e
    devolve `{"ineps": [...], "lotes": [...]}` — 1 entrada por INEP com o
    motivo de inclusão/exclusão e os 3 totais (planilha, IXC, EACE).

    Todo LOTE criado aqui guarda o valor faturado de cada INEP
    (`Lote.valores_faturados_planilha`), que é o valor do INEP no LOTE.
    `incluir_divergentes` (pedido do usuário, 2026-10-07): o INEP fora de
    LOTE que não passa na regra (Status (MIP) ou valores) entra mesmo
    assim (`MOTIVO_IMPORTACAO_INCLUIDO_VALOR_PLANILHA`), para o total de
    "Processo Concluído" bater com a planilha."""
    catalogo_kits = list(KitPadrao.objects.all())
    escolas = {
        escola.inep: escola
        for escola in Escola.objects.filter(inep__in=list(linhas_por_inep)).prefetch_related("lotes")
    }
    resultado_ineps = []
    candidatos = {}

    for inep, linhas in linhas_por_inep.items():
        total_planilha = sum((linha["valor_liberado"] for linha in linhas), Decimal("0.00"))
        registro = {
            "inep": inep, "total_planilha": total_planilha, "total_ixc": None, "total_eace": None,
            "lado3_preenchido": False, "lote": "",
        }
        resultado_ineps.append(registro)
        escola = escolas.get(inep)
        if escola is None:
            registro["motivo"] = MOTIVO_IMPORTACAO_NAO_CADASTRADO
            continue
        registro["estado"], registro["municipio"] = escola.estado, escola.municipio
        lotes_existentes = list(escola.lotes.all())
        if lotes_existentes:
            registro["motivo"] = MOTIVO_IMPORTACAO_JA_EM_LOTE
            registro["lote"] = ", ".join(str(lote) for lote in lotes_existentes)
            continue
        total_ixc, total_eace = _totais_lote_mip(escola, catalogo_kits)
        registro["total_ixc"], registro["total_eace"] = total_ixc, total_eace
        ri_antes = Ri.objects.filter(escola=escola).order_by("-criado_em").first()
        registro["status_mip_antes"] = escola.get_status_mip_display()
        registro["status_ri_antes"] = ri_antes.get_status_display() if ri_antes else ""
        chave_cidade = (escola.estado, _normalizar_texto_cidade(escola.municipio))
        if escola.status_mip != Escola.AGUARDANDO_VALIDACAO_EACE:
            registro["status_mip"] = escola.get_status_mip_display() or "(sem Status (MIP))"
            if incluir_divergentes:
                registro["motivo"] = MOTIVO_IMPORTACAO_INCLUIDO_VALOR_PLANILHA
                candidatos.setdefault(chave_cidade, []).append((escola, registro))
            else:
                registro["motivo"] = MOTIVO_IMPORTACAO_STATUS
            continue

        lado3_vazio = not escola.itens_relatorio_eace_mip.exists()
        if lado3_vazio and total_ixc is not None and total_ixc == total_planilha:
            try:
                with transaction.atomic():
                    _sincronizar_relatorio_eace_mip_da_escola(escola, linhas, sobrepor=False, usuario=usuario)
                    total_ixc, total_eace = _totais_lote_mip(escola, catalogo_kits)
                    if total_eace != total_planilha:
                        raise _DesfazerPreenchimentoLado3
                registro["lado3_preenchido"] = True
                registro["total_eace"] = total_eace
            except _DesfazerPreenchimentoLado3:
                total_ixc, total_eace = _totais_lote_mip(escola, catalogo_kits)

        if total_ixc is None or total_ixc != total_eace or total_eace != total_planilha:
            registro["motivo"] = MOTIVO_IMPORTACAO_INCLUIDO_VALOR_PLANILHA if incluir_divergentes else MOTIVO_IMPORTACAO_VALOR
            if incluir_divergentes:
                candidatos.setdefault(chave_cidade, []).append((escola, registro))
            continue
        registro["motivo"] = MOTIVO_IMPORTACAO_INCLUIDO
        candidatos.setdefault(chave_cidade, []).append((escola, registro))

    lotes = []
    for (estado, _municipio_normalizado), itens in sorted(candidatos.items()):
        # Pedido do usuário (2026-09-29): mesmo Município com grafias
        # diferentes no cadastro (ex.: "SAO PAULO" e "São Paulo") vira 1
        # LOTE só — o INEP com a grafia diferente passa a usar a mais
        # comum sem ser toda em maiúsculas, com registro no histórico.
        grafias = Counter(escola.municipio for escola, _ in itens)
        municipio = max(grafias, key=lambda grafia: (not grafia.isupper(), grafias[grafia]))
        for escola, registro in itens:
            if escola.municipio == municipio:
                continue
            municipio_anterior = escola.municipio
            escola.municipio = municipio
            escola.save(update_fields=["municipio"])
            registro["municipio"], registro["municipio_anterior"] = municipio, municipio_anterior
            ri_atual = Ri.objects.filter(escola=escola).order_by("-criado_em").first()
            if ri_atual:
                _registrar_log_campo_lote(ri_atual, usuario, "Município", municipio_anterior, municipio)
        try:
            lote = criar_lote_mip(
                estado, municipio, None, None, usuario, escola_ids=[escola.pk for escola, _ in itens],
                exigir_relatorio_eace_mip=False,
            )
        except LoteMipError:
            if not incluir_divergentes:
                for _, registro in itens:
                    registro["motivo"] = MOTIVO_IMPORTACAO_VALOR
                continue
            lote = Lote.objects.create(estado=estado, municipio=municipio, criado_por=usuario, status=Lote.EM_ANDAMENTO)
        if incluir_divergentes:
            # Quem a regra do LOTE (`criar_lote_mip`) não aceitou entra
            # valendo o valor faturado na planilha.
            ids_aceitos = set(lote.escolas.values_list("pk", flat=True))
            fora_da_regra = [escola for escola, _ in itens if escola.pk not in ids_aceitos]
            _colocar_escolas_no_lote(lote, fora_da_regra, usuario)
            for escola, registro in itens:
                if escola in fora_da_regra:
                    registro["motivo"] = MOTIVO_IMPORTACAO_INCLUIDO_VALOR_PLANILHA
        lote.importado_em_massa = True
        lote.arquivo_importacao = nome_arquivo
        ids_no_lote = set(lote.escolas.values_list("pk", flat=True))
        lote.valores_faturados_planilha = {
            escola.inep: str(registro["total_planilha"]) for escola, registro in itens if escola.pk in ids_no_lote
        }
        lote.save(update_fields=["importado_em_massa", "arquivo_importacao", "valores_faturados_planilha"])
        aplicar_status_lote_mip(lote, Lote.FATURAMENTO_CONCLUIDO, usuario)
        for escola, registro in itens:
            if escola.pk in ids_no_lote:
                registro["lote"] = str(lote)
                _registrar_historico_importacao_em_massa(escola, registro, lote, usuario, nome_arquivo)
            else:
                registro["motivo"] = MOTIVO_IMPORTACAO_VALOR
        lotes.append(lote)
    return {"ineps": resultado_ineps, "lotes": lotes}


def valor_total_lotes_mip_por_status():
    """{status do LOTE: valor total} pela mesma regra da coluna "Valor
    Total do LOTE" da tela "Projeto > MIP (LOTE)" (`mip_lote_inep_view`):
    por INEP, o faturado na planilha (LOTE importado em massa) ou o Valor
    Total (IXC). Usado na conferência da importação em massa."""
    catalogo_kits = list(KitPadrao.objects.all())
    totais = {status: Decimal("0.00") for status, _ in Lote.STATUS_CHOICES}
    for lote in Lote.objects.prefetch_related("escolas__ris__itens_ixc"):
        for escola in lote.escolas.all():
            valor = lote.valor_faturado_planilha(escola)
            if valor is None:
                ris_da_escola = list(escola.ris.all())
                valor, _incompleto = _valor_total_itens(
                    _resolver_lado_ixc(ris_da_escola[0] if ris_da_escola else None, escola.lote, catalogo_kits)
                )
            totais[lote.status] += valor or Decimal("0.00")
    return totais


# Pedido do usuario (2026-09-15): envio de e-mail do LOTE comentado (nao
# sera usado por enquanto) -- MIP (LOTE) passa a usar so o campo de status
# manual (Lote.EM_ANDAMENTO / Lote.EM_FATURAMENTO / Lote.FATURAMENTO_CONCLUIDO,
# ver apps.escolas.views.mip_lote_status_update_view). Codigo mantido
# comentado (nao apagado) para reativacao futura.
#
# def montar_assunto_email_lote(lote):
    # """FEAT-045 (a formalizar pelo Orquestrador em business_rules.md;
    # pedido do usuário, 2026-09-14): assunto sugerido do e-mail do LOTE —
    # mesmo padrão visual do assunto do e-mail do RI
    # (`apps.ri.views._assunto_sugerido_email`, RN-009/RN-050), mas sem o
    # código de rastreio: aquele mecanismo existe para o financeiro
    # responder e o sistema casar a resposta com o INEP certo (FEAT-009,
    # leitura automática de e-mail) — o LOTE não tem esse fluxo de leitura
    # de resposta, só o envio (pedido do usuário)."""
    # return f"Faturamento EACE — {lote} — {lote.municipio}/{lote.estado}"


# def montar_corpo_email_lote(lote):
    # """Texto simples do corpo do e-mail do LOTE — mesmo espírito de
    # `apps.ri.services.montar_corpo_email_financeiro`, adaptado para
    # listar todos os INEPs do lote (o RI lista os itens de 1 RI só)."""
    # escolas = list(lote.escolas.order_by("nome"))
    # RN-098 (correção, 2026-09-14): Data início/fim agora são opcionais
    # (ver `criar_lote_mip`) - sem as duas, o LOTE não tem período pra
    # mostrar (nunca formata `None` como data, CLAUDE.md §9).
    # if lote.data_inicio and lote.data_fim:
        # periodo = f"Período: {lote.data_inicio:%d/%m/%Y} a {lote.data_fim:%d/%m/%Y}"
    # else:
        # periodo = "Período: não informado"
    # partes = [
        # f"LOTE: {lote}",
        # f"Município/UF: {lote.municipio}/{lote.estado}",
        # periodo,
        # f"Total de INEPs: {len(escolas)}",
        # "",
        # "INEPs deste LOTE:",
    # ]
    # for escola in escolas:
        # partes.append(f"- {escola.inep} — {escola.nome}")
    # return "\n".join(partes)


# @transaction.atomic
# def enviar_email_lote(lote, *, para, assunto, mensagem, anexo_extra, usuario):
    # """FEAT-045/FEAT-046 (a formalizar pelo Orquestrador em
    # business_rules.md; pedido do usuário, 2026-09-14): envia o e-mail do
    # LOTE, avança `Lote.status` para "Email em LOTE enviado" e grava, no
    # histórico do RI atual de CADA INEP deste LOTE, que o e-mail foi
    # disparado a partir dele — pedido explícito do usuário: "todos os
    # históricos de todos os INEPs que estiver dentro desse LOTE deve
    # receber a informação que o email foi disparado do LOTE X". Mesmo
    # `tipo=RiHistorico.EMAIL` já usado pelo e-mail do RI (FEAT-008) — o
    # painel de histórico (`ri/_historico_panel.html`) já sabe exibir esse
    # tipo, nenhuma mudança de template precisou ser feita aqui.

    # Só pode ser chamada com `Lote.status` em `AGUARDANDO_ENCERRAMENTO` ou
    # já `EMAIL_ENVIADO` (reenvio permitido enquanto nada mais aconteceu
    # depois) — levanta `LoteMipError` se o LOTE já avançou para "Em
    # Andamento"/"Faturamento Concluído" (`mip_lote_status_update_view`):
    # reenviar nesse ponto reverteria `Escola.status_mip` de todo INEP do
    # LOTE de volta para "Email em LOTE enviado", inclusive de quem já saiu
    # daqui (ex.: RI reaberto) — decisão do Dev (2026-09-14, reversível/
    # baixo risco, CLAUDE.md §9).

    # "De" é sempre `settings.DEFAULT_FROM_EMAIL` (mesmo do RI, pedido do
    # usuário: "o Do email é o mesmo") — nem é parâmetro desta função, quem
    # decide é sempre o `EmailMessage`. "Para" pode chegar vazio (`[]`,
    # pedido do usuário: "o PARA pode deixar em branco") — sem nenhum
    # destinatário, `EmailMessage.send()` simplesmente não entrega nada
    # (comportamento padrão do Django, não é erro daqui); mesmo assim o
    # histórico de cada INEP é gravado e `Lote.email_enviado_em` é
    # atualizado, porque o usuário pode estar só validando o texto/anexo
    # antes de preencher o Para de verdade depois.

    # FEAT-045 (pedido do usuário, 2026-09-14, resolvendo a pendência
    # anterior desta função — "esse anexo vai ser criado futuramente"): o
    # anexo OFICIAL do e-mail do LOTE agora é gerado automaticamente,
    # SEMPRE — `gerar_planilha_faturamento_implantacao_lote` (mesmo modelo
    # `doc/FATURAMENTO IMPLANTAÇÃO.xlsx`, RN a formalizar), com os INEPs
    # fixos deste LOTE (nunca um novo filtro por Estado/Município/status —
    # ver docstring daquela função) e `data_envio=` a data de hoje (o
    # VENCIMENTO da planilha é essa data + 30 dias corridos, "a criação
    # desse documento" citada pelo usuário). Mesmo padrão do e-mail do RI
    # (`apps.ri.views.ri_enviar_email_financeiro_view`): essa planilha
    # gerada é quem fica salva no histórico de cada INEP (`RiHistorico.
    # anexo`), não o `anexo_extra` abaixo.

    # "anexo_extra" é o arquivo opcional enviado manualmente no formulário
    # de composição (mesmo espírito de `RiEmailFinanceiroForm.anexo_extra`)
    # — só mais um anexo do e-mail, somado ao acima; nunca substitui a
    # planilha gerada e não é salvo no histórico dos INEPs (mesmo critério
    # do RI: só o documento oficial fica registrado ali)."""
    # if lote.status not in (Lote.AGUARDANDO_ENCERRAMENTO, Lote.EMAIL_ENVIADO):
        # raise LoteMipError(
            # f'{lote} já está em "{lote.get_status_display()}" — não é mais possível reenviar '
            # "o e-mail deste LOTE."
        # )

    # workbook = gerar_planilha_faturamento_implantacao_lote(lote, data_envio=timezone.localdate())
    # planilha_stream = io.BytesIO()
    # workbook.save(planilha_stream)
    # planilha_bytes = planilha_stream.getvalue()
    # nome_planilha = nome_arquivo_planilha_faturamento_implantacao(lote)

    # anexo_extra_bytes = anexo_extra.read() if anexo_extra else None
    # anexo_extra_nome = anexo_extra.name if anexo_extra else None
    # anexo_extra_content_type = anexo_extra.content_type if anexo_extra else None

    # email = EmailMessage(
        # subject=assunto,
        # body=mensagem,
        # from_email=settings.DEFAULT_FROM_EMAIL,
        # to=para,
    # )
    # email.attach(nome_planilha, planilha_bytes, MIME_PLANILHA_FATURAMENTO_IMPLANTACAO)
    # if anexo_extra_bytes:
        # email.attach(anexo_extra_nome, anexo_extra_bytes, anexo_extra_content_type)
    # email.send(fail_silently=False)

    # lote.email_enviado_em = timezone.now()
    # lote.email_enviado_por = usuario
    # lote.status = Lote.EMAIL_ENVIADO
    # lote.save(update_fields=["email_enviado_em", "email_enviado_por", "status"])

    # auditar(
        # usuario,
        # Auditoria.ENVIO_EMAIL,
        # entidade="Lote",
        # entidade_id=lote.pk,
        # campo="assunto",
        # valor_novo=assunto,
    # )

    # for escola in lote.escolas.all():
        # status_anterior = escola.get_status_mip_display()
        # escola.status_mip = Escola.EMAIL_LOTE_ENVIADO
        # escola.save(update_fields=["status_mip"])

        # ri_atual = Ri.objects.filter(escola=escola).order_by("-criado_em").first()
        # if not ri_atual:
            # continue
        # entrada = RiHistorico(
            # ri=ri_atual,
            # tipo=RiHistorico.EMAIL,
            # autor=usuario,
            # mensagem=f"E-mail do {lote} enviado. Assunto: {assunto}",
        # )
        # entrada.anexo.save(nome_planilha, ContentFile(planilha_bytes), save=False)
        # entrada.save()
        # _registrar_log_campo_lote(
            # ri_atual, usuario, "Status (MIP)", status_anterior, escola.get_status_mip_display(),
        # )



# ---------------------------------------------------------------------------
# Planilha de faturamento de implantação — a pedido do usuário, gerada tanto
# a partir do mesmo filtro Estado+Município do grid "Projeto > MIP"
# (`apps.escolas.views.mip_inep_view`, `gerar_planilha_faturamento_
# implantacao`) quanto a partir dos INEPs fixos de um `Lote` (FEAT-045,
# `gerar_planilha_faturamento_implantacao_lote`, usada pelo e-mail do LOTE —
# `enviar_email_lote` — e pelo botão "Baixar planilha"). RN própria desta
# feature ainda será formalizada pelo Orquestrador em `business_rules.md`/
# `checklist.md`; aqui ela referencia as regras já existentes que
# reaproveita: RN-074 (base de escolas — RI atual em "Aguardando validação
# EACE"), RN-079 (filtro Estado/Município) e RN-076 (Valor Total IXC =
# quantidade × Valor de serviço dos itens do Lado IXC).
# ---------------------------------------------------------------------------


class PlanilhaFaturamentoImplantacaoError(Exception):
    """Erro de negócio ao gerar a planilha de faturamento de implantação
    (`gerar_planilha_faturamento_implantacao`/`gerar_planilha_faturamento_
    implantacao_lote`) — quem chamar (comando/view) converte em mensagem
    para o usuário. Nome próprio, não reaproveita `apps.ri.services.
    PlanilhaFaturamentoError`: são planilhas e fluxos diferentes (esta é por
    Estado/Município ou por LOTE, a do RI é por RI)."""


CAMINHO_PLANILHA_FATURAMENTO_IMPLANTACAO_MODELO = settings.BASE_DIR / "doc" / "FATURAMENTO IMPLANTAÇÃO.xlsx"

MIME_PLANILHA_FATURAMENTO_IMPLANTACAO = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Mesmo padrão de `apps.ri.services._CARACTERES_INVALIDOS_ARQUIVO` —
# duplicado aqui (função pequena, evita importar símbolo privado de outro
# módulo, mesmo critério já usado por `apps.escolas.forms.
# _limpar_lista_emails_lote`) para o nome do .xlsx anexado ao e-mail do
# LOTE/baixado pelo botão "Baixar planilha" (FEAT-045).
_CARACTERES_INVALIDOS_ARQUIVO_IMPLANTACAO = re.compile(r'[\\/:*?"<>|\r\n]')

# Mesmo padrão de `apps.ri.services._RE_OBS_*`/`_substituir_observacoes_nf`
# (RN-013): troca só os trechos variáveis da célula F10, preservando
# literalmente o resto do texto (nº de contrato, "DADOS BANCÁRIOS: XXXX",
# texto legal do Anexo/Portaria/Edital) copiado do modelo.
_RE_OBS_IMPLANTACAO_MUNICIPIO_UF = re.compile(r"(MUNICIPIO/UF:\s*).*?(?=\s+VENCIMENTO:)", re.DOTALL)
_RE_OBS_IMPLANTACAO_VENCIMENTO = re.compile(r"(VENCIMENTO:\s*)\S+")
_RE_OBS_IMPLANTACAO_CODIGO_INEPS = re.compile(r"(CÓDIGO INEPS:\s*).*?(?=\s+Serviço executado)", re.DOTALL)

_CARACTERES_INVALIDOS_ABA_EXCEL = re.compile(r"[\[\]:*?/\\]")


def _substituir_observacoes_faturamento_implantacao(texto_modelo, *, municipio, estado, data_str, codigos_ineps):
    """Troca MUNICIPIO/UF, VENCIMENTO e CÓDIGO INEPS no texto da célula F10
    já existente na planilha-modelo — nunca reescreve o texto do zero.

    Pedido do usuário (2026-09-16): nome do Município em maiúsculo neste
    texto de observação (`municipio.upper()`) — só aqui; o nome da aba
    (`_nome_aba_municipio`) continua na capitalização normal de
    `Escola.municipio`/`Lote.municipio`, sem mudança."""
    texto = _RE_OBS_IMPLANTACAO_MUNICIPIO_UF.sub(
        lambda m: m.group(1) + f"{municipio.upper()}/{estado}", texto_modelo, count=1
    )
    texto = _RE_OBS_IMPLANTACAO_VENCIMENTO.sub(lambda m: m.group(1) + data_str, texto, count=1)
    texto = _RE_OBS_IMPLANTACAO_CODIGO_INEPS.sub(lambda m: m.group(1) + codigos_ineps, texto, count=1)
    return texto


def _nome_aba_municipio(municipio):
    """Nome da aba = nome do Município, na mesma capitalização de
    `Escola.municipio` (pedido do usuário — a planilha-modelo já nasce com 1
    aba só, nomeada assim). Limite do Excel (máx. 31 caracteres, sem
    `[ ] : * ? / \\`) aplicado só por segurança — nenhum município real do
    projeto deveria precisar do corte."""
    limpo = _CARACTERES_INVALIDOS_ABA_EXCEL.sub("", municipio).strip()
    return limpo[:31] or municipio[:31]


def nome_arquivo_planilha_faturamento_implantacao(lote):
    """Nome do .xlsx anexado ao e-mail do LOTE (FEAT-045) e baixado pelo
    botão "Baixar planilha" — mesmo espírito de `apps.ri.services.
    nome_arquivo_planilha_faturamento` (facilita achar o arquivo certo),
    adaptado ao identificador do LOTE (não ao INEP, como no RI, já que este
    arquivo soma todos os INEPs do LOTE): "FATURAMENTO IMPLANTAÇÃO EACE -
    <Município>-<UF> - LOTE-0001.xlsx"."""
    municipio_limpo = _CARACTERES_INVALIDOS_ARQUIVO_IMPLANTACAO.sub("", lote.municipio or "").strip()
    return f"FATURAMENTO IMPLANTAÇÃO EACE - {municipio_limpo}-{lote.estado} - {lote}.xlsx"


def _nome_arquivo_planilha_faturamento_implantacao_rateio(lote, cidade):
    """Nome do .xlsx extra gerado quando o LOTE tem algum INEP rateado
    (pedido do usuário, 2026-09-24) — 1 arquivo por Cidade diferente da do
    LOTE (`nome_arquivo_planilha_faturamento_implantacao`, acima), mesmo
    padrão de nome, trocando o Município pela Cidade da planilha de
    origem (ex.: "Brasília2") e marcando "RATEIO" para não confundir com o
    arquivo principal do LOTE."""
    cidade_limpa = _CARACTERES_INVALIDOS_ARQUIVO_IMPLANTACAO.sub("", cidade or "").strip()
    return f"FATURAMENTO IMPLANTAÇÃO EACE - {cidade_limpa}-{lote.estado} - {lote} (RATEIO).xlsx"


def gerar_planilha_faturamento_implantacao(estado, municipio, data_envio):
    """Planilha de faturamento de implantação (`doc/FATURAMENTO
    IMPLANTAÇÃO.xlsx`) pedida pelo usuário: 1 arquivo por Estado+Município
    filtrado no grid "Projeto > MIP" — "os INEPs que vierem, os dados são
    somados e geram essa planilha". Reaproveita a mesma base do grid (RN-074:
    RI atual em "Aguardando validação EACE") e o mesmo filtro (RN-079:
    Estado+Município) — Estado e Município são OBRIGATÓRIOS aqui (o grid
    permite Estado sozinho; esta função não, RN própria a formalizar).

    VALOR R$ (H10) = soma do Valor Total (IXC) (RN-076) de cada escola
    filtrada — mesmo `_valor_total_itens`/`_resolver_lado_ixc` do grid, não o
    Valor Total (EACE)/Lado 3 (RN-077). Escola do filtro sem nenhum item do
    Lado IXC lançado (`_valor_total_itens` devolve `None`) soma 0 dela —
    decisão do Dev (2026-09-08, reversível/baixo risco, CLAUDE.md §9): é
    preferível gerar a planilha com uma parcela zerada, documentada aqui, a
    travar a geração inteira por causa de 1 escola sem lançamento — o
    Orquestrador decide, na RN formal, se isso deve virar aviso na tela
    quando a UI existir. Mesmo raciocínio para item sem correspondência no
    catálogo (`incompleto=True` do `_valor_total_itens`): entra na soma só
    pelo que tem valor conhecido, nunca inventado.

    CÓDIGO INEPS (dentro do texto de F10) = "<INEP>/<cod_fornecedor>" de
    cada escola filtrada, nesta ordem (mesma ordem do grid, `order_by
    ("nome")`), juntos por ";". `Escola.cod_fornecedor` vem do Sincronizador
    do Relatório EACE (MIP) (`sincronizar_relatorio_eace_mip_de_todas_as_
    escolas`); sem valor gravado ainda, entra como string vazia (nunca
    inventa dado).

    VENCIMENTO (E10, e dentro do texto de F10) = `data_envio` + 30 dias
    corridos — `data_envio` é parâmetro (ainda não há campo na tela para o
    usuário informar isso; decisão de UI pendente do usuário/Orquestrador).

    A13 = "OPERAÇÃO REDE INTERNA/IMPLANTAÇÃO  - <MÊS>/<ANO>" do momento da
    geração (`timezone.now()`), mesmo padrão de `apps.ri.services.
    gerar_planilha_faturamento` (RN-053, célula A20 daquela outra planilha).

    Demais células (cabeçalho A9:H9, CNPJ CLIENTE, RAZÃO SOCIAL, CFOP, ID
    IXC, CONTRATO EACE, textos fixos de A6/A8/A15/A16/A17 e o restante do
    texto de F10) são constantes copiadas do modelo, nunca calculadas aqui.

    Levanta `PlanilhaFaturamentoImplantacaoError` sem gerar nada quando falta
    Município (ou Estado) ou quando o filtro não encontra nenhum INEP —
    quem chamar (comando de gestão, por ora) converte em mensagem. Devolve o
    `Workbook` já preenchido, pronto para o chamador decidir o destino
    (salvar em disco, `HttpResponse`, anexo de e-mail — ainda não decidido
    pelo usuário)."""
    estado = (estado or "").strip()
    municipio = (municipio or "").strip()
    if not estado or not municipio:
        raise PlanilhaFaturamentoImplantacaoError(
            "Informe Estado e Município para gerar a planilha de faturamento de implantação."
        )

    # Mesma base do grid do MIP (RN-074): RI atual (mais recente por
    # `criado_em`) em "Aguardando validação EACE"; mesmo filtro Estado/
    # Município (RN-079), mas aqui os dois são exigidos, não opcionais.
    ri_atual_qs = Ri.objects.filter(escola=OuterRef("pk")).order_by("-criado_em")
    escolas = list(
        Escola.objects.annotate(status_ri_atual=Subquery(ri_atual_qs.values("status")[:1]))
        .filter(
            status_ri_atual=Ri.FATURAMENTO_RI_CONCLUIDO,
            estado=estado, municipio=municipio,
        )
        .order_by("nome")
        .prefetch_related(
            Prefetch("ris", queryset=Ri.objects.order_by("-criado_em").prefetch_related("itens_ixc"))
        )
    )
    if not escolas:
        raise PlanilhaFaturamentoImplantacaoError(
            f"Nenhum INEP encontrado para {municipio}/{estado}."
        )

    return _montar_planilha_faturamento_implantacao(
        escolas, estado=estado, municipio=municipio, data_envio=data_envio
    )


def gerar_planilha_faturamento_implantacao_lote(lote, data_envio):
    """FEAT-045 (a formalizar pelo Orquestrador em business_rules.md; pedido
    do usuário, 2026-09-14): mesma planilha de `gerar_planilha_faturamento_
    implantacao` acima (mesmo modelo `doc/FATURAMENTO IMPLANTAÇÃO.xlsx`,
    mesmas células calculadas), mas a partir dos INEPs FIXOS de um `Lote`
    (`lote.escolas`, RN-098) — nunca reaplica o filtro por Estado/Município/
    status daquela função: o que compõe ESTE arquivo é exatamente quem está
    no LOTE hoje, ponto (pedido do usuário: "o valor é a soma de todos os
    INEPS daquele LOTE"), mesmo que outro INEP do mesmo Estado/Município
    tenha entrado em "Aguardando validação EACE" depois da criação do LOTE
    (ou o LOTE tenha sido criado antes deste sistema separar INEPs em
    LOTEs). Usada pelo e-mail do LOTE (`enviar_email_lote`, anexo sempre
    gerado) e pelo botão "Baixar planilha" (`mip_lote_baixar_planilha_
    view`).

    Estado/Município (rótulo do texto de observação e nome da aba) vêm de
    `lote.estado`/`lote.municipio` — o "rótulo" gravado na criação do LOTE
    (RN-098), não de cada Escola individualmente (todo INEP de um mesmo
    LOTE já tem o mesmo Estado/Município, por construção de `criar_lote_
    mip`). `data_envio` é a data em que o e-mail está sendo enviado (ou a
    data de hoje, no caso do "Baixar planilha") — mesma regra de VENCIMENTO
    = `data_envio` + 30 dias corridos.

    Levanta `PlanilhaFaturamentoImplantacaoError` se o LOTE não tiver
    nenhum INEP — não deveria acontecer na prática (todo LOTE nasce com
    pelo menos 1, `criar_lote_mip`), mas esta função nunca gera uma
    planilha vazia."""
    escolas = list(
        lote.escolas.order_by("nome").prefetch_related(
            Prefetch("ris", queryset=Ri.objects.order_by("-criado_em").prefetch_related("itens_ixc"))
        )
    )
    if not escolas:
        raise PlanilhaFaturamentoImplantacaoError(f"{lote} não tem nenhum INEP.")

    return _montar_planilha_faturamento_implantacao(
        escolas, estado=lote.estado, municipio=lote.municipio, data_envio=data_envio
    )


def planilhas_faturamento_implantacao_lote(lote, data_envio):
    """RN a formalizar pelo Orquestrador em business_rules.md (pedido do
    usuário, 2026-09-24): mesma planilha de `gerar_planilha_faturamento_
    implantacao_lote` (acima), mas dividida em mais de 1 arquivo quando o
    LOTE tem algum INEP rateado (RN-069: mesma planilha da EACE trazendo o
    mesmo INEP com linhas de Cidades diferentes, ex.: "Brasília" e
    "Brasília2" — `escola_rateada_relatorio_eace_mip`).

    1 arquivo para o Município do LOTE (`lote.municipio`, sempre o
    primeiro da lista, mesmo nome de arquivo de sempre,
    `nome_arquivo_planilha_faturamento_implantacao`) — recebe o Valor
    Total (IXC) cheio de cada INEP não rateado, e só a fração da Cidade
    que bate com `lote.municipio` de cada INEP rateado (comparação sem
    acento/caixa, `_normalizar_texto_cidade`) — mais 1 arquivo extra por
    Cidade DIFERENTE encontrada entre os INEPs rateados
    (`_nome_arquivo_planilha_faturamento_implantacao_rateio`), cada um só
    com a fração daquele INEP para aquela Cidade (nunca o valor cheio).
    Ordem alfabética entre os arquivos extras.

    A fração de cada Cidade vem do Lado 3/EACE
    (`rateio_relatorio_eace_mip_da_escola`, soma de quantidade × Valor de
    serviço só daquela Cidade) — não do Lado 2/IXC (que não guarda Cidade
    por item); como a elegibilidade do LOTE já exige Valor Total (IXC) ==
    Valor Total (EACE) por INEP (RN-076/RN-077), a soma das frações de
    Cidade do Lado 3 sempre fecha com o Valor Total (IXC) inteiro do INEP.
    Item do INEP rateado sem Cidade preenchida (raro — `rateio_relatorio_
    eace_mip_da_escola` só lista Cidade preenchida) entra na fração do
    Município do LOTE — nunca é descartado (CLAUDE.md §9: nunca perde
    valor lançado).

    Sem nenhum INEP rateado, devolve sempre 1 único item na lista — mesmo
    conteúdo de `gerar_planilha_faturamento_implantacao_lote`. Devolve
    lista de `(nome_arquivo, Workbook)`. Levanta
    `PlanilhaFaturamentoImplantacaoError` nas mesmas condições de `gerar_
    planilha_faturamento_implantacao_lote` (LOTE sem nenhum INEP)."""
    escolas = list(
        lote.escolas.order_by("nome").prefetch_related(
            Prefetch("ris", queryset=Ri.objects.order_by("-criado_em").prefetch_related("itens_ixc")),
            "itens_relatorio_eace_mip",
        )
    )
    if not escolas:
        raise PlanilhaFaturamentoImplantacaoError(f"{lote} não tem nenhum INEP.")

    catalogo_kits = list(KitPadrao.objects.all())
    municipio_lote_normalizado = _normalizar_texto_cidade(lote.municipio)

    contribuicoes_municipio_lote = []
    contribuicoes_por_cidade_extra = {}
    for escola in escolas:
        if not escola_rateada_relatorio_eace_mip(escola):
            ris_da_escola = list(escola.ris.all())
            ri_atual = ris_da_escola[0] if ris_da_escola else None
            itens_ixc = _resolver_lado_ixc(ri_atual, escola.lote, catalogo_kits)
            valor_total_ixc, _incompleto = _valor_total_itens(itens_ixc)
            contribuicoes_municipio_lote.append((escola, valor_total_ixc))
            continue

        for linha_rateio in rateio_relatorio_eace_mip_da_escola(escola):
            cidade = linha_rateio["cidade"]
            valor = linha_rateio["valor"]
            if _normalizar_texto_cidade(cidade) == municipio_lote_normalizado:
                contribuicoes_municipio_lote.append((escola, valor))
            else:
                contribuicoes_por_cidade_extra.setdefault(cidade, []).append((escola, valor))

        # Item sem Cidade preenchida não aparece em `rateio_relatorio_eace_
        # mip_da_escola` (só lista Cidade preenchida) — nunca descartado
        # aqui: entra na fração do Município do LOTE (nunca perde valor
        # lançado, CLAUDE.md §9).
        itens_sem_cidade = _grupos_rateio_relatorio_eace_mip_da_escola(escola).get("", [])
        if itens_sem_cidade:
            valor_sem_cidade, _incompleto = _valor_total_itens(
                [{"quantidade": item.quantidade, "valor_servico": item.valor_servico} for item in itens_sem_cidade]
            )
            contribuicoes_municipio_lote.append((escola, valor_sem_cidade))

    planilhas = [
        (
            nome_arquivo_planilha_faturamento_implantacao(lote),
            _montar_planilha_faturamento_implantacao_de_contribuicoes(
                contribuicoes_municipio_lote, estado=lote.estado, municipio=lote.municipio, data_envio=data_envio
            ),
        )
    ]
    for cidade in sorted(contribuicoes_por_cidade_extra):
        workbook = _montar_planilha_faturamento_implantacao_de_contribuicoes(
            contribuicoes_por_cidade_extra[cidade], estado=lote.estado, municipio=cidade, data_envio=data_envio
        )
        planilhas.append((_nome_arquivo_planilha_faturamento_implantacao_rateio(lote, cidade), workbook))
    return planilhas


def _montar_planilha_faturamento_implantacao(escolas, *, estado, municipio, data_envio):
    """Preenche o modelo `doc/FATURAMENTO IMPLANTAÇÃO.xlsx` a partir de uma
    lista de `escolas` já resolvida pelo chamador — compartilhado por
    `gerar_planilha_faturamento_implantacao` (filtro Estado+Município do
    grid "Projeto > MIP") e `gerar_planilha_faturamento_implantacao_lote`
    (INEPs fixos de um `Lote`, FEAT-045): só muda de onde vêm as escolas, o
    preenchimento da planilha é sempre o mesmo — 1 contribuição por Escola,
    sempre o Valor Total (IXC) cheio dela. Ver `_montar_planilha_
    faturamento_implantacao_de_contribuicoes` (abaixo) para o caso de uma
    Escola contribuir só com uma fração do valor (INEP rateado,
    `planilhas_faturamento_implantacao_lote`)."""
    # Catálogo carregado uma única vez (fora do loop), mesmo padrão anti-N+1
    # já usado pelo grid do MIP (RN-010/RN-076).
    catalogo_kits = list(KitPadrao.objects.all())
    contribuicoes = []
    for escola in escolas:
        ris_da_escola = list(escola.ris.all())
        ri_atual = ris_da_escola[0] if ris_da_escola else None
        itens_ixc = _resolver_lado_ixc(ri_atual, escola.lote, catalogo_kits)
        valor_total_ixc, _incompleto = _valor_total_itens(itens_ixc)
        contribuicoes.append((escola, valor_total_ixc))

    return _montar_planilha_faturamento_implantacao_de_contribuicoes(
        contribuicoes, estado=estado, municipio=municipio, data_envio=data_envio
    )


def _montar_planilha_faturamento_implantacao_de_contribuicoes(contribuicoes, *, estado, municipio, data_envio):
    """Mesmo preenchimento de `_montar_planilha_faturamento_implantacao`
    (acima), mas a partir de uma lista `(escola, valor)` já resolvida pelo
    chamador, em vez de recalcular o Valor Total (IXC) cheio de cada
    Escola — usada pela divisão da planilha de faturamento por Cidade de
    um INEP rateado (pedido do usuário, 2026-09-24,
    `planilhas_faturamento_implantacao_lote`), onde a MESMA Escola pode
    aparecer em mais de 1 planilha, cada uma só com a fração de valor
    daquela Cidade (nunca o Valor Total (IXC) inteiro dela)."""
    total_valor_ixc = Decimal("0.00")
    codigos_ineps = []
    for escola, valor in contribuicoes:
        total_valor_ixc += valor or Decimal("0.00")
        codigos_ineps.append(f"{escola.inep}/{escola.cod_fornecedor}")

    data_vencimento = data_envio + datetime.timedelta(days=30)
    data_vencimento_str = data_vencimento.strftime("%d/%m/%Y")

    workbook = openpyxl.load_workbook(CAMINHO_PLANILHA_FATURAMENTO_IMPLANTACAO_MODELO)
    aba = workbook.worksheets[0]
    # Renomeado em 2 passos por uma peculiaridade do openpyxl: o setter de
    # `title` (`avoid_duplicate_name`) compara o novo nome com os nomes já
    # existentes SEM diferenciar maiúsculas/minúsculas — como a aba do
    # modelo já se chama "ABADIÂNIA" (maiúsculo), renomear direto para
    # "Abadiânia" (mesma grafia, capitalização de `Escola.municipio`) é
    # visto como um "nome duplicado" da própria aba, e o openpyxl apenda um
    # "1" (renomeia para "Abadiânia1", nunca visto pelo teste manual — só
    # reproduzido programaticamente). Passar por um nome intermediário sem
    # relação nenhuma com o município evita o falso positivo.
    aba.title = "_RENOMEANDO_"
    aba.title = _nome_aba_municipio(municipio)

    aba["E10"] = data_vencimento
    aba["F10"] = _substituir_observacoes_faturamento_implantacao(
        aba["F10"].value or "",
        municipio=municipio,
        estado=estado,
        data_str=data_vencimento_str,
        codigos_ineps=";".join(codigos_ineps),
    )
    # RN-053 (mesmo padrão de `apps.ri.services.gerar_planilha_faturamento`):
    # mês/ano sempre do momento da geração, nunca de um campo salvo — dobra
    # sozinho para o mês/ano seguinte sem precisar de manutenção.
    agora = timezone.now()
    mes_nome = dict(Ri.MESES_OPERACAO_CHOICES).get(agora.month, "")
    aba["A13"] = f"OPERAÇÃO REDE INTERNA/IMPLANTAÇÃO  - {mes_nome.upper()}/{agora.year}"
    aba["H10"] = float(total_valor_ixc)

    return workbook


# ---------------------------------------------------------------------------
# Pedido do usuário (2026-10-07): aba "Faturamento MIP" do Dashboard — mesmo
# formato da aba Faturamento (RI), comparando o valor do MIP no sistema, por
# Status (MIP), com a planilha "BASE CONSOLIDADA MIP" (total faturado).
# ---------------------------------------------------------------------------

CAMINHO_BASE_CONSOLIDADA_MIP = settings.BASE_DIR / "doc" / "BASE CONSOLIDADA MIP 2026.xlsb"
_cache_planilha_mip = {}


def valores_planilha_base_consolidada_mip(caminho=None):
    """{INEP: {"valor", "uf", "cidade"}} da planilha "BASE CONSOLIDADA MIP"
    (soma do "Valor Liberado ACS" por INEP), ou `None` sem a planilha.
    Guardado em memória enquanto o arquivo não muda (mesma data de
    modificação) — a planilha só é lida de novo quando é trocada."""
    from apps.escolas.management.commands.importar_lotes_mip_em_massa import _abas_da_planilha, _linhas_por_inep

    caminho = caminho or CAMINHO_BASE_CONSOLIDADA_MIP
    try:
        chave = (str(caminho), os.path.getmtime(caminho))
    except OSError:
        return None
    if chave not in _cache_planilha_mip:
        try:
            _aba, linhas_por_inep = _linhas_por_inep(_abas_da_planilha(caminho))
        except Exception:
            logger.exception("Não foi possível ler a planilha %s", caminho)
            return None
        _cache_planilha_mip.clear()
        _cache_planilha_mip[chave] = {
            inep: {
                "valor": sum((linha["valor_liberado"] for linha in linhas), Decimal("0.00")),
                "uf": str(linhas[0]["uf"] or "").strip().upper(),
                "cidade": str(linhas[0]["cidade"] or "").strip(),
            }
            for inep, linhas in linhas_por_inep.items()
        }
    return _cache_planilha_mip[chave]


def _valor_inep_mip(escola, catalogo_kits):
    """Valor do INEP no MIP — mesma regra da coluna "Valor Total do LOTE"
    (`mip_lote_inep_view`): no LOTE importado em massa, o faturado na
    planilha; senão (ou sem LOTE), o Valor Total (IXC)."""
    for lote in escola.lotes.all():
        valor = lote.valor_faturado_planilha(escola)
        if valor is not None:
            return valor
    ris_da_escola = list(escola.ris.all())
    valor, _incompleto = _valor_total_itens(
        _resolver_lado_ixc(ris_da_escola[0] if ris_da_escola else None, escola.lote, catalogo_kits)
    )
    return valor


def _percentual_css(valor, total):
    if not total:
        return "0"
    return str(min(Decimal("100"), valor / total * 100).quantize(Decimal("0.1")))


def _meta_servico_por_escola(catalogo_kits):
    """{INEP: (estado, município, valor)} — "Valor Total do Projeto" do
    MIP, pedido do usuário (2026-10-07): Kit + Nobreak iniciais (1º lado)
    de cada escola, pelo valor de SERVIÇO da LPU por Lote — mesma conta do
    card da aba Faturamento (`montar_dashboard_financeiro`), que usa o
    valor de equipamento. Sem correspondência no catálogo, conta zero."""
    def servico(item):
        return Decimal(str(item.valor_servico)) if item and item.valor_servico not in (None, "") else Decimal("0")

    metas = {}
    for escola in Escola.objects.only("inep", "estado", "municipio", "kit_inicial", "nobreak_inicial", "lote"):
        kit = KitPadrao.resolver_kit_declarado(escola.kit_inicial, lote=escola.lote, catalogo=catalogo_kits)
        nobreak = KitPadrao.resolver_nobreak_declarado(escola.nobreak_inicial, lote=escola.lote, catalogo=catalogo_kits)
        metas[escola.inep] = (escola.estado, escola.municipio, servico(kit) + servico(nobreak))
    return metas


def montar_dashboard_faturamento_mip(
    *, estado=None, municipio=None, status_selecionado=None, uf_selecionada=None, conferencia_planilha=False,
):
    """Dados da aba "Faturamento MIP". Cada INEP do MIP (com Status (MIP))
    entra no seu status com o valor do sistema (`_valor_inep_mip`) e o
    valor da planilha; INEP da planilha que não está no MIP entra só no
    total da planilha. Estado/Município vêm do cadastro da Escola (da
    planilha, para INEP não cadastrado); `municipio` só vale com `estado`.
    A meta (Valor Total do Projeto) é `_meta_servico_por_escola`.

    `conferencia_planilha` (`settings.MIP_CONFERENCIA_PLANILHA`, pedido do
    usuário: só na validação local, nunca em produção): sem ela a planilha
    nem é lida e todos os valores de planilha ficam vazios."""
    planilha = (valores_planilha_base_consolidada_mip() or {}) if conferencia_planilha else {}
    catalogo_kits = list(KitPadrao.objects.all())
    escolas = (
        (Escola.objects.exclude(status_mip="") | Escola.objects.filter(inep__in=list(planilha)))
        .distinct()
        .prefetch_related("lotes", Prefetch("ris", queryset=Ri.objects.prefetch_related("itens_ixc")))
    )
    zero = Decimal("0.00")

    registros = []
    for escola in escolas:
        dado_planilha = planilha.get(escola.inep) or {}
        registros.append({
            "inep": escola.inep,
            "nome": escola.nome,
            "estado": escola.estado or dado_planilha.get("uf", ""),
            "municipio": escola.municipio or dado_planilha.get("cidade", ""),
            "status": escola.status_mip or "",
            "valor": (_valor_inep_mip(escola, catalogo_kits) or zero) if escola.status_mip else zero,
            "valor_planilha": dado_planilha.get("valor"),
        })
    cadastrados = {registro["inep"] for registro in registros}
    for inep, dado in planilha.items():
        if inep not in cadastrados:
            registros.append({
                "inep": inep, "nome": "(INEP não cadastrado)", "estado": dado["uf"], "municipio": dado["cidade"],
                "status": "", "valor": zero, "valor_planilha": dado["valor"],
            })

    def soma(itens, chave="valor"):
        return sum((registro[chave] for registro in itens if registro[chave] is not None), zero)

    def no_estado(registro):
        return not estado or registro["estado"] == estado

    def no_recorte(registro):
        return no_estado(registro) and (
            not municipio or _normalizar_texto_cidade(registro["municipio"]) == _normalizar_texto_cidade(municipio)
        )

    metas = [
        {"estado": uf, "municipio": cidade, "valor": valor}
        for uf, cidade, valor in _meta_servico_por_escola(catalogo_kits).values()
    ]
    recorte = [registro for registro in registros if no_recorte(registro)]
    concluido = [registro for registro in recorte if registro["status"] == Escola.FATURAMENTO_CONCLUIDO]
    total_projeto = soma([meta for meta in metas if no_recorte(meta)])
    total_planilha = soma(recorte, "valor_planilha")
    total_concluido = soma(concluido)
    percentual_css = _percentual_css(total_concluido, total_projeto)

    cards = []
    for status, rotulo in Escola.STATUS_MIP_CHOICES:
        do_status = [registro for registro in recorte if registro["status"] == status]
        cards.append({
            "status": status,
            "rotulo": rotulo,
            "valor": soma(do_status),
            "valor_planilha": soma(do_status, "valor_planilha"),
            "quantidade_ineps": len(do_status),
            "na_planilha": sum(1 for registro in do_status if registro["valor_planilha"] is not None),
        })
    fora_do_mip = [registro for registro in recorte if not registro["status"] and registro["valor_planilha"] is not None]

    por_estado = []
    if status_selecionado:
        agrupado = {}
        for registro in recorte:
            if registro["status"] == status_selecionado:
                agrupado.setdefault(registro["estado"] or "(sem UF)", []).append(registro)
        total_por_uf = {uf: soma(itens) for uf, itens in agrupado.items()}
        maior = max(total_por_uf.values(), default=zero)
        for uf, itens in sorted(agrupado.items(), key=lambda par: -total_por_uf[par[0]]):
            por_estado.append({
                "estado": uf,
                "valor": total_por_uf[uf],
                "valor_planilha": soma(itens, "valor_planilha"),
                "quantidade_ineps": len(itens),
                "percentual_css": _percentual_css(total_por_uf[uf], maior),
                "ineps": sorted(itens, key=lambda registro: registro["inep"]) if uf == uf_selecionada else [],
            })

    def linhas_grafico(chave, itens, metas_do_grafico):
        """Processo Concluído (sistema) x Valor Total do Projeto, por Estado
        ou Município (barra = % da meta, ordem do maior % para o menor —
        mesma regra da aba Faturamento), com a conferência da planilha."""
        agrupado, meta_por_rotulo = {}, {}
        for registro in itens:
            agrupado.setdefault(registro[chave] or "(vazio)", []).append(registro)
        for meta in metas_do_grafico:
            rotulo = meta[chave] or "(vazio)"
            meta_por_rotulo[rotulo] = meta_por_rotulo.get(rotulo, zero) + meta["valor"]
            agrupado.setdefault(rotulo, [])
        linhas = []
        for rotulo, grupo in agrupado.items():
            valor_planilha = soma(grupo, "valor_planilha")
            valor_concluido = soma([r for r in grupo if r["status"] == Escola.FATURAMENTO_CONCLUIDO])
            valor_meta = meta_por_rotulo.get(rotulo, zero)
            if valor_planilha or valor_concluido or valor_meta:
                linhas.append({
                    "rotulo": rotulo, "valor": valor_concluido, "meta": valor_meta,
                    "valor_planilha": valor_planilha, "diferenca_planilha": valor_concluido - valor_planilha,
                    "percentual": valor_concluido / valor_meta * 100 if valor_meta else Decimal("0"),
                    "percentual_css": _percentual_css(valor_concluido, valor_meta),
                })
        return sorted(linhas, key=lambda linha: (-linha["percentual"], -linha["valor"]))

    return {
        "conferencia_planilha": conferencia_planilha,
        "planilha_encontrada": bool(planilha),
        "arquivo_planilha": CAMINHO_BASE_CONSOLIDADA_MIP.name,
        "total_projeto": total_projeto,
        "escolas_projeto": sum(1 for meta in metas if no_recorte(meta)),
        "falta_projeto": max(total_projeto - total_concluido, zero),
        "excedente_projeto": max(total_concluido - total_projeto, zero),
        "total_planilha": total_planilha,
        "ineps_planilha": sum(1 for registro in recorte if registro["valor_planilha"] is not None),
        "total_concluido": total_concluido,
        "ineps_concluido": len(concluido),
        "diferenca": total_concluido - total_planilha,
        "diferenca_abs": abs(total_concluido - total_planilha),
        "percentual_pct": total_concluido / total_projeto * 100 if total_projeto else Decimal("0"),
        "percentual_css": percentual_css,
        "percentual_faltante_css": str(Decimal("100") - Decimal(percentual_css)),
        "cards": cards,
        "fora_do_mip": len(fora_do_mip),
        "valor_fora_do_mip": soma(fora_do_mip, "valor_planilha"),
        "por_estado": por_estado,
        "grafico_estado": linhas_grafico("estado", registros, metas),
        "grafico_municipio": (
            linhas_grafico("municipio", [r for r in registros if no_estado(r)], [m for m in metas if no_estado(m)])
            if estado else []
        ),
    }
