import re
from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.escolas.models import Escola

# RN-011 (2026-08-24): nome de exibição do KitPadrao nas listas/selects do
# Lado IXC — a Descrição completa da LPU vem com um qualificador entre
# parênteses no final (ex.: "(serviços, materiais e equipamentos)",
# "(padrão ABNT NBR 14136)"), que deixa o nome grande demais para caber
# numa lista. Tira só esse sufixo; se não houver parênteses, usa a
# descrição inteira (nunca fica em branco).
_SUFIXO_ENTRE_PARENTESES = re.compile(r"\s*\([^)]*\)\s*$")


def _derivar_descricao_curta(descricao):
    curto = _SUFIXO_ENTRE_PARENTESES.sub("", descricao or "").strip()
    return curto or (descricao or "").strip()


# RN-010 ampliada (2026-08-25): para parte das escolas, Escola.kit_inicial
# não traz o texto completo do kit, só o número informado pela EACE (ex.:
# "4"). Esse número sempre corresponde à quantidade de Access Points do
# kit — mesmo conceito já usado no campo "Número de Access Points" da
# opção "Outro" do Lado IXC (RN-011, ver forms.py).
_NUMERO_ACCESS_POINTS = re.compile(r"(\d+)\s*Access Points?", re.IGNORECASE)


def _derivar_numero_access_points(descricao):
    correspondencia = _NUMERO_ACCESS_POINTS.search(descricao or "")
    return int(correspondencia.group(1)) if correspondencia else None


