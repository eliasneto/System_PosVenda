"""FEAT-008 (RF-16/17/18): monta a planilha de faturamento (RN-013) e o
corpo do e-mail enviados ao financeiro a partir dos itens do lado IXC +
observações do usuário — mantém a view enxuta (CLAUDE.md §11). FEAT-009
(RF-08/09/19): polling da resposta do financeiro na mesma caixa."""

import copy
import csv
import io
import logging
import re
from collections import OrderedDict
from datetime import timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal
from email import message_from_bytes, policy
from email.header import decode_header
from urllib.parse import quote

import openpyxl
import requests
from django.conf import settings
from django.core.files.base import ContentFile
from django.db.models import Count, DecimalField, F, Prefetch, Sum
from django.utils import timezone

from apps.auditoria.models import Auditoria
from apps.auditoria.services import registrar as auditar
from apps.core.email_tracking import extrair_primeiro_inep_rastreio
from apps.escolas.models import Escola

from .models import (
    Documento,
    EmailFinanceiroLog,
    EmailFinanceiroSync,
    KitPadrao,
    PlanilhaEace,
    Ri,
    RiDivergencia,
    RiHistorico,
    RiItemIxc,
    RiItemRelatorioEace,
    _derivar_numero_access_points,
)

logger = logging.getLogger(__name__)


def _linhas_itens_ixc(ri):
    """RN-013: mesma origem de preço da planilha de faturamento — o
    catálogo `KitPadrao` (via `_resolver_catalogo_ixc`), nunca
    `RiItemIxc.valor_unitario` (nasce 0,00, RN-011). Sem isso o corpo do
    e-mail mostrava todo item e o total zerados."""
    escola = ri.escola
    linhas = [["Descrição", "Quantidade", "Valor unitário", "Subtotal"]]
    total = Decimal("0")
    for item in ri.itens_ixc.all():
        catalogo = _resolver_catalogo_ixc(item.descricao_item, item.eh_kit, escola.lote)
        valor_unitario = catalogo.valor_total if catalogo else Decimal("0")
        subtotal = item.quantidade * valor_unitario
        total += subtotal
        linhas.append(
            [
                item.descricao_item,
                str(item.quantidade),
                f"R$ {valor_unitario:.2f}",
                f"R$ {subtotal:.2f}",
            ]
        )
    return linhas, total


def montar_corpo_email_financeiro(ri):
    """Texto simples (mesmos dados do PDF, RF-17) para o corpo do e-mail."""
    escola = ri.escola
    linhas, total = _linhas_itens_ixc(ri)
    partes = [
        f"Escola: {escola.nome}",
        f"INEP: {escola.inep}",
        f"Endereço: {escola.endereco or 'Não informado'}"
        + (f" — {escola.municipio}/{escola.estado}" if escola.municipio else ""),
        "",
        "Itens (lado IXC):",
    ]
    for descricao, quantidade, valor_unitario, subtotal in linhas[1:]:
        partes.append(f"- {descricao} — {quantidade} un. — {valor_unitario} — {subtotal}")
    partes.append(f"\nValor total: R$ {total:.2f}")
    if ri.observacoes_envio_financeiro:
        partes.append(f"\nObservações: {ri.observacoes_envio_financeiro}")
    return "\n".join(partes)


# ==========================================
# FEAT-017/RN-013 (2026-08-26): planilha de faturamento anexada ao e-mail
# do financeiro, no lugar do PDF — cópia preenchida da planilha-modelo
# mantida pelo financeiro (`doc/FATURAMENTO MATERIAS EACE.xlsx`), com uma
# aba por produto distinto lançado no Lado IXC (KIT incluso). O conteúdo
# da coluna F é copiado direto para a Nota Fiscal: só os 4 trechos citados
# na RN-013 são trocados, todo o resto do texto/estrutura da planilha-
# modelo é preservado byte a byte.
#
# Ajuste (2026-08-26, pedido do usuário): a 1ª versão bloqueava o envio
# quando o produto não tinha `KitPadrao.aba_planilha_financeiro` cadastrado
# à mão. Usuário reportou que isso trava todo produto novo, já que não dá
# pra saber de antemão qual produto vai ser lançado — passa a CRIAR a aba
# automaticamente (clonando o layout de uma aba já existente na planilha-
# modelo) quando não há correspondência. `aba_planilha_financeiro`
# continua existindo, agora como atalho opcional para juntar produtos
# parecidos numa aba só (ex.: Rack 3U/5U/7U → aba "RACK"); sem preenchê-lo,
# cada produto ganha a própria aba, nomeada com a descrição dele.

CAMINHO_PLANILHA_FATURAMENTO_MODELO = settings.BASE_DIR / "doc" / "FATURAMENTO MATERIAS EACE.xlsx"

# RN-013: todo KIT (Unidade Escola/Escola-Mês) usa esta aba fixa — o nome
# real na planilha-modelo tem um espaço sobrando no final ("NF KIT "),
# por isso a busca (`_encontrar_aba`) ignora espaços nas pontas.
ABA_KIT_PLANILHA_FATURAMENTO = "NF KIT"

# Excel proíbe estes caracteres em nome de aba e limita a 31 caracteres.
_CARACTERES_INVALIDOS_ABA = re.compile(r"[\[\]:\*\?/\\]")

_RE_OBS_INEP = re.compile(r"(INEP:\s*)\S+")
_RE_OBS_ITEM_LPU = re.compile(r"(ITEM LPU:\s*).*?(?=\s+MUNICIPIO/UF:)", re.DOTALL)
_RE_OBS_MUNICIPIO_UF = re.compile(r"(MUNICIPIO/UF:\s*).*?(?=\s+VENCIMENTO:)", re.DOTALL)
_RE_OBS_VENCIMENTO = re.compile(r"(VENCIMENTO:\s*)\S+")


class PlanilhaFaturamentoError(Exception):
    """RN-013/RN-014: bloqueia a geração da planilha (envio de e-mail ou
    download) — falta KIT, Data de Ativação, Município ou Estado do Lado
    IXC, ou a planilha-modelo não tem nenhuma aba para basear a criação
    automática de uma aba nova."""


def _juntar_com_e(itens):
    """"a, b e c" — junção em português para a mensagem de campos
    faltando (RN-013/RN-014)."""
    itens = list(itens)
    if len(itens) <= 1:
        return itens[0] if itens else ""
    return ", ".join(itens[:-1]) + " e " + itens[-1]


def _nome_aba_valido(nome):
    """Nome de aba do Excel: no máximo 31 caracteres, sem `[ ] : * ? / \\`."""
    limpo = _CARACTERES_INVALIDOS_ABA.sub("", nome or "").strip()
    return limpo[:31] or "Produto"


def _substituir_observacoes_nf(texto_modelo, *, inep, item_lpu, municipio, uf, data_str):
    """RN-013: troca só INEP/ITEM LPU/MUNICIPIO-UF/VENCIMENTO no texto já
    existente na célula F10 daquela aba — preserva literalmente o resto
    (nº de contrato, texto legal, espaçamento) já cadastrado na planilha-
    modelo; texto copiado para a Nota Fiscal, não pode mudar de estrutura."""
    texto = _RE_OBS_INEP.sub(lambda m: m.group(1) + inep, texto_modelo, count=1)
    texto = _RE_OBS_ITEM_LPU.sub(lambda m: m.group(1) + item_lpu, texto, count=1)
    texto = _RE_OBS_MUNICIPIO_UF.sub(lambda m: m.group(1) + f"{municipio}/{uf}", texto, count=1)
    texto = _RE_OBS_VENCIMENTO.sub(lambda m: m.group(1) + data_str, texto, count=1)
    return texto


def _encontrar_aba(workbook, nome):
    alvo = (nome or "").strip().casefold()
    for aba in workbook.worksheets:
        if aba.title.strip().casefold() == alvo:
            return aba
    return None


def _obter_ou_criar_aba(workbook, nome, aba_modelo):
    """RN-013 (ajuste 2026-08-26): usa a aba já existente com esse nome
    (ex.: "NF KIT", ou uma aba de produto já cadastrada antes) ou cria uma
    nova clonando o layout/formatação de `aba_modelo` — nenhum produto
    fica bloqueado por falta de cadastro prévio.

    Correção (2026-08-26): `Workbook.copy_worksheet` (openpyxl) copia
    célula, formatação e mesclagem, mas NÃO copia imagem — limitação
    conhecida da biblioteca. Sem isso, a logo do financeiro (a mesma
    imagem já presente em toda aba da planilha-modelo) sumia de toda aba
    criada automaticamente, ficando só na primeira aba (a que já existia
    no modelo, nunca clonada). Copiada manualmente aqui."""
    aba = _encontrar_aba(workbook, nome)
    if aba is not None:
        return aba
    nova = workbook.copy_worksheet(aba_modelo)
    nova.title = _nome_aba_valido(nome)
    for imagem in aba_modelo._images:
        nova.add_image(copy.deepcopy(imagem))
    return nova


def _resolver_catalogo_ixc(descricao, eh_kit, lote):
    """RN-013/RN-010: preço vem sempre do catálogo `KitPadrao`, nunca do
    `RiItemIxc.valor_unitario` gravado no item (nasce 0,00, RN-011). KIT
    cruza pelo número de Access Points (mesmo critério de
    `resolver_kit_declarado`/RN-010 ampliada) — `descricao_item` guarda a
    forma curta ("Kit Cobertura Wi-Fi - N Access Points"), que não bate
    com `KitPadrao.descricao` (forma completa), só com o número."""
    if eh_kit:
        numero = _derivar_numero_access_points(descricao)
        if numero is None:
            return None
        return KitPadrao.resolver_kit_declarado(str(numero), lote=lote)
    qs = KitPadrao.objects.filter(descricao_curta=descricao)
    if lote is not None:
        qs = qs.filter(lote=lote)
    return qs.first()


def _item_lpu_e_aba(descricao, eh_kit, catalogo):
    """RN-013: texto do ITEM LPU e nome da aba a usar. KIT sempre usa a
    aba fixa e o texto "KIT N" (N = número de Access Points, extraído da
    própria descrição). Produto avulso usa `KitPadrao.aba_planilha_
    financeiro` quando cadastrado (permite juntar vários produtos numa
    aba só); sem cadastro, usa a própria descrição do produto — a aba é
    criada automaticamente com esse nome (`_obter_ou_criar_aba`)."""
    if eh_kit:
        numero = _derivar_numero_access_points(descricao)
        texto = f"KIT {numero}" if numero else descricao
        return texto, ABA_KIT_PLANILHA_FATURAMENTO
    nome = (catalogo.aba_planilha_financeiro if catalogo else "") or descricao
    return nome, nome


