from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from apps.ri.services import (
    montar_dashboard_equipamentos,
    montar_dashboard_financeiro,
    montar_faturamento_por_estado,
    montar_faturamento_por_municipio,
    montar_kits_instalados_por_estado,
    montar_produtos_complementares_por_estado,
)

from .models import User


@login_required
def home(request):
    """FEAT-026 (RN-025/RN-026): dashboard financeiro do projeto — submenu
    "Faturamento" (pedido do usuário, 2026-08-27: dashboard ganha 3
    submenus — Faturamento, Equipamentos e Relatórios).

    RN-027 (ampliação, 2026-08-27): `?estado=UF` filtra os 2 cards por
    estado — mesmo clique de uma linha do gráfico "Faturado por Estado".
    O mesmo gráfico expande (dentro do card, mesma informação) mostrando
    os Municípios daquele estado; `?estado=UF&municipio=Nome` filtra os 2
    cards mais 1 nível. Município só é aplicado com estado informado
    (nome se repete entre UFs diferentes).

    `?kit=Descrição`/`?produto=Descrição` (ampliação, 2026-08-28, pedido
    do usuário — navegação cruzada vinda do dashboard Equipamentos, "Ver
    Faturamento de UF"): restringe os 2 cards a só aquele Kit/Equipamento
    Complementar — usuário reportou que o valor tinha que ser "referente
    aquele filtro", não o valor geral do estado. Com `produto` (sem meta,
    RN-025 não se aplica), o Card 1 e o gráfico "Faturado por Estado"/
    "por Município" somem — só o Card 2 (Valor Faturado) faz sentido.
    `kit`/`produto` nunca vêm juntos (mutuamente exclusivos na origem).

    `href`/`rotulo`/`selecionado` de cada linha são montados aqui (não no
    service, que fica só com o cálculo) para o template
    `core/_linha_faturamento.html` renderizar sem lógica de URL."""
    estado = (request.GET.get("estado") or "").strip().upper()[:2] or None
    municipio = (request.GET.get("municipio") or "").strip()[:150] or None
    kit = (request.GET.get("kit") or "").strip()[:255] or None
    produto = (request.GET.get("produto") or "").strip()[:255] or None
    if not estado:
        municipio = None

    contexto = montar_dashboard_financeiro(estado=estado, municipio=municipio, kit=kit, produto=produto)

    # Os gráficos "Faturado por Estado"/"por Município" comparam vários
    # estados/municípios ao mesmo tempo — não fazem sentido já filtrados
    # por 1 Kit/Equipamento específico (o Card 2 sozinho já mostra esse
    # valor), por isso só são montados sem kit/produto.
    if not kit and not produto:
        linhas_estado = montar_faturamento_por_estado()
        for linha in linhas_estado:
            linha["href"] = f"?{urlencode({'estado': linha['estado']})}"
            linha["rotulo"] = linha["estado"]
            linha["selecionado"] = linha["estado"] == estado
        contexto["faturamento_por_estado"] = linhas_estado

        linhas_municipio = montar_faturamento_por_municipio(estado) if estado else []
        for linha in linhas_municipio:
            linha["href"] = f"?{urlencode({'estado': estado, 'municipio': linha['municipio']})}"
            linha["rotulo"] = linha["municipio"]
            linha["selecionado"] = linha["municipio"] == municipio
        contexto["faturamento_por_municipio"] = linhas_municipio
    else:
        contexto["faturamento_por_estado"] = []
        contexto["faturamento_por_municipio"] = []

    # Texto dos 2 cards ("de todas as escolas" / "do projeto" vs. o recorte
    # filtrado) — montado aqui para o template não empilhar `{% if %}` por
    # combinação de estado/município.
    if municipio:
        contexto["recorte_label"] = f"{municipio}/{estado}"
    elif estado:
        contexto["recorte_label"] = estado
    else:
        contexto["recorte_label"] = None

    # "Ver Faturamento geral" (ampliação, 2026-08-28) limpa kit/produto,
    # preservando estado/município — inverso do link que trouxe o usuário
    # de Equipamentos até aqui.
    contexto["limpar_kit_produto_href"] = (
        f"?{urlencode({k: v for k, v in {'estado': estado, 'municipio': municipio}.items() if v})}"
    )

    return render(request, "core/home.html", contexto)


