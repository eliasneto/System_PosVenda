"""API do Módulo Financeiro (`apps.escolas.api_financeiro`): planilhas de faturamento de implantação dos LOTEs."""

import base64
import datetime
import io

import openpyxl
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.ri.models import Ri

from .models import Escola, Lote

TOKEN = "token-financeiro-teste"


@override_settings(FINANCEIRO_API_TOKEN=TOKEN)
class FinanceiroApiTests(TestCase):
    def setUp(self):
        escola = Escola.objects.create(inep="10000501", nome="Escola API Financeiro",
                                       status_mip=Escola.EM_FATURAMENTO_LOTE)
        Ri.objects.create(escola=escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        self.lote = Lote.objects.create(estado="MT", municipio="Várzea Grande", status=Lote.EM_FATURAMENTO)
        self.lote.escolas.add(escola)
        outra = Lote.objects.create(estado="SP", municipio="Alumínio", status=Lote.EM_ANDAMENTO)
        outra.escolas.add(escola)

    def _get(self, url, token=TOKEN, **params):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
        return self.client.get(url, params, **headers)

    def test_lista_os_lotes_em_faturamento_com_os_arquivos(self):
        resp = self._get(reverse("api_financeiro_mip_lotes"), data="2026-10-22")
        self.assertEqual(resp.status_code, 200)
        dados = resp.json()
        self.assertEqual(dados["data"], "2026-10-22")
        self.assertEqual([l["lote"] for l in dados["lotes"]], [str(self.lote)])
        lote = dados["lotes"][0]
        self.assertEqual((lote["municipio"], lote["uf"], lote["status"]), ("Várzea Grande", "MT", "em_faturamento"))
        arquivo = lote["arquivos"][0]
        self.assertEqual(arquivo["nome"], f"FATURAMENTO IMPLANTAÇÃO EACE - Várzea Grande-MT - {self.lote}.xlsx")
        self.assertEqual((arquivo["municipio"], arquivo["valor"], arquivo["rateio"]), ("Várzea Grande", "0.00", False))
        self.assertNotIn("conteudo_base64", arquivo)

    def test_entrega_as_planilhas_com_o_vencimento_da_data_pedida(self):
        resp = self._get(reverse("api_financeiro_mip_lote_planilhas", kwargs={"pk": self.lote.pk}), data="2026-10-22")
        self.assertEqual(resp.status_code, 200)
        planilha = resp.json()["planilhas"][0]
        workbook = openpyxl.load_workbook(io.BytesIO(base64.b64decode(planilha["conteudo_base64"])))
        aba = workbook.worksheets[0]
        self.assertEqual(aba.title, "Várzea Grande")
        self.assertEqual(aba["E10"].value.date(), datetime.date(2026, 11, 21))  # 22/10 + 30 dias
        self.assertIn("VENCIMENTO: 21/11/2026", aba["F10"].value)
        self.assertEqual(Lote.objects.get(pk=self.lote.pk).status, Lote.EM_FATURAMENTO)  # só leitura

    def test_sem_token_ou_token_errado(self):
        url = reverse("api_financeiro_mip_lotes")
        self.assertEqual(self._get(url, token="").status_code, 401)
        self.assertEqual(self._get(url, token="errado").status_code, 401)

    @override_settings(FINANCEIRO_API_TOKEN="")
    def test_api_desligada_sem_token_configurado(self):
        self.assertEqual(self._get(reverse("api_financeiro_mip_lotes")).status_code, 503)

    def test_data_ou_status_invalido_e_lote_sem_inep(self):
        self.assertEqual(self._get(reverse("api_financeiro_mip_lotes"), data="22/10/2026").status_code, 400)
        self.assertEqual(self._get(reverse("api_financeiro_mip_lotes"), status="xyz").status_code, 400)
        self.lote.escolas.clear()
        url = reverse("api_financeiro_mip_lote_planilhas", kwargs={"pk": self.lote.pk})
        self.assertEqual(self._get(url).status_code, 422)
        self.assertEqual(self._get(reverse("api_financeiro_mip_lote_planilhas", kwargs={"pk": 999999})).status_code, 404)

    def test_so_aceita_get(self):
        resp = self.client.post(reverse("api_financeiro_mip_lotes"), HTTP_AUTHORIZATION=f"Bearer {TOKEN}")
        self.assertEqual(resp.status_code, 405)
