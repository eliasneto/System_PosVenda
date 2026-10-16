"""Testes do RPA do BDO (`rpa_bdo.py`) - navegacao Playwright toda
mockada, sem navegador nem rede. O PDF e real (reportlab + pdfplumber)."""

import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.integracoes.eace.config import ConfigEace
from apps.integracoes.eace.rpa_bdo import anexar_pdf_bdo, arquivo_nf_do_card, cards_do_municipio_uf
from apps.integracoes.eace.tests import _gerar_pdf_nota_fiscal

PEDIDOS_DO_PORTAL = ["3472", "3474", "3657", "3658"]


def _card(municipio="Campo Grande", uf="MS", status="Pendente", valor="1.094,45", posicao=0):
    return {"posicao": posicao, "municipio": municipio, "uf": uf, "ibge": "", "status": status, "valor": valor}


class CardsDoMunicipioUfTests(SimpleTestCase):

    def test_uf_separa_municipios_de_mesmo_nome(self):
        cards = [_card(uf="MS", posicao=0), _card(uf="PB", posicao=1)]
        self.assertEqual([c["posicao"] for c in cards_do_municipio_uf(cards, "CAMPO GRANDE", "ms")], [0])

    def test_sem_uf_traz_todos_do_municipio(self):
        cards = [_card(uf="MS", posicao=0), _card(uf="PB", posicao=1)]
        self.assertEqual(len(cards_do_municipio_uf(cards, "Campo Grande", None)), 2)

    def test_card_sem_uf_no_portal_nao_e_descartado(self):
        self.assertEqual(len(cards_do_municipio_uf([_card(uf="")], "Campo Grande", "MS")), 1)


class ArquivoNfDoCardTests(SimpleTestCase):

    def test_le_o_pdf_anexado_no_card_real(self):
        texto = (
            "Município: Campo Grande/MS\nCod. IBGE: \nStatus: Aprovado\n"
            "Valor total a ser emitido: R$ 1.094,45\nArquivo da Nota Fiscal\n504_13-10-2026_NOME_MEGA INFRA.pdf"
        )
        self.assertEqual(arquivo_nf_do_card(texto), "504_13-10-2026_NOME_MEGA INFRA.pdf")

    def test_card_sem_pdf(self):
        self.assertEqual(arquivo_nf_do_card("Status: Pendente\nArquivo da Nota Fiscal\n"), "")


