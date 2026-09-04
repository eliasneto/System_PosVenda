"""FEAT-033 (Fase 1, `ADR-004`/`RN-056`/`RN-057`): sobe 1 par PDF+XML no
portal EACE via terminal, sem model de log nem tela ainda - so valida que
o nucleo da automacao (`apps/integracoes/eace/`) funciona de ponta a
ponta contra o portal real, inclusive a conferencia dos dados extraidos
do PDF (INEP/Produto/Valor) contra o portal. A Fase 2 substitui a chamada
manual deste comando pelo log por Nota Fiscal (RN-056), exibindo os
mesmos dados extraidos no proprio log e gravando o resultado ("Sucesso"/
"Erro" + motivo) e, quando todos os logs de um RI derem "Sucesso",
avancando o status para "Aguardando validacao EACE" (RN-001).
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.integracoes.eace.rpa import RpaEaceIndisponivel, anexar_nota_fiscal


class Command(BaseCommand):
    help = (
        "Sobe 1 Nota Fiscal (1 PDF + 1 XML) no portal EACE para um INEP de "
        "uma OSP especifica, via Playwright, conferindo antes os dados "
        "extraidos do PDF (RN-057). Uso manual de terminal (Fase 1 da "
        "FEAT-033) - nao le nem grava nada no banco."
    )

    def add_arguments(self, parser):
        parser.add_argument("--osp", required=True, help="Numero da OSP no portal EACE.")
        parser.add_argument("--inep", required=True, help="Numero do INEP a processar.")
        parser.add_argument(
            "--indice",
            type=int,
            default=1,
            help=(
                "Posicao (1-based) da linha do INEP no grid do portal (KIT ou "
                "NOBREAK aparecem como linhas separadas); padrao 1."
            ),
        )
        parser.add_argument("--pdf", required=True, help="Caminho do arquivo PDF (Nota Fiscal).")
        parser.add_argument("--xml", required=True, help="Caminho do arquivo XML correspondente.")

    def handle(self, *args, **options):
        pdf = Path(options["pdf"])
        xml = Path(options["xml"])
        if not pdf.is_file():
            raise CommandError(f"PDF nao encontrado: {pdf}")
        if not xml.is_file():
            raise CommandError(f"XML nao encontrado: {xml}")

        osp = options["osp"]
        inep = options["inep"]
        indice = options["indice"]

        self.stdout.write(f"Iniciando RPA EACE - OSP={osp} INEP={inep} indice={indice}...")

        try:
            resultado = anexar_nota_fiscal(
                osp=osp,
                inep=inep,
                indice=indice,
                caminho_pdf=str(pdf),
                caminho_xml=str(xml),
            )
        except RpaEaceIndisponivel as exc:
            raise CommandError(str(exc))

        if resultado.dados_pdf:
            d = resultado.dados_pdf
            self.stdout.write(
                f"Dados extraidos da NF: INEP={d.get('inep') or '?'} | "
                f"Produto={d.get('produto') or '?'} | Valor={d.get('valor') or '?'}"
                + (f" | Valor no portal={resultado.valor_portal}" if resultado.valor_portal else "")
            )

        if not resultado.sucesso:
            raise CommandError(
                f"RPA terminou com erro ({resultado.motivo}) - ver o log acima e os "
                "screenshots em media/rpa_eace/screenshots/."
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"OK - PDF+XML anexados no portal EACE (OSP={osp}, INEP={inep}, "
                f"indice={indice})."
            )
        )
