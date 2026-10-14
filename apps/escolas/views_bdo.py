"""Tela "Projeto > BDO" (pedido do usuário, 2026-10-14): faturamento
mensal das manutenções de RI e RE, a partir da planilha FR_XXXX do
Boletim de desempenho. Cada Boletim é independente: o mesmo município
aparece uma vez em cada Boletim, nunca somado entre Boletins. Grid por
INEP (os valores são do município naquele Boletim, repetidos em cada INEP
dele) ou agrupado por Município/UF dentro de cada Boletim. Fora do
Visualizador: as rotas não estão na lista liberada do
`VisualizadorAccessMiddleware`. A importação fica em "Administrador >
Relatório BDO" (`relatorio_bdo_view`), só do Administrador, mesmo critério
das demais importações (RN-004)."""

from collections import defaultdict
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, DateField, OuterRef, Subquery, Sum
from django.db.models.functions import Upper
from django.http import HttpResponseForbidden, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.ri.models import KitPadrao, Ri

from .bdo import (
    COLUNAS_VALORES, PlanilhaBdoError, _normalizar, dias_no_mes_referencia, importar_planilha_bdo, valor_proporcional,
)
from .forms import MesReferenciaBdoForm, PlanilhaBdoUploadForm
from .models import BoletimBdo, Escola, InepBdo, MunicipioBdo
from .views import _parse_data_filtro

AGRUPAMENTOS = (("inep", "Por INEP"), ("municipio", "Por Município"), ("uf", "Por UF"))
LINHAS_POR_PAGINA = 50


def _somar(atual, valor):
    """Soma que fica vazia (`None`) se algum valor do grupo é vazio - só
    acontece no Boletim importado antes dos valores de composição."""
    return None if atual is None or valor is None else atual + valor


def _linhas_agrupadas(municipios, ineps, agrupar):
    """Agrupa por Município (nome sem diferença de maiúsculas + UF) ou por
    UF dentro de cada Boletim, somando os valores de cada linha da
    planilha uma vez só."""
    quantidade_ineps = defaultdict(int)
    for municipio_id in ineps.values_list("municipio_bdo_id", flat=True):
        quantidade_ineps[municipio_id] += 1

    grupos = {}
    for municipio in municipios.select_related("boletim"):
        nome = municipio.municipio.upper()
        numero = municipio.boletim.numero
        chave = (numero, municipio.uf, nome) if agrupar == "municipio" else (numero, municipio.uf)
        grupo = grupos.setdefault(chave, {
            "boletim": numero, "tipo": municipio.boletim.tipo, "uf": municipio.uf, "municipio": nome, "municipios": set(),
            "quantidade_ineps": 0, "municipio_ids": [], **{campo: Decimal("0") for campo in COLUNAS_VALORES},
        })
        grupo["municipios"].add(nome)
        grupo["municipio_ids"].append(municipio.pk)
        grupo["quantidade_ineps"] += quantidade_ineps[municipio.pk]
        for campo in COLUNAS_VALORES:
            grupo[campo] = _somar(grupo[campo], getattr(municipio, campo))

    linhas = sorted(grupos.values(), key=lambda grupo: (grupo["uf"], grupo["municipio"]))
    linhas.sort(key=lambda grupo: grupo["boletim"], reverse=True)
    for grupo in linhas:
        grupo["quantidade_municipios"] = len(grupo.pop("municipios"))
        grupo["valores_em_ordem"] = [grupo[campo] for campo in MunicipioBdo.CAMPOS_VALORES]
    return linhas


def _anotar_data_ativacao(linhas):
    """Pedido do usuário (2026-10-14): Data de Ativação (`Ri.data_ativacao`)
    do RI atual de cada INEP da página - a mesma no Boletim de RE, que não
    tem data própria. INEP sem RI no sistema fica vazio. Busca em Python,
    não por subquery: no MySQL a tabela do BDO tem collation diferente da
    `Escola` e o `=` entre as duas colunas dá erro 1267."""
    datas = {}
    ris = Ri.objects.filter(escola__inep__in={linha.inep for linha in linhas}).order_by("escola__inep", "-criado_em")
    for inep, data_ativacao in ris.values_list("escola__inep", "data_ativacao"):
        datas.setdefault(inep, data_ativacao)
    for linha in linhas:
        linha.data_ativacao = datas.get(linha.inep)
        linha.dias_proporcionais = dias_no_mes_referencia(linha.data_ativacao, linha.municipio_bdo.boletim.mes_referencia)
    _anotar_valor_assinatura(linhas)
    for linha in linhas:
        linha.valor_proporcional = valor_proporcional(linha.valor_assinatura, linha.dias_proporcionais)