def gerar_planilha_faturamento(ri, data_vencimento):
    """RN-013: cópia preenchida da planilha-modelo do financeiro
    (`doc/FATURAMENTO MATERIAS EACE.xlsx`), uma aba por produto distinto
    lançado no Lado IXC daquele RI (KIT incluso, RN-011); demais abas do
    modelo (produtos não lançados neste RI) não entram na cópia final.
    Produto sem aba já cadastrada ganha uma aba nova, criada na hora
    clonando o layout de uma aba existente (ajuste 2026-08-26) — nada
    fica bloqueado por falta de cadastro prévio no catálogo.

    RN-013/RN-014 (2026-08-26): KIT, Data de Ativação, Município e Estado
    do Lado IXC são exigidos só AQUI — na hora de gerar a planilha (envio
    de e-mail ou download), não a cada "Salvar" do Lado IXC (RN-011). Isso
    evita travar o lançamento de um Produto novo, ou uma correção de Data
    de Ativação, por causa de um campo sem relação com aquela ação — o
    usuário só precisa ter os quatro preenchidos até o momento de enviar/
    baixar. Levanta `PlanilhaFaturamentoError` — sem gerar nada — listando
    tudo que falta de uma vez.

    Agrupado pela ABA de destino, não pela descrição exata do item: vários
    produtos do catálogo (ex.: "Rack 3U", "Rack 5U") podem apontar para a
    mesma aba (ex.: "RACK", via `KitPadrao.aba_planilha_financeiro`) — o
    valor da aba soma o subtotal (quantidade × valor do catálogo) de cada
    um deles, não só a quantidade de um produto só."""
    itens = list(ri.itens_ixc.all())
    faltando = []
    if not itens:
        faltando.append("nenhum item lançado (KIT ou produto)")
    elif not any(item.eh_kit for item in itens):
        faltando.append("o KIT Instalado")
    if not ri.data_ativacao:
        faltando.append("a Data de Ativação")
    if not (ri.municipio_ixc or "").strip():
        faltando.append("o Município (Lado IXC)")
    if not (ri.estado_ixc or "").strip():
        faltando.append("o Estado (Lado IXC)")
    if faltando:
        raise PlanilhaFaturamentoError(
            "Antes de enviar o e-mail ou baixar a planilha, preencha no "
            f"Lado IXC: {_juntar_com_e(faltando)}."
        )

    escola = ri.escola
    data_str = data_vencimento.strftime("%d/%m/%Y")

    grupos = OrderedDict()  # aba_nome -> {"item_lpu": str, "subtotal": Decimal}
    for item in sorted(itens, key=lambda item: item.criado_em):
        catalogo = _resolver_catalogo_ixc(item.descricao_item, item.eh_kit, escola.lote)
        item_lpu, aba_nome = _item_lpu_e_aba(item.descricao_item, item.eh_kit, catalogo)
        valor_unitario = catalogo.valor_total if catalogo else Decimal("0")
        grupo = grupos.setdefault(aba_nome, {"item_lpu": item_lpu, "subtotal": Decimal("0")})
        grupo["subtotal"] += valor_unitario * item.quantidade
        # Último item lançado prevalece no texto do ITEM LPU — um RI só
        # tem mais de uma variação na mesma aba num cenário raro (ex.:
        # correção trocando o tamanho do KIT); a soma do valor continua
        # correta mesmo assim.
        grupo["item_lpu"] = item_lpu

    workbook = openpyxl.load_workbook(CAMINHO_PLANILHA_FATURAMENTO_MODELO)
    if not workbook.worksheets:
        raise PlanilhaFaturamentoError(
            "A planilha-modelo (doc/FATURAMENTO MATERIAS EACE.xlsx) não tem "
            "nenhuma aba para basear a criação automática de uma aba nova."
        )
    aba_modelo = workbook.worksheets[0]

    abas_usadas = set()
    for aba_nome, dados in grupos.items():
        aba = _obter_ou_criar_aba(workbook, aba_nome, aba_modelo)

        aba["E10"] = data_vencimento
        aba["F10"] = _substituir_observacoes_nf(
            aba["F10"].value or "",
            inep=escola.inep,
            item_lpu=dados["item_lpu"],
            municipio=ri.municipio_ixc,
            uf=ri.estado_ixc,
            data_str=data_str,
        )
        aba["H10"] = float(dados["subtotal"])
        aba["C16"] = escola.nome
        aba["F16"] = escola.endereco
        aba["G16"] = ri.municipio_ixc
        aba["H16"] = ri.estado_ixc
        aba["I16"] = dados["item_lpu"]
        abas_usadas.add(aba.title)

    for aba in list(workbook.worksheets):
        if aba.title not in abas_usadas:
            workbook.remove(aba)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def trocar_status_com_log(ri, novo_status, usuario):
    """FEAT-006/RN-008: troca o status do RI e grava o log automático na
    linha do tempo (FEAT-014) — reaproveitado pela troca manual (drill-
    down, view), pela automática de envio (RF-18) e pela automática de
    recebimento (RF-19, `sincronizar_respostas_financeiro` abaixo).
    `usuario=None` é válido (RiHistorico.autor aceita nulo) — a leitura da
    caixa de e-mail é uma rotina automática, sem usuário logado.

    FEAT-010/RF-11: ao concluir manualmente, grava `concluido_em` — mesmo
    carimbo já gravado na conclusão automática (RN-024,
    `_concluir_ri_por_status_escola_conectada` abaixo), para o campo
    refletir a conclusão real independente de como ela aconteceu."""
    status_anterior = ri.get_status_display()
    ri.status = novo_status
    campos_alterados = ["status", "atualizado_em"]
    if novo_status == Ri.FATURAMENTO_CONCLUIDO:
        ri.concluido_em = timezone.now()
        campos_alterados.append("concluido_em")
    ri.save(update_fields=campos_alterados)
    RiHistorico.objects.create(
        ri=ri,
        tipo=RiHistorico.LOG_STATUS,
        autor=usuario,
        campo="Status do RI",
        valor_anterior=status_anterior,
        valor_novo=ri.get_status_display(),
    )
    auditar(
        usuario,
        Auditoria.TRANSICAO_STATUS,
        entidade="Ri",
        entidade_id=ri.pk,
        campo="Status do RI",
        valor_anterior=status_anterior,
        valor_novo=ri.get_status_display(),
    )


def _cesta_itens(itens):
    """RN-003 (2026-08-26): soma a Quantidade por Descrição — usado para
    comparar o conjunto de "Produtos" entre o Lado IXC e o Lado Relatório
    EACE (mesmo produto lançado em mais de uma linha conta como uma soma
    só, não uma linha a mais para casar)."""
    cesta = {}
    for item in itens:
        cesta[item.descricao_item] = cesta.get(item.descricao_item, 0) + item.quantidade
    return cesta


def comparar_kit_e_produtos_ixc_relatorio(ri):
    """RN-003 (2026-08-26): confronto formal entre o Lado IXC (2º lado) e
    o Lado Relatório EACE (3º lado) — Descrição (qual KIT/Produto do
    catálogo `KitPadrao` foi escolhido, RN-011/RN-018) e Quantidade, sem
    Valor Unitário (o Lado IXC nasce sempre 0,00, RN-011 — comparar valor
    acusaria divergência em todo item, sem relação com o faturamento
    real).

    Consulta os itens direto no banco (não usa `ri.itens_ixc.all()`/
    `ri.itens_relatorio_eace.all()`) para nunca ler um cache de
    `prefetch_related` desatualizado logo depois de criar/editar/excluir
    um item na mesma requisição.

    Retorna um dicionário usado tanto para persistir a divergência formal
    (`sincronizar_divergencia_kit_relatorio`, abaixo) quanto para destacar
    em vermelho os itens do Lado IXC na tela (`ri_detail_view`)."""
    itens_ixc = list(RiItemIxc.objects.filter(ri=ri))
    itens_eace = list(RiItemRelatorioEace.objects.filter(ri=ri))

    kit_ixc = next((item for item in itens_ixc if item.eh_kit), None)
    kit_eace = next((item for item in itens_eace if item.eh_kit), None)
    kit_diverge = (kit_ixc is None) != (kit_eace is None) or bool(
        kit_ixc and kit_eace and kit_ixc.descricao_item != kit_eace.descricao_item
    )

    produtos_ixc = _cesta_itens(item for item in itens_ixc if not item.eh_kit)
    produtos_eace = _cesta_itens(item for item in itens_eace if not item.eh_kit)
    produtos_divergentes = {
        descricao: (produtos_ixc.get(descricao, 0), produtos_eace.get(descricao, 0))
        for descricao in set(produtos_ixc) | set(produtos_eace)
        if produtos_ixc.get(descricao, 0) != produtos_eace.get(descricao, 0)
    }

    itens_ixc_divergentes_pks = {
        item.pk
        for item in itens_ixc
        if (item.eh_kit and kit_diverge) or (not item.eh_kit and item.descricao_item in produtos_divergentes)
    }

    return {
        "diverge": kit_diverge or bool(produtos_divergentes),
        "kit_diverge": kit_diverge,
        "kit_ixc_descricao": kit_ixc.descricao_item if kit_ixc else None,
        "kit_eace_descricao": kit_eace.descricao_item if kit_eace else None,
        "produtos_divergentes": produtos_divergentes,
        "itens_ixc_divergentes_pks": itens_ixc_divergentes_pks,
    }


def comparar_status_escola_relatorio(ri):
    """RN-046 (2026-08-28): compara o "Status escola" (coluna T da
    Planilha EACE, RN-024) gravado por item no Lado Relatório EACE. Não é
    um confronto entre lados diferentes (como a RN-002/RN-003 acima) — é
    entre os próprios itens do Lado 3 do mesmo RI, por isso não existe um
    lado de referência "correto": havendo qualquer divergência, todos os
    itens ficam marcados (decisão do usuário, sem meio-termo de maioria).

    Item sem valor (lançado manualmente, fora do Sincronizador) não entra
    na comparação. Só computado na renderização (mesmo padrão de
    `divergencia_kit`/`divergencia_municipio_ixc` em `views.py`) — é só um
    alerta visual, não bloqueia nenhuma transição de status, então não
    precisa de uma tabela `RiDivergencia` própria."""
    valores = sorted(
        {item.status_escola for item in ri.itens_relatorio_eace.all() if item.status_escola}
    )
    return {"diverge": len(valores) > 1, "valores": valores}


def _descricao_divergencia_kit_relatorio(resultado):
    """Texto gravado em `RiDivergencia.descricao` (RN-003) — lista o que
    diverge, para quem for resolver (Lado IXC) entender o motivo sem abrir
    os dois painéis lado a lado."""
    partes = []
    if resultado["kit_diverge"]:
        partes.append(
            "KIT Instalado — Lado IXC: {} / Relatório EACE: {}.".format(
                resultado["kit_ixc_descricao"] or "nenhum lançado",
                resultado["kit_eace_descricao"] or "nenhum lançado",
            )
        )
    for descricao, (quantidade_ixc, quantidade_eace) in sorted(resultado["produtos_divergentes"].items()):
        partes.append(
            f"{descricao} — Lado IXC: {quantidade_ixc} un. / Relatório EACE: {quantidade_eace} un."
        )
    return " ".join(partes)


