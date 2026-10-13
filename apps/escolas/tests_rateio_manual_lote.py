"""Rateio manual do LOTE (pedido do usuário, 2026-10-13): no modal "Revisar
INEPs do LOTE", o valor total de um INEP é dividido em N partes (Cidade +
valor); cada parte vira uma planilha de faturamento própria. A soma nunca
pode ser menor nem maior que o valor total do INEP."""
import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.escolas.models import Lote
from apps.escolas.services import (
    LoteMipError,
    criar_lote_mip,
    nome_arquivo_planilha_faturamento_implantacao,
    planilhas_faturamento_implantacao_lote,
)
from apps.escolas.tests import _criar_escola_elegivel_lote, _criar_escola_rateada_lote
from apps.ri.models import KitPadrao

User = get_user_model()


class _BaseRateioManual(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user(username="analista-rateio", password="senha-teste-123")
        KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 2 Access Points", lote=9,
            valor_equipamento="1000.00", valor_servico="300.00",
        )

    def _criar(self, escolas, rateio_manual):
        return criar_lote_mip(
            "GO", "Abadiânia", None, None, self.usuario,
            escola_ids=[escola.pk for escola in escolas], rateio_manual=rateio_manual,
        )


class CriarLoteRateioManualTests(_BaseRateioManual):
    """Validação e gravação do rateio em `criar_lote_mip` (valor total do
    INEP da fixture = R$ 300,00)."""

    def test_rateio_valido_e_gravado_no_lote(self):
        escola, _ri = _criar_escola_elegivel_lote("20000001")
        lote = self._criar([escola], {str(escola.pk): [("Abadiânia", "100.50"), ("Brasília", "199,50")]})
        self.assertEqual(
            lote.rateio_manual,
            {"20000001": [{"cidade": "Abadiânia", "valor": "100.50"}, {"cidade": "Brasília", "valor": "199.50"}]},
        )

    def test_soma_menor_que_o_total_nao_cria_lote(self):
        escola, _ri = _criar_escola_elegivel_lote("20000002")
        with self.assertRaisesMessage(LoteMipError, "tem que ser igual"):
            self._criar([escola], {str(escola.pk): [("Abadiânia", "100.00"), ("Brasília", "199.99")]})
        self.assertEqual(Lote.objects.count(), 0)

    def test_soma_maior_que_o_total_nao_cria_lote(self):
        escola, _ri = _criar_escola_elegivel_lote("20000003")
        with self.assertRaisesMessage(LoteMipError, "tem que ser igual"):
            self._criar([escola], {str(escola.pk): [("Abadiânia", "100.00"), ("Brasília", "200.01")]})
        self.assertEqual(Lote.objects.count(), 0)

    def test_menos_de_2_partes_nao_cria_lote(self):
        escola, _ri = _criar_escola_elegivel_lote("20000004")
        with self.assertRaisesMessage(LoteMipError, "ao menos 2 partes"):
            self._criar([escola], {str(escola.pk): [("Abadiânia", "300.00")]})
        self.assertEqual(Lote.objects.count(), 0)

    def test_parte_sem_cidade_nao_cria_lote(self):
        escola, _ri = _criar_escola_elegivel_lote("20000005")
        with self.assertRaisesMessage(LoteMipError, "informe a Cidade da parte 2"):
            self._criar([escola], {str(escola.pk): [("Abadiânia", "150.00"), ("  ", "150.00")]})
        self.assertEqual(Lote.objects.count(), 0)

    def test_parte_com_valor_zero_ou_invalido_nao_cria_lote(self):
        escola, _ri = _criar_escola_elegivel_lote("20000006")
        for valor in ("0", "-10", "abc", "", "NaN"):
            with self.subTest(valor=valor), self.assertRaises(LoteMipError):
                self._criar([escola], {str(escola.pk): [("Abadiânia", "300.00"), ("Brasília", valor)]})
        self.assertEqual(Lote.objects.count(), 0)

    def test_valor_com_mais_de_2_casas_nao_cria_lote(self):
        escola, _ri = _criar_escola_elegivel_lote("20000007")
        with self.assertRaisesMessage(LoteMipError, "mais de 2 casas"):
            self._criar([escola], {str(escola.pk): [("Abadiânia", "150.005"), ("Brasília", "149.995")]})

    def test_cidade_com_caractere_invalido_nao_cria_lote(self):
        escola, _ri = _criar_escola_elegivel_lote("20000008")
        with self.assertRaisesMessage(LoteMipError, "é inválida"):
            self._criar([escola], {str(escola.pk): [("Abadiânia", "150.00"), ("Bras/ília", "150.00")]})

    def test_inep_com_rateio_automatico_nao_aceita_rateio_manual(self):
        escola, _ri = _criar_escola_rateada_lote("20000009")
        with self.assertRaisesMessage(LoteMipError, "rateio automático"):
            self._criar([escola], {str(escola.pk): [("Abadiânia", "150.00"), ("Brasília", "150.00")]})
        self.assertEqual(Lote.objects.count(), 0)

    def test_rateio_de_inep_desmarcado_e_ignorado(self):
        escola, _ri = _criar_escola_elegivel_lote("20000010")
        escola_desmarcada, _ri2 = _criar_escola_elegivel_lote("20000011")
        lote = self._criar([escola], {str(escola_desmarcada.pk): [("Abadiânia", "1.00"), ("Brasília", "1.00")]})
        self.assertEqual(lote.rateio_manual, {})

    def test_sem_rateio_lote_nasce_com_rateio_vazio(self):
        escola, _ri = _criar_escola_elegivel_lote("20000012")
        lote = self._criar([escola], None)
        self.assertEqual(lote.rateio_manual, {})


