"""Relatório "Faturamento EACE Materiais (NOVO)" a partir das NF-e recebidas
do financeiro (correção pedida pelo usuário em 2026-11-11): o total do
período tem que ser o mesmo do Relatório do modulo-financeiro filtrado pela
autorização da NF-e - valor, data e processo vêm do XML da NF, nunca do
Lado Relatório EACE nem do catálogo."""
import os
import shutil
import tempfile
import zipfile
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

import openpyxl
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.escolas.models import Escola

from .models import Documento, LogRpaEace, Ri, RiHistorico, RiItemRelatorioEace
from .services import (
    gerar_planilha_relatorio_faturamento_eace_materiais_novo,
    ler_dados_xml_nf,
    montar_relatorio_faturamento_eace_materiais_novo,
)

User = get_user_model()
_MEDIA_ROOT = tempfile.mkdtemp()

ESPECIAL, CLASSICO = "18", "90"


def _xml_nf(numero, valor, item_lpu, forma_pagamento=ESPECIAL, autorizada_em="2026-11-10T10:00:00-03:00"):
    return (
        f"<nfeProc><NFe><infNFe><ide><nNF>{numero}</nNF><natOp>Revenda Mercadoria</natOp></ide>"
        f"<total><ICMSTot><vProd>{valor}</vProd><vNF>{valor}</vNF></ICMSTot></total>"
        f"<pag><detPag><tPag>{forma_pagamento}</tPag></detPag></pag>"
        f"<infAdic><infCpl>INEP: 60000099 ITEM LPU: {item_lpu} MUNICIPIO/UF: Recife/PE VENCIMENTO: 10/12/2026"
        f"</infCpl></infAdic></infNFe></NFe>"
        f"<protNFe><infProt><dhRecbto>{autorizada_em}</dhRecbto></infProt></protNFe></nfeProc>"
    ).encode()


def _receber(ri, notas, recebido_em, manual=False, cancelado=False):
    """Simula 1 resposta do financeiro (e-mail) com o PDF + XML de cada NF.
    `notas`: [(numero, data_nf "dd-mm-aaaa", valor, item_lpu, forma_pagamento)]."""
    documentos = []
    for numero, data_nf, valor, item_lpu, forma in notas:
        nome = f"{numero}_{data_nf}_NOME_MEGA_INFRA"
        xml = Documento.objects.create(ri=ri, tipo=Documento.XML, recebido_em=recebido_em,
                                       arquivo=ContentFile(_xml_nf(numero, valor, item_lpu, forma), f"{nome}.xml"))
        pdf = Documento.objects.create(ri=ri, tipo=Documento.NOTA_FISCAL_PDF, recebido_em=recebido_em,
                                       arquivo=ContentFile(b"%PDF-fake", f"{nome}.pdf"))
        documentos += [xml, pdf]
        if manual or cancelado:
            LogRpaEace.objects.create(ri=ri, documento_pdf=pdf, documento_xml=xml, criado_manualmente=manual,
                                      resultado=LogRpaEace.CANCELADO if cancelado else LogRpaEace.SUCESSO)
    if not manual:
        entrada = RiHistorico.objects.create(ri=ri, tipo=RiHistorico.EMAIL, mensagem="Resposta do financeiro.")
        entrada.documentos.set(documentos)
        RiHistorico.objects.filter(pk=entrada.pk).update(criado_em=recebido_em)
    return documentos


def _quando(dia, hora=10):
    return timezone.make_aware(datetime(2026, 11, dia, hora, 0))


