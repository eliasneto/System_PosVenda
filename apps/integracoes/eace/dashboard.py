"""Navegacao e upload no dashboard do portal EACE.

Portado de `doc/auto_eace_nf_servidor/src/dashboard.py` (FEAT-033,
`ADR-004`), so trocando o log (loguru) por `logging` padrao. Traz somente
o necessario para a Fase 1 (1 par PDF+XML por chamada, via `upload_linha`)
- a variante `anexar_arquivos_inep` do prototipo (upload em lote por tipo
KIT/NOBREAK) nao foi portada; RN-056 (Fase 2) processa 1 par por log, o
mesmo grao de `upload_linha`.
"""

from __future__ import annotations

import logging
import re

from playwright.sync_api import Page, TimeoutError as PWTimeout

from .config import SCREENSHOTS_DIR

logger = logging.getLogger(__name__)

_STATUS_CONHECIDOS = ["Pendente", "Enviado", "Aprovado", "Reprovado", "Concluido", "Em construcao"]
_RE_MOEDA = re.compile(r"^R\$\s*[\d.,]+$")


def abrir_medicoes(pagina: Page) -> bool:
    """Aguarda o dashboard carregar e clica no card 'Medições'.

    O texto do portal tem acento ('Medições') - o prototipo original
    buscava 'Medicoes' sem acento, o que nunca deu match (Playwright
    ':has-text' nao ignora acento); corrigido em 2026-09-03 apos teste
    real contra o portal (FEAT-033, Fase 1).
    """
    logger.info("Aguardando dashboard carregar...")

    try:
        card = pagina.locator(".clickable-element:has-text('Medições')").first
        card.wait_for(state="visible", timeout=60_000)
        logger.info("Dashboard carregado. Clicando em 'Medições'...")
        card.click()
    except PWTimeout as exc:
        logger.error("Timeout ao aguardar/clicar em 'Medições': %s", exc)
        return False

    try:
        pagina.locator("button:has-text('Ver OSPs')").wait_for(state="visible", timeout=15_000)
        logger.info("Modal de Medicoes aberto.")
        return True
    except PWTimeout:
        logger.error("Modal de Medicoes nao apareceu apos clicar em 'Medicoes'.")
        return False


def abrir_osps(pagina: Page) -> bool:
    """Clica em 'Ver OSPs' no modal de Medicoes e aguarda a lista carregar."""
    logger.info("Clicando em 'Ver OSPs'...")

    try:
        botao = pagina.get_by_role("button", name="Ver OSPs")
        botao.wait_for(state="visible", timeout=10_000)
        botao.click()
    except PWTimeout as exc:
        logger.error("Timeout ao clicar em 'Ver OSPs': %s", exc)
        return False

    try:
        pagina.wait_for_load_state("networkidle", timeout=20_000)
        logger.info("Secao OSPs aberta. URL: %s", pagina.url)
        return True
    except PWTimeout:
        logger.warning("networkidle nao atingido apos 'Ver OSPs', continuando.")
        return True


def pesquisar_osp(pagina: Page, numero_osp: str) -> bool:
    """Digita o numero da OSP no campo de pesquisa e confirma com Enter."""
    logger.info("Pesquisando OSP: %s", numero_osp)

    try:
        campo = pagina.locator(".baaLlaV1")
        campo.wait_for(state="visible", timeout=15_000)
        campo.click()
        campo.press_sequentially(numero_osp, delay=80)
        campo.press("Enter")
        logger.info("Pesquisa enviada. Aguardando resultados...")
    except PWTimeout as exc:
        logger.error("Timeout ao localizar campo de pesquisa: %s", exc)
        return False

    try:
        pagina.wait_for_load_state("networkidle", timeout=20_000)
        logger.info("Resultados carregados para OSP %s.", numero_osp)
        return True
    except PWTimeout:
        logger.warning("networkidle nao atingido apos pesquisa, continuando.")
        return True


