from django.conf import settings
from django.db import models
from django.utils import timezone


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
    # FEAT-044/RN-098 (a formalizar pelo Orquestrador em business_rules.md;
    # pedido do usuário, 2026-09-14): status próprio do MIP (LOTE) — gravado
    # automaticamente em todo INEP incluído num `Lote` (`escolas/views.
    # mip_lote_criar_view`), nunca escolhido manualmente pelo `<select>` de
    # Status (MIP) da tela de detalhe (só o resultado da criação de um
    # LOTE) — ver `status_mip_opcoes_editavel` em `mip_detail_view`.
    AGUARDANDO_ENCERRAMENTO_LOTE = "aguardando_encerramento_lote"
    # FEAT-046 (a formalizar pelo Orquestrador em business_rules.md; pedido
    # do usuário, 2026-09-14): gravado automaticamente em todo INEP do LOTE
    # quando o e-mail do LOTE é enviado (`apps.escolas.services.
    # enviar_email_lote`) — também nunca escolhido manualmente (mesmo
    # critério do valor acima).
    # Pedido do usuário (2026-09-15): envio de e-mail do LOTE foi comentado
    # (não será usado por enquanto, ver `Lote` abaixo) — este status deixou
    # de ser alcançável, mas a constante e o valor ficam mantidos (dado
    # histórico e reativação futura).
    EMAIL_LOTE_ENVIADO = "email_lote_enviado"
    # Pedido do usuário (2026-09-15): novo status intermediário do fluxo do
    # LOTE, escolhido manualmente no lugar do antigo envio de e-mail — ver
    # `Lote.EM_FATURAMENTO`.
    EM_FATURAMENTO_LOTE = "em_faturamento_lote"
    FATURAMENTO_CONCLUIDO = "faturamento_concluido"
    STATUS_MIP_CHOICES = [
        (EM_ANDAMENTO, "Em Andamento"),
        (AGUARDANDO_VALIDACAO_EACE, "Aguardando Validação EACE"),
        (AGUARDANDO_ENCERRAMENTO_LOTE, "Aguardando Encerramento LOTE"),
        # (EMAIL_LOTE_ENVIADO, "Email em LOTE enviado"),  # e-mail do LOTE comentado (pedido do usuário, 2026-09-15)
        (EM_FATURAMENTO_LOTE, "Em Faturamento"),
        (FATURAMENTO_CONCLUIDO, "Processo Concluído"),
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
    sincronizacao_confirmada = models.BooleanField(
        "Sincronização já confirmada",
        default=False,
        help_text=(
            "Marca se o usuário já escolheu sobrepor ou não os INEPs "
            "deste arquivo com Lado 3 já preenchido — depois de "
            "marcado, a tela para de perguntar de novo até um novo "
            "arquivo ser importado."
        ),
    )

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


class Lote(models.Model):
    """FEAT-044/RN-098 (a formalizar pelo Orquestrador em business_rules.md;
    pedido do usuário, 2026-09-14): agrupa, num "LOTE", os INEPs do MIP que
    estavam em "Aguardando Validação EACE" e com Valor Total (IXC) == Valor
    Total (EACE) (RN-076/RN-077) — criado a partir do filtro Estado +
    Município + Data inicial/final já existente no grid "Projeto > MIP"
    (RN-079/RN-075), pelo botão "Criar LOTE" ao lado do Total geral
    (RN-080, `apps.escolas.views.mip_lote_criar_view`/
    `apps.escolas.services.escolas_elegiveis_lote_mip`).

    Não confundir com `Escola.lote` (acima) — campo antigo e sem relação
    com este, é só o número do "Lote" do catálogo EACE (`KitPadrao.lote`)
    usado para casar cada Escola com a faixa de preço certa do catálogo
    (RN-010); nomes iguais por coincidência de vocabulário do negócio.

    Estado/Município/Data início/Data fim gravados aqui são só o "rótulo"
    do lote (o filtro usado na hora da criação, exibido na tela "Projeto >
    MIP (LOTE)") — quem de fato compõe o lote são os INEPs em `escolas`.
    Ao entrar aqui, cada INEP ganha `Escola.status_mip =
    "aguardando_encerramento_lote"` e um novo `RiHistorico` (campo "Status
    (MIP)" + campo "LOTE", pedido explícito do usuário) — nenhum outro dado
    do INEP é alterado.

    RN-098 (correção, 2026-09-14 — bug real reportado pelo usuário: filtrou
    só Estado/Município para um LOTE de 1 INEP e o botão "Criar LOTE" não
    apareceu): Data início/Data fim passam a ser OPCIONAIS — Estado e
    Município continuam obrigatórios (são eles que dizem "qual grupo"),
    mas a Data deixou de ser um requisito pra sequer aparecer o botão;
    quando informada, continua restringindo pela Data de Ativação do RI
    (RN-075), igual a antes."""

    estado = models.CharField("UF", max_length=2)
    municipio = models.CharField("Município", max_length=150)
    data_inicio = models.DateField("Data início", null=True, blank=True)
    data_fim = models.DateField("Data fim", null=True, blank=True)
    escolas = models.ManyToManyField(Escola, related_name="lotes", verbose_name="INEPs")
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Criado por",
    )
    criado_em = models.DateTimeField("Criado em", auto_now_add=True)
    # FEAT-045 (a formalizar pelo Orquestrador em business_rules.md; pedido
    # do usuário, 2026-09-14): e-mail do LOTE (`apps.escolas.services.
    # enviar_email_lote`) — registro de "quando" (e "por quem") foi
    # disparado pela última vez; reenvio permitido enquanto `status` ainda
    # estiver em `AGUARDANDO_ENCERRAMENTO`/`EMAIL_ENVIADO` (bloqueado depois
    # que o LOTE avança para "Em Andamento"/"Faturamento Concluído" —
    # RN a formalizar, pedido do usuário 2026-09-14, ver `enviar_email_lote`).
    #
    # Pedido do usuário (2026-09-15): o envio de e-mail do LOTE foi
    # comentado em todo o código (`apps.escolas.services.enviar_email_lote`,
    # a view, o form, o botão e o modal) — não será usado por enquanto. Os
    # 2 campos abaixo ficam mantidos (sem migration de remoção) só para não
    # perder o dado de quem já tinha e-mail enviado antes dessa mudança e
    # para permitir reativar a função no futuro sem recriar coluna.
    email_enviado_em = models.DateTimeField("E-mail enviado em", null=True, blank=True)
    email_enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="E-mail enviado por",
    )
    # FEAT-046 (a formalizar pelo Orquestrador em business_rules.md; pedido
    # do usuário, 2026-09-14): ciclo de vida próprio do LOTE — nasce em
    # AGUARDANDO_ENCERRAMENTO (mesmo instante da criação, espelha o
    # `Escola.status_mip = "aguardando_encerramento_lote"` que cada INEP já
    # ganha).
    #
    # Pedido do usuário (2026-09-15): o envio de e-mail (`EMAIL_ENVIADO`,
    # que antes liberava a troca manual) foi comentado — no lugar dele, a
    # tela "Projeto > MIP (LOTE)" mostra direto, a partir de
    # AGUARDANDO_ENCERRAMENTO, o campo de troca manual de status com as 3
    # opções abaixo: EM_ANDAMENTO ("vai para o RI como é hoje", pedido do
    # usuário), EM_FATURAMENTO (novo status intermediário) e
    # FATURAMENTO_CONCLUIDO (rótulo "Processo Concluído" — fim do
    # processo). Cada transição muda também o `Escola.status_mip` de todos
    # os INEPs do LOTE e grava no histórico de cada um (pedido explícito do
    # usuário) — `apps.escolas.views.mip_lote_status_update_view`.
    AGUARDANDO_ENCERRAMENTO = "aguardando_encerramento"
    # EMAIL_ENVIADO — e-mail do LOTE comentado (pedido do usuário,
    # 2026-09-15); constante mantida para não quebrar LOTE antigo que já
    # tenha esse valor gravado.
    EMAIL_ENVIADO = "email_enviado"
    EM_ANDAMENTO = "em_andamento"
    EM_FATURAMENTO = "em_faturamento"
    FATURAMENTO_CONCLUIDO = "faturamento_concluido"
    STATUS_CHOICES = [
        (AGUARDANDO_ENCERRAMENTO, "Aguardando Encerramento LOTE"),
        # (EMAIL_ENVIADO, "Email em LOTE enviado"),  # e-mail do LOTE comentado (pedido do usuário, 2026-09-15)
        (EM_ANDAMENTO, "Em Andamento"),
        (EM_FATURAMENTO, "Em Faturamento"),
        (FATURAMENTO_CONCLUIDO, "Processo Concluído"),
    ]
    status = models.CharField(
        "Status", max_length=30, choices=STATUS_CHOICES, default=AGUARDANDO_ENCERRAMENTO
    )
    # Pedido do usuário (2026-09-17): depois que o financeiro gera as Notas
    # Fiscais de todo o LOTE, ele devolve tudo junto num único .zip — este
    # campo deixa esse arquivo disponível para download na tela "Projeto >
    # MIP (LOTE)". No máximo 1 arquivo por LOTE — um novo upload substitui
    # o anterior (`substituir_notas_fiscais_zip`), mesmo padrão de arquivo
    # único já usado em `PlanilhaEace`/`PlanilhaRelatorioEaceMip` (RN-021).
    arquivo_notas_fiscais_zip = models.FileField(
        "Notas Fiscais (.zip)", upload_to="lotes_notas_fiscais/%Y/%m/", max_length=255, blank=True
    )
    nome_original_notas_fiscais_zip = models.CharField(
        "Nome original do arquivo de Notas Fiscais", max_length=255, blank=True
    )
    notas_fiscais_zip_enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Notas Fiscais (.zip) enviado por",
    )
    notas_fiscais_zip_enviado_em = models.DateTimeField(
        "Notas Fiscais (.zip) enviado em", null=True, blank=True
    )

    class Meta:
        verbose_name = "Lote"
        verbose_name_plural = "Lotes"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"LOTE-{self.pk:04d}"

    def substituir_notas_fiscais_zip(self, arquivo, usuario):
        """Substitui o .zip de Notas Fiscais deste LOTE (pedido do usuário,
        2026-09-17) — no máximo 1 arquivo por vez; apaga o anterior do
        disco antes de gravar o novo (mesmo padrão de `PlanilhaEace.
        substituir`, RN-021)."""
        if self.arquivo_notas_fiscais_zip:
            self.arquivo_notas_fiscais_zip.delete(save=False)
        self.arquivo_notas_fiscais_zip = arquivo
        self.nome_original_notas_fiscais_zip = arquivo.name
        self.notas_fiscais_zip_enviado_por = usuario
        self.notas_fiscais_zip_enviado_em = timezone.now()
        self.save(update_fields=[
            "arquivo_notas_fiscais_zip", "nome_original_notas_fiscais_zip",
            "notas_fiscais_zip_enviado_por", "notas_fiscais_zip_enviado_em",
        ])
