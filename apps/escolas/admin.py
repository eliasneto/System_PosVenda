from django.contrib import admin

from .models import Escola


@admin.register(Escola)
class EscolaAdmin(admin.ModelAdmin):
    list_display = ("inep", "nome", "municipio", "estado", "status_conexao")
    search_fields = ("inep", "nome")
    list_filter = ("status_conexao", "estado")
