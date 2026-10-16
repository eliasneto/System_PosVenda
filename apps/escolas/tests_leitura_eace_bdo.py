"""Leitura EACE do BDO (`leitura_eace_bdo.py`) e coluna "Portal EACE" do
grid Por Município - o RPA do BDO fica mockado, sem navegador nem rede."""

from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.escolas.bdo import importar_planilha_bdo, ler_planilha_bdo
from apps.escolas.leitura_eace_bdo import (
    aplicar_cards_no_boletim,
    enfileirar_leitura_eace_bdo,
    processar_proxima_leitura_eace_bdo,
)
from apps.escolas.models import BoletimBdo, LeituraEaceBdo, MunicipioBdo
from apps.escolas.tests_bdo import LINHAS_3658, _planilha
from apps.integracoes.eace.rpa_mip import ResultadoRpaMip

User = get_user_model()


def _card(municipio, uf, status="Aprovado", valor="1.094,45", arquivo="504_13-10-2026_NOME_MEGA INFRA.pdf"):
    return {"posicao": 0, "municipio": municipio, "uf": uf, "ibge": "", "status": status, "valor": valor,
            "arquivo": arquivo}


class LeituraEaceBdoTests(TestCase):

    def setUp(self):
        self.admin = User.objects.create_user(
            username="bdo-eace", password="senha-teste-123", perfil=User.PERFIL_ADMINISTRADOR,
        )
        importar_planilha_bdo(ler_planilha_bdo(_planilha(LINHAS_3658)), "RI", "FR_3658.xlsx", self.admin)
        self.boletim = BoletimBdo.objects.get(numero="3658")

    def _municipio(self, nome):
        return MunicipioBdo.objects.get(boletim=self.boletim, municipio=nome)

    def test_grava_o_card_no_municipio_de_mesmo_nome_e_uf_sem_acento(self):
        atualizados, sobras = aplicar_cards_no_boletim(self.boletim, [
            _card("CAMPO GRANDE", "MS"),
            _card("Atibaia", "SP", status="Pendente", valor="277,89", arquivo=""),
            _card("Campo Grande", "PB", valor="1,00"),
        ])
        self.assertEqual(atualizados, 2)
        self.assertEqual(sobras, ["Campo Grande/PB"])
        campo_grande = self._municipio("Campo Grande")
        self.assertEqual(campo_grande.status_eace, "Aprovado")
        self.assertEqual(campo_grande.valor_eace, Decimal("1094.45"))
        self.assertEqual(campo_grande.arquivo_nf_eace, "504_13-10-2026_NOME_MEGA INFRA.pdf")
        self.assertEqual(self._municipio("ATIBAIA").status_eace, "Pendente")
        americana = self._municipio("AMERICANA")
        self.assertEqual(americana.status_eace, "")
        self.assertIsNotNone(americana.eace_lido_em)

    def test_mesmo_municipio_em_2_cards_usa_o_de_valor_igual_ao_da_planilha(self):
        aplicar_cards_no_boletim(self.boletim, [
            _card("Campo Grande", "MS", valor="10,00", status="Pendente"),
            _card("Campo Grande", "MS", valor="1.094,45"),
        ])
        self.assertEqual(self._municipio("Campo Grande").status_eace, "Aprovado")

    def test_enfileirar_reaproveita_a_leitura_em_andamento_do_boletim(self):
        primeira, criada = enfileirar_leitura_eace_bdo(self.boletim, self.admin)
        segunda, criada_de_novo = enfileirar_leitura_eace_bdo(self.boletim, self.admin)
        self.assertTrue(criada)
        self.assertFalse(criada_de_novo)
        self.assertEqual(primeira.pk, segunda.pk)

    def test_processar_le_o_portal_e_grava_os_municipios(self):
        enfileirar_leitura_eace_bdo(self.boletim, self.admin)
        resultado = ResultadoRpaMip(sucesso=True, pedido="3658", simulado=True,
                                    cards_encontrados=[_card("Campo Grande", "MS")])
        with patch("apps.integracoes.eace.rpa_bdo.ler_cards_bdo", return_value=resultado) as ler:
            leitura = processar_proxima_leitura_eace_bdo()
        ler.assert_called_once()
        self.assertEqual(ler.call_args.args[0], "3658")
        self.assertEqual(leitura.status, LeituraEaceBdo.SUCESSO)
        self.assertEqual((leitura.cards_lidos, leitura.municipios_atualizados), (1, 1))
        self.assertEqual(self._municipio("Campo Grande").status_eace, "Aprovado")

    def test_erro_do_portal_nao_apaga_a_leitura_anterior(self):
        aplicar_cards_no_boletim(self.boletim, [_card("Campo Grande", "MS")])
        enfileirar_leitura_eace_bdo(self.boletim, self.admin)
        resultado = ResultadoRpaMip(sucesso=False, motivo="pedido_nao_encontrado", pedido="3658")
        with patch("apps.integracoes.eace.rpa_bdo.ler_cards_bdo", return_value=resultado):
            leitura = processar_proxima_leitura_eace_bdo()
        self.assertEqual(leitura.status, LeituraEaceBdo.ERRO)
        self.assertEqual(leitura.motivo_erro, "pedido_nao_encontrado")
        self.assertEqual(self._municipio("Campo Grande").status_eace, "Aprovado")

    def test_worker_da_fila_eace_processa_a_leitura_com_os_envios_vazios(self):
        enfileirar_leitura_eace_bdo(self.boletim, self.admin)
        resultado = ResultadoRpaMip(sucesso=True, pedido="3658", simulado=True, cards_encontrados=[])
        saida = StringIO()
        with patch("apps.integracoes.eace.rpa_bdo.ler_cards_bdo", return_value=resultado), \
                patch("apps.ri.management.commands.processar_fila_rpa_eace.processar_proxima_validacao_nf_mip") as mip:
            call_command("processar_fila_rpa_eace", stdout=saida)
        self.assertIn("Leitura EACE do BDO", saida.getvalue())
        mip.assert_not_called()

    def test_botao_enfileira_e_volta_para_o_grid(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("bdo_leitura_eace", args=[self.boletim.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("boletim=3658", resp["Location"])
        self.assertEqual(LeituraEaceBdo.objects.filter(boletim=self.boletim).count(), 1)

    def test_botao_so_por_post(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("bdo_leitura_eace", args=[self.boletim.pk])).status_code, 405)

    def test_status_em_andamento_faz_polling_e_recarrega_ao_terminar(self):
        self.client.force_login(self.admin)
        leitura, _ = enfileirar_leitura_eace_bdo(self.boletim, self.admin)
        url = reverse("bdo_leitura_eace_status", args=[self.boletim.pk])
        self.assertContains(self.client.get(url, {"acompanhando": "1"}), "every 3s")
        leitura.status = LeituraEaceBdo.SUCESSO
        leitura.save()
        resp = self.client.get(url, {"acompanhando": "1"})
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(resp["HX-Refresh"], "true")

    def test_grid_por_municipio_mostra_o_card_do_portal(self):
        aplicar_cards_no_boletim(self.boletim, [_card("Campo Grande", "MS", valor="1.100,00")])
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("bdo"), {"agrupar": "municipio", "boletim": "3658"})
        self.assertContains(resp, "Atualizar do portal EACE")
        self.assertContains(resp, "504_13-10-2026_NOME_MEGA INFRA.pdf")
        self.assertContains(resp, "Sem card no portal")
        linha = next(l for l in resp.context["page_obj"] if l["municipio"] == "CAMPO GRANDE")
        self.assertEqual(linha["status_eace"], "Aprovado")
        self.assertEqual(linha["diferenca_eace"], Decimal("5.55"))

    def test_grid_sem_leitura_mostra_nao_lido(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("bdo"), {"agrupar": "municipio"})
        self.assertContains(resp, "Não lido")
        self.assertNotContains(resp, reverse("bdo_leitura_eace", args=[self.boletim.pk]))

    def test_excel_por_municipio_tem_as_colunas_do_portal(self):
        import openpyxl
        from io import BytesIO

        aplicar_cards_no_boletim(self.boletim, [_card("Campo Grande", "MS")])
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("bdo"), {"agrupar": "municipio", "exportar": "excel"})
        aba = openpyxl.load_workbook(BytesIO(resp.content)).active
        titulos = [celula.value for celula in aba[1]]
        self.assertIn("Status EACE", titulos)
        self.assertIn("Arquivo da NF (EACE)", titulos)