def _montar(inicio=date(2026, 11, 10), fim=date(2026, 11, 11), **filtros):
    return montar_relatorio_faturamento_eace_materiais_novo(inicio, fim, **filtros)


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class MontarRelatorioFaturamentoNovoTests(TestCase):

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.escola = Escola.objects.create(inep="60000099", nome="Escola NF Financeiro", estado="SP", lote=9)
        self.ri = Ri.objects.create(escola=self.escola, status=Ri.FATURAMENTO_RI_CONCLUIDO)

    def test_valor_vem_da_nf_mesmo_com_o_kit_fora_do_lado_relatorio_eace(self):
        """Caso real do INEP 35010293: o Sincronizador apagou o KIT do Lado
        Relatório EACE, mas a NF do KIT foi faturada e recebida - entra com
        o valor da NF, e o Nº OSP vem do item com o mesmo número de NF."""
        RiItemRelatorioEace.objects.create(ri=self.ri, descricao_item="Nobreak", quantidade=1,
                                           valor_unitario="9999.00", nota_fiscal="3849", num_osp="5877")
        _receber(self.ri, [("3847", "10-11-2026", "20171.96", "KIT 10", ESPECIAL),
                           ("3849", "10-11-2026", "1551.93", "Nobreak", ESPECIAL)], _quando(10))
        linhas = _montar()
        self.assertEqual([(l["nota_fiscal"], l["valor"], l["numero_osp"]) for l in linhas],
                         [("3847", Decimal("20171.96"), ""), ("3849", Decimal("1551.93"), "5877")])
        self.assertEqual({l["data_nf"] for l in linhas}, {date(2026, 11, 10)})
        self.assertEqual({l["processo"] for l in linhas}, {"Especial"})

    def test_periodo_e_a_data_da_nf_nao_a_do_recebimento(self):
        _receber(self.ri, [("3518", "09-11-2026", "20171.96", "KIT 10", ESPECIAL)], _quando(10))
        _receber(self.ri, [("3519", "10-11-2026", "1551.93", "Nobreak", ESPECIAL)], _quando(10, 12))
        self.assertEqual([l["nota_fiscal"] for l in _montar()], ["3519"])
        self.assertEqual([l["nota_fiscal"] for l in _montar(date(2026, 11, 9), date(2026, 11, 9))], ["3518"])

    def test_nf_refaturada_sai_e_a_do_outro_item_continua(self):
        """Caso real do INEP 35008998: o financeiro refaturou o KIT (4103 →
        4185) e mandou só a NF nova; o Nobreak (4104) da 1ª resposta vale."""
        _receber(self.ri, [("4103", "10-11-2026", "8276.71", "KIT 1", ESPECIAL),
                           ("4104", "10-11-2026", "1551.93", "Nobreak", ESPECIAL)], _quando(10, 22))
        _receber(self.ri, [("4185", "11-11-2026", "8276.72", "KIT 1", ESPECIAL)], _quando(11, 11))
        self.assertEqual([l["nota_fiscal"] for l in _montar()], ["4104", "4185"])

    def test_mesma_nf_recebida_duas_vezes_conta_uma(self):
        _receber(self.ri, [("3879", "10-11-2026", "21408.19", "KIT 11", ESPECIAL)], _quando(10))
        _receber(self.ri, [("3879", "10-11-2026", "21408.19", "KIT 11", ESPECIAL)], _quando(10, 15))
        linhas = _montar()
        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0]["valor"], Decimal("21408.19"))

    def test_nf_recebida_por_fora_substitui_a_do_mesmo_item(self):
        """Processamento RPA manual (NF corrigida enviada por fora do e-mail)."""
        _receber(self.ri, [("3891", "10-11-2026", "1034.31", "Switch Gigabit 8 portas PoE+", ESPECIAL)], _quando(10))
        _receber(self.ri, [("4203", "11-11-2026", "994.18", "Switch Gigabit 8 portas PoE+", ESPECIAL)],
                 _quando(11, 16), manual=True)
        self.assertEqual([(l["nota_fiscal"], l["valor"]) for l in _montar()], [("4203", Decimal("994.18"))])

    def test_nf_de_processamento_cancelado_nao_conta(self):
        _receber(self.ri, [("5000", "10-11-2026", "100.00", "Rack 7U", ESPECIAL)], _quando(10),
                 manual=True, cancelado=True)
        self.assertEqual(_montar(), [])

    def test_processo_pela_forma_de_pagamento_e_filtro(self):
        _receber(self.ri, [("3378", "10-11-2026", "24142.36", "KIT 14", CLASSICO),
                           ("3379", "10-11-2026", "2983.44", "Nobreak", ESPECIAL),
                           ("3380", "10-11-2026", "209.00", "Conversor", "01")], _quando(10))
        self.assertEqual({l["nota_fiscal"]: l["processo"] for l in _montar()},
                         {"3378": "Clássico", "3379": "Especial", "3380": "Não identificado"})
        self.assertEqual([l["nota_fiscal"] for l in _montar(processo="especial")], ["3379"])
        self.assertEqual([l["nota_fiscal"] for l in _montar(processo="classico")], ["3378"])

    def test_hora_filtra_pela_autorizacao_na_sefaz(self):
        _receber(self.ri, [("6000", "10-11-2026", "10.00", "Rack 7U", ESPECIAL)], _quando(10))  # 10:00
        dia = {"inicio": date(2026, 11, 10), "fim": date(2026, 11, 10)}
        from datetime import time
        self.assertEqual(len(_montar(**dia, hora_inicio=time(9, 0), hora_fim=time(10, 0))), 1)
        self.assertEqual(_montar(**dia, hora_inicio=time(10, 1)), [])

    def test_xml_e_lido_uma_vez_so(self):
        _receber(self.ri, [("7000", "10-11-2026", "50.00", "Rack 7U", ESPECIAL)], _quando(10))
        with patch("apps.ri.services.ler_dados_xml_nf", wraps=ler_dados_xml_nf) as ler:
            for _ in range(3):
                linhas = _montar()
        self.assertEqual(ler.call_count, 1)
        self.assertEqual(linhas[0]["valor"], Decimal("50.00"))

    def test_ri_sem_nf_recebida_nao_aparece(self):
        RiItemRelatorioEace.objects.create(ri=self.ri, descricao_item="Nobreak", quantidade=1,
                                           valor_unitario="1551.93", nota_fiscal="9999", num_osp="1")
        self.assertEqual(_montar(), [])


