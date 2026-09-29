"""RPA do MIP: anexa o PDF da Nota Fiscal de um municipio no portal EACE.

Modulo independente - ainda nao e chamado por nenhuma tela, fila ou
comando do sistema. So reaproveita (sem alterar) os helpers de navegacao
ja existentes em `.login` e `.dashboard` para o trecho comum com o outro
RPA do portal: login, perfil "Fornecedor" e clique no card "Medições".

Fluxo:
  1. le o valor do PDF antes de abrir o navegador;
  2. login -> "Fornecedor" -> "Medições";
  3. "Ver MIPs" (mesmo modal de "Ver OSPs") abre a pagina com o grid de
     pedidos; expande o pedido de MAIOR numero na coluna "Pedido";
  4. o pedido expandido mostra 1 card por municipio (Municipio, Status,
     "Valor total a ser emitido" e o campo "Arquivo da Nota Fiscal");
     filtra os cards do municipio informado e valida status e valor;
  5. anexa somente o PDF no card escolhido.

`playwright`/`pdfplumber` (e `.login`/`.dashboard`, que importam
`playwright.sync_api` no topo) so sao importados dentro das funcoes, para
`manage.py` nao quebrar se a lib nao estiver instalada.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import SCREENSHOTS_DIR, ConfigEace
from .extrair_dados_pdf import extrair_inep, extrair_produto, extrair_texto_pdf, extrair_valor, valores_iguais

logger = logging.getLogger(__name__)


# NF do MIP e NFS-e (nota de servico), layout diferente da NF de produto do
# RI (primeiro envio real, 2026-09-29: "pdf_sem_valor" no LOTE-0037 - o PDF
# traz "VALOR TOTAL DO SERVIÇO = R$ 15.483,97" e "VALOR TOTAL COBRADO = R$
# 15.483,97", nunca "Valor Total da Nota"). Tentados nesta ordem, so quando
# o padrao da NF de produto (`extrair_valor`, usado pelo RPA do RI) nao acha.
_RES_VALOR_NFSE = (
    re.compile(r"VALOR\s+TOTAL\s+DO\s+SERVI[ÇC]O\s*=?\s*R\$\s*([\d.]+,\d{2})", re.IGNORECASE),
    re.compile(r"VALOR\s+TOTAL\s+COBRADO\s*=?\s*R\$\s*([\d.]+,\d{2})", re.IGNORECASE),
)


def extrair_valor_nfse(texto: str) -> str:
    for regex in _RES_VALOR_NFSE:
        encontrado = regex.search(texto)
        if encontrado:
            return encontrado.group(1)
    return ""


def extrair_dados_nf_mip(caminho_pdf: str) -> dict:
    """Mesmo formato de `extrair_dados_pdf.extrair_dados_nota_fiscal`
    ({"inep", "produto", "valor", "ilegivel"}), mas o valor tambem sai do
    layout de NFS-e (`extrair_valor_nfse`) - sem mudar o extrator
    compartilhado com o RPA do RI."""
    texto = extrair_texto_pdf(caminho_pdf)
    dados = {
        "inep": extrair_inep(texto),
        "produto": extrair_produto(texto),
        "valor": extrair_valor(texto) or extrair_valor_nfse(texto),
        "ilegivel": not texto.strip(),
    }
    logger.info(
        "Dados extraidos da NF do MIP (%s): Valor=%s | Ilegivel=%s",
        Path(caminho_pdf).name, dados["valor"] or "?", dados["ilegivel"],
    )
    return dados


class RpaMipIndisponivel(Exception):
    """`playwright`/`pdfplumber` nao instalados, ou Chromium ausente."""


@dataclass
class ResultadoRpaMip:
    sucesso: bool
    motivo: str | None = None
    dados_pdf: dict | None = None
    valor_portal: str | None = None
    pedido: str | None = None
    # True quando rodou em modo de validacao (`simular=True`): chegou no
    # card certo, mas nao anexou nada.
    simulado: bool = False
    # Todos os cards de municipio lidos no pedido expandido (quando chegou
    # ate eles) - para conferir no modo de validacao o que o portal mostrou.
    cards_encontrados: list[dict] | None = None
    # Status do(s) card(s) do municipio no portal quando a validacao de
    # status/valor recusou (ex.: "Aprovado" em `documento_ja_enviado`) -
    # pedido do usuario (2026-09-29) para a mensagem dizer em que status
    # o card esta.
    status_portal: str = ""


# Motivos possiveis em ResultadoRpaMip.motivo quando sucesso=False:
#   pdf_ilegivel             - PDF ausente/corrompido, nenhum texto extraido
#   pdf_sem_valor            - PDF lido, mas sem "Valor Total da Nota"
#   credenciais_ausentes     - .env sem EACE_USUARIO/EACE_SENHA
#   login                    - login recusado pelo portal
#   selecao_perfil           - modal "Fornecedor" nao respondeu
#   abrir_medicoes           - card "Medições" nao encontrado
#   abrir_mips               - botao "Ver MIPs" nao encontrado no modal de Medições
#   pedidos_nao_encontrados  - grid de pedidos (coluna "Pedido") vazio ou nao carregou
#   pedido_nao_encontrado    - numero de pedido informado nao esta no grid de MIPs
#   expandir_pedido          - seta do pedido escolhido nao respondeu
#   municipio_nao_encontrado - nenhum card do municipio informado no pedido expandido
#   documento_ja_enviado     - nenhum card do municipio com status pendente
#   valor_divergente         - nenhum card pendente do municipio com valor igual ao do PDF
#   valor_ambiguo            - 2+ cards pendentes do municipio com valor igual ao do PDF
#   upload                   - falha ao anexar o PDF no card
#   envio_nao_confirmado     - PDF anexado, mas o card nao saiu de "Pendente" no tempo esperado
#   erro_playwright          - erro inesperado do Playwright (rede, crash, etc.)

# Mesmo criterio da RN-058 do RPA do RI (`rpa.MOTIVOS_REGRA_DE_NEGOCIO`):
# dependem do dado da NF ou do estado do portal - repetir sem ninguem
# corrigir nada nao muda o resultado, entao a fila nunca reprocessa sozinha.
# `envio_nao_confirmado` entra aqui de proposito: o PDF ja pode ter subido,
# e reprocessar sozinho arriscaria anexar a mesma NF 2 vezes.
MOTIVOS_REGRA_DE_NEGOCIO_MIP = frozenset({
    "pdf_sem_valor",
    "pedidos_nao_encontrados",
    "pedido_nao_encontrado",
    "municipio_nao_encontrado",
    "documento_ja_enviado",
    "valor_divergente",
    "valor_ambiguo",
    "envio_nao_confirmado",
})

ETAPAS_RPA_MIP = (
    "Lendo os dados da Nota Fiscal",
    "Abrindo o portal EACE",
    "Preenchendo usuário",
    "Preenchendo senha",
    "Aguardando o portal responder",
    "Selecionando o perfil Fornecedor",
    "Abrindo Medições",
    "Abrindo MIPs",
    "Lendo os pedidos",
    "Expandindo o pedido",
    "Lendo os municípios do pedido",
    "Conferindo status e valor",
    "Anexando o PDF",
    "Confirmando o envio",
)

# Ciclo do card no portal (confirmado pelo usuario, 2026-09-28):
# "Pendente" (aguarda a NF) -> "Aguardando Aprovação" (NF anexada) ->
# "Aprovado" (o portal muda sozinho). So "Pendente" aceita o PDF; os
# outros dois contam como ja enviado - e sao o sinal de que o upload
# funcionou. Comparados sem acento/maiuscula (`normalizar_texto`).
STATUS_PENDENTES = frozenset({"PENDENTE"})
STATUS_ENVIADOS = frozenset({"AGUARDANDO APROVACAO", "APROVADO"})


class ProgressoRpaMip:
    """Avanca 1 posicao em `ETAPAS_RPA_MIP` a cada `avancar()` e chama
    `callback(etapa, percentual)`; falha no callback so e logada."""

    def __init__(self, callback=None):
        self._callback = callback
        self._indice = 0

    def avancar(self) -> str | None:
        """Avanca 1 etapa e devolve o nome dela (`None` se ja acabaram)."""
        if self._indice >= len(ETAPAS_RPA_MIP):
            return None
        etapa = ETAPAS_RPA_MIP[self._indice]
        self._indice += 1
        percentual = round(self._indice / len(ETAPAS_RPA_MIP) * 100)
        if self._callback:
            try:
                self._callback(etapa, percentual)
            except Exception:
                logger.exception("Erro ao reportar progresso do RPA MIP (etapa: %s).", etapa)
        return etapa


class CapturasRpaMip:
    """Modo de validacao: salva 1 screenshot numerado por etapa em `pasta`
    (ex.: `03_Preenchendo_senha.png`), para conferir o caminho visualmente.
    Falha ao salvar so e logada - nunca derruba a RPA."""

    def __init__(self, pasta):
        self.pasta = Path(pasta)
        self.pasta.mkdir(parents=True, exist_ok=True)
        self._numero = 0

    def salvar(self, pagina, descricao: str) -> None:
        self._numero += 1
        nome = re.sub(r"[^A-Za-z0-9]+", "_", normalizar_municipio(descricao).title()).strip("_")
        caminho = self.pasta / f"{self._numero:02d}_{nome}.png"
        try:
            pagina.screenshot(path=str(caminho), full_page=True)
            logger.info("Captura salva: %s", caminho)
        except Exception as exc:
            logger.warning("Nao foi possivel salvar a captura %s: %s", caminho, exc)


def anexar_pdf_mip(
    *,
    municipio: str | None,
    caminho_pdf: str | None,
    config: ConfigEace | None = None,
    progresso_callback=None,
    simular: bool = False,
    pasta_capturas=None,
    headless: bool | None = None,
    lento_ms: int = 0,
    gravar_video: bool = False,
    pedido: str | None = None,
) -> ResultadoRpaMip:
    """Anexa o PDF da Nota Fiscal no card do `municipio` (dentro do pedido
    mais recente do MIP) cujo status esta pendente e cujo "Valor total a
    ser emitido" bate com o valor do PDF.

    `pedido` (opcional): numero do pedido a abrir no grid de MIPs em vez
    do de maior numero - se nao existir no grid, para com
    `pedido_nao_encontrado`.

    Opcoes do modo de validacao (comando `validar_rpa_mip`):
      - `simular`: faz todo o caminho e as validacoes, destaca o card que
        receberia o PDF e para ali - nao anexa nada (`simulado=True`);
      - `pasta_capturas`: salva 1 screenshot por etapa nessa pasta;
      - `headless`/`lento_ms`: sobrescrevem o `.env` para ver o navegador
        abrindo e desacelerar cada acao;
      - `gravar_video`: grava um video da execucao em `pasta_capturas`.

    So em `simular=True`, `caminho_pdf` e `municipio` podem ser `None`,
    para validar o caminho antes de ter a Nota Fiscal: sem PDF, para depois
    de ler os cards (sem conferir status/valor), destacando o 1º card do
    municipio; sem municipio, so le todos os cards do pedido.
    """
    if not simular and not (caminho_pdf and municipio):
        raise ValueError("Anexar de verdade exige municipio e caminho_pdf - so a simulacao aceita sem eles.")
    municipio = municipio or ""
    progresso = ProgressoRpaMip(progresso_callback)
    capturas = CapturasRpaMip(pasta_capturas) if pasta_capturas else None
    try:
        import pdfplumber  # noqa: F401  (so para falhar cedo se faltar)
        from playwright.sync_api import Error as PlaywrightError, sync_playwright

        from .dashboard import abrir_medicoes
        from .login import fazer_login, selecionar_perfil_fornecedor
    except ImportError as exc:
        raise RpaMipIndisponivel(
            "Playwright/pdfplumber nao instalados - rode "
            "'pip install -r requirements.txt' e "
            "'python -m playwright install chromium'."
        ) from exc

    dados_pdf = extrair_dados_nf_mip(caminho_pdf) if caminho_pdf else {}
    progresso.avancar()  # "Lendo os dados da Nota Fiscal"

    if caminho_pdf:
        if dados_pdf["ilegivel"]:
            return ResultadoRpaMip(sucesso=False, motivo="pdf_ilegivel", dados_pdf=dados_pdf)
        if not dados_pdf["valor"]:
            return ResultadoRpaMip(sucesso=False, motivo="pdf_sem_valor", dados_pdf=dados_pdf)

    cfg = config or ConfigEace.carregar()
    if not cfg.usuario or not cfg.senha:
        logger.error("EACE_USUARIO/EACE_SENHA nao configurados no .env - abortando.")
        return ResultadoRpaMip(sucesso=False, motivo="credenciais_ausentes", dados_pdf=dados_pdf)

    headless = cfg.headless if headless is None else headless
    logger.info(
        "Iniciando RPA MIP | municipio=%s headless=%s simular=%s capturas=%s",
        municipio, headless, simular, pasta_capturas,
    )

    try:
        with sync_playwright() as p:
            navegador = p.chromium.launch(
                headless=headless,
                slow_mo=lento_ms,
                args=[] if headless else ["--start-maximized"],
            )
            # Em headless nao ha janela fisica - viewport explicito garante que
            # o portal renderize as colunas no tamanho esperado (getBoundingClientRect).
            # Video exige viewport fixo, entao tambem usa 1920x1080 quando gravado.
            viewport_fixo = headless or gravar_video
            opcoes_contexto = {
                "no_viewport": not viewport_fixo,
                "viewport": {"width": 1920, "height": 1080} if viewport_fixo else None,
            }
            if gravar_video and pasta_capturas:
                opcoes_contexto["record_video_dir"] = str(pasta_capturas)
                opcoes_contexto["record_video_size"] = {"width": 1920, "height": 1080}
            contexto = navegador.new_context(**opcoes_contexto)
            pagina = contexto.new_page()
            pagina.set_default_timeout(cfg.timeout_ms)
            # "Ver MIPs" abre outra aba - a partir dali tudo (inclusive o
            # screenshot de erro) acontece na aba nova.
            atual = {"pagina": pagina}

            def avancar() -> None:
                etapa = progresso.avancar()
                if capturas and etapa:
                    capturas.salvar(atual["pagina"], etapa)

            def falhar(motivo, valor_portal=None, pedido=None):
                if capturas:
                    capturas.salvar(atual["pagina"], f"Erro {motivo}")
                return _falhar(atual["pagina"], municipio, motivo, dados_pdf, valor_portal, pedido=pedido)

            try:
                pagina.goto(cfg.url, wait_until="load", timeout=60_000)
                avancar()  # "Abrindo o portal EACE"

                if not fazer_login(pagina, cfg.usuario, cfg.senha, avancar):
                    return falhar("login")

                if not selecionar_perfil_fornecedor(pagina):
                    return falhar("selecao_perfil")
                avancar()  # "Selecionando o perfil Fornecedor"

                if not abrir_medicoes(pagina):
                    return falhar("abrir_medicoes")
                avancar()  # "Abrindo Medições"

                motivo, pedido = _navegar_caminho_mip(atual, municipio, avancar, cfg.timeout_ms, pedido)
                if motivo:
                    return falhar(motivo, pedido=pedido)
                pagina = atual["pagina"]

                todos_os_cards = listar_cards_municipio(pagina)
                cards = [
                    card for card in todos_os_cards
                    if not municipio or mesmo_municipio(card["municipio"], municipio)
                ]
                if not cards:
                    resultado = falhar("municipio_nao_encontrado", pedido=pedido)
                    resultado.cards_encontrados = todos_os_cards
                    return resultado
                avancar()  # "Lendo os municípios do pedido"

                if not caminho_pdf:
                    # Validacao sem Nota Fiscal: para aqui, sem conferir status/valor.
                    if municipio:
                        destacar_card(pagina, cards[0]["posicao"])
                    if capturas:
                        capturas.salvar(pagina, "Sem PDF cards do pedido")
                    logger.info(
                        "RPA MIP (simulacao sem PDF) - pedido=%s: %s card(s) lido(s), %s do municipio '%s'.",
                        pedido, len(todos_os_cards), len(cards), municipio,
                    )
                    return ResultadoRpaMip(
                        sucesso=True, dados_pdf=dados_pdf, pedido=pedido, simulado=True,
                        cards_encontrados=todos_os_cards,
                    )

                card_alvo, motivo = localizar_card_pendente(cards, dados_pdf["valor"])
                if motivo:
                    resultado = falhar(motivo, card_alvo["valor"] if card_alvo else None, pedido)
                    resultado.cards_encontrados = todos_os_cards
                    resultado.status_portal = (
                        card_alvo["status"] if card_alvo
                        else ", ".join(sorted({card["status"] for card in cards if card["status"]}))
                    )
                    return resultado
                avancar()  # "Conferindo status e valor"

                if simular:
                    destacar_card(pagina, card_alvo["posicao"])
                    if capturas:
                        capturas.salvar(pagina, "Simulacao card que receberia o PDF")
                    logger.info(
                        "RPA MIP (simulacao) - pedido=%s municipio=%s valor=%s: PDF NAO anexado.",
                        pedido, card_alvo["municipio"], card_alvo["valor"],
                    )
                    return ResultadoRpaMip(
                        sucesso=True, dados_pdf=dados_pdf, valor_portal=card_alvo["valor"],
                        pedido=pedido, simulado=True, cards_encontrados=todos_os_cards,
                    )

                if not anexar_pdf_no_card(pagina, card_alvo["posicao"], caminho_pdf):
                    return falhar("upload", card_alvo["valor"], pedido)
                avancar()  # "Anexando o PDF"

                status_final = confirmar_envio_card(pagina, card_alvo["posicao"])
                if not status_enviado(status_final):
                    logger.error(
                        "Card do municipio %s continua '%s' depois do upload - envio nao confirmado.",
                        card_alvo["municipio"], status_final,
                    )
                    return falhar("envio_nao_confirmado", card_alvo["valor"], pedido)
                avancar()  # "Confirmando o envio" -> 100%

                logger.info("RPA MIP concluido - pedido=%s municipio=%s.", pedido, card_alvo["municipio"])
                return ResultadoRpaMip(
                    sucesso=True, dados_pdf=dados_pdf, valor_portal=card_alvo["valor"], pedido=pedido,
                )
            finally:
                _encerrar(contexto, navegador)

    except PlaywrightError as exc:
        logger.error("Erro inesperado do Playwright: %s", exc)
        return ResultadoRpaMip(sucesso=False, motivo="erro_playwright", dados_pdf=dados_pdf)


def _navegar_caminho_mip(
    atual: dict, municipio: str, avancar, timeout_ms: int, pedido_desejado: str | None = None,
) -> tuple[str | None, str | None]:
    """Navega do modal "Medições" ate o pedido expandido (cards por
    municipio) - o de maior numero, ou `pedido_desejado` quando informado.
    `atual["pagina"]` passa a ser a aba aberta por "Ver MIPs".

    Retorna `(motivo, pedido)`: `motivo` e `None` quando o pedido foi
    expandido. Cada passo concluido chama `avancar()` e tem sua etapa
    listada em `ETAPAS_RPA_MIP`, na mesma ordem.
    """
    pagina_mips = abrir_mips(atual["pagina"])
    if pagina_mips is None:
        return "abrir_mips", None
    pagina_mips.set_default_timeout(timeout_ms)
    atual["pagina"] = pagina_mips
    avancar()  # "Abrindo MIPs"

    pedidos = listar_pedidos_mip(pagina_mips)
    if pedido_desejado:
        posicao = posicao_do_pedido(pedidos, pedido_desejado)
        if posicao is None:
            logger.error("Pedido %s nao esta no grid de MIPs. Lidos: %s", pedido_desejado, pedidos)
            return "pedido_nao_encontrado", pedido_desejado
    else:
        posicao = posicao_maior_pedido(pedidos)
        if posicao is None:
            logger.error("Nenhum pedido numerico no grid de MIPs - municipio %s. Lidos: %s", municipio, pedidos)
            return "pedidos_nao_encontrados", None
    pedido = pedidos[posicao]
    logger.info("Pedidos no grid de MIPs: %s - escolhido: %s.", pedidos, pedido)
    avancar()  # "Lendo os pedidos"

    if not expandir_pedido_mip(pagina_mips, posicao):
        return "expandir_pedido", pedido
    avancar()  # "Expandindo o pedido"
    return None, pedido


def abrir_mips(pagina, timeout_nova_aba_ms: int = 15_000):
    """Clica em "Ver MIPs" no modal de Medições (mesmo modal de "Ver OSPs",
    ja aberto por `abrir_medicoes`) e devolve a aba onde o grid de MIPs
    abriu - `None` se o botao nao apareceu.

    O portal abre o grid de MIPs em OUTRA aba; se nenhuma aba nova abrir
    dentro de `timeout_nova_aba_ms`, segue na propria aba (caso o portal
    passe a navegar na mesma aba).

    Localiza pelo texto do botao, nao pela classe (`bbdaJn2`), que e gerada
    pelo Bubble.io e pode mudar a cada publicacao do portal."""
    from playwright.sync_api import TimeoutError as PWTimeout

    logger.info("Clicando em 'Ver MIPs'...")
    try:
        botao = pagina.get_by_role("button", name="Ver MIPs")
        botao.wait_for(state="visible", timeout=10_000)
    except PWTimeout as exc:
        logger.error("Timeout ao localizar 'Ver MIPs': %s", exc)
        return None

    try:
        with pagina.context.expect_page(timeout=timeout_nova_aba_ms) as nova_aba:
            botao.click()
        pagina_mips = nova_aba.value
        logger.info("'Ver MIPs' abriu uma aba nova.")
    except PWTimeout:
        logger.warning("'Ver MIPs' nao abriu aba nova - seguindo na mesma aba.")
        pagina_mips = pagina

    try:
        pagina_mips.wait_for_load_state("load", timeout=60_000)
        pagina_mips.wait_for_load_state("networkidle", timeout=20_000)
        logger.info("Secao MIPs aberta. URL: %s", pagina_mips.url)
    except PWTimeout:
        logger.warning("networkidle nao atingido apos 'Ver MIPs', continuando.")
    return pagina_mips


# Marca cada linha/card lido com a posicao, para o clique/upload acertar
# exatamente o elemento escolhido (as classes `bcaKa...` do Bubble.io sao
# geradas e mudam a cada publicacao do portal, por isso nao sao usadas).
_ATRIBUTO_LINHA_PEDIDO = "data-rpa-mip-pedido"
_ATRIBUTO_CARD_MUNICIPIO = "data-rpa-mip-municipio"


def listar_pedidos_mip(pagina, timeout_ms: int = 30_000) -> list[str]:
    """Le a coluna "Pedido" do grid de MIPs, na ordem das linhas.

    Estrutura do portal (Bubble.io): o cabecalho com o texto "Pedido" e o
    RepeatingGroup (`.bubble-rg`) ficam no mesmo container; cada linha do
    RepeatingGroup e um `.group-item` cujo 1º texto e o numero do pedido.
    """
    from playwright.sync_api import TimeoutError as PWTimeout

    try:
        pagina.get_by_text("Pedido", exact=True).first.wait_for(state="visible", timeout=timeout_ms)
    except PWTimeout:
        logger.error("Grid de MIPs (coluna 'Pedido') nao apareceu.")
        return []

    return pagina.evaluate(
        """(atributo) => {
            const cabecalho = [...document.querySelectorAll('.bubble-element.Text')]
                .find(el => el.innerText.trim() === 'Pedido' && el.getBoundingClientRect().height > 0);
            if (!cabecalho) return [];
            const container = cabecalho.parentElement && cabecalho.parentElement.parentElement;
            const grid = container && container.querySelector('.bubble-rg');
            if (!grid) return [];
            return [...grid.querySelectorAll(':scope > .group-item')].map((linha, posicao) => {
                linha.setAttribute(atributo, String(posicao));
                const celula = linha.querySelector(':scope > .clickable-element > .bubble-element.Text');
                return celula ? celula.innerText.trim() : '';
            });
        }""",
        _ATRIBUTO_LINHA_PEDIDO,
    ) or []


def posicao_do_pedido(pedidos: list[str], numero: str) -> int | None:
    """Posicao (0-based) do pedido `numero` no grid (compara como numero,
    entao "0402" acha "402"). `None` se nao estiver no grid."""
    alvo = numero.strip()
    if not alvo.isdigit():
        return None
    for posicao, texto in enumerate(pedidos):
        if texto.isdigit() and int(texto) == int(alvo):
            return posicao
    return None


def posicao_maior_pedido(pedidos: list[str]) -> int | None:
    """Posicao (0-based) do maior numero de pedido; ignora textos nao
    numericos. `None` se nenhum for numerico."""
    numericos = [(int(texto), posicao) for posicao, texto in enumerate(pedidos) if texto.isdigit()]
    if not numericos:
        return None
    return max(numericos)[1]


def expandir_pedido_mip(pagina, posicao: int) -> bool:
    """Clica na seta (chevron-down) da linha do pedido para expandi-lo."""
    from playwright.sync_api import TimeoutError as PWTimeout

    linha = pagina.locator(f"[{_ATRIBUTO_LINHA_PEDIDO}='{posicao}']")
    try:
        seta = linha.locator("button:has(use[href*='chevron-down'])").first
        seta.wait_for(state="visible", timeout=10_000)
        seta.scroll_into_view_if_needed()
        seta.click()
    except PWTimeout as exc:
        logger.error("Timeout ao clicar na seta do pedido (posicao %s): %s", posicao, exc)
        return False

    try:
        pagina.wait_for_load_state("networkidle", timeout=20_000)
    except PWTimeout:
        logger.warning("networkidle nao atingido apos expandir o pedido, continuando.")
    return True


def listar_cards_municipio(pagina, timeout_ms: int = 30_000) -> list[dict]:
    """Le os cards de municipio do pedido expandido.

    Cada card e o `.group-item` mais interno que contem "Município:" e
    "Valor total a ser emitido" (o `.group-item` da linha do pedido tambem
    contem esses textos depois de expandido, por isso so o mais interno
    conta). Retorna [{"posicao", "municipio", "uf", "ibge", "status",
    "valor"}, ...] - ver `interpretar_card_municipio`.
    """
    from playwright.sync_api import TimeoutError as PWTimeout

    try:
        pagina.get_by_text("Valor total a ser emitido").first.wait_for(state="visible", timeout=timeout_ms)
    except PWTimeout:
        logger.error("Cards de municipio do pedido nao apareceram.")
        return []

    _carregar_todos_os_cards(pagina)

    textos: list[str] = pagina.evaluate(
        """(atributo) => {
            const ehCard = el => el.innerText.includes('Município:')
                && el.innerText.includes('Valor total a ser emitido');
            const cards = [...document.querySelectorAll('.group-item')]
                .filter(el => ehCard(el) && ![...el.querySelectorAll('.group-item')].some(ehCard));
            return cards.map((card, posicao) => {
                card.setAttribute(atributo, String(posicao));
                return card.innerText;
            });
        }""",
        _ATRIBUTO_CARD_MUNICIPIO,
    ) or []

    cards = []
    for posicao, texto in enumerate(textos):
        card = interpretar_card_municipio(texto)
        card["posicao"] = posicao
        cards.append(card)
    logger.info("Cards de municipio lidos: %s", [(c["municipio"], c["status"], c["valor"]) for c in cards])
    return cards


_JS_CONTAR_E_ROLAR_CARDS = """() => {
    const ehCard = el => el.innerText.includes('Município:')
        && el.innerText.includes('Valor total a ser emitido');
    const cards = [...document.querySelectorAll('.group-item')]
        .filter(el => ehCard(el) && ![...el.querySelectorAll('.group-item')].some(ehCard));
    if (cards.length) {
        const ultimo = cards[cards.length - 1];
        ultimo.scrollIntoView({ block: 'end' });
        const grid = ultimo.closest('.bubble-rg');
        if (grid) grid.scrollTop = grid.scrollHeight;
    }
    window.scrollTo(0, document.body.scrollHeight);
    return cards.length;
}"""


def _carregar_todos_os_cards(pagina, max_rolagens: int = 20, espera_ms: int = 1_500) -> int:
    """O RepeatingGroup do Bubble.io so renderiza mais cards conforme a
    pagina rola (execucao real, 2026-09-28: 17 de 29 cards do pedido 506
    sem rolar). Rola ate o ultimo card ate a quantidade parar de crescer
    por 2 rodadas seguidas; devolve a quantidade final."""
    anterior, estavel = -1, 0
    total = 0
    for _ in range(max_rolagens):
        total = pagina.evaluate(_JS_CONTAR_E_ROLAR_CARDS) or 0
        if total == anterior:
            estavel += 1
            if estavel >= 2:
                break
        else:
            estavel = 0
        anterior = total
        pagina.wait_for_timeout(espera_ms)
    logger.info("Cards de municipio carregados apos rolar: %s.", total)
    return total


_RE_MUNICIPIO = re.compile(r"Munic[ií]pio:\s*([^/\n]*)(?:/([^\n]*))?")
_RE_IBGE = re.compile(r"Cod\.\s*IBGE:[ \t]*(\d*)")
_RE_STATUS = re.compile(r"Status:[ \t]*([^\n]+)")
_RE_VALOR = re.compile(r"Valor total a ser emitido:\s*R\$\s*([\d.,]+)")


def interpretar_card_municipio(texto: str) -> dict:
    """Extrai os campos do texto de 1 card, no formato do portal:

        Município: PAULINIA/
        Cod. IBGE: 3510104
        Status: Aprovado
        Valor total a ser emitido: R$ 16.109,00
    """
    municipio = _RE_MUNICIPIO.search(texto)
    ibge = _RE_IBGE.search(texto)
    status = _RE_STATUS.search(texto)
    valor = _RE_VALOR.search(texto)
    return {
        "municipio": municipio.group(1).strip() if municipio else "",
        "uf": (municipio.group(2) or "").strip() if municipio else "",
        "ibge": ibge.group(1) if ibge else "",
        "status": status.group(1).strip() if status else "",
        "valor": valor.group(1) if valor else "",
    }


def normalizar_texto(texto: str) -> str:
    """Maiusculo, sem acento e sem espaco repetido - o portal mistura
    "São Paulo" e "SAO PAULO", "Cândido Rodrigues" etc."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return " ".join(sem_acento.upper().split())