def contar_pedidos_osp(pagina: Page) -> int | None:
    """Le o resumo "N pedido(s)  M INEPs" mostrado apos a pesquisa e
    retorna N. `None` se o texto nao foi encontrado (formato mudou -
    nesse caso o chamador nao deve presumir OSP inexistente).

    Confirmado contra o portal real em 2026-09-03: OSP inexistente mostra
    "0 pedido(s)  0 INEPs"; OSP existente mostra "1 pedido(s)  8 INEPs"
    (o numero de INEPs varia, o de pedidos e o que importa aqui).
    """
    try:
        textos = pagina.evaluate(
            """() => [...document.querySelectorAll('*')]
                .filter(el => el.children.length === 0 && /pedido/i.test(el.textContent))
                .map(el => el.textContent.trim())"""
        )
    except Exception as exc:
        logger.warning("Nao foi possivel ler o resumo de pedidos da OSP: %s", exc)
        return None

    for texto in textos:
        match = re.search(r"(\d+)\s*pedido", texto, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def expandir_resultado_osp(pagina: Page) -> bool:
    """Clica na seta (chevron-down) da linha de resultado para expandir a OSP."""
    logger.info("Expandindo resultado da OSP...")

    try:
        seta = pagina.locator(".baaJhaN1").first
        seta.wait_for(state="visible", timeout=15_000)
        seta.click()
        logger.info("Seta clicada, aguardando expansao...")
    except PWTimeout as exc:
        logger.error("Timeout ao localizar seta de expansao: %s", exc)
        return False

    try:
        pagina.wait_for_load_state("networkidle", timeout=20_000)
        logger.info("Detalhe da OSP expandido.")
        return True
    except PWTimeout:
        logger.warning("networkidle nao atingido apos expandir, continuando.")
        return True


def expandir_notas_fiscais(pagina: Page) -> bool:
    """Clica na linha 'Notas Fiscais' para expandir a secao."""
    logger.info("Expandindo secao 'Notas Fiscais'...")

    try:
        linha = pagina.locator(".clickable-element:has-text('Notas Fiscais')").first
        linha.wait_for(state="visible", timeout=15_000)
        linha.click()
        logger.info("Secao 'Notas Fiscais' clicada, aguardando expansao...")
    except PWTimeout as exc:
        logger.error("Timeout ao localizar secao 'Notas Fiscais': %s", exc)
        return False

    try:
        pagina.wait_for_load_state("networkidle", timeout=20_000)
        logger.info("Secao 'Notas Fiscais' expandida.")
        return True
    except PWTimeout:
        logger.warning("networkidle nao atingido apos expandir Notas Fiscais, continuando.")
        return True


def extrair_dados_grid(pagina: Page, numero_inep: str) -> list[dict]:
    """Extrai INEP, Status e Descricao das linhas do grid com o INEP informado.

    Retorna lista de dicts: [{"inep", "status", "descricao", "valor", "indice"}, ...]
    (`indice` e 1-based, na ordem visual das linhas - o mesmo numero a
    passar em `--indice` para `upload_linha`).
    """
    logger.info("Extraindo dados do grid para INEP %s...", numero_inep)

    try:
        pagina.get_by_text(numero_inep, exact=True).first.wait_for(state="visible", timeout=15_000)
    except PWTimeout:
        logger.error("INEP %s nao encontrado no grid.", numero_inep)
        return []

    linhas_raw: list[list[str]] = pagina.evaluate(
        """() => {
            const rows = document.querySelectorAll(
                '.bubble-element.group-item.bubble-cross-axis'
            );
            return [...rows].map(row => {
                const cells = [...row.querySelectorAll('.bubble-element.Text')]
                    .map(el => ({
                        text: el.innerText.trim(),
                        x: el.getBoundingClientRect().left
                    }))
                    .filter(c => c.text.length > 0)
                    .sort((a, b) => a.x - b.x);
                return cells.map(c => c.text);
            });
        }"""
    )

    resultados = []
    indice = 0
    for textos in linhas_raw:
        if numero_inep not in textos:
            continue

        status = next(
            (t for t in textos if any(s in t for s in _STATUS_CONHECIDOS)),
            "Desconhecido",
        )

        idx_inep = textos.index(numero_inep)
        descricao = textos[idx_inep + 1] if idx_inep + 1 < len(textos) else ""

        valor_raw = next((t for t in textos if _RE_MOEDA.match(t)), "")
        valor = valor_raw.replace("R$", "").strip() if valor_raw else ""

        indice += 1
        resultados.append({
            "inep": numero_inep,
            "status": status,
            "descricao": descricao,
            "valor": valor,
            "indice": indice,
        })

    if resultados:
        for r in resultados:
            logger.info(
                "  Ocorrencia %s: INEP=%s | Status=%s | Descricao=%s | Valor=%s",
                r["indice"], r["inep"], r["status"], r["descricao"], r["valor"],
            )
        logger.info("Total: %s linha(s) encontrada(s) com INEP %s.", len(resultados), numero_inep)
    else:
        logger.error("Nenhuma linha com INEP %s encontrada apos varredura.", numero_inep)

    return resultados


def _confirmar_modal_pos_upload(pagina: Page) -> None:
    """Aguarda e clica em 'Confirmar informacoes' no modal pos-upload."""
    pagina.wait_for_timeout(2_500)

    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    pagina.screenshot(
        path=str(SCREENSHOTS_DIR / "debug_modal_pre_confirmacao.png"),
        full_page=True,
    )
    logger.info("  [Modal] Screenshot salvo em debug_modal_pre_confirmacao.png")

    try:
        btn = pagina.locator(
            "button.baaMyaY0, "
            "button:has-text('Confirmar informacoes'), "
            "button:has-text('Confirmar'), "
            "button:has-text('Salvar'), "
            "button:has-text('OK')"
        ).first
        btn.wait_for(state="visible", timeout=10_000)
        btn.click()
        logger.info("  [Modal] Botao de confirmacao clicado.")
        pagina.wait_for_timeout(2_000)
    except PWTimeout:
        logger.warning("  [Modal] Botao de confirmacao nao apareceu - continuando.")
    except Exception as exc:
        logger.warning("  [Modal] Erro ao confirmar modal: %s", exc)


def _ir_para_linha(pagina: Page, linha) -> None:
    """Rola a pagina ate a linha, centraliza na tela e destaca visualmente."""
    try:
        linha.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
        pagina.wait_for_timeout(600)
        linha.evaluate(
            "el => {"
            "  el.style.outline = '3px solid #FF6B00';"
            "  el.style.background = 'rgba(255, 107, 0, 0.10)';"
            "}"
        )
    except Exception:
        linha.scroll_into_view_if_needed()


def _set_arquivo(pagina: Page, file_input, caminho: str, label: str) -> bool:
    """Tenta anexar um arquivo via expect_file_chooser (clique real) com fallback para set_input_files."""
    try:
        with pagina.expect_file_chooser(timeout=5_000) as fc_info:
            file_input.click()
        fc_info.value.set_files(caminho)
        logger.info("    %s anexado via file chooser: %s", label, caminho)
        return True
    except Exception as exc:
        logger.warning("    file chooser falhou para %s (%s), tentando set_input_files...", label, exc)

    try:
        file_input.set_input_files(caminho)
        logger.info("    %s anexado via set_input_files: %s", label, caminho)
        return True
    except Exception as exc:
        logger.error("    Erro ao anexar %s: %s", label, exc)
        return False


def upload_linha(
    pagina: Page,
    numero_inep: str,
    indice_zero: int,
    caminho_pdf: str,
    caminho_xml: str,
) -> bool:
    """Faz upload de PDF e XML em uma linha especifica do grid (por indice 0-based).

    O modal de confirmacao so aparece apos o XML - nao ha modal intermediario apos o PDF.
    """
    linhas = pagina.locator(".bubble-element.group-item.bubble-cross-axis").filter(has_text=numero_inep)
    linha = linhas.nth(indice_zero)
    _ir_para_linha(pagina, linha)

    logger.info("    PDF upload...")
    if not _set_arquivo(pagina, linha.locator("input[type='file']").nth(0), caminho_pdf, "PDF"):
        return False

    pagina.wait_for_timeout(2_000)

    logger.info("    XML upload...")
    # Re-query apos o upload do PDF: Bubble.io pode ter re-renderizado a linha.
    if not _set_arquivo(pagina, linha.locator("input[type='file']").nth(1), caminho_xml, "XML"):
        return False

    # Modal de confirmacao aparece apos o XML.
    pagina.wait_for_timeout(2_000)
    _confirmar_modal_pos_upload(pagina)
    return True


def clicar_enviar_notas(pagina: Page) -> bool:
    """Clica no botao 'Enviar notas' apos o upload de todos os arquivos do INEP."""
    logger.info("Clicando em 'Enviar notas'...")
    try:
        btn = pagina.locator("button.baaNgaC3, button:has-text('Enviar notas')").first
        btn.wait_for(state="visible", timeout=10_000)
        btn.scroll_into_view_if_needed()
        btn.click()
        logger.info("'Enviar notas' clicado.")
        pagina.wait_for_timeout(2_000)
        return True
    except PWTimeout:
        logger.error("Timeout ao localizar botao 'Enviar notas'.")
        return False
    except Exception as exc:
        logger.error("Erro ao clicar em 'Enviar notas': %s", exc)
        return False