class LerDadosXmlNfTests(TestCase):

    def test_data_pelo_nome_do_arquivo(self):
        dados = ler_dados_xml_nf(_xml_nf("4104", "1551.93", "Nobreak", autorizada_em="2026-11-11T00:10:00-03:00"),
                                 "documentos_ri/2026/11/4104_10-11-2026_NOME_MEGA_INFRA.xml")
        self.assertEqual(dados["data_nf"], "2026-11-10")  # o nome manda (data registrada no financeiro)
        self.assertEqual((dados["numero_nf"], dados["valor"], dados["item_lpu"], dados["processo"]),
                         ("4104", "1551.93", "Nobreak", "especial"))

    def test_sem_padrao_no_nome_usa_a_autorizacao_na_sefaz(self):
        dados = ler_dados_xml_nf(_xml_nf("1", "2.00", "Rack 7U", autorizada_em="2026-11-09T23:30:00-03:00"),
                                 "nota-enviada-por-fora.xml")
        self.assertEqual(dados["data_nf"], "2026-11-09")

    def test_campo_ausente_fica_vazio(self):
        dados = ler_dados_xml_nf(b"<nfeProc></nfeProc>", "x.xml")
        self.assertEqual((dados["numero_nf"], dados["valor"], dados["data_nf"], dados["processo"]), ("", "", "", ""))


