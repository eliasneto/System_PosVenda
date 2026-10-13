"""Pedidos do usuário (2026-10-13): INEP que já está em LOTE some do grid do
MIP, e "Criar LOTE em massa" — 1 LOTE por cidade com INEP elegível,
revisado num modal antes de criar."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.escolas.models import Lote
from apps.escolas.services import (
    criar_lote_mip,
    criar_lotes_mip_em_massa,
    desfazer_lote_mip,
    escolas_no_grid_mip,
    lotes_mip_previstos_em_massa,
)
from apps.escolas.tests import _criar_escola_elegivel_lote
from apps.ri.models import KitPadrao

User = get_user_model()


class _Base(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user(username="analista-massa", password="senha-teste-123")
        KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 2 Access Points", lote=9,
            valor_equipamento="1000.00", valor_servico="300.00",
        )


class GridMipSemInepsEmLoteTests(_Base):
    def test_inep_em_lote_some_do_grid_e_volta_ao_desfazer(self):
        escola, _ri = _criar_escola_elegivel_lote("30000001")
        sobrou, _ri2 = _criar_escola_elegivel_lote("30000002")
        lote = criar_lote_mip("GO", "Abadiânia", None, None, self.usuario, escola_ids=[escola.pk])

        self.assertNotIn(escola, escolas_no_grid_mip())
        self.assertIn(sobrou, escolas_no_grid_mip())

        desfazer_lote_mip(lote, self.usuario)
        self.assertIn(escola, escolas_no_grid_mip())

    def test_tela_do_mip_nao_lista_inep_em_lote(self):
        escola, _ri = _criar_escola_elegivel_lote("30000003")
        _criar_escola_elegivel_lote("30000004")
        criar_lote_mip("GO", "Abadiânia", None, None, self.usuario, escola_ids=[escola.pk])
        self.client.force_login(self.usuario)
        resp = self.client.get(reverse("mip_inep"))
        self.assertNotContains(resp, "30000003")
        self.assertContains(resp, "30000004")


class LotesMipEmMassaTests(_Base):
    def test_previa_separa_1_lote_por_cidade_elegivel(self):
        _criar_escola_elegivel_lote("30000010")
        _criar_escola_elegivel_lote("30000011")
        _criar_escola_elegivel_lote("30000012", municipio="Anápolis")
        _criar_escola_elegivel_lote("30000013", estado="DF", municipio="Brasília")

        previstos = lotes_mip_previstos_em_massa()

        self.assertEqual(
            [(p["estado"], p["municipio"], len(p["escolas"])) for p in previstos],
            [("DF", "Brasília", 1), ("GO", "Abadiânia", 2), ("GO", "Anápolis", 1)],
        )
        self.assertEqual(str(previstos[1]["valor_total"]), "600.00")

    def test_previa_respeita_o_estado_do_filtro(self):
        _criar_escola_elegivel_lote("30000014")
        _criar_escola_elegivel_lote("30000015", estado="DF", municipio="Brasília")
        previstos = lotes_mip_previstos_em_massa(estado="DF")
        self.assertEqual([p["municipio"] for p in previstos], ["Brasília"])

    def test_previa_ignora_inep_ja_em_lote(self):
        escola, _ri = _criar_escola_elegivel_lote("30000016")
        criar_lote_mip("GO", "Abadiânia", None, None, self.usuario)
        self.assertEqual(lotes_mip_previstos_em_massa(), [])
        self.assertTrue(escola.lotes.exists())

    def test_cria_so_as_cidades_marcadas(self):
        _criar_escola_elegivel_lote("30000020")
        fora, _ri = _criar_escola_elegivel_lote("30000021", municipio="Anápolis")

        lotes, erros = criar_lotes_mip_em_massa([("GO", "Abadiânia")], None, None, self.usuario)

        self.assertEqual(erros, [])
        self.assertEqual(len(lotes), 1)
        self.assertEqual(lotes[0].municipio, "Abadiânia")
        self.assertFalse(fora.lotes.exists())
        self.assertIn(fora, escolas_no_grid_mip())

    def test_cidade_sem_elegivel_vira_erro_sem_travar_as_outras(self):
        _criar_escola_elegivel_lote("30000022")
        lotes, erros = criar_lotes_mip_em_massa(
            [("GO", "Abadiânia"), ("GO", "Goiânia")], None, None, self.usuario
        )
        self.assertEqual(len(lotes), 1)
        self.assertEqual(len(erros), 1)
        self.assertIn("Goiânia/GO", erros[0])


class LotesMipEmMassaViewsTests(_Base):
    def test_previa_lista_as_cidades(self):
        _criar_escola_elegivel_lote("30000030")
        _criar_escola_elegivel_lote("30000031", municipio="Anápolis")
        self.client.force_login(self.usuario)
        resp = self.client.get(reverse("mip_lotes_em_massa_previa"))
        self.assertContains(resp, 'value="GO|Abadiânia"')
        self.assertContains(resp, 'value="GO|Anápolis"')

    def test_post_cria_lotes_marcados(self):
        _criar_escola_elegivel_lote("30000032")
        _criar_escola_elegivel_lote("30000033", municipio="Anápolis")
        self.client.force_login(self.usuario)
        resp = self.client.post(
            reverse("mip_lotes_em_massa_criar"), {"cidades": ["GO|Abadiânia", "GO|Anápolis"]}, follow=True,
        )
        self.assertRedirects(resp, reverse("mip_lote_inep"))
        self.assertEqual(Lote.objects.count(), 2)
        self.assertContains(resp, "2 LOTE(s) criado(s) em massa")

    def test_post_sem_nenhuma_cidade_mostra_erro(self):
        self.client.force_login(self.usuario)
        resp = self.client.post(reverse("mip_lotes_em_massa_criar"), {}, follow=True)
        self.assertEqual(Lote.objects.count(), 0)
        self.assertContains(resp, "Nenhum LOTE selecionado")

    def test_get_no_criar_nao_cria(self):
        self.client.force_login(self.usuario)
        resp = self.client.get(reverse("mip_lotes_em_massa_criar"))
        self.assertRedirects(resp, reverse("mip_inep"))

    def test_exige_login(self):
        resp = self.client.get(reverse("mip_lotes_em_massa_previa"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp.url)

    def test_visualizador_nao_cria_lote_em_massa(self):
        _criar_escola_elegivel_lote("30000034")
        visualizador = User.objects.create_user(
            username="visualizador-massa", password="senha-teste-123", perfil=User.PERFIL_VISUALIZADOR,
        )
        self.client.force_login(visualizador)
        self.client.post(reverse("mip_lotes_em_massa_criar"), {"cidades": ["GO|Abadiânia"]})
        self.assertEqual(Lote.objects.count(), 0)
