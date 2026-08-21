from django.contrib import admin

from .models import Documento, EmailFinanceiroLog, Ri, RiDivergencia, RiItemEace, RiItemIxc


@admin.register(Ri)
class RiAdmin(admin.ModelAdmin):
    list_display = ("id", "escola", "status", "responsavel", "atualizado_em")
    list_filter = ("status",)
    search_fields = ("escola__inep", "escola__nome")


admin.site.register(RiItemEace)
admin.site.register(RiItemIxc)
admin.site.register(RiDivergencia)
admin.site.register(Documento)
admin.site.register(EmailFinanceiroLog)
