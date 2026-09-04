"""Navegacao no dashboard do portal EACE."""

from __future__ import annotations

import re

from playwright.sync_api import Locator, Page, TimeoutError as PWTimeout

from config import SCREENSHOTS_DIR
from logger import log

_RE_MOEDA = re.compile(r"^R\$\s*[\d.,]+$")


def abrir_medicoes(pagina: Page) -> bool:
    """Aguarda o dashboard carregar e clica no card 'Medicoes'."""
    log.info("Aguardando dashboard carregar...")

    try:
        # Aguarda o card 'Medicoes'/'Medicoes' ficar visivel.
        # Usa filter+regex para ignorar acento (portal pode exibir "Medicoes" ou "Medicoes").
        card = pagina.locator(".clickable-element:has-text('Medicoes')").first
        card.wait_for(state="visible", timeout=60_000)
        log.info("Dashboard carregado. Clicando em 'Medicoes'...")
        card.click()
    except PWTimeout as exc:
        log.error("Timeout ao aguardar/clicar em 'Medicoes': {}", exc)
        return False

    # Aguarda o modal com as opcoes aparecer (Ver BDOs / Ver MIPs / Ver OSPs).
    try:
        pagina.locator("button:has-text('Ver OSPs')").wait_for(
            state="visible", timeout=15_000
        )
        log.success("Modal de Medicoes aberto.")
        return True
    except PWTimeout:
        log.error("Modal de Medicoes nao apareceu apos clicar em 'Medicoes'.")
        return False


def abrir_osps(pagina: Page) -> bool:
    """Clica em 'Ver OSPs' no modal de Medicoes e aguarda a lista carregar."""
    log.info("Clicando em 'Ver OSPs'...")

    try:
        botao = pagina.get_by_role("button", name="Ver OSPs")
        botao.wait_for(state="visible", timeout=10_000)
        botao.click()
    except PWTimeout as exc:
        log.error("Timeout ao clicar em 'Ver OSPs': {}", exc)
        return False

    try:
        pagina.wait_for_load_state("networkidle", timeout=20_000)
        log.success("Secao OSPs aberta. URL: {}", pagina.url)
        return True
    except PWTimeout:
        log.warning("networkidle nao atingido apos 'Ver OSPs', continuando.")
        return True


def pesquisar_osp(pagina: Page, numero_osp: str) -> bool:
    """Digita o numero da OSP no campo de pesquisa e confirma com Enter."""
    log.info("Pesquisando OSP: {}", numero_osp)

    try:
        # Campo de pesquisa identificado pela classe baaLlaV1 no HTML inspecionado.
        campo = pagina.locator(".baaLlaV1")
        campo.wait_for(state="visible", timeout=15_000)
        campo.click()
        campo.press_sequentially(numero_osp, delay=80)
        campo.press("Enter")
        log.info("Pesquisa enviada. Aguardando resultados...")
    except PWTimeout as exc:
        log.error("Timeout ao localizar campo de pesquisa: {}", exc)
        return False

    try:
        pagina.wait_for_load_state("networkidle", timeout=20_000)
        log.success("Resultados carregados para OSP {}.", numero_osp)
        return True
    except PWTimeout:
        log.warning("networkidle nao atingido apos pesquisa, continuando.")
        return True


def expandir_notas_fiscais(pagina: Page) -> bool:
    """Clica na linha 'Notas Fiscais' para expandir a secao."""
    log.info("Expandindo secao 'Notas Fiscais'...")

    try:
        # Clica na linha clicavel que contem o texto 'Notas Fiscais'.
        linha = pagina.locator(".clickable-element:has-text('Notas Fiscais')").first
        linha.wait_for(state="visible", timeout=15_000)
        linha.click()
        log.info("Secao 'Notas Fiscais' clicada, aguardando expansao...")
    except PWTimeout as exc:
        log.error("Timeout ao localizar secao 'Notas Fiscais': {}", exc)
        return False

    try:
        pagina.wait_for_load_state("networkidle", timeout=20_000)
        log.success("Secao 'Notas Fiscais' expandida.")
        return True
    except PWTimeout:
        log.warning("networkidle nao atingido apos expandir Notas Fiscais, continuando.")
        return True


