"""FEAT-011 (RF-12/RN-006): liga o login do usuário (sinal nativo do
Django) ao registro de auditoria — o choice `LOGIN` já existia em
`Auditoria.ACAO_CHOICES` desde a base do projeto (FEAT-001), sem nenhum
emissor até esta feature. Conectado em `AuditoriaConfig.ready()`."""

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .models import Auditoria
from .services import registrar


def _ip_da_requisicao(request):
    """Mesmo critério comum de proxy (`X-Forwarded-For`): usa o primeiro IP
    da cadeia quando presente, senão o IP direto da conexão."""
    if request is None:
        return None
    encaminhado = request.META.get("HTTP_X_FORWARDED_FOR")
    if encaminhado:
        return encaminhado.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


@receiver(user_logged_in)
def _auditar_login(sender, request, user, **kwargs):
    registrar(
        user,
        Auditoria.LOGIN,
        entidade="User",
        entidade_id=user.pk,
        ip_origem=_ip_da_requisicao(request),
    )
