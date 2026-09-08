import datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import DateTimeField, OuterRef, Prefetch, Q, Subquery
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from apps.ri.forms import RiHistoricoForm
from apps.ri.models import Documento, KitPadrao, Ri, RiHistorico

from .forms import PlanilhaRelatorioEaceMipPeriodoForm, PlanilhaRelatorioEaceMipUploadForm
from .models import Escola, EscolaItemRelatorioEaceMip, PlanilhaRelatorioEaceMip
from .services import (
    RelatorioEaceMipSincronizacaoError,
    _resolver_lado_ixc,
    _valor_servico,
    _valor_total_itens,
    sincronizar_relatorio_eace_mip_de_todas_as_escolas,
)

# Mesmo tamanho de página do histórico do RI (`apps.ri.views.
# HISTORICO_ITENS_POR_PAGINA`) — o painel é o mesmo (`ri/_historico_
# panel.html`), reaproveitado aqui sem importar o módulo de views do RI só
# por essa constante.
HISTORICO_ITENS_POR_PAGINA = 10


@login_required
def mip_inep_view(request):
    """Projeto > MIP: visão dos INEPs (Escola) cujo RI atual está em
    "Aguardando validação EACE" — INEP, nome, Estado, Município e Valor
    Total dos Lados IXC/EACE (RN-076/RN-077 abaixo; RN-078 abaixo troca a
    coluna Endereço por Estado/Município separados) — com drill-down dos
    mesmos 2 primeiros lados do RI (Kit declarado EACE e IXC; RiItemEace/
    RiItemIxc), só de leitura (editar status/RI continua em Projeto >
    Equipamentos, `ri.views.grid_inep_view`). Diferença combinada com o
    usuário: os valores mostrados são o Valor de serviço (`KitPadrao.
    valor_servico`), não o Valor de equipamento (`KitPadrao.
    valor_faturavel`) usado no RI.

    RN-076 (a criar): coluna "Valor Total (IXC)" no lugar da coluna Lote
    (usuário pediu pra tirar Lote e colocar o valor total do INEP) — soma
    quantidade × Valor de serviço de cada item do Lado IXC (2º) daquele
    INEP (`_valor_total_itens`, abaixo). Não usa o Lado 1 (Kit declarado)
    — só o Lado IXC, como pedido.

    RN-077 (a criar): coluna "Valor Total (EACE)", na sequência da
    RN-076 — mesma soma (`_valor_total_itens`), agora sobre o Lado 3
    (Relatório EACE, `EscolaItemRelatorioEaceMip`). Quando os dois totais
    (IXC e EACE) são conhecidos e diferem, o valor do Lado EACE aparece em
    amarelo (decidido pelo template) — sem um dos dois lados ter total
    ainda, não há o que comparar.

    RN-078 (a criar): coluna Endereço removida do grid (usuário pediu) —
    no lugar dela, Estado e Município separados (mesmos campos que já
    apareciam juntos na coluna Município/UF, removida também pra não
    duplicar o dado). Puramente de template, sem cálculo novo — usa
    `Escola.estado`/`Escola.municipio` direto.

    RN-079 (a criar): filtros Estado (`?estado=`) e Município
    (`?municipio=`), ambos do tipo lista (`<select>`) — pedido explícito
    do usuário. Estado só lista as UFs que já têm pelo menos 1 INEP na
    base do grid (Validação EACE, RN-074); um valor fora dessa lista (URL
    montada à mão) é ignorado, sem erro. Município só é filtrável depois
    de um Estado escolhido — sem Estado selecionado, o filtro de
    Município é sempre ignorado, mesmo vindo na URL — e lista só os
    municípios daquele Estado dentro da mesma base. Mesmo padrão de
    filtro por `<select>` + botão "Filtrar" já usado no Grid de
    Equipamentos (`ri.views.grid_inep_view`, "Status de conexão"/"Status
    do RI") — sem auto-envio ao trocar: o usuário escolhe o Estado,
    clica em "Filtrar", e só então o Município daquele Estado fica
    disponível pra escolher.

    RN-080 (a criar): linha de total geral abaixo do grid — soma "Valor
    Total (IXC)" e "Valor Total (EACE)" (RN-076/RN-077) de todos os INEPs
    que passaram pelos filtros já aplicados (busca, data, Estado/
    Município, divergência, período), não só da página atual. Pedido
    explícito do usuário: os totais têm que "refletir os filtros" — por
    isso são somados sobre `linhas` já filtrada, antes da paginação.

    RN-081 (a criar): bolinha verde/vermelha no grid, pedida pelo
    usuário, sobre o resultado da última vez que "Sincronizar todos os
    INEPs" rodou (`sincronizar_relatorio_eace_mip_de_todas_as_escolas`,
    `Escola.encontrado_relatorio_eace_mip`) — não recalculada ao vivo só
    por abrir a tela. Verde: o INEP apareceu na planilha da última
    sincronização (e está normalmente na lista, RN-074). Vermelho: duas
    situações — (a) o INEP está na lista (RI em "Aguardando validação
    EACE") mas NÃO apareceu na última sincronização; (b) o INEP apareceu
    na última sincronização mas a Escola NÃO está em "Aguardando
    validação EACE" — esse 2º caso vira uma linha própria, numa lista à
    parte abaixo do grid principal (`escolas_fora_da_validacao_eace`),
    porque não é uma linha normal do grid (RN-074) e mesmo assim precisa
    aparecer, sinalizada. Sem nenhuma sincronização ainda
    (`encontrado_relatorio_eace_mip is None`), não mostra bolinha
    nenhuma — nunca assume um resultado que não existe (CLAUDE.md §9).

    RN-074 (a criar): usuário pediu para a lista deixar de mostrar todos
    os INEPs cadastrados (RN-066) e passar a mostrar só os que estão na
    etapa "Aguardando validação EACE" do RI — esse status é do RI
    (`Ri.status`), não da Escola. "RI atual" segue o mesmo critério já
    usado pelas RN-068/RN-072 (o mais recente por `criado_em`); sem RI
    ainda, ou com RI em qualquer outro status, o INEP não aparece nesta
    lista (mas continua acessível direto por `/mip/<inep>/`,
    `mip_detail_view`, que não tem esse filtro). Filtro resolvido no
    banco (Subquery pelo status do RI mais recente por Escola) para não
    carregar/paginar em memória as milhares de Escolas que nunca
    apareceriam na lista.

    3º lado (Relatório EACE) vem de `EscolaItemRelatorioEaceMip`, lançado
    pelo Sincronizador da planilha do MIP (RN-069/RN-070, "Administrador
    > Relatório EACE (MIP)") — tabela própria, independente do Lado 3 do
    RI (RN-067).

    RN-071: confronto de Valor de serviço entre o Lado IXC (2º) e o Lado
    Relatório EACE do MIP (3º) — usuário pediu "o mesmo card de
    divergente que tem na RI". Como a divergência é calculada em memória
    (não é campo do banco), a paginação segue o mesmo padrão já usado
    pelo Grid de Equipamentos (`ri.views.grid_inep_view`, RN-003): pagina
    a lista `linhas` já filtrada, não o queryset de `Escola`.

    RN-073 (a criar): card "No período" — resolve a pendência de uso do
    período (Data inicial/Data final) do Relatório EACE do MIP (RN-069,
    editado à parte do upload desde a mudança pedida pelo usuário): conta
    os INEPs com pelo menos um item do Lado 3 (`EscolaItemRelatorioEaceMip`,
    RN-070) cuja Data Emissão ACS cai dentro do período da planilha ativa
    — mesmo padrão de card/filtro do "Com divergência" (RN-071). Sem
    planilha ativa ou sem período definido ainda, não há o que comparar:
    o card não aparece (decidido pelo template) e o filtro `?periodo=1`
    é ignorado. Não confundir com o filtro de data da RN-075 abaixo — são
    períodos de coisas diferentes (Data Emissão ACS da planilha × data em
    que o RI entrou em "Aguardando validação EACE").

    RN-075 (a criar): filtro por Data inicial/Data final (`?data_inicial=`/
    `?data_final=`, formato ISO) da data em que o RI atual **entrou** em
    "Aguardando validação EACE" — não a data de criação do RI nem
    qualquer outra. Essa data vem do log automático de mudança de status
    (`RiHistorico`, tipo `LOG_STATUS`, gravado por
    `apps.ri.services.trocar_status_com_log` toda vez que o status muda,
    manual ou automaticamente); usa sempre a entrada mais recente cujo
    `valor_novo` é o rótulo desse status — se o RI saiu e voltou a entrar
    em "Aguardando validação EACE" mais de uma vez, a(s) entrada(s)
    antiga(s) são ignoradas (pedido explícito do usuário). RI sem essa
    entrada registrada (não deveria acontecer em uso normal, já que toda
    transição passa por `trocar_status_com_log`) não casa com nenhuma
    data — some da lista assim que um dos dois filtros é preenchido, para
    não arriscar mostrar (ou esconder) um INEP fora do período por falta
    de dado (CLAUDE.md §9). Filtro também resolvido no banco (Subquery
    correlacionada ao RI atual já calculado abaixo), sem novo N+1.
    """
    q = (request.GET.get("q") or "").strip()
    divergencia_filtro = (request.GET.get("divergencia") or "").strip() == "1"
    data_inicial_validacao = _parse_data_filtro(request.GET.get("data_inicial"))
    data_final_validacao = _parse_data_filtro(request.GET.get("data_final"))
    if data_inicial_validacao and data_final_validacao and data_inicial_validacao > data_final_validacao:
        messages.error(request, "A data inicial não pode ser depois da data final — filtro de data ignorado.")
        data_inicial_validacao = None
        data_final_validacao = None

    planilha_ativa = PlanilhaRelatorioEaceMip.ativa()
    periodo_definido = bool(planilha_ativa and planilha_ativa.data_inicial and planilha_ativa.data_final)
    periodo_filtro = periodo_definido and (request.GET.get("periodo") or "").strip() == "1"
    escolas_no_periodo_ids = set()
    if periodo_definido:
        escolas_no_periodo_ids = set(
            EscolaItemRelatorioEaceMip.objects.filter(
                data_emissao_acs__range=(planilha_ativa.data_inicial, planilha_ativa.data_final)
            ).values_list("escola_id", flat=True)
        )

    ri_atual_qs = Ri.objects.filter(escola=OuterRef("pk")).order_by("-criado_em")
    escolas = Escola.objects.annotate(
        status_ri_atual=Subquery(ri_atual_qs.values("status")[:1]),
        ri_atual_id=Subquery(ri_atual_qs.values("pk")[:1]),
    ).filter(status_ri_atual=Ri.AGUARDANDO_VALIDACAO_EACE)

    # RN-079 (a criar): opções do filtro Estado — só os estados que já
    # têm pelo menos 1 INEP na base do grid ("Validação EACE"), calculado
    # antes de qualquer outro filtro (busca, data, o próprio Estado) —
    # pedido do usuário, pra lista não encolher enquanto ele ainda está
    # escolhendo. Município só é filtrável depois de um Estado escolhido
    # (também pedido do usuário) — lista vem só dos municípios daquele
    # Estado, na mesma base.
    estado_filtro = (request.GET.get("estado") or "").strip()
    municipio_filtro = (request.GET.get("municipio") or "").strip()
    estados_disponiveis = list(
        escolas.exclude(estado="").order_by("estado").values_list("estado", flat=True).distinct()
    )
    if estado_filtro not in estados_disponiveis:
        estado_filtro = ""
    municipios_disponiveis = []
    if estado_filtro:
        municipios_disponiveis = list(
            escolas.filter(estado=estado_filtro)
            .exclude(municipio="")
            .order_by("municipio")
            .values_list("municipio", flat=True)
            .distinct()
        )
    if municipio_filtro not in municipios_disponiveis:
        municipio_filtro = ""
    if estado_filtro:
        escolas = escolas.filter(estado=estado_filtro)
        if municipio_filtro:
            escolas = escolas.filter(municipio=municipio_filtro)

    if data_inicial_validacao or data_final_validacao:
        # RN-075 (a criar): entrada mais recente do log de status
        # (`RiHistorico`) que marcou o RI atual como "Aguardando
        # validação EACE" — ignora entradas antigas de uma eventual
        # entrada/saída anterior desse mesmo status.
        rotulo_validacao_eace = dict(Ri.STATUS_CHOICES)[Ri.AGUARDANDO_VALIDACAO_EACE]
        data_entrada_validacao_eace = Subquery(
            RiHistorico.objects.filter(
                ri_id=OuterRef("ri_atual_id"),
                tipo=RiHistorico.LOG_STATUS,
                valor_novo=rotulo_validacao_eace,
            ).order_by("-criado_em").values("criado_em")[:1],
            output_field=DateTimeField(),
        )
        escolas = escolas.annotate(data_entrada_validacao_eace=data_entrada_validacao_eace)
        if data_inicial_validacao:
            escolas = escolas.filter(data_entrada_validacao_eace__date__gte=data_inicial_validacao)
        if data_final_validacao:
            escolas = escolas.filter(data_entrada_validacao_eace__date__lte=data_final_validacao)

    escolas = escolas.order_by("nome")
    if q:
        escolas = escolas.filter(
            Q(inep__icontains=q)
            | Q(nome__icontains=q)
            | Q(municipio__icontains=q)
            | Q(estado__icontains=q)
        )
    total_inep = escolas.count()

    escolas = escolas.prefetch_related(
        Prefetch(
            "ris",
            queryset=Ri.objects.order_by("-criado_em").prefetch_related("itens_eace", "itens_ixc"),
        ),
        "itens_relatorio_eace_mip",
    )

    # Catálogo carregado uma única vez (fora do loop) para resolver o
    # Valor de serviço de cada item em memória — evita 1 consulta por
    # item (mesmo padrão do Grid de Equipamentos, RN-010).
    catalogo_kits = list(KitPadrao.objects.all())

    linhas = []
    total_divergencia = 0
    total_periodo = 0
    for escola in escolas:
        ris_da_escola = list(escola.ris.all())
        ri_atual = ris_da_escola[0] if ris_da_escola else None
        divergencia = _comparar_valor_servico_ixc_relatorio_mip(ri_atual, escola, escola.lote, catalogo_kits)
        if divergencia["diverge"]:
            total_divergencia += 1
        no_periodo = escola.pk in escolas_no_periodo_ids
        if no_periodo:
            total_periodo += 1
        # Cards "Com divergência" e "No período" viram filtro (mesmo
        # padrão do RN-003 no Grid de Equipamentos) — checados depois de
        # contar os totais, para os cards continuarem mostrando o total
        # mesmo com algum filtro já ativo.
        if divergencia_filtro and not divergencia["diverge"]:
            continue
        if periodo_filtro and not no_periodo:
            continue
        # RN-081 (a criar): bolinha verde/vermelha — reflete só o
        # resultado da última vez que "Sincronizar todos os INEPs" rodou
        # (`Escola.encontrado_relatorio_eace_mip`), nunca recalculada s
        # ó por abrir a tela. `None` (nenhuma sincronização ainda) não
        # mostra bolinha nenhuma.
        if escola.encontrado_relatorio_eace_mip is None:
            status_planilha_mip = None
        elif escola.encontrado_relatorio_eace_mip:
            status_planilha_mip = "verde"
        else:
            status_planilha_mip = "vermelho"
        lado2_ixc = _resolver_lado_ixc(ri_atual, escola.lote, catalogo_kits)
        lado3_relatorio_eace_mip = _resolver_lado3_relatorio_eace_mip(escola)
        valor_total_lado2, valor_total_lado2_incompleto = _valor_total_itens(lado2_ixc)
        valor_total_lado3, valor_total_lado3_incompleto = _valor_total_itens(lado3_relatorio_eace_mip)
        # RN-077 (a criar): destaque em amarelo do valor do Lado 3 quando
        # os dois totais são conhecidos e diferem — sem um dos dois lados
        # ter total (nenhum item lançado ainda), não há o que comparar
        # (mesmo critério da RN-003/RN-071 pra divergência item a item).
        valor_total_diverge = (
            valor_total_lado2 is not None
            and valor_total_lado3 is not None
            and valor_total_lado2 != valor_total_lado3
        )
        linhas.append(
            {
                "escola": escola,
                "lado1_kit_declarado": _resolver_lado_kit_declarado(escola, ri_atual, catalogo_kits),
                "lado2_ixc": lado2_ixc,
                "lado3_relatorio_eace_mip": lado3_relatorio_eace_mip,
                "valor_total_lado2": valor_total_lado2,
                "valor_total_lado2_incompleto": valor_total_lado2_incompleto,
                "valor_total_lado3": valor_total_lado3,
                "valor_total_lado3_incompleto": valor_total_lado3_incompleto,
                "valor_total_diverge": valor_total_diverge,
                "status_planilha_mip": status_planilha_mip,
                "divergencia_aberta": divergencia["diverge"],
                "itens_ixc_divergentes_pks": divergencia["itens_ixc_divergentes_pks"],
                "itens_mip_divergentes_pks": divergencia["itens_mip_divergentes_pks"],
            }
        )

    # RN-080 (a criar): linha de total geral abaixo do grid, somando
    # "Valor Total (IXC)" e "Valor Total (EACE)" de todos os INEPs que
    # passaram pelos filtros já aplicados acima (busca, data, Estado/
    # Município, divergência, período) — não só da página atual
    # (`linhas` ainda não foi paginado aqui). Usuário pediu
    # explicitamente que os totais "reflitam os filtros".
    total_geral_lado2 = sum(
        (linha["valor_total_lado2"] for linha in linhas if linha["valor_total_lado2"] is not None), Decimal("0.00")
    )
    total_geral_lado2_incompleto = any(linha["valor_total_lado2_incompleto"] for linha in linhas)
    total_geral_lado3 = sum(
        (linha["valor_total_lado3"] for linha in linhas if linha["valor_total_lado3"] is not None), Decimal("0.00")
    )
    total_geral_lado3_incompleto = any(linha["valor_total_lado3_incompleto"] for linha in linhas)

    # RN-081 (a criar): INEPs encontrados na última sincronização do
    # Relatório EACE (MIP), mas cuja Escola não está em "Aguardando
    # validação EACE" — não são linha normal do grid (RN-074), mas o
    # usuário pediu pra sinalizar esse descompasso mesmo assim: aparecem
    # à parte, sempre em vermelho. Só a busca (`q`) filtra essa lista —
    # Estado/Município não, porque o `<select>` de Estado (RN-079) só
    # oferece as UFs da base Validação EACE, e essas escolas por
    # definição estão fora dela (poderiam ter um Estado nem listado no
    # `<select>`); divergência/período/data de entrada em Validação EACE
    # também não fazem sentido pra quem nunca chegou nesse status.
    # `.exclude(status_ri_atual=...)` sozinho excluiria também quem nunca
    # teve RI nenhum (`status_ri_atual` NULL) — três-valores do SQL faz
    # `NOT (NULL = 'x')` virar NULL, tratado como falso pelo WHERE; por
    # isso o "OR ... isnull" explícito abaixo, pra incluir esse caso.
    escolas_fora_da_validacao_eace = Escola.objects.annotate(
        status_ri_atual=Subquery(ri_atual_qs.values("status")[:1])
    ).filter(encontrado_relatorio_eace_mip=True).filter(
        Q(status_ri_atual__isnull=True) | ~Q(status_ri_atual=Ri.AGUARDANDO_VALIDACAO_EACE)
    )
    if q:
        escolas_fora_da_validacao_eace = escolas_fora_da_validacao_eace.filter(
            Q(inep__icontains=q)
            | Q(nome__icontains=q)
            | Q(municipio__icontains=q)
            | Q(estado__icontains=q)
        )
    escolas_fora_da_validacao_eace = list(escolas_fora_da_validacao_eace.order_by("nome"))

    paginator = Paginator(linhas, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "escolas/mip_inep.html",
        {
            "page_obj": page_obj,
            "total_inep": total_inep,
            "total_divergencia": total_divergencia,
            "divergencia_filtro": divergencia_filtro,
            "planilha_ativa": planilha_ativa,
            "total_periodo": total_periodo,
            "periodo_filtro": periodo_filtro,
            "data_inicial_validacao": data_inicial_validacao,
            "data_final_validacao": data_final_validacao,
            "estado_filtro": estado_filtro,
            "estados_disponiveis": estados_disponiveis,
            "municipio_filtro": municipio_filtro,
            "municipios_disponiveis": municipios_disponiveis,
            "total_geral_lado2": total_geral_lado2,
            "total_geral_lado2_incompleto": total_geral_lado2_incompleto,
            "total_geral_lado3": total_geral_lado3,
            "total_geral_lado3_incompleto": total_geral_lado3_incompleto,
            "escolas_fora_da_validacao_eace": escolas_fora_da_validacao_eace,
            "q": q,
        },
    )


