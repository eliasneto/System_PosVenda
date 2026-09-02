from datetime import timedelta
from decimal import Decimal
from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.core.mail import EmailMessage
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache

from apps.auditoria.models import Auditoria
from apps.auditoria.services import registrar as auditar
from apps.core.email_tracking import montar_assunto_com_codigo, montar_codigo_rastreio
from apps.escolas.models import Escola

from .forms import (
    PlanilhaEaceUploadForm,
    RiDataAtivacaoForm,
    RiEmailFinanceiroForm,
    RiHistoricoForm,
    RiItemIxcForm,
    RiItemIxcKitForm,
    RiItemIxcProdutoFormSet,
    RiItemRelatorioEaceForm,
    RiItemRelatorioEaceKitForm,
    RiItemRelatorioEaceProdutoFormSet,
)
from .models import (
    EmailFinanceiroLog,
    KitPadrao,
    PlanilhaEace,
    Ri,
    RiHistorico,
    RiItemIxc,
    RiItemRelatorioEace,
)
from .services import (
    RI_BLOQUEADO_FATURAMENTO_CONCLUIDO,
    RI_SEM_LINHA_NA_PLANILHA,
    PlanilhaEaceSincronizacaoError,
    PlanilhaFaturamentoError,
    comparar_kit_e_produtos_ixc_relatorio,
    comparar_status_escola_relatorio,
    gerar_planilha_faturamento,
    montar_corpo_email_financeiro,
    nome_arquivo_planilha_faturamento,
    sincronizar_divergencia_kit_relatorio,
    # FEAT-024/RN-022: Sincronizador do Lado Relatório EACE a partir da
    # Planilha EACE (RN-021), casada com o catálogo pelo INEP.
    sincronizar_relatorio_eace_da_planilha,
    # FEAT-025/RN-023: mesmo Sincronizador aplicado ao RI atual de cada
    # Escola de uma vez, a partir do card "Arquivo ativo".
    sincronizar_relatorio_eace_de_todas_as_ri,
    trocar_status_com_log,
    # RN-018: mesma resolução de preço por catálogo já usada na planilha de
    # faturamento (RN-013) — reaproveitada aqui para o Valor Unitário do
    # Lado Relatório EACE, que (diferente do Lado IXC) precisa de um valor
    # real, não 0,00.
    _resolver_catalogo_ixc,
    # RN-051 (2026-09-02): mesma checagem usada por `gerar_planilha_
    # faturamento` — reaproveitada aqui para decidir se a opção de status
    # "Envio de Email para Faturamento" pode aparecer na tela de detalhe.
    itens_faltando_para_planilha_faturamento,
)

User = get_user_model()

# RF-16/17/18 e architecture.md ("Fluxo de e-mail com o financeiro"):
# destinatários fixos, nunca em lote — 1 e-mail por INEP.
DESTINATARIOS_FINANCEIRO = ["hilber.lustosa@speedcsc.com.br", "financeiro@speedcsc.com.br"]
COPIA_FINANCEIRO = [
    "logistica-l@speedcsc.com.br",
    "posvendas@megainfraestrutura.com.br",
    "david.alves@speedcsc.com.br",
]

# RN-001: só estes status são trocados manualmente pelo usuário. Fora daqui
# ficam "Implantação EACE" (só nasce assim, ninguém troca para ele) e os dois
# automáticos ("Aguardando financeiro", "Resposta Financeiro" — quem troca é
# o sistema, ver seção 5 dos requisitos).
STATUS_RI_MANUAIS = [
    Ri.ANDAMENTO,
    Ri.ENVIO_EMAIL_FATURAMENTO,
    Ri.AGUARDANDO_VALIDACAO_EACE,
    Ri.FATURAMENTO_CONCLUIDO,
    Ri.CORRECAO_MEGA,
]

# Par (valor, rótulo) só dos status manuais acima — usado tanto pelo grid
# (FEAT-007) quanto pela resposta HTMX de `ri_status_update_view`
# (FEAT-019), para os dois montarem o mesmo <select>.
STATUS_RI_EDITAVEIS = [
    (valor, rotulo) for valor, rotulo in Ri.STATUS_CHOICES if valor in STATUS_RI_MANUAIS
]

# RN-008 (2026-08-26): tamanho da página da linha do tempo do RI — pedido
# do usuário para não carregar o histórico inteiro de uma vez.
HISTORICO_ITENS_POR_PAGINA = 10

# RN-020 (2026-08-27): com o RI em "Faturamento Concluído", os campos do
# Lado IXC e do Lado Relatório EACE ficam bloqueados para os dois perfis —
# mensagem única reaproveitada por toda view que mexe nesses dois lados.
MENSAGEM_BLOQUEIO_FATURAMENTO_CONCLUIDO = (
    'RI em "Faturamento Concluído" — os campos do Lado Relatório EACE '
    "ficam bloqueados até o Administrador trocar o status (RN-020)."
)

# RN-052 (2026-09-02): Lado IXC só é editável com o RI em "Em Andamento" —
# mensagem única reaproveitada por toda view que mexe nesse lado.
MENSAGEM_LADO_IXC_SOMENTE_LEITURA = (
    'Os campos do Lado IXC só são editáveis com o RI em "Em Andamento" (RN-052).'
)


def _assunto_sugerido_email(escola, hoje):
    """FEAT-008 (RN-009/RN-050): assunto sugerido do e-mail ao financeiro
    — código de rastreio + INEP + nome da escola. Reaproveitado pelo grid
    (RF-05) e pela tela de detalhe do RI (RN-051), para os dois montarem
    o mesmo texto."""
    codigo = montar_codigo_rastreio(escola.inep, hoje)
    return montar_assunto_com_codigo(codigo, f"Faturamento EACE — INEP {escola.inep} — {escola.nome}")


def _pronto_para_envio_email_financeiro(ri):
    """RN-051 (2026-09-02): True quando o RI pode ir para "Envio de Email
    para Faturamento" hoje — mesma regra usada por `_validar_transicao_
    status_ri` (divergência aberta bloqueante + pré-requisitos da
    planilha de faturamento, RN-013). Usada pela tela de detalhe do RI
    para decidir se essa opção aparece no <select> de status — sem
    esconder, o usuário poderia escolher um destino que o backend ia
    recusar de qualquer forma."""
    if ri.divergencias.filter(resolvida_em__isnull=True, bloqueia=True).exists():
        return False
    return not itens_faltando_para_planilha_faturamento(ri)


def _status_ri_opcoes_disponiveis(ri):
    """RN-051 (2026-09-02): opções manuais de status para o <select> da
    tela de detalhe — "Envio de Email para Faturamento" só entra quando
    pronto para envio hoje (`_pronto_para_envio_email_financeiro`) OU
    quando já é o status atual do RI (mantém visível/selecionado mesmo
    que algo tenha mudado depois, ex.: item excluído — mesmo tratamento
    gracioso já usado para status automático em `_status_form.html`)."""
    return [
        (valor, rotulo)
        for valor, rotulo in STATUS_RI_EDITAVEIS
        if valor != Ri.ENVIO_EMAIL_FATURAMENTO
        or ri.status == Ri.ENVIO_EMAIL_FATURAMENTO
        or _pronto_para_envio_email_financeiro(ri)
    ]


def _bloqueado_faturamento_concluido(ri):
    """RN-020: True quando o RI está em "Faturamento Concluído" — os
    campos do Lado Relatório EACE ficam bloqueados para os dois perfis
    (Administrador e Analista) enquanto o RI estiver nesse status; voltam
    a ficar liberados assim que o status muda (só o Administrador troca,
    ver `_validar_transicao_status_ri`). O Lado IXC não usa mais esta
    função — tem regra própria e mais restritiva (RN-052,
    `_lado_ixc_editavel`), que já cobre este status como um dos "qualquer
    outro status" bloqueados."""
    return ri.status == Ri.FATURAMENTO_CONCLUIDO


def _lado_ixc_editavel(ri):
    """RN-052 (2026-09-02): True só quando `ri.status == Ri.ANDAMENTO`
    ("Em Andamento") — os campos do Lado IXC (2º lado: RN-011 KIT
    Instalado + Produtos, RN-014 Município/Estado, RN-048 CNPJ/CNPJ
    Fictício) só são lançados/editados nesse status, para os dois perfis
    (Administrador e Analista); em qualquer outro status (inclusive
    "Faturamento Concluído", que antes tinha bloqueio próprio na RN-020)
    ficam somente leitura — os itens já lançados continuam visíveis, só
    não editáveis/excluíveis. Não afeta o Lado Relatório EACE (RN-020,
    `_bloqueado_faturamento_concluido`, segue valendo sem alteração)."""
    return ri.status == Ri.ANDAMENTO


