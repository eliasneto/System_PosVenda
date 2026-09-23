from django.core.management.base import BaseCommand
from django.db import transaction

from apps.ixc import services
from apps.ixc.models import ExecucaoAutomacaoIxc


class Command(BaseCommand):
    """FEAT-053 (ADR-007, emenda 2026-09-23): 1 passada do processo
    consumidor das Automações IXC — pega a execução "Processando" mais
    antiga (entre Login/Endereços e Atendimentos, os 2 slots de cada) e
    processa 1 chunk (`apps.ixc.services.processar_proximo_chunk`). Não
    agenda nada sozinho — precisa ser chamado repetidamente por um
    container próprio (`ixc_worker`, `docker-compose.yml`/`.hml.yml`),
    mesmo padrão do `processar_fila_rpa_eace` (RPA EACE).

    Revisão da decisão original do ADR-007 (só HTMX, sem worker): uma
    execução iniciada e depois "esquecida" (aba fechada antes de
    terminar) ficava parada para sempre em 0%, sem erro nenhum — caso
    real em produção, INEP/planilha de login travada às 19:26 sem
    nenhuma linha processada. Este worker garante que toda execução
    "Processando" avança sozinha, com ou sem alguém olhando a tela."""

    help = (
        "Processa 1 chunk da execução 'Processando' mais antiga das "
        "Automações IXC (Login/Endereços ou Atendimentos)."
    )

    def handle(self, *args, **options):
        with transaction.atomic():
            execucao = (
                ExecucaoAutomacaoIxc.objects.select_for_update(skip_locked=True)
                .filter(status=ExecucaoAutomacaoIxc.PROCESSANDO)
                .order_by("criado_em")
                .first()
            )
            if execucao is None:
                self.stdout.write("Nenhuma execução 'Processando' — nada para fazer.")
                return

            execucao = services.processar_proximo_chunk(execucao, usuario=execucao.criado_por)

        self.stdout.write(
            self.style.SUCCESS(
                f"Execução {execucao.pk} ({execucao.tipo}, slot {execucao.slot}): "
                f"{execucao.progresso_pct}% — status {execucao.get_status_display()}"
            )
        )
