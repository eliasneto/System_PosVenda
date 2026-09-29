"""Testes do RPA do MIP (`rpa_mip.py`) - navegacao Playwright toda
mockada, sem navegador nem rede. O PDF e real (reportlab + pdfplumber)."""

import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.integracoes.eace.config import ConfigEace
from apps.integracoes.eace.rpa_mip import (
    anexar_pdf_mip,
    interpretar_card_municipio,
    localizar_card_pendente,
    mesmo_municipio,
    posicao_do_pedido,
    posicao_maior_pedido,
)
from apps.integracoes.eace.tests import _gerar_pdf_nota_fiscal

PEDIDOS_DO_PORTAL = ["402", "413", "429", "442", "455", "473", "492", "506"]


def _card(municipio="PAULINIA", status="Pendente", valor="16.109,00", posicao=0):
    return {"posicao": posicao, "municipio": municipio, "uf": "", "ibge": "", "status": status, "valor": valor}


class PosicaoMaiorPedidoTests(SimpleTestCase):

    def test_maior_pedido_do_grid_real(self):
        self.assertEqual(posicao_maior_pedido(PEDIDOS_DO_PORTAL), 7)

    def test_maior_pedido_fora_de_ordem(self):
        self.assertEqual(posicao_maior_pedido(["506", "1024", "99"]), 1)

    def test_ignora_texto_nao_numerico(self):
        self.assertEqual(posicao_maior_pedido(["", "abc", "12"]), 2)

    def test_sem_pedido_numerico(self):
        self.assertIsNone(posicao_maior_pedido([]))
        self.assertIsNone(posicao_maior_pedido(["", "Pedido"]))


class PosicaoDoPedidoTests(SimpleTestCase):

    def test_acha_o_pedido_informado(self):
        self.assertEqual(posicao_do_pedido(PEDIDOS_DO_PORTAL, "429"), 2)

    def test_compara_como_numero(self):
        self.assertEqual(posicao_do_pedido(PEDIDOS_DO_PORTAL, " 0402 "), 0)

    def test_pedido_ausente_ou_invalido(self):
        self.assertIsNone(posicao_do_pedido(PEDIDOS_DO_PORTAL, "999"))
        self.assertIsNone(posicao_do_pedido(PEDIDOS_DO_PORTAL, "abc"))

class InterpretarCardMunicipioTests(SimpleTestCase):
    """Texto no mesmo formato do `innerText` dos cards do portal."""

    def test_card_sem_ibge(self):
        texto = (
            "Município: PAULINIA/\nCod. IBGE: \nFR: \nStatus: Aprovado\n"
            "Valor total a ser emitido: R$ 16.109,00\n405_22-09-2026_NOME_MEGA INFRA.pdf\nArquivo da Nota Fiscal"
        )
        card = interpretar_card_municipio(texto)
        self.assertEqual(card["municipio"], "PAULINIA")
        self.assertEqual(card["ibge"], "")
        self.assertEqual(card["status"], "Aprovado")
        self.assertEqual(card["valor"], "16.109,00")

    def test_card_com_acento_e_ibge(self):
        texto = (
            "Município: Cândido Rodrigues/\nCod. IBGE: 3510104\nFR: \nStatus: Pendente\n"
            "Valor total a ser emitido: R$ 2.282,27\nArquivo da Nota Fiscal"
        )
        card = interpretar_card_municipio(texto)
        self.assertEqual(card["municipio"], "Cândido Rodrigues")
        self.assertEqual(card["ibge"], "3510104")
        self.assertEqual(card["status"], "Pendente")
        self.assertEqual(card["valor"], "2.282,27")


class MesmoMunicipioTests(SimpleTestCase):

    def test_ignora_acento_e_maiuscula(self):
        self.assertTrue(mesmo_municipio("São Paulo", "SAO PAULO"))
        self.assertTrue(mesmo_municipio("Cândido  Rodrigues", "candido rodrigues"))

    def test_municipios_diferentes(self):
        self.assertFalse(mesmo_municipio("São José dos Campos", "São Paulo"))

    def test_nome_vazio_no_portal_nunca_bate(self):
        self.assertFalse(mesmo_municipio("", ""))


