import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.escolas.models import Escola
from apps.ri.models import KitPadrao, Ri, RiItemRelatorioEace

from .email_tracking import (
    extrair_codigos_rastreio,
    montar_assunto_com_codigo,
    montar_codigo_rastreio,
)

User = get_user_model()


def _sem_href(linhas):
    """Tira `href`/`selecionado` (adicionados pela view, ampliação
    2026-08-28 — clique numa linha filtra a página) das linhas de
    `kits_por_produto`/`produtos_complementares`, para comparar só o dado
    calculado pelo service nos testes que não testam o clique em si."""
    return [{k: v for k, v in linha.items() if k not in ("href", "selecionado")} for linha in linhas]


class EmailTrackingTests(TestCase):
    """RN-009: código de rastreio do e-mail do RI (FEAT-008/FEAT-009)."""

    def test_montar_codigo_rastreio_formato(self):
        codigo = montar_codigo_rastreio("35296909", datetime.date(2026, 8, 23))
        self.assertEqual(codigo, "RI-20260823-35296909")

    def test_montar_assunto_com_codigo(self):
        assunto = montar_assunto_com_codigo("RI-20260823-35296909", "Faturamento EACE")
        self.assertEqual(assunto, "#RI-20260823-35296909 - Faturamento EACE")

    def test_extrair_codigos_rastreio_encontra_no_assunto(self):
        codigos = extrair_codigos_rastreio(
            "RE: #RI-20260823-35296909 - Faturamento EACE — INEP 35296909"
        )
        self.assertEqual(codigos, ["RI-20260823-35296909"])

    def test_extrair_codigos_rastreio_sem_codigo_retorna_vazio(self):
        """RN-009: sem código identificável não bloqueia (mesma exceção da RN-005) — a
        view/leitura decide o que fazer com a lista vazia, esta função só não inventa."""
        self.assertEqual(extrair_codigos_rastreio("Assunto qualquer sem código"), [])

    def test_extrair_codigos_rastreio_varios_no_mesmo_texto(self):
        codigos = extrair_codigos_rastreio(
            "RI-20260823-35296909 e também RI-20260824-10000002"
        )
        self.assertEqual(codigos, ["RI-20260823-35296909", "RI-20260824-10000002"])


class HomeViewTests(TestCase):
    """FEAT-026 (RN-025/RN-026): dashboard financeiro na tela inicial."""

    def setUp(self):
        self.user = User.objects.create_user(username="analista", password="senha-teste-123")

    def test_exige_login(self):
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp.url)

    def test_dashboard_mostra_os_2_cards_com_os_valores_calculados(self):
        KitPadrao.objects.create(
            descricao="Kit Wi-Fi Indoor", lote=9, unidade="Escola",
            valor_equipamento="1000.00", valor_servico="500.00",
        )
        Escola.objects.create(inep="10000001", nome="Escola A", kit_inicial="Kit Wi-Fi Indoor", lote=9,
                               nobreak_inicial="")
        escola_ri = Escola.objects.create(inep="10000002", nome="Escola B", nobreak_inicial="", lote=9)
        ri = Ri.objects.create(escola=escola_ri, status=Ri.FATURAMENTO_CONCLUIDO)
        RiItemRelatorioEace.objects.create(
            ri=ri, descricao_item="Kit Wi-Fi Indoor", quantidade=1, valor_unitario="600.00",
        )

        self.client.force_login(self.user)
        resp = self.client.get(reverse("home"))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Valor Total do Projeto")
        self.assertContains(resp, "Valor já Faturado")
        # Pedido do usuário (2026-08-27): separador de milhar e vírgula decimal (pt-BR).
        self.assertContains(resp, "1.500,00")
        self.assertContains(resp, "600,00")
        # RN-026: a barra proporcional é CSS (`style="height: ...%"`) — precisa
        # de ponto decimal, nunca vírgula (que o navegador não entende).
        self.assertContains(resp, "height: 40.00%")
        self.assertContains(resp, "height: 60.00%")
        # Pedido do usuário (2026-08-27): % já entregue, no canto do card 2 e do
        # gráfico (+ a ocorrência já existente no aria-label da barra do card 2).
        self.assertContains(resp, "40%", count=3)
        self.assertEqual(resp.context["valor_total_projeto"], Decimal("1500.00"))
        self.assertEqual(resp.context["valor_faturado"], Decimal("600.00"))
        self.assertFalse(resp.context["meta_atingida"])

    def test_badge_mostra_mais_de_100_quando_ultrapassa_a_meta(self):
        """Correção (2026-08-27, pedido do usuário): faturado acima da
        meta mostra "200%" no badge, não trava em "100%"."""
        KitPadrao.objects.create(
            descricao="Kit Wi-Fi Indoor", lote=9, unidade="Escola",
            valor_equipamento="1000.00", valor_servico="500.00",
        )
        escola_ri = Escola.objects.create(
            inep="10000003", nome="Escola C", kit_inicial="Kit Wi-Fi Indoor", nobreak_inicial="", lote=9,
        )
        ri = Ri.objects.create(escola=escola_ri, status=Ri.FATURAMENTO_CONCLUIDO)
        RiItemRelatorioEace.objects.create(
            ri=ri, descricao_item="Kit Wi-Fi Indoor", quantidade=1, valor_unitario="3000.00",
        )

        self.client.force_login(self.user)
        resp = self.client.get(reverse("home"))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "200%", count=3)  # badge do card 2 + badge do gráfico + aria-label
        self.assertContains(resp, "height: 100.00%")  # barra do card 2 capada, mesmo passando de 100%


