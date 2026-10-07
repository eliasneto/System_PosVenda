from django.core.management.base import BaseCommand

from apps.escolas.rpa_mip_lote import (
    processar_proximo_rpa_mip,
    proximo_enfileirado_rpa_mip_em,
    recuperar_envios_mip_interrompidos,
)
from apps.escolas.validacao_nf_mip import (
    agendar_validacao_nf_mip_se_devido,
    processar_proxima_validacao_nf_mip,
    recuperar_validacoes_interrompidas,
)
from apps.ri.models import LogRpaEace
from apps.ri.services import processar_proximo_da_fila_rpa_eace


class Command(BaseCommand):
    """FEAT-033 (Fase 3, RN-058): 1 passada do processo consumidor da fila
    do RPA EACE - pega o log "Na fila" mais antigo e processa. Não agenda
    nada sozinho - precisa ser chamado repetidamente por um agendador
    externo (mesmo padrão do `sincronizar_email_financeiro`: container
    próprio em loop no docker-compose.yml, a configurar pelo DevOps).

    Pedido do usuário (2026-09-29, RN-XXX a formalizar pelo Orquestrador):
    a MESMA fila também leva o envio da NF dos LOTEs do MIP
    (`apps.escolas.rpa_mip_lote`, log próprio `LogRpaEaceMip`) - 1 item
    por passada, o mais antigo entre RI e MIP (ordem de chegada), então
    continua no máximo 1 execução do portal por vez em todo o sistema.
    Com os envios (RI/MIP) vazios, processa a Validação MIP (NF) (leitura
    de status do portal, só leitura) - pedido do usuário, 2026-09-29."""

    help = (
        "Processa 1 item da fila do RPA EACE (RN-058) - RI ou MIP, o mais "
        "antigo 'Na fila' - e decide reprocessar (erro não mapeado, só 1 "
        "vez) ou finalizar (sucesso ou erro definitivo)."
    )

    @staticmethod
    def _processar_validacao_nf_mip():
        recuperar_validacoes_interrompidas()
        agendar_validacao_nf_mip_se_devido()  # só age com VALIDACAO_NF_MIP_AGENDADA=True
        return processar_proxima_validacao_nf_mip()

    def handle(self, *args, **options):
        interrompidos = recuperar_envios_mip_interrompidos()
        if interrompidos:
            self.stdout.write(f"MIP: {len(interrompidos)} envio(s) interrompido(s) recuperado(s).")
            return

        mip_em = proximo_enfileirado_rpa_mip_em()
        ri_mais_antigo = (
            LogRpaEace.objects.filter(resultado=LogRpaEace.NA_FILA).order_by("enfileirado_em").first()
        )
        ri_em = ri_mais_antigo.enfileirado_em if ri_mais_antigo else None
        if mip_em and (ri_em is None or mip_em < ri_em):
            resultado = processar_proximo_rpa_mip()
            tipo = "MIP"
        else:
            resultado = processar_proximo_da_fila_rpa_eace()
            tipo = "RI"

        if resultado is None:
            # Pedido do usuário (2026-09-29): com a fila de envios (RI/MIP)
            # vazia, o mesmo worker processa a Validação MIP (NF) - leitura
            # de status do portal, `apps.escolas.validacao_nf_mip` - em vez
            # de um container próprio; continua 1 login no portal por vez.
            validacao = self._processar_validacao_nf_mip()
            if validacao is None:
                self.stdout.write("Fila vazia - nada para processar.")
            else:
                self.stdout.write(self.style.SUCCESS(
                    f"Validação MIP (NF) #{validacao.pk}: {validacao.get_status_display()}"
                    f"{f' ({validacao.motivo_erro})' if validacao.motivo_erro else ''}"
                ))
            return
        if "orfaos_recuperados" in resultado:
            self.stdout.write(f"RI: {len(resultado['orfaos_recuperados'])} log(s) interrompido(s) recuperado(s).")
            return

        detalhe = f" ({resultado['motivo']})" if resultado["motivo"] else ""
        self.stdout.write(
            self.style.SUCCESS(f"{tipo} - Log {resultado['log_id']}: {resultado['resultado']}{detalhe}")
        )
