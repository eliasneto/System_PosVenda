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
# Aviso na TV (pedido do usuário, 2026-11-16): fica 1 minuto (6 atualizações de 10 s) a partir de uma redução e some;
# só volta numa redução nova, pelo menos 1 minuto depois de sumir.
SEGUNDOS_AVISO = 60
SEGUNDOS_SEM_AVISO = 60


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


def amostra_cpu(caminho: str) -> tuple[int, int]:
    """(total, ocioso) em ticks de /proc/stat, somando todos os núcleos (linha "cpu")."""
    with open(caminho, encoding="ascii") as arquivo:
        campos = [int(v) for v in arquivo.readline().split()[1:9]]
    user, nice, system, idle, iowait, irq, softirq, steal = (campos + [0] * 8)[:8]
    return user + nice + system + idle + iowait + irq + softirq + steal, idle + iowait


class UsoDosRobos:
    """Memória e processador de cada robô, em % da máquina (painel técnico, pedido do usuário, 2026-11-16).

    Cada robô é 1 processo do supervisor mais os filhos (o Chromium do Playwright e os processos dele): soma a
    memória (RSS) e o tempo de processador de toda a árvore lendo /proc. Processador = tempo usado desde a medição
    anterior ÷ (tempo passado × núcleos); sem medição anterior do mesmo processo (passada nova), a média desde
    que ele começou. `proc` injetável para teste.

    `cpu_servidor_pct` (correção 2026-11-17): o processador da máquina inteira medido na MESMA janela dos robôs.
    Antes a TV media o total por conta própria, em outra janela (cada um dos 5 processos do gunicorn guardava a
    sua leitura anterior, então o total era a média de 20-50 s contra os últimos 5 s dos robôs) e a soma dos
    robôs passava do total. `None` na 1ª medição ou fora do Linux."""

    def __init__(self, proc: str = "/proc"):
        self.proc = proc
        self._anterior: dict = {}  # chave do robô -> (pid, instante, ticks)
        self._ticks_por_segundo = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
        self._stat_anterior: tuple[int, int] | None = None
        self.cpu_servidor_pct: int | None = None

    def _medir_servidor(self) -> None:
        try:
            total, ocioso = amostra_cpu(f"{self.proc}/stat")
        except (OSError, ValueError):
            self._stat_anterior, self.cpu_servidor_pct = None, None
            return
        anterior, self._stat_anterior = self._stat_anterior, (total, ocioso)
        delta_total = total - anterior[0] if anterior else 0
        if delta_total <= 0:
            self.cpu_servidor_pct = None
            return
        ocupado = delta_total - (ocioso - anterior[1])
        self.cpu_servidor_pct = max(0, min(100, round(100 * ocupado / delta_total)))

    def _processos(self) -> dict[int, tuple[int, int, int, int]]:
        """pid -> (ppid, ticks de processador, memória em kB, início em ticks desde o boot)."""
        pagina_kb = (os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096) // 1024
        processos = {}
        for nome in os.listdir(self.proc):
            if not nome.isdigit():
                continue
            try:
                with open(f"{self.proc}/{nome}/stat", encoding="ascii", errors="replace") as arquivo:
                    texto = arquivo.read()
            except OSError:  # o processo terminou entre o listdir e a leitura
                continue
            campos = texto[texto.rfind(")") + 2:].split()  # o nome do processo pode ter espaço e parêntese
            try:
                processos[int(nome)] = (int(campos[1]), int(campos[11]) + int(campos[12]),
                                        int(campos[21]) * pagina_kb, int(campos[19]))
            except (IndexError, ValueError):
                continue
        return processos

    def _segundos_desde_o_boot(self) -> float:
        try:
            with open(f"{self.proc}/uptime", encoding="ascii") as arquivo:
                return float(arquivo.read().split()[0])
        except (OSError, ValueError, IndexError):
            return 0.0

    def medir(self, raizes: dict, recursos: Recursos | None, agora: float | None = None) -> dict[str, dict]:
        """`raizes`: chave do robô -> pid do processo dele. Devolve {chave: {"memoria_pct", "cpu_pct",
        "memoria_mb"}} (chave em texto, para gravar em JSON). Atualiza também `cpu_servidor_pct`."""
        if recursos is None:
            self._anterior, self._stat_anterior, self.cpu_servidor_pct = {}, None, None
            return {}
        agora = time.monotonic() if agora is None else agora
        processos = self._processos()
        self._medir_servidor()  # logo depois dos processos: mesma janela que o uso dos robôs
        if not raizes:
            self._anterior = {}
            return {}
        filhos: dict[int, list[int]] = {}
        for pid, (ppid, *_resto) in processos.items():
            filhos.setdefault(ppid, []).append(pid)
        uptime = self._segundos_desde_o_boot()
        uso, anterior_novo = {}, {}
        for chave, raiz in raizes.items():
            if raiz not in processos:
                continue
            arvore, pendentes = [], [raiz]
            while pendentes:
                pid = pendentes.pop()
                arvore.append(pid)
                pendentes.extend(filhos.get(pid, ()))
            ticks = sum(processos[pid][1] for pid in arvore)
            memoria_kb = sum(processos[pid][2] for pid in arvore)
            anterior = self._anterior.get(chave)
            if anterior and anterior[0] == raiz and agora > anterior[1]:
                segundos, usados = agora - anterior[1], ticks - anterior[2]
            else:  # passada nova: média desde que o processo começou
                segundos = uptime - processos[raiz][3] / self._ticks_por_segundo
                usados = ticks
            cpu = 100 * usados / self._ticks_por_segundo / (segundos * recursos.nucleos) if segundos > 0 else 0
            uso[str(chave)] = {
                "memoria_pct": round(min(100.0, 100 * memoria_kb / 1024 / recursos.total_mb), 1) if recursos.total_mb else 0,
                "cpu_pct": round(max(0.0, min(100.0, cpu)), 1),
                "memoria_mb": round(memoria_kb / 1024),
            }
            anterior_novo[chave] = (raiz, agora, ticks)
        self._anterior = anterior_novo
        return uso


