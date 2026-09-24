from django.urls import path

from . import views

urlpatterns = [
    path("mip/", views.mip_inep_view, name="mip_inep"),
    path("mip/lote/", views.mip_lote_inep_view, name="mip_lote_inep"),
    path("mip/lote/criar/", views.mip_lote_criar_view, name="mip_lote_criar"),
    # e-mail do LOTE comentado (pedido do usuário, 2026-09-15) — ver apps.escolas.views.mip_lote_enviar_email_view
    # path("mip/lote/<int:pk>/enviar-email/", views.mip_lote_enviar_email_view, name="mip_lote_enviar_email"),
    path(
        "mip/lote/<int:pk>/baixar-planilha/",
        views.mip_lote_baixar_planilha_view,
        name="mip_lote_baixar_planilha",
    ),
    path(
        "mip/lote/baixar-planilhas-zip/",
        views.mip_lote_baixar_planilhas_zip_view,
        name="mip_lote_baixar_planilhas_zip",
    ),
    path("mip/lote/<int:pk>/status/", views.mip_lote_status_update_view, name="mip_lote_status_update"),
    path("mip/lote/<int:pk>/desfazer/", views.mip_lote_desfazer_view, name="mip_lote_desfazer"),
    path(
        "mip/lote/<int:pk>/notas-fiscais/",
        views.mip_lote_notas_fiscais_upload_view,
        name="mip_lote_notas_fiscais_upload",
    ),
    path("mip/<str:inep>/", views.mip_detail_view, name="mip_detail"),
    path("mip/<str:inep>/status/", views.mip_status_update_view, name="mip_status_update"),
    path(
        "mip/<str:inep>/lado-ixc/servico/salvar/",
        views.mip_item_ixc_somente_servico_salvar_view,
        name="mip_item_ixc_somente_servico_salvar",
    ),
    path(
        "mip/lado-ixc/servico/<int:item_pk>/excluir/",
        views.mip_item_ixc_somente_servico_delete_view,
        name="mip_item_ixc_somente_servico_delete",
    ),
    path(
        "administrador/relatorio-eace-mip/",
        views.relatorio_eace_mip_view,
        name="relatorio_eace_mip",
    ),
    path(
        "administrador/relatorio-eace-mip/sincronizar-todas/",
        views.relatorio_eace_mip_sincronizar_todas_view,
        name="relatorio_eace_mip_sincronizar_todas",
    ),
    path(
        "administrador/relatorio-eace-mip/notas-fiscais/",
        views.relatorio_eace_mip_notas_fiscais_upload_view,
        name="relatorio_eace_mip_notas_fiscais_upload",
    ),
    path(
        "administrador/relatorio-eace-mip/notas-fiscais/sincronizar/",
        views.relatorio_eace_mip_notas_fiscais_sincronizar_view,
        name="relatorio_eace_mip_notas_fiscais_sincronizar",
    ),
]
