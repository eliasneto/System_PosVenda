"""Configuracao do RPA de anexo no portal EACE (FEAT-033, `ADR-004`).

Le credenciais e parametros via `python-decouple`, mesmo padrao ja usado
em `config/settings.py` - nunca com valor default real (CLAUDE.md Sec. 6).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from decouple import config as env
from django.conf import settings


@dataclass(frozen=True)
class ConfigEace:
    """Parametros de conexao/execucao do RPA, lidos do `.env`."""

    url: str
    usuario: str
    senha: str
    headless: bool
    timeout_ms: int
    delay_ms: int

    @classmethod
    def carregar(cls) -> "ConfigEace":
        return cls(
            url=env("EACE_URL", default="https://eace.org.br/login?login=login"),
            usuario=env("EACE_USUARIO", default=""),
            senha=env("EACE_SENHA", default=""),
            headless=env("EACE_HEADLESS", default=True, cast=bool),
            timeout_ms=env("EACE_TIMEOUT_MS", default=30000, cast=int),
            delay_ms=env("EACE_DELAY_MS", default=1500, cast=int),
        )


# Screenshots de diagnostico (sucesso e erro) - nao servidos por URL, so
# para conferencia manual de quem rodar o comando de terminal (Fase 1).
SCREENSHOTS_DIR = Path(settings.MEDIA_ROOT) / "rpa_eace" / "screenshots"
