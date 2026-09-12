from django.contrib import messages
from django.shortcuts import redirect, render
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


# RN-093/FEAT-040: usuário Visualizador só acessa Projeto > Equipamentos
# (grid_inep + ri_detail), somente leitura — qualquer outra rota, ou um
# POST/PUT/DELETE nessas duas, é bloqueado aqui, antes da view rodar (a
# tela em si já esconde os controles de edição/Status/Responsável/logs/
# RPA; isto é o reforço técnico, RN-093). Mesmo padrão de
# AcessoLiberadoMiddleware acima (resolve a URL manualmente).
#
# RN-096 (nova, a formalizar pelo Orquestrador em business_rules.md;
# pedido do usuário, 2026-09-12): Visualizador ganha também Projeto > MIP
# (mip_inep + mip_detail), mesma regra de só leitura (GET) das 2 rotas
# acima — os templates escondem os valores financeiros e os controles de
# edição (Status (MIP), lançamento de equipamento só valor de serviço)
# para esse perfil; aqui é só o reforço técnico de acesso, igual ao
# padrão já usado para grid_inep/ri_detail.
_URL_NAMES_VISUALIZADOR = {"grid_inep", "ri_detail", "mip_inep", "mip_detail"}


class VisualizadorAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        usuario = getattr(request, "user", None)
        if usuario is not None and usuario.is_authenticated and usuario.is_visualizador:
            if not request.path.startswith(_PREFIXOS_ISENTOS):
                try:
                    url_name = resolve(request.path_info).url_name
                except Resolver404:
                    url_name = None
                permitido = url_name in _URL_NAMES_ISENTOS or (
                    url_name in _URL_NAMES_VISUALIZADOR and request.method == "GET"
                )
                if url_name is not None and not permitido:
                    messages.error(
                        request,
                        "Usuário Visualizador só pode visualizar Projeto > Equipamentos.",
                    )
                    return redirect("grid_inep")
        return self.get_response(request)
