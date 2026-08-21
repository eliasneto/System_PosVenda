from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CoreUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Gerenciador Pos-Venda", {"fields": ("perfil",)}),
    )
    list_display = ("username", "email", "perfil", "is_staff", "is_superuser")