class PlanilhasRateioManualTests(_BaseRateioManual):
    """Cada parte do rateio manual vira 1 planilha só dela."""

    data_envio = datetime.date(2026, 10, 13)

    def test_cada_parte_gera_1_planilha_com_o_valor_da_parte(self):
        escola_normal, _ri = _criar_escola_elegivel_lote("20000020")
        escola_rateada, _ri2 = _criar_escola_elegivel_lote("20000021")
        lote = self._criar(
            [escola_normal, escola_rateada],
            {str(escola_rateada.pk): [("Abadiânia", "100.00"), ("Abadiânia", "50.00"), ("Brasília", "150.00")]},
        )

        planilhas = planilhas_faturamento_implantacao_lote(lote, self.data_envio)

        self.assertEqual(len(planilhas), 4)
        nomes = [nome for nome, _wb in planilhas]
        self.assertEqual(nomes[0], nome_arquivo_planilha_faturamento_implantacao(lote))
        # Planilha do Município do LOTE: só o INEP sem rateio manual.
        self.assertEqual(planilhas[0][1].worksheets[0]["H10"].value, 300.00)
        self.assertEqual(len(set(nomes)), 4)
        self.assertIn("(RATEIO 20000021 1-3)", nomes[1])
        self.assertIn("(RATEIO 20000021 3-3)", nomes[3])
        self.assertIn("Brasília", nomes[3])
        valores = [wb.worksheets[0]["H10"].value for _nome, wb in planilhas[1:]]
        self.assertEqual(valores, [100.00, 50.00, 150.00])
        self.assertEqual(sum(Decimal(str(v)) for v in valores), Decimal("300.00"))

    def test_lote_com_todos_os_ineps_rateados_nao_gera_planilha_vazia_do_municipio(self):
        escola, _ri = _criar_escola_elegivel_lote("20000022")
        lote = self._criar([escola], {str(escola.pk): [("Abadiânia", "120.00"), ("Brasília", "180.00")]})

        planilhas = planilhas_faturamento_implantacao_lote(lote, self.data_envio)

        self.assertEqual(len(planilhas), 2)
        self.assertTrue(all("RATEIO 20000022" in nome for nome, _wb in planilhas))


