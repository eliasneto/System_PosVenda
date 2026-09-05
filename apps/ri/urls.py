from django.urls import path

from . import views

urlpatterns = [
    path("inep/", views.grid_inep_view, name="grid_inep"),
    path("administrador/planilha-eace/", views.planilha_eace_view, name="planilha_eace"),
    path(
        "administrador/planilha-eace/sincronizar-todas/",
        views.planilha_eace_sincronizar_todas_view,
        name="planilha_eace_sincronizar_todas",
    ),
    path("inep/<str:inep>/", views.ri_detail_view, name="ri_detail"),
    path("inep/<str:inep>/iniciar/", views.ri_iniciar_view, name="ri_iniciar"),
    path("ri/<int:pk>/status/", views.ri_status_update_view, name="ri_status_update"),
    path(
        "ri/<int:pk>/responsavel/",
        views.ri_responsavel_update_view,
        name="ri_responsavel_update",
    ),
    path(
        "ri/<int:pk>/financeiro/enviar/",
        views.ri_enviar_email_financeiro_view,
        name="ri_enviar_email_financeiro",
    ),
    path(
        "ri/<int:pk>/financeiro/planilha/",
        views.ri_baixar_planilha_financeiro_view,
        name="ri_baixar_planilha_financeiro",
    ),
    path(
        "ri/itens/ixc/<int:item_pk>/editar/",
        views.ri_item_ixc_update_view,
        name="ri_item_ixc_update",
    ),
    path(
        "ri/itens/ixc/<int:item_pk>/excluir/",
        views.ri_item_ixc_delete_view,
        name="ri_item_ixc_delete",
    ),
    path(
        "ri/itens/relatorio-eace/<int:item_pk>/editar/",
        views.ri_item_relatorio_eace_update_view,
        name="ri_item_relatorio_eace_update",
    ),
    path(
        "ri/itens/relatorio-eace/<int:item_pk>/excluir/",
        views.ri_item_relatorio_eace_delete_view,
        name="ri_item_relatorio_eace_delete",
    ),
    path(
        "ri/logs-rpa-eace/<int:pk>/disparar/",
        views.ri_log_rpa_eace_disparar_view,
        name="ri_log_rpa_eace_disparar",
    ),
    path(
        "ri/logs-rpa-eace/<int:pk>/marcar-manual/",
        views.ri_log_rpa_eace_marcar_manual_view,
        name="ri_log_rpa_eace_marcar_manual",
    ),
    path(
        "inep/<str:inep>/logs-rpa-eace/status/",
        views.ri_logs_rpa_eace_status_view,
        name="ri_logs_rpa_eace_status",
    ),
    path(
        "ri/<int:pk>/pendencias-portal-eace/consultar/",
        views.ri_consultar_pendencias_eace_view,
        name="ri_consultar_pendencias_eace",
    ),
]
