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
    actions = ["clonar_robos"]
    list_display = ("nome", "usuario", "ativo", "atualizado_em")
    list_editable = ("ativo",)
    list_filter = ("ativo",)
    search_fields = ("nome", "usuario")

    def get_urls(self):
        """Painel técnico da fila (pedido do usuário, 2026-11-16): o painel da TV com servidor, limite/freio e o uso
        de memória e processador de cada robô. Dentro do admin: só quem pode ver os robôs."""
        from django.urls import path

        from apps.ri import views_fila_tv

        def protegida(view):
            def com_permissao(request, *args, **kwargs):
                if not self.has_view_permission(request):
                    from django.core.exceptions import PermissionDenied

                    raise PermissionDenied
                return view(request, *args, **kwargs)

            return self.admin_site.admin_view(com_permissao)

        return [
            path("painel-tecnico/", protegida(views_fila_tv.painel_tecnico_view),
                 name="core_roborpaeace_painel_tecnico"),
            path("painel-tecnico/conteudo/", protegida(views_fila_tv.painel_tecnico_conteudo_view),
                 name="core_roborpaeace_painel_tecnico_conteudo"),
            path("painel-tecnico/planilha/", protegida(views_fila_tv.resposta_planilha),
                 name="core_roborpaeace_painel_tecnico_planilha"),
        ] + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        """Mostra no topo da lista quantos robôs a máquina aguenta agora
        (gravado pelo supervisor a cada ~5 s - `EstadoRobosRpaEace`) e o link do painel técnico."""
        from django.contrib import messages
        from django.urls import reverse
        from django.utils.html import format_html

        from .models import EstadoRobosRpaEace

        messages.info(request, format_html(
            'Painel técnico da fila (servidor e uso de memória e processador de cada robô): <a href="{}" '
            'target="_blank" rel="noopener"><b>abrir o painel técnico</b></a>.',
            reverse("admin:core_roborpaeace_painel_tecnico"),
        ))
        estado = EstadoRobosRpaEace.objects.filter(pk=1).first()
        if estado and estado.atualizado_em:
            texto = (
                f"Capacidade da máquina ({estado.recursos}): {estado.capacidade_maquina} robôs em paralelo. "
                f"Limite em vigor: {estado.limite_atual} · rodando agora: {estado.robos_rodando}."
            )
            if estado.teto_manual:
                texto += f" Teto manual (RPA_EACE_MAX_ROBOS): {estado.teto_manual}."
            if estado.freio_motivo:
                messages.warning(request, texto + f" Freio de segurança acionado: {estado.freio_motivo}.")
            else:
                messages.info(request, texto)
        return super().changelist_view(request, extra_context)

    @admin.action(description="Clonar robôs selecionados (mesmo usuário e senha)")
    def clonar_robos(self, request, queryset):
        """Pedido do usuário (2026-11-11): criar mais robôs sem digitar
        usuário e senha de novo. Cada cópia ganha o próximo nome livre
        "Robô N" e nasce INATIVA - ativar na própria lista (coluna Ativo)."""
        criados = []
        for robo in queryset.order_by("pk"):
            numero = RoboRpaEace.objects.count() + 1
            while RoboRpaEace.objects.filter(nome=f"Robô {numero}").exists():
                numero += 1
            copia = RoboRpaEace.objects.create(
                nome=f"Robô {numero}", usuario=robo.usuario, senha=robo.senha, ativo=False,
            )
            criados.append(copia.nome)
        self.message_user(
            request,
            f"Criado(s): {', '.join(criados)} - inativo(s). Marque \"Ativo\" na lista para começar a rodar "
            "(acima do limite em vigor, os demais ficam esperando - veja a capacidade no topo da lista).",
        )
