"""Testes do envio da NF do LOTE (MIP) ao portal EACE pela fila do RPA EACE
(`apps.escolas.rpa_mip_lote`, botão em "Projeto > MIP (LOTE)", seção MIP da
tela "Projeto > Fila"). O RPA do portal (`anexar_pdf_mip`) é sempre
mockado - nenhum navegador nem rede."""

import shutil
import tempfile
from datetime import timedelta
from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db.models import Prefetch
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.auditoria.models import Auditoria
from apps.core.models import User
from apps.escolas.models import Escola, LogRpaEaceMip, Lote, NotaFiscalMip
from apps.escolas.rpa_mip_lote import (
    EnvioRpaMipRecusado,
    enfileirar_rpa_mip_lote,
    estados_rpa_mip_dos_lotes,
    nota_fiscal_comum_do_lote,
    processar_proximo_rpa_mip,
    recuperar_envios_mip_interrompidos,
)
from apps.integracoes.eace.rpa_mip import ResultadoRpaMip

RPA = "apps.integracoes.eace.rpa_mip.anexar_pdf_mip"
_MEDIA = tempfile.mkdtemp(prefix="test_rpa_mip_lote_")


def _nota(nome):
    return MagicMock(nome_original=nome)


class NotaFiscalComumDoLoteTests(TestCase):

    def test_nf_presente_em_todos_os_ineps(self):
        nota, motivo = nota_fiscal_comum_do_lote([[_nota("A.pdf")], [_nota("A.pdf")]])
        self.assertEqual(nota.nome_original, "A.pdf")
        self.assertEqual(motivo, "")

    def test_inep_rateado_com_nf_de_outro_municipio(self):
        nota, _ = nota_fiscal_comum_do_lote([[_nota("A.pdf"), _nota("OUTRA_CIDADE.pdf")], [_nota("A.pdf")]])
        self.assertEqual(nota.nome_original, "A.pdf")

    def test_inep_sem_nf(self):
        nota, motivo = nota_fiscal_comum_do_lote([[_nota("A.pdf")], []])
        self.assertIsNone(nota)
        self.assertIn("sem Nota Fiscal", motivo)

    def test_nenhuma_nf_comum(self):
        nota, motivo = nota_fiscal_comum_do_lote([[_nota("A.pdf")], [_nota("B.pdf")]])
        self.assertIsNone(nota)
        self.assertIn("Nenhuma Nota Fiscal é comum", motivo)

    def test_mais_de_uma_nf_comum(self):
        nota, motivo = nota_fiscal_comum_do_lote([[_nota("A.pdf"), _nota("B.pdf")], [_nota("A.pdf"), _nota("B.pdf")]])
        self.assertIsNone(nota)
        self.assertIn("2 Notas Fiscais", motivo)

    def test_mesma_nf_gravada_com_nome_diferente_conta_como_1_e_vale_a_mais_recente(self):
        """Dado real (2026-09-29): 2 sincronizações gravaram a mesma NF com
        "_" (24/09) e com espaço (25/09) no nome."""
        antiga = MagicMock(nome_original="377_22-09-2026_NOME_MEGA_INFRA.pdf",
                           sincronizada_em=timezone.now() - timedelta(days=1))
        nova = MagicMock(nome_original="377_22-09-2026_NOME_MEGA INFRA.pdf", sincronizada_em=timezone.now())
        nota, motivo = nota_fiscal_comum_do_lote([[antiga, nova], [nova]])
        self.assertIs(nota, nova)
        self.assertEqual(motivo, "")

    def test_lote_sem_ineps(self):
        nota, motivo = nota_fiscal_comum_do_lote([])
        self.assertIsNone(nota)
        self.assertIn("não tem INEPs", motivo)


@override_settings(MEDIA_ROOT=_MEDIA)
class BaseLoteComNf(TestCase):

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA, ignore_errors=True)

    def setUp(self):
        self.usuario = User.objects.create_user(username="analista", password="senha-teste-123")
        self.escola_a = Escola.objects.create(inep="52000001", nome="ESCOLA A")
        self.escola_b = Escola.objects.create(inep="52000002", nome="ESCOLA B")
        self.lote = Lote.objects.create(estado="GO", municipio="Goiânia")
        self.lote.escolas.set([self.escola_a, self.escola_b])
        for escola in (self.escola_a, self.escola_b):
            self._nf(escola, "377_22-09-2026_NOME_MEGA INFRA.pdf")

    def _nf(self, escola, nome):
        return NotaFiscalMip.objects.create(
            escola=escola, nome_original=nome, sincronizada_em=timezone.now(),
            arquivo=SimpleUploadedFile(nome, b"%PDF-1.4 teste", content_type="application/pdf"),
        )

    def _lote_prefetch(self, lote=None):
        return Lote.objects.prefetch_related(
            Prefetch("escolas", queryset=Escola.objects.prefetch_related("notas_fiscais_mip"))
        ).get(pk=(lote or self.lote).pk)


