"""NF-e canceladas no Módulo Financeiro (pedido do usuário, 2026-11-12): API de entrada, tela "NFs canceladas no
financeiro" com "Dar baixa" e o efeito da baixa no relatório "Faturamento EACE Materiais (NOVO)"."""
import json
import shutil
import tempfile
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.auditoria.models import Auditoria
from apps.escolas.models import Escola

from .models import Documento, NfCanceladaFinanceiro, Ri, RiHistorico
from .services import ler_dados_xml_nf, montar_relatorio_faturamento_eace_materiais_novo
from .tests_relatorio_faturamento_novo import _quando, _xml_nf

User = get_user_model()
_MEDIA_ROOT = tempfile.mkdtemp()
TOKEN = "token-teste-nfs-canceladas"
URL_API = "/api/financeiro/nfs-canceladas/"
CHAVE_KIT = "35261112345678000199550010000034711000034719"
CHAVE_NOBREAK = "35261112345678000199550010000034721000034720"


def _xml_com_chave(numero, valor, item_lpu, chave):
    xml = _xml_nf(numero, valor, item_lpu).decode()
    if chave:
        xml = xml.replace("<protNFe><infProt>", f"<protNFe><infProt><chNFe>{chave}</chNFe>")
    return xml.encode()


def _receber(ri, notas, recebido_em):
    """1 resposta do financeiro por e-mail com o XML de cada NF. `notas`: [(numero, valor, item_lpu, chave)]."""
    documentos = [
        Documento.objects.create(ri=ri, tipo=Documento.XML, recebido_em=recebido_em,
                                 arquivo=ContentFile(_xml_com_chave(numero, valor, item, chave),
                                                     f"{numero}_10-11-2026_NOME_MEGA_INFRA.xml"))
        for numero, valor, item, chave in notas
    ]
    entrada = RiHistorico.objects.create(ri=ri, tipo=RiHistorico.EMAIL, mensagem="Resposta do financeiro.")
    entrada.documentos.set(documentos)
    RiHistorico.objects.filter(pk=entrada.pk).update(criado_em=recebido_em)


def _montar():
    return montar_relatorio_faturamento_eace_materiais_novo(date(2026, 11, 10), date(2026, 11, 11))


def _corpo(**extra):
    corpo = {"id_financeiro": "454-0", "numero_nf": "3471", "serie": "1", "chave": CHAVE_KIT, "inep": "52039412",
             "escola": "COLEGIO TESTE", "item": "NF KIT", "valor": "25330.63",
             "cancelada_em": "2026-11-12T18:00:00-03:00", "cancelada_por": "Hilber Lustosa", "motivo": "CFOP errado",
             "email_financeiro": 216, "assunto": "#RI-1 - Faturamento EACE"}
    corpo.update(extra)
    return corpo


