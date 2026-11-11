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

    def test_nunca_abaixo_de_1(self):
        freio = FreioDeSeguranca()
        apertado = recursos(50, 24, disponivel_gb=0.5)
        for i in range(10):
            limite = freio.atualizar(apertado, rodando=1, capacidade=16, agora=i * 31)
        self.assertEqual(limite, 1)
