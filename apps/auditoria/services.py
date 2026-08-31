"""FEAT-011 (RF-12/RN-006): ponto único de gravação da auditoria técnica —
usado pela troca de status e alteração de campo do RI/itens
(`apps/ri/services.py`/`apps/ri/views.py`), pelo envio/recebimento de
e-mail (FEAT-008/FEAT-009), pelo login (`signals.py`) e pelos erros não
tratados (`middleware.py`). Separado da linha do tempo voltada ao usuário
(`RiHistorico`, FEAT-014) — a `Auditoria` (RN-006) é o registro técnico,
sem tela própria nesta versão (consulta só por acesso direto ao banco)."""

import logging

from .models import Auditoria

logger = logging.getLogger(__name__)


def registrar(
    usuario,
    acao,
    *,
    entidade="",
    entidade_id=None,
    campo="",
    valor_anterior="",
    valor_novo="",
    ip_origem=None,
):
    """Nunca interrompe a ação sendo auditada — uma falha ao gravar o
    registro não pode derrubar login, troca de status, envio de e-mail
    etc. `usuario=None` é válido (rotina automática, sem usuário logado:
    RF-18/RF-19, Sincronizador)."""
    if usuario is not None and not getattr(usuario, "is_authenticated", False):
        usuario = None
    try:
        Auditoria.objects.create(
            usuario=usuario,
            acao=acao,
            entidade=entidade,
            entidade_id=entidade_id,
            campo=campo,
            valor_anterior=str(valor_anterior)[:4000] if valor_anterior else "",
            valor_novo=str(valor_novo)[:4000] if valor_novo else "",
            ip_origem=ip_origem,
        )
    except Exception:
        logger.exception("Falha ao gravar registro de auditoria (ação=%s).", acao)
