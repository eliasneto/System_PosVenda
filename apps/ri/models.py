from django.conf import settings
from django.db import models

from apps.escolas.models import Escola


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
        (ANDAMENTO, "Andamento"),
        (ENVIO_EMAIL_FATURAMENTO, "Envio de Email para faturamento"),
        (AGUARDANDO_FINANCEIRO, "Aguardando financeiro"),
        (AGUARDANDO_ANEXO_PORTAL_EACE, "Aguardando Anexo portal EACE"),
        (AGUARDANDO_VALIDACAO_EACE, "Aguardando validação EACE"),
        (FATURAMENTO_CONCLUIDO, "Faturamento Concluído"),
        (CORRECAO_MEGA, "Correção MEGA"),
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
    concluido_em = models.DateTimeField("Concluído em", null=True, blank=True)
    criado_em = models.DateTimeField("Criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        verbose_name = "RI"
        verbose_name_plural = "RIs"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"RI {self.escola.inep} - {self.get_status_display()}"


class RiItemEace(models.Model):
    """Itens do relatório da EACE (RF-02). Lado que nunca é editado
    diretamente pelo pós-venda (RN-003) - correção só via novo relatório."""

    ri = models.ForeignKey(Ri, on_delete=models.CASCADE, related_name="itens_eace")
    descricao_item = models.CharField("Descrição do item", max_length=255)
    quantidade = models.PositiveIntegerField("Quantidade")
    valor_unitario = models.DecimalField("Valor unitário", max_digits=10, decimal_places=2)
    criado_em = models.DateTimeField("Criado em", auto_now_add=True)

    class Meta:
        verbose_name = "Item do relatório EACE"
        verbose_name_plural = "Itens do relatório EACE"

    def __str__(self):
        return f"{self.descricao_item} ({self.quantidade}x)"


class RiItemIxc(models.Model):
    """Itens do atendimento IXC, digitados manualmente nesta versão (RF-03)."""

    ri = models.ForeignKey(Ri, on_delete=models.CASCADE, related_name="itens_ixc")
    descricao_item = models.CharField("Descrição do item", max_length=255)
    quantidade = models.PositiveIntegerField("Quantidade")
    valor_unitario = models.DecimalField("Valor unitário", max_digits=10, decimal_places=2)
    criado_em = models.DateTimeField("Criado em", auto_now_add=True)

    class Meta:
        verbose_name = "Item do atendimento IXC"
        verbose_name_plural = "Itens do atendimento IXC"

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
    data_hora = models.DateTimeField("Data/hora", auto_now_add=True)

    class Meta:
        verbose_name = "E-mail com o financeiro"
        verbose_name_plural = "E-mails com o financeiro"
        ordering = ["-data_hora"]

    def __str__(self):
        return f"{self.get_direcao_display()} - RI {self.ri_id} - {self.data_hora:%d/%m/%Y %H:%M}"