class Ri(models.Model):
    """RI (kit) - tabela central do processo de faturamento (RN-001)."""

    IMPLANTACAO_EACE = "implantacao_eace"
    ANDAMENTO = "andamento"
    ENVIO_EMAIL_FATURAMENTO = "envio_email_faturamento"
    AGUARDANDO_FINANCEIRO = "aguardando_financeiro"
    AGUARDANDO_ANEXO_PORTAL_EACE = "aguardando_anexo_portal_eace"
    AGUARDANDO_VALIDACAO_EACE = "aguardando_validacao_eace"
    FATURAMENTO_CONCLUIDO = "faturamento_concluido"
    CORRECAO_MEGA = "correcao_mega"

    STATUS_CHOICES = [
        (IMPLANTACAO_EACE, "Implantação EACE"),
        (ANDAMENTO, "Em Andamento"),
        (ENVIO_EMAIL_FATURAMENTO, "Envio de Email para faturamento"),
        (AGUARDANDO_FINANCEIRO, "Aguardando financeiro"),
        (AGUARDANDO_ANEXO_PORTAL_EACE, "Resposta Financeiro"),
        (AGUARDANDO_VALIDACAO_EACE, "Aguardando validação EACE"),
        (FATURAMENTO_CONCLUIDO, "Faturamento Concluído"),
        (CORRECAO_MEGA, "Correção MEGA"),
    ]

    # RN-053 (2026-09-03): mês da "OPERAÇÃO COMPRA E VENDA" (célula A20 de
    # cada aba da planilha de faturamento, RN-013) — lista fixa dos 12
    # meses, não ligada a nenhuma data já existente no RI (o ano dessa
    # mesma célula não vem daqui, é sempre o ano corrente no momento de
    # gerar a planilha — ver `gerar_planilha_faturamento`).
    MESES_OPERACAO_CHOICES = [
        (1, "Janeiro"), (2, "Fevereiro"), (3, "Março"), (4, "Abril"),
        (5, "Maio"), (6, "Junho"), (7, "Julho"), (8, "Agosto"),
        (9, "Setembro"), (10, "Outubro"), (11, "Novembro"), (12, "Dezembro"),
    ]

    escola = models.ForeignKey(
        Escola, on_delete=models.PROTECT, related_name="ris", verbose_name="Escola"
    )
    responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ris_responsavel",
        verbose_name="Responsável",
    )
    status = models.CharField(
        "Status", max_length=30, choices=STATUS_CHOICES, default=IMPLANTACAO_EACE
    )
    kit_informado_ixc = models.CharField("Kit informado (IXC)", max_length=100, blank=True)
    divergencia_kit = models.BooleanField("Divergência de KIT (alerta, RN-002)", default=False)
    # RN-011 (2026-08-24): valor único do RI, não por item — exibido e
    # editado no bloco "Produtos" do Lado IXC (2º lado).
    data_ativacao = models.DateField("Data de Ativação", null=True, blank=True)
    # RN-014 (2026-08-26): Município/Estado do Lado IXC — preenchimento
    # manual, usado na planilha de faturamento (RN-013). Não reaproveita
    # Escola.municipio/Escola.estado direto: é conferido contra o cadastro
    # da Escola (alerta visual quando diverge), decisão do usuário.
    municipio_ixc = models.CharField("Município (Lado IXC)", max_length=150, blank=True)
    estado_ixc = models.CharField("Estado (Lado IXC, UF)", max_length=2, blank=True)
    # RN-048 (2026-09-01): CNPJ/CNPJ Fictício do Lado IXC — preenchimento
    # manual, mesmo bloco de Data de Ativação/Município/Estado. Vão para a
    # planilha de faturamento (RN-013): CNPJ na célula A16, CNPJ Fictício
    # na B16, de cada aba. Mesmo padrão de município_ixc/estado_ixc: campo
    # opcional aqui — "obrigatório" é só na hora de gerar a planilha/enviar
    # o e-mail (ver `gerar_planilha_faturamento`, apps/ri/services.py).
    cnpj = models.CharField("CNPJ (Lado IXC)", max_length=20, blank=True)
    cnpj_ficticio = models.CharField("CNPJ Fictício (Lado IXC)", max_length=20, blank=True)
    # RN-053 (2026-09-03): mês da "OPERAÇÃO COMPRA E VENDA" (A20 de cada
    # aba da planilha de faturamento, RN-013) — select com os 12 meses,
    # nasce preenchido com o mês corrente (RiDataAtivacaoForm), continua
    # editável (RI de operação retroativa/futura). Opcional aqui, mesmo
    # padrão de município_ixc/estado_ixc — ver `gerar_planilha_faturamento`
    # (usa o mês corrente quando este campo nunca foi salvo).
    mes_operacao_ixc = models.PositiveSmallIntegerField(
        "Mês da Operação (Lado IXC)", choices=MESES_OPERACAO_CHOICES, null=True, blank=True
    )
    # FEAT-008/RF-16: "dados a enviar ao financeiro" reaproveitam os itens
    # já lançados do lado IXC (sem redigitar); este campo guarda o texto
    # livre digitado no campo "Mensagem" da tela de composição de e-mail
    # (RF-17/18) — mesmo dado, nome de campo mantido (decisão técnica
    # reversível e de baixo risco, CLAUDE.md §9).
    observacoes_envio_financeiro = models.TextField(
        "Observações para o financeiro", blank=True
    )
    dados_financeiro_confirmados_em = models.DateTimeField(
        "Dados para o financeiro confirmados em", null=True, blank=True
    )
    # RN-063 (melhoria 2026-09-04): última leitura somente-consulta do
    # grid do portal EACE para a OSP deste RI (`consultar_pendencias_
    # eace`) - mostrada ao lado do Produto/Valor de cada NF no select de
    # "Disparar RPA", pra não precisar mais escolher às cegas e só
    # descobrir a NF errada depois de um "Erro (valor divergente)",
    # RN-057. Lista de dicts (`{"status", "descricao", "valor"}`); vazio
    # até a 1ª consulta ou quando ela falha (motivo fica registrado à
    # parte, não aqui).
    pendencias_portal_eace = models.JSONField("Pendências no portal EACE", default=list, blank=True)
    pendencias_portal_eace_consultado_em = models.DateTimeField(
        "Pendências no portal EACE consultadas em", null=True, blank=True
    )
    pendencias_portal_eace_motivo_erro = models.CharField(
        "Motivo do erro na última consulta de pendências", max_length=50, blank=True
    )
    concluido_em = models.DateTimeField("Concluído em", null=True, blank=True)
    criado_em = models.DateTimeField("Criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        verbose_name = "RI"
        verbose_name_plural = "RIs"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"RI {self.escola.inep} - {self.get_status_display()}"


class KitPadrao(models.Model):
    """Catálogo de valores fixos por produto/kit (RN-010), usado para
    resolver Quantidade e Valor unitário do Kit declarado (1º lado,
    `RiItemEace`) a partir da descrição já informada pela EACE
    (`Escola.kit_inicial`, mesmo texto da coluna do `CONSOLIDADO
    EACE.xlsx`) — nunca digitados à mão pelo usuário. Alimentado pela aba
    `LPU` do `CONSOLIDADO EACE.xlsx` ("TABELA 1 - LISTA DE PREÇOS
    UNITÁRIOS"), via comando `importar_catalogo_lpu` (FEAT-015) ou cadastro
    manual (Django admin). O valor é fixo por Lote — a mesma descrição
    pode ter preço diferente em lote diferente, por isso o cruzamento com
    `Escola.kit_inicial` usa também `Escola.lote`.

    RN-010 ampliada (FEAT-016): para parte das escolas, `Escola.kit_inicial`
    traz só o número do KIT (ex.: "4"), não o texto completo — ver
    `numero_access_points` e `resolver_kit_declarado`."""

    descricao = models.CharField(
        "Descrição do item",
        max_length=255,
        help_text="Mesmo texto usado em Escola.kit_inicial (coluna do CONSOLIDADO EACE).",
    )
    descricao_curta = models.CharField(
        "Descrição curta",
        max_length=255,
        blank=True,
        help_text=(
            "Nome mostrado nas listas do Lado IXC (RN-011) — a Descrição completa é "
            'muito longa para um select. Ex.: "Kit Cobertura Wi-Fi - 8 Access Points". '
            "Preenchida automaticamente ao salvar quando fica em branco (tira o "
            "qualificador entre parênteses do final da Descrição); pode ser digitada "
            "à mão para um caso que a regra automática não resolva bem."
        ),
    )
    numero_access_points = models.PositiveIntegerField(
        "Número de Access Points",
        null=True,
        blank=True,
        help_text=(
            "Quantidade de Access Points do kit, extraída automaticamente da "
            'Descrição (ex.: "... 4 Access Points" → 4). Usada para cruzar com '
            "Escola.kit_inicial quando a EACE informa só o número do KIT, em vez "
            "do texto completo (RN-010 ampliada). Fica vazia quando a Descrição "
            "não segue esse padrão (itens avulsos: km, enlace, metro, par)."
        ),
    )
    lote = models.PositiveIntegerField(
        "Lote",
        null=True,
        blank=True,
        help_text="Mesmo valor de Escola.lote — o preço varia por lote (ex.: 9, 11).",
    )
    unidade = models.CharField(
        "Unidade",
        max_length=50,
        blank=True,
        help_text=(
            'Texto da coluna "Unidade" da planilha (Escola, Escola/Mês, Unidade, km, '
            "enlace, metro, par). Define se o valor é o KIT fechado da escola ou "
            "preço unitário de item avulso."
        ),
    )
    # RN-013 (2026-08-26; ajustada no mesmo dia): atalho OPCIONAL para
    # juntar vários produtos parecidos numa aba só da planilha de
    # faturamento (`doc/FATURAMENTO MATERIAS EACE.xlsx`) — ex.: "Rack 3U",
    # "Rack 5U", "Rack 7U" todos apontando para a aba "RACK". Sem
    # preencher, cada produto ganha sua própria aba, criada automaticamente
    # na hora (clonando o layout de uma aba existente) com o nome do
    # próprio produto — nenhum produto fica bloqueado por falta de
    # cadastro aqui. Também vira o texto do ITEM LPU na Nota Fiscal. Não
    # se aplica a KIT (Unidade Escola/Escola-Mês) — todo KIT usa a aba fixa
    # "NF KIT", com o texto "KIT N" calculado do número de Access Points
    # (ver `apps/ri/services.py`, `gerar_planilha_faturamento`).
    aba_planilha_financeiro = models.CharField(
        "Aba da planilha de faturamento (opcional)",
        max_length=50,
        blank=True,
        help_text=(
            "Preencha só para juntar este produto numa aba compartilhada "
            '(ex.: "RACK"). Em branco, o produto ganha aba própria, criada '
            "automaticamente com o nome dele. Não se aplica a KIT."
        ),
    )
    quantidade_padrao = models.PositiveIntegerField("Quantidade padrão", default=1)
    valor_equipamento = models.DecimalField(
        "Valor de equipamento", max_digits=10, decimal_places=2, null=True, blank=True
    )
    valor_servico = models.DecimalField(
        "Valor de serviço", max_digits=10, decimal_places=2, null=True, blank=True
    )
    criado_em = models.DateTimeField("Criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        verbose_name = "Kit padrão (catálogo de valores)"
        verbose_name_plural = "Kits padrão (catálogo de valores)"
        ordering = ["descricao", "lote"]
        constraints = [
            models.UniqueConstraint(
                fields=["descricao", "lote"], name="kitpadrao_unico_descricao_lote"
            ),
        ]

    def __str__(self):
        lote = f" (Lote {self.lote})" if self.lote else ""
        return f"{self.descricao}{lote}"

    def save(self, *args, **kwargs):
        if not self.descricao_curta:
            self.descricao_curta = _derivar_descricao_curta(self.descricao)
        if self.numero_access_points is None:
            self.numero_access_points = _derivar_numero_access_points(self.descricao)
        super().save(*args, **kwargs)

    @property
    def valor_total(self):
        """Soma de equipamento + serviço. Calculado, não guardado: a
        planilha de origem às vezes deixa "Valor Total" vazio mesmo quando
        só o serviço tem valor (RN-010). Aceita `str`/`Decimal`/`None` nos
        dois campos, pois um valor recém-atribuído (antes de salvar/
        recarregar) ainda não foi convertido pelo Django."""
        def _decimal(valor):
            return Decimal(str(valor)) if valor not in (None, "") else Decimal("0")

        return _decimal(self.valor_equipamento) + _decimal(self.valor_servico)

    @property
    def valor_faturavel(self):
        """Valor usado para preencher o Valor Unitário de um item (KIT ou
        Produto) resolvido deste catálogo — só o valor de equipamento, sem
        somar o valor de serviço (correção pedida pelo usuário em
        2026-08-31: a LPU estava sendo lida com equipamento + serviço
        somados, inflando o Valor Unitário faturado; vale para todo item,
        não só o KIT, e para todos os Lotes). Mesmo fallback de
        `None`/vazio que `valor_total`."""
        return Decimal(str(self.valor_equipamento)) if self.valor_equipamento not in (None, "") else Decimal("0")

    @property
    def kit_fechado_por_escola(self):
        """RN-010: True quando a Unidade indica preço fechado do KIT
        completo por escola (unidade "Escola" ou "Escola/Mês"); False
        quando é preço unitário de item avulso/complementar."""
        return self.unidade.strip().lower().startswith("escola")

    @classmethod
    def resolver_kit_declarado(cls, kit_inicial, lote=None, catalogo=None):
        """RN-010 ampliada: cruza o Kit declarado (1º lado, valor de
        `Escola.kit_inicial`) com este catálogo. Quando `kit_inicial` é só
        um número — formato usado por parte das escolas, em vez do texto
        completo do kit —, o cruzamento usa `numero_access_points`; caso
        contrário, usa a Descrição completa (regra original da RN-010).
        `lote`, quando informado, sempre restringe a busca — o valor do kit
        varia por Lote. Retorna `None` sem valor inventado quando não há
        correspondência (CLAUDE.md §9).

        `catalogo`, quando informado (lista/iterável já carregado em
        memória), evita 1 consulta por chamada — usado pelo Grid de INEPs
        (FEAT-007), que resolve o Kit declarado de várias escolas na mesma
        página."""
        kit_inicial = (kit_inicial or "").strip()
        if not kit_inicial:
            return None
        if catalogo is not None:
            candidatos = [k for k in catalogo if not lote or k.lote == lote]
            if kit_inicial.isdigit():
                alvo = int(kit_inicial)
                return next((k for k in candidatos if k.numero_access_points == alvo), None)
            return next((k for k in candidatos if k.descricao == kit_inicial), None)
        qs = cls.objects.filter(lote=lote) if lote else cls.objects
        if kit_inicial.isdigit():
            return qs.filter(numero_access_points=int(kit_inicial)).first()
        return qs.filter(descricao=kit_inicial).first()

    @classmethod
    def resolver_nobreak_declarado(cls, nobreak_inicial, lote=None, catalogo=None):
        """RN-017 (correção 2026-08-27): cruza o Nobreak declarado (1º
        lado, `Escola.nobreak_inicial`) com este catálogo, para uso no
        dashboard financeiro (RN-025/FEAT-026) — nunca exibido nas telas
        do Kit Declarado, que continuam só informativas. A Descrição
        completa da LPU vem com um qualificador entre parênteses (ex.:
        "Nobreak (serviço, material, equipamento)"); o cruzamento usa
        `descricao_curta` (mesmo campo derivado automaticamente, RN-011),
        que bate com o valor padrão "Nobreak" gravado em
        `Escola.nobreak_inicial`. `lote` sempre restringe a busca — o
        valor do Nobreak também varia por Lote, igual ao Kit. Retorna
        `None` sem valor inventado quando não há correspondência
        (CLAUDE.md §9). `catalogo`, quando informado, evita 1 consulta por
        chamada (mesmo padrão de `resolver_kit_declarado`)."""
        nobreak_inicial = (nobreak_inicial or "").strip()
        if not nobreak_inicial:
            return None
        if catalogo is not None:
            candidatos = [k for k in catalogo if not lote or k.lote == lote]
            return next((k for k in candidatos if k.descricao_curta == nobreak_inicial), None)
        qs = cls.objects.filter(lote=lote) if lote else cls.objects
        return qs.filter(descricao_curta=nobreak_inicial).first()


class PlanilhaEace(models.Model):
    """FEAT-023/RN-021: arquivo ativo da Planilha EACE (faturamento por
    INEP, mesmo layout de `doc/EACE.csv`), enviado pela tela "Administrador
    > Planilha EACE". Não guarda as linhas em tabela própria — o
    Sincronizador do Lado Relatório EACE (RN-022) reprocessa este arquivo
    sob demanda a cada clique, filtrando pelo INEP do RI. Singleton: existe
    no máximo 1 registro; um novo upload substitui o arquivo (e o
    registro) anterior."""

    COLUNAS_OBRIGATORIAS = ("Projeto", "Descrição do Item", "Qtde Produto", "Valor Unit UR")

    arquivo = models.FileField("Arquivo", upload_to="planilha_eace/")
    nome_original = models.CharField("Nome do arquivo", max_length=255)
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
        verbose_name = "Planilha EACE"
        verbose_name_plural = "Planilha EACE"

    def __str__(self):
        return f"{self.nome_original} ({self.enviado_em:%d/%m/%Y %H:%M})"

    @classmethod
    def substituir(cls, arquivo, usuario):
        """RN-021: novo upload substitui o arquivo ativo anterior — remove
        o arquivo antigo do disco antes de gravar o novo (no máximo 1
        registro ativo por vez)."""
        for antiga in cls.objects.all():
            antiga.arquivo.delete(save=False)
            antiga.delete()
        return cls.objects.create(
            arquivo=arquivo, nome_original=arquivo.name, enviado_por=usuario
        )

    @classmethod
    def ativa(cls):
        """Único registro ativo, se houver — `None` quando nenhuma
        planilha foi enviada ainda."""
        return cls.objects.first()


class RiItemEace(models.Model):
    """1º lado do RI: itens do Kit declarado pela EACE, informado ANTES do
    início do projeto (RF-02). Nome da classe mantido por ser decisão
    técnica reversível e de baixo risco (CLAUDE.md §9) — não é "o
    relatório" (isso é `RiItemRelatorioEace`, 3º lado). Lado que nunca é
    editado diretamente pelo pós-venda - correção só via novo lançamento.
    Confrontado contra o lado IXC na RN-002 (informal, alerta amarelo, não
    bloqueia).

    RN-010 (2026-08-24): não há tela para o usuário lançar item deste
    lado — descricao_item/quantidade/valor_unitario nunca são digitados.
    Escolas do Lote 1 têm o item criado direto no banco (fora desta tela,
    ainda bloqueado pela ausência da planilha com Quantidade/Valor por
    kit); Lote 2/3 são cadastrados pelo administrador via Django admin,
    só nesta primeira versão do sistema (decisão do usuário). Os campos
    continuam simples (não FK para `KitPadrao`) para preservar o valor
    lançado como um retrato histórico, mesmo padrão já usado nos outros
    2 lados."""

    ri = models.ForeignKey(Ri, on_delete=models.CASCADE, related_name="itens_eace")
    descricao_item = models.CharField("Descrição do item", max_length=255)
    quantidade = models.PositiveIntegerField("Quantidade")
    valor_unitario = models.DecimalField("Valor unitário", max_digits=10, decimal_places=2)
    criado_em = models.DateTimeField("Criado em", auto_now_add=True)

    class Meta:
        verbose_name = "Item do Kit declarado (1º lado)"
        verbose_name_plural = "Itens do Kit declarado (1º lado)"

    def __str__(self):
        return f"{self.descricao_item} ({self.quantidade}x)"


class RiItemIxc(models.Model):
    """2º lado do RI: itens do atendimento IXC, digitados manualmente
    nesta versão (RF-03). Único lado editável/excluível pelo pós-venda.
    Confrontado contra o 1º lado (RN-002, informal) e contra o 3º lado
    (RN-003, formal — divergência é destacada do lado deste, o IXC)."""

    ri = models.ForeignKey(Ri, on_delete=models.CASCADE, related_name="itens_ixc")
    descricao_item = models.CharField("Descrição do item", max_length=255)
    quantidade = models.PositiveIntegerField("Quantidade")
    valor_unitario = models.DecimalField("Valor unitário", max_digits=10, decimal_places=2)
    # RN-013 (2026-08-26): marca o item como o "KIT Instalado" do Lado IXC
    # (RN-011), não um produto avulso — a planilha de faturamento usa isso
    # para escolher a aba fixa "NF KIT" em vez do catálogo de produtos
    # avulsos (`KitPadrao.aba_planilha_financeiro`).
    eh_kit = models.BooleanField("É o KIT Instalado (não produto avulso)", default=False)
    criado_em = models.DateTimeField("Criado em", auto_now_add=True)

    class Meta:
        verbose_name = "Item do atendimento IXC (2º lado)"
        verbose_name_plural = "Itens do atendimento IXC (2º lado)"

    def __str__(self):
        return f"{self.descricao_item} ({self.quantidade}x)"


class RiItemRelatorioEace(models.Model):
    """3º lado do RI (novo, 2026-08-22): itens do relatório baixado no
    portal da EACE, DEPOIS da instalação (RN-003). Nunca editado
    diretamente pelo pós-venda - correção só via um relatório novo/
    atualizado da própria EACE. Confrontado contra o lado IXC na RN-003
    (formal, sem tolerância, bloqueia a transição do RI enquanto aberto).

    RN-018 (2026-08-26): lançamento passa a usar o mesmo mecanismo do Lado
    IXC (RN-011) — "KIT Instalado" (catálogo `KitPadrao`) + "Produtos" via
    "+", ambos com Valor Unitário resolvido automaticamente pelo catálogo.
    Exceção à imutabilidade descrita acima: qualquer item deste lado (KIT
    ou Produto) pode ser editado/excluído — exclusão restrita a
    Administrador (RN-004). Inicialmente só o KIT tinha essa exceção (o
    limite de 1 KIT por INEP, RN-015, tornaria impossível corrigi-lo pela
    tela); ampliada para Produtos em 2026-08-27, depois de o Sincronizador
    (FEAT-024/RN-022) poder casar um Produto errado com a Planilha EACE
    sem forma de corrigir."""

    ri = models.ForeignKey(Ri, on_delete=models.CASCADE, related_name="itens_relatorio_eace")
    descricao_item = models.CharField("Descrição do item", max_length=255)
    quantidade = models.PositiveIntegerField("Quantidade")
    valor_unitario = models.DecimalField("Valor unitário", max_digits=10, decimal_places=2)
    # RN-018: marca o item como o "KIT Instalado" deste lado (mesmo papel
    # de `RiItemIxc.eh_kit`) — usado para o limite de 1 KIT por INEP
    # (RN-015) e para liberar editar/excluir só nesse item.
    eh_kit = models.BooleanField("É o KIT Instalado (não produto avulso)", default=False)
    # RN-022 (ampliada, 2026-08-27): campos fechados — só o Sincronizador
    # preenche, lidos da mesma linha da Planilha EACE que originou o item
    # (colunas "Num OSP"/"Validação OSP"/"Nota Fiscal"); nunca digitados
    # nem editados manualmente. Item lançado fora do Sincronizador nasce
    # com os três em branco. `nota_fiscal` é por item (não por RI) — a
    # planilha real traz um número de Nota Fiscal diferente por
    # KIT/Produto do mesmo INEP, cobrindo a Quantidade inteira daquele
    # item, não por unidade.
    num_osp = models.CharField("Num OSP", max_length=50, blank=True)
    validacao_osp = models.CharField("Validação OSP", max_length=50, blank=True)
    nota_fiscal = models.CharField("Nota Fiscal", max_length=50, blank=True)
    # RN-046 (2026-08-28): mesmo padrão dos 3 campos acima — fechado, só o
    # Sincronizador preenche, lido da coluna "Status escola" (coluna T) da
    # mesma linha da planilha. É por item (não por RI) porque a planilha
    # traz 1 valor por produto — itens do mesmo RI com valor diferente
    # entre si geram a divergência da RN-046 (ri_detail_view). Rótulo
    # exibido como "Status Equip" (ajuste de texto, 2026-08-28) — o nome
    # do campo continua ligado à coluna de origem da planilha.
    status_escola = models.CharField("Status Equip", max_length=50, blank=True)
    # RN-062 (2026-09-04): marca que este item veio do Sincronizador (nesta
    # sincronização ou numa anterior) — usado para decidir, numa próxima
    # sincronização, quais itens podem ser removidos/substituídos quando a
    # Planilha EACE ativa não trouxer mais aquela Descrição para o INEP
    # ("a última planilha é sempre a que vale", fora de "Implantação EACE"/
    # "Em Andamento" — ver `sincronizar_relatorio_eace_da_planilha`). Item
    # lançado manualmente nasce com este campo `False` e nunca é removido
    # por uma sincronização; passa a `True` se uma planilha real confirmar
    # a mesma Descrição depois (a partir daí, uma planilha seguinte sem
    # essa Descrição pode removê-lo).
    origem_sincronizador = models.BooleanField("Lançado/confirmado pelo Sincronizador", default=False)
    criado_em = models.DateTimeField("Criado em", auto_now_add=True)

    class Meta:
        verbose_name = "Item do Relatório EACE (3º lado)"
        verbose_name_plural = "Itens do Relatório EACE (3º lado)"

    def __str__(self):
        return f"{self.descricao_item} ({self.quantidade}x)"


class RiDivergencia(models.Model):
    """RN-003 - catálogo de `tipo` ainda em aberto (P-03, ver
    business_rules.md e requisitos.md); os valores abaixo seguem a
    proposta registrada, sujeitos a ajuste quando o cliente confirmar."""

    TIPO_VALOR = "valor"
    TIPO_QUANTIDADE = "quantidade"
    TIPO_KIT_RELATORIO = "kit_relatorio"
    TIPO_NF_FINANCEIRO = "nf_financeiro"
    TIPO_CHOICES = [
        (TIPO_VALOR, "Divergência de valor"),
        (TIPO_QUANTIDADE, "Divergência de quantidade"),
        (TIPO_KIT_RELATORIO, "Divergência de KIT (contra relatório)"),
        (TIPO_NF_FINANCEIRO, "Divergência da Nota Fiscal"),
    ]

    ri = models.ForeignKey(Ri, on_delete=models.CASCADE, related_name="divergencias")
    tipo = models.CharField("Tipo", max_length=30, choices=TIPO_CHOICES)
    bloqueia = models.BooleanField("Bloqueia", default=True)
    descricao = models.TextField("Descrição", blank=True)
    resolvida_em = models.DateTimeField("Resolvida em", null=True, blank=True)
    criado_em = models.DateTimeField("Criado em", auto_now_add=True)

    class Meta:
        verbose_name = "Divergência do RI"
        verbose_name_plural = "Divergências do RI"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"{self.get_tipo_display()} - RI {self.ri_id}"


class Documento(models.Model):
    """Nota Fiscal (PDF) e XML recebidos do financeiro (RF-08)."""

    NOTA_FISCAL_PDF = "nota_fiscal_pdf"
    XML = "xml"
    TIPO_CHOICES = [
        (NOTA_FISCAL_PDF, "Nota Fiscal (PDF)"),
        (XML, "XML"),
    ]

    ri = models.ForeignKey(Ri, on_delete=models.CASCADE, related_name="documentos")
    tipo = models.CharField("Tipo", max_length=20, choices=TIPO_CHOICES)
    arquivo = models.FileField("Arquivo", upload_to="documentos_ri/%Y/%m/")
    versao = models.PositiveIntegerField("Versão", default=1)
    ativo = models.BooleanField("Ativo (versão vigente)", default=True)
    recebido_em = models.DateTimeField("Recebido em", null=True, blank=True)
    criado_em = models.DateTimeField("Criado em", auto_now_add=True)

    class Meta:
        verbose_name = "Documento do RI"
        verbose_name_plural = "Documentos do RI"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"{self.get_tipo_display()} v{self.versao} - RI {self.ri_id}"


class LogRpaEace(models.Model):
    """RN-056/RN-057/RN-058 (FEAT-033): 1 log por Nota Fiscal esperada,
    criado quando o financeiro responde (RN-016). Usuário escolhe
    manualmente o par PDF+XML entre os `Documento` daquela resposta;
    "Disparar RPA" só enfileira (RN-058, Fase 3) - quem executa de fato é
    o processo consumidor único (`apps/ri/services.py`,
    `processar_proximo_da_fila_rpa_eace`)."""

    PENDENTE = "pendente"
    NA_FILA = "na_fila"
    PROCESSANDO = "processando"
    SUCESSO = "sucesso"
    ERRO = "erro"
    RESULTADO_CHOICES = [
        (PENDENTE, "Pendente"),
        (NA_FILA, "Na fila"),
        (PROCESSANDO, "Processando"),
        (SUCESSO, "Sucesso"),
        (ERRO, "Erro"),
    ]

    ri = models.ForeignKey(Ri, on_delete=models.CASCADE, related_name="logs_rpa_eace")
    documento_pdf = models.ForeignKey(
        Documento, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="logs_rpa_eace_pdf", verbose_name="Nota fiscal (PDF)",
    )
    documento_xml = models.ForeignKey(
        Documento, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="logs_rpa_eace_xml", verbose_name="XML",
    )
    resultado = models.CharField("Resultado", max_length=11, choices=RESULTADO_CHOICES, default=PENDENTE)
    motivo_erro = models.CharField("Motivo do erro", max_length=50, blank=True)
    # RN-057: dados extraidos do PDF, gravados mesmo quando o resultado e
    # "Erro" - o usuario confere o que foi lido do PDF sem abrir o arquivo.
    inep_pdf = models.CharField("INEP extraído do PDF", max_length=20, blank=True)
    produto_pdf = models.CharField("Produto extraído do PDF", max_length=255, blank=True)
    valor_pdf = models.CharField("Valor extraído do PDF", max_length=20, blank=True)
    valor_portal = models.CharField("Valor exibido no portal EACE", max_length=20, blank=True)
    # RN-058 (Fase 3): fila FIFO - `enfileirado_em` reordena para o final a
    # cada disparo/reprocessamento; `tentativas` conta quantas execucoes
    # reais ja aconteceram desde o ultimo enfileiramento manual (reseta a
    # cada "Disparar RPA"/"Tentar novamente") - erro nao mapeado com
    # tentativas < 2 volta pra fila em vez de virar erro definitivo.
    enfileirado_em = models.DateTimeField("Enfileirado em", null=True, blank=True)
    tentativas = models.PositiveIntegerField("Tentativas", default=0)
    executado_em = models.DateTimeField("Executado em", null=True, blank=True)
    # Pedido do usuário (2026-09-03): barra de progresso enquanto roda -
    # `apps/integracoes/eace/rpa.py` (ETAPAS_RPA_EACE) reporta cada etapa
    # concluída (login, navegação, upload, etc.) por callback, gravada
    # aqui a cada avanço para o polling da tela mostrar que não travou.
    etapa_atual = models.CharField("Etapa atual da RPA", max_length=100, blank=True)
    progresso_pct = models.PositiveSmallIntegerField("Progresso da RPA (%)", default=0)
    # RN-065 (2026-09-05): usuário reportou precisar marcar 1 Nota Fiscal
    # como concluída manualmente (ex.: anexou direto no portal EACE, sem
    # passar pela RPA) - grava o mesmo `resultado="sucesso"` de uma
    # execução automática (mesmo critério de avanço do RI, RN-056), só
    # que este campo marca que não foi a automação que fez, pra tela
    # distinguir sem inventar um resultado novo.
    concluido_manualmente = models.BooleanField("Concluído manualmente", default=False)
    criado_em = models.DateTimeField("Criado em", auto_now_add=True)

    class Meta:
        verbose_name = "Log da RPA EACE"
        verbose_name_plural = "Logs da RPA EACE"
        ordering = ["id"]

    def __str__(self):
        return f"Log RPA EACE #{self.pk} - RI {self.ri_id} ({self.get_resultado_display()})"


class RiHistorico(models.Model):
    """Linha do tempo de comunicação do RI (RN-008, FEAT-014) — mensagem
    (com anexo opcional), anexo isolado e log automático de mudança de
    status/campo relevante. Reaproveita o padrão de `RegistroHistorico` do
    modulo-posVenda (lá RN-029/041), adaptado para FK direta com `Ri`
    nesta versão — nome de campo/tabela é decisão técnica reversível do
    Dev (mesmo critério já usado para `auditoria`, ver `modelo-dados.md`).
    Tipo `email` fica pronto no schema para quando a FEAT-008/009 (envio e
    leitura de e-mail) existirem e passarem a gravar aqui; sem produtor
    ainda. Entrada não é editada nem excluída depois de criada."""

    MENSAGEM = "mensagem"
    ANEXO = "anexo"
    LOG_STATUS = "log_status"
    LOG_CAMPO = "log_campo"
    EMAIL = "email"
    TIPO_CHOICES = [
        (MENSAGEM, "Mensagem"),
        (ANEXO, "Anexo"),
        (LOG_STATUS, "Mudança de status"),
        (LOG_CAMPO, "Mudança de campo"),
        (EMAIL, "E-mail"),
    ]

    ri = models.ForeignKey(Ri, on_delete=models.CASCADE, related_name="historico")
    tipo = models.CharField("Tipo", max_length=20, choices=TIPO_CHOICES)
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Autor",
    )
    mensagem = models.TextField("Mensagem", max_length=250, blank=True)
    # max_length=255 (2026-08-31): o padrão do FileField (100) estourava
    # com escola de nome comprido — o anexo da planilha de faturamento
    # passou a se chamar "FATURAMENTO MATERIAS EACE - <INEP> - <escola>.xlsx"
    # (RN-013, pedido do usuário) e há escola cadastrada com nome de 100
    # caracteres (Escola.nome permite até 255).
    anexo = models.FileField(
        "Anexo", upload_to="ri_historico/%Y/%m/", max_length=255, blank=True
    )
    # RN-008/FEAT-009 (2026-08-27): a resposta do financeiro (RF-08) chega
    # com 2 arquivos (NF PDF + XML) numa única mensagem — `anexo` acima só
    # guarda 1 por entrada (usado pelo envio, FEAT-008, com a planilha
    # única). Em vez de duplicar o conteúdo do arquivo em outra entrada
    # separada (quebrava o registro em vários cards na linha do tempo),
    # esta entrada só referencia os `Documento` já salvos (sem duplicar
    # upload) — a mesma entrada "E-mail" mostra os 2 links de download.
    documentos = models.ManyToManyField(
        "Documento", blank=True, related_name="entradas_historico", verbose_name="Documentos anexados"
    )
    campo = models.CharField("Campo alterado", max_length=100, blank=True)
    valor_anterior = models.CharField("Valor anterior", max_length=255, blank=True)
    valor_novo = models.CharField("Valor novo", max_length=255, blank=True)
    criado_em = models.DateTimeField("Criado em", auto_now_add=True)

    class Meta:
        verbose_name = "Histórico do RI"
        verbose_name_plural = "Histórico do RI"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"{self.get_tipo_display()} - RI {self.ri_id}"


class EmailFinanceiroLog(models.Model):
    """Histórico de envio/recebimento com o financeiro (RF-07/RF-08)."""

    ENVIADO = "enviado"
    RECEBIDO = "recebido"
    DIRECAO_CHOICES = [(ENVIADO, "Enviado"), (RECEBIDO, "Recebido")]

    OK = "ok"
    FORA_DO_PADRAO = "fora_do_padrao"
    STATUS_LEITURA_CHOICES = [(OK, "OK"), (FORA_DO_PADRAO, "Fora do padrão")]

    ri = models.ForeignKey(Ri, on_delete=models.CASCADE, related_name="emails_financeiro")
    direcao = models.CharField("Direção", max_length=10, choices=DIRECAO_CHOICES)
    remetente = models.EmailField("Remetente", blank=True)
    destinatarios = models.TextField("Destinatários", blank=True)
    assunto = models.CharField("Assunto", max_length=255, blank=True)
    anexo_pdf = models.CharField("Anexo PDF (caminho)", max_length=500, blank=True)
    status_leitura = models.CharField(
        "Status de leitura", max_length=20, choices=STATUS_LEITURA_CHOICES, blank=True
    )
    # FEAT-009: ID da mensagem no Microsoft Graph — evita reprocessar a
    # mesma resposta se o delta query da sincronização entregá-la de novo.
    mensagem_id_externo = models.CharField("ID da mensagem (Graph)", max_length=255, blank=True)
    data_hora = models.DateTimeField("Data/hora", auto_now_add=True)

    class Meta:
        verbose_name = "E-mail com o financeiro"
        verbose_name_plural = "E-mails com o financeiro"
        ordering = ["-data_hora"]

    def __str__(self):
        return f"{self.get_direcao_display()} - RI {self.ri_id} - {self.data_hora:%d/%m/%Y %H:%M}"


class EmailFinanceiroSync(models.Model):
    """FEAT-009: cursor de sincronização (delta link do Microsoft Graph) da
    caixa do financeiro — evita reler o histórico inteiro a cada passada de
    polling. Reaproveita só o *padrão* já usado no `modulo-posVenda`
    (`EmailCotacaoRespostaSync`); credenciais e app do Azure são
    exclusivos deste sistema (ADR de independência — usuário confirmou em
    2026-08-25 que o Sistema_posvenda não pode depender do modulo-posVenda
    em tempo de execução)."""

    mailbox = models.EmailField("Caixa monitorada", unique=True)
    delta_link = models.TextField("Delta link", blank=True)
    ultima_sincronizacao_em = models.DateTimeField("Última sincronização em", null=True, blank=True)
    ultimo_erro = models.TextField("Último erro", blank=True)
    atualizado_em = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        verbose_name = "Sincronização de e-mail do financeiro"
        verbose_name_plural = "Sincronizações de e-mail do financeiro"

    def __str__(self):
        return f"Sincronização — {self.mailbox}"

    @classmethod
    def obter_configuracao(cls, mailbox):
        configuracao, _ = cls.objects.get_or_create(mailbox=mailbox)
        return configuracao
