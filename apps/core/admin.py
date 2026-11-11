from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import RoboRpaEace, User


@admin.register(User)
class CoreUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Gerenciador Pos-Venda", {"fields": ("perfil", "acesso_liberado")}),
    )
    list_display = ("username", "email", "perfil", "acesso_liberado", "is_staff", "is_superuser")


class RoboRpaEaceForm(forms.ModelForm):
    """Senha nunca volta para a tela; em branco na edição mantém a atual."""

    senha = forms.CharField(
        label="Senha no portal EACE",
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Na edição, deixe em branco para manter a senha atual.",
    )

    class Meta:
        model = RoboRpaEace
        fields = ("nome", "usuario", "senha", "ativo")

    def clean_senha(self):
        senha = self.cleaned_data.get("senha")
        if senha:
            return senha
        if self.instance.pk:
            return self.instance.senha
        raise forms.ValidationError("Informe a senha do robô no portal EACE.")


@admin.register(RoboRpaEace)
class RoboRpaEaceAdmin(admin.ModelAdmin):
    """ADR-009 (pedido do usuário, 2026-11-10): cada robô ativo é 1
    processo próprio do RPA EACE (navegador e login próprios), rodando em
    paralelo com os outros na mesma fila. Sem nenhum ativo, roda 1 robô com
    o login do .env. Robô que já trabalhou não pode ser excluído - desative."""

    form = RoboRpaEaceForm
    list_display = ("nome", "usuario", "ativo", "atualizado_em")
    list_editable = ("ativo",)
    list_filter = ("ativo",)
    search_fields = ("nome", "usuario")
