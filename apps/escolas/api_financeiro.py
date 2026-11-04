"""API de integração com o Módulo Financeiro (Entrada > IXC — faturamento da implantação MIP).

O pós-venda anexa no atendimento do IXC as planilhas de faturamento de implantação dos LOTEs, mas o IXC não deixa
outro sistema baixar esses anexos. Esta API entrega ao Módulo Financeiro as mesmas planilhas, geradas aqui pela mesma
função do botão "Baixar planilha" da tela "Projeto > MIP (LOTE)" (`planilhas_faturamento_implantacao_lote`).

Autenticação: header `Authorization: Bearer <FINANCEIRO_API_TOKEN>` (token vazio = API desligada). Só leitura: nada
do LOTE é alterado.

- GET /api/financeiro/mip/lotes/?status=em_faturamento&data=AAAA-MM-DD
  LOTEs com o status pedido e, de cada um, os arquivos (nome, município/cidade, valor) — para o financeiro casar com
  as cidades e os valores da descrição do atendimento.
- GET /api/financeiro/mip/lotes/<id>/planilhas/?data=AAAA-MM-DD
  As planilhas (.xlsx em base64) do LOTE.

`data` é a data de envio usada na planilha (VENCIMENTO = data + 30 dias, como no botão "Baixar planilha"); o
financeiro manda a data de abertura do atendimento no IXC para a planilha sair igual à que o pós-venda anexou.
Padrão: hoje."""

import base64
import datetime
import hmac
import io
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET

from .models import Lote
from .services import PlanilhaFaturamentoImplantacaoError, planilhas_faturamento_implantacao_lote

VALUE_CELL = "H10"  # "VALOR R$" do quadro DADOS DESTINATÁRIO da planilha-modelo


def _error(message, status):
    return JsonResponse({"erro": message}, status=status)


def _check_token(request):
    """None if the request carries the configured token; otherwise the error response."""
    expected = settings.FINANCEIRO_API_TOKEN
    if not expected:
        return _error("API do Módulo Financeiro desligada (FINANCEIRO_API_TOKEN vazio).", 503)
    header = request.headers.get("Authorization", "")
    received = header[7:].strip() if header.startswith("Bearer ") else ""
    if not received or not hmac.compare_digest(received.encode(), expected.encode()):
        return _error("Token inválido.", 401)
    return None


def _sending_date(request):
    text = (request.GET.get("data") or "").strip()
    if not text:
        return timezone.localdate()
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        return None


def _spreadsheet_value(workbook):
    try:
        return Decimal(str(workbook.worksheets[0][VALUE_CELL].value or 0)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _files(lot, sending_date, with_content):
    files = []
    for name, workbook in planilhas_faturamento_implantacao_lote(lot, data_envio=sending_date):
        value = _spreadsheet_value(workbook)
        item = {"nome": name, "municipio": workbook.worksheets[0].title, "uf": lot.estado,
                "valor": str(value) if value is not None else None, "rateio": "(RATEIO)" in name}
        if with_content:
            stream = io.BytesIO()
            workbook.save(stream)
            item["conteudo_base64"] = base64.b64encode(stream.getvalue()).decode()
        files.append(item)
    return files


def _lot_data(lot):
    return {"id": lot.pk, "lote": str(lot), "municipio": lot.municipio, "uf": lot.estado, "status": lot.status,
            "status_descricao": lot.get_status_display(), "criado_em": lot.criado_em.isoformat()}


@require_GET
def mip_lots_view(request):
    refused = _check_token(request)
    if refused:
        return refused
    sending_date = _sending_date(request)
    if sending_date is None:
        return _error("Data inválida (use AAAA-MM-DD).", 400)
    status = request.GET.get("status") or Lote.EM_FATURAMENTO
    if status not in dict(Lote.STATUS_CHOICES):
        return _error("Status inválido.", 400)
    lots = []
    for lot in Lote.objects.filter(status=status).order_by("pk"):
        try:
            files = _files(lot, sending_date, with_content=False)
        except PlanilhaFaturamentoImplantacaoError as exc:
            lots.append({**_lot_data(lot), "arquivos": [], "erro": str(exc)})
            continue
        lots.append({**_lot_data(lot), "arquivos": files, "erro": ""})
    return JsonResponse({"data": sending_date.isoformat(), "status": status, "lotes": lots})


@require_GET
def mip_lot_spreadsheets_view(request, pk):
    refused = _check_token(request)
    if refused:
        return refused
    sending_date = _sending_date(request)
    if sending_date is None:
        return _error("Data inválida (use AAAA-MM-DD).", 400)
    lot = get_object_or_404(Lote, pk=pk)
    try:
        files = _files(lot, sending_date, with_content=True)
    except PlanilhaFaturamentoImplantacaoError as exc:
        return _error(str(exc), 422)
    return JsonResponse({**_lot_data(lot), "data": sending_date.isoformat(), "planilhas": files})