class MipLoteCriarViewRateioManualTests(_BaseRateioManual):
    """POST do modal com os campos `rateio_cidade_<pk>`/`rateio_valor_<pk>`."""

    def test_post_com_rateio_valido_cria_lote_com_rateio(self):
        escola, _ri = _criar_escola_elegivel_lote("20000030")
        self.client.force_login(self.usuario)
        resp = self.client.post(
            reverse("mip_lote_criar"),
            {
                "estado": "GO", "municipio": "Abadiânia", "escola_ids": [str(escola.pk)],
                f"rateio_cidade_{escola.pk}": ["Abadiânia", "Brasília"],
                f"rateio_valor_{escola.pk}": ["200.00", "100.00"],
            },
        )
        self.assertRedirects(resp, reverse("mip_lote_inep"))
        lote = Lote.objects.get()
        self.assertEqual(len(lote.rateio_manual["20000030"]), 2)

    def test_post_com_soma_errada_mostra_erro_e_nao_cria(self):
        escola, _ri = _criar_escola_elegivel_lote("20000031")
        self.client.force_login(self.usuario)
        resp = self.client.post(
            reverse("mip_lote_criar"),
            {
                "estado": "GO", "municipio": "Abadiânia", "escola_ids": [str(escola.pk)],
                f"rateio_cidade_{escola.pk}": ["Abadiânia", "Brasília"],
                f"rateio_valor_{escola.pk}": ["200.00", "50.00"],
            },
            follow=True,
        )
        self.assertEqual(Lote.objects.count(), 0)
        self.assertContains(resp, "tem que ser igual ao valor total")

    def test_post_com_menos_valores_que_cidades_mostra_erro(self):
        escola, _ri = _criar_escola_elegivel_lote("20000032")
        self.client.force_login(self.usuario)
        self.client.post(
            reverse("mip_lote_criar"),
            {
                "estado": "GO", "municipio": "Abadiânia", "escola_ids": [str(escola.pk)],
                f"rateio_cidade_{escola.pk}": ["Abadiânia", "Brasília"],
                f"rateio_valor_{escola.pk}": ["300.00"],
            },
        )
        self.assertEqual(Lote.objects.count(), 0)

    def test_modal_mostra_botao_ratear_so_para_inep_sem_rateio_automatico(self):
        _criar_escola_elegivel_lote("20000033")
        self.client.force_login(self.usuario)
        resp = self.client.get(reverse("mip_inep"), {"estado": "GO", "municipio": "Abadiânia"})
        self.assertContains(resp, "<button type=\"button\" data-toggle-rateio-manual", count=1)
        self.assertContains(resp, 'data-valor-total="300.00"')

    def test_lote_mostra_partes_do_rateio_manual_no_detalhe(self):
        escola, _ri = _criar_escola_elegivel_lote("20000034")
        self._criar([escola], {str(escola.pk): [("Abadiânia", "200.00"), ("Brasília", "100.00")]})
        self.client.force_login(self.usuario)
        resp = self.client.get(reverse("mip_lote_inep"))
        self.assertContains(resp, "Rateio manual (2)")
        self.assertContains(resp, "Brasília: R$ 100,00")


class PlanilhaModeloAusenteTests(_BaseRateioManual):
    """Bug real no servidor EACE (2026-10-13): sem o modelo em doc/, o
    "Baixar planilhas (.zip)" dava erro 500 — agora vira mensagem na tela."""

    def test_zip_sem_modelo_mostra_mensagem_em_vez_de_500(self):
        from pathlib import Path
        from unittest.mock import patch

        escola, _ri = _criar_escola_elegivel_lote("20000040")
        lote = self._criar([escola], None)
        self.client.force_login(self.usuario)
        with patch(
            "apps.escolas.services.CAMINHO_PLANILHA_FATURAMENTO_IMPLANTACAO_MODELO", Path("/nao/existe.xlsx")
        ):
            resp = self.client.post(reverse("mip_lote_baixar_planilhas_zip"), {"lote_ids": [lote.pk]}, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Planilha-modelo de faturamento de implantação não encontrada")