def extrair_dados_grid(pagina: Page, numero_inep: str) -> list[dict]:
    """Extrai INEP, Status e Descricao das linhas do grid com o INEP informado.

    Retorna lista de dicts:
        [{"inep": "...", "status": "...", "descricao": "...", "indice": N}, ...]

    As celulas de cada linha sao ordenadas por posicao horizontal (x) para
    respeitar a ordem visual das colunas: Status | INEP | Descricao | ...
    """
    log.info("Extraindo dados do grid para INEP {}...", numero_inep)

    try:
        pagina.get_by_text(numero_inep, exact=True).first.wait_for(
            state="visible", timeout=15_000
        )
    except PWTimeout:
        log.error("INEP {} nao encontrado no grid.", numero_inep)
        return []

    _STATUS_CONHECIDOS = ["Pendente", "Enviado", "Aprovado", "Reprovado", "Concluido", "Em construcao"]

    # Ordena os textos de cada linha pela posicao X (esquerda → direita),
    # garantindo que a ordem visual das colunas seja preservada.
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

        # A Descricao e o texto imediatamente apos o INEP na ordem horizontal.
        idx_inep = textos.index(numero_inep)
        descricao = textos[idx_inep + 1] if idx_inep + 1 < len(textos) else ""

        # Valor: primeiro texto no formato "R$ 9.512,95" - remove o prefixo R$
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
            log.info(
                "  Ocorrencia {}: INEP={} | Status={} | Descricao={} | Valor={}",
                r["indice"], r["inep"], r["status"], r["descricao"], r["valor"],
            )
        log.success("Total: {} linha(s) encontrada(s) com INEP {}.", len(resultados), numero_inep)
    else:
        log.error("Nenhuma linha com INEP {} encontrada apos varredura.", numero_inep)

    return resultados


_STATUS_ENVIADO = "Enviado"
_STATUS_CONHECIDOS = ["Pendente", "Enviado", "Aprovado", "Reprovado", "Concluido", "Em construcao"]


def _tipo_da_linha(linha_locator) -> str:
    """Determina se a linha e KIT ou NOBREAK com base no texto da Descricao."""
    texto = linha_locator.inner_text().upper()
    if "NOBREAK" in texto:
        return "NOBREAK"
    return "KIT"


def _status_da_linha(linha_locator) -> str:
    """Le o status atual da linha diretamente do DOM."""
    texto = linha_locator.inner_text()
    for s in _STATUS_CONHECIDOS:
        if s in texto:
            return s
    return "Desconhecido"


def anexar_arquivos_inep(
    pagina: Page,
    numero_inep: str,
    arquivos: dict[str, tuple[str, str]],
) -> bool:
    """Para cada linha do grid com o INEP, verifica o status antes de fazer upload.

    - Se a linha ja estiver com status "Enviado", pula e informa.
    - Se TODAS as linhas estiverem "Enviado", retorna False (processo encerrado).
    - Caso contrario, faz upload do PDF e XML conforme o tipo (KIT ou NOBREAK).

    `arquivos` → {"KIT": (pdf, xml), "NOBREAK": (pdf, xml)}
    """
    linhas = pagina.locator(".bubble-element.group-item.bubble-cross-axis").filter(
        has_text=numero_inep
    )

    total = linhas.count()
    if total == 0:
        log.error("Nenhuma linha com INEP {} encontrada para upload.", numero_inep)
        return False

    # Verifica os status antes de iniciar qualquer upload.
    statuses = [_status_da_linha(linhas.nth(i)) for i in range(total)]
    ja_enviados = [s == _STATUS_ENVIADO for s in statuses]

    if all(ja_enviados):
        log.warning(
            "INEP {} - todas as {} linha(s) ja foram enviadas anteriormente. "
            "Nenhum upload sera realizado.",
            numero_inep, total,
        )
        return False

    log.info("Iniciando upload em {} linha(s) com INEP {}...", total, numero_inep)

    for i in range(total):
        linha = linhas.nth(i)
        linha.scroll_into_view_if_needed()
        tipo = _tipo_da_linha(linha)

        if ja_enviados[i]:
            log.warning(
                "  Linha {}/{} - tipo={} | Status ja e '{}', pulando.",
                i + 1, total, tipo, _STATUS_ENVIADO,
            )
            continue

        if tipo not in arquivos:
            log.error("Tipo '{}' nao encontrado nos arquivos carregados.", tipo)
            return False

        caminho_pdf, caminho_xml = arquivos[tipo]

        # O Bubble.io sobrepoe um <input type="file"> invisivel sobre o botao visivel.
        # set_input_files() no input direto e a forma correta de fazer upload aqui.
        # Ordem dos inputs na linha: 1º → Nota fiscal (PDF), 2º → XML.
        file_inputs = linha.locator("input[type='file']")

        log.info("  Linha {}/{} - tipo={} | PDF upload...", i + 1, total, tipo)
        try:
            file_inputs.nth(0).set_input_files(caminho_pdf)
            log.success("    PDF anexado: {}", caminho_pdf)
        except Exception as exc:
            log.error("    Erro ao anexar PDF na linha {}: {}", i + 1, exc)
            return False

        pagina.wait_for_timeout(1_500)

        log.info("  Linha {}/{} - tipo={} | XML upload...", i + 1, total, tipo)
        try:
            file_inputs.nth(1).set_input_files(caminho_xml)
            log.success("    XML anexado: {}", caminho_xml)
        except Exception as exc:
            log.error("    Erro ao anexar XML na linha {}: {}", i + 1, exc)
            return False

        pagina.wait_for_timeout(1_500)

    log.success("Upload concluido para INEP {}.", numero_inep)
    return True


