from django.urls import path

from . import views

urlpatterns = [
    path("automacoes-ixc/login-enderecos/", views.login_enderecos_view, name="ixc_login_enderecos"),
    path("automacoes-ixc/atendimentos/", views.atendimentos_view, name="ixc_atendimentos"),
    path("automacoes-ixc/<str:tipo>/modelo/", views.ixc_baixar_modelo_view, name="ixc_baixar_modelo"),
    path("automacoes-ixc/<str:tipo>/<int:slot>/upload/", views.ixc_upload_view, name="ixc_upload"),
    path("automacoes-ixc/execucao/<int:pk>/iniciar/", views.ixc_iniciar_view, name="ixc_iniciar"),
    path("automacoes-ixc/execucao/<int:pk>/status/", views.ixc_status_execucao_view, name="ixc_status"),
    path("automacoes-ixc/execucao/<int:pk>/parar/", views.ixc_parar_view, name="ixc_parar"),
    path("automacoes-ixc/execucao/<int:pk>/saida/", views.ixc_baixar_saida_view, name="ixc_baixar_saida"),
]
