"""Carrega as configuracoes do projeto a partir do arquivo .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

VERSAO = "1.0.0"

# Raiz do projeto (pasta que contem este arquivo src/).
BASE_DIR = Path(__file__).resolve().parent.parent

# Carrega o .env da raiz do projeto, se existir.
load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class Config:
    """Configuracoes usadas pelo RPA."""

    url: str
    usuario: str
    senha: str
    headless: bool
    timeout_ms: int
    delay_ms: int

    @classmethod
    def carregar(cls) -> "Config":
        return cls(
            url=os.getenv("EACE_URL", "https://eace.org.br/login?login=login"),
            usuario=os.getenv("EACE_USUARIO", ""),
            senha=os.getenv("EACE_SENHA", ""),
            headless=os.getenv("HEADLESS", "false").lower() == "true",
            timeout_ms=int(os.getenv("TIMEOUT_MS", "30000")),
            delay_ms=int(os.getenv("DELAY_MS", "1500")),
        )


# Pastas do projeto.
# input/ e output/ ficam na raiz (acesso direto pelo usuario).
# Pastas internas do sistema ficam em config/.
INPUT_DIR      = BASE_DIR / "input"
OUTPUT_DIR     = BASE_DIR / "output"
EACE_DIR       = BASE_DIR / "input" / "EACE"
LOGS_DIR       = BASE_DIR / "config" / "logs"
SCREENSHOTS_DIR = BASE_DIR / "config" / "screenshots"

for _pasta in (INPUT_DIR, OUTPUT_DIR, EACE_DIR, LOGS_DIR, SCREENSHOTS_DIR):
    _pasta.mkdir(parents=True, exist_ok=True)