class GerarPlanilhaRelatorioFaturamentoNovoTests(TestCase):

    def test_colunas_e_total(self):
        linhas = [
            {"inep": "60000099", "nota_fiscal": "3847", "data_nf": date(2026, 11, 10), "processo": "Especial",
             "valor": Decimal("20171.96"), "numero_osp": ""},
            {"inep": "60000099", "nota_fiscal": "3849", "data_nf": date(2026, 11, 10), "processo": "Especial",
             "valor": Decimal("1551.93"), "numero_osp": "5877"},
        ]
        aba = openpyxl.load_workbook(BytesIO(gerar_planilha_relatorio_faturamento_eace_materiais_novo(linhas)))[
            "CONSOLIDADO"]
        self.assertEqual([c.value for c in aba[2]], ["INEP", "NF", "DATA DA NF", "PROCESSO", "VALOR", "Nº OSP", "SITUAÇÃO"])
        self.assertEqual([aba["A3"].value, aba["B3"].value, aba["D3"].value, aba["E3"].value],
                         ["60000099", "3847", "Especial", 20171.96])
        self.assertEqual(aba["C3"].value.date(), date(2026, 11, 10))
        self.assertEqual(aba["A5"].value, "TOTAL DO PERÍODO")
        self.assertEqual(aba["E5"].value, 21723.89)

    def test_sem_linhas_nao_tem_total(self):
        aba = openpyxl.load_workbook(BytesIO(gerar_planilha_relatorio_faturamento_eace_materiais_novo([])))[
            "CONSOLIDADO"]
        self.assertEqual(aba.max_row, 2)


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class RelatorioFaturamentoNovoViewTests(TestCase):

    def setUp(self):
        self.admin = User.objects.create_user(username="admin-novo-nf", password="x",
                                              perfil=User.PERFIL_ADMINISTRADOR)
        self.analista = User.objects.create_user(username="analista-novo-nf", password="x",
                                                 perfil=User.PERFIL_ANALISTA)
        escola = Escola.objects.create(inep="60000098", nome="Escola View NF", estado="SP")
        self.ri = Ri.objects.create(escola=escola, status=Ri.FATURAMENTO_RI_CONCLUIDO)
        self.docs = _receber(self.ri, [("3847", "10-11-2026", "20171.96", "KIT 10", ESPECIAL),
                                       ("3378", "10-11-2026", "24142.36", "KIT 14", CLASSICO)], _quando(10))
        _receber(self.ri, [("3000", "01-11-2026", "5.00", "Rack 7U", ESPECIAL)], _quando(1))
        self.periodo = {"data_inicio": "2026-11-10", "data_fim": "2026-11-11"}

    def test_sem_periodo_mostra_so_o_formulario(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("relatorio_faturamento_eace_materiais_novo"))
        self.assertIsNone(resp.context["linhas"])
        self.assertContains(resp, "Data da NF - início")

    def test_tela_com_total_e_filtro_de_processo(self):
        self.client.force_login(self.admin)
        url = reverse("relatorio_faturamento_eace_materiais_novo")
        resp = self.client.get(url, self.periodo)
        self.assertEqual(resp.context["total_valor"], Decimal("44314.32"))
        self.assertContains(resp, "10/11/2026")
        resp = self.client.get(url, {**self.periodo, "processo": "especial"})
        self.assertEqual([l["nota_fiscal"] for l in resp.context["linhas"]], ["3847"])
        self.assertContains(resp, "&amp;processo=especial", count=2)  # Excel e .zip

    def test_analista_nao_acessa(self):
        self.client.force_login(self.analista)
        self.assertEqual(self.client.get(reverse("relatorio_faturamento_eace_materiais_novo")).status_code, 403)
        self.assertEqual(self.client.get(reverse("relatorio_faturamento_eace_materiais_novo_exportar"),
                                         self.periodo).status_code, 403)

    def test_exportar_excel(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("relatorio_faturamento_eace_materiais_novo_exportar"),
                               {**self.periodo, "processo": "classico"})
        aba = openpyxl.load_workbook(BytesIO(resp.content))["CONSOLIDADO"]
        self.assertEqual((aba["B3"].value, aba["E3"].value), ("3378", 24142.36))
        self.assertEqual(aba["A4"].value, "TOTAL DO PERÍODO")

    def test_exportar_sem_periodo_retorna_400(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("relatorio_faturamento_eace_materiais_novo_exportar")).status_code,
                         400)

    def test_zip_so_com_os_arquivos_das_nf_do_relatorio(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("relatorio_faturamento_eace_materiais_novo_exportar_arquivos"),
                               {**self.periodo, "processo": "especial"})
        nomes = sorted(zipfile.ZipFile(BytesIO(resp.content)).namelist())
        esperados = sorted(f"60000098/{os.path.basename(d.arquivo.name)}" for d in self.docs[:2])
        self.assertEqual(nomes, esperados)  # só a 3847 (PDF + XML); a 3378 é clássica e a 3000 é de 01/11


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class FiltroCanceladosRelatorioNovoTests(TestCase):
    """Filtro "Cancelados" (pedido do usuário, 2026-11-13): NF cancelada no financeiro e baixada aqui, e NF de
    processo cancelado pela EACE - fora (padrão), só elas ou todas, com a Situação de cada uma."""

    def setUp(self):
        from .models import CancelamentoEace, NfCanceladaFinanceiro

        self.escola = Escola.objects.create(inep="60000099", nome="Escola NF Financeiro", estado="SP", lote=9)
        self.ri = Ri.objects.create(escola=self.escola, status=Ri.FATURAMENTO_RI_CONCLUIDO)
        _receber(self.ri, [("5001", "10-11-2026", "100.00", "KIT 15", ESPECIAL),
                           ("5002", "10-11-2026", "50.00", "NOBREAK", ESPECIAL)], _quando(10))
        NfCanceladaFinanceiro.objects.create(id_financeiro="9-0", numero_nf="5002", inep="60000099",
                                             baixada_em=_quando(11))
        # outro INEP com o processo cancelado pela EACE depois de receber a NF
        outra = Escola.objects.create(inep="60000098", nome="Escola Cancelada", estado="SP", lote=9)
        self.ri_eace = Ri.objects.create(escola=outra, status=Ri.IMPLANTACAO_EACE)
        documentos = _receber(self.ri_eace, [("6001", "11-11-2026", "30.00", "KIT 15", ESPECIAL)], _quando(11))
        cancelamento = CancelamentoEace.objects.create(ri=self.ri_eace, motivo="EACE cancelou", status_anterior="x")
        Documento.objects.filter(pk__in=[d.pk for d in documentos]).update(cancelamento_eace=cancelamento)

    def _nfs(self, cancelados):
        return [(linha["nota_fiscal"], linha["situacao"]) for linha in _montar(cancelados=cancelados)]

    def test_sem_cancelados_e_o_padrao(self):
        self.assertEqual(self._nfs("sem"), [("5001", "")])
        self.assertEqual([linha["nota_fiscal"] for linha in _montar()], ["5001"])

    def test_cancelados_e_cancelados_eace_separados(self):
        self.assertEqual(self._nfs("financeiro"), [("5002", "Cancelada no financeiro")])
        self.assertEqual(self._nfs("eace"), [("6001", "Cancelada pela EACE")])

    def test_todos(self):
        self.assertEqual(self._nfs("todos"), [("5001", ""), ("5002", "Cancelada no financeiro"),
                                              ("6001", "Cancelada pela EACE")])

    def test_tela_excel_e_zip_respeitam_o_filtro(self):
        admin = User.objects.create_user("admin-canc-rel", password="x", perfil=User.PERFIL_ADMINISTRADOR)
        self.client.force_login(admin)
        filtro = {"data_inicio": "2026-11-10", "data_fim": "2026-11-11", "cancelados": "todos"}
        resposta = self.client.get(reverse("relatorio_faturamento_eace_materiais_novo"), filtro)
        self.assertContains(resposta, "Cancelada pela EACE")
        self.assertContains(resposta, "Canceladas: R$ 50,00")
        self.assertContains(resposta, "Canceladas EACE: R$ 30,00")
        self.assertContains(resposta, "cancelados=todos")
        planilha = openpyxl.load_workbook(BytesIO(self.client.get(
            reverse("relatorio_faturamento_eace_materiais_novo_exportar"), filtro).content)).active
        valores = [celula for linha in planilha.iter_rows(values_only=True) for celula in linha]
        self.assertIn("SITUAÇÃO", valores)
        self.assertIn("Cancelada no financeiro", valores)
        pacote = zipfile.ZipFile(BytesIO(self.client.get(
            reverse("relatorio_faturamento_eace_materiais_novo_exportar_arquivos"), filtro).content))
        self.assertTrue(any("6001" in nome for nome in pacote.namelist()))
        pacote_eace = zipfile.ZipFile(BytesIO(self.client.get(
            reverse("relatorio_faturamento_eace_materiais_novo_exportar_arquivos"),
            {**filtro, "cancelados": "eace"}).content))
        self.assertTrue(any("6001" in nome for nome in pacote_eace.namelist()))
        self.assertFalse(any("5001" in nome or "5002" in nome for nome in pacote_eace.namelist()))
