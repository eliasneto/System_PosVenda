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

    inep = models.CharField("INEP", max_length=8, unique=True)
    nome = models.CharField("Nome da escola", max_length=255)
    endereco = models.CharField("Endereço", max_length=255, blank=True)
    lote = models.PositiveIntegerField("Lote", null=True, blank=True)
    estado = models.CharField("UF", max_length=2, blank=True)
    municipio = models.CharField("Município", max_length=150, blank=True)
    kit_inicial = models.CharField("Kit declarado (EACE)", max_length=100, blank=True)
    velocidade_dl_minima = models.CharField("Velocidade mínima", max_length=50, blank=True)
    status_conexao = models.CharField(
        "Status de conexão",
        max_length=25,
        choices=STATUS_CONEXAO_CHOICES,
        default=DESCONECTADO,
    )
    data_instalacao_re = models.DateField("Data de instalação RE", null=True, blank=True)
    data_instalacao_ri = models.DateField("Data de instalação RI", null=True, blank=True)
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
