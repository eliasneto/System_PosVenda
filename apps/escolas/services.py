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
import re
from decimal import Decimal

import openpyxl
from django.conf import settings
from django.db.models import OuterRef, Prefetch, Subquery
from django.utils import timezone

from apps.ri.models import KitPadrao, Ri
from apps.ri.services import casar_planilha_eace_com_catalogo, quantidade_planilha_eace

from .models import Escola, EscolaItemRelatorioEaceMip, PlanilhaRelatorioEaceMip


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


def _sincronizar_relatorio_eace_mip_da_escola(escola, linhas):
    """1 Escola: mesma regra de casamento Descrição×catálogo do
    Sincronizador do RI (RN-022) — KIT por número de Access Points,
    produto avulso por prefixo da Descrição curta — mas grava o Valor de
    serviço (RN-067), por Escola. A última planilha ativa é sempre a
    fonte de verdade (sem conceito de fase/status do RI para preservar
    lançamento manual, já que aqui não existe lançamento manual, RN-067):
    Descrição confirmada nesta rodada é criada/atualizada; Descrição
    ausente é removida. Mesma regra "só 1 KIT por INEP" do RI (RN-015):
    um novo KIT nunca substitui o já lançado, só protege o existente de
    ser removido."""
    itens_existentes = {item.descricao_item: item for item in escola.itens_relatorio_eace_mip.all()}
    kit_existente = next((item for item in itens_existentes.values() if item.eh_kit), None)
    confirmados = set()
    mudou = False

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

    for descricao_item, item in itens_existentes.items():
        if descricao_item not in confirmados:
            item.delete()
            mudou = True

    return mudou


def sincronizar_relatorio_eace_mip_de_todas_as_escolas():
    """Botão "Sincronizar todos os INEPs" (Administrador > Relatório EACE
    (MIP)) — aplica `_sincronizar_relatorio_eace_mip_da_escola` a toda
    Escola de uma vez, a partir do arquivo ativo (RN-069). Levanta
    `RelatorioEaceMipSincronizacaoError` só quando não há planilha ativa
    — a view converte em mensagem de erro.

    RN-081 (a criar): também grava, em toda Escola, se o INEP apareceu ou
    não na planilha desta rodada (`Escola.encontrado_relatorio_eace_mip`)
    — vira a bolinha verde/vermelha do grid do MIP. Sempre grava (mesmo
    quando `False`), pra refletir sempre o resultado desta sincronização,
    nunca de uma anterior.

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
        if _sincronizar_relatorio_eace_mip_da_escola(escola, linhas):
            escolas_atualizadas += 1

    return {"escolas_atualizadas": escolas_atualizadas, "escolas_sem_linha": escolas_sem_linha}


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


def _valor_total_itens(itens):
    """RN-076/RN-077 (a criar): soma quantidade × Valor de serviço de uma
    lista de itens do MIP — mesmo formato de dict usado tanto pelo Lado IXC
    (`_resolver_lado_ixc`, coluna "Valor Total (IXC)") quanto pelo Lado
    Relatório EACE (`apps.escolas.views._resolver_lado3_relatorio_eace_mip`,
    coluna "Valor Total (EACE)") — chaves "quantidade"/"valor_servico".

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
# Planilha de faturamento de implantação — a pedido do usuário, gerada a
# partir do mesmo filtro Estado+Município do grid "Projeto > MIP"
# (`apps.escolas.views.mip_inep_view`). RN própria desta feature ainda será
# formalizada pelo Orquestrador em `business_rules.md`/`checklist.md`; aqui
# ela referencia as regras já existentes que reaproveita: RN-074 (base de
# escolas — RI atual em "Aguardando validação EACE"), RN-079 (filtro Estado/
# Município) e RN-076 (Valor Total IXC = quantidade × Valor de serviço dos
# itens do Lado IXC).
# ---------------------------------------------------------------------------


class PlanilhaFaturamentoImplantacaoError(Exception):
    """Erro de negócio ao gerar a planilha de faturamento de implantação
    (`gerar_planilha_faturamento_implantacao`) — quem chamar (comando/futura
    view) converte em mensagem para o usuário. Nome próprio, não reaproveita
    `apps.ri.services.PlanilhaFaturamentoError`: são planilhas e fluxos
    diferentes (esta é por Estado/Município, a do RI é por RI)."""


CAMINHO_PLANILHA_FATURAMENTO_IMPLANTACAO_MODELO = settings.BASE_DIR / "doc" / "FATURAMENTO IMPLANTAÇÃO.xlsx"

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
    já existente na planilha-modelo — nunca reescreve o texto do zero."""
    texto = _RE_OBS_IMPLANTACAO_MUNICIPIO_UF.sub(
        lambda m: m.group(1) + f"{municipio}/{estado}", texto_modelo, count=1
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
