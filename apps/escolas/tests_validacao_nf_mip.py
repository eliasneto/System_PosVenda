"""Testes da rotina e da tela "Projeto > Validação MIP (NF)"
(`apps.escolas.validacao_nf_mip` / `views_validacao_nf_mip`). O RPA do
portal (`anexar_pdf_mip`) é sempre mockado - nenhum navegador nem rede."""

from datetime import datetime, timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import User
from apps.escolas.models import CardValidacaoNfMip, ValidacaoNfMip
from apps.escolas.validacao_nf_mip import (
    agendar_validacao_nf_mip_se_devido,
    enfileirar_validacao_nf_mip,
    processar_proxima_validacao_nf_mip,
    recuperar_validacoes_interrompidas,
)
from apps.integracoes.eace.rpa_mip import ResultadoRpaMip

FUSO = ZoneInfo("America/Fortaleza")
RPA = "apps.integracoes.eace.rpa_mip.anexar_pdf_mip"


def _local(hora, minuto=0, dia=28):
    return datetime(2026, 9, dia, hora, minuto, tzinfo=FUSO)


def _card(municipio, status, valor, posicao=0, ibge=""):
    return {"posicao": posicao, "municipio": municipio, "uf": "", "ibge": ibge, "status": status, "valor": valor}


def _sucesso(*cards, pedido="506"):
    return ResultadoRpaMip(sucesso=True, pedido=pedido, simulado=True, dados_pdf={}, cards_encontrados=list(cards))


class EnfileirarValidacaoTests(TestCase):

    def test_cria_na_fila(self):
        validacao, criada = enfileirar_validacao_nf_mip(ValidacaoNfMip.MANUAL)
        self.assertTrue(criada)
        self.assertEqual(validacao.status, ValidacaoNfMip.NA_FILA)

    def test_reaproveita_a_que_ja_esta_em_andamento(self):
        primeira, _ = enfileirar_validacao_nf_mip(ValidacaoNfMip.MANUAL)
        segunda, criada = enfileirar_validacao_nf_mip(ValidacaoNfMip.AGENDADA)
        self.assertFalse(criada)
        self.assertEqual(segunda.pk, primeira.pk)
        self.assertEqual(ValidacaoNfMip.objects.count(), 1)


class AgendarValidacaoTests(TestCase):
    """Com o agendamento ligado (`VALIDACAO_NF_MIP_AGENDADA=True`)."""

    def setUp(self):
        ligado = patch("apps.escolas.validacao_nf_mip.agendamento_ativo", return_value=True)
        ligado.start()
        self.addCleanup(ligado.stop)

    def _finalizar_todas(self):
        ValidacaoNfMip.objects.update(status=ValidacaoNfMip.SUCESSO, finalizado_em=timezone.now())

    def test_fora_do_horario_nao_agenda(self):
        self.assertIsNone(agendar_validacao_nf_mip_se_devido(_local(7, 59)))
        self.assertIsNone(agendar_validacao_nf_mip_se_devido(_local(20, 0)))
        self.assertFalse(ValidacaoNfMip.objects.exists())

    def test_agenda_uma_por_hora_das_8_as_19(self):
        with patch("django.utils.timezone.now", return_value=_local(8, 5)):
            self.assertIsNotNone(agendar_validacao_nf_mip_se_devido(_local(8, 5)))
        self._finalizar_todas()
        # mesma hora: nao agenda de novo
        self.assertIsNone(agendar_validacao_nf_mip_se_devido(_local(8, 50)))
        with patch("django.utils.timezone.now", return_value=_local(19, 2)):
            validacao = agendar_validacao_nf_mip_se_devido(_local(19, 2))
        self.assertEqual(validacao.origem, ValidacaoNfMip.AGENDADA)
        self.assertEqual(ValidacaoNfMip.objects.filter(origem=ValidacaoNfMip.AGENDADA).count(), 2)

    def test_com_manual_em_andamento_espera_ela_terminar(self):
        enfileirar_validacao_nf_mip(ValidacaoNfMip.MANUAL)
        self.assertIsNone(agendar_validacao_nf_mip_se_devido(_local(10, 0)))
        self.assertEqual(ValidacaoNfMip.objects.count(), 1)


