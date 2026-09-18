import datetime
import io
import shutil
import tempfile
import zipfile
from decimal import Decimal
from pathlib import Path

import openpyxl
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.escolas.models import Escola, EscolaItemRelatorioEaceMip, Lote, PlanilhaRelatorioEaceMip
from apps.escolas.services import (
    LoteMipError,
    PlanilhaFaturamentoImplantacaoError,
    criar_lote_mip,
    desfazer_lote_mip,
    # enviar_email_lote, montar_assunto_email_lote — e-mail do LOTE comentado (pedido do usuário, 2026-09-15, ver apps.escolas.services).
    escolas_elegiveis_lote_mip,
    gerar_planilha_faturamento_implantacao,
    gerar_planilha_faturamento_implantacao_lote,
    nome_arquivo_planilha_faturamento_implantacao,
)
from apps.ri.models import Documento, KitPadrao, Ri, RiHistorico, RiItemEace, RiItemIxc, RiItemRelatorioEace

User = get_user_model()

CABECALHO = [
    "LOTE", "UF ", "MUNICIPIO", "INEP", "UNIDADE ESCOLAR ",
    "ENDEREÇO UNIDADE ESCOLAR ", "VELOCIDADE", "KIT WIFI ESTIMADO",
]


def _criar_planilha(tmp_path, linhas, linha_cabecalho=13):
    """Monta um .xlsx no mesmo formato do CONSOLIDADO EACE.xlsx real: dados
    fora da aba comecam em branco, cabecalho na linha `linha_cabecalho` e
    colunas com espacos/acentos identicos ao arquivo de origem."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "FATURAMENTO MATERIAIS"

    for indice, titulo in enumerate(CABECALHO, start=1):
        ws.cell(row=linha_cabecalho, column=indice, value=titulo)

    for offset, linha in enumerate(linhas, start=1):
        for indice, valor in enumerate(linha, start=1):
            ws.cell(row=linha_cabecalho + offset, column=indice, value=valor)

    caminho = tmp_path / "planilha_teste.xlsx"
    wb.save(caminho)
    return caminho


class ImportarEscolasPlanilhaTests(TestCase):
    """FEAT-002: importacao de Escola a partir da planilha CONSOLIDADO EACE.xlsx."""

    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp_dir.name)
        self.addCleanup(self._tmp_dir.cleanup)

    def test_importa_escolas_da_planilha(self):
        caminho = _criar_planilha(self.tmp_path, [
            [9, "SP", "Nova Aliança", 35006380, "ESCOLA MUNICIPAL VICENTE FERNANDES",
             "LOURENCO PALA, 276 CENTRO. 15210-000 Nova Aliança - SP.", 50, 2],
            [11, "DF", "Brasília", 53012089, "EC 02 DO RIACHO FUNDO",
             "QUADRA QN 5, 07 AREA ESPECIAL.", 300, 10],
        ])

        call_command("importar_escolas_planilha", str(caminho))

        self.assertEqual(Escola.objects.count(), 2)
        escola = Escola.objects.get(inep="35006380")
        self.assertEqual(escola.nome, "ESCOLA MUNICIPAL VICENTE FERNANDES")
        self.assertEqual(escola.lote, 9)
        self.assertEqual(escola.estado, "SP")
        self.assertEqual(escola.municipio, "Nova Aliança")
        self.assertEqual(escola.velocidade_dl_minima, "50")
        self.assertEqual(escola.kit_inicial, "2")
        self.assertEqual(escola.nobreak_inicial, "Nobreak")  # RN-017

    def test_inep_curto_e_preenchido_com_zeros_a_esquerda(self):
        caminho = _criar_planilha(self.tmp_path, [
            [1, "SP", "Teste", 123, "ESCOLA TESTE", "RUA TESTE, 1", 50, 1],
        ])

        call_command("importar_escolas_planilha", str(caminho))

        self.assertTrue(Escola.objects.filter(inep="00000123").exists())

    def test_linha_em_branco_no_rodape_e_ignorada(self):
        caminho = _criar_planilha(self.tmp_path, [
            [9, "SP", "Nova Aliança", 35006380, "ESCOLA MUNICIPAL VICENTE FERNANDES",
             "LOURENCO PALA, 276 CENTRO.", 50, 2],
            [None, None, None, None, None, None, None, None],
            [None, None, None, None, None, None, None, None],
        ])

        call_command("importar_escolas_planilha", str(caminho))

        self.assertEqual(Escola.objects.count(), 1)

    def test_reimportar_nao_duplica_nem_sobrescreve_escola_existente(self):
        Escola.objects.create(inep="35006380", nome="NOME JA CADASTRADO MANUALMENTE")
        caminho = _criar_planilha(self.tmp_path, [
            [9, "SP", "Nova Aliança", 35006380, "ESCOLA MUNICIPAL VICENTE FERNANDES",
             "LOURENCO PALA, 276 CENTRO.", 50, 2],
        ])

        call_command("importar_escolas_planilha", str(caminho))
        call_command("importar_escolas_planilha", str(caminho))  # roda de novo, tem que ser idempotente

        self.assertEqual(Escola.objects.count(), 1)
        escola = Escola.objects.get(inep="35006380")
        self.assertEqual(escola.nome, "NOME JA CADASTRADO MANUALMENTE")

    def test_escola_nova_nasce_desconectada(self):
        caminho = _criar_planilha(self.tmp_path, [
            [9, "SP", "Nova Aliança", 35006380, "ESCOLA MUNICIPAL VICENTE FERNANDES",
             "LOURENCO PALA, 276 CENTRO.", 50, 2],
        ])

        call_command("importar_escolas_planilha", str(caminho))

        escola = Escola.objects.get(inep="35006380")
        self.assertEqual(escola.status_conexao, Escola.DESCONECTADO)

    def test_aba_inexistente_gera_erro_claro(self):
        wb = openpyxl.Workbook()
        wb.active.title = "OUTRA ABA"
        caminho = self.tmp_path / "planilha_sem_aba.xlsx"
        wb.save(caminho)

        with self.assertRaises(Exception):
            call_command("importar_escolas_planilha", str(caminho))


CABECALHO_NOVA_BASE = [
    "Fase", "UF", "Cidade", "Codigo Inep", "Nome da Escola", "Endereço",
    "Velocidade DL Mínima (Mbps)", "Kit Wi-Fi\n(estimado)",
]


def _criar_nova_base(tmp_path, linhas):
    """Monta um .xlsx no mesmo formato de "Nova BASE EACE.xlsx": aba
    "base", cabeçalho na linha 1, colunas com nomes/quebra de linha
    idênticos ao arquivo real."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "base"

    for indice, titulo in enumerate(CABECALHO_NOVA_BASE, start=1):
        ws.cell(row=1, column=indice, value=titulo)

    for offset, linha in enumerate(linhas, start=1):
        for indice, valor in enumerate(linha, start=1):
            ws.cell(row=1 + offset, column=indice, value=valor)

    caminho = tmp_path / "nova_base_teste.xlsx"
    wb.save(caminho)
    return caminho


class ImportarNovaBaseEaceTests(TestCase):
    """Correção pontual (2026-09-01): importação de Escola a partir de
    "Nova BASE EACE.xlsx" (aba "base") — formato de coluna diferente do
    CONSOLIDADO EACE.xlsx (`importar_escolas_planilha`), mesma regra de
    segurança (só cria INEP novo, nunca sobrescreve)."""

    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp_dir.name)
        self.addCleanup(self._tmp_dir.cleanup)

    def test_simulacao_nao_grava_nada(self):
        caminho = _criar_nova_base(self.tmp_path, [
            [11, "TO", "ARAGUAINA", 17057590, "CENTRO DE EDUCACAO INFANTIL PEQUENO PRINCIPE",
             "ERICO VERISSIMO, 271", 50, 2],
        ])

        call_command("importar_nova_base_eace", str(caminho))

        self.assertEqual(Escola.objects.count(), 0)

    def test_aplicar_cria_escolas_novas(self):
        caminho = _criar_nova_base(self.tmp_path, [
            [11, "TO", "ARAGUAINA", 17057590, "CENTRO DE EDUCACAO INFANTIL PEQUENO PRINCIPE",
             "ERICO VERISSIMO, 271", 50, 2],
            [9, "SP", "LORENA", 35243875, "MARIA ANTONIETA ARANTES FERREIRA PROFA ESCOLA MUNICIPAL",
             "LUIZA CHAGAS PROFESSORA, SN", 200, 7],
        ])

        call_command("importar_nova_base_eace", str(caminho), "--aplicar")

        self.assertEqual(Escola.objects.count(), 2)
        escola = Escola.objects.get(inep="17057590")
        self.assertEqual(escola.nome, "CENTRO DE EDUCACAO INFANTIL PEQUENO PRINCIPE")
        self.assertEqual(escola.lote, 11)
        self.assertEqual(escola.estado, "TO")
        self.assertEqual(escola.municipio, "ARAGUAINA")
        self.assertEqual(escola.endereco, "ERICO VERISSIMO, 271")
        self.assertEqual(escola.velocidade_dl_minima, "50")
        self.assertEqual(escola.kit_inicial, "2")
        self.assertEqual(escola.nobreak_inicial, "Nobreak")
        self.assertEqual(escola.status_conexao, Escola.DESCONECTADO)

    def test_nao_duplica_nem_sobrescreve_escola_existente(self):
        Escola.objects.create(inep="17057590", nome="NOME JA CADASTRADO MANUALMENTE")
        caminho = _criar_nova_base(self.tmp_path, [
            [11, "TO", "ARAGUAINA", 17057590, "CENTRO DE EDUCACAO INFANTIL PEQUENO PRINCIPE",
             "ERICO VERISSIMO, 271", 50, 2],
        ])

        call_command("importar_nova_base_eace", str(caminho), "--aplicar")
        call_command("importar_nova_base_eace", str(caminho), "--aplicar")  # idempotente

        self.assertEqual(Escola.objects.count(), 1)
        self.assertEqual(Escola.objects.get(inep="17057590").nome, "NOME JA CADASTRADO MANUALMENTE")

    def test_linha_duplicada_dentro_do_arquivo_conta_so_a_primeira(self):
        caminho = _criar_nova_base(self.tmp_path, [
            [11, "TO", "ARAGUAINA", 17057590, "CENTRO DE EDUCACAO INFANTIL PEQUENO PRINCIPE",
             "ERICO VERISSIMO, 271", 50, 2],
            [11, "TO", "ARAGUAINA", 17057590, "CENTRO DE EDUCACAO INFANTIL PEQUENO PRINCIPE",
             "ERICO VERISSIMO, 271", 50, 2],
        ])

        call_command("importar_nova_base_eace", str(caminho), "--aplicar")

        self.assertEqual(Escola.objects.count(), 1)

    def test_inep_curto_e_preenchido_com_zeros_a_esquerda(self):
        caminho = _criar_nova_base(self.tmp_path, [
            [1, "SP", "Teste", 123, "ESCOLA TESTE", "RUA TESTE, 1", 50, 1],
        ])

        call_command("importar_nova_base_eace", str(caminho), "--aplicar")

        self.assertTrue(Escola.objects.filter(inep="00000123").exists())

    def test_linha_sem_inep_e_ignorada(self):
        caminho = _criar_nova_base(self.tmp_path, [
            [11, "TO", "ARAGUAINA", None, "ESCOLA SEM INEP", "RUA TESTE, 1", 50, 1],
        ])

        call_command("importar_nova_base_eace", str(caminho), "--aplicar")

        self.assertEqual(Escola.objects.count(), 0)

    def test_aba_inexistente_gera_erro_claro(self):
        wb = openpyxl.Workbook()
        wb.active.title = "OUTRA ABA"
        caminho = self.tmp_path / "planilha_sem_aba.xlsx"
        wb.save(caminho)

        with self.assertRaises(Exception):
            call_command("importar_nova_base_eace", str(caminho))


class EscolaStatusConexaoTests(TestCase):
    """RN-007: status de conexao derivado do preenchimento das datas de
    instalacao RE/RI."""

    def test_nasce_desconectada(self):
        escola = Escola.objects.create(inep="11111111", nome="Escola A")
        self.assertEqual(escola.status_conexao, Escola.DESCONECTADO)

    def test_fica_parcialmente_conectada_com_apenas_um_processo(self):
        escola = Escola.objects.create(
            inep="22222222", nome="Escola B",
            data_instalacao_ri=datetime.date(2026, 8, 1),
        )
        self.assertEqual(escola.status_conexao, Escola.PARCIALMENTE_CONECTADO)

    def test_fica_conectada_com_os_dois_processos(self):
        escola = Escola.objects.create(
            inep="33333333", nome="Escola C",
            data_instalacao_re=datetime.date(2026, 8, 1),
            data_instalacao_ri=datetime.date(2026, 8, 2),
        )
        self.assertEqual(escola.status_conexao, Escola.CONECTADO)

    def test_volta_a_parcialmente_conectada_se_uma_data_for_removida(self):
        escola = Escola.objects.create(
            inep="44444444", nome="Escola D",
            data_instalacao_re=datetime.date(2026, 8, 1),
            data_instalacao_ri=datetime.date(2026, 8, 2),
        )
        escola.data_instalacao_ri = None
        escola.save()
        self.assertEqual(escola.status_conexao, Escola.PARCIALMENTE_CONECTADO)


class EscolaNobreakTests(TestCase):
    """RN-017: Nobreak declarado é item padrão, igual para toda escola —
    sem passo manual, tanto para escola já existente quanto para nova."""

    def test_escola_nova_nasce_com_nobreak_padrao(self):
        escola = Escola.objects.create(inep="55555555", nome="Escola E")
        self.assertEqual(escola.nobreak_inicial, "Nobreak")

    def test_nobreak_padrao_e_o_mesmo_para_qualquer_escola(self):
        escola_a = Escola.objects.create(inep="66666666", nome="Escola F")
        escola_b = Escola.objects.create(inep="77777777", nome="Escola G")
        self.assertEqual(escola_a.nobreak_inicial, escola_b.nobreak_inicial)