@override_settings(FINANCEIRO_API_TOKEN=TOKEN)
class ApiNfsCanceladasTests(TestCase):

    def setUp(self):
        self.escola = Escola.objects.create(inep="52039412", nome="Colegio Teste", estado="GO")
        self.ri = Ri.objects.create(escola=self.escola, status=Ri.FATURAMENTO_RI_CONCLUIDO)

    def _post(self, corpo, token=TOKEN):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
        return self.client.post(URL_API, data=json.dumps(corpo), content_type="application/json", **headers)

    def test_url_final(self):
        self.assertEqual(reverse("api_financeiro_nfs_canceladas"), URL_API)

    def test_sem_token_ou_token_errado_recusa(self):
        self.assertEqual(self._post(_corpo(), token="").status_code, 401)
        self.assertEqual(self._post(_corpo(), token="errado").status_code, 401)
        self.assertFalse(NfCanceladaFinanceiro.objects.exists())

    @override_settings(FINANCEIRO_API_TOKEN="")
    def test_token_vazio_desliga_a_api(self):
        self.assertEqual(self._post(_corpo()).status_code, 503)
        self.assertEqual(self.client.get(URL_API, {"ids": "454-0"}).status_code, 503)

    def test_post_cria_com_os_dados_e_vincula_o_ri(self):
        resp = self._post(_corpo())
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json(), {"id_financeiro": "454-0", "status": "pendente", "baixada_em": None,
                                       "baixada_por": ""})
        nf = NfCanceladaFinanceiro.objects.get()
        self.assertEqual((nf.numero_nf, nf.serie, nf.chave, nf.inep, nf.valor, nf.email_financeiro, nf.ri),
                         ("3471", "1", CHAVE_KIT, "52039412", Decimal("25330.63"), 216, self.ri))
        self.assertEqual(nf.cancelada_em.isoformat(), "2026-11-12T21:00:00+00:00")

    def test_post_sem_ri_do_inep_grava_sem_vinculo(self):
        resp = self._post(_corpo(id_financeiro="9-0", inep="99999999", chave=""))
        self.assertEqual(resp.status_code, 201)
        self.assertIsNone(NfCanceladaFinanceiro.objects.get().ri)

    def test_post_repetido_atualiza_sem_duplicar_e_mantem_a_baixa(self):
        self._post(_corpo())
        resp = self._post(_corpo(motivo="Valor errado"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(NfCanceladaFinanceiro.objects.count(), 1)
        self.assertEqual(NfCanceladaFinanceiro.objects.get().motivo, "Valor errado")

        usuario = User.objects.create_user(username="baixa", password="x", first_name="Maria", last_name="Silva")
        NfCanceladaFinanceiro.objects.update(baixada_por=usuario, baixada_em=_quando(12, 19))
        resp = self._post(_corpo())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "baixada")
        self.assertEqual(resp.json()["baixada_por"], "Maria Silva")
        self.assertTrue(resp.json()["baixada_em"].startswith("2026-11-12T19:00:00"))

    def test_validacao(self):
        for corpo, trecho in (
            ({**_corpo(), "id_financeiro": ""}, "id_financeiro"),
            ({k: v for k, v in _corpo().items() if k != "numero_nf"}, "numero_nf"),
            ({**_corpo(), "inep": None}, "inep"),
            (_corpo(chave="123"), "Chave"),
            (_corpo(valor="abc"), "Valor"),
            (_corpo(cancelada_em="ontem"), "cancelamento"),
            ([1, 2], "JSON"),
        ):
            resp = self._post(corpo)
            self.assertEqual(resp.status_code, 400, corpo)
            self.assertIn(trecho, resp.json()["erro"])
        resp = self.client.post(URL_API, data="{nao json", content_type="application/json",
                                HTTP_AUTHORIZATION=f"Bearer {TOKEN}")
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(NfCanceladaFinanceiro.objects.exists())

    def test_get_status_por_ids(self):
        self._post(_corpo())
        self._post(_corpo(id_financeiro="455-0", numero_nf="3472", chave=""))
        NfCanceladaFinanceiro.objects.filter(id_financeiro="455-0").update(baixada_em=_quando(12, 19))
        resp = self.client.get(URL_API, {"ids": "454-0, 455-0,desconhecido"}, HTTP_AUTHORIZATION=f"Bearer {TOKEN}")
        self.assertEqual(resp.status_code, 200)
        resultados = {r["id_financeiro"]: r for r in resp.json()["resultados"]}
        self.assertEqual(set(resultados), {"454-0", "455-0"})
        self.assertEqual(resultados["454-0"]["status"], "pendente")
        self.assertEqual(resultados["455-0"]["status"], "baixada")
        self.assertEqual(resultados["455-0"]["baixada_por"], "")

    def test_metodo_nao_permitido(self):
        resp = self.client.delete(URL_API, HTTP_AUTHORIZATION=f"Bearer {TOKEN}")
        self.assertEqual(resp.status_code, 405)


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class BaixaTiraNfDoRelatorioNovoTests(TestCase):

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.escola = Escola.objects.create(inep="52039412", nome="Colegio Teste", estado="GO")
        self.ri = Ri.objects.create(escola=self.escola, status=Ri.FATURAMENTO_RI_CONCLUIDO)
        self.admin = User.objects.create_user(username="admin-canc", password="x", perfil=User.PERFIL_ADMINISTRADOR)

    def _cancelada(self, **campos):
        dados = {"id_financeiro": "454-0", "numero_nf": "3471", "chave": CHAVE_KIT, "inep": "52039412"}
        dados.update(campos)
        return NfCanceladaFinanceiro.objects.create(**dados)

    def _baixar(self, nf):
        self.client.force_login(self.admin)
        return self.client.post(reverse("nf_cancelada_financeiro_baixar", args=[nf.pk]))

    def test_conta_antes_da_baixa_e_sai_depois_pela_chave(self):
        _receber(self.ri, [("3471", "25330.63", "KIT 10", CHAVE_KIT),
                           ("3472", "1551.93", "Nobreak", CHAVE_NOBREAK)], _quando(10))
        nf = self._cancelada()
        linhas = _montar()
        self.assertEqual([l["nota_fiscal"] for l in linhas], ["3471", "3472"])
        self.assertEqual(sum(l["valor"] for l in linhas), Decimal("26882.56"))

        self._baixar(nf)
        linhas = _montar()
        self.assertEqual([l["nota_fiscal"] for l in linhas], ["3472"])
        self.assertEqual(sum(l["valor"] for l in linhas), Decimal("1551.93"))

    def test_chave_diferente_nao_tira_mesmo_com_o_mesmo_numero(self):
        _receber(self.ri, [("3471", "25330.63", "KIT 10", CHAVE_KIT)], _quando(10))
        self._baixar(self._cancelada(chave=CHAVE_NOBREAK))
        self.assertEqual([l["nota_fiscal"] for l in _montar()], ["3471"])

    def test_sem_chave_identifica_pelo_numero_e_inep(self):
        _receber(self.ri, [("3471", "25330.63", "KIT 10", ""), ("3472", "1551.93", "Nobreak", "")], _quando(10))
        nf = self._cancelada(chave="", numero_nf="03471")
        outro_inep = self._cancelada(id_financeiro="500-0", chave="", numero_nf="3472", inep="11111111")
        self.assertEqual(len(_montar()), 2)
        self._baixar(nf)
        self._baixar(outro_inep)  # mesmo número, outro INEP: não mexe neste
        self.assertEqual([l["nota_fiscal"] for l in _montar()], ["3472"])

    def test_nf_com_chave_e_xml_sem_chave_usa_numero_e_inep(self):
        _receber(self.ri, [("3471", "25330.63", "KIT 10", "")], _quando(10))
        self._baixar(self._cancelada())
        self.assertEqual(_montar(), [])

    def test_le_a_chave_do_xml(self):
        self.assertEqual(ler_dados_xml_nf(_xml_com_chave("1", "2.00", "Rack", CHAVE_KIT))["chave"], CHAVE_KIT)
        xml_sem_protocolo = f'<NFe><infNFe versao="4.00" Id="NFe{CHAVE_NOBREAK}"><ide><nNF>1</nNF></ide></infNFe></NFe>'
        self.assertEqual(ler_dados_xml_nf(xml_sem_protocolo)["chave"], CHAVE_NOBREAK)
        self.assertEqual(ler_dados_xml_nf(b"<nfeProc></nfeProc>")["chave"], "")

    def test_cache_antigo_sem_chave_e_relido(self):
        _receber(self.ri, [("3471", "25330.63", "KIT 10", CHAVE_KIT)], _quando(10))
        Documento.objects.update(dados_nf_lidos={"versao": 1, "numero_nf": "3471", "valor": "25330.63",
                                                 "data_nf": "2026-11-10", "autorizada_em": "", "item_lpu": "KIT 10",
                                                 "processo": "especial"})
        self._baixar(self._cancelada())
        self.assertEqual(_montar(), [])
        self.assertEqual(Documento.objects.get().dados_nf_lidos["chave"], CHAVE_KIT)


class TelaNfsCanceladasTests(TestCase):

    def setUp(self):
        self.admin = User.objects.create_user(username="admin-tela", password="x", perfil=User.PERFIL_ADMINISTRADOR,
                                              first_name="Ana", last_name="Admin")
        self.analista = User.objects.create_user(username="analista-tela", password="x",
                                                 perfil=User.PERFIL_ANALISTA)
        escola = Escola.objects.create(inep="52039412", nome="Colegio Teste", estado="GO")
        self.ri = Ri.objects.create(escola=escola, status=Ri.FATURAMENTO_RI_CONCLUIDO)
        self.pendente = NfCanceladaFinanceiro.objects.create(
            id_financeiro="454-0", numero_nf="3471", inep="52039412", escola="COLEGIO TESTE", ri=self.ri,
            motivo="CFOP errado", valor=Decimal("25330.63"), email_financeiro=216)
        self.baixada = NfCanceladaFinanceiro.objects.create(
            id_financeiro="455-0", numero_nf="3999", inep="35000001", escola="ESCOLA OUTRA",
            baixada_em=_quando(11, 15), baixada_por=self.admin)
        self.url = reverse("nfs_canceladas_financeiro")

    def _numeros(self, resp):
        return [nf.numero_nf for nf in resp.context["pagina"].object_list]

    def test_padrao_lista_so_as_aguardando_baixa(self):
        self.client.force_login(self.admin)
        resp = self.client.get(self.url)
        self.assertEqual(self._numeros(resp), ["3471"])
        self.assertContains(resp, "Dar baixa")
        self.assertContains(resp, "data-confirmar")
        self.assertContains(resp, "CFOP errado")

    def test_filtro_por_status_e_busca(self):
        self.client.force_login(self.admin)
        resp = self.client.get(self.url, {"status": "baixadas"})
        self.assertEqual(self._numeros(resp), ["3999"])
        self.assertContains(resp, "Baixada por Ana Admin em 11/11/2026 15:00")
        self.assertEqual(sorted(self._numeros(self.client.get(self.url, {"status": "todas"}))), ["3471", "3999"])
        self.assertEqual(self._numeros(self.client.get(self.url, {"status": "todas", "q": "outra"})), ["3999"])
        self.assertEqual(self._numeros(self.client.get(self.url, {"status": "todas", "q": "52039412"})), ["3471"])
        self.assertEqual(self._numeros(self.client.get(self.url, {"status": "todas", "q": "3999"})), ["3999"])

    def test_dar_baixa_grava_quem_e_quando_historico_e_auditoria(self):
        self.client.force_login(self.admin)
        voltar = f"{self.url}?status=todas"
        resp = self.client.post(reverse("nf_cancelada_financeiro_baixar", args=[self.pendente.pk]), {"next": voltar})
        self.assertRedirects(resp, voltar)
        self.pendente.refresh_from_db()
        self.assertEqual(self.pendente.baixada_por, self.admin)
        self.assertIsNotNone(self.pendente.baixada_em)
        self.assertTrue(RiHistorico.objects.filter(ri=self.ri, autor=self.admin,
                                                   mensagem__contains="NF 3471").exists())
        self.assertTrue(Auditoria.objects.filter(entidade="NfCanceladaFinanceiro",
                                                 entidade_id=self.pendente.pk).exists())

    def test_dar_baixa_de_novo_nao_muda_quem_baixou(self):
        outro_admin = User.objects.create_user(username="admin-2", password="x", perfil=User.PERFIL_ADMINISTRADOR)
        self.client.force_login(outro_admin)
        self.client.post(reverse("nf_cancelada_financeiro_baixar", args=[self.baixada.pk]))
        self.baixada.refresh_from_db()
        self.assertEqual(self.baixada.baixada_por, self.admin)

    def test_dar_baixa_so_por_post_e_next_externo_ignorado(self):
        self.client.force_login(self.admin)
        url_baixa = reverse("nf_cancelada_financeiro_baixar", args=[self.pendente.pk])
        self.assertEqual(self.client.get(url_baixa).status_code, 405)
        resp = self.client.post(url_baixa, {"next": "https://externo.example.com/"})
        self.assertRedirects(resp, self.url)

    def test_analista_nao_ve_nem_da_baixa(self):
        self.client.force_login(self.analista)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        resp = self.client.post(reverse("nf_cancelada_financeiro_baixar", args=[self.pendente.pk]))
        self.assertEqual(resp.status_code, 403)
        self.pendente.refresh_from_db()
        self.assertIsNone(self.pendente.baixada_em)

    def test_link_no_menu_do_administrador(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("relatorio_administrador"))
        self.assertContains(resp, self.url)
        self.assertContains(resp, "NFs canceladas no financeiro")


class BaixaEmLoteTests(TestCase):
    """Baixa em várias NFs de uma vez (pedido do usuário, 2026-11-13)."""

    def setUp(self):
        TelaNfsCanceladasTests.setUp(self)
        self.segunda = NfCanceladaFinanceiro.objects.create(
            id_financeiro="456-0", numero_nf="3472", inep="52039412", escola="COLEGIO TESTE", ri=self.ri)
        self.url_lote = reverse("nfs_canceladas_financeiro_baixar_lote")

    def test_tela_tem_caixas_so_nas_aguardando_baixa(self):
        self.client.force_login(self.admin)
        resp = self.client.get(self.url, {"status": "todas"})
        self.assertContains(resp, 'id="form-baixa-lote"')
        self.assertContains(resp, 'form="form-baixa-lote"', count=2)
        self.assertContains(resp, 'data-baixa-lote-nf="3471"')
        self.assertNotContains(resp, 'data-baixa-lote-nf="3999"')
        self.assertNotContains(self.client.get(self.url, {"status": "baixadas"}), 'id="form-baixa-lote"')

    def test_baixa_as_marcadas_com_historico_e_auditoria_de_cada_uma(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self.url_lote, {"nfs": [self.pendente.pk, self.segunda.pk, self.baixada.pk],
                                                "next": self.url}, follow=True)
        self.assertContains(resp, "Baixa dada em 2 NFs (3471, 3472)")
        self.assertContains(resp, "1 NF já estava baixada.")
        for nf in (self.pendente, self.segunda):
            nf.refresh_from_db()
            self.assertEqual(nf.baixada_por, self.admin)
            self.assertTrue(Auditoria.objects.filter(entidade="NfCanceladaFinanceiro", entidade_id=nf.pk).exists())
        self.assertEqual(RiHistorico.objects.filter(ri=self.ri, mensagem__startswith="Baixa da NF").count(), 2)
        self.baixada.refresh_from_db()
        self.assertEqual(self.baixada.baixada_por, self.admin)

    def test_sem_nf_marcada_nao_faz_nada(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self.url_lote, {"next": self.url}, follow=True)
        self.assertContains(resp, "Marque pelo menos uma NF")
        self.pendente.refresh_from_db()
        self.assertIsNone(self.pendente.baixada_em)

    def test_analista_nao_da_baixa_em_lote(self):
        self.client.force_login(self.analista)
        self.assertEqual(self.client.post(self.url_lote, {"nfs": [self.pendente.pk]}).status_code, 403)
        self.assertEqual(self.client.get(self.url_lote).status_code, 405)
        self.pendente.refresh_from_db()
        self.assertIsNone(self.pendente.baixada_em)

    def test_icone_da_aba(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(self.url), 'rel="icon" type="image/svg+xml"')
