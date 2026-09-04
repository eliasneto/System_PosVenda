"""Ponto de entrada do RPA EACE."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError, Page, sync_playwright

from arquivos import localizar_arquivos_inep
from config import EACE_DIR, OUTPUT_DIR, SCREENSHOTS_DIR, VERSAO, Config
from extrair_dados_pdf import (
    atualizar_planilha_pos_portal,
    ler_registros_excel,
    ler_valor_pdf,
    main as extrair_planilha,
    validar_pasta_vs_inep,
    valores_iguais,
)
from dashboard import (
    abrir_medicoes,
    abrir_osps,
    clicar_enviar_notas,
    expandir_notas_fiscais,
    expandir_resultado_osp,
    extrair_dados_grid,
    pesquisar_osp,
    upload_linha,
)
from input_osp import ler_osps
from logger import log
from login import fazer_login, selecionar_perfil_fornecedor


def _exibir_banner() -> None:
    try:
        cols = os.get_terminal_size().columns
    except OSError:
        cols = 100

    W = 60
    titulo = "BACKOFFICE - Portal do Cliente EACE"
    versao = f"v{VERSAO}"
    pad = " " * max(0, (cols - W - 2) // 2)

    print()
    print(pad + "+" + "=" * W + "+")
    print(pad + "|" + " " * W + "|")
    print(pad + "|" + " " * W + "|")
    print(pad + "|" + titulo.upper().center(W) + "|")
    print(pad + "|" + versao.center(W) + "|")
    print(pad + "|" + " " * W + "|")
    print(pad + "|" + " " * W + "|")
    print(pad + "+" + "=" * W + "+")
    print()


def pausa(pagina: Page, cfg: Config) -> None:
    pagina.wait_for_timeout(cfg.delay_ms)


def _validar_prerequisitos() -> bool:
    """Valida pastas INEP e presenca de PDF/XML antes de abrir o portal."""
    erros = []

    pastas_inep = sorted(p for p in EACE_DIR.iterdir() if p.is_dir()) if EACE_DIR.exists() else []
    if not pastas_inep:
        erros.append(f"Nenhuma pasta INEP encontrada em: {EACE_DIR}")
    else:
        for pasta in pastas_inep:
            for tipo in ("KIT", "NOBREAK"):
                subpasta = pasta / tipo
                if not subpasta.exists():
                    erros.append(f"Pasta ausente: {pasta.name}/{tipo}")
                    continue
                if not list(subpasta.glob("*.pdf")):
                    erros.append(f"PDF ausente em: {pasta.name}/{tipo}")
                if not list(subpasta.glob("*.xml")):
                    erros.append(f"XML ausente em: {pasta.name}/{tipo}")

    if erros:
        log.error("Pre-requisitos nao atendidos - abortando antes de abrir o portal:")
        for erro in erros:
            log.error("  * {}", erro)
        return False

    log.success("Pre-requisitos OK: {} pasta(s) INEP validada(s).", len(pastas_inep))
    return True


def _processar_inep(
    pagina: Page,
    cfg: Config,
    inep: str,
    caminho_excel: Path,
) -> None:
    """Valida e faz upload dos arquivos de um INEP no portal."""
    log.info("── Processando INEP {} ──", inep)

    dados_inep = extrair_dados_grid(pagina, inep)
    if not dados_inep:
        pagina.screenshot(path=str(SCREENSHOTS_DIR / f"erro_inep_{inep}.png"), full_page=True)
        log.error("INEP {} nao encontrado no grid do portal.", inep)
        atualizar_planilha_pos_portal(
            [{"inep": inep, "tipo": None, "valor_portal": "", "status": "INEP nao encontrado no portal"}],
            caminho_excel,
        )
        return
    pausa(pagina, cfg)
    pagina.screenshot(path=str(SCREENSHOTS_DIR / f"inep_{inep}_localizado.png"), full_page=True)

    arquivos = localizar_arquivos_inep(inep)

    # Passo 1 - valida todos os itens do INEP sem fazer nenhum upload ainda
    erros_validacao: list[dict] = []
    itens_para_upload: list[dict] = []

    for item in dados_inep:
        tipo = "NOBREAK" if "NOBREAK" in item["descricao"].upper() else "KIT"
        valor_portal = item["valor"]
        indice = item["indice"] - 1

        valor_pdf = ler_valor_pdf(inep, tipo, caminho_excel)
        if not valores_iguais(valor_pdf, valor_portal):
            msg = f"Valor divergente (NF: {valor_pdf} | Portal: {valor_portal})"
            log.warning("  {} - {}.", tipo, msg)
            erros_validacao.append({"inep": inep, "tipo": tipo, "valor_portal": valor_portal, "status": msg})
            continue

        if item["status"] == "Enviado":
            log.warning("  {} - Documento enviado anteriormente.", tipo)
            erros_validacao.append({"inep": inep, "tipo": tipo, "valor_portal": valor_portal, "status": "Documento enviado anteriormente"})
            continue

        if not arquivos or tipo not in arquivos:
            log.error("  {} - Arquivos nao encontrados em EACE/{}/{}.", tipo, inep, tipo)
            erros_validacao.append({"inep": inep, "tipo": tipo, "valor_portal": valor_portal, "status": "Arquivo nao encontrado"})
            continue

        itens_para_upload.append({
            "tipo": tipo,
            "valor_portal": valor_portal,
            "valor_pdf": valor_pdf,
            "indice": indice,
        })

    if erros_validacao:
        log.warning(
            "INEP {} - {} item(s) com erro. Nenhum upload sera realizado para este INEP.",
            inep, len(erros_validacao),
        )
        atualizar_planilha_pos_portal(erros_validacao, caminho_excel)
        return

    # Passo 2 - todos os itens passaram: executa os uploads
    atualizacoes: list[dict] = []
    for it in itens_para_upload:
        tipo = it["tipo"]
        caminho_pdf, caminho_xml = arquivos[tipo]
        log.info("  {} - Iniciando upload (NF={} | Portal={})...", tipo, it["valor_pdf"], it["valor_portal"])
        ok = upload_linha(pagina, inep, it["indice"], caminho_pdf, caminho_xml)
        pausa(pagina, cfg)

        status = "Lancado com sucesso" if ok else "Erro no upload"
        if ok:
            log.success("  {} - {}.", tipo, status)
        else:
            log.error("  {} - {}.", tipo, status)
        atualizacoes.append({"inep": inep, "tipo": tipo, "valor_portal": it["valor_portal"], "status": status})

    houve_upload = any(a["status"] == "Lancado com sucesso" for a in atualizacoes)
    if houve_upload:
        ok_envio = clicar_enviar_notas(pagina)
        pausa(pagina, cfg)
        pagina.screenshot(path=str(SCREENSHOTS_DIR / f"enviar_notas_{inep}.png"), full_page=True)
        for a in atualizacoes:
            if a["status"] == "Lancado com sucesso":
                a["status"] = "Enviado com sucesso" if ok_envio else "Upload OK mas falha ao enviar"
    else:
        log.info("  Nenhum upload realizado para INEP {} - 'Enviar notas' ignorado.", inep)

    log.info("Atualizando planilha - INEP {}...", inep)
    atualizar_planilha_pos_portal(atualizacoes, caminho_excel)


def _executar_osp(pagina: Page, cfg: Config, osp: str) -> None:
    """Executa o processo completo para uma OSP: PDF → Excel → portal."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    caminho_excel = OUTPUT_DIR / f"{osp}_{timestamp}.xlsx"
    log.info("OSP {} - planilha: {}", osp, caminho_excel.name)

    # Extrai dados dos PDFs e gera planilha
    log.info("OSP {} - Extraindo dados dos PDFs...", osp)
    sucesso = extrair_planilha(osp=osp, caminho_excel=caminho_excel)
    if not sucesso:
        log.error("OSP {} - falha na geracao da planilha (verifique os PDFs em EACE/).", osp)
        return

    # Valida INEP x pasta
    log.info("OSP {} - Validando INEP das notas x nome das pastas...", osp)
    registros_excel = ler_registros_excel(caminho_excel)
    if not registros_excel:
        log.error("OSP {} - planilha vazia ou nao encontrada.", osp)
        return
    if not validar_pasta_vs_inep(registros_excel):
        log.error(
            "OSP {} - INEP extraido da nota nao confere com o nome da pasta. "
            "Corrija a estrutura de pastas ou as notas antes de continuar.",
            osp,
        )
        return

    ineps = list(dict.fromkeys(r["pasta"] for r in registros_excel))
    log.info("OSP {} - INEPs a processar: {}", osp, ineps)

    # Navega ate a lista de OSPs
    if not abrir_medicoes(pagina):
        pagina.screenshot(path=str(SCREENSHOTS_DIR / f"osp_{osp}_erro_medicoes.png"), full_page=True)
        log.error("OSP {} - falha ao abrir Medicoes.", osp)
        return
    pausa(pagina, cfg)

    if not abrir_osps(pagina):
        pagina.screenshot(path=str(SCREENSHOTS_DIR / f"osp_{osp}_erro_osps.png"), full_page=True)
        log.error("OSP {} - falha ao abrir OSPs.", osp)
        return
    pausa(pagina, cfg)

    if not pesquisar_osp(pagina, osp):
        pagina.screenshot(path=str(SCREENSHOTS_DIR / f"osp_{osp}_erro_pesquisa.png"), full_page=True)
        log.error("OSP {} - falha na pesquisa.", osp)
        return
    pausa(pagina, cfg)
    pagina.screenshot(path=str(SCREENSHOTS_DIR / f"osp_{osp}_resultado.png"), full_page=True)

    if not expandir_resultado_osp(pagina):
        pagina.screenshot(path=str(SCREENSHOTS_DIR / f"osp_{osp}_erro_expandir.png"), full_page=True)
        log.error("OSP {} - falha ao expandir resultado.", osp)
        return
    pausa(pagina, cfg)

    if not expandir_notas_fiscais(pagina):
        pagina.screenshot(path=str(SCREENSHOTS_DIR / f"osp_{osp}_erro_notas_fiscais.png"), full_page=True)
        log.error("OSP {} - falha ao expandir Notas Fiscais.", osp)
        return
    pausa(pagina, cfg)
    pagina.screenshot(path=str(SCREENSHOTS_DIR / f"osp_{osp}_notas_fiscais.png"), full_page=True)

    # Processa cada INEP
    for inep in ineps:
        _processar_inep(pagina, cfg, inep, caminho_excel)

    pagina.screenshot(path=str(SCREENSHOTS_DIR / f"osp_{osp}_concluido.png"), full_page=True)
    log.success("OSP {} - processamento concluido.", osp)


