"""FEAT-053 (a formalizar pelo Orquestrador em business_rules.md/checklist.md):
Automações IXC — criação em massa de Login (Endereços) e abertura de
Atendimentos no IXC, por planilha. Cada tela (`apps/ixc/views.py`) mostra 2
grids independentes ("Processamento 1"/"Processamento 2") — cada grid é 1
`slot` com sua própria fila de execuções, para permitir 2 lotes em
andamento ao mesmo tempo sem um bloquear o outro (decisão técnica
reversível e de baixo risco, CLAUDE.md Sec. 9).

RN a formalizar (processamento em chunks; ADR-007, emendada em
2026-09-23): quem processa de verdade é o comando `processar_fila_
automacoes_ixc`, repetido por um container worker próprio (`ixc_worker`,
mesmo padrão do RPA EACE/ADR-005) — Start só marca `Processando`; o
worker encontra a execução `Processando` mais antiga e processa em
pequenos lotes ("chunks", `apps.ixc.services.processar_proximo_chunk`)
até não sobrar linha pendente. O polling da tela (`ixc_status`, HTMX
`hx-trigger="every 3s"`) é só leitura — nunca processa nada sozinho, por
isso o processamento não depende mais de ninguém com a aba aberta (era o
problema da 1ª versão, só HTMX). Stop só marca `cancelar_solicitado=True`,
checado pelo worker no início do próximo chunk."""

from django.conf import settings
from django.db import models


class ExecucaoAutomacaoIxc(models.Model):
    LOGIN_ENDERECOS = "login_enderecos"
    ATENDIMENTOS = "atendimentos"
    TIPO_CHOICES = [
        (LOGIN_ENDERECOS, "Login (Endereços)"),
        (ATENDIMENTOS, "Atendimentos"),
    ]

    PENDENTE = "pendente"
    PROCESSANDO = "processando"
    CONCLUIDO = "concluido"
    CANCELADO = "cancelado"
    STATUS_CHOICES = [
        (PENDENTE, "Pendente"),
        (PROCESSANDO, "Processando"),
        (CONCLUIDO, "Concluído"),
        (CANCELADO, "Cancelado"),
    ]

    SLOT_CHOICES = [(1, "Processamento 1"), (2, "Processamento 2")]

    tipo = models.CharField("Tipo", max_length=20, choices=TIPO_CHOICES)
    slot = models.PositiveSmallIntegerField("Grid", choices=SLOT_CHOICES)
    nome_arquivo_original = models.CharField("Arquivo enviado", max_length=255)
    status = models.CharField("Status", max_length=11, choices=STATUS_CHOICES, default=PENDENTE)
    # Stop (RN a formalizar): só sinaliza a intenção — quem efetivamente
    # para é o próprio `processar_proximo_chunk` (apps/ixc/services.py) no
    # início do próximo chunk, nunca no meio de uma chamada já em curso ao
    # IXC.
    cancelar_solicitado = models.BooleanField("Cancelamento solicitado", default=False)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="execucoes_automacao_ixc",
    )
    criado_em = models.DateTimeField("Criado em", auto_now_add=True)
    concluido_em = models.DateTimeField("Concluído em", null=True, blank=True)

    class Meta:
        verbose_name = "Execução de automação IXC"
        verbose_name_plural = "Execuções de automação IXC"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"{self.get_tipo_display()} — Processamento {self.slot} (#{self.pk})"

    @property
    def total_linhas(self):
        return self.linhas.count()

    @property
    def linhas_processadas(self):
        return self.linhas.exclude(status=LinhaExecucaoIxc.PENDENTE).count()

    @property
    def linhas_sucesso(self):
        return self.linhas.filter(status=LinhaExecucaoIxc.SUCESSO).count()

    @property
    def linhas_erro(self):
        return self.linhas.filter(status=LinhaExecucaoIxc.ERRO).count()

    @property
    def progresso_pct(self):
        """RN a formalizar (pedido do usuário, 2026-09-23): 100% é
        exclusivo de `Concluído` — mesmo com todas as linhas processadas,
        o cálculo trava em 99% até o status virar `Concluído` de fato (só
        acontece depois da última linha do último chunk, `services.
        processar_proximo_chunk`), pra 100% nunca aparecer "no meio" do
        processamento."""
        if self.status == self.CONCLUIDO:
            return 100
        total = self.total_linhas
        if not total:
            return 0
        return min(int(self.linhas_processadas * 100 / total), 99)

    @property
    def eh_terminal(self):
        """`Concluído`/`Cancelado` — processamento encerrado (com sucesso
        ou não); RN a formalizar: só esses 2 status somem do grid ao
        recarregar a tela (`slot_atual`), o resultado passa a viver só no
        Histórico de execuções."""
        return self.status in (self.CONCLUIDO, self.CANCELADO)

    @classmethod
    def slot_atual(cls, tipo, slot):
        """Execução "ativa" mais recente deste slot (`Pendente`/
        `Processando`) — RN a formalizar (pedido do usuário, 2026-09-23):
        ao terminar (`Concluído`/`Cancelado`), a próxima vez que a tela
        for carregada o grid volta a aparecer vazio/pronto para um novo
        upload; a execução terminada não é apagada, só passa a viver
        só no Histórico de execuções (`apps.ixc.views`). Nada aqui afeta
        a resposta ao vivo do próprio chunk que termina o processamento —
        essa resposta sempre usa a execução por `pk`, não por este
        método."""
        return (
            cls.objects.filter(tipo=tipo, slot=slot)
            .exclude(status__in=(cls.CONCLUIDO, cls.CANCELADO))
            .order_by("-criado_em")
            .first()
        )


class LinhaExecucaoIxc(models.Model):
    PENDENTE = "pendente"
    SUCESSO = "sucesso"
    ERRO = "erro"
    STATUS_CHOICES = [
        (PENDENTE, "Pendente"),
        (SUCESSO, "Sucesso"),
        (ERRO, "Erro"),
    ]

    execucao = models.ForeignKey(
        ExecucaoAutomacaoIxc, on_delete=models.CASCADE, related_name="linhas",
    )
    numero_linha = models.PositiveIntegerField("Linha na planilha")
    dados_entrada = models.JSONField("Dados da linha")
    status = models.CharField("Status", max_length=8, choices=STATUS_CHOICES, default=PENDENTE)
    mensagem = models.CharField("Mensagem", max_length=500, blank=True)
    id_ixc = models.CharField("ID no IXC", max_length=50, blank=True)

    class Meta:
        verbose_name = "Linha de execução IXC"
        verbose_name_plural = "Linhas de execução IXC"
        ordering = ["numero_linha"]

    def __str__(self):
        return f"Linha {self.numero_linha} da execução #{self.execucao_id}"
