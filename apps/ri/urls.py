from django.urls import path

from . import views

urlpatterns = [
    path("inep/", views.grid_inep_view, name="grid_inep"),
]
