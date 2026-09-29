"""Botão "Enviar ao portal EACE" de cada LOTE em "Projeto > MIP (LOTE)"
(RN-XXX, a formalizar pelo Orquestrador em business_rules.md; pedido do
usuário, 2026-09-29) - `apps.escolas.rpa_mip_lote`. Fora do Visualizador:
as rotas não estão na lista liberada do `VisualizadorAccessMiddleware`."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Escola, Lote
from .rpa_mip_lote import EnvioRpaMipRecusado, enfileirar_rpa_mip_lote, estado_rpa_mip_do_lote


def _lote_com_notas(pk):
    return get_object_or_404(
        Lote.objects.prefetch_related(
            Prefetch("escolas", queryset=Escola.objects.prefetch_related("notas_fiscais_mip"))
        ),
        pk=pk,
    )


@login_required
@require_POST
def rpa_mip_lote_enviar_view(request, pk):
    lote = _lote_com_notas(pk)
    try:
        enfileirar_rpa_mip_lote(lote, request.user)
    except EnvioRpaMipRecusado as exc:
        messages.error(request, f"{lote}: {exc}")
    else:
        messages.success(request, f"{lote}: envio da NF ao portal EACE colocado na fila.")
    next_url = request.POST.get("next") or ""
    return redirect(next_url if next_url.startswith("/") else "mip_lote_inep")


@login_required
def rpa_mip_lote_status_view(request, pk):
    """Fragmento do botão (polling HTMX a cada 3 s enquanto o envio estiver
    Na fila/Processando - para sozinho quando termina)."""
    lote = _lote_com_notas(pk)
    return render(
        request,
        "escolas/_rpa_mip_lote_acao.html",
        {"lote": lote, "rpa_mip": estado_rpa_mip_do_lote(lote), "next": request.GET.get("next", "")},
    )
