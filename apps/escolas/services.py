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
import re
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
from apps.ri.services import casar_planilha_eace_com_catalogo, quantidade_planilha_eace

from .models import Escola, EscolaItemRelatorioEaceMip, Lote, PlanilhaRelatorioEaceMip


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
    ativa ou sem nenhum INEP dela batendo com uma Escola já preenchida."""
    planilha = PlanilhaRelatorioEaceMip.ativa()
    if not planilha:
        return 0
    ineps_da_planilha = _agrupar_linhas_relatorio_eace_mip_por_inep(planilha).keys()
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
    `apps.escolas.views._comparar_valor_servico_ixc_relatorio_mip`)."""
    if not ri:
        return []
    return [
        {
            "pk": item.pk,
            "descricao": item.descricao_item,
            "quantidade": item.quantidade,
            "valor_servico": _valor_servico(item.descricao_item, item.eh_kit, lote, catalogo),
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


# ---------------------------------------------------------------------------
# FEAT-044/RN-098 (a formalizar pelo Orquestrador em business_rules.md;
# pedido do usuário, 2026-09-14): "Projeto > MIP (LOTE)" — agrupa, num
# `Lote`, os INEPs do MIP em "Aguardando Validação EACE" com Valor Total
# (IXC) == Valor Total (EACE) (RN-076/RN-077) dentro do filtro Estado +
# Município + Data inicial/final já existente no grid "Projeto > MIP"
# (RN-079/RN-075) — botão "Criar LOTE" ao lado do Total geral (RN-080,
# `apps.escolas.views.mip_lote_criar_view`).
# ---------------------------------------------------------------------------


def escolas_elegiveis_lote_mip(estado, municipio, data_inicio, data_fim):
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
    if data_inicio:
        escolas = escolas.filter(data_ativacao_ri_atual__gte=data_inicio)
    if data_fim:
        escolas = escolas.filter(data_ativacao_ri_atual__lte=data_fim)
    escolas = escolas.order_by("nome").prefetch_related(
        Prefetch("ris", queryset=Ri.objects.order_by("-criado_em").prefetch_related("itens_ixc"))
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
def criar_lote_mip(estado, municipio, data_inicio, data_fim, usuario, *, escola_ids=None):
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

    Cada INEP elegível ganha `Escola.status_mip =
    "aguardando_encerramento_lote"` e 2 entradas no histórico do RI atual
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

    elegiveis = escolas_elegiveis_lote_mip(estado, municipio, data_inicio, data_fim)
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
    )
    lote.escolas.set(escolas)
    for escola in escolas:
        status_anterior = escola.get_status_mip_display()
        escola.status_mip = Escola.AGUARDANDO_ENCERRAMENTO_LOTE
        escola.save(update_fields=["status_mip"])
        ris_da_escola = list(escola.ris.all())
        ri_atual = ris_da_escola[0] if ris_da_escola else None
        if ri_atual:
            _registrar_log_campo_lote(
                ri_atual, usuario, "Status (MIP)", status_anterior, escola.get_status_mip_display(),
            )
            _registrar_log_campo_lote(ri_atual, usuario, "LOTE", "", str(lote))
    return lote


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
    if lote.status != Lote.AGUARDANDO_ENCERRAMENTO:
        raise LoteMipError(
            f'Não é possível desfazer {lote} — já está em "{lote.get_status_display()}".'
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
        .filter(status_ri_atual=Ri.AGUARDANDO_VALIDACAO_EACE, estado=estado, municipio=municipio)
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


def _montar_planilha_faturamento_implantacao(escolas, *, estado, municipio, data_envio):
    """Preenche o modelo `doc/FATURAMENTO IMPLANTAÇÃO.xlsx` a partir de uma
    lista de `escolas` já resolvida pelo chamador — compartilhado por
    `gerar_planilha_faturamento_implantacao` (filtro Estado+Município do
    grid "Projeto > MIP") e `gerar_planilha_faturamento_implantacao_lote`
    (INEPs fixos de um `Lote`, FEAT-045): só muda de onde vêm as escolas, o
    preenchimento da planilha é sempre o mesmo. Ver as duas funções acima
    para o detalhamento de cada célula calculada (VALOR R$/H10, CÓDIGO
    INEPS/F10, VENCIMENTO/E10, aba/A13)."""
    # Catálogo carregado uma única vez (fora do loop), mesmo padrão anti-N+1
    # já usado pelo grid do MIP (RN-010/RN-076).
    catalogo_kits = list(KitPadrao.objects.all())
    total_valor_ixc = Decimal("0.00")
    codigos_ineps = []
    for escola in escolas:
        ris_da_escola = list(escola.ris.all())
        ri_atual = ris_da_escola[0] if ris_da_escola else None
        itens_ixc = _resolver_lado_ixc(ri_atual, escola.lote, catalogo_kits)
        valor_total_ixc, _incompleto = _valor_total_itens(itens_ixc)
        total_valor_ixc += valor_total_ixc or Decimal("0.00")
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
