"""Le e valida a lista de OSPs do arquivo input/osp.txt."""

from __future__ import annotations

import re
from pathlib import Path

from config import INPUT_DIR
from logger import log

OSP_TXT = INPUT_DIR / "osp.txt"
_RE_VALIDA = re.compile(r"^\d{1,6}$")


def ler_osps() -> list[str]:
    """Le OSPs de input/osp.txt; cria o arquivo se nao existir.

    Regras de validacao por linha:
    - Deve ser numero com no maximo 6 digitos
    - Nao pode conter espacos

    Retorna lista de OSPs validas, ou lista vazia em caso de erro.
    """
    INPUT_DIR.mkdir(exist_ok=True)

    if not OSP_TXT.exists():
        OSP_TXT.write_text("", encoding="utf-8")
        log.warning(
            "Arquivo input/osp.txt nao encontrado - foi criado em: {}\n"
            "Preencha com os numeros de OSP (um por linha) e execute novamente.",
            OSP_TXT,
        )
        return []

    linhas_brutas = OSP_TXT.read_text(encoding="utf-8").splitlines()
    linhas = [(i + 1, l) for i, l in enumerate(linhas_brutas) if l.strip()]

    if not linhas:
        log.warning(
            "Arquivo input/osp.txt esta vazio. "
            "Preencha com os numeros de OSP (um por linha) e execute novamente."
        )
        return []

    erros: list[str] = []
    osps: list[str] = []

    for num, linha in linhas:
        if " " in linha or "\t" in linha:
            erros.append(f"  Linha {num}: '{linha}' - contem espaco")
        elif not _RE_VALIDA.match(linha.strip()):
            erros.append(
                f"  Linha {num}: '{linha}' - deve ser um numero com no maximo 6 digitos"
            )
        else:
            osps.append(linha.strip())

    if erros:
        log.error("Erros em input/osp.txt - corrija e execute novamente:")
        for erro in erros:
            log.error("{}", erro)
        return []

    log.success("{} OSP(s) carregada(s): {}", len(osps), ", ".join(osps))
    return osps
