"""Painel da fila do RPA EACE para TV (`apps.ri.views_fila_tv`) e
atualização automática da tela "Projeto > Fila"."""

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import RoboRpaEace, User
from apps.escolas.models import Escola
from apps.ri.models import LogRpaEace, Ri

TOKEN = "codigo-de-teste-da-tv"


@override_settings(FILA_TV_TOKEN=TOKEN)
class FilaTvTests(TestCase):

    def setUp(self):
        self.robo = RoboRpaEace.objects.create(nome="Robô 1", usuario="r@t", senha="x")
        escola = Escola.objects.create(inep="11000001", nome="ESCOLA PROCESSANDO")
        ri = Ri.objects.create(escola=escola)
        LogRpaEace.objects.create(ri=ri, resultado=LogRpaEace.PROCESSANDO, robo=self.robo,
                                  etapa_atual="Anexando o PDF e o XML", progresso_pct=81)
        LogRpaEace.objects.create(ri=ri, resultado=LogRpaEace.NA_FILA, enfileirado_em=timezone.now())
        LogRpaEace.objects.create(ri=ri, resultado=LogRpaEace.SUCESSO, executado_em=timezone.now())

    def test_abre_sem_login_e_mostra_o_que_esta_rodando(self):
        resp = self.client.get(reverse("fila_tv", args=[TOKEN]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "11000001")
        self.assertContains(resp, "Robô 1")
        self.assertContains(resp, "81% — Anexando o PDF e o XML")
        self.assertContains(resp, "trabalhando")
        self.assertEqual(resp.context["total_na_fila"], 1)
        self.assertEqual(resp.context["sucesso_hoje"], 1)

    def test_conteudo_parcial_para_a_atualizacao_de_10_s(self):
        resp = self.client.get(reverse("fila_tv_conteudo", args=[TOKEN]))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "<html")
        self.assertContains(resp, "hora-servidor")
        self.assertIn("no-cache", resp["Cache-Control"])

    def test_codigo_errado_404(self):
        self.assertEqual(self.client.get(reverse("fila_tv", args=["errado"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("fila_tv_conteudo", args=["errado"])).status_code, 404)

    @override_settings(FILA_TV_TOKEN="")
    def test_sem_codigo_configurado_painel_desligado(self):
        self.assertEqual(self.client.get(reverse("fila_tv", args=[TOKEN])).status_code, 404)

    def test_usuario_visualizador_logado_tambem_abre(self):
        user = User.objects.create_user(username="tv", password="senha-teste-123")
        user.acesso_liberado = False
        user.save()
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("fila_tv", args=[TOKEN])).status_code, 200)

    def test_tela_fila_atualiza_sozinha_e_mostra_o_botao_da_tv(self):
        user = User.objects.create_user(username="analista", password="senha-teste-123", acesso_liberado=True)
        self.client.force_login(user)
        resp = self.client.get(reverse("fila_rpa_eace"), {"status": "andamento"})
        self.assertContains(resp, 'id="fila-conteudo"')
        self.assertContains(resp, 'hx-trigger="every 10s"')
        self.assertContains(resp, 'hx-select-oob="#fila-totais"')
        self.assertContains(resp, reverse("fila_tv", args=[TOKEN]))
