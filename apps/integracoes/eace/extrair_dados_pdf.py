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

# Botão "Validar Notas Fiscais" (a formalizar pelo Orquestrador em
# business_rules.md; ver `apps.ri.services.validar_notas_fiscais_financeiro`):
# texto do "ITEM LPU" gravado em "Dados Adicionais" do DANFE — mesmo texto
# que `apps.ri.services._item_lpu_e_aba` grava na aba da planilha de
# faturamento (RN-013). É esse campo, não a "DESCRIÇÃO DO PRODUTO/SERVIÇO"
# (fiscal, ex.: "CONVERSOR DE MIDIA"), que corresponde ao nome do
# equipamento/produto usado internamente (ex.: "SWITCH") — confirmado
# lendo um DANFE real (`doc/Nota Fiscal.pdf`).
_RE_ITEM_LPU = re.compile(r"ITEM LPU:\s*(.+?)\s+MUNIC[IÍ]PIO", re.IGNORECASE)
# Linha completa da tabela "DADOS DO PRODUTO/SERVIÇO" do DANFE, na mesma
# ordem das colunas do cabeçalho: CÓD.PROD. DESCRIÇÃO NCM CST CFOP UNID.
# QUANT. V.UNITÁRIO V.TOTAL (resto da linha, não capturado, ignorado).
_RE_ITEM_PRODUTO_NF = re.compile(
    r"^\S+\s+(?P<descricao>.+?)\s+\d{4}\.\d{2}\.\d{2}\s+\d{2,3}\s+\d{4}\s+\S+\s+"
    r"(?P<quantidade>[\d.,]+)\s+(?P<valor_unitario>[\d.,]+)\s+(?P<valor_total>[\d.,]+)\b",
    re.MULTILINE,
)


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


def extrair_numero_nf(texto: str) -> str:
    """Número do DANFE (ex.: "1365"), lido pela vizinhança do rótulo fixo
    "Chave de acesso" — texto sem acento, não corrompe na leitura do PDF
    (diferente de "Nº", que vira "N" + caractere inválido em parte dos
    DANFE, confirmado lendo um real, `doc/Nota Fiscal.pdf`). O layout
    padrão do cabeçalho do DANFE sempre traz o número da nota logo antes
    desse rótulo — usa o último número encontrado numa janela curta antes
    dele, para não pegar outro número do cabeçalho (ex.: Telefone)."""
    indice = texto.find("Chave de acesso")
    if indice == -1:
        return ""
    numeros = re.findall(r"\d{1,10}", texto[max(0, indice - 60):indice])
    return numeros[-1] if numeros else ""


def extrair_item_lpu(texto: str) -> str:
    """Texto do "ITEM LPU" (Dados Adicionais do DANFE) — ver `_RE_ITEM_LPU`
    acima para o porquê deste campo, não a Descrição fiscal, ser o que
    corresponde ao nome do equipamento/produto usado internamente."""
    match = _RE_ITEM_LPU.search(texto)
    return match.group(1).strip() if match else ""


def extrair_itens_produto_nf(texto: str) -> list[dict]:
    """Todas as linhas da tabela "DADOS DO PRODUTO/SERVIÇO" do DANFE —
    Descrição (fiscal), Quantidade, Valor Unitário e Valor Total de cada
    item faturado. Lista vazia quando nenhuma linha bate com o layout
    esperado (`_RE_ITEM_PRODUTO_NF`)."""
    return [
        {
            "descricao": match.group("descricao").strip(),
            "quantidade": match.group("quantidade"),
            "valor_unitario": match.group("valor_unitario"),
            "valor_total": match.group("valor_total"),
        }
        for match in _RE_ITEM_PRODUTO_NF.finditer(texto)
    ]


def extrair_dados_validacao_nf(caminho_pdf: str) -> dict:
    """Extrai {"numero_nf", "inep", "item_lpu", "itens", "ilegivel"} do PDF
    para o botão "Validar Notas Fiscais" (ver `apps.ri.services.
    validar_notas_fiscais_financeiro`) — diferente de
    `extrair_dados_nota_fiscal` (RN-057), que lê 1 Produto/Valor da Nota
    inteira para conferir contra o portal EACE, esta extrai a tabela de
    itens completa (Descrição/Quantidade/Valor Unitário/Valor Total) para
    conferir contra o Lado Relatório EACE (3º lado) do RI. Mesmo critério
    de "ilegivel" de `extrair_dados_nota_fiscal`: nenhum texto lido no PDF
    (arquivo ausente/corrompido) é diferente de texto lido sem os dados
    esperados."""
    texto = extrair_texto_pdf(caminho_pdf)
    return {
        "numero_nf": extrair_numero_nf(texto),
        "inep": extrair_inep(texto),
        "item_lpu": extrair_item_lpu(texto),
        "itens": extrair_itens_produto_nf(texto),
        "ilegivel": not texto.strip(),
    }


def extrair_dados_nota_fiscal(caminho_pdf: str) -> dict:
    """Extrai {"inep", "produto", "valor", "ilegivel"} do PDF (RN-057).
    Campo vazio quando o padrao correspondente nao foi encontrado no texto
    - o chamador decide se isso e um erro bloqueante.

    "ilegivel" (`True`) distingue "nao foi possivel ler texto NENHUM do
    arquivo" (arquivo ausente/corrompido/scaneado sem OCR - falha tecnica/
    de ambiente, `motivo="pdf_ilegivel"` em `rpa.py`) de "o texto foi lido,
    mas o INEP/valor nao aparece nele" (`motivo="pdf_sem_inep"`/
    "pdf_sem_valor" - dado da Nota Fiscal, regra de negocio). Antes desta
    distincao, `extrair_texto_pdf` engolia qualquer excecao (arquivo nao
    encontrado incluso, `Path.open`/`pdfplumber.open` levantam `OSError`)
    e devolvia "" do mesmo jeito que um PDF ilegivel de verdade - os dois
    casos viravam "pdf_sem_inep", escondendo um problema de arquivo
    ausente atras de uma mensagem que sugeria dado errado na Nota Fiscal."""
    texto = extrair_texto_pdf(caminho_pdf)
    dados = {
        "inep": extrair_inep(texto),
        "produto": extrair_produto(texto),
        "valor": extrair_valor(texto),
        "ilegivel": not texto.strip(),
    }
    logger.info(
        "Dados extraidos da NF (%s): INEP=%s | Produto=%s | Valor=%s | Ilegivel=%s",
        Path(caminho_pdf).name, dados["inep"] or "?", dados["produto"] or "?", dados["valor"] or "?",
        dados["ilegivel"],
    )
    return dados