@login_required
def mip_detail_view(request, inep):
    """Tela aberta ao clicar em qualquer card do MIP — mesma estrutura de
    3 lados da tela do RI (`ri_detail`), só que 100% leitura: Kit
    declarado (1º), IXC (2º) e Relatório EACE (3º, `EscolaItemRelatorio
    EaceMip`), mais o histórico de comunicação do RI atual daquele INEP
    logo abaixo. Reaproveita o histórico do RI
    (`RiHistorico`/`ri/_historico_panel.html`) em vez de um histórico
    próprio do MIP — o formulário de nova mensagem do painel posta direto
    para `ri_detail` (mesmo endpoint que o RI já usa), então as duas
    telas leem e escrevem o mesmo histórico daquele RI (decisão combinada
    com o usuário, 2026-09-07). Sem RI ainda para o INEP, não há onde
    gravar histórico — mostra só um aviso, sem o painel.
    """
    escola = get_object_or_404(Escola, inep=inep)
    ri = (
        Ri.objects.filter(escola=escola)
        .order_by("-criado_em")
        .prefetch_related("itens_eace", "itens_ixc")
        .first()
    )

    catalogo_kits = list(KitPadrao.objects.all())
    lado1_kit_declarado = _resolver_lado_kit_declarado(escola, ri, catalogo_kits)
    lado2_ixc = _resolver_lado_ixc(ri, escola.lote, catalogo_kits)
    lado3_relatorio_eace_mip = _resolver_lado3_relatorio_eace_mip(escola)
    divergencia_valor_servico = _comparar_valor_servico_ixc_relatorio_mip(ri, escola, escola.lote, catalogo_kits)
    lado2_nf_recebida_em = _resolver_lado2_nf_recebida_em(ri)

    historico_form = None
    historico_page_obj = None
    if ri:
        historico_form = RiHistoricoForm()
        historico_paginator = Paginator(
            ri.historico.select_related("autor").prefetch_related("documentos"),
            HISTORICO_ITENS_POR_PAGINA,
        )
        historico_page_obj = historico_paginator.get_page(request.GET.get("historico_page"))

    return render(
        request,
        "escolas/mip_detail.html",
        {
            "escola": escola,
            "ri": ri,
            "lado1_kit_declarado": lado1_kit_declarado,
            "lado2_ixc": lado2_ixc,
            "lado3_relatorio_eace_mip": lado3_relatorio_eace_mip,
            "divergencia_valor_servico": divergencia_valor_servico,
            "lado2_nf_recebida_em": lado2_nf_recebida_em,
            "historico_form": historico_form,
            "historico": historico_page_obj,
        },
    )


