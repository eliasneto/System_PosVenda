"""Integração direta com o Módulo Financeiro, o segundo caminho do e-mail (pedido do usuário, 2026-11-13).

O e-mail continua sendo o caminho principal nos dois sentidos. Esta API só leva o que o e-mail não conseguiu levar:

- GET /api/financeiro/envios/
  Envios ao financeiro cujo e-mail falhou (`EnvioFinanceiro.canal = api`) e que o financeiro ainda não confirmou.
  Cada um vem com o Message-ID, assunto, corpo, remetente, Para/Cc e os anexos em base64 (planilha e anexo extra).
- POST /api/financeiro/envios/confirmar/  (JSON {"message_id": "<...>"})
  O financeiro confirma que gravou o envio: ele sai da lista. Idempotente.
- GET /api/financeiro/cancelamentos/  e  POST /api/financeiro/cancelamentos/confirmar/ (JSON {"id", "resultado"})
  Processos cancelados pela EACE (`cancelamento_eace.py`) que o financeiro ainda não confirmou: ele marca os
  e-mails dele (pelos códigos de rastreio e Message-IDs) como "Cancelado pela EACE" e confirma.
- POST /api/financeiro/respostas/  (multipart: `message_id`, `assunto`, `remetente`, arquivos PDF/XML)
  Resposta do financeiro com as NFs quando o e-mail de resposta falhou. Passa pelo mesmo processo da resposta lida
  na caixa (`services.processar_resposta_financeiro`): documentos, logs do RPA EACE, histórico e status. O
  Message-ID é o mesmo do e-mail de resposta: se o e-mail também chegar, cai em "duplicados".

Autenticação igual à das outras APIs do financeiro: `Authorization: Bearer <FINANCEIRO_API_TOKEN>`."""

import base64
import json
import logging

from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.escolas.api_financeiro import _check_token, _error, _refusal

from .models import CancelamentoEace, EnvioFinanceiro, RiHistorico
from .services import processar_resposta_financeiro

logger = logging.getLogger(__name__)

LIMITE_ENVIOS = 20
MAX_ARQUIVO_RESPOSTA = 15 * 1024 * 1024

# resultado de processar_resposta_financeiro -> (HTTP, mensagem ao financeiro); o que não está aqui é recusa
_ACEITOS = {
    "identificados": "Resposta recebida pelo pós-venda.",
    "fora_do_padrao": "Resposta recebida pelo pós-venda, mas fora do padrão (quantidade de PDF diferente da de XML).",
    "duplicados": "O pós-venda já tinha recebido esta resposta.",
}
_RECUSAS = {
    "sem_codigo": "O assunto não tem o código de rastreio do pós-venda (#RI-AAAAMMDD-INEP).",
    "sem_ri_aguardando": "O pós-venda não encontrou o RI do código de rastreio do assunto.",
    "cancelados": "O processo deste RI foi cancelado pela EACE no pós-venda: a resposta não vale mais.",
}


def _arquivo(campo):
    if not campo:
        return None
    with campo.open("rb") as arquivo:
        return base64.b64encode(arquivo.read()).decode()


def _dados_envio(envio):
    anexos = [{"nome": envio.nome_planilha,
               "tipo": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
               "conteudo_base64": _arquivo(envio.planilha)}]
    if envio.anexo_extra:
        anexos.append({"nome": envio.nome_anexo_extra, "tipo": envio.tipo_anexo_extra or "application/octet-stream",
                       "conteudo_base64": _arquivo(envio.anexo_extra)})
    return {
        "message_id": envio.message_id,
        "inep": envio.ri.escola.inep,
        "remetente": envio.remetente,
        "remetente_nome": "Pós-venda",
        "destinatarios": [e.strip() for e in envio.destinatarios.split(",") if e.strip()],
        "copia": [e.strip() for e in envio.copia.split(",") if e.strip()],
        "assunto": envio.assunto,
        "corpo": envio.corpo,
        "enviado_em": timezone.localtime(envio.criado_em).isoformat(),
        "anexos": anexos,
    }


@require_GET
def envios_pendentes_view(request):
    refused = _check_token(request)
    if refused:
        return refused
    envios = (
        EnvioFinanceiro.objects.select_related("ri__escola")
        .filter(canal=EnvioFinanceiro.API, coletado_em__isnull=True, cancelamento_eace__isnull=True)
        .order_by("criado_em")[:LIMITE_ENVIOS]
    )
    dados = []
    for envio in envios:
        try:
            dados.append(_dados_envio(envio))
        except (FileNotFoundError, OSError):
            logger.exception("Arquivo do envio ao financeiro %s não encontrado.", envio.pk)
    return JsonResponse({"envios": dados})


