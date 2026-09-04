"""Extrai INEP, Produto e Valor Total da Nota de dentro do PDF da Nota
Fiscal (FEAT-033, `RN-057`).

Portado de `doc/auto_eace_nf_servidor/src/extrair_dados_pdf.py`, trazendo
so o nucleo de leitura/regex (`pdfplumber`) - a parte de planilha de
controle e varredura de pasta em lote do prototipo nao se aplica aqui: a
FEAT-033 recebe 1 PDF por vez (via `--pdf`, Fase 1, ou via o log por Nota
Fiscal, Fase 2), sem estrutura de pastas nem Excel de acompanhamento.

`pdfplumber` e importado dentro de `extrair_texto_pdf` (nao no topo do
modulo) pelo mesmo motivo do Playwright em `rpa.py` - nao quebrar
`manage.py` inteiro se a lib nao estiver instalada.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_RE_INEP = re.compile(r"INEP[:\s]+(\d{7,8})", re.IGNORECASE)
_RE_VALOR = re.compile(r"VALOR\s+TOTAL\s+DA\s+NOTA", re.IGNORECASE)
# Linha de dados do produto: [COD.PROD] [DESCRICAO] [NCM 0000.00.00] [resto...]
_RE_PRODUTO = re.compile(r"^\S+\s+(.+?)\s+\d{4}\.\d{2}\.\d{2}", re.MULTILINE)


def extrair_texto_pdf(caminho_pdf: str) -> str:
    """Le todo o texto do PDF (todas as paginas). Retorna "" em caso de
    erro de leitura - o chamador decide o que fazer com texto vazio."""
    import pdfplumber

    texto = []
    try:
        with pdfplumber.open(caminho_pdf) as pdf:
            for pagina in pdf.pages:
                conteudo = pagina.extract_text()
                if conteudo:
                    texto.append(conteudo)
    except Exception as exc:
        logger.error("Erro ao ler PDF %s: %s", Path(caminho_pdf).name, exc)
    return "\n".join(texto)


def extrair_inep(texto: str) -> str:
    match = _RE_INEP.search(texto)
    return match.group(1) if match else ""


def extrair_produto(texto: str) -> str:
    match = _RE_PRODUTO.search(texto)
    return match.group(1).strip() if match else ""


def extrair_valor(texto: str) -> str:
    """Le o "Valor Total da Nota": procura o rotulo e le o ultimo numero
    da linha seguinte (formato da NF, ex.: "1 22.644,43 22.644,43")."""
    linhas = texto.splitlines()
    for i, linha in enumerate(linhas):
        if _RE_VALOR.search(linha):
            if i + 1 < len(linhas):
                numeros = re.findall(r"[\d]+(?:[.,][\d]+)*", linhas[i + 1])
                if numeros:
                    return numeros[-1]
    return ""


def _normalizar_valor(valor: str) -> float:
    """Converte "22.644,43" (formato BR) em 22644.43. -1.0 se invalido -
    nunca compara igual a outro valor invalido (ver `valores_iguais`)."""
    try:
        return float(valor.strip().replace(".", "").replace(",", "."))
    except (ValueError, AttributeError):
        return -1.0


def valores_iguais(v1: str, v2: str) -> bool:
    n1, n2 = _normalizar_valor(v1), _normalizar_valor(v2)
    return n1 >= 0 and n2 >= 0 and abs(n1 - n2) < 0.01


def extrair_dados_nota_fiscal(caminho_pdf: str) -> dict:
    """Extrai {"inep", "produto", "valor"} do PDF (RN-057). Campo vazio
    quando o padrao correspondente nao foi encontrado no texto - o
    chamador decide se isso e um erro bloqueante."""
    texto = extrair_texto_pdf(caminho_pdf)
    dados = {
        "inep": extrair_inep(texto),
        "produto": extrair_produto(texto),
        "valor": extrair_valor(texto),
    }
    logger.info(
        "Dados extraidos da NF (%s): INEP=%s | Produto=%s | Valor=%s",
        Path(caminho_pdf).name, dados["inep"] or "?", dados["produto"] or "?", dados["valor"] or "?",
    )
    return dados
