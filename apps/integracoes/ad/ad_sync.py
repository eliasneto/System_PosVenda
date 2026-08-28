"""RN-044 (FEAT-027): sincronizacao de e-mail e nome a partir do Active
Directory, a cada login (via AD ou local) - reaproveitado do
`modulo-posVenda` (`apps/integracoes/ad/ad_sync.py`, ADR-002), mesma conta
de servico de bind usada na autenticacao (RN-043, `config/settings.py`).

Nao importa `ldap` no topo do modulo de proposito: com `USE_AD_AUTH=false`
(padrao) ou a biblioteca ainda nao instalada (pendencia de DevOps, ADR-002),
o modulo continua importavel e a sincronizacao so nao acontece
(`_ldap_disponivel()`), sem derrubar a aplicacao nem o login local.
"""

import logging
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver


logger = logging.getLogger(__name__)


def _ldap_disponivel():
    if not getattr(settings, "USE_AD_AUTH", False):
        return False
    try:
        import ldap  # noqa: F401
        from ldap.filter import escape_filter_chars  # noqa: F401
    except ImportError:
        return False
    return True


def _username_candidates(username):
    bruto = (username or "").strip()
    candidatos = []

    if bruto:
        candidatos.append(bruto)
    if "\\" in bruto:
        candidatos.append(bruto.split("\\")[-1].strip())
    if "@" in bruto:
        candidatos.append(bruto.split("@")[0].strip())

    vistos = set()
    ordenados = []
    for item in candidatos:
        chave = item.lower()
        if item and chave not in vistos:
            vistos.add(chave)
            ordenados.append(item)
    return ordenados


def _principal_candidates(username):
    candidatos = _username_candidates(username)
    dominio_bind = ""
    bind_dn = (os.getenv("AD_BIND_DN") or "").strip()
    if "@" in bind_dn:
        dominio_bind = bind_dn.split("@", 1)[1].strip()

    principais = []
    vistos = set()

    for candidato in candidatos:
        variantes = [candidato]
        if "@" not in candidato and dominio_bind:
            variantes.append(f"{candidato}@{dominio_bind}")

        for variante in variantes:
            chave = variante.lower()
            if variante and chave not in vistos:
                vistos.add(chave)
                principais.append(variante)

    return principais


def _decode_ldap_value(value):
    if value in (None, b"", ""):
        return ""
    if isinstance(value, bytes):
        for encoding in ("utf-8", "latin1"):
            try:
                return value.decode(encoding).strip()
            except Exception:
                continue
        return value.decode("utf-8", errors="ignore").strip()
    return str(value).strip()


def _emails_from_proxy_addresses(values):
    emails = []
    for value in values or []:
        bruto = _decode_ldap_value(value)
        if not bruto:
            continue
        if ":" in bruto:
            prefixo, endereco = bruto.split(":", 1)
            if prefixo.lower() == "smtp" and endereco.strip():
                emails.append((prefixo == "SMTP", endereco.strip()))
        elif "@" in bruto:
            emails.append((False, bruto.strip()))
    return emails


def _selecionar_nome(attrs):
    first_name = _decode_ldap_value((attrs.get("displayName") or [""])[0])
    last_name = _decode_ldap_value((attrs.get("sn") or [""])[0])
    return first_name[:150], last_name[:150]


def _selecionar_melhor_email(attrs):
    mail = _decode_ldap_value((attrs.get("mail") or [""])[0])
    upn = _decode_ldap_value((attrs.get("userPrincipalName") or [""])[0])
    proxy_emails = _emails_from_proxy_addresses(attrs.get("proxyAddresses") or [])

    emails_proxy_ordenados = [
        email for primario, email in sorted(proxy_emails, key=lambda item: (not item[0], item[1].lower()))
    ]

    candidatos = []
    if mail:
        candidatos.append(mail)
    candidatos.extend(emails_proxy_ordenados)
    if upn:
        candidatos.append(upn)

    vistos = set()
    emails_unicos = []
    for candidato in candidatos:
        chave = candidato.lower()
        if candidato and chave not in vistos and "@" in candidato:
            vistos.add(chave)
            emails_unicos.append(candidato)

    return emails_unicos[0] if emails_unicos else ""