@login_required
def relatorio_eace_mip_view(request):
    """FEAT-034/FEAT-035: tela "Administrador > Relatório EACE (MIP)" —
    upload da planilha de origem do Lado 3 (Relatório EACE) do MIP.
    Mesmo padrão de arquivo único da Planilha EACE do RI (`apps.ri.views.
    planilha_eace_view`), em tela própria para não misturar com a
    planilha do RI. Ação restrita a Administrador, mesmo critério das
    demais ações administrativas (RN-004).

    RN-069 alterada (usuário pediu): o período (Data inicial/Data final)
    deixou de ser exigido no upload — agora é editado à parte, direto no
    card "Arquivo ativo" (Sincronizador), sem precisar reimportar o
    arquivo só para ajustar a data. Os dois formulários postam pra esta
    mesma view/URL, diferenciados pelo campo oculto `acao`."""
    if not request.user.is_administrador:
        return HttpResponseForbidden("Somente Administrador pode acessar esta tela.")

    planilha_ativa = PlanilhaRelatorioEaceMip.ativa()
    periodo_inicial = {
        "data_inicial": planilha_ativa.data_inicial if planilha_ativa else None,
        "data_final": planilha_ativa.data_final if planilha_ativa else None,
    }

    if request.method == "POST" and request.POST.get("acao") == "definir_periodo":
        upload_form = PlanilhaRelatorioEaceMipUploadForm()
        if not planilha_ativa:
            messages.error(request, "Nenhum Relatório EACE (MIP) ativo para definir o período.")
            return redirect("relatorio_eace_mip")
        periodo_form = PlanilhaRelatorioEaceMipPeriodoForm(request.POST)
        if periodo_form.is_valid():
            planilha_ativa.definir_periodo(
                periodo_form.cleaned_data["data_inicial"],
                periodo_form.cleaned_data["data_final"],
            )
            messages.success(request, "Período do Relatório EACE (MIP) atualizado com sucesso.")
            return redirect("relatorio_eace_mip")
        mensagens_erro = [erro for erros in periodo_form.errors.values() for erro in erros]
        messages.error(request, "Não foi possível salvar o período: " + " ".join(mensagens_erro))
    elif request.method == "POST":
        periodo_form = PlanilhaRelatorioEaceMipPeriodoForm(initial=periodo_inicial)
        upload_form = PlanilhaRelatorioEaceMipUploadForm(request.POST, request.FILES)
        if upload_form.is_valid():
            PlanilhaRelatorioEaceMip.substituir(upload_form.cleaned_data["arquivo"], request.user)
            messages.success(request, "Relatório EACE (MIP) importado com sucesso.")
            return redirect("relatorio_eace_mip")
        mensagens_erro = [erro for erros in upload_form.errors.values() for erro in erros]
        messages.error(request, "Não foi possível importar: " + " ".join(mensagens_erro))
    else:
        upload_form = PlanilhaRelatorioEaceMipUploadForm()
        periodo_form = PlanilhaRelatorioEaceMipPeriodoForm(initial=periodo_inicial)

    return render(request, "escolas/relatorio_eace_mip.html", {
        "form": upload_form,
        "periodo_form": periodo_form,
        "planilha_ativa": planilha_ativa,
    })