def sincronizar_divergencia_kit_relatorio(ri):
    """RN-003 (2026-08-26): recalcula o confronto formal (Lado IXC × Lado
    Relatório EACE) e mantém 1 único registro de `RiDivergencia`
    (`tipo=kit_relatorio`) sincronizado com o resultado — chamado depois
    de qualquer lançamento, edição ou exclusão de item nesses dois lados
    (`ri_detail_view` — ações `salvar_ixc`/`salvar_relatorio_eace` —,
    `ri_item_ixc_update_view`, `ri_item_ixc_delete_view`,
    `ri_item_relatorio_eace_update_view`,
    `ri_item_relatorio_eace_delete_view`). Não acumula 1 registro por item
    divergente — só há 1 divergência aberta por RI para este confronto,
    coerente com o bloqueio já implementado em `_validar_transicao_status_ri`
    (`ri.divergencias...exists()`, `apps/ri/views.py`).

    Retorna o resultado do confronto (`comparar_kit_e_produtos_ixc_relatorio`)
    para quem chamou reaproveitar, sem precisar recalcular de novo."""
    resultado = comparar_kit_e_produtos_ixc_relatorio(ri)
    aberta = ri.divergencias.filter(
        tipo=RiDivergencia.TIPO_KIT_RELATORIO, resolvida_em__isnull=True
    ).first()

    if not resultado["diverge"]:
        if aberta:
            aberta.resolvida_em = timezone.now()
            aberta.save(update_fields=["resolvida_em"])
        return resultado

    descricao = _descricao_divergencia_kit_relatorio(resultado)
    if aberta:
        if aberta.descricao != descricao:
            aberta.descricao = descricao
            aberta.save(update_fields=["descricao"])
    else:
        RiDivergencia.objects.create(
            ri=ri, tipo=RiDivergencia.TIPO_KIT_RELATORIO, bloqueia=True, descricao=descricao,
        )
    return resultado


# ==========================================
# FEAT-024 (RN-022): Sincronizador do Lado Relatório EACE — reprocessa o
# arquivo ativo da Planilha EACE (RN-021) sob demanda, filtra pelo INEP do
# RI e lança os itens casados com o catálogo `KitPadrao` como
# `RiItemRelatorioEace`, igual a um lançamento manual (RN-018).
# ==========================================


class PlanilhaEaceSincronizacaoError(Exception):
    """RN-022: bloqueia o Sincronizador — sem Planilha EACE ativa, ou sem
    nenhuma linha para o INEP do RI. Não é um erro de sistema, só falta de
    dado — mesma família de `PlanilhaFaturamentoError`."""


def _agrupar_linhas_planilha_eace_por_inep(planilha):
    """RN-022/RN-023: lê o arquivo ativo da Planilha EACE (RN-021) uma
    única vez e agrupa as linhas por "Projeto" (INEP) — mesma normalização
    (8 dígitos, zero à esquerda) já usada na importação de Escola
    (RN-007). Reaproveitado pelo Sincronizador em lote (FEAT-025), que
    processa muitos INEPs de uma vez e não pode reabrir/reler o arquivo a
    cada RI."""
    with planilha.arquivo.open("rb") as arquivo:
        texto = arquivo.read().decode("utf-8-sig")
    leitor = csv.DictReader(io.StringIO(texto), delimiter=";")
    agrupado = {}
    for linha in leitor:
        projeto_bruto = (linha.get("Projeto") or "").strip()
        try:
            projeto = str(int(projeto_bruto)).zfill(8)
        except ValueError:
            continue
        agrupado.setdefault(projeto, []).append(linha)
    return agrupado


def _linhas_planilha_eace_para_inep(planilha, inep):
    """RN-022: linhas da Planilha EACE ativa (RN-021) para 1 INEP."""
    return _agrupar_linhas_planilha_eace_por_inep(planilha).get(inep, [])


def _casar_planilha_com_catalogo(descricao_planilha, lote):
    """RN-022: casa a "Descrição do Item" da Planilha EACE com o catálogo
    `KitPadrao`. A Descrição real da planilha traz sufixos que o texto
    limpo do catálogo não tem (ex.: "Kit Cobertura Wi-Fi - 12 Access
    Points - Equip - MEGA - CO"), então a comparação exata de texto não
    serve nos dois casos:

    - KIT: mesmo critério de `numero_access_points` já usado no Kit
      Declarado (RN-010 ampliada/FEAT-016) — extrai o número de Access
      Points da descrição e cruza com o catálogo (Unidade "Escola"/
      "Escola-Mês"), restrito ao Lote quando informado.
    - Produto avulso: a Descrição curta do catálogo precisa ser um
      prefixo (sem diferenciar maiúsculas/minúsculas) da Descrição da
      planilha — cobre o mesmo padrão de sufixo (fornecedor/UF) visto nos
      KITs.

    Sem correspondência, devolve `(None, None)` — nenhum valor inventado
    (CLAUDE.md §9). Retorna `(instancia_catalogo, eh_kit)`."""
    numero = _derivar_numero_access_points(descricao_planilha)
    if numero is not None:
        candidato = KitPadrao.resolver_kit_declarado(str(numero), lote=lote)
        return (candidato, True) if candidato else (None, None)

    descricao_normalizada = (descricao_planilha or "").strip().casefold()
    if not descricao_normalizada:
        return None, None
    qs = KitPadrao.objects.exclude(unidade__istartswith="escola")
    if lote is not None:
        qs = qs.filter(lote=lote)
    for candidato in qs:
        referencia = (candidato.descricao_curta or candidato.descricao).strip().casefold()
        if referencia and descricao_normalizada.startswith(referencia):
            return candidato, False
    return None, None


def _quantidade_planilha_eace(valor_bruto):
    """"Qtde Produto" da planilha pode vir com separador decimal
    brasileiro (vírgula) — devolve `None` (em vez de inventar 1) quando o
    valor não é um número válido."""
    texto = (valor_bruto or "").strip().replace(".", "").replace(",", ".")
    try:
        quantidade = int(Decimal(texto))
    except Exception:
        return None
    return quantidade if quantidade > 0 else None


# RN-024: valor exato da coluna "Status escola" (coluna T da Planilha
# EACE) que dispara a conclusão automática do RI — comparação com
# `.strip()`, sem case-fold (a planilha sempre traz esta grafia).
STATUS_ESCOLA_CONECTADA = "Conectada"


def _concluir_ri_por_status_escola_conectada(ri, linhas):
    """RN-024: quando alguma linha do INEP trouxer "Status escola" (coluna
    T) exatamente "Conectada", conclui o RI — a partir de qualquer status
    atual (RN-001), inclusive encerrando uma "Correção MEGA" em aberto sem
    exigir o retorno manual para "Andamento" (decisão explícita do
    usuário, ver `business_rules.md`). Grava `concluido_em` como numa
    conclusão manual e registra o log na linha do tempo (RN-008) com o
    mesmo padrão de `trocar_status_com_log`, só ajustando o rótulo do
    campo para indicar que a origem foi o Sincronizador.

    RI já em "Faturamento Concluído" não é afetado — os dois botões já não
    chegam a chamar esta função nesse caso (RN-020: lote pula antes,
    template individual esconde o próprio botão), checagem aqui é só
    defensiva. Devolve `True` quando a conclusão foi aplicada."""
    if ri.status == Ri.FATURAMENTO_CONCLUIDO:
        return False
    if not any(
        (linha.get("Status escola") or "").strip() == STATUS_ESCOLA_CONECTADA for linha in linhas
    ):
        return False

    status_anterior = ri.get_status_display()
    ri.status = Ri.FATURAMENTO_CONCLUIDO
    ri.concluido_em = timezone.now()
    ri.save(update_fields=["status", "concluido_em", "atualizado_em"])
    RiHistorico.objects.create(
        ri=ri,
        tipo=RiHistorico.LOG_STATUS,
        autor=None,
        campo="Status do RI (Sincronizador)",
        valor_anterior=status_anterior,
        valor_novo=ri.get_status_display(),
    )
    auditar(
        None,
        Auditoria.TRANSICAO_STATUS,
        entidade="Ri",
        entidade_id=ri.pk,
        campo="Status do RI (Sincronizador)",
        valor_anterior=status_anterior,
        valor_novo=ri.get_status_display(),
    )
    return True


def _valores_fechados_da_linha(linha):
    """RN-022 (ampliada)/RN-046: os 4 campos fechados do Lado Relatório
    EACE — só o Sincronizador preenche, nunca o formulário manual — lidos
    direto da linha da planilha que originou o item. Centraliza a leitura
    usada tanto na criação do item quanto na atualização de um já
    lançado (`_atualizar_campos_fechados_item_existente`, abaixo)."""
    return {
        "num_osp": (linha.get("Num OSP") or "").strip(),
        "validacao_osp": (linha.get("Validação OSP") or "").strip(),
        "nota_fiscal": (linha.get("Nota Fiscal") or "").strip(),
        "status_escola": (linha.get("Status escola") or "").strip(),
    }


def _atualizar_campos_fechados_item_existente(item_existente, linha):
    """RN-022 (ampliada)/RN-046 (correção, 2026-08-28): item já lançado
    (KIT ou Produto) nunca ganha outro registro ao sincronizar de novo
    (mesma Descrição + Quantidade) — antes deste ajuste, os 4 campos
    fechados (Num OSP, Validação OSP, Nota Fiscal, "Status Equip") só
    eram gravados na criação; um item sincronizado antes de a EACE emitir
    a Nota Fiscal (ou antes de "Status Equip" existir) ficava para sempre
    sem o valor, mesmo depois de subir uma planilha nova com o dado
    presente. Usuário confirmou (2026-08-28) que quer os 4 sempre
    atualizados a cada nova planilha, não só na criação.

    Só atualiza o campo cujo valor novo veio preenchido e é diferente do
    já gravado — planilha com a coluna vazia nunca apaga um valor já
    salvo (mesmo critério conservador da RN-046 original: falta de dado
    não é tratada como "backfill negativo"). `item_existente=None` é
    válido — cobre o caso do KIT ignorado por RN-015 quando é um KIT
    diferente do já lançado (nenhum item para atualizar)."""
    if item_existente is None:
        return
    campos_alterados = []
    for campo, valor_novo in _valores_fechados_da_linha(linha).items():
        if valor_novo and getattr(item_existente, campo) != valor_novo:
            setattr(item_existente, campo, valor_novo)
            campos_alterados.append(campo)
    if campos_alterados:
        item_existente.save(update_fields=campos_alterados)


