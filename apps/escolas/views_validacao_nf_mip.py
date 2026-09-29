"""Tela "Projeto > Validação MIP (NF)" (RN-XXX, a formalizar pelo
Orquestrador em business_rules.md; pedido do usuário, 2026-09-28).

Mostra os cards de município (Município, Valor, Status) lidos na última
execução com Sucesso da rotina `apps.escolas.validacao_nf_mip`, a data/hora
e o status da última execução, e o botão "Rodar agora" (só enfileira -
quem executa é o worker do MIP). Fora do Visualizador: a rota não está na
lista liberada do `VisualizadorAccessMiddleware`."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .models import ValidacaoNfMip
from .validacao_nf_mip import (
    HORA_FIM_AGENDADA,
    HORA_INICIO_AGENDADA,
    agendamento_ativo,
    enfileirar_validacao_nf_mip,
    mensagem_motivo,
    ultima_validacao_com_cards,
)


def _contexto_status():
    ultima = ValidacaoNfMip.objects.select_related("solicitado_por").first()
    if ultima and ultima.motivo_erro:
        if ultima.motivo_erro == "pedido_nao_encontrado" and ultima.pedido_solicitado:
            ultima.motivo_legivel = f"O pedido {ultima.pedido_solicitado} não está no grid de MIPs."
        else:
            ultima.motivo_legivel = mensagem_motivo(ultima.motivo_erro)
    return {
        "ultima": ultima,
        "em_andamento": bool(ultima and ultima.em_andamento),
        "hora_inicio": HORA_INICIO_AGENDADA,
        "hora_fim": HORA_FIM_AGENDADA,
        "agendamento_ativo": agendamento_ativo(),
    }


@login_required
def validacao_nf_mip_view(request):
    """Grid dos cards da última execução com Sucesso. Filtros por GET:
    Município (busca parcial) e Status no portal - o resumo por status
    (quantidade e valor) é sempre sobre todos os cards da execução, e cada
    card do resumo também serve de atalho de filtro."""
    municipio_filtro = (request.GET.get("municipio") or "").strip()
    status_filtro = (request.GET.get("status") or "").strip()

    base = ultima_validacao_com_cards()
    cards = base.cards.all() if base else []
    resumo_por_status = []
    total_valor = None
    if base:
        resumo_por_status = list(
            base.cards.values("status_portal")
            .annotate(quantidade=Count("pk"), valor=Sum("valor"))
            .order_by("status_portal")
        )
        if municipio_filtro:
            cards = cards.filter(municipio__icontains=municipio_filtro)
        if status_filtro:
            cards = cards.filter(status_portal=status_filtro)
        total_valor = cards.aggregate(total=Sum("valor"))["total"]

    return render(
        request,
        "escolas/validacao_nf_mip.html",
        {
            **_contexto_status(),
            "base": base,
            "cards": cards,
            "resumo_por_status": resumo_por_status,
            "total_valor": total_valor,
            "municipio_filtro": municipio_filtro,
            "status_filtro": status_filtro,
        },
    )


@login_required
@require_POST
def validacao_nf_mip_rodar_view(request):
    """Campo "Nº do pedido" opcional: vazio lê o pedido de maior número;
    preenchido (só dígitos), lê exatamente aquele pedido."""
    pedido = (request.POST.get("pedido") or "").strip()
    if pedido and (not pedido.isdigit() or len(pedido) > 20):
        messages.error(request, "Nº do pedido inválido - informe só números (ex.: 506) ou deixe em branco.")
        return redirect("validacao_nf_mip")

    validacao, criada = enfileirar_validacao_nf_mip(ValidacaoNfMip.MANUAL, request.user, pedido)
    if criada:
        alvo = f"do pedido {pedido}" if pedido else "do pedido mais recente"
        messages.success(request, f"Validação {alvo} colocada na fila. A tela se atualiza sozinha quando terminar.")
    else:
        messages.info(request, "Já existe uma validação em andamento - aguarde ela terminar.")
    return redirect("validacao_nf_mip")


@login_required
def validacao_nf_mip_status_view(request):
    """Fragmento do card "Última rotina" (polling HTMX a cada 3 s enquanto
    houver execução em andamento). Quando a execução que a tela estava
    acompanhando termina, pede recarregar a página inteira (`HX-Refresh`)
    para o grid mostrar os cards novos."""
    contexto = _contexto_status()
    if request.GET.get("acompanhando") and not contexto["em_andamento"]:
        resposta = HttpResponse(status=204)
        resposta["HX-Refresh"] = "true"
        return resposta
    return render(request, "escolas/_validacao_nf_mip_status.html", contexto)
