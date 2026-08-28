from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    verbose_name = "Core"

    def ready(self):
        # RN-044 (FEAT-027): conecta os receivers de sincronizacao com o AD
        # ao sinal `user_logged_in` - modulo importavel mesmo sem
        # `USE_AD_AUTH`/`python-ldap` (ver apps/integracoes/ad/ad_sync.py).
        import apps.integracoes.ad.ad_sync  # noqa: F401