def _requisicao_htmx(request):
    """FEAT-019: identifica requisição feita pelo HTMX (header enviado
    automaticamente por toda troca `hx-*`) — usado para responder com um
    fragmento (out-of-band) em vez de redirecionar/renderizar a página
    inteira. Sem esse header (JavaScript/HTMX indisponível), o fluxo
    tradicional de POST + redirect continua funcionando sem alteração."""
    return request.headers.get("HX-Request") == "true"


def _validar_transicao_status_ri(ri, novo_status, usuario):
    """RN-001/RN-003: regras já fechadas do ciclo de vida do RI (FEAT-006
    iniciada fora de ordem, ver `checklist.md`). Retorna None se a
    transição for permitida, ou uma mensagem explicando o bloqueio."""
    if ri.status == Ri.FATURAMENTO_CONCLUIDO and not getattr(usuario, "is_administrador", False):
        # RN-020: com o RI em "Faturamento Concluído", só o Administrador
        # troca o status — Analista perde, só nesse status, a opção manual
        # que tem nos demais status editáveis (RN-001). Sai antes de
        # qualquer outra regra, inclusive quando o destino seria permitido.
        return 'Só o Administrador pode alterar o status a partir de "Faturamento Concluído" (RN-020).'
    if novo_status not in STATUS_RI_MANUAIS:
        # RN-019: exceção do Administrador — força a saída de "Aguardando
        # financeiro" direto para "Resposta Financeiro" (mesmo destino do
        # gatilho automático), sem esperar a resposta do financeiro chegar.
        # Analista não tem essa opção, igual aos demais status automáticos.
        if (
            ri.status == Ri.AGUARDANDO_FINANCEIRO
            and novo_status == Ri.AGUARDANDO_ANEXO_PORTAL_EACE
            and getattr(usuario, "is_administrador", False)
        ):
            return None
        return "Esse status só é alterado automaticamente pelo sistema."
    if novo_status == Ri.CORRECAO_MEGA and ri.status != Ri.ANDAMENTO:
        return 'Só é possível marcar "Correção MEGA" a partir de "Em Andamento".'
    if ri.status == Ri.CORRECAO_MEGA and novo_status != Ri.ANDAMENTO:
        return '"Correção MEGA" só retorna manualmente para "Em Andamento".'
    if (
        ri.status == Ri.ANDAMENTO
        and novo_status == Ri.ENVIO_EMAIL_FATURAMENTO
        and ri.divergencias.filter(resolvida_em__isnull=True, bloqueia=True).exists()
    ):
        return "Bloqueado: há divergência aberta que impede o envio ao financeiro (RN-003)."
    # RN-051 (2026-09-02) — decisão deliberada, não esquecimento: KIT/Data
    # de Ativação/Município/Estado/CNPJ/CNPJ Fictício NÃO travam esta
    # transição — mesmo espírito da RN-013/RN-014 (esses campos só são
    # exigidos na hora de GERAR a planilha/enviar o e-mail, nunca a cada
    # mudança de status/campo). A tela de detalhe só ESCONDE a opção
    # "Envio de Email para Faturamento" do <select> quando não está pronta
    # (`_status_ri_opcoes_disponiveis`) — não bloqueia aqui, para não
    # repetir o mesmo problema que a RN-014 já corrigiu uma vez (usuário
    # ficando travado por um campo sem relação com a ação que queria
    # fazer). Quem enviar direto por fora da tela (ou com a opção ainda
    # visível de uma checagem desatualizada) esbarra do mesmo jeito no
    # `PlanilhaFaturamentoError` de `gerar_planilha_faturamento`.
    # FEAT-010/RF-10: marcação manual do anexo no portal EACE só a partir
    # de "Resposta Financeiro" — mesmo destino do gatilho automático
    # (RF-19). `FATURAMENTO_CONCLUIDO` também é aceito como origem para
    # não travar a correção do Administrador (RN-020: só ele chega aqui
    # vindo desse status, o guard do início da função já garante isso).
    if novo_status == Ri.AGUARDANDO_VALIDACAO_EACE and ri.status not in (
        Ri.AGUARDANDO_ANEXO_PORTAL_EACE,
        Ri.FATURAMENTO_CONCLUIDO,
    ):
        return 'Só é possível marcar o anexo feito no EACE a partir de "Resposta Financeiro" (RN-001).'
    # FEAT-010/RF-11: conclusão manual só depois da marcação de anexo —
    # "Botão de conclusão só habilitado depois da marcação de anexo"
    # (checklist.md), aqui aplicado como bloqueio de origem, mesmo padrão
    # das demais regras desta função.
    if novo_status == Ri.FATURAMENTO_CONCLUIDO and ri.status != Ri.AGUARDANDO_VALIDACAO_EACE:
        return 'Só é possível concluir o faturamento a partir de "Aguardando validação EACE" (RN-001).'
    return None


def _nome_usuario(usuario):
    """RN-012: rótulo de exibição do responsável (nome completo, ou
    username quando o usuário não tem nome cadastrado; "Não atribuído"
    quando o RI ainda não tem responsável)."""
    if not usuario:
        return "Não atribuído"
    return usuario.get_full_name() or usuario.username


def _registrar_log_campo(ri, usuario, campo, valor_anterior, valor_novo):
    """RN-008 (esclarecida em 2026-08-26): grava uma entrada de log
    automático — cadastro ou alteração de campo — na linha do tempo do RI.
    Reaproveitado por toda ação que precisa registrar "campo mudou de X
    para Y": troca de responsável (RN-012), e cadastro/edição/exclusão dos
    itens do Lado IXC e do Relatório EACE. `valor_anterior=""` identifica
    um cadastro novo (sem valor anterior), não uma alteração."""
    RiHistorico.objects.create(
        ri=ri,
        tipo=RiHistorico.LOG_CAMPO,
        autor=usuario,
        campo=campo,
        valor_anterior=valor_anterior,
        valor_novo=valor_novo,
    )
    # FEAT-011/RF-12: mesmo evento também vira registro de auditoria
    # técnica — cobre responsável (RN-012) e cadastro/edição/exclusão dos
    # itens do Lado IXC e do Relatório EACE, únicos chamadores desta
    # função.
    auditar(
        usuario,
        Auditoria.ALTERACAO_CAMPO,
        entidade="Ri",
        entidade_id=ri.pk,
        campo=campo,
        valor_anterior=valor_anterior,
        valor_novo=valor_novo,
    )


def _resumo_item_ixc(descricao, quantidade, valor_unitario=None):
    """Texto gravado no log (RN-008) para um item do Lado IXC/Relatório
    EACE. Omitido no cadastro do Lado IXC (nasce sempre 0, RN-011, mesmo
    critério já usado na listagem visual); incluído nos demais casos —
    edição do Lado IXC (valor digitado de fato) e cadastro/edição do Lado
    Relatório EACE (valor resolvido do catálogo, RN-018)."""
    resumo = f"{descricao} — {quantidade} un."
    if valor_unitario is not None:
        resumo += f" — R$ {valor_unitario:.2f}"
    return resumo


# RN-008/RN-014/RN-048: rótulo de log de cada campo do formulário único de
# Data de Ativação/Município/Estado/CNPJ/CNPJ Fictício do Lado IXC
# (`RiDataAtivacaoForm`).
ROTULOS_CAMPO_ATIVACAO_IXC = {
    "data_ativacao": "Data de Ativação",
    "municipio_ixc": "Município (Lado IXC)",
    "estado_ixc": "Estado (Lado IXC)",
    "cnpj": "CNPJ (Lado IXC)",
    "cnpj_ficticio": "CNPJ Fictício (Lado IXC)",
}


def _texto_campo_ativacao(valor):
    """Formata valor anterior/novo do log de Data de Ativação/Município/
    Estado (RN-008) — data em dd/mm/aaaa, texto vazio para `None`."""
    if hasattr(valor, "strftime"):
        return valor.strftime("%d/%m/%Y")
    return str(valor or "")


def _trocar_responsavel_com_log(ri, novo_responsavel, usuario):
    """RN-012: reatribui o responsável do RI e grava o log na linha do
    tempo (mesmo padrão de `_trocar_status_com_log`)."""
    responsavel_anterior = _nome_usuario(ri.responsavel)
    ri.responsavel = novo_responsavel
    ri.save(update_fields=["responsavel", "atualizado_em"])
    _registrar_log_campo(ri, usuario, "Responsável", responsavel_anterior, _nome_usuario(novo_responsavel))


