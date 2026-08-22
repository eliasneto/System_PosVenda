from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.escolas.models import Escola

from .models import Ri, RiDivergencia, RiItemEace, RiItemIxc

User = get_user_model()


class GridInepViewTests(TestCase):
    """FEAT-007: grid principal de INEPs (RF-05/RF-06)."""

    def setUp(self):
        self.user = User.objects.create_user(username="analista", password="senha-teste-123")
        self.escola_sem_ri = Escola.objects.create(
            inep="10000001", nome="Escola Sem RI", municipio="Fortaleza", estado="CE"
        )
        self.escola_com_ri = Escola.objects.create(
            inep="10000002", nome="Escola Com RI", municipio="Sobral", estado="CE"
        )
        self.ri = Ri.objects.create(
            escola=self.escola_com_ri, status=Ri.ANDAMENTO, responsavel=self.user
        )

    def test_exige_login(self):
        resp = self.client.get(reverse("grid_inep"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp.url)

    def test_caminho_principal_lista_todas_as_escolas(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("grid_inep"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.escola_sem_ri.inep)
        self.assertContains(resp, self.escola_com_ri.inep)
        self.assertContains(resp, "Sem RI")
        self.assertContains(resp, "Andamento")

    def test_filtro_por_status(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("grid_inep"), {"status": Ri.ANDAMENTO})
        self.assertContains(resp, self.escola_com_ri.inep)
        self.assertNotContains(resp, self.escola_sem_ri.inep)

    def test_busca_por_inep_nome_municipio_ou_uf(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("grid_inep"), {"q": "Sobral"})
        self.assertContains(resp, self.escola_com_ri.inep)
        self.assertNotContains(resp, self.escola_sem_ri.inep)

    def test_busca_sem_resultado_mostra_estado_vazio(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("grid_inep"), {"q": "inep-que-nao-existe"})
        self.assertContains(resp, "Nenhum INEP encontrado")

    def test_divergencia_aberta_conta_no_card_e_marca_a_linha(self):
        RiDivergencia.objects.create(ri=self.ri, tipo=RiDivergencia.TIPO_QUANTIDADE)
        self.client.force_login(self.user)
        resp = self.client.get(reverse("grid_inep"))
        self.assertContains(resp, "Divergência aberta")
        # card "Com divergência" conta 1
        self.assertContains(resp, ">1<")

    def test_divergencia_resolvida_nao_conta_como_aberta(self):
        RiDivergencia.objects.create(
            ri=self.ri,
            tipo=RiDivergencia.TIPO_QUANTIDADE,
            resolvida_em="2026-08-22T00:00:00Z",
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("grid_inep"))
        self.assertNotContains(resp, "Divergência aberta")

    def test_drilldown_mostra_itens_eace_e_ixc_do_ri(self):
        RiItemEace.objects.create(
            ri=self.ri, descricao_item="Kit Wi-Fi", quantidade=2, valor_unitario="350.00"
        )
        RiItemIxc.objects.create(
            ri=self.ri, descricao_item="Kit Wi-Fi", quantidade=2, valor_unitario="350.00"
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("grid_inep"))
        self.assertContains(resp, "Kit Wi-Fi")
