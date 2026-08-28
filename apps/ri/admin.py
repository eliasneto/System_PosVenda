from django.contrib import admin

from .models import (
    Documento,
    EmailFinanceiroLog,
    EmailFinanceiroSync,
    KitPadrao,
    PlanilhaEace,
    Ri,
    RiDivergencia,
    RiHistorico,
    RiItemEace,
    RiItemIxc,
    RiItemRelatorioEace,
)


@admin.register(Ri)
class RiAdmin(admin.ModelAdmin):
    list_display = ("id", "escola", "status", "responsavel", "atualizado_em")
    list_filter = ("status",)
    search_fields = ("escola__inep", "escola__nome")


@admin.register(KitPadrao)
class KitPadraoAdmin(admin.ModelAdmin):
    """RN-010: catálogo de valores fixos por kit, cruzado com o Kit
    declarado (1º lado do RI) pela descrição e pelo Lote."""

    list_display = (
        "descricao", "descricao_curta", "aba_planilha_financeiro", "numero_access_points",
        "lote", "unidade", "valor_equipamento", "valor_servico", "valor_total", "atualizado_em",
    )
    # RN-013: campo editável direto na listagem — cadastro em lote da aba
    # da planilha de faturamento para os produtos já importados da LPU.
    list_editable = ("aba_planilha_financeiro",)
    list_filter = ("lote", "unidade")
    search_fields = ("descricao", "descricao_curta")


@admin.register(PlanilhaEace)
class PlanilhaEaceAdmin(admin.ModelAdmin):
    """RN-021: só leitura por aqui — o upload/substituição é feito pela
    tela "Administrador > Planilha EACE" (FEAT-023), que já garante o
    singleton (no máximo 1 registro ativo)."""

    list_display = ("nome_original", "enviado_por", "enviado_em")
    readonly_fields = ("nome_original", "enviado_por", "enviado_em")

    def has_add_permission(self, request):
        return False


admin.site.register(RiItemEace)
admin.site.register(RiItemIxc)
admin.site.register(RiItemRelatorioEace)
admin.site.register(RiDivergencia)
admin.site.register(Documento)
admin.site.register(EmailFinanceiroLog)
admin.site.register(EmailFinanceiroSync)
admin.site.register(RiHistorico)
