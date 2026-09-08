from django.core.management.base import BaseCommand, CommandError

from apps.ri.services import EmailFinanceiroSyncError, recuperar_documentos_perdidos


class Command(BaseCommand):
    """Recuperação pontual (achado em produção, 2026-09-08): o serviço
    `email_scheduler` rodou um tempo sem o volume nomeado do `media/`
    (`docker-compose.hml.yml`) — o `Documento` (PDF/XML da Nota Fiscal
    recebida por e-mail) ficava salvo no registro do banco normalmente,
    mas o arquivo em si nunca chegava a existir no storage que o resto
    do sistema enxerga. Este comando busca de novo o e-mail original na
    caixa do financeiro (pelo `mensagem_id_externo` já salvo em
    `EmailFinanceiroLog`) e regrava os mesmos bytes no mesmo `Documento`
    — nunca cria registro novo, nunca move/apaga nada na caixa de
    e-mail."""

    help = (
        "Busca de novo, no Microsoft Graph, o e-mail original de cada Documento cujo "
        "arquivo sumiu do storage, e regrava o mesmo arquivo no mesmo registro. "
        "Por padrão só simula (--aplicar grava de verdade)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--ri", type=int, default=None, dest="ri_id",
            help="Recupera só este RI (padrão: todo RI com Documento sem arquivo no storage).",
        )
        parser.add_argument(
            "--aplicar", action="store_true",
            help="Grava de verdade — sem essa flag só simula e relata o que faria.",
        )

    def handle(self, *args, **options):
        try:
            resultado = recuperar_documentos_perdidos(ri_id=options["ri_id"], aplicar=options["aplicar"])
        except EmailFinanceiroSyncError as erro:
            raise CommandError(str(erro))

        if not resultado:
            self.stdout.write(self.style.SUCCESS("Nenhum Documento com arquivo ausente encontrado."))
            return

        recuperados = [linha for linha in resultado if linha["status"] == "recuperado"]
        simulados = [linha for linha in resultado if linha["status"] == "simulado"]
        pulados = [linha for linha in resultado if linha["status"] == "pulado"]

        for linha in resultado:
            estilo = {
                "recuperado": self.style.SUCCESS,
                "simulado": self.style.WARNING,
                "pulado": self.style.ERROR,
            }[linha["status"]]
            self.stdout.write(
                estilo(f"RI {linha['ri_id']} (INEP {linha['inep']}) — {linha['status']}: {linha['motivo']}")
            )

        self.stdout.write("")
        if options["aplicar"]:
            self.stdout.write(self.style.SUCCESS(f"{len(recuperados)} RI(s) recuperado(s)."))
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"Simulação (nada foi gravado): {len(simulados)} RI(s) seriam recuperados. "
                    "Rode novamente com --aplicar para gravar."
                )
            )
        if pulados:
            self.stdout.write(self.style.ERROR(f"{len(pulados)} RI(s) precisam de revisão manual."))