class EnfileirarRpaMipLoteTests(BaseLoteComNf):

    def test_enfileira_com_a_nf_comum_e_audita(self):
        log = enfileirar_rpa_mip_lote(self._lote_prefetch(), self.usuario)
        self.assertEqual(log.resultado, LogRpaEaceMip.NA_FILA)
        self.assertEqual(log.municipio, "Goiânia")
        self.assertEqual(log.nome_nota_fiscal, "377_22-09-2026_NOME_MEGA INFRA.pdf")
        self.assertEqual(log.solicitado_por, self.usuario)
        self.assertTrue(Auditoria.objects.filter(entidade="Lote", entidade_id=self.lote.pk).exists())

    def test_recusa_enquanto_esta_na_fila(self):
        enfileirar_rpa_mip_lote(self._lote_prefetch(), self.usuario)
        with self.assertRaisesMessage(EnvioRpaMipRecusado, "já está na fila"):
            enfileirar_rpa_mip_lote(self._lote_prefetch(), self.usuario)
        self.assertEqual(LogRpaEaceMip.objects.count(), 1)

    def test_recusa_depois_de_sucesso(self):
        log = enfileirar_rpa_mip_lote(self._lote_prefetch(), self.usuario)
        LogRpaEaceMip.objects.filter(pk=log.pk).update(resultado=LogRpaEaceMip.SUCESSO)
        with self.assertRaisesMessage(EnvioRpaMipRecusado, "já foi enviada"):
            enfileirar_rpa_mip_lote(self._lote_prefetch(), self.usuario)

    def test_depois_de_erro_permite_de_novo(self):
        log = enfileirar_rpa_mip_lote(self._lote_prefetch(), self.usuario)
        LogRpaEaceMip.objects.filter(pk=log.pk).update(resultado=LogRpaEaceMip.ERRO, motivo_erro="valor_divergente")
        enfileirar_rpa_mip_lote(self._lote_prefetch(), self.usuario)
        self.assertEqual(LogRpaEaceMip.objects.filter(resultado=LogRpaEaceMip.NA_FILA).count(), 1)

    def test_recusa_quando_a_nf_ja_estava_no_portal(self):
        log = enfileirar_rpa_mip_lote(self._lote_prefetch(), self.usuario)
        LogRpaEaceMip.objects.filter(pk=log.pk).update(
            resultado=LogRpaEaceMip.ERRO, motivo_erro="documento_ja_enviado", status_portal="Aprovado",
        )
        with self.assertRaisesMessage(EnvioRpaMipRecusado, 'está "Aprovado"'):
            enfileirar_rpa_mip_lote(self._lote_prefetch(), self.usuario)
        self.assertEqual(LogRpaEaceMip.objects.count(), 1)

    def test_recusa_sem_nf_comum(self):
        self.escola_b.notas_fiscais_mip.all().delete()
        with self.assertRaisesMessage(EnvioRpaMipRecusado, "sem Nota Fiscal"):
            enfileirar_rpa_mip_lote(self._lote_prefetch(), self.usuario)
        self.assertFalse(LogRpaEaceMip.objects.exists())


