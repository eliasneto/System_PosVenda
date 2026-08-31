from django.apps import AppConfig


class AuditoriaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.auditoria"
    verbose_name = "Auditoria"

    def ready(self):
        # RN-006/FEAT-011: conecta o receiver de login (`user_logged_in`)
        # ao registro de auditoria.
        import apps.auditoria.signals  # noqa: F401
