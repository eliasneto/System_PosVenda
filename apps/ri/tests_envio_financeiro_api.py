"""Integração direta com o financeiro como segundo caminho do e-mail (pedido do usuário, 2026-11-13): o e-mail
continua principal; se ele falha, a planilha vai pela API, e a resposta do financeiro pela API passa pelo mesmo
processo da resposta lida na caixa, sem duplicar quando os dois caminhos entregam."""
import base64
import json
import shutil
import smtplib
import tempfile
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.email_tracking import montar_codigo_rastreio
from apps.escolas.models import Escola

from .models import EmailFinanceiroLog, EnvioFinanceiro, LogRpaEace, Ri, RiHistorico, RiItemIxc, RiItemRelatorioEace
from .services import SUFIXO_RESPOSTA_VIA_API, _processar_mensagem
from .tests_faturamento_complementar import _email_bytes

User = get_user_model()
_MEDIA_ROOT = tempfile.mkdtemp()
TOKEN = "token-teste-envios"
INEP = "50000077"
FALHA_SMTP = "apps.ri.envio_financeiro.EmailMessage.send"


@override_settings(MEDIA_ROOT=_MEDIA_ROOT, FINANCEIRO_API_TOKEN=TOKEN)
class EnvioFinanceiroApiTests(TestCase):

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.user = User.objects.create_user(username="analista-envio", password="senha-teste-123")
        self.escola = Escola.objects.create(inep=INEP, nome="Escola Envio", municipio="Fortaleza", estado="CE")
        self.ri = Ri.objects.create(
            escola=self.escola, status=Ri.ENVIO_EMAIL_FATURAMENTO, municipio_ixc="Fortaleza", estado_ixc="CE",
            data_ativacao=date(2026, 8, 1), cnpj="00.000.000/0001-00", cnpj_ficticio="11.111.111/0001-11",
        )
        for modelo in (RiItemIxc, RiItemRelatorioEace):
            modelo.objects.create(ri=self.ri, descricao_item="Kit Cobertura Wi-Fi - 4 Access Points", quantidade=1,
                                  valor_unitario="0", eh_kit=True)

    def _enviar(self):
        self.client.force_login(self.user)
        return self.client.post(
            reverse("ri_enviar_email_financeiro", kwargs={"pk": self.ri.pk}),
            {"para": "financeiro@speedcsc.com.br", "cc": "", "assunto": f"Faturamento EACE — INEP {INEP}",
             "mensagem": "", "next": reverse("grid_inep")},
            follow=True,
        )

    def _api(self, metodo, nome, token=TOKEN, **kwargs):
        self.client.logout()
        cabecalho = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
        return getattr(self.client, metodo)(reverse(nome), **kwargs, **cabecalho)

    # ------------------------------------------------------------ ida: planilha ao financeiro

    def test_email_ok_vai_pelo_email_com_o_message_id_do_envio_e_nao_entra_na_api(self):
        self._enviar()
        envio = EnvioFinanceiro.objects.get()
        self.assertEqual(envio.canal, EnvioFinanceiro.EMAIL)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].extra_headers["Message-ID"], envio.message_id)
        self.assertIn(envio.message_id, mail.outbox[0].message().as_string())
        self.assertEqual(self._api("get", "api_financeiro_envios").json(), {"envios": []})

    def test_email_fora_do_ar_libera_a_planilha_na_api_e_o_ri_segue(self):
        with patch(FALHA_SMTP, side_effect=smtplib.SMTPServerDisconnected("Connection unexpectedly closed")):
            resposta = self._enviar()
        self.assertContains(resposta, "pela integração direta")
        self.ri.refresh_from_db()
        self.assertEqual(self.ri.status, Ri.AGUARDANDO_FINANCEIRO)
        envio = EnvioFinanceiro.objects.get()
        self.assertEqual(envio.canal, EnvioFinanceiro.API)
        self.assertIn("SMTPServerDisconnected", envio.erro_email)
        self.assertTrue(RiHistorico.objects.filter(ri=self.ri, mensagem__contains="pela integração direta").exists())

        dados = self._api("get", "api_financeiro_envios").json()["envios"]
        self.assertEqual(len(dados), 1)
        self.assertEqual(dados[0]["message_id"], envio.message_id)
        self.assertEqual(dados[0]["inep"], INEP)
        self.assertIn(montar_codigo_rastreio(INEP, timezone.localdate()), dados[0]["assunto"])
        self.assertEqual(dados[0]["destinatarios"], ["financeiro@speedcsc.com.br"])
        planilha = base64.b64decode(dados[0]["anexos"][0]["conteudo_base64"])
        self.assertTrue(planilha.startswith(b"PK"))  # .xlsx

        confirmar = {"data": json.dumps({"message_id": envio.message_id}), "content_type": "application/json"}
        self.assertEqual(self._api("post", "api_financeiro_envios_confirmar", **confirmar).status_code, 200)
        self.assertEqual(self._api("post", "api_financeiro_envios_confirmar", **confirmar).status_code, 200)
        self.assertEqual(self._api("get", "api_financeiro_envios").json(), {"envios": []})
        self.assertEqual(RiHistorico.objects.filter(ri=self.ri, mensagem__startswith="O financeiro recebeu").count(), 1)

    def test_api_sem_token_recusa(self):
        self.assertEqual(self._api("get", "api_financeiro_envios", token="errado").status_code, 401)
        self.assertEqual(self._api("post", "api_financeiro_respostas", token="").status_code, 401)

    # ------------------------------------------------------------ volta: NFs do financeiro

    def _responder_pela_api(self, message_id="<financeiro-resposta-1@speedcsc.com.br>", assunto=None):
        assunto = assunto or f"RE: #{montar_codigo_rastreio(INEP, timezone.localdate())} - Faturamento EACE"
        return self._api("post", "api_financeiro_respostas", data={
            "message_id": message_id, "assunto": assunto, "remetente": "financeiro@speedcsc.com.br",
            "arquivo_0": SimpleUploadedFile("4001_NOME.pdf", b"%PDF-1", content_type="application/pdf"),
            "arquivo_1": SimpleUploadedFile("4001_NOME.xml", b"<nfe/>", content_type="application/xml"),
        })

    def test_resposta_pela_api_faz_o_mesmo_processo_do_email(self):
        self.ri.status = Ri.AGUARDANDO_FINANCEIRO
        self.ri.save()
        resposta = self._responder_pela_api()
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json()["resultado"], "identificados")
        self.ri.refresh_from_db()
        self.assertEqual(self.ri.status, Ri.AGUARDANDO_ANEXO_PORTAL_EACE)
        self.assertEqual(LogRpaEace.objects.filter(ri=self.ri).count(), 1)
        self.assertEqual(self.ri.documentos.count(), 2)
        log = EmailFinanceiroLog.objects.get(direcao=EmailFinanceiroLog.RECEBIDO)
        self.assertEqual(log.mensagem_id_externo, "<financeiro-resposta-1@speedcsc.com.br>")
        entrada = RiHistorico.objects.get(ri=self.ri, tipo=RiHistorico.EMAIL)
        self.assertTrue(entrada.mensagem.endswith(SUFIXO_RESPOSTA_VIA_API))
        self.assertEqual(entrada.documentos.count(), 2)

    def test_resposta_pela_api_e_pelo_email_nao_duplica(self):
        self.ri.status = Ri.AGUARDANDO_FINANCEIRO
        self.ri.save()
        self._responder_pela_api()
        self.assertEqual(self._responder_pela_api().json()["resultado"], "duplicados")
        codigo = montar_codigo_rastreio(INEP, timezone.localdate())
        bruto = _email_bytes(f"RE: #{codigo} - Faturamento EACE", [("4001.pdf", b"%PDF"), ("4001.xml", b"<nfe/>")])
        self.assertEqual(_processar_mensagem(bruto, "<financeiro-resposta-1@speedcsc.com.br>"), "duplicados")
        self.assertEqual(LogRpaEace.objects.filter(ri=self.ri).count(), 1)
        self.assertEqual(self.ri.documentos.count(), 2)

    def test_resposta_pela_api_sem_codigo_de_rastreio_e_recusada(self):
        resposta = self._responder_pela_api(assunto="RE: Faturamento")
        self.assertEqual(resposta.status_code, 422)
        self.assertEqual(resposta.json()["erro"]["codigo"], "SEM_CODIGO")