def _anotar_total_howbe(grupos, ineps):
    """Pedido do usuário (2026-10-14): "Total Howbe" de cada município da
    página no agrupamento por Município - soma do valor proporcional dos
    INEPs dele no Boletim (os mesmos contados na coluna INEPs). É o valor
    bruto com o único desconto do lado Howbe, o de dias proporcionais, e
    por isso bate com Valor serviços - Valor descontos proporcionais da
    planilha, não com o Valor total (que tira também o Valor descontos).
    INEP sem valor proporcional fica fora da soma e é contado em
    `ineps_sem_valor_howbe`; sem nenhum, fica vazio."""
    por_municipio = {}
    for grupo in grupos:
        for municipio_id in grupo["municipio_ids"]:
            por_municipio[municipio_id] = grupo
        grupo["total_howbe"] = None
        grupo["ineps_sem_valor_howbe"] = 0
    linhas = list(
        ineps.filter(municipio_bdo_id__in=por_municipio).select_related("municipio_bdo__boletim")
    )
    _anotar_data_ativacao(linhas)
    for linha in linhas:
        grupo = por_municipio[linha.municipio_bdo_id]
        if linha.valor_proporcional is None:
            grupo["ineps_sem_valor_howbe"] += 1
        else:
            grupo["total_howbe"] = (grupo["total_howbe"] or Decimal("0")) + linha.valor_proporcional
    for grupo in grupos:
        servicos, proporcionais = grupo["valor_servicos"], grupo["valor_descontos_proporcionais"]
        grupo["valor_conferencia_howbe"] = None if servicos is None or proporcionais is None else servicos - proporcionais
        grupo["diferenca_howbe"] = (
            None if grupo["total_howbe"] is None or grupo["valor_conferencia_howbe"] is None
            else grupo["total_howbe"] - grupo["valor_conferencia_howbe"]
        )


def _anotar_valor_assinatura(linhas):
    """Pedido do usuário (2026-10-14), só conferência no grid: valor mensal
    do INEP conforme o tipo do Boletim - no RE a assinatura da escola
    (`Escola.valor_assinatura_re`), no RI a "Manutenção de Rede Interna" do
    LPU (`KitPadrao`) no Lote da escola. Vazio sem escola, sem valor, sem
    Lote ou em Boletim sem tipo. Busca em Python pelo mesmo motivo de
    collation de `_anotar_data_ativacao`."""
    escolas = {
        inep: (lote, assinatura_re) for inep, lote, assinatura_re in Escola.objects.filter(
            inep__in={linha.inep for linha in linhas},
        ).values_list("inep", "lote", "valor_assinatura_re")
    }
    manutencao_ri = dict(
        KitPadrao.objects.filter(descricao__istartswith="Manutenção de Rede Interna")
        .values_list("lote", "valor_servico")
    )
    for linha in linhas:
        lote, assinatura_re = escolas.get(linha.inep, (None, None))
        tipo = linha.municipio_bdo.boletim.tipo
        if tipo == BoletimBdo.TIPO_RE:
            linha.valor_assinatura = assinatura_re
        elif tipo == BoletimBdo.TIPO_RI:
            linha.valor_assinatura = manutencao_ri.get(lote) if lote else None
        else:
            linha.valor_assinatura = None


def _ineps_ativados_no_periodo(data_inicial, data_final):
    """INEPs cuja Data de Ativação do RI atual está no período (pedido do
    usuário, 2026-10-14). Devolve a lista de INEPs, não uma subquery: no
    MySQL a tabela do BDO tem collation diferente da `Escola` e o `=`
    entre as duas colunas dá erro 1267. RI sem Data de Ativação fica de
    fora, mesmo critério do filtro do MIP (RN-075)."""
    ri_atual = Ri.objects.filter(escola=OuterRef("pk")).order_by("-criado_em")
    escolas = Escola.objects.annotate(
        data_ativacao_ri_atual=Subquery(ri_atual.values("data_ativacao")[:1], output_field=DateField()),
    )
    if data_inicial:
        escolas = escolas.filter(data_ativacao_ri_atual__gte=data_inicial)
    if data_final:
        escolas = escolas.filter(data_ativacao_ri_atual__lte=data_final)
    return list(escolas.values_list("inep", flat=True))