@login_required
def grid_inep_view(request):
    """FEAT-007: grid principal de INEPs, 5 colunas (RF-05/RF-20): INEP,
    Nome da escola, Endereço, Status de conexão (Escola, RF-20) e Status do
    RI (RN-001) — com filtro próprio para cada um dos dois status e
    drill-down dos itens EACE/IXC daquele INEP (RF-06). Uma linha por
    INEP/Escola; Status do RI é o do RI mais recente dela, quando existir.
    "Responsável" (RN-012) não é coluna desta tabela — aparece só dentro do
    drill-down, editável. O cadastro do RI e dos itens é feito na tela da
    FEAT-004 (`ri_detail`).
    """
    q = (request.GET.get("q") or "").strip()
    status_conexao_filtro = (request.GET.get("status_conexao") or "").strip()
    status_ri_filtro = (request.GET.get("status_ri") or "").strip()
    divergencia_filtro = (request.GET.get("divergencia") or "").strip() == "1"

    escolas = Escola.objects.all().order_by("nome")
    if q:
        escolas = escolas.filter(
            Q(inep__icontains=q)
            | Q(nome__icontains=q)
            | Q(municipio__icontains=q)
            | Q(estado__icontains=q)
        )
    if status_conexao_filtro:
        escolas = escolas.filter(status_conexao=status_conexao_filtro)

    # Prefetch unico evita N+1: todas as Escolas da pagina trazem seus RIs
    # (mais recente primeiro) e, de cada RI, os itens e as divergencias.
    escolas = escolas.prefetch_related(
        Prefetch(
            "ris",
            queryset=Ri.objects.order_by("-criado_em").prefetch_related(
                "itens_eace", "itens_ixc", "itens_relatorio_eace", "divergencias"
            ),
        )
    )

    # Catálogo carregado uma única vez (fora do loop) para resolver o Kit
    # declarado de cada escola em memória — evita 1 consulta por linha do
    # Grid (RN-010, mesmo cruzamento de `ri_detail_view`).
    catalogo_kits = list(KitPadrao.objects.all())

    hoje = timezone.localdate()
    linhas = []
    total_divergencia = 0
    total_resposta_financeiro = 0
    for escola in escolas:
        ris_da_escola = list(escola.ris.all())
        ri_atual = ris_da_escola[0] if ris_da_escola else None
        divergencia_aberta = bool(ri_atual) and any(
            d.resolvida_em is None for d in ri_atual.divergencias.all()
        )
        if divergencia_aberta:
            total_divergencia += 1
        # RN-016: card de contagem de INEPs em "Resposta Financeiro" —
        # mesma lógica do total de divergência, contado antes do filtro de
        # Status do RI para o card continuar visível mesmo filtrando por
        # outro status.
        if ri_atual and ri_atual.status == Ri.AGUARDANDO_ANEXO_PORTAL_EACE:
            total_resposta_financeiro += 1

        if status_ri_filtro and (not ri_atual or ri_atual.status != status_ri_filtro):
            continue
        # Card "Com divergência" vira filtro (mesmo padrão do card
        # "Resposta Financeiro", RN-016) — checado depois de contar
        # `total_divergencia` acima, para o card continuar mostrando o
        # total mesmo com outro filtro (status/divergência) já ativo.
        if divergencia_filtro and not divergencia_aberta:
            continue

        # Mesma referência mostrada no card "Kit declarado" da tela de
        # detalhe (RN-010) — usada no drill-down quando ainda não existe
        # item de fato lançado (`RiItemEace`), para o Grid não divergir do
        # que a tela de detalhe já mostra como dado da EACE.
        kit_declarado_resolvido = KitPadrao.resolver_kit_declarado(
            escola.kit_inicial, lote=escola.lote, catalogo=catalogo_kits
        )
        kit_declarado_referencia = (
            kit_declarado_resolvido.descricao_curta
            if kit_declarado_resolvido
            else escola.kit_inicial
        )

        linha = {
            "escola": escola,
            "ri": ri_atual,
            "divergencia_aberta": divergencia_aberta,
            "kit_declarado_referencia": kit_declarado_referencia,
        }
        # FEAT-008: assunto sugerido (com o código de rastreio RN-009) para
        # pré-preencher a tela de composição de e-mail — só quando o botão
        # "Compor e-mail" pode aparecer para esse INEP.
        # RN-050 (2026-09-02): nome da escola incluído no assunto, a pedido
        # do usuário — o financeiro recebe muitos e-mails por INEP e o
        # nome ajuda a identificar a escola sem abrir o e-mail.
        if ri_atual and ri_atual.status == Ri.ENVIO_EMAIL_FATURAMENTO:
            linha["assunto_sugerido"] = _assunto_sugerido_email(escola, hoje)
        linhas.append(linha)

    paginator = Paginator(linhas, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "ri/grid_inep.html",
        {
            "page_obj": page_obj,
            "total_inep": escolas.count(),
            "total_divergencia": total_divergencia,
            "total_resposta_financeiro": total_resposta_financeiro,
            "status_resposta_financeiro": Ri.AGUARDANDO_ANEXO_PORTAL_EACE,
            # RN-019: exceção do Administrador — botão para forçar a saída
            # manual de "Aguardando financeiro", no drill-down do grid.
            "usuario_administrador": request.user.is_administrador,
            "q": q,
            "status_conexao_filtro": status_conexao_filtro,
            "status_ri_filtro": status_ri_filtro,
            "divergencia_filtro": divergencia_filtro,
            "status_conexao_opcoes": Escola.STATUS_CONEXAO_CHOICES,
            "status_ri_opcoes": Ri.STATUS_CHOICES,
            "status_ri_editaveis": STATUS_RI_EDITAVEIS,
            "status_ri_manuais": STATUS_RI_MANUAIS,
            # RN-012: usuários do sistema para o <select> de reatribuição do
            # responsável, dentro do drill-down.
            "usuarios": User.objects.order_by("username"),
            # FEAT-008: pré-preenchem a tela de composição de e-mail; "De" é
            # sempre o remetente do sistema (não editável), Para/Cc/Assunto
            # o usuário pode editar antes de enviar.
            "remetente_financeiro": settings.DEFAULT_FROM_EMAIL,
            "para_financeiro_sugestao": ", ".join(DESTINATARIOS_FINANCEIRO),
            "cc_financeiro_sugestao": ", ".join(COPIA_FINANCEIRO),
        },
    )


@login_required
def ri_status_update_view(request, pk):
    """Troca manual de status do RI direto pelo drill-down do grid (início
    da FEAT-006 fora de ordem, autorizado pelo usuário em 2026-08-22) — só
    os status "trocados pelo usuário" (RN-001) ficam disponíveis; os
    automáticos ("Aguardando financeiro", "Resposta Financeiro") e
    o inicial ("Implantação EACE") não aparecem aqui.

    FEAT-019: via HTMX, responde com um fragmento (formulário + badge do
    grid + mensagem) em vez de recarregar a página — preserva rolagem e
    filtros. Sem o header do HTMX, mantém o POST + redirect de sempre."""
    ri = get_object_or_404(Ri, pk=pk)
    next_url = request.POST.get("next") or ""
    if not next_url.startswith("/"):
        next_url = reverse("grid_inep")
    # RN-051 (2026-09-02): mesmo padrão de `ri_responsavel_update_view` —
    # qual dos dois formulários (drill-down do grid ou tela de detalhe)
    # deve ser reposto na resposta HTMX.
    origem = request.POST.get("origem") or "grid"

    if request.method == "POST":
        novo_status = request.POST.get("status")
        erro = _validar_transicao_status_ri(ri, novo_status, request.user)
        if erro:
            messages.error(request, erro)
        else:
            trocar_status_com_log(ri, novo_status, request.user)
            messages.success(request, "Status do RI atualizado.")

    if _requisicao_htmx(request):
        if origem == "detail":
            return _fragmento_status_detail_htmx(request, ri, next_url)
        return _fragmento_status_htmx(request, ri, next_url)
    return redirect(next_url)


def _fragmento_status_htmx(request, ri, next_url):
    """FEAT-019: fragmento out-of-band devolvido a `ri_status_update_view`
    quando a troca vem do HTMX — repõe o formulário de status com o valor
    real (inclusive quando a troca foi rejeitada), o badge de status na
    linha resumida do grid e o toast de mensagem, sem recarregar a página."""
    html = render_to_string(
        "ri/_status_form.html",
        {
            "ri": ri,
            "next_url": next_url,
            "status_ri_manuais": STATUS_RI_MANUAIS,
            "status_ri_editaveis": STATUS_RI_EDITAVEIS,
            # RN-019: exceção do Administrador — botão para forçar a saída
            # manual de "Aguardando financeiro".
            "usuario_administrador": request.user.is_administrador,
            "status_resposta_financeiro": Ri.AGUARDANDO_ANEXO_PORTAL_EACE,
        },
        request=request,
    )
    html += render_to_string(
        "ri/_status_badge_grid.html",
        {
            "ri": ri,
            "escola": ri.escola,
            "divergencia_aberta": ri.divergencias.filter(resolvida_em__isnull=True).exists(),
        },
        request=request,
    )
    html += render_to_string("core/_messages.html", request=request)
    return HttpResponse(html)