class AnexarPdfBdoTests(SimpleTestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.pdf = Path(self._tmp.name) / "nota.pdf"
        _gerar_pdf_nota_fiscal(self.pdf, valor="1.094,45")
        self.config = ConfigEace(
            url="https://exemplo", usuario="u", senha="s", headless=True, timeout_ms=1000, delay_ms=0,
        )

    @staticmethod
    def _mock_sync_playwright():
        contexto = MagicMock()
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
        for _ in range(3):
            progresso_callback()
        return True

    @staticmethod
    def _caminho(pedidos=PEDIDOS_DO_PORTAL, expandiu=True, notas_fiscais=True):
        return {
            "bdos": patch("apps.integracoes.eace.rpa_bdo.abrir_bdos", return_value=MagicMock()),
            "pedidos": patch("apps.integracoes.eace.rpa_bdo.listar_pedidos_mip", return_value=list(pedidos)),
            "expandir": patch("apps.integracoes.eace.rpa_bdo.expandir_pedido_mip", return_value=expandiu),
            "notas": patch("apps.integracoes.eace.rpa_bdo.abrir_notas_fiscais", return_value=notas_fiscais),
        }

    def _rodar(self, extras, pedido="3658", municipio="Campo Grande", **kwargs):
        patches = {
            "playwright": patch("playwright.sync_api.sync_playwright", return_value=self._mock_sync_playwright()),
            "login": patch("apps.integracoes.eace.login.fazer_login", side_effect=self._login_com_progresso),
            "perfil": patch("apps.integracoes.eace.login.selecionar_perfil_fornecedor", return_value=True),
            "medicoes": patch("apps.integracoes.eace.dashboard.abrir_medicoes", return_value=True),
            **extras,
        }
        with ExitStack() as stack:
            mocks = {nome: stack.enter_context(p) for nome, p in patches.items()}
            resultado = anexar_pdf_bdo(
                pedido=pedido, municipio=municipio, caminho_pdf=str(self.pdf), config=self.config, **kwargs,
            )
        return resultado, mocks

    @staticmethod
    def _cards(cards):
        return patch("apps.integracoes.eace.rpa_bdo.listar_cards_municipio", return_value=cards)

    @staticmethod
    def _upload(**kwargs):
        return patch("apps.integracoes.eace.rpa_bdo.anexar_pdf_no_card", **kwargs)

    @staticmethod
    def _status_apos_upload(status="Aguardando Aprovação"):
        return patch("apps.integracoes.eace.rpa_bdo.confirmar_envio_card", return_value=status)

    def test_pedido_e_obrigatorio(self):
        with self.assertRaises(ValueError):
            anexar_pdf_bdo(pedido="", municipio="Campo Grande", caminho_pdf=str(self.pdf), config=self.config)

    def test_pdf_sem_valor_aborta_antes_do_navegador(self):
        _gerar_pdf_nota_fiscal(self.pdf, com_valor=False)
        with patch("playwright.sync_api.sync_playwright") as mock_pw:
            resultado = anexar_pdf_bdo(
                pedido="3658", municipio="Campo Grande", caminho_pdf=str(self.pdf), config=self.config,
            )
        self.assertEqual(resultado.motivo, "pdf_sem_valor")
        mock_pw.assert_not_called()

    def test_sem_botao_ver_bdos_aborta(self):
        resultado, mocks = self._rodar({
            "bdos": patch("apps.integracoes.eace.rpa_bdo.abrir_bdos", return_value=None),
            "cards": self._cards([]),
        })
        self.assertEqual(resultado.motivo, "abrir_bdos")
        mocks["cards"].assert_not_called()

    def test_boletim_fora_do_grid_aborta(self):
        resultado, mocks = self._rodar({**self._caminho(), "cards": self._cards([])}, pedido="9999")
        self.assertEqual(resultado.motivo, "pedido_nao_encontrado")
        self.assertEqual(resultado.pedido, "9999")
        mocks["expandir"].assert_not_called()

    def test_falha_ao_abrir_notas_fiscais_aborta(self):
        resultado, mocks = self._rodar({**self._caminho(notas_fiscais=False), "cards": self._cards([])})
        self.assertEqual(resultado.motivo, "abrir_notas_fiscais")
        mocks["cards"].assert_not_called()

    def test_notas_fiscais_sem_cards(self):
        resultado, _ = self._rodar({**self._caminho(), "cards": self._cards([])})
        self.assertEqual(resultado.motivo, "notas_fiscais_sem_cards")

    def test_municipio_de_outra_uf_nao_recebe_o_pdf(self):
        resultado, mocks = self._rodar(
            {**self._caminho(), "cards": self._cards([_card(uf="PB")]), "upload": self._upload()},
            uf="MS",
        )
        self.assertEqual(resultado.motivo, "municipio_nao_encontrado")
        mocks["upload"].assert_not_called()

    def test_expande_o_boletim_informado_e_anexa_no_card_do_municipio(self):
        etapas = []
        resultado, mocks = self._rodar(
            {
                **self._caminho(),
                "cards": self._cards([
                    _card(municipio="Cuiabá", uf="MT", posicao=0),
                    _card(status="Aprovado", posicao=1),
                    _card(posicao=2),
                ]),
                "upload": self._upload(return_value=True),
                "confirmar": self._status_apos_upload(),
            },
            uf="MS",
            progresso_callback=lambda etapa, pct: etapas.append((etapa, pct)),
        )
        self.assertTrue(resultado.sucesso)
        self.assertEqual(resultado.pedido, "3658")
        self.assertEqual(mocks["expandir"].call_args.args[1], 3)
        self.assertEqual(mocks["notas"].call_args.args[1], 3)
        _, posicao, caminho = mocks["upload"].call_args.args
        self.assertEqual(posicao, 2)
        self.assertEqual(caminho, str(self.pdf))
        self.assertEqual(etapas[-1], ("Confirmando o envio", 100))

    def test_card_ja_aprovado_nao_anexa(self):
        resultado, mocks = self._rodar({
            **self._caminho(), "cards": self._cards([_card(status="Aprovado")]), "upload": self._upload(),
        })
        self.assertEqual(resultado.motivo, "documento_ja_enviado")
        self.assertEqual(resultado.status_portal, "Aprovado")
        mocks["upload"].assert_not_called()

    def test_valor_divergente_nao_anexa(self):
        resultado, mocks = self._rodar({
            **self._caminho(), "cards": self._cards([_card(valor="1,00")]), "upload": self._upload(),
        })
        self.assertEqual(resultado.motivo, "valor_divergente")
        mocks["upload"].assert_not_called()

    def test_simulacao_nao_anexa(self):
        resultado, mocks = self._rodar(
            {
                **self._caminho(),
                "cards": self._cards([_card()]),
                "upload": self._upload(),
                "destacar": patch("apps.integracoes.eace.rpa_bdo.destacar_card"),
            },
            simular=True,
        )
        self.assertTrue(resultado.sucesso)
        self.assertTrue(resultado.simulado)
        mocks["upload"].assert_not_called()

    def test_card_continua_pendente_apos_upload(self):
        resultado, _ = self._rodar({
            **self._caminho(),
            "cards": self._cards([_card()]),
            "upload": self._upload(return_value=True),
            "confirmar": self._status_apos_upload("Pendente"),
        })
        self.assertEqual(resultado.motivo, "envio_nao_confirmado")
