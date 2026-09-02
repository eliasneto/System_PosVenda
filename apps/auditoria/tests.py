"""FEAT-011 (RF-12/RN-006): auditoria estendida — login, transição de
status, alteração de campo do RI/itens, envio/recebimento de e-mail e
erro do sistema geram registro em `Auditoria`. Reaproveita os dublês de
e-mail/Graph já usados em `apps.ri.tests` (mesma suíte, sem reinventar
MIME/Graph fake) — não há como, nem se deve, testar contra o Microsoft
Graph de verdade."""

import shutil
import tempfile
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.email_tracking import montar_codigo_rastreio
from apps.escolas.models import Escola
from apps.ri.models import Ri, RiItemIxc
from apps.ri.services import sincronizar_respostas_financeiro
from apps.ri.tests import _CONFIG_GRAPH_FINANCEIRO_TESTE, _montar_email_bytes, _RespostaGraphFake

from .middleware import AuditoriaErroMiddleware
from .models import Auditoria
from .services import registrar

User = get_user_model()


class RegistrarAuditoriaServiceTests(TestCase):
    """Testa `apps.auditoria.services.registrar` isolado — os demais testes
    deste arquivo confirmam a chamada em cada ponto real (login, status,
    campo, e-mail, erro)."""

    def setUp(self):
        self.usuario = User.objects.create_user(username="aud-user", password="senha-teste-123")

    def test_grava_registro_com_usuario_autenticado(self):
        registrar(
            self.usuario,
            Auditoria.ALTERACAO_CAMPO,
            entidade="Ri",
            entidade_id=42,
            campo="status",
            valor_anterior="Andamento",
            valor_novo="Envio de Email para faturamento",
        )
        registro = Auditoria.objects.get()
        self.assertEqual(registro.usuario, self.usuario)
        self.assertEqual(registro.acao, Auditoria.ALTERACAO_CAMPO)
        self.assertEqual(registro.entidade_id, 42)
        self.assertEqual(registro.valor_anterior, "Andamento")

    def test_usuario_none_e_valido(self):
        """Rotina automática (RF-18/RF-19, Sincronizador) — sem usuário
        logado, `RiHistorico.autor` também aceita nulo (mesmo padrão)."""
        registrar(None, Auditoria.TRANSICAO_STATUS, entidade="Ri", entidade_id=1)
        registro = Auditoria.objects.get()
        self.assertIsNone(registro.usuario)

    def test_usuario_anonimo_vira_none(self):
        registrar(AnonymousUser(), Auditoria.LOGIN)
        registro = Auditoria.objects.get()
        self.assertIsNone(registro.usuario)

    def test_falha_ao_gravar_nao_propaga_excecao(self):
        """Falhar ao gravar auditoria não pode derrubar a ação sendo
        auditada (login, troca de status, envio de e-mail etc.)."""
        with patch("apps.auditoria.services.Auditoria.objects.create", side_effect=Exception("erro de banco")):
            registrar(self.usuario, Auditoria.ERRO)  # não levanta
        self.assertFalse(Auditoria.objects.exists())


class LoginAuditoriaTests(TestCase):
    def test_login_gera_registro_de_auditoria(self):
        usuario = User.objects.create_user(username="login-aud", password="senha-teste-123")
        self.client.force_login(usuario)
        registro = Auditoria.objects.get(acao=Auditoria.LOGIN)
        self.assertEqual(registro.usuario, usuario)
        self.assertEqual(registro.entidade, "User")
        self.assertEqual(registro.entidade_id, usuario.pk)


