import datetime
import io
import tempfile
from pathlib import Path
from decimal import Decimal

import openpyxl
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.escolas.bdo import (
    PlanilhaBdoError, dias_no_mes_referencia, dias_proporcionais, importar_planilha_bdo, ler_planilha_bdo, valor_proporcional,
)
from apps.escolas.models import BoletimBdo, Escola, InepBdo, MunicipioBdo
from apps.ri.models import KitPadrao, Ri

User = get_user_model()

CABECALHO = (
    "Fornecedor", "CNPJ", "Boletim de desempenho", "Município", "UF", "Valor serviços", "Valor créditos",
    "Valor descontos", "Valor descontos proporcionais", "Valor total", "Status", "Qntd escola", "INEPs",
)


def _linha(boletim, municipio, uf, valor_total, ineps, servicos="0,00", creditos="0,00", descontos="0,00",
           proporcionais="0,00"):
    return (
        "MEGA", "07.525.262/0004-61", boletim, municipio, uf, servicos, creditos, descontos, proporcionais,
        valor_total, "Pendente", "", ineps,
    )


def _planilha(linhas, cabecalho=CABECALHO, nome="FR_3658.xlsx"):
    workbook = openpyxl.Workbook()
    aba = workbook.active
    aba.title = "FR_3658"
    aba.append(cabecalho)
    for linha in linhas:
        aba.append(linha)
    conteudo = io.BytesIO()
    workbook.save(conteudo)
    return SimpleUploadedFile(
        nome, conteudo.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


LINHAS_3658 = [
    _linha("3658", "AMERICANA", "SP", "49,92", "35058592"),
    _linha("3658", "ATIBAIA", "SP", "277,89", "35011006"),
    _linha(
        "3658", "Campo Grande", "MS", "1.094,45", "50031287, 50005111, 50033433, 50028340",
        servicos="1.462,48", descontos="2,41", proporcionais="365,62",
    ),
    _linha("3658", "Brasília", "DF", "31.183,68", "53002814, 53002474"),
]


class LerPlanilhaBdoTests(TestCase):
    def test_le_valor_brasileiro_e_ineps_separados_por_virgula(self):
        boletins = ler_planilha_bdo(_planilha(LINHAS_3658))
        self.assertEqual(list(boletins), ["3658"])
        campo_grande = boletins["3658"][2]
        self.assertEqual(
            [campo_grande[campo] for campo in MunicipioBdo.CAMPOS_VALORES],
            [Decimal("1462.48"), Decimal("0.00"), Decimal("2.41"), Decimal("365.62"), Decimal("1094.45")],
        )
        self.assertEqual(campo_grande["ineps"], ["50031287", "50005111", "50033433", "50028340"])

    def test_aceita_valor_numerico_do_excel_e_cabecalho_sem_acento(self):
        cabecalho = tuple("Municipio" if coluna == "Município" else coluna for coluna in CABECALHO)
        boletins = ler_planilha_bdo(_planilha([_linha(3658, "AMERICANA", "sp", 49.92, 35058592)], cabecalho))
        linha = boletins["3658"][0]
        self.assertEqual((linha["uf"], linha["valor_total"], linha["ineps"]), ("SP", Decimal("49.92"), ["35058592"]))

    def test_aceita_colunas_a_mais_a_menos_e_fora_de_ordem(self):
        """Só as colunas usadas pelo BDO importam: as outras podem faltar,
        sobrar ou vir em qualquer ordem, e o nome não depende de
        maiúscula, acento ou espaço extra."""
        cabecalho = (
            "  ineps ", "Coluna Nova", "VALOR TOTAL", "uf", "Valor descontos proporcionais", "Observação",
            "Valor Descontos", "valor creditos", "Valor  Servicos", "MUNICIPIO", "Boletim de Desempenho",
        )
        linha = (
            "35058592, 35004330", "x", "49,92", "sp", "316,98", "qualquer coisa",
            "13,48", "0,00", "380,38", "AMERICANA", "3658",
        )
        boletins = ler_planilha_bdo(_planilha([linha], cabecalho))
        [americana] = boletins["3658"]
        self.assertEqual((americana["municipio"], americana["uf"]), ("AMERICANA", "SP"))
        self.assertEqual(americana["ineps"], ["35058592", "35004330"])
        self.assertEqual(
            [americana[campo] for campo in MunicipioBdo.CAMPOS_VALORES],
            [Decimal("380.38"), Decimal("0.00"), Decimal("13.48"), Decimal("316.98"), Decimal("49.92")],
        )

    def test_sem_coluna_obrigatoria_da_erro(self):
        for faltando in ("INEPs", "Valor créditos", "Valor descontos proporcionais"):
            with self.subTest(faltando=faltando):
                cabecalho = tuple(coluna for coluna in CABECALHO if coluna != faltando)
                with self.assertRaisesMessage(PlanilhaBdoError, "colunas obrigatórias"):
                    ler_planilha_bdo(_planilha([], cabecalho))

    def test_linha_sem_inep_ou_valor_invalido_da_erro_com_numero_da_linha(self):
        linhas = [LINHAS_3658[0], _linha("3658", "ATIBAIA", "SP", "abc", "", creditos="")]
        with self.assertRaisesMessage(PlanilhaBdoError, "linha 3 (Valor créditos, Valor total, INEPs)"):
            ler_planilha_bdo(_planilha(linhas))

    def test_planilha_sem_dados_da_erro(self):
        with self.assertRaisesMessage(PlanilhaBdoError, "nenhuma linha de dados"):
            ler_planilha_bdo(_planilha([]))


class ImportarPlanilhaBdoTests(TestCase):
    def test_boletim_ja_importado_e_recusado_sem_alterar_os_dados(self):
        importar_planilha_bdo(ler_planilha_bdo(_planilha(LINHAS_3658)), "RI", "FR_3658.xlsx", None)
        with self.assertRaisesMessage(PlanilhaBdoError, "Boletim de desempenho já importado: 3658"):
            importar_planilha_bdo(ler_planilha_bdo(_planilha(LINHAS_3658[:1])), "RI", "FR_3658.xlsx", None)
        self.assertEqual(BoletimBdo.objects.count(), 1)
        self.assertEqual(MunicipioBdo.objects.count(), 4)
        self.assertEqual(InepBdo.objects.count(), 8)

    def test_planilha_com_boletim_novo_e_repetido_nao_grava_nenhum(self):
        importar_planilha_bdo(ler_planilha_bdo(_planilha(LINHAS_3658)), "RI", "FR_3658.xlsx", None)
        linhas = [LINHAS_3658[0], _linha("3700", "AMERICANA", "SP", "10,00", "35058592")]
        with self.assertRaises(PlanilhaBdoError):
            importar_planilha_bdo(ler_planilha_bdo(_planilha(linhas)), "RI", "misto.xlsx", None)
        self.assertFalse(BoletimBdo.objects.filter(numero="3700").exists())

    def test_boletim_novo_e_gravado_sem_mexer_nos_anteriores(self):
        importar_planilha_bdo(ler_planilha_bdo(_planilha(LINHAS_3658)), "RI", "FR_3658.xlsx", None)
        importar_planilha_bdo(
            ler_planilha_bdo(_planilha([_linha("3700", "AMERICANA", "SP", "10,00", "35058592")])), "RI", "FR_3700.xlsx", None,
        )
        self.assertEqual(sorted(BoletimBdo.objects.values_list("numero", flat=True)), ["3658", "3700"])
        self.assertEqual(InepBdo.objects.count(), 9)


class DiasProporcionaisTests(TestCase):
    def test_conta_ate_o_dia_30_sem_o_dia_da_ativacao(self):
        self.assertEqual(dias_proporcionais(datetime.date(2026, 9, 15)), 15)
        self.assertEqual(dias_proporcionais(datetime.date(2026, 9, 1)), 29)
        self.assertEqual(dias_proporcionais(datetime.date(2026, 9, 30)), 0)

    def test_fevereiro_tambem_vai_ate_o_dia_30(self):
        self.assertEqual(dias_proporcionais(datetime.date(2026, 2, 20)), 10)

    def test_dia_31_vai_para_o_mes_seguinte_cheio(self):
        self.assertEqual(dias_proporcionais(datetime.date(2026, 8, 31)), 30)

    def test_sem_data_de_ativacao_fica_vazio(self):
        self.assertIsNone(dias_proporcionais(None))


class DiasNoMesReferenciaTests(TestCase):
    SETEMBRO = datetime.date(2026, 9, 1)

    def test_ativado_antes_do_mes_conta_cheio(self):
        self.assertEqual(dias_no_mes_referencia(datetime.date(2026, 7, 10), self.SETEMBRO), 30)
        self.assertEqual(dias_no_mes_referencia(datetime.date(2026, 8, 31), self.SETEMBRO), 30)
        self.assertEqual(dias_no_mes_referencia(datetime.date(2025, 12, 5), self.SETEMBRO), 30)

    def test_ativado_no_mes_conta_proporcional(self):
        self.assertEqual(dias_no_mes_referencia(datetime.date(2026, 9, 15), self.SETEMBRO), 15)
        self.assertEqual(dias_no_mes_referencia(datetime.date(2026, 10, 31), datetime.date(2026, 10, 1)), 0)

    def test_ativado_depois_do_mes_ou_sem_data_fica_vazio(self):
        self.assertIsNone(dias_no_mes_referencia(datetime.date(2026, 10, 1), self.SETEMBRO))
        self.assertIsNone(dias_no_mes_referencia(None, self.SETEMBRO))

    def test_boletim_sem_mes_de_referencia_conta_como_antes(self):
        self.assertEqual(dias_no_mes_referencia(datetime.date(2026, 7, 10), None), 20)


class ValorProporcionalTests(TestCase):
    def test_valor_mensal_vezes_dias_sobre_30_em_centavos(self):
        self.assertEqual(valor_proporcional(Decimal("380.38"), 15), Decimal("190.19"))
        self.assertEqual(valor_proporcional(Decimal("365.62"), 29), Decimal("353.43"))
        self.assertEqual(valor_proporcional(Decimal("760.00"), 30), Decimal("760.00"))
        self.assertEqual(valor_proporcional(Decimal("760.00"), 0), Decimal("0.00"))

    def test_sem_valor_ou_sem_dias_fica_vazio(self):
        self.assertIsNone(valor_proporcional(None, 15))
        self.assertIsNone(valor_proporcional(Decimal("760.00"), None))


class BdoViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="bdo-admin", password="senha-teste-123", perfil=User.PERFIL_ADMINISTRADOR,
        )
        self.analista = User.objects.create_user(
            username="bdo-analista", password="senha-teste-123", perfil=User.PERFIL_ANALISTA,
        )

    def _importar(self, linhas=LINHAS_3658, tipo="RI"):
        importar_planilha_bdo(ler_planilha_bdo(_planilha(linhas)), tipo, "FR_3658.xlsx", self.admin)

    def test_anonimo_vai_pro_login(self):
        resp = self.client.get(reverse("bdo"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp["Location"])

    def test_sem_boletim_mostra_estado_vazio(self):
        self.client.force_login(self.analista)
        resp = self.client.get(reverse("bdo"))
        self.assertContains(resp, "Nenhum Boletim importado")
        self.assertNotContains(resp, 'enctype="multipart/form-data"')
        self.assertNotContains(resp, f'href="{reverse("relatorio_bdo")}"')

    def test_tela_do_bdo_nao_tem_mais_upload_e_admin_ve_o_atalho(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("bdo"))
        self.assertNotContains(resp, 'enctype="multipart/form-data"')
        self.assertContains(resp, f'href="{reverse("relatorio_bdo")}"')

    def test_grid_por_inep_repete_o_valor_do_municipio_e_total_nao_duplica(self):
        self._importar()
        self.client.force_login(self.analista)
        resp = self.client.get(reverse("bdo"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["page_obj"].paginator.count, 8)
        self.assertEqual(resp.context["total_ineps"], 8)
        self.assertEqual(resp.context["total_municipios"], 4)
        self.assertEqual(resp.context["valor_total"], Decimal("32605.94"))
        self.assertContains(resp, "53002814")
        self.assertContains(resp, "Boletim de desempenho")

    def test_grid_por_inep_mostra_a_data_de_ativacao_do_ri_atual_tambem_no_re(self):
        escola = Escola.objects.create(inep="35058592", nome="Escola Americana", estado="SP", municipio="Americana")
        Ri.objects.create(escola=escola, data_ativacao=datetime.date(2026, 8, 1))
        Ri.objects.create(escola=escola, data_ativacao=datetime.date(2026, 9, 5))
        self._importar(tipo="RI")
        importar_planilha_bdo(
            ler_planilha_bdo(_planilha([_linha("3700", "AMERICANA", "SP", "10,00", "35058592")])),
            "RE", "FR_3700.xlsx", self.admin,
        )
        self.client.force_login(self.analista)
        resp = self.client.get(reverse("bdo"))
        datas = {
            (linha.municipio_bdo.boletim.tipo, linha.inep): linha.data_ativacao for linha in resp.context["page_obj"]
        }
        self.assertEqual(datas[("RI", "35058592")], datetime.date(2026, 9, 5))
        self.assertEqual(datas[("RE", "35058592")], datetime.date(2026, 9, 5))
        self.assertIsNone(datas[("RI", "53002814")])
        self.assertContains(resp, "Dias proporcionais")
        self.assertContains(resp, "Data de ativação")
        self.assertContains(resp, "05/09/2026", count=2)

    def test_valor_assinatura_conforme_o_tipo_do_boletim(self):
        """RE: assinatura da escola; RI: manutenção do LPU no Lote da escola."""
        KitPadrao.objects.create(
            descricao="Manutenção de Rede Interna (serviços, materiais e equipamentos)", lote=9,
            unidade="Escola/Mês", valor_servico=Decimal("380.38"),
        )
        KitPadrao.objects.create(
            descricao="Manutenção de Rede Interna (serviços, materiais e equipamentos)", lote=11,
            unidade="Escola/Mês", valor_servico=Decimal("365.62"),
        )
        Escola.objects.create(inep="35058592", nome="Americana", lote=9, valor_assinatura_re=Decimal("760.00"))
        Escola.objects.create(inep="35011006", nome="Atibaia", lote=11)
        Escola.objects.create(inep="50031287", nome="Campo Grande", valor_assinatura_re=Decimal("370.00"))
        self._importar(tipo="RI")
        importar_planilha_bdo(
            ler_planilha_bdo(_planilha([_linha("3700", "AMERICANA", "SP", "10,00", "35058592, 35011006")])),
            "RE", "FR_3700.xlsx", self.admin,
        )
        self.client.force_login(self.analista)
        resp = self.client.get(reverse("bdo"))
        valores = {
            (linha.municipio_bdo.boletim.tipo, linha.inep): linha.valor_assinatura for linha in resp.context["page_obj"]
        }
        self.assertEqual(valores[("RI", "35058592")], Decimal("380.38"))
        self.assertEqual(valores[("RI", "35011006")], Decimal("365.62"))
        self.assertEqual(valores[("RE", "35058592")], Decimal("760.00"))
        self.assertIsNone(valores[("RE", "35011006")])  # escola sem assinatura RE
        self.assertIsNone(valores[("RI", "50031287")])  # escola sem Lote
        self.assertIsNone(valores[("RI", "53002814")])  # INEP sem escola
        self.assertContains(resp, "Valor assinatura")
        self.assertContains(resp, "R$ 760,00")

    def test_valor_assinatura_vazio_em_boletim_sem_tipo(self):
        Escola.objects.create(inep="35058592", nome="Americana", valor_assinatura_re=Decimal("760.00"))
        self._importar(tipo="")
        self.client.force_login(self.analista)
        resp = self.client.get(reverse("bdo"), {"inep": "35058592"})
        self.assertIsNone(resp.context["page_obj"][0].valor_assinatura)

    def test_filtro_de_data_de_ativacao_usa_o_ri_atual(self):
        americana = Escola.objects.create(inep="35058592", nome="Escola Americana", estado="SP", municipio="Americana")
        Ri.objects.create(escola=americana, data_ativacao=datetime.date(2026, 9, 15))
        atibaia = Escola.objects.create(inep="35011006", nome="Escola Atibaia", estado="SP", municipio="Atibaia")
        Ri.objects.create(escola=atibaia, data_ativacao=datetime.date(2026, 9, 20))
        Ri.objects.create(escola=atibaia, data_ativacao=datetime.date(2026, 8, 10))
        self._importar()
        self.client.force_login(self.analista)

        resp = self.client.get(reverse("bdo"), {"data_inicial": "01/09/2026", "data_final": "30/09/2026"})
        self.assertEqual([linha.inep for linha in resp.context["page_obj"]], ["35058592"])
        self.assertEqual(resp.context["total_municipios"], 1)
        self.assertContains(resp, "data_inicial=01%2F09%2F2026")

        resp = self.client.get(reverse("bdo"), {"data_inicial": "01/08/2026", "agrupar": "uf"})
        self.assertEqual(resp.context["total_ineps"], 2)

        resp = self.client.get(reverse("bdo"), {"data_inicial": "30/09/2026", "data_final": "01/09/2026"})
        self.assertEqual(resp.context["page_obj"].paginator.count, 8)
        self.assertContains(resp, "A data inicial não pode ser depois da data final")

    def test_agrupar_por_municipio_mostra_quantidade_de_ineps_e_valor(self):
        self._importar()
        self.client.force_login(self.analista)
        resp = self.client.get(reverse("bdo"), {"agrupar": "municipio"})
        linhas = {linha["municipio"]: (linha["quantidade_ineps"], linha["valor_total"]) for linha in resp.context["page_obj"]}
        self.assertEqual(linhas["CAMPO GRANDE"], (4, Decimal("1094.45")))
        self.assertContains(resp, "R$ 1.462,48")
        self.assertContains(resp, "R$ 365,62")
        self.assertEqual(linhas["BRASÍLIA"], (2, Decimal("31183.68")))

    def _escola_ri(self, inep, lote, data_ativacao, assinatura_re=None):
        escola = Escola.objects.create(inep=inep, nome=f"Escola {inep}", lote=lote, valor_assinatura_re=assinatura_re)
        Ri.objects.create(escola=escola, data_ativacao=data_ativacao)

    def test_valor_proporcional_por_inep_e_total_howbe_por_municipio(self):
        KitPadrao.objects.create(
            descricao="Manutenção de Rede Interna (serviços, materiais e equipamentos)", lote=11,
            unidade="Escola/Mês", valor_servico=Decimal("365.62"),
        )
        self._escola_ri("50031287", 11, datetime.date(2026, 9, 15))   # 15 dias: 182,81
        self._escola_ri("50005111", 11, datetime.date(2026, 9, 1))    # 29 dias: 353,43
        self._escola_ri("50033433", 11, datetime.date(2026, 8, 31))   # 30 dias: 365,62
        self._escola_ri("53002814", 11, datetime.date(2026, 9, 10))   # 20 dias: 243,75
        self._escola_ri("53002474", 11, datetime.date(2026, 9, 10))
        self._importar(tipo="RI")
        self.client.force_login(self.analista)

        resp = self.client.get(reverse("bdo"), {"inep": "50031287"})
        self.assertEqual(resp.context["page_obj"][0].valor_proporcional, Decimal("182.81"))
        self.assertContains(resp, "Valor proporcional")
        self.assertContains(resp, "R$ 182,81")

        resp = self.client.get(reverse("bdo"), {"agrupar": "municipio"})
        linhas = {linha["municipio"]: linha for linha in resp.context["page_obj"]}
        # 50028340 sem escola: fica fora da soma e é sinalizado
        self.assertEqual(linhas["CAMPO GRANDE"]["total_howbe"], Decimal("901.86"))
        self.assertEqual(linhas["CAMPO GRANDE"]["ineps_sem_valor_howbe"], 1)
        self.assertEqual(linhas["BRASÍLIA"]["total_howbe"], Decimal("487.50"))
        self.assertEqual(linhas["BRASÍLIA"]["ineps_sem_valor_howbe"], 0)
        self.assertIsNone(linhas["AMERICANA"]["total_howbe"])
        self.assertContains(resp, "Total Howbe")
        self.assertContains(resp, "1 INEP(s) sem valor")

    def test_total_howbe_com_mes_de_referencia_cobra_cheio_quem_ativou_antes(self):
        self._escola_ri("35058592", None, datetime.date(2026, 7, 20), assinatura_re=Decimal("600.00"))  # cheio
        self._escola_ri("35011006", None, datetime.date(2026, 9, 25), assinatura_re=Decimal("300.00"))  # 5 dias
        self._escola_ri("35022222", None, datetime.date(2026, 10, 2), assinatura_re=Decimal("900.00"))  # depois
        importar_planilha_bdo(
            ler_planilha_bdo(_planilha([_linha("3700", "AMERICANA", "SP", "650,00", "35058592, 35011006, 35022222")])),
            "RE", "FR_3700.xlsx", self.admin, datetime.date(2026, 9, 18),
        )
        self.assertEqual(BoletimBdo.objects.get().mes_referencia, datetime.date(2026, 9, 1))
        self.client.force_login(self.analista)
        resp = self.client.get(reverse("bdo"), {"agrupar": "municipio"})
        linha = resp.context["page_obj"][0]
        self.assertEqual(linha["total_howbe"], Decimal("650.00"))
        self.assertEqual(linha["ineps_sem_valor_howbe"], 1)
        self.assertEqual(linha["diferenca_howbe"], Decimal("650.00"))  # planilha sem serviços
        resp = self.client.get(reverse("bdo"))
        dias = {linha.inep: linha.dias_proporcionais for linha in resp.context["page_obj"]}
        self.assertEqual(dias, {"35058592": 30, "35011006": 5, "35022222": None})

    def test_total_howbe_confere_com_servicos_menos_descontos_proporcionais(self):
        self._escola_ri("35058592", None, datetime.date(2026, 7, 20), assinatura_re=Decimal("600.00"))  # cheio
        self._escola_ri("35011006", None, datetime.date(2026, 9, 25), assinatura_re=Decimal("300.00"))  # 50,00
        importar_planilha_bdo(
            ler_planilha_bdo(_planilha([_linha(
                "3700", "AMERICANA", "SP", "645,00", "35058592, 35011006",
                servicos="900,00", descontos="5,00", proporcionais="250,00",
            )])),
            "RE", "FR_3700.xlsx", self.admin, datetime.date(2026, 9, 1),
        )
        self.client.force_login(self.analista)
        resp = self.client.get(reverse("bdo"), {"agrupar": "municipio"})
        linha = resp.context["page_obj"][0]
        self.assertEqual(linha["total_howbe"], Decimal("650.00"))
        self.assertEqual(linha["valor_conferencia_howbe"], Decimal("650.00"))
        self.assertEqual(linha["diferenca_howbe"], Decimal("0.00"))
        self.assertNotContains(resp, "Dif. R$")
        MunicipioBdo.objects.update(valor_descontos_proporcionais=Decimal("240.00"))
        resp = self.client.get(reverse("bdo"), {"agrupar": "municipio"})
        self.assertEqual(resp.context["page_obj"][0]["diferenca_howbe"], Decimal("-10.00"))
        self.assertContains(resp, "Dif. R$ -10,00")

    def test_total_howbe_usa_o_tipo_de_cada_boletim_e_segue_o_filtro_de_inep(self):
        self._escola_ri("35058592", None, datetime.date(2026, 9, 20), assinatura_re=Decimal("600.00"))
        self._escola_ri("35011006", None, datetime.date(2026, 9, 25), assinatura_re=Decimal("300.00"))
        importar_planilha_bdo(
            ler_planilha_bdo(_planilha([_linha("3700", "AMERICANA", "SP", "250,00", "35058592, 35011006")])),
            "RE", "FR_3700.xlsx", self.admin,
        )
        self.client.force_login(self.analista)
        resp = self.client.get(reverse("bdo"), {"agrupar": "municipio"})
        linha = resp.context["page_obj"][0]
        self.assertEqual(linha["total_howbe"], Decimal("250.00"))  # 200,00 + 50,00
        resp = self.client.get(reverse("bdo"), {"agrupar": "municipio", "inep": "35011006"})
        self.assertEqual(resp.context["page_obj"][0]["total_howbe"], Decimal("50.00"))

    def test_agrupar_por_uf_soma_cada_municipio_uma_vez(self):
        self._importar()
        self.client.force_login(self.analista)
        resp = self.client.get(reverse("bdo"), {"agrupar": "uf"})
        linhas = {linha["uf"]: linha for linha in resp.context["page_obj"]}
        self.assertEqual(linhas["SP"]["quantidade_municipios"], 2)
        self.assertEqual(linhas["SP"]["quantidade_ineps"], 2)
        self.assertEqual(linhas["SP"]["valor_total"], Decimal("327.81"))
        self.assertEqual(linhas["DF"]["valor_total"], Decimal("31183.68"))

    def test_filtros_de_uf_municipio_e_inep(self):
        self._importar()
        self.client.force_login(self.analista)
        resp = self.client.get(reverse("bdo"), {"uf": "sp"})
        self.assertEqual(resp.context["total_ineps"], 2)
        resp = self.client.get(reverse("bdo"), {"municipio": "campo grande"})
        self.assertEqual(resp.context["total_ineps"], 4)
        resp = self.client.get(reverse("bdo"), {"inep": "53002814"})
        self.assertEqual(resp.context["total_ineps"], 1)
        self.assertEqual(resp.context["valor_total"], Decimal("31183.68"))

    def test_lista_de_municipios_segue_a_uf_e_so_tem_os_do_grid(self):
        self._importar()
        self.client.force_login(self.analista)
        resp = self.client.get(reverse("bdo"))
        self.assertEqual(resp.context["nomes_municipios"], ["AMERICANA", "ATIBAIA", "BRASÍLIA", "CAMPO GRANDE"])
        resp = self.client.get(reverse("bdo"), {"uf": "SP"})
        self.assertEqual(resp.context["nomes_municipios"], ["AMERICANA", "ATIBAIA"])

    def test_municipio_fora_da_uf_escolhida_e_ignorado(self):
        self._importar()
        self.client.force_login(self.analista)
        resp = self.client.get(reverse("bdo"), {"uf": "SP", "municipio": "Campo Grande"})
        self.assertEqual(resp.context["municipio_filtro"], "")
        self.assertEqual(resp.context["total_ineps"], 2)

    def _importar_dois_boletins(self):
        self._importar()
        self._importar([
            _linha("3700", "Americana", "SP", "10,00", "35058592"),
            _linha("3700", "ITU", "SP", "5,00", "35099999"),
        ])

    def test_sem_filtro_mostra_todos_os_boletins_cada_um_independente(self):
        self._importar_dois_boletins()
        self.client.force_login(self.analista)
        resp = self.client.get(reverse("bdo"))
        self.assertIsNone(resp.context["boletim"])
        self.assertEqual(resp.context["page_obj"].paginator.count, 10)
        self.assertEqual(resp.context["total_boletins"], 2)
        self.assertEqual(resp.context["total_ineps"], 9)  # 35058592 está nos 2 Boletins: conta uma vez
        self.assertEqual(resp.context["total_municipios"], 6)
        self.assertEqual(resp.context["valor_total"], Decimal("32620.94"))

    def test_agrupar_por_municipio_mostra_o_mesmo_municipio_em_cada_boletim(self):
        self._importar_dois_boletins()
        self.client.force_login(self.analista)
        resp = self.client.get(reverse("bdo"), {"agrupar": "municipio"})
        americana = {
            linha["boletim"]: (linha["quantidade_ineps"], linha["valor_total"])
            for linha in resp.context["page_obj"] if linha["municipio"] == "AMERICANA"
        }
        self.assertEqual(americana, {"3658": (1, Decimal("49.92")), "3700": (1, Decimal("10.00"))})
        self.assertEqual(resp.context["page_obj"][0]["boletim"], "3700")

    def test_agrupar_por_uf_separa_os_boletins(self):
        self._importar_dois_boletins()
        self.client.force_login(self.analista)
        resp = self.client.get(reverse("bdo"), {"agrupar": "uf"})
        sp = {linha["boletim"]: linha for linha in resp.context["page_obj"] if linha["uf"] == "SP"}
        self.assertEqual(sp["3658"]["quantidade_municipios"], 2)
        self.assertEqual(sp["3658"]["valor_total"], Decimal("327.81"))
        self.assertEqual(sp["3700"]["quantidade_municipios"], 2)
        self.assertEqual(sp["3700"]["quantidade_ineps"], 2)
        self.assertEqual(sp["3700"]["valor_total"], Decimal("15.00"))

    def test_mesmo_municipio_repetido_no_boletim_soma_no_agrupamento(self):
        self._importar([
            _linha("3800", "ATIBAIA", "SP", "10,00", "35000001", servicos="12,00", descontos="2,00"),
            _linha("3800", "Atibaia", "SP", "5,00", "35000002", servicos="5,00"),
        ])
        self.client.force_login(self.analista)
        resp = self.client.get(reverse("bdo"), {"agrupar": "municipio"})
        [atibaia] = resp.context["page_obj"]
        self.assertEqual(atibaia["quantidade_ineps"], 2)
        self.assertEqual(atibaia["valores_em_ordem"], [
            Decimal("17.00"), Decimal("0.00"), Decimal("2.00"), Decimal("0.00"), Decimal("15.00"),
        ])

    def test_boletim_sem_os_valores_de_composicao_mostra_traco(self):
        self._importar()
        MunicipioBdo.objects.update(valor_servicos=None)
        self.client.force_login(self.analista)
        resp = self.client.get(reverse("bdo"), {"agrupar": "uf"})
        self.assertIsNone(resp.context["page_obj"][0]["valor_servicos"])
        self.assertContains(resp, '">—</span>')

    def test_filtro_de_boletim_mostra_so_aquele_boletim(self):
        self._importar_dois_boletins()
        self.client.force_login(self.analista)
        resp = self.client.get(reverse("bdo"), {"boletim": "3700"})
        self.assertEqual(resp.context["boletim"].numero, "3700")
        self.assertEqual(resp.context["total_ineps"], 2)
        self.assertEqual(resp.context["valor_total"], Decimal("15.00"))

    def test_relatorio_bdo_lista_os_boletins_importados(self):
        self._importar()
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("relatorio_bdo"))
        self.assertEqual(resp.status_code, 200)
        [boletim] = resp.context["boletins"]
        self.assertEqual((boletim.quantidade_municipios, boletim.quantidade_ineps), (4, 8))
        self.assertEqual(boletim.valor_total, Decimal("32605.94"))
        self.assertContains(resp, '<th class="px-4 py-2">Boletim de desempenho</th>', html=False)
        self.assertContains(resp, ">3658</span>")
        self.assertContains(resp, f'href="{reverse("bdo")}?boletim=3658"')
        self.assertContains(resp, 'enctype="multipart/form-data"')

    def test_relatorio_bdo_aparece_no_menu_administrador(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("relatorio_bdo"))
        self.assertContains(resp, f'href="{reverse("relatorio_bdo")}"')

    def test_administrador_importa_pela_tela(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("relatorio_bdo"), {"tipo": "RI", "mes_referencia": "2026-09", "arquivo": _planilha(LINHAS_3658)}, follow=True)
        self.assertRedirects(resp, reverse("relatorio_bdo"))
        self.assertContains(resp, "Boletim 3658 (RI) importado: 4 município(s), 8 INEP(s).")
        self.assertEqual(InepBdo.objects.count(), 8)

    def test_importacao_grava_o_mes_de_referencia_e_exige_o_campo(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("relatorio_bdo"), {"tipo": "RI", "arquivo": _planilha(LINHAS_3658)}, follow=True)
        self.assertContains(resp, "Informe o mês de referência da planilha.")
        self.assertFalse(BoletimBdo.objects.exists())
        self.client.post(
            reverse("relatorio_bdo"), {"tipo": "RI", "mes_referencia": "2026-09", "arquivo": _planilha(LINHAS_3658)},
        )
        self.assertEqual(BoletimBdo.objects.get().mes_referencia, datetime.date(2026, 9, 1))
        resp = self.client.get(reverse("relatorio_bdo"))
        self.assertContains(resp, 'value="2026-09"')

    def test_administrador_altera_o_mes_de_referencia_de_boletim_ja_importado(self):
        self._importar()
        boletim = BoletimBdo.objects.get()
        self.assertIsNone(boletim.mes_referencia)
        url = reverse("bdo_mes_referencia", args=[boletim.pk])
        self.client.force_login(self.admin)
        resp = self.client.post(url, {"mes_referencia": "2026-08"}, follow=True)
        self.assertRedirects(resp, reverse("relatorio_bdo"))
        self.assertContains(resp, "Boletim 3658: mês de referência 08/2026.")
        boletim.refresh_from_db()
        self.assertEqual(boletim.mes_referencia, datetime.date(2026, 8, 1))
        resp = self.client.post(url, {"mes_referencia": "agosto"}, follow=True)
        self.assertContains(resp, "Informe o mês de referência no formato mês/ano.")
        boletim.refresh_from_db()
        self.assertEqual(boletim.mes_referencia, datetime.date(2026, 8, 1))

    def test_so_administrador_altera_o_mes_de_referencia(self):
        self._importar()
        url = reverse("bdo_mes_referencia", args=[BoletimBdo.objects.get().pk])
        self.client.force_login(self.analista)
        self.assertEqual(self.client.post(url, {"mes_referencia": "2026-08"}).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertIsNone(BoletimBdo.objects.get().mes_referencia)

    def test_importacao_grava_o_tipo_escolhido(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("relatorio_bdo"), {"tipo": "RE", "mes_referencia": "2026-09", "arquivo": _planilha(LINHAS_3658)})
        self.assertEqual(BoletimBdo.objects.get().tipo, "RE")
        resp = self.client.get(reverse("relatorio_bdo"))
        self.assertContains(resp, ">RE</span>")

    def test_relatorio_bdo_filtra_os_boletins_por_tipo(self):
        self._importar(tipo="RI")
        self._importar([_linha("3700", "ITU", "SP", "5,00", "35099999")], tipo="RE")
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("relatorio_bdo"), {"tipo": "re"})
        self.assertEqual([boletim.numero for boletim in resp.context["boletins"]], ["3700"])
        resp = self.client.get(reverse("relatorio_bdo"), {"tipo": "XX"})
        self.assertEqual(len(resp.context["boletins"]), 2)
        BoletimBdo.objects.filter(tipo="RI").delete()
        resp = self.client.get(reverse("relatorio_bdo"), {"tipo": "RI"})
        self.assertContains(resp, "Nenhum Boletim RI importado.")

    def test_importacao_sem_tipo_ou_com_tipo_invalido_e_recusada(self):
        self.client.force_login(self.admin)
        for dados in ({"mes_referencia": "2026-09"}, {"tipo": "XX", "mes_referencia": "2026-09"}):
            with self.subTest(dados=dados):
                resp = self.client.post(
                    reverse("relatorio_bdo"), {**dados, "arquivo": _planilha(LINHAS_3658)}, follow=True,
                )
                self.assertContains(resp, "Não foi possível importar")
        self.assertFalse(BoletimBdo.objects.exists())

    def test_tipo_aparece_no_filtro_de_boletim_e_na_coluna_sem_filtro_proprio(self):
        self._importar(tipo="RI")
        self._importar([_linha("3700", "ITU", "SP", "5,00", "35099999")], tipo="RE")
        self.client.force_login(self.analista)
        resp = self.client.get(reverse("bdo"), {"agrupar": "uf"})
        self.assertContains(resp, "3700 — RE")
        self.assertContains(resp, "3658 — RI")
        self.assertEqual({linha["tipo"] for linha in resp.context["page_obj"]}, {"RE", "RI"})
        self.assertNotContains(resp, 'name="tipo"')

    def test_importacao_invalida_mostra_erro_e_nao_grava(self):
        self.client.force_login(self.admin)
        planilha = _planilha([_linha("3658", "ATIBAIA", "SP", "277,89", "")])
        resp = self.client.post(reverse("relatorio_bdo"), {"tipo": "RI", "mes_referencia": "2026-09", "arquivo": planilha}, follow=True)
        self.assertContains(resp, "Não foi possível importar")
        self.assertFalse(BoletimBdo.objects.exists())

    def test_reenviar_boletim_ja_importado_mostra_erro_pela_tela(self):
        self._importar()
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("relatorio_bdo"), {"tipo": "RI", "mes_referencia": "2026-09", "arquivo": _planilha(LINHAS_3658[:1])}, follow=True)
        self.assertContains(resp, "Boletim de desempenho já importado: 3658")
        self.assertEqual(InepBdo.objects.count(), 8)

    def test_analista_ve_o_grid_mas_nao_acessa_o_relatorio_bdo(self):
        self.client.force_login(self.analista)
        self.assertEqual(self.client.get(reverse("relatorio_bdo")).status_code, 403)
        resp = self.client.post(reverse("relatorio_bdo"), {"tipo": "RI", "mes_referencia": "2026-09", "arquivo": _planilha(LINHAS_3658)})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(BoletimBdo.objects.exists())
        self.assertNotContains(self.client.get(reverse("bdo")), f'href="{reverse("relatorio_bdo")}"')

    def test_visualizador_e_bloqueado_e_nao_ve_o_link(self):
        visualizador = User.objects.create_user(
            username="bdo-visualizador", password="senha-teste-123", perfil=User.PERFIL_VISUALIZADOR,
        )
        self.client.force_login(visualizador)
        self.assertRedirects(self.client.get(reverse("bdo")), reverse("grid_inep"))
        resp = self.client.post(reverse("relatorio_bdo"), {"tipo": "RI", "mes_referencia": "2026-09", "arquivo": _planilha(LINHAS_3658)})
        self.assertRedirects(resp, reverse("grid_inep"))
        self.assertFalse(BoletimBdo.objects.exists())
        self.assertNotContains(self.client.get(reverse("grid_inep")), f'href="{reverse("bdo")}"')