def sincronizar_relatorio_eace_da_planilha(ri, planilha=None, linhas_por_inep=None):
    """RN-022/FEAT-024: reprocessa o arquivo ativo da Planilha EACE
    (RN-021) sob demanda, filtra pelo INEP do RI e lança os itens casados
    com o catálogo como `RiItemRelatorioEace` — igual a um lançamento
    manual (RN-018): Descrição curta do catálogo, Quantidade da planilha
    (KIT sempre 1, mesmo critério da RN-018), Valor Unitário do catálogo
    — nunca o valor bruto da planilha, que é só conferência (o próprio
    usuário confirmou que já deve bater com o do catálogo).

    Item já lançado (mesma Descrição + Quantidade) não duplica ao
    sincronizar de novo — mas os 4 campos fechados (Num OSP, Validação
    OSP, Nota Fiscal, "Status Equip") são atualizados nele quando a
    planilha ativa trouxer um valor novo e diferente do já gravado
    (correção 2026-08-28, `_atualizar_campos_fechados_item_existente`):
    cobre o caso real de a EACE emitir a Nota Fiscal só depois de o item
    já ter sido sincronizado sem ela. RI que já tem um KIT lançado nesse
    lado (RN-015) não ganha outro — a linha da planilha some para a lista
    "kit_ignorado" em vez de bloquear o resto da sincronização, mas o KIT
    já lançado também recebe essa atualização. Item sem correspondência
    no catálogo, ou com Quantidade inválida, nunca é lançado — fica nas
    listas devolvidas para o usuário decidir (CLAUDE.md §9).

    RN-022 (ampliada, 2026-08-27): também grava Num OSP, Validação OSP e
    Nota Fiscal (colunas "Num OSP"/"Validação OSP"/"Nota Fiscal" da mesma
    linha) — campos fechados, só para exibição, nunca preenchidos fora do
    Sincronizador.

    RN-024 (2026-08-27): também confere a coluna "Status escola" das
    mesmas linhas — "Conectada" conclui o RI automaticamente
    (`_concluir_ri_por_status_escola_conectada`), independente do
    resultado do lançamento de itens acima (duas verificações
    independentes sobre a mesma linha da planilha).

    RN-046 (2026-08-28): a mesma coluna "Status escola" também é gravada
    por item (`RiItemRelatorioEace.status_escola`), para exibição no Lado
    3 e para o alerta de divergência entre produtos do mesmo RI
    (`comparar_status_escola_relatorio`) — não substitui a verificação da
    RN-024 acima, que continua olhando todas as linhas do INEP.

    `planilha`/`linhas_por_inep` são atalhos internos do Sincronizador em
    lote (RN-023/FEAT-025): quando informados, pulam a busca da Planilha
    ativa e a releitura do arquivo, já feitas uma única vez para todos os
    RIs do lote. Chamada normal (botão individual do RI) não informa
    nenhum dos dois — comportamento idêntico ao de antes.

    Levanta `PlanilhaEaceSincronizacaoError` só quando não há nada para
    processar (sem Planilha EACE ativa, ou sem nenhuma linha para o
    INEP) — a view converte em mensagem de erro."""
    if planilha is None:
        planilha = PlanilhaEace.ativa()
        if not planilha:
            raise PlanilhaEaceSincronizacaoError(
                "Nenhuma Planilha EACE ativa. Envie o arquivo em Administrador > "
                "Planilha EACE antes de sincronizar."
            )

    escola = ri.escola
    if linhas_por_inep is not None:
        linhas = linhas_por_inep.get(escola.inep, [])
    else:
        linhas = _linhas_planilha_eace_para_inep(planilha, escola.inep)
    if not linhas:
        raise PlanilhaEaceSincronizacaoError(
            f"Nenhum item encontrado na Planilha EACE para o INEP {escola.inep}."
        )

    # RN-046 (correção, 2026-08-28): dicionário (não mais um set) para
    # conseguir, no item já lançado (`duplicados` abaixo), reaproveitar o
    # objeto e atualizar o "Status escola" — item lançado antes desta
    # regra existir nasceu com o campo em branco e uma nova sincronização
    # não criava outro item (mesma Descrição + Quantidade), então nunca
    # preenchia o valor. Num OSP/Validação OSP/Nota Fiscal (RN-022
    # ampliada) continuam só na criação — não fazem parte deste ajuste.
    itens_existentes = {
        (item.descricao_item, item.quantidade): item for item in ri.itens_relatorio_eace.all()
    }
    kit_ja_lancado = ri.itens_relatorio_eace.filter(eh_kit=True).exists()

    resultado = {
        "criados": [],
        "duplicados": [],
        "sem_correspondencia": [],
        "kit_ignorado": [],
        "quantidade_invalida": [],
        "concluido_status_escola": False,
    }

    for linha in linhas:
        descricao_planilha = (linha.get("Descrição do Item") or "").strip()
        if not descricao_planilha:
            continue

        catalogo, eh_kit = _casar_planilha_com_catalogo(descricao_planilha, escola.lote)
        if not catalogo:
            resultado["sem_correspondencia"].append(descricao_planilha)
            continue

        if eh_kit:
            quantidade = 1  # RN-018: KIT sempre quantidade 1 (kit fechado da escola).
        else:
            quantidade = _quantidade_planilha_eace(linha.get("Qtde Produto"))
            if quantidade is None:
                resultado["quantidade_invalida"].append(descricao_planilha)
                continue

        descricao_item = catalogo.descricao_curta or catalogo.descricao
        if eh_kit and kit_ja_lancado:
            resultado["kit_ignorado"].append(descricao_item)
            # RN-046 (correção): o KIT já lançado é o mesmo caso de
            # "duplicados" abaixo (mesma Descrição + Quantidade), mas cai
            # neste ramo primeiro (RN-015) — sem isto, o KIT nunca recebia
            # a atualização dos campos fechados.
            _atualizar_campos_fechados_item_existente(
                itens_existentes.get((descricao_item, quantidade)), linha
            )
            continue
        if (descricao_item, quantidade) in itens_existentes:
            resultado["duplicados"].append(descricao_item)
            _atualizar_campos_fechados_item_existente(
                itens_existentes[(descricao_item, quantidade)], linha
            )
            continue

        item = RiItemRelatorioEace.objects.create(
            ri=ri,
            descricao_item=descricao_item,
            quantidade=quantidade,
            valor_unitario=catalogo.valor_total,
            eh_kit=eh_kit,
            # RN-022 (ampliada)/RN-046: campos fechados, só de exibição —
            # lidos direto da mesma linha da planilha que originou o item.
            **_valores_fechados_da_linha(linha),
        )
        itens_existentes[(descricao_item, quantidade)] = item
        resultado["criados"].append(item)
        if eh_kit:
            kit_ja_lancado = True

    if resultado["criados"]:
        sincronizar_divergencia_kit_relatorio(ri)

    # RN-024: independe do resultado do lançamento de itens acima.
    resultado["concluido_status_escola"] = _concluir_ri_por_status_escola_conectada(ri, linhas)

    return resultado


# RI "bloqueado pelo status" no resumo do lote (RN-023) — mesmo texto usado
# pela view para não duplicar a string em dois lugares.
RI_BLOQUEADO_FATURAMENTO_CONCLUIDO = "bloqueado_status"
RI_SEM_LINHA_NA_PLANILHA = "sem_linha_planilha"


def sincronizar_relatorio_eace_de_todas_as_ri():
    """RN-023/FEAT-025: aplica `sincronizar_relatorio_eace_da_planilha` ao
    RI "atual" (o mais recente) de cada Escola de uma vez só — mesmo
    critério de "RI atual" já usado no grid (FEAT-007) — sem precisar abrir
    RI por RI. Só levanta `PlanilhaEaceSincronizacaoError` quando não há
    Planilha EACE ativa (nada a processar); pendência de um RI (sem linha
    na planilha para o INEP dele, ou bloqueado pelo status "Faturamento
    Concluído", RN-020) nunca interrompe os demais — entra no resumo
    devolvido, para o Administrador decidir/agir manualmente (CLAUDE.md
    §9).

    Devolve uma lista de `(ri, resultado)`, na mesma ordem de `Escola`
    (por nome); `resultado` é o dicionário de
    `sincronizar_relatorio_eace_da_planilha` para quem foi processado, ou
    uma das constantes `RI_BLOQUEADO_FATURAMENTO_CONCLUIDO`/
    `RI_SEM_LINHA_NA_PLANILHA` para quem foi pulado."""
    planilha = PlanilhaEace.ativa()
    if not planilha:
        raise PlanilhaEaceSincronizacaoError(
            "Nenhuma Planilha EACE ativa. Envie o arquivo em Administrador > "
            "Planilha EACE antes de sincronizar."
        )
    # Arquivo lido e agrupado por INEP 1 única vez para o lote inteiro —
    # `sincronizar_relatorio_eace_da_planilha` reabrir o arquivo a cada RI
    # não escalaria com o número de Escolas do sistema.
    linhas_por_inep = _agrupar_linhas_planilha_eace_por_inep(planilha)

    # Mesmo prefetch do grid (FEAT-007): 1 consulta para todas as Escolas,
    # 1 para todos os RIs (já ordenados, o primeiro de cada Escola é o
    # atual) — evita N+1 ao processar o sistema inteiro de uma vez.
    escolas = Escola.objects.order_by("nome").prefetch_related(
        Prefetch("ris", queryset=Ri.objects.order_by("-criado_em"))
    )

    processados = []
    for escola in escolas:
        ris_da_escola = list(escola.ris.all())
        if not ris_da_escola:
            continue
        ri = ris_da_escola[0]
        if ri.status == Ri.FATURAMENTO_CONCLUIDO:
            processados.append((ri, RI_BLOQUEADO_FATURAMENTO_CONCLUIDO))
            continue
        try:
            resultado = sincronizar_relatorio_eace_da_planilha(
                ri, planilha=planilha, linhas_por_inep=linhas_por_inep
            )
        except PlanilhaEaceSincronizacaoError:
            # Só pode ser "sem linha para o INEP" — a Planilha ativa já foi
            # conferida acima, antes do laço.
            processados.append((ri, RI_SEM_LINHA_NA_PLANILHA))
            continue
        processados.append((ri, resultado))

    return processados


# ==========================================
# FEAT-009 (RF-08/RF-09/RF-19, RN-005/RN-009): leitura da resposta do
# financeiro na caixa própria do sistema, por polling (~5 min,
# architecture.md "Fluxo de e-mail com o financeiro") via Microsoft Graph
# (delta query) — IMAP com usuário/senha foi tentado e não funciona mais
# nessa caixa (Basic Auth aposentada pela Microsoft; confirmado em
# 2026-08-25 direto com o servidor real: "AUTHENTICATE failed. Provided
# authentication mechanism is not supported."). Reaproveita só o *padrão*
# de código já usado no `modulo-posVenda`
# (`apps/integracoes/email/sincronizar_respostas_email_cotacao.py`) — o
# app do Azure (Client ID/Secret/Tenant) é exclusivo deste sistema; nunca
# reaproveitar `GRAPH_EMAIL_REPLIES_*` (aquele é do modulo-posVenda; usar
# os dois juntos criaria uma dependência entre sistemas independentes,
# decisão confirmada pelo usuário em 2026-08-25). A cadência do polling em
# si (agendamento) é responsabilidade do DevOps; esta rotina só faz uma
# passada e devolve.
#
# Escopo desta primeira versão (RN-005): confere que a resposta tem
# exatamente 1 PDF + 1 XML e que o INEP é identificável pelo código de
# rastreio do assunto (RN-009) — isso já é o critério completo descrito na
# exceção da RN-005 ("sem 1 PDF + 1 XML, ou sem INEP identificável" não
# bloqueia, só alerta). Comparar o CONTEÚDO da Nota Fiscal/XML contra os
# itens do lado IXC para detectar divergência "NF × financeiro" (RN-003)
# não está implementado aqui: a RN-003 já registra em aberto o critério
# exato de casamento entre itens, e não há especificação de que campo do
# XML da NFe corresponde a qual dado do RI — decisão de negócio pendente,
# não uma lacuna técnica (CLAUDE.md §9, "nunca inventar regra ausente").
# ==========================================

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"


