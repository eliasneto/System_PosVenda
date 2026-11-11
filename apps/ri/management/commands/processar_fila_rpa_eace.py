from django.core.management.base import BaseCommand, CommandError

from apps.core.models import RoboRpaEace
from apps.escolas.leitura_eace_bdo import processar_proxima_leitura_eace_bdo, recuperar_leituras_interrompidas
from apps.escolas.validacao_nf_mip import (
    agendar_validacao_nf_mip_se_devido,
    processar_proxima_validacao_nf_mip,
    recuperar_validacoes_interrompidas,
)
from apps.integracoes.eace.config import usar_credenciais_do_robo
from apps.ri.fila_rpa_eace import (
    executar_envio_reservado,
    filtro_dos_robos,
    recuperar_envios_interrompidos,
    reservar_proximo_envio,
)


class Command(BaseCommand):
    """FEAT-033 (Fase 3, RN-058): 1 passada de 1 robô da fila do RPA EACE -
    pega o envio "Na fila" mais antigo (RI ou MIP, ordem de chegada) e
    processa. Não agenda nada sozinho - quem chama de novo é o supervisor
    (`supervisionar_robos_rpa_eace`, container `rpa_eace_worker`).

    ADR-009 (pedido do usuário, 2026-11-10): `--robo <id>` roda como o robô
    cadastrado no admin (login próprio no portal EACE, navegador próprio,
    neste processo); sem `--robo`, é o robô padrão com o login do `.env`.
    Vários robôs rodam ao mesmo tempo, cada um no seu processo, sem nunca
    pegar o mesmo item nem 2 itens do mesmo INEP (`apps.ri.fila_rpa_eace`).

    Com os envios (RI/MIP) vazios ou todos com INEP ocupado, processa a
    Leitura EACE do BDO e depois a Validação MIP (NF) - só leitura do
    portal (pedidos do usuário, 2026-09-29 e 2026-10-16)."""

    help = (
        "Processa 1 item da fila do RPA EACE (RN-058/ADR-009) - RI ou MIP, o "
        "mais antigo 'Na fila' com INEP livre - como o robô --robo (ou o "
        "robô padrão do .env)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--robo", type=int, help="id do Robô do RPA EACE (admin); vazio = login do .env")

    @staticmethod
    def _processar_validacao_nf_mip():
        recuperar_validacoes_interrompidas()
        agendar_validacao_nf_mip_se_devido()  # só age com VALIDACAO_NF_MIP_AGENDADA=True
        return processar_proxima_validacao_nf_mip()

    def handle(self, *args, **options):
        robo = None
        if options.get("robo"):
            robo = RoboRpaEace.objects.filter(pk=options["robo"], ativo=True).first()
            if robo is None:
                raise CommandError(f"Robô {options['robo']} não existe ou está inativo.")
            usar_credenciais_do_robo(robo.usuario, robo.senha)
        nome = robo.nome if robo else "padrão (.env)"

        # Só os envios deste mesmo robô: se ainda estão "Processando" no
        # começo de uma passada dele, a passada anterior morreu no meio.
        recuperados = recuperar_envios_interrompidos(filtro_dos_robos({robo.pk if robo else None}))
        if recuperados:
            self.stdout.write(f"[{nome}] {len(recuperados)} envio(s) interrompido(s) recuperado(s): {recuperados}")
            return

        reserva = reservar_proximo_envio(robo)
        if reserva is not None:
            tipo, log_id = reserva
            resultado = executar_envio_reservado(tipo, log_id)
            detalhe = f" ({resultado['motivo']})" if resultado["motivo"] else ""
            self.stdout.write(self.style.SUCCESS(
                f"[{nome}] {tipo} - Log {resultado['log_id']}: {resultado['resultado']}{detalhe}"
            ))
            return

        recuperar_leituras_interrompidas()
        leitura = processar_proxima_leitura_eace_bdo()
        if leitura is not None:
            self.stdout.write(self.style.SUCCESS(
                f"[{nome}] Leitura EACE do BDO #{leitura.pk}: {leitura.get_status_display()}"
                f"{f' ({leitura.motivo_erro})' if leitura.motivo_erro else ''}"
            ))
            return
        validacao = self._processar_validacao_nf_mip()
        if validacao is None:
            self.stdout.write(f"[{nome}] Fila vazia - nada para processar.")
        else:
            self.stdout.write(self.style.SUCCESS(
                f"[{nome}] Validação MIP (NF) #{validacao.pk}: {validacao.get_status_display()}"
                f"{f' ({validacao.motivo_erro})' if validacao.motivo_erro else ''}"
            ))