@login_required
def bdo_view(request):
    boletins = list(BoletimBdo.objects.all())
    numero_filtro = (request.GET.get("boletim") or "").strip()
    boletim = next((b for b in boletins if b.numero == numero_filtro), None)

    agrupar = request.GET.get("agrupar") or "inep"
    if agrupar not in dict(AGRUPAMENTOS):
        agrupar = "inep"
    inep_filtro = (request.GET.get("inep") or "").strip()
    uf_filtro = (request.GET.get("uf") or "").strip().upper()
    municipio_filtro = (request.GET.get("municipio") or "").strip()
    data_inicial = _parse_data_filtro(request.GET.get("data_inicial"))
    data_final = _parse_data_filtro(request.GET.get("data_final"))
    if data_inicial and data_final and data_inicial > data_final:
        messages.error(request, "A data inicial não pode ser depois da data final — filtro de data ignorado.")
        data_inicial = data_final = None
    contexto = {
        "boletins": boletins,
        "boletim": boletim,
        "agrupar": agrupar,
        "agrupamentos": AGRUPAMENTOS,
        "inep_filtro": inep_filtro,
        "uf_filtro": uf_filtro,
        "municipio_filtro": municipio_filtro,
        "data_inicial": data_inicial,
        "data_final": data_final,
    }
    if not boletins:
        return render(request, "escolas/bdo.html", contexto)
    contexto.update(_contexto_recebiveis(QueryDict()))

    municipios = MunicipioBdo.objects.all()
    if boletim:
        municipios = municipios.filter(boletim=boletim)
    ufs = list(municipios.order_by("uf").values_list("uf", flat=True).distinct())
    if uf_filtro:
        municipios = municipios.filter(uf=uf_filtro)
    # Pedido do usuário (2026-10-14): lista só os municípios do grid no
    # Boletim e na UF escolhidos; nome sem diferença de maiúsculas.
    # Maiúsculas em Python: o UPPER do SQLite não converte acento.
    grafias = defaultdict(set)
    for nome in municipios.values_list("municipio", flat=True).distinct():
        grafias[nome.upper()].add(nome)
    nomes_municipios = sorted(grafias, key=_normalizar)
    municipio_filtro = municipio_filtro.upper()
    if municipio_filtro not in grafias:
        municipio_filtro = ""
    if municipio_filtro:
        municipios = municipios.filter(municipio__in=grafias[municipio_filtro])
    ineps = InepBdo.objects.filter(municipio_bdo__in=municipios)
    if inep_filtro:
        ineps = ineps.filter(inep__icontains=inep_filtro)
    if data_inicial or data_final:
        ineps = ineps.filter(inep__in=_ineps_ativados_no_periodo(data_inicial, data_final))
    if inep_filtro or data_inicial or data_final:
        municipios = municipios.filter(pk__in=ineps.values("municipio_bdo_id"))

    if agrupar == "inep":
        linhas = ineps.select_related("municipio_bdo__boletim").order_by(
            "-municipio_bdo__boletim__numero", "municipio_bdo__uf", Upper("municipio_bdo__municipio"), "inep",
        )
    else:
        linhas = _linhas_agrupadas(municipios, ineps, agrupar)

    page_obj = Paginator(linhas, LINHAS_POR_PAGINA).get_page(request.GET.get("page"))
    if agrupar == "inep":
        page_obj.object_list = list(page_obj.object_list)
        _anotar_data_ativacao(page_obj.object_list)
    elif agrupar == "municipio":
        _anotar_total_howbe(page_obj.object_list, ineps)
    filtros = {
        chave: valor for chave, valor in (
            ("boletim", numero_filtro if boletim else ""), ("inep", inep_filtro),
            ("uf", uf_filtro), ("municipio", municipio_filtro),
            ("data_inicial", data_inicial.strftime("%d/%m/%Y") if data_inicial else ""),
            ("data_final", data_final.strftime("%d/%m/%Y") if data_final else ""),
        ) if valor
    }
    valor_total = municipios.aggregate(total=Sum("valor_total"))["total"] or Decimal("0")
    contexto.update({
        "page_obj": page_obj,
        "ufs": ufs,
        "nomes_municipios": nomes_municipios,
        "municipio_filtro": municipio_filtro,
        # Card "INEPs": cada INEP uma vez, mesmo repetido em mais de um
        # Boletim (pedido do usuário, 2026-10-14) - o grid continua com
        # uma linha por INEP em cada Boletim.
        "total_ineps": ineps.values("inep").distinct().count(),
        "total_municipios": municipios.values("boletim_id", "uf", nome=Upper("municipio")).distinct().count(),
        "total_boletins": municipios.values("boletim_id").distinct().count(),
        "valor_total": valor_total.quantize(Decimal("0.01")),
        "filtros_ativos": bool(boletim or inep_filtro or uf_filtro or municipio_filtro or data_inicial or data_final),
        "querystring_filtros": urlencode(filtros),
        "querystring_paginacao": urlencode({**filtros, "agrupar": agrupar}),
    })
    return render(request, "escolas/bdo.html", contexto)


