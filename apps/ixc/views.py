from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse, HttpResponseForbidden, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render

from . import services
from .forms import PlanilhaIxcAtendimentosUploadForm, PlanilhaIxcLoginEnderecosUploadForm
from .models import ExecucaoAutomacaoIxc

MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
HISTORICO_ITENS_POR_PAGINA = 10

FORM_POR_TIPO = {
    ExecucaoAutomacaoIxc.LOGIN_ENDERECOS: PlanilhaIxcLoginEnderecosUploadForm,
    ExecucaoAutomacaoIxc.ATENDIMENTOS: PlanilhaIxcAtendimentosUploadForm,
}
URL_NOME_POR_TIPO = {
    ExecucaoAutomacaoIxc.LOGIN_ENDERECOS: "ixc_login_enderecos",
    ExecucaoAutomacaoIxc.ATENDIMENTOS: "ixc_atendimentos",
}
NOME_ARQUIVO_MODELO_POR_TIPO = {
    ExecucaoAutomacaoIxc.LOGIN_ENDERECOS: "modelo_login_enderecos_ixc.xlsx",
    ExecucaoAutomacaoIxc.ATENDIMENTOS: "modelo_atendimentos_ixc.xlsx",
}


def _exige_administrador(request):
    if not request.user.is_administrador:
        return HttpResponseForbidden("Somente Administrador pode acessar esta tela.")
    return None


def _fragmento_execucao(request, execucao):
    return render(request, "ixc/_grid_linha.html", {
        "execucao": execucao, "slot": execucao.slot, "tipo": execucao.tipo,
    })


def _resposta_pos_acao(request, execucao):
    """Requisição HTMX (Start/Stop) devolve só a linha do grid, que se
    autoatualiza; sem JS, cai de volta na página cheia (RN a formalizar —
    mesma tela sempre acessível mesmo sem HTMX)."""
    if request.headers.get("HX-Request") == "true":
        return _fragmento_execucao(request, execucao)
    return redirect(URL_NOME_POR_TIPO[execucao.tipo])


def _tela_automacao(request, tipo, template):
    """Comum às 2 telas de Automações IXC: os 2 grids (slot 1/2) mais o
    histórico de todas as execuções já criadas para este tipo — mesmo
    padrão de paginação da linha do tempo do RI (`apps.ri.views`,
    `historico_page`), pedido do usuário em 2026-09-23 (quem rodou, quando
    e a planilha de saída de qualquer execução, não só a do slot atual)."""
    resposta_proibida = _exige_administrador(request)
    if resposta_proibida:
        return resposta_proibida

    historico_qs = ExecucaoAutomacaoIxc.objects.filter(tipo=tipo).select_related("criado_por")
    historico_page_obj = Paginator(historico_qs, HISTORICO_ITENS_POR_PAGINA).get_page(
        request.GET.get("historico_page")
    )
    return render(request, template, {
        "tipo": tipo,
        "execucoes": {
            1: ExecucaoAutomacaoIxc.slot_atual(tipo, 1),
            2: ExecucaoAutomacaoIxc.slot_atual(tipo, 2),
        },
        "historico": historico_page_obj,
    })


@login_required
def login_enderecos_view(request):
    """Automações IXC > Login (Endereços) — criação em massa de login
    (Endereços) no IXC (RN-004: mesmo critério de acesso das demais telas
    administrativas). 2 grids independentes (slot 1/2, FEAT-053)."""
    return _tela_automacao(request, ExecucaoAutomacaoIxc.LOGIN_ENDERECOS, "ixc/login_enderecos.html")


@login_required
def atendimentos_view(request):
    """Automações IXC > Atendimentos — abertura em massa de atendimentos
    no IXC (RN-004: mesmo critério de acesso das demais telas
    administrativas). 2 grids independentes (slot 1/2, FEAT-053)."""
    return _tela_automacao(request, ExecucaoAutomacaoIxc.ATENDIMENTOS, "ixc/atendimentos.html")


