import os
import tempfile
from io import StringIO
from unittest.mock import patch

import openpyxl
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase

from apps.auditoria.models import Auditoria
from apps.core.services import BackupError
from apps.escolas.models import Escola

from .models import Ri, RiHistorico

COMANDO = "apps.ri.management.commands.baixar_ri_concluido_em_massa"
CABECALHO = ["DocNum", "Secretaria", "Empenho", "Status", "DISCRIMINACAO"]


def _discriminacao(inep, item):
    return f"INEP: {inep} ITEM LPU: {item} MUNICIPIO/UF: IPERO/SP VENCIMENTO: 30/09/2026 N CONTRATO: 213"


class BaixarRiConcluidoEmMassaTests(TestCase):
    """Pedido do usuário (2026-10-07): comando `baixar_ri_concluido_em_massa`."""

    def setUp(self):
        self.usuario = get_user_model().objects.create_user(
            username="operador", password="x", first_name="Ana", last_name="Lima"
        )
        self.ri_andamento = Ri.objects.create(
            escola=Escola.objects.create(inep="35000001", nome="Escola Andamento"), status=Ri.ANDAMENTO
        )
        self.ri_concluido = Ri.objects.create(
            escola=Escola.objects.create(inep="35000002", nome="Escola Concluida"),
            status=Ri.FATURAMENTO_RI_CONCLUIDO,
        )
        self.ri_fora_da_planilha = Ri.objects.create(
            escola=Escola.objects.create(inep="35000003", nome="Escola Fora"), status=Ri.ANDAMENTO
        )
        self.arquivo = self._planilha([
            ["101", "Escola Andamento", "35000001", "Fechado", _discriminacao("35000001", "KIT 7")],
            ["102", "Escola Andamento", "35000001", "Fechado", _discriminacao("35000001", "NOBREAK")],
            ["103", "Escola Concluida", "35000002", "Fechado", _discriminacao("35000002", "KIT 2")],
            ["104", "Escola Nova", "35999999", "Aberto", _discriminacao("35999999", "KIT 1")],
            [None, None, None, None, None],
            ["Filtros aplicados: ..."],
        ])

    def _planilha(self, linhas):
        workbook = openpyxl.Workbook()
        aba = workbook.active
        aba.append(CABECALHO)
        for linha in linhas:
            aba.append(linha)
        descritor, caminho = tempfile.mkstemp(suffix=".xlsx")
        os.close(descritor)
        workbook.save(caminho)
        self.addCleanup(os.remove, caminho)
        return caminho

    def _rodar(self, *argumentos):
        patcher = patch(f"{COMANDO}.criar_backup_seguranca", return_value="/backups/seguranca.sql.gz")
        self.backup = patcher.start()
        self.addCleanup(patcher.stop)
        saida = StringIO()
        call_command("baixar_ri_concluido_em_massa", self.arquivo, "--usuario", "operador", *argumentos, stdout=saida)
        return saida.getvalue()

    def test_simulacao_nao_grava_nada(self):
        saida = self._rodar()
        self.ri_andamento.refresh_from_db()
        self.assertEqual(self.ri_andamento.status, Ri.ANDAMENTO)
        self.assertFalse(RiHistorico.objects.exists())
        self.assertIn("Baixado como Faturamento RI Concluído: 1", saida)
        self.assertIn("SIMULACAO", saida)
        self.backup.assert_not_called()

    def test_backup_falhando_nao_grava_nada(self):
        with patch(f"{COMANDO}.criar_backup_seguranca", side_effect=BackupError("sem acesso")):
            with self.assertRaisesMessage(CommandError, "nada foi gravado"):
                call_command(
                    "baixar_ri_concluido_em_massa", self.arquivo, "--usuario", "operador", "--aplicar", stdout=StringIO()
                )
        self.ri_andamento.refresh_from_db()
        self.assertEqual(self.ri_andamento.status, Ri.ANDAMENTO)
        self.assertFalse(RiHistorico.objects.exists())

    def test_aplicar_baixa_ri_com_log_auditoria_e_historico_de_massa(self):
        saida = self._rodar("--aplicar")
        self.backup.assert_called_once_with("operador")
        self.ri_andamento.refresh_from_db()
        self.assertEqual(self.ri_andamento.status, Ri.FATURAMENTO_RI_CONCLUIDO)
        self.assertIsNotNone(self.ri_andamento.concluido_em)
        self.assertEqual(self.ri_andamento.escola.status_mip, Escola.AGUARDANDO_VALIDACAO_EACE)

        log = self.ri_andamento.historico.get(tipo=RiHistorico.LOG_STATUS)
        self.assertEqual((log.autor, log.valor_anterior, log.valor_novo), (self.usuario, "Em Andamento", "Faturamento RI Concluído"))
        self.assertTrue(Auditoria.objects.filter(entidade="Ri", entidade_id=self.ri_andamento.pk).exists())

        massa = self.ri_andamento.historico.get(tipo=RiHistorico.IMPORTACAO_MASSA)
        self.assertEqual(massa.autor, self.usuario)
        self.assertIn("processamento em massa", massa.mensagem)
        self.assertIn("por Ana Lima", massa.mensagem)
        self.assertIn("2 NF(s) faturada(s): KIT 7, NOBREAK", massa.mensagem)
        self.assertLessEqual(len(massa.mensagem), 250)
        self.assertIn("INEP não cadastrado no sistema: 1", saida)
        self.assertIn('NF 104 do INEP 35999999: Status da nota "Aberto"', saida)

    def test_ri_ja_concluido_e_fora_da_planilha_nao_sao_tocados(self):
        self._rodar("--aplicar")
        self.assertFalse(self.ri_concluido.historico.exists())
        self.ri_fora_da_planilha.refresh_from_db()
        self.assertEqual(self.ri_fora_da_planilha.status, Ri.ANDAMENTO)
        self.assertFalse(Escola.objects.filter(inep="35999999").exists())

    def test_rodar_de_novo_nao_duplica(self):
        self._rodar("--aplicar")
        saida = self._rodar("--aplicar")
        self.assertEqual(self.ri_andamento.historico.filter(tipo=RiHistorico.IMPORTACAO_MASSA).count(), 1)
        self.assertIn("Baixado como Faturamento RI Concluído: 0", saida)
        self.assertIn("Já estava em Faturamento RI Concluído (desconsiderado): 2", saida)

    def test_mensagem_corta_lista_de_itens_longa(self):
        self.arquivo = self._planilha([
            [str(n), "Escola Andamento", "35000001", "Fechado", _discriminacao("35000001", f"ITEM COMPRIDO NUMERO {n}")]
            for n in range(30)
        ])
        self._rodar("--aplicar")
        mensagem = self.ri_andamento.historico.get(tipo=RiHistorico.IMPORTACAO_MASSA).mensagem
        self.assertLessEqual(len(mensagem), 250)
        self.assertTrue(mensagem.endswith("..."))

    def test_usuario_inexistente(self):
        with self.assertRaises(CommandError):
            call_command("baixar_ri_concluido_em_massa", self.arquivo, "--usuario", "ninguem", stdout=StringIO())
