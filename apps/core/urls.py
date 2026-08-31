from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("equipamentos/", views.dashboard_equipamentos, name="dashboard_equipamentos"),
    path("relatorios/", views.dashboard_relatorios, name="dashboard_relatorios"),
    path("administrador/usuarios/", views.usuarios_view, name="usuarios"),
    path(
        "administrador/usuarios/<int:usuario_id>/trocar-perfil/",
        views.usuarios_trocar_perfil_view,
        name="usuarios_trocar_perfil",
    ),
    path(
        "administrador/usuarios/<int:usuario_id>/trocar-acesso/",
        views.usuarios_trocar_acesso_view,
        name="usuarios_trocar_acesso",
    ),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="core/login.html", redirect_authenticated_user=True),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
]