def _fragmento_status_detail_htmx(request, ri, next_url):
    """RN-051 (2026-09-02): fragmento out-of-band devolvido a
    `ri_status_update_view` quando a troca vem da tela de detalhe do RI —
    repõe o pill de status do cabeçalho (com a lista de opções já
    filtrada pela regra de negócio de hoje) e o bloco de ação "Enviar
    e-mail" (aparece/some conforme o novo status, sem precisar de F5)."""
    status_ri_opcoes_disponiveis = _status_ri_opcoes_disponiveis(ri)
    html = render_to_string(
        "ri/_status_pill_detail.html",
        {
            "ri": ri,
            "next_url": next_url,
            "status_ri_manuais": STATUS_RI_MANUAIS,
            "status_ri_opcoes_disponiveis": status_ri_opcoes_disponiveis,
            "usuario_administrador": request.user.is_administrador,
        },
        request=request,
    )
    html += render_to_string(
        "ri/_acao_envio_email_detail.html",
        {
            "ri": ri,
            "escola": ri.escola,
            "next_url": next_url,
            "assunto_sugerido": _assunto_sugerido_email(ri.escola, timezone.localdate()),
            "remetente_financeiro": settings.DEFAULT_FROM_EMAIL,
            "para_financeiro_sugestao": ", ".join(DESTINATARIOS_FINANCEIRO),
            "cc_financeiro_sugestao": ", ".join(COPIA_FINANCEIRO),
        },
        request=request,
    )
    html += render_to_string("core/_messages.html", request=request)
    return HttpResponse(html)


@login_required
def ri_responsavel_update_view(request, pk):
    """RN-012: reatribuição manual do responsável do RI, a partir de um
    <select> com os usuários do sistema — usado tanto pelo drill-down do
    grid (FEAT-007) quanto pela tela de detalhe (FEAT-004). Mesma
    permissão de edição do resto do RI (RN-004: Administrador e Analista,
    sem perfil exclusivo).

    FEAT-019: via HTMX, responde com um fragmento (formulário + mensagem)
    em vez de recarregar a página; o campo `origem` (grid ou detail) diz
    qual dos dois formulários — o do drill-down do grid ou o do
    cabeçalho da tela de detalhe — deve ser reposto. Sem o header do
    HTMX, mantém o POST + redirect de sempre."""
    ri = get_object_or_404(Ri, pk=pk)
    next_url = request.POST.get("next") or ""
    if not next_url.startswith("/"):
        next_url = reverse("grid_inep")
    origem = request.POST.get("origem") or "grid"

    if request.method == "POST":
        novo_responsavel_id = request.POST.get("responsavel")
        if not novo_responsavel_id:
            messages.error(request, "Selecione um responsável.")
        else:
            novo_responsavel = get_object_or_404(User, pk=novo_responsavel_id)
            if novo_responsavel_id != str(ri.responsavel_id):
                _trocar_responsavel_com_log(ri, novo_responsavel, request.user)
            messages.success(request, "Responsável do RI atualizado.")

    if _requisicao_htmx(request):
        return _fragmento_responsavel_htmx(request, ri, next_url, origem)
    return redirect(next_url)


def _fragmento_responsavel_htmx(request, ri, next_url, origem):
    """FEAT-019: fragmento out-of-band devolvido a
    `ri_responsavel_update_view` quando a troca vem do HTMX."""
    template = (
        "ri/_responsavel_form_detail.html" if origem == "detail" else "ri/_responsavel_form_grid.html"
    )
    contexto = {"ri": ri, "next_url": next_url, "usuarios": User.objects.order_by("username")}
    html = render_to_string(template, contexto, request=request)
    html += render_to_string("core/_messages.html", request=request)
    return HttpResponse(html)


