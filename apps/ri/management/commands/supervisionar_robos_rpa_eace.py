import signal
import subprocess
import sys
import time
from pathlib import Path

from decouple import config as env
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

from apps.core.models import EstadoRobosRpaEace, RoboRpaEace
from apps.ri.capacidade_robos import FreioDeSeguranca, capacidade_maquina, ler_recursos
from apps.ri.fila_rpa_eace import recuperar_envios_de_robos_parados

PADRAO = None  # robô padrão (login do .env), usado quando não há robô ativo


class Command(BaseCommand):
    """ADR-009 (pedido do usuário, 2026-11-10): processo principal do
    container `rpa_eace_worker`. Mantém 1 processo por robô ativo do admin
    ("Robôs do RPA EACE"), cada um rodando `processar_fila_rpa_eace --robo
    <id>` em loop - 1 passada por processo, então cada execução abre e fecha
    o próprio navegador. Sem robô ativo, roda só o robô padrão do `.env`.

    Lê o cadastro a cada segundo: robô novo/reativado começa na hora; robô
    desativado termina o item em andamento e não volta. Envio "Processando"
    de robô sem processo rodando (processo morto no meio) volta para a fila
    (RN-058)."""

    help = "Supervisiona os robôs do RPA EACE (1 processo por robô ativo)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-robos", type=int,
            default=settings.RPA_EACE_MAX_ROBOS,
            help="Teto manual de robôs ao mesmo tempo; 0 = automático pela capacidade da máquina "
                 "(apps.ri.capacidade_robos).",
        )
        parser.add_argument(
            "--espera-desligar", type=float, default=300,
            help="Ao receber SIGTERM, segundos esperando os robôs terminarem a nota atual (padrão 300).",
        )
        parser.add_argument(
            "--intervalo", type=float,
            default=env("RPA_EACE_POLL_INTERVAL_SECONDS", default=5, cast=float),
            help="Segundos entre 2 passadas do mesmo robô (padrão 5).",
        )

    def handle(self, *args, **options):
        intervalo = options["intervalo"]
        teto_manual = max(0, options["max_robos"] or 0)
        freio = FreioDeSeguranca()
        limite_anterior = None
        estado_gravado_em = 0.0
        manage_py = str(Path(settings.BASE_DIR) / "manage.py")
        rodando: dict[int | None, subprocess.Popen] = {}
        proxima_passada: dict[int | None, float] = {}
        parar = False

        def _parar(*_):
            nonlocal parar
            parar = True

        signal.signal(signal.SIGTERM, _parar)
        signal.signal(signal.SIGINT, _parar)
        self.stdout.write(
            "Supervisor dos robôs do RPA EACE iniciado "
            f"(teto manual: {teto_manual or 'automático'}; capacidade da máquina: "
            f"{capacidade_maquina(ler_recursos())} robô(s))."
        )

        while not parar:
            for chave, processo in list(rodando.items()):
                if processo.poll() is not None:
                    del rodando[chave]
                    proxima_passada[chave] = time.monotonic() + intervalo
            # Limite em vigor (pedido do usuário, 2026-11-11): com teto manual
            # (RPA_EACE_MAX_ROBOS) é ele que manda - o usuário escolheu 15 numa
            # máquina cuja capacidade calculada é 12; sem teto, vale a
            # capacidade da máquina lida AGORA. Em qualquer caso o freio de
            # segurança de memória/swap pode reduzir. Só os N primeiros robôs
            # ativos (ordem do cadastro) rodam; acima disso terminam a nota
            # atual e esperam.
            recursos = ler_recursos()
            capacidade = capacidade_maquina(recursos)
            limite = freio.atualizar(recursos, len(rodando), teto_manual or capacidade)
            if limite != limite_anterior:
                self.stdout.write(
                    f"Limite de robôs: {limite} (capacidade da máquina {capacidade}"
                    f"{f', teto manual {teto_manual}' if teto_manual else ''}"
                    f"{f', freio: {freio.motivo}' if freio.motivo else ''})."
                )
                limite_anterior = limite
            try:
                ativos = list(
                    RoboRpaEace.objects.filter(ativo=True).order_by("pk").values_list("pk", flat=True)[:limite]
                )
                if time.monotonic() - estado_gravado_em >= 15:
                    EstadoRobosRpaEace.objects.update_or_create(pk=1, defaults={
                        "capacidade_maquina": min(capacidade, 999),
                        "limite_atual": limite,
                        "teto_manual": teto_manual,
                        "robos_rodando": len(rodando),
                        "freio_motivo": freio.motivo[:120],
                        "recursos": (
                            f"{recursos.nucleos} núcleos · {recursos.total_mb / 1024:.0f} GB de memória"
                            if recursos else ""
                        ),
                        "atualizado_em": timezone.now(),
                    })
                    estado_gravado_em = time.monotonic()
                recuperados = recuperar_envios_de_robos_parados(set(rodando))
                if recuperados:
                    self.stdout.write(f"Envio(s) de robô parado recuperado(s): {recuperados}")
            except Exception as exc:  # banco fora do ar: tenta de novo no próximo ciclo
                self.stderr.write(f"Supervisor: erro ao ler os robôs ({exc}).")
                close_old_connections()
                time.sleep(5)
                continue
            finally:
                close_old_connections()

            for chave in ativos or [PADRAO]:
                if chave in rodando or time.monotonic() < proxima_passada.get(chave, 0):
                    continue
                comando = [sys.executable, manage_py, "processar_fila_rpa_eace"]
                if chave is not PADRAO:
                    comando += ["--robo", str(chave)]
                rodando[chave] = subprocess.Popen(comando)
            time.sleep(1)

        # Desligamento suave (pedido do usuário, 2026-11-11 - deploy não pode
        # quebrar o processamento): o `docker compose stop/up` manda SIGTERM
        # só para este processo (PID 1); os robôs seguem até terminar a nota
        # atual e nenhum novo é iniciado. Só depois de `--espera-desligar`
        # segundos (o `stop_grace_period` do compose precisa ser maior) os
        # que sobrarem são encerrados - a nota deles volta para a fila na
        # próxima subida (recuperação de interrompidos, RN-058).
        if rodando:
            self.stdout.write(
                f"Desligando: aguardando {len(rodando)} robô(s) terminarem a nota atual "
                f"(até {options['espera_desligar']:.0f} s)..."
            )
        limite = time.monotonic() + options["espera_desligar"]
        while rodando and time.monotonic() < limite:
            for chave, processo in list(rodando.items()):
                if processo.poll() is not None:
                    del rodando[chave]
            time.sleep(1)
        for processo in rodando.values():
            processo.terminate()
        for processo in rodando.values():
            try:
                processo.wait(timeout=20)
            except subprocess.TimeoutExpired:
                processo.kill()
        self.stdout.write("Supervisor dos robôs do RPA EACE encerrado.")
