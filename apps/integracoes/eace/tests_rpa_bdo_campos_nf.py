"""Modal "Enviar nota fiscal" do BDO (correção 2026-11-17): o cliente devolveu NFs enviadas com campos em branco -
o RPA confirmava antes de o portal terminar de preencher. Testa num Chromium de verdade com uma página que imita o
modal (campos preenchidos com atraso, Descrição em branco e um "Descrição" na página de fundo)."""

from unittest import SkipTest

from django.test import SimpleTestCase

from .rpa_bdo import DESCRICAO_PADRAO_BDO_RE, aguardar_campos_nf_bdo, campo_nf_preenchido

PAGINA_MODAL = """<!doctype html><html><body>
<table><tr><th>Descrição</th><th>Valor</th></tr><tr><td>LINK DE DADOS</td><td><input value="fundo"></td></tr></table>
<div class="modal"><h2>Enviar nota fiscal - 3851</h2>
  <div class="form">
    <div><label>CNPJ Fornecedor</label><p>MEGA INFRA</p><input value="07.525.262/0004-61"></div>
    <div><label>Data emissão NF</label><input id="data"></div>
    <div class="linha">
      <div><label>Número da Nota fiscal <small>(somente números)</small></label><input id="numero"></div>
      <div><label>Valor a ser medido</label><input id="medido" value="R$0,00"></div>
    </div>
    <div><label>Valor bruto da nota</label><input id="bruto"></div>
    <div><label>Estado</label><input value="São Paulo"></div>
    <div><label>Descrição</label><textarea id="descricao" placeholder="Descrição">%(descricao)s</textarea></div>
    <button>Confirmar informações</button>
  </div>
</div>
<script>
  if (%(preencher)s) setTimeout(() => {
    document.getElementById('data').value = '14/11/2026';
    document.getElementById('numero').value = '645';
    document.getElementById('medido').value = 'R$1.043,54';
    document.getElementById('bruto').value = 'R$1.043,54';
  }, 800);
</script>
</body></html>"""


class CampoPreenchidoTests(SimpleTestCase):

    def test_vazio_e_zero_nao_contam(self):
        for valor in (None, "", "  ", "R$0,00", "R$ 0,00", "0"):
            self.assertFalse(campo_nf_preenchido(valor), valor)
        for valor in ("14/11/2026", "2026-11-14", "R$1.043,54", "645"):
            self.assertTrue(campo_nf_preenchido(valor), valor)