def _confirmar_modal_pos_upload(pagina: Page) -> None:
    """Aguarda e clica em 'Confirmar informacoes' no modal pos-upload."""
    pagina.wait_for_timeout(2_500)

    # Screenshot de diagnostico: mostra o que esta na tela quando o modal deveria aparecer.
    pagina.screenshot(
        path=str(SCREENSHOTS_DIR / "debug_modal_pre_confirmacao.png"),
        full_page=True,
    )
    log.info("  [Modal] Screenshot salvo em debug_modal_pre_confirmacao.png")

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
        log.success("  [Modal] Botao de confirmacao clicado.")
        pagina.wait_for_timeout(2_000)
    except PWTimeout:
        log.warning("  [Modal] Botao de confirmacao nao apareceu - continuando.")
    except Exception as exc:
        log.warning("  [Modal] Erro ao confirmar modal: {}", exc)


def _ir_para_linha(pagina: Page, linha) -> None:
    """Rola a pagina ate a linha, centraliza na tela e destaca visualmente."""
    try:
        linha.evaluate(
            "el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })"
        )
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
        log.success("    {} anexado via file chooser: {}", label, caminho)
        return True
    except Exception as exc:
        log.warning("    file chooser falhou para {} ({}), tentando set_input_files...", label, exc)

    try:
        file_input.set_input_files(caminho)
        log.success("    {} anexado via set_input_files: {}", label, caminho)
        return True
    except Exception as exc:
        log.error("    Erro ao anexar {}: {}", label, exc)
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
    linhas = pagina.locator(".bubble-element.group-item.bubble-cross-axis").filter(
        has_text=numero_inep
    )
    linha = linhas.nth(indice_zero)
    _ir_para_linha(pagina, linha)

    log.info("    PDF upload...")
    if not _set_arquivo(pagina, linha.locator("input[type='file']").nth(0), caminho_pdf, "PDF"):
        return False

    pagina.wait_for_timeout(2_000)

    log.info("    XML upload...")
    # Re-query apos o upload do PDF: Bubble.io pode ter re-renderizado a linha.
    if not _set_arquivo(pagina, linha.locator("input[type='file']").nth(1), caminho_xml, "XML"):
        return False

    # Modal de confirmacao aparece apos o XML.
    pagina.wait_for_timeout(2_000)
    _confirmar_modal_pos_upload(pagina)
    return True


def clicar_enviar_notas(pagina: Page) -> bool:
    """Clica no botao 'Enviar notas' apos o upload de todos os arquivos do INEP."""
    log.info("Clicando em 'Enviar notas'...")
    try:
        btn = pagina.locator(
            "button.baaNgaC3, button:has-text('Enviar notas')"
        ).first
        btn.wait_for(state="visible", timeout=10_000)
        btn.scroll_into_view_if_needed()
        btn.click()
        log.success("'Enviar notas' clicado.")
        pagina.wait_for_timeout(2_000)
        return True
    except PWTimeout:
        log.error("Timeout ao localizar botao 'Enviar notas'.")
        return False
    except Exception as exc:
        log.error("Erro ao clicar em 'Enviar notas': {}", exc)
        return False


def expandir_resultado_osp(pagina: Page) -> bool:
    """Clica na seta (chevron-down) da linha de resultado para expandir a OSP."""
    log.info("Expandindo resultado da OSP...")

    try:
        # Botao identificado pela classe baaJhaN1 e icone chevron-down (ionic icons).
        seta = pagina.locator(".baaJhaN1").first
        seta.wait_for(state="visible", timeout=15_000)
        seta.click()
        log.info("Seta clicada, aguardando expansao...")
    except PWTimeout as exc:
        log.error("Timeout ao localizar seta de expansao: {}", exc)
        return False

    try:
        pagina.wait_for_load_state("networkidle", timeout=20_000)
        log.success("Detalhe da OSP expandido.")
        return True
    except PWTimeout:
        log.warning("networkidle nao atingido apos expandir, continuando.")
        return True