@login_required
def relatorio_eace_mip_sincronizar_todas_view(request):
    """Botão "Sincronizar todos os INEPs" do card "Arquivo ativo" —
    usuário pediu "as mesmas regras de sincronização do RI": aplica
    `sincronizar_relatorio_eace_mip_de_todas_as_escolas` (RN-070) ao
    arquivo ativo (RN-069), lançando os itens do Lado 3 do MIP por
    Escola. Ação restrita a Administrador, mesmo critério da tela
    (RN-004)."""
    if not request.user.is_administrador:
        return HttpResponseForbidden("Somente Administrador pode acessar esta tela.")
    if request.method != "POST":
        return redirect("relatorio_eace_mip")

    try:
        resultado = sincronizar_relatorio_eace_mip_de_todas_as_escolas()
    except RelatorioEaceMipSincronizacaoError as erro:
        messages.error(request, str(erro))
        return redirect("relatorio_eace_mip")

    messages.success(
        request,
        f"Sincronização em lote: {resultado['escolas_atualizadas']} INEP(s) atualizado(s).",
    )
    return redirect("relatorio_eace_mip")


def _resolver_lado3_relatorio_eace_mip(escola):
    """3º lado (Relatório EACE) do MIP — itens lançados pelo Sincronizador
    da planilha do MIP (RN-069/RN-070), por Escola; tabela própria
    (`EscolaItemRelatorioEaceMip`), independente do Lado 3 do RI
    (RN-067). `pk` incluído para o template destacar em vermelho o
    produto divergente do confronto com o Lado IXC
    (`itens_mip_divergentes_pks`, `_comparar_valor_servico_ixc_relatorio_mip`)."""
    return [
        {
            "pk": item.pk,
            "descricao": item.descricao_item,
            "quantidade": item.quantidade,
            "valor_servico": item.valor_servico,
        }
        for item in escola.itens_relatorio_eace_mip.all()
    ]