class LocalizarCardPendenteTests(SimpleTestCase):

    def test_card_pendente_com_valor_igual(self):
        card, motivo = localizar_card_pendente(
            [_card(status="Aprovado", posicao=0), _card(posicao=1)], "16109,00",
        )
        self.assertIsNone(motivo)
        self.assertEqual(card["posicao"], 1)

    def test_mesmo_municipio_em_dois_cards_desempata_pelo_valor(self):
        cards = [
            _card(municipio="São Paulo", valor="2.282,27", posicao=1),
            _card(municipio="SAO PAULO", valor="16.109,00", posicao=12),
        ]
        card, motivo = localizar_card_pendente(cards, "16.109,00")
        self.assertIsNone(motivo)
        self.assertEqual(card["posicao"], 12)

    def test_sem_card_pendente(self):
        card, motivo = localizar_card_pendente([_card(status="Aprovado")], "16.109,00")
        self.assertEqual(motivo, "documento_ja_enviado")
        self.assertIsNone(card)

    def test_valor_divergente(self):
        card, motivo = localizar_card_pendente([_card(valor="1.000,00")], "16.109,00")
        self.assertEqual(motivo, "valor_divergente")
        self.assertEqual(card["valor"], "1.000,00")

    def test_valor_ambiguo(self):
        _, motivo = localizar_card_pendente([_card(posicao=0), _card(posicao=1)], "16.109,00")
        self.assertEqual(motivo, "valor_ambiguo")


