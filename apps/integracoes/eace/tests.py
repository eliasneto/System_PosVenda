"""FEAT-033 (Fase 1, ADR-004/RN-056/RN-057): testes do nucleo do RPA
(extracao de dados do PDF, validacao antes de abrir o portal) e do
comando de terminal `eace_anexar_nota_fiscal`, sem depender de navegador
nem de rede - o nucleo Playwright (`anexar_nota_fiscal`) e mockado nos
testes do comando. Os testes de `extrair_dados_pdf` e da validacao
antecipada de `anexar_nota_fiscal` (RN-057) sao reais - geram um PDF de
verdade (reportlab, ja usado no projeto) e leem com pdfplumber. A
validacao contra o portal em si (valor divergente, upload) e manual
(RN-056/FEAT-033, "Fase 1"), como qualquer RPA nao tem como ser coberta
por teste automatizado de verdade.
"""

import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from reportlab.pdfgen import canvas

from apps.integracoes.eace import extrair_dados_pdf
from apps.integracoes.eace.rpa import ResultadoRpaEace, RpaEaceIndisponivel, anexar_nota_fiscal


def _gerar_pdf_nota_fiscal(caminho, inep="35083938", valor="22.644,43", com_inep=True, com_valor=True):
    """Gera um PDF minimo com o mesmo formato que `extrair_dados_pdf`
    procura - usado para testar a extracao de ponta a ponta, sem
    depender de um PDF real de Nota Fiscal."""
    c = canvas.Canvas(str(caminho))
    y = 750  # pagina padrao (letter) tem 792pt de altura - fica com margem
    linhas = ["NOTA FISCAL ELETRONICA", "MEGA INFRA SOLUCOES EM INFRAESTRUTURA"]
    if com_inep:
        linhas.append(f"INEP: {inep}")
    linhas.append("001 Kit Cobertura Wi-Fi - 12 Access Points 8517.62.59")
    if com_valor:
        linhas.append("VALOR TOTAL DA NOTA")
        linhas.append(f"1 {valor} {valor}")
    for linha in linhas:
        c.drawString(50, y, linha)
        y -= 20
    c.save()


class ExtrairDadosPdfTests(SimpleTestCase):
    """RN-057: regex de extracao, isoladas (sem PDF, so o texto)."""

    def test_extrai_inep(self):
        self.assertEqual(extrair_dados_pdf.extrair_inep("algo\nINEP: 35083938\noutro"), "35083938")

    def test_inep_ausente_retorna_vazio(self):
        self.assertEqual(extrair_dados_pdf.extrair_inep("nada aqui"), "")

    def test_extrai_valor(self):
        texto = "VALOR TOTAL DA NOTA\n1 22.644,43 22.644,43"
        self.assertEqual(extrair_dados_pdf.extrair_valor(texto), "22.644,43")

    def test_valor_ausente_retorna_vazio(self):
        self.assertEqual(extrair_dados_pdf.extrair_valor("sem essa secao"), "")

    def test_extrai_produto(self):
        texto = "001 Kit Cobertura Wi-Fi - 12 Access Points 8517.62.59"
        self.assertEqual(extrair_dados_pdf.extrair_produto(texto), "Kit Cobertura Wi-Fi - 12 Access Points")

    def test_valores_iguais_ignora_formatacao(self):
        self.assertTrue(extrair_dados_pdf.valores_iguais("22.644,43", "22.644,43"))

    def test_valores_diferentes(self):
        self.assertFalse(extrair_dados_pdf.valores_iguais("22.644,43", "1.551,93"))

    def test_valor_invalido_nunca_bate(self):
        self.assertFalse(extrair_dados_pdf.valores_iguais("", "22.644,43"))
        self.assertFalse(extrair_dados_pdf.valores_iguais("abc", "abc"))


