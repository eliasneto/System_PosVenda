from django.conf import settings
from django.db import models


class Auditoria(models.Model):
    """RN-006 - reaproveita o conceito de LoginAuditoria do modulo-posVenda
    (RNF-05), ampliado para cobrir alteração de campo, transição de status,
    envio/recebimento de e-mail, ação manual e erro (RF-12)."""

    LOGIN = "login"
    ALTERACAO_CAMPO = "alteracao_campo"
    TRANSICAO_STATUS = "transicao_status"
    ENVIO_EMAIL = "envio_email"
    RECEBIMENTO_EMAIL = "recebimento_email"
    ERRO = "erro"
    EXECUCAO_RPA_EACE = "execucao_rpa_eace"
    ACAO_CHOICES = [
        (LOGIN, "Login"),
        (ALTERACAO_CAMPO, "Alteração de campo"),
        (TRANSICAO_STATUS, "Transição de status"),
        (ENVIO_EMAIL, "Envio de e-mail"),
        (RECEBIMENTO_EMAIL, "Recebimento de e-mail"),
        (ERRO, "Erro"),
        # FEAT-033 (RN-058): 1 registro por tentativa de execução do RPA de
        # anexo no portal EACE - o usuário pediu (2026-09-03) que cada
        # rodada fique registrada, mesmo quando `LogRpaEace` (que só guarda
        # o estado mais recente) já sobrescreveu os dados da tentativa
        # anterior por cima.
        (EXECUCAO_RPA_EACE, "Execução RPA EACE"),
    ]

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="registros_auditoria",
        verbose_name="Usuário",
    )
    acao = models.CharField("Ação", max_length=30, choices=ACAO_CHOICES)
    entidade = models.CharField("Entidade", max_length=50, blank=True)
    entidade_id = models.PositiveBigIntegerField("ID da entidade", null=True, blank=True)
    campo = models.CharField("Campo alterado", max_length=100, blank=True)
    valor_anterior = models.TextField("Valor anterior", blank=True)
    valor_novo = models.TextField("Valor novo", blank=True)
    ip_origem = models.GenericIPAddressField("IP de origem", null=True, blank=True)
    criado_em = models.DateTimeField("Criado em", auto_now_add=True)

    class Meta:
        verbose_name = "Registro de auditoria"
        verbose_name_plural = "Registros de auditoria"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"{self.get_acao_display()} - {self.criado_em:%d/%m/%Y %H:%M}"
