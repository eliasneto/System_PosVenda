from django.contrib import admin

from .models import Auditoria


@admin.register(Auditoria)
class AuditoriaAdmin(admin.ModelAdmin):
    list_display = ("acao", "usuario", "entidade", "entidade_id", "criado_em")
    list_filter = ("acao",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