class AgendamentoDesligadoTests(TestCase):
    """Pedido do usuário (2026-09-28): automática desligada até ele liberar."""

    def test_desligado_por_padrao(self):
        from apps.escolas.validacao_nf_mip import agendamento_ativo

        with patch.dict("os.environ", {"VALIDACAO_NF_MIP_AGENDADA": ""}):
            self.assertFalse(agendamento_ativo())

    def test_liga_pela_variavel_de_ambiente(self):
        from apps.escolas.validacao_nf_mip import agendamento_ativo

        with patch.dict("os.environ", {"VALIDACAO_NF_MIP_AGENDADA": "True"}):
            self.assertTrue(agendamento_ativo())

    def test_desligado_nao_agenda_nem_no_horario(self):
        with patch("apps.escolas.validacao_nf_mip.agendamento_ativo", return_value=False):
            self.assertIsNone(agendar_validacao_nf_mip_se_devido(_local(10, 0)))
        self.assertFalse(ValidacaoNfMip.objects.exists())

    def test_comando_desligado_nao_cria_execucao_sozinho(self):
        with patch("apps.escolas.validacao_nf_mip.agendamento_ativo", return_value=False), \
                patch("apps.escolas.validacao_nf_mip.timezone.localtime", return_value=_local(10, 0)), \
                patch(RPA) as mock_rpa:
            call_command("processar_validacao_nf_mip", stdout=StringIO())
        self.assertFalse(ValidacaoNfMip.objects.exists())
        mock_rpa.assert_not_called()

    def test_tela_informa_que_esta_so_manual(self):
        usuario = User.objects.create_user(username="analista", password="senha-teste-123")
        self.client.force_login(usuario)
        with patch("apps.escolas.views_validacao_nf_mip.agendamento_ativo", return_value=False):
            resposta = self.client.get(reverse("validacao_nf_mip"))
        self.assertContains(resposta, "desativada — só manual")


class RecuperarInterrompidasTests(TestCase):

    def test_processando_ha_mais_de_30_minutos_vira_erro(self):
        agora = timezone.now()
        travada = ValidacaoNfMip.objects.create(
            origem=ValidacaoNfMip.MANUAL, status=ValidacaoNfMip.PROCESSANDO, iniciado_em=agora - timedelta(minutes=31)
        )
        recente = ValidacaoNfMip.objects.create(
            origem=ValidacaoNfMip.MANUAL, status=ValidacaoNfMip.PROCESSANDO, iniciado_em=agora - timedelta(minutes=5)
        )
        self.assertEqual(recuperar_validacoes_interrompidas(agora), 1)
        travada.refresh_from_db()
        recente.refresh_from_db()
        self.assertEqual(travada.status, ValidacaoNfMip.ERRO)
        self.assertEqual(travada.motivo_erro, "interrompida")
        self.assertEqual(recente.status, ValidacaoNfMip.PROCESSANDO)


