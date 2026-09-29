from django.core.management.base import BaseCommand

from apps.escolas.validacao_nf_mip import (
    agendar_validacao_nf_mip_se_devido,
    processar_proxima_validacao_nf_mip,
    recuperar_validacoes_interrompidas,
)


class Command(BaseCommand):
    """1 passada da rotina "Validação MIP (NF)": recupera execuções
    interrompidas, agenda a execução da hora (08:00-19:00) se ainda não
    houver e processa a próxima da fila (agendada ou do botão "Rodar
    agora"). Quem repete no tempo é o worker do MIP (docker-compose,
    `mip_worker`) - mesmo padrão de `processar_fila_rpa_eace`."""

    help = "Agenda (08h-19h, 1x por hora) e processa a fila da Validação MIP (NF)."

    def handle(self, *args, **opcoes):
        interrompidas = recuperar_validacoes_interrompidas()
        if interrompidas:
            self.stdout.write(f"{interrompidas} validação(ões) interrompida(s) marcada(s) como Erro.")

        agendada = agendar_validacao_nf_mip_se_devido()
        if agendada:
            self.stdout.write(f"Validação agendada #{agendada.pk} enfileirada.")

        validacao = processar_proxima_validacao_nf_mip()
        if validacao:
            self.stdout.write(
                f"Validação #{validacao.pk}: {validacao.get_status_display()}"
                f"{f' ({validacao.motivo_erro})' if validacao.motivo_erro else ''}"
                f" | pedido {validacao.pedido or '-'} | {validacao.cards.count()} card(s)."
            )
