"""Tela "Administrador > NFs canceladas no financeiro" (pedido do usuário, 2026-11-12).

Lista as NF-e que o Módulo Financeiro cancelou depois de enviar ao pós-venda (recebidas pela API
`api_nfs_canceladas.py`). O botão "Dar baixa" confirma o cancelamento no pós-venda: a partir daí a NF deixa de
contar no relatório "Faturamento EACE Materiais (NOVO)" (`notas_fiscais_vigentes_do_financeiro`). Mesmo acesso das
telas de relatório de faturamento: só Administrador (RN-004)."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.auditoria.models import Auditoria
from apps.auditoria.services import registrar as auditar

from .models import NfCanceladaFinanceiro, RiHistorico

FILTROS_STATUS = (
    ("pendentes", "Aguardando baixa"),
    ("baixadas", "Baixadas"),
    ("todas", "Todas"),
)
_SEM_PERMISSAO = "Somente Administrador pode acessar esta tela."


@login_required
def nfs_canceladas_financeiro_view(request):
    if not request.user.is_administrador:
        return HttpResponseForbidden(_SEM_PERMISSAO)

    status = request.GET.get("status") or "pendentes"
    if status not in dict(FILTROS_STATUS):
        status = "pendentes"
    busca = (request.GET.get("q") or "").strip()

    nfs = NfCanceladaFinanceiro.objects.select_related("baixada_por", "ri")
    if status == "pendentes":
        nfs = nfs.filter(baixada_em__isnull=True)
    elif status == "baixadas":
        nfs = nfs.filter(baixada_em__isnull=False)
    if busca:
        nfs = nfs.filter(Q(inep__icontains=busca) | Q(escola__icontains=busca) | Q(numero_nf__icontains=busca))

    pagina = Paginator(nfs, 50).get_page(request.GET.get("page"))
    return render(request, "ri/nfs_canceladas_financeiro.html", {
        "pagina": pagina,
        "status": status,
        "busca": busca,
        "filtros_status": FILTROS_STATUS,
        "total_pendentes": NfCanceladaFinanceiro.objects.filter(baixada_em__isnull=True).count(),
        "voltar": request.get_full_path(),
        "pendentes_na_pagina": sum(1 for nf in pagina.object_list if not nf.baixada_em),
    })


def _voltar(request):
    voltar = request.POST.get("next") or ""
    if not url_has_allowed_host_and_scheme(voltar, allowed_hosts={request.get_host()},
                                           require_https=request.is_secure()):
        voltar = reverse("nfs_canceladas_financeiro")
    return voltar


def _dar_baixa(nf, request):
    """Baixa de uma NF já travada (`select_for_update`): grava quem/quando, histórico do RI e auditoria. False se
    ela já estava baixada (nada muda)."""
    if nf.baixada_em:
        return False
    nf.baixada_em = timezone.now()
    nf.baixada_por = request.user
    nf.save(update_fields=["baixada_em", "baixada_por", "atualizada_em"])
    if nf.ri_id:
        mensagem = (f"Baixa da NF {nf.numero_nf} cancelada no financeiro"
                    f"{f' (motivo: {nf.motivo})' if nf.motivo else ''}: deixa de contar no faturamento.")
        RiHistorico.objects.create(ri_id=nf.ri_id, tipo=RiHistorico.MENSAGEM, autor=request.user,
                                   mensagem=mensagem[:250])
    auditar(request.user, Auditoria.ALTERACAO_CAMPO, entidade="NfCanceladaFinanceiro", entidade_id=nf.pk,
            campo="baixada_em", valor_novo=f"NF {nf.numero_nf} / INEP {nf.inep} baixada",
            ip_origem=request.META.get("REMOTE_ADDR"))
    return True


@login_required
@require_POST
def nf_cancelada_financeiro_baixar_view(request, pk):
    if not request.user.is_administrador:
        return HttpResponseForbidden(_SEM_PERMISSAO)

    voltar = _voltar(request)
    with transaction.atomic():
        nf = get_object_or_404(NfCanceladaFinanceiro.objects.select_for_update(), pk=pk)
        baixou = _dar_baixa(nf, request)
    if not baixou:
        messages.info(request, f"A NF {nf.numero_nf} (INEP {nf.inep}) já estava baixada.")
        return redirect(voltar)
    messages.success(request, f"Baixa dada na NF {nf.numero_nf} (INEP {nf.inep}): ela deixa de contar no relatório "
                              "Faturamento EACE Materiais (NOVO).")
    return redirect(voltar)


@login_required
@require_POST
def nfs_canceladas_financeiro_baixar_lote_view(request):
    """Baixa em várias NFs de uma vez (pedido do usuário, 2026-11-13): as marcadas na lista. Mesmo efeito da baixa
    de uma por uma (histórico do RI e auditoria de cada NF); as que já estavam baixadas são só contadas."""
    if not request.user.is_administrador:
        return HttpResponseForbidden(_SEM_PERMISSAO)

    voltar = _voltar(request)
    ids = [valor for valor in request.POST.getlist("nfs") if valor.isdigit()]
    if not ids:
        messages.error(request, "Marque pelo menos uma NF para dar baixa.")
        return redirect(voltar)

    baixadas, ja_baixadas = [], 0
    with transaction.atomic():
        for nf in NfCanceladaFinanceiro.objects.select_for_update().filter(pk__in=ids).order_by("pk"):
            if _dar_baixa(nf, request):
                baixadas.append(nf.numero_nf)
            else:
                ja_baixadas += 1

    if baixadas:
        messages.success(request, f"Baixa dada em {len(baixadas)} NF{'s' if len(baixadas) > 1 else ''} "
                                  f"({', '.join(baixadas)}): elas deixam de contar no relatório Faturamento EACE "
                                  "Materiais (NOVO).")
    if ja_baixadas:
        messages.info(request, f"{ja_baixadas} NF{'s' if ja_baixadas > 1 else ''} já estava"
                               f"{'m' if ja_baixadas > 1 else ''} baixada{'s' if ja_baixadas > 1 else ''}.")
    if not baixadas and not ja_baixadas:
        messages.error(request, "Nenhuma das NFs marcadas foi encontrada.")
    return redirect(voltar)