class EmailFinanceiroSyncError(Exception):
    """Falha ao autenticar/ler a caixa do financeiro no Microsoft Graph —
    não é o caso de "e-mail fora do padrão" (RN-005), que não é erro."""


def _graph_habilitado():
    return bool(
        settings.GRAPH_FINANCEIRO_ENABLED
        and settings.GRAPH_FINANCEIRO_CLIENT_ID
        and settings.GRAPH_FINANCEIRO_CLIENT_SECRET
        and settings.GRAPH_FINANCEIRO_TENANT_ID
    )


def _resolver_caixa():
    caixa = (settings.GRAPH_FINANCEIRO_MAILBOX or settings.DEFAULT_FROM_EMAIL or "").strip().lower()
    if not caixa:
        raise EmailFinanceiroSyncError(
            "Não foi possível determinar a caixa monitorada do financeiro "
            "(GRAPH_FINANCEIRO_MAILBOX/DEFAULT_FROM_EMAIL vazios)."
        )
    return caixa


def _obter_token():
    """Isolado à parte para o teste substituir por um dublê — fala com o
    Microsoft Graph de verdade, não dá para testar direto."""
    tenant_id = settings.GRAPH_FINANCEIRO_TENANT_ID.strip()
    resposta = requests.post(
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
        data={
            "client_id": settings.GRAPH_FINANCEIRO_CLIENT_ID,
            "client_secret": settings.GRAPH_FINANCEIRO_CLIENT_SECRET,
            "grant_type": "client_credentials",
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=settings.GRAPH_FINANCEIRO_TIMEOUT,
    )
    try:
        corpo = resposta.json()
    except ValueError:
        corpo = {"raw": resposta.text}

    if resposta.status_code >= 400 or "access_token" not in corpo:
        raise EmailFinanceiroSyncError(
            f"Falha ao autenticar no Microsoft Graph: "
            f"{corpo.get('error_description') or corpo.get('error') or corpo}"
        )
    return corpo["access_token"]


def _graph_get(url, token, params=None):
    resposta = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=settings.GRAPH_FINANCEIRO_TIMEOUT,
    )
    if resposta.status_code >= 400:
        raise EmailFinanceiroSyncError(f"Falha na leitura do Microsoft Graph: {resposta.text}")
    return resposta


def _buscar_mime(caixa, id_mensagem, token):
    """`Accept: message/rfc822` devolve o e-mail bruto — mesmo formato que
    `_processar_mensagem` já sabe interpretar (parsing testado à parte,
    sem depender de rede)."""
    url = f"{GRAPH_BASE_URL}/users/{quote(caixa, safe='')}/messages/{quote(id_mensagem, safe='')}/$value"
    resposta = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "message/rfc822"},
        timeout=settings.GRAPH_FINANCEIRO_TIMEOUT,
    )
    if resposta.status_code >= 400:
        raise EmailFinanceiroSyncError(f"Falha ao baixar a mensagem do Microsoft Graph: {resposta.text}")
    return resposta.content


def _parametros_iniciais():
    """Primeira sincronização (sem delta link salvo ainda): limita à janela
    de dias configurada, não ao histórico inteiro da caixa."""
    desde = timezone.now() - timedelta(days=settings.GRAPH_FINANCEIRO_INITIAL_LOOKBACK_DAYS)
    desde_utc = desde.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "changeType": "created",
        "$select": "id,internetMessageId,subject,from,receivedDateTime",
        "$filter": f"receivedDateTime ge {desde_utc}",
        "$top": "50",
    }


def _decodificar_cabecalho(valor):
    """Assunto de e-mail pode vir em "encoded-word" MIME (`=?UTF-8?B?...?=`)
    — decodifica para texto simples antes de procurar o código de
    rastreio (RN-009)."""
    if not valor:
        return ""
    partes = decode_header(valor)
    texto = ""
    for fragmento, codificacao in partes:
        if isinstance(fragmento, bytes):
            texto += fragmento.decode(codificacao or "utf-8", errors="replace")
        else:
            texto += fragmento
    return texto


def _classificar_anexos(mensagem):
    """Separa os anexos do e-mail em PDF e XML (RN-005) pelo Content-Type —
    ignora o corpo do e-mail (texto/HTML sem `Content-Disposition:
    attachment`)."""
    pdfs = []
    xmls = []
    for parte in mensagem.walk():
        if parte.get_content_disposition() != "attachment":
            continue
        tipo = parte.get_content_type()
        payload = parte.get_payload(decode=True)
        if not payload:
            continue
        nome = parte.get_filename() or ""
        if tipo == "application/pdf" or nome.lower().endswith(".pdf"):
            pdfs.append((nome or "nota_fiscal.pdf", payload))
        elif tipo in ("text/xml", "application/xml") or nome.lower().endswith(".xml"):
            xmls.append((nome or "nota_fiscal.xml", payload))
    return pdfs, xmls


def _salvar_documento(ri, tipo, nome_arquivo, payload):
    """RF-08: grava a nova versão como vigente e aposenta a anterior — o
    próprio model já prevê múltiplas versões (`Documento.versao/ativo`)."""
    Documento.objects.filter(ri=ri, tipo=tipo, ativo=True).update(ativo=False)
    ultima_versao = (
        Documento.objects.filter(ri=ri, tipo=tipo).order_by("-versao").values_list("versao", flat=True).first()
        or 0
    )
    documento = Documento(ri=ri, tipo=tipo, versao=ultima_versao + 1, ativo=True, recebido_em=timezone.now())
    documento.arquivo.save(nome_arquivo, ContentFile(payload), save=False)
    documento.save()
    return documento


def _processar_mensagem(bruto, mensagem_id_externo):
    """Processa uma mensagem já baixada do Graph (bytes RFC822, formato
    igual ao de um `.eml`). Devolve uma string com o resultado
    (`"identificados"`, `"fora_do_padrao"`, `"sem_codigo"`,
    `"sem_ri_aguardando"` ou `"duplicado"`) — usada só para contagem."""
    if mensagem_id_externo and EmailFinanceiroLog.objects.filter(
        mensagem_id_externo=mensagem_id_externo
    ).exists():
        # O delta query do Graph pode reentregar a mesma mensagem entre
        # passadas (garantia "ao menos uma vez", não "exatamente uma vez").
        return "duplicados"

    mensagem = message_from_bytes(bruto, policy=policy.default)
    assunto = _decodificar_cabecalho(mensagem.get("Subject", ""))
    remetente = mensagem.get("From", "")

    inep = extrair_primeiro_inep_rastreio(assunto)
    if not inep:
        logger.warning("E-mail do financeiro sem código de rastreio no assunto: %r", assunto)
        return "sem_codigo"

    ri = (
        Ri.objects.filter(escola__inep=inep, status=Ri.AGUARDANDO_FINANCEIRO)
        .order_by("-criado_em")
        .first()
    )
    if not ri:
        logger.warning(
            "E-mail do financeiro com INEP %s identificado, mas nenhum RI está "
            "aguardando financeiro para esse INEP.",
            inep,
        )
        return "sem_ri_aguardando"

    pdfs, xmls = _classificar_anexos(mensagem)
    padrao_ok = len(pdfs) == 1 and len(xmls) == 1
    status_leitura = EmailFinanceiroLog.OK if padrao_ok else EmailFinanceiroLog.FORA_DO_PADRAO

    anexo_pdf_nome = pdfs[0][0] if padrao_ok else ""
    documentos_recebidos = []
    if padrao_ok:
        documentos_recebidos.append(_salvar_documento(ri, Documento.NOTA_FISCAL_PDF, pdfs[0][0], pdfs[0][1]))
        documentos_recebidos.append(_salvar_documento(ri, Documento.XML, xmls[0][0], xmls[0][1]))

    EmailFinanceiroLog.objects.create(
        ri=ri,
        direcao=EmailFinanceiroLog.RECEBIDO,
        remetente=remetente,
        assunto=assunto,
        anexo_pdf=anexo_pdf_nome,
        status_leitura=status_leitura,
        mensagem_id_externo=mensagem_id_externo or "",
    )
    auditar(
        None,
        Auditoria.RECEBIMENTO_EMAIL,
        entidade="Ri",
        entidade_id=ri.pk,
        campo="assunto",
        valor_novo=assunto,
    )

    if padrao_ok:
        resumo = f"E-mail de resposta do financeiro recebido. Assunto: {assunto}"
    else:
        resumo = (
            f"E-mail de resposta do financeiro fora do padrão (esperado 1 PDF + 1 XML; "
            f"recebido {len(pdfs)} PDF e {len(xmls)} XML). Assunto: {assunto}"
        )
    entrada_email = RiHistorico.objects.create(ri=ri, tipo=RiHistorico.EMAIL, autor=None, mensagem=resumo)
    if documentos_recebidos:
        # RN-008 (correção 2026-08-27): referencia os `Documento` já
        # salvos, em vez de duplicar o arquivo numa entrada separada —
        # PDF e XML ficam disponíveis para download na própria entrada do
        # e-mail, não em cards à parte na linha do tempo.
        entrada_email.documentos.set(documentos_recebidos)

    # RN-016: qualquer resposta do financeiro avança o RI para "Resposta
    # Financeiro" — válida ou fora do padrão. Antes, só a resposta no
    # padrão fazia essa transição; a fora do padrão ficava parada em
    # "Aguardando financeiro", visível só pelo alerta no log.
    trocar_status_com_log(ri, Ri.AGUARDANDO_ANEXO_PORTAL_EACE, usuario=None)

    if not padrao_ok:
        logger.warning("RI %s: %s", ri.pk, resumo)
        return "fora_do_padrao"

    return "identificados"