@login_required
def dashboard_equipamentos(request):
    """FEAT-026: submenu "Equipamentos" do dashboard — cards "Kits
    Programados", "Kits Instalados" e "Nobreaks Programados" (pedido do
    usuário, 2026-08-28, em cards separados por serem unidades de
    natureza diferente), com detalhamento dos Kits por Equipamento, o
    bloco "Equipamentos Complementares" e o gráfico "Kits Instalados por
    Estado" (mesmo padrão do gráfico "Faturado por Estado" em `home`).
    Critério de aceite ainda não formalizado em business_rules.md/
    checklist.md (ver nota para o Orquestrador).

    3 filtros independentes e combináveis, todos por clique numa linha
    (ampliação, 2026-08-28, pedido do usuário — mesmo padrão de clique já
    usado no gráfico por estado):
    - `?estado=UF`: clique numa linha do gráfico "Kits Instalados por
      Estado".
    - `?kit=Descrição`: clique numa linha de "Kits por Equipamento" —
      restringe os 3 cards, o próprio detalhamento e o gráfico por estado
      a só aquele tipo de Kit.
    - `?produto=Descrição`: clique numa linha de "Equipamentos
      Complementares" — restringe aquele bloco e revela o gráfico
      "Equipamentos Complementares por Estado" (ampliação, 2026-08-28,
      pedido do usuário: "preciso saber o estado que está aquele
      equipamento") — não afeta Kit/Nobreak, que são eixos independentes.

    Cada "Ver todos os X" limpa só o próprio filtro, preservando os
    outros 2 — por isso os hrefs de limpeza são montados aqui (não no
    service, que fica só com o cálculo). Clicar numa linha do gráfico por
    estado (do Kit ou do Equipamento Complementar) define `estado`, que
    já dispara o link cruzado "Ver Faturamento de UF" — é ali que o
    usuário vê o valor faturado daquele estado (pedido do usuário: "o
    valor no filtro de faturamento")."""
    estado = (request.GET.get("estado") or "").strip().upper()[:2] or None
    kit = (request.GET.get("kit") or "").strip()[:255] or None
    produto = (request.GET.get("produto") or "").strip()[:255] or None
    contexto = montar_dashboard_equipamentos(estado=estado, kit=kit, produto=produto)

    # Cada "Ver todos os X" preserva os outros 2 filtros — 3 eixos
    # independentes, diferente do estado/município do Faturamento (onde
    # município depende do estado). Calculados antes das linhas abaixo:
    # clicar numa linha já selecionada usa o mesmo href pra "desclicar"
    # (toggle), em vez de recarregar a mesma página sem efeito.
    limpar_estado_href = f"?{urlencode({k: v for k, v in {'kit': kit, 'produto': produto}.items() if v})}"
    limpar_kit_href = f"?{urlencode({k: v for k, v in {'estado': estado, 'produto': produto}.items() if v})}"
    limpar_produto_href = f"?{urlencode({k: v for k, v in {'estado': estado, 'kit': kit}.items() if v})}"
    contexto["limpar_estado_href"] = limpar_estado_href
    contexto["limpar_kit_href"] = limpar_kit_href
    contexto["limpar_produto_href"] = limpar_produto_href

    linhas_estado = montar_kits_instalados_por_estado(kit=kit)
    for linha in linhas_estado:
        selecionado = linha["estado"] == estado
        if selecionado:
            linha["href"] = limpar_estado_href
        else:
            params_linha = {"estado": linha["estado"]}
            if kit:
                params_linha["kit"] = kit
            linha["href"] = f"?{urlencode(params_linha)}"
        linha["rotulo"] = linha["estado"]
        linha["selecionado"] = selecionado
    contexto["kits_instalados_por_estado"] = linhas_estado

    for item in contexto["kits_por_produto"]:
        selecionado = item["descricao_item"] == kit
        if selecionado:
            item["href"] = limpar_kit_href
        else:
            params_item = {"kit": item["descricao_item"]}
            if estado:
                params_item["estado"] = estado
            item["href"] = f"?{urlencode(params_item)}"
        item["selecionado"] = selecionado

    for item in contexto["produtos_complementares"]:
        selecionado = item["descricao_item"] == produto
        if selecionado:
            item["href"] = limpar_produto_href
        else:
            # Correção (2026-08-28, reportada pelo usuário): trocar de
            # Equipamento Complementar NÃO carrega o estado que estava
            # selecionado — esse estado veio da distribuição do
            # equipamento ANTERIOR (ex.: "Rack 7U" em RJ) e pode não
            # dizer nada sobre o equipamento novo (ex.: "Switch" pode nem
            # existir em RJ). Cada equipamento começa do zero, mostrando
            # a própria distribuição por estado inteira.
            item["href"] = f"?{urlencode({'produto': item['descricao_item']})}"
        item["selecionado"] = selecionado

    # Gráfico "Equipamentos Complementares por Estado" (ampliação,
    # 2026-08-28, pedido do usuário) — só existe com 1 Equipamento
    # Complementar selecionado (ver docstring do service). Clicar numa
    # linha define `estado`, preservando `produto` — mesmo padrão de
    # combinação do gráfico de Kits.
    linhas_produto_estado = montar_produtos_complementares_por_estado(produto)
    for linha in linhas_produto_estado:
        selecionado = linha["estado"] == estado
        if selecionado:
            linha["href"] = limpar_estado_href
        else:
            params_linha = {"produto": produto, "estado": linha["estado"]}
            linha["href"] = f"?{urlencode(params_linha)}"
        linha["selecionado"] = selecionado
    contexto["produtos_complementares_por_estado"] = linhas_produto_estado

    # Navegação cruzada pro Faturamento (ampliação, 2026-08-28, pedido do
    # usuário: "o financeiro tem que trazer os valores referente aquele
    # filtro") — carrega kit/produto além do estado, pro Faturamento
    # mostrar o valor daquele Kit/Equipamento específico, não o valor
    # geral do estado. Só existe com estado selecionado (Faturamento não
    # filtra por Kit/Equipamento sem um estado — mesma exigência de
    # município no próprio Faturamento, RN-027).
    if estado:
        params_faturamento = {"estado": estado}
        if kit:
            params_faturamento["kit"] = kit
        elif produto:
            params_faturamento["produto"] = produto
        contexto["ver_faturamento_href"] = f"{urlencode(params_faturamento)}"

    return render(request, "core/dashboard_equipamentos.html", contexto)


