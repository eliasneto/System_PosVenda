from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    def create_user(self, username, email=None, password=None, **extra_fields):
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
    campo `perfil` acrescentado para os dois perfis fixos deste sistema
    (RN-004): Administrador (tudo) e Analista (tudo, exceto excluir)."""

    PERFIL_ADMINISTRADOR = "administrador"
    PERFIL_ANALISTA = "analista"
    PERFIL_CHOICES = [
        (PERFIL_ADMINISTRADOR, "Administrador"),
        (PERFIL_ANALISTA, "Analista"),
    ]

    username = models.CharField("Usuario", max_length=150, unique=True)
    email = models.EmailField("Endereco de E-mail", unique=True, blank=True, null=True)
    perfil = models.CharField(
        "Perfil", max_length=20, choices=PERFIL_CHOICES, default=PERFIL_ANALISTA
    )

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