class ProcessarRpaMipTests(BaseLoteComNf):

    def setUp(self):
        super().setUp()
        self.log = enfileirar_rpa_mip_lote(self._lote_prefetch(), self.usuario)

    def _resultado(self, sucesso=True, motivo=None):
        return ResultadoRpaMip(
            sucesso=sucesso, motivo=motivo, pedido="506", valor_portal="27.549,38", dados_pdf={"valor": "27.549,38"},
        )

    def test_fila_vazia(self):
        LogRpaEaceMip.objects.all().delete()
        self.assertIsNone(processar_proximo_rpa_mip())

    def test_sucesso(self):
        with patch(RPA, return_value=self._resultado()) as mock_rpa:
            retorno = processar_proximo_rpa_mip()
        kwargs = mock_rpa.call_args.kwargs
        self.assertEqual(kwargs["municipio"], "Goiânia")
        self.assertTrue(kwargs["caminho_pdf"].endswith(".pdf"))
        self.assertNotIn("simular", kwargs)  # anexa de verdade
        self.log.refresh_from_db()
        self.assertEqual(retorno["resultado"], LogRpaEaceMip.SUCESSO)
        self.assertEqual(self.log.resultado, LogRpaEaceMip.SUCESSO)
        self.assertEqual(self.log.pedido, "506")
        self.assertEqual(self.log.valor_portal, "27.549,38")
        self.assertEqual(self.log.tentativas, 1)

    def test_erro_de_regra_de_negocio_e_definitivo_na_1a_tentativa(self):
        with patch(RPA, return_value=self._resultado(False, "valor_divergente")):
            processar_proximo_rpa_mip()
        self.log.refresh_from_db()
        self.assertEqual(self.log.resultado, LogRpaEaceMip.ERRO)
        self.assertEqual(self.log.motivo_erro, "valor_divergente")

    def test_documento_ja_enviado_grava_o_status_do_card(self):
        resultado = self._resultado(False, "documento_ja_enviado")
        resultado.status_portal = "Aprovado"
        with patch(RPA, return_value=resultado):
            processar_proximo_rpa_mip()
        self.log.refresh_from_db()
        self.assertEqual(self.log.resultado, LogRpaEaceMip.ERRO)
        self.assertEqual(self.log.status_portal, "Aprovado")
        self.assertTrue(self.log.ja_estava_no_portal)
        self.assertEqual(self.log.motivo_erro_legivel, 'O card do município no portal está "Aprovado" (NF já enviada).')

    def test_envio_nao_confirmado_nunca_reprocessa_sozinho(self):
        with patch(RPA, return_value=self._resultado(False, "envio_nao_confirmado")):
            processar_proximo_rpa_mip()
        self.log.refresh_from_db()
        self.assertEqual(self.log.resultado, LogRpaEaceMip.ERRO)

    def test_erro_tecnico_reprocessa_1_vez(self):
        with patch(RPA, return_value=self._resultado(False, "erro_playwright")):
            processar_proximo_rpa_mip()
            self.log.refresh_from_db()
            self.assertEqual(self.log.resultado, LogRpaEaceMip.NA_FILA)
            self.assertEqual(self.log.tentativas, 1)
            processar_proximo_rpa_mip()
        self.log.refresh_from_db()
        self.assertEqual(self.log.resultado, LogRpaEaceMip.ERRO)
        self.assertEqual(self.log.tentativas, 2)

    def test_excecao_inesperada_volta_para_a_fila(self):
        with patch(RPA, side_effect=RuntimeError("boom")):
            processar_proximo_rpa_mip()
        self.log.refresh_from_db()
        self.assertEqual(self.log.resultado, LogRpaEaceMip.NA_FILA)
        self.assertEqual(self.log.motivo_erro, "erro_inesperado")

    def test_nf_apagada_do_sistema(self):
        NotaFiscalMip.objects.all().delete()
        with patch(RPA) as mock_rpa:
            processar_proximo_rpa_mip()
        mock_rpa.assert_not_called()
        self.log.refresh_from_db()
        self.assertEqual(self.log.resultado, LogRpaEaceMip.ERRO)
        self.assertEqual(self.log.motivo_erro, "nota_fiscal_ausente")

    def test_progresso_gravado_durante_a_execucao(self):
        vistos = []

        def rpa_falso(**kwargs):
            kwargs["progresso_callback"]("Anexando o PDF", 86)
            vistos.append(LogRpaEaceMip.objects.values_list("resultado", "etapa_atual", "progresso_pct").get(
                pk=self.log.pk))
            return self._resultado()

        with patch(RPA, side_effect=rpa_falso):
            processar_proximo_rpa_mip()
        self.assertEqual(vistos, [(LogRpaEaceMip.PROCESSANDO, "Anexando o PDF", 86)])

    def test_processando_interrompido_volta_para_a_fila_e_depois_vira_erro(self):
        LogRpaEaceMip.objects.filter(pk=self.log.pk).update(resultado=LogRpaEaceMip.PROCESSANDO)
        self.assertEqual(recuperar_envios_mip_interrompidos(), [self.log.pk])
        self.log.refresh_from_db()
        self.assertEqual(self.log.resultado, LogRpaEaceMip.NA_FILA)
        LogRpaEaceMip.objects.filter(pk=self.log.pk).update(resultado=LogRpaEaceMip.PROCESSANDO)
        recuperar_envios_mip_interrompidos()
        self.log.refresh_from_db()
        self.assertEqual(self.log.resultado, LogRpaEaceMip.ERRO)
        self.assertEqual(self.log.motivo_erro, "interrompido")


