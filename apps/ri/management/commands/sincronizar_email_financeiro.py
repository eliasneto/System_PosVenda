from django.core.management.base import BaseCommand, CommandError

from apps.ri.services import EmailFinanceiroSyncError, sincronizar_respostas_financeiro


class Command(BaseCommand):
    """FEAT-009 (RF-08/RF-09/RF-19): uma passada de polling na caixa do
    financeiro. Não agenda nada sozinho — precisa ser chamado a cada ~5 min
    por um agendador externo (cron/Task Scheduler/systemd timer), a
    configurar pelo DevOps (fora do escopo deste comando)."""

    help = (
        "Lê as mensagens não lidas da caixa do financeiro, identifica o RI pelo "
        "código de rastreio do assunto (RN-009) e processa a resposta (RN-005)."
    )

    def handle(self, *args, **options):
        try:
            resultado = sincronizar_respostas_financeiro()
        except EmailFinanceiroSyncError as erro:
            raise CommandError(str(erro))

        # RN-016: resposta no padrão e fora do padrão avançam o status do
        # RI (a diferença é só anexar ou não NF+XML) — "RIs com status
        # alterado" soma as duas, para o resumo não subestimar o que a
        # passada realmente mudou.
        status_alterado = resultado["identificados"] + resultado["fora_do_padrao"]
        self.stdout.write(
            self.style.SUCCESS(
                f"E-mails avaliados: {resultado['processados']}; "
                f"RIs com status alterado: {status_alterado} "
                f"(documentos anexados: {resultado['identificados']}; "
                f"fora do padrão: {resultado['fora_do_padrao']}); "
                f"sem código de rastreio: {resultado['sem_codigo']}; "
                f"sem RI aguardando financeiro: {resultado['sem_ri_aguardando']}; "
                f"duplicados (já processados antes): {resultado['duplicados']}."
            )
        )