def executar() -> None:
    _exibir_banner()
    cfg = Config.carregar()
    log.info("Iniciando RPA EACE | headless={} | delay={}ms", cfg.headless, cfg.delay_ms)

    # 0a. Le OSPs do arquivo input/osp.txt
    osps = ler_osps()
    if not osps:
        return

    # 0b. Valida pre-requisitos (estrutura EACE/)
    if not _validar_prerequisitos():
        return

    try:
        with sync_playwright() as p:
            navegador = p.chromium.launch(
                headless=cfg.headless,
                args=[] if cfg.headless else ["--start-maximized"],
            )
            # Em headless nao ha janela fisica - define viewport explicito para garantir
            # que o portal renderize as colunas no tamanho esperado (getBoundingClientRect).
            contexto = navegador.new_context(
                no_viewport=not cfg.headless,
                viewport={"width": 1920, "height": 1080} if cfg.headless else None,
            )
            pagina = contexto.new_page()
            pagina.set_default_timeout(cfg.timeout_ms)

            # Abre o portal e faz login (uma unica vez para todas as OSPs)
            log.info("Abrindo pagina de login...")
            pagina.goto(cfg.url, wait_until="load", timeout=60_000)
            log.info("Pagina carregada: {}", pagina.title())
            pausa(pagina, cfg)

            if not cfg.usuario or not cfg.senha:
                log.warning("Credenciais nao configuradas no .env - pulando login.")
            else:
                sucesso = fazer_login(pagina, cfg.usuario, cfg.senha)
                if not sucesso:
                    pagina.screenshot(path=str(SCREENSHOTS_DIR / "erro_login.png"), full_page=True)
                    log.error("Abortando execucao apos falha no login.")
                    _encerrar(contexto, navegador)
                    return
                pausa(pagina, cfg)

                sucesso = selecionar_perfil_fornecedor(pagina)
                if not sucesso:
                    pagina.screenshot(path=str(SCREENSHOTS_DIR / "erro_perfil.png"), full_page=True)
                    log.error("Abortando execucao apos falha na selecao de perfil.")
                    _encerrar(contexto, navegador)
                    return
                pausa(pagina, cfg)
                pagina.screenshot(path=str(SCREENSHOTS_DIR / "pos_login.png"), full_page=True)

            # Processa cada OSP listada no txt
            for osp in osps:
                log.info("━━━━━━━━━━ OSP {} ━━━━━━━━━━", osp)
                _executar_osp(pagina, cfg, osp)

            if not cfg.headless:
                input("\n  Navegador aberto. Pressione Enter para fechar...\n")

            _encerrar(contexto, navegador)

    except PlaywrightError as exc:
        if "closed" in str(exc).lower():
            log.warning("Navegador fechado durante a execucao - processo interrompido.")
        else:
            log.error("Erro inesperado do Playwright: {}", exc)

    log.info("Execucao finalizada.")


def _encerrar(contexto, navegador) -> None:
    try:
        contexto.close()
        navegador.close()
    except Exception:
        pass


if __name__ == "__main__":
    executar()