class WorkerFilaUnicaTests(BaseLoteComNf):
    """`processar_fila_rpa_eace` (worker do RI) leva também o MIP - 1 item
    por passada, o mais antigo entre os 2."""

    CMD = "apps.ri.management.commands.processar_fila_rpa_eace"

    def _rodar(self, ri_mais_antigo_em=None):
        ri_qs = MagicMock()
        ri_qs.filter.return_value.order_by.return_value.first.return_value = (
            MagicMock(enfileirado_em=ri_mais_antigo_em) if ri_mais_antigo_em else None
        )
        saida = StringIO()
        with patch(f"{self.CMD}.LogRpaEace.objects", ri_qs), \
                patch(f"{self.CMD}.processar_proximo_rpa_mip", return_value={"log_id": 1, "resultado": "sucesso", "motivo": ""}) as mip, \
                patch(f"{self.CMD}.processar_proximo_da_fila_rpa_eace", return_value=None) as ri:
            call_command("processar_fila_rpa_eace", stdout=saida)
        return mip, ri, saida.getvalue()

    def test_so_mip_na_fila(self):
        enfileirar_rpa_mip_lote(self._lote_prefetch(), self.usuario)
        mip, ri, saida = self._rodar()
        mip.assert_called_once()
        ri.assert_not_called()
        self.assertIn("MIP", saida)

    def test_ri_mais_antigo_vai_primeiro(self):
        enfileirar_rpa_mip_lote(self._lote_prefetch(), self.usuario)
        mip, ri, _ = self._rodar(ri_mais_antigo_em=timezone.now() - timedelta(minutes=10))
        ri.assert_called_once()
        mip.assert_not_called()

    def test_mip_mais_antigo_vai_primeiro(self):
        enfileirar_rpa_mip_lote(self._lote_prefetch(), self.usuario)
        mip, ri, _ = self._rodar(ri_mais_antigo_em=timezone.now() + timedelta(minutes=10))
        mip.assert_called_once()
        ri.assert_not_called()

    def test_sem_mip_segue_so_o_ri(self):
        mip, ri, saida = self._rodar()
        ri.assert_called_once()
        mip.assert_not_called()
        self.assertIn("vazia", saida)


class EstadosDoBotaoTests(BaseLoteComNf):

    def test_uma_consulta_para_todos_os_lotes(self):
        outro = Lote.objects.create(estado="GO", municipio="Anápolis")
        outro.escolas.set([self.escola_a])
        lotes = list(Lote.objects.prefetch_related(
            Prefetch("escolas", queryset=Escola.objects.prefetch_related("notas_fiscais_mip"))
        ))
        with self.assertNumQueries(1):
            estados = estados_rpa_mip_dos_lotes(lotes)
        self.assertTrue(estados[self.lote.pk].pode_enviar)


