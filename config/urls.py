from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.core.urls")),
    path("", include("apps.ri.urls")),
]

if settings.DEBUG:
    # Serve os anexos do histórico do RI (FEAT-014) e demais uploads em
    # desenvolvimento; em produção isso é responsabilidade do servidor
    # web/proxy, não do Django (settings.DEBUG já garante isso).
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
