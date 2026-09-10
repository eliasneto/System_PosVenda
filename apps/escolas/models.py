from django.conf import settings
from django.db import models


class Escola(models.Model):
    """Reaproveitado de apps.escolas.Escola do modulo-posVenda (RF-01) -
    somente os campos ligados ao Gerenciador Pos-Venda, mais os campos
    novos definidos em requisitos.md ITEM 11 e RN-007 (business_rules.md).
    """

    DESCONECTADO = "desconectado"
    PARCIALMENTE_CONECTADO = "parcialmente_conectado"
    CONECTADO = "conectado"
    STATUS_CONEXAO_CHOICES = [
        (DESCONECTADO, "Desconectado"),
        (PARCIALMENTE_CONECTADO, "Parcialmente conectado"),
        (CONECTADO, "Conectado"),
    ]

    # Pedido do usuário (2026-09-10): status próprio do MIP, independente
    # de `Ri.status` — a partir do momento em que o RI de um INEP chega em
    # "Aguardando validação EACE" (RN-001) pela 1ª vez, o INEP "sai" do
    # grid de Equipamentos (Projeto > Equipamentos, FEAT-007) e passa a
    # ser controlado só por aqui, no MIP (`apps.ri.services.
    # trocar_status_com_log` grava `AGUARDANDO_VALIDACAO_EACE` nesse
    # momento — ver RN-092). Enquanto `None`, o INEP nunca esteve no MIP
    # (nenhum RI dele chegou lá ainda) — não aparece no grid do MIP, mas
    # continua no grid de Equipamentos normalmente.
    EM_ANDAMENTO = "em_andamento"
    AGUARDANDO_VALIDACAO_EACE = "aguardando_validacao_eace"
    FATURAMENTO_CONCLUIDO = "faturamento_concluido"
    STATUS_MIP_CHOICES = [
        (EM_ANDAMENTO, "Em Andamento"),
        (AGUARDANDO_VALIDACAO_EACE, "Aguardando Validação EACE"),
        (FATURAMENTO_CONCLUIDO, "Faturamento Concluído"),
    ]

    inep = models.CharField("INEP", max_length=8, unique=True)
    nome = models.CharField("Nome da escola", max_length=255)
    endereco = models.CharField("Endereço", max_length=255, blank=True)
    lote = models.PositiveIntegerField("Lote", null=True, blank=True)
    estado = models.CharField("UF", max_length=2, blank=True)
    municipio = models.CharField("Município", max_length=150, blank=True)
    kit_inicial = models.CharField("Kit declarado (EACE)", max_length=100, blank=True)
    nobreak_inicial = models.CharField(
        "Nobreak declarado (EACE)",
        max_length=100,
        blank=True,
        default="Nobreak",
        help_text=(
            "RN-017: item padrão, igual para todas as escolas (sem "
            "quantidade/valor, não entra no cálculo financeiro)."
        ),
    )
    velocidade_dl_minima = models.CharField("Velocidade mínima", max_length=50, blank=True)
    status_conexao = models.CharField(
        "Status de conexão",
        max_length=25,
        choices=STATUS_CONEXAO_CHOICES,
        default=DESCONECTADO,
    )
    data_instalacao_re = models.DateField("Data de instalação RE", null=True, blank=True)
    data_instalacao_ri = models.DateField("Data de instalação RI", null=True, blank=True)
    # RN-081 (a criar): bolinha verde/vermelha do grid do MIP — atualizado
    # só quando "Sincronizar todos os INEPs" roda (`sincronizar_relatorio_
    # eace_mip_de_todas_as_escolas`), não a cada carregamento da tela.
    # `True` = INEP apareceu na planilha ativa na última sincronização;
    # `False` = não apareceu; `None` = nenhuma sincronização rodou ainda
    # (sem cor no grid até lá — nunca assume um resultado que não existe).
    encontrado_relatorio_eace_mip = models.BooleanField(
        "Encontrado na última sincronização do Relatório EACE (MIP)",
        null=True,
        blank=True,
        default=None,
    )
    status_mip = models.CharField(
        "Status (MIP)",
        max_length=30,
        choices=STATUS_MIP_CHOICES,
        null=True,
        blank=True,
        default=None,
        help_text=(
            "Gravado automaticamente quando o RI chega em 'Aguardando "
            "validação EACE' pela 1ª vez (RN-092); editável manualmente "
            "só na tela do MIP a partir daí."
        ),
    )
    cod_fornecedor = models.CharField(
        "Cód. Fornecedor (Relatório EACE MIP)",
        max_length=20,
        blank=True,
        help_text=(
            "Coluna 'Cod Fornecedor' da planilha do MIP (RN-069) — igual "
            "para toda linha do mesmo INEP; usado junto com o INEP para "
            "gerar o arquivo Excel pedido pelo usuário. Gravado pelo "
            "Sincronizador do Lado 3, preservado quando o INEP some de uma "
            "rodada (mesma regra do `encontrado_relatorio_eace_mip`)."
        ),
    )
    # Pedido do usuário (2026-09-10): marca um INEP cujo RI nasceu a partir
    # do histórico legado do pós-venda (planilha "CONSOLIDADO EACE
    # Atualizado.xlsx", comando `importar_ri_legado_eace`) — atendimento já
    # realizado antes deste sistema existir, sem lançamento manual pela
    # tela. Exibido em negrito/amarelo (cor de destaque do sistema) no Grid
    # de INEPs e no MIP, para diferenciar de um INEP cadastrado/trabalhado
    # pelo fluxo normal do sistema.
    legado = models.BooleanField(
        "Dado legado (histórico anterior ao sistema)",
        default=False,
        help_text=(
            "Marcado automaticamente pela importação do histórico do "
            "pós-venda — nunca marcado manualmente pela tela."
        ),
    )
    criado_em = models.DateTimeField("Criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        verbose_name = "Escola"
        verbose_name_plural = "Escolas"
        ordering = ["nome"]

    def __str__(self):
        return f"{self.inep} - {self.nome}"

    def recalcular_status_conexao(self):
        """RN-007: desconectado -> parcialmente conectado -> conectado,
        conforme o preenchimento das datas de instalação de RE e RI."""
        preenchidos = sum([bool(self.data_instalacao_re), bool(self.data_instalacao_ri)])
        if preenchidos == 0:
            self.status_conexao = self.DESCONECTADO
        elif preenchidos == 1:
            self.status_conexao = self.PARCIALMENTE_CONECTADO
        else:
            self.status_conexao = self.CONECTADO
        return self.status_conexao

    def save(self, *args, **kwargs):
        self.recalcular_status_conexao()
        super().save(*args, **kwargs)


class PlanilhaRelatorioEaceMip(models.Model):
    """FEAT-034/FEAT-035 (Lado 3/Relatório EACE do MIP): arquivo ativo da
    planilha de origem, enviado pela tela "Administrador > Relatório EACE
    (MIP)". Fonte real informada pelo usuário: "Base MIP.xlsx", aba
    "_Base contrato_taxa_instalação" — mesmo padrão de singleton do
    `PlanilhaEace` (`apps.ri`, RN-021), um novo upload substitui o arquivo
    anterior.

    Período (Data inicial/Data final, usado pelo card "No período" do
    grid do MIP, RN-073): RN-090 (2026-09-09) tirou a edição do período
    da tela "Administrador > Relatório EACE (MIP)" de vez — usuário
    pediu para tirar essas datas de lá; os dois campos continuam no
    modelo só porque o card do Grid ainda os lê (mantido como está por
    pedido do usuário), mas nenhuma tela os preenche mais.
    `definir_periodo()` sobrevive para quem já usa o dado diretamente
    (testes, Django admin/shell); `substituir()` continua preservando o
    período do arquivo anterior a cada novo upload, sem mudança."""

    # Colunas exigidas pelo usuário na aba de dados (comparadas
    # normalizadas — maiúsculas, sem quebra de linha/espaço duplicado,
    # mesmo padrão de `importar_nova_base_eace`): "Projeto" é o INEP;
    # "Cod Fornecedor" é gravado em `Escola.cod_fornecedor`, junto com o
    # INEP, para o arquivo Excel pedido pelo usuário; "Data Emissão ACS" é
    # a data por linha (não confundir com o período Data inicial/Data
    # final do upload, que é um dado próprio do envio).
    COLUNAS_OBRIGATORIAS = (
        "PROJETO",
        "COD FORNECEDOR",
        "DESCRIÇÃO DO ITEM",
        "QTDE PRODUTO",
        "VALOR UNIT UR",
        "DATA EMISSÃO ACS",
        "UF",
        "CIDADE",
    )

    arquivo = models.FileField("Arquivo", upload_to="relatorio_eace_mip/")
    nome_original = models.CharField("Nome do arquivo", max_length=255)
    data_inicial = models.DateField("Data inicial", null=True, blank=True)
    data_final = models.DateField("Data final", null=True, blank=True)
    enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Enviado por",
    )
    enviado_em = models.DateTimeField("Enviado em", auto_now_add=True)

    class Meta:
        verbose_name = "Relatório EACE (MIP)"
        verbose_name_plural = "Relatório EACE (MIP)"

    def __str__(self):
        if self.data_inicial and self.data_final:
            periodo = f"({self.data_inicial:%d/%m/%Y} a {self.data_final:%d/%m/%Y})"
        else:
            periodo = "(sem período definido)"
        return f"{self.nome_original} {periodo}"

    @classmethod
    def substituir(cls, arquivo, usuario):
        """Novo upload substitui o arquivo ativo anterior — remove o
        arquivo antigo do disco antes de gravar o novo (no máximo 1
        registro ativo por vez, mesma regra do `PlanilhaEace`). O
        período (Data inicial/Data final) do arquivo substituído é
        preservado no novo registro — nenhuma tela informa/edita esse
        período (RN-090); sem arquivo anterior, fica em aberto."""
        anteriores = list(cls.objects.all())
        data_inicial = anteriores[0].data_inicial if anteriores else None
        data_final = anteriores[0].data_final if anteriores else None
        for antiga in anteriores:
            antiga.arquivo.delete(save=False)
            antiga.delete()
        return cls.objects.create(
            arquivo=arquivo,
            nome_original=arquivo.name,
            data_inicial=data_inicial,
            data_final=data_final,
            enviado_por=usuario,
        )

    def definir_periodo(self, data_inicial, data_final):
        """Alimenta o card "No período" do grid do MIP (RN-073). RN-090
        (2026-09-09) tirou a tela que chamava este método (usuário pediu
        para tirar as datas da tela de importar/sincronizar) — sobrevive
        para quem ainda usa o dado diretamente (testes, Django admin/
        shell)."""
        self.data_inicial = data_inicial
        self.data_final = data_final
        self.save(update_fields=["data_inicial", "data_final"])

    @classmethod
    def ativa(cls):
        """Único registro ativo, se houver — `None` quando nenhuma
        planilha foi enviada ainda."""
        return cls.objects.first()