class ExtrairDadosNotaFiscalPdfRealTests(SimpleTestCase):
    """RN-057: gera um PDF de verdade (reportlab) e le com pdfplumber -
    cobre o pipeline completo de `extrair_dados_nota_fiscal`, nao so o
    regex isolado."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.pdf = Path(self._tmp.name) / "nota.pdf"

    def test_extrai_inep_produto_e_valor_de_pdf_real(self):
        _gerar_pdf_nota_fiscal(self.pdf, inep="35083938", valor="22.644,43")
        dados = extrair_dados_pdf.extrair_dados_nota_fiscal(str(self.pdf))
        self.assertEqual(dados["inep"], "35083938")
        self.assertEqual(dados["valor"], "22.644,43")
        self.assertIn("Kit Cobertura Wi-Fi", dados["produto"])

    def test_pdf_sem_inep(self):
        _gerar_pdf_nota_fiscal(self.pdf, com_inep=False)
        dados = extrair_dados_pdf.extrair_dados_nota_fiscal(str(self.pdf))
        self.assertEqual(dados["inep"], "")

    def test_pdf_sem_valor(self):
        _gerar_pdf_nota_fiscal(self.pdf, com_valor=False)
        dados = extrair_dados_pdf.extrair_dados_nota_fiscal(str(self.pdf))
        self.assertEqual(dados["valor"], "")

    def test_pdf_ilegivel_nao_estoura_excecao(self):
        arquivo_invalido = Path(self._tmp.name) / "nao-e-pdf.pdf"
        arquivo_invalido.write_bytes(b"isto nao e um PDF de verdade")
        dados = extrair_dados_pdf.extrair_dados_nota_fiscal(str(arquivo_invalido))
        self.assertEqual(dados, {"inep": "", "produto": "", "valor": ""})


class AnexarNotaFiscalValidacaoAntecipadaTests(SimpleTestCase):
    """RN-057: `anexar_nota_fiscal` confere o PDF ANTES de abrir o
    navegador - por isso estes testes rodam de verdade (sem mock do
    Playwright) e ainda assim nao precisam de rede nem de portal real."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.pdf = Path(self._tmp.name) / "nota.pdf"
        self.xml = Path(self._tmp.name) / "nota.xml"
        self.xml.write_text("<xml/>", encoding="utf-8")

    def _rodar(self, **kwargs):
        base = {"osp": "3929", "inep": "35083938", "indice": 1, "caminho_xml": str(self.xml)}
        base.update(kwargs)
        return anexar_nota_fiscal(caminho_pdf=str(self.pdf), **base)

    def test_pdf_sem_inep_aborta_antes_do_navegador(self):
        _gerar_pdf_nota_fiscal(self.pdf, com_inep=False)
        resultado = self._rodar()
        self.assertFalse(resultado.sucesso)
        self.assertEqual(resultado.motivo, "pdf_sem_inep")

    def test_pdf_sem_valor_aborta_antes_do_navegador(self):
        _gerar_pdf_nota_fiscal(self.pdf, com_valor=False)
        resultado = self._rodar()
        self.assertFalse(resultado.sucesso)
        self.assertEqual(resultado.motivo, "pdf_sem_valor")

    def test_inep_do_pdf_diferente_do_informado_aborta_antes_do_navegador(self):
        _gerar_pdf_nota_fiscal(self.pdf, inep="35083938")
        resultado = self._rodar(inep="99999999")
        self.assertFalse(resultado.sucesso)
        self.assertEqual(resultado.motivo, "inep_divergente_do_pdf")
        self.assertEqual(resultado.dados_pdf["inep"], "35083938")


