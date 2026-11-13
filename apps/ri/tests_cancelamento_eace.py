"""Processo do RI cancelado pela EACE depois do envio ao financeiro (pedido do usuário, 2026-11-13): o RI volta para
"Implantação EACE", o envio/resposta/logs do RPA deixam de valer (ficam só para auditoria) e o financeiro é avisado
pela integração."""
import json
import shutil
import tempfile
from datetime import date

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.email_tracking import montar_codigo_rastreio
from apps.escolas.models import Escola

from .models import (
    CancelamentoEace,
    Documento,
    EmailFinanceiroLog,
    LogRpaEace,
    Ri,
    RiDivergencia,
    RiHistorico,
)
from .services import _processar_mensagem
from .tests_faturamento_complementar import _email_bytes

User = get_user_model()
_MEDIA_ROOT = tempfile.mkdtemp()
INEP = "35007212"
TOKEN = "token-teste-cancelamento"


@override_settings(MEDIA_ROOT=_MEDIA_ROOT, FINANCEIRO_API_TOKEN=TOKEN)
class CancelamentoEaceTests(TestCase):

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.analista = User.objects.create_user("analista-canc", password="x", perfil=User.PERFIL_ANALISTA)
        self.visualizador = User.objects.create_user("visu-canc", password="x", perfil=User.PERFIL_VISUALIZADOR)
        self.escola = Escola.objects.create(inep=INEP, nome="EM Joao Batista", municipio="Recife", estado="PE")
        self.ri = Ri.objects.create(escola=self.escola, status=Ri.AGUARDANDO_ANEXO_PORTAL_EACE,
                                    data_ativacao=date(2026, 10, 1), dados_financeiro_confirmados_em=timezone.now())
        self.codigo = montar_codigo_rastreio(INEP, timezone.localdate())
        self.assunto = f"#{self.codigo} - Faturamento EACE — INEP {INEP}"
        EmailFinanceiroLog.objects.create(ri=self.ri, direcao=EmailFinanceiroLog.ENVIADO, assunto=self.assunto)
        EmailFinanceiroLog.objects.create(ri=self.ri, direcao=EmailFinanceiroLog.RECEBIDO, assunto="RE: " + self.assunto,
                                          mensagem_id_externo="<resp-1@financeiro>")
        self.pdf = Documento(ri=self.ri, tipo=Documento.NOTA_FISCAL_PDF, recebido_em=timezone.now())
        self.pdf.arquivo.save("4001_NF.pdf", ContentFile(b"%PDF"), save=True)
        entrada = RiHistorico.objects.create(ri=self.ri, tipo=RiHistorico.EMAIL, mensagem="Resposta recebida.")
        entrada.documentos.set([self.pdf])
        LogRpaEace.objects.create(ri=self.ri, resultado=LogRpaEace.NA_FILA)
        RiDivergencia.objects.create(ri=self.ri, tipo=RiDivergencia.TIPO_NF_FINANCEIRO, descricao="NF divergente")
        self.url = reverse("ri_cancelar_eace", kwargs={"pk": self.ri.pk})
        self.detalhe = reverse("ri_detail", kwargs={"inep": INEP})

    def _cancelar(self, usuario=None, motivo="EACE cancelou a instalação"):
        self.client.force_login(usuario or self.analista)
        return self.client.post(self.url, {"motivo": motivo, "next": self.detalhe}, follow=True)

    def test_cancelar_volta_para_implantacao_e_desconsidera_o_faturamento(self):
        resposta = self._cancelar()
        self.assertContains(resposta, "Processo cancelado pela EACE")
        self.ri.refresh_from_db()
        self.assertEqual(self.ri.status, Ri.IMPLANTACAO_EACE)
        self.assertIsNone(self.ri.dados_financeiro_confirmados_em)
        # some de tudo (relatórios, fila do RPA, data de faturamento)...
        self.assertFalse(EmailFinanceiroLog.objects.filter(ri=self.ri).exists())
        self.assertFalse(Documento.objects.filter(ri=self.ri).exists())
        self.assertFalse(self.ri.logs_rpa_eace.exists())
        self.assertFalse(LogRpaEace.objects.filter(resultado=LogRpaEace.NA_FILA).exists())
        self.assertFalse(self.ri.divergencias.filter(resolvida_em__isnull=True).exists())
        # ...mas fica no banco para auditoria
        cancelamento = CancelamentoEace.objects.get()
        self.assertEqual(EmailFinanceiroLog.todos.filter(cancelamento_eace=cancelamento).count(), 2)
        self.assertEqual(Documento.todos.filter(cancelamento_eace=cancelamento).count(), 1)
        self.assertEqual(cancelamento.codigos_rastreio, [self.codigo])
        self.assertEqual(cancelamento.status_anterior, Ri.AGUARDANDO_ANEXO_PORTAL_EACE)
        self.assertEqual(cancelamento.resumo, {"emails_enviados": 1, "respostas": 1, "documentos": 1, "logs_rpa": 1})
        self.assertTrue(RiHistorico.objects.filter(
            ri=self.ri, mensagem__startswith="Processo cancelado pela EACE. Motivo: EACE cancelou").exists())
        # o histórico continua com o PDF da resposta cancelada
        self.assertContains(self.client.get(self.detalhe), "4001_NF")

    def test_motivo_obrigatorio(self):
        self.assertContains(self._cancelar(motivo="  "), "Informe o motivo")
        self.ri.refresh_from_db()
        self.assertEqual(self.ri.status, Ri.AGUARDANDO_ANEXO_PORTAL_EACE)
        self.assertFalse(CancelamentoEace.objects.exists())

    def test_visualizador_nao_cancela(self):
        self._cancelar(usuario=self.visualizador)
        self.ri.refresh_from_db()
        self.assertEqual(self.ri.status, Ri.AGUARDANDO_ANEXO_PORTAL_EACE)

    def test_bloqueios_mip_e_robo_rodando(self):
        LogRpaEace.objects.update(resultado=LogRpaEace.PROCESSANDO)
        self.assertContains(self._cancelar(), "robô do RPA EACE está anexando")
        LogRpaEace.objects.update(resultado=LogRpaEace.NA_FILA)
        Escola.objects.filter(pk=self.escola.pk).update(status_mip=Escola.AGUARDANDO_VALIDACAO_EACE)
        self.assertContains(self._cancelar(), "já está no MIP")
        self.assertFalse(CancelamentoEace.objects.exists())

    def test_botao_so_aparece_com_email_enviado(self):
        self.client.force_login(self.analista)
        self.assertContains(self.client.get(self.detalhe), "Cancelado pela EACE")
        self._cancelar()
        self.assertNotContains(self.client.get(self.detalhe), 'data-abrir-modal-email="modal-cancelar-eace')

    def test_resposta_que_chega_depois_do_cancelamento_e_ignorada(self):
        self._cancelar()
        bruto = _email_bytes("RE: " + self.assunto, [("9.pdf", b"%PDF"), ("9.xml", b"<nfe/>")])
        self.assertEqual(_processar_mensagem(bruto, "<resp-2@financeiro>"), "cancelados")
        self.assertEqual(_processar_mensagem(bruto, "<resp-2@financeiro>"), "duplicados")
        self.ri.refresh_from_db()
        self.assertEqual(self.ri.status, Ri.IMPLANTACAO_EACE)
        self.assertFalse(Documento.objects.filter(ri=self.ri).exists())
        self.assertFalse(self.ri.logs_rpa_eace.exists())
        self.assertTrue(RiHistorico.objects.filter(ri=self.ri, mensagem__startswith="Resposta do financeiro ignorada").exists())

    def test_reenvio_no_mesmo_dia_aceita_a_resposta_nova(self):
        self._cancelar()
        Ri.objects.filter(pk=self.ri.pk).update(status=Ri.AGUARDANDO_FINANCEIRO)
        EmailFinanceiroLog.objects.create(ri=self.ri, direcao=EmailFinanceiroLog.ENVIADO, assunto=self.assunto)
        bruto = _email_bytes("RE: " + self.assunto, [("9.pdf", b"%PDF"), ("9.xml", b"<nfe/>")])
        self.assertEqual(_processar_mensagem(bruto, "<resp-3@financeiro>"), "identificados")
        self.ri.refresh_from_db()
        self.assertEqual(self.ri.status, Ri.AGUARDANDO_ANEXO_PORTAL_EACE)

    def test_api_entrega_o_cancelamento_ao_financeiro_e_recebe_a_confirmacao(self):
        self._cancelar()
        self.client.logout()
        auth = {"HTTP_AUTHORIZATION": f"Bearer {TOKEN}"}
        dados = self.client.get(reverse("api_financeiro_cancelamentos"), **auth).json()["cancelamentos"]
        self.assertEqual(len(dados), 1)
        self.assertEqual((dados[0]["inep"], dados[0]["codigos_rastreio"], dados[0]["motivo"]),
                         (INEP, [self.codigo], "EACE cancelou a instalação"))
        corpo = json.dumps({"id": dados[0]["id"], "resultado": "1 e-mail marcado."})
        resposta = self.client.post(reverse("api_financeiro_cancelamentos_confirmar"), corpo,
                                    content_type="application/json", **auth)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(self.client.get(reverse("api_financeiro_cancelamentos"), **auth).json(), {"cancelamentos": []})
        self.assertTrue(RiHistorico.objects.filter(ri=self.ri, mensagem__contains="1 e-mail marcado").exists())
