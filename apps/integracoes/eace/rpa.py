"""Orquestracao do RPA de anexo de Nota Fiscal no portal EACE.

Nucleo da automacao (FEAT-033, `ADR-004`, `RN-056`/`RN-057`): extrai os
dados da NF do PDF, login, navegacao ate a OSP/INEP, valida os dados
extraidos contra o portal e upload de 1 par PDF+XML. Usado hoje (Fase 1)
pelo management command `eace_anexar_nota_fiscal` (terminal); a Fase 2
chamara a mesma funcao `anexar_nota_fiscal` a partir do log por Nota
Fiscal, exibindo `ResultadoRpaEace.dados_pdf` no proprio log (RN-057) e
gravando `motivo` quando o resultado nao for sucesso.

`playwright`/`pdfplumber` (e os modulos `.dashboard`/`.login`, que
importam `playwright.sync_api` no proprio topo) so sao importados dentro
da funcao `anexar_nota_fiscal`, nunca no topo deste modulo - assim
`manage.py` inteiro nao quebra se alguma lib nao estiver instalada. Mesmo
padrao defensivo ja usado para `python-ldap` em
`apps/integracoes/ad/ad_sync.py`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from .config import SCREENSHOTS_DIR, ConfigEace
from .extrair_dados_pdf import extrair_dados_nota_fiscal, valores_iguais

logger = logging.getLogger(__name__)


class RpaEaceIndisponivel(Exception):
    """`playwright`/`pdfplumber` nao instalados, ou navegador Chromium
    ausente (`playwright install chromium`) - falha de ambiente, nao do
    portal nem da Nota Fiscal."""


@dataclass
class ResultadoRpaEace:
    """Resultado de 1 execucao do RPA (RN-056/RN-057).

    `dados_pdf` vem preenchido sempre que o PDF pelo menos foi lido
    (mesmo em erro depois disso) - e o que a Fase 2 exibe no log da Nota
    Fiscal (RN-057), antes e independente do resultado do upload.
    """

    sucesso: bool
    motivo: str | None = None
    dados_pdf: dict | None = None
    valor_portal: str | None = None


# Motivos possiveis em ResultadoRpaEace.motivo quando sucesso=False:
#   pdf_ilegivel            - pdfplumber nao extraiu nenhum texto do PDF
#   pdf_sem_inep            - PDF lido, mas sem "INEP: ########" no texto
#   pdf_sem_valor           - PDF lido, mas sem "Valor Total da Nota" no texto
#   inep_divergente_do_pdf  - INEP do PDF diferente do --inep informado
#   login                   - login recusado pelo portal
#   selecao_perfil          - modal "Fornecedor" nao respondeu
#   abrir_medicoes          - card "Medições" nao encontrado
#   abrir_osps              - botao "Ver OSPs" nao encontrado
#   osp_nao_encontrada      - portal mostra "0 pedido(s)" pra essa OSP
#   expandir_resultado_osp  - resultado da OSP nao expandiu (OSP existe, UI travou)
#   expandir_notas_fiscais  - secao "Notas Fiscais" nao expandiu
#   inep_nao_encontrado     - INEP nao aparece no grid do portal (pode ja estar enviado)
#   indice_invalido         - --indice fora do numero de linhas do INEP
#   documento_ja_enviado    - linha nao esta "Pendente" (ja enviada/aprovada/etc.)
#   valor_divergente        - valor do PDF diferente do valor exibido na linha do portal
#   upload                  - falha ao anexar PDF/XML no input do portal
#   enviar_notas            - falha ao clicar em "Enviar notas"
#   credenciais_ausentes    - .env sem EACE_USUARIO/EACE_SENHA
#   erro_playwright         - erro inesperado do proprio Playwright (rede, crash, etc.)
#   ambiente_indisponivel   - Playwright/Chromium/pdfplumber nao instalados (RpaEaceIndisponivel)
#   erro_inesperado         - qualquer outra excecao nao prevista (fila, apps/ri/services.py)


# RN-058 (FEAT-033, Fase 3): motivos de "regra de negocio" - dependem do
# dado da Nota Fiscal ou do estado do portal, nunca de falha tecnica/de
# ambiente. A fila (apps/ri/services.py) nunca reprocessa esses sozinha,
# porque repetir a mesma tentativa sem o usuario corrigir nada (trocar o
# PDF/XML, esperar o portal mudar) nao muda o resultado. Qualquer motivo
# de ResultadoRpaEace.motivo fora deste conjunto conta como "nao mapeado"
# (falha tecnica/de ambiente) e ganha 1 reprocessamento automatico.
MOTIVOS_REGRA_DE_NEGOCIO = frozenset({
    "pdf_sem_inep",
    "pdf_sem_valor",
    "inep_divergente_do_pdf",
    "valor_divergente",
    "osp_nao_encontrada",
    "inep_nao_encontrado",
    "documento_ja_enviado",
    "indice_invalido",
})


# Pedido do usuário (2026-09-03): barra de progresso enquanto a RPA roda
# de verdade (pode levar dezenas de segundos), pra dar visibilidade de
# que o processo esta andando e nao travado. Cada etapa do caminho feliz
# de `anexar_nota_fiscal`/`fazer_login` chama `ProgressoRpaEace.avancar()`
# nesta MESMA ORDEM - a etapa e o percentual (posicao/total) sao
# reportados por callback pra quem chamou (`apps/ri/services.py`, que
# grava em `LogRpaEace.etapa_atual`/`progresso_pct` pro polling da tela).
ETAPAS_RPA_EACE = (
    "Lendo os dados da Nota Fiscal",
    "Abrindo o portal EACE",
    "Preenchendo usuário",
    "Preenchendo senha",
    "Aguardando o portal responder",
    "Selecionando o perfil Fornecedor",
    "Abrindo Medições",
    "Abrindo OSPs",
    "Pesquisando a OSP",
    "Conferindo pedidos da OSP",
    "Expandindo o resultado da OSP",
    "Expandindo Notas Fiscais",
    "Lendo as linhas do grid",
    "Conferindo os dados da Nota Fiscal",
    "Anexando o PDF e o XML",
    "Enviando as notas",
)


class ProgressoRpaEace:
    """Avança 1 posição em `ETAPAS_RPA_EACE` a cada `avancar()` e chama
    `callback(etapa, percentual)` - nunca deixa uma falha ao reportar
    progresso derrubar a RPA (so loga)."""

    def __init__(self, callback=None):
        self._callback = callback
        self._indice = 0

    def avancar(self) -> None:
        if self._indice >= len(ETAPAS_RPA_EACE):
            return
        etapa = ETAPAS_RPA_EACE[self._indice]
        self._indice += 1
        percentual = round(self._indice / len(ETAPAS_RPA_EACE) * 100)
        if self._callback:
            try:
                self._callback(etapa, percentual)
            except Exception:
                logger.exception("Erro ao reportar progresso do RPA EACE (etapa: %s).", etapa)


def anexar_nota_fiscal(
    *,
    osp: str,
    inep: str,
    caminho_pdf: str,
    caminho_xml: str,
    indice: int | None = None,
    config: ConfigEace | None = None,
    progresso_callback=None,
) -> ResultadoRpaEace:
    """Extrai os dados da NF do PDF, confere contra o INEP informado e,
    se bater, sobe o par PDF+XML no portal EACE (linha do INEP dentro da
    OSP informada) - so depois de conferir que o valor do PDF bate com o
    valor exibido na linha do portal (RN-057).

    `indice` (1-based) e opcional: quando informado (Fase 1, comando de
    terminal), usa exatamente essa linha. Quando omitido (Fase 2, log por
    Nota Fiscal - RN-056), localiza sozinho a linha "Pendente" cujo valor
    bate com o valor extraido do PDF - o usuario do log nao tem como saber
    a ordem das linhas no portal.

    `progresso_callback(etapa: str, percentual: int)`, se informado, e
    chamado a cada etapa concluida do caminho feliz (`ETAPAS_RPA_EACE`) -
    pedido do usuario (2026-09-03) pra alimentar uma barra de progresso na
    tela enquanto a RPA roda de verdade. Nao e chamado em caminhos de
    erro/validacao anteriores a abertura do navegador.

    Levanta `RpaEaceIndisponivel` se o ambiente nao tiver Playwright/
    Chromium/pdfplumber - a unica falha que nao e "Erro" de processamento
    (RN-056) nem chega a extrair/comparar nada.
    """
    progresso = ProgressoRpaEace(progresso_callback)
    try:
        import pdfplumber  # noqa: F401  (so para falhar cedo se faltar)
        from playwright.sync_api import Error as PlaywrightError, sync_playwright

        from .dashboard import (
            abrir_medicoes,
            abrir_osps,
            clicar_enviar_notas,
            contar_pedidos_osp,
            expandir_notas_fiscais,
            expandir_resultado_osp,
            extrair_dados_grid,
            pesquisar_osp,
            upload_linha,
        )
        from .login import fazer_login, selecionar_perfil_fornecedor
    except ImportError as exc:
        raise RpaEaceIndisponivel(
            "Playwright/pdfplumber nao instalados - rode "
            "'pip install -r requirements.txt' e "
            "'python -m playwright install chromium'."
        ) from exc

    # RN-057: extrai e confere os dados da NF ANTES de abrir o navegador -
    # falha rapido, sem gastar tempo/rede se o PDF nao bate com o pedido.
    dados_pdf = extrair_dados_nota_fiscal(caminho_pdf)
    progresso.avancar()  # "Lendo os dados da Nota Fiscal"

    if not dados_pdf["inep"]:
        return ResultadoRpaEace(sucesso=False, motivo="pdf_sem_inep", dados_pdf=dados_pdf)
    if not dados_pdf["valor"]:
        return ResultadoRpaEace(sucesso=False, motivo="pdf_sem_valor", dados_pdf=dados_pdf)
    if dados_pdf["inep"] != inep:
        logger.error(
            "INEP do PDF (%s) diferente do INEP informado (%s) - abortando antes de abrir o portal.",
            dados_pdf["inep"], inep,
        )
        return ResultadoRpaEace(sucesso=False, motivo="inep_divergente_do_pdf", dados_pdf=dados_pdf)

    cfg = config or ConfigEace.carregar()
    if not cfg.usuario or not cfg.senha:
        logger.error("EACE_USUARIO/EACE_SENHA nao configurados no .env - abortando.")
        return ResultadoRpaEace(sucesso=False, motivo="credenciais_ausentes", dados_pdf=dados_pdf)

    logger.info(
        "Iniciando RPA EACE | OSP=%s INEP=%s indice=%s headless=%s",
        osp, inep, indice, cfg.headless,
    )

    try:
        with sync_playwright() as p:
            navegador = p.chromium.launch(
                headless=cfg.headless,
                args=[] if cfg.headless else ["--start-maximized"],
            )
            # Em headless nao ha janela fisica - viewport explicito garante que
            # o portal renderize as colunas no tamanho esperado (getBoundingClientRect).
            contexto = navegador.new_context(
                no_viewport=not cfg.headless,
                viewport={"width": 1920, "height": 1080} if cfg.headless else None,
            )
            pagina = contexto.new_page()
            pagina.set_default_timeout(cfg.timeout_ms)

            try:
                pagina.goto(cfg.url, wait_until="load", timeout=60_000)
                logger.info("Pagina carregada: %s", pagina.title())
                progresso.avancar()  # "Abrindo o portal EACE"

                if not fazer_login(pagina, cfg.usuario, cfg.senha, progresso.avancar):
                    return _falhar(pagina, inep, "login", dados_pdf)

                if not selecionar_perfil_fornecedor(pagina):
                    return _falhar(pagina, inep, "selecao_perfil", dados_pdf)
                progresso.avancar()  # "Selecionando o perfil Fornecedor"

                if not abrir_medicoes(pagina):
                    return _falhar(pagina, inep, "abrir_medicoes", dados_pdf)
                progresso.avancar()  # "Abrindo Medições"

                if not abrir_osps(pagina):
                    return _falhar(pagina, inep, "abrir_osps", dados_pdf)
                progresso.avancar()  # "Abrindo OSPs"

                if not pesquisar_osp(pagina, osp):
                    return _falhar(pagina, inep, "pesquisar_osp", dados_pdf)
                progresso.avancar()  # "Pesquisando a OSP"

                # OSP inexistente mostra "0 pedido(s)" - checa antes de tentar
                # expandir (a seta de expansao nao e exclusiva do resultado da
                # OSP, entao um timeout ali nao distinguiria os dois casos).
                total_pedidos = contar_pedidos_osp(pagina)
                if total_pedidos == 0:
                    return _falhar(pagina, inep, "osp_nao_encontrada", dados_pdf)
                progresso.avancar()  # "Conferindo pedidos da OSP"

                if not expandir_resultado_osp(pagina):
                    return _falhar(pagina, inep, "expandir_resultado_osp", dados_pdf)
                progresso.avancar()  # "Expandindo o resultado da OSP"

                if not expandir_notas_fiscais(pagina):
                    return _falhar(pagina, inep, "expandir_notas_fiscais", dados_pdf)
                progresso.avancar()  # "Expandindo Notas Fiscais"

                linhas = extrair_dados_grid(pagina, inep)
                if not linhas:
                    return _falhar(pagina, inep, "inep_nao_encontrado", dados_pdf)
                progresso.avancar()  # "Lendo as linhas do grid"

                if indice is None:
                    # Fase 2 (RN-057): sem indice explicito, localiza a
                    # linha "Pendente" cujo valor bate com o valor extraido
                    # do PDF - o log nao sabe a ordem das linhas no portal.
                    pendentes = [l for l in linhas if l["status"] == "Pendente"]
                    if not pendentes:
                        logger.error(
                            "Nenhuma linha 'Pendente' para o INEP %s - "
                            "documento provavelmente ja enviado antes.", inep,
                        )
                        return _falhar(pagina, inep, "documento_ja_enviado", dados_pdf)
                    linha_alvo = next(
                        (l for l in pendentes if valores_iguais(dados_pdf["valor"], l["valor"])),
                        None,
                    )
                    if linha_alvo is None:
                        logger.error(
                            "Nenhuma linha 'Pendente' do INEP %s tem valor igual ao do PDF (%s).",
                            inep, dados_pdf["valor"],
                        )
                        return _falhar(pagina, inep, "valor_divergente", dados_pdf, pendentes[0]["valor"])
                    indice = linha_alvo["indice"]
                    valor_portal = linha_alvo["valor"]
                else:
                    if indice < 1 or indice > len(linhas):
                        logger.error(
                            "Indice %s fora do intervalo - INEP %s tem %s linha(s) no grid.",
                            indice, inep, len(linhas),
                        )
                        return _falhar(pagina, inep, "indice_invalido", dados_pdf)

                    # RN-056: linha ja processada (qualquer status !=
                    # "Pendente") nao aceita novo upload - portal so libera
                    # o input de arquivo para linha "Pendente".
                    status_linha = linhas[indice - 1]["status"]
                    if status_linha != "Pendente":
                        logger.error(
                            "Linha nao esta mais pendente (status atual: %s) - "
                            "INEP %s, indice %s. Documento provavelmente ja "
                            "enviado antes.",
                            status_linha, inep, indice,
                        )
                        return _falhar(pagina, inep, "documento_ja_enviado", dados_pdf)

                    # RN-057: confere o valor do PDF contra o valor exibido
                    # na linha do portal ANTES de subir qualquer arquivo.
                    valor_portal = linhas[indice - 1]["valor"]
                    if not valores_iguais(dados_pdf["valor"], valor_portal):
                        logger.error(
                            "Valor divergente - PDF=%s | Portal=%s (INEP %s, indice %s).",
                            dados_pdf["valor"], valor_portal, inep, indice,
                        )
                        return _falhar(pagina, inep, "valor_divergente", dados_pdf, valor_portal)
                progresso.avancar()  # "Conferindo os dados da Nota Fiscal"

                if not upload_linha(pagina, inep, indice - 1, caminho_pdf, caminho_xml):
                    return _falhar(pagina, inep, "upload", dados_pdf, valor_portal)
                progresso.avancar()  # "Anexando o PDF e o XML"

                if not clicar_enviar_notas(pagina):
                    return _falhar(pagina, inep, "enviar_notas", dados_pdf, valor_portal)
                progresso.avancar()  # "Enviando as notas" -> 100%

                logger.info("RPA concluido com sucesso - OSP=%s INEP=%s indice=%s.", osp, inep, indice)
                return ResultadoRpaEace(sucesso=True, dados_pdf=dados_pdf, valor_portal=valor_portal)
            finally:
                _encerrar(contexto, navegador)

    except PlaywrightError as exc:
        logger.error("Erro inesperado do Playwright: %s", exc)
        return ResultadoRpaEace(sucesso=False, motivo="erro_playwright", dados_pdf=dados_pdf)


def _falhar(pagina, inep: str, motivo: str, dados_pdf: dict, valor_portal: str | None = None) -> ResultadoRpaEace:
    """Loga e tira um screenshot de diagnostico antes de propagar o erro."""
    logger.error("RPA encerrado com erro (%s) - INEP %s.", motivo, inep)
    try:
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pagina.screenshot(
            path=str(SCREENSHOTS_DIR / f"erro_{motivo}_{inep}_{timestamp}.png"),
            full_page=True,
        )
    except Exception:
        pass
    return ResultadoRpaEace(sucesso=False, motivo=motivo, dados_pdf=dados_pdf, valor_portal=valor_portal)


def _encerrar(contexto, navegador) -> None:
    try:
        contexto.close()
        navegador.close()
    except Exception:
        pass


@dataclass
class ResultadoConsultaPendencias:
    """Resultado de 1 consulta somente-leitura ao portal EACE (RN-063) -
    mesma navegação de `anexar_nota_fiscal` até ler o grid, nunca sobe
    arquivo nem clica em nada depois disso."""

    sucesso: bool
    motivo: str | None = None
    linhas: list[dict] | None = None


def consultar_pendencias_eace(
    *, osp: str, inep: str, config: ConfigEace | None = None,
) -> ResultadoConsultaPendencias:
    """RN-063 (melhoria 2026-09-04): lê as linhas do grid do portal EACE
    para a OSP/INEP informados, sem subir nada - usuário reportou não ter
    como saber, antes de escolher o par PDF+XML às cegas, qual Nota Fiscal
    (Produto/Valor) o portal espera em cada linha "Pendente" - só
    descobria depois de um "Erro (valor divergente)" (RN-057). Mesmo
    caminho de `anexar_nota_fiscal` até "Lendo as linhas do grid",
    reaproveitando os mesmos helpers de `.dashboard`/`.login`.

    Levanta `RpaEaceIndisponivel` nas mesmas condições de `anexar_nota_
    fiscal` (Playwright/Chromium ausente)."""
    try:
        from playwright.sync_api import Error as PlaywrightError, sync_playwright

        from .dashboard import (
            abrir_medicoes,
            abrir_osps,
            contar_pedidos_osp,
            expandir_notas_fiscais,
            expandir_resultado_osp,
            extrair_dados_grid,
            pesquisar_osp,
        )
        from .login import fazer_login, selecionar_perfil_fornecedor
    except ImportError as exc:
        raise RpaEaceIndisponivel(
            "Playwright nao instalado - rode 'pip install -r requirements.txt' e "
            "'python -m playwright install chromium'."
        ) from exc

    cfg = config or ConfigEace.carregar()
    if not cfg.usuario or not cfg.senha:
        logger.error("EACE_USUARIO/EACE_SENHA nao configurados no .env - abortando.")
        return ResultadoConsultaPendencias(sucesso=False, motivo="credenciais_ausentes")

    logger.info("Consultando pendencias no portal EACE | OSP=%s INEP=%s headless=%s", osp, inep, cfg.headless)

    try:
        with sync_playwright() as p:
            navegador = p.chromium.launch(
                headless=cfg.headless,
                args=[] if cfg.headless else ["--start-maximized"],
            )
            contexto = navegador.new_context(
                no_viewport=not cfg.headless,
                viewport={"width": 1920, "height": 1080} if cfg.headless else None,
            )
            pagina = contexto.new_page()
            pagina.set_default_timeout(cfg.timeout_ms)

            try:
                pagina.goto(cfg.url, wait_until="load", timeout=60_000)

                if not fazer_login(pagina, cfg.usuario, cfg.senha):
                    return ResultadoConsultaPendencias(sucesso=False, motivo="login")
                if not selecionar_perfil_fornecedor(pagina):
                    return ResultadoConsultaPendencias(sucesso=False, motivo="selecao_perfil")
                if not abrir_medicoes(pagina):
                    return ResultadoConsultaPendencias(sucesso=False, motivo="abrir_medicoes")
                if not abrir_osps(pagina):
                    return ResultadoConsultaPendencias(sucesso=False, motivo="abrir_osps")
                if not pesquisar_osp(pagina, osp):
                    return ResultadoConsultaPendencias(sucesso=False, motivo="pesquisar_osp")

                total_pedidos = contar_pedidos_osp(pagina)
                if total_pedidos == 0:
                    return ResultadoConsultaPendencias(sucesso=False, motivo="osp_nao_encontrada")

                if not expandir_resultado_osp(pagina):
                    return ResultadoConsultaPendencias(sucesso=False, motivo="expandir_resultado_osp")
                if not expandir_notas_fiscais(pagina):
                    return ResultadoConsultaPendencias(sucesso=False, motivo="expandir_notas_fiscais")

                linhas = extrair_dados_grid(pagina, inep)
                if not linhas:
                    return ResultadoConsultaPendencias(sucesso=False, motivo="inep_nao_encontrado")

                logger.info("Consulta de pendencias concluida - OSP=%s INEP=%s: %s linha(s).", osp, inep, len(linhas))
                return ResultadoConsultaPendencias(sucesso=True, linhas=linhas)
            finally:
                _encerrar(contexto, navegador)
    except PlaywrightError as exc:
        logger.error("Erro inesperado do Playwright: %s", exc)
        return ResultadoConsultaPendencias(sucesso=False, motivo="erro_playwright")
