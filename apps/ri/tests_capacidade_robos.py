"""Capacidade da máquina e freio de segurança dos robôs do RPA EACE
(`apps.ri.capacidade_robos`)."""

from django.test import SimpleTestCase

from apps.ri.capacidade_robos import FreioDeSeguranca, Recursos, capacidade_maquina, memoria_apertada

GB = 1024


def recursos(total_gb, nucleos, disponivel_gb=None, swap_livre_mb=3000, swap_total_mb=3800):
    return Recursos(
        total_mb=int(total_gb * GB), disponivel_mb=int((disponivel_gb if disponivel_gb is not None else total_gb) * GB),
        swap_total_mb=swap_total_mb, swap_livre_mb=swap_livre_mb, nucleos=nucleos,
    )


class CapacidadeMaquinaTests(SimpleTestCase):

    def test_maquinas_de_hoje(self):
        self.assertEqual(capacidade_maquina(recursos(3.8, 4)), 1)     # antes do upgrade
        self.assertEqual(capacidade_maquina(recursos(19.5, 12)), 6)   # o que se viu na prática
        self.assertEqual(capacidade_maquina(recursos(49, 24)), 12)

    def test_limitado_pelos_nucleos(self):
        self.assertEqual(capacidade_maquina(recursos(100, 6)), 3)

    def test_fora_do_linux_nao_limita(self):
        self.assertEqual(capacidade_maquina(None), 999)