def _resolver_lado_kit_declarado(escola, ri, catalogo):
    """1º lado (Kit declarado EACE) — mesmos itens do RI (`RiItemEace`)
    quando já lançados; sem lançamento ainda, cai na mesma referência
    calculada ao vivo que o Grid de Equipamentos já usa (RN-010), a
    partir de `Escola.kit_inicial`. Este lado é sempre o Kit fechado (não
    existe produto avulso aqui, RN-010) — por isso cruza com o catálogo
    pelo número de Access Points, igual ao Lado IXC quando é o KIT
    Instalado (`eh_kit=True`)."""
    itens = list(ri.itens_eace.all()) if ri else []
    if itens:
        return [
            {
                "descricao": item.descricao_item,
                "quantidade": item.quantidade,
                "valor_servico": _valor_servico(item.descricao_item, True, escola.lote, catalogo),
            }
            for item in itens
        ]
    kit_resolvido = KitPadrao.resolver_kit_declarado(escola.kit_inicial, lote=escola.lote, catalogo=catalogo)
    if not kit_resolvido:
        return []
    return [
        {
            "descricao": kit_resolvido.descricao_curta or kit_resolvido.descricao,
            "quantidade": 1,
            "valor_servico": kit_resolvido.valor_servico,
            "referencia": True,
        }
    ]