MIME_PLANILHA_FATURAMENTO = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Vencimento da NF = data de geração da planilha (envio do e-mail ou
# clique em "Baixar planilha") + 30 dias corridos — não a própria data
# de geração (correção 2026-08-31, RN-013 desatualizada nesse ponto).
DIAS_VENCIMENTO_PLANILHA_FATURAMENTO = 30


@login_required
def ri_enviar_email_financeiro_view(request, pk):
    """FEAT-008/RF-16-18, RN-009: recebe o envio da tela de composição de
    e-mail (De automático/Para/Cc/Assunto/Anexo/Mensagem), aberta pelo
    botão único do grid. Gera a planilha de faturamento com os itens do
    lado IXC (sempre anexada, RN-013 — substitui o PDF gerado antes)
    mais o anexo extra opcional, envia o e-mail com os dados confirmados
    na tela, registra o envio (`EmailFinanceiroLog` e linha do tempo da
    FEAT-014) e muda o status do RI para "Aguardando financeiro"
    (automático, RF-18). O código de rastreio (RN-009) é garantido no
    assunto mesmo que o usuário o edite/remova na tela."""
    ri = get_object_or_404(Ri, pk=pk)
    next_url = request.POST.get("next") or ""
    if not next_url.startswith("/"):
        next_url = reverse("grid_inep")

    if request.method == "POST":
        if ri.status != Ri.ENVIO_EMAIL_FATURAMENTO:
            messages.error(request, 'Esse RI não está em "Envio de Email para faturamento".')
            return redirect(next_url)

        form = RiEmailFinanceiroForm(request.POST, request.FILES)
        if not form.is_valid():
            for erros_campo in form.errors.values():
                for erro in erros_campo:
                    messages.error(request, erro)
            return redirect(next_url)

        # RN-013: sem a planilha não há o que anexar/enviar — bloqueia
        # antes de mexer em qualquer outro dado do RI (mesma mensagem
        # objetiva do botão "Baixar planilha").
        try:
            planilha_bytes = gerar_planilha_faturamento(
                ri,
                data_vencimento=timezone.localdate()
                + timedelta(days=DIAS_VENCIMENTO_PLANILHA_FATURAMENTO),
            )
        except PlanilhaFaturamentoError as erro:
            messages.error(request, str(erro))
            return redirect(next_url)

        destinatarios = form.cleaned_data["para"]
        copia = form.cleaned_data["cc"]
        mensagem = form.cleaned_data["mensagem"]

        ri.observacoes_envio_financeiro = mensagem
        ri.dados_financeiro_confirmados_em = timezone.now()
        ri.save(
            update_fields=[
                "observacoes_envio_financeiro",
                "dados_financeiro_confirmados_em",
                "atualizado_em",
            ]
        )

        # RN-009: o código de rastreio precisa sobreviver mesmo se o
        # usuário editar o campo Assunto na tela de composição.
        codigo = montar_codigo_rastreio(ri.escola.inep, timezone.localdate())
        assunto = form.cleaned_data["assunto"]
        if codigo not in assunto:
            assunto = montar_assunto_com_codigo(codigo, assunto)

        corpo = montar_corpo_email_financeiro(ri)
        nome_planilha = nome_arquivo_planilha_faturamento(ri.escola)

        email = EmailMessage(
            subject=assunto,
            body=corpo,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=destinatarios,
            cc=copia,
        )
        email.attach(nome_planilha, planilha_bytes, MIME_PLANILHA_FATURAMENTO)
        anexo_extra = form.cleaned_data.get("anexo_extra")
        if anexo_extra:
            email.attach(anexo_extra.name, anexo_extra.read(), anexo_extra.content_type)
        email.send(fail_silently=False)

        EmailFinanceiroLog.objects.create(
            ri=ri,
            direcao=EmailFinanceiroLog.ENVIADO,
            remetente=settings.DEFAULT_FROM_EMAIL,
            destinatarios=(
                "Para: " + ", ".join(destinatarios) + "; Cc: " + ", ".join(copia)
            ),
            assunto=assunto,
            anexo_pdf=nome_planilha,
        )
        auditar(
            request.user,
            Auditoria.ENVIO_EMAIL,
            entidade="Ri",
            entidade_id=ri.pk,
            campo="assunto",
            valor_novo=assunto,
            ip_origem=request.META.get("REMOTE_ADDR"),
        )
        entrada_email = RiHistorico(
            ri=ri,
            tipo=RiHistorico.EMAIL,
            autor=request.user,
            mensagem=f"E-mail enviado ao financeiro. Assunto: {assunto}",
        )
        entrada_email.anexo.save(nome_planilha, ContentFile(planilha_bytes), save=False)
        entrada_email.save()

        trocar_status_com_log(ri, Ri.AGUARDANDO_FINANCEIRO, request.user)
        messages.success(request, "E-mail enviado ao financeiro. Status do RI atualizado.")

    return redirect(next_url)


@login_required
def ri_baixar_planilha_financeiro_view(request, pk):
    """FEAT-017/RN-013: baixa a mesma planilha de faturamento que seria
    anexada ao e-mail (sem enviar nada), para o usuário validar os dados
    antes de confirmar o envio — botão "Baixar planilha" na tela de
    composição (FEAT-008)."""
    ri = get_object_or_404(Ri, pk=pk)
    next_url = request.GET.get("next") or ""
    if not next_url.startswith("/"):
        next_url = reverse("grid_inep")

    try:
        planilha_bytes = gerar_planilha_faturamento(
            ri,
            data_vencimento=timezone.localdate()
            + timedelta(days=DIAS_VENCIMENTO_PLANILHA_FATURAMENTO),
        )
    except PlanilhaFaturamentoError as erro:
        messages.error(request, str(erro))
        return redirect(next_url)

    nome_planilha = nome_arquivo_planilha_faturamento(ri.escola)
    resposta = HttpResponse(planilha_bytes, content_type=MIME_PLANILHA_FATURAMENTO)
    # Nome da escola pode ter acento — filename comum (fallback ASCII) +
    # filename* (RFC 5987/6266) para o navegador mostrar o nome completo.
    nome_ascii = nome_planilha.encode("ascii", "ignore").decode("ascii") or "faturamento.xlsx"
    resposta["Content-Disposition"] = (
        f'attachment; filename="{nome_ascii}"; filename*=UTF-8\'\'{quote(nome_planilha)}'
    )
    return resposta


@login_required
@never_cache
def ri_detail_view(request, inep):
    """FEAT-004: cadastro manual do RI e dos 3 lados de um INEP já
    existente (Escola) — Kit declarado (1º), IXC (2º) e Relatório EACE
    (3º, novo em 2026-08-22). Sem RI ainda, a tela só oferece iniciar um
    (`ri_iniciar`). Kit declarado e Relatório EACE só aceitam lançar item
    novo — nunca editar ou excluir um já salvo (RN-002/RN-003); IXC aceita
    editar e excluir. Lançamento do IXC (RN-011, ajustada em 2026-08-24):
    "KIT Instalado" (obrigatório) + "Produtos" via "+" — descrição dos dois
    vem do catálogo `KitPadrao` (aba LPU do CONSOLIDADO EACE.xlsx,
    RN-010/FEAT-015), filtrado por `Escola.lote`; cada linha vira um
    `RiItemIxc` normal.

    `@never_cache` (bug reportado pelo usuário, 2026-08-24): sem cabeçalho
    de cache, o navegador guardava uma cópia antiga desta página e a
    reexibia num F5 comum — o bloco "Produtos" aparecia com linhas que na
    verdade eram de uma versão anterior renderizada em memória do próprio
    navegador, não do servidor (o formset sempre nasce com 0 linhas aqui;
    confirmado lendo o contexto de resposta direto, sem passar pelo
    navegador). `never_cache` força o navegador a sempre buscar a versão
    atual no servidor.
    """
    escola = get_object_or_404(Escola, inep=inep)
    ri = (
        Ri.objects.filter(escola=escola)
        .order_by("-criado_em")
        .prefetch_related("itens_eace", "itens_ixc", "itens_relatorio_eace")
        .first()
    )

    # RN-010 ampliada/FEAT-016: parte das escolas tem Escola.kit_inicial só
    # com o número do KIT (ex.: "4"), não o texto completo — resolve pelo
    # catálogo para exibir a descrição de verdade. Usa a Descrição curta
    # (RN-011), mesma nomenclatura já usada no Lado IXC — a completa tem o
    # qualificador entre parênteses e não cabe no campo. Sem
    # correspondência, mostra o dado bruto mesmo (nenhum valor inventado,
    # CLAUDE.md §9).
    itens_eace_existentes = list(ri.itens_eace.all()) if ri else []
    kit_declarado_resolvido = KitPadrao.resolver_kit_declarado(
        escola.kit_inicial, lote=escola.lote
    )
    if itens_eace_existentes:
        # Bug reportado pelo usuário (2026-08-26): com o item do 1º lado já
        # lançado (Django admin), este campo mostrava a pré-visualização
        # calculada de Escola.kit_inicial — podendo divergir do que foi de
        # fato registrado (ex.: Escola.kit_inicial mudou depois, ou o
        # lançamento corrigiu o dado, RN-002). Com item lançado, o campo
        # passa a refletir o item real (o mais recente, já que correção
        # não edita — lança um novo, RN-002) em vez da pré-visualização.
        kit_declarado_descricao = max(
            itens_eace_existentes, key=lambda item: item.criado_em
        ).descricao_item
    else:
        kit_declarado_descricao = (
            kit_declarado_resolvido.descricao_curta
            if kit_declarado_resolvido
            else escola.kit_inicial
        )

    # RN-011 (ajuste, 2026-08-26): 1 KIT por INEP — RI que já tem um KIT
    # lançado (`eh_kit=True`) não pode lançar outro; para trocar, o
    # usuário edita ou exclui o item já lançado (RN-004).
    kit_ja_lancado = bool(ri and ri.itens_ixc.filter(eh_kit=True).exists())
    # RN-018 (2026-08-26): mesmo limite de 1 KIT, agora também no Lado
    # Relatório EACE — com a diferença de que, lá, editar/excluir o item
    # KIT continua liberado (exceção pontual à imutabilidade da RN-003).
    kit_ja_lancado_eace = bool(ri and ri.itens_relatorio_eace.filter(eh_kit=True).exists())

    kit_form = RiItemIxcKitForm(escola=escola)
    produto_formset = RiItemIxcProdutoFormSet(form_kwargs={"escola": escola})
    data_ativacao_form = RiDataAtivacaoForm(instance=ri)
    # RN-018: mesmos campos do bloco do Lado IXC acima, com prefixo próprio
    # para não colidir com os ids/nomes do outro formulário na mesma
    # página (os dois usam a mesma classe de campo "kit"/"produto").
    kit_form_eace = RiItemRelatorioEaceKitForm(escola=escola, prefix="eace")
    produto_formset_eace = RiItemRelatorioEaceProdutoFormSet(
        form_kwargs={"escola": escola}, prefix="eace_produto"
    )
    historico_form = RiHistoricoForm()

    if ri and request.method == "POST":
        acao = request.POST.get("acao")
        if acao == "salvar_ixc" and not _lado_ixc_editavel(ri):
            # RN-052: Lado IXC só aceita lançamento/edição com o RI em "Em
            # Andamento" — checado antes de instanciar/validar o formulário.
            messages.error(request, MENSAGEM_LADO_IXC_SOMENTE_LEITURA)
            return redirect("ri_detail", inep=inep)
        if acao in (
            "salvar_relatorio_eace", "sincronizar_planilha_eace",
        ) and _bloqueado_faturamento_concluido(ri):
            # RN-020: bloqueio do Lado Relatório EACE, para os dois perfis —
            # checado antes de instanciar/validar qualquer formulário.
            messages.error(request, MENSAGEM_BLOQUEIO_FATURAMENTO_CONCLUIDO)
            return redirect("ri_detail", inep=inep)
        if acao == "salvar_ixc":
            # RN-011 (2026-08-24, formulário único): usuário pediu para não
            # ter dois botões de salvar no mesmo bloco — KIT Instalado,
            # Produtos e Data Ativação são validados e salvos juntos numa
            # submissão só. Cada um é opcional nessa submissão (ex.: só
            # atualizar a Data Ativação, sem lançar KIT nem Produto).
            # Quantidade do KIT sempre 1 (kit fechado da escola). Valor
            # unitário (ajuste do usuário): não é mais digitado — nasce 0,
            # corrigido depois editando o item (RN-004).
            kit_form = RiItemIxcKitForm(request.POST, escola=escola)
            produto_formset = RiItemIxcProdutoFormSet(
                request.POST, form_kwargs={"escola": escola}
            )
            data_ativacao_form = RiDataAtivacaoForm(request.POST, instance=ri)
            if kit_form.is_valid() and produto_formset.is_valid() and data_ativacao_form.is_valid():
                if kit_form.kit_selecionado and kit_ja_lancado:
                    messages.error(
                        request,
                        "Este RI já tem um KIT lançado — só é permitido um "
                        "KIT por INEP. Para trocar, edite ou exclua o item "
                        "já lançado (acima) antes de lançar outro.",
                    )
                    return redirect("ri_detail", inep=inep)
                linhas_preenchidas = [
                    dados
                    for dados in produto_formset.cleaned_data
                    if dados and dados.get("produto")
                ]
                data_mudou = data_ativacao_form.has_changed()
                if kit_form.kit_selecionado or linhas_preenchidas or data_mudou:
                    if kit_form.kit_selecionado:
                        item_kit = RiItemIxc.objects.create(
                            ri=ri,
                            descricao_item=kit_form.descricao_selecionada,
                            quantidade=1,
                            valor_unitario=Decimal("0"),
                            # RN-013: marca o item como o "KIT Instalado" —
                            # a planilha de faturamento usa isso para
                            # escolher a aba fixa "NF KIT" em vez do
                            # catálogo de produtos avulsos.
                            eh_kit=True,
                        )
                        _registrar_log_campo(
                            ri, request.user, "KIT Instalado (Lado IXC)", "",
                            _resumo_item_ixc(item_kit.descricao_item, item_kit.quantidade),
                        )
                    for dados in linhas_preenchidas:
                        produto = dados["produto"]
                        item_produto = RiItemIxc.objects.create(
                            ri=ri,
                            # RN-011: Descrição curta (sem o qualificador entre
                            # parênteses do catálogo) — mesmo texto já mostrado
                            # no select do "+".
                            descricao_item=produto.descricao_curta or produto.descricao,
                            quantidade=dados["quantidade"],
                            valor_unitario=Decimal("0"),
                        )
                        _registrar_log_campo(
                            ri, request.user, "Produto (Lado IXC)", "",
                            _resumo_item_ixc(item_produto.descricao_item, item_produto.quantidade),
                        )
                    if data_mudou:
                        # RN-008: valor anterior vem do `initial` do form —
                        # capturado do RI ainda em memória no momento da
                        # instanciação (`RiDataAtivacaoForm(request.POST,
                        # instance=ri)`), antes de `is_valid()` já ter
                        # escrito os valores novos na própria instância.
                        campos_alterados = data_ativacao_form.changed_data
                        valores_anteriores = {
                            campo: data_ativacao_form.initial.get(campo) for campo in campos_alterados
                        }
                        data_ativacao_form.save()
                        for campo in campos_alterados:
                            _registrar_log_campo(
                                ri, request.user, ROTULOS_CAMPO_ATIVACAO_IXC[campo],
                                _texto_campo_ativacao(valores_anteriores[campo]),
                                _texto_campo_ativacao(getattr(ri, campo)),
                            )
                    # RN-003: recalcula o confronto formal contra o Lado
                    # Relatório EACE a cada mudança do Lado IXC.
                    sincronizar_divergencia_kit_relatorio(ri)
                    messages.success(request, "Atendimento IXC atualizado.")
                    return redirect("ri_detail", inep=inep)
                if kit_ja_lancado or ri.data_ativacao:
                    # RN-011 (correção 2026-09-02, bug reportado pelo
                    # usuário): reenviar o formulário sem nenhuma alteração
                    # nova (ex.: clique duplo em "Salvar", ou visitar a tela
                    # já preenchida e clicar "Salvar" sem mudar nada) caía
                    # sempre na mensagem "Selecione um KIT..." — enganosa
                    # quando o KIT e/ou a Data de Ativação já estão
                    # lançados/preenchidos (visíveis na própria tela).
                    # Mensagem neutra quando já existe algo salvo; mantém a
                    # original só quando realmente nada foi preenchido
                    # ainda (nem KIT, nem Data de Ativação).
                    messages.error(request, "Nenhuma alteração para salvar.")
                else:
                    messages.error(
                        request,
                        "Selecione um KIT, um produto ou informe a Data de Ativação.",
                    )
                # Post/Redirect/Get: sem isso, a resposta do POST fica na
                # mesma URL e um F5 do usuário reenvia o formulário — o
                # navegador repete a submissão (e a mensagem de erro volta
                # a aparecer) mesmo sem clicar em "Salvar" de novo (bug
                # reportado pelo usuário, 2026-08-26).
                return redirect("ri_detail", inep=inep)
        elif acao == "salvar_relatorio_eace":
            # RN-018 (2026-08-26): mesmo mecanismo do Lado IXC (RN-011) —
            # "KIT Instalado" (no máximo um por INEP, RN-015) e 0 ou mais
            # "Produtos" via "+", ambos escolhidos no catálogo `KitPadrao`.
            # Diferente do Lado IXC, o Valor Unitário não nasce 0 — vem do
            # catálogo (mesma resolução usada na planilha de faturamento,
            # RN-013), porque aqui a informação tem uso real (RN-003).
            kit_form_eace = RiItemRelatorioEaceKitForm(request.POST, escola=escola, prefix="eace")
            produto_formset_eace = RiItemRelatorioEaceProdutoFormSet(
                request.POST, form_kwargs={"escola": escola}, prefix="eace_produto"
            )
            if kit_form_eace.is_valid() and produto_formset_eace.is_valid():
                if kit_form_eace.kit_selecionado and kit_ja_lancado_eace:
                    messages.error(
                        request,
                        "Este RI já tem um KIT lançado no Relatório EACE — só é "
                        "permitido um KIT por INEP. Para trocar, edite ou exclua o "
                        "item já lançado (acima) antes de lançar outro.",
                    )
                    return redirect("ri_detail", inep=inep)
                linhas_preenchidas = [
                    dados
                    for dados in produto_formset_eace.cleaned_data
                    if dados and dados.get("produto")
                ]
                if kit_form_eace.kit_selecionado or linhas_preenchidas:
                    if kit_form_eace.kit_selecionado:
                        descricao = kit_form_eace.descricao_selecionada
                        instancia = kit_form_eace.instancia_selecionada
                        if instancia:
                            valor_unitario_kit = instancia.valor_faturavel
                        else:
                            # "Outro" — sem instância de catálogo escolhida
                            # direto; cai para a mesma resolução por número
                            # de Access Points já usada na planilha de
                            # faturamento (RN-013). Sem correspondência,
                            # 0,00 — nenhum valor inventado (CLAUDE.md §9).
                            catalogo = _resolver_catalogo_ixc(descricao, True, escola.lote)
                            valor_unitario_kit = catalogo.valor_faturavel if catalogo else Decimal("0")
                        item_kit = RiItemRelatorioEace.objects.create(
                            ri=ri,
                            descricao_item=descricao,
                            quantidade=1,
                            valor_unitario=valor_unitario_kit,
                            eh_kit=True,
                        )
                        _registrar_log_campo(
                            ri, request.user, "KIT Instalado (Relatório EACE)", "",
                            _resumo_item_ixc(
                                item_kit.descricao_item, item_kit.quantidade, item_kit.valor_unitario
                            ),
                        )
                    for dados in linhas_preenchidas:
                        produto = dados["produto"]
                        descricao = produto.descricao_curta or produto.descricao
                        item_produto = RiItemRelatorioEace.objects.create(
                            ri=ri,
                            descricao_item=descricao,
                            quantidade=dados["quantidade"],
                            # Já temos a instância do catálogo escolhida no
                            # select — sem precisar re-resolver por descrição.
                            valor_unitario=produto.valor_faturavel,
                        )
                        _registrar_log_campo(
                            ri, request.user, "Produto (Relatório EACE)", "",
                            _resumo_item_ixc(
                                item_produto.descricao_item, item_produto.quantidade, item_produto.valor_unitario
                            ),
                        )
                    # RN-003: recalcula o confronto formal contra o Lado
                    # IXC a cada mudança do Lado Relatório EACE.
                    sincronizar_divergencia_kit_relatorio(ri)
                    messages.success(request, "Relatório EACE atualizado.")
                    return redirect("ri_detail", inep=inep)
                # Nada preenchido nesta submissão. Se já existe item lançado
                # neste lado (manualmente ou pelo Sincronizador, FEAT-024) —
                # caso comum de clicar "Salvar" por engano depois de
                # sincronizar, já que o campo "Kit" some da tela com o
                # limite de 1 por INEP (RN-015) — a mensagem deixa claro que
                # os dados já estão salvos, em vez de soar como um erro.
                if ri.itens_relatorio_eace.exists():
                    messages.success(
                        request,
                        "Os itens do Relatório EACE já estão salvos — nada novo para "
                        'lançar (use o "+" para adicionar mais produtos).',
                    )
                else:
                    messages.error(request, "Selecione um KIT ou um produto para lançar.")
                return redirect("ri_detail", inep=inep)
        elif acao == "sincronizar_planilha_eace":
            # RN-022/FEAT-024: reprocessa a Planilha EACE ativa (RN-021) e
            # lança os itens casados com o catálogo, igual a um
            # lançamento manual (RN-018) — não substitui o preenchimento
            # manual, que continua disponível antes e depois de
            # sincronizar.
            try:
                resultado = sincronizar_relatorio_eace_da_planilha(ri)
            except PlanilhaEaceSincronizacaoError as erro:
                messages.error(request, str(erro))
                return redirect("ri_detail", inep=inep)

            for item in resultado["criados"]:
                campo = (
                    "KIT Instalado (Relatório EACE, Sincronizador)"
                    if item.eh_kit
                    else "Produto (Relatório EACE, Sincronizador)"
                )
                _registrar_log_campo(
                    ri, request.user, campo, "",
                    _resumo_item_ixc(item.descricao_item, item.quantidade, item.valor_unitario),
                )

            partes = []
            if resultado["criados"]:
                partes.append(f"{len(resultado['criados'])} item(ns) lançado(s)")
            if resultado["duplicados"]:
                partes.append(f"{len(resultado['duplicados'])} já lançado(s) antes")
            if resultado["sem_correspondencia"]:
                partes.append(
                    f"{len(resultado['sem_correspondencia'])} sem correspondência no catálogo"
                )
            if resultado["kit_ignorado"]:
                partes.append(f"{len(resultado['kit_ignorado'])} KIT ignorado (já havia um lançado)")
            if resultado["quantidade_invalida"]:
                partes.append(
                    f"{len(resultado['quantidade_invalida'])} com quantidade inválida na planilha"
                )
            resumo = "Sincronização: " + (", ".join(partes) if partes else "nada para lançar") + "."
            if resultado["criados"]:
                messages.success(request, resumo)
            else:
                messages.error(request, resumo)
            return redirect("ri_detail", inep=inep)
        elif acao == "adicionar_historico":
            historico_form = RiHistoricoForm(request.POST, request.FILES)
            if historico_form.is_valid():
                entrada = historico_form.save(commit=False)
                entrada.ri = ri
                entrada.autor = request.user
                entrada.tipo = (
                    RiHistorico.MENSAGEM
                    if entrada.mensagem.strip()
                    else RiHistorico.ANEXO
                )
                entrada.save()
                messages.success(request, "Registro adicionado ao histórico do RI.")
                if not _requisicao_htmx(request):
                    return redirect("ri_detail", inep=inep)
                # FEAT-019: via HTMX não redireciona — o formulário volta
                # limpo para a próxima entrada e o fragmento é montado mais
                # abaixo, junto com o restante do contexto da página.
                historico_form = RiHistoricoForm()

    # RN-014: alerta visual (não bloqueante) quando Município/Estado do
    # Lado IXC divergem do cadastro da Escola — só quando os dois lados
    # têm valor preenchido; comparação sem diferenciar caixa/espaços para
    # não acusar falso positivo por formatação.
    def _diverge(valor_ixc, valor_escola):
        valor_ixc = (valor_ixc or "").strip().casefold()
        valor_escola = (valor_escola or "").strip().casefold()
        return bool(valor_ixc and valor_escola and valor_ixc != valor_escola)

    divergencia_municipio_ixc = ri and _diverge(ri.municipio_ixc, escola.municipio)
    divergencia_estado_ixc = ri and _diverge(ri.estado_ixc, escola.estado)

    # RN-002 (esclarecida em 2026-08-26): mesma mecânica visual acima
    # (RN-014), campo único — "Kit declarado" (1º lado, já resolvido em
    # `kit_declarado_descricao`) × "KIT Instalado" do Lado IXC (2º lado,
    # item com `eh_kit=True`, já vem prefetched em `itens_ixc`, sem query
    # nova). Não persiste em `Ri.kit_informado_ixc`/`Ri.divergencia_kit`
    # (campos criados antes da RN-002 ser reescrita como confronto item a
    # item, hoje sem uso) — computado na renderização, mesmo padrão do
    # alerta de Município/Estado; decisão técnica reversível (CLAUDE.md §9).
    kit_instalado_item = (
        next((item for item in ri.itens_ixc.all() if item.eh_kit), None) if ri else None
    )
    divergencia_kit = ri and _diverge(
        kit_instalado_item.descricao_item if kit_instalado_item else "", kit_declarado_descricao
    )

    # RN-003 (2026-08-26): confronto formal Lado IXC × Lado Relatório EACE
    # — recalculado na renderização (mesmo padrão dos alertas acima) para
    # destacar em vermelho os itens do Lado IXC divergentes; a persistência
    # em `RiDivergencia` (bloqueia o envio ao financeiro) já foi feita nas
    # ações que mudam algum dos dois lados (`sincronizar_divergencia_kit_relatorio`).
    divergencia_kit_relatorio = comparar_kit_e_produtos_ixc_relatorio(ri) if ri else None

    # RN-046 (2026-08-28): divergência de "Status escola" (coluna T) entre
    # os próprios itens do Lado Relatório EACE — mesmo padrão de cálculo
    # na renderização acima; não bloqueia nada, só destaca em vermelho
    # todos os itens do Lado 3 quando houver mais de um valor entre eles.
    divergencia_status_escola = comparar_status_escola_relatorio(ri) if ri else None

    # RN-008 (2026-08-26): linha do tempo paginada (10 por página) — evita
    # trazer todo o histórico do RI de uma vez, algo que tende a crescer
    # bastante agora que cadastro/edição/exclusão dos itens do Lado IXC e
    # do Relatório EACE também geram entrada. Página seguinte só é
    # consultada quando o usuário clica (Paginator faz LIMIT/OFFSET, não
    # busca tudo em memória).
    historico_page_obj = None
    if ri:
        historico_paginator = Paginator(
            ri.historico.select_related("autor").prefetch_related("documentos"), HISTORICO_ITENS_POR_PAGINA
        )
        historico_page_obj = historico_paginator.get_page(request.GET.get("historico_page"))

    # FEAT-019: só a ação "adicionar_historico" tem versão HTMX (linha do
    # tempo sem reload); as demais ações desta tela continuam com o
    # POST + redirect/render tradicional, fora do escopo desta feature.
    if (
        request.method == "POST"
        and request.POST.get("acao") == "adicionar_historico"
        and _requisicao_htmx(request)
    ):
        return _fragmento_historico_htmx(request, ri, historico_form, historico_page_obj)

    # RN-051 (2026-09-02): status do RI editável direto na tela de detalhe
    # (mesmo padrão do drill-down do grid) — "Envio de Email para
    # Faturamento" só aparece no <select> quando as regras de negócio do
    # envio (RN-013) estão satisfeitas hoje; o botão/modal "Enviar e-mail"
    # aparece logo abaixo quando o RI já está nesse status. Os dois
    # atualizam via HTMX ao trocar o status, sem precisar de F5.
    status_ri_opcoes_disponiveis = _status_ri_opcoes_disponiveis(ri) if ri else []

    # RN-052: fora de "Em Andamento", os campos do Lado IXC continuam
    # visíveis (usuário precisa ver Data Ativação/CNPJ/Município/Estado já
    # lançados) mas ganham o atributo `disabled` — protege também no
    # back-end, já que um campo `disabled` do Django ignora valor
    # submetido e sempre usa o inicial.
    lado_ixc_editavel = bool(ri) and _lado_ixc_editavel(ri)
    if ri and not lado_ixc_editavel:
        for campo in kit_form.fields.values():
            campo.disabled = True
        for campo in data_ativacao_form.fields.values():
            campo.disabled = True
        for subform in produto_formset.forms:
            for campo in subform.fields.values():
                campo.disabled = True

    return render(
        request,
        "ri/ri_detail.html",
        {
            "escola": escola,
            "kit_declarado_descricao": kit_declarado_descricao,
            "ri": ri,
            "kit_form": kit_form,
            "kit_ja_lancado": kit_ja_lancado,
            # RN-020: com o RI em "Faturamento Concluído", os campos do
            # Lado Relatório EACE ficam somente leitura.
            "ri_bloqueado_faturamento_concluido": bool(ri) and _bloqueado_faturamento_concluido(ri),
            # RN-052: Lado IXC só é editável com o RI em "Em Andamento".
            "lado_ixc_editavel": lado_ixc_editavel,
            "produto_formset": produto_formset,
            "data_ativacao_form": data_ativacao_form,
            "divergencia_municipio_ixc": divergencia_municipio_ixc,
            "divergencia_estado_ixc": divergencia_estado_ixc,
            "divergencia_kit": divergencia_kit,
            "divergencia_kit_relatorio": divergencia_kit_relatorio,
            "divergencia_status_escola": divergencia_status_escola,
            "kit_form_eace": kit_form_eace,
            "kit_ja_lancado_eace": kit_ja_lancado_eace,
            "produto_formset_eace": produto_formset_eace,
            "historico_form": historico_form,
            "historico": historico_page_obj,
            # RN-012: usuários do sistema para o <select> de reatribuição do
            # responsável.
            "usuarios": User.objects.order_by("username"),
            # RN-051: status editável + ação "Enviar e-mail" na própria tela.
            "status_ri_manuais": STATUS_RI_MANUAIS,
            "status_ri_opcoes_disponiveis": status_ri_opcoes_disponiveis,
            "usuario_administrador": request.user.is_administrador,
            "assunto_sugerido": _assunto_sugerido_email(escola, timezone.localdate()) if ri else "",
            "remetente_financeiro": settings.DEFAULT_FROM_EMAIL,
            "para_financeiro_sugestao": ", ".join(DESTINATARIOS_FINANCEIRO),
            "cc_financeiro_sugestao": ", ".join(COPIA_FINANCEIRO),
        },
    )


def _fragmento_historico_htmx(request, ri, historico_form, historico_page_obj):
    """FEAT-019: fragmento out-of-band devolvido por `ri_detail_view`
    quando um novo registro de histórico (RN-008) chega via HTMX — repõe
    a linha do tempo inteira (formulário limpo + entradas + paginação) e
    o toast de mensagem, sem recarregar a página."""
    html = render_to_string(
        "ri/_historico_panel.html",
        {"ri": ri, "historico_form": historico_form, "historico": historico_page_obj},
        request=request,
    )
    html += render_to_string("core/_messages.html", request=request)
    return HttpResponse(html)


@login_required
def planilha_eace_view(request):
    """FEAT-023/RN-021: tela "Administrador > Planilha EACE" — upload do
    arquivo usado pelo Sincronizador do Lado Relatório EACE (RN-022). Ação
    restrita a Administrador, mesmo critério das demais ações
    administrativas (RN-004)."""
    if not request.user.is_administrador:
        return HttpResponseForbidden("Somente Administrador pode acessar esta tela.")

    if request.method == "POST":
        form = PlanilhaEaceUploadForm(request.POST, request.FILES)
        if form.is_valid():
            PlanilhaEace.substituir(form.cleaned_data["arquivo"], request.user)
            messages.success(request, "Planilha EACE importada com sucesso.")
            return redirect("planilha_eace")
        mensagens_erro = [erro for erros in form.errors.values() for erro in erros]
        messages.error(request, "Não foi possível importar: " + " ".join(mensagens_erro))
    else:
        form = PlanilhaEaceUploadForm()

    return render(request, "ri/planilha_eace.html", {
        "form": form,
        "planilha_ativa": PlanilhaEace.ativa(),
    })


@login_required
def planilha_eace_sincronizar_todas_view(request):
    """FEAT-025/RN-023: botão "Sincronizar todas as RI" do card "Arquivo
    ativo" — aplica o Sincronizador do Lado Relatório EACE (RN-022/
    FEAT-024) ao RI atual de cada Escola de uma vez, sem precisar abrir RI
    por RI. Ação restrita a Administrador, mesmo critério da tela
    (RN-021)."""
    if not request.user.is_administrador:
        return HttpResponseForbidden("Somente Administrador pode acessar esta tela.")
    if request.method != "POST":
        return redirect("planilha_eace")

    try:
        processados = sincronizar_relatorio_eace_de_todas_as_ri()
    except PlanilhaEaceSincronizacaoError as erro:
        messages.error(request, str(erro))
        return redirect("planilha_eace")

    total_atualizados = 0

    for ri, resultado in processados:
        if resultado in (RI_BLOQUEADO_FATURAMENTO_CONCLUIDO, RI_SEM_LINHA_NA_PLANILHA):
            continue

        # RN-023/RN-008: cada item lançado pelo lote entra na linha do
        # tempo do RI correspondente, igual ao Sincronizador individual
        # (FEAT-024) — mesmo rótulo, só identificando a origem em lote.
        for item in resultado["criados"]:
            campo = (
                "KIT Instalado (Relatório EACE, Sincronizador em lote)"
                if item.eh_kit
                else "Produto (Relatório EACE, Sincronizador em lote)"
            )
            _registrar_log_campo(
                ri, request.user, campo, "",
                _resumo_item_ixc(item.descricao_item, item.quantidade, item.valor_unitario),
            )

        if resultado["criados"]:
            total_atualizados += 1

    # RN-023 (ajustada em 2026-08-27): usuário pediu só a contagem de
    # INEPs atualizados — o detalhamento (já sincronizado, bloqueado,
    # sem linha na planilha, sem correspondência) não é o que ele
    # precisa ver na mensagem; quem quiser investigar um INEP específico
    # sem novidade abre o RI dele.
    messages.success(request, f"Sincronização em lote: {total_atualizados} INEP(s) atualizado(s).")
    return redirect("planilha_eace")


@login_required
def ri_iniciar_view(request, inep):
    """Cria o RI inicial do INEP, status "Implantação EACE" (RN-001), se
    ainda não existir nenhum RI para essa escola."""
    escola = get_object_or_404(Escola, inep=inep)
    if request.method == "POST" and not Ri.objects.filter(escola=escola).exists():
        Ri.objects.create(
            escola=escola, status=Ri.IMPLANTACAO_EACE, responsavel=request.user
        )
        messages.success(request, "RI iniciado para este INEP.")
    return redirect("ri_detail", inep=inep)


@login_required
def ri_item_ixc_update_view(request, item_pk):
    """Edição do item do lado IXC — Administrador e Analista (RN-004)."""
    item = get_object_or_404(RiItemIxc, pk=item_pk)
    inep = item.ri.escola.inep
    if not _lado_ixc_editavel(item.ri):
        messages.error(request, MENSAGEM_LADO_IXC_SOMENTE_LEITURA)
        return redirect("ri_detail", inep=inep)
    if request.method == "POST":
        valor_anterior = _resumo_item_ixc(item.descricao_item, item.quantidade, item.valor_unitario)
        form = RiItemIxcForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            _registrar_log_campo(
                item.ri, request.user, "Item do Lado IXC (editado)", valor_anterior,
                _resumo_item_ixc(item.descricao_item, item.quantidade, item.valor_unitario),
            )
            # RN-003: recalcula o confronto formal contra o Lado Relatório
            # EACE a cada mudança do Lado IXC.
            sincronizar_divergencia_kit_relatorio(item.ri)
            messages.success(request, "Item do atendimento IXC atualizado.")
        else:
            messages.error(
                request, "Não foi possível salvar o item IXC: dados inválidos."
            )
    return redirect("ri_detail", inep=inep)


@login_required
def ri_item_ixc_delete_view(request, item_pk):
    """Exclusão do item do lado IXC — só Administrador (RN-004)."""
    item = get_object_or_404(RiItemIxc, pk=item_pk)
    inep = item.ri.escola.inep
    if not _lado_ixc_editavel(item.ri):
        messages.error(request, MENSAGEM_LADO_IXC_SOMENTE_LEITURA)
        return redirect("ri_detail", inep=inep)
    if not request.user.is_administrador:
        return HttpResponseForbidden("Somente Administrador pode excluir itens.")
    if request.method == "POST":
        ri = item.ri
        valor_anterior = _resumo_item_ixc(item.descricao_item, item.quantidade, item.valor_unitario)
        item.delete()
        _registrar_log_campo(ri, request.user, "Item do Lado IXC (excluído)", valor_anterior, "Excluído")
        # RN-003: recalcula o confronto formal contra o Lado Relatório
        # EACE a cada mudança do Lado IXC.
        sincronizar_divergencia_kit_relatorio(ri)
        messages.success(request, "Item do atendimento IXC excluído.")
    return redirect("ri_detail", inep=inep)


@login_required
def ri_item_relatorio_eace_update_view(request, item_pk):
    """RN-018 (ampliada, 2026-08-27): edição do item do Relatório EACE —
    exceção à imutabilidade geral da RN-003, hoje liberada para qualquer
    item desse lado (KIT ou Produto), não só o marcado como KIT. Usuário
    pediu a ampliação depois de sincronizar itens da Planilha EACE
    (FEAT-024) e não conseguir corrigir um Produto casado errado (ex.:
    "Nobreak") — o mesmo problema valeria para qualquer lançamento manual.
    Administrador e Analista (RN-004), mesma permissão do Lado IXC."""
    item = get_object_or_404(RiItemRelatorioEace, pk=item_pk)
    inep = item.ri.escola.inep
    if _bloqueado_faturamento_concluido(item.ri):
        messages.error(request, MENSAGEM_BLOQUEIO_FATURAMENTO_CONCLUIDO)
        return redirect("ri_detail", inep=inep)
    if request.method == "POST":
        valor_anterior = _resumo_item_ixc(item.descricao_item, item.quantidade, item.valor_unitario)
        form = RiItemRelatorioEaceForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            _registrar_log_campo(
                item.ri, request.user, "Item do Relatório EACE (editado)", valor_anterior,
                _resumo_item_ixc(item.descricao_item, item.quantidade, item.valor_unitario),
            )
            # RN-003: recalcula o confronto formal contra o Lado IXC a
            # cada mudança do Lado Relatório EACE.
            sincronizar_divergencia_kit_relatorio(item.ri)
            messages.success(request, "Item do Relatório EACE atualizado.")
        else:
            messages.error(
                request, "Não foi possível salvar o item do Relatório EACE: dados inválidos."
            )
    return redirect("ri_detail", inep=inep)


@login_required
def ri_item_relatorio_eace_delete_view(request, item_pk):
    """RN-018 (ampliada, 2026-08-27): exclusão de qualquer item do
    Relatório EACE (KIT ou Produto) — mesma exceção da edição acima, só
    Administrador (RN-004)."""
    item = get_object_or_404(RiItemRelatorioEace, pk=item_pk)
    inep = item.ri.escola.inep
    if _bloqueado_faturamento_concluido(item.ri):
        messages.error(request, MENSAGEM_BLOQUEIO_FATURAMENTO_CONCLUIDO)
        return redirect("ri_detail", inep=inep)
    if not request.user.is_administrador:
        return HttpResponseForbidden("Somente Administrador pode excluir itens.")
    if request.method == "POST":
        ri = item.ri
        valor_anterior = _resumo_item_ixc(item.descricao_item, item.quantidade, item.valor_unitario)
        item.delete()
        _registrar_log_campo(
            ri, request.user, "Item do Relatório EACE (excluído)", valor_anterior, "Excluído"
        )
        # RN-003: recalcula o confronto formal contra o Lado IXC a cada
        # mudança do Lado Relatório EACE.
        sincronizar_divergencia_kit_relatorio(ri)
        messages.success(request, "Item do Relatório EACE excluído.")
    return redirect("ri_detail", inep=inep)
