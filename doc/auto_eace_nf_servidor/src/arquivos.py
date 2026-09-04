"""Localiza os arquivos de nota fiscal na estrutura de pastas EACE/{INEP}/{TIPO}/."""

from __future__ import annotations

from pathlib import Path

from config import EACE_DIR
from logger import log

# Subpastas reconhecidas dentro de cada INEP.
TIPOS = ["KIT", "NOBREAK"]


def _buscar_pdf_xml(pasta: Path) -> tuple[str, str] | None:
    """Retorna (caminho_pdf, caminho_xml) dentro de `pasta`, ou None se faltar algum."""
    pdfs = list(pasta.glob("*.pdf"))
    xmls = list(pasta.glob("*.xml"))

    if not pdfs:
        log.error("Nenhum .pdf encontrado em: {}", pasta)
        return None
    if not xmls:
        log.error("Nenhum .xml encontrado em: {}", pasta)
        return None

    if len(pdfs) > 1:
        log.warning("Mais de um PDF em {}. Usando: {}", pasta, pdfs[0].name)
    if len(xmls) > 1:
        log.warning("Mais de um XML em {}. Usando: {}", pasta, xmls[0].name)

    return str(pdfs[0]), str(xmls[0])


def localizar_arquivos_inep(inep: str) -> dict[str, tuple[str, str]] | None:
    """Busca PDF e XML em EACE/{inep}/KIT/ e EACE/{inep}/NOBREAK/.

    Retorna um dicionario:
        {
            "KIT":     (caminho_pdf, caminho_xml),
            "NOBREAK": (caminho_pdf, caminho_xml),
        }
    Retorna None se a pasta do INEP nao existir ou algum arquivo estiver faltando.
    """
    pasta_inep = EACE_DIR / inep

    if not pasta_inep.exists():
        log.error("Pasta nao encontrada: {}", pasta_inep)
        log.error("  INEP buscado (repr): {!r}", inep)
        pastas_existentes = [p.name for p in EACE_DIR.iterdir() if p.is_dir()] if EACE_DIR.exists() else []
        log.error("  Pastas encontradas em EACE/: {}", pastas_existentes or "nenhuma")
        log.error("Crie a estrutura:  EACE\\{}\\KIT\\  e  EACE\\{}\\NOBREAK\\", inep, inep)
        return None

    resultado: dict[str, tuple[str, str]] = {}

    for tipo in TIPOS:
        pasta_tipo = pasta_inep / tipo
        if not pasta_tipo.exists():
            log.error("Subpasta '{}' nao encontrada em: {}", tipo, pasta_inep)
            return None

        arquivos = _buscar_pdf_xml(pasta_tipo)
        if arquivos is None:
            return None

        resultado[tipo] = arquivos
        log.info("  [{}] PDF : {}", tipo, arquivos[0])
        log.info("  [{}] XML : {}", tipo, arquivos[1])

    log.success("Arquivos localizados para INEP {} - KIT e NOBREAK.", inep)
    return resultado