def sincronizar_respostas_financeiro():
    """Uma passada de polling (RF-08/RF-19): lê as mensagens novas da caixa
    do financeiro desde a última passada (delta query do Microsoft Graph),
    identifica o RI pelo código de rastreio (RN-009) e processa a resposta
    (RN-005). Mensagem sem código reconhecível, sem RI correspondente
    aguardando, ou fora do padrão nunca bloqueia — só gera alerta no log
    (`logger.warning`, visível em `docker compose logs web`)."""
    if not _graph_habilitado():
        raise EmailFinanceiroSyncError(
            "Sincronização do Microsoft Graph desabilitada — defina "
            "GRAPH_FINANCEIRO_ENABLED/CLIENT_ID/CLIENT_SECRET/TENANT_ID no .env."
        )

    resultado = {
        "processados": 0,
        "identificados": 0,
        "fora_do_padrao": 0,
        "sem_codigo": 0,
        "sem_ri_aguardando": 0,
        "duplicados": 0,
    }

    caixa = _resolver_caixa()
    estado = EmailFinanceiroSync.obter_configuracao(caixa)

    try:
        token = _obter_token()
        url = (
            estado.delta_link
            or f"{GRAPH_BASE_URL}/users/{quote(caixa, safe='')}/mailFolders/inbox/messages/delta"
        )
        params = None if estado.delta_link else _parametros_iniciais()
        delta_link_final = None
        paginas = 0

        while url:
            paginas += 1
            if paginas > settings.GRAPH_FINANCEIRO_MAX_PAGES_PER_RUN:
                raise EmailFinanceiroSyncError(
                    "A sincronização excedeu o limite de páginas desta execução."
                )

            resposta = _graph_get(url, token, params=params)
            dados = resposta.json()
            params = None

            for item in dados.get("value", []):
                if "@removed" in item:
                    continue

                id_mensagem = (item.get("id") or "").strip()
                if not id_mensagem:
                    continue

                resultado["processados"] += 1
                mensagem_id_externo = (item.get("internetMessageId") or "").strip() or id_mensagem
                try:
                    bruto = _buscar_mime(caixa, id_mensagem, token)
                    chave = _processar_mensagem(bruto, mensagem_id_externo)
                    resultado[chave] += 1
                except Exception as erro:
                    logger.exception("Erro ao processar mensagem do Graph %s.", id_mensagem)
                    auditar(
                        None,
                        Auditoria.ERRO,
                        entidade="EmailFinanceiroSync",
                        campo=type(erro).__name__,
                        valor_novo=f"Mensagem {id_mensagem}: {erro}",
                    )

            proxima = dados.get("@odata.nextLink")
            delta_link_final = dados.get("@odata.deltaLink") or delta_link_final
            url = proxima

        if delta_link_final:
            estado.delta_link = delta_link_final
        estado.ultima_sincronizacao_em = timezone.now()
        estado.ultimo_erro = ""
        estado.save()
    except EmailFinanceiroSyncError as erro:
        estado.ultimo_erro = str(erro)
        estado.save(update_fields=["ultimo_erro", "atualizado_em"])
        raise

    return resultado


def montar_dashboard_financeiro(estado=None, municipio=None, kit=None, produto=None):
    """FEAT-026 (RN-025/RN-026): valores dos 2 primeiros cards do
    dashboard financeiro (`core/home.html`).

    "Valor Total do Projeto" soma, para todas as Escolas do sistema, o
    valor do Kit Declarado (RN-010) + o valor do Nobreak inicial (RN-017,
    correção 2026-08-27) — os dois resolvidos pelo catálogo `KitPadrao`.
    O catálogo é pequeno (LPU) e é carregado 1 única vez, cruzado em
    memória com cada Escola (mesma técnica de `catalogo=` já usada pelo
    Grid de INEPs, FEAT-007) — evita 1 consulta por escola.

    "Valor já faturado" soma `quantidade * valor_unitario` dos itens do
    Lado Relatório EACE (3º lado) só dos RIs com status "Faturamento
    Concluído" — 1 única consulta agregada no banco.

    Escola sem correspondência no catálogo (Kit ou Nobreak) contribui com
    R$ 0,00 nessa parte do total (RN-025 — opção conservadora, mesma
    pendência de decisão ainda aberta na RN-010).

    `estado` (RN-027, FEAT-026 ampliada, 2026-08-27): quando informado
    (UF de `Escola.estado`), os 2 cards passam a somar só as escolas (card
    1) e os RIs (card 2, via `ri__escola__estado`) daquele estado — mesmo
    clique do gráfico "Faturado por Estado" (`montar_faturamento_por_estado`).

    `municipio` (RN-027 ampliada, 2026-08-27): drill-down de 1 nível —
    clicar num município do gráfico "Faturado por Município" (dentro do
    estado selecionado) filtra ainda mais os 2 cards. Só é aplicado junto
    com `estado` (nome de município se repete entre estados diferentes;
    sem o estado, filtrar só por município misturaria cidades homônimas
    de UFs distintas).

    `kit`/`produto` (ampliação, 2026-08-28, pedido do usuário — navegação
    cruzada com o dashboard Equipamentos): usuário reportou que ao clicar
    "Ver Faturamento de UF" vindo de um Kit/Equipamento Complementar
    filtrado, o Faturamento tinha que "mostrar o valor daquele filtro",
    não o valor geral do estado. `kit` restringe os 2 cards a só aquele
    tipo de Kit — meta (Card 1) some do Nobreak, conta só o Kit
    filtrado; faturado (Card 2) soma só os itens daquele Kit
    (`eh_kit=True`). `produto` restringe só o Card 2 (Valor Faturado) —
    Equipamento Complementar nunca é programado antes do projeto
    (confirmado pelo usuário), não tem meta; `tem_meta=False` sinaliza o
    template a esconder o Card 1 e a comparação com meta nesse caso.
    `kit`/`produto` nunca vêm juntos (mutuamente exclusivos na origem —
    dashboard Equipamentos só filtra 1 de cada vez)."""
    duas_casas = Decimal("0.01")
    catalogo = list(KitPadrao.objects.all())
    tem_meta = not produto

    escolas_qs = Escola.objects.only("kit_inicial", "nobreak_inicial", "lote")
    if estado:
        escolas_qs = escolas_qs.filter(estado=estado)
        if municipio:
            escolas_qs = escolas_qs.filter(municipio=municipio)

    valor_total_projeto = Decimal("0")
    if tem_meta:
        for escola in escolas_qs:
            kit_resolvido = KitPadrao.resolver_kit_declarado(
                escola.kit_inicial, lote=escola.lote, catalogo=catalogo
            )
            if kit_resolvido:
                descricao = kit_resolvido.descricao_curta or kit_resolvido.descricao
                if not kit or descricao == kit:
                    valor_total_projeto += kit_resolvido.valor_total
            if not kit:
                # Nobreak só entra na meta geral (sem filtro de Kit) — ao
                # filtrar 1 tipo de Kit específico, a meta é só dele.
                nobreak = KitPadrao.resolver_nobreak_declarado(
                    escola.nobreak_inicial, lote=escola.lote, catalogo=catalogo
                )
                if nobreak:
                    valor_total_projeto += nobreak.valor_total
    valor_total_projeto = valor_total_projeto.quantize(duas_casas)

    itens_relatorio_eace_qs = RiItemRelatorioEace.objects.filter(
        ri__status=Ri.FATURAMENTO_CONCLUIDO
    )
    if estado:
        itens_relatorio_eace_qs = itens_relatorio_eace_qs.filter(ri__escola__estado=estado)
        if municipio:
            itens_relatorio_eace_qs = itens_relatorio_eace_qs.filter(ri__escola__municipio=municipio)
    if kit:
        itens_relatorio_eace_qs = itens_relatorio_eace_qs.filter(descricao_item=kit, eh_kit=True)
    elif produto:
        itens_relatorio_eace_qs = itens_relatorio_eace_qs.filter(descricao_item=produto, eh_kit=False)
    valor_faturado = itens_relatorio_eace_qs.aggregate(
        total=Sum(
            F("quantidade") * F("valor_unitario"),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        )
    )["total"] or Decimal("0")
    # RN-026: soma agregada no banco — SQLite (dev/teste) nem sempre devolve
    # a mesma escala decimal do MySQL (produção, `DB_ENGINE=mysql`); força
    # 2 casas para a exibição em R$ ficar sempre consistente entre os dois.
    valor_faturado = Decimal(valor_faturado).quantize(duas_casas)

    diferenca = valor_total_projeto - valor_faturado
    meta_atingida = diferenca <= 0
    valor_faltante = max(diferenca, Decimal("0"))
    valor_excedente = max(-diferenca, Decimal("0"))

    if valor_total_projeto > 0:
        # Correção (2026-08-27, pedido do usuário): sem cap — quando o valor
        # faturado ultrapassa a meta, o texto/badge deve mostrar mais de
        # 100% (ex.: 120%), não travar em 100%.
        percentual_faturado_pct = (valor_faturado / valor_total_projeto) * 100
    else:
        percentual_faturado_pct = Decimal("100") if valor_faturado > 0 else Decimal("0")
    # A barra de 2 segmentos (verde/vermelho) do card 2 é geometricamente
    # limitada a 100% da altura do contêiner — usa uma % capada só para as
    # alturas em CSS; o texto/badge usa a % real (sem cap) acima.
    percentual_faturado_barra_pct = min(percentual_faturado_pct, Decimal("100"))
    percentual_faltante_pct = Decimal("100") - percentual_faturado_barra_pct

    return {
        "valor_total_projeto": valor_total_projeto,
        "valor_faturado": valor_faturado,
        "valor_faltante": valor_faltante,
        "valor_excedente": valor_excedente,
        "meta_atingida": meta_atingida,
        "percentual_faturado_pct": percentual_faturado_pct,
        "percentual_faltante_pct": percentual_faltante_pct,
        # RN-026: valores prontos para `style="height: ...%"` — formatados em
        # Python (ponto decimal sempre), nunca via filtro de template, que
        # localizaria para vírgula (CSS inválido, ex.: "40,00%"). Sempre
        # 0..100 (capados), diferente de `percentual_faturado_pct` acima.
        "percentual_faturado_css": f"{percentual_faturado_barra_pct:.2f}",
        "percentual_faltante_css": f"{percentual_faltante_pct:.2f}",
        "estado_filtrado": estado,
        "municipio_filtrado": municipio if estado else None,
        "kit_filtrado": kit,
        "produto_filtrado": produto,
        "tem_meta": tem_meta,
    }