class RecebiveisBdoTests(TestCase):
    """Modal "Recebíveis" da tela BDO (pedido do usuário, 2026-10-14): só
    montagem, nada é gravado; retirar é por município, nunca por INEP."""

    def setUp(self):
        self.admin = User.objects.create_user(
            username="receb-admin", password="senha-teste-123", perfil=User.PERFIL_ADMINISTRADOR,
        )
        self.analista = User.objects.create_user(
            username="receb-analista", password="senha-teste-123", perfil=User.PERFIL_ANALISTA,
        )
        importar_planilha_bdo(ler_planilha_bdo(_planilha(LINHAS_3658)), "RI", "FR_3658.xlsx", self.admin)
        # Campo Grande repetido no Boletim 3700: já vem rateado pelo cliente.
        importar_planilha_bdo(ler_planilha_bdo(_planilha([
            _linha("3700", "Campo Grande", "MS", "100,00", "50031287, 50005111"),
            _linha("3700", "CAMPO GRANDE", "MS", "50,00", "50033433"),
            _linha("3700", "ITU", "SP", "5,00", "35099999"),
        ])), "RE", "FR_3700.xlsx", self.admin)
        self.client.force_login(self.analista)

    def _post(self, **dados):
        return self.client.post(reverse("bdo_recebiveis"), dados)

    def _id(self, boletim, municipio, valor_total):
        return MunicipioBdo.objects.get(
            boletim__numero=boletim, municipio=municipio, valor_total=Decimal(valor_total),
        ).pk

    def test_tela_bdo_tem_o_botao_e_o_modal_sem_boletim_escolhido(self):
        resp = self.client.get(reverse("bdo"))
        self.assertContains(resp, 'data-abrir-modal-email="modal-recebiveis"')
        self.assertContains(resp, "Escolha um ou mais Boletins")
        self.assertEqual(resp.context["recebiveis_valor_total"], Decimal("0"))

    def test_escolher_mais_de_um_boletim_traz_todas_as_linhas(self):
        resp = self._post(boletim=["3658", "3700"])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context["recebiveis_linhas"]), 7)
        self.assertEqual(resp.context["recebiveis_quantidade_ineps"], 12)
        self.assertEqual(resp.context["recebiveis_valor_total"], Decimal("32760.94"))
        self.assertContains(resp, "50005111, 50028340, 50031287, 50033433")

    def test_retirar_municipio_tira_o_valor_e_os_ineps_e_voltar_devolve(self):
        brasilia = self._id("3658", "Brasília", "31183.68")
        resp = self._post(boletim="3658", retirar=str(brasilia))
        self.assertEqual(resp.context["recebiveis_valor_total"], Decimal("1422.26"))
        self.assertEqual(resp.context["recebiveis_quantidade_ineps"], 6)
        self.assertContains(resp, f'name="retirado" value="{brasilia}"')
        # O estado volta no formulário: o retirado continua fora na próxima mudança.
        resp = self._post(boletim="3658", retirado=str(brasilia), visao="boletim")
        self.assertEqual(resp.context["recebiveis_valor_total"], Decimal("1422.26"))
        resp = self._post(boletim="3658", retirado=str(brasilia), restaurar=str(brasilia))
        self.assertEqual(resp.context["recebiveis_valor_total"], Decimal("32605.94"))
        resp = self._post(boletim="3658", retirado=str(brasilia), restaurar="todos")
        self.assertEqual(resp.context["recebiveis_retirados"], [])

    def test_linha_repetida_do_municipio_e_independente(self):
        rateio = self._id("3700", "CAMPO GRANDE", "50.00")
        resp = self._post(boletim="3700", retirar=str(rateio))
        self.assertEqual(resp.context["recebiveis_valor_total"], Decimal("105.00"))
        self.assertEqual(resp.context["recebiveis_quantidade_ineps"], 3)

    def test_agrupar_por_municipio_soma_as_linhas_repetidas_dentro_de_cada_boletim(self):
        resp = self._post(boletim=["3658", "3700"], visao="municipio")
        grupos = {(g["boletim"].numero, g["municipio"]): g for g in resp.context["recebiveis_grupos"]}
        self.assertEqual(grupos[("3700", "CAMPO GRANDE")]["valor_total"], Decimal("150.00"))
        self.assertEqual(grupos[("3700", "CAMPO GRANDE")]["quantidade_ineps"], 3)
        self.assertEqual(grupos[("3658", "CAMPO GRANDE")]["valor_total"], Decimal("1094.45"))
        # "Retirar" no agrupado tira todas as linhas do município naquele Boletim.
        resp = self._post(boletim="3700", visao="municipio", retirar=grupos[("3700", "CAMPO GRANDE")]["ids"])
        self.assertEqual(resp.context["recebiveis_valor_total"], Decimal("5.00"))
        self.assertEqual(len(resp.context["recebiveis_retirados"]), 2)

    def test_por_boletim_mostra_o_total_de_cada_boletim(self):
        resp = self._post(boletim=["3658", "3700"], visao="boletim")
        totais = {g["boletim"].numero: (g["valor_total"], g["quantidade_municipios"]) for g in resp.context["recebiveis_grupos"]}
        self.assertEqual(totais, {"3658": (Decimal("32605.94"), 4), "3700": (Decimal("155.00"), 2)})

    def test_nao_tem_retirar_por_inep_nem_adicionar_inep(self):
        resp = self._post(boletim="3658")
        self.assertNotContains(resp, 'name="inep"')
        self.assertNotContains(resp, 'name="retirar_inep"')

    def test_retirado_de_boletim_desmarcado_e_id_invalido_sao_ignorados(self):
        itu = self._id("3700", "ITU", "5.00")
        resp = self._post(boletim="3658", retirado=[str(itu), "abc", "999999"], visao="xx")
        self.assertEqual(resp.context["recebiveis_retirados"], [])
        self.assertEqual(resp.context["recebiveis_visao"], "linhas")
        self.assertEqual(resp.context["recebiveis_valor_total"], Decimal("32605.94"))

    def test_nada_e_gravado(self):
        antes = (BoletimBdo.objects.count(), MunicipioBdo.objects.count(), InepBdo.objects.count())
        self._post(boletim=["3658", "3700"], retirar=str(self._id("3700", "ITU", "5.00")))
        self.assertEqual((BoletimBdo.objects.count(), MunicipioBdo.objects.count(), InepBdo.objects.count()), antes)

    def test_anonimo_vai_pro_login_e_visualizador_e_bloqueado(self):
        self.client.logout()
        resp = self._post(boletim="3658")
        self.assertIn(reverse("login"), resp["Location"])
        visualizador = User.objects.create_user(
            username="receb-visualizador", password="senha-teste-123", perfil=User.PERFIL_VISUALIZADOR,
        )
        self.client.force_login(visualizador)
        self.assertRedirects(self._post(boletim="3658"), reverse("grid_inep"))