normalizar_municipio = normalizar_texto


def mesmo_municipio(nome_portal: str, nome_informado: str) -> bool:
    return bool(nome_portal) and normalizar_municipio(nome_portal) == normalizar_municipio(nome_informado)


def status_pendente(status: str) -> bool:
    return normalizar_texto(status) in STATUS_PENDENTES


def status_enviado(status: str) -> bool:
    return normalizar_texto(status) in STATUS_ENVIADOS


def localizar_card_pendente(cards: list[dict], valor_pdf: str) -> tuple[dict | None, str | None]:
    """Escolhe, entre os cards do municipio, o pendente cujo valor bate com
    o do PDF.

    Retorna `(card, None)` quando ha exatamente 1 candidato, ou
    `(card_de_referencia, motivo)` em caso de falha - o card de referencia
    (ou `None`) so serve para registrar o valor visto no portal. O mesmo
    municipio pode aparecer em mais de um card (ex.: "São Paulo" e
    "SAO PAULO", com valores diferentes) - o valor desempata; com 2+
    candidatos de mesmo valor, recusa em vez de adivinhar.
    """
    pendentes = [card for card in cards if status_pendente(card["status"])]
    if not pendentes:
        return None, "documento_ja_enviado"

    candidatos = [card for card in pendentes if valores_iguais(valor_pdf, card["valor"])]
    if not candidatos:
        return pendentes[0], "valor_divergente"
    if len(candidatos) > 1:
        return candidatos[0], "valor_ambiguo"
    return candidatos[0], None