def _resolver_lado2_nf_recebida_em(ri):
    """Data do recebimento do e-mail do financeiro com a Nota Fiscal (PDF +
    XML, RF-08) mais recente do RI atual — pedido do usuário para aparecer
    junto do Lado 2 (IXC) do MIP. `Documento.recebido_em` é gravado no
    instante em que cada arquivo daquela resposta é salvo (`apps.ri.
    services._salvar_documento`); um RI com mais de uma Nota Fiscal usa só
    a mais recente (decisão combinada com o usuário, 2026-09-07) — não uma
    lista por Nota Fiscal."""
    if not ri:
        return None
    return (
        Documento.objects.filter(ri=ri, recebido_em__isnull=False)
        .order_by("-recebido_em")
        .values_list("recebido_em", flat=True)
        .first()
    )


def _comparar_valor_servico_ixc_relatorio_mip(ri, escola, lote, catalogo):
    """RN-071 (a criar): confronto de **Valor de serviço** entre o Lado
    IXC (2º, `RiItemIxc` do RI atual) e o Lado Relatório EACE do MIP
    (3º, `EscolaItemRelatorioEaceMip`) — usuário pediu explicitamente
    "as mesmas regras" do confronto formal do RI (RN-003,
    `apps.ri.services.comparar_kit_e_produtos_ixc_relatorio`): KIT
    comparado isolado (no máximo 1 de cada lado), Produtos comparados
    como conjunto por Descrição. Diferença pedida: compara Valor de
    serviço — nunca Quantidade nem Valor de equipamento (RN-067) — já
    que os dois lados resolvem o mesmo valor a partir do catálogo
    `KitPadrao`; uma diferença aqui normalmente indica que o catálogo
    mudou depois da última sincronização do Lado 3 (RN-070). Sem os
    dois lados terem algum item, não há divergência (mesmo critério da
    RN-003, ajuste de 2026-09-02)."""
    itens_ixc = list(ri.itens_ixc.all()) if ri else []
    itens_mip = list(escola.itens_relatorio_eace_mip.all())
    if not itens_ixc or not itens_mip:
        return {
            "diverge": False,
            "kit_diverge": False,
            "produtos_divergentes": {},
            "itens_ixc_divergentes_pks": set(),
            "itens_mip_divergentes_pks": set(),
        }

    kit_ixc = next((item for item in itens_ixc if item.eh_kit), None)
    kit_mip = next((item for item in itens_mip if item.eh_kit), None)
    valor_kit_ixc = _valor_servico(kit_ixc.descricao_item, True, lote, catalogo) if kit_ixc else None
    valor_kit_mip = kit_mip.valor_servico if kit_mip else None
    kit_diverge = (kit_ixc is None) != (kit_mip is None) or bool(
        kit_ixc and kit_mip and valor_kit_ixc != valor_kit_mip
    )

    produtos_ixc = {
        item.descricao_item: _valor_servico(item.descricao_item, False, lote, catalogo)
        for item in itens_ixc if not item.eh_kit
    }
    produtos_mip = {item.descricao_item: item.valor_servico for item in itens_mip if not item.eh_kit}
    produtos_divergentes = {
        descricao: (produtos_ixc.get(descricao), produtos_mip.get(descricao))
        for descricao in set(produtos_ixc) | set(produtos_mip)
        if produtos_ixc.get(descricao) != produtos_mip.get(descricao)
    }

    itens_ixc_divergentes_pks = {
        item.pk
        for item in itens_ixc
        if (item.eh_kit and kit_diverge) or (not item.eh_kit and item.descricao_item in produtos_divergentes)
    }
    # Mesmo critério acima, mas para os itens do Lado 3 (Relatório EACE
    # do MIP) — usuário pediu para destacar em vermelho também o nome do
    # produto divergente desse lado, não só do Lado IXC.
    itens_mip_divergentes_pks = {
        item.pk
        for item in itens_mip
        if (item.eh_kit and kit_diverge) or (not item.eh_kit and item.descricao_item in produtos_divergentes)
    }

    return {
        "diverge": kit_diverge or bool(produtos_divergentes),
        "kit_diverge": kit_diverge,
        "produtos_divergentes": produtos_divergentes,
        "itens_ixc_divergentes_pks": itens_ixc_divergentes_pks,
        "itens_mip_divergentes_pks": itens_mip_divergentes_pks,
    }


def _parse_data_filtro(valor):
    """RN-075 (a criar): parser tolerante do `?data_inicial=`/`?data_final=`
    do filtro por data de entrada em "Aguardando validação EACE" —
    formato "dd/mm/aaaa", mesmo padrão usado no resto do sistema. Campo
    de texto com máscara (`data-mascara-data`, template), não `<input
    type="date">` nativo — usuário pediu pra tirar o placeholder "mm/dd/
    yyyy" desse widget, que segue o idioma/formato do navegador do
    usuário em vez do da página. Valor ausente ou mal formado vira `None`
    (filtro simplesmente não aplicado), nunca erro 500."""
    valor = (valor or "").strip()
    if not valor:
        return None
    try:
        return datetime.datetime.strptime(valor, "%d/%m/%Y").date()
    except ValueError:
        return None
