from django.shortcuts import render
from django.urls import Resolver404, resolve

# FEAT-029/RN-045: usuário Desligado (`acesso_liberado=False`) loga
# normalmente e vê o menu, mas nenhuma tela com dado do projeto renderiza
# informação — nem as do próprio menu "Administrador" (Planilha EACE,
# Usuários). Não bloqueia login/logout (senão ninguém entraria) nem o
# `/admin/` do Django (ferramenta do superusuário, já isolada por
# permissão própria — `is_staff`); esses ficam de fora por nome de rota ou
# prefixo de caminho, verificados antes de resolver a view.
_URL_NAMES_ISENTOS = {"login", "logout"}
_PREFIXOS_ISENTOS = ("/admin/", "/static/", "/media/")


class AcessoLiberadoMiddleware:
    """Aplicado a todas as rotas autenticadas (`config/settings.py`,
    depois de `AuthenticationMiddleware`, que preenche `request.user`).
    Resolve a URL manualmente, em vez de esperar `request.resolver_match`
    — neste ponto do processamento a view ainda não foi despachada."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        usuario = getattr(request, "user", None)
        if usuario is not None and usuario.is_authenticated and not usuario.acesso_liberado:
            if not request.path.startswith(_PREFIXOS_ISENTOS):
                try:
                    url_name = resolve(request.path_info).url_name
                except Resolver404:
                    url_name = None
                if url_name not in _URL_NAMES_ISENTOS:
                    return render(request, "core/acesso_bloqueado.html", status=200)
        return self.get_response(request)
