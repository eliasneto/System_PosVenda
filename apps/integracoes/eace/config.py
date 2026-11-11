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

# Correção (2026-11-11, servidor com 3,8 GB de RAM em swap): o Chromium
# chegava a ~2,5 GB na página do portal e a falta de memória deixava o
# navegador tão lento que o botão "Enviar notas" estourava o tempo de espera
# (metade das execuções). Opções que reduzem memória/processos do Chromium
# headless, sem mudar o que a página renderiza.
ARGS_CHROMIUM_HEADLESS = [
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-sync",
    "--mute-audio",
    "--renderer-process-limit=1",
]


def args_chromium(headless: bool) -> list[str]:
    return list(ARGS_CHROMIUM_HEADLESS) if headless else ["--start-maximized"]


def usar_credenciais_do_robo(usuario: str, senha: str) -> None:
    """ADR-009: cada robô do RPA EACE roda num processo próprio
    (`processar_fila_rpa_eace --robo <id>`) e chama isto no começo - a
    partir daí `ConfigEace.carregar()` (lida a cada execução do RPA) usa o
    login daquele robô em vez do `.env`. Vale só para o processo atual, então
    um robô nunca vê as credenciais de outro."""
    import os

    os.environ["EACE_USUARIO"] = usuario
    os.environ["EACE_SENHA"] = senha
