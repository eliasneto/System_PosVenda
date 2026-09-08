import datetime

from django.core.management.base import BaseCommand, CommandError

from apps.escolas.services import (
    PlanilhaFaturamentoImplantacaoError,
    gerar_planilha_faturamento_implantacao,
)


class Command(BaseCommand):
    """Forma provisória de gerar/testar a planilha de faturamento de
    implantação (`gerar_planilha_faturamento_implantacao`, `apps.escolas.
    services`) enquanto o usuário não define onde o arquivo fica disponível
    na tela — sem view/URL/botão ainda. Só grava o `.xlsx` em `--saida`;
    quem decide se o resultado vai por e-mail, download ou outro destino é
    a próxima etapa, ainda não definida.
    """

    help = (
        "Gera a planilha de faturamento de implantação (1 arquivo por "
        "Estado+Município) a partir do filtro de Projeto > MIP e salva em "
        "--saida."
    )

    def add_arguments(self, parser):
        parser.add_argument("--estado", required=True, help="UF do filtro (ex.: GO).")
        parser.add_argument("--municipio", required=True, help="Município do filtro (ex.: Abadiânia).")
        parser.add_argument(
            "--data-envio", required=True,
            help="Data de envio no formato dd/mm/aaaa — o VENCIMENTO é essa data + 30 dias corridos.",
        )
        parser.add_argument(
            "--saida", required=True,
            help="Caminho do arquivo .xlsx de saída (sobrescreve se já existir).",
        )

    def handle(self, *args, **options):
        try:
            data_envio = datetime.datetime.strptime(options["data_envio"], "%d/%m/%Y").date()
        except ValueError:
            raise CommandError(
                f"Data de envio inválida: {options['data_envio']!r} — use o formato dd/mm/aaaa."
            )

        try:
            workbook = gerar_planilha_faturamento_implantacao(
                options["estado"], options["municipio"], data_envio,
            )
        except PlanilhaFaturamentoImplantacaoError as erro:
            raise CommandError(str(erro))

        workbook.save(options["saida"])
        self.stdout.write(self.style.SUCCESS(f"Planilha gerada em: {options['saida']}"))