@login_required
def ixc_upload_view(request, tipo, slot):
    """Envia a planilha de um dos 2 grids — sempre cria uma execução nova
    (RN a formalizar): a anterior daquele slot continua no banco, só para
    de aparecer na tela. RN a formalizar (pedido do usuário, 2026-09-23):
    slot com uma execução `Processando` fica travado para novo upload até
    ela ser liberada (`Concluído`/`Cancelado`)."""
    resposta_proibida = _exige_administrador(request)
    if resposta_proibida:
        return resposta_proibida
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    if tipo not in FORM_POR_TIPO or slot not in (1, 2):
        raise Http404

    if ExecucaoAutomacaoIxc.objects.filter(
        tipo=tipo, slot=slot, status=ExecucaoAutomacaoIxc.PROCESSANDO
    ).exists():
        messages.error(
            request,
            f"Processamento {slot} está em andamento — espere terminar (ou pare) antes de enviar outra planilha.",
        )
        return redirect(URL_NOME_POR_TIPO[tipo])

    form = FORM_POR_TIPO[tipo](request.POST, request.FILES)
    if form.is_valid():
        services.criar_execucao(tipo, slot, form.cleaned_data["arquivo"], request.user)
        messages.success(request, f"Planilha enviada — Processamento {slot} pronto para iniciar.")
    else:
        erros = "; ".join(str(erro) for lista in form.errors.values() for erro in lista)
        messages.error(request, f"Não foi possível importar a planilha (Processamento {slot}): {erros}")

    return redirect(URL_NOME_POR_TIPO[tipo])


@login_required
def ixc_baixar_modelo_view(request, tipo):
    resposta_proibida = _exige_administrador(request)
    if resposta_proibida:
        return resposta_proibida
    if tipo not in FORM_POR_TIPO:
        raise Http404

    conteudo = services.gerar_planilha_modelo(tipo)
    resposta = HttpResponse(conteudo, content_type=MIME_XLSX)
    resposta["Content-Disposition"] = f'attachment; filename="{NOME_ARQUIVO_MODELO_POR_TIPO[tipo]}"'
    return resposta


@login_required
def ixc_iniciar_view(request, pk):
    resposta_proibida = _exige_administrador(request)
    if resposta_proibida:
        return resposta_proibida
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    execucao = get_object_or_404(ExecucaoAutomacaoIxc, pk=pk)
    if execucao.status == ExecucaoAutomacaoIxc.PENDENTE:
        execucao.status = ExecucaoAutomacaoIxc.PROCESSANDO
        execucao.cancelar_solicitado = False
        execucao.save(update_fields=["status", "cancelar_solicitado"])
    return _resposta_pos_acao(request, execucao)


@login_required
def ixc_status_execucao_view(request, pk):
    """Só leitura — chamada pelo próprio HTMX da linha (`hx-trigger="every
    3s"`) enquanto `status == "processando"`, só para atualizar o
    progresso na tela. RN a formalizar (ADR-007 emendada, 2026-09-23):
    quem processa de verdade é o worker (`processar_fila_automacoes_ixc`,
    container `ixc_worker`) — esta view nunca chama `processar_proximo_
    chunk`, então ninguém com a tela aberta acidentalmente disputa uma
    linha com o worker."""
    resposta_proibida = _exige_administrador(request)
    if resposta_proibida:
        return resposta_proibida

    execucao = get_object_or_404(ExecucaoAutomacaoIxc, pk=pk)
    return _fragmento_execucao(request, execucao)


@login_required
def ixc_parar_view(request, pk):
    """RN a formalizar (pedido do usuário, 2026-09-23): só quem iniciou o
    processamento (`criado_por`) ou o superadmin do sistema
    (`is_superuser`) pode pará-lo — Administrador comum não pode parar o
    processamento de outra pessoa."""
    resposta_proibida = _exige_administrador(request)
    if resposta_proibida:
        return resposta_proibida
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    execucao = get_object_or_404(ExecucaoAutomacaoIxc, pk=pk)
    if execucao.criado_por_id != request.user.pk and not request.user.is_superuser:
        return HttpResponseForbidden(
            "Só quem iniciou este processamento (ou o superadmin do sistema) pode pará-lo."
        )
    execucao.cancelar_solicitado = True
    execucao.save(update_fields=["cancelar_solicitado"])
    return _resposta_pos_acao(request, execucao)


@login_required
def ixc_baixar_saida_view(request, pk):
    resposta_proibida = _exige_administrador(request)
    if resposta_proibida:
        return resposta_proibida

    execucao = get_object_or_404(ExecucaoAutomacaoIxc, pk=pk)
    if execucao.status != ExecucaoAutomacaoIxc.CONCLUIDO:
        return HttpResponseForbidden("Esta execução ainda não terminou de processar.")

    conteudo = services.gerar_planilha_saida(execucao)
    resposta = HttpResponse(conteudo, content_type=MIME_XLSX)
    resposta["Content-Disposition"] = f'attachment; filename="resultado_processamento_{execucao.pk}.xlsx"'
    return resposta
