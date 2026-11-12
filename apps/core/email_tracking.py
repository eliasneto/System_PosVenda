"""Código de rastreio do e-mail do RI (RN-009, FEAT-008/FEAT-009).

Reaproveita o mecanismo de `apps/core/email_tracking.py` do
`modulo-posVenda` (lá RN-042/PO-066), adaptado: sem a taxonomia de níveis
RE/RI/MC/Global do original, porque este sistema só trata RI (exceção já
registrada em RN-008). Sem dependência de model — só string.
"""

import re

PREFIXO = "RI"
PADRAO_CODIGO = re.compile(r"\bRI-(\d{8})-(\d{8})\b")


def montar_codigo_rastreio(inep, data_envio):
    """RN-009: `RI-AAAAMMDD-INEP` (data do envio + INEP do RI)."""
    return f"{PREFIXO}-{data_envio:%Y%m%d}-{inep}"


def montar_assunto_com_codigo(codigo, assunto_original):
    """RN-009: prefixa o assunto original com `#{codigo} - `."""
    return f"#{codigo} - {assunto_original}"


def extrair_codigos_rastreio(texto):
    """RN-009 (uso na FEAT-009): varre `texto` (ex.: assunto de um
    e-mail recebido) e retorna todos os códigos `RI-AAAAMMDD-INEP`
    encontrados, na ordem em que aparecem. Lista vazia quando nenhum é
    identificável — RN-009 trata isso como alerta, não bloqueio (mesma
    exceção da RN-005)."""
    return [f"{PREFIXO}-{data}-{inep}" for data, inep in PADRAO_CODIGO.findall(texto or "")]


def extrair_primeiro_inep_rastreio(texto):
    """RN-009 (FEAT-009): identifica o RI de origem de uma resposta só pelo
    INEP do primeiro código de rastreio reconhecido em `texto` — sem
    depender de remetente ou corpo do e-mail. Retorna `None` quando nenhum
    código é identificável (RN-005: exceção, não bloqueio)."""
    correspondencia = PADRAO_CODIGO.search(texto or "")
    return correspondencia.group(2) if correspondencia else None


# Faturamento complementar (pedido do usuário, 2026-11-12, v1.6.0): o e-mail
# de um complementar leva `RI-AAAAMMDD-INEP-C<n>` - o `PADRAO_CODIGO` acima
# continua casando (o "-" depois do INEP é fronteira de palavra), então quem
# só procura o INEP (inclusive o Módulo Financeiro) segue funcionando.
PADRAO_CODIGO_COMPLEMENTAR = re.compile(r"\bRI-(\d{8})-(\d{8})-C(\d+)\b")


def montar_codigo_rastreio_complementar(inep, data_envio, numero):
    """`RI-AAAAMMDD-INEP-C<n>` - código do faturamento complementar n."""
    return f"{montar_codigo_rastreio(inep, data_envio)}-C{numero}"


def extrair_codigo_complementar(texto):
    """Primeiro código de faturamento complementar em `texto` (ex.: assunto
    "RE: #RI-20261112-12345678-C1 - ..."), ou `None`."""
    correspondencia = PADRAO_CODIGO_COMPLEMENTAR.search(texto or "")
    return correspondencia.group(0) if correspondencia else None


def assunto_contem_codigo(assunto, codigo):
    """True quando `codigo` aparece inteiro em `assunto` (não só como
    prefixo de outro código, ex.: "-C1" dentro de "-C12")."""
    return bool(re.search(re.escape(codigo) + r"(?![\w])", assunto or ""))
