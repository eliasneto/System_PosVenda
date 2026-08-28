from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CoreUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Gerenciador Pos-Venda", {"fields": ("perfil", "acesso_liberado")}),
    )
    list_display = ("username", "email", "perfil", "acesso_liberado", "is_staff", "is_superuser")