@login_required
def relatorio_bdo_view(request):
    """Tela "Administrador > Relatório BDO" (pedido do usuário, 2026-10-14):
    importação da planilha FR_XXXX, mesmo layout das demais importações
    (`relatorio_eace_mip_view`). Lista os Boletins já importados - cada um
    independente, um número repetido é recusado."""
    if not request.user.is_administrador:
        return HttpResponseForbidden("Somente Administrador pode acessar esta tela.")

    if request.method == "POST":
        form = PlanilhaBdoUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                gravados = importar_planilha_bdo(
                    form.cleaned_data["boletins"], form.cleaned_data["tipo"], form.cleaned_data["arquivo"].name,
                    request.user, form.cleaned_data["mes_referencia"],
                )
            except PlanilhaBdoError as erro:
                messages.error(request, f"Não foi possível importar: {erro}")
                return redirect("relatorio_bdo")
            for boletim in gravados:
                messages.success(
                    request,
                    f"Boletim {boletim.numero} ({boletim.tipo}) importado: {boletim.municipios.count()} município(s), "
                    f"{InepBdo.objects.filter(municipio_bdo__boletim=boletim).count()} INEP(s).",
                )
            return redirect("relatorio_bdo")
        mensagens_erro = [erro for erros in form.errors.values() for erro in erros]
        messages.error(request, "Não foi possível importar: " + " ".join(mensagens_erro))
    else:
        form = PlanilhaBdoUploadForm()

    tipo_filtro = (request.GET.get("tipo") or "").strip().upper()
    if tipo_filtro not in dict(BoletimBdo.TIPO_CHOICES):
        tipo_filtro = ""
    boletins = BoletimBdo.objects.select_related("importado_por").annotate(
        quantidade_municipios=Count("municipios", distinct=True),
        quantidade_ineps=Count("municipios__ineps"),
    )
    if tipo_filtro:
        boletins = boletins.filter(tipo=tipo_filtro)
    boletins = list(boletins)
    valores = dict(
        MunicipioBdo.objects.filter(boletim__in=boletins)
        .values("boletim_id").annotate(total=Sum("valor_total")).values_list("boletim_id", "total")
    )
    for boletim in boletins:
        boletim.valor_total = (valores.get(boletim.pk) or Decimal("0")).quantize(Decimal("0.01"))

    return render(request, "escolas/relatorio_bdo.html", {
        "form": form,
        "boletins": boletins,
        "tipo_filtro": tipo_filtro,
        "tipos": BoletimBdo.TIPO_CHOICES,
    })


@login_required
@require_POST
def bdo_mes_referencia_view(request, pk):
    """Grava o mês de referência de um Boletim já importado (pedido do
    usuário, 2026-10-14). Só Administrador, como a importação."""
    if not request.user.is_administrador:
        return HttpResponseForbidden("Somente Administrador pode alterar o Boletim.")
    boletim = get_object_or_404(BoletimBdo, pk=pk)
    form = MesReferenciaBdoForm(request.POST)
    if form.is_valid():
        boletim.mes_referencia = form.cleaned_data["mes_referencia"].replace(day=1)
        boletim.save(update_fields=["mes_referencia"])
        messages.success(request, f"Boletim {boletim.numero}: mês de referência {boletim.mes_referencia:%m/%Y}.")
    else:
        mensagens_erro = [erro for erros in form.errors.values() for erro in erros]
        messages.error(request, f"Boletim {boletim.numero}: " + " ".join(mensagens_erro))
    return redirect("relatorio_bdo")


VISOES_RECEBIVEIS = (("linhas", "Linhas"), ("municipio", "Por Município"), ("boletim", "Por Boletim"))


