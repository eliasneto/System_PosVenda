import signal
import subprocess
import sys
import time
from pathlib import Path

from decouple import config as env
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections

from apps.core.models import RoboRpaEace
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
            help="Teto de robôs rodando ao mesmo tempo (cada um abre um Chromium de ~2,5 GB); padrão 3.",
        )
        parser.add_argument(
            "--intervalo", type=float,
            default=env("RPA_EACE_POLL_INTERVAL_SECONDS", default=5, cast=float),
            help="Segundos entre 2 passadas do mesmo robô (padrão 5).",
        )

    def handle(self, *args, **options):
        intervalo = options["intervalo"]
        max_robos = max(1, options["max_robos"])
        manage_py = str(Path(settings.BASE_DIR) / "manage.py")
        rodando: dict[int | None, subprocess.Popen] = {}
        proxima_passada: dict[int | None, float] = {}
        parar = False

        def _parar(*_):
            nonlocal parar
            parar = True

        signal.signal(signal.SIGTERM, _parar)
        signal.signal(signal.SIGINT, _parar)
        self.stdout.write(f"Supervisor dos robôs do RPA EACE iniciado (máximo {max_robos} robô(s) ao mesmo tempo).")

        while not parar:
            for chave, processo in list(rodando.items()):
                if processo.poll() is not None:
                    del rodando[chave]
                    proxima_passada[chave] = time.monotonic() + intervalo
            try:
                # Teto de memória: só os N primeiros robôs ativos (ordem do
                # cadastro) rodam; os outros ficam esperando no admin.
                ativos = list(
                    RoboRpaEace.objects.filter(ativo=True).order_by("pk").values_list("pk", flat=True)[:max_robos]
                )
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

        for processo in rodando.values():
            processo.terminate()
        for processo in rodando.values():
            try:
                processo.wait(timeout=20)
            except subprocess.TimeoutExpired:
                processo.kill()
        self.stdout.write("Supervisor dos robôs do RPA EACE encerrado.")