class TransicaoStatusAuditoriaTests(TestCase):
    """Mesmo cenário de `RiStatusUpdateViewTests` (apps.ri.tests) — aqui só
    confirma o registro de auditoria, a regra de transição já está
    coberta lá."""

    def setUp(self):
        self.user = User.objects.create_user(username="analista-status-aud", password="senha-teste-123")
        self.escola = Escola.objects.create(inep="60000001", nome="Escola Auditoria Status")

    def test_troca_manual_de_status_gera_registro_de_auditoria(self):
        ri = Ri.objects.create(escola=self.escola, status=Ri.ANDAMENTO)
        self.client.force_login(self.user)
        self.client.post(
            reverse("ri_status_update", kwargs={"pk": ri.pk}),
            {"status": Ri.ENVIO_EMAIL_FATURAMENTO, "next": reverse("grid_inep")},
        )
        registro = Auditoria.objects.get(acao=Auditoria.TRANSICAO_STATUS, entidade="Ri", entidade_id=ri.pk)
        self.assertEqual(registro.usuario, self.user)
        self.assertEqual(registro.valor_anterior, "Em Andamento")
        self.assertEqual(registro.valor_novo, "Envio de Email para faturamento")

    def test_transicao_bloqueada_nao_gera_registro(self):
        ri = Ri.objects.create(escola=self.escola, status=Ri.ENVIO_EMAIL_FATURAMENTO)
        self.client.force_login(self.user)
        self.client.post(
            reverse("ri_status_update", kwargs={"pk": ri.pk}),
            # "Aguardando financeiro" só é trocado pelo sistema (RN-001) —
            # tentativa manual é bloqueada antes de chamar trocar_status_com_log.
            {"status": Ri.AGUARDANDO_FINANCEIRO, "next": reverse("grid_inep")},
        )
        self.assertFalse(Auditoria.objects.filter(acao=Auditoria.TRANSICAO_STATUS).exists())


class AlteracaoCampoAuditoriaTests(TestCase):
    """Mesmo cenário de `RiResponsavelUpdateViewTests` (apps.ri.tests) —
    `_registrar_log_campo` é a única origem de `RiHistorico.LOG_CAMPO`,
    reaproveitada também pelo cadastro/edição/exclusão de item do Lado
    IXC e do Relatório EACE (mesma função, mesmo registro de auditoria)."""

    def setUp(self):
        self.user = User.objects.create_user(username="analista-campo-aud", password="senha-teste-123")
        self.outro = User.objects.create_user(username="outro-campo-aud", password="senha-teste-123")
        self.escola = Escola.objects.create(inep="60000002", nome="Escola Auditoria Campo")
        self.ri = Ri.objects.create(escola=self.escola, status=Ri.ANDAMENTO, responsavel=self.user)

    def test_troca_de_responsavel_gera_registro_de_auditoria(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("ri_responsavel_update", kwargs={"pk": self.ri.pk}),
            {"responsavel": self.outro.pk, "next": reverse("grid_inep")},
        )
        registro = Auditoria.objects.get(acao=Auditoria.ALTERACAO_CAMPO, entidade="Ri", entidade_id=self.ri.pk)
        self.assertEqual(registro.campo, "Responsável")
        self.assertEqual(registro.valor_anterior, self.user.username)
        self.assertEqual(registro.valor_novo, self.outro.username)
        self.assertEqual(registro.usuario, self.user)


