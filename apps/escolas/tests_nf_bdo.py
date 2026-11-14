"""NFs do financeiro do BDO no portal EACE (pedido do usuário, 2026-11-13): o .zip do financeiro, a ligação de cada
NFCom ao município do Boletim (município escrito na NF + valor do card), as decisões, a fila e o robô."""
import io
import shutil
import tempfile
import zipfile
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.integracoes.eace.rpa_bdo import extrair_valor_nfcom

from . import nf_bdo
from .models import BoletimBdo, MunicipioBdo, NotaFiscalBdo

User = get_user_model()
_MEDIA_ROOT = tempfile.mkdtemp()


def _texto_nf(numero, valor, liberacao="3657 UF ITOBI/SP"):
    """Trechos do layout real da NFCom do BDO (NF 349 do Boletim 3657)."""
    return (f"DOCUMENTO AUXILIAR DA NOTA FISCAL DE FATURA DE SERVIÇO DE COMUNICAÇÃO ELETRÔNICA\n"
            f"ASSOCIACAO ADMINISTRADORA DA NOTA FISCAL Nº {numero} - SÉRIE: 1\n"
            f"TOTAL A PAGAR: R$ {valor}\nVALOR TOTAL NF {valor} INFORMAÇÃO DOS TRIBUTOS\n"
            f"INFORMAÇÕES COMPLEMENTARES\n"
            + (f"CODIGO DE LIBERACAO {liberacao} VENCIMENTO 08/11/2026 Banco Itau Ag: 1646\n" if liberacao else ""))