class MipInepViewTests(TestCase):
    """Projeto > MIP: visão dos INEPs com `Escola.status_mip ==
    "Aguardando Validação EACE"` (RN-104, 2026-09-17, desfaz a RN-103,
    2026-09-16, a pedido do usuário — o Grid de Equipamentos continua
    mostrando toda Escola sempre, sem essa restrição)."""

    def setUp(self):
        self.user = User.objects.create_user(username="analista", password="senha-teste-123")
        self.escola = Escola.objects.create(
            inep="10000001",
            nome="Escola Teste MIP",
            endereco="Rua Teste, 1",
            municipio="Fortaleza",
            estado="CE",
            lote=9,
        )
        Ri.objects.create(escola=self.escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)

    def test_exige_login(self):
        resp = self.client.get(reverse("mip_inep"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp.url)

    def test_caminho_principal_lista_ineps_em_validacao_eace(self):
        """Estado e Município em colunas separadas (pedido do usuário) —
        no lugar da coluna Endereço, removida."""
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.escola.inep)
        self.assertContains(resp, self.escola.nome)
        self.assertContains(resp, "Fortaleza")
        self.assertContains(resp, "CE")
        self.assertNotContains(resp, "Rua Teste, 1")

    def test_coluna_endereco_foi_substituida_por_estado_e_municipio(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertContains(resp, "<th class=\"px-4 py-2\">Estado</th>")
        self.assertContains(resp, "<th class=\"px-4 py-2\">Município</th>")
        self.assertNotContains(resp, "<th class=\"px-4 py-2\">Endereço</th>")
        self.assertNotContains(resp, "<th class=\"px-4 py-2\">Município/UF</th>")

    def test_ri_fora_de_validacao_eace_nao_aparece(self):
        """RN-104 (2026-09-17): RI em outro status não aparece no grid do
        MIP — continua sempre visível no Grid de Equipamentos."""
        escola_em_andamento = Escola.objects.create(inep="10000003", nome="Escola Em Andamento")
        Ri.objects.create(escola=escola_em_andamento, status=Ri.ANDAMENTO)
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertContains(resp, self.escola.inep)
        self.assertNotContains(resp, escola_em_andamento.inep)
        resp_ri = self.client.get(reverse("grid_inep"))
        self.assertContains(resp_ri, escola_em_andamento.inep)

    def test_sem_ri_nao_aparece(self):
        """RN-104 (2026-09-17): sem RI, o INEP não aparece no grid do MIP
        (sem handoff possível) — continua sempre visível no Grid de
        Equipamentos."""
        escola_sem_ri = Escola.objects.create(inep="10000004", nome="Escola Sem RI")
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertNotContains(resp, escola_sem_ri.inep)
        resp_ri = self.client.get(reverse("grid_inep"))
        self.assertContains(resp_ri, escola_sem_ri.inep)

    def test_busca_por_inep_nome_municipio_ou_uf(self):
        outra_escola = Escola.objects.create(inep="10000002", nome="Escola Sobral", municipio="Sobral", estado="CE")
        Ri.objects.create(escola=outra_escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"), {"q": "Sobral"})
        self.assertContains(resp, outra_escola.inep)
        self.assertNotContains(resp, self.escola.inep)

    def test_busca_sem_resultado_mostra_estado_vazio(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"), {"q": "inep-que-nao-existe"})
        self.assertContains(resp, "Nenhum INEP encontrado")

    def test_nao_mostra_status_de_ri_ou_conexao(self):
        """Diferença deliberada em relação ao grid de Equipamentos
        (`grid_inep`): MIP não tem coluna/filtro de status de conexão nem
        editor de status do RI — só o drill-down somente-leitura dos
        lados 1/2 (RN combinada com o usuário, 2026-09-07). (Não testa a
        string "Status do RI" pura — `core/base.html` já a usa num
        comentário de CSS, presente em qualquer página do sistema.)"""
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertNotContains(resp, "Status de conexão")
        self.assertNotContains(resp, "Sem RI")


class StatusMipHandoffTests(TestCase):
    """RN-092 (2026-09-10): handoff pro MIP — `Ri.save()` grava
    `Escola.status_mip` sozinho na 1ª vez que o RI chega em "Aguardando
    validação EACE" ou "Faturamento Concluído", cobrindo tanto a troca
    manual/automática de status quanto a criação direta de um RI já
    nesses status (comandos de gestão, admin)."""

    def test_handoff_ao_trocar_status_para_aguardando_validacao_eace(self):
        escola = Escola.objects.create(inep="10000001", nome="Escola Teste")
        ri = Ri.objects.create(escola=escola, status=Ri.ANDAMENTO)
        self.assertIsNone(Escola.objects.get(pk=escola.pk).status_mip)

        ri.status = Ri.AGUARDANDO_VALIDACAO_EACE
        ri.save()

        escola.refresh_from_db()
        self.assertEqual(escola.status_mip, Escola.AGUARDANDO_VALIDACAO_EACE)

    def test_handoff_ao_criar_ri_ja_em_aguardando_validacao_eace(self):
        escola = Escola.objects.create(inep="10000002", nome="Escola Teste")
        Ri.objects.create(escola=escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)

        escola.refresh_from_db()
        self.assertEqual(escola.status_mip, Escola.AGUARDANDO_VALIDACAO_EACE)

    def test_handoff_ao_chegar_em_faturamento_concluido(self):
        escola = Escola.objects.create(inep="10000003", nome="Escola Teste")
        Ri.objects.create(escola=escola, status=Ri.FATURAMENTO_CONCLUIDO)

        escola.refresh_from_db()
        self.assertEqual(escola.status_mip, Escola.FATURAMENTO_CONCLUIDO)

    def test_status_mip_e_ressincronizado_quando_o_ri_chega_de_novo_no_status(self):
        """Revisão da RN-092 (2026-09-10, mesmo dia): "Em Andamento" no
        MIP volta a ser o `Ri.status="andamento"` de verdade — o RI pode
        progredir sozinho de novo (fluxo normal de e-mail/financeiro,
        RN-001) e chegar outra vez em "Aguardando validação EACE"/
        "Faturamento Concluído". `Ri.save()` precisa sincronizar de novo
        nesse caso, não só na 1ª vez — senão o MIP ficaria preso
        mostrando "Em Andamento" para sempre."""
        escola = Escola.objects.create(
            inep="10000004", nome="Escola Teste", status_mip=Escola.EM_ANDAMENTO
        )
        ri = Ri.objects.create(escola=escola, status=Ri.ANDAMENTO)

        ri.status = Ri.AGUARDANDO_VALIDACAO_EACE
        ri.save()

        escola.refresh_from_db()
        self.assertEqual(escola.status_mip, Escola.AGUARDANDO_VALIDACAO_EACE)

    def test_outros_status_do_ri_nao_disparam_handoff(self):
        escola = Escola.objects.create(inep="10000005", nome="Escola Teste")
        Ri.objects.create(escola=escola, status=Ri.ANDAMENTO)

        escola.refresh_from_db()
        self.assertIsNone(escola.status_mip)


class MipInepStatusFiltroTests(TestCase):
    """RN-104 (2026-09-17, desfaz a RN-103/RN-092 nesse ponto): grid do
    MIP volta a mostrar só quem está com `Escola.status_mip ==
    "Aguardando Validação EACE"` — os demais valores do MIP (Em
    Andamento, Aguardando Encerramento LOTE, Em Faturamento, Faturamento
    Concluído) e quem ainda não passou pelo handoff saem da lista, mas
    continuam sempre visíveis no Grid de Equipamentos
    (`ri.views.grid_inep_view`, que a RN-104 não muda)."""

    def setUp(self):
        self.user = User.objects.create_user(username="analista", password="senha-teste-123")

    def test_mostra_so_aguardando_validacao_eace(self):
        em_andamento = Escola.objects.create(inep="10000001", nome="Escola Andamento")
        Ri.objects.create(escola=em_andamento, status=Ri.ANDAMENTO)
        em_andamento.status_mip = Escola.EM_ANDAMENTO
        em_andamento.save()

        aguardando = Escola.objects.create(inep="10000002", nome="Escola Validacao")
        Ri.objects.create(escola=aguardando, status=Ri.AGUARDANDO_VALIDACAO_EACE)

        concluido = Escola.objects.create(inep="10000003", nome="Escola Concluida")
        Ri.objects.create(escola=concluido, status=Ri.FATURAMENTO_CONCLUIDO)

        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertNotContains(resp, em_andamento.inep)
        self.assertContains(resp, aguardando.inep)
        self.assertNotContains(resp, concluido.inep)

        # Nenhum dos 3 nunca sai do Grid de Equipamentos (RI) — RN-104 só
        # mexe na visibilidade do MIP.
        resp_ri = self.client.get(reverse("grid_inep"))
        self.assertContains(resp_ri, em_andamento.inep)
        self.assertContains(resp_ri, aguardando.inep)
        self.assertContains(resp_ri, concluido.inep)

    def test_sem_handoff_nao_aparece_no_mip(self):
        """RN-104: sem handoff (`status_mip` `None`), o INEP não aparece
        no grid do MIP — continua acessível direto por `/mip/<inep>/` e
        sempre visível no Grid de Equipamentos."""
        escola = Escola.objects.create(inep="10000004", nome="Escola Sem Handoff")
        Ri.objects.create(escola=escola, status=Ri.IMPLANTACAO_EACE)

        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertNotContains(resp, escola.inep)

        resp_ri = self.client.get(reverse("grid_inep"))
        self.assertContains(resp_ri, escola.inep)

    def test_inep_legado_mostra_o_mesmo_destaque_do_grid_de_equipamentos(self):
        """Bug reportado pelo usuário (2026-09-10): o INEP legado
        (`Escola.legado=True`, `importar_ri_legado_eace`) nasce direto em
        "Aguardando validação EACE". O destaque em negrito/branco
        precisa aparecer aqui também, igual ao Grid de Equipamentos."""
        escola = Escola.objects.create(inep="10000005", nome="Escola Legado", legado=True)
        Ri.objects.create(escola=escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)

        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertContains(resp, "INEP legado")


class MipInepDrilldownTests(TestCase):
    """Projeto > MIP, drill-down dos 3 lados (RN combinada com o usuário,
    2026-09-07): lados 1 e 2 mostram os mesmos itens do RI (RiItemEace/
    RiItemIxc), mas com o Valor de serviço (`KitPadrao.valor_servico`),
    não o Valor de equipamento usado no RI. Lado 3 vem de
    `EscolaItemRelatorioEaceMip` (RN-069/RN-070)."""

    def setUp(self):
        self.user = User.objects.create_user(username="analista", password="senha-teste-123")
        self.escola = Escola.objects.create(
            inep="10000001", nome="Escola Teste MIP", lote=9, kit_inicial="Kit Cobertura Wi-Fi - 8 Access Points",
        )
        self.kit_8ap = KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 8 Access Points",
            lote=9,
            valor_equipamento="1000.00",
            valor_servico="250.00",
        )
        # RN-074 (a criar): só aparece na lista quem está em "Aguardando
        # validação EACE" — sem esse RI, nenhum teste desta classe veria
        # o INEP no grid.
        self.ri = Ri.objects.create(escola=self.escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)

    def test_lado3_sem_item_sincronizado_mostra_nenhum_item_lancado(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertNotContains(resp, "Em aberto — planilha de origem ainda não definida.")
        self.assertContains(resp, "Nenhum item lançado.")

    def test_lado3_mostra_item_sincronizado(self):
        EscolaItemRelatorioEaceMip.objects.create(
            escola=self.escola, descricao_item="Kit Cobertura Wi-Fi - 8 Access Points",
            quantidade=1, valor_servico="250.00", eh_kit=True,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertContains(resp, "Kit Cobertura Wi-Fi - 8 Access Points — 1 un. —")
        self.assertContains(resp, "R$ 250,00")

    def test_lado1_sem_lancamento_usa_referencia_do_kit_declarado(self):
        """Sem RiItemEace lançado, cai na mesma referência ao vivo do Grid
        de Equipamentos (RN-010), mas mostrando valor_servico."""
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertContains(resp, "Kit Cobertura Wi-Fi - 8 Access Points")
        self.assertContains(resp, "R$ 250,00")
        self.assertContains(resp, "referência, ainda não lançado no RI")

    def test_lado1_com_lancamento_usa_itens_do_ri(self):
        """RiItemEace já lançado: mostra a quantidade lançada (não mais
        1 fixo da referência), com o valor_servico resolvido pelo mesmo
        texto do item."""
        RiItemEace.objects.create(
            ri=self.ri, descricao_item="Kit Cobertura Wi-Fi - 8 Access Points", quantidade=2, valor_unitario="1000.00",
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertContains(resp, "Kit Cobertura Wi-Fi - 8 Access Points — 2 un. —")
        self.assertContains(resp, "R$ 250,00")
        self.assertNotContains(resp, "referência, ainda não lançado no RI")

    def test_lado2_mostra_itens_ixc_do_ri_com_valor_de_servico(self):
        RiItemIxc.objects.create(
            ri=self.ri, descricao_item="Kit Cobertura Wi-Fi - 8 Access Points", quantidade=1,
            valor_unitario="0.00", eh_kit=True,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertContains(resp, "IXC")
        self.assertContains(resp, "R$ 250,00")

    def test_lado2_produto_avulso_cruza_pela_descricao_curta(self):
        produto = KitPadrao.objects.create(
            descricao="Cabo de rede (material e serviço)", lote=9, valor_equipamento="50.00", valor_servico="10.00",
        )
        RiItemIxc.objects.create(
            ri=self.ri, descricao_item=produto.descricao_curta, quantidade=3, valor_unitario="0.00", eh_kit=False,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertContains(resp, "Cabo de rede — 3 un. —")
        self.assertContains(resp, "R$ 10,00")

    def test_item_sem_correspondencia_no_catalogo_avisa_em_vez_de_inventar_valor(self):
        """CLAUDE.md §9: sem correspondência no catálogo, nunca inventa um
        valor — mostra aviso."""
        RiItemIxc.objects.create(
            ri=self.ri, descricao_item="Produto descontinuado, fora do catálogo", quantidade=1,
            valor_unitario="0.00", eh_kit=False,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertContains(resp, "valor de serviço não encontrado")

    def test_ri_sem_item_ixc_mostra_nenhum_item_lancado(self):
        """RI já existe (RN-074, a criar — exigido pra aparecer na lista),
        mas ainda sem RiItemIxc lançado."""
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertContains(resp, "Nenhum item lançado.")


class MipValorTotalLado2Tests(TestCase):
    """RN-076 (a criar): coluna "Valor Total (IXC)" do grid do MIP, no
    lugar da coluna Lote (removida a pedido do usuário) — soma
    quantidade × Valor de serviço de cada item do Lado IXC (2º)."""

    def setUp(self):
        self.user = User.objects.create_user(username="analista-valor-total", password="senha-teste-123")
        self.escola = Escola.objects.create(inep="10000030", nome="Escola Valor Total", lote=9)
        self.kit_2ap = KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 2 Access Points", lote=9,
            valor_equipamento="1000.00", valor_servico="300.00",
        )
        self.ri = Ri.objects.create(escola=self.escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)

    def test_coluna_lote_foi_substituida_por_valor_total(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertContains(resp, "Valor Total (IXC)")
        self.assertNotContains(resp, "<th class=\"px-4 py-2\">Lote</th>")

    def test_sem_item_no_lado_ixc_mostra_travessao(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        linha = resp.context["page_obj"][0]
        self.assertIsNone(linha["valor_total_lado2"])

    def test_soma_quantidade_vezes_valor_de_servico_de_todos_os_itens(self):
        RiItemIxc.objects.create(
            ri=self.ri, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
            quantidade=1, valor_unitario="0.00", eh_kit=True,
        )
        KitPadrao.objects.create(
            descricao="Cabo de rede (material e serviço)", lote=9, valor_equipamento="50.00", valor_servico="10.00",
        )
        RiItemIxc.objects.create(
            ri=self.ri, descricao_item="Cabo de rede", quantidade=3, valor_unitario="0.00", eh_kit=False,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        linha = resp.context["page_obj"][0]
        # 1 x 300,00 (KIT) + 3 x 10,00 (Cabo de rede) = 330,00
        self.assertEqual(linha["valor_total_lado2"], Decimal("330.00"))
        self.assertFalse(linha["valor_total_lado2_incompleto"])
        self.assertContains(resp, "R$ 330,00")

    def test_item_sem_correspondencia_no_catalogo_fica_fora_da_soma_e_avisa(self):
        """CLAUDE.md §9: item sem Valor de serviço no catálogo não entra
        na soma (nunca inventa valor) — mas o total fica marcado como
        incompleto, pro template avisar."""
        RiItemIxc.objects.create(
            ri=self.ri, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
            quantidade=1, valor_unitario="0.00", eh_kit=True,
        )
        RiItemIxc.objects.create(
            ri=self.ri, descricao_item="Produto fora do catálogo", quantidade=5,
            valor_unitario="0.00", eh_kit=False,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        linha = resp.context["page_obj"][0]
        self.assertEqual(linha["valor_total_lado2"], Decimal("300.00"))
        self.assertTrue(linha["valor_total_lado2_incompleto"])
        self.assertContains(resp, "R$ 300,00")

    def test_valor_acima_de_mil_usa_ponto_como_separador_de_milhar(self):
        """Pedido do usuário: separador de milhar com ponto, decimal com
        vírgula (ex.: "10.356,00") — mesmo filtro `intcomma` (`django.
        contrib.humanize`) já usado nos totais em R$ do Dashboard."""
        KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 40 Access Points", lote=9,
            valor_equipamento="5000.00", valor_servico="10356.00",
        )
        RiItemIxc.objects.create(
            ri=self.ri, descricao_item="Kit Cobertura Wi-Fi - 40 Access Points",
            quantidade=1, valor_unitario="0.00", eh_kit=True,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertContains(resp, "R$ 10.356,00")


class MipValorTotalLado3Tests(TestCase):
    """RN-077 (a criar): coluna "Valor Total (EACE)" do grid do MIP —
    mesma soma quantidade × Valor de serviço da RN-076, agora sobre o
    Lado 3 (Relatório EACE, `EscolaItemRelatorioEaceMip`)."""

    def setUp(self):
        self.user = User.objects.create_user(username="analista-valor-total-eace", password="senha-teste-123")
        self.escola = Escola.objects.create(inep="10000031", nome="Escola Valor Total Eace", lote=9)
        Ri.objects.create(escola=self.escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)

    def test_coluna_valor_total_eace_aparece(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertContains(resp, "Valor Total (EACE)")

    def test_sem_item_no_lado3_mostra_travessao(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        linha = resp.context["page_obj"][0]
        self.assertIsNone(linha["valor_total_lado3"])

    def test_soma_quantidade_vezes_valor_de_servico_do_lado3(self):
        EscolaItemRelatorioEaceMip.objects.create(
            escola=self.escola, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
            quantidade=1, valor_servico="300.00", eh_kit=True,
        )
        EscolaItemRelatorioEaceMip.objects.create(
            escola=self.escola, descricao_item="Cabo de rede",
            quantidade=3, valor_servico="10.00", eh_kit=False,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        linha = resp.context["page_obj"][0]
        self.assertEqual(linha["valor_total_lado3"], Decimal("330.00"))
        self.assertFalse(linha["valor_total_lado3_incompleto"])
        self.assertContains(resp, "R$ 330,00")

    def test_item_sem_valor_de_servico_fica_fora_da_soma_e_avisa(self):
        """CLAUDE.md §9: item sem Valor de serviço preenchido não entra
        na soma — mas o total fica marcado como incompleto."""
        EscolaItemRelatorioEaceMip.objects.create(
            escola=self.escola, descricao_item="Kit sem valor",
            quantidade=1, valor_servico=None, eh_kit=True,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        linha = resp.context["page_obj"][0]
        self.assertEqual(linha["valor_total_lado3"], Decimal("0"))
        self.assertTrue(linha["valor_total_lado3_incompleto"])


class MipValorTotalDivergeTests(TestCase):
    """RN-077 (a criar): destaque em amarelo do Valor Total (EACE) quando
    diverge do Valor Total (IXC) — usuário pediu explicitamente esse
    destaque quando os dois totais são diferentes."""

    def setUp(self):
        self.user = User.objects.create_user(username="analista-valor-total-diverge", password="senha-teste-123")
        self.escola = Escola.objects.create(inep="10000032", nome="Escola Valor Diverge", lote=9)
        KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 2 Access Points", lote=9,
            valor_equipamento="1000.00", valor_servico="300.00",
        )
        self.ri = Ri.objects.create(escola=self.escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)

    def test_totais_iguais_nao_destaca(self):
        RiItemIxc.objects.create(
            ri=self.ri, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
            quantidade=1, valor_unitario="0.00", eh_kit=True,
        )
        EscolaItemRelatorioEaceMip.objects.create(
            escola=self.escola, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
            quantidade=1, valor_servico="300.00", eh_kit=True,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        linha = resp.context["page_obj"][0]
        self.assertFalse(linha["valor_total_diverge"])
        self.assertNotContains(resp, "Diverge do Valor Total (IXC)")

    def test_totais_diferentes_destaca_o_lado_eace(self):
        RiItemIxc.objects.create(
            ri=self.ri, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
            quantidade=1, valor_unitario="0.00", eh_kit=True,
        )
        EscolaItemRelatorioEaceMip.objects.create(
            escola=self.escola, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
            quantidade=1, valor_servico="250.00", eh_kit=True,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        linha = resp.context["page_obj"][0]
        self.assertTrue(linha["valor_total_diverge"])
        self.assertContains(resp, "Diverge do Valor Total (IXC)")
        self.assertContains(resp, "text-amber-500 dark:text-amber-400")

    def test_um_lado_sem_total_nao_diverge(self):
        """Mesmo critério da RN-003/RN-071: sem um dos dois lados ter
        total ainda, não há o que comparar."""
        RiItemIxc.objects.create(
            ri=self.ri, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
            quantidade=1, valor_unitario="0.00", eh_kit=True,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        linha = resp.context["page_obj"][0]
        self.assertFalse(linha["valor_total_diverge"])


class MipTotalGeralTests(TestCase):
    """RN-080 (a criar): linha de total geral (Valor Total IXC/EACE)
    abaixo do grid do MIP — soma todos os INEPs que passaram pelos
    filtros já aplicados, não só da página atual; muda ao aplicar
    qualquer filtro (pedido explícito do usuário)."""

    def setUp(self):
        self.user = User.objects.create_user(username="analista-total-geral", password="senha-teste-123")
        KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 2 Access Points", lote=9,
            valor_equipamento="1000.00", valor_servico="300.00",
        )
        self.escola_ce = Escola.objects.create(inep="10000050", nome="Escola CE Total", estado="CE", lote=9)
        self.escola_sp = Escola.objects.create(inep="10000051", nome="Escola SP Total", estado="SP", lote=9)
        self.ri_ce = Ri.objects.create(escola=self.escola_ce, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        self.ri_sp = Ri.objects.create(escola=self.escola_sp, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        RiItemIxc.objects.create(
            ri=self.ri_ce, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
            quantidade=1, valor_unitario="0.00", eh_kit=True,
        )
        RiItemIxc.objects.create(
            ri=self.ri_sp, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
            quantidade=2, valor_unitario="0.00", eh_kit=True,
        )
        EscolaItemRelatorioEaceMip.objects.create(
            escola=self.escola_ce, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
            quantidade=1, valor_servico="300.00", eh_kit=True,
        )

    def test_total_geral_soma_todos_os_ineps_filtrados(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        # IXC: 1 x 300,00 (CE) + 2 x 300,00 (SP) = 900,00
        self.assertEqual(resp.context["total_geral_lado2"], Decimal("900.00"))
        # EACE: só a CE tem item lançado = 300,00
        self.assertEqual(resp.context["total_geral_lado3"], Decimal("300.00"))
        self.assertContains(resp, "R$ 900,00")
        self.assertContains(resp, "R$ 300,00")

    def test_total_geral_muda_ao_filtrar_por_estado(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"), {"estado": "SP"})
        self.assertEqual(resp.context["total_geral_lado2"], Decimal("600.00"))
        self.assertEqual(resp.context["total_geral_lado3"], Decimal("0"))

    def test_total_geral_incompleto_mostra_asterisco(self):
        RiItemIxc.objects.create(
            ri=self.ri_ce, descricao_item="Produto fora do catálogo", quantidade=1,
            valor_unitario="0.00", eh_kit=False,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertTrue(resp.context["total_geral_lado2_incompleto"])

    def test_sem_resultado_nao_mostra_total_geral(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"), {"q": "inep-inexistente"})
        self.assertNotContains(resp, "Total geral")


class MipStatusPlanilhaMipTests(TestCase):
    """RN-081 (revista em 2026-09-14, pedido do usuário — bug reportado
    com o INEP 35583972): bolinha verde/vermelha no grid do MIP passa a
    refletir se o INEP TEM item lançado no Lado Relatório EACE (3º),
    calculado ao vivo — não mais só o resultado da ÚLTIMA sincronização
    (`Escola.encontrado_relatorio_eace_mip`, que continua existindo só
    para a lista separada "fora da Validação EACE", abaixo)."""

    def setUp(self):
        self.user = User.objects.create_user(username="analista-status-planilha", password="senha-teste-123")

    def test_com_item_no_lado3_mostra_bolinha_verde(self):
        escola = Escola.objects.create(inep="10000060", nome="Escola Verde", lote=9)
        Ri.objects.create(escola=escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        EscolaItemRelatorioEaceMip.objects.create(
            escola=escola, descricao_item="Kit Cobertura Wi-Fi", quantidade=1, valor_servico=Decimal("100.00"),
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        linha = resp.context["page_obj"][0]
        self.assertEqual(linha["status_planilha_mip"], "verde")
        self.assertContains(resp, "bg-emerald-500")

    def test_sem_item_no_lado3_mostra_bolinha_vermelha(self):
        escola = Escola.objects.create(inep="10000061", nome="Escola Vermelha", lote=9)
        Ri.objects.create(escola=escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        linha = resp.context["page_obj"][0]
        self.assertEqual(linha["status_planilha_mip"], "vermelho")

    def test_bug_35583972_item_de_sincronizacao_anterior_mostra_verde(self):
        """Caso real reportado pelo usuário (INEP 35583972): a última
        sincronização não trouxe o INEP de novo (`encontrado_relatorio_
        eace_mip=False`), mas ele já tinha item lançado de uma rodada
        anterior, com Valor Total (IXC) e (EACE) batendo — antes desta
        correção isso ficava vermelho, mesmo sem nenhum problema real no
        dado; agora fica verde, porque o dado existe."""
        escola = Escola.objects.create(
            inep="35583972", nome="Escola Bug Bolinha", lote=9, encontrado_relatorio_eace_mip=False,
        )
        Ri.objects.create(escola=escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        EscolaItemRelatorioEaceMip.objects.create(
            escola=escola, descricao_item="Kit Cobertura Wi-Fi", quantidade=1, valor_servico=Decimal("100.00"),
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        linha = resp.context["page_obj"][0]
        self.assertEqual(linha["status_planilha_mip"], "verde")

    def test_encontrado_na_ultima_sincronizacao_mas_sem_item_lancado_mostra_vermelha(self):
        """Simétrico ao teste acima: `encontrado_relatorio_eace_mip=True`
        sozinho não basta mais — sem item de verdade no Lado 3 (ex.: a
        linha da planilha não casou com nenhum item do catálogo), a
        bolinha é vermelha."""
        escola = Escola.objects.create(
            inep="10000067", nome="Escola Encontrada Sem Item", lote=9, encontrado_relatorio_eace_mip=True,
        )
        Ri.objects.create(escola=escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        linha = resp.context["page_obj"][0]
        self.assertEqual(linha["status_planilha_mip"], "vermelho")

    def test_nunca_sincronizado_mostra_bolinha_vermelha(self):
        """Sem nenhuma sincronização ainda (`encontrado_relatorio_eace_
        mip` nulo) e sem item lançado, a bolinha é vermelha — não há
        estado "sem bolinha" (a bolinha agora só depende de existir ou
        não item real no Lado 3, sempre calculável)."""
        escola = Escola.objects.create(inep="10000062", nome="Escola Sem Sync", lote=9)
        Ri.objects.create(escola=escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        linha = resp.context["page_obj"][0]
        self.assertEqual(linha["status_planilha_mip"], "vermelho")

    def test_encontrado_fora_da_validacao_eace_aparece_so_na_lista_a_parte(self):
        """RN-104 (2026-09-17): a escola NÃO aparece no grid principal
        (RI em "Em Andamento", nunca fez handoff) — só na lista "Fora da
        Validação EACE" (RN-081, sinaliza o descompasso da própria
        sincronização, sem relação com a visibilidade do grid)."""
        escola = Escola.objects.create(
            inep="10000063", nome="Escola Fora Validacao", estado="SP", municipio="Campinas", lote=9,
            encontrado_relatorio_eace_mip=True,
        )
        Ri.objects.create(escola=escola, status=Ri.ANDAMENTO)
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertEqual(resp.context["page_obj"].paginator.count, 0)
        self.assertEqual(list(resp.context["escolas_fora_da_validacao_eace"]), [escola])
        self.assertContains(resp, "Fora da Validação EACE")
        self.assertContains(resp, escola.inep)

    def test_nao_encontrado_nunca_aparece_na_lista_fora_da_validacao_eace(self):
        """RN-081: sem ter sido encontrado na última sincronização
        (`encontrado_relatorio_eace_mip=False`), o INEP nunca entra na
        lista separada "Fora da Validação EACE" — mesmo sem aparecer no
        grid principal (RN-104: sem RI, não há handoff)."""
        Escola.objects.create(
            inep="10000064", nome="Escola Irrelevante", lote=9, encontrado_relatorio_eace_mip=False,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertNotContains(resp, "10000064")
        self.assertEqual(list(resp.context["escolas_fora_da_validacao_eace"]), [])

    def test_sem_nenhum_fora_da_validacao_eace_nao_mostra_secao(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertNotContains(resp, "Fora da Validação EACE")

    def test_lista_a_parte_respeita_busca(self):
        escola_sp = Escola.objects.create(
            inep="10000065", nome="Escola SP Fora", estado="SP", lote=9, encontrado_relatorio_eace_mip=True,
        )
        escola_rj = Escola.objects.create(
            inep="10000066", nome="Escola RJ Fora", estado="RJ", lote=9, encontrado_relatorio_eace_mip=True,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"), {"q": "SP Fora"})
        self.assertContains(resp, escola_sp.inep)
        self.assertNotContains(resp, escola_rj.inep)


class MipDivergenciaValorServicoTests(TestCase):
    """RN-071 (a criar): confronto de Valor de serviço entre o Lado IXC
    (2º) e o Lado Relatório EACE do MIP (3º) — usuário pediu "as mesmas
    regras" do confronto formal do RI (RN-003), mas comparando Valor de
    serviço (nunca Quantidade nem Valor de equipamento)."""

    def setUp(self):
        self.user = User.objects.create_user(username="analista-divergencia", password="senha-teste-123")
        self.escola = Escola.objects.create(inep="10000009", nome="Escola Divergencia", lote=9)
        self.kit_2ap = KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 2 Access Points", lote=9,
            valor_equipamento="1000.00", valor_servico="300.00",
        )
        # RN-074 (a criar): só aparece na lista quem está em "Aguardando
        # validação EACE".
        self.ri = Ri.objects.create(escola=self.escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)

    def test_sem_divergencia_quando_lado3_esta_vazio(self):
        """Mesmo ajuste da RN-003 (2026-09-02): com um dos dois lados
        totalmente vazio, não há divergência."""
        RiItemIxc.objects.create(
            ri=self.ri, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
            quantidade=1, valor_unitario="0.00", eh_kit=True,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertNotContains(resp, "Valor de serviço diverge")

    def test_divergencia_quando_valor_do_kit_diverge(self):
        """Catálogo mudou depois da última sincronização do Lado 3 —
        Lado IXC resolve o valor ao vivo (300,00), Lado 3 ficou com o
        valor antigo (250,00) da sincronização anterior."""
        RiItemIxc.objects.create(
            ri=self.ri, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
            quantidade=1, valor_unitario="0.00", eh_kit=True,
        )
        EscolaItemRelatorioEaceMip.objects.create(
            escola=self.escola, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
            quantidade=1, valor_servico="250.00", eh_kit=True,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertEqual(resp.context["total_divergencia"], 1)
        self.assertContains(resp, "Valor de serviço diverge")

    def test_sem_divergencia_quando_valores_de_servico_batem(self):
        RiItemIxc.objects.create(
            ri=self.ri, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
            quantidade=1, valor_unitario="0.00", eh_kit=True,
        )
        EscolaItemRelatorioEaceMip.objects.create(
            escola=self.escola, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
            quantidade=1, valor_servico="300.00", eh_kit=True,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertNotContains(resp, "Valor de serviço diverge")

    def test_produto_avulso_com_valor_divergente(self):
        KitPadrao.objects.create(
            descricao="Rack de parede", lote=9,
            valor_equipamento="50.00", valor_servico="10.00",
        )
        RiItemIxc.objects.create(
            ri=self.ri, descricao_item="Rack de parede", quantidade=1,
            valor_unitario="0.00", eh_kit=False,
        )
        EscolaItemRelatorioEaceMip.objects.create(
            escola=self.escola, descricao_item="Rack de parede",
            quantidade=1, valor_servico="9.00", eh_kit=False,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertContains(resp, "Valor de serviço diverge")

    def test_produto_avulso_divergente_destaca_nome_no_lado3(self):
        """Usuário pediu para destacar em vermelho também o nome do
        produto divergente do Lado 3 (Relatório EACE), não só do Lado
        IXC — mesmo critério de divergência (Valor de serviço)."""
        KitPadrao.objects.create(
            descricao="Régua de Alimentação 5P", lote=9,
            valor_equipamento="500.00", valor_servico="479.77",
        )
        RiItemIxc.objects.create(
            ri=self.ri, descricao_item="Régua de Alimentação 5P", quantidade=1,
            valor_unitario="0.00", eh_kit=False,
        )
        item_mip = EscolaItemRelatorioEaceMip.objects.create(
            escola=self.escola, descricao_item="Régua de Alimentação 5P",
            quantidade=1, valor_servico="400.00", eh_kit=False,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        linha = resp.context["page_obj"][0]
        self.assertIn(item_mip.pk, linha["itens_mip_divergentes_pks"])

    def test_filtro_divergencia_mostra_so_divergentes(self):
        outra_escola = Escola.objects.create(inep="10000010", nome="Escola Sem Divergencia", lote=9)
        outro_ri = Ri.objects.create(escola=outra_escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        RiItemIxc.objects.create(
            ri=outro_ri, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
            quantidade=1, valor_unitario="0.00", eh_kit=True,
        )
        EscolaItemRelatorioEaceMip.objects.create(
            escola=outra_escola, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
            quantidade=1, valor_servico="300.00", eh_kit=True,
        )
        RiItemIxc.objects.create(
            ri=self.ri, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
            quantidade=1, valor_unitario="0.00", eh_kit=True,
        )
        EscolaItemRelatorioEaceMip.objects.create(
            escola=self.escola, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
            quantidade=1, valor_servico="250.00", eh_kit=True,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"), {"divergencia": "1"})
        self.assertContains(resp, self.escola.inep)
        self.assertNotContains(resp, outra_escola.inep)

    def test_detalhe_mostra_banner_de_divergencia(self):
        RiItemIxc.objects.create(
            ri=self.ri, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
            quantidade=1, valor_unitario="0.00", eh_kit=True,
        )
        EscolaItemRelatorioEaceMip.objects.create(
            escola=self.escola, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
            quantidade=1, valor_servico="250.00", eh_kit=True,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_detail", kwargs={"inep": self.escola.inep}))
        self.assertContains(resp, "Valor de serviço diverge")

    def test_detalhe_destaca_nome_do_produto_divergente_no_lado3(self):
        KitPadrao.objects.create(
            descricao="Régua de Alimentação 5P", lote=9,
            valor_equipamento="500.00", valor_servico="479.77",
        )
        RiItemIxc.objects.create(
            ri=self.ri, descricao_item="Régua de Alimentação 5P", quantidade=1,
            valor_unitario="0.00", eh_kit=False,
        )
        item_mip = EscolaItemRelatorioEaceMip.objects.create(
            escola=self.escola, descricao_item="Régua de Alimentação 5P",
            quantidade=1, valor_servico="400.00", eh_kit=False,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_detail", kwargs={"inep": self.escola.inep}))
        self.assertIn(item_mip.pk, resp.context["divergencia_valor_servico"]["itens_mip_divergentes_pks"])


_MEDIA_ROOT_TESTE_MIP_PERIODO = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=_MEDIA_ROOT_TESTE_MIP_PERIODO)
class MipFiltroPeriodoTests(TestCase):
    """RN-073 (a criar): card "No período" do grid do MIP — resolve a
    pendência de uso do período (Data inicial/Data final) do upload do
    Relatório EACE (MIP, RN-069): conta/filtra os INEPs com pelo menos um
    item do Lado 3 (`EscolaItemRelatorioEaceMip`, RN-070) cuja Data
    Emissão ACS cai dentro do período da planilha ativa — mesmo padrão
    de card/filtro do "Com divergência" (RN-071)."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT_TESTE_MIP_PERIODO, ignore_errors=True)

    def setUp(self):
        self.user = User.objects.create_user(username="analista-periodo-mip", password="senha-teste-123")
        self.admin = User.objects.create_user(
            username="admin-periodo-mip", password="senha-teste-123", perfil=User.PERFIL_ADMINISTRADOR,
        )
        self.escola_no_periodo = Escola.objects.create(inep="10000011", nome="Escola No Periodo", lote=9)
        self.escola_fora_do_periodo = Escola.objects.create(inep="10000012", nome="Escola Fora Do Periodo", lote=9)
        # RN-074 (a criar): só aparece na lista quem está em "Aguardando
        # validação EACE".
        Ri.objects.create(escola=self.escola_no_periodo, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        Ri.objects.create(escola=self.escola_fora_do_periodo, status=Ri.AGUARDANDO_VALIDACAO_EACE)

    def _ativar_planilha(self, data_inicial=datetime.date(2026, 9, 1), data_final=datetime.date(2026, 9, 30)):
        planilha = PlanilhaRelatorioEaceMip.substituir(_xlsx_relatorio_eace_mip(), self.admin)
        planilha.definir_periodo(data_inicial, data_final)
        return planilha

    def test_sem_planilha_ativa_nao_mostra_card(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertNotContains(resp, "No período")

    def test_planilha_ativa_sem_periodo_definido_nao_mostra_card(self):
        """RN-069 alterada: upload deixou de exigir o período — sem o
        usuário defini-lo ainda pelo card do Sincronizador, não há como
        calcular o card "No período"."""
        PlanilhaRelatorioEaceMip.substituir(_xlsx_relatorio_eace_mip(), self.admin)
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertNotContains(resp, "No período")

    def test_card_mostra_total_de_ineps_com_item_no_periodo(self):
        self._ativar_planilha()
        EscolaItemRelatorioEaceMip.objects.create(
            escola=self.escola_no_periodo, descricao_item="Rack de parede",
            quantidade=1, data_emissao_acs=datetime.date(2026, 9, 15),
        )
        EscolaItemRelatorioEaceMip.objects.create(
            escola=self.escola_fora_do_periodo, descricao_item="Rack de parede",
            quantidade=1, data_emissao_acs=datetime.date(2026, 10, 1),
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertContains(resp, "No período")
        self.assertEqual(resp.context["total_periodo"], 1)

    def test_filtro_periodo_mostra_so_ineps_no_periodo(self):
        self._ativar_planilha()
        EscolaItemRelatorioEaceMip.objects.create(
            escola=self.escola_no_periodo, descricao_item="Rack de parede",
            quantidade=1, data_emissao_acs=datetime.date(2026, 9, 15),
        )
        EscolaItemRelatorioEaceMip.objects.create(
            escola=self.escola_fora_do_periodo, descricao_item="Rack de parede",
            quantidade=1, data_emissao_acs=datetime.date(2026, 10, 1),
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"), {"periodo": "1"})
        self.assertContains(resp, self.escola_no_periodo.inep)
        self.assertNotContains(resp, self.escola_fora_do_periodo.inep)

    def test_item_sem_data_emissao_acs_nao_conta_no_periodo(self):
        self._ativar_planilha()
        EscolaItemRelatorioEaceMip.objects.create(
            escola=self.escola_no_periodo, descricao_item="Rack de parede", quantidade=1,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertEqual(resp.context["total_periodo"], 0)


class MipFiltroDataAtivacaoTests(TestCase):
    """RN-075 (revista em 2026-09-09): filtro por Data inicial/Data final
    do grid do MIP pela Data de Ativação (`Ri.data_ativacao`) do RI atual
    — campo do Lado IXC (2º lado, RN-011), preenchido manualmente pelo
    usuário. Antes desta revisão, o filtro usava a data em que o RI
    entrou em "Aguardando validação EACE" (log de status); usuário pediu
    a troca."""

    def setUp(self):
        self.user = User.objects.create_user(username="analista-data-ativacao", password="senha-teste-123")
        self.escola = Escola.objects.create(inep="10000020", nome="Escola Validacao Eace", lote=9)
        self.ri = Ri.objects.create(escola=self.escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)

    def _definir_data_ativacao(self, data):
        self.ri.data_ativacao = data
        self.ri.save(update_fields=["data_ativacao"])

    def test_sem_filtro_de_data_mostra_normalmente(self):
        self._definir_data_ativacao(datetime.date(2026, 9, 5))
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertContains(resp, self.escola.inep)

    def test_data_dentro_do_intervalo_mostra_o_inep(self):
        self._definir_data_ativacao(datetime.date(2026, 9, 5))
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"), {"data_inicial": "01/09/2026", "data_final": "10/09/2026"})
        self.assertContains(resp, self.escola.inep)

    def test_data_fora_do_intervalo_esconde_o_inep(self):
        self._definir_data_ativacao(datetime.date(2026, 8, 20))
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"), {"data_inicial": "01/09/2026", "data_final": "10/09/2026"})
        self.assertNotContains(resp, self.escola.inep)

    def test_so_data_inicial_filtra_a_partir_dela(self):
        self._definir_data_ativacao(datetime.date(2026, 8, 20))
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"), {"data_inicial": "01/09/2026"})
        self.assertNotContains(resp, self.escola.inep)

    def test_so_data_final_filtra_ate_ela(self):
        self._definir_data_ativacao(datetime.date(2026, 9, 15))
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"), {"data_final": "10/09/2026"})
        self.assertNotContains(resp, self.escola.inep)

    def test_ri_sem_data_ativacao_some_ao_filtrar_por_data(self):
        """RI já está em "Aguardando validação EACE" (aparece sem filtro
        de data), mas sem Data de Ativação preenchida no Lado IXC — não
        há data pra comparar, então some assim que um filtro de data é
        aplicado (CLAUDE.md §9: nunca inventa/assume um dado ausente)."""
        self.client.force_login(self.user)
        resp_sem_filtro = self.client.get(reverse("mip_inep"))
        self.assertContains(resp_sem_filtro, self.escola.inep)
        resp_com_filtro = self.client.get(reverse("mip_inep"), {"data_inicial": "01/01/2026", "data_final": "31/12/2026"})
        self.assertNotContains(resp_com_filtro, self.escola.inep)

    def test_data_inicial_depois_da_final_ignora_o_filtro_e_avisa(self):
        self._definir_data_ativacao(datetime.date(2026, 9, 5))
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"), {"data_inicial": "10/09/2026", "data_final": "01/09/2026"})
        self.assertContains(resp, self.escola.inep)
        self.assertContains(resp, "A data inicial não pode ser depois da data final")

    def test_data_em_formato_invalido_e_ignorada_silenciosamente(self):
        self._definir_data_ativacao(datetime.date(2026, 9, 5))
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"), {"data_inicial": "não-é-uma-data"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.escola.inep)

    def test_data_em_formato_iso_e_ignorada(self):
        """Depois da mudança pro formato dd/mm/aaaa (usuário pediu pra
        tirar o `<input type="date">` nativo), um valor em ISO
        (formato antigo) não é mais reconhecido — ignorado, não quebra."""
        self._definir_data_ativacao(datetime.date(2026, 9, 5))
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"), {"data_inicial": "2026-09-01"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.escola.inep)


class MipFiltroEstadoMunicipioTests(TestCase):
    """RN-079 (a criar): filtros Estado e Município (tipo lista) do grid
    do MIP — Estado só lista as UFs que já têm INEP na base do grid
    ("Aguardando Validação EACE", RN-104); Município só é filtrável
    depois de um Estado escolhido."""

    def setUp(self):
        self.user = User.objects.create_user(username="analista-estado-municipio", password="senha-teste-123")
        self.escola_ce_fortaleza = Escola.objects.create(
            inep="10000040", nome="Escola CE Fortaleza", estado="CE", municipio="Fortaleza",
        )
        self.escola_ce_sobral = Escola.objects.create(
            inep="10000041", nome="Escola CE Sobral", estado="CE", municipio="Sobral",
        )
        self.escola_sp = Escola.objects.create(
            inep="10000042", nome="Escola SP", estado="SP", municipio="Campinas",
        )
        self.escola_rj = Escola.objects.create(
            inep="10000043", nome="Escola RJ", estado="RJ", municipio="Niterói",
        )
        for escola in (self.escola_ce_fortaleza, self.escola_ce_sobral, self.escola_sp, self.escola_rj):
            Ri.objects.create(escola=escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)

    def test_select_estado_so_lista_uf_com_inep_na_base(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertEqual(sorted(resp.context["estados_disponiveis"]), ["CE", "RJ", "SP"])
        self.assertContains(resp, '<option value="CE"')
        self.assertContains(resp, '<option value="SP"')
        self.assertContains(resp, '<option value="RJ"')

    def test_filtro_estado_mostra_so_escolas_daquele_estado(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"), {"estado": "CE"})
        self.assertContains(resp, self.escola_ce_fortaleza.inep)
        self.assertContains(resp, self.escola_ce_sobral.inep)
        self.assertNotContains(resp, self.escola_sp.inep)

    def test_sem_estado_selecionado_select_municipio_fica_desabilitado(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertContains(resp, "data-select-placeholder disabled")

    def test_municipio_sem_estado_e_ignorado_mesmo_vindo_na_url(self):
        """Pedido do usuário: Município só funciona depois de escolher
        Estado — sem Estado, o filtro de Município nem é aplicado."""
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"), {"municipio": "Fortaleza"})
        self.assertEqual(resp.context["municipio_filtro"], "")
        self.assertContains(resp, self.escola_ce_fortaleza.inep)
        self.assertContains(resp, self.escola_ce_sobral.inep)
        self.assertContains(resp, self.escola_sp.inep)

    def test_select_municipio_lista_so_municipios_do_estado_escolhido(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"), {"estado": "CE"})
        self.assertEqual(sorted(resp.context["municipios_disponiveis"]), ["Fortaleza", "Sobral"])
        self.assertNotContains(resp, "data-select-placeholder disabled")

    def test_filtro_estado_e_municipio_juntos(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"), {"estado": "CE", "municipio": "Sobral"})
        self.assertContains(resp, self.escola_ce_sobral.inep)
        self.assertNotContains(resp, self.escola_ce_fortaleza.inep)
        self.assertNotContains(resp, self.escola_sp.inep)

    def test_estado_invalido_e_ignorado(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"), {"estado": "XX"})
        self.assertEqual(resp.context["estado_filtro"], "")
        self.assertContains(resp, self.escola_ce_fortaleza.inep)
        self.assertContains(resp, self.escola_sp.inep)

    def test_municipio_invalido_para_o_estado_e_ignorado(self):
        """Município de outro Estado (valor preso na URL de uma escolha
        anterior) some sem esvaziar o resultado inteiro — mesmo critério
        de "não inventar/assumir filtro" do CLAUDE.md §9."""
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"), {"estado": "CE", "municipio": "Campinas"})
        self.assertEqual(resp.context["municipio_filtro"], "")
        self.assertContains(resp, self.escola_ce_fortaleza.inep)
        self.assertContains(resp, self.escola_ce_sobral.inep)


class MipDetailViewTests(TestCase):
    """Tela aberta ao clicar em qualquer card do MIP — os 3 lados juntos
    (mesma estrutura da tela do RI, `ri_detail`), só leitura, mais o
    histórico do RI atual do INEP, reaproveitando `RiHistorico`/
    `ri/_historico_panel.html` (decisão combinada com o usuário,
    2026-09-07: um único histórico para RI e MIP, não um separado)."""

    def setUp(self):
        self.user = User.objects.create_user(username="analista", password="senha-teste-123")
        self.escola = Escola.objects.create(
            inep="10000001", nome="Escola Teste MIP", lote=9, kit_inicial="Kit Cobertura Wi-Fi - 8 Access Points",
        )
        KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 8 Access Points", lote=9,
            valor_equipamento="1000.00", valor_servico="250.00",
        )

    def test_exige_login(self):
        resp = self.client.get(reverse("mip_detail", kwargs={"inep": self.escola.inep}))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp.url)

    def test_inep_inexistente_da_404(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_detail", kwargs={"inep": "99999999"}))
        self.assertEqual(resp.status_code, 404)

    def test_mostra_os_3_lados_juntos(self):
        """Os 3 cards aparecem na mesma tela — não uma tela por lado."""
        ri = Ri.objects.create(escola=self.escola, status=Ri.ANDAMENTO)
        RiItemIxc.objects.create(
            ri=ri, descricao_item="Kit Cobertura Wi-Fi - 8 Access Points", quantidade=1,
            valor_unitario="0.00", eh_kit=True,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_detail", kwargs={"inep": self.escola.inep}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Kit declarado")
        self.assertContains(resp, "IXC")
        self.assertContains(resp, "Relatório EACE")
        # lado 1 (referência, sem lançamento) e lado 2 (lançado no RI), os dois com valor de serviço
        self.assertContains(resp, "referência, ainda não lançado no RI")
        self.assertContains(resp, "Kit Cobertura Wi-Fi - 8 Access Points — 1 un. —")
        self.assertContains(resp, "R$ 250,00")

    def test_sem_ri_mostra_aviso_de_historico(self):
        """RN-074 (a criar): sem RI, o INEP não aparece mais no grid do
        MIP, mas `mip_detail` continua acessível direto pela URL e sem
        filtro — lado 1 cai na referência ao vivo (RN-010) e lado 2 fica
        sem item, igual a antes."""
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_detail", kwargs={"inep": self.escola.inep}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Ainda não há RI iniciado para este INEP")
        self.assertContains(resp, "referência, ainda não lançado no RI")
        self.assertContains(resp, "Nenhum item lançado.")

    def test_com_ri_mostra_painel_de_historico_do_ri(self):
        ri = Ri.objects.create(escola=self.escola, status=Ri.ANDAMENTO)
        RiHistorico.objects.create(ri=ri, tipo=RiHistorico.MENSAGEM, autor=self.user, mensagem="Mensagem já registrada no RI")
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_detail", kwargs={"inep": self.escola.inep}))
        self.assertEqual(resp.status_code, 200)
        # Mesmo histórico do RI aparece aqui — não é um histórico separado do MIP.
        self.assertContains(resp, "Mensagem já registrada no RI")
        self.assertContains(resp, "Histórico de comunicação")
        # Formulário de nova mensagem posta pro mesmo endpoint do RI (RN combinada com o usuário).
        self.assertContains(resp, f'hx-post="{reverse("ri_detail", kwargs={"inep": self.escola.inep})}"')

    def test_lado3_ganha_dados_da_ri_com_linha_divisoria_quando_aguardando_validacao_eace(self):
        """RN-095 (2026-09-12): com o Status (MIP) em "Aguardando
        Validação EACE", o card Relatório EACE (3º) ganha também os dados
        do próprio Lado 3 da RI, acima de uma linha divisória — só para o
        usuário bater visualmente os 2 relatórios; o bloco de dados do
        MIP continua aparecendo do jeito de sempre, logo abaixo."""
        self.escola.status_mip = Escola.AGUARDANDO_VALIDACAO_EACE
        self.escola.save()
        ri = Ri.objects.create(escola=self.escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        RiItemRelatorioEace.objects.create(
            ri=ri, descricao_item="Nobreak", quantidade=1, valor_unitario=Decimal("150.00"),
        )
        KitPadrao.objects.create(
            descricao="Nobreak", lote=9, valor_equipamento="150.00", valor_servico="30.00",
        )
        EscolaItemRelatorioEaceMip.objects.create(
            escola=self.escola, descricao_item="Cabo de rede", quantidade=10,
            valor_servico=Decimal("20.00"),
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_detail", kwargs={"inep": self.escola.inep}))
        self.assertContains(resp, "Dados Relatório RI")
        self.assertContains(resp, "Dados Relatório MIP")
        # Dado da RI: valor de serviço vem do catálogo (R$ 30,00), nunca o
        # valor_unitario gravado no item (R$ 150,00, valor de equipamento).
        self.assertContains(resp, "Nobreak — 1 un. —")
        self.assertContains(resp, "R$ 30,00")
        self.assertNotContains(resp, "R$ 150,00")
        # Dado do MIP: continua aparecendo igual a antes.
        self.assertContains(resp, "Cabo de rede — 10 un. —")
        self.assertContains(resp, "R$ 20,00")

    def test_lado3_nao_ganha_dados_da_ri_fora_do_status_aguardando_validacao_eace(self):
        """Fora de "Aguardando Validação EACE" (RN-095), o card continua
        idêntico a antes — sem a linha divisória nem os dados da RI."""
        ri = Ri.objects.create(escola=self.escola, status=Ri.ANDAMENTO)
        RiItemRelatorioEace.objects.create(
            ri=ri, descricao_item="Nobreak", quantidade=1, valor_unitario=Decimal("150.00"),
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_detail", kwargs={"inep": self.escola.inep}))
        self.assertNotContains(resp, "Dados Relatório RI")
        self.assertNotContains(resp, "Dados Relatório MIP")
        self.assertNotContains(resp, "Nobreak")

    def test_os_3_cards_do_mip_linkam_para_a_mesma_tela_de_detalhe(self):
        # RN-074 (a criar): só aparece no grid quem está em "Aguardando
        # validação EACE".
        Ri.objects.create(escola=self.escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertContains(
            resp,
            reverse("mip_detail", kwargs={"inep": self.escola.inep}),
            count=3,
        )


class VisualizadorMipTests(TestCase):
    """RN-096 (2026-09-12): usuário Visualizador ganha acesso (só leitura)
    ao Projeto > MIP — mip_inep e mip_detail continuam mostrando os itens
    normalmente, mas sem nenhum valor financeiro ("R$ ..."), sem os
    controles de edição (Status (MIP), lançamento de equipamento só
    valor de serviço). O acesso técnico à rota é testado em
    `apps.core.tests.VisualizadorAccessMiddlewareTests`; aqui é só o que
    a própria tela mostra/esconde."""

    def setUp(self):
        self.visualizador = User.objects.create_user(
            username="visualizador-mip", password="senha-teste-123",
            perfil=User.PERFIL_VISUALIZADOR,
        )
        self.escola = Escola.objects.create(
            inep="10000001", nome="Escola Visualizador MIP", lote=9,
            status_mip=Escola.AGUARDANDO_VALIDACAO_EACE,
        )
        KitPadrao.objects.create(
            descricao="Nobreak", lote=9, valor_equipamento="150.00", valor_servico="30.00",
        )
        self.ri = Ri.objects.create(escola=self.escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        RiItemIxc.objects.create(
            ri=self.ri, descricao_item="Nobreak", quantidade=1, valor_unitario="150.00",
        )
        EscolaItemRelatorioEaceMip.objects.create(
            escola=self.escola, descricao_item="Cabo de rede", quantidade=10,
            valor_servico=Decimal("20.00"),
        )

    def test_grid_do_mip_esconde_valor_financeiro(self):
        self.client.force_login(self.visualizador)
        resp = self.client.get(reverse("mip_inep"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "R$")
        self.assertNotContains(resp, "Valor Total (IXC)")
        self.assertNotContains(resp, "Valor Total (EACE)")
        # Descrição/quantidade continuam aparecendo — só o valor some.
        self.assertContains(resp, "Nobreak")
        self.assertContains(resp, "Cabo de rede")

    def test_grid_do_mip_mostra_valor_financeiro_para_quem_nao_e_visualizador(self):
        """Regressão: ninguém além do Visualizador perde o valor."""
        analista = User.objects.create_user(
            username="analista-mip-valor", password="senha-teste-123",
        )
        self.client.force_login(analista)
        resp = self.client.get(reverse("mip_inep"))
        self.assertContains(resp, "R$")
        self.assertContains(resp, "Valor Total (IXC)")

    def test_detalhe_do_mip_esconde_valor_financeiro(self):
        self.client.force_login(self.visualizador)
        resp = self.client.get(reverse("mip_detail", kwargs={"inep": self.escola.inep}))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "R$")
        self.assertContains(resp, "Nobreak")
        self.assertContains(resp, "Cabo de rede")

    def test_detalhe_do_mip_mostra_status_como_texto_sem_formulario(self):
        """Visualizador vê o Status (MIP), só não troca — sem o
        `<select>`/formulário de edição."""
        self.client.force_login(self.visualizador)
        resp = self.client.get(reverse("mip_detail", kwargs={"inep": self.escola.inep}))
        self.assertContains(resp, "Aguardando Validação EACE")
        self.assertNotContains(resp, 'name="status_mip"')
        self.assertNotContains(resp, reverse("mip_status_update", kwargs={"inep": self.escola.inep}))

    def test_detalhe_do_mip_esconde_lancamento_de_equipamento_so_servico(self):
        self.client.force_login(self.visualizador)
        resp = self.client.get(reverse("mip_detail", kwargs={"inep": self.escola.inep}))
        self.assertNotContains(resp, "Equipamento (só valor de serviço)")
        self.assertNotContains(
            resp, reverse("mip_item_ixc_somente_servico_salvar", kwargs={"inep": self.escola.inep})
        )

    def test_detalhe_do_mip_mostra_total_dos_lados_para_quem_nao_e_visualizador(self):
        """RN-097 (2026-09-12): total (Quantidade × Valor de serviço) de
        cada um dos 3 lados, abaixo da lista de itens."""
        analista = User.objects.create_user(
            username="analista-mip-total", password="senha-teste-123",
        )
        self.client.force_login(analista)
        resp = self.client.get(reverse("mip_detail", kwargs={"inep": self.escola.inep}))
        self.assertContains(resp, "R$ 30,00")  # total do Lado 2 (IXC: 1 Nobreak × R$ 30,00)
        self.assertContains(resp, "R$ 200,00")  # total do Lado 3 (MIP: 10 Cabo de rede × R$ 20,00)
        self.assertContains(resp, "nenhum item lançado")  # total do Lado 1 (Kit declarado vazio)

    def test_detalhe_do_mip_esconde_total_dos_lados_do_visualizador(self):
        self.client.force_login(self.visualizador)
        resp = self.client.get(reverse("mip_detail", kwargs={"inep": self.escola.inep}))
        self.assertNotContains(resp, "Total:")


class MipStatusUpdateViewTests(TestCase):
    """RN-092 (revista em 2026-09-10): troca do Status (MIP). "Aguardando
    Validação EACE"/"Faturamento Concluído" só mexem em `Escola.
    status_mip` (label do MIP). "Em Andamento" é diferente — é o mesmo
    `Ri.status="andamento"` de sempre: libera todo o acesso de edição que
    "Em Andamento" já tem hoje no grid de Equipamentos (RN-011/RN-052).
    RN-104 (2026-09-17): essa troca tira o INEP do grid principal do MIP
    (só lista "Aguardando Validação EACE"), mas ele nunca sai do Grid de
    Equipamentos, que continua mostrando toda Escola sempre."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="analista", password="senha-teste-123", perfil=User.PERFIL_ANALISTA,
        )
        self.admin = User.objects.create_user(
            username="admin-mip-status", password="senha-teste-123", perfil=User.PERFIL_ADMINISTRADOR,
        )
        self.escola = Escola.objects.create(
            inep="10000001", nome="Escola Teste", status_mip=Escola.AGUARDANDO_VALIDACAO_EACE,
        )
        self.ri = Ri.objects.create(escola=self.escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)

    def test_exige_login(self):
        resp = self.client.post(
            reverse("mip_status_update", kwargs={"inep": self.escola.inep}),
            {"status_mip": Escola.EM_ANDAMENTO},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp.url)

    def test_em_andamento_muda_o_ri_de_verdade_e_continua_aparecendo_no_grid_de_equipamentos(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("mip_status_update", kwargs={"inep": self.escola.inep}),
            {"status_mip": Escola.EM_ANDAMENTO},
        )
        self.escola.refresh_from_db()
        self.ri.refresh_from_db()
        self.assertEqual(self.escola.status_mip, Escola.EM_ANDAMENTO)
        self.assertEqual(self.ri.status, Ri.ANDAMENTO)
        # Mesmo log automático de troca de status do RI (RN-008), não um
        # log separado do MIP — é o mesmo `trocar_status_com_log`.
        self.assertTrue(
            self.ri.historico.filter(tipo=RiHistorico.LOG_STATUS, campo="Status do RI").exists()
        )
        # RN-103/ADR-006: o INEP já aparecia aqui antes da troca também —
        # esta chamada só confirma que continua aparecendo, não que "voltou".
        resp = self.client.get(reverse("grid_inep"))
        self.assertContains(resp, self.escola.inep)

    def test_em_andamento_bloqueado_pela_mesma_regra_do_ri_rn020(self):
        """RN-020: com o RI em "Faturamento Concluído", só Administrador
        muda o status — vale também pra tentativa de "Em Andamento" vinda
        do MIP, porque reaproveita a mesma validação do RI."""
        self.escola.status_mip = Escola.FATURAMENTO_CONCLUIDO
        self.escola.save()
        self.ri.status = Ri.FATURAMENTO_CONCLUIDO
        self.ri.save()
        self.client.force_login(self.user)
        self.client.post(
            reverse("mip_status_update", kwargs={"inep": self.escola.inep}),
            {"status_mip": Escola.EM_ANDAMENTO},
        )
        self.escola.refresh_from_db()
        self.ri.refresh_from_db()
        self.assertEqual(self.escola.status_mip, Escola.FATURAMENTO_CONCLUIDO)
        self.assertEqual(self.ri.status, Ri.FATURAMENTO_CONCLUIDO)

    def test_administrador_consegue_em_andamento_a_partir_de_faturamento_concluido(self):
        self.escola.status_mip = Escola.FATURAMENTO_CONCLUIDO
        self.escola.save()
        self.ri.status = Ri.FATURAMENTO_CONCLUIDO
        self.ri.save()
        self.client.force_login(self.admin)
        self.client.post(
            reverse("mip_status_update", kwargs={"inep": self.escola.inep}),
            {"status_mip": Escola.EM_ANDAMENTO},
        )
        self.escola.refresh_from_db()
        self.ri.refresh_from_db()
        self.assertEqual(self.escola.status_mip, Escola.EM_ANDAMENTO)
        self.assertEqual(self.ri.status, Ri.ANDAMENTO)

    def test_aguardando_validacao_eace_so_mexe_no_status_mip(self):
        """Ida/volta pra "Aguardando Validação EACE" direto do MIP não
        mexe no `Ri.status` — só quem faz isso é "Em Andamento"."""
        self.escola.status_mip = Escola.EM_ANDAMENTO
        self.escola.save()
        self.ri.status = Ri.ANDAMENTO
        self.ri.save()
        self.client.force_login(self.user)
        self.client.post(
            reverse("mip_status_update", kwargs={"inep": self.escola.inep}),
            {"status_mip": Escola.AGUARDANDO_VALIDACAO_EACE},
        )
        self.escola.refresh_from_db()
        self.ri.refresh_from_db()
        self.assertEqual(self.escola.status_mip, Escola.AGUARDANDO_VALIDACAO_EACE)
        self.assertEqual(self.ri.status, Ri.ANDAMENTO)  # Ri.status nao mudou
        self.assertTrue(
            self.ri.historico.filter(tipo=RiHistorico.LOG_CAMPO, campo="Status (MIP)").exists()
        )

    def test_valor_invalido_nao_altera_nada(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("mip_status_update", kwargs={"inep": self.escola.inep}),
            {"status_mip": "valor-invalido"},
        )
        self.escola.refresh_from_db()
        self.assertEqual(self.escola.status_mip, Escola.AGUARDANDO_VALIDACAO_EACE)

    def test_sem_ri_nao_consegue_ir_para_em_andamento(self):
        escola_sem_ri = Escola.objects.create(
            inep="10000002", nome="Escola Sem RI", status_mip=Escola.AGUARDANDO_VALIDACAO_EACE,
        )
        self.client.force_login(self.user)
        self.client.post(
            reverse("mip_status_update", kwargs={"inep": escola_sem_ri.inep}),
            {"status_mip": Escola.EM_ANDAMENTO},
        )
        escola_sem_ri.refresh_from_db()
        self.assertEqual(escola_sem_ri.status_mip, Escola.AGUARDANDO_VALIDACAO_EACE)


class MipItemIxcSomenteServicoTests(TestCase):
    """RN-089/RN-092 (ampliação, 2026-09-10): equipamento só valor de
    serviço (LPU sem "Equipamentos R$") pode ser lançado/excluído direto
    no MIP quando `Escola.status_mip == "Aguardando Validação EACE"` —
    exceção pontual, nunca o KIT nem um Produto normal, e sem precisar
    mandar o INEP de volta pra "Em Andamento"."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="analista-mip-servico", password="senha-teste-123", perfil=User.PERFIL_ANALISTA,
        )
        self.admin = User.objects.create_user(
            username="admin-mip-servico", password="senha-teste-123", perfil=User.PERFIL_ADMINISTRADOR,
        )
        self.escola = Escola.objects.create(
            inep="10000001", nome="Escola Teste", lote=9, status_mip=Escola.AGUARDANDO_VALIDACAO_EACE,
        )
        self.ri = Ri.objects.create(escola=self.escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        self.injetor = KitPadrao.objects.create(
            descricao="Injetor PoE (serviço, material, equipamento)", lote=9, unidade="Unidade",
            valor_equipamento=None, valor_servico="564.04",
        )
        self.kit_normal = KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 2 Access Points", lote=9, unidade="Escola",
            valor_equipamento="1000.00", valor_servico="200.00",
        )

    def test_lancar_equipamento_quando_aguardando_validacao_eace(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("mip_item_ixc_somente_servico_salvar", kwargs={"inep": self.escola.inep}),
            {
                "produto_servico_mip-TOTAL_FORMS": 1, "produto_servico_mip-INITIAL_FORMS": 0,
                "produto_servico_mip-0-produto": self.injetor.pk, "produto_servico_mip-0-quantidade": 2,
            },
        )
        item = self.ri.itens_ixc.get()
        self.assertEqual(item.descricao_item, "Injetor PoE")
        self.assertEqual(item.quantidade, 2)
        self.assertEqual(item.valor_unitario, Decimal("0"))
        self.assertFalse(item.eh_kit)

    def test_lancamento_bloqueado_fora_de_aguardando_validacao_eace(self):
        self.escola.status_mip = Escola.EM_ANDAMENTO
        self.escola.save()
        self.client.force_login(self.user)
        self.client.post(
            reverse("mip_item_ixc_somente_servico_salvar", kwargs={"inep": self.escola.inep}),
            {
                "produto_servico_mip-TOTAL_FORMS": 1, "produto_servico_mip-INITIAL_FORMS": 0,
                "produto_servico_mip-0-produto": self.injetor.pk, "produto_servico_mip-0-quantidade": 2,
            },
        )
        self.assertFalse(self.ri.itens_ixc.exists())

    def test_catalogo_nao_aceita_kit_nem_produto_normal(self):
        """O formset só oferece o catálogo restrito (RN-089) — um `pk` de
        KIT (Unidade "Escola", com valor de equipamento) é inválido."""
        self.client.force_login(self.user)
        self.client.post(
            reverse("mip_item_ixc_somente_servico_salvar", kwargs={"inep": self.escola.inep}),
            {
                "produto_servico_mip-TOTAL_FORMS": 1, "produto_servico_mip-INITIAL_FORMS": 0,
                "produto_servico_mip-0-produto": self.kit_normal.pk, "produto_servico_mip-0-quantidade": 1,
            },
        )
        self.assertFalse(self.ri.itens_ixc.exists())

    def test_excluir_item_administrador(self):
        item = RiItemIxc.objects.create(
            ri=self.ri, descricao_item="Injetor PoE", quantidade=1, valor_unitario="0",
        )
        self.client.force_login(self.admin)
        self.client.post(
            reverse("mip_item_ixc_somente_servico_delete", kwargs={"item_pk": item.pk})
        )
        self.assertFalse(RiItemIxc.objects.filter(pk=item.pk).exists())

    def test_excluir_item_analista_e_negado(self):
        item = RiItemIxc.objects.create(
            ri=self.ri, descricao_item="Injetor PoE", quantidade=1, valor_unitario="0",
        )
        self.client.force_login(self.user)
        resp = self.client.post(
            reverse("mip_item_ixc_somente_servico_delete", kwargs={"item_pk": item.pk})
        )
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(RiItemIxc.objects.filter(pk=item.pk).exists())

    def test_nao_exclui_kit_nem_produto_normal_por_esta_rota(self):
        """Mesmo o Administrador não consegue excluir o KIT ou um Produto
        normal por esta rota restrita — só itens do catálogo RN-089."""
        item_kit = RiItemIxc.objects.create(
            ri=self.ri, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
            quantidade=1, valor_unitario="0", eh_kit=True,
        )
        item_produto = RiItemIxc.objects.create(
            ri=self.ri, descricao_item="Produto Qualquer", quantidade=1, valor_unitario="0",
        )
        self.client.force_login(self.admin)
        resp_kit = self.client.post(
            reverse("mip_item_ixc_somente_servico_delete", kwargs={"item_pk": item_kit.pk})
        )
        resp_produto = self.client.post(
            reverse("mip_item_ixc_somente_servico_delete", kwargs={"item_pk": item_produto.pk})
        )
        self.assertEqual(resp_kit.status_code, 403)
        self.assertEqual(resp_produto.status_code, 403)
        self.assertTrue(RiItemIxc.objects.filter(pk=item_kit.pk).exists())
        self.assertTrue(RiItemIxc.objects.filter(pk=item_produto.pk).exists())

    def test_exclusao_bloqueada_fora_de_aguardando_validacao_eace(self):
        item = RiItemIxc.objects.create(
            ri=self.ri, descricao_item="Injetor PoE", quantidade=1, valor_unitario="0",
        )
        self.escola.status_mip = Escola.EM_ANDAMENTO
        self.escola.save()
        self.client.force_login(self.admin)
        self.client.post(
            reverse("mip_item_ixc_somente_servico_delete", kwargs={"item_pk": item.pk})
        )
        self.assertTrue(RiItemIxc.objects.filter(pk=item.pk).exists())

    def test_tela_do_mip_mostra_formulario_so_com_status_correto(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_detail", kwargs={"inep": self.escola.inep}))
        self.assertContains(resp, "Equipamento (só valor de serviço)")

        self.escola.status_mip = Escola.EM_ANDAMENTO
        self.escola.save()
        resp2 = self.client.get(reverse("mip_detail", kwargs={"inep": self.escola.inep}))
        self.assertNotContains(resp2, "Equipamento (só valor de serviço)")


_MEDIA_ROOT_TESTE_MIP_NF_FINANCEIRO = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=_MEDIA_ROOT_TESTE_MIP_NF_FINANCEIRO)
class MipDetailLado2NfRecebidaEmTests(TestCase):
    """Data do recebimento do e-mail do financeiro (Nota Fiscal PDF + XML,
    RF-08) junto do Lado 2 (IXC) do MIP — pedido do usuário em 2026-09-07.
    MEDIA_ROOT isolado num diretório temporário para os arquivos de teste
    não irem para o `media/` real."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT_TESTE_MIP_NF_FINANCEIRO, ignore_errors=True)

    def setUp(self):
        self.user = User.objects.create_user(username="analista-mip-nf", password="senha-teste-123")
        self.escola = Escola.objects.create(inep="10000002", nome="Escola Teste MIP NF")
        self.ri = Ri.objects.create(escola=self.escola, status=Ri.ANDAMENTO)

    def test_sem_ri_nao_mostra_data(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_detail", kwargs={"inep": self.escola.inep}))
        self.assertNotContains(resp, "Nota Fiscal recebida do financeiro em")

    def test_ri_sem_documento_nao_mostra_data(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_detail", kwargs={"inep": self.escola.inep}))
        self.assertNotContains(resp, "Nota Fiscal recebida do financeiro em")

    def test_mostra_data_de_recebimento_do_pdf_e_xml_do_financeiro(self):
        recebido_em = timezone.make_aware(datetime.datetime(2026, 9, 5, 14, 30))
        Documento.objects.create(
            ri=self.ri, tipo=Documento.NOTA_FISCAL_PDF,
            arquivo=SimpleUploadedFile("nota.pdf", b"%PDF-fake"), recebido_em=recebido_em,
        )
        Documento.objects.create(
            ri=self.ri, tipo=Documento.XML,
            arquivo=SimpleUploadedFile("nota.xml", b"<nfe/>"), recebido_em=recebido_em,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_detail", kwargs={"inep": self.escola.inep}))
        self.assertContains(resp, "Nota Fiscal recebida do financeiro em 05/09/2026")

    def test_com_mais_de_uma_nf_mostra_so_a_data_mais_recente(self):
        """RI com mais de 1 Nota Fiscal (mais de 1 resposta do financeiro) —
        decisão combinada com o usuário: mostra só a mais recente, não uma
        lista por Nota Fiscal."""
        Documento.objects.create(
            ri=self.ri, tipo=Documento.NOTA_FISCAL_PDF,
            arquivo=SimpleUploadedFile("nota1.pdf", b"%PDF-fake"),
            recebido_em=timezone.make_aware(datetime.datetime(2026, 9, 1, 10, 0)),
        )
        Documento.objects.create(
            ri=self.ri, tipo=Documento.NOTA_FISCAL_PDF,
            arquivo=SimpleUploadedFile("nota2.pdf", b"%PDF-fake"),
            recebido_em=timezone.make_aware(datetime.datetime(2026, 9, 5, 14, 30)),
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_detail", kwargs={"inep": self.escola.inep}))
        self.assertContains(resp, "Nota Fiscal recebida do financeiro em 05/09/2026")
        self.assertNotContains(resp, "Nota Fiscal recebida do financeiro em 01/09/2026")


def _xlsx_relatorio_eace_mip(nome="relatorio.xlsx", cabecalho=None):
    """Gera um .xlsx mínimo no formato exigido pelo upload do Relatório
    EACE (MIP) — só o cabeçalho, sem se preocupar com o conteúdo das
    linhas (a leitura das linhas ainda não foi implementada, RelatorioEaceMipViewTests)."""
    if cabecalho is None:
        cabecalho = list(PlanilhaRelatorioEaceMip.COLUNAS_OBRIGATORIAS)
    workbook = openpyxl.Workbook()
    planilha = workbook.active
    planilha.title = "_Base contrato_taxa_instalação"
    planilha.append(cabecalho)
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return SimpleUploadedFile(
        nome, buffer.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


_MEDIA_ROOT_TESTE_RELATORIO_EACE_MIP = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=_MEDIA_ROOT_TESTE_RELATORIO_EACE_MIP)
class RelatorioEaceMipViewTests(TestCase):
    """FEAT-034/FEAT-035: upload da planilha de origem do Lado 3
    (Relatório EACE) do MIP, tela "Administrador > Relatório EACE (MIP)".
    Fonte real informada pelo usuário: "Base MIP.xlsx". MEDIA_ROOT isolado
    num diretório temporário para o arquivo de teste não ir para o
    `media/` real."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT_TESTE_RELATORIO_EACE_MIP, ignore_errors=True)

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin-relatorio-eace-mip", password="senha-teste-123",
            perfil=User.PERFIL_ADMINISTRADOR,
        )
        self.analista = User.objects.create_user(
            username="analista-relatorio-eace-mip", password="senha-teste-123",
            perfil=User.PERFIL_ANALISTA,
        )

    def _post(self, arquivo=None):
        if arquivo is None:
            arquivo = _xlsx_relatorio_eace_mip()
        return self.client.post(reverse("relatorio_eace_mip"), {"arquivo": arquivo})

    def test_upload_valido_cria_planilha_ativa_sem_periodo_definido(self):
        """RN-069 alterada (usuário pediu): o período deixou de ser
        exigido no upload — 1ª importação fica sem período até o usuário
        defini-lo pelo card do Sincronizador (RN-073)."""
        self.client.force_login(self.admin)
        resp = self._post(_xlsx_relatorio_eace_mip(nome="relatorio.xlsx"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(PlanilhaRelatorioEaceMip.objects.count(), 1)
        planilha = PlanilhaRelatorioEaceMip.objects.first()
        self.assertEqual(planilha.nome_original, "relatorio.xlsx")
        self.assertIsNone(planilha.data_inicial)
        self.assertIsNone(planilha.data_final)
        self.assertEqual(planilha.enviado_por, self.admin)

    def test_upload_sem_extensao_xlsx_e_rejeitado(self):
        self.client.force_login(self.admin)
        arquivo = SimpleUploadedFile("relatorio.csv", b"conteudo\n", content_type="text/csv")
        resp = self._post(arquivo)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(PlanilhaRelatorioEaceMip.objects.count(), 0)
        self.assertContains(resp, "Envie um arquivo .xlsx")

    def test_upload_com_coluna_obrigatoria_faltando_e_rejeitado(self):
        self.client.force_login(self.admin)
        arquivo = _xlsx_relatorio_eace_mip(cabecalho=["Projeto", "Descrição do Item"])
        resp = self._post(arquivo)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(PlanilhaRelatorioEaceMip.objects.count(), 0)
        self.assertContains(resp, "Nenhuma aba do arquivo tem as colunas obrigatórias")

    def test_novo_upload_preserva_periodo_do_anterior(self):
        """Usuário pediu para não precisar reimportar o arquivo só para
        ajustar a data — o período sobrevive a um novo upload."""
        self.client.force_login(self.admin)
        self._post(_xlsx_relatorio_eace_mip(nome="relatorio_v1.xlsx"))
        planilha = PlanilhaRelatorioEaceMip.objects.first()
        planilha.definir_periodo(datetime.date(2026, 9, 1), datetime.date(2026, 9, 30))
        arquivo_antigo = planilha.arquivo
        self._post(_xlsx_relatorio_eace_mip(nome="relatorio_v2.xlsx"))
        self.assertEqual(PlanilhaRelatorioEaceMip.objects.count(), 1)
        nova_planilha = PlanilhaRelatorioEaceMip.objects.first()
        self.assertEqual(nova_planilha.nome_original, "relatorio_v2.xlsx")
        self.assertEqual(nova_planilha.data_inicial, datetime.date(2026, 9, 1))
        self.assertEqual(nova_planilha.data_final, datetime.date(2026, 9, 30))
        self.assertFalse(arquivo_antigo.storage.exists(arquivo_antigo.name))

    def test_analista_nao_acessa(self):
        self.client.force_login(self.analista)
        resp = self.client.get(reverse("relatorio_eace_mip"))
        self.assertEqual(resp.status_code, 403)

    def test_pagina_exibe_planilha_ativa(self):
        PlanilhaRelatorioEaceMip.substituir(_xlsx_relatorio_eace_mip(nome="relatorio.xlsx"), self.admin)
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("relatorio_eace_mip"))
        self.assertContains(resp, "relatorio.xlsx")

    def test_pagina_nao_tem_mais_campo_de_periodo(self):
        """RN-090 (2026-09-09): usuário pediu para tirar as datas (Data
        inicial/Data final) da tela de importar/sincronizar — não há
        mais formulário de período aqui, só o upload do arquivo."""
        PlanilhaRelatorioEaceMip.substituir(_xlsx_relatorio_eace_mip(nome="relatorio.xlsx"), self.admin)
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("relatorio_eace_mip"))
        self.assertNotContains(resp, "Período coberto pela planilha")
        self.assertNotContains(resp, "Salvar período")

    def test_input_de_arquivo_mostra_rotulo_em_portugues(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("relatorio_eace_mip"))
        self.assertContains(resp, "Escolher arquivo")
        self.assertContains(resp, "Nenhum arquivo selecionado")
        self.assertNotContains(resp, "Choose File")


_CABECALHO_RELATORIO_EACE_MIP = [
    "Projeto", "Cod Fornecedor", "Descrição do Item", "Qtde Produto",
    "Valor Unit UR", "Data Emissão ACS", "UF", "CIDADE",
]


def _xlsx_relatorio_eace_mip_com_linhas(linhas, nome="relatorio.xlsx"):
    """.xlsx com linhas de dados reais (RelatorioEaceMipSincronizarTodasViewTests)
    — cada linha é uma tupla na ordem de `_CABECALHO_RELATORIO_EACE_MIP`
    (Projeto, Cod Fornecedor, Descrição do Item, Qtde Produto, Valor Unit
    UR, Data Emissão ACS, UF, CIDADE)."""
    workbook = openpyxl.Workbook()
    planilha = workbook.active
    planilha.title = "_Base contrato_taxa_instalação"
    planilha.append(_CABECALHO_RELATORIO_EACE_MIP)
    for linha in linhas:
        planilha.append(list(linha))
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return SimpleUploadedFile(
        nome, buffer.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


_MEDIA_ROOT_TESTE_RELATORIO_EACE_MIP_SYNC = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=_MEDIA_ROOT_TESTE_RELATORIO_EACE_MIP_SYNC)
class RelatorioEaceMipSincronizarTodasViewTests(TestCase):
    """Botão "Sincronizar todos os INEPs" — usuário pediu "as mesmas
    regras de sincronização do RI" (RN-070): casamento Descrição×catálogo
    idêntico ao Sincronizador do RI (RN-022, reaproveita
    `casar_planilha_eace_com_catalogo`/`quantidade_planilha_eace`), mas
    grava em `EscolaItemRelatorioEaceMip`, por Escola, com o Valor de
    serviço (RN-067) em vez do Valor de equipamento usado no RI."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT_TESTE_RELATORIO_EACE_MIP_SYNC, ignore_errors=True)

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin-sync-relatorio-eace-mip", password="senha-teste-123",
            perfil=User.PERFIL_ADMINISTRADOR,
        )
        self.analista = User.objects.create_user(
            username="analista-sync-relatorio-eace-mip", password="senha-teste-123",
            perfil=User.PERFIL_ANALISTA,
        )
        self.escola = Escola.objects.create(inep="53004230", nome="Escola Teste Sync", lote=9)
        self.kit_2ap = KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 2 Access Points", lote=9,
            valor_equipamento="1000.00", valor_servico="300.00",
        )
        self.produto_avulso = KitPadrao.objects.create(
            descricao="Rack de parede", lote=9,
            valor_equipamento="50.00", valor_servico="10.00",
        )

    def _ativar_planilha(self, linhas):
        # Sincronização não depende do período (Data inicial/Data final,
        # RN-069 alterada) — só do arquivo ativo.
        PlanilhaRelatorioEaceMip.substituir(_xlsx_relatorio_eace_mip_com_linhas(linhas), self.admin)

    def test_exige_login(self):
        resp = self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp.url)

    def test_analista_nao_acessa(self):
        self.client.force_login(self.analista)
        resp = self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"))
        self.assertEqual(resp.status_code, 403)

    def test_sem_planilha_ativa_mostra_erro(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"), follow=True)
        self.assertContains(resp, "Nenhum Relatório EACE (MIP) ativo")
        self.assertEqual(EscolaItemRelatorioEaceMip.objects.count(), 0)

    def test_sincroniza_cria_item_do_lado3_kit(self):
        self._ativar_planilha([
            ("53004230", "19001", "Kit Cobertura Wi-Fi - 2 Access Points - Serv - MEGA - SE", 1,
             "15728.61", "19/08/2026", "SP", "Atibaia"),
        ])
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"), follow=True)
        self.assertContains(resp, "1 INEP(s) atualizado(s)")
        item = EscolaItemRelatorioEaceMip.objects.get(escola=self.escola)
        self.assertEqual(item.descricao_item, "Kit Cobertura Wi-Fi - 2 Access Points")
        self.assertEqual(item.quantidade, 1)
        self.assertEqual(str(item.valor_servico), "300.00")
        self.assertTrue(item.eh_kit)
        self.assertEqual(item.uf, "SP")
        self.assertEqual(item.cidade, "Atibaia")
        self.assertEqual(item.data_emissao_acs, datetime.date(2026, 8, 19))

    def test_sincroniza_cria_item_produto_avulso(self):
        self._ativar_planilha([
            ("53004230", "19001", "Rack de parede - Equip - MEGA - SE", 3, "10.00", "19/08/2026", "SP", "Atibaia"),
        ])
        self.client.force_login(self.admin)
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"))
        item = EscolaItemRelatorioEaceMip.objects.get(escola=self.escola)
        self.assertEqual(item.quantidade, 3)
        self.assertFalse(item.eh_kit)

    def test_sincronizacao_seguinte_atualiza_valor_e_data_alterados(self):
        self._ativar_planilha([
            ("53004230", "19001", "Kit Cobertura Wi-Fi - 2 Access Points", 1, "15728.61", "19/08/2026", "SP", "Atibaia"),
        ])
        self.client.force_login(self.admin)
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"))
        self.kit_2ap.valor_servico = "350.00"
        self.kit_2ap.save(update_fields=["valor_servico"])
        self._ativar_planilha([
            ("53004230", "19001", "Kit Cobertura Wi-Fi - 2 Access Points", 1, "15728.61", "20/08/2026", "SP", "Atibaia"),
        ])
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"))
        item = EscolaItemRelatorioEaceMip.objects.get(escola=self.escola)
        self.assertEqual(str(item.valor_servico), "350.00")
        self.assertEqual(item.data_emissao_acs, datetime.date(2026, 8, 20))
        self.assertEqual(EscolaItemRelatorioEaceMip.objects.filter(escola=self.escola).count(), 1)

    def test_item_removido_quando_planilha_nao_traz_mais_a_descricao(self):
        self._ativar_planilha([
            ("53004230", "19001", "Rack de parede", 3, "10.00", "19/08/2026", "SP", "Atibaia"),
        ])
        self.client.force_login(self.admin)
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"))
        self.assertEqual(EscolaItemRelatorioEaceMip.objects.filter(escola=self.escola).count(), 1)
        # INEP continua tendo linha na planilha nova, só que sem mais essa
        # Descrição — mesma regra do RI: um INEP sem NENHUMA linha na
        # planilha ativa nem é processado (RI_SEM_LINHA_NA_PLANILHA), fica
        # com os itens antigos intactos; a remoção só roda quando o INEP
        # segue aparecendo, mas a Descrição em si some.
        self._ativar_planilha([
            ("53004230", "19001", "Produto que não existe no catálogo", 1, "1.00", "19/08/2026", "SP", "Atibaia"),
        ])
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"))
        self.assertEqual(EscolaItemRelatorioEaceMip.objects.filter(escola=self.escola).count(), 0)

    def test_inep_sem_nenhuma_linha_na_planilha_preserva_itens_antigos(self):
        """Mesma regra do RI (`RI_SEM_LINHA_NA_PLANILHA`): um INEP que não
        aparece mais na planilha ativa (0 linhas) não é processado — os
        itens já lançados ficam intactos, em vez de serem apagados."""
        self._ativar_planilha([
            ("53004230", "19001", "Rack de parede", 3, "10.00", "19/08/2026", "SP", "Atibaia"),
        ])
        self.client.force_login(self.admin)
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"))
        self._ativar_planilha([])
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"))
        self.assertEqual(EscolaItemRelatorioEaceMip.objects.filter(escola=self.escola).count(), 1)

    def test_kit_ja_lancado_nao_e_substituido_por_outro_kit(self):
        """RN-015 (mesma regra do RI): 1 KIT por INEP — um KIT diferente
        não substitui o já lançado."""
        KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 11 Access Points", lote=9,
            valor_equipamento="2000.00", valor_servico="500.00",
        )
        self._ativar_planilha([
            ("53004230", "19001", "Kit Cobertura Wi-Fi - 2 Access Points", 1, "15728.61", "19/08/2026", "SP", "Atibaia"),
        ])
        self.client.force_login(self.admin)
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"))
        self._ativar_planilha([
            ("53004230", "19001", "Kit Cobertura Wi-Fi - 11 Access Points", 1, "28281.06", "19/08/2026", "SP", "Atibaia"),
        ])
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"))
        itens = EscolaItemRelatorioEaceMip.objects.filter(escola=self.escola)
        self.assertEqual(itens.count(), 1)
        self.assertEqual(itens.first().descricao_item, "Kit Cobertura Wi-Fi - 2 Access Points")

    def test_sem_correspondencia_no_catalogo_e_ignorado(self):
        self._ativar_planilha([
            ("53004230", "19001", "Produto Inexistente no Catalogo", 1, "10.00", "19/08/2026", "SP", "Atibaia"),
        ])
        self.client.force_login(self.admin)
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"))
        self.assertEqual(EscolaItemRelatorioEaceMip.objects.count(), 0)

    def test_quantidade_invalida_e_ignorada(self):
        self._ativar_planilha([
            ("53004230", "19001", "Rack de parede", 0, "10.00", "19/08/2026", "SP", "Atibaia"),
        ])
        self.client.force_login(self.admin)
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"))
        self.assertEqual(EscolaItemRelatorioEaceMip.objects.count(), 0)

    def test_inep_sem_linha_na_planilha_nao_e_afetado(self):
        outra_escola = Escola.objects.create(inep="99999999", nome="Escola Sem Linha", lote=9)
        EscolaItemRelatorioEaceMip.objects.create(
            escola=outra_escola, descricao_item="Item manual antigo", quantidade=1,
            valor_servico="1.00",
        )
        self._ativar_planilha([
            ("53004230", "19001", "Rack de parede", 3, "10.00", "19/08/2026", "SP", "Atibaia"),
        ])
        self.client.force_login(self.admin)
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"))
        self.assertEqual(EscolaItemRelatorioEaceMip.objects.filter(escola=outra_escola).count(), 1)

    def test_sincronizacao_marca_escola_encontrada_na_planilha(self):
        """RN-081 (a criar): vira a bolinha verde/vermelha do grid do
        MIP — `True` quando o INEP apareceu na planilha desta rodada."""
        self._ativar_planilha([
            ("53004230", "19001", "Rack de parede", 3, "10.00", "19/08/2026", "SP", "Atibaia"),
        ])
        self.client.force_login(self.admin)
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"))
        self.escola.refresh_from_db()
        self.assertTrue(self.escola.encontrado_relatorio_eace_mip)

    def test_sincronizacao_marca_escola_sem_linha_como_nao_encontrada(self):
        outra_escola = Escola.objects.create(inep="88888888", nome="Escola Sem Linha Encontrado", lote=9)
        self._ativar_planilha([
            ("53004230", "19001", "Rack de parede", 3, "10.00", "19/08/2026", "SP", "Atibaia"),
        ])
        self.client.force_login(self.admin)
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"))
        outra_escola.refresh_from_db()
        self.assertFalse(outra_escola.encontrado_relatorio_eace_mip)

    def test_sincronizacao_seguinte_atualiza_encontrado_de_true_para_false(self):
        """A bolinha reflete sempre a ÚLTIMA sincronização, não uma
        anterior."""
        self._ativar_planilha([
            ("53004230", "19001", "Rack de parede", 3, "10.00", "19/08/2026", "SP", "Atibaia"),
        ])
        self.client.force_login(self.admin)
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"))
        self.escola.refresh_from_db()
        self.assertTrue(self.escola.encontrado_relatorio_eace_mip)
        self._ativar_planilha([])
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"))
        self.escola.refresh_from_db()
        self.assertFalse(self.escola.encontrado_relatorio_eace_mip)

    def test_sincronizacao_grava_cod_fornecedor_da_escola(self):
        """Coluna "Cod Fornecedor" da planilha — gravada junto com o INEP
        para o arquivo Excel pedido pelo usuário."""
        self._ativar_planilha([
            ("53004230", "19001", "Rack de parede", 3, "10.00", "19/08/2026", "SP", "Atibaia"),
        ])
        self.client.force_login(self.admin)
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"))
        self.escola.refresh_from_db()
        self.assertEqual(self.escola.cod_fornecedor, "19001")

    def test_cod_fornecedor_e_preservado_quando_inep_some_da_planilha(self):
        """Mesma filosofia do `encontrado_relatorio_eace_mip`/itens: o
        código já gravado não é apagado só porque o INEP não apareceu
        nesta rodada."""
        self._ativar_planilha([
            ("53004230", "19001", "Rack de parede", 3, "10.00", "19/08/2026", "SP", "Atibaia"),
        ])
        self.client.force_login(self.admin)
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"))
        self._ativar_planilha([])
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"))
        self.escola.refresh_from_db()
        self.assertEqual(self.escola.cod_fornecedor, "19001")

    def test_sobrepor_0_pula_escola_que_ja_tem_item_no_lado3(self):
        """Pedido do usuário (2026-09-16): "Não, só os vazios" — Escola
        cujo Lado 3 já tem item lançado é pulada inteira, itens mantidos
        exatamente como estavam."""
        self._ativar_planilha([
            ("53004230", "19001", "Rack de parede", 3, "10.00", "19/08/2026", "SP", "Atibaia"),
        ])
        self.client.force_login(self.admin)
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"))
        item_original = EscolaItemRelatorioEaceMip.objects.get(escola=self.escola)

        self._ativar_planilha([
            ("53004230", "19001", "Rack de parede", 99, "10.00", "20/08/2026", "RJ", "Niterói"),
        ])
        resp = self.client.post(
            reverse("relatorio_eace_mip_sincronizar_todas"), {"sobrepor": "0"}, follow=True,
        )
        self.assertContains(resp, "0 INEP(s) atualizado(s)")
        self.assertContains(resp, "1 INEP(s) que já tinham dado no Lado 3 foram mantidos sem alteração")
        item_original.refresh_from_db()
        self.assertEqual(item_original.quantidade, 3)
        self.assertEqual(item_original.uf, "SP")

    def test_sobrepor_0_ainda_cadastra_escola_com_lado3_vazio(self):
        """"Não, só os vazios" não bloqueia quem ainda não tem nada no
        Lado 3 — só protege quem já tem."""
        escola_vazia = Escola.objects.create(inep="53004231", nome="Escola Vazia", lote=9)
        self._ativar_planilha([
            ("53004230", "19001", "Rack de parede", 3, "10.00", "19/08/2026", "SP", "Atibaia"),
        ])
        self.client.force_login(self.admin)
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"))

        self._ativar_planilha([
            ("53004230", "19001", "Rack de parede", 99, "10.00", "20/08/2026", "RJ", "Niterói"),
            ("53004231", "19002", "Rack de parede", 5, "10.00", "20/08/2026", "RJ", "Niterói"),
        ])
        resp = self.client.post(
            reverse("relatorio_eace_mip_sincronizar_todas"), {"sobrepor": "0"}, follow=True,
        )
        self.assertContains(resp, "1 INEP(s) atualizado(s)")
        self.assertContains(resp, "1 INEP(s) que já tinham dado no Lado 3 foram mantidos sem alteração")
        item_novo = EscolaItemRelatorioEaceMip.objects.get(escola=escola_vazia)
        self.assertEqual(item_novo.quantidade, 5)

    def test_sobrepor_1_continua_atualizando_normalmente(self):
        """"Sim, sobrepor" (ou o botão único de sempre, sem conflito) —
        mesmo comportamento de antes desta mudança."""
        self._ativar_planilha([
            ("53004230", "19001", "Rack de parede", 3, "10.00", "19/08/2026", "SP", "Atibaia"),
        ])
        self.client.force_login(self.admin)
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"))

        self._ativar_planilha([
            ("53004230", "19001", "Rack de parede", 99, "10.00", "20/08/2026", "RJ", "Niterói"),
        ])
        resp = self.client.post(
            reverse("relatorio_eace_mip_sincronizar_todas"), {"sobrepor": "1"}, follow=True,
        )
        self.assertContains(resp, "1 INEP(s) atualizado(s)")
        self.assertNotContains(resp, "mantidos sem alteração")
        item = EscolaItemRelatorioEaceMip.objects.get(escola=self.escola)
        self.assertEqual(item.quantidade, 99)
        self.assertEqual(item.uf, "RJ")


class RelatorioEaceMipSincronizarHistoricoTests(TestCase):
    """Pedido do usuário (2026-09-16): item alterado pelo Sincronizador
    do Lado 3 do MIP grava, no histórico do RI (`RiHistorico`, mesmo
    painel compartilhado do RI e do MIP, RN-068), o antes/depois do item
    e o usuário que rodou a sincronização."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT_TESTE_RELATORIO_EACE_MIP_SYNC, ignore_errors=True)

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin-historico-lado3", password="senha-teste-123",
            perfil=User.PERFIL_ADMINISTRADOR,
        )
        self.escola = Escola.objects.create(inep="53004230", nome="Escola Teste Histórico", lote=9)
        self.ri = Ri.objects.create(escola=self.escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        self.kit_2ap = KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 2 Access Points", lote=9,
            valor_equipamento="1000.00", valor_servico="300.00",
        )
        self.produto_avulso = KitPadrao.objects.create(
            descricao="Rack de parede", lote=9,
            valor_equipamento="50.00", valor_servico="10.00",
        )

    def _ativar_planilha(self, linhas):
        PlanilhaRelatorioEaceMip.substituir(_xlsx_relatorio_eace_mip_com_linhas(linhas), self.admin)

    def test_item_novo_grava_historico_com_autor_e_sem_item_antes(self):
        self._ativar_planilha([
            ("53004230", "19001", "Rack de parede", 3, "10.00", "19/08/2026", "SP", "Atibaia"),
        ])
        self.client.force_login(self.admin)
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"))

        entrada = self.ri.historico.get(tipo=RiHistorico.LOG_CAMPO, campo="Relatório EACE (MIP) — Rack de parede")
        self.assertEqual(entrada.autor, self.admin)
        self.assertEqual(entrada.valor_anterior, "(sem item antes)")
        self.assertIn("3 un.", entrada.valor_novo)
        self.assertIn("R$ 10.00", entrada.valor_novo)
        self.assertIn("SP/Atibaia", entrada.valor_novo)

    def test_item_atualizado_grava_antes_e_depois(self):
        self._ativar_planilha([
            ("53004230", "19001", "Rack de parede", 3, "10.00", "19/08/2026", "SP", "Atibaia"),
        ])
        self.client.force_login(self.admin)
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"))

        self._ativar_planilha([
            ("53004230", "19001", "Rack de parede", 99, "10.00", "20/08/2026", "RJ", "Niterói"),
        ])
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"), {"sobrepor": "1"})

        entradas = list(
            self.ri.historico.filter(
                tipo=RiHistorico.LOG_CAMPO, campo="Relatório EACE (MIP) — Rack de parede",
            ).order_by("criado_em")
        )
        self.assertEqual(len(entradas), 2)
        entrada_atualizacao = entradas[1]
        self.assertEqual(entrada_atualizacao.autor, self.admin)
        self.assertIn("3 un.", entrada_atualizacao.valor_anterior)
        self.assertIn("SP/Atibaia", entrada_atualizacao.valor_anterior)
        self.assertIn("99 un.", entrada_atualizacao.valor_novo)
        self.assertIn("RJ/Niterói", entrada_atualizacao.valor_novo)

    def test_item_removido_grava_antes_e_removido(self):
        self._ativar_planilha([
            ("53004230", "19001", "Rack de parede", 3, "10.00", "19/08/2026", "SP", "Atibaia"),
        ])
        self.client.force_login(self.admin)
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"))

        # O INEP precisa continuar aparecendo na planilha (só sem mais
        # essa Descrição) — um INEP totalmente ausente da planilha não é
        # processado (`RI_SEM_LINHA_NA_PLANILHA`, itens antigos ficam
        # intactos, ver `test_inep_sem_nenhuma_linha_na_planilha_
        # preserva_itens_antigos`).
        self._ativar_planilha([
            ("53004230", "19001", "Produto que não existe no catálogo", 1, "1.00", "19/08/2026", "SP", "Atibaia"),
        ])
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"), {"sobrepor": "1"})

        entradas = list(
            self.ri.historico.filter(
                tipo=RiHistorico.LOG_CAMPO, campo="Relatório EACE (MIP) — Rack de parede",
            ).order_by("criado_em")
        )
        self.assertEqual(len(entradas), 2)
        entrada_remocao = entradas[1]
        self.assertEqual(entrada_remocao.autor, self.admin)
        self.assertIn("3 un.", entrada_remocao.valor_anterior)
        self.assertEqual(entrada_remocao.valor_novo, "(removido)")

    def test_escola_sem_ri_nao_gera_historico_mas_item_e_criado(self):
        escola_sem_ri = Escola.objects.create(inep="53004299", nome="Escola Sem RI", lote=9)
        self._ativar_planilha([
            ("53004299", "19002", "Rack de parede", 3, "10.00", "19/08/2026", "SP", "Atibaia"),
        ])
        self.client.force_login(self.admin)
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"))

        self.assertTrue(EscolaItemRelatorioEaceMip.objects.filter(escola=escola_sem_ri).exists())
        self.assertEqual(RiHistorico.objects.filter(campo__startswith="Relatório EACE (MIP)").count(), 0)

    def test_item_pulado_por_sobrepor_0_nao_gera_historico(self):
        self._ativar_planilha([
            ("53004230", "19001", "Rack de parede", 3, "10.00", "19/08/2026", "SP", "Atibaia"),
        ])
        self.client.force_login(self.admin)
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"))
        total_antes = self.ri.historico.filter(campo__startswith="Relatório EACE (MIP)").count()

        self._ativar_planilha([
            ("53004230", "19001", "Rack de parede", 99, "10.00", "20/08/2026", "RJ", "Niterói"),
        ])
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"), {"sobrepor": "0"})

        self.assertEqual(
            self.ri.historico.filter(campo__startswith="Relatório EACE (MIP)").count(), total_antes,
        )


class RelatorioEaceMipViewConflitoLado3Tests(TestCase):
    """Tela "Administrador > Relatório EACE (MIP)" — pedido do usuário
    (2026-09-16): quando o arquivo ativo tem INEP com o Lado 3 já
    preenchido, o botão "Sincronizar todos os INEPs" vira uma pergunta
    (2 botões) em vez de agir direto."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT_TESTE_RELATORIO_EACE_MIP_SYNC, ignore_errors=True)

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin-conflito-lado3", password="senha-teste-123",
            perfil=User.PERFIL_ADMINISTRADOR,
        )
        self.escola = Escola.objects.create(inep="53004230", nome="Escola Teste Conflito", lote=9)
        self.kit_2ap = KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 2 Access Points", lote=9,
            valor_equipamento="1000.00", valor_servico="300.00",
        )

    def _ativar_planilha(self, linhas):
        PlanilhaRelatorioEaceMip.substituir(_xlsx_relatorio_eace_mip_com_linhas(linhas), self.admin)

    def test_sem_conflito_mostra_botao_unico(self):
        self._ativar_planilha([
            ("53004230", "19001", "Kit Cobertura Wi-Fi - 2 Access Points", 1, "15728.61", "19/08/2026", "SP", "Atibaia"),
        ])
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("relatorio_eace_mip"))
        self.assertEqual(resp.context["total_escolas_com_lado3_preenchido"], 0)
        self.assertContains(resp, "Sincronizar todos os INEPs")
        self.assertNotContains(resp, "Sim, sobrepor")

    def test_com_conflito_mostra_2_botoes_e_o_total(self):
        """Conflito de verdade: um NOVO arquivo importado depois de uma
        sincronização anterior já ter preenchido o Lado 3 do mesmo INEP
        — a pergunta é sobre este arquivo (recém chegado), não sobre a
        sincronização de antes."""
        self._ativar_planilha([
            ("53004230", "19001", "Kit Cobertura Wi-Fi - 2 Access Points", 1, "15728.61", "19/08/2026", "SP", "Atibaia"),
        ])
        self.client.force_login(self.admin)
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"))

        self._ativar_planilha([
            ("53004230", "19001", "Kit Cobertura Wi-Fi - 2 Access Points", 2, "15728.61", "20/08/2026", "SP", "Atibaia"),
        ])
        resp = self.client.get(reverse("relatorio_eace_mip"))
        self.assertEqual(resp.context["total_escolas_com_lado3_preenchido"], 1)
        self.assertContains(resp, "1 INEP(s) deste arquivo já tem dado lançado no Lado 3")
        self.assertContains(resp, "Sim, sobrepor")
        self.assertContains(resp, "Não, só os vazios")

    def test_apos_escolher_pergunta_some_no_mesmo_arquivo(self):
        """Pedido do usuário (2026-09-17): depois de clicar em "Sim,
        sobrepor" ou "Não, só os vazios", a pergunta não pode voltar a
        aparecer pro MESMO arquivo — a própria sincronização preenche o
        Lado 3, então sem essa trava a tela ficaria perguntando de novo
        pra sempre. Só some de vez quando um arquivo novo é importado
        (`test_novo_upload_faz_pergunta_voltar_a_aparecer`)."""
        self._ativar_planilha([
            ("53004230", "19001", "Kit Cobertura Wi-Fi - 2 Access Points", 1, "15728.61", "19/08/2026", "SP", "Atibaia"),
        ])
        self.client.force_login(self.admin)
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"), {"sobrepor": "1"})

        resp = self.client.get(reverse("relatorio_eace_mip"))
        self.assertEqual(resp.context["total_escolas_com_lado3_preenchido"], 0)
        self.assertContains(resp, "Sincronizar todos os INEPs")
        self.assertNotContains(resp, "Sim, sobrepor")
        self.assertNotContains(resp, "Não, só os vazios")

    def test_novo_upload_faz_pergunta_voltar_a_aparecer(self):
        """Um novo arquivo importado em "Substituir arquivo" reseta a
        confirmação — mesmo repetindo um INEP já sincronizado antes, a
        pergunta é por arquivo, não por INEP."""
        self._ativar_planilha([
            ("53004230", "19001", "Kit Cobertura Wi-Fi - 2 Access Points", 1, "15728.61", "19/08/2026", "SP", "Atibaia"),
        ])
        self.client.force_login(self.admin)
        self.client.post(reverse("relatorio_eace_mip_sincronizar_todas"), {"sobrepor": "1"})

        self._ativar_planilha([
            ("53004230", "19001", "Kit Cobertura Wi-Fi - 2 Access Points", 2, "15728.61", "20/08/2026", "SP", "Atibaia"),
        ])
        resp = self.client.get(reverse("relatorio_eace_mip"))
        self.assertEqual(resp.context["total_escolas_com_lado3_preenchido"], 1)
        self.assertContains(resp, "Sim, sobrepor")

    def test_sem_planilha_ativa_total_e_zero(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("relatorio_eace_mip"))
        self.assertEqual(resp.context["total_escolas_com_lado3_preenchido"], 0)

    def test_arquivo_ativo_sumiu_do_storage_nao_quebra_a_tela(self):
        """Bug real reportado pelo usuário (2026-09-18): o registro da
        Planilha ativa continua no banco, mas o `.xlsx` sumiu do storage
        (`FileNotFoundError` travava a tela inteira) — tratado como "sem
        planilha para consultar", mesmo critério de `sincronizacao_
        confirmada`/planilha ausente já usado acima."""
        self._ativar_planilha([
            ("53004230", "19001", "Kit Cobertura Wi-Fi - 2 Access Points", 1, "15728.61", "19/08/2026", "SP", "Atibaia"),
        ])
        planilha = PlanilhaRelatorioEaceMip.ativa()
        Path(planilha.arquivo.path).unlink()

        self.client.force_login(self.admin)
        resp = self.client.get(reverse("relatorio_eace_mip"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["total_escolas_com_lado3_preenchido"], 0)


class GerarPlanilhaFaturamentoImplantacaoTests(TestCase):
    """Planilha de faturamento de implantação (`doc/FATURAMENTO
    IMPLANTAÇÃO.xlsx`), gerada a partir do filtro Estado+Município do grid
    Projeto > MIP (`gerar_planilha_faturamento_implantacao`, `apps.escolas.
    services`) — reaproveita a mesma base (RN-074) e o mesmo filtro
    (RN-079) do grid, e o mesmo Valor Total (IXC) da RN-076. RN própria
    desta feature ainda a formalizar pelo Orquestrador."""

    def setUp(self):
        KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 2 Access Points", lote=9,
            valor_equipamento="1000.00", valor_servico="300.00",
        )
        self.escola_a = Escola.objects.create(
            inep="52171205", nome="Escola A Abadiânia", estado="GO", municipio="Abadiânia",
            lote=9, cod_fornecedor="42598",
        )
        self.escola_b = Escola.objects.create(
            inep="52171206", nome="Escola B Abadiânia", estado="GO", municipio="Abadiânia",
            lote=9, cod_fornecedor="42599",
        )
        self.ri_a = Ri.objects.create(escola=self.escola_a, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        self.ri_b = Ri.objects.create(escola=self.escola_b, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        RiItemIxc.objects.create(
            ri=self.ri_a, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
            quantidade=1, valor_unitario="0.00", eh_kit=True,
        )
        RiItemIxc.objects.create(
            ri=self.ri_b, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
            quantidade=2, valor_unitario="0.00", eh_kit=True,
        )
        self.data_envio = datetime.date(2026, 9, 8)

    def test_soma_valor_total_ixc_de_todas_as_escolas_do_filtro(self):
        """RN-076: 1 x 300,00 (Escola A) + 2 x 300,00 (Escola B) = 900,00."""
        workbook = gerar_planilha_faturamento_implantacao("GO", "Abadiânia", self.data_envio)
        aba = workbook.worksheets[0]
        self.assertEqual(aba["H10"].value, 900.00)

    def test_codigo_ineps_lista_inep_cod_fornecedor_na_ordem_do_grid(self):
        """Mesma ordem do grid (`order_by("nome")`): Escola A antes de
        Escola B."""
        workbook = gerar_planilha_faturamento_implantacao("GO", "Abadiânia", self.data_envio)
        aba = workbook.worksheets[0]
        self.assertIn("CÓDIGO INEPS: 52171205/42598;52171206/42599", aba["F10"].value)

    def test_municipio_uf_e_vencimento_no_texto_da_observacao(self):
        """Pedido do usuário (2026-09-16): nome do Município em maiúsculo
        no texto de observação (F10) — "ABADIÂNIA", não "Abadiânia"."""
        workbook = gerar_planilha_faturamento_implantacao("GO", "Abadiânia", self.data_envio)
        aba = workbook.worksheets[0]
        self.assertIn("MUNICIPIO/UF: ABADIÂNIA/GO", aba["F10"].value)
        self.assertIn("VENCIMENTO: 08/10/2026", aba["F10"].value)  # 08/09/2026 + 30 dias

    def test_vencimento_e10_e_data_envio_mais_30_dias(self):
        workbook = gerar_planilha_faturamento_implantacao("GO", "Abadiânia", self.data_envio)
        aba = workbook.worksheets[0]
        self.assertEqual(aba["E10"].value, datetime.date(2026, 10, 8))

    def test_erro_claro_sem_municipio(self):
        with self.assertRaisesMessage(
            PlanilhaFaturamentoImplantacaoError, "Informe Estado e Município",
        ):
            gerar_planilha_faturamento_implantacao("GO", "", self.data_envio)

    def test_erro_claro_sem_ineps_no_filtro(self):
        with self.assertRaisesMessage(
            PlanilhaFaturamentoImplantacaoError, "Nenhum INEP encontrado para Campinas/SP.",
        ):
            gerar_planilha_faturamento_implantacao("SP", "Campinas", self.data_envio)

    def test_escola_sem_ri_em_validacao_eace_nao_entra_na_soma(self):
        """RN-074: mesmo critério do grid — só entra quem está com o RI
        atual em "Aguardando validação EACE"."""
        escola_fora = Escola.objects.create(
            inep="52171207", nome="Escola Fora Validacao", estado="GO", municipio="Abadiânia", lote=9,
        )
        ri_fora = Ri.objects.create(escola=escola_fora, status=Ri.ANDAMENTO)
        RiItemIxc.objects.create(
            ri=ri_fora, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
            quantidade=5, valor_unitario="0.00", eh_kit=True,
        )
        workbook = gerar_planilha_faturamento_implantacao("GO", "Abadiânia", self.data_envio)
        aba = workbook.worksheets[0]
        self.assertEqual(aba["H10"].value, 900.00)  # sem mudança — escola fora não entra na soma
        self.assertNotIn(escola_fora.inep, aba["F10"].value)

    def test_aba_e_renomeada_para_o_municipio(self):
        workbook = gerar_planilha_faturamento_implantacao("GO", "Abadiânia", self.data_envio)
        self.assertEqual(workbook.worksheets[0].title, "Abadiânia")


class GerarPlanilhaFaturamentoImplantacaoCommandTests(TestCase):
    """Command `gerar_planilha_faturamento_implantacao` — forma provisória
    de gerar/testar o arquivo enquanto não há tela própria para o usuário
    (view/URL/botão ainda não definidos)."""

    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp_dir.name)
        self.addCleanup(self._tmp_dir.cleanup)
        KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 2 Access Points", lote=9,
            valor_equipamento="1000.00", valor_servico="300.00",
        )
        self.escola = Escola.objects.create(
            inep="52171205", nome="Escola Comando", estado="GO", municipio="Abadiânia",
            lote=9, cod_fornecedor="42598",
        )
        self.ri = Ri.objects.create(escola=self.escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        RiItemIxc.objects.create(
            ri=self.ri, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
            quantidade=1, valor_unitario="0.00", eh_kit=True,
        )

    def test_comando_gera_arquivo_na_saida_informada(self):
        caminho_saida = self.tmp_path / "faturamento_teste.xlsx"
        call_command(
            "gerar_planilha_faturamento_implantacao",
            "--estado", "GO", "--municipio", "Abadiânia",
            "--data-envio", "08/09/2026", "--saida", str(caminho_saida),
        )
        self.assertTrue(caminho_saida.exists())
        workbook = openpyxl.load_workbook(caminho_saida)
        self.assertEqual(workbook.worksheets[0]["H10"].value, 300.00)

    def test_comando_reporta_erro_de_negocio_como_command_error(self):
        caminho_saida = self.tmp_path / "nao_deve_existir.xlsx"
        with self.assertRaises(CommandError):
            call_command(
                "gerar_planilha_faturamento_implantacao",
                "--estado", "SP", "--municipio", "Município Sem Inep",
                "--data-envio", "08/09/2026", "--saida", str(caminho_saida),
            )

    def test_comando_reporta_data_envio_invalida_como_command_error(self):
        caminho_saida = self.tmp_path / "nao_deve_existir.xlsx"
        with self.assertRaises(CommandError):
            call_command(
                "gerar_planilha_faturamento_implantacao",
                "--estado", "GO", "--municipio", "Abadiânia",
                "--data-envio", "31/13/2026", "--saida", str(caminho_saida),
            )


# ---------------------------------------------------------------------------
# FEAT-044/RN-098 (a formalizar pelo Orquestrador em business_rules.md;
# pedido do usuário, 2026-09-14): "Projeto > MIP (LOTE)".
# ---------------------------------------------------------------------------


def _criar_escola_elegivel_lote(inep, *, estado="GO", municipio="Abadiânia", data_ativacao=None):
    """Fixture comum: 1 INEP "Aguardando Validação EACE", com Valor Total
    (IXC) == Valor Total (EACE) (os dois = R$ 300,00) — mesmo Lote/catálogo
    (`Escola.lote`, RN-010) dos demais testes do MIP desta suíte. Não
    confundir `Escola.lote=9` (número do catálogo) com o `Lote` (LOTE) da
    FEAT-044 — nomes iguais por coincidência, conceitos diferentes."""
    escola = Escola.objects.create(
        inep=inep, nome=f"Escola {inep}", estado=estado, municipio=municipio, lote=9,
        status_mip=Escola.AGUARDANDO_VALIDACAO_EACE,
    )
    ri = Ri.objects.create(
        escola=escola, status=Ri.AGUARDANDO_VALIDACAO_EACE,
        data_ativacao=data_ativacao or datetime.date(2026, 9, 5),
    )
    RiItemIxc.objects.create(
        ri=ri, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
        quantidade=1, valor_unitario="0.00", eh_kit=True,
    )
    EscolaItemRelatorioEaceMip.objects.create(
        escola=escola, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
        quantidade=1, valor_servico="300.00", eh_kit=True,
    )
    return escola, ri


class LoteMipElegibilidadeTests(TestCase):
    """RN-098 (a criar): base elegível para um LOTE — Estado/Município/Data
    de Ativação do filtro (RN-079/RN-075), restrita a "Aguardando
    Validação EACE" com Valor Total (IXC) == Valor Total (EACE), os dois
    conhecidos e completos."""

    def setUp(self):
        KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 2 Access Points", lote=9,
            valor_equipamento="1000.00", valor_servico="300.00",
        )

    def test_escola_elegivel_entra_na_lista(self):
        escola, _ri = _criar_escola_elegivel_lote("10000001")
        elegiveis = escolas_elegiveis_lote_mip("GO", "Abadiânia", datetime.date(2026, 9, 1), datetime.date(2026, 9, 30))
        self.assertEqual(elegiveis, [escola])

    def test_valores_diferentes_nao_entra(self):
        escola, ri = _criar_escola_elegivel_lote("10000002")
        item = EscolaItemRelatorioEaceMip.objects.get(escola=escola)
        item.valor_servico = "250.00"
        item.save()
        elegiveis = escolas_elegiveis_lote_mip("GO", "Abadiânia", datetime.date(2026, 9, 1), datetime.date(2026, 9, 30))
        self.assertNotIn(escola, elegiveis)

    def test_status_diferente_de_aguardando_validacao_eace_nao_entra(self):
        escola, _ri = _criar_escola_elegivel_lote("10000003")
        escola.status_mip = Escola.EM_ANDAMENTO
        escola.save()
        elegiveis = escolas_elegiveis_lote_mip("GO", "Abadiânia", datetime.date(2026, 9, 1), datetime.date(2026, 9, 30))
        self.assertNotIn(escola, elegiveis)

    def test_fora_do_periodo_nao_entra(self):
        _criar_escola_elegivel_lote("10000004", data_ativacao=datetime.date(2026, 8, 1))
        elegiveis = escolas_elegiveis_lote_mip("GO", "Abadiânia", datetime.date(2026, 9, 1), datetime.date(2026, 9, 30))
        self.assertEqual(elegiveis, [])

    def test_outro_municipio_nao_entra(self):
        _criar_escola_elegivel_lote("10000005", municipio="Anápolis")
        elegiveis = escolas_elegiveis_lote_mip("GO", "Abadiânia", datetime.date(2026, 9, 1), datetime.date(2026, 9, 30))
        self.assertEqual(elegiveis, [])

    def test_total_incompleto_nao_entra_mesmo_com_soma_igual(self):
        """Item sem correspondência no catálogo deixa o total "incompleto"
        (RN-076) — mesmo que a soma dos itens conhecidos bata com o outro
        lado, o LOTE não considera elegível (decisão conservadora do Dev,
        CLAUDE.md §9)."""
        escola, ri = _criar_escola_elegivel_lote("10000006")
        RiItemIxc.objects.create(
            ri=ri, descricao_item="Produto fora do catálogo", quantidade=1,
            valor_unitario="0.00", eh_kit=False,
        )
        elegiveis = escolas_elegiveis_lote_mip("GO", "Abadiânia", datetime.date(2026, 9, 1), datetime.date(2026, 9, 30))
        self.assertNotIn(escola, elegiveis)

    def test_sem_estado_ou_municipio_devolve_vazio(self):
        _criar_escola_elegivel_lote("10000007")
        self.assertEqual(escolas_elegiveis_lote_mip("", "Abadiânia", datetime.date(2026, 9, 1), datetime.date(2026, 9, 30)), [])
        self.assertEqual(escolas_elegiveis_lote_mip("GO", "", datetime.date(2026, 9, 1), datetime.date(2026, 9, 30)), [])

    def test_sem_nenhuma_data_entra_mesmo_assim(self):
        """RN-098 (correção, 2026-09-14 — bug real reportado pelo usuário,
        INEP 52171205): Data início/Data fim são opcionais — só Estado e
        Município são obrigatórios."""
        escola, _ri = _criar_escola_elegivel_lote("10000071")
        self.assertEqual(escolas_elegiveis_lote_mip("GO", "Abadiânia", None, None), [escola])

    def test_so_data_inicio_restringe_so_essa_ponta(self):
        escola_dentro, _ri1 = _criar_escola_elegivel_lote("10000072", data_ativacao=datetime.date(2026, 9, 15))
        escola_fora, _ri2 = _criar_escola_elegivel_lote("10000073", data_ativacao=datetime.date(2026, 8, 1))
        elegiveis = escolas_elegiveis_lote_mip("GO", "Abadiânia", datetime.date(2026, 9, 1), None)
        self.assertIn(escola_dentro, elegiveis)
        self.assertNotIn(escola_fora, elegiveis)


class CriarLoteMipTests(TestCase):
    """RN-098 (a criar): `criar_lote_mip` — cria o `Lote`, muda o Status
    (MIP) de cada INEP elegível para "Aguardando Encerramento LOTE" e
    grava o histórico (status + número do LOTE), pedido explícito do
    usuário."""

    def setUp(self):
        self.usuario = User.objects.create_user(username="analista-lote", password="senha-teste-123")
        KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 2 Access Points", lote=9,
            valor_equipamento="1000.00", valor_servico="300.00",
        )

    def test_sem_estado_ou_municipio_levanta_erro_e_nao_cria_lote(self):
        with self.assertRaises(LoteMipError):
            criar_lote_mip("", "Abadiânia", datetime.date(2026, 9, 1), datetime.date(2026, 9, 30), self.usuario)
        with self.assertRaises(LoteMipError):
            criar_lote_mip("GO", "", datetime.date(2026, 9, 1), datetime.date(2026, 9, 30), self.usuario)
        self.assertEqual(Lote.objects.count(), 0)

    def test_data_inicial_depois_da_final_levanta_erro(self):
        with self.assertRaises(LoteMipError):
            criar_lote_mip("GO", "Abadiânia", datetime.date(2026, 9, 30), datetime.date(2026, 9, 1), self.usuario)
        self.assertEqual(Lote.objects.count(), 0)

    def test_cria_lote_sem_nenhuma_data(self):
        """RN-098 (correção, 2026-09-14 — bug real reportado pelo usuário,
        INEP 52171205): Estado e Município bastam — Data inicial/final
        ficam `None` no `Lote` quando não informadas."""
        escola, _ri = _criar_escola_elegivel_lote("10000074")
        lote = criar_lote_mip("GO", "Abadiânia", None, None, self.usuario)
        self.assertIsNone(lote.data_inicio)
        self.assertIsNone(lote.data_fim)
        self.assertEqual(set(lote.escolas.all()), {escola})

    def test_sem_elegivel_levanta_erro_e_nao_cria_lote(self):
        with self.assertRaises(LoteMipError):
            criar_lote_mip("GO", "Abadiânia", datetime.date(2026, 9, 1), datetime.date(2026, 9, 30), self.usuario)
        self.assertEqual(Lote.objects.count(), 0)

    def test_cria_lote_com_os_ineps_elegiveis(self):
        escola1, _ri1 = _criar_escola_elegivel_lote("10000010")
        escola2, _ri2 = _criar_escola_elegivel_lote("10000011")
        _criar_escola_elegivel_lote("10000012", municipio="Anápolis")  # fora do filtro

        lote = criar_lote_mip("GO", "Abadiânia", datetime.date(2026, 9, 1), datetime.date(2026, 9, 30), self.usuario)

        self.assertEqual(lote.estado, "GO")
        self.assertEqual(lote.municipio, "Abadiânia")
        self.assertEqual(lote.data_inicio, datetime.date(2026, 9, 1))
        self.assertEqual(lote.data_fim, datetime.date(2026, 9, 30))
        self.assertEqual(lote.criado_por, self.usuario)
        self.assertEqual(set(lote.escolas.all()), {escola1, escola2})

    def test_muda_status_mip_e_grava_historico_com_status_e_numero_do_lote(self):
        escola, ri = _criar_escola_elegivel_lote("10000013")
        lote = criar_lote_mip("GO", "Abadiânia", datetime.date(2026, 9, 1), datetime.date(2026, 9, 30), self.usuario)

        escola.refresh_from_db()
        self.assertEqual(escola.status_mip, Escola.AGUARDANDO_ENCERRAMENTO_LOTE)

        entrada_status = ri.historico.get(tipo=RiHistorico.LOG_CAMPO, campo="Status (MIP)")
        self.assertEqual(entrada_status.valor_anterior, "Aguardando Validação EACE")
        self.assertEqual(entrada_status.valor_novo, "Aguardando Encerramento LOTE")

        entrada_lote = ri.historico.get(tipo=RiHistorico.LOG_CAMPO, campo="LOTE")
        self.assertEqual(entrada_lote.valor_novo, str(lote))

    def test_escola_ids_restringe_ao_selecionado(self):
        """FEAT-050 (pedido do usuário, 2026-09-14): `escola_ids`
        restringe o LOTE aos INEPs marcados no modal de revisão."""
        escola1, _ri1 = _criar_escola_elegivel_lote("10000015")
        escola2, _ri2 = _criar_escola_elegivel_lote("10000016")
        lote = criar_lote_mip(
            "GO", "Abadiânia", datetime.date(2026, 9, 1), datetime.date(2026, 9, 30), self.usuario,
            escola_ids=[str(escola1.pk)],
        )
        self.assertEqual(set(lote.escolas.all()), {escola1})
        escola2.refresh_from_db()
        self.assertEqual(escola2.status_mip, Escola.AGUARDANDO_VALIDACAO_EACE)

    def test_escola_ids_vazio_levanta_erro(self):
        _criar_escola_elegivel_lote("10000017")
        with self.assertRaises(LoteMipError):
            criar_lote_mip(
                "GO", "Abadiânia", datetime.date(2026, 9, 1), datetime.date(2026, 9, 30), self.usuario,
                escola_ids=[],
            )
        self.assertEqual(Lote.objects.count(), 0)

    def test_nao_cria_lote_duplicado_ao_tentar_de_novo_sem_elegivel(self):
        """Depois que um INEP entra no LOTE, ele sai de "Aguardando
        Validação EACE" — uma 2ª tentativa com o mesmo filtro não acha
        mais nenhum elegível."""
        _criar_escola_elegivel_lote("10000014")
        criar_lote_mip("GO", "Abadiânia", datetime.date(2026, 9, 1), datetime.date(2026, 9, 30), self.usuario)
        with self.assertRaises(LoteMipError):
            criar_lote_mip("GO", "Abadiânia", datetime.date(2026, 9, 1), datetime.date(2026, 9, 30), self.usuario)
        self.assertEqual(Lote.objects.count(), 1)


class MipLoteCriarViewTests(TestCase):
    """View do botão "Criar LOTE" (`mip_lote_criar_view`) — lê o POST,
    delega para `criar_lote_mip` e converte erro em mensagem."""

    def setUp(self):
        self.usuario = User.objects.create_user(username="analista-lote-view", password="senha-teste-123")
        KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 2 Access Points", lote=9,
            valor_equipamento="1000.00", valor_servico="300.00",
        )

    def test_exige_login(self):
        resp = self.client.post(reverse("mip_lote_criar"), {"estado": "GO"})
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp.url)

    def test_get_nao_cria_nada(self):
        self.client.force_login(self.usuario)
        resp = self.client.get(reverse("mip_lote_criar"))
        self.assertRedirects(resp, reverse("mip_inep"))
        self.assertEqual(Lote.objects.count(), 0)

    def test_faltando_municipio_mostra_erro_e_nao_cria(self):
        self.client.force_login(self.usuario)
        resp = self.client.post(
            reverse("mip_lote_criar"),
            {"estado": "GO", "municipio": "", "data_inicial": "01/09/2026", "data_final": "30/09/2026"},
            follow=True,
        )
        self.assertEqual(Lote.objects.count(), 0)
        self.assertContains(resp, "Informe Estado e Município")

    def test_sem_data_cria_lote_normalmente(self):
        """RN-098 (correção, 2026-09-14 — bug real reportado pelo usuário,
        INEP 52171205)."""
        escola, _ri = _criar_escola_elegivel_lote("10000021")
        self.client.force_login(self.usuario)
        resp = self.client.post(
            reverse("mip_lote_criar"),
            {"estado": "GO", "municipio": "Abadiânia", "escola_ids": [str(escola.pk)]},
        )
        self.assertRedirects(resp, reverse("mip_lote_inep"))
        self.assertEqual(Lote.objects.count(), 1)

    def test_sem_nenhum_escola_id_marcado_mostra_erro_e_nao_cria(self):
        """FEAT-050 (pedido do usuário, 2026-09-14): modal de revisão com
        checkbox por INEP — desmarcar todos não pode criar um LOTE vazio."""
        _criar_escola_elegivel_lote("10000022")
        self.client.force_login(self.usuario)
        resp = self.client.post(
            reverse("mip_lote_criar"),
            {"estado": "GO", "municipio": "Abadiânia"},  # sem "escola_ids" - tudo desmarcado
            follow=True,
        )
        self.assertEqual(Lote.objects.count(), 0)
        self.assertContains(resp, "Nenhum INEP selecionado")

    def test_sem_elegivel_mostra_erro_e_preserva_filtro_no_redirecionamento(self):
        self.client.force_login(self.usuario)
        resp = self.client.post(
            reverse("mip_lote_criar"),
            {"estado": "GO", "municipio": "Abadiânia", "data_inicial": "01/09/2026", "data_final": "30/09/2026"},
        )
        self.assertEqual(Lote.objects.count(), 0)
        self.assertIn("estado=GO", resp.url)
        self.assertIn("municipio=Abadi", resp.url)

    def test_happy_path_cria_lote_e_redireciona_para_lista(self):
        escola, _ri = _criar_escola_elegivel_lote("10000020")
        self.client.force_login(self.usuario)
        resp = self.client.post(
            reverse("mip_lote_criar"),
            {
                "estado": "GO", "municipio": "Abadiânia",
                "data_inicial": "01/09/2026", "data_final": "30/09/2026",
                "escola_ids": [str(escola.pk)],
            },
        )
        self.assertRedirects(resp, reverse("mip_lote_inep"))
        self.assertEqual(Lote.objects.count(), 1)

    def test_desmarcar_um_inep_no_modal_exclui_ele_do_lote(self):
        """FEAT-050 (pedido do usuário, 2026-09-14): usuário desmarca 1
        INEP no modal de revisão — só os marcados entram no LOTE."""
        escola_marcada, _ri1 = _criar_escola_elegivel_lote("10000023")
        escola_desmarcada, _ri2 = _criar_escola_elegivel_lote("10000024")
        self.client.force_login(self.usuario)
        resp = self.client.post(
            reverse("mip_lote_criar"),
            {"estado": "GO", "municipio": "Abadiânia", "escola_ids": [str(escola_marcada.pk)]},
        )
        self.assertRedirects(resp, reverse("mip_lote_inep"))
        lote = Lote.objects.get()
        self.assertEqual(set(lote.escolas.all()), {escola_marcada})
        escola_desmarcada.refresh_from_db()
        self.assertEqual(escola_desmarcada.status_mip, Escola.AGUARDANDO_VALIDACAO_EACE)

    def test_escola_id_manipulado_fora_dos_elegiveis_e_ignorado(self):
        """Segurança (CLAUDE.md §6): `escola_ids` vindo do POST nunca é
        confiado cegamente — um ID de uma Escola que não é elegível de
        verdade (ex.: POST manipulado) é ignorado, nunca entra no LOTE."""
        escola_elegivel, _ri = _criar_escola_elegivel_lote("10000025")
        escola_nao_elegivel = Escola.objects.create(
            inep="10000026", nome="Escola Não Elegível", estado="GO", municipio="Abadiânia",
            status_mip=Escola.EM_ANDAMENTO,
        )
        self.client.force_login(self.usuario)
        resp = self.client.post(
            reverse("mip_lote_criar"),
            {
                "estado": "GO", "municipio": "Abadiânia",
                "escola_ids": [str(escola_elegivel.pk), str(escola_nao_elegivel.pk)],
            },
        )
        self.assertRedirects(resp, reverse("mip_lote_inep"))
        lote = Lote.objects.get()
        self.assertEqual(set(lote.escolas.all()), {escola_elegivel})


class MipLoteInepViewTests(TestCase):
    """Projeto > MIP (LOTE) (`mip_lote_inep_view`) — lista os LOTE já
    criados, com drill-down dos INEPs de cada um."""

    def setUp(self):
        self.usuario = User.objects.create_user(username="analista-lote-lista", password="senha-teste-123")
        self.visualizador = User.objects.create_user(
            username="visualizador-lote", password="senha-teste-123", perfil=User.PERFIL_VISUALIZADOR,
        )
        KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 2 Access Points", lote=9,
            valor_equipamento="1000.00", valor_servico="300.00",
        )

    def test_exige_login(self):
        resp = self.client.get(reverse("mip_lote_inep"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp.url)

    def test_sem_lote_mostra_estado_vazio(self):
        self.client.force_login(self.usuario)
        resp = self.client.get(reverse("mip_lote_inep"))
        self.assertContains(resp, "Nenhum LOTE criado")

    def test_lista_o_lote_criado_com_os_dados_e_os_ineps(self):
        escola, _ri = _criar_escola_elegivel_lote("10000030")
        lote = criar_lote_mip("GO", "Abadiânia", datetime.date(2026, 9, 1), datetime.date(2026, 9, 30), self.usuario)
        self.client.force_login(self.usuario)
        resp = self.client.get(reverse("mip_lote_inep"))
        self.assertContains(resp, str(lote))
        self.assertContains(resp, "GO")
        self.assertContains(resp, "Abadiânia")
        self.assertContains(resp, "01/09/2026")
        self.assertContains(resp, "30/09/2026")
        self.assertContains(resp, escola.inep)
        self.assertContains(resp, "R$ 300,00")

    def test_lote_sem_data_mostra_travessao(self):
        """RN-098 (correção, 2026-09-14): `Lote` criado sem Data
        inicial/final não quebra a tela — mostra "—" nas 2 colunas.
        Pedido do usuário (2026-09-15): a checagem do corpo de e-mail
        sugerido (`montar_corpo_email_lote`) saiu daqui — e-mail do LOTE
        comentado, a tela não calcula mais esse texto."""
        _criar_escola_elegivel_lote("10000032")
        criar_lote_mip("GO", "Abadiânia", None, None, self.usuario)
        self.client.force_login(self.usuario)
        resp = self.client.get(reverse("mip_lote_inep"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "—")

    def test_visualizador_e_bloqueado(self):
        """Pedido do usuário (2026-09-14, revisão): "esse MIP lote não
        pode ser acessado pelo usuario apenas com permissão de
        Visualizador" — diferente do grid "Projeto > MIP" (RN-096), aqui
        não há nem leitura; `VisualizadorAccessMiddleware` redireciona
        antes da view rodar."""
        _criar_escola_elegivel_lote("10000031")
        criar_lote_mip("GO", "Abadiânia", datetime.date(2026, 9, 1), datetime.date(2026, 9, 30), self.usuario)
        self.client.force_login(self.visualizador)
        resp = self.client.get(reverse("mip_lote_inep"))
        self.assertRedirects(resp, reverse("grid_inep"))

    def test_mostra_checkbox_por_lote_e_botao_de_baixar_zip(self):
        """Pedido do usuário (2026-09-15): checkbox por LOTE (fora do
        `<form>` de status/desfazer da própria linha, ligado por
        `form="form-baixar-planilhas-lotes"`) e o botão "Baixar planilhas
        (.zip)" no topo da tela."""
        _criar_escola_elegivel_lote("10000033")
        lote = criar_lote_mip("GO", "Abadiânia", datetime.date(2026, 9, 1), datetime.date(2026, 9, 30), self.usuario)
        self.client.force_login(self.usuario)
        resp = self.client.get(reverse("mip_lote_inep"))
        self.assertContains(resp, reverse("mip_lote_baixar_planilhas_zip"))
        self.assertContains(resp, "Baixar planilhas (.zip)")
        self.assertContains(
            resp,
            f'<input type="checkbox" name="lote_ids" value="{lote.pk}" form="form-baixar-planilhas-lotes"',
        )


class MipLoteBotaoGridTests(TestCase):
    """Botão "Criar LOTE" no grid "Projeto > MIP" (`mip_inep.html`) —
    exige Estado e Município (Data inicial/final são opcionais, RN-098
    revista em 2026-09-14) e mostra a contagem de elegíveis antes de o
    usuário clicar."""

    def setUp(self):
        self.usuario = User.objects.create_user(username="analista-lote-botao", password="senha-teste-123")
        self.visualizador = User.objects.create_user(
            username="visualizador-lote-botao", password="senha-teste-123", perfil=User.PERFIL_VISUALIZADOR,
        )
        KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 2 Access Points", lote=9,
            valor_equipamento="1000.00", valor_servico="300.00",
        )
        self.escola, _ri = _criar_escola_elegivel_lote("10000040")

    def test_sem_filtro_completo_nao_mostra_botao(self):
        self.client.force_login(self.usuario)
        resp = self.client.get(reverse("mip_inep"), {"estado": "GO"})
        self.assertNotContains(resp, "Criar LOTE")
        self.assertContains(resp, "Preencha Estado e Município")

    def test_estado_e_municipio_sem_data_mostra_botao_habilitado(self):
        """RN-098 (correção, 2026-09-14 — bug real reportado pelo
        usuário, INEP 52171205): filtrar só Estado/Município (sem data)
        já mostra o botão "Criar LOTE" habilitado."""
        self.client.force_login(self.usuario)
        resp = self.client.get(reverse("mip_inep"), {"estado": "GO", "municipio": "Abadiânia"})
        self.assertContains(resp, "Criar LOTE")
        self.assertContains(resp, "1 INEP")
        self.assertNotContains(resp, 'button" disabled')

    def test_filtro_completo_com_elegivel_mostra_botao_habilitado(self):
        self.client.force_login(self.usuario)
        resp = self.client.get(
            reverse("mip_inep"),
            {"estado": "GO", "municipio": "Abadiânia", "data_inicial": "01/09/2026", "data_final": "30/09/2026"},
        )
        self.assertContains(resp, "Criar LOTE")
        self.assertContains(resp, "1 INEP")
        # `disabled:opacity-40` (classe Tailwind) sempre aparece no HTML —
        # o que muda é o atributo `disabled` do próprio `<button>` que
        # abre o modal de revisão (FEAT-050, `_modal_criar_lote.html`).
        self.assertNotContains(resp, 'button" disabled')

    def test_filtro_completo_sem_elegivel_mostra_botao_desabilitado(self):
        # Diverge o Valor Total (EACE) do (IXC) sem tirar a escola de
        # "Aguardando Validação EACE" — RN-104: se ela saísse desse
        # status, "GO" sumiria do `<select>` de Estado (RN-079, base é
        # "Validação EACE") e o filtro seria ignorado, não "0 elegíveis".
        EscolaItemRelatorioEaceMip.objects.filter(escola=self.escola).update(quantidade=2)
        self.client.force_login(self.usuario)
        resp = self.client.get(
            reverse("mip_inep"),
            {"estado": "GO", "municipio": "Abadiânia", "data_inicial": "01/09/2026", "data_final": "30/09/2026"},
        )
        self.assertContains(resp, "Nenhum INEP elegível")
        self.assertContains(resp, 'button" disabled')

    def test_modal_de_revisao_lista_os_ineps_elegiveis_com_checkbox(self):
        """FEAT-050 (pedido do usuário, 2026-09-14): modal com 1 checkbox
        marcado por INEP elegível, pronto pra desmarcar antes de criar."""
        self.client.force_login(self.usuario)
        resp = self.client.get(
            reverse("mip_inep"),
            {"estado": "GO", "municipio": "Abadiânia", "data_inicial": "01/09/2026", "data_final": "30/09/2026"},
        )
        self.assertContains(resp, "Revisar INEPs do LOTE")
        self.assertContains(resp, f'value="{self.escola.pk}" checked')
        self.assertContains(resp, self.escola.inep)

    def test_visualizador_nao_ve_botao(self):
        self.client.force_login(self.visualizador)
        resp = self.client.get(
            reverse("mip_inep"),
            {"estado": "GO", "municipio": "Abadiânia", "data_inicial": "01/09/2026", "data_final": "30/09/2026"},
        )
        self.assertNotContains(resp, "Criar LOTE")


class MipStatusAguardandoEncerramentoLoteNaoManualTests(TestCase):
    """FEAT-044/RN-098: "Aguardando Encerramento LOTE" nunca é escolhido
    manualmente — só `criar_lote_mip` grava esse status."""

    def setUp(self):
        self.usuario = User.objects.create_user(username="analista-lote-manual", password="senha-teste-123")
        self.escola = Escola.objects.create(
            inep="10000050", nome="Escola Teste Manual", status_mip=Escola.AGUARDANDO_VALIDACAO_EACE,
        )
        Ri.objects.create(escola=self.escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)

    def test_dropdown_do_detalhe_nao_oferece_a_opcao(self):
        self.client.force_login(self.usuario)
        resp = self.client.get(reverse("mip_detail", kwargs={"inep": self.escola.inep}))
        self.assertNotContains(resp, '<option value="aguardando_encerramento_lote"')

    def test_post_direto_e_rejeitado(self):
        self.client.force_login(self.usuario)
        self.client.post(
            reverse("mip_status_update", kwargs={"inep": self.escola.inep}),
            {"status_mip": Escola.AGUARDANDO_ENCERRAMENTO_LOTE},
        )
        self.escola.refresh_from_db()
        self.assertEqual(self.escola.status_mip, Escola.AGUARDANDO_VALIDACAO_EACE)


class GerarPlanilhaFaturamentoImplantacaoLoteTests(TestCase):
    """`gerar_planilha_faturamento_implantacao_lote` (FEAT-045, a formalizar
    pelo Orquestrador em business_rules.md) — mesma planilha de
    `gerar_planilha_faturamento_implantacao` (`GerarPlanilhaFaturamento
    ImplantacaoTests` acima), mas a partir dos INEPs FIXOS de um `Lote`
    (`lote.escolas`), nunca de um filtro por Estado/Município/status."""

    def setUp(self):
        KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 2 Access Points", lote=9,
            valor_equipamento="1000.00", valor_servico="300.00",
        )
        self.escola_a = Escola.objects.create(
            inep="60171205", nome="Escola A do LOTE", estado="GO", municipio="Abadiânia",
            lote=9, cod_fornecedor="52598",
        )
        self.escola_b = Escola.objects.create(
            inep="60171206", nome="Escola B do LOTE", estado="GO", municipio="Abadiânia",
            lote=9, cod_fornecedor="52599",
        )
        self.ri_a = Ri.objects.create(escola=self.escola_a, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        self.ri_b = Ri.objects.create(escola=self.escola_b, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        RiItemIxc.objects.create(
            ri=self.ri_a, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
            quantidade=1, valor_unitario="0.00", eh_kit=True,
        )
        RiItemIxc.objects.create(
            ri=self.ri_b, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
            quantidade=2, valor_unitario="0.00", eh_kit=True,
        )
        self.lote = Lote.objects.create(
            estado="GO", municipio="Abadiânia",
            data_inicio=datetime.date(2026, 9, 1), data_fim=datetime.date(2026, 9, 30),
        )
        self.lote.escolas.set([self.escola_a, self.escola_b])
        self.data_envio = datetime.date(2026, 9, 8)

    def test_soma_valor_total_ixc_dos_ineps_do_lote(self):
        """RN-076: 1 x 300,00 (Escola A) + 2 x 300,00 (Escola B) = 900,00."""
        workbook = gerar_planilha_faturamento_implantacao_lote(self.lote, self.data_envio)
        self.assertEqual(workbook.worksheets[0]["H10"].value, 900.00)

    def test_codigo_ineps_e_aba_usam_so_os_ineps_do_lote(self):
        workbook = gerar_planilha_faturamento_implantacao_lote(self.lote, self.data_envio)
        aba = workbook.worksheets[0]
        self.assertEqual(aba.title, "Abadiânia")
        self.assertIn("CÓDIGO INEPS: 60171205/52598;60171206/52599", aba["F10"].value)

    def test_vencimento_e10_e_data_envio_mais_30_dias(self):
        workbook = gerar_planilha_faturamento_implantacao_lote(self.lote, self.data_envio)
        self.assertEqual(workbook.worksheets[0]["E10"].value, datetime.date(2026, 10, 8))

    def test_municipio_uf_em_maiusculo_no_texto_da_observacao(self):
        """Pedido do usuário (2026-09-16): nome do Município em maiúsculo
        no texto de observação (F10) — "ABADIÂNIA", não "Abadiânia"."""
        workbook = gerar_planilha_faturamento_implantacao_lote(self.lote, self.data_envio)
        aba = workbook.worksheets[0]
        self.assertIn("MUNICIPIO/UF: ABADIÂNIA/GO", aba["F10"].value)

    def test_escola_do_mesmo_municipio_fora_do_lote_nao_entra(self):
        """Diferença chave em relação a `gerar_planilha_faturamento_
        implantacao` (filtro por Estado/Município): um INEP do MESMO
        Estado/Município, mas que não foi incluído neste LOTE, nunca entra
        na soma nem no CÓDIGO INEPS — só quem está de fato em
        `lote.escolas` conta (pedido do usuário: "a soma de todos os
        INEPS daquele LOTE")."""
        escola_fora_do_lote = Escola.objects.create(
            inep="60171207", nome="Escola Fora do LOTE", estado="GO", municipio="Abadiânia",
            lote=9, cod_fornecedor="99999",
        )
        ri_fora = Ri.objects.create(escola=escola_fora_do_lote, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        RiItemIxc.objects.create(
            ri=ri_fora, descricao_item="Kit Cobertura Wi-Fi - 2 Access Points",
            quantidade=5, valor_unitario="0.00", eh_kit=True,
        )
        workbook = gerar_planilha_faturamento_implantacao_lote(self.lote, self.data_envio)
        aba = workbook.worksheets[0]
        self.assertEqual(aba["H10"].value, 900.00)  # sem mudança — quem não está no LOTE não entra
        self.assertNotIn("60171207", aba["F10"].value)

    def test_erro_claro_sem_nenhum_inep_no_lote(self):
        self.lote.escolas.clear()
        with self.assertRaisesMessage(PlanilhaFaturamentoImplantacaoError, f"{self.lote} não tem nenhum INEP."):
            gerar_planilha_faturamento_implantacao_lote(self.lote, self.data_envio)


# Pedido do usuario (2026-09-15): envio de e-mail do LOTE comentado (nao
# sera usado por enquanto) -- classes de teste abaixo mantidas comentadas
# (nao apagadas) para reativacao futura, junto com o codigo que testam
# (apps.escolas.services.enviar_email_lote e afins).
# # ---------------------------------------------------------------------------
# # FEAT-045 (a formalizar pelo Orquestrador em business_rules.md; pedido do
# # usuário, 2026-09-14): "Enviar e-mail" do LOTE.
# # ---------------------------------------------------------------------------


# _MEDIA_ROOT_TESTE_EMAIL_LOTE = tempfile.mkdtemp()


# @override_settings(MEDIA_ROOT=_MEDIA_ROOT_TESTE_EMAIL_LOTE)
# class EnviarEmailLoteTests(TestCase):
    # """`apps.escolas.services.enviar_email_lote` — envia o e-mail e grava,
    # no histórico do RI atual de cada INEP do LOTE, que o e-mail foi
    # disparado (pedido explícito do usuário). MEDIA_ROOT isolado num
    # diretório temporário para os arquivos de teste não irem para o
    # `media/` real (mesmo padrão de `MipDetailLado2NfRecebidaEmTests`)."""

    # @classmethod
    # def tearDownClass(cls):
        # super().tearDownClass()
        # shutil.rmtree(_MEDIA_ROOT_TESTE_EMAIL_LOTE, ignore_errors=True)

    # def setUp(self):
        # self.usuario = User.objects.create_user(username="analista-email-lote", password="senha-teste-123")
        # self.escola1 = Escola.objects.create(
            # inep="10000060", nome="Escola Email Lote 1", estado="GO", municipio="Abadiânia",
            # status_mip=Escola.AGUARDANDO_ENCERRAMENTO_LOTE,
        # )
        # self.escola2 = Escola.objects.create(
            # inep="10000061", nome="Escola Email Lote 2", estado="GO", municipio="Abadiânia",
            # status_mip=Escola.AGUARDANDO_ENCERRAMENTO_LOTE,
        # )
        # self.ri1 = Ri.objects.create(escola=self.escola1, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        # self.ri2 = Ri.objects.create(escola=self.escola2, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        # self.lote = Lote.objects.create(
            # estado="GO", municipio="Abadiânia",
            # data_inicio=datetime.date(2026, 9, 1), data_fim=datetime.date(2026, 9, 30),
            # criado_por=self.usuario,
        # )
        # self.lote.escolas.set([self.escola1, self.escola2])

    # def test_envia_o_email_com_de_fixo_e_para_informado(self):
        # enviar_email_lote(
            # self.lote, para=["financeiro@example.com"], assunto="Assunto teste",
            # mensagem="Corpo teste", anexo_extra=None, usuario=self.usuario,
        # )
        # self.assertEqual(len(mail.outbox), 1)
        # enviado = mail.outbox[0]
        # self.assertEqual(enviado.to, ["financeiro@example.com"])
        # self.assertEqual(enviado.subject, "Assunto teste")
        # self.assertEqual(enviado.body, "Corpo teste")
        # from django.conf import settings
        # self.assertEqual(enviado.from_email, settings.DEFAULT_FROM_EMAIL)

    # def test_para_vazio_nao_impede_o_registro_no_historico(self):
        # """Pedido do usuário: "o PARA pode deixar em branco" — sem
        # destinatário, o Django não entrega nada de verdade, mas o
        # histórico de cada INEP é gravado do mesmo jeito."""
        # enviar_email_lote(
            # self.lote, para=[], assunto="Assunto teste", mensagem="Corpo teste",
            # anexo_extra=None, usuario=self.usuario,
        # )
        # self.assertTrue(
            # self.ri1.historico.filter(tipo=RiHistorico.EMAIL, mensagem__contains=str(self.lote)).exists()
        # )
        # self.assertTrue(
            # self.ri2.historico.filter(tipo=RiHistorico.EMAIL, mensagem__contains=str(self.lote)).exists()
        # )

    # def test_grava_historico_em_todos_os_ineps_do_lote(self):
        # enviar_email_lote(
            # self.lote, para=["financeiro@example.com"], assunto="Assunto teste",
            # mensagem="Corpo teste", anexo_extra=None, usuario=self.usuario,
        # )
        # entrada1 = self.ri1.historico.get(tipo=RiHistorico.EMAIL)
        # entrada2 = self.ri2.historico.get(tipo=RiHistorico.EMAIL)
        # self.assertIn(str(self.lote), entrada1.mensagem)
        # self.assertIn("Assunto teste", entrada1.mensagem)
        # self.assertIn(str(self.lote), entrada2.mensagem)
        # self.assertEqual(entrada1.autor, self.usuario)

    # def test_escola_sem_ri_nao_quebra_o_envio(self):
        # escola_sem_ri = Escola.objects.create(
            # inep="10000062", nome="Escola Sem RI", status_mip=Escola.AGUARDANDO_ENCERRAMENTO_LOTE,
        # )
        # self.lote.escolas.add(escola_sem_ri)
        # enviar_email_lote(
            # self.lote, para=["fin@example.com"], assunto="Assunto teste", mensagem="Corpo teste",
            # anexo_extra=None, usuario=self.usuario,
        # )
        # self.assertEqual(len(mail.outbox), 1)
        # self.assertTrue(self.ri1.historico.filter(tipo=RiHistorico.EMAIL).exists())
        # self.assertTrue(self.ri2.historico.filter(tipo=RiHistorico.EMAIL).exists())

    # def test_atualiza_email_enviado_em_e_por(self):
        # self.assertIsNone(self.lote.email_enviado_em)
        # enviar_email_lote(
            # self.lote, para=[], assunto="Assunto teste", mensagem="Corpo teste",
            # anexo_extra=None, usuario=self.usuario,
        # )
        # self.lote.refresh_from_db()
        # self.assertIsNotNone(self.lote.email_enviado_em)
        # self.assertEqual(self.lote.email_enviado_por, self.usuario)

    # def test_avanca_status_do_lote_e_dos_ineps_para_email_enviado(self):
        # """FEAT-046 (a criar): pedido do usuário — depois de enviar o
        # e-mail, o Status do LOTE vira "Email em LOTE enviado" e todo INEP
        # do LOTE ganha o mesmo Status (MIP), registrado no histórico."""
        # enviar_email_lote(
            # self.lote, para=[], assunto="Assunto teste", mensagem="Corpo teste",
            # anexo_extra=None, usuario=self.usuario,
        # )
        # self.lote.refresh_from_db()
        # self.escola1.refresh_from_db()
        # self.escola2.refresh_from_db()
        # self.assertEqual(self.lote.status, Lote.EMAIL_ENVIADO)
        # self.assertEqual(self.escola1.status_mip, Escola.EMAIL_LOTE_ENVIADO)
        # self.assertEqual(self.escola2.status_mip, Escola.EMAIL_LOTE_ENVIADO)
        # entrada_status = self.ri1.historico.get(tipo=RiHistorico.LOG_CAMPO, campo="Status (MIP)")
        # self.assertEqual(entrada_status.valor_novo, "Email em LOTE enviado")

    # def test_escola_sem_ri_tambem_avanca_status_mip(self):
        # escola_sem_ri = Escola.objects.create(
            # inep="10000063", nome="Escola Sem RI 2", status_mip=Escola.AGUARDANDO_ENCERRAMENTO_LOTE,
        # )
        # self.lote.escolas.add(escola_sem_ri)
        # enviar_email_lote(
            # self.lote, para=[], assunto="Assunto teste", mensagem="Corpo teste",
            # anexo_extra=None, usuario=self.usuario,
        # )
        # escola_sem_ri.refresh_from_db()
        # self.assertEqual(escola_sem_ri.status_mip, Escola.EMAIL_LOTE_ENVIADO)

    # def test_reenvio_permitido_enquanto_status_nao_avancou(self):
        # enviar_email_lote(
            # self.lote, para=[], assunto="1º envio", mensagem="Corpo", anexo_extra=None, usuario=self.usuario,
        # )
        # enviar_email_lote(
            # self.lote, para=[], assunto="2º envio", mensagem="Corpo", anexo_extra=None, usuario=self.usuario,
        # )
        # self.assertEqual(self.ri1.historico.filter(tipo=RiHistorico.EMAIL).count(), 2)

    # def test_bloqueado_depois_que_lote_avanca_para_em_andamento(self):
        # self.lote.status = Lote.EM_ANDAMENTO
        # self.lote.save()
        # with self.assertRaises(LoteMipError):
            # enviar_email_lote(
                # self.lote, para=[], assunto="Teste", mensagem="Corpo", anexo_extra=None, usuario=self.usuario,
            # )

    # def test_bloqueado_depois_que_lote_avanca_para_faturamento_concluido(self):
        # self.lote.status = Lote.FATURAMENTO_CONCLUIDO
        # self.lote.save()
        # with self.assertRaises(LoteMipError):
            # enviar_email_lote(
                # self.lote, para=[], assunto="Teste", mensagem="Corpo", anexo_extra=None, usuario=self.usuario,
            # )

    # def test_planilha_de_faturamento_e_sempre_anexada_ao_email(self):
        # """FEAT-045 (pedido do usuário, 2026-09-14): o anexo OFICIAL do
        # e-mail do LOTE passa a ser gerado automaticamente — mesmo sem
        # nenhum `anexo_extra` informado — a partir dos INEPs deste LOTE
        # (`gerar_planilha_faturamento_implantacao_lote`)."""
        # self.escola1.cod_fornecedor = "1111"
        # self.escola1.save(update_fields=["cod_fornecedor"])
        # self.escola2.cod_fornecedor = "2222"
        # self.escola2.save(update_fields=["cod_fornecedor"])

        # enviar_email_lote(
            # self.lote, para=["fin@example.com"], assunto="Assunto teste", mensagem="Corpo teste",
            # anexo_extra=None, usuario=self.usuario,
        # )

        # self.assertEqual(len(mail.outbox[0].attachments), 1)
        # nome_email, conteudo_email, mime_email = mail.outbox[0].attachments[0]
        # self.assertEqual(nome_email, nome_arquivo_planilha_faturamento_implantacao(self.lote))
        # self.assertEqual(mime_email, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        # workbook_recebido = openpyxl.load_workbook(io.BytesIO(conteudo_email))
        # aba = workbook_recebido.worksheets[0]
        # self.assertEqual(aba.title, "Abadiânia")
        # self.assertIn("CÓDIGO INEPS: 10000060/1111;10000061/2222", aba["F10"].value)

    # def test_planilha_gerada_e_salva_no_historico_de_cada_inep(self):
        # enviar_email_lote(
            # self.lote, para=["fin@example.com"], assunto="Assunto teste", mensagem="Corpo teste",
            # anexo_extra=None, usuario=self.usuario,
        # )
        # entrada1 = self.ri1.historico.get(tipo=RiHistorico.EMAIL)
        # entrada2 = self.ri2.historico.get(tipo=RiHistorico.EMAIL)
        # # 2 INEPs recebem a MESMA planilha salva 2x — o storage evita
        # # sobrescrever o 1º arquivo, então o nome do 2º ganha um sufixo
        # # (comportamento padrão do Django); por isso conferir só a
        # # extensão, não o nome exato, e o CONTEÚDO (uma planilha válida).
        # for entrada in (entrada1, entrada2):
            # self.assertTrue(entrada.anexo.name.endswith(".xlsx"))
            # entrada.anexo.open("rb")
            # conteudo_historico = entrada.anexo.read()
            # entrada.anexo.close()
            # workbook_historico = openpyxl.load_workbook(io.BytesIO(conteudo_historico))
            # self.assertEqual(workbook_historico.worksheets[0].title, "Abadiânia")

    # def test_anexo_extra_soma_no_email_mas_nao_substitui_a_planilha_no_historico(self):
        # anexo_extra = SimpleUploadedFile("comprovante.pdf", b"conteudo-pdf", content_type="application/pdf")
        # enviar_email_lote(
            # self.lote, para=["fin@example.com"], assunto="Assunto teste", mensagem="Corpo teste",
            # anexo_extra=anexo_extra, usuario=self.usuario,
        # )
        # self.assertEqual(len(mail.outbox[0].attachments), 2)
        # nome_extra, conteudo_extra, mime_extra = mail.outbox[0].attachments[1]
        # self.assertEqual(nome_extra, "comprovante.pdf")
        # self.assertEqual(conteudo_extra, b"conteudo-pdf")

        # entrada1 = self.ri1.historico.get(tipo=RiHistorico.EMAIL)
        # self.assertTrue(entrada1.anexo.name.endswith(".xlsx"))
        # entrada1.anexo.open("rb")
        # conteudo_historico = entrada1.anexo.read()
        # entrada1.anexo.close()
        # self.assertNotEqual(conteudo_historico, b"conteudo-pdf")

    # def test_lote_sem_nenhum_inep_levanta_erro_sem_enviar_nada(self):
        # self.lote.escolas.clear()
        # with self.assertRaises(PlanilhaFaturamentoImplantacaoError):
            # enviar_email_lote(
                # self.lote, para=[], assunto="Teste", mensagem="Corpo",
                # anexo_extra=None, usuario=self.usuario,
            # )
        # self.assertEqual(len(mail.outbox), 0)
        # self.lote.refresh_from_db()
        # self.assertIsNone(self.lote.email_enviado_em)

    # def test_montar_assunto_email_lote_usa_lote_municipio_estado(self):
        # assunto = montar_assunto_email_lote(self.lote)
        # self.assertIn(str(self.lote), assunto)
        # self.assertIn("Abadiânia/GO", assunto)


# class MipLoteEnviarEmailViewTests(TestCase):
    # """`mip_lote_enviar_email_view` — recebe o POST do modal de composição
    # e delega para `enviar_email_lote`."""

    # def setUp(self):
        # self.usuario = User.objects.create_user(username="analista-email-lote-view", password="senha-teste-123")
        # self.visualizador = User.objects.create_user(
            # username="visualizador-email-lote", password="senha-teste-123", perfil=User.PERFIL_VISUALIZADOR,
        # )
        # self.escola = Escola.objects.create(
            # inep="10000070", nome="Escola Email Lote View", status_mip=Escola.AGUARDANDO_ENCERRAMENTO_LOTE,
        # )
        # self.ri = Ri.objects.create(escola=self.escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        # self.lote = Lote.objects.create(
            # estado="GO", municipio="Abadiânia",
            # data_inicio=datetime.date(2026, 9, 1), data_fim=datetime.date(2026, 9, 30),
        # )
        # self.lote.escolas.add(self.escola)

    # def test_exige_login(self):
        # resp = self.client.post(
            # reverse("mip_lote_enviar_email", kwargs={"pk": self.lote.pk}), {"assunto": "Teste"},
        # )
        # self.assertEqual(resp.status_code, 302)
        # self.assertIn(reverse("login"), resp.url)

    # def test_get_nao_envia_nada(self):
        # self.client.force_login(self.usuario)
        # resp = self.client.get(reverse("mip_lote_enviar_email", kwargs={"pk": self.lote.pk}))
        # self.assertRedirects(resp, reverse("mip_lote_inep"))
        # self.assertEqual(len(mail.outbox), 0)

    # def test_sem_assunto_mostra_erro_e_nao_envia(self):
        # self.client.force_login(self.usuario)
        # self.client.post(
            # reverse("mip_lote_enviar_email", kwargs={"pk": self.lote.pk}), {"assunto": "", "para": ""},
        # )
        # self.assertEqual(len(mail.outbox), 0)

    # def test_para_com_email_invalido_mostra_erro_e_nao_envia(self):
        # self.client.force_login(self.usuario)
        # self.client.post(
            # reverse("mip_lote_enviar_email", kwargs={"pk": self.lote.pk}),
            # {"assunto": "Teste", "para": "nao-e-email"},
        # )
        # self.assertEqual(len(mail.outbox), 0)

    # def test_para_em_branco_e_aceito(self):
        # """Pedido do usuário: "o PARA pode deixar em branco" — o form
        # aceita (sem erro de validação) e o histórico do INEP é gravado.
        # `EmailMessage.send()` do Django não entrega nada sem nenhum
        # destinatário (nem `mail.outbox` recebe a mensagem) — comportamento
        # padrão do Django, documentado em `enviar_email_lote`."""
        # self.client.force_login(self.usuario)
        # resp = self.client.post(
            # reverse("mip_lote_enviar_email", kwargs={"pk": self.lote.pk}),
            # {"assunto": "Teste", "para": "", "mensagem": "Corpo"},
        # )
        # self.assertRedirects(resp, reverse("mip_lote_inep"))
        # self.assertEqual(len(mail.outbox), 0)
        # self.assertTrue(self.ri.historico.filter(tipo=RiHistorico.EMAIL).exists())

    # def test_visualizador_nao_consegue_enviar(self):
        # self.client.force_login(self.visualizador)
        # resp = self.client.post(
            # reverse("mip_lote_enviar_email", kwargs={"pk": self.lote.pk}),
            # {"assunto": "Teste", "para": ""},
        # )
        # self.assertEqual(len(mail.outbox), 0)
        # self.escola.refresh_from_db()
        # self.assertFalse(self.ri.historico.filter(tipo=RiHistorico.EMAIL).exists())


class MipLoteBaixarPlanilhaViewTests(TestCase):
    """`mip_lote_baixar_planilha_view` (FEAT-045) — baixa a mesma planilha
    que seria anexada ao e-mail do LOTE, sem enviar nada (botão "Baixar
    planilha" do modal), mesmo padrão de
    `apps.ri.views.ri_baixar_planilha_financeiro_view`."""

    def setUp(self):
        self.usuario = User.objects.create_user(username="analista-baixar-planilha-lote", password="senha-teste-123")
        self.escola = Escola.objects.create(
            inep="10000075", nome="Escola Baixar Planilha Lote", status_mip=Escola.AGUARDANDO_ENCERRAMENTO_LOTE,
        )
        Ri.objects.create(escola=self.escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        self.lote = Lote.objects.create(
            estado="GO", municipio="Abadiânia",
            data_inicio=datetime.date(2026, 9, 1), data_fim=datetime.date(2026, 9, 30),
        )
        self.lote.escolas.add(self.escola)

    def test_exige_login(self):
        resp = self.client.get(reverse("mip_lote_baixar_planilha", kwargs={"pk": self.lote.pk}))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp.url)

    def test_baixa_o_xlsx_sem_enviar_email(self):
        self.client.force_login(self.usuario)
        resp = self.client.get(reverse("mip_lote_baixar_planilha", kwargs={"pk": self.lote.pk}))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn("attachment;", resp["Content-Disposition"])
        self.assertEqual(len(mail.outbox), 0)

        workbook = openpyxl.load_workbook(io.BytesIO(resp.content))
        self.assertEqual(workbook.worksheets[0].title, "Abadiânia")

    def test_lote_sem_nenhum_inep_mostra_erro_e_redireciona(self):
        self.lote.escolas.clear()
        self.client.force_login(self.usuario)
        resp = self.client.get(reverse("mip_lote_baixar_planilha", kwargs={"pk": self.lote.pk}))
        self.assertRedirects(resp, reverse("mip_lote_inep"))


_MEDIA_ROOT_TESTE_NOTAS_FISCAIS_LOTE = tempfile.mkdtemp()


def _gerar_zip_teste():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as arquivo_zip:
        arquivo_zip.writestr("nota1.pdf", b"conteudo fake")
    return buffer.getvalue()


@override_settings(MEDIA_ROOT=_MEDIA_ROOT_TESTE_NOTAS_FISCAIS_LOTE)
class MipLoteNotasFiscaisUploadViewTests(TestCase):
    """Pedido do usuário (2026-09-17): botão de upload do .zip de Notas
    Fiscais que o financeiro devolve para todo o LOTE de uma vez — 1
    arquivo por LOTE, substituível (`Lote.substituir_notas_fiscais_zip`).
    MEDIA_ROOT isolado num diretório temporário (arquivo de verdade no
    disco, mesmo padrão de `MipLoteBaixarPlanilhaViewTests`)."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT_TESTE_NOTAS_FISCAIS_LOTE, ignore_errors=True)

    def setUp(self):
        self.usuario = User.objects.create_user(username="analista-nf-lote", password="senha-teste-123")
        self.lote = Lote.objects.create(estado="GO", municipio="Abadiânia")

    def _enviar(self, nome="notas.zip", conteudo=None):
        conteudo = conteudo if conteudo is not None else _gerar_zip_teste()
        return self.client.post(
            reverse("mip_lote_notas_fiscais_upload", kwargs={"pk": self.lote.pk}),
            {"arquivo": SimpleUploadedFile(nome, conteudo), "next": ""},
        )

    def test_exige_login(self):
        resp = self._enviar()
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp.url)

    def test_envia_o_primeiro_arquivo(self):
        self.client.force_login(self.usuario)
        self._enviar()
        self.lote.refresh_from_db()
        self.assertTrue(self.lote.arquivo_notas_fiscais_zip.name)
        self.assertEqual(self.lote.nome_original_notas_fiscais_zip, "notas.zip")
        self.assertEqual(self.lote.notas_fiscais_zip_enviado_por, self.usuario)
        self.assertIsNotNone(self.lote.notas_fiscais_zip_enviado_em)

    def test_substitui_sem_manter_2_arquivos(self):
        self.client.force_login(self.usuario)
        self._enviar(nome="notas-v1.zip")
        self.lote.refresh_from_db()
        caminho_v1 = self.lote.arquivo_notas_fiscais_zip.path
        self.assertTrue(Path(caminho_v1).exists())

        self._enviar(nome="notas-v2.zip")
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.nome_original_notas_fiscais_zip, "notas-v2.zip")
        self.assertFalse(Path(caminho_v1).exists())  # arquivo antigo apagado do disco (só 1 por vez)

    def test_recusa_arquivo_que_nao_e_zip_de_verdade(self):
        self.client.force_login(self.usuario)
        resp = self._enviar(nome="notas.zip", conteudo=b"nao e um zip de verdade")
        self.lote.refresh_from_db()
        self.assertFalse(self.lote.arquivo_notas_fiscais_zip.name)
        mensagens = [str(m) for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("zip" in m.lower() for m in mensagens))

    def test_recusa_extensao_diferente_de_zip(self):
        self.client.force_login(self.usuario)
        self._enviar(nome="notas.pdf", conteudo=b"conteudo qualquer")
        self.lote.refresh_from_db()
        self.assertFalse(self.lote.arquivo_notas_fiscais_zip.name)


class MipLoteBaixarPlanilhasZipViewTests(TestCase):
    """`mip_lote_baixar_planilhas_zip_view` — pedido do usuário
    (2026-09-15): marcar vários LOTEs na tela "Projeto > MIP (LOTE)" e
    baixar, num único .zip, 1 planilha de faturamento de implantação por
    LOTE marcado."""

    def setUp(self):
        self.usuario = User.objects.create_user(username="analista-zip-lotes", password="senha-teste-123")
        self.visualizador = User.objects.create_user(
            username="visualizador-zip-lotes", password="senha-teste-123", perfil=User.PERFIL_VISUALIZADOR,
        )

        self.escola1 = Escola.objects.create(
            inep="10000076", nome="Escola ZIP Lote 1", estado="GO", municipio="Abadiânia",
            status_mip=Escola.AGUARDANDO_ENCERRAMENTO_LOTE,
        )
        Ri.objects.create(escola=self.escola1, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        self.lote1 = Lote.objects.create(
            estado="GO", municipio="Abadiânia",
            data_inicio=datetime.date(2026, 9, 1), data_fim=datetime.date(2026, 9, 30),
        )
        self.lote1.escolas.add(self.escola1)

        self.escola2 = Escola.objects.create(
            inep="10000077", nome="Escola ZIP Lote 2", estado="GO", municipio="Anápolis",
            status_mip=Escola.AGUARDANDO_ENCERRAMENTO_LOTE,
        )
        Ri.objects.create(escola=self.escola2, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        self.lote2 = Lote.objects.create(
            estado="GO", municipio="Anápolis",
            data_inicio=datetime.date(2026, 9, 1), data_fim=datetime.date(2026, 9, 30),
        )
        self.lote2.escolas.add(self.escola2)

        # LOTE de fora da seleção — usado pra confirmar que só os marcados
        # entram no .zip.
        self.escola3 = Escola.objects.create(
            inep="10000078", nome="Escola ZIP Lote 3", estado="GO", municipio="Trindade",
            status_mip=Escola.AGUARDANDO_ENCERRAMENTO_LOTE,
        )
        Ri.objects.create(escola=self.escola3, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        self.lote3 = Lote.objects.create(
            estado="GO", municipio="Trindade",
            data_inicio=datetime.date(2026, 9, 1), data_fim=datetime.date(2026, 9, 30),
        )
        self.lote3.escolas.add(self.escola3)

    def test_exige_login(self):
        resp = self.client.post(
            reverse("mip_lote_baixar_planilhas_zip"), {"lote_ids": [self.lote1.pk]},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp.url)

    def test_get_nao_baixa_nada(self):
        self.client.force_login(self.usuario)
        resp = self.client.get(reverse("mip_lote_baixar_planilhas_zip"))
        self.assertRedirects(resp, reverse("mip_lote_inep"))

    def test_sem_selecionar_nenhum_mostra_erro_e_redireciona(self):
        self.client.force_login(self.usuario)
        resp = self.client.post(reverse("mip_lote_baixar_planilhas_zip"), {}, follow=True)
        self.assertRedirects(resp, reverse("mip_lote_inep"))
        mensagens = [str(m) for m in resp.context["messages"]]
        self.assertTrue(any("Selecione ao menos um LOTE" in m for m in mensagens))

    def test_baixa_zip_com_uma_planilha_por_lote_marcado(self):
        self.client.force_login(self.usuario)
        resp = self.client.post(
            reverse("mip_lote_baixar_planilhas_zip"),
            {"lote_ids": [self.lote1.pk, self.lote2.pk]},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/zip")
        self.assertIn("attachment;", resp["Content-Disposition"])

        arquivo_zip = zipfile.ZipFile(io.BytesIO(resp.content))
        nomes_no_zip = arquivo_zip.namelist()
        self.assertEqual(len(nomes_no_zip), 2)
        self.assertIn(nome_arquivo_planilha_faturamento_implantacao(self.lote1), nomes_no_zip)
        self.assertIn(nome_arquivo_planilha_faturamento_implantacao(self.lote2), nomes_no_zip)

        planilha1 = openpyxl.load_workbook(
            io.BytesIO(arquivo_zip.read(nome_arquivo_planilha_faturamento_implantacao(self.lote1)))
        )
        self.assertEqual(planilha1.worksheets[0].title, "Abadiânia")
        planilha2 = openpyxl.load_workbook(
            io.BytesIO(arquivo_zip.read(nome_arquivo_planilha_faturamento_implantacao(self.lote2)))
        )
        self.assertEqual(planilha2.worksheets[0].title, "Anápolis")

    def test_nao_inclui_lote_nao_marcado(self):
        self.client.force_login(self.usuario)
        resp = self.client.post(
            reverse("mip_lote_baixar_planilhas_zip"), {"lote_ids": [self.lote1.pk]},
        )
        arquivo_zip = zipfile.ZipFile(io.BytesIO(resp.content))
        nomes_no_zip = arquivo_zip.namelist()
        self.assertEqual(len(nomes_no_zip), 1)
        self.assertNotIn(nome_arquivo_planilha_faturamento_implantacao(self.lote3), nomes_no_zip)

    def test_lote_marcado_sem_nenhum_inep_mostra_erro_e_redireciona(self):
        self.lote2.escolas.clear()
        self.client.force_login(self.usuario)
        resp = self.client.post(
            reverse("mip_lote_baixar_planilhas_zip"),
            {"lote_ids": [self.lote1.pk, self.lote2.pk]},
            follow=True,
        )
        self.assertRedirects(resp, reverse("mip_lote_inep"))
        mensagens = [str(m) for m in resp.context["messages"]]
        self.assertTrue(any(str(self.lote2) in m for m in mensagens))

    def test_visualizador_bloqueado_pelo_middleware(self):
        self.client.force_login(self.visualizador)
        resp = self.client.post(
            reverse("mip_lote_baixar_planilhas_zip"), {"lote_ids": [self.lote1.pk]},
        )
        self.assertRedirects(resp, reverse("grid_inep"))


# class MipLoteEmailBotaoListaTests(TestCase):
    # """Botão "Enviar e-mail" na tela "Projeto > MIP (LOTE)"
    # (`mip_lote_inep.html`)."""

    # def setUp(self):
        # self.usuario = User.objects.create_user(username="analista-email-lote-botao", password="senha-teste-123")
        # self.visualizador = User.objects.create_user(
            # username="visualizador-email-lote-botao", password="senha-teste-123", perfil=User.PERFIL_VISUALIZADOR,
        # )
        # self.escola = Escola.objects.create(
            # inep="10000080", nome="Escola Email Lote Botao", status_mip=Escola.AGUARDANDO_ENCERRAMENTO_LOTE,
        # )
        # self.lote = Lote.objects.create(
            # estado="GO", municipio="Abadiânia",
            # data_inicio=datetime.date(2026, 9, 1), data_fim=datetime.date(2026, 9, 30),
        # )
        # self.lote.escolas.add(self.escola)

    # def test_botao_aparece_para_quem_nao_e_visualizador(self):
        # self.client.force_login(self.usuario)
        # resp = self.client.get(reverse("mip_lote_inep"))
        # self.assertContains(resp, "Enviar e-mail")
        # self.assertContains(resp, reverse("mip_lote_enviar_email", kwargs={"pk": self.lote.pk}))

    # def test_visualizador_nem_chega_a_ver_o_botao(self):
        # """Pedido do usuário (2026-09-14, revisão): Visualizador não
        # acessa "Projeto > MIP (LOTE)" de jeito nenhum — o middleware
        # redireciona antes da página (e o botão) renderizar."""
        # self.client.force_login(self.visualizador)
        # resp = self.client.get(reverse("mip_lote_inep"))
        # self.assertRedirects(resp, reverse("grid_inep"))

    # def test_indicador_de_envio_aparece_depois_de_enviar(self):
        # self.client.force_login(self.usuario)
        # resp = self.client.get(reverse("mip_lote_inep"))
        # self.assertNotContains(resp, "Enviado em")

        # enviar_email_lote(
            # self.lote, para=[], assunto="Teste", mensagem="Corpo",
            # anexo_extra=None, usuario=self.usuario,
        # )
        # resp = self.client.get(reverse("mip_lote_inep"))
        # self.assertContains(resp, "Enviado em")


# ---------------------------------------------------------------------------
# FEAT-046 (a formalizar pelo Orquestrador em business_rules.md; pedido do
# usuário, 2026-09-14) — pedido do usuário (2026-09-15): Status do LOTE —
# campo de troca manual disponível direto a partir de "Aguardando
# Encerramento LOTE" (envio de e-mail comentado, deixou de ser pré-requisito)
# entre "Em Andamento" (vai para o RI), "Em Faturamento" (novo status
# intermediário) e "Processo Concluído" (encerra, fim do processo).
# ---------------------------------------------------------------------------


class MipLoteStatusUpdateViewTests(TestCase):
    """`mip_lote_status_update_view` — troca o Status do LOTE entre "Em
    Andamento", "Em Faturamento" e "Processo Concluído", aplicando a
    mudança a todos os INEPs do LOTE de uma vez."""

    def setUp(self):
        self.usuario = User.objects.create_user(username="analista-status-lote", password="senha-teste-123")
        self.admin = User.objects.create_user(
            username="admin-status-lote", password="senha-teste-123", perfil=User.PERFIL_ADMINISTRADOR,
        )
        self.visualizador = User.objects.create_user(
            username="visualizador-status-lote", password="senha-teste-123", perfil=User.PERFIL_VISUALIZADOR,
        )
        self.escola1 = Escola.objects.create(inep="10000090", nome="Escola Status Lote 1")
        self.escola2 = Escola.objects.create(inep="10000091", nome="Escola Status Lote 2")
        # `Ri.save()` sincroniza `Escola.status_mip` sempre que o RI está
        # "Aguardando validação EACE"/"Faturamento Concluído" (RN-092) —
        # por isso o `status_mip` de "Aguardando Encerramento LOTE" só é
        # atribuído DEPOIS de criar o RI, senão o save() do RI sobrescreve.
        self.ri1 = Ri.objects.create(escola=self.escola1, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        self.ri2 = Ri.objects.create(escola=self.escola2, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        self.escola1.status_mip = Escola.AGUARDANDO_ENCERRAMENTO_LOTE
        self.escola1.save(update_fields=["status_mip"])
        self.escola2.status_mip = Escola.AGUARDANDO_ENCERRAMENTO_LOTE
        self.escola2.save(update_fields=["status_mip"])
        self.lote = Lote.objects.create(
            estado="GO", municipio="Abadiânia",
            data_inicio=datetime.date(2026, 9, 1), data_fim=datetime.date(2026, 9, 30),
            status=Lote.AGUARDANDO_ENCERRAMENTO,
        )
        self.lote.escolas.set([self.escola1, self.escola2])

    def test_exige_login(self):
        resp = self.client.post(
            reverse("mip_lote_status_update", kwargs={"pk": self.lote.pk}), {"status": Lote.FATURAMENTO_CONCLUIDO},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp.url)

    def test_get_nao_altera_nada(self):
        self.client.force_login(self.usuario)
        resp = self.client.get(reverse("mip_lote_status_update", kwargs={"pk": self.lote.pk}))
        self.assertRedirects(resp, reverse("mip_lote_inep"))
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.status, Lote.AGUARDANDO_ENCERRAMENTO)

    def test_status_invalido_nao_altera_nada(self):
        self.client.force_login(self.usuario)
        self.client.post(
            reverse("mip_lote_status_update", kwargs={"pk": self.lote.pk}), {"status": "valor-invalido"},
        )
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.status, Lote.AGUARDANDO_ENCERRAMENTO)

    def test_bloqueado_quando_ja_processo_concluido(self):
        self.lote.status = Lote.FATURAMENTO_CONCLUIDO
        self.lote.save()
        self.client.force_login(self.usuario)
        self.client.post(
            reverse("mip_lote_status_update", kwargs={"pk": self.lote.pk}),
            {"status": Lote.EM_ANDAMENTO},
        )
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.status, Lote.FATURAMENTO_CONCLUIDO)

    def test_disponivel_direto_de_aguardando_encerramento(self):
        """Pedido do usuário (2026-09-15): sem o envio de e-mail, o campo
        de status já funciona direto a partir de "Aguardando Encerramento
        LOTE" (não precisa mais de nenhum passo intermediário)."""
        self.client.force_login(self.usuario)
        resp = self.client.post(
            reverse("mip_lote_status_update", kwargs={"pk": self.lote.pk}),
            {"status": Lote.EM_FATURAMENTO},
        )
        self.assertRedirects(resp, reverse("mip_lote_inep"))
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.status, Lote.EM_FATURAMENTO)

    def test_em_faturamento_muda_lote_e_todos_os_ineps_com_historico(self):
        self.client.force_login(self.usuario)
        resp = self.client.post(
            reverse("mip_lote_status_update", kwargs={"pk": self.lote.pk}),
            {"status": Lote.EM_FATURAMENTO},
        )
        self.assertRedirects(resp, reverse("mip_lote_inep"))
        self.lote.refresh_from_db()
        self.escola1.refresh_from_db()
        self.escola2.refresh_from_db()
        self.assertEqual(self.lote.status, Lote.EM_FATURAMENTO)
        self.assertEqual(self.escola1.status_mip, Escola.EM_FATURAMENTO_LOTE)
        self.assertEqual(self.escola2.status_mip, Escola.EM_FATURAMENTO_LOTE)
        for ri in (self.ri1, self.ri2):
            entrada = ri.historico.get(tipo=RiHistorico.LOG_CAMPO, campo="Status (MIP)")
            self.assertEqual(entrada.valor_novo, "Em Faturamento")
        # "Em Faturamento" nunca mexe no Ri.status (mesmo critério do
        # Status (MIP) individual, RN-092).
        self.ri1.refresh_from_db()
        self.assertEqual(self.ri1.status, Ri.AGUARDANDO_VALIDACAO_EACE)

    def test_processo_concluido_muda_lote_e_todos_os_ineps_com_historico(self):
        self.client.force_login(self.usuario)
        resp = self.client.post(
            reverse("mip_lote_status_update", kwargs={"pk": self.lote.pk}),
            {"status": Lote.FATURAMENTO_CONCLUIDO},
        )
        self.assertRedirects(resp, reverse("mip_lote_inep"))
        self.lote.refresh_from_db()
        self.escola1.refresh_from_db()
        self.escola2.refresh_from_db()
        self.assertEqual(self.lote.status, Lote.FATURAMENTO_CONCLUIDO)
        self.assertEqual(self.escola1.status_mip, Escola.FATURAMENTO_CONCLUIDO)
        self.assertEqual(self.escola2.status_mip, Escola.FATURAMENTO_CONCLUIDO)
        for ri in (self.ri1, self.ri2):
            entrada = ri.historico.get(tipo=RiHistorico.LOG_CAMPO, campo="Status (MIP)")
            self.assertEqual(entrada.valor_novo, "Processo Concluído")
        # "Processo Concluído" nunca mexe no Ri.status (mesmo critério do
        # Status (MIP) individual, RN-092).
        self.ri1.refresh_from_db()
        self.assertEqual(self.ri1.status, Ri.AGUARDANDO_VALIDACAO_EACE)

    def test_em_andamento_reabre_o_ri_de_cada_inep(self):
        self.client.force_login(self.usuario)
        resp = self.client.post(
            reverse("mip_lote_status_update", kwargs={"pk": self.lote.pk}), {"status": Lote.EM_ANDAMENTO},
        )
        self.assertRedirects(resp, reverse("mip_lote_inep"))
        self.lote.refresh_from_db()
        self.escola1.refresh_from_db()
        self.escola2.refresh_from_db()
        self.ri1.refresh_from_db()
        self.ri2.refresh_from_db()
        self.assertEqual(self.lote.status, Lote.EM_ANDAMENTO)
        self.assertEqual(self.escola1.status_mip, Escola.EM_ANDAMENTO)
        self.assertEqual(self.escola2.status_mip, Escola.EM_ANDAMENTO)
        self.assertEqual(self.ri1.status, Ri.ANDAMENTO)
        self.assertEqual(self.ri2.status, Ri.ANDAMENTO)
        # Mesmo log automático de troca de status do RI (RN-008) — igual
        # ao Status (MIP) individual, `trocar_status_com_log` já grava.
        self.assertTrue(self.ri1.historico.filter(tipo=RiHistorico.LOG_STATUS, campo="Status do RI").exists())

    def test_em_andamento_tudo_ou_nada_quando_um_ri_bloqueia(self):
        """RN-020: RI em "Faturamento Concluído" só muda com Administrador
        — se 1 INEP do LOTE estiver bloqueado, NENHUM dos dois é alterado
        (mesmo critério de `criar_lote_mip`)."""
        self.ri2.status = Ri.FATURAMENTO_CONCLUIDO
        # `Ri.save()` já sincroniza `escola2.status_mip` pra
        # "faturamento_concluido" aqui mesmo, de propósito (RN-092,
        # comportamento existente, não é o que este teste está checando)
        # — só pra montar o cenário de bloqueio do RN-020.
        self.ri2.save()
        self.client.force_login(self.usuario)
        self.client.post(
            reverse("mip_lote_status_update", kwargs={"pk": self.lote.pk}), {"status": Lote.EM_ANDAMENTO},
        )
        self.lote.refresh_from_db()
        self.escola1.refresh_from_db()
        self.ri1.refresh_from_db()
        # O que este teste confere de verdade: nada avançou por causa do
        # bloqueio — nem o LOTE, nem o INEP que NÃO estava bloqueado.
        self.assertEqual(self.lote.status, Lote.AGUARDANDO_ENCERRAMENTO)
        self.assertEqual(self.escola1.status_mip, Escola.AGUARDANDO_ENCERRAMENTO_LOTE)
        self.assertEqual(self.ri1.status, Ri.AGUARDANDO_VALIDACAO_EACE)

    def test_em_andamento_administrador_consegue_com_ri_faturamento_concluido(self):
        self.ri2.status = Ri.FATURAMENTO_CONCLUIDO
        self.ri2.save()
        self.client.force_login(self.admin)
        self.client.post(
            reverse("mip_lote_status_update", kwargs={"pk": self.lote.pk}), {"status": Lote.EM_ANDAMENTO},
        )
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.status, Lote.EM_ANDAMENTO)

    def test_visualizador_nao_consegue_alterar(self):
        self.client.force_login(self.visualizador)
        self.client.post(
            reverse("mip_lote_status_update", kwargs={"pk": self.lote.pk}),
            {"status": Lote.FATURAMENTO_CONCLUIDO},
        )
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.status, Lote.AGUARDANDO_ENCERRAMENTO)


# ---------------------------------------------------------------------------
# FEAT-049 (a formalizar pelo Orquestrador em business_rules.md; pedido do
# usuário, 2026-09-14): "Desfazer LOTE" — os INEPs voltam para "Aguardando
# Validação EACE" e o LOTE deixa de existir; histórico de cada INEP registra
# a troca e quem desfez.
# ---------------------------------------------------------------------------


class DesfazerLoteMipServiceTests(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user(username="analista-desfazer-lote", password="senha-teste-123")
        self.escola1 = Escola.objects.create(inep="10000092", nome="Escola Desfazer Lote 1")
        self.escola2 = Escola.objects.create(inep="10000093", nome="Escola Desfazer Lote 2")
        # Mesmo cuidado de `MipLoteStatusUpdateViewTests.setUp` — `Ri.save()`
        # sincroniza `Escola.status_mip` pra "aguardando_validacao_eace"
        # (RN-092), então o valor de "dentro do LOTE" só é atribuído DEPOIS.
        self.ri1 = Ri.objects.create(escola=self.escola1, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        self.ri2 = Ri.objects.create(escola=self.escola2, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        self.escola1.status_mip = Escola.AGUARDANDO_ENCERRAMENTO_LOTE
        self.escola1.save(update_fields=["status_mip"])
        self.escola2.status_mip = Escola.AGUARDANDO_ENCERRAMENTO_LOTE
        self.escola2.save(update_fields=["status_mip"])
        self.lote = Lote.objects.create(
            estado="GO", municipio="Abadiânia",
            data_inicio=datetime.date(2026, 9, 1), data_fim=datetime.date(2026, 9, 30),
        )
        self.lote.escolas.set([self.escola1, self.escola2])

    def test_volta_status_mip_de_cada_inep_para_aguardando_validacao_eace(self):
        desfazer_lote_mip(self.lote, self.usuario)
        self.escola1.refresh_from_db()
        self.escola2.refresh_from_db()
        self.assertEqual(self.escola1.status_mip, Escola.AGUARDANDO_VALIDACAO_EACE)
        self.assertEqual(self.escola2.status_mip, Escola.AGUARDANDO_VALIDACAO_EACE)

    def test_exclui_o_lote(self):
        lote_pk = self.lote.pk
        desfazer_lote_mip(self.lote, self.usuario)
        self.assertFalse(Lote.objects.filter(pk=lote_pk).exists())

    def test_grava_historico_com_status_lote_e_autor(self):
        identificacao_lote = str(self.lote)
        desfazer_lote_mip(self.lote, self.usuario)

        for ri in (self.ri1, self.ri2):
            entrada_status = ri.historico.get(tipo=RiHistorico.LOG_CAMPO, campo="Status (MIP)")
            self.assertEqual(entrada_status.valor_novo, "Aguardando Validação EACE")
            self.assertEqual(entrada_status.autor, self.usuario)

            entrada_lote = ri.historico.get(tipo=RiHistorico.LOG_CAMPO, campo="LOTE")
            self.assertEqual(entrada_lote.valor_anterior, identificacao_lote)
            self.assertEqual(entrada_lote.valor_novo, "Desfeito")
            self.assertEqual(entrada_lote.autor, self.usuario)

    def test_bloqueado_a_partir_de_em_andamento(self):
        self.lote.status = Lote.EM_ANDAMENTO
        self.lote.save()
        with self.assertRaises(LoteMipError):
            desfazer_lote_mip(self.lote, self.usuario)
        self.escola1.refresh_from_db()
        self.assertEqual(self.escola1.status_mip, Escola.AGUARDANDO_ENCERRAMENTO_LOTE)
        self.assertTrue(Lote.objects.filter(pk=self.lote.pk).exists())

    def test_bloqueado_a_partir_de_faturamento_concluido(self):
        self.lote.status = Lote.FATURAMENTO_CONCLUIDO
        self.lote.save()
        with self.assertRaises(LoteMipError):
            desfazer_lote_mip(self.lote, self.usuario)

    def test_bloqueado_a_partir_de_em_faturamento(self):
        self.lote.status = Lote.EM_FATURAMENTO
        self.lote.save()
        with self.assertRaises(LoteMipError):
            desfazer_lote_mip(self.lote, self.usuario)

    def test_bloqueado_com_email_ja_enviado(self):
        """Pedido do usuário (2026-09-15): com o envio de e-mail do LOTE
        comentado, `EMAIL_ENVIADO` deixou de ser um status alcançável por
        um LOTE novo — um LOTE antigo com esse valor (dado histórico)
        passa a ser tratado como "já avançou", igual a qualquer outro
        status fora de `AGUARDANDO_ENCERRAMENTO`."""
        self.lote.status = Lote.EMAIL_ENVIADO
        self.lote.save()
        with self.assertRaises(LoteMipError):
            desfazer_lote_mip(self.lote, self.usuario)
        self.assertTrue(Lote.objects.filter(pk=self.lote.pk).exists())


class MipLoteDesfazerViewTests(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user(username="analista-desfazer-lote-view", password="senha-teste-123")
        self.visualizador = User.objects.create_user(
            username="visualizador-desfazer-lote", password="senha-teste-123", perfil=User.PERFIL_VISUALIZADOR,
        )
        self.escola = Escola.objects.create(inep="10000094", nome="Escola Desfazer Lote View")
        self.ri = Ri.objects.create(escola=self.escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        self.escola.status_mip = Escola.AGUARDANDO_ENCERRAMENTO_LOTE
        self.escola.save(update_fields=["status_mip"])
        self.lote = Lote.objects.create(
            estado="GO", municipio="Abadiânia",
            data_inicio=datetime.date(2026, 9, 1), data_fim=datetime.date(2026, 9, 30),
        )
        self.lote.escolas.set([self.escola])

    def test_exige_login(self):
        resp = self.client.post(reverse("mip_lote_desfazer", kwargs={"pk": self.lote.pk}))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp.url)

    def test_get_nao_altera_nada(self):
        self.client.force_login(self.usuario)
        resp = self.client.get(reverse("mip_lote_desfazer", kwargs={"pk": self.lote.pk}))
        self.assertRedirects(resp, reverse("mip_lote_inep"))
        self.assertTrue(Lote.objects.filter(pk=self.lote.pk).exists())

    def test_post_desfaz_o_lote(self):
        self.client.force_login(self.usuario)
        resp = self.client.post(
            reverse("mip_lote_desfazer", kwargs={"pk": self.lote.pk}), {"next": ""},
        )
        self.assertRedirects(resp, reverse("mip_lote_inep"))
        self.assertFalse(Lote.objects.filter(pk=self.lote.pk).exists())
        self.escola.refresh_from_db()
        self.assertEqual(self.escola.status_mip, Escola.AGUARDANDO_VALIDACAO_EACE)

    def test_bloqueado_a_partir_de_em_andamento_mostra_mensagem(self):
        self.lote.status = Lote.EM_ANDAMENTO
        self.lote.save()
        self.client.force_login(self.usuario)
        resp = self.client.post(
            reverse("mip_lote_desfazer", kwargs={"pk": self.lote.pk}), {"next": ""}, follow=True,
        )
        self.assertTrue(Lote.objects.filter(pk=self.lote.pk).exists())
        mensagens = [str(m) for m in resp.context["messages"]]
        self.assertTrue(any("Não é possível desfazer" in m for m in mensagens))

    def test_visualizador_nao_consegue_desfazer(self):
        self.client.force_login(self.visualizador)
        self.client.post(reverse("mip_lote_desfazer", kwargs={"pk": self.lote.pk}), {"next": ""})
        self.assertTrue(Lote.objects.filter(pk=self.lote.pk).exists())


class MipLoteStatusColunaListaTests(TestCase):
    """Coluna "Status" e o `<select>` de troca (Em Andamento/Em
    Faturamento/Processo Concluído) na tela "Projeto > MIP (LOTE)".

    Pedido do usuário (2026-09-15): com o envio de e-mail comentado, o
    `<select>` de troca de status fica disponível direto a partir de
    "Aguardando Encerramento LOTE" (não precisa mais do e-mail enviado) e
    só some quando o LOTE já chegou em "Processo Concluído" (fim do
    processo); o botão "Enviar e-mail" nunca mais aparece."""

    def setUp(self):
        self.usuario = User.objects.create_user(username="analista-status-lote-coluna", password="senha-teste-123")
        self.escola = Escola.objects.create(
            inep="10000095", nome="Escola Status Coluna", status_mip=Escola.AGUARDANDO_ENCERRAMENTO_LOTE,
        )
        self.lote = Lote.objects.create(
            estado="GO", municipio="Abadiânia",
            data_inicio=datetime.date(2026, 9, 1), data_fim=datetime.date(2026, 9, 30),
        )
        self.lote.escolas.add(self.escola)

    def test_botao_de_enviar_email_nunca_aparece(self):
        """`core/base.html` tem um comentário de JS genérico mencionando
        "Enviar e-mail" (reaproveitado pelo modal de e-mail do RI, que
        continua ativo) — por isso a checagem aqui é pelo atributo
        específico do botão do LOTE (`data-abrir-modal-email="modal-email-
        lote-`), não pelo texto solto."""
        self.client.force_login(self.usuario)
        resp = self.client.get(reverse("mip_lote_inep"))
        self.assertNotContains(resp, 'data-abrir-modal-email="modal-email-lote-')

    def test_status_inicial_ja_mostra_select_de_troca(self):
        self.client.force_login(self.usuario)
        resp = self.client.get(reverse("mip_lote_inep"))
        self.assertContains(resp, "Aguardando Encerramento LOTE")
        self.assertContains(resp, "Mudar status...")
        self.assertContains(resp, reverse("mip_lote_status_update", kwargs={"pk": self.lote.pk}))
        self.assertContains(resp, '<option value="em_andamento">Em Andamento</option>')
        self.assertContains(resp, '<option value="em_faturamento">Em Faturamento</option>')
        self.assertContains(resp, '<option value="faturamento_concluido">Processo Concluído</option>')

    def test_status_em_andamento_continua_mostrando_select(self):
        self.lote.status = Lote.EM_ANDAMENTO
        self.lote.save()
        self.client.force_login(self.usuario)
        resp = self.client.get(reverse("mip_lote_inep"))
        self.assertContains(resp, "Em Andamento")
        self.assertContains(resp, "Mudar status...")

    def test_status_em_faturamento_continua_mostrando_select(self):
        self.lote.status = Lote.EM_FATURAMENTO
        self.lote.save()
        self.client.force_login(self.usuario)
        resp = self.client.get(reverse("mip_lote_inep"))
        self.assertContains(resp, "Em Faturamento")
        self.assertContains(resp, "Mudar status...")

    def test_processo_concluido_esconde_select(self):
        self.lote.status = Lote.FATURAMENTO_CONCLUIDO
        self.lote.save()
        self.client.force_login(self.usuario)
        resp = self.client.get(reverse("mip_lote_inep"))
        self.assertContains(resp, "Processo Concluído")
        self.assertNotContains(resp, "Mudar status...")