class FreioDeSeguranca:
    """Limite dinâmico de robôs (ver docstring do módulo). `agora` injetável
    para teste. `capacidade` já vem limitada aos robôs ativos no cadastro: o
    limite nunca passa de quantos robôs existem para rodar (bug de 2026-11-16:
    com 5 ativos e teto manual alto a TV mostrava "reduzidos para 9")."""

    def __init__(self):
        self.limite: int | None = None  # None = sem freio (vale a capacidade)
        self.motivo = ""
        self._ultima_mudanca = 0.0
        self._aviso_desde: float | None = None

    def aviso_ativo(self, agora: float | None = None) -> bool:
        """O aviso do freio aparece na TV (só no 1º minuto depois de uma redução)."""
        agora = time.monotonic() if agora is None else agora
        return self._aviso_desde is not None and agora - self._aviso_desde < SEGUNDOS_AVISO

    def _reduziu(self, agora: float) -> None:
        if self._aviso_desde is None or agora - self._aviso_desde >= SEGUNDOS_AVISO + SEGUNDOS_SEM_AVISO:
            self._aviso_desde = agora

    def atualizar(self, recursos: Recursos | None, rodando: int, capacidade: int, agora: float | None = None) -> int:
        agora = time.monotonic() if agora is None else agora
        if recursos is None:
            return capacidade
        aperto = memoria_apertada(recursos)
        if aperto:
            if agora - self._ultima_mudanca >= SEGUNDOS_ENTRE_REDUCOES:
                atual = self.limite if self.limite is not None else min(rodando, capacidade)
                novo = max(1, min(atual, rodando, capacidade) - 1)
                if self.limite is None or novo < self.limite:
                    self._reduziu(agora)
                self.limite = novo
                self.motivo = aperto
                self._ultima_mudanca = agora
        elif self.limite is not None and self.limite >= capacidade:  # já cabem todos os robôs ativos
            self.limite, self.motivo = None, ""
        elif self.limite is not None and recursos.disponivel_mb >= DISPONIVEL_FOLGA_MB:
            if agora - self._ultima_mudanca >= SEGUNDOS_ENTRE_AUMENTOS:
                self.limite += 1
                self._ultima_mudanca = agora
                if self.limite >= capacidade:
                    self.limite, self.motivo = None, ""
        return min(capacidade, self.limite) if self.limite is not None else capacidade