def _ids(valores):
    """Ids de `MunicipioBdo` vindos do formulário, um por campo ou vários
    separados por vírgula (botão "Retirar" de um município agrupado)."""
    ids = set()
    for valor in valores:
        ids.update(int(parte) for parte in valor.split(",") if parte.strip().isdigit())
    return ids


def _contexto_recebiveis(dados):
    """Pedido do usuário (2026-10-14): modal "Recebíveis" da tela BDO, só
    montagem e conferência - nada é gravado. Escolhe um ou mais Boletins,
    traz as linhas da planilha deles e deixa retirar por município, nunca
    por INEP: os valores são do município. Cada linha da planilha é
    independente - município repetido no Boletim já vem rateado pelo
    cliente - e "Retirar" age só nela (ou em todas as do grupo, na visão
    "Por Município"). Os Boletins continuam independentes: o agrupamento
    por município é dentro de cada Boletim. O estado (Boletins, retirados,
    visão) vai e volta no próprio formulário do modal."""
    boletins = list(BoletimBdo.objects.all())
    numeros = set(dados.getlist("boletim"))
    selecionados = [boletim for boletim in boletins if boletim.numero in numeros]
    visao = dados.get("visao") or "linhas"
    if visao not in dict(VISOES_RECEBIVEIS):
        visao = "linhas"

    retirados = _ids(dados.getlist("retirado")) | _ids(dados.getlist("retirar"))
    restaurar = dados.getlist("restaurar")
    retirados = set() if "todos" in restaurar else retirados - _ids(restaurar)

    municipios = list(
        MunicipioBdo.objects.filter(boletim__in=selecionados).select_related("boletim")
        .annotate(quantidade_ineps=Count("ineps")).order_by("-boletim__numero", "uf", Upper("municipio"), "pk")
    )
    ineps = defaultdict(list)
    for municipio_id, inep in InepBdo.objects.filter(municipio_bdo__in=municipios).values_list("municipio_bdo_id", "inep"):
        ineps[municipio_id].append(inep)
    for municipio in municipios:
        municipio.lista_ineps = ineps[municipio.pk]
    retirados &= {municipio.pk for municipio in municipios}
    mantidos = [municipio for municipio in municipios if municipio.pk not in retirados]

    agrupados = {}
    for municipio in mantidos:
        chave = (municipio.boletim.numero, municipio.uf, municipio.municipio.upper())
        if visao == "boletim":
            chave = chave[:1]
        grupo = agrupados.setdefault(chave, {
            "boletim": municipio.boletim, "uf": municipio.uf, "municipio": municipio.municipio.upper(),
            "ids": [], "nomes": set(), "linhas": 0, "quantidade_ineps": 0, "valor_total": Decimal("0"),
        })
        grupo["ids"].append(str(municipio.pk))
        grupo["nomes"].add((municipio.uf, municipio.municipio.upper()))
        grupo["linhas"] += 1
        grupo["quantidade_ineps"] += municipio.quantidade_ineps
        grupo["valor_total"] += municipio.valor_total
    for grupo in agrupados.values():
        grupo["ids"] = ",".join(grupo.pop("ids"))
        grupo["quantidade_municipios"] = len(grupo.pop("nomes"))

    return {
        "recebiveis_boletins": boletins,
        "recebiveis_selecionados": {boletim.numero for boletim in selecionados},
        "recebiveis_visao": visao,
        "recebiveis_visoes": VISOES_RECEBIVEIS,
        "recebiveis_linhas": mantidos,
        "recebiveis_grupos": list(agrupados.values()),
        "recebiveis_retirados": [municipio for municipio in municipios if municipio.pk in retirados],
        "recebiveis_quantidade_ineps": sum(municipio.quantidade_ineps for municipio in mantidos),
        "recebiveis_quantidade_municipios": len({(m.boletim_id, m.uf, m.municipio.upper()) for m in mantidos}),
        "recebiveis_valor_total": sum((municipio.valor_total for municipio in mantidos), Decimal("0.00")),
    }


@login_required
def bdo_recebiveis_view(request):
    """Conteúdo do modal "Recebíveis" (HTMX). POST só para o estado do
    formulário (Boletins e retirados) não esbarrar no limite da URL - não
    grava nada. Fora do Visualizador: rota fora da lista liberada do
    `VisualizadorAccessMiddleware`."""
    dados = request.POST if request.method == "POST" else request.GET
    return render(request, "escolas/_bdo_recebiveis.html", _contexto_recebiveis(dados))