def montar_faturamento_por_estado():
    """FEAT-026 (ampliação, 2026-08-27): dados do gráfico "Faturado por
    Estado" — 1 linha por UF de `Escola.estado` (não vazio), com o valor
    já faturado (mesma regra da RN-026: só itens do Lado Relatório EACE de
    RIs em "Faturamento Concluído") e a meta daquele estado (Kit + Nobreak
    inicial das escolas da UF, mesmo cálculo por escola da RN-025). Clicar
    numa linha filtra os 2 cards por aquele estado
    (`montar_dashboard_financeiro(estado=...)`).

    A barra é proporcional a quanto da própria meta do estado já foi
    faturado — mesma semântica dos 2 cards de cima (RN-026), não ao valor
    bruto faturado comparado entre estados. Ordenado por essa mesma %,
    do maior (mais perto de bater a meta) para o menor (2026-08-27,
    pedido do usuário) — não pelo valor bruto faturado.

    UF sem nenhum item faturado ainda entra com R$ 0,00 — não fica de
    fora do gráfico, para o usuário poder comparar até quem ainda não
    faturou nada. Escola sem Estado cadastrado não entra (não há UF para
    agrupar); é uma lacuna de cadastro, não tratada aqui."""
    duas_casas = Decimal("0.01")
    catalogo = list(KitPadrao.objects.all())

    meta_por_uf = {}
    for escola in Escola.objects.exclude(estado="").only(
        "kit_inicial", "nobreak_inicial", "lote", "estado"
    ):
        kit = KitPadrao.resolver_kit_declarado(
            escola.kit_inicial, lote=escola.lote, catalogo=catalogo
        )
        nobreak = KitPadrao.resolver_nobreak_declarado(
            escola.nobreak_inicial, lote=escola.lote, catalogo=catalogo
        )
        valor = Decimal("0")
        if kit:
            valor += kit.valor_total
        if nobreak:
            valor += nobreak.valor_total
        meta_por_uf[escola.estado] = meta_por_uf.get(escola.estado, Decimal("0")) + valor

    faturado_por_uf = dict(
        RiItemRelatorioEace.objects.filter(ri__status=Ri.FATURAMENTO_CONCLUIDO)
        .values("ri__escola__estado")
        .annotate(
            total=Sum(
                F("quantidade") * F("valor_unitario"),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            )
        )
        .values_list("ri__escola__estado", "total")
    )

    linhas = []
    for uf, meta in meta_por_uf.items():
        meta = meta.quantize(duas_casas)
        faturado = Decimal(faturado_por_uf.get(uf) or Decimal("0")).quantize(duas_casas)
        if meta > 0:
            percentual = min((faturado / meta) * 100, Decimal("100"))
        else:
            percentual = Decimal("100") if faturado > 0 else Decimal("0")
        linhas.append({
            "estado": uf,
            "valor": faturado,
            "meta": meta,
            "percentual": percentual,
            # Ponto decimal sempre (CSS de `style="width: ...%"` — nunca vírgula).
            "percentual_css": f"{percentual:.2f}",
        })
    # Ordena pela % da meta já faturada (100% primeiro), não pelo valor bruto.
    linhas.sort(key=lambda linha: linha["percentual"], reverse=True)

    return linhas


def montar_faturamento_por_municipio(estado):
    """FEAT-026 (ampliação, 2026-08-27): drill-down de 1 nível do gráfico
    "Faturado por Estado" — usuário pediu que, ao clicar num estado, o
    mesmo gráfico expanda mostrando os Municípios daquele estado, com as
    mesmas informações (valor faturado, meta e barra proporcional).

    Mesma regra da RN-027, só que agrupando por `Escola.municipio` dentro
    do `estado` informado (obrigatório — nome de município se repete
    entre UFs diferentes, RN-027 ampliada). Município sem faturamento
    ainda entra com R$ 0,00; escola sem Município cadastrado não entra.
    Ordenado pela % da meta já faturada, do maior para o menor (mesmo
    critério do gráfico de Estado). Sem `estado`, retorna lista vazia
    (não há o que expandir)."""
    if not estado:
        return []

    duas_casas = Decimal("0.01")
    catalogo = list(KitPadrao.objects.all())

    meta_por_municipio = {}
    escolas_qs = (
        Escola.objects.filter(estado=estado)
        .exclude(municipio="")
        .only("kit_inicial", "nobreak_inicial", "lote", "municipio")
    )
    for escola in escolas_qs:
        kit = KitPadrao.resolver_kit_declarado(
            escola.kit_inicial, lote=escola.lote, catalogo=catalogo
        )
        nobreak = KitPadrao.resolver_nobreak_declarado(
            escola.nobreak_inicial, lote=escola.lote, catalogo=catalogo
        )
        valor = Decimal("0")
        if kit:
            valor += kit.valor_total
        if nobreak:
            valor += nobreak.valor_total
        meta_por_municipio[escola.municipio] = (
            meta_por_municipio.get(escola.municipio, Decimal("0")) + valor
        )

    faturado_por_municipio = dict(
        RiItemRelatorioEace.objects.filter(
            ri__status=Ri.FATURAMENTO_CONCLUIDO, ri__escola__estado=estado
        )
        .values("ri__escola__municipio")
        .annotate(
            total=Sum(
                F("quantidade") * F("valor_unitario"),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            )
        )
        .values_list("ri__escola__municipio", "total")
    )

    linhas = []
    for municipio, meta in meta_por_municipio.items():
        meta = meta.quantize(duas_casas)
        faturado = Decimal(faturado_por_municipio.get(municipio) or Decimal("0")).quantize(duas_casas)
        if meta > 0:
            percentual = min((faturado / meta) * 100, Decimal("100"))
        else:
            percentual = Decimal("100") if faturado > 0 else Decimal("0")
        linhas.append({
            "municipio": municipio,
            "valor": faturado,
            "meta": meta,
            "percentual": percentual,
            "percentual_css": f"{percentual:.2f}",
        })
    # Ordena pela % da meta já faturada (100% primeiro), não pelo valor bruto
    # (mesmo critério do gráfico "Faturado por Estado", pedido do usuário).
    linhas.sort(key=lambda linha: linha["percentual"], reverse=True)

    return linhas


# ==========================================
# FEAT-026 (submenu "Equipamentos" do dashboard, pedido do usuário,
# 2026-08-28): card "Equipamentos Programados". Critério de aceite ainda
# não formalizado em business_rules.md/checklist.md (nasceu como
# placeholder "sem cards definidos", mesmo caso já registrado da RN-027 —
# nota para o Orquestrador deixada no checklist.md).
# ==========================================


def montar_dashboard_equipamentos(estado=None, kit=None, produto=None):
    """3 cards: "Kits Programados", "Kits Instalados" e "Nobreaks
    Programados", mais o detalhamento "Produtos Complementares"
    (ampliação, 2026-08-28, pedido do usuário) — equipamento avulso (ex.:
    Rack, Switch, Access Point adicional) lançado no Lado Relatório EACE
    além do Kit e do Nobreak; usuário confirmou que essa lista também vem
    do Lado 3. Ver docstring do bloco de "Produtos Complementares" mais
    abaixo para os detalhes.

    Definição revista com o usuário 3 vezes no mesmo dia (2026-08-28):
    1ª versão somava a Quantidade cadastrada em `RiItemEace` (1º lado do
    RI), mas essa tabela tinha só 9 registros lançados para as 2.622
    escolas do projeto real — Lote 1 fica bloqueado sem a planilha de
    Quantidade/Valor e Lote 2/3 dependem de lançamento manual no admin
    (RN-010), então quase nada tinha sido lançado ainda; sem uso prático.
    2ª versão somava o `numero_access_points` do Kit de cada escola — o
    usuário reportou, vendo o app real, que isso ultrapassava 20 mil,
    quando "Kits Programados" deveria ser 1 por escola (no máximo 2.622).
    3ª versão manteve 1 Kit por escola no card, mas ainda expunha o total
    de Access Points (escolas × tamanho do Kit) no detalhamento "Kits por
    Produto" — usuário esclareceu que esse número (ex.: 267 escolas × 15 =
    4.005) não corresponde a nada real no inventário dele; "Access
    Points" é só o nome/tamanho do tipo de Kit, não uma contagem de
    equipamento físico que se multiplica pela quantidade de escolas.
    Versão final: nenhum card ou detalhamento multiplica escola por
    tamanho de Kit — só contagem de escolas, em todo lugar.

    "Kits Instalados" (ampliação, 2026-08-28, pedido do usuário): 1ª
    versão usava `Escola.status_conexao` "conectado" (RN-007) — usuário
    corrigiu, apontando que o dado certo é o Kit lançado no Lado
    Relatório EACE (3º lado, `RiItemRelatorioEace.eh_kit=True`) de RIs com
    status "Faturamento Concluído" — mesma fonte já usada no card "Valor
    já Faturado" (RN-026), o Lado que é literalmente baixado da EACE
    depois da instalação (ao contrário do Lado IXC/2º lado, digitado
    manualmente pelo técnico, que tinha só 2 dos 368 RIs em Faturamento
    Concluído com Kit lançado — dado quase inexistente). Conta escolas
    distintas (não RIs) para não contar 2x uma escola com mais de 1 RI
    concluído histórico.

    Fonte de dado do "Kits Programados"/"Nobreaks Programados" é a mesma
    já usada no card "Valor Total do Projeto"
    (RN-025): `Escola.kit_inicial` + `Escola.nobreak_inicial` (RN-017)
    resolvidos pelo catálogo `KitPadrao` — dado que já existe para as
    2.622 escolas.

    Kit e Nobreak são contados em cards separados (pedido do usuário,
    2026-08-28) — são unidades de natureza diferente (Kit de rede Wi-Fi ×
    equipamento de energia), somar os dois num único total não faz
    sentido para leitura.

    Para cada Escola do sistema (visão global, sem filtro de período/
    lote/status, mesmo recorte da RN-025): "Kits Programados" conta 1 por
    escola com Kit Declarado resolvido no catálogo; "Nobreaks Programados"
    conta 1 por escola com Nobreak resolvido no catálogo (RN-017: item
    fixo). Escola sem correspondência no catálogo (Kit ou Nobreak) não
    soma nessa parte — mesma regra conservadora da RN-025, não trava o
    dashboard nem inventa quantidade (CLAUDE.md §9).

    `estado` (ampliação, 2026-08-28): quando informado (UF de
    Escola.estado), os 3 cards e o detalhamento "Kits por Produto" passam
    a contar só as escolas daquele estado — mesmo clique do gráfico "Kits
    Instalados por Estado" (`montar_kits_instalados_por_estado`), mesmo
    padrão do filtro por estado já usado no dashboard Faturamento
    (RN-027).

    `kit`/`produto` (ampliação, 2026-08-28, pedido do usuário): clique
    numa linha de "Kits por Produto"/"Produtos Complementares" — mesmo
    padrão de clique do `estado`, os 3 filtros são combináveis (o usuário
    pode filtrar estado + kit ao mesmo tempo, por exemplo). `kit`
    restringe "Kits Programados"/"Kits Instalados"/o próprio
    detalhamento a só aquele tipo de Kit (Descrição); `produto` restringe
    só "Produtos Complementares" — Kit e Produto Complementar são eixos
    independentes, um filtro não afeta o outro.

    Também devolve, por tipo de Kit (Descrição), a quantidade de escolas
    Programadas e Instaladas com aquele Kit (maior Programados primeiro)
    — pedido do usuário (2026-08-28): ao filtrar por estado, o total do
    card "Kits Instalados" sozinho não dizia quais tipos de Kit formam
    aquele número; agora cada linha do detalhamento mostra as 2 contagens
    lado a lado, já dentro do recorte de estado selecionado. Uma
    Descrição pode aparecer só do lado Instalados (sem Programados) se o
    texto gravado no Lado Relatório EACE não bater com o resolvido agora
    pelo catálogo a partir de `Escola.kit_inicial` — nenhuma linha é
    descartada nesse caso, para não esconder Kit instalado (CLAUDE.md
    §9). Nobreak não entra nesse detalhamento — é um item único, já
    coberto pelo próprio card.

    Também devolve `percentual_kits_instalados_pct`/`kits_meta_atingida`
    (ampliação, 2026-08-28, pedido do usuário) — badge de % igual ao já
    usado no card "Valor já Faturado" (RN-026): % de Kits Instalados
    sobre Kits Programados, sem teto (podendo passar de 100% se as 2
    fontes divergirem num recorte), "meta atingida" só com meta real
    alcançada/ultrapassada."""
    catalogo = list(KitPadrao.objects.all())
    escolas_qs = Escola.objects.only("kit_inicial", "nobreak_inicial", "lote")
    if estado:
        escolas_qs = escolas_qs.filter(estado=estado)

    total_kits = 0
    total_nobreaks = 0
    kits_por_produto = {}
    for escola in escolas_qs:
        kit_resolvido = KitPadrao.resolver_kit_declarado(
            escola.kit_inicial, lote=escola.lote, catalogo=catalogo
        )
        nobreak = KitPadrao.resolver_nobreak_declarado(
            escola.nobreak_inicial, lote=escola.lote, catalogo=catalogo
        )
        if kit_resolvido:
            descricao = kit_resolvido.descricao_curta or kit_resolvido.descricao
            if not kit or descricao == kit:
                total_kits += 1
                kits_por_produto[descricao] = kits_por_produto.get(descricao, 0) + 1
        if nobreak:
            total_nobreaks += 1

    kits_instalados_qs = RiItemRelatorioEace.objects.filter(
        eh_kit=True, ri__status=Ri.FATURAMENTO_CONCLUIDO
    )
    if estado:
        kits_instalados_qs = kits_instalados_qs.filter(ri__escola__estado=estado)
    if kit:
        kits_instalados_qs = kits_instalados_qs.filter(descricao_item=kit)
    total_kits_instalados = kits_instalados_qs.values("ri__escola_id").distinct().count()

    instalados_por_produto = dict(
        kits_instalados_qs.values("descricao_item")
        .annotate(total=Count("ri__escola_id", distinct=True))
        .values_list("descricao_item", "total")
    )

    # União das 2 origens (RN-025-style, CLAUDE.md §9): uma Descrição só do
    # lado Instalados (sem Programados no recorte atual) ainda aparece —
    # não descarta Kit instalado por não bater com o catálogo resolvido
    # agora a partir de Escola.kit_inicial.
    todas_descricoes = set(kits_por_produto) | set(instalados_por_produto)
    linhas = sorted(
        (
            {
                "descricao_item": descricao,
                "quantidade_total": kits_por_produto.get(descricao, 0),
                "instalados_total": instalados_por_produto.get(descricao, 0),
            }
            for descricao in todas_descricoes
        ),
        key=lambda linha: (-linha["quantidade_total"], -linha["instalados_total"], linha["descricao_item"]),
    )

    # Produtos Complementares (ampliação, 2026-08-28, pedido do usuário):
    # equipamento avulso lançado no Lado Relatório EACE (3º lado, mesma
    # fonte confirmada pelo usuário para "Kits Instalados") além do Kit
    # (eh_kit=True) e do Nobreak (descrição fixa "Nobreak", também
    # lançado avulso às vezes — excluído daqui por já ter card/linha
    # próprios). Diferente do Kit (quantidade sempre 1, RN-018), o campo
    # Quantidade aqui é uma contagem real por escola (ex.: 2 Racks) — soma
    # legítima, não é o mesmo problema do "267 × 15 Access Points" (RN-010
    # ampliada) resolvido antes: aqui a Quantidade não vem embutida na
    # Descrição, é um dado lançado à parte. Nunca programado antes do
    # projeto (usuário) — só aparece depois que alguém lança/confirma a
    # instalação, por isso não tem par "Programado" como o Kit.
    produtos_complementares_qs = RiItemRelatorioEace.objects.filter(
        eh_kit=False, ri__status=Ri.FATURAMENTO_CONCLUIDO
    ).exclude(descricao_item="Nobreak")
    if estado:
        produtos_complementares_qs = produtos_complementares_qs.filter(ri__escola__estado=estado)
    if produto:
        produtos_complementares_qs = produtos_complementares_qs.filter(descricao_item=produto)
    produtos_complementares = list(
        produtos_complementares_qs.values("descricao_item")
        .annotate(
            quantidade_total=Sum("quantidade"),
            escolas_total=Count("ri__escola_id", distinct=True),
        )
        .order_by("-quantidade_total", "descricao_item")
    )

    # Badge de % (pedido do usuário, 2026-08-28): mesmo padrão do card
    # "Valor já Faturado" (RN-026) — % sem teto (instalado pode superar o
    # programado num recorte com divergência entre as 2 fontes), "meta
    # atingida" só quando há meta real e ela foi alcançada/ultrapassada.
    if total_kits > 0:
        percentual_kits_instalados_pct = (total_kits_instalados / total_kits) * 100
    else:
        percentual_kits_instalados_pct = 100 if total_kits_instalados > 0 else 0
    kits_meta_atingida = total_kits > 0 and total_kits_instalados >= total_kits

    return {
        "total_kits_programados": total_kits,
        "total_kits_instalados": total_kits_instalados,
        "total_nobreaks_programados": total_nobreaks,
        "kits_por_produto": linhas,
        "produtos_complementares": produtos_complementares,
        "estado_filtrado": estado,
        "kit_filtrado": kit,
        "produto_filtrado": produto,
        "percentual_kits_instalados_pct": percentual_kits_instalados_pct,
        "kits_meta_atingida": kits_meta_atingida,
    }


