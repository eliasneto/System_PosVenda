"""API de integração com o Módulo Financeiro (Entrada > IXC — faturamento da implantação MIP).

O pós-venda anexa no atendimento do IXC as planilhas de faturamento de implantação dos LOTEs, mas o IXC não deixa
outro sistema baixar esses anexos. Esta API entrega ao Módulo Financeiro as mesmas planilhas, geradas aqui pela mesma
função do botão "Baixar planilha" da tela "Projeto > MIP (LOTE)" (`planilhas_faturamento_implantacao_lote`).

Autenticação: header `Authorization: Bearer <FINANCEIRO_API_TOKEN>` (token vazio = API desligada). Os GET só leem;
o POST das notas fiscais é a única escrita.

- GET /api/financeiro/mip/lotes/?status=em_faturamento&data=AAAA-MM-DD
  LOTEs com o status pedido e, de cada um, os arquivos (nome, município/cidade, valor) — para o financeiro casar com
  as cidades e os valores da descrição do atendimento.
- GET /api/financeiro/mip/lotes/<id>/planilhas/?data=AAAA-MM-DD
  As planilhas (.xlsx em base64) do LOTE.
- POST /api/financeiro/mip/lotes/<id>/notas-fiscais/  (multipart: `arquivo` = PDF da NFS-e, `numero` = nº da NFS-e)
  A NFS-e de um município do LOTE, assim que o financeiro a emite (botão "Enviar NFS-e ao pós-venda"), sem esperar o
  atendimento ser finalizado no IXC. Faz o mesmo que "Sincronizar Notas Fiscais dos INEPs" só para este LOTE: lê os
  INEPs do "CÓDIGO INEPS" do PDF, grava a NF em cada INEP do LOTE e conclui o INEP. Só LOTE "Em Andamento MIP".

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
from django.db import transaction
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .models import Lote
from .services import (
    PlanilhaFaturamentoImplantacaoError,
    _extrair_texto_pdf_bytes,
    concluir_inep_com_nota_fiscal_mip,
    extrair_ineps_nota_fiscal_mip,
    planilhas_faturamento_implantacao_lote,
)

VALUE_CELL = "H10"  # "VALOR R$" do quadro DADOS DESTINATÁRIO da planilha-modelo
MAX_INVOICE_SIZE = 10 * 1024 * 1024


def _error(message, status):
    return JsonResponse({"erro": message}, status=status)


def _refusal(code, message, status):
    """Recusa de uma gravacao pela regra do pos-venda, no formato que o Modulo Financeiro le ({"erro": {"codigo",
    "mensagem"}}): a mensagem chega na tela do financeiro."""
    return JsonResponse({"erro": {"codigo": code, "mensagem": message}}, status=status)


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


@csrf_exempt
@require_POST
def mip_lot_invoice_view(request, pk):
    refused = _check_token(request)
    if refused:
        return refused
    lot = get_object_or_404(Lote, pk=pk)
    if lot.status != Lote.EM_ANDAMENTO:
        return _refusal("LOTE_FORA_DO_STATUS", f'O {lot} está "{lot.get_status_display()}" no pós-venda: só LOTEs '
                        f'"{dict(Lote.STATUS_CHOICES)[Lote.EM_ANDAMENTO]}" recebem a NF.', 409)
    upload = request.FILES.get("arquivo")
    number = (request.POST.get("numero") or "").strip()
    if upload is None or not number:
        return _refusal("NF_INCOMPLETA", "Envie o PDF da NFS-e (arquivo) e o número (numero).", 400)
    if upload.size > MAX_INVOICE_SIZE:
        return _refusal("NF_GRANDE_DEMAIS", "O PDF passa de 10 MB.", 400)
    content = upload.read()
    if not content.startswith(b"%PDF"):
        return _refusal("NF_NAO_E_PDF", "O arquivo não é um PDF.", 400)
    try:
        ineps = extrair_ineps_nota_fiscal_mip(_extrair_texto_pdf_bytes(content))
    except Exception:  # PDF corrompido: pdfplumber levanta varios tipos
        return _refusal("NF_ILEGIVEL", "Não foi possível ler o PDF da NFS-e.", 400)
    schools = [school for school in lot.escolas.all() if school.inep in ineps]
    if not schools:
        return _refusal("NF_SEM_INEP_DO_LOTE", f'A NFS-e nº {number} não tem INEP do {lot} no "CÓDIGO INEPS" '
                        f'(INEPs da nota: {", ".join(ineps) or "nenhum"}).', 422)
    name = (upload.name or f"{number}.pdf").rsplit("/", 1)[-1]
    with transaction.atomic():
        for school in schools:
            school.adicionar_ou_substituir_nota_fiscal_mip(content, name)
            concluir_inep_com_nota_fiscal_mip(school)
        numbers = [n for n in lot.nf_financeiro_numeros.split(", ") if n]
        if number not in numbers:
            numbers.append(number)
        lot.nf_financeiro_numeros = ", ".join(numbers)[:200]
        lot.nf_financeiro_recebida_em = timezone.now()
        lot.save(update_fields=["nf_financeiro_numeros", "nf_financeiro_recebida_em"])
    lot_ineps = {school.inep for school in lot.escolas.all()}
    return JsonResponse({**_lot_data(lot), "numero": number, "ineps": [school.inep for school in schools],
                         "ineps_fora_do_lote": [inep for inep in ineps if inep not in lot_ineps],
                         "recebida_em": lot.nf_financeiro_recebida_em.isoformat()})
