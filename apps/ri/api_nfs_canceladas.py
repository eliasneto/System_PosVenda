"""API de entrada das NF-e canceladas no Módulo Financeiro (pedido do usuário, 2026-11-12).

O financeiro pode cancelar uma NF que já enviou ao pós-venda por e-mail. Ele avisa por esta API; a NF aparece em
"Administrador > NFs canceladas no financeiro" e só deixa de contar no relatório "Faturamento EACE Materiais (NOVO)"
depois que alguém do pós-venda der baixa nela.

Autenticação igual à da API do financeiro (`apps/escolas/api_financeiro.py`): header
`Authorization: Bearer <FINANCEIRO_API_TOKEN>` (token vazio = API desligada, 503).

- POST /api/financeiro/nfs-canceladas/  (JSON) - registra/atualiza a NF cancelada; idempotente por `id_financeiro`
  (a baixa já dada é mantida). 201 quando cria, 200 quando atualiza.
- GET /api/financeiro/nfs-canceladas/?ids=454-0,455-0 - status de cada NF (ids desconhecidos não aparecem).
"""

import json
from decimal import Decimal, InvalidOperation

from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt

from apps.escolas.api_financeiro import _check_token, _error

from .models import NfCanceladaFinanceiro, Ri

_CAMPOS_OBRIGATORIOS = ("id_financeiro", "numero_nf", "inep")


def _status(nf):
    return {
        "id_financeiro": nf.id_financeiro,
        "status": nf.status,
        "baixada_em": timezone.localtime(nf.baixada_em).isoformat() if nf.baixada_em else None,
        "baixada_por": nf.nome_baixada_por,
    }


def _texto(dados, campo, limite):
    valor = dados.get(campo)
    return "" if valor is None else str(valor).strip()[:limite]


def _dados_validos(dados):
    """(campos do modelo, None) ou (None, mensagem de erro)."""
    if not isinstance(dados, dict):
        return None, "Corpo JSON inválido."
    faltando = [campo for campo in _CAMPOS_OBRIGATORIOS if not _texto(dados, campo, 100)]
    if faltando:
        return None, f"Campo(s) obrigatório(s): {', '.join(faltando)}."

    chave = "".join(_texto(dados, "chave", 100).split())
    if chave and (len(chave) != 44 or not chave.isdigit()):
        return None, "Chave de acesso inválida (44 dígitos ou vazio)."

    valor = None
    texto_valor = _texto(dados, "valor", 30)
    if texto_valor:
        try:
            valor = Decimal(texto_valor.replace(",", ".")).quantize(Decimal("0.01"))
        except InvalidOperation:
            return None, "Valor inválido."

    cancelada_em = None
    texto_data = _texto(dados, "cancelada_em", 40)
    if texto_data:
        try:
            cancelada_em = parse_datetime(texto_data)
        except ValueError:
            cancelada_em = None
        if cancelada_em is None:
            return None, "Data de cancelamento inválida (use ISO 8601)."
        if timezone.is_naive(cancelada_em):
            cancelada_em = timezone.make_aware(cancelada_em)

    email = dados.get("email_financeiro")
    if email in (None, ""):
        email = None
    else:
        try:
            email = int(email)
        except (TypeError, ValueError):
            return None, "email_financeiro inválido (número do e-mail)."
        if email < 0:
            return None, "email_financeiro inválido (número do e-mail)."

    return {
        "numero_nf": _texto(dados, "numero_nf", 20),
        "serie": _texto(dados, "serie", 10),
        "chave": chave,
        "inep": _texto(dados, "inep", 20),
        "escola": _texto(dados, "escola", 255),
        "item": _texto(dados, "item", 255),
        "valor": valor,
        "cancelada_em": cancelada_em,
        "cancelada_por": _texto(dados, "cancelada_por", 150),
        "motivo": _texto(dados, "motivo", 4000),
        "email_financeiro": email,
        "assunto": _texto(dados, "assunto", 500),
    }, None


def _registrar(request):
    try:
        dados = json.loads(request.body.decode("utf-8") or "null")
    except (UnicodeDecodeError, ValueError):
        return _error("Corpo JSON inválido.", 400)
    campos, erro = _dados_validos(dados)
    if erro:
        return _error(erro, 400)
    id_financeiro = _texto(dados, "id_financeiro", 60)
    campos["ri"] = Ri.objects.filter(escola__inep=campos["inep"]).order_by("-pk").first()
    nf, criada = NfCanceladaFinanceiro.objects.update_or_create(id_financeiro=id_financeiro, defaults=campos)
    return JsonResponse(_status(nf), status=201 if criada else 200)


def _consultar(request):
    ids = [parte.strip() for parte in (request.GET.get("ids") or "").split(",") if parte.strip()]
    nfs = NfCanceladaFinanceiro.objects.filter(id_financeiro__in=ids).select_related("baixada_por").order_by("pk")
    return JsonResponse({"resultados": [_status(nf) for nf in nfs]})


@csrf_exempt
def nfs_canceladas_view(request):
    if request.method not in ("GET", "POST"):
        return _error("Método não permitido.", 405)
    recusa = _check_token(request)
    if recusa:
        return recusa
    if request.method == "POST":
        return _registrar(request)
    return _consultar(request)