def montar_kits_instalados_por_estado(kit=None):
    """FEAT-026 (submenu Equipamentos, ampliação 2026-08-28, pedido do
    usuário): dados do gráfico "Kits Instalados por Estado" — mesmo
    padrão visual e de cálculo do gráfico "Faturado por Estado" (RN-027),
    adaptado pra contagem de Kits em vez de R$.

    1 linha por UF de `Escola.estado` (não vazio), com a quantidade de
    Kits já instalados e a meta de Kits Programados daquele estado.
    "Instalado" é o Kit lançado no Lado Relatório EACE (3º lado,
    `RiItemRelatorioEace.eh_kit=True`) de RI com status "Faturamento
    Concluído" — mesma fonte do card "Valor já Faturado" (RN-026),
    corrigida pelo usuário (1ª versão usava `status_conexao`/RN-007).
    "Programado" é o mesmo critério do card "Kits Programados" (Kit
    reconhecido no catálogo `KitPadrao`). Clicar numa linha filtra os 3
    cards por aquele estado (`montar_dashboard_equipamentos(estado=...)`).

    A barra é proporcional a quanto da meta do estado já foi instalado —
    mesma semântica do gráfico de Faturamento, não ao valor bruto
    instalado comparado entre estados. Ordenado por essa mesma %, do
    maior (mais perto de bater a meta) para o menor.

    UF sem nenhum Kit instalado ainda entra com 0 — não fica de fora do
    gráfico. Escola sem Estado cadastrado, ou sem Kit reconhecido no
    catálogo, não entra na meta (mesma regra conservadora da RN-025 — não
    trava, não inventa).

    `kit` (ampliação, 2026-08-28, pedido do usuário): quando informado
    (clique numa linha de "Kits por Produto"), restringe Programado e
    Instalado a só aquele tipo de Kit — mostra a distribuição por estado
    de 1 Kit específico, combinável com o clique de estado."""
    catalogo = list(KitPadrao.objects.all())

    programados_por_uf = {}
    escolas_qs = Escola.objects.exclude(estado="").only("kit_inicial", "lote", "estado")
    for escola in escolas_qs:
        kit_resolvido = KitPadrao.resolver_kit_declarado(
            escola.kit_inicial, lote=escola.lote, catalogo=catalogo
        )
        if not kit_resolvido:
            continue
        descricao = kit_resolvido.descricao_curta or kit_resolvido.descricao
        if not kit or descricao == kit:
            programados_por_uf[escola.estado] = programados_por_uf.get(escola.estado, 0) + 1

    instalados_qs = RiItemRelatorioEace.objects.filter(
        eh_kit=True, ri__status=Ri.FATURAMENTO_CONCLUIDO
    ).exclude(ri__escola__estado="")
    if kit:
        instalados_qs = instalados_qs.filter(descricao_item=kit)
    instalados_por_uf = dict(
        instalados_qs.values("ri__escola__estado")
        .annotate(total=Count("ri__escola_id", distinct=True))
        .values_list("ri__escola__estado", "total")
    )

    linhas = []
    for uf, meta in programados_por_uf.items():
        instalado = instalados_por_uf.get(uf, 0)
        if meta > 0:
            percentual = min((instalado / meta) * 100, 100)
        else:
            percentual = 100 if instalado > 0 else 0
        linhas.append({
            "estado": uf,
            "valor": instalado,
            "meta": meta,
            "percentual": percentual,
            "percentual_css": f"{percentual:.2f}",
        })
    # Ordena pela % da meta já instalada (100% primeiro), mesmo critério
    # do gráfico "Faturado por Estado".
    linhas.sort(key=lambda linha: linha["percentual"], reverse=True)

    return linhas


def montar_produtos_complementares_por_estado(produto):
    """FEAT-026 (ampliação, 2026-08-28, pedido do usuário): usuário
    apontou que clicar num Equipamento Complementar precisa "filtrar a
    página toda" e mostrar "o estado que está aquele equipamento" — sem
    isso, o clique só filtrava o bloco "Equipamentos Complementares",
    sem dar acesso ao gráfico por estado nem ao link cruzado pro
    Faturamento (que só aparece com um estado selecionado). Esta função
    devolve 1 linha por UF onde aquele Equipamento Complementar
    específico aparece, com a Quantidade e as escolas — clicar numa
    linha define `estado`, que já dispara o link "Ver Faturamento de UF"
    existente (mesmo padrão do Kit) — é ali que o usuário vê "o valor no
    filtro de faturamento".

    Sem `produto` informado devolve lista vazia: misturar Rack + Switch +
    Access Point adicional num único total por estado não conta uma
    história clara (são equipamentos de natureza diferente) — só faz
    sentido depois que o usuário escolhe 1 Equipamento Complementar
    específico (mesmo racional de não somar Kits de tamanhos diferentes,
    resolvido antes nesta mesma FEAT).

    Diferente do gráfico de Kits, não tem "meta"/"programado" (RN-025 não
    se aplica — usuário confirmou que esses itens nunca são programados
    antes do projeto) — só a Quantidade real por estado, maior primeiro."""
    if not produto:
        return []

    linhas = list(
        RiItemRelatorioEace.objects.filter(
            eh_kit=False, ri__status=Ri.FATURAMENTO_CONCLUIDO, descricao_item=produto,
        )
        .exclude(ri__escola__estado="")
        .values("ri__escola__estado")
        .annotate(
            quantidade_total=Sum("quantidade"),
            escolas_total=Count("ri__escola_id", distinct=True),
        )
        .order_by("-quantidade_total", "ri__escola__estado")
    )
    return [
        {
            "estado": linha["ri__escola__estado"],
            "quantidade_total": linha["quantidade_total"],
            "escolas_total": linha["escolas_total"],
        }
        for linha in linhas
    ]
