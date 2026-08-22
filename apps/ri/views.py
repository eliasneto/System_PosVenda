from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.shortcuts import render

from apps.escolas.models import Escola

from .models import Ri


@login_required
def grid_inep_view(request):
    """FEAT-007: grid principal de INEPs (RF-05), com filtro por status e
    drill-down dos itens EACE/IXC daquele INEP (RF-06). Uma linha por
    INEP/Escola; o Status/Responsável exibidos são os do RI mais recente
    dela, quando existir (FEAT-004 ainda não tem formulário de cadastro,
    então hoje normalmente não existe RI nenhum).
    """
    q = (request.GET.get("q") or "").strip()
    status_filtro = (request.GET.get("status") or "").strip()

    escolas = Escola.objects.all().order_by("nome")
    if q:
        escolas = escolas.filter(
            Q(inep__icontains=q)
            | Q(nome__icontains=q)
            | Q(municipio__icontains=q)
            | Q(estado__icontains=q)
        )

    # Prefetch unico evita N+1: todas as Escolas da pagina trazem seus RIs
    # (mais recente primeiro) e, de cada RI, os itens e as divergencias.
    escolas = escolas.prefetch_related(
        Prefetch(
            "ris",
            queryset=Ri.objects.order_by("-criado_em").prefetch_related(
                "itens_eace", "itens_ixc", "divergencias"
            ),
        )
    )

    linhas = []
    total_divergencia = 0
    for escola in escolas:
        ris_da_escola = list(escola.ris.all())
        ri_atual = ris_da_escola[0] if ris_da_escola else None
        divergencia_aberta = bool(ri_atual) and any(
            d.resolvida_em is None for d in ri_atual.divergencias.all()
        )
        if divergencia_aberta:
            total_divergencia += 1

        if status_filtro and (not ri_atual or ri_atual.status != status_filtro):
            continue

        linhas.append(
            {
                "escola": escola,
                "ri": ri_atual,
                "divergencia_aberta": divergencia_aberta,
            }
        )

    paginator = Paginator(linhas, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "ri/grid_inep.html",
        {
            "page_obj": page_obj,
            "total_inep": escolas.count(),
            "total_divergencia": total_divergencia,
            "q": q,
            "status_filtro": status_filtro,
            "status_opcoes": Ri.STATUS_CHOICES,
        },
    )