class HomeFiltroPorKitEProdutoTests(TestCase):
    """FEAT-026 (ampliação, 2026-08-28, pedido do usuário): "o financeiro
    tem que trazer os valores referente aquele filtro" — navegação cruzada
    vinda de Equipamentos ("Ver Faturamento de UF") passa a carregar
    também `?kit=`/`?produto=`, e o Faturamento mostra o valor daquele
    filtro específico, não o valor geral do estado."""

    def setUp(self):
        self.user = User.objects.create_user(username="analista", password="senha-teste-123")
        self.client.force_login(self.user)
        KitPadrao.objects.create(
            descricao="Kit Wi-Fi Indoor", lote=9, unidade="Escola",
            valor_equipamento="1000.00", valor_servico="500.00",
        )
        self.escola = Escola.objects.create(
            inep="70000001", nome="Escola A", kit_inicial="Kit Wi-Fi Indoor", lote=9,
            estado="SP", nobreak_inicial="",
        )
        self.ri = Ri.objects.create(escola=self.escola, status=Ri.FATURAMENTO_CONCLUIDO)
        RiItemRelatorioEace.objects.create(
            ri=self.ri, descricao_item="Kit Wi-Fi Indoor", quantidade=1,
            valor_unitario="600.00", eh_kit=True,
        )
        RiItemRelatorioEace.objects.create(
            ri=self.ri, descricao_item="Rack 7U", quantidade=2,
            valor_unitario="100.00", eh_kit=False,
        )

    def test_filtro_por_kit_restringe_os_2_cards_ao_kit(self):
        resp = self.client.get(reverse("home"), {"kit": "Kit Wi-Fi Indoor"})

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["tem_meta"])
        self.assertEqual(resp.context["kit_filtrado"], "Kit Wi-Fi Indoor")
        # Meta é só do Kit (1.500,00) — Nobreak não entra ao filtrar 1 Kit específico.
        self.assertEqual(resp.context["valor_total_projeto"], Decimal("1500.00"))
        # Faturado é só o item do Kit (600,00) — o Rack 7U (200,00) fica de fora.
        self.assertEqual(resp.context["valor_faturado"], Decimal("600.00"))
        self.assertContains(resp, "Kit: Kit Wi-Fi Indoor")
        self.assertContains(resp, "Ver Faturamento geral")

    def test_filtro_por_produto_mostra_so_o_valor_faturado_sem_meta(self):
        resp = self.client.get(reverse("home"), {"produto": "Rack 7U"})

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context["tem_meta"])
        self.assertEqual(resp.context["produto_filtrado"], "Rack 7U")
        self.assertEqual(resp.context["valor_total_projeto"], Decimal("0.00"))
        # 2 unidades x R$ 100,00 = 200,00 — só o Rack 7U, o Kit fica de fora.
        self.assertEqual(resp.context["valor_faturado"], Decimal("200.00"))
        self.assertNotContains(resp, "Valor Total do Projeto")
        self.assertContains(resp, "Equipamento: Rack 7U")
        self.assertContains(resp, "nunca programado antes do projeto")

    def test_grafico_faturado_por_estado_some_com_kit_ou_produto_filtrado(self):
        resp = self.client.get(reverse("home"), {"kit": "Kit Wi-Fi Indoor"})
        self.assertNotContains(resp, "Faturado por Estado")
        self.assertEqual(resp.context["faturamento_por_estado"], [])

    def test_ver_faturamento_geral_preserva_estado(self):
        resp = self.client.get(reverse("home"), {"kit": "Kit Wi-Fi Indoor", "estado": "SP"})
        resp2 = self.client.get(reverse("home") + resp.context["limpar_kit_produto_href"])

        self.assertIsNone(resp2.context["kit_filtrado"])
        self.assertEqual(resp2.context["estado_filtrado"], "SP")