class BotaoNaTelaDoLoteTests(BaseLoteComNf):

    def setUp(self):
        super().setUp()
        self.client.force_login(self.usuario)

    def test_lote_com_nf_mostra_o_botao_habilitado(self):
        resposta = self.client.get(reverse("mip_lote_inep"))
        self.assertContains(resposta, "Enviar ao portal EACE")
        self.assertContains(resposta, f'action="{reverse("rpa_mip_lote_enviar", kwargs={"pk": self.lote.pk})}"')

    def test_lote_sem_nf_comum_mostra_o_motivo_e_nao_tem_form(self):
        self.escola_b.notas_fiscais_mip.all().delete()
        resposta = self.client.get(reverse("mip_lote_inep"))
        self.assertContains(resposta, "Há INEP do LOTE sem Nota Fiscal sincronizada.")
        self.assertNotContains(resposta, f'action="{reverse("rpa_mip_lote_enviar", kwargs={"pk": self.lote.pk})}"')

    def test_clicar_enfileira_e_o_botao_fica_inacessivel(self):
        resposta = self.client.post(
            reverse("rpa_mip_lote_enviar", kwargs={"pk": self.lote.pk}), {"next": reverse("mip_lote_inep")},
        )
        self.assertRedirects(resposta, reverse("mip_lote_inep"))
        self.assertEqual(LogRpaEaceMip.objects.get().resultado, LogRpaEaceMip.NA_FILA)
        pagina = self.client.get(reverse("mip_lote_inep"))
        self.assertContains(pagina, "Envio da NF ao portal EACE na fila")
        self.assertContains(pagina, 'hx-trigger="every 3s"')
        self.assertNotContains(pagina, f'action="{reverse("rpa_mip_lote_enviar", kwargs={"pk": self.lote.pk})}"')

    def test_sucesso_desabilita_de_vez(self):
        log = enfileirar_rpa_mip_lote(self._lote_prefetch(), self.usuario)
        LogRpaEaceMip.objects.filter(pk=log.pk).update(resultado=LogRpaEaceMip.SUCESSO, executado_em=timezone.now())
        resposta = self.client.get(reverse("rpa_mip_lote_status", kwargs={"pk": self.lote.pk}))
        self.assertContains(resposta, "NF enviada em")
        self.assertNotContains(resposta, "hx-trigger")
        self.assertNotContains(resposta, f'action="{reverse("rpa_mip_lote_enviar", kwargs={"pk": self.lote.pk})}"')
        self.client.post(reverse("rpa_mip_lote_enviar", kwargs={"pk": self.lote.pk}))
        self.assertEqual(LogRpaEaceMip.objects.count(), 1)

    def test_nf_que_ja_estava_no_portal_desabilita_como_sucesso(self):
        log = enfileirar_rpa_mip_lote(self._lote_prefetch(), self.usuario)
        LogRpaEaceMip.objects.filter(pk=log.pk).update(
            resultado=LogRpaEaceMip.ERRO, motivo_erro="documento_ja_enviado", status_portal="Aprovado",
            executado_em=timezone.now(),
        )
        resposta = self.client.get(reverse("rpa_mip_lote_status", kwargs={"pk": self.lote.pk}))
        self.assertContains(resposta, "NF já estava no portal (Aprovado)")
        self.assertContains(resposta, "check-circle-2")
        self.assertNotContains(resposta, f'action="{reverse("rpa_mip_lote_enviar", kwargs={"pk": self.lote.pk})}"')

    def test_erro_habilita_de_novo_com_o_motivo(self):
        log = enfileirar_rpa_mip_lote(self._lote_prefetch(), self.usuario)
        LogRpaEaceMip.objects.filter(pk=log.pk).update(resultado=LogRpaEaceMip.ERRO, motivo_erro="valor_divergente")
        resposta = self.client.get(reverse("rpa_mip_lote_status", kwargs={"pk": self.lote.pk}))
        self.assertContains(resposta, "Tentar de novo")
        self.assertContains(resposta, "O valor da Nota Fiscal é diferente")
        self.assertContains(resposta, f'action="{reverse("rpa_mip_lote_enviar", kwargs={"pk": self.lote.pk})}"')

    def test_enviar_so_aceita_post(self):
        resposta = self.client.get(reverse("rpa_mip_lote_enviar", kwargs={"pk": self.lote.pk}))
        self.assertEqual(resposta.status_code, 405)

    def test_visualizador_nao_envia(self):
        visualizador = User.objects.create_user(
            username="visualizador", password="senha-teste-123", perfil=User.PERFIL_VISUALIZADOR
        )
        self.client.force_login(visualizador)
        self.client.post(reverse("rpa_mip_lote_enviar", kwargs={"pk": self.lote.pk}))
        self.assertFalse(LogRpaEaceMip.objects.exists())


class FilaMostraMipTests(BaseLoteComNf):

    def test_fila_lista_o_envio_do_mip_marcado_como_mip(self):
        self.client.force_login(self.usuario)
        enfileirar_rpa_mip_lote(self._lote_prefetch(), self.usuario)
        resposta = self.client.get(reverse("fila_rpa_eace"))
        self.assertContains(resposta, "Envios do MIP (LOTE)")
        self.assertContains(resposta, "377_22-09-2026_NOME_MEGA INFRA.pdf"[-30:])
        self.assertEqual(resposta.context["total_na_fila"], 1)
        self.assertEqual(len(resposta.context["page_mip"]), 1)
