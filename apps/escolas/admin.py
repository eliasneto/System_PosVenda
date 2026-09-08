from django.contrib import admin

from .models import Escola, PlanilhaRelatorioEaceMip


@admin.register(Escola)
class EscolaAdmin(admin.ModelAdmin):
    list_display = ("inep", "nome", "municipio", "estado", "status_conexao", "cod_fornecedor")
    search_fields = ("inep", "nome")
    list_filter = ("status_conexao", "estado")


@admin.register(PlanilhaRelatorioEaceMip)
class PlanilhaRelatorioEaceMipAdmin(admin.ModelAdmin):
    """FEAT-034 (pendência): só leitura por aqui — o upload/substituição é
    feito pela tela "Administrador > Relatório EACE (MIP)", que já
    garante o singleton (no máximo 1 registro ativo)."""

    list_display = ("nome_original", "data_inicial", "data_final", "enviado_por", "enviado_em")
    readonly_fields = ("nome_original", "data_inicial", "data_final", "enviado_por", "enviado_em")

    def has_add_permission(self, request):
        return False