@login_required
def dashboard_relatorios(request):
    """FEAT-026: submenu "Relatórios" do dashboard — placeholder, sem
    critério de aceite definido ainda (Orquestrador/usuário)."""
    return render(request, "core/dashboard_relatorios.html")


@login_required
def usuarios_view(request):
    """FEAT-028 (RN-004 ampliada): tela "Administrador > Usuários" — lista
    os usuários do sistema e permite trocar o perfil (Administrador ↔
    Analista) de qualquer usuário, exceto o próprio. Escopo mínimo,
    confirmado com o usuário: só listar e trocar perfil — criar usuário,
    editar username/e-mail e ativar/desativar continuam só pelo `/admin/`
    do Django. Ação restrita a Administrador, mesmo critério das demais
    ações administrativas (RN-004)."""
    if not request.user.is_administrador:
        return HttpResponseForbidden("Somente Administrador pode acessar esta tela.")

    usuarios = User.objects.all().order_by("username")
    return render(request, "core/usuarios.html", {"usuarios": usuarios})


@login_required
def usuarios_trocar_perfil_view(request, usuario_id):
    """FEAT-028 (RN-004 ampliada): alterna o perfil de outro usuário entre
    Administrador e Analista. Bloqueia a troca do próprio perfil — evita o
    Administrador se autorrebaixar sem ter outro Administrador por perto
    para reverter (decisão do Orquestrador, opção mais conservadora)."""
    if not request.user.is_administrador:
        return HttpResponseForbidden("Somente Administrador pode acessar esta tela.")
    if request.method != "POST":
        return redirect("usuarios")

    usuario = get_object_or_404(User, pk=usuario_id)
    if usuario_id == request.user.id:
        messages.error(request, "Você não pode trocar o próprio perfil por esta tela.")
        return redirect("usuarios")

    usuario.perfil = (
        User.PERFIL_ANALISTA if usuario.perfil == User.PERFIL_ADMINISTRADOR else User.PERFIL_ADMINISTRADOR
    )
    usuario.save(update_fields=["perfil"])
    messages.success(request, f"Perfil de {usuario.username} alterado para {usuario.get_perfil_display()}.")
    return redirect("usuarios")


@login_required
def usuarios_trocar_acesso_view(request, usuario_id):
    """FEAT-029/RN-045: liga/desliga o acesso de outro usuário aos dados
    do projeto — controle independente do perfil (vale também para
    Administrador). Mesmo bloqueio de autotroca da troca de perfil
    (FEAT-028): evita o Administrador se desligar sem ter outro
    Administrador já Ligado por perto para reverter."""
    if not request.user.is_administrador:
        return HttpResponseForbidden("Somente Administrador pode acessar esta tela.")
    if request.method != "POST":
        return redirect("usuarios")

    usuario = get_object_or_404(User, pk=usuario_id)
    if usuario_id == request.user.id:
        messages.error(request, "Você não pode ligar/desligar o próprio acesso por esta tela.")
        return redirect("usuarios")

    usuario.acesso_liberado = not usuario.acesso_liberado
    usuario.save(update_fields=["acesso_liberado"])
    situacao = "Ligado" if usuario.acesso_liberado else "Desligado"
    messages.success(request, f"Acesso de {usuario.username} alterado para {situacao}.")
    return redirect("usuarios")
