"""LOTE reprovado pelo cliente (pedido do usuário, 2026-10-15): só o
Administrador reprova um LOTE em "Processo Concluído", com motivo; os
valores saem dos relatórios de faturamento e só aparecem no filtro
"Reprovado" do MIP (LOTE); as NFs ficam guardadas no LOTE reprovado e os
INEPs podem entrar num LOTE novo para refaturar."""

import shutil
import tempfile
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.escolas.models import Escola, Lote, NotaFiscalMip
from apps.escolas.rpa_mip_lote import EnvioRpaMipRecusado, enfileirar_rpa_mip_lote
from apps.escolas.services import (
    LoteMipError,
    aplicar_status_lote_mip,
    criar_lote_mip,
    desfazer_reprovacao_lote_mip,
    escolas_elegiveis_lote_mip,
    escolas_no_grid_mip,
    montar_dashboard_faturamento_mip,
    reprovar_lote_mip,
)
from apps.escolas.tests import _criar_escola_elegivel_lote
from apps.ri.models import KitPadrao, RiHistorico

User = get_user_model()
_MEDIA_ROOT = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class LoteReprovadoTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin-reprovado", password="senha-teste-123", perfil=User.PERFIL_ADMINISTRADOR,
        )
        self.analista = User.objects.create_user(
            username="analista-reprovado", password="senha-teste-123", perfil=User.PERFIL_ANALISTA,
        )
        KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 2 Access Points", lote=9,
            valor_equipamento="1000.00", valor_servico="300.00",
        )
        self.escola1, self.ri1 = _criar_escola_elegivel_lote("10000501")
        self.escola2, _ri2 = _criar_escola_elegivel_lote("10000502")
        self.lote = criar_lote_mip("GO", "Abadiânia", None, None, self.admin)
        aplicar_status_lote_mip(self.lote, Lote.FATURAMENTO_CONCLUIDO, self.admin)
        self.nota1 = self.escola1.adicionar_ou_substituir_nota_fiscal_mip(b"%PDF-1", "615_NF.pdf")
        self.nota2 = self.escola2.adicionar_ou_substituir_nota_fiscal_mip(b"%PDF-1", "615_NF.pdf")

    def _recarregar(self):
        for objeto in (self.lote, self.escola1, self.escola2, self.nota1, self.nota2):
            objeto.refresh_from_db()

    # --- regra (service) -------------------------------------------------

    def test_reprovar_muda_lote_e_ineps_guarda_motivo_e_nfs(self):
        reprovar_lote_mip(self.lote, "  Cliente recusou o valor  ", self.admin)
        self._recarregar()
        self.assertEqual(self.lote.status, Lote.REPROVADO)
        self.assertEqual(self.lote.motivo_reprovacao, "Cliente recusou o valor")
        self.assertEqual(self.lote.reprovado_por, self.admin)
        self.assertIsNotNone(self.lote.reprovado_em)
        self.assertEqual(self.escola1.status_mip, Escola.REPROVADO_MIP)
        self.assertEqual(self.escola2.status_mip, Escola.REPROVADO_MIP)
        self.assertEqual(self.nota1.lote_reprovado, self.lote)
        self.assertEqual(self.lote.notas_fiscais_da_escola(self.escola1), [self.nota1])
        self.assertTrue(RiHistorico.objects.filter(
            ri=self.ri1, campo="LOTE", valor_novo="Reprovado pelo cliente: Cliente recusou o valor",
        ).exists())
        self.assertTrue(RiHistorico.objects.filter(
            ri=self.ri1, campo="Status (MIP)", valor_anterior="Processo Concluído", valor_novo="Reprovado",
        ).exists())

    def test_so_lote_em_processo_concluido_e_com_motivo(self):
        with self.assertRaisesMessage(LoteMipError, "Informe o motivo"):
            reprovar_lote_mip(self.lote, "   ", self.admin)
        aplicar_status_lote_mip(self.lote, Lote.EM_FATURAMENTO, self.admin)
        with self.assertRaisesMessage(LoteMipError, 'Só LOTE em "Processo Concluído"'):
            reprovar_lote_mip(self.lote, "motivo", self.admin)
        self._recarregar()
        self.assertEqual(self.lote.status, Lote.EM_FATURAMENTO)
        self.assertIsNone(self.nota1.lote_reprovado)

    def test_ineps_reprovados_entram_num_lote_novo_sem_a_nf_antiga(self):
        self.assertEqual(escolas_elegiveis_lote_mip("GO", "Abadiânia", None, None), [])
        reprovar_lote_mip(self.lote, "Cliente recusou", self.admin)
        self.assertEqual(
            {escola.inep for escola in escolas_elegiveis_lote_mip("GO", "Abadiânia", None, None)},
            {"10000501", "10000502"},
        )
        self.assertTrue(escolas_no_grid_mip().filter(pk=self.escola1.pk).exists())

        lote_novo = criar_lote_mip("GO", "Abadiânia", None, None, self.admin)
        self.escola1.refresh_from_db()
        self.assertEqual(self.escola1.status_mip, Escola.EM_ANDAMENTO)
        self.assertEqual(lote_novo.notas_fiscais_da_escola(self.escola1), [])
        self.assertEqual(self.lote.notas_fiscais_da_escola(self.escola1), [self.nota1])
        # LOTE novo ativo prende o INEP de novo
        self.assertEqual(escolas_elegiveis_lote_mip("GO", "Abadiânia", None, None), [])
        self.assertFalse(escolas_no_grid_mip().filter(pk=self.escola1.pk).exists())

        # NF nova com o mesmo nome não substitui a guardada no LOTE reprovado
        nova = self.escola1.adicionar_ou_substituir_nota_fiscal_mip(b"%PDF-2", "615_NF.pdf")
        self.assertNotEqual(nova.pk, self.nota1.pk)
        self.assertEqual(lote_novo.notas_fiscais_da_escola(self.escola1), [nova])
        self.assertEqual(NotaFiscalMip.objects.filter(escola=self.escola1).count(), 2)

    def test_desfazer_reprovacao_volta_tudo(self):
        reprovar_lote_mip(self.lote, "Cliente recusou", self.admin)
        desfazer_reprovacao_lote_mip(self.lote, self.admin)
        self._recarregar()
        self.assertEqual(self.lote.status, Lote.FATURAMENTO_CONCLUIDO)
        self.assertEqual(self.lote.motivo_reprovacao, "")
        self.assertIsNone(self.lote.reprovado_por)
        self.assertEqual(self.escola1.status_mip, Escola.FATURAMENTO_CONCLUIDO)
        self.assertIsNone(self.nota1.lote_reprovado)
        self.assertTrue(RiHistorico.objects.filter(ri=self.ri1, campo="LOTE", valor_novo="Reprovação desfeita").exists())

    def test_desfazer_reprovacao_recusa_inep_ja_em_lote_novo(self):
        reprovar_lote_mip(self.lote, "Cliente recusou", self.admin)
        criar_lote_mip("GO", "Abadiânia", None, None, self.admin, escola_ids=[self.escola1.pk])
        with self.assertRaisesMessage(LoteMipError, "INEP(s) já em outro LOTE: 10000501"):
            desfazer_reprovacao_lote_mip(self.lote, self.admin)
        self._recarregar()
        self.assertEqual(self.lote.status, Lote.REPROVADO)

    def test_dashboard_faturamento_mip_nao_soma_reprovado(self):
        antes = montar_dashboard_faturamento_mip()
        self.assertEqual(antes["ineps_concluido"], 2)
        self.assertEqual(antes["total_concluido"], Decimal("600.00"))
        reprovar_lote_mip(self.lote, "Cliente recusou", self.admin)
        depois = montar_dashboard_faturamento_mip()
        self.assertEqual(depois["ineps_concluido"], 0)
        self.assertEqual(depois["total_concluido"], Decimal("0.00"))
        self.assertNotIn(Escola.REPROVADO_MIP, [card["status"] for card in depois["cards"]])

    def test_lote_reprovado_nao_vai_ao_portal(self):
        reprovar_lote_mip(self.lote, "Cliente recusou", self.admin)
        with self.assertRaisesMessage(EnvioRpaMipRecusado, "LOTE reprovado"):
            enfileirar_rpa_mip_lote(self.lote, self.admin)

    # --- telas -----------------------------------------------------------

    def test_administrador_reprova_pela_tela(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("mip_lote_inep"))
        self.assertContains(resp, reverse("mip_lote_reprovar", kwargs={"pk": self.lote.pk}))
        self.assertContains(resp, "Motivo da reprovação")

        resp = self.client.post(
            reverse("mip_lote_reprovar", kwargs={"pk": self.lote.pk}), {"motivo": "Valor divergente"}, follow=True,
        )
        self.assertContains(resp, "reprovado. Os INEPs podem entrar num LOTE novo")
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.status, Lote.REPROVADO)
        self.assertContains(resp, "Valor divergente")
        self.assertContains(resp, reverse("mip_lote_desfazer_reprovacao", kwargs={"pk": self.lote.pk}))

    def test_reprovar_sem_motivo_mostra_erro(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("mip_lote_reprovar", kwargs={"pk": self.lote.pk}), {"motivo": ""}, follow=True)
        self.assertContains(resp, "Informe o motivo da reprovação.")
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.status, Lote.FATURAMENTO_CONCLUIDO)

    def test_analista_nao_reprova_nem_desfaz_nem_ve_o_botao(self):
        self.client.force_login(self.analista)
        resp = self.client.get(reverse("mip_lote_inep"))
        self.assertNotContains(resp, reverse("mip_lote_reprovar", kwargs={"pk": self.lote.pk}))
        resp = self.client.post(reverse("mip_lote_reprovar", kwargs={"pk": self.lote.pk}), {"motivo": "x"})
        self.assertEqual(resp.status_code, 403)
        reprovar_lote_mip(self.lote, "Cliente recusou", self.admin)
        resp = self.client.post(reverse("mip_lote_desfazer_reprovacao", kwargs={"pk": self.lote.pk}))
        self.assertEqual(resp.status_code, 403)
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.status, Lote.REPROVADO)

    def test_administrador_desfaz_pela_tela(self):
        reprovar_lote_mip(self.lote, "Cliente recusou", self.admin)
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("mip_lote_desfazer_reprovacao", kwargs={"pk": self.lote.pk}), follow=True)
        self.assertContains(resp, "Reprovação de")
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.status, Lote.FATURAMENTO_CONCLUIDO)

    def test_troca_de_status_nao_mexe_no_lote_reprovado(self):
        reprovar_lote_mip(self.lote, "Cliente recusou", self.admin)
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("mip_lote_status_update", kwargs={"pk": self.lote.pk}), {"status": Lote.EM_ANDAMENTO}, follow=True,
        )
        self.assertContains(resp, "está reprovado")
        resp = self.client.post(
            reverse("mip_lote_status_em_massa"), {"status": Lote.EM_ANDAMENTO, "lote_ids": [self.lote.pk]}, follow=True,
        )
        self.assertContains(resp, "não foram alterados")
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.status, Lote.REPROVADO)

    def test_tela_mip_lote_tira_o_reprovado_dos_totais_e_mostra_no_filtro(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("mip_lote_inep"))
        self.assertEqual(resp.context["valor_total_todos_status"], Decimal("600.00"))
        reprovar_lote_mip(self.lote, "Cliente recusou", self.admin)

        resp = self.client.get(reverse("mip_lote_inep"))
        self.assertEqual(resp.context["valor_total_todos_status"], Decimal("0.00"))
        self.assertEqual(resp.context["valor_total_geral"], Decimal("0.00"))
        resumo = {item["status"]: item for item in resp.context["resumo_por_status"]}
        self.assertEqual(resumo[Lote.REPROVADO]["valor_total"], Decimal("600.00"))
        self.assertEqual(resumo[Lote.FATURAMENTO_CONCLUIDO]["valor_total"], Decimal("0.00"))

        resp = self.client.get(reverse("mip_lote_inep"), {"status": Lote.REPROVADO})
        self.assertEqual([linha["lote"].pk for linha in resp.context["linhas_lote"]], [self.lote.pk])
        self.assertEqual(resp.context["valor_total_geral"], Decimal("600.00"))
        self.assertContains(resp, "Cliente recusou")

    def test_status_reprovado_nunca_e_escolhido_a_mao_no_inep(self):
        reprovar_lote_mip(self.lote, "Cliente recusou", self.admin)
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("mip_detail", kwargs={"inep": "10000501"}))
        self.assertNotIn(Escola.REPROVADO_MIP, dict(resp.context["status_mip_opcoes"]))
        resp = self.client.post(
            reverse("mip_status_update", kwargs={"inep": "10000502"}), {"status_mip": Escola.REPROVADO_MIP}, follow=True,
        )
        self.assertContains(resp, "Status inválido.")