class ProcessarValidacaoTests(TestCase):

    def test_fila_vazia(self):
        self.assertIsNone(processar_proxima_validacao_nf_mip())

    def test_sucesso_grava_os_cards(self):
        validacao, _ = enfileirar_validacao_nf_mip(ValidacaoNfMip.MANUAL)
        resultado = _sucesso(
            _card("PAULINIA", "Aprovado", "16.109,00", 0),
            _card("Cândido Rodrigues", "Aguardando Aprovação", "2.282,27", 1, ibge="3510104"),
            _card("ITU", "Pendente", "", 2),
        )
        with patch(RPA, return_value=resultado) as mock_rpa:
            processar_proxima_validacao_nf_mip()
        kwargs = mock_rpa.call_args.kwargs
        self.assertTrue(kwargs["simular"])
        self.assertIsNone(kwargs["caminho_pdf"])
        self.assertIsNone(kwargs["municipio"])

        validacao.refresh_from_db()
        self.assertEqual(validacao.status, ValidacaoNfMip.SUCESSO)
        self.assertEqual(validacao.pedido, "506")
        self.assertIsNotNone(validacao.finalizado_em)
        cards = list(validacao.cards.all())
        self.assertEqual([c.municipio for c in cards], ["PAULINIA", "Cândido Rodrigues", "ITU"])
        self.assertEqual(cards[0].valor, Decimal("16109.00"))
        self.assertEqual(cards[1].status_portal, "Aguardando Aprovação")
        self.assertEqual(cards[1].codigo_ibge, "3510104")
        self.assertIsNone(cards[2].valor)

    def test_erro_do_portal_grava_o_motivo(self):
        validacao, _ = enfileirar_validacao_nf_mip(ValidacaoNfMip.AGENDADA)
        with patch(RPA, return_value=ResultadoRpaMip(sucesso=False, motivo="login", dados_pdf={})):
            processar_proxima_validacao_nf_mip()
        validacao.refresh_from_db()
        self.assertEqual(validacao.status, ValidacaoNfMip.ERRO)
        self.assertEqual(validacao.motivo_erro, "login")
        self.assertFalse(validacao.cards.exists())

    def test_excecao_inesperada_nao_deixa_processando(self):
        validacao, _ = enfileirar_validacao_nf_mip(ValidacaoNfMip.MANUAL)
        with patch(RPA, side_effect=RuntimeError("boom")):
            processar_proxima_validacao_nf_mip()
        validacao.refresh_from_db()
        self.assertEqual(validacao.status, ValidacaoNfMip.ERRO)
        self.assertEqual(validacao.motivo_erro, "erro_inesperado")

    def test_progresso_e_gravado_durante_a_execucao(self):
        validacao, _ = enfileirar_validacao_nf_mip(ValidacaoNfMip.MANUAL)
        vistos = []

        def rpa_falso(**kwargs):
            kwargs["progresso_callback"]("Abrindo MIPs", 62)
            vistos.append(ValidacaoNfMip.objects.values_list("etapa_atual", "progresso_pct").get(pk=validacao.pk))
            return _sucesso()

        with patch(RPA, side_effect=rpa_falso):
            processar_proxima_validacao_nf_mip()
        self.assertEqual(vistos, [("Abrindo MIPs", 62)])

    def test_pedido_solicitado_e_repassado_ao_rpa(self):
        validacao, _ = enfileirar_validacao_nf_mip(ValidacaoNfMip.MANUAL, pedido=" 429 ")
        self.assertEqual(validacao.pedido_solicitado, "429")
        with patch(RPA, return_value=_sucesso(pedido="429")) as mock_rpa:
            processar_proxima_validacao_nf_mip()
        self.assertEqual(mock_rpa.call_args.kwargs["pedido"], "429")
        validacao.refresh_from_db()
        self.assertEqual(validacao.pedido, "429")

    def test_sem_pedido_solicitado_o_rpa_usa_o_maior(self):
        enfileirar_validacao_nf_mip(ValidacaoNfMip.AGENDADA)
        with patch(RPA, return_value=_sucesso()) as mock_rpa:
            processar_proxima_validacao_nf_mip()
        self.assertIsNone(mock_rpa.call_args.kwargs["pedido"])

    def test_comando_do_worker_agenda_e_processa(self):
        saida = StringIO()
        with patch("apps.escolas.validacao_nf_mip.agendamento_ativo", return_value=True), \
                patch("apps.escolas.validacao_nf_mip.timezone.localtime", return_value=_local(9, 0)), \
                patch(RPA, return_value=_sucesso(_card("ITU", "Pendente", "1,00"))):
            call_command("processar_validacao_nf_mip", stdout=saida)
        validacao = ValidacaoNfMip.objects.get()
        self.assertEqual(validacao.origem, ValidacaoNfMip.AGENDADA)
        self.assertEqual(validacao.status, ValidacaoNfMip.SUCESSO)
        self.assertIn("Sucesso", saida.getvalue())