class FreioDeSegurancaTests(SimpleTestCase):

    def test_memoria_apertada(self):
        self.assertEqual(memoria_apertada(recursos(50, 24, disponivel_gb=10)), "")
        self.assertIn("memória disponível", memoria_apertada(recursos(50, 24, disponivel_gb=1.5)))
        self.assertEqual(memoria_apertada(recursos(50, 24, disponivel_gb=10, swap_livre_mb=500)), "")
        self.assertIn("swap", memoria_apertada(recursos(50, 24, disponivel_gb=3, swap_livre_mb=500)))
        self.assertEqual(memoria_apertada(recursos(50, 24, disponivel_gb=10, swap_livre_mb=0, swap_total_mb=0)), "")

    def test_reduz_1_por_vez_e_volta_com_folga(self):
        freio = FreioDeSeguranca()
        apertado, folgado = recursos(50, 24, disponivel_gb=1), recursos(50, 24, disponivel_gb=10)
        self.assertEqual(freio.atualizar(folgado, rodando=15, capacidade=16, agora=0), 16)
        self.assertEqual(freio.atualizar(apertado, rodando=15, capacidade=16, agora=100), 14)
        self.assertEqual(freio.atualizar(apertado, rodando=15, capacidade=16, agora=110), 14)  # espera 30 s
        self.assertEqual(freio.atualizar(apertado, rodando=14, capacidade=16, agora=131), 13)
        self.assertTrue(freio.motivo)
        self.assertEqual(freio.atualizar(folgado, rodando=13, capacidade=16, agora=150), 13)   # espera 60 s
        self.assertEqual(freio.atualizar(folgado, rodando=13, capacidade=16, agora=192), 14)
        self.assertEqual(freio.atualizar(folgado, rodando=14, capacidade=16, agora=253), 15)
        self.assertEqual(freio.atualizar(folgado, rodando=15, capacidade=16, agora=314), 16)
        self.assertEqual(freio.motivo, "")

    def test_limite_nunca_passa_dos_robos_ativos(self):
        # 2026-11-16: 5 robôs ativos e teto manual alto - a TV mostrava "reduzidos para 9"
        freio = FreioDeSeguranca()
        apertado, folgado = recursos(12, 6, disponivel_gb=1.9), recursos(12, 6, disponivel_gb=5)
        self.assertEqual(freio.atualizar(apertado, rodando=5, capacidade=5, agora=100), 4)
        self.assertEqual(freio.atualizar(folgado, rodando=4, capacidade=5, agora=170), 5)
        self.assertEqual(freio.motivo, "")
        self.assertIsNone(freio.limite)
        for agora in range(230, 1000, 60):
            self.assertEqual(freio.atualizar(folgado, rodando=5, capacidade=5, agora=agora), 5)
        # robôs desativados no meio do freio: o limite cai junto e o freio acaba
        freio.atualizar(apertado, rodando=5, capacidade=5, agora=1100)
        self.assertEqual(freio.atualizar(folgado, rodando=3, capacidade=3, agora=1110), 3)
        self.assertIsNone(freio.limite)

    def test_aviso_fica_1_minuto_e_so_volta_1_minuto_depois_de_sumir(self):
        freio = FreioDeSeguranca()
        apertado = recursos(12, 6, disponivel_gb=1.9)
        self.assertFalse(freio.aviso_ativo(agora=0))
        freio.atualizar(apertado, rodando=5, capacidade=5, agora=100)   # reduz para 4: aviso
        self.assertTrue(freio.aviso_ativo(agora=100))
        self.assertTrue(freio.aviso_ativo(agora=159))
        freio.atualizar(apertado, rodando=4, capacidade=5, agora=131)   # reduz para 3 dentro do minuto
        self.assertFalse(freio.aviso_ativo(agora=160))                  # some no 60º segundo
        freio.atualizar(apertado, rodando=3, capacidade=5, agora=200)   # reduz para 2: ainda no minuto sem aviso
        self.assertFalse(freio.aviso_ativo(agora=200))
        freio.atualizar(apertado, rodando=2, capacidade=5, agora=231)   # reduz para 1 depois de 1 min sem aviso
        self.assertTrue(freio.aviso_ativo(agora=231))
        freio.atualizar(apertado, rodando=1, capacidade=5, agora=262)   # já no mínimo: não reduz, não renova
        self.assertFalse(freio.aviso_ativo(agora=291))

    def test_uso_de_cada_robo_soma_o_navegador_e_vem_em_porcentagem(self):
        import os
        import tempfile

        from apps.ri.capacidade_robos import UsoDosRobos

        proc = tempfile.mkdtemp()

        def processo(pid, ppid, ticks, rss_paginas, inicio=0, nome="python"):
            os.makedirs(f"{proc}/{pid}", exist_ok=True)
            campos = ["S", ppid] + [0] * 9 + [ticks, 0] + [0] * 6 + [inicio, 0, rss_paginas]
            with open(f"{proc}/{pid}/stat", "w", encoding="ascii") as arquivo:
                arquivo.write(f"{pid} ({nome}) " + " ".join(str(c) for c in campos))

        with open(f"{proc}/uptime", "w", encoding="ascii") as arquivo:
            arquivo.write("1000.0 0")
        maquina = recursos(10, 4)
        pagina = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
        um_gb = GB * 1024 * 1024 // pagina
        processo(100, 1, 0, um_gb // 2)                      # robô 2
        processo(101, 100, 0, um_gb // 2, nome="chrome (gpu)")  # Chromium dele
        processo(200, 1, 0, um_gb)                           # robô 3, sem filho
        processo(300, 1, 0, um_gb * 5)                       # outro processo: não entra
        uso = UsoDosRobos(proc)
        ticks = uso._ticks_por_segundo
        primeira = uso.medir({2: 100, 3: 200, 9: 999}, maquina, agora=10)
        self.assertEqual(set(primeira), {"2", "3"})            # o robô 9 não tem processo
        self.assertEqual(primeira["2"]["memoria_pct"], 10.0)   # 1 GB de 10 GB, robô + navegador
        self.assertEqual(primeira["2"]["memoria_mb"], 1024)
        processo(100, 1, ticks * 2, um_gb // 2)
        processo(101, 100, ticks * 2, um_gb // 2, nome="chrome (gpu)")
        segunda = uso.medir({2: 100, 3: 200}, maquina, agora=12)
        # 4 s de processador em 2 s com 4 núcleos = 50% da máquina
        self.assertEqual(segunda["2"]["cpu_pct"], 50.0)
        self.assertEqual(segunda["3"]["cpu_pct"], 0.0)
        self.assertEqual(uso.medir({}, maquina), {})

    def test_nunca_abaixo_de_1(self):
        freio = FreioDeSeguranca()
        apertado = recursos(50, 24, disponivel_gb=0.5)
        for i in range(10):
            limite = freio.atualizar(apertado, rodando=1, capacidade=16, agora=i * 31)
        self.assertEqual(limite, 1)
