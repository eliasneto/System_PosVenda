"""Quantos robôs do RPA EACE a máquina aguenta em paralelo (pedido do usuário,
2026-11-11).

Duas partes, sempre lendo os recursos ATUAIS da máquina (/proc do Linux, que
dentro do container mostra a máquina inteira) - se a infra aumentar ou
diminuir memória/núcleos, o limite acompanha sem mudar configuração:

1. **Capacidade da máquina** (`capacidade_maquina`): quantos robôs cabem
   "tranquilos" pela memória total e pelos núcleos, com os valores medidos em
   produção em 2026-11-11 (pico de ~2,8 GB e ~2 núcleos por robô, ~3 GB do
   resto do servidor). Ex.: 20 GB/12 núcleos -> 6 (o que se viu na prática);
   50 GB/24 núcleos -> 12 (com 15, 1 nota em 4 falhava por processador cheio).
2. **Freio de segurança** (`FreioDeSeguranca`): mesmo abaixo da capacidade,
   se a memória disponível cair abaixo de 2 GB ou o swap livre abaixo de
   1 GB, o limite desce 1 robô (no máximo a cada 30 s) - o robô de número mais
   alto termina a nota atual e não pega outra. Com folga (mais de 4 GB
   disponíveis) o limite sobe de volta, 1 robô por minuto, até a capacidade.

O supervisor (`supervisionar_robos_rpa_eace`) usa o teto manual
`RPA_EACE_MAX_ROBOS` quando configurado (escolha do usuário prevalece) ou, sem
ele, a capacidade da máquina - e o freio de segurança pode reduzir os dois.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from decouple import config as env

MB_POR_ROBO = env("RPA_EACE_MB_POR_ROBO", default=2800, cast=int)
NUCLEOS_POR_ROBO = env("RPA_EACE_NUCLEOS_POR_ROBO", default=2.0, cast=float)
MB_RESERVADOS = env("RPA_EACE_MB_RESERVADOS", default=3000, cast=int)

DISPONIVEL_MINIMO_MB = 2048
SWAP_LIVRE_MINIMO_MB = 1024
DISPONIVEL_FOLGA_MB = 4096
SEGUNDOS_ENTRE_REDUCOES = 30
SEGUNDOS_ENTRE_AUMENTOS = 60


@dataclass(frozen=True)
class Recursos:
    total_mb: int
    disponivel_mb: int
    swap_total_mb: int
    swap_livre_mb: int
    nucleos: int


def ler_recursos(meminfo: str = "/proc/meminfo") -> Recursos | None:
    """Memória e núcleos atuais da máquina; `None` fora do Linux."""
    valores = {}
    try:
        with open(meminfo, encoding="ascii") as arquivo:
            for linha in arquivo:
                nome, _, resto = linha.partition(":")
                partes = resto.split()
                if partes:
                    valores[nome] = int(partes[0]) // 1024  # kB -> MB
    except (OSError, ValueError):
        return None
    return Recursos(
        total_mb=valores.get("MemTotal", 0),
        disponivel_mb=valores.get("MemAvailable", 0),
        swap_total_mb=valores.get("SwapTotal", 0),
        swap_livre_mb=valores.get("SwapFree", 0),
        nucleos=os.cpu_count() or 1,
    )


def capacidade_maquina(recursos: Recursos | None) -> int:
    """Robôs que cabem "tranquilos" na máquina (mínimo 1). Sem leitura dos
    recursos (fora do Linux), não limita (999)."""
    if recursos is None:
        return 999
    pela_memoria = (recursos.total_mb - MB_RESERVADOS) // MB_POR_ROBO
    pelos_nucleos = int(recursos.nucleos // NUCLEOS_POR_ROBO)
    return max(1, min(pela_memoria, pelos_nucleos))


def memoria_apertada(recursos: Recursos) -> str:
    """Motivo do aperto ("" se está tudo bem)."""
    if recursos.disponivel_mb < DISPONIVEL_MINIMO_MB:
        return f"memória disponível baixa ({recursos.disponivel_mb} MB)"
    # Swap cheio só é perigo junto com pouca memória: páginas paradas no swap
    # (servidor ligado há semanas) com RAM sobrando não justificam frear.
    if (
        recursos.swap_total_mb
        and recursos.swap_livre_mb < SWAP_LIVRE_MINIMO_MB
        and recursos.disponivel_mb < DISPONIVEL_FOLGA_MB
    ):
        return f"swap quase cheio ({recursos.swap_livre_mb} MB livres) com pouca memória"
    return ""


class FreioDeSeguranca:
    """Limite dinâmico de robôs (ver docstring do módulo). `agora` injetável
    para teste."""

    def __init__(self):
        self.limite: int | None = None  # None = sem freio (vale a capacidade)
        self.motivo = ""
        self._ultima_mudanca = 0.0

    def atualizar(self, recursos: Recursos | None, rodando: int, capacidade: int, agora: float | None = None) -> int:
        agora = time.monotonic() if agora is None else agora
        if recursos is None:
            return capacidade
        aperto = memoria_apertada(recursos)
        if aperto:
            if agora - self._ultima_mudanca >= SEGUNDOS_ENTRE_REDUCOES:
                atual = self.limite if self.limite is not None else min(rodando, capacidade)
                self.limite = max(1, min(atual, rodando) - 1)
                self.motivo = aperto
                self._ultima_mudanca = agora
        elif self.limite is not None and recursos.disponivel_mb >= DISPONIVEL_FOLGA_MB:
            if agora - self._ultima_mudanca >= SEGUNDOS_ENTRE_AUMENTOS:
                self.limite += 1
                self._ultima_mudanca = agora
                if self.limite >= capacidade:
                    self.limite, self.motivo = None, ""
        return min(capacidade, self.limite) if self.limite is not None else capacidade