class DashboardFaturadoPorEstadoTests(TestCase):
    """FEAT-026 ampliada (RN-027): gráfico "Faturado por Estado" e o
    filtro `?estado=UF` nos 2 cards de cima."""

    def setUp(self):
        self.user = User.objects.create_user(username="analista", password="senha-teste-123")
        KitPadrao.objects.create(
            descricao="Kit Wi-Fi Indoor", lote=9, unidade="Escola",
            valor_equipamento="1000.00", valor_servico="500.00",
        )
        self.escola_sp = Escola.objects.create(
            inep="30000001", nome="Escola SP", kit_inicial="Kit Wi-Fi Indoor", lote=9,
            estado="SP", municipio="Campinas", nobreak_inicial="",
        )
        self.escola_rj = Escola.objects.create(
            inep="30000002", nome="Escola RJ", kit_inicial="Kit Wi-Fi Indoor", lote=9,
            estado="RJ", nobreak_inicial="",
        )
        ri_sp = Ri.objects.create(escola=self.escola_sp, status=Ri.FATURAMENTO_CONCLUIDO)
        ri_rj = Ri.objects.create(escola=self.escola_rj, status=Ri.FATURAMENTO_CONCLUIDO)
        RiItemRelatorioEace.objects.create(
            ri=ri_sp, descricao_item="Kit Wi-Fi Indoor", quantidade=1, valor_unitario="700.00",
        )
        RiItemRelatorioEace.objects.create(
            ri=ri_rj, descricao_item="Kit Wi-Fi Indoor", quantidade=1, valor_unitario="300.00",
        )
        self.client.force_login(self.user)

    def test_dashboard_sem_filtro_mostra_o_grafico_dos_2_estados(self):
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Faturado por Estado")
        self.assertContains(resp, ">SP<")
        self.assertContains(resp, ">RJ<")
        # Pedido do usuário: valor faturado e, no final da linha, a meta do estado.
        self.assertContains(resp, "R$ 700,00 faturado")
        self.assertContains(resp, "Meta: R$ 1.500,00", count=2)  # SP e RJ têm a mesma meta (só Kit)
        self.assertEqual(resp.context["valor_total_projeto"], Decimal("3000.00"))
        self.assertEqual(resp.context["valor_faturado"], Decimal("1000.00"))
        self.assertIsNone(resp.context["estado_filtrado"])
        # Pedido do usuário: o gráfico só "expande" para Município com um
        # estado selecionado — sem filtro, essa seção nem aparece.
        self.assertNotContains(resp, "Faturado por Município ·")  # cabeçalho real; distingue do comentário HTML

    def test_clicar_no_estado_filtra_os_2_cards_e_expande_municipios(self):
        resp = self.client.get(reverse("home"), {"estado": "SP"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["estado_filtrado"], "SP")
        self.assertEqual(resp.context["valor_total_projeto"], Decimal("1500.00"))
        self.assertEqual(resp.context["valor_faturado"], Decimal("700.00"))
        self.assertContains(resp, "Filtrado por SP")
        self.assertContains(resp, "Ver todos os estados")
        # O gráfico expande mostrando os municípios de SP, mesma informação.
        self.assertContains(resp, "Faturado por Município · SP")
        self.assertContains(resp, ">Campinas<")
        self.assertContains(resp, "R$ 700,00 faturado")

    def test_estado_filtrado_mostra_link_cruzado_para_equipamentos(self):
        """Ampliação (2026-08-28, pedido do usuário): navegação cruzada
        entre Faturamento e Equipamentos, mantendo o mesmo estado
        filtrado — os 2 dashboards usam o mesmo parâmetro `?estado=UF`."""
        resp = self.client.get(reverse("home"), {"estado": "SP"})
        self.assertContains(resp, "Ver Equipamentos de SP")
        self.assertContains(resp, reverse("dashboard_equipamentos") + "?estado=SP")

    def test_sem_filtro_nao_mostra_link_cruzado(self):
        resp = self.client.get(reverse("home"))
        self.assertNotContains(resp, "Ver Equipamentos de")

    def test_clicar_no_municipio_filtra_os_2_cards_mais_1_nivel(self):
        resp = self.client.get(reverse("home"), {"estado": "SP", "municipio": "Campinas"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["estado_filtrado"], "SP")
        self.assertEqual(resp.context["municipio_filtrado"], "Campinas")
        self.assertEqual(resp.context["valor_total_projeto"], Decimal("1500.00"))
        self.assertEqual(resp.context["valor_faturado"], Decimal("700.00"))
        self.assertContains(resp, "Filtrado por SP · Campinas")
        self.assertContains(resp, "Ver todos os municípios")

    def test_municipio_sem_estado_na_url_e_ignorado(self):
        """Nome de município se repete entre UFs — sem o estado, o filtro
        não é aplicado (RN-027 ampliada)."""
        resp = self.client.get(reverse("home"), {"municipio": "Campinas"})
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context["estado_filtrado"])
        self.assertIsNone(resp.context["municipio_filtrado"])
        self.assertEqual(resp.context["valor_total_projeto"], Decimal("3000.00"))
        self.assertNotContains(resp, "Faturado por Município ·")  # cabeçalho real; distingue do comentário HTML

    def test_estado_invalido_na_url_nao_quebra_a_pagina(self):
        resp = self.client.get(reverse("home"), {"estado": "xx-invalido"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["valor_total_projeto"], Decimal("0"))


class DashboardSubmenusTests(TestCase):
    """FEAT-026: submenus "Equipamentos" e "Relatórios" do dashboard
    (pedido do usuário, 2026-08-27). Renderização básica — o card de
    "Equipamentos" ganhou critério próprio (`DashboardEquipamentosTests`
    abaixo); "Relatórios" segue placeholder."""

    def setUp(self):
        self.user = User.objects.create_user(username="analista", password="senha-teste-123")

    def test_equipamentos_exige_login(self):
        resp = self.client.get(reverse("dashboard_equipamentos"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp.url)

    def test_equipamentos_renderiza_para_usuario_logado(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("dashboard_equipamentos"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Equipamentos")

    def test_relatorios_exige_login(self):
        resp = self.client.get(reverse("dashboard_relatorios"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp.url)

    def test_relatorios_renderiza_para_usuario_logado(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("dashboard_relatorios"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Relatórios")


class DashboardEquipamentosTests(TestCase):
    """FEAT-026 (submenu "Equipamentos", pedido do usuário, 2026-08-28):
    cards "Kits Programados", "Kits Instalados" e "Nobreaks Programados",
    separados por serem unidades de natureza diferente (pedido do
    usuário) — Kit Declarado, Kit instalado (Lado Relatório EACE/3º lado)
    e Nobreak inicial (RN-017), mesma origem do card "Valor Total do
    Projeto" (RN-025). "Kits Programados" teve a definição revista 2
    vezes no mesmo dia: 1ª somava `RiItemEace` (1º lado) — só 9 registros
    pras 2.622 escolas do projeto real, sem uso prático (RN-010); 2ª
    somava os Access Points de cada Kit — usuário reportou, vendo o app
    real, que isso passava de 20 mil, quando deveria ser 1 por escola (no
    máximo 2.622). Versão final: 1 Kit por escola; Access Points aparecem
    só no detalhamento "Kits por Produto". "Kits Instalados" (ampliação do
    mesmo dia) também teve a fonte corrigida pelo usuário: 1ª versão usava
    `Escola.status_conexao` (RN-007); versão final usa o Kit lançado no
    Lado Relatório EACE (3º lado) de RI com status "Faturamento
    Concluído" — mesma fonte do card "Valor já Faturado" (RN-026)."""

    def setUp(self):
        self.user = User.objects.create_user(username="analista", password="senha-teste-123")
        self.client.force_login(self.user)

    def test_sem_nenhuma_escola_mostra_zero_e_mensagem_vazia(self):
        resp = self.client.get(reverse("dashboard_equipamentos"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Kits Programados")
        self.assertContains(resp, "Kits Instalados")
        self.assertContains(resp, "Nobreaks Programados")
        self.assertEqual(resp.context["total_kits_programados"], 0)
        self.assertEqual(resp.context["total_kits_instalados"], 0)
        self.assertEqual(resp.context["total_nobreaks_programados"], 0)
        self.assertContains(resp, "Nenhuma escola com Kit declarado")

    def test_kits_contam_1_por_escola_nao_os_access_points(self):
        """Correção (2026-08-28, reportada pelo usuário no app real): 2
        escolas com o mesmo Kit de 4 Access Points são 2 Kits Programados,
        não 8 — 1 Kit por escola, sempre."""
        KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 4 Access Points", lote=9, unidade="Escola",
            numero_access_points=4,
        )
        KitPadrao.objects.create(
            descricao="Nobreak (serviço, material, equipamento)", lote=9, unidade="Escola",
        )
        Escola.objects.create(inep="40000001", nome="Escola A", kit_inicial="4", lote=9)
        Escola.objects.create(inep="40000002", nome="Escola B", kit_inicial="4", lote=9)

        resp = self.client.get(reverse("dashboard_equipamentos"))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["total_kits_programados"], 2)
        self.assertEqual(resp.context["total_nobreaks_programados"], 2)

    def test_kits_instalados_conta_kit_do_lado_relatorio_eace_em_ri_concluido(self):
        """Correção (2026-08-28, reportada pelo usuário): "Kits
        Instalados" não é `Escola.status_conexao` (RN-007) — é o Kit
        lançado no Lado Relatório EACE (3º lado) de RI com status
        "Faturamento Concluído", mesma fonte do card "Valor já Faturado"
        (RN-026). RI concluído sem Kit no Lado 3, RI com Kit mas não
        concluído, e RI concluído com Kit no Lado IXC (2º lado, não no
        3º) não contam."""
        KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 4 Access Points", lote=9, unidade="Escola",
            numero_access_points=4,
        )
        escola_instalada = Escola.objects.create(inep="40000006", nome="Escola F", kit_inicial="4", lote=9)
        ri_instalado = Ri.objects.create(escola=escola_instalada, status=Ri.FATURAMENTO_CONCLUIDO)
        RiItemRelatorioEace.objects.create(
            ri=ri_instalado, descricao_item="Kit Cobertura Wi-Fi - 4 Access Points",
            quantidade=1, valor_unitario="0.00", eh_kit=True,
        )

        escola_nao_concluida = Escola.objects.create(inep="40000007", nome="Escola G", kit_inicial="4", lote=9)
        ri_nao_concluido = Ri.objects.create(escola=escola_nao_concluida, status=Ri.ANDAMENTO)
        RiItemRelatorioEace.objects.create(
            ri=ri_nao_concluido, descricao_item="Kit Cobertura Wi-Fi - 4 Access Points",
            quantidade=1, valor_unitario="0.00", eh_kit=True,
        )

        Escola.objects.create(inep="40000008", nome="Escola H", kit_inicial="4", lote=9)  # sem RI

        resp = self.client.get(reverse("dashboard_equipamentos"))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["total_kits_programados"], 3)
        self.assertEqual(resp.context["total_kits_instalados"], 1)

    def test_escola_sem_correspondencia_no_catalogo_contribui_com_zero(self):
        """RN-025 (mesma regra conservadora): sem catálogo compatível para
        o Lote/descrição, a escola não trava o dashboard nem inventa
        quantidade — só não soma nada por ela, nos 3 cards."""
        Escola.objects.create(inep="40000003", nome="Escola C", kit_inicial="Kit inexistente", lote=9)

        resp = self.client.get(reverse("dashboard_equipamentos"))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["total_kits_programados"], 0)
        self.assertEqual(resp.context["total_kits_instalados"], 0)
        self.assertEqual(resp.context["total_nobreaks_programados"], 0)

    def test_kits_por_produto_agrupa_pela_quantidade_de_escolas_por_tipo(self):
        """Correção (2026-08-28, reportada pelo usuário no app real): o
        detalhamento também não multiplica escola por tamanho de Kit — só
        conta escolas por tipo, igual ao card principal. Usuário apontou
        que "267 escolas x 15 Access Points = 4.005" não representa nada
        real no inventário dele."""
        KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 4 Access Points", lote=9, unidade="Escola",
            numero_access_points=4,
        )
        KitPadrao.objects.create(
            descricao="Nobreak (serviço, material, equipamento)", lote=9, unidade="Escola",
        )
        Escola.objects.create(inep="40000004", nome="Escola D", kit_inicial="4", lote=9)
        Escola.objects.create(inep="40000005", nome="Escola E", kit_inicial="4", lote=9)

        resp = self.client.get(reverse("dashboard_equipamentos"))

        kits_por_produto = _sem_href(resp.context["kits_por_produto"])
        self.assertEqual(
            kits_por_produto,
            [{"descricao_item": "Kit Cobertura Wi-Fi - 4 Access Points", "quantidade_total": 2, "instalados_total": 0}],
        )

    def test_kits_por_produto_traz_programados_e_instalados_lado_a_lado(self):
        """Ampliação (2026-08-28, pedido do usuário): ao filtrar por
        estado, o total do card "Kits Instalados" sozinho não dizia quais
        tipos de Kit formavam aquele número — "Kits por Produto" passa a
        trazer as 2 contagens por tipo, já dentro do recorte de estado."""
        KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 4 Access Points", lote=9, unidade="Escola",
            numero_access_points=4,
        )
        KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 8 Access Points", lote=9, unidade="Escola",
            numero_access_points=8,
        )
        escola_4_instalada = Escola.objects.create(
            inep="40000009", nome="Escola I", kit_inicial="4", lote=9, estado="SP",
        )
        ri_4 = Ri.objects.create(escola=escola_4_instalada, status=Ri.FATURAMENTO_CONCLUIDO)
        RiItemRelatorioEace.objects.create(
            ri=ri_4, descricao_item="Kit Cobertura Wi-Fi - 4 Access Points",
            quantidade=1, valor_unitario="0.00", eh_kit=True,
        )
        escola_8_nao_instalada = Escola.objects.create(
            inep="40000010", nome="Escola J", kit_inicial="8", lote=9, estado="SP",
        )
        Ri.objects.create(escola=escola_8_nao_instalada, status=Ri.ANDAMENTO)

        resp = self.client.get(reverse("dashboard_equipamentos"), {"estado": "SP"})

        kits_por_produto = _sem_href(resp.context["kits_por_produto"])
        self.assertEqual(
            kits_por_produto,
            [
                {"descricao_item": "Kit Cobertura Wi-Fi - 4 Access Points", "quantidade_total": 1, "instalados_total": 1},
                {"descricao_item": "Kit Cobertura Wi-Fi - 8 Access Points", "quantidade_total": 1, "instalados_total": 0},
            ],
        )
        # Pedido do usuário (2026-08-28): badge de % igual ao já usado no
        # card "Valor já Faturado" (RN-026) — 1 de 2 Kits instalados = 50%.
        self.assertEqual(resp.context["percentual_kits_instalados_pct"], 50)
        self.assertFalse(resp.context["kits_meta_atingida"])
        self.assertContains(resp, "50%")

    def test_badge_de_porcentagem_mostra_mais_de_100_quando_instalado_supera_programado(self):
        """Mesmo caso do badge do card "Valor já Faturado" (RN-026,
        correção 2026-08-27): sem teto no texto/badge quando Instalado
        supera Programado — cenário raro em que uma escola conta como
        instalada (Lado Relatório EACE) sem contar como programada (Kit
        sem correspondência no catálogo)."""
        KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 4 Access Points", lote=9, unidade="Escola",
            numero_access_points=4,
        )
        escola_programada = Escola.objects.create(inep="40000011", nome="Escola K", kit_inicial="4", lote=9)
        ri_1 = Ri.objects.create(escola=escola_programada, status=Ri.FATURAMENTO_CONCLUIDO)
        RiItemRelatorioEace.objects.create(
            ri=ri_1, descricao_item="Kit Cobertura Wi-Fi - 4 Access Points",
            quantidade=1, valor_unitario="0.00", eh_kit=True,
        )
        escola_sem_catalogo = Escola.objects.create(
            inep="40000012", nome="Escola L", kit_inicial="Kit inexistente", lote=9,
        )
        ri_2 = Ri.objects.create(escola=escola_sem_catalogo, status=Ri.FATURAMENTO_CONCLUIDO)
        RiItemRelatorioEace.objects.create(
            ri=ri_2, descricao_item="Kit Cobertura Wi-Fi - 4 Access Points",
            quantidade=1, valor_unitario="0.00", eh_kit=True,
        )

        resp = self.client.get(reverse("dashboard_equipamentos"))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["total_kits_programados"], 1)
        self.assertEqual(resp.context["total_kits_instalados"], 2)
        self.assertEqual(resp.context["percentual_kits_instalados_pct"], 200)
        self.assertTrue(resp.context["kits_meta_atingida"])
        self.assertContains(resp, "200%")

    def test_nobreak_aparece_a_parte_dentro_de_kits_por_produto_com_legenda(self):
        """Ampliação (2026-08-28, pedido do usuário): "Kits por Produto"
        ganha 1 linha à parte para o Nobreak, com "+" na frente do número e
        uma legenda explicando que não é um tipo de Kit — mesmo total do
        card "Nobreaks Programados", já dentro do recorte de estado."""
        KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 4 Access Points", lote=9, unidade="Escola",
            numero_access_points=4,
        )
        KitPadrao.objects.create(
            descricao="Nobreak (serviço, material, equipamento)", lote=9, unidade="Escola",
        )
        Escola.objects.create(inep="40000013", nome="Escola M", kit_inicial="4", lote=9, estado="SP")
        Escola.objects.create(inep="40000014", nome="Escola N", kit_inicial="4", lote=9, estado="RJ")

        resp_sem_filtro = self.client.get(reverse("dashboard_equipamentos"))
        self.assertEqual(resp_sem_filtro.context["total_nobreaks_programados"], 2)
        self.assertContains(resp_sem_filtro, "+ 2")
        self.assertContains(resp_sem_filtro, "não é um tipo de Kit")

        resp_sp = self.client.get(reverse("dashboard_equipamentos"), {"estado": "SP"})
        self.assertEqual(resp_sp.context["total_nobreaks_programados"], 1)
        self.assertContains(resp_sp, "+ 1")

    def test_produtos_complementares_agrupa_quantidade_e_escolas_por_tipo(self):
        """Ampliação (2026-08-28, pedido do usuário): "outros equipamentos
        além de Nobreak e Kit" — Produtos avulsos lançados no Lado
        Relatório EACE (3º lado, confirmado pelo usuário), nunca
        programados antes do projeto. Diferente do Kit, a Quantidade aqui
        é uma soma real (não embutida na Descrição) — 2 escolas com 2
        Racks cada somam 4, corretamente."""
        escola_a = Escola.objects.create(inep="40000015", nome="Escola O")
        ri_a = Ri.objects.create(escola=escola_a, status=Ri.FATURAMENTO_CONCLUIDO)
        RiItemRelatorioEace.objects.create(
            ri=ri_a, descricao_item="Rack 7U", quantidade=2, valor_unitario="0.00", eh_kit=False,
        )
        escola_b = Escola.objects.create(inep="40000016", nome="Escola P")
        ri_b = Ri.objects.create(escola=escola_b, status=Ri.FATURAMENTO_CONCLUIDO)
        RiItemRelatorioEace.objects.create(
            ri=ri_b, descricao_item="Rack 7U", quantidade=2, valor_unitario="0.00", eh_kit=False,
        )
        RiItemRelatorioEace.objects.create(
            ri=ri_b, descricao_item="Switch Gigabit 8 portas PoE+", quantidade=1,
            valor_unitario="0.00", eh_kit=False,
        )

        resp = self.client.get(reverse("dashboard_equipamentos"))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Equipamentos Complementares")
        produtos = _sem_href(resp.context["produtos_complementares"])
        self.assertEqual(
            produtos,
            [
                {"descricao_item": "Rack 7U", "quantidade_total": 4, "escolas_total": 2},
                {"descricao_item": "Switch Gigabit 8 portas PoE+", "quantidade_total": 1, "escolas_total": 1},
            ],
        )

    def test_produtos_complementares_exclui_kit_e_nobreak_e_ri_nao_concluido(self):
        """Kit (eh_kit=True) e "Nobreak" (mesmo avulso) não entram aqui —
        já têm card/linha próprios. RI não concluído também não conta,
        mesma regra do card "Kits Instalados" (RN-026)."""
        escola = Escola.objects.create(inep="40000017", nome="Escola Q")
        ri = Ri.objects.create(escola=escola, status=Ri.FATURAMENTO_CONCLUIDO)
        RiItemRelatorioEace.objects.create(
            ri=ri, descricao_item="Kit Cobertura Wi-Fi - 4 Access Points",
            quantidade=1, valor_unitario="0.00", eh_kit=True,
        )
        RiItemRelatorioEace.objects.create(
            ri=ri, descricao_item="Nobreak", quantidade=1, valor_unitario="0.00", eh_kit=False,
        )
        escola_nao_concluida = Escola.objects.create(inep="40000018", nome="Escola R")
        ri_nao_concluido = Ri.objects.create(escola=escola_nao_concluida, status=Ri.ANDAMENTO)
        RiItemRelatorioEace.objects.create(
            ri=ri_nao_concluido, descricao_item="Rack 5U", quantidade=1,
            valor_unitario="0.00", eh_kit=False,
        )

        resp = self.client.get(reverse("dashboard_equipamentos"))

        self.assertEqual(resp.context["produtos_complementares"], [])
        self.assertContains(resp, "Nenhum equipamento complementar lançado ainda.")

    def test_produtos_complementares_respeita_filtro_de_estado(self):
        escola_sp = Escola.objects.create(inep="40000019", nome="Escola S", estado="SP")
        ri_sp = Ri.objects.create(escola=escola_sp, status=Ri.FATURAMENTO_CONCLUIDO)
        RiItemRelatorioEace.objects.create(
            ri=ri_sp, descricao_item="Rack 7U", quantidade=1, valor_unitario="0.00", eh_kit=False,
        )
        escola_rj = Escola.objects.create(inep="40000020", nome="Escola T", estado="RJ")
        ri_rj = Ri.objects.create(escola=escola_rj, status=Ri.FATURAMENTO_CONCLUIDO)
        RiItemRelatorioEace.objects.create(
            ri=ri_rj, descricao_item="Rack 9U", quantidade=1, valor_unitario="0.00", eh_kit=False,
        )

        resp_sp = self.client.get(reverse("dashboard_equipamentos"), {"estado": "SP"})

        self.assertEqual(
            _sem_href(resp_sp.context["produtos_complementares"]),
            [{"descricao_item": "Rack 7U", "quantidade_total": 1, "escolas_total": 1}],
        )