class AnexarNotaFiscalValidacaoContraOPortalTests(SimpleTestCase):
    """RN-056: checagens feitas depois de abrir o portal (OSP inexistente,
    linha ja processada) - navegacao inteira mockada, sem browser real."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.pdf = Path(self._tmp.name) / "nota.pdf"
        self.xml = Path(self._tmp.name) / "nota.xml"
        _gerar_pdf_nota_fiscal(self.pdf, inep="35083938", valor="22.644,43")
        self.xml.write_text("<xml/>", encoding="utf-8")

    def _mock_sync_playwright(self):
        """Monta a cadeia sync_playwright() -> p -> navegador -> contexto
        -> pagina, toda com MagicMock, para nao precisar de browser real."""
        pagina = MagicMock()
        pagina.title.return_value = "Login"
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

    def test_osp_nao_encontrada_aborta_sem_tentar_expandir(self):
        with patch("playwright.sync_api.sync_playwright", return_value=self._mock_sync_playwright()), \
                patch("apps.integracoes.eace.login.fazer_login", return_value=True), \
                patch("apps.integracoes.eace.login.selecionar_perfil_fornecedor", return_value=True), \
                patch("apps.integracoes.eace.dashboard.abrir_medicoes", return_value=True), \
                patch("apps.integracoes.eace.dashboard.abrir_osps", return_value=True), \
                patch("apps.integracoes.eace.dashboard.pesquisar_osp", return_value=True), \
                patch("apps.integracoes.eace.dashboard.contar_pedidos_osp", return_value=0) as mock_contar, \
                patch("apps.integracoes.eace.dashboard.expandir_resultado_osp") as mock_expandir:
            resultado = anexar_nota_fiscal(
                osp="999999999", inep="35083938", indice=1,
                caminho_pdf=str(self.pdf), caminho_xml=str(self.xml),
            )
        self.assertFalse(resultado.sucesso)
        self.assertEqual(resultado.motivo, "osp_nao_encontrada")
        mock_contar.assert_called_once()
        mock_expandir.assert_not_called()

    def test_documento_ja_enviado_aborta_sem_upload(self):
        linha_ja_enviada = [
            {"inep": "35083938", "status": "Aprovado", "descricao": "Kit", "valor": "22.644,43", "indice": 1},
        ]
        with patch("playwright.sync_api.sync_playwright", return_value=self._mock_sync_playwright()), \
                patch("apps.integracoes.eace.login.fazer_login", return_value=True), \
                patch("apps.integracoes.eace.login.selecionar_perfil_fornecedor", return_value=True), \
                patch("apps.integracoes.eace.dashboard.abrir_medicoes", return_value=True), \
                patch("apps.integracoes.eace.dashboard.abrir_osps", return_value=True), \
                patch("apps.integracoes.eace.dashboard.pesquisar_osp", return_value=True), \
                patch("apps.integracoes.eace.dashboard.contar_pedidos_osp", return_value=1), \
                patch("apps.integracoes.eace.dashboard.expandir_resultado_osp", return_value=True), \
                patch("apps.integracoes.eace.dashboard.expandir_notas_fiscais", return_value=True), \
                patch("apps.integracoes.eace.dashboard.extrair_dados_grid", return_value=linha_ja_enviada), \
                patch("apps.integracoes.eace.dashboard.upload_linha") as mock_upload:
            resultado = anexar_nota_fiscal(
                osp="3929", inep="35083938", indice=1,
                caminho_pdf=str(self.pdf), caminho_xml=str(self.xml),
            )
        self.assertFalse(resultado.sucesso)
        self.assertEqual(resultado.motivo, "documento_ja_enviado")
        mock_upload.assert_not_called()

    def test_linha_pendente_com_valor_igual_segue_ate_o_upload(self):
        linha_pendente = [
            {"inep": "35083938", "status": "Pendente", "descricao": "Kit", "valor": "22.644,43", "indice": 1},
        ]
        with patch("playwright.sync_api.sync_playwright", return_value=self._mock_sync_playwright()), \
                patch("apps.integracoes.eace.login.fazer_login", return_value=True), \
                patch("apps.integracoes.eace.login.selecionar_perfil_fornecedor", return_value=True), \
                patch("apps.integracoes.eace.dashboard.abrir_medicoes", return_value=True), \
                patch("apps.integracoes.eace.dashboard.abrir_osps", return_value=True), \
                patch("apps.integracoes.eace.dashboard.pesquisar_osp", return_value=True), \
                patch("apps.integracoes.eace.dashboard.contar_pedidos_osp", return_value=1), \
                patch("apps.integracoes.eace.dashboard.expandir_resultado_osp", return_value=True), \
                patch("apps.integracoes.eace.dashboard.expandir_notas_fiscais", return_value=True), \
                patch("apps.integracoes.eace.dashboard.extrair_dados_grid", return_value=linha_pendente), \
                patch("apps.integracoes.eace.dashboard.upload_linha", return_value=True) as mock_upload, \
                patch("apps.integracoes.eace.dashboard.clicar_enviar_notas", return_value=True):
            resultado = anexar_nota_fiscal(
                osp="3929", inep="35083938", indice=1,
                caminho_pdf=str(self.pdf), caminho_xml=str(self.xml),
            )
        self.assertTrue(resultado.sucesso)
        mock_upload.assert_called_once()

    def test_progresso_reporta_todas_as_etapas_ate_100_por_cento(self):
        """Pedido do usuário (2026-09-03): no caminho feliz completo, o
        `progresso_callback` precisa passar por TODAS as etapas de
        `ETAPAS_RPA_EACE`, em ordem, terminando em 100% - inclusive as 3
        etapas internas de `fazer_login` (usuário/senha/aguardar), por
        isso o mock daqui chama o callback recebido (diferente dos outros
        testes desta classe, que só retornam True)."""
        from apps.integracoes.eace.rpa import ETAPAS_RPA_EACE

        linha_pendente = [
            {"inep": "35083938", "status": "Pendente", "descricao": "Kit", "valor": "22.644,43", "indice": 1},
        ]

        def _fazer_login_side_effect(pagina, usuario, senha, progresso_callback=None):
            if progresso_callback:
                progresso_callback()
                progresso_callback()
                progresso_callback()
            return True

        chamadas = []
        with patch("playwright.sync_api.sync_playwright", return_value=self._mock_sync_playwright()), \
                patch("apps.integracoes.eace.login.fazer_login", side_effect=_fazer_login_side_effect), \
                patch("apps.integracoes.eace.login.selecionar_perfil_fornecedor", return_value=True), \
                patch("apps.integracoes.eace.dashboard.abrir_medicoes", return_value=True), \
                patch("apps.integracoes.eace.dashboard.abrir_osps", return_value=True), \
                patch("apps.integracoes.eace.dashboard.pesquisar_osp", return_value=True), \
                patch("apps.integracoes.eace.dashboard.contar_pedidos_osp", return_value=1), \
                patch("apps.integracoes.eace.dashboard.expandir_resultado_osp", return_value=True), \
                patch("apps.integracoes.eace.dashboard.expandir_notas_fiscais", return_value=True), \
                patch("apps.integracoes.eace.dashboard.extrair_dados_grid", return_value=linha_pendente), \
                patch("apps.integracoes.eace.dashboard.upload_linha", return_value=True), \
                patch("apps.integracoes.eace.dashboard.clicar_enviar_notas", return_value=True):
            resultado = anexar_nota_fiscal(
                osp="3929", inep="35083938", indice=1,
                caminho_pdf=str(self.pdf), caminho_xml=str(self.xml),
                progresso_callback=lambda etapa, pct: chamadas.append((etapa, pct)),
            )

        self.assertTrue(resultado.sucesso)
        esperado = [
            (etapa, round((i + 1) / len(ETAPAS_RPA_EACE) * 100)) for i, etapa in enumerate(ETAPAS_RPA_EACE)
        ]
        self.assertEqual(chamadas, esperado)
        self.assertEqual(chamadas[-1], ("Enviando as notas", 100))


class ConsultarPendenciasEaceTests(SimpleTestCase):
    """RN-063 (melhoria 2026-09-04): consulta somente-leitura do grid do
    portal - mesma navegação de `anexar_nota_fiscal` até ler o grid,
    nunca chega a `upload_linha`/`clicar_enviar_notas`."""

    def _mock_sync_playwright(self):
        pagina = MagicMock()
        pagina.title.return_value = "Login"
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

    def test_retorna_as_linhas_do_grid_sem_subir_nada(self):
        from apps.integracoes.eace.rpa import consultar_pendencias_eace

        linhas = [
            {"inep": "53005090", "status": "Pendente", "descricao": "Nobreak", "valor": "1.491,72", "indice": 1},
        ]
        with patch("playwright.sync_api.sync_playwright", return_value=self._mock_sync_playwright()), \
                patch("apps.integracoes.eace.login.fazer_login", return_value=True), \
                patch("apps.integracoes.eace.login.selecionar_perfil_fornecedor", return_value=True), \
                patch("apps.integracoes.eace.dashboard.abrir_medicoes", return_value=True), \
                patch("apps.integracoes.eace.dashboard.abrir_osps", return_value=True), \
                patch("apps.integracoes.eace.dashboard.pesquisar_osp", return_value=True), \
                patch("apps.integracoes.eace.dashboard.contar_pedidos_osp", return_value=1), \
                patch("apps.integracoes.eace.dashboard.expandir_resultado_osp", return_value=True), \
                patch("apps.integracoes.eace.dashboard.expandir_notas_fiscais", return_value=True), \
                patch("apps.integracoes.eace.dashboard.extrair_dados_grid", return_value=linhas), \
                patch("apps.integracoes.eace.dashboard.upload_linha") as mock_upload:
            resultado = consultar_pendencias_eace(osp="3905", inep="53005090")

        self.assertTrue(resultado.sucesso)
        self.assertEqual(resultado.linhas, linhas)
        mock_upload.assert_not_called()

    def test_osp_nao_encontrada(self):
        from apps.integracoes.eace.rpa import consultar_pendencias_eace

        with patch("playwright.sync_api.sync_playwright", return_value=self._mock_sync_playwright()), \
                patch("apps.integracoes.eace.login.fazer_login", return_value=True), \
                patch("apps.integracoes.eace.login.selecionar_perfil_fornecedor", return_value=True), \
                patch("apps.integracoes.eace.dashboard.abrir_medicoes", return_value=True), \
                patch("apps.integracoes.eace.dashboard.abrir_osps", return_value=True), \
                patch("apps.integracoes.eace.dashboard.pesquisar_osp", return_value=True), \
                patch("apps.integracoes.eace.dashboard.contar_pedidos_osp", return_value=0):
            resultado = consultar_pendencias_eace(osp="999999999", inep="53005090")

        self.assertFalse(resultado.sucesso)
        self.assertEqual(resultado.motivo, "osp_nao_encontrada")

    def test_credenciais_ausentes(self):
        from apps.integracoes.eace.config import ConfigEace
        from apps.integracoes.eace.rpa import consultar_pendencias_eace

        cfg = ConfigEace(
            url="https://eace.org.br", usuario="", senha="", headless=True, timeout_ms=1000, delay_ms=0,
        )
        resultado = consultar_pendencias_eace(osp="3905", inep="53005090", config=cfg)

        self.assertFalse(resultado.sucesso)
        self.assertEqual(resultado.motivo, "credenciais_ausentes")


class ProgressoRpaEaceTests(SimpleTestCase):
    """Pedido do usuário (2026-09-03): barra de progresso na tela enquanto
    a RPA roda - cobre só a contagem/percentual de `ProgressoRpaEace`,
    isolada do Playwright."""

    def test_avanca_na_ordem_e_calcula_percentual(self):
        from apps.integracoes.eace.rpa import ETAPAS_RPA_EACE, ProgressoRpaEace

        chamadas = []
        progresso = ProgressoRpaEace(lambda etapa, pct: chamadas.append((etapa, pct)))
        for _ in ETAPAS_RPA_EACE:
            progresso.avancar()

        self.assertEqual(len(chamadas), len(ETAPAS_RPA_EACE))
        self.assertEqual(chamadas[0], (ETAPAS_RPA_EACE[0], round(1 / len(ETAPAS_RPA_EACE) * 100)))
        self.assertEqual(chamadas[-1], (ETAPAS_RPA_EACE[-1], 100))

    def test_nao_avanca_alem_do_total_de_etapas(self):
        from apps.integracoes.eace.rpa import ETAPAS_RPA_EACE, ProgressoRpaEace

        chamadas = []
        progresso = ProgressoRpaEace(lambda etapa, pct: chamadas.append((etapa, pct)))
        for _ in range(len(ETAPAS_RPA_EACE) + 5):
            progresso.avancar()

        self.assertEqual(len(chamadas), len(ETAPAS_RPA_EACE))

    def test_sem_callback_nao_faz_nada(self):
        from apps.integracoes.eace.rpa import ProgressoRpaEace

        ProgressoRpaEace(None).avancar()  # não deve levantar exceção

    def test_erro_no_callback_nao_propaga(self):
        from apps.integracoes.eace.rpa import ProgressoRpaEace

        def _quebra(etapa, pct):
            raise RuntimeError("boom")

        ProgressoRpaEace(_quebra).avancar()  # não deve levantar


class EaceAnexarNotaFiscalCommandTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

        self.pdf = tmp_dir / "nota.pdf"
        self.xml = tmp_dir / "nota.xml"
        self.pdf.write_bytes(b"%PDF-fake")
        self.xml.write_text("<xml/>", encoding="utf-8")

        self.base_args = {
            "osp": "12345",
            "inep": "35083938",
            "pdf": str(self.pdf),
            "xml": str(self.xml),
        }

    def _rodar(self, **overrides):
        args = {**self.base_args, **overrides}
        out = StringIO()
        call_command("eace_anexar_nota_fiscal", stdout=out, **args)
        return out.getvalue()

    def test_pdf_inexistente_aborta_sem_chamar_o_rpa(self):
        with patch("apps.ri.management.commands.eace_anexar_nota_fiscal.anexar_nota_fiscal") as mock_rpa:
            with self.assertRaises(CommandError):
                self._rodar(pdf=str(Path(self._tmp.name) / "nao-existe.pdf"))
            mock_rpa.assert_not_called()

    def test_xml_inexistente_aborta_sem_chamar_o_rpa(self):
        with patch("apps.ri.management.commands.eace_anexar_nota_fiscal.anexar_nota_fiscal") as mock_rpa:
            with self.assertRaises(CommandError):
                self._rodar(xml=str(Path(self._tmp.name) / "nao-existe.xml"))
            mock_rpa.assert_not_called()

    def test_sucesso_do_rpa_mostra_dados_extraidos_e_nao_levanta_erro(self):
        resultado = ResultadoRpaEace(
            sucesso=True,
            dados_pdf={"inep": "35083938", "produto": "Kit Cobertura Wi-Fi", "valor": "22.644,43"},
            valor_portal="22.644,43",
        )
        with patch(
            "apps.ri.management.commands.eace_anexar_nota_fiscal.anexar_nota_fiscal",
            return_value=resultado,
        ) as mock_rpa:
            saida = self._rodar()
            mock_rpa.assert_called_once_with(
                osp="12345",
                inep="35083938",
                indice=1,
                caminho_pdf=str(self.pdf),
                caminho_xml=str(self.xml),
            )
            self.assertIn("Kit Cobertura Wi-Fi", saida)
            self.assertIn("22.644,43", saida)
            self.assertIn("OK", saida)

    def test_erro_do_rpa_vira_command_error_com_o_motivo(self):
        resultado = ResultadoRpaEace(
            sucesso=False,
            motivo="valor_divergente",
            dados_pdf={"inep": "35083938", "produto": "Kit", "valor": "1,00"},
            valor_portal="22.644,43",
        )
        with patch(
            "apps.ri.management.commands.eace_anexar_nota_fiscal.anexar_nota_fiscal",
            return_value=resultado,
        ):
            with self.assertRaises(CommandError) as ctx:
                self._rodar()
            self.assertIn("valor_divergente", str(ctx.exception))

    def test_indisponibilidade_do_playwright_vira_command_error(self):
        with patch(
            "apps.ri.management.commands.eace_anexar_nota_fiscal.anexar_nota_fiscal",
            side_effect=RpaEaceIndisponivel("Playwright nao instalado"),
        ):
            with self.assertRaises(CommandError):
                self._rodar()

    def test_indice_customizado_e_repassado_ao_rpa(self):
        with patch(
            "apps.ri.management.commands.eace_anexar_nota_fiscal.anexar_nota_fiscal",
            return_value=ResultadoRpaEace(sucesso=True, dados_pdf={"inep": "1", "produto": "x", "valor": "1"}),
        ) as mock_rpa:
            self._rodar(indice=2)
            self.assertEqual(mock_rpa.call_args.kwargs["indice"], 2)