class AnexarPdfMipTests(SimpleTestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.pdf = Path(self._tmp.name) / "nota.pdf"
        _gerar_pdf_nota_fiscal(self.pdf, valor="16.109,00")
        self.config = ConfigEace(
            url="https://exemplo", usuario="u", senha="s", headless=True, timeout_ms=1000, delay_ms=0,
        )

    @staticmethod
    def _mock_sync_playwright():
        pagina = MagicMock()
        contexto = MagicMock()
        contexto.new_page.return_value = pagina
        navegador = MagicMock()
        navegador.new_context.return_value = contexto
        p = MagicMock()
        p.chromium.launch.return_value = navegador
        cm = MagicMock()
        cm.__enter__.return_value = p
        cm.__exit__.return_value = False
        return cm

    @staticmethod
    def _login_com_progresso(pagina, usuario, senha, progresso_callback=None):
        for _ in range(3):  # usuario, senha, resposta do portal - igual ao login real
            progresso_callback()
        return True

    @staticmethod
    def _caminho(pedidos=PEDIDOS_DO_PORTAL, expandiu=True):
        return {
            "mips": patch("apps.integracoes.eace.rpa_mip.abrir_mips", return_value=MagicMock()),
            "pedidos": patch("apps.integracoes.eace.rpa_mip.listar_pedidos_mip", return_value=list(pedidos)),
            "expandir": patch("apps.integracoes.eace.rpa_mip.expandir_pedido_mip", return_value=expandiu),
        }

    def _rodar(self, extras, municipio="Paulínia", **kwargs):
        """Mocka o trecho comum ate "Medições" + `extras` (nome -> patch).
        Retorna (resultado, dict nome -> mock)."""
        patches = {
            "playwright": patch("playwright.sync_api.sync_playwright", return_value=self._mock_sync_playwright()),
            "login": patch("apps.integracoes.eace.login.fazer_login", side_effect=self._login_com_progresso),
            "perfil": patch("apps.integracoes.eace.login.selecionar_perfil_fornecedor", return_value=True),
            "medicoes": patch("apps.integracoes.eace.dashboard.abrir_medicoes", return_value=True),
            **extras,
        }
        with ExitStack() as stack:
            mocks = {nome: stack.enter_context(p) for nome, p in patches.items()}
            resultado = anexar_pdf_mip(municipio=municipio, caminho_pdf=str(self.pdf), config=self.config, **kwargs)
        return resultado, mocks

    @staticmethod
    def _cards(cards):
        return patch("apps.integracoes.eace.rpa_mip.listar_cards_municipio", return_value=cards)

    @staticmethod
    def _upload(**kwargs):
        return patch("apps.integracoes.eace.rpa_mip.anexar_pdf_no_card", **kwargs)

    @staticmethod
    def _status_apos_upload(status="Aguardando Aprovação"):
        return patch("apps.integracoes.eace.rpa_mip.confirmar_envio_card", return_value=status)

    def test_pdf_sem_valor_aborta_antes_do_navegador(self):
        _gerar_pdf_nota_fiscal(self.pdf, com_valor=False)
        with patch("playwright.sync_api.sync_playwright") as mock_pw:
            resultado = anexar_pdf_mip(municipio="Paulínia", caminho_pdf=str(self.pdf), config=self.config)
        self.assertEqual(resultado.motivo, "pdf_sem_valor")
        mock_pw.assert_not_called()

    def test_sem_botao_ver_mips_aborta(self):
        resultado, mocks = self._rodar({
            "mips": patch("apps.integracoes.eace.rpa_mip.abrir_mips", return_value=None),
            "cards": self._cards([]),
        })
        self.assertEqual(resultado.motivo, "abrir_mips")
        mocks["cards"].assert_not_called()

    def test_grid_de_pedidos_vazio_aborta(self):
        resultado, mocks = self._rodar({**self._caminho(pedidos=[]), "cards": self._cards([])})
        self.assertEqual(resultado.motivo, "pedidos_nao_encontrados")
        mocks["expandir"].assert_not_called()
        mocks["cards"].assert_not_called()

    def test_falha_ao_expandir_pedido_aborta(self):
        resultado, mocks = self._rodar({**self._caminho(expandiu=False), "cards": self._cards([])})
        self.assertEqual(resultado.motivo, "expandir_pedido")
        self.assertEqual(resultado.pedido, "506")
        mocks["cards"].assert_not_called()

    def test_municipio_sem_card_no_pedido_aborta(self):
        resultado, mocks = self._rodar({
            **self._caminho(),
            "cards": self._cards([_card(municipio="ITU")]),
            "upload": self._upload(),
        })
        self.assertEqual(resultado.motivo, "municipio_nao_encontrado")
        mocks["upload"].assert_not_called()

    def test_expande_maior_pedido_e_anexa_o_pdf_no_card_do_municipio(self):
        etapas = []
        resultado, mocks = self._rodar(
            {
                **self._caminho(),
                "cards": self._cards([
                    _card(municipio="ITU", posicao=0),
                    _card(municipio="PAULINIA", status="Aprovado", posicao=1),
                    _card(municipio="PAULINIA", posicao=2),
                ]),
                "upload": self._upload(return_value=True),
                "confirmar": self._status_apos_upload(),
            },
            progresso_callback=lambda etapa, pct: etapas.append((etapa, pct)),
        )
        self.assertTrue(resultado.sucesso)
        self.assertEqual(resultado.pedido, "506")
        self.assertEqual(resultado.valor_portal, "16.109,00")
        self.assertEqual(mocks["expandir"].call_args.args[1], 7)
        _, posicao, caminho = mocks["upload"].call_args.args
        self.assertEqual(posicao, 2)
        self.assertEqual(caminho, str(self.pdf))
        self.assertEqual(etapas[-1], ("Confirmando o envio", 100))

    def test_valor_divergente_nao_anexa(self):
        resultado, mocks = self._rodar({
            **self._caminho(),
            "cards": self._cards([_card(valor="1,00")]),
            "upload": self._upload(),
        })
        self.assertEqual(resultado.motivo, "valor_divergente")
        self.assertEqual(resultado.valor_portal, "1,00")
        mocks["upload"].assert_not_called()

    def test_card_ja_aprovado_informa_o_status_do_portal(self):
        resultado, _ = self._rodar({
            **self._caminho(),
            "cards": self._cards([_card(status="Aprovado"), _card(status="Aguardando Aprovação", posicao=1)]),
            "upload": self._upload(),
        })
        self.assertEqual(resultado.motivo, "documento_ja_enviado")
        self.assertEqual(resultado.status_portal, "Aguardando Aprovação, Aprovado")

    def test_valor_divergente_informa_o_status_do_card(self):
        resultado, _ = self._rodar({
            **self._caminho(),
            "cards": self._cards([_card(valor="1,00")]),
            "upload": self._upload(),
        })
        self.assertEqual(resultado.status_portal, "Pendente")

    def test_card_ja_aprovado_nao_anexa(self):
        resultado, mocks = self._rodar({
            **self._caminho(),
            "cards": self._cards([_card(status="Aprovado")]),
            "upload": self._upload(),
        })
        self.assertEqual(resultado.motivo, "documento_ja_enviado")
        mocks["upload"].assert_not_called()

    def test_falha_no_upload(self):
        resultado, _ = self._rodar({
            **self._caminho(),
            "cards": self._cards([_card()]),
            "upload": self._upload(return_value=False),
        })
        self.assertEqual(resultado.motivo, "upload")

    def test_modo_simulacao_chega_no_card_certo_sem_anexar(self):
        resultado, mocks = self._rodar(
            {
                **self._caminho(),
                "cards": self._cards([_card(posicao=0), _card(municipio="ITU", posicao=1)]),
                "destacar": patch("apps.integracoes.eace.rpa_mip.destacar_card"),
                "upload": self._upload(),
            },
            simular=True,
        )
        self.assertTrue(resultado.sucesso)
        self.assertTrue(resultado.simulado)
        self.assertEqual(resultado.pedido, "506")
        self.assertEqual(mocks["destacar"].call_args.args[1], 0)
        mocks["upload"].assert_not_called()

    def test_pasta_de_capturas_salva_uma_imagem_por_etapa(self):
        with patch("apps.integracoes.eace.rpa_mip.CapturasRpaMip.salvar") as mock_salvar:
            resultado, _ = self._rodar(
                {
                    **self._caminho(),
                    "cards": self._cards([_card()]),
                    "upload": self._upload(return_value=True),
                    "confirmar": self._status_apos_upload(),
                },
                pasta_capturas=Path(self._tmp.name) / "capturas",
            )
        self.assertTrue(resultado.sucesso)
        descricoes = [chamada.args[1] for chamada in mock_salvar.call_args_list]
        self.assertEqual(descricoes[0], "Abrindo o portal EACE")
        self.assertIn("Abrindo MIPs", descricoes)
        self.assertIn("Expandindo o pedido", descricoes)
        self.assertEqual(descricoes[-2:], ["Anexando o PDF", "Confirmando o envio"])

    def test_erro_tambem_gera_captura(self):
        with patch("apps.integracoes.eace.rpa_mip.CapturasRpaMip.salvar") as mock_salvar:
            resultado, _ = self._rodar(
                {**self._caminho(), "cards": self._cards([])},
                pasta_capturas=Path(self._tmp.name) / "capturas",
            )
        self.assertEqual(resultado.motivo, "municipio_nao_encontrado")
        self.assertEqual(mock_salvar.call_args_list[-1].args[1], "Erro municipio_nao_encontrado")

    def _rodar_sem_pdf(self, extras, municipio=None):
        """Mesmo mock de `_rodar`, mas sem PDF (simulacao)."""
        patches = {
            "playwright": patch("playwright.sync_api.sync_playwright", return_value=self._mock_sync_playwright()),
            "login": patch("apps.integracoes.eace.login.fazer_login", side_effect=self._login_com_progresso),
            "perfil": patch("apps.integracoes.eace.login.selecionar_perfil_fornecedor", return_value=True),
            "medicoes": patch("apps.integracoes.eace.dashboard.abrir_medicoes", return_value=True),
            **extras,
        }
        with ExitStack() as stack:
            mocks = {nome: stack.enter_context(p) for nome, p in patches.items()}
            resultado = anexar_pdf_mip(municipio=municipio, caminho_pdf=None, config=self.config, simular=True)
        return resultado, mocks

    def test_simulacao_sem_pdf_e_sem_municipio_le_todos_os_cards(self):
        cards = [_card(municipio="ITU", status="Aprovado"), _card(municipio="PAULINIA", posicao=1)]
        resultado, mocks = self._rodar_sem_pdf({
            **self._caminho(),
            "cards": self._cards(cards),
            "destacar": patch("apps.integracoes.eace.rpa_mip.destacar_card"),
            "upload": self._upload(),
        })
        self.assertTrue(resultado.sucesso)
        self.assertTrue(resultado.simulado)
        self.assertEqual(resultado.pedido, "506")
        self.assertEqual(resultado.cards_encontrados, cards)
        mocks["destacar"].assert_not_called()
        mocks["upload"].assert_not_called()

    def test_simulacao_sem_pdf_destaca_o_card_do_municipio_mesmo_ja_aprovado(self):
        cards = [_card(municipio="ITU", posicao=0), _card(municipio="PAULINIA", status="Aprovado", posicao=1)]
        resultado, mocks = self._rodar_sem_pdf({
            **self._caminho(),
            "cards": self._cards(cards),
            "destacar": patch("apps.integracoes.eace.rpa_mip.destacar_card"),
            "upload": self._upload(),
        }, municipio="Paulínia")
        self.assertTrue(resultado.sucesso)
        self.assertEqual(mocks["destacar"].call_args.args[1], 1)
        mocks["upload"].assert_not_called()

    def test_simulacao_sem_pdf_municipio_ausente_devolve_os_cards_lidos(self):
        cards = [_card(municipio="ITU")]
        resultado, _ = self._rodar_sem_pdf({**self._caminho(), "cards": self._cards(cards)}, municipio="Barueri")
        self.assertEqual(resultado.motivo, "municipio_nao_encontrado")
        self.assertEqual(resultado.cards_encontrados, cards)

    def test_anexar_de_verdade_sem_pdf_e_recusado(self):
        with self.assertRaises(ValueError):
            anexar_pdf_mip(municipio="Itu", caminho_pdf=None, config=self.config)
    def test_card_aguardando_aprovacao_conta_como_ja_enviado(self):
        resultado, mocks = self._rodar({
            **self._caminho(),
            "cards": self._cards([_card(status="Aguardando Aprovação")]),
            "upload": self._upload(),
        })
        self.assertEqual(resultado.motivo, "documento_ja_enviado")
        mocks["upload"].assert_not_called()

    def test_card_continua_pendente_depois_do_upload_e_erro(self):
        resultado, _ = self._rodar({
            **self._caminho(),
            "cards": self._cards([_card()]),
            "upload": self._upload(return_value=True),
            "confirmar": self._status_apos_upload("Pendente"),
        })
        self.assertFalse(resultado.sucesso)
        self.assertEqual(resultado.motivo, "envio_nao_confirmado")

    def test_card_ja_aprovado_logo_apos_o_upload_e_sucesso(self):
        resultado, _ = self._rodar({
            **self._caminho(),
            "cards": self._cards([_card()]),
            "upload": self._upload(return_value=True),
            "confirmar": self._status_apos_upload("Aprovado"),
        })
        self.assertTrue(resultado.sucesso)

    def test_pedido_informado_expande_esse_pedido_e_nao_o_maior(self):
        resultado, mocks = self._rodar_sem_pdf({**self._caminho(), "cards": self._cards([_card()])})
        self.assertEqual(mocks["expandir"].call_args.args[1], 7)  # sem pedido: o maior (506)

        patches = {**self._caminho(), "cards": self._cards([_card()])}
        with ExitStack() as stack:
            base = {
                "playwright": patch("playwright.sync_api.sync_playwright", return_value=self._mock_sync_playwright()),
                "login": patch("apps.integracoes.eace.login.fazer_login", side_effect=self._login_com_progresso),
                "perfil": patch("apps.integracoes.eace.login.selecionar_perfil_fornecedor", return_value=True),
                "medicoes": patch("apps.integracoes.eace.dashboard.abrir_medicoes", return_value=True),
                **patches,
            }
            mocks = {nome: stack.enter_context(p) for nome, p in base.items()}
            resultado = anexar_pdf_mip(municipio=None, caminho_pdf=None, config=self.config, simular=True, pedido="429")
        self.assertTrue(resultado.sucesso)
        self.assertEqual(resultado.pedido, "429")
        self.assertEqual(mocks["expandir"].call_args.args[1], 2)

    def test_pedido_informado_que_nao_existe_no_grid(self):
        with ExitStack() as stack:
            base = {
                "playwright": patch("playwright.sync_api.sync_playwright", return_value=self._mock_sync_playwright()),
                "login": patch("apps.integracoes.eace.login.fazer_login", side_effect=self._login_com_progresso),
                "perfil": patch("apps.integracoes.eace.login.selecionar_perfil_fornecedor", return_value=True),
                "medicoes": patch("apps.integracoes.eace.dashboard.abrir_medicoes", return_value=True),
                **self._caminho(),
                "cards": self._cards([_card()]),
            }
            mocks = {nome: stack.enter_context(p) for nome, p in base.items()}
            resultado = anexar_pdf_mip(municipio=None, caminho_pdf=None, config=self.config, simular=True, pedido="999")
        self.assertEqual(resultado.motivo, "pedido_nao_encontrado")
        self.assertEqual(resultado.pedido, "999")
        mocks["expandir"].assert_not_called()
        mocks["cards"].assert_not_called()

class ConfirmarEnvioCardTests(SimpleTestCase):
    """`confirmar_envio_card` rele o card ate o status sair de "Pendente"."""

    def _pagina(self, *status_lidos):
        pagina = MagicMock()
        textos = [f"Município: ITU/\nStatus: {s}\nValor total a ser emitido: R$ 1,00" for s in status_lidos]
        pagina.locator.return_value.inner_text.side_effect = textos
        return pagina

    def test_espera_ate_aguardando_aprovacao(self):
        from apps.integracoes.eace.rpa_mip import confirmar_envio_card

        pagina = self._pagina("Pendente", "Pendente", "Aguardando Aprovação")
        self.assertEqual(confirmar_envio_card(pagina, 0, timeout_ms=10_000), "Aguardando Aprovação")
        self.assertEqual(pagina.wait_for_timeout.call_count, 2)

    def test_desiste_no_timeout_e_devolve_o_ultimo_status(self):
        from apps.integracoes.eace.rpa_mip import confirmar_envio_card

        pagina = self._pagina(*["Pendente"] * 4)
        self.assertEqual(confirmar_envio_card(pagina, 0, timeout_ms=3_000), "Pendente")
        self.assertEqual(pagina.wait_for_timeout.call_count, 3)

class ComandoValidarRpaMipTests(SimpleTestCase):
    """`validar_rpa_mip` (apps/escolas): simulacao por padrao, repassa as
    opcoes visuais para `anexar_pdf_mip`."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.pdf = Path(self._tmp.name) / "nota.pdf"
        _gerar_pdf_nota_fiscal(self.pdf, valor="16.109,00")

    def _rodar(self, *args):
        from io import StringIO

        from django.core.management import call_command

        from apps.integracoes.eace.rpa_mip import ResultadoRpaMip

        saida = StringIO()
        resultado = ResultadoRpaMip(sucesso=True, dados_pdf={"valor": "16.109,00"}, valor_portal="16.109,00",
                                    pedido="506", simulado="--aplicar" not in args)
        with patch("apps.escolas.management.commands.validar_rpa_mip.anexar_pdf_mip",
                   return_value=resultado) as mock_rpa:
            call_command("validar_rpa_mip", "--municipio", "São Paulo", "--pdf", str(self.pdf),
                         "--pasta", self._tmp.name, *args, stdout=saida)
        return mock_rpa.call_args.kwargs, saida.getvalue()

    def test_padrao_e_simulacao_headless_do_env(self):
        kwargs, saida = self._rodar()
        self.assertTrue(kwargs["simular"])
        self.assertIsNone(kwargs["headless"])
        self.assertEqual(kwargs["lento_ms"], 0)
        self.assertFalse(kwargs["gravar_video"])
        self.assertIn("Nada foi anexado", saida)

    def test_visivel_abre_navegador_e_desacelera(self):
        kwargs, _ = self._rodar("--visivel", "--video")
        self.assertFalse(kwargs["headless"])
        self.assertEqual(kwargs["lento_ms"], 500)
        self.assertTrue(kwargs["gravar_video"])

    def test_aplicar_anexa_de_verdade(self):
        kwargs, saida = self._rodar("--aplicar")
        self.assertFalse(kwargs["simular"])
        self.assertIn("PDF anexado no portal", saida)

    def test_pdf_inexistente(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("validar_rpa_mip", "--municipio", "Itu", "--pdf", str(Path(self._tmp.name) / "x.pdf"))

    def test_sem_pdf_e_sem_municipio_roda_simulacao(self):
        from io import StringIO

        from django.core.management import call_command

        from apps.integracoes.eace.rpa_mip import ResultadoRpaMip

        saida = StringIO()
        resultado = ResultadoRpaMip(sucesso=True, dados_pdf={}, pedido="506", simulado=True,
                                    cards_encontrados=[_card(municipio="Cândido Rodrigues", status="Aprovado")])
        with patch("apps.escolas.management.commands.validar_rpa_mip.anexar_pdf_mip",
                   return_value=resultado) as mock_rpa:
            call_command("validar_rpa_mip", "--pasta", self._tmp.name, stdout=saida)
        kwargs = mock_rpa.call_args.kwargs
        self.assertIsNone(kwargs["caminho_pdf"])
        self.assertIsNone(kwargs["municipio"])
        self.assertTrue(kwargs["simular"])
        self.assertIn("Cândido Rodrigues", saida.getvalue())
        self.assertIn("Simulacao sem PDF OK", saida.getvalue())

    def test_aplicar_sem_pdf_e_recusado(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("validar_rpa_mip", "--municipio", "Itu", "--aplicar")

    def test_pedido_repassado_para_o_rpa(self):
        from io import StringIO

        from django.core.management import call_command

        from apps.integracoes.eace.rpa_mip import ResultadoRpaMip

        resultado = ResultadoRpaMip(sucesso=True, dados_pdf={}, pedido="429", simulado=True, cards_encontrados=[])
        with patch("apps.escolas.management.commands.validar_rpa_mip.anexar_pdf_mip",
                   return_value=resultado) as mock_rpa:
            call_command("validar_rpa_mip", "--pedido", "429", "--pasta", self._tmp.name, stdout=StringIO())
        self.assertEqual(mock_rpa.call_args.kwargs["pedido"], "429")

    def test_pedido_invalido_e_recusado(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("validar_rpa_mip", "--pedido", "40a")


class CarregarTodosOsCardsTests(SimpleTestCase):
    """O grid do Bubble.io so renderiza mais cards conforme rola."""

    def test_rola_ate_a_quantidade_parar_de_crescer(self):
        from apps.integracoes.eace.rpa_mip import _carregar_todos_os_cards

        pagina = MagicMock()
        pagina.evaluate.side_effect = [17, 24, 29, 29, 29, 29]
        self.assertEqual(_carregar_todos_os_cards(pagina, espera_ms=0), 29)
        self.assertEqual(pagina.evaluate.call_count, 5)

    def test_para_no_limite_de_rolagens(self):
        from apps.integracoes.eace.rpa_mip import _carregar_todos_os_cards

        pagina = MagicMock()
        pagina.evaluate.side_effect = list(range(1, 100))
        self.assertEqual(_carregar_todos_os_cards(pagina, max_rolagens=4, espera_ms=0), 4)


class ExtrairValorNfseTests(SimpleTestCase):
    """NF do MIP é NFS-e - texto real do 1º envio (LOTE-0037, 2026-09-29)."""

    def test_valor_total_do_servico(self):
        from apps.integracoes.eace.rpa_mip import extrair_valor_nfse

        texto = "Discriminação dos Serviços\nVALOR TOTAL DO SERVIÇO = R$ 15.483,97\nVALOR TOTAL COBRADO = R$ 15.483,97"
        self.assertEqual(extrair_valor_nfse(texto), "15.483,97")

    def test_sem_servico_usa_o_valor_cobrado(self):
        from apps.integracoes.eace.rpa_mip import extrair_valor_nfse

        self.assertEqual(extrair_valor_nfse("VALOR TOTAL COBRADO = R$ 2.282,27"), "2.282,27")

    def test_sem_valor(self):
        from apps.integracoes.eace.rpa_mip import extrair_valor_nfse

        self.assertEqual(extrair_valor_nfse("Valor Total das Deduções (R$) Base de Cálculo (R$)"), "")

    def test_pdf_nfse_de_ponta_a_ponta(self):
        from reportlab.pdfgen import canvas

        from apps.integracoes.eace.rpa_mip import extrair_dados_nf_mip

        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "nfse.pdf"
            c = canvas.Canvas(str(caminho))
            c.drawString(50, 750, "NOTA FISCAL ELETRONICA DE SERVICOS - NFS-e")
            c.drawString(50, 730, "VALOR TOTAL DO SERVICO = R$ 15.483,97")
            c.save()
            dados = extrair_dados_nf_mip(str(caminho))
        self.assertEqual(dados["valor"], "15.483,97")
        self.assertFalse(dados["ilegivel"])

    def test_nf_de_produto_continua_funcionando(self):
        from apps.integracoes.eace.rpa_mip import extrair_dados_nf_mip

        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "nf.pdf"
            _gerar_pdf_nota_fiscal(caminho, valor="22.644,43")
            self.assertEqual(extrair_dados_nf_mip(str(caminho))["valor"], "22.644,43")