class AguardarCamposNfBdoTests(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        try:
            from playwright.sync_api import sync_playwright

            cls._pw = sync_playwright().start()
            cls._navegador = cls._pw.chromium.launch()
        except Exception as exc:  # ambiente sem Playwright/Chromium
            raise SkipTest(f"Chromium indisponível: {exc}")

    @classmethod
    def tearDownClass(cls):
        cls._navegador.close()
        cls._pw.stop()
        super().tearDownClass()

    def _modal(self, preencher=True, descricao=""):
        pagina = self._navegador.new_page()
        self.addCleanup(pagina.close)
        pagina.set_content(PAGINA_MODAL % {"preencher": "true" if preencher else "false", "descricao": descricao})
        return pagina

    def _aguardar(self, pagina, descricao_padrao, timeout_ms=10_000, espera_minima_ms=0):
        return aguardar_campos_nf_bdo(pagina, descricao_padrao, timeout_ms=timeout_ms, intervalo_ms=200,
                                      espera_descricao_ms=400, espera_minima_ms=espera_minima_ms)

    def test_bdo_re_espera_os_campos_e_preenche_a_descricao(self):
        pagina = self._modal()
        self.assertIsNone(self._aguardar(pagina, DESCRICAO_PADRAO_BDO_RE))
        self.assertEqual(pagina.input_value("#descricao"), "MENSALIDADE ASSINATURA DE ACESSO BDO RE")
        self.assertEqual(pagina.input_value("#bruto"), "R$1.043,54")  # só confirmaria depois de preenchido
        self.assertEqual(pagina.get_attribute("#medido", "data-rpa-bdo-campo"), "1")

    def test_espera_o_minimo_mesmo_com_os_campos_ja_preenchidos(self):
        import time

        pagina = self._modal()
        inicio = time.monotonic()
        self.assertIsNone(self._aguardar(pagina, DESCRICAO_PADRAO_BDO_RE, espera_minima_ms=3_000))
        self.assertGreaterEqual(time.monotonic() - inicio, 3)

    def test_bdo_ri_com_descricao_em_branco_nao_confirma(self):
        pagina = self._modal()
        self.assertEqual(self._aguardar(pagina, None), "descricao_em_branco")
        self.assertEqual(pagina.input_value("#descricao"), "")

    def test_descricao_do_portal_e_mantida(self):
        pagina = self._modal(descricao="LINK DE DADOS EACE")
        self.assertIsNone(self._aguardar(pagina, DESCRICAO_PADRAO_BDO_RE))
        self.assertEqual(pagina.input_value("#descricao"), "LINK DE DADOS EACE")

    def test_portal_nao_preenche_os_campos(self):
        pagina = self._modal(preencher=False)
        self.assertEqual(self._aguardar(pagina, DESCRICAO_PADRAO_BDO_RE, timeout_ms=1_000), "campos_nf_em_branco")
        self.assertEqual(pagina.input_value("#descricao"), "")


PAGINA_CARD_REPROVADO = """<!doctype html><html><body>
<div data-rpa-mip-municipio="0">Município: Pacaembu/SP Status: Reprovado
  <input type="file" id="arquivo" style="display:none">
  <button id="reenviar" onclick="window.reenviou = true">Reenviar nota</button>
</div>
<div id="modal" style="display:none"><h2>Enviar nota fiscal - 3851</h2>
  <div><label>Data emissão NF</label><input id="data"></div>
  <div><label>Valor a ser medido</label><input id="medido"></div>
  <div><label>Valor bruto da nota</label><input id="bruto"></div>
  <div><label>Descrição</label><textarea id="descricao"></textarea></div>
  <button id="confirmar">Confirmar informações</button>
</div>
<script>
  document.getElementById('arquivo').addEventListener('change', () => {
    document.getElementById('modal').style.display = 'block';
    setTimeout(() => {
      document.getElementById('data').value = '13/11/2026';
      document.getElementById('medido').value = 'R$707,54';
      document.getElementById('bruto').value = 'R$707,54';
    }, 700);
  });
  // como o portal: só aceita com a Descrição digitada
  document.getElementById('confirmar').addEventListener('click', () => {
    if (document.getElementById('descricao').value) document.getElementById('modal').style.display = 'none';
  });
</script>
</body></html>"""


class AnexarNoCardReprovadoTests(AguardarCamposNfBdoTests):
    """Fluxo do card Reprovado conferido no portal (Boletim 3851, 2026-11-17): campo de arquivo escondido,
    modal, Descrição digitada, "Confirmar informações" e depois "Reenviar nota"."""

    def test_anexa_confirma_e_reenvia(self):
        import tempfile

        from unittest.mock import patch

        from .rpa_bdo import anexar_pdf_no_card_bdo

        pdf = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        pdf.write(b"%PDF-1.4")
        pdf.close()
        pagina = self._navegador.new_page()
        self.addCleanup(pagina.close)
        pagina.set_content(PAGINA_CARD_REPROVADO)
        with patch("apps.integracoes.eace.rpa_bdo.aguardar_campos_nf_bdo",
                   side_effect=lambda p, d: self._aguardar(p, d)):
            self.assertIsNone(anexar_pdf_no_card_bdo(pagina, 0, pdf.name, DESCRICAO_PADRAO_BDO_RE))
        self.assertEqual(pagina.input_value("#descricao"), DESCRICAO_PADRAO_BDO_RE)
        self.assertFalse(pagina.is_visible("#modal"))
        self.assertTrue(pagina.evaluate("window.reenviou === true"))

    # os testes herdados do modal não precisam rodar de novo aqui
    test_bdo_re_espera_os_campos_e_preenche_a_descricao = None
    test_bdo_ri_com_descricao_em_branco_nao_confirma = None
    test_descricao_do_portal_e_mantida = None
    test_portal_nao_preenche_os_campos = None
    test_espera_o_minimo_mesmo_com_os_campos_ja_preenchidos = None
