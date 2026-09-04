"""Fluxo de autenticacao no portal EACE (Bubble.io)."""

from __future__ import annotations

from playwright.sync_api import Page, TimeoutError as PWTimeout

from logger import log


def fazer_login(pagina: Page, usuario: str, senha: str) -> bool:
    """Preenche e envia o formulario de login.

    Considera sucesso quando:
      - A URL muda (saiu da tela de login), OU
      - O texto 'Fornecedor' aparece (modal de selecao de perfil).
    """
    log.info("Preenchendo credenciais de login...")

    try:
        campo_email = pagina.locator("input[type='email']")
        campo_email.wait_for(state="visible")
        campo_email.click()
        campo_email.press_sequentially(usuario, delay=80)

        campo_senha = pagina.locator("#log_pass")
        campo_senha.wait_for(state="visible")
        campo_senha.click()
        campo_senha.press_sequentially(senha, delay=80)

        botao = pagina.get_by_role("button", name="Log In")
        botao.wait_for(state="visible")
        botao.click()
        log.info("Botao 'Log In' clicado, aguardando resposta do portal...")

    except PWTimeout as exc:
        log.error("Timeout ao localizar elemento de login: {}", exc)
        return False

    # Aguarda ate 15 s que a URL mude OU que o texto 'Fornecedor' fique visivel
    # (indica que o modal de selecao de perfil foi exibido apos login bem-sucedido).
    try:
        pagina.wait_for_function(
            """() => {
                const urlOk = !window.location.href.includes('login');

                // Verifica se algum elemento de texto com 'Fornecedor' esta visivel.
                const texts = Array.from(document.querySelectorAll('.bubble-element'));
                const modalOk = texts.some(el =>
                    el.innerText && el.innerText.trim().includes('Fornecedor')
                    && el.getBoundingClientRect().height > 0
                );

                return urlOk || modalOk;
            }""",
            timeout=15_000,
        )
    except PWTimeout:
        erro = _capturar_mensagem_de_erro(pagina)
        if erro:
            log.error("Falha no login - mensagem do portal: {}", erro)
        else:
            log.error("Login nao produziu resposta esperada dentro do tempo limite.")
        return False

    log.success("Login aceito! URL: {}", pagina.url)
    return True


def selecionar_perfil_fornecedor(pagina: Page) -> bool:
    """Aguarda o modal de selecao de perfil e clica em 'Fornecedor'.

    O modal e um CustomElement do Bubble.io - nao um Popup convencional.
    """
    log.info("Aguardando modal de selecao de perfil...")

    try:
        # Aguarda o texto 'Fornecedor' estar visivel na tela.
        opcao = pagina.get_by_text("Fornecedor", exact=True).first
        opcao.wait_for(state="visible", timeout=10_000)
        log.info("Modal de perfil detectado. Clicando em 'Fornecedor'...")

        # Clica no container clicavel pai que envolve o texto.
        linha = pagina.locator(".clickable-element:has-text('Fornecedor')").first
        linha.click()

    except PWTimeout as exc:
        log.error("Timeout ao aguardar selecao de perfil: {}", exc)
        return False

    # Aguarda o modal desaparecer ou a URL mudar.
    try:
        pagina.wait_for_function(
            """() => {
                const texts = Array.from(document.querySelectorAll('.bubble-element'));
                const modalSumiu = !texts.some(el =>
                    el.innerText && el.innerText.trim().includes('Selecione o perfil')
                    && el.getBoundingClientRect().height > 0
                );
                return modalSumiu || !window.location.href.includes('login');
            }""",
            timeout=15_000,
        )
        log.success("Perfil selecionado! URL atual: {}", pagina.url)
        return True

    except PWTimeout:
        log.error("Portal nao respondeu apos selecao do perfil.")
        return False


def _capturar_mensagem_de_erro(pagina: Page) -> str | None:
    seletores = [
        ".bubble-element.Text[class*='error']",
        "[class*='alert']",
        "[class*='Error']",
    ]
    for seletor in seletores:
        try:
            el = pagina.locator(seletor).first
            if el.is_visible():
                return el.inner_text().strip()
        except Exception:
            continue
    return None
