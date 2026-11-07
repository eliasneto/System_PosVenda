"""API do Módulo Financeiro (`apps.escolas.api_financeiro`): planilhas de faturamento de implantação dos LOTEs."""

import base64
import datetime
import io

from unittest import mock

import openpyxl
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
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


PDF = b"%PDF-1.4 nfse 909"
TEXTO_NFSE = ("MUNICIPIO/UF: ANAPOLIS/GO VENCIMENTO: 05/12/2026 CÓDIGO INEPS: 10000601/19001;10000602/19001;99999999/1 "
              "Serviço executado conforme obrigação")


@override_settings(FINANCEIRO_API_TOKEN=TOKEN)
@mock.patch("apps.escolas.api_financeiro._extrair_texto_pdf_bytes", return_value=TEXTO_NFSE)
class FinanceiroApiNotaFiscalTests(TestCase):
    """POST /api/financeiro/mip/lotes/<id>/notas-fiscais/ (pedido do usuário, 2026-11-07): a NFS-e do município chega
    do financeiro assim que é emitida e faz o mesmo que "Sincronizar Notas Fiscais dos INEPs" só para o LOTE."""

    def setUp(self):
        self.escolas = [Escola.objects.create(inep=inep, nome=f"Escola {inep}", status_mip=Escola.EM_ANDAMENTO)
                        for inep in ("10000601", "10000602", "10000603")]
        self.lote = Lote.objects.create(estado="GO", municipio="Anápolis", status=Lote.EM_ANDAMENTO)
        self.lote.escolas.add(*self.escolas)
        self.url = reverse("api_financeiro_mip_lote_notas_fiscais", kwargs={"pk": self.lote.pk})

    def _post(self, numero="909", conteudo=PDF, token=TOKEN):
        dados = {"numero": numero, "arquivo": SimpleUploadedFile("909_06-11-2026_NOME_MEGA INFRA.pdf", conteudo,
                                                                   content_type="application/pdf")}
        return self.client.post(self.url, dados, HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_grava_a_nf_nos_ineps_do_lote_e_conclui(self, _texto):
        resp = self._post()
        self.assertEqual(resp.status_code, 200, resp.content)
        dados = resp.json()
        self.assertEqual((dados["lote"], dados["numero"]), (str(self.lote), "909"))
        self.assertEqual(dados["ineps"], ["10000601", "10000602"])
        self.assertEqual(dados["ineps_fora_do_lote"], ["99999999"])
        for escola in self.escolas[:2]:
            escola.refresh_from_db()
            self.assertEqual(escola.status_mip, Escola.FATURAMENTO_CONCLUIDO)
            self.assertEqual([n.nome_original for n in escola.notas_fiscais_mip.all()],
                             ["909_06-11-2026_NOME_MEGA INFRA.pdf"])
        self.escolas[2].refresh_from_db()
        self.assertEqual(self.escolas[2].status_mip, Escola.EM_ANDAMENTO)  # INEP fora da NF nao e tocado
        self.lote.refresh_from_db()
        self.assertTrue(self.lote.nf_financeiro_recebida_em)
        self.assertEqual(self.lote.nf_financeiro_numeros, "909")
        # reenvio da mesma NF substitui (nao duplica) e outra NF do LOTE (rateio) entra na lista
        self._post()
        self._post(numero="910")
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.nf_financeiro_numeros, "909, 910")
        self.assertEqual(self.escolas[0].notas_fiscais_mip.count(), 1)

    def test_recusas(self, texto):
        self.assertEqual(self._post(token="errado").status_code, 401)
        self.assertEqual(self._post(conteudo=b"nao e pdf").status_code, 400)
        self.assertEqual(self._post(numero="").status_code, 400)
        texto.return_value = "CÓDIGO INEPS: 55555555/1 Serviço"
        resp = self._post()
        self.assertEqual(resp.status_code, 422)
        self.assertIn("não tem INEP do", resp.json()["erro"]["mensagem"])
        texto.return_value = TEXTO_NFSE
        Lote.objects.filter(pk=self.lote.pk).update(status=Lote.FATURAMENTO_CONCLUIDO)
        resp = self._post()
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["erro"]["codigo"], "LOTE_FORA_DO_STATUS")
        self.assertIn("só LOTEs", resp.json()["erro"]["mensagem"])
        self.assertFalse(Lote.objects.get(pk=self.lote.pk).nf_financeiro_recebida_em)
        self.assertEqual(self.client.get(self.url, HTTP_AUTHORIZATION=f"Bearer {TOKEN}").status_code, 405)

    def test_card_nf_do_financeiro_na_tela_de_lotes(self, _texto):
        outro = Lote.objects.create(estado="GO", municipio="Crixás", status=Lote.EM_ANDAMENTO)
        outro.escolas.add(Escola.objects.create(inep="10000699", nome="Escola sem NF", status_mip=Escola.EM_ANDAMENTO))
        self._post()
        self.client.force_login(get_user_model().objects.create_user(username="analista-nf-financeiro",
                                                                     password="senha-teste-123"))
        html = self.client.get(reverse("mip_lote_inep")).content.decode()
        self.assertIn("NF do financeiro", html)
        filtrado = self.client.get(reverse("mip_lote_inep"), {"nf_financeiro": "1"})
        self.assertEqual([linha["lote"].pk for linha in filtrado.context["page_obj"].object_list], [self.lote.pk])
        self.assertEqual(filtrado.context["total_nf_financeiro"], 1)