@csrf_exempt
@require_POST
def confirmar_envio_view(request):
    refused = _check_token(request)
    if refused:
        return refused
    try:
        message_id = (json.loads(request.body or b"{}").get("message_id") or "").strip()
    except (ValueError, AttributeError):
        return _error("Corpo JSON inválido.", 400)
    envio = EnvioFinanceiro.objects.filter(message_id=message_id).select_related("ri").first()
    if not envio:
        return _refusal("ENVIO_DESCONHECIDO", "O pós-venda não tem esse envio.", 404)
    if envio.coletado_em is None:
        with transaction.atomic():
            envio.coletado_em = timezone.now()
            envio.save(update_fields=["coletado_em"])
            RiHistorico.objects.create(
                ri=envio.ri,
                tipo=RiHistorico.EMAIL,
                autor=None,
                faturamento_complementar=envio.faturamento_complementar,
                mensagem=f"O financeiro recebeu a planilha pela integração direta. Assunto: {envio.assunto}",
            )
    return JsonResponse({"message_id": envio.message_id,
                         "coletado_em": timezone.localtime(envio.coletado_em).isoformat()})


@csrf_exempt
@require_POST
def resposta_financeiro_view(request):
    refused = _check_token(request)
    if refused:
        return refused
    message_id = (request.POST.get("message_id") or "").strip()[:255]
    assunto = (request.POST.get("assunto") or "").strip()[:255]
    remetente = (request.POST.get("remetente") or "").strip()[:254]
    if not message_id or not assunto:
        return _error("Campos obrigatórios: message_id e assunto.", 400)

    pdfs, xmls = [], []
    for arquivo in request.FILES.values():
        if arquivo.size > MAX_ARQUIVO_RESPOSTA:
            return _refusal("ARQUIVO_GRANDE", f"O arquivo {arquivo.name} passa de 15 MB.", 400)
        nome = arquivo.name or ""
        tipo = (arquivo.content_type or "").lower()
        if tipo == "application/pdf" or nome.lower().endswith(".pdf"):
            pdfs.append((nome or "nota_fiscal.pdf", arquivo.read()))
        elif tipo in ("text/xml", "application/xml") or nome.lower().endswith(".xml"):
            xmls.append((nome or "nota_fiscal.xml", arquivo.read()))

    with transaction.atomic():
        resultado = processar_resposta_financeiro(assunto, remetente, pdfs, xmls, message_id, via_api=True)
    if resultado in _RECUSAS:
        return _refusal(resultado.upper(), _RECUSAS[resultado], 422)
    return JsonResponse({"resultado": resultado, "mensagem": _ACEITOS.get(resultado, resultado)})


@require_GET
def cancelamentos_pendentes_view(request):
    refused = _check_token(request)
    if refused:
        return refused
    cancelamentos = (CancelamentoEace.objects.select_related("ri__escola", "criado_por")
                     .filter(confirmado_em__isnull=True).order_by("criado_em")[:LIMITE_ENVIOS])
    return JsonResponse({"cancelamentos": [{
        "id": c.pk,
        "inep": c.ri.escola.inep,
        "codigos_rastreio": c.codigos_rastreio,
        "message_ids": c.message_ids,
        "motivo": c.motivo,
        "cancelado_por": (c.criado_por.get_full_name() or c.criado_por.get_username()) if c.criado_por else "",
        "cancelado_em": timezone.localtime(c.criado_em).isoformat(),
    } for c in cancelamentos]})


@csrf_exempt
@require_POST
def confirmar_cancelamento_view(request):
    refused = _check_token(request)
    if refused:
        return refused
    try:
        dados = json.loads(request.body or b"{}")
        pk = int(dados.get("id"))
    except (ValueError, TypeError, AttributeError):
        return _error("Corpo JSON inválido (id numérico).", 400)
    cancelamento = CancelamentoEace.objects.filter(pk=pk).select_related("ri").first()
    if not cancelamento:
        return _refusal("CANCELAMENTO_DESCONHECIDO", "O pós-venda não tem esse cancelamento.", 404)
    if cancelamento.confirmado_em is None:
        with transaction.atomic():
            cancelamento.confirmado_em = timezone.now()
            cancelamento.resultado_financeiro = str(dados.get("resultado") or "")[:255]
            cancelamento.save(update_fields=["confirmado_em", "resultado_financeiro"])
            RiHistorico.objects.create(
                ri=cancelamento.ri, tipo=RiHistorico.MENSAGEM, autor=None,
                mensagem=(f"O financeiro recebeu o cancelamento pela EACE. {cancelamento.resultado_financeiro}")[:250],
            )
    return JsonResponse({"id": cancelamento.pk, "confirmado_em": timezone.localtime(cancelamento.confirmado_em).isoformat()})
