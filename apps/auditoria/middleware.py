"""FEAT-011 (RF-12/RN-006): captura qualquer erro não tratado durante uma
requisição e grava na auditoria — rede de segurança abrangente, sem
precisar instrumentar cada view. Erro de rotina em segundo plano, fora do
ciclo de requisição (ex.: leitura da caixa do financeiro), é registrado no
próprio ponto onde acontece (`apps/ri/services.py`), não aqui."""

from .models import Auditoria
from .services import registrar


class AuditoriaErroMiddleware:
    """Registrado depois de `AuthenticationMiddleware` (`config/settings.py`)
    — `request.user` já está disponível quando um erro acontece."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        registrar(
            getattr(request, "user", None),
            Auditoria.ERRO,
            entidade=request.path,
            campo=type(exception).__name__,
            valor_novo=str(exception),
            ip_origem=request.META.get("REMOTE_ADDR"),
        )
        return None  # não trata o erro - só registra; segue o comportamento padrão do Django