class ImportarAssinaturaReTests(TestCase):
    def _planilha(self, linhas):
        workbook = openpyxl.Workbook()
        aba = workbook.active
        aba.title = "FATURAMENTO BDO"
        aba.append(("EACE - APRENDER CONECTADO",))
        aba.append(("LOTE", "UF ", "MUNICIPIO", "INEP", "ASSINATURA MENSAL R.E", "MANUTENÇÃO R.I MENSAL"))
        for linha in linhas:
            aba.append(linha)
        pasta = tempfile.mkdtemp()
        caminho = Path(pasta) / "CONSOLIDADO EACE Atualizado.xlsx"
        workbook.save(caminho)
        return str(caminho)

    def test_grava_a_assinatura_e_substitui_a_anterior(self):
        americana = Escola.objects.create(inep="35058592", nome="Americana", valor_assinatura_re=Decimal("1.00"))
        atibaia = Escola.objects.create(inep="35011006", nome="Atibaia")
        saida = io.StringIO()
        call_command("importar_assinatura_re", self._planilha([
            (9, "SP", "Americana", 35058592, 760, 380.38),
            (11, "TO", "Atibaia", "35011006", "370,50", 365.62),
            (9, "SP", "Lins", 35005434, 360, 380.38),
            (9, "SP", "Itu", 35099999, None, 380.38),
        ]), stdout=saida)
        americana.refresh_from_db()
        atibaia.refresh_from_db()
        self.assertEqual(americana.valor_assinatura_re, Decimal("760.00"))
        self.assertEqual(atibaia.valor_assinatura_re, Decimal("370.50"))
        self.assertFalse(Escola.objects.filter(inep="35005434").exists())
        self.assertIn("2 escola(s) atualizada(s), 1 INEP(s) sem escola no sistema, 1 linha(s)", saida.getvalue())
