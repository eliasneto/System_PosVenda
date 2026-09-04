from django.core.management.base import BaseCommand

from apps.ri.services import processar_proximo_da_fila_rpa_eace


class Command(BaseCommand):
    """FEAT-033 (Fase 3, RN-058): 1 passada do processo consumidor da fila
    do RPA EACE - pega o log "Na fila" mais antigo e processa. Não agenda
    nada sozinho - precisa ser chamado repetidamente por um agendador
    externo (mesmo padrão do `sincronizar_email_financeiro`: container
    próprio em loop no docker-compose.yml, a configurar pelo DevOps)."""

    help = (
        "Processa 1 item da fila do RPA EACE (RN-058) - pega o log mais "
        "antigo 'Na fila', executa e decide reprocessar (erro não mapeado, "
        "só 1 vez) ou finalizar (sucesso ou erro definitivo)."
    )

    def handle(self, *args, **options):
        resultado = processar_proximo_da_fila_rpa_eace()
        if resultado is None:
            self.stdout.write("Fila vazia - nada para processar.")
            return

        detalhe = f" ({resultado['motivo']})" if resultado["motivo"] else ""
        self.stdout.write(
            self.style.SUCCESS(f"Log {resultado['log_id']}: {resultado['resultado']}{detalhe}")
        )