class ADDirectoryClient:
    """Cliente fino sobre `python-ldap`, usando a mesma conta de bind da
    autenticacao (`AD_BIND_DN`/`AD_BIND_PASSWORD`, RN-043)."""

    def __init__(self):
        self.server_uri = (os.getenv("AD_SERVER_URI") or "").strip()
        self.bind_dn = (os.getenv("AD_BIND_DN") or "").strip()
        self.bind_password = os.getenv("AD_BIND_PASSWORD") or ""
        self.search_base = (os.getenv("AD_USER_SEARCH_BASE") or "").strip()
        self.connection = None

    def ready(self):
        return all([self.server_uri, self.bind_dn, self.search_base]) and _ldap_disponivel()

    def connect(self):
        if self.connection is not None:
            return self.connection

        import ldap

        conn = ldap.initialize(self.server_uri)
        conn.set_option(ldap.OPT_REFERRALS, 0)
        conn.simple_bind_s(self.bind_dn, self.bind_password)
        self.connection = conn
        return conn

    def close(self):
        if self.connection is None:
            return
        try:
            self.connection.unbind_s()
        except Exception:
            pass
        self.connection = None

    def buscar_email(self, username):
        _, attrs = self.buscar_usuario(username)
        if not attrs:
            return ""
        return _selecionar_melhor_email(attrs)

    def buscar_nome(self, username):
        _, attrs = self.buscar_usuario(username)
        if not attrs:
            return "", ""
        return _selecionar_nome(attrs)

    def buscar_usuario(self, username):
        if not self.ready():
            return None, {}

        import ldap
        from ldap.filter import escape_filter_chars

        conn = self.connect()
        for candidato in _principal_candidates(username):
            seguro = escape_filter_chars(candidato)
            filtro = (
                "(|"
                f"(sAMAccountName={seguro})"
                f"(userPrincipalName={seguro})"
                f"(mail={seguro})"
                ")"
            )
            resultados = conn.search_s(
                self.search_base,
                ldap.SCOPE_SUBTREE,
                filtro,
                ["cn", "displayName", "sn", "mail", "userPrincipalName", "proxyAddresses", "sAMAccountName"],
            )
            for dn, attrs in resultados:
                if not dn or not attrs:
                    continue
                return dn, attrs
        return None, {}


def sincronizar_email_usuario(user, client=None):
    """RN-044: nao sobrescreve e-mail ja usado por outro usuario local."""
    if not user or not getattr(user, "username", None):
        return False, "usuario_invalido"

    client = client or ADDirectoryClient()
    if not client.ready():
        return False, "ldap_indisponivel"

    email_ad = client.buscar_email(user.username)
    if not email_ad:
        return False, "email_nao_encontrado"

    User = get_user_model()
    email_conflitante = (
        User.objects.exclude(pk=user.pk)
        .filter(email__iexact=email_ad)
        .only("id")
        .first()
    )
    if email_conflitante:
        return False, "email_ja_utilizado"

    if (user.email or "").strip().lower() == email_ad.lower():
        return False, "email_ja_atualizado"

    user.email = email_ad
    user.save(update_fields=["email"])
    return True, email_ad


@receiver(user_logged_in)
def sincronizar_email_usuario_no_login(sender, user, request, **kwargs):
    try:
        atualizado, resultado = sincronizar_email_usuario(user)
        if atualizado:
            logger.info("E-mail do usuario %s sincronizado do AD para %s.", user.username, resultado)
    except Exception:
        logger.exception("Falha ao sincronizar e-mail do AD para o usuario %s.", getattr(user, "username", "-"))


def sincronizar_nome_usuario(user, client=None):
    """RN-044: preenche first_name/last_name a partir do AD (displayName/sn)."""
    if not user or not getattr(user, "username", None):
        return False, "usuario_invalido"

    client = client or ADDirectoryClient()
    if not client.ready():
        return False, "ldap_indisponivel"

    first_name_ad, last_name_ad = client.buscar_nome(user.username)
    if not first_name_ad and not last_name_ad:
        return False, "nome_nao_encontrado"

    campos_atualizados = []
    if first_name_ad and user.first_name != first_name_ad:
        user.first_name = first_name_ad
        campos_atualizados.append("first_name")
    if last_name_ad and user.last_name != last_name_ad:
        user.last_name = last_name_ad
        campos_atualizados.append("last_name")

    if not campos_atualizados:
        return False, "nome_ja_atualizado"

    user.save(update_fields=campos_atualizados)
    return True, f"{user.first_name} {user.last_name}".strip()


@receiver(user_logged_in)
def sincronizar_nome_usuario_no_login(sender, user, request, **kwargs):
    try:
        atualizado, resultado = sincronizar_nome_usuario(user)
        if atualizado:
            logger.info("Nome do usuario %s sincronizado do AD para %s.", user.username, resultado)
    except Exception:
        logger.exception("Falha ao sincronizar nome do AD para o usuario %s.", getattr(user, "username", "-"))
