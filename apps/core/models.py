from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    def create_user(self, username, email=None, password=None, **extra_fields):
        # RN-045/FEAT-029: `create_user` é sempre criação direta e
        # deliberada (bootstrap via `createsuperuser`, scripts, testes) —
        # nunca as 2 formas que a regra mira (painel `/admin/` do Django e
        # login automático via AD), que não passam por este método e por
        # isso continuam pegando o `default=False` do campo no model.
        # Sem essa exceção, nem o primeiro superusuário nasceria Ligado
        # para liberar os próximos.
        extra_fields.setdefault("acesso_liberado", True)
        if not username:
            raise ValueError("O nome de usuario e obrigatorio")
        email = self.normalize_email(email)
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("perfil", User.PERFIL_ADMINISTRADOR)
        return self.create_user(username, email, password, **extra_fields)


class User(AbstractUser):
    """Reaproveitado de apps.core.User do modulo-posVenda (RNF-05), com o
    campo `perfil` acrescentado para os perfis fixos deste sistema
    (RN-004): Administrador (tudo), Analista (tudo, exceto excluir) e
    Visualizador (RN-093/FEAT-040: só visualiza Projeto > Equipamentos,
    sem Status/Responsável/logs/RPA e sem editar nada)."""

    PERFIL_ADMINISTRADOR = "administrador"
    PERFIL_ANALISTA = "analista"
    PERFIL_VISUALIZADOR = "visualizador"
    PERFIL_CHOICES = [
        (PERFIL_ADMINISTRADOR, "Administrador"),
        (PERFIL_ANALISTA, "Analista"),
        (PERFIL_VISUALIZADOR, "Visualizador"),
    ]

    username = models.CharField("Usuario", max_length=150, unique=True)
    email = models.EmailField("Endereco de E-mail", unique=True, blank=True, null=True)
    perfil = models.CharField(
        "Perfil", max_length=20, choices=PERFIL_CHOICES, default=PERFIL_ANALISTA
    )
    # RN-045/FEAT-029: controle de acesso aos dados, independente do
    # perfil — vale também para Administrador. Só usuário já existente
    # antes desta feature é ligado automaticamente (migration de dado);
    # conta criada a partir de agora (inclusive via login AD, RN-043)
    # nasce Desligada, aguardando um Administrador já Ligado liberar.
    acesso_liberado = models.BooleanField("Acesso liberado", default=False)

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["email"]
    objects = UserManager()

    def save(self, *args, **kwargs):
        if self.email == "":
            self.email = None
        super().save(*args, **kwargs)

    @property
    def is_administrador(self):
        """RN-004: superuser tambem conta como Administrador."""
        return self.is_superuser or self.perfil == self.PERFIL_ADMINISTRADOR

    @property
    def is_visualizador(self):
        """RN-093/FEAT-040: superuser/Administrador nunca cai aqui, mesmo
        que o campo `perfil` esteja (por engano) como Visualizador."""
        return not self.is_administrador and self.perfil == self.PERFIL_VISUALIZADOR


class RoboRpaEace(models.Model):
    """Robôs do RPA EACE (pedido do usuário, 2026-11-10; emenda a RN-058/
    ADR-008 - ver ADR-009): cada robô ativo cadastrado aqui vira 1 processo
    próprio no container `rpa_eace_worker` (supervisor
    `supervisionar_robos_rpa_eace`), com o próprio navegador Chromium e o
    próprio login no portal EACE - todos consomem a mesma fila (RI e MIP,
    ordem de chegada), em paralelo.

    Dois robôs nunca trabalham no mesmo INEP ao mesmo tempo
    (`apps.ri.fila_rpa_eace.reservar_proximo_envio`).

    Sem nenhum robô ativo, o supervisor roda 1 robô só com o login do
    `.env` (`EACE_USUARIO`/`EACE_SENHA`) - mesmo comportamento de antes."""

    nome = models.CharField("Nome", max_length=60, unique=True)
    usuario = models.CharField("Usuário (e-mail) no portal EACE", max_length=150)
    senha = models.CharField("Senha no portal EACE", max_length=150)
    ativo = models.BooleanField(
        "Ativo",
        default=True,
        help_text="Desmarcado, o robô termina o item em andamento e não pega mais nenhum.",
    )
    criado_em = models.DateTimeField("Criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        verbose_name = "Robô do RPA EACE"
        verbose_name_plural = "Robôs do RPA EACE"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class TravaFilaRpaEace(models.Model):
    """Linha única (pk=1) travada com `select_for_update` só durante a
    reserva do próximo item da fila do RPA EACE - garante que 2 robôs não
    escolham ao mesmo tempo o mesmo item nem 2 itens do mesmo INEP. A trava
    é liberada antes de abrir o navegador (a execução em si roda em
    paralelo)."""

    class Meta:
        verbose_name = "Trava da fila do RPA EACE"
        verbose_name_plural = "Trava da fila do RPA EACE"


class EstadoRobosRpaEace(models.Model):
    """Linha única (pk=1) que o supervisor dos robôs atualiza a cada ~15 s
    (pedido do usuário, 2026-11-11): capacidade da máquina, limite em vigor
    (com o freio de segurança) e quantos robôs estão rodando - o painel da TV
    e o admin leem daqui (o supervisor roda em outro container)."""

    capacidade_maquina = models.PositiveIntegerField("Capacidade da máquina (robôs)", default=0)
    limite_atual = models.PositiveIntegerField("Limite em vigor (robôs)", default=0)
    teto_manual = models.PositiveIntegerField("Teto manual (RPA_EACE_MAX_ROBOS, 0 = automático)", default=0)
    robos_rodando = models.PositiveIntegerField("Robôs rodando", default=0)
    freio_motivo = models.CharField("Freio de segurança acionado por", max_length=120, blank=True)
    recursos = models.CharField("Recursos da máquina", max_length=200, blank=True)
    atualizado_em = models.DateTimeField("Atualizado em", null=True, blank=True)

    class Meta:
        verbose_name = "Estado dos robôs do RPA EACE"
        verbose_name_plural = "Estado dos robôs do RPA EACE"

    def __str__(self):
        return f"{self.robos_rodando} rodando · limite {self.limite_atual} · capacidade {self.capacidade_maquina}"