_MEDIA_ROOT_TESTE_AUDITORIA_ENVIO = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=_MEDIA_ROOT_TESTE_AUDITORIA_ENVIO)
class EnvioEmailAuditoriaTests(TestCase):
    """Mesmo cenário de `RiEnvioFinanceiroTests` (apps.ri.tests)."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT_TESTE_AUDITORIA_ENVIO, ignore_errors=True)

    def setUp(self):
        self.user = User.objects.create_user(username="analista-envio-aud", password="senha-teste-123")
        self.escola = Escola.objects.create(
            inep="60000003", nome="Escola Auditoria Envio", municipio="Fortaleza", estado="CE"
        )
        self.ri = Ri.objects.create(
            escola=self.escola,
            status=Ri.ENVIO_EMAIL_FATURAMENTO,
            municipio_ixc="Fortaleza",
            estado_ixc="CE",
            data_ativacao=date(2026, 8, 1),
            cnpj="00.000.000/0001-00",
            cnpj_ficticio="11.111.111/0001-11",
        )
        RiItemIxc.objects.create(
            ri=self.ri,
            descricao_item="Kit Cobertura Wi-Fi - 4 Access Points",
            quantidade=1,
            valor_unitario="0",
            eh_kit=True,
        )

    def test_envio_de_email_gera_registro_de_auditoria(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("ri_enviar_email_financeiro", kwargs={"pk": self.ri.pk}),
            {
                "para": "hilber.lustosa@speedcsc.com.br",
                "cc": "",
                "assunto": f"Faturamento EACE — INEP {self.escola.inep}",
                "mensagem": "",
                "next": reverse("grid_inep"),
            },
        )
        registro = Auditoria.objects.get(acao=Auditoria.ENVIO_EMAIL, entidade="Ri", entidade_id=self.ri.pk)
        self.assertEqual(registro.usuario, self.user)
        self.assertIn(self.escola.inep, registro.valor_novo)


_MEDIA_ROOT_TESTE_AUDITORIA_RECEBIMENTO = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=_MEDIA_ROOT_TESTE_AUDITORIA_RECEBIMENTO, **_CONFIG_GRAPH_FINANCEIRO_TESTE)
class RecebimentoEmailAuditoriaTests(TestCase):
    """Mesmo cenário de `SincronizarEmailFinanceiroTests` (apps.ri.tests) —
    credenciais e chamadas de rede são dublês."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT_TESTE_AUDITORIA_RECEBIMENTO, ignore_errors=True)

    def setUp(self):
        self.escola = Escola.objects.create(inep="60000004", nome="Escola Auditoria Recebimento")
        self.ri = Ri.objects.create(escola=self.escola, status=Ri.AGUARDANDO_FINANCEIRO)
        self.codigo = montar_codigo_rastreio(self.escola.inep, timezone.localdate())

    def test_recebimento_de_email_gera_registro_de_auditoria(self):
        bruto = _montar_email_bytes(
            f"#{self.codigo} - Faturamento EACE — INEP {self.escola.inep}",
            anexos=[
                ("nota_fiscal.pdf", "application", "pdf", b"%PDF-1.4 conteudo"),
                ("nota_fiscal.xml", "text", "xml", b"<nfe></nfe>"),
            ],
        )
        resposta = _RespostaGraphFake(
            {
                "value": [{"id": "graph-id-0", "internetMessageId": "<msg-aud@financeiro>"}],
                "@odata.deltaLink": "https://graph.microsoft.com/v1.0/.../delta?token=abc",
            }
        )
        with patch("apps.ri.services._obter_token", return_value="token-de-teste"), patch(
            "apps.ri.services._graph_get", return_value=resposta
        ), patch("apps.ri.services._buscar_mime", return_value=bruto):
            sincronizar_respostas_financeiro()

        registro = Auditoria.objects.get(acao=Auditoria.RECEBIMENTO_EMAIL, entidade="Ri", entidade_id=self.ri.pk)
        self.assertIsNone(registro.usuario)
        self.assertIn(self.escola.inep, registro.valor_novo)


class ErroSistemaAuditoriaMiddlewareTests(TestCase):
    """`AuditoriaErroMiddleware.process_exception` testado isolado (via
    `RequestFactory`) — mais estável do que forçar uma view real a
    levantar exceção através do cliente de teste."""

    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = AuditoriaErroMiddleware(get_response=lambda request: None)

    def test_process_exception_grava_registro_de_auditoria(self):
        usuario = User.objects.create_user(username="erro-user-aud", password="senha-teste-123")
        request = self.factory.get("/algum-caminho/")
        request.user = usuario

        resultado = self.middleware.process_exception(request, ValueError("falha de teste"))

        self.assertIsNone(resultado)  # não trata o erro, só registra
        registro = Auditoria.objects.get(acao=Auditoria.ERRO)
        self.assertEqual(registro.usuario, usuario)
        self.assertEqual(registro.entidade, "/algum-caminho/")
        self.assertEqual(registro.campo, "ValueError")
        self.assertIn("falha de teste", registro.valor_novo)

    def test_process_exception_sem_usuario_autenticado(self):
        request = self.factory.get("/outro-caminho/")
        request.user = AnonymousUser()

        self.middleware.process_exception(request, RuntimeError("erro sem login"))

        registro = Auditoria.objects.get(acao=Auditoria.ERRO)
        self.assertIsNone(registro.usuario)