class EscolaItemRelatorioEaceMip(models.Model):
    """Lado 3 (Relatório EACE) do MIP — usuário pediu "as mesmas regras
    de sincronização do RI": casamento de Descrição×catálogo idêntico ao
    Sincronizador do RI (`apps.ri.services.
    sincronizar_relatorio_eace_da_planilha`, RN-022), reaproveitando as
    mesmas funções (`casar_planilha_eace_com_catalogo`,
    `quantidade_planilha_eace`) — mas a partir da planilha do MIP
    (`PlanilhaRelatorioEaceMip`, RN-069) e por Escola/INEP, não por RI.
    Tabela própria, independente de `RiItemRelatorioEace` (RI): as duas
    fontes de planilha são diferentes por decisão já registrada
    (RN-067) e nunca deveriam se misturar — sincronizar o MIP nunca
    altera o Lado 3 do RI, e vice-versa. Mostra o **Valor de serviço**
    (`KitPadrao.valor_servico`), não o Valor de equipamento usado no RI
    (mesma diferença já aplicada aos lados 1/2 do MIP, RN-067).

    Sem formulário de lançamento manual (MIP é só leitura, RN-067) — todo
    item aqui vem do Sincronizador; por isso, ao contrário de
    `RiItemRelatorioEace`, não precisa de um campo "origem_sincronizador"
    para decidir o que pode ser removido: a última planilha ativa é
    sempre a fonte de verdade, sem exceção de fase/status (RI tem essa
    exceção, RN-062, porque tem um formulário manual a proteger; o MIP
    não)."""

    escola = models.ForeignKey(
        Escola, on_delete=models.CASCADE, related_name="itens_relatorio_eace_mip"
    )
    descricao_item = models.CharField("Descrição do item", max_length=255)
    quantidade = models.PositiveIntegerField("Quantidade")
    valor_servico = models.DecimalField(
        "Valor de serviço", max_digits=10, decimal_places=2, null=True, blank=True
    )
    eh_kit = models.BooleanField("É o KIT Instalado (não produto avulso)", default=False)
    # Colunas extras da planilha do MIP (RN-069), sem regra própria ainda
    # além de guardar/exibir — só leitura, lidas direto da linha que
    # originou o item.
    uf = models.CharField("UF", max_length=2, blank=True)
    cidade = models.CharField("Cidade", max_length=150, blank=True)
    data_emissao_acs = models.DateField("Data Emissão ACS", null=True, blank=True)
    atualizado_em = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        verbose_name = "Item do Relatório EACE (MIP, 3º lado)"
        verbose_name_plural = "Itens do Relatório EACE (MIP, 3º lado)"

    def __str__(self):
        return f"{self.escola.inep} — {self.descricao_item}"
