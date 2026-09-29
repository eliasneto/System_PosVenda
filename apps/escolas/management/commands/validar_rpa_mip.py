from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.integracoes.eace.rpa_mip import RpaMipIndisponivel, anexar_pdf_mip


class Command(BaseCommand):
    """Roda o RPA do MIP (`apps/integracoes/eace/rpa_mip.py`) so para
    validacao visual do caminho no portal EACE: salva 1 screenshot por
    etapa numa pasta e, opcionalmente, abre o navegador visivel e grava um
    video.

    Por padrao roda em modo simulacao: faz login, abre o pedido mais
    recente do MIP, le os cards de municipio e para ali - NAO anexa nada.
      - com --pdf: tambem confere status e valor e destaca o card que
        receberia o PDF;
      - sem --pdf: para depois de ler os cards (lista todos no terminal);
      - sem --municipio: so le os cards, sem filtrar.
    Use --aplicar (exige --pdf e --municipio) para anexar de verdade -
    mesmo padrao dos demais comandos deste projeto (ex.:
    `importar_nova_base_eace`).
    """

    help = (
        "Valida o RPA do MIP com capturas de tela por etapa. "
        "Simulacao por padrao (nao anexa o PDF); use --aplicar para anexar."
    )

    def add_arguments(self, parser):
        parser.add_argument("--municipio", help='Municipio do card no portal (ex.: "São Paulo"). Opcional na simulacao.')
        parser.add_argument("--pdf", help="Caminho do PDF da Nota Fiscal. Opcional na simulacao.")
        parser.add_argument("--pedido", help="Numero do pedido a abrir (padrao: o de maior numero no grid de MIPs).")
        parser.add_argument(
            "--pasta",
            help="Pasta das capturas (padrao: MEDIA_ROOT/rpa_eace/validacao_mip/<data_hora>).",
        )
        parser.add_argument("--visivel", action="store_true", help="Abre o navegador na tela (nao headless).")
        parser.add_argument(
            "--lento",
            type=int,
            default=None,
            help="Pausa em ms entre cada acao do navegador (padrao: 500 com --visivel, 0 sem).",
        )
        parser.add_argument("--video", action="store_true", help="Grava um video (.webm) da execucao na pasta.")
        parser.add_argument("--aplicar", action="store_true", help="Anexa o PDF de verdade (exige --pdf e --municipio).")

    def handle(self, *args, **opcoes):
        municipio = opcoes["municipio"]
        caminho_pdf = Path(opcoes["pdf"]) if opcoes["pdf"] else None
        if caminho_pdf and not caminho_pdf.is_file():
            raise CommandError(f"PDF nao encontrado: {caminho_pdf}")
        pedido = (opcoes["pedido"] or "").strip() or None
        if pedido and not pedido.isdigit():
            raise CommandError("--pedido deve ter so numeros (ex.: 506).")
        if opcoes["aplicar"] and not (caminho_pdf and municipio):
            raise CommandError("--aplicar exige --pdf e --municipio.")

        pasta = Path(opcoes["pasta"]) if opcoes["pasta"] else (
            Path(settings.MEDIA_ROOT) / "rpa_eace" / "validacao_mip" / datetime.now().strftime("%Y%m%d_%H%M%S")
        )
        lento = opcoes["lento"] if opcoes["lento"] is not None else (500 if opcoes["visivel"] else 0)
        simular = not opcoes["aplicar"]

        self.stdout.write(
            f"Municipio: {municipio or '(todos)'} | PDF: {caminho_pdf or '(sem PDF)'}"
            f" | Pedido: {pedido or '(maior numero)'}\n"
            f"Modo: {'SIMULACAO (nao anexa)' if simular else 'APLICAR (anexa o PDF de verdade)'}\n"
            f"Capturas em: {pasta}"
        )

        def mostrar_progresso(etapa, percentual):
            self.stdout.write(f"  [{percentual:3d}%] {etapa}")

        try:
            resultado = anexar_pdf_mip(
                municipio=municipio,
                caminho_pdf=str(caminho_pdf) if caminho_pdf else None,
                progresso_callback=mostrar_progresso,
                simular=simular,
                pasta_capturas=pasta,
                headless=False if opcoes["visivel"] else None,
                lento_ms=lento,
                gravar_video=opcoes["video"],
                pedido=pedido,
            )
        except RpaMipIndisponivel as exc:
            raise CommandError(str(exc)) from exc

        if resultado.cards_encontrados is not None:
            self.stdout.write(f"\nCards de municipio no pedido {resultado.pedido}: {len(resultado.cards_encontrados)}")
            for card in resultado.cards_encontrados:
                ibge = f" (IBGE {card['ibge']})" if card["ibge"] else ""
                self.stdout.write(
                    f"  - {card['municipio'] or '?'}{ibge} | Status: {card['status'] or '?'} | R$ {card['valor'] or '?'}"
                )

        dados_pdf = resultado.dados_pdf or {}
        self.stdout.write(
            f"\nValor do PDF: {dados_pdf.get('valor') or '-'} | Valor no portal: {resultado.valor_portal or '-'} "
            f"| Pedido: {resultado.pedido or '-'}"
        )
        if not resultado.sucesso:
            self.stdout.write(self.style.ERROR(f"Parou com erro: {resultado.motivo}"))
        elif resultado.simulado and not caminho_pdf:
            self.stdout.write(self.style.SUCCESS(
                "Simulacao sem PDF OK - chegou nos cards do pedido. Status/valor nao conferidos, nada anexado."
            ))
        elif resultado.simulado:
            self.stdout.write(self.style.SUCCESS(
                "Simulacao OK - o card certo foi encontrado e destacado na ultima captura. Nada foi anexado."
            ))
        else:
            self.stdout.write(self.style.SUCCESS("PDF anexado no portal."))
        self.stdout.write(f"Capturas em: {pasta}")
