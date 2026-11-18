""""Cancelar faturamento" da tela do MIP (pedido do usuário, 2026-11-18): NF já gerada que o cliente cancelou, com o
INEP já no MIP e fora de LOTE. O faturamento do RI deixa de valer (fica só no histórico), o INEP sai do MIP e o RI
volta para "Implantação EACE" para refazer o processo. Caso real: INEP 35224546 (NFs 3737 e 3738)."""
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
from apps.escolas.models import Escola, Lote

from .models import CancelamentoEace, Documento, EmailFinanceiroLog, LogRpaEace, Ri, RiHistorico
from .services import trocar_status_com_log

User = get_user_model()
_MEDIA_ROOT = tempfile.mkdtemp()
INEP = "35224546"
TOKEN = "token-teste-cancelar-mip"


@override_settings(MEDIA_ROOT=_MEDIA_ROOT, FINANCEIRO_API_TOKEN=TOKEN)
class CancelarFaturamentoMipTests(TestCase):

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.admin = User.objects.create_user("admin-mip", password="x", perfil=User.PERFIL_ADMINISTRADOR)
        self.analista = User.objects.create_user("analista-mip", password="x", perfil=User.PERFIL_ANALISTA)
        self.escola = Escola.objects.create(inep=INEP, nome="CAMILO FERRARINI", municipio="Itu", estado="SP")
        # `Ri.save` põe o INEP no MIP em "Aguardando Validação EACE" (RN-092).
        self.ri = Ri.objects.create(escola=self.escola, status=Ri.FATURAMENTO_RI_CONCLUIDO,
                                    data_ativacao=date(2026, 10, 1), dados_financeiro_confirmados_em=timezone.now(),
                                    concluido_em=timezone.now())
        self.escola.refresh_from_db()
        assert self.escola.status_mip == Escola.AGUARDANDO_VALIDACAO_EACE
        self.codigo = montar_codigo_rastreio(INEP, timezone.localdate())
        assunto = f"#{self.codigo} - Faturamento EACE — INEP {INEP}"
        EmailFinanceiroLog.objects.create(ri=self.ri, direcao=EmailFinanceiroLog.ENVIADO, assunto=assunto)
        EmailFinanceiroLog.objects.create(ri=self.ri, direcao=EmailFinanceiroLog.RECEBIDO, assunto="RE: " + assunto)
        for numero in ("3737", "3738"):
            for tipo, extensao in ((Documento.NOTA_FISCAL_PDF, "pdf"), (Documento.XML, "xml")):
                documento = Documento(ri=self.ri, tipo=tipo, recebido_em=timezone.now())
                documento.arquivo.save(f"{numero}_NF.{extensao}", ContentFile(b"x"), save=True)
            LogRpaEace.objects.create(ri=self.ri, resultado=LogRpaEace.SUCESSO)
        self.url = reverse("mip_cancelar_faturamento", kwargs={"inep": INEP})
        self.detalhe_mip = reverse("mip_detail", kwargs={"inep": INEP})

    def _cancelar(self, usuario=None, motivo="Cliente cancelou as NFs 3737 e 3738"):
        self.client.force_login(usuario or self.admin)
        return self.client.post(self.url, {"motivo": motivo}, follow=True)

    def test_cancelar_tira_do_mip_volta_o_ri_e_guarda_no_historico(self):
        resposta = self._cancelar()
        self.assertContains(resposta, "Faturamento do INEP 35224546 cancelado")
        self.ri.refresh_from_db()
        self.escola.refresh_from_db()
        self.assertEqual(self.ri.status, Ri.IMPLANTACAO_EACE)
        self.assertIsNone(self.ri.concluido_em)
        self.assertIsNone(self.ri.dados_financeiro_confirmados_em)
        self.assertIsNone(self.escola.status_mip)
        # NFs, e-mails e logs do RPA deixam de valer, mas ficam para auditoria
        self.assertFalse(Documento.objects.filter(ri=self.ri).exists())
        self.assertFalse(EmailFinanceiroLog.objects.filter(ri=self.ri).exists())
        self.assertFalse(self.ri.logs_rpa_eace.exists())
        cancelamento = CancelamentoEace.objects.get()
        self.assertEqual(cancelamento.origem, CancelamentoEace.CLIENTE_MIP)
        self.assertEqual(cancelamento.status_anterior, Ri.FATURAMENTO_RI_CONCLUIDO)
        self.assertEqual(cancelamento.status_mip_anterior, Escola.AGUARDANDO_VALIDACAO_EACE)
        self.assertEqual(cancelamento.resumo, {"emails_enviados": 1, "respostas": 1, "documentos": 4, "logs_rpa": 2})
        self.assertEqual(Documento.todos.filter(cancelamento_eace=cancelamento).count(), 4)
        historico = RiHistorico.objects.filter(ri=self.ri)
        self.assertTrue(historico.filter(
            mensagem__startswith="Faturamento cancelado no MIP (NF cancelada pelo cliente). Motivo: Cliente cancelou"
        ).exists())
        self.assertTrue(historico.filter(campo="Status (MIP)", valor_anterior="Aguardando Validação EACE",
                                         valor_novo="Fora do MIP (faturamento cancelado)").exists())
        self.assertTrue(historico.filter(campo="Status do RI", valor_novo="Implantação EACE").exists())

    def test_refazer_o_processo_devolve_o_inep_ao_mip(self):
        self._cancelar()
        trocar_status_com_log(Ri.objects.get(pk=self.ri.pk), Ri.FATURAMENTO_RI_CONCLUIDO, self.admin)
        self.escola.refresh_from_db()
        self.assertEqual(self.escola.status_mip, Escola.AGUARDANDO_VALIDACAO_EACE)

    def test_motivo_obrigatorio(self):
        self.assertContains(self._cancelar(motivo="  "), "Informe o motivo")
        self.escola.refresh_from_db()
        self.assertEqual(self.escola.status_mip, Escola.AGUARDANDO_VALIDACAO_EACE)
        self.assertFalse(CancelamentoEace.objects.exists())

    def test_so_administrador(self):
        self.client.force_login(self.analista)
        self.assertEqual(self.client.post(self.url, {"motivo": "x"}).status_code, 403)
        self.assertNotContains(self.client.get(self.detalhe_mip), "Cancelar faturamento")
        self.ri.refresh_from_db()
        self.assertEqual(self.ri.status, Ri.FATURAMENTO_RI_CONCLUIDO)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(self.detalhe_mip), 'data-abrir-modal-email="modal-cancelar-faturamento-mip"')

    def test_inep_em_lote_ativo_e_bloqueado(self):
        lote = Lote.objects.create(estado="SP", municipio="Itu")
        lote.escolas.add(self.escola)
        resposta = self._cancelar()
        self.assertContains(resposta, "LOTE-")
        self.assertContains(resposta, "se desfaz pelo LOTE")
        self.assertFalse(CancelamentoEace.objects.exists())
        # LOTE reprovado não prende o INEP
        Lote.objects.filter(pk=lote.pk).update(status=Lote.REPROVADO)
        self._cancelar()
        self.assertTrue(CancelamentoEace.objects.exists())

    def test_robo_rodando_bloqueia(self):
        LogRpaEace.objects.filter(ri=self.ri).update(resultado=LogRpaEace.PROCESSANDO)
        self.assertContains(self._cancelar(), "robô do RPA EACE está anexando")
        self.assertFalse(CancelamentoEace.objects.exists())

    def test_inep_fora_do_mip_nao_cancela(self):
        Escola.objects.filter(pk=self.escola.pk).update(status_mip=None)
        self.assertContains(self._cancelar(), "não está no MIP")
        self.assertFalse(CancelamentoEace.objects.exists())

    def test_api_avisa_o_financeiro_com_a_origem(self):
        self._cancelar()
        self.client.logout()
        auth = {"HTTP_AUTHORIZATION": f"Bearer {TOKEN}"}
        dados = self.client.get(reverse("api_financeiro_cancelamentos"), **auth).json()["cancelamentos"]
        self.assertEqual((dados[0]["inep"], dados[0]["origem"], dados[0]["codigos_rastreio"]),
                         (INEP, CancelamentoEace.CLIENTE_MIP, [self.codigo]))
        corpo = json.dumps({"id": dados[0]["id"], "resultado": "1 e-mail marcado."})
        self.client.post(reverse("api_financeiro_cancelamentos_confirmar"), corpo,
                         content_type="application/json", **auth)
        self.assertTrue(RiHistorico.objects.filter(
            ri=self.ri, mensagem__startswith="O financeiro recebeu o cancelamento (Faturamento cancelado no MIP").exists())
