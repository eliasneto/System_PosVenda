from django.urls import path

from . import views

urlpatterns = [
    path("mip/", views.mip_inep_view, name="mip_inep"),
    path("mip/<str:inep>/", views.mip_detail_view, name="mip_detail"),
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
]