def _zip(notas, dentro=()):
    """`notas`: [(numero, valor, liberacao)] -> .zip com 1 "PDF" por NF (o texto, lido pelo patch de ler_texto_pdf);
    `dentro`: as que vão também num .zip dentro do .zip (como o financeiro manda)."""
    def montar(lista):
        saida = io.BytesIO()
        with zipfile.ZipFile(saida, "w") as arquivo:
            for numero, valor, liberacao in lista:
                arquivo.writestr(f"{numero}_09-10-2026_NOME_MEGA INFRA.pdf", _texto_nf(numero, valor, liberacao))
        return saida.getvalue()

    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w") as arquivo:
        for numero, valor, liberacao in notas:
            arquivo.writestr(f"{numero}_09-10-2026_NOME_MEGA INFRA.pdf", _texto_nf(numero, valor, liberacao))
        if dentro:
            arquivo.writestr("348_09-10-2026_NOME_MEGA INFRA.zip", montar(dentro))
    return SimpleUploadedFile("348_09-10-2026_NOME_MEGA INFRA.zip", saida.getvalue())


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
@patch("apps.escolas.nf_bdo.ler_texto_pdf", lambda conteudo: conteudo.decode())
class NfBdoTests(TestCase):

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.analista = User.objects.create_user("nf-bdo", password="x", perfil=User.PERFIL_ANALISTA)
        self.boletim = BoletimBdo.objects.create(numero="3657", tipo="RE")
        self.cards = {}
        for nome, uf, valor, status in (
            ("Itobi", "SP", "6.27", "Pendente"), ("Araguaína", "TO", "1120.20", "Pendente"),
            ("Heitoraí", "GO", "107.60", "Pendente"), ("Cândido Rodrigues", "SP", "246.27", "Pendente"),
            ("Chapada da Natividade", "TO", "796.53", "Pendente"), ("Abadiânia", "GO", "366.60", "Pendente"),
            ("Santa Bárbara d'Oeste", "SP", "114.27", "Pendente"), ("Santo André", "SP", "11518.27", "Pendente"),
            ("Caldas Novas", "GO", "529.93", "Aprovado"),
        ):
            self.cards[nome] = MunicipioBdo.objects.create(
                boletim=self.boletim, municipio=nome, uf=uf, valor_total=Decimal(valor), valor_eace=Decimal(valor),
                status_eace=status)

    def _situacoes(self):
        return {n.numero_nf: (n.situacao, n.municipio_bdo.municipio if n.municipio_bdo else None)
                for n in NotaFiscalBdo.objects.all()}

    def test_le_o_layout_da_nfcom(self):
        dados = nf_bdo.ler_nf(_texto_nf("359", "1.120,20", "3657 UF ARAGUAINA/TO"))
        self.assertEqual(dados, {"numero": "359", "valor": Decimal("1120.20"), "boletim": "3657",
                                 "municipio": "ARAGUAINA", "uf": "TO"})
        self.assertEqual(extrair_valor_nfcom(_texto_nf("359", "1.120,20")), "1.120,20")

    def test_liga_pelo_municipio_e_valor_e_para_o_que_nao_concorda(self):
        remessa = nf_bdo.processar_remessa(_zip([
            ("349", "6,27", "3657 UF ITOBI/SP"),
            ("359", "1.120,20", "3657 UF ARAGUAINA/TO"),
            ("361", "796,53", "3657 UF CHAPADA DA NATVIDADE/TO"),  # erro de digitacao
            ("356", "366,60", "3657 UF LENCOIS ABADIANIA/GO"),  # lixo antes do nome
            ("362", "114,27", "3657 UF SANTA BARBARA DOESTE/SP"),  # sem apostrofo
            ("218", "246,27", "3657 UF HEITORAI/GO"),  # municipio trocado: o valor e o de Candido Rodrigues
            ("205", "11.518,27", None),  # sem o codigo: o valor so bate com Santo Andre
            ("400", "529,93", "3657 UF CALDAS NOVAS/GO"),  # card ja Aprovado no portal
            ("500", "10,00", "9999 UF ITOBI/SP"),  # Boletim nao importado
        ], dentro=[("349", "6,27", "3657 UF ITOBI/SP")]), self.analista)
        self.assertEqual(remessa.resumo["pdfs"], 9)  # a NF repetida no .zip de dentro conta 1
        situacoes = self._situacoes()
        for numero, municipio in (("349", "Itobi"), ("359", "Araguaína"), ("361", "Chapada da Natividade"),
                                  ("356", "Abadiânia"), ("362", "Santa Bárbara d'Oeste")):
            self.assertEqual(situacoes[numero], ("pronta", municipio))
        self.assertEqual(situacoes["218"], ("divergente", "Heitoraí"))
        nota = NotaFiscalBdo.objects.get(numero_nf="218")
        self.assertIn("O valor bate com o card de Cândido Rodrigues/SP", nota.motivo)
        self.assertEqual(situacoes["205"], ("divergente", "Santo André"))
        self.assertEqual(situacoes["400"], ("ja_no_portal", "Caldas Novas"))
        self.assertEqual(situacoes["500"], ("fora_do_boletim", None))

    def test_decidir_fila_robo_e_baixa_do_municipio(self):
        nf_bdo.processar_remessa(_zip([("349", "6,27", "3657 UF ITOBI/SP"), ("218", "246,27", "3657 UF HEITORAI/GO")]))
        divergente = NotaFiscalBdo.objects.get(numero_nf="218")
        nf_bdo.decidir_nota(divergente, self.cards["Cândido Rodrigues"].pk, self.analista)
        divergente.refresh_from_db()
        self.assertEqual((divergente.situacao, divergente.ligada_por), ("pronta", "manual"))
        with self.assertRaisesMessage(ValueError, "Itobi/SP já tem a NF 349"):
            nf_bdo.decidir_nota(divergente, self.cards["Itobi"].pk, self.analista)
        self.assertEqual(nf_bdo.enfileirar_notas(self.boletim, self.analista), 2)

        chamadas = []

        def robo(**kwargs):
            chamadas.append((kwargs["pedido"], kwargs["municipio"], kwargs["uf"]))
            if kwargs["municipio"] == "Itobi":
                return SimpleNamespace(sucesso=True, motivo=None, status_portal="NF anexada")
            return SimpleNamespace(sucesso=False, motivo="valor_divergente", status_portal="Pendente")

        with patch("apps.integracoes.eace.rpa_bdo.anexar_pdf_bdo", robo):
            self.assertEqual(nf_bdo.processar_proximo_envio_nf_bdo().numero_nf, "349")
            nf_bdo.processar_proximo_envio_nf_bdo()
            self.assertIsNone(nf_bdo.processar_proximo_envio_nf_bdo())
        self.assertEqual(chamadas, [("3657", "Itobi", "SP"), ("3657", "Cândido Rodrigues", "SP")])
        self.assertEqual(self._situacoes(), {"349": ("anexada", "Itobi"), "218": ("erro", "Cândido Rodrigues")})
        self.cards["Itobi"].refresh_from_db()
        self.assertEqual((self.cards["Itobi"].status_eace, self.cards["Itobi"].arquivo_nf_eace),
                         ("NF anexada", "349_09-10-2026_NOME_MEGA INFRA.pdf"))
        # enviar de novo a que deu erro
        erro = NotaFiscalBdo.objects.get(numero_nf="218")
        self.assertEqual(nf_bdo.enfileirar_notas(self.boletim, self.analista, [erro.pk]), 1)
        # a mesma remessa de novo: a anexada fica de fora, nada duplica
        remessa = nf_bdo.processar_remessa(_zip([("349", "6,27", "3657 UF ITOBI/SP")]))
        self.assertEqual((remessa.resumo["ja_enviadas"], NotaFiscalBdo.objects.filter(numero_nf="349").count()), (1, 1))

    def test_tela_envia_o_zip_decide_e_coloca_na_fila(self):
        self.client.force_login(self.analista)
        resposta = self.client.post(reverse("bdo_nf_remessa"), {"arquivo": _zip([
            ("349", "6,27", "3657 UF ITOBI/SP"), ("218", "246,27", "3657 UF HEITORAI/GO")])}, follow=True)
        pagina = resposta.content.decode()
        self.assertIn("2 NF(s) lida(s)", pagina)
        self.assertIn("NFs do financeiro no portal EACE — Boletim 3657", pagina)
        self.assertIn("1 para decidir", pagina)
        self.assertIn("O valor bate com o card de Cândido Rodrigues/SP", pagina)
        nota = NotaFiscalBdo.objects.get(numero_nf="218")
        self.client.post(reverse("bdo_nf_decidir", args=[nota.pk]), {"municipio": "descartar"})
        nota.refresh_from_db()
        self.assertEqual(nota.situacao, "descartada")
        resposta = self.client.post(reverse("bdo_nf_enfileirar", args=[self.boletim.pk]), follow=True)
        self.assertContains(resposta, "1 NF(s) do Boletim 3657 na fila do robô do portal EACE.")
        painel = {e["nome"]: e["texto"] for e in resposta.context["painel"]["etapas"]}
        self.assertEqual(painel["NFs no portal"], "1 de 9 município(s) com NF no portal, 1 na fila")

    def test_visualizador_nao_envia_e_arquivo_invalido(self):
        visualizador = User.objects.create_user("nf-bdo-vis", password="x", perfil=User.PERFIL_VISUALIZADOR)
        self.client.force_login(visualizador)
        self.assertNotEqual(self.client.post(reverse("bdo_nf_remessa"), {"arquivo": _zip([])}).status_code, 200)
        self.client.force_login(self.analista)
        resposta = self.client.post(reverse("bdo_nf_remessa"),
                                    {"arquivo": SimpleUploadedFile("nfs.pdf", b"%PDF")}, follow=True)
        self.assertContains(resposta, "NFs não lidas: Envie o arquivo do financeiro em .zip ou .rar.")
        self.assertFalse(NotaFiscalBdo.objects.exists())


