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


@override_settings(FILA_TV_TOKEN=TOKEN)
class FilaTvContagemTests(TestCase):

    def test_reprocessando_agora_nao_conta_como_falha_e_atencao_nao_e_erro(self):
        from apps.ri.views_fila_tv import contexto_fila_tv

        ri = Ri.objects.create(escola=Escola.objects.create(inep="11000002", nome="E"))
        agora = timezone.now()
        LogRpaEace.objects.create(ri=ri, resultado=LogRpaEace.SUCESSO, executado_em=agora)
        LogRpaEace.objects.create(ri=ri, resultado=LogRpaEace.PROCESSANDO, executado_em=agora, motivo_erro="enviar_notas")
        LogRpaEace.objects.create(ri=ri, resultado=LogRpaEace.ATENCAO, executado_em=agora,
                                  motivo_erro="documento_ja_enviado")
        ctx = contexto_fila_tv()
        self.assertEqual(ctx["falha_hora"], 0)
        self.assertEqual(ctx["sucesso_hora"], 2)
        self.assertEqual(ctx["erro_hoje"], 0)
        self.assertEqual(ctx["atencao_hoje"], 1)


class PrevisaoFilaZerarTests(TestCase):

    def test_formatos(self):
        from datetime import datetime

        from apps.ri.views_fila_tv import _previsao_fila_zerar

        agora = timezone.make_aware(datetime(2026, 11, 11, 10, 0))
        self.assertIsNone(_previsao_fila_zerar(0, 10, agora))
        self.assertEqual(_previsao_fila_zerar(5, 0, agora), {"texto": None, "as": None})
        self.assertEqual(_previsao_fila_zerar(10, 60, agora), {"texto": "~10 min", "as": "10:10"})
        self.assertEqual(_previsao_fila_zerar(150, 60, agora), {"texto": "~2 h 30 min", "as": "12:30"})
        self.assertEqual(_previsao_fila_zerar(385, 40, agora)["texto"], "~9 h 38 min")
        self.assertEqual(_previsao_fila_zerar(2000, 40, agora)["texto"], "~2,1 dia(s)")

    def test_so_conta_o_que_saiu_da_fila(self):
        from apps.ri.views_fila_tv import contexto_fila_tv

        ri = Ri.objects.create(escola=Escola.objects.create(inep="11000003", nome="E"))
        agora = timezone.now()
        LogRpaEace.objects.create(ri=ri, resultado=LogRpaEace.SUCESSO, executado_em=agora)
        LogRpaEace.objects.create(ri=ri, resultado=LogRpaEace.NA_FILA, executado_em=agora,
                                  enfileirado_em=agora, motivo_erro="enviar_notas")
        ctx = contexto_fila_tv()
        self.assertEqual(ctx["saida_hora"], 1)
        self.assertEqual(ctx["previsao"]["texto"], "~1 h")


class SaudeServidorTests(TestCase):

    def setUp(self):
        from apps.ri import views_fila_tv

        views_fila_tv._ULTIMA_AMOSTRA_CPU.clear()

    def _arquivos(self, livre_kb, ocupado_pct):
        import tempfile
        from pathlib import Path

        pasta = Path(tempfile.mkdtemp())
        (pasta / "meminfo").write_text(
            f"MemTotal: 12205056 kB\nMemAvailable: {livre_kb} kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n", encoding="ascii")
        stat = pasta / "stat"
        stat.write_text("cpu  0 0 0 0 0 0 0 0 0 0\n", encoding="ascii")
        return str(pasta / "meminfo"), str(stat), ocupado_pct

    def _medir(self, meminfo, stat, ocupado_pct):
        """1ª leitura zerada; durante a pausa, o arquivo passa a ter 1000
        ticks, `ocupado_pct`% deles ocupados."""
        from unittest.mock import patch

        from apps.ri.views_fila_tv import saude_servidor

        def pausa(_):
            ocioso = 1000 - ocupado_pct * 10
            open(stat, "w", encoding="ascii").write(f"cpu  {ocupado_pct * 10} 0 0 {ocioso} 0 0 0 0 0 0\n")

        with patch("apps.ri.views_fila_tv.time.sleep", side_effect=pausa):
            return saude_servidor(meminfo, stat)

    def test_niveis_e_alertas(self):
        ok = self._medir(*self._arquivos(5 * 1024 * 1024, 40))
        self.assertEqual((ok["nivel_memoria"], ok["nivel_cpu"], ok["alertas"]), ("ok", "ok", []))
        self.assertEqual((ok["livre_gb"], ok["total_gb"], ok["cpu_pct"]), ("5,0", "12", 40))

        atencao = self._medir(*self._arquivos(int(1.7 * 1024 * 1024), 95))
        self.assertEqual((atencao["nivel_memoria"], atencao["nivel_cpu"], atencao["alertas"]), ("atencao", "atencao", []))

        critico = self._medir(*self._arquivos(800 * 1024, 99))
        self.assertEqual((critico["nivel_memoria"], critico["nivel_cpu"]), ("critico", "critico"))
        self.assertEqual(len(critico["alertas"]), 2)
        self.assertIn("Desative um robô", critico["alertas"][0])

    def test_uso_nunca_passa_de_100(self):
        self.assertLessEqual(self._medir(*self._arquivos(5 * 1024 * 1024, 100))["cpu_pct"], 100)

    def test_fora_do_linux_nao_mostra(self):
        from apps.ri.views_fila_tv import saude_servidor

        self.assertIsNone(saude_servidor("/nao/existe/meminfo", "/nao/existe/stat"))
