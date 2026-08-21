from django import template

register = template.Library()


@register.filter(name="has_group")
def has_group(user, group_name):
    """Reaproveitado de apps.core.templatetags.auth_extras do
    modulo-posVenda. Mantido para eventual uso futuro de grupos do Django;
    a permissao por perfil deste sistema (RN-004) usa `user.perfil`/
    `user.is_administrador` diretamente."""
    if not user.is_authenticated:
        return False
    return user.groups.filter(name=group_name).exists() or user.is_superuser