@override_settings(MEDIA_ROOT=_MEDIA_ROOT, FILA_TV_TOKEN="tv-teste")
class NfBdoNaFilaETvTests(TestCase):
    """As NFs do BDO aparecem na tela Projeto > Fila e no painel da TV, junto com RI e MIP (pedido do usuário,
    2026-11-13: "tanto o MIP como o BDO tem que aparecer para ver os robôs trabalhando")."""

    def setUp(self):
        self.boletim = BoletimBdo.objects.create(numero="3657", tipo="RE")
        MunicipioBdo.objects.create(boletim=self.boletim, municipio="Itobi", uf="SP", valor_total=Decimal("6.27"),
                                    valor_eace=Decimal("6.27"), status_eace="Pendente")
        with patch("apps.escolas.nf_bdo.ler_texto_pdf", lambda conteudo: conteudo.decode()):
            nf_bdo.processar_remessa(_zip([("349", "6,27", "3657 UF ITOBI/SP")]))
        nf_bdo.enfileirar_notas(self.boletim, None)

    def test_fila_e_tv_mostram_a_nf_do_bdo(self):
        from apps.ri.views_fila_tv import contexto_fila_tv

        self.client.force_login(User.objects.create_user("fila-bdo", password="x", perfil=User.PERFIL_ANALISTA))
        resposta = self.client.get(reverse("fila_rpa_eace"))
        self.assertContains(resposta, "Envios do BDO")
        self.assertContains(resposta, "Boletim 3657")
        self.assertEqual(resposta.context["total_na_fila"], 1)
        contexto = contexto_fila_tv()
        self.assertEqual([(i["tipo"], i["nome"]) for i in contexto["proximos"]], [("BDO", "Itobi/SP")])
        self.assertEqual(contexto["total_na_fila"], 1)
        pagina = self.client.get(reverse("fila_tv", args=["tv-teste"])).content.decode()
        self.assertIn("etq-bdo", pagina)