class DashboardFiltrosPorKitEEquipamentoTests(TestCase):
    """FEAT-026 (ampliação, 2026-08-28, pedido do usuário): clicar numa
    linha de "Kits por Equipamento" ou "Equipamentos Complementares"
    filtra a página inteira por aquele item — mesmo padrão de clique já
    usado no gráfico por estado. Os 3 filtros (estado/kit/produto) são
    combináveis e independentes; cada "Ver todos os X" limpa só o
    próprio, preservando os outros 2."""

    def setUp(self):
        self.user = User.objects.create_user(username="analista", password="senha-teste-123")
        self.client.force_login(self.user)
        KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 4 Access Points", lote=9, unidade="Escola",
            numero_access_points=4,
        )
        KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 8 Access Points", lote=9, unidade="Escola",
            numero_access_points=8,
        )
        self.escola_kit4_sp = Escola.objects.create(
            inep="60000001", nome="Escola A", kit_inicial="4", lote=9, estado="SP",
        )
        Escola.objects.create(inep="60000002", nome="Escola B", kit_inicial="8", lote=9, estado="SP")
        escola_kit4_rj = Escola.objects.create(inep="60000003", nome="Escola C", kit_inicial="4", lote=9, estado="RJ")
        ri = Ri.objects.create(escola=self.escola_kit4_sp, status=Ri.FATURAMENTO_CONCLUIDO)
        RiItemRelatorioEace.objects.create(
            ri=ri, descricao_item="Kit Cobertura Wi-Fi - 4 Access Points",
            quantidade=1, valor_unitario="0.00", eh_kit=True,
        )
        RiItemRelatorioEace.objects.create(
            ri=ri, descricao_item="Rack 7U", quantidade=1, valor_unitario="0.00", eh_kit=False,
        )
        ri_rj = Ri.objects.create(escola=escola_kit4_rj, status=Ri.FATURAMENTO_CONCLUIDO)
        RiItemRelatorioEace.objects.create(
            ri=ri_rj, descricao_item="Rack 7U", quantidade=2, valor_unitario="0.00", eh_kit=False,
        )

    def test_clicar_num_kit_filtra_os_cards_e_o_grafico_por_estado(self):
        resp = self.client.get(
            reverse("dashboard_equipamentos"), {"kit": "Kit Cobertura Wi-Fi - 4 Access Points"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["kit_filtrado"], "Kit Cobertura Wi-Fi - 4 Access Points")
        self.assertEqual(resp.context["total_kits_programados"], 2)  # SP + RJ com Kit de 4
        self.assertEqual(resp.context["total_kits_instalados"], 1)
        self.assertContains(resp, "Kit: Kit Cobertura Wi-Fi - 4 Access Points")
        self.assertContains(resp, "Ver todos os Kits")
        # Gráfico "Kits Instalados por Estado" também restrito a esse Kit.
        linhas = {linha["estado"]: linha for linha in resp.context["kits_instalados_por_estado"]}
        self.assertEqual(linhas["SP"]["meta"], 1)
        self.assertEqual(linhas["RJ"]["meta"], 1)

    def test_filtro_de_kit_e_estado_sao_combinaveis(self):
        resp = self.client.get(
            reverse("dashboard_equipamentos"),
            {"kit": "Kit Cobertura Wi-Fi - 4 Access Points", "estado": "SP"},
        )
        self.assertEqual(resp.context["total_kits_programados"], 1)
        self.assertEqual(resp.context["total_kits_instalados"], 1)
        self.assertContains(resp, "Filtrado por SP")
        self.assertContains(resp, "Kit: Kit Cobertura Wi-Fi - 4 Access Points")

    def test_link_cruzado_pro_faturamento_carrega_o_kit_filtrado(self):
        """Ampliação (2026-08-28, pedido do usuário): "o financeiro tem
        que trazer os valores referente aquele filtro" — o link "Ver
        Faturamento de UF" passa a carregar o Kit também, não só o
        estado."""
        resp = self.client.get(
            reverse("dashboard_equipamentos"),
            {"kit": "Kit Cobertura Wi-Fi - 4 Access Points", "estado": "SP"},
        )
        # `assertContains` compararia contra o HTML escapado (`&amp;`); o
        # valor em `context` é o dado real, sem escape de template.
        self.assertEqual(
            resp.context["ver_faturamento_href"],
            "estado=SP&kit=Kit+Cobertura+Wi-Fi+-+4+Access+Points",
        )

        resp2 = self.client.get(reverse("home"), {"estado": "SP", "kit": "Kit Cobertura Wi-Fi - 4 Access Points"})
        self.assertEqual(resp2.context["kit_filtrado"], "Kit Cobertura Wi-Fi - 4 Access Points")
        self.assertEqual(resp2.context["estado_filtrado"], "SP")

    def test_clicar_de_novo_no_kit_ja_selecionado_limpa_o_filtro(self):
        """A linha do Kit já selecionado aponta pro href de "limpar" (só o
        kit, preservando o estado) — clicar de novo desmarca, em vez de
        recarregar a mesma página sem efeito."""
        resp = self.client.get(
            reverse("dashboard_equipamentos"),
            {"kit": "Kit Cobertura Wi-Fi - 4 Access Points", "estado": "SP"},
        )
        linha_selecionada = next(item for item in resp.context["kits_por_produto"] if item["selecionado"])
        self.assertEqual(linha_selecionada["href"], resp.context["limpar_kit_href"])

        resp2 = self.client.get(reverse("dashboard_equipamentos") + linha_selecionada["href"])
        self.assertIsNone(resp2.context["kit_filtrado"])
        self.assertEqual(resp2.context["estado_filtrado"], "SP")

    def test_clicar_num_equipamento_complementar_filtra_so_aquele_bloco(self):
        resp = self.client.get(reverse("dashboard_equipamentos"), {"produto": "Rack 7U"})
        self.assertEqual(resp.context["produto_filtrado"], "Rack 7U")
        self.assertEqual(
            _sem_href(resp.context["produtos_complementares"]),
            [{"descricao_item": "Rack 7U", "quantidade_total": 3, "escolas_total": 2}],
        )
        # Kit/Nobreak são eixos independentes — não são afetados.
        self.assertEqual(resp.context["total_kits_programados"], 3)
        self.assertContains(resp, "Equipamento: Rack 7U")
        self.assertContains(resp, "Ver todos os Equipamentos Complementares")

    def test_clicar_no_equipamento_revela_o_grafico_por_estado(self):
        """Ampliação (2026-08-28, pedido do usuário): "preciso saber o
        estado que está aquele equipamento" — sem `produto`, o gráfico
        fica vazio (misturar tipos não conta história); com `produto`,
        mostra 1 linha por UF onde aquele equipamento aparece."""
        resp_sem_produto = self.client.get(reverse("dashboard_equipamentos"))
        self.assertEqual(resp_sem_produto.context["produtos_complementares_por_estado"], [])

        resp = self.client.get(reverse("dashboard_equipamentos"), {"produto": "Rack 7U"})
        self.assertContains(resp, '"Rack 7U" por Estado')
        linhas = {linha["estado"]: linha for linha in resp.context["produtos_complementares_por_estado"]}
        self.assertEqual(linhas["SP"]["quantidade_total"], 1)
        self.assertEqual(linhas["SP"]["escolas_total"], 1)
        self.assertFalse(linhas["SP"]["selecionado"])
        self.assertEqual(linhas["RJ"]["quantidade_total"], 2)
        self.assertEqual(linhas["RJ"]["escolas_total"], 1)

    def test_clicar_no_estado_do_grafico_do_equipamento_define_estado_e_mostra_link_faturamento(self):
        """Pedido do usuário: "o valor no filtro de faturamento" — ao
        definir o estado por esse gráfico, o link cruzado "Ver Faturamento
        de UF" (já existente) aparece, preservando o produto filtrado."""
        resp = self.client.get(reverse("dashboard_equipamentos"), {"produto": "Rack 7U"})
        linha_rj = next(l for l in resp.context["produtos_complementares_por_estado"] if l["estado"] == "RJ")

        resp2 = self.client.get(reverse("dashboard_equipamentos") + linha_rj["href"])

        self.assertEqual(resp2.context["estado_filtrado"], "RJ")
        self.assertEqual(resp2.context["produto_filtrado"], "Rack 7U")
        self.assertContains(resp2, "Ver Faturamento de RJ")
        self.assertContains(resp2, reverse("home") + "?estado=RJ")

    def test_trocar_de_equipamento_complementar_zera_o_estado_selecionado(self):
        """Correção (2026-08-28, reportada pelo usuário): depois de ver a
        distribuição de "Rack 7U" por estado e voltar pra lista completa
        (ainda filtrada por RJ), escolher OUTRO equipamento não pode
        carregar o estado anterior — ele valia só pra distribuição do
        equipamento de antes; o novo pode nem existir naquele estado."""
        escola_switch_rj = Escola.objects.create(inep="60000004", nome="Escola D", estado="RJ")
        ri_switch_rj = Ri.objects.create(escola=escola_switch_rj, status=Ri.FATURAMENTO_CONCLUIDO)
        RiItemRelatorioEace.objects.create(
            ri=ri_switch_rj, descricao_item="Switch Gigabit 8 portas PoE+", quantidade=1,
            valor_unitario="0.00", eh_kit=False,
        )
        # Mesma situação de ter clicado "Ver todos os Equipamentos
        # Complementares" depois de navegar pela distribuição de "Rack 7U".
        resp = self.client.get(reverse("dashboard_equipamentos"), {"estado": "RJ"})
        linha_switch = next(
            item for item in resp.context["produtos_complementares"]
            if item["descricao_item"] == "Switch Gigabit 8 portas PoE+"
        )
        self.assertEqual(linha_switch["href"], "?produto=Switch+Gigabit+8+portas+PoE%2B")

        resp2 = self.client.get(reverse("dashboard_equipamentos") + linha_switch["href"])
        self.assertIsNone(resp2.context["estado_filtrado"])
        self.assertEqual(resp2.context["produto_filtrado"], "Switch Gigabit 8 portas PoE+")

    def test_ver_todos_os_x_preserva_os_outros_2_filtros(self):
        resp = self.client.get(
            reverse("dashboard_equipamentos"),
            {"kit": "Kit Cobertura Wi-Fi - 4 Access Points", "estado": "SP", "produto": "Rack 7U"},
        )

        resp_sem_estado = self.client.get(reverse("dashboard_equipamentos") + resp.context["limpar_estado_href"])
        self.assertIsNone(resp_sem_estado.context["estado_filtrado"])
        self.assertEqual(resp_sem_estado.context["kit_filtrado"], "Kit Cobertura Wi-Fi - 4 Access Points")
        self.assertEqual(resp_sem_estado.context["produto_filtrado"], "Rack 7U")

        resp_sem_produto = self.client.get(reverse("dashboard_equipamentos") + resp.context["limpar_produto_href"])
        self.assertIsNone(resp_sem_produto.context["produto_filtrado"])
        self.assertEqual(resp_sem_produto.context["estado_filtrado"], "SP")
        self.assertEqual(resp_sem_produto.context["kit_filtrado"], "Kit Cobertura Wi-Fi - 4 Access Points")


class DashboardKitsInstaladosPorEstadoTests(TestCase):
    """FEAT-026 (submenu Equipamentos, ampliação 2026-08-28, pedido do
    usuário): gráfico "Kits Instalados por Estado" e o filtro `?estado=UF`
    nos 3 cards de cima — mesmo padrão do gráfico "Faturado por Estado"
    (RN-027, Faturamento), adaptado pra contagem de Kits em vez de R$."""

    def setUp(self):
        self.user = User.objects.create_user(username="analista", password="senha-teste-123")
        KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 4 Access Points", lote=9, unidade="Escola",
            numero_access_points=4,
        )
        self.escola_sp = Escola.objects.create(
            inep="50000001", nome="Escola SP", kit_inicial="4", lote=9, estado="SP",
        )
        ri_sp = Ri.objects.create(escola=self.escola_sp, status=Ri.FATURAMENTO_CONCLUIDO)
        RiItemRelatorioEace.objects.create(
            ri=ri_sp, descricao_item="Kit Cobertura Wi-Fi - 4 Access Points",
            quantidade=1, valor_unitario="0.00", eh_kit=True,
        )  # Kit instalado
        self.escola_rj = Escola.objects.create(
            inep="50000002", nome="Escola RJ", kit_inicial="4", lote=9, estado="RJ",
        )
        Ri.objects.create(escola=self.escola_rj, status=Ri.ANDAMENTO)  # sem Kit instalado ainda
        self.client.force_login(self.user)

    def test_dashboard_sem_filtro_mostra_o_grafico_dos_2_estados(self):
        resp = self.client.get(reverse("dashboard_equipamentos"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Kits Instalados por Estado")
        self.assertContains(resp, ">SP<")
        self.assertContains(resp, ">RJ<")
        self.assertContains(resp, "1 instalado")  # SP
        self.assertContains(resp, "0 instalado")  # RJ
        self.assertContains(resp, "Meta: 1", count=2)  # SP e RJ têm 1 Kit cada
        self.assertEqual(resp.context["total_kits_programados"], 2)
        self.assertEqual(resp.context["total_kits_instalados"], 1)
        self.assertIsNone(resp.context["estado_filtrado"])

    def test_clicar_no_estado_filtra_os_3_cards(self):
        resp = self.client.get(reverse("dashboard_equipamentos"), {"estado": "SP"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["estado_filtrado"], "SP")
        self.assertEqual(resp.context["total_kits_programados"], 1)
        self.assertEqual(resp.context["total_kits_instalados"], 1)
        self.assertContains(resp, "Filtrado por SP")
        self.assertContains(resp, "Ver todos os estados")

    def test_estado_filtrado_mostra_link_cruzado_para_faturamento(self):
        """Ampliação (2026-08-28, pedido do usuário): navegação cruzada
        entre Equipamentos e Faturamento, mantendo o mesmo estado
        filtrado — os 2 dashboards usam o mesmo parâmetro `?estado=UF`."""
        resp = self.client.get(reverse("dashboard_equipamentos"), {"estado": "SP"})
        self.assertContains(resp, "Ver Faturamento de SP")
        self.assertContains(resp, reverse("home") + "?estado=SP")

    def test_sem_filtro_nao_mostra_link_cruzado(self):
        resp = self.client.get(reverse("dashboard_equipamentos"))
        self.assertNotContains(resp, "Ver Faturamento de")

    def test_estado_sem_nenhum_kit_instalado_entra_com_zero_no_grafico(self):
        resp = self.client.get(reverse("dashboard_equipamentos"))
        linhas = {linha["estado"]: linha for linha in resp.context["kits_instalados_por_estado"]}
        self.assertEqual(linhas["RJ"]["valor"], 0)
        self.assertEqual(linhas["RJ"]["meta"], 1)

    def test_estado_invalido_na_url_nao_quebra_a_pagina(self):
        resp = self.client.get(reverse("dashboard_equipamentos"), {"estado": "xx-invalido"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["total_kits_programados"], 0)


class UsuariosTrocarPerfilTests(TestCase):
    """FEAT-028 (RN-004 ampliada): tela "Administrador > Usuários" — lista
    usuários e troca o perfil (Administrador ↔ Analista), restrita a
    Administrador, sem permitir trocar o próprio perfil."""

    def setUp(self):
        self.administrador = User.objects.create_user(
            username="admin-teste", password="senha-teste-123", perfil=User.PERFIL_ADMINISTRADOR,
        )
        self.analista = User.objects.create_user(
            username="analista-teste", password="senha-teste-123", perfil=User.PERFIL_ANALISTA,
        )

    def test_exige_login(self):
        resp = self.client.get(reverse("usuarios"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp.url)

    def test_bloqueado_para_analista_na_tela(self):
        self.client.force_login(self.analista)
        resp = self.client.get(reverse("usuarios"))
        self.assertEqual(resp.status_code, 403)

    def test_bloqueado_para_analista_na_rota_direta(self):
        self.client.force_login(self.analista)
        resp = self.client.post(reverse("usuarios_trocar_perfil", args=[self.administrador.id]))
        self.assertEqual(resp.status_code, 403)
        self.administrador.refresh_from_db()
        self.assertEqual(self.administrador.perfil, User.PERFIL_ADMINISTRADOR)

    def test_administrador_ve_a_lista_de_usuarios(self):
        self.client.force_login(self.administrador)
        resp = self.client.get(reverse("usuarios"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "admin-teste")
        self.assertContains(resp, "analista-teste")

    def test_administrador_promove_analista(self):
        self.client.force_login(self.administrador)
        resp = self.client.post(reverse("usuarios_trocar_perfil", args=[self.analista.id]), follow=True)
        self.assertEqual(resp.status_code, 200)
        self.analista.refresh_from_db()
        self.assertEqual(self.analista.perfil, User.PERFIL_ADMINISTRADOR)
        self.assertContains(resp, "alterado para Administrador")

    def test_administrador_rebaixa_outro_administrador(self):
        outro_admin = User.objects.create_user(
            username="admin-teste-2", password="senha-teste-123", perfil=User.PERFIL_ADMINISTRADOR,
        )
        self.client.force_login(self.administrador)
        resp = self.client.post(reverse("usuarios_trocar_perfil", args=[outro_admin.id]), follow=True)
        self.assertEqual(resp.status_code, 200)
        outro_admin.refresh_from_db()
        self.assertEqual(outro_admin.perfil, User.PERFIL_ANALISTA)
        self.assertContains(resp, "alterado para Analista")

    def test_administrador_nao_troca_o_proprio_perfil(self):
        self.client.force_login(self.administrador)
        resp = self.client.post(reverse("usuarios_trocar_perfil", args=[self.administrador.id]), follow=True)
        self.assertEqual(resp.status_code, 200)
        self.administrador.refresh_from_db()
        self.assertEqual(self.administrador.perfil, User.PERFIL_ADMINISTRADOR)
        self.assertContains(resp, "não pode trocar o próprio perfil")

    def test_get_na_rota_de_troca_nao_altera_e_redireciona(self):
        self.client.force_login(self.administrador)
        resp = self.client.get(reverse("usuarios_trocar_perfil", args=[self.analista.id]))
        self.assertEqual(resp.status_code, 302)
        self.analista.refresh_from_db()
        self.assertEqual(self.analista.perfil, User.PERFIL_ANALISTA)


class UsuariosTrocarAcessoTests(TestCase):
    """FEAT-029 (RN-045): liga/desliga o acesso aos dados de outro usuário,
    mesma tela "Administrador > Usuários" (FEAT-028), restrita a
    Administrador, sem permitir ligar/desligar a própria conta."""

    def setUp(self):
        self.administrador = User.objects.create_user(
            username="admin-teste", password="senha-teste-123", perfil=User.PERFIL_ADMINISTRADOR,
        )
        self.analista = User.objects.create_user(
            username="analista-teste", password="senha-teste-123", perfil=User.PERFIL_ANALISTA,
        )

    def test_bloqueado_para_analista_na_rota_direta(self):
        self.client.force_login(self.analista)
        resp = self.client.post(reverse("usuarios_trocar_acesso", args=[self.administrador.id]))
        self.assertEqual(resp.status_code, 403)

    def test_administrador_desliga_usuario_ligado(self):
        self.assertTrue(self.analista.acesso_liberado)  # create_user já nasce Ligado (bootstrap/teste)
        self.client.force_login(self.administrador)
        resp = self.client.post(reverse("usuarios_trocar_acesso", args=[self.analista.id]), follow=True)
        self.assertEqual(resp.status_code, 200)
        self.analista.refresh_from_db()
        self.assertFalse(self.analista.acesso_liberado)
        self.assertContains(resp, "alterado para Desligado")

    def test_administrador_liga_usuario_desligado(self):
        self.analista.acesso_liberado = False
        self.analista.save(update_fields=["acesso_liberado"])
        self.client.force_login(self.administrador)
        resp = self.client.post(reverse("usuarios_trocar_acesso", args=[self.analista.id]), follow=True)
        self.assertEqual(resp.status_code, 200)
        self.analista.refresh_from_db()
        self.assertTrue(self.analista.acesso_liberado)
        self.assertContains(resp, "alterado para Ligado")

    def test_administrador_nao_troca_o_proprio_acesso(self):
        self.client.force_login(self.administrador)
        resp = self.client.post(reverse("usuarios_trocar_acesso", args=[self.administrador.id]), follow=True)
        self.assertEqual(resp.status_code, 200)
        self.administrador.refresh_from_db()
        self.assertTrue(self.administrador.acesso_liberado)
        self.assertContains(resp, "não pode ligar/desligar o próprio acesso")

    def test_get_na_rota_de_troca_nao_altera_e_redireciona(self):
        self.client.force_login(self.administrador)
        resp = self.client.get(reverse("usuarios_trocar_acesso", args=[self.analista.id]))
        self.assertEqual(resp.status_code, 302)
        self.analista.refresh_from_db()
        self.assertTrue(self.analista.acesso_liberado)


class AcessoLiberadoMiddlewareTests(TestCase):
    """FEAT-029 (RN-045): usuário Desligado loga e vê o menu, mas nenhuma
    tela com dado do projeto mostra informação — em vez disso, aviso de
    "aguardando liberação"; login/logout continuam acessíveis."""

    def setUp(self):
        self.desligado = User.objects.create_user(
            username="desligado-teste", password="senha-teste-123", acesso_liberado=False,
        )
        self.ligado = User.objects.create_user(username="ligado-teste", password="senha-teste-123")

    def test_usuario_desligado_ve_aviso_em_vez_do_dashboard(self):
        self.client.force_login(self.desligado)
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Aguardando liberação do Administrador")
        self.assertNotContains(resp, "Valor Total do Projeto")

    def test_usuario_desligado_ve_aviso_na_tela_de_usuarios(self):
        """Vale até para as telas do próprio menu Administrador (RN-045) —
        aqui usa um Administrador Desligado de propósito, para provar que
        perfil não isenta do controle."""
        admin_desligado = User.objects.create_user(
            username="admin-desligado", password="senha-teste-123",
            perfil=User.PERFIL_ADMINISTRADOR, acesso_liberado=False,
        )
        self.client.force_login(admin_desligado)
        resp = self.client.get(reverse("usuarios"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Aguardando liberação do Administrador")

    def test_usuario_ligado_ve_o_dashboard_normalmente(self):
        self.client.force_login(self.ligado)
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Aguardando liberação do Administrador")

    def test_usuario_desligado_consegue_fazer_logout(self):
        self.client.force_login(self.desligado)
        resp = self.client.post(reverse("logout"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp.url)

    def test_usuario_nao_autenticado_nao_e_afetado(self):
        """Sem login, o `@login_required` de cada view já redireciona antes
        do middleware ter qualquer usuário Desligado para checar."""
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp.url)