class ValidacaoNfMipViewTests(TestCase):

    def setUp(self):
        self.analista = User.objects.create_user(username="analista", password="senha-teste-123")
        self.visualizador = User.objects.create_user(
            username="visualizador", password="senha-teste-123", perfil=User.PERFIL_VISUALIZADOR
        )
        self.client.force_login(self.analista)

    def _execucao(self, status, cards=(), minutos_atras=0):
        validacao = ValidacaoNfMip.objects.create(
            origem=ValidacaoNfMip.AGENDADA, status=status, pedido="506",
            finalizado_em=timezone.now() - timedelta(minutes=minutos_atras),
        )
        for ordem, (municipio, status_portal, valor) in enumerate(cards):
            CardValidacaoNfMip.objects.create(
                validacao=validacao, ordem=ordem, municipio=municipio, status_portal=status_portal, valor=valor,
            )
        return validacao

    def test_grid_mostra_cards_da_ultima_com_sucesso_mesmo_se_a_ultima_deu_erro(self):
        self._execucao(ValidacaoNfMip.SUCESSO, [("PAULINIA", "Aprovado", Decimal("16109.00"))], minutos_atras=60)
        self._execucao(ValidacaoNfMip.ERRO)
        resposta = self.client.get(reverse("validacao_nf_mip"))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "PAULINIA")
        self.assertContains(resposta, "16.109,00")
        self.assertContains(resposta, "✗ Erro")

    def test_sem_execucao_mostra_estado_vazio(self):
        resposta = self.client.get(reverse("validacao_nf_mip"))
        self.assertContains(resposta, "Nunca executada")
        self.assertContains(resposta, "ainda não leu o portal")

    def test_filtros_de_municipio_e_status(self):
        self._execucao(ValidacaoNfMip.SUCESSO, [
            ("PAULINIA", "Aprovado", Decimal("1.00")),
            ("ITU", "Pendente", Decimal("2.00")),
            ("ITUPEVA", "Aguardando Aprovação", Decimal("3.00")),
        ])
        resposta = self.client.get(reverse("validacao_nf_mip"), {"municipio": "itu"})
        self.assertEqual([c.municipio for c in resposta.context["cards"]], ["ITU", "ITUPEVA"])
        resposta = self.client.get(reverse("validacao_nf_mip"), {"municipio": "itu", "status": "Pendente"})
        self.assertEqual([c.municipio for c in resposta.context["cards"]], ["ITU"])
        self.assertEqual(len(resposta.context["resumo_por_status"]), 3)

    def test_rodar_agora_enfileira_manual_com_o_usuario(self):
        resposta = self.client.post(reverse("validacao_nf_mip_rodar"))
        self.assertRedirects(resposta, reverse("validacao_nf_mip"))
        validacao = ValidacaoNfMip.objects.get()
        self.assertEqual(validacao.origem, ValidacaoNfMip.MANUAL)
        self.assertEqual(validacao.solicitado_por, self.analista)
        self.assertEqual(validacao.status, ValidacaoNfMip.NA_FILA)

    def test_rodar_agora_so_aceita_post(self):
        self.assertEqual(self.client.get(reverse("validacao_nf_mip_rodar")).status_code, 405)

    def test_pagina_em_andamento_faz_polling_e_desabilita_o_botao(self):
        enfileirar_validacao_nf_mip(ValidacaoNfMip.MANUAL)
        resposta = self.client.get(reverse("validacao_nf_mip"))
        self.assertContains(resposta, 'hx-trigger="every 3s"')
        self.assertContains(resposta, "Em andamento")

    def test_status_recarrega_a_pagina_quando_termina(self):
        self._execucao(ValidacaoNfMip.SUCESSO)
        resposta = self.client.get(reverse("validacao_nf_mip_status"), {"acompanhando": "1"})
        self.assertEqual(resposta.status_code, 204)
        self.assertEqual(resposta["HX-Refresh"], "true")

    def test_status_em_andamento_continua_o_polling(self):
        enfileirar_validacao_nf_mip(ValidacaoNfMip.MANUAL)
        resposta = self.client.get(reverse("validacao_nf_mip_status"), {"acompanhando": "1"})
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Na fila")

    def test_visualizador_nao_acessa(self):
        self.client.force_login(self.visualizador)
        self.assertRedirects(self.client.get(reverse("validacao_nf_mip")), reverse("grid_inep"),
                             fetch_redirect_response=False)
        self.client.post(reverse("validacao_nf_mip_rodar"))
        self.assertFalse(ValidacaoNfMip.objects.exists())

    def test_link_no_menu_projeto(self):
        resposta = self.client.get(reverse("validacao_nf_mip"))
        self.assertContains(resposta, "Validação MIP (NF)")

    def test_consulta_nao_cresce_com_a_quantidade_de_cards(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        def consultas_da_pagina():
            with CaptureQueriesContext(connection) as capturadas:
                self.client.get(reverse("validacao_nf_mip"))
            return len(capturadas)

        validacao = self._execucao(ValidacaoNfMip.SUCESSO, [("MUNICIPIO 0", "Aprovado", Decimal("1.00"))])
        com_1_card = consultas_da_pagina()
        for i in range(1, 30):
            CardValidacaoNfMip.objects.create(
                validacao=validacao, ordem=i, municipio=f"MUNICIPIO {i}", status_portal="Aprovado", valor=1,
            )
        self.assertEqual(consultas_da_pagina(), com_1_card)

    def test_rodar_agora_com_numero_do_pedido(self):
        self.client.post(reverse("validacao_nf_mip_rodar"), {"pedido": "402"})
        self.assertEqual(ValidacaoNfMip.objects.get().pedido_solicitado, "402")

    def test_rodar_agora_com_pedido_invalido_nao_enfileira(self):
        resposta = self.client.post(reverse("validacao_nf_mip_rodar"), {"pedido": "40a"}, follow=True)
        self.assertFalse(ValidacaoNfMip.objects.exists())
        self.assertContains(resposta, "pedido inválido")

    def test_erro_de_pedido_nao_encontrado_mostra_o_numero(self):
        ValidacaoNfMip.objects.create(
            origem=ValidacaoNfMip.MANUAL, status=ValidacaoNfMip.ERRO, motivo_erro="pedido_nao_encontrado",
            pedido_solicitado="999", finalizado_em=timezone.now(),
        )
        resposta = self.client.get(reverse("validacao_nf_mip"))
        self.assertContains(resposta, "O pedido 999 não está no grid de MIPs.")

    def test_campo_do_pedido_na_tela(self):
        resposta = self.client.get(reverse("validacao_nf_mip"))
        self.assertContains(resposta, 'name="pedido"')
