import datetime
import io
import shutil
import tempfile
from decimal import Decimal
from pathlib import Path

import openpyxl
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.escolas.models import Escola, EscolaItemRelatorioEaceMip, PlanilhaRelatorioEaceMip
from apps.escolas.services import (
    PlanilhaFaturamentoImplantacaoError,
    gerar_planilha_faturamento_implantacao,
)
from apps.ri.models import Documento, KitPadrao, Ri, RiHistorico, RiItemEace, RiItemIxc

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
    """Projeto > MIP: visão dos INEPs cujo RI atual está em "Aguardando
    validação EACE" (RN-074, a criar) — deixou de listar todos os INEPs
    cadastrados (RN-066), a pedido do usuário."""

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
        """RN-074 (a criar): só entra na lista quem está em "Aguardando
        validação EACE" — qualquer outro status do RI atual fica de fora."""
        escola_em_andamento = Escola.objects.create(inep="10000003", nome="Escola Em Andamento")
        Ri.objects.create(escola=escola_em_andamento, status=Ri.ANDAMENTO)
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertContains(resp, self.escola.inep)
        self.assertNotContains(resp, escola_em_andamento.inep)

    def test_sem_ri_nao_aparece(self):
        """RN-074 (a criar): sem RI ainda não há status pra comparar — o
        INEP não aparece na lista (mas continua acessível direto por
        `mip_detail`, que não tem esse filtro)."""
        escola_sem_ri = Escola.objects.create(inep="10000004", nome="Escola Sem RI")
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertNotContains(resp, escola_sem_ri.inep)

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
    """RN-081 (a criar): bolinha verde/vermelha no grid do MIP, sobre o
    resultado da última sincronização do Relatório EACE (MIP)
    (`Escola.encontrado_relatorio_eace_mip`) — verde quando encontrado e
    normal do grid (Validação EACE); vermelho quando não encontrado
    (mas ainda em Validação EACE) OU encontrado mas fora da Validação
    EACE (lista à parte); sem bolinha quando nunca sincronizou."""

    def setUp(self):
        self.user = User.objects.create_user(username="analista-status-planilha", password="senha-teste-123")

    def test_encontrado_e_validacao_eace_mostra_bolinha_verde(self):
        escola = Escola.objects.create(
            inep="10000060", nome="Escola Verde", lote=9, encontrado_relatorio_eace_mip=True,
        )
        Ri.objects.create(escola=escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        linha = resp.context["page_obj"][0]
        self.assertEqual(linha["status_planilha_mip"], "verde")
        self.assertContains(resp, "bg-emerald-500")

    def test_nao_encontrado_e_validacao_eace_mostra_bolinha_vermelha(self):
        escola = Escola.objects.create(
            inep="10000061", nome="Escola Vermelha", lote=9, encontrado_relatorio_eace_mip=False,
        )
        Ri.objects.create(escola=escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        linha = resp.context["page_obj"][0]
        self.assertEqual(linha["status_planilha_mip"], "vermelho")

    def test_nunca_sincronizado_nao_mostra_bolinha(self):
        """Sem bolinha no dict de contexto — a legenda no topo da tela
        sempre mostra as duas cores como referência, então a ausência é
        conferida pelo dado (`status_planilha_mip`), não pela presença
        das classes CSS na página inteira."""
        escola = Escola.objects.create(inep="10000062", nome="Escola Sem Sync", lote=9)
        Ri.objects.create(escola=escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        linha = resp.context["page_obj"][0]
        self.assertIsNone(linha["status_planilha_mip"])

    def test_encontrado_fora_da_validacao_eace_aparece_na_lista_a_parte(self):
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

    def test_nao_encontrado_e_fora_da_validacao_eace_nao_aparece_em_lugar_nenhum(self):
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
    do MIP — Estado só lista as UFs que já têm INEP na base (Validação
    EACE); Município só é filtrável depois de um Estado escolhido."""

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
        self.escola_rj_sem_ri = Escola.objects.create(
            inep="10000043", nome="Escola RJ Sem RI", estado="RJ", municipio="Niterói",
        )
        for escola in (self.escola_ce_fortaleza, self.escola_ce_sobral, self.escola_sp):
            Ri.objects.create(escola=escola, status=Ri.AGUARDANDO_VALIDACAO_EACE)
        # RJ fica de fora da base porque não tem RI em Validação EACE
        # (RN-074) — por isso não deve aparecer nem como opção de Estado.

    def test_select_estado_so_lista_uf_com_inep_na_base(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mip_inep"))
        self.assertEqual(sorted(resp.context["estados_disponiveis"]), ["CE", "SP"])
        self.assertContains(resp, '<option value="CE"')
        self.assertContains(resp, '<option value="SP"')
        self.assertNotContains(resp, '<option value="RJ"')

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
        workbook = gerar_planilha_faturamento_implantacao("GO", "Abadiânia", self.data_envio)
        aba = workbook.worksheets[0]
        self.assertIn("MUNICIPIO/UF: Abadiânia/GO", aba["F10"].value)
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