def destacar_card(pagina, posicao: int) -> None:
    """Rola ate o card e contorna em laranja (modo de validacao)."""
    from .dashboard import _ir_para_linha

    _ir_para_linha(pagina, pagina.locator(f"[{_ATRIBUTO_CARD_MUNICIPIO}='{posicao}']"))


def anexar_pdf_no_card(pagina, posicao: int, caminho_pdf: str) -> bool:
    """Anexa o PDF no campo "Arquivo da Nota Fiscal" do card (o
    `input[type='file']` do card) e confirma o modal pos-upload se o
    portal abrir um. A confirmacao de que o portal aceitou fica em
    `confirmar_envio_card`."""
    from .dashboard import _confirmar_modal_pos_upload, _ir_para_linha, _set_arquivo

    card = pagina.locator(f"[{_ATRIBUTO_CARD_MUNICIPIO}='{posicao}']")
    _ir_para_linha(pagina, card)

    logger.info("    PDF upload...")
    if not _set_arquivo(pagina, card.locator("input[type='file']").first, caminho_pdf, "PDF"):
        return False

    pagina.wait_for_timeout(2_000)
    _confirmar_modal_pos_upload(pagina)
    return True


def confirmar_envio_card(pagina, posicao: int, timeout_ms: int = 30_000, intervalo_ms: int = 1_000) -> str:
    """Rele o status do card ate ele sair de "Pendente" para "Aguardando
    Aprovação"/"Aprovado" (ou estourar `timeout_ms`) e devolve o ultimo
    status lido - o chamador decide com `status_enviado`."""
    card = pagina.locator(f"[{_ATRIBUTO_CARD_MUNICIPIO}='{posicao}']")
    status = ""
    decorrido = 0
    while True:
        try:
            status = interpretar_card_municipio(card.inner_text(timeout=5_000))["status"]
        except Exception as exc:
            logger.warning("    Nao foi possivel reler o status do card: %s", exc)
        if status_enviado(status) or decorrido >= timeout_ms:
            break
        pagina.wait_for_timeout(intervalo_ms)
        decorrido += intervalo_ms
    logger.info("    Status do card apos o upload: %s", status or "(nao lido)")
    return status


def _falhar(
    pagina, municipio: str, motivo: str, dados_pdf: dict, valor_portal: str | None = None, pedido: str | None = None,
) -> ResultadoRpaMip:
    """Loga e tira um screenshot de diagnostico antes de devolver o erro."""
    logger.error("RPA MIP encerrado com erro (%s) - municipio %s.", motivo, municipio)
    try:
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        nome = re.sub(r"[^A-Z0-9]+", "_", normalizar_municipio(municipio)).strip("_") or "sem_municipio"
        pagina.screenshot(
            path=str(SCREENSHOTS_DIR / f"erro_mip_{motivo}_{nome}_{timestamp}.png"),
            full_page=True,
        )
    except Exception:
        pass
    return ResultadoRpaMip(
        sucesso=False, motivo=motivo, dados_pdf=dados_pdf, valor_portal=valor_portal, pedido=pedido,
    )


def _encerrar(contexto, navegador) -> None:
    try:
        contexto.close()
        navegador.close()
    except Exception:
        pass
