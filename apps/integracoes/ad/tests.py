import os
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.integracoes.ad import ad_sync

User = get_user_model()


class SincronizarEmailUsuarioTests(TestCase):
    """RN-044: e-mail sincronizado do AD (mail/proxyAddresses/userPrincipalName),
    sem sobrescrever e-mail ja usado por outro usuario local."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="ana.souza", email="ana.souza@velha.com", password="senha-teste-123",
        )

    def test_usuario_invalido_nao_sincroniza(self):
        atualizado, motivo = ad_sync.sincronizar_email_usuario(None)
        self.assertFalse(atualizado)
        self.assertEqual(motivo, "usuario_invalido")

    def test_ldap_indisponivel_nao_sincroniza(self):
        client = MagicMock()
        client.ready.return_value = False

        atualizado, motivo = ad_sync.sincronizar_email_usuario(self.user, client=client)

        self.assertFalse(atualizado)
        self.assertEqual(motivo, "ldap_indisponivel")

    def test_email_nao_encontrado_no_ad(self):
        client = MagicMock()
        client.ready.return_value = True
        client.buscar_email.return_value = ""

        atualizado, motivo = ad_sync.sincronizar_email_usuario(self.user, client=client)

        self.assertFalse(atualizado)
        self.assertEqual(motivo, "email_nao_encontrado")

    def test_email_ja_utilizado_por_outro_usuario_nao_e_sobrescrito(self):
        User.objects.create_user(
            username="outro.usuario", email="ana.souza@ad.local", password="senha-teste-123",
        )
        client = MagicMock()
        client.ready.return_value = True
        client.buscar_email.return_value = "ana.souza@ad.local"

        atualizado, motivo = ad_sync.sincronizar_email_usuario(self.user, client=client)

        self.user.refresh_from_db()
        self.assertFalse(atualizado)
        self.assertEqual(motivo, "email_ja_utilizado")
        self.assertEqual(self.user.email, "ana.souza@velha.com")

    def test_email_ja_atualizado_nao_grava_novamente(self):
        client = MagicMock()
        client.ready.return_value = True
        client.buscar_email.return_value = "ana.souza@velha.com"

        with patch.object(User, "save") as save_mock:
            atualizado, motivo = ad_sync.sincronizar_email_usuario(self.user, client=client)

        self.assertFalse(atualizado)
        self.assertEqual(motivo, "email_ja_atualizado")
        save_mock.assert_not_called()

    def test_email_e_sincronizado_do_ad_quando_diferente(self):
        client = MagicMock()
        client.ready.return_value = True
        client.buscar_email.return_value = "ana.souza@ad.local"

        atualizado, resultado = ad_sync.sincronizar_email_usuario(self.user, client=client)

        self.user.refresh_from_db()
        self.assertTrue(atualizado)
        self.assertEqual(self.user.email, "ana.souza@ad.local")
        self.assertEqual(resultado, "ana.souza@ad.local")


class SincronizarNomeUsuarioTests(TestCase):
    """RN-044: nome (first_name/last_name) sincronizado do AD (displayName/sn)."""

    def setUp(self):
        self.user = User.objects.create_user(username="ana.souza", password="senha-teste-123")

    def test_usuario_invalido_nao_sincroniza(self):
        atualizado, motivo = ad_sync.sincronizar_nome_usuario(None)
        self.assertFalse(atualizado)
        self.assertEqual(motivo, "usuario_invalido")

    def test_ldap_indisponivel_nao_sincroniza(self):
        client = MagicMock()
        client.ready.return_value = False

        atualizado, motivo = ad_sync.sincronizar_nome_usuario(self.user, client=client)

        self.assertFalse(atualizado)
        self.assertEqual(motivo, "ldap_indisponivel")

    def test_nome_nao_encontrado_no_ad(self):
        client = MagicMock()
        client.ready.return_value = True
        client.buscar_nome.return_value = ("", "")

        atualizado, motivo = ad_sync.sincronizar_nome_usuario(self.user, client=client)

        self.assertFalse(atualizado)
        self.assertEqual(motivo, "nome_nao_encontrado")

    def test_nome_e_sobrenome_sincronizados_do_ad(self):
        client = MagicMock()
        client.ready.return_value = True
        client.buscar_nome.return_value = ("Ana", "Souza")

        atualizado, resultado = ad_sync.sincronizar_nome_usuario(self.user, client=client)

        self.user.refresh_from_db()
        self.assertTrue(atualizado)
        self.assertEqual(self.user.first_name, "Ana")
        self.assertEqual(self.user.last_name, "Souza")
        self.assertEqual(resultado, "Ana Souza")

    def test_sobrenome_vazio_no_ad_nao_apaga_valor_existente(self):
        self.user.last_name = "Souza"
        self.user.save(update_fields=["last_name"])

        client = MagicMock()
        client.ready.return_value = True
        client.buscar_nome.return_value = ("Ana", "")

        atualizado, _ = ad_sync.sincronizar_nome_usuario(self.user, client=client)

        self.user.refresh_from_db()
        self.assertTrue(atualizado)
        self.assertEqual(self.user.first_name, "Ana")
        self.assertEqual(self.user.last_name, "Souza")


class ADDirectoryClientBuscarTests(TestCase):
    def test_buscar_email_prefere_mail_a_proxyaddresses_e_upn(self):
        client = ad_sync.ADDirectoryClient()
        with patch.object(client, "buscar_usuario", return_value=("dn", {
            "mail": [b"ana.souza@ad.local"],
            "proxyAddresses": [b"SMTP:ana.souza@alias.local"],
            "userPrincipalName": [b"ana.souza@upn.local"],
        })):
            email = client.buscar_email("ana.souza")

        self.assertEqual(email, "ana.souza@ad.local")

    def test_buscar_nome_extrai_displayname_e_sn(self):
        client = ad_sync.ADDirectoryClient()
        with patch.object(client, "buscar_usuario", return_value=("dn", {
            "displayName": [b"Ana Souza"],
            "sn": [b"Souza"],
        })):
            first_name, last_name = client.buscar_nome("ana.souza")

        self.assertEqual(first_name, "Ana Souza")
        self.assertEqual(last_name, "Souza")

    def test_buscar_sem_usuario_no_ldap_retorna_vazio(self):
        client = ad_sync.ADDirectoryClient()
        with patch.object(client, "buscar_usuario", return_value=(None, {})):
            self.assertEqual(client.buscar_email("desconhecido"), "")
            self.assertEqual(client.buscar_nome("desconhecido"), ("", ""))

    def test_client_nao_fica_pronto_sem_configuracao(self):
        """Sem AD_SERVER_URI/AD_BIND_DN/AD_USER_SEARCH_BASE no .env, o
        cliente nao tenta conectar; a sincronizacao so retorna
        "ldap_indisponivel". Limpa as 3 variaveis explicitamente (nao
        confia no ambiente onde o teste roda - com o `.env` real
        preenchido, `os.getenv` as encontraria)."""
        env_vazio = {"AD_SERVER_URI": "", "AD_BIND_DN": "", "AD_USER_SEARCH_BASE": ""}
        with patch.dict(os.environ, env_vazio):
            client = ad_sync.ADDirectoryClient()
            self.assertFalse(client.ready())

    def test_client_nao_fica_pronto_sem_biblioteca_ldap(self):
        """Sem `python-ldap` instalado (pendencia de DevOps, ADR-002) ou
        com `USE_AD_AUTH=False`, o cliente tambem nao fica pronto, mesmo
        com AD_SERVER_URI/AD_BIND_DN/AD_USER_SEARCH_BASE configurados."""
        with patch.object(ad_sync, "_ldap_disponivel", return_value=False):
            client = ad_sync.ADDirectoryClient()
            client.server_uri, client.bind_dn, client.search_base = "ldap://x", "dn", "base"
            self.assertFalse(client.ready())


class ReceiversDeLoginTests(TestCase):
    """Receivers conectados a `user_logged_in` (RN-044) - nunca propagam
    excecao, para nao derrubar o login (criterio de aceite FEAT-027)."""

    def setUp(self):
        self.user = User.objects.create_user(username="ana.souza", password="senha-teste-123")

    def test_receiver_de_email_nao_propaga_excecao(self):
        with patch.object(ad_sync, "sincronizar_email_usuario", side_effect=Exception("falha ldap")):
            try:
                ad_sync.sincronizar_email_usuario_no_login(sender=None, user=self.user, request=None)
            except Exception:  # noqa: BLE001
                self.fail("o receiver nao deve propagar excecao do sync do AD")

    def test_receiver_de_nome_nao_propaga_excecao(self):
        with patch.object(ad_sync, "sincronizar_nome_usuario", side_effect=Exception("falha ldap")):
            try:
                ad_sync.sincronizar_nome_usuario_no_login(sender=None, user=self.user, request=None)
            except Exception:  # noqa: BLE001
                self.fail("o receiver nao deve propagar excecao do sync do AD")

    def test_receiver_de_email_chama_o_sync_com_o_usuario_logado(self):
        with patch.object(
            ad_sync, "sincronizar_email_usuario", return_value=(True, "ana.souza@ad.local")
        ) as sync_mock:
            ad_sync.sincronizar_email_usuario_no_login(sender=None, user=self.user, request=None)

        sync_mock.assert_called_once_with(self.user)
