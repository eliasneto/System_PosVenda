"""RPA do BDO: anexa o PDF da Nota Fiscal de um municipio no portal EACE.

Modulo independente - ainda nao e chamado por nenhuma tela, fila ou
comando do sistema (so pelo comando de validacao `validar_rpa_bdo`).

Mesmo processo do RPA do MIP (pedido do usuario, 2026-10-16), mudando so
o caminho ate os cards - caminho conferido no portal em 2026-10-16:
  1. le o valor do PDF antes de abrir o navegador;
  2. login -> "Fornecedor" -> "Medições";
  3. "Ver BDOs" (mesmo modal de "Ver MIPs") abre, na mesma aba, o grid de
     pedidos; o numero do pedido e o numero do Boletim (borderô) e e
     obrigatorio - nao ha "pedido mais recente" como no MIP;
  4. o pedido expandido mostra Historico e as secoes "Dados do contrato",
     "Medições", "Anexos" e "Notas Fiscais"; os cards por municipio
     (Municipio/UF, Status, "Valor total a ser emitido" e "Arquivo da Nota
     Fiscal" - mesmo layout do MIP) ficam dentro de "Notas Fiscais";
  5. filtra os cards do municipio (e da UF, quando informada), valida
     status e valor e anexa somente o PDF no card escolhido.

Leitura dos cards, validacao e upload sao os mesmos helpers do RPA do MIP
(`.rpa_mip`), reaproveitados sem alterar.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from .config import SCREENSHOTS_DIR, ConfigEace, args_chromium
from .rpa_mip import (
    CapturasRpaMip,
    ResultadoRpaMip,
    RpaMipIndisponivel,
    _ATRIBUTO_CARD_MUNICIPIO,
    _ATRIBUTO_LINHA_PEDIDO,
    _encerrar,
    cards_do_municipio,
    confirmar_envio_card,
    destacar_card,
    expandir_pedido_mip,
    extrair_dados_nf_mip,
    listar_cards_municipio,
    listar_pedidos_mip,
    localizar_card_pendente,
    normalizar_municipio,
    normalizar_texto,
    posicao_do_pedido,
    status_enviado,
    status_pendente,
)

logger = logging.getLogger(__name__)

RpaBdoIndisponivel = RpaMipIndisponivel
ResultadoRpaBdo = ResultadoRpaMip

# NF do BDO e NFCom (fatura de servico de comunicacao), nao NF-e/NFS-e: o valor
# vem em "TOTAL A PAGAR: R$ 1.120,20" ou "VALOR TOTAL NF 1.120,20" (layout
# conferido nas NFs do Boletim 3657, 2026-11-13).
_RES_VALOR_NFCOM = (
    re.compile(r"TOTAL A PAGAR:\s*R\$\s*([\d.]+,\d{2})"),
    re.compile(r"VALOR TOTAL NF\s+([\d.]+,\d{2})"),
)


def extrair_valor_nfcom(texto: str) -> str:
    for regex in _RES_VALOR_NFCOM:
        encontrado = regex.search(texto or "")
        if encontrado:
            return encontrado.group(1)
    return ""


def extrair_dados_nf_bdo(caminho_pdf: str) -> dict:
    """`extrair_dados_nf_mip` + o valor da NFCom (layout das NFs do BDO)."""
    from .extrair_dados_pdf import extrair_texto_pdf

    dados = extrair_dados_nf_mip(caminho_pdf)
    if not dados["valor"]:
        dados["valor"] = extrair_valor_nfcom(extrair_texto_pdf(caminho_pdf))
    return dados

# Motivos possiveis em ResultadoRpaBdo.motivo quando sucesso=False - os
# mesmos do MIP (`rpa_mip`), com estas diferencas:
#   abrir_bdos               - botao "Ver BDOs" nao encontrado no modal de Medições
#   pedido_nao_encontrado    - numero do Boletim informado nao esta no grid de BDOs
#   abrir_notas_fiscais      - secao "Notas Fiscais" do pedido nao respondeu
#   notas_fiscais_sem_cards  - secao "Notas Fiscais" aberta, mas sem nenhum card
#                              (o BDO ainda nao chegou na emissao da NF)
#   campos_nf_em_branco      - depois do upload o portal nao preencheu "Data emissão NF", "Valor a ser medido"
#                              e "Valor bruto da nota" a tempo - o RPA NAO confirma (correcao 2026-11-17)
#   descricao_em_branco      - "Descrição" em branco num Boletim que nao e RE (so o RE tem texto padrao)
MOTIVOS_REGRA_DE_NEGOCIO_BDO = frozenset({
    "descricao_em_branco",
    "pdf_sem_valor",
    "pedidos_nao_encontrados",
    "pedido_nao_encontrado",
    "notas_fiscais_sem_cards",
    "municipio_nao_encontrado",
    "documento_ja_enviado",
    "valor_divergente",
    "valor_ambiguo",
    "envio_nao_confirmado",
})

ETAPAS_RPA_BDO = (
    "Lendo os dados da Nota Fiscal",
    "Abrindo o portal EACE",
    "Preenchendo usuário",
    "Preenchendo senha",
    "Aguardando o portal responder",
    "Selecionando o perfil Fornecedor",
    "Abrindo Medições",
    "Abrindo BDOs",
    "Lendo os pedidos",
    "Expandindo o pedido",
    "Abrindo Notas Fiscais",
    "Lendo os municípios do pedido",
    "Conferindo status e valor",
    "Anexando o PDF",
    "Confirmando o envio",
)


class ProgressoRpaBdo:
    """Avanca 1 posicao em `ETAPAS_RPA_BDO` a cada `avancar()` e chama
    `callback(etapa, percentual)`; falha no callback so e logada."""

    def __init__(self, callback=None):
        self._callback = callback
        self._indice = 0

    def avancar(self) -> str | None:
        if self._indice >= len(ETAPAS_RPA_BDO):
            return None
        etapa = ETAPAS_RPA_BDO[self._indice]
        self._indice += 1
        percentual = round(self._indice / len(ETAPAS_RPA_BDO) * 100)
        if self._callback:
            try:
                self._callback(etapa, percentual)
            except Exception:
                logger.exception("Erro ao reportar progresso do RPA BDO (etapa: %s).", etapa)
        return etapa


def anexar_pdf_bdo(
    *,
    pedido: str,
    municipio: str | None,
    caminho_pdf: str | None,
    uf: str | None = None,
    config: ConfigEace | None = None,
    progresso_callback=None,
    simular: bool = False,
    pasta_capturas=None,
    headless: bool | None = None,
    lento_ms: int = 0,
    gravar_video: bool = False,
    descricao_padrao: str | None = None,
) -> ResultadoRpaBdo:
    """Anexa o PDF da Nota Fiscal no card do `municipio` (secao "Notas
    Fiscais" do pedido `pedido` = numero do Boletim) cujo status esta
    pendente e cujo "Valor total a ser emitido" bate com o valor do PDF.

    `uf` (opcional) restringe os cards a essa UF - o BDO mistura estados
    (ex.: "Campo Grande/MS" e municipios de SP no mesmo pedido).

    `descricao_padrao`: texto da "Descrição" do modal "Enviar nota fiscal"
    quando o portal a deixa em branco - so no Boletim RE
    (`DESCRICAO_PADRAO_BDO_RE`); sem ele, descricao em branco nao e enviada.

    Opcoes do modo de validacao: as mesmas de `rpa_mip.anexar_pdf_mip`.
    So em `simular=True`, `caminho_pdf` e `municipio` podem ser `None`.
    """
    if not (pedido or "").strip().isdigit():
        raise ValueError("O numero do Boletim (pedido) e obrigatorio e deve ter so numeros.")
    if not simular and not (caminho_pdf and municipio):
        raise ValueError("Anexar de verdade exige municipio e caminho_pdf - so a simulacao aceita sem eles.")
    pedido = pedido.strip()
    municipio = municipio or ""
    progresso = ProgressoRpaBdo(progresso_callback)
    capturas = CapturasRpaMip(pasta_capturas) if pasta_capturas else None
    try:
        import pdfplumber  # noqa: F401  (so para falhar cedo se faltar)
        from playwright.sync_api import Error as PlaywrightError, sync_playwright

        from .dashboard import abrir_medicoes, motivo_falha_navegacao
        from .login import fazer_login, selecionar_perfil_fornecedor
    except ImportError as exc:
        raise RpaBdoIndisponivel(
            "Playwright/pdfplumber nao instalados - rode "
            "'pip install -r requirements.txt' e "
            "'python -m playwright install chromium'."
        ) from exc

    dados_pdf = extrair_dados_nf_bdo(caminho_pdf) if caminho_pdf else {}
    progresso.avancar()  # "Lendo os dados da Nota Fiscal"

    if caminho_pdf:
        if dados_pdf["ilegivel"]:
            return ResultadoRpaBdo(sucesso=False, motivo="pdf_ilegivel", dados_pdf=dados_pdf, pedido=pedido)
        if not dados_pdf["valor"]:
            return ResultadoRpaBdo(sucesso=False, motivo="pdf_sem_valor", dados_pdf=dados_pdf, pedido=pedido)

    cfg = config or ConfigEace.carregar()
    if not cfg.usuario or not cfg.senha:
        logger.error("EACE_USUARIO/EACE_SENHA nao configurados no .env - abortando.")
        return ResultadoRpaBdo(sucesso=False, motivo="credenciais_ausentes", dados_pdf=dados_pdf, pedido=pedido)

    headless = cfg.headless if headless is None else headless
    logger.info(
        "Iniciando RPA BDO | pedido=%s municipio=%s uf=%s headless=%s simular=%s",
        pedido, municipio, uf, headless, simular,
    )

    try:
        with sync_playwright() as p:
            navegador = p.chromium.launch(
                headless=headless,
                slow_mo=lento_ms,
                args=args_chromium(headless),
            )
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
            atual = {"pagina": pagina}

            def avancar() -> None:
                etapa = progresso.avancar()
                if capturas and etapa:
                    capturas.salvar(atual["pagina"], etapa)

            def falhar(motivo, valor_portal=None):
                if capturas:
                    capturas.salvar(atual["pagina"], f"Erro {motivo}")
                return _falhar(atual["pagina"], pedido, municipio, motivo, dados_pdf, valor_portal)

            try:
                pagina.goto(cfg.url, wait_until="load", timeout=60_000)
                avancar()  # "Abrindo o portal EACE"

                if not fazer_login(pagina, cfg.usuario, cfg.senha, avancar):
                    return falhar("login")

                if not selecionar_perfil_fornecedor(pagina):
                    return falhar("selecao_perfil")
                avancar()  # "Selecionando o perfil Fornecedor"

                if not abrir_medicoes(pagina):
                    return falhar(motivo_falha_navegacao(pagina, "abrir_medicoes"))
                avancar()  # "Abrindo Medições"

                motivo = _navegar_caminho_bdo(atual, pedido, avancar, cfg.timeout_ms)
                if motivo:
                    return falhar(motivo)
                pagina = atual["pagina"]

                todos_os_cards = listar_cards_municipio(pagina)
                if not todos_os_cards:
                    return falhar("notas_fiscais_sem_cards")
                anotar_arquivos_nf(pagina, todos_os_cards)
                cards = cards_do_municipio_uf(todos_os_cards, municipio, uf)
                if not cards:
                    resultado = falhar("municipio_nao_encontrado")
                    resultado.cards_encontrados = todos_os_cards
                    return resultado
                avancar()  # "Lendo os municípios do pedido"

                if not caminho_pdf:
                    if municipio:
                        destacar_card(pagina, cards[0]["posicao"])
                    if capturas:
                        capturas.salvar(pagina, "Sem PDF cards do pedido")
                    logger.info(
                        "RPA BDO (simulacao sem PDF) - pedido=%s: %s card(s) lido(s), %s do municipio '%s'.",
                        pedido, len(todos_os_cards), len(cards), municipio,
                    )
                    return ResultadoRpaBdo(
                        sucesso=True, dados_pdf=dados_pdf, pedido=pedido, simulado=True,
                        cards_encontrados=todos_os_cards,
                    )

                card_alvo, motivo = localizar_card_pendente(cards, dados_pdf["valor"], aceita=status_aceita_nf_bdo)
                if motivo:
                    resultado = falhar(motivo, card_alvo["valor"] if card_alvo else None)
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
                        "RPA BDO (simulacao) - pedido=%s municipio=%s valor=%s: PDF NAO anexado.",
                        pedido, card_alvo["municipio"], card_alvo["valor"],
                    )
                    return ResultadoRpaBdo(
                        sucesso=True, dados_pdf=dados_pdf, valor_portal=card_alvo["valor"],
                        pedido=pedido, simulado=True, cards_encontrados=todos_os_cards,
                    )

                motivo = anexar_pdf_no_card_bdo(pagina, card_alvo["posicao"], caminho_pdf, descricao_padrao)
                if motivo:
                    return falhar(motivo, card_alvo["valor"])
                avancar()  # "Anexando o PDF"

                status_final = confirmar_envio_card(pagina, card_alvo["posicao"])
                if not status_enviado(status_final):
                    logger.error(
                        "Card do municipio %s continua '%s' depois do upload - envio nao confirmado.",
                        card_alvo["municipio"], status_final,
                    )
                    return falhar("envio_nao_confirmado", card_alvo["valor"])
                avancar()  # "Confirmando o envio" -> 100%

                logger.info("RPA BDO concluido - pedido=%s municipio=%s.", pedido, card_alvo["municipio"])
                return ResultadoRpaBdo(
                    sucesso=True, dados_pdf=dados_pdf, valor_portal=card_alvo["valor"], pedido=pedido,
                )
            finally:
                _encerrar(contexto, navegador)

    except PlaywrightError as exc:
        logger.error("Erro inesperado do Playwright: %s", exc)
        return ResultadoRpaBdo(sucesso=False, motivo="erro_playwright", dados_pdf=dados_pdf, pedido=pedido)


# Pedido do usuario (2026-11-17): NF devolvida pelo cliente deixa o card "Reprovado" - o BDO reenvia nele (o
# MIP e o RI continuam so em "Pendente").
STATUS_REPROVADO = "REPROVADO"


def status_aceita_nf_bdo(status: str) -> bool:
    return status_pendente(status) or normalizar_texto(status) == STATUS_REPROVADO


# Pedido do usuario (2026-11-17): o cliente devolveu as NFs do BDO enviadas com campos em branco no modal
# "Enviar nota fiscal". O portal preenche os campos sozinho depois do upload, mas as vezes demora, e o RPA
# confirmava antes (espera fixa de ~4,5 s). Agora espera os campos e, so no BDO RE, completa a Descricao.
DESCRICAO_PADRAO_BDO_RE = "MENSALIDADE ASSINATURA DE ACESSO BDO RE"
CAMPO_DATA_EMISSAO = "Data emissão NF"
CAMPO_VALOR_MEDIDO = "Valor a ser medido"
CAMPO_VALOR_BRUTO = "Valor bruto da nota"
CAMPO_DESCRICAO = "Descrição"
CAMPOS_OBRIGATORIOS_NF_BDO = (CAMPO_DATA_EMISSAO, CAMPO_VALOR_MEDIDO, CAMPO_VALOR_BRUTO)
_ATRIBUTO_CAMPO_NF = "data-rpa-bdo-campo"

# Le o valor de cada campo do modal pelo rotulo (sem depender de id/classe do portal): acha o menor bloco que
# contem todos os rotulos (o formulario do modal) e, para cada rotulo, o 1o input/textarea depois dele no
# mesmo grupo. Marca o campo com `data-rpa-bdo-campo` para o Playwright preencher. Campo nao achado -> null.
_JS_LER_CAMPOS_NF = """({rotulos, atributo}) => {
  const norm = s => (s || '').normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').replace(/\\s+/g, ' ').trim().toLowerCase();
  const visivel = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const alvos = rotulos.map(norm);
  let raiz = null;
  for (const el of document.querySelectorAll('body *')) {
    if (!visivel(el)) continue;
    const texto = norm(el.textContent);
    if (alvos.every(a => texto.includes(a)) && (!raiz || el.textContent.length < raiz.textContent.length)) raiz = el;
  }
  const resultado = {};
  rotulos.forEach((rotulo, i) => { resultado[rotulo] = null; });
  if (!raiz) return resultado;
  const campoDe = rotuloEl => {
    let atual = rotuloEl;
    for (let nivel = 0; nivel < 5 && atual && atual !== raiz.parentElement; nivel++, atual = atual.parentElement) {
      const campos = [...atual.querySelectorAll('input:not([type=hidden]):not([type=file]), textarea')].filter(visivel);
      const depois = campos.find(c => rotuloEl.compareDocumentPosition(c) & Node.DOCUMENT_POSITION_FOLLOWING);
      if (depois) return depois;
    }
    return null;
  };
  rotulos.forEach((rotulo, i) => {
    const alvo = alvos[i];
    const candidatos = [...raiz.querySelectorAll('*')].filter(el => {
      const texto = norm(el.textContent);
      return visivel(el) && texto.startsWith(alvo) && texto.length <= alvo.length + 40;
    }).sort((a, b) => a.textContent.length - b.textContent.length);
    for (const rotuloEl of candidatos) {
      const campo = campoDe(rotuloEl);
      if (campo) {
        campo.setAttribute(atributo, String(i));
        resultado[rotulo] = campo.value == null ? '' : String(campo.value);
        return;
      }
    }
  });
  return resultado;
}"""


def campo_nf_preenchido(valor: str | None) -> bool:
    """Valor de campo do modal preenchido: nao vazio e, se for numero/moeda, diferente de zero ("R$0,00")."""
    texto = (valor or "").strip()
    if not texto:
        return False
    if re.fullmatch(r"(R\$)?\s*[\d.,\s]+", texto):
        return bool(re.sub(r"\D", "", texto).strip("0"))
    return True


def ler_campos_nf_bdo(pagina) -> dict[str, str | None]:
    rotulos = [*CAMPOS_OBRIGATORIOS_NF_BDO, CAMPO_DESCRICAO]
    try:
        return pagina.evaluate(_JS_LER_CAMPOS_NF, {"rotulos": rotulos, "atributo": _ATRIBUTO_CAMPO_NF})
    except Exception as exc:  # pagina navegando/fechando: le de novo no proximo ciclo
        logger.warning("    Nao foi possivel ler os campos do modal: %s", exc)
        return {rotulo: None for rotulo in rotulos}


def aguardar_campos_nf_bdo(
    pagina, descricao_padrao: str | None = None, timeout_ms: int = 90_000, intervalo_ms: int = 1_000,
    espera_descricao_ms: int = 10_000, espera_minima_ms: int = 10_000,
) -> str | None:
    """Espera o portal preencher "Data emissão NF", "Valor a ser medido" e "Valor bruto da nota" (2 leituras
    iguais seguidas, para nao pegar o campo no meio do preenchimento). Depois, se a "Descrição" continuar em
    branco por `espera_descricao_ms`: preenche com `descricao_padrao` (BDO RE) ou devolve "descricao_em_branco".
    Nunca antes de `espera_minima_ms` depois do upload (pedido do usuario, 2026-11-17): o portal leva uns 10 s
    para trazer os dados de todos os campos (impostos, valor liquido), mesmo com os 3 obrigatorios ja na tela.
    Devolve o motivo da falha ou `None` (pode confirmar)."""
    decorrido, anterior, campos = 0, None, {}
    while True:
        campos = ler_campos_nf_bdo(pagina)
        obrigatorios = {rotulo: campos.get(rotulo) for rotulo in CAMPOS_OBRIGATORIOS_NF_BDO}
        if (all(campo_nf_preenchido(valor) for valor in obrigatorios.values()) and obrigatorios == anterior
                and decorrido >= espera_minima_ms):
            break
        anterior = obrigatorios
        if decorrido >= timeout_ms:
            logger.error("    Portal nao preencheu os campos da NF em %ss: %s", timeout_ms // 1000, campos)
            return "campos_nf_em_branco"
        pagina.wait_for_timeout(intervalo_ms)
        decorrido += intervalo_ms
    logger.info("    Campos da NF preenchidos pelo portal: %s", campos)

    esperou = 0
    while not (campos.get(CAMPO_DESCRICAO) or "").strip() and esperou < espera_descricao_ms:
        pagina.wait_for_timeout(intervalo_ms)
        esperou += intervalo_ms
        campos = ler_campos_nf_bdo(pagina)
    if (campos.get(CAMPO_DESCRICAO) or "").strip():
        return None
    if not descricao_padrao:
        logger.error("    Descricao da NF em branco (Boletim sem texto padrao) - nao confirma.")
        return "descricao_em_branco"
    if campos.get(CAMPO_DESCRICAO) is None:
        logger.error("    Campo Descricao nao encontrado no modal - nao confirma.")
        return "campos_nf_em_branco"
    indice = [*CAMPOS_OBRIGATORIOS_NF_BDO, CAMPO_DESCRICAO].index(CAMPO_DESCRICAO)
    campo = pagina.locator(f"[{_ATRIBUTO_CAMPO_NF}='{indice}']").first
    try:
        # Digitado tecla por tecla e saindo do campo (Tab): o portal (Bubble) ignora o `fill` - o texto sumia e o
        # "Confirmar informações" seguia desativado (teste real no Boletim 3851, 2026-11-17).
        campo.click()
        campo.press_sequentially(descricao_padrao, delay=30)
        campo.press("Tab")
        pagina.wait_for_timeout(1_500)
        preenchido = campo.input_value(timeout=5_000).strip()
    except Exception as exc:
        logger.error("    Erro ao preencher a Descricao: %s", exc)
        return "descricao_em_branco"
    if preenchido != descricao_padrao:
        logger.error("    Descricao nao ficou gravada no campo (lido: %r).", preenchido)
        return "descricao_em_branco"
    logger.info("    Descricao em branco preenchida com o texto padrao: %s", descricao_padrao)
    return None


TITULO_MODAL_NF = "Enviar nota fiscal"
BOTAO_CONFIRMAR_NF = "Confirmar informações"
BOTAO_REENVIAR_NF = "Reenviar nota"


def confirmar_modal_nf_bdo(pagina, timeout_ms: int = 20_000) -> bool:
    """Clica em "Confirmar informações" e espera o modal fechar - aberto ainda = o portal nao aceitou."""
    try:
        pagina.locator(f"button:has-text('{BOTAO_CONFIRMAR_NF}')").filter(visible=True).last.click(timeout=10_000)
    except Exception as exc:
        logger.error("    Botao '%s' nao clicado: %s", BOTAO_CONFIRMAR_NF, exc)
        return False
    titulo = pagina.get_by_text(TITULO_MODAL_NF).filter(visible=True)
    for _ in range(timeout_ms // 1_000):
        if not titulo.count():
            logger.info("    [Modal] Informacoes confirmadas.")
            return True
        pagina.wait_for_timeout(1_000)
    logger.error("    Modal '%s' continua aberto depois de confirmar.", TITULO_MODAL_NF)
    return False


def anexar_pdf_no_card_bdo(pagina, posicao: int, caminho_pdf: str, descricao_padrao: str | None = None) -> str | None:
    """Anexa o PDF no card e so confirma o modal "Enviar nota fiscal" depois que os campos estao preenchidos
    (`aguardar_campos_nf_bdo`). No card Reprovado (NF devolvida) o portal ainda pede "Reenviar nota" depois do
    modal - sem ele o card continua Reprovado (teste real no Boletim 3851, 2026-11-17). Devolve o motivo da
    falha ou `None`."""
    from .dashboard import _ir_para_linha, _set_arquivo

    card = pagina.locator(f"[{_ATRIBUTO_CARD_MUNICIPIO}='{posicao}']")
    _ir_para_linha(pagina, card)
    logger.info("    PDF upload...")
    campo_arquivo = card.locator("input[type='file']").first
    try:
        visivel = campo_arquivo.is_visible()
    except Exception:
        visivel = False
    if visivel:
        anexou = _set_arquivo(pagina, campo_arquivo, caminho_pdf, "PDF")
    else:  # card Reprovado: o campo existe escondido (o clique esperaria 30 s a toa)
        try:
            campo_arquivo.set_input_files(caminho_pdf)
            logger.info("    PDF anexado via set_input_files (campo escondido): %s", caminho_pdf)
            anexou = True
        except Exception as exc:
            logger.error("    Erro ao anexar PDF: %s", exc)
            anexou = False
    if not anexou:
        return "upload"
    motivo = aguardar_campos_nf_bdo(pagina, descricao_padrao)
    if motivo:
        return motivo
    if not confirmar_modal_nf_bdo(pagina):
        return "envio_nao_confirmado"
    pagina.wait_for_timeout(1_500)
    reenviar = card.locator(f"button:has-text('{BOTAO_REENVIAR_NF}')").filter(visible=True)
    if reenviar.count():
        reenviar.first.click()
        logger.info("    Card Reprovado: '%s' clicado.", BOTAO_REENVIAR_NF)
    return None


def ler_cards_bdo(pedido: str, progresso_callback=None) -> ResultadoRpaBdo:
    """Só leitura: abre "Notas Fiscais" do Boletim `pedido` e devolve
    todos os cards em `cards_encontrados` (com "arquivo"), sem anexar nada."""
    return anexar_pdf_bdo(
        pedido=pedido, municipio=None, caminho_pdf=None, simular=True, progresso_callback=progresso_callback,
    )


_RE_ARQUIVO_NF = re.compile(r"^[^\n]*\S\.pdf\b[^\n]*$", re.IGNORECASE | re.MULTILINE)


def arquivo_nf_do_card(texto: str) -> str:
    """Nome do PDF anexado no campo "Arquivo da Nota Fiscal" do card
    (ex.: "504_13-10-2026_NOME_MEGA INFRA.pdf"); vazio sem PDF."""
    encontrado = _RE_ARQUIVO_NF.search(texto or "")
    return encontrado.group(0).strip() if encontrado else ""


def anotar_arquivos_nf(pagina, cards: list[dict]) -> None:
    """Acrescenta "arquivo" em cada card, relendo o texto dos cards já
    marcados por `listar_cards_municipio` (1 só `evaluate`)."""
    try:
        textos = pagina.evaluate(
            """(atributo) => Object.fromEntries([...document.querySelectorAll(`[${atributo}]`)]
                .map(card => [card.getAttribute(atributo), card.innerText]))""",
            _ATRIBUTO_CARD_MUNICIPIO,
        )
    except Exception as exc:
        logger.warning("Nao foi possivel ler o arquivo da NF dos cards: %s", exc)
        textos = {}
    if not isinstance(textos, dict):
        textos = {}
    for card in cards:
        card["arquivo"] = arquivo_nf_do_card(textos.get(str(card["posicao"]), ""))


def _navegar_caminho_bdo(atual: dict, pedido: str, avancar, timeout_ms: int) -> str | None:
    """Navega do modal "Medições" ate a secao "Notas Fiscais" aberta no
    pedido `pedido`. Devolve o motivo da falha ou `None`. Cada passo
    concluido chama `avancar()`, na ordem de `ETAPAS_RPA_BDO`."""
    pagina_bdos = abrir_bdos(atual["pagina"])
    if pagina_bdos is None:
        return "abrir_bdos"
    pagina_bdos.set_default_timeout(timeout_ms)
    atual["pagina"] = pagina_bdos
    avancar()  # "Abrindo BDOs"

    pedidos = listar_pedidos_mip(pagina_bdos)
    if not pedidos:
        return "pedidos_nao_encontrados"
    posicao = posicao_do_pedido(pedidos, pedido)
    if posicao is None:
        logger.error("Pedido %s nao esta no grid de BDOs. Lidos: %s", pedido, pedidos)
        return "pedido_nao_encontrado"
    logger.info("Pedidos no grid de BDOs: %s - escolhido: %s.", pedidos, pedido)
    avancar()  # "Lendo os pedidos"

    if not expandir_pedido_mip(pagina_bdos, posicao):
        return "expandir_pedido"
    avancar()  # "Expandindo o pedido"

    if not abrir_notas_fiscais(pagina_bdos, posicao):
        return "abrir_notas_fiscais"
    avancar()  # "Abrindo Notas Fiscais"
    return None


def abrir_bdos(pagina, timeout_nova_aba_ms: int = 5_000):
    """Clica em "Ver BDOs" no modal de Medições e devolve a aba do grid de
    BDOs - `None` se o botao nao apareceu. Em 2026-10-16 o portal abriu o
    grid na mesma aba (o de MIPs abre outra); se passar a abrir aba nova,
    segue nela."""
    from playwright.sync_api import TimeoutError as PWTimeout

    logger.info("Clicando em 'Ver BDOs'...")
    try:
        botao = pagina.get_by_role("button", name="Ver BDOs")
        botao.wait_for(state="visible", timeout=10_000)
    except PWTimeout as exc:
        logger.error("Timeout ao localizar 'Ver BDOs': %s", exc)
        return None

    try:
        with pagina.context.expect_page(timeout=timeout_nova_aba_ms) as nova_aba:
            botao.click()
        pagina_bdos = nova_aba.value
        logger.info("'Ver BDOs' abriu uma aba nova.")
    except PWTimeout:
        pagina_bdos = pagina

    try:
        pagina_bdos.wait_for_load_state("load", timeout=60_000)
        pagina_bdos.wait_for_load_state("networkidle", timeout=20_000)
        logger.info("Secao BDOs aberta. URL: %s", pagina_bdos.url)
    except PWTimeout:
        logger.warning("networkidle nao atingido apos 'Ver BDOs', continuando.")
    return pagina_bdos


def abrir_notas_fiscais(pagina, posicao: int, timeout_ms: int = 15_000) -> bool:
    """Clica no titulo da secao "Notas Fiscais" do pedido expandido (as
    secoes sao acordeoes fechados) e espera o 1º card aparecer. Sem card
    no tempo, devolve True assim mesmo - `listar_cards_municipio` decide
    (`notas_fiscais_sem_cards`)."""
    from playwright.sync_api import TimeoutError as PWTimeout

    linha = pagina.locator(f"[{_ATRIBUTO_LINHA_PEDIDO}='{posicao}']")
    titulo = linha.get_by_text("Notas Fiscais", exact=True)
    try:
        if not titulo.count():
            titulo = pagina.get_by_text("Notas Fiscais", exact=True)
        titulo = titulo.first
        titulo.wait_for(state="visible", timeout=timeout_ms)
        titulo.scroll_into_view_if_needed()
        titulo.click()
    except PWTimeout as exc:
        logger.error("Timeout ao abrir a secao 'Notas Fiscais' do pedido: %s", exc)
        return False

    try:
        pagina.get_by_text("Valor total a ser emitido").first.wait_for(state="visible", timeout=timeout_ms)
    except PWTimeout:
        logger.warning("Secao 'Notas Fiscais' aberta, mas nenhum card apareceu em %sms.", timeout_ms)
    return True


def cards_do_municipio_uf(cards: list[dict], municipio: str, uf: str | None) -> list[dict]:
    """`rpa_mip.cards_do_municipio` + filtro de UF quando informada (card
    sem UF no portal nao e descartado)."""
    encontrados = cards_do_municipio(cards, municipio)
    if not uf:
        return encontrados
    alvo = normalizar_texto(uf)
    return [card for card in encontrados if not card["uf"] or normalizar_texto(card["uf"]) == alvo]


def _falhar(
    pagina, pedido: str, municipio: str, motivo: str, dados_pdf: dict, valor_portal: str | None = None,
) -> ResultadoRpaBdo:
    """Loga e tira um screenshot de diagnostico antes de devolver o erro."""
    logger.error("RPA BDO encerrado com erro (%s) - pedido %s municipio %s.", motivo, pedido, municipio)
    try:
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        nome = re.sub(r"[^A-Z0-9]+", "_", normalizar_municipio(municipio)).strip("_") or "sem_municipio"
        pagina.screenshot(
            path=str(SCREENSHOTS_DIR / f"erro_bdo_{motivo}_{pedido}_{nome}_{timestamp}.png"),
            full_page=True,
        )
    except Exception:
        pass
    return ResultadoRpaBdo(
        sucesso=False, motivo=motivo, dados_pdf=dados_pdf, valor_portal=valor_portal, pedido=pedido,
    )
