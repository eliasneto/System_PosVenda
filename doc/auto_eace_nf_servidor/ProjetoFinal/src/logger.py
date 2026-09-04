"""Configuracao centralizada de logging com loguru."""

from __future__ import annotations

import sys

from loguru import logger

from config import LOGS_DIR

# Garante UTF-8 no console (evita caracteres corrompidos no ps2exe/Windows)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass

logger.remove()

# Console: stdout (evita prefixo "ERROR:" do ps2exe que trata stderr como erro)
logger.add(
    sys.stdout,
    level="INFO",
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
)

# Arquivo rotativo
logger.add(
    LOGS_DIR / "eace_{time:YYYY-MM-DD}.log",
    level="DEBUG",
    rotation="10 MB",
    retention="14 days",
    encoding="utf-8",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
)

log = logger
