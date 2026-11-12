"""SÓ PARA DESENVOLVIMENTO (v1.6.0): simula a resposta do financeiro a um
e-mail do RI - monta a mensagem com os PDF/XML informados e passa pelo mesmo
processamento da leitura da caixa (`_processar_mensagem`), sem Microsoft
Graph. Serve para o faturamento normal e para o complementar (código
`RI-AAAAMMDD-INEP-C<n>` no assunto).

Bloqueado com `DEBUG=False` (produção/homologação).

Exemplos:
    python manage.py simular_resposta_financeiro --complementar 12345678 1 \\
        --arquivo /tmp/4001_10-11-2026_X.pdf --arquivo /tmp/4001_10-11-2026_X.xml
    python manage.py simular_resposta_financeiro --assunto "RE: #RI-20261112-12345678 - ..." \\
        --arquivo nf.pdf --arquivo nf.xml
"""
import os
import uuid
from email.message import EmailMessage

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.ri.models import FaturamentoComplementar
from apps.ri.services import _processar_mensagem


class Command(BaseCommand):
    help = "DEV: simula a resposta do financeiro (PDF/XML) a um e-mail do RI ou de um faturamento complementar."

    def add_arguments(self, parser):
        grupo = parser.add_mutually_exclusive_group(required=True)
        grupo.add_argument("--assunto", help='Assunto completo da resposta (ex.: "RE: #RI-20261112-12345678 - ...").')
        grupo.add_argument(
            "--complementar", nargs=2, metavar=("INEP", "N"),
            help="Usa o assunto do faturamento complementar C<N> já enviado do INEP.",
        )
        parser.add_argument("--arquivo", action="append", default=[], help="PDF ou XML a anexar (repita a opção).")
        parser.add_argument("--remetente", default="financeiro@speedcsc.com.br")

    def handle(self, *args, **opcoes):
        if not settings.DEBUG:
            raise CommandError("Comando só para desenvolvimento: bloqueado com DEBUG=False.")

        if opcoes["complementar"]:
            inep, numero = opcoes["complementar"]
            complementar = (
                FaturamentoComplementar.objects.filter(ri__escola__inep=inep, numero=numero)
                .exclude(codigo_rastreio="").order_by("-pk").first()
            )
            if not complementar:
                raise CommandError(f"Nenhum faturamento complementar C{numero} enviado para o INEP {inep}.")
            assunto = f"RE: {complementar.assunto or '#' + complementar.codigo_rastreio}"
        else:
            assunto = opcoes["assunto"]

        mensagem = EmailMessage()
        mensagem["Subject"] = assunto
        mensagem["From"] = opcoes["remetente"]
        mensagem["To"] = "posvendas@megainfraestrutura.com.br"
        mensagem.set_content("Resposta simulada (desenvolvimento).")
        for caminho in opcoes["arquivo"]:
            if not os.path.isfile(caminho):
                raise CommandError(f"Arquivo não encontrado: {caminho}")
            subtipo = "pdf" if caminho.lower().endswith(".pdf") else "xml"
            with open(caminho, "rb") as arquivo:
                mensagem.add_attachment(
                    arquivo.read(), maintype="application", subtype=subtipo, filename=os.path.basename(caminho)
                )

        resultado = _processar_mensagem(mensagem.as_bytes(), f"simulado-{uuid.uuid4()}")
        self.stdout.write(f"Assunto: {assunto}")
        self.stdout.write(self.style.SUCCESS(f"Resultado: {resultado}"))
