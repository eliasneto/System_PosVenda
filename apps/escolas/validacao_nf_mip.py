"""Rotina "Validação MIP (NF)" (RN-XXX, a formalizar pelo Orquestrador em
business_rules.md; pedido do usuário, 2026-09-28).

Lê, no portal EACE, os cards de município do pedido de MAIOR número do
MIP (Município, Status e "Valor total a ser emitido") e guarda o
resultado em `ValidacaoNfMip`/`CardValidacaoNfMip`. Nunca anexa nada: usa
o RPA do MIP (`apps.integracoes.eace.rpa_mip.anexar_pdf_mip`) em modo
simulação, sem PDF e sem município.

- `agendar_validacao_nf_mip_se_devido`: 1 execução "agendada" por hora
  cheia, das 08:00 às 19:00 (fuso do sistema, `TIME_ZONE`).
- `enfileirar_validacao_nf_mip`: botão "Rodar agora" (e o agendamento) -
  só entra na fila; se já houver uma na fila/processando, reaproveita.
- `processar_proxima_validacao_nf_mip`: executa a próxima da fila - quem
  chama em loop é o worker do MIP (`manage.py processar_validacao_nf_mip`).
"""

from __future__ import annotations

import logging
import os
import re
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from decouple import config as env
from django.db import transaction
from django.utils import timezone

from .models import CardValidacaoNfMip, ValidacaoNfMip

logger = logging.getLogger(__name__)

HORA_INICIO_AGENDADA = 8
HORA_FIM_AGENDADA = 19


def agendamento_ativo() -> bool:
    """Pedido do usuário (2026-09-28): a execução automática (08h-19h) fica
    DESLIGADA até ele definir a partir de quando deve rodar - só o botão
    "Rodar agora" enfileira. Para ligar: `VALIDACAO_NF_MIP_AGENDADA=True`
    no `.env` do worker do MIP."""
    return env("VALIDACAO_NF_MIP_AGENDADA", default=False, cast=bool)

# Uma execução normal leva poucos minutos; "Processando" há mais que isso
# só acontece se o worker morreu no meio (deploy, reinício do container).
TEMPO_MAXIMO_PROCESSANDO = timedelta(minutes=30)

MENSAGENS_MOTIVO = {
    "credenciais_ausentes": "Usuário/senha do portal EACE não configurados.",
    "login": "O portal EACE recusou o login.",
    "selecao_perfil": "O portal não respondeu ao selecionar o perfil Fornecedor.",
    "abrir_medicoes": "Card \"Medições\" não encontrado no portal.",
    "abrir_mips": "Botão \"Ver MIPs\" não encontrado no portal.",
    "pedidos_nao_encontrados": "Nenhum pedido encontrado no grid de MIPs.",
    "pedido_nao_encontrado": "O pedido informado não está no grid de MIPs.",
    "expandir_pedido": "Não foi possível expandir o pedido.",
    "municipio_nao_encontrado": "Nenhum card deste município no pedido mais recente do portal.",
    # Envio da NF do LOTE (`apps.escolas.rpa_mip_lote`).
    "pdf_ilegivel": "Não foi possível ler o PDF da Nota Fiscal.",
    "pdf_sem_valor": "O PDF da Nota Fiscal não tem o \"Valor Total da Nota\".",
    "documento_ja_enviado": "O card do município no portal não está mais \"Pendente\" (NF já enviada).",
    "valor_divergente": "O valor da Nota Fiscal é diferente do valor do card do município no portal.",
    "valor_ambiguo": "Mais de um card pendente do município tem o mesmo valor da NF - resolver manualmente.",
    "upload": "Falha ao anexar o PDF no card do portal.",
    "envio_nao_confirmado": "PDF anexado, mas o card não mudou para \"Aguardando Aprovação\" - conferir no portal.",
    "nota_fiscal_ausente": "O arquivo da Nota Fiscal não existe mais no sistema.",
    "interrompido": "Execução interrompida (o worker parou no meio).",
    "erro_playwright": "Erro inesperado do navegador (rede ou portal fora do ar).",
    "ambiente_indisponivel": "Navegador da automação não instalado no servidor.",
    "interrompida": "Execução interrompida (o worker parou no meio).",
    "erro_inesperado": "Erro inesperado na rotina.",
}


def mensagem_motivo(motivo: str) -> str:
    return MENSAGENS_MOTIVO.get(motivo, motivo)


@contextmanager
def _orm_liberado_dentro_do_playwright():
    """Mesmo escape-hatch já usado no progresso do RPA EACE do RI
    (`apps.ri.services`, RN-058): o `sync_playwright` roda um event loop
    na mesma thread e o Django bloqueia o ORM com `SynchronousOnlyOperation`
    (falso positivo - o código é síncrono). Liga só ao redor da gravação."""
    anterior = os.environ.get("DJANGO_ALLOW_ASYNC_UNSAFE")
    os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
    try:
        yield
    finally:
        if anterior is None:
            os.environ.pop("DJANGO_ALLOW_ASYNC_UNSAFE", None)
        else:
            os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = anterior


def enfileirar_validacao_nf_mip(origem: str, usuario=None, pedido: str = "") -> tuple[ValidacaoNfMip, bool]:
    """Coloca uma validação na fila - `pedido` vazio lê o pedido de maior
    número; preenchido, lê exatamente aquele. Se já existir uma "Na fila"
    ou "Processando", devolve essa (`criada=False`) em vez de criar outra
    (1 leitura do portal por vez)."""
    with transaction.atomic():
        existente = (
            ValidacaoNfMip.objects.select_for_update()
            .filter(status__in=(ValidacaoNfMip.NA_FILA, ValidacaoNfMip.PROCESSANDO))
            .order_by("criado_em")
            .first()
        )
        if existente:
            return existente, False
        return ValidacaoNfMip.objects.create(
            origem=origem, solicitado_por=usuario, pedido_solicitado=(pedido or "").strip(),
        ), True


def agendar_validacao_nf_mip_se_devido(agora=None) -> ValidacaoNfMip | None:
    """Enfileira a execução agendada da hora atual, se estiver entre 08:00
    e 19:59 e ainda não houver uma agendada criada nesta hora. Se uma
    manual estiver em andamento, não cria nada agora - a próxima passada
    do worker (depois que ela terminar) cria a agendada da hora. Não faz
    nada enquanto o agendamento estiver desligado (`agendamento_ativo`)."""
    if not agendamento_ativo():
        return None
    local = timezone.localtime(agora or timezone.now())
    if not HORA_INICIO_AGENDADA <= local.hour <= HORA_FIM_AGENDADA:
        return None
    inicio_da_hora = local.replace(minute=0, second=0, microsecond=0)
    if ValidacaoNfMip.objects.filter(origem=ValidacaoNfMip.AGENDADA, criado_em__gte=inicio_da_hora).exists():
        return None
    validacao, criada = enfileirar_validacao_nf_mip(ValidacaoNfMip.AGENDADA)
    return validacao if criada else None


def recuperar_validacoes_interrompidas(agora=None) -> int:
    """Marca como Erro as que ficaram "Processando" além do tempo máximo
    (worker reiniciado no meio) - senão a fila travaria para sempre."""
    limite = (agora or timezone.now()) - TEMPO_MAXIMO_PROCESSANDO
    return ValidacaoNfMip.objects.filter(
        status=ValidacaoNfMip.PROCESSANDO, iniciado_em__lt=limite
    ).update(
        status=ValidacaoNfMip.ERRO,
        motivo_erro="interrompida",
        finalizado_em=agora or timezone.now(),
    )


def _valor_decimal(texto: str) -> Decimal | None:
    """ "16.109,00" -> Decimal("16109.00")."""
    limpo = re.sub(r"[^\d,]", "", texto or "").replace(",", ".")
    try:
        return Decimal(limpo) if limpo else None
    except InvalidOperation:
        return None


def processar_proxima_validacao_nf_mip() -> ValidacaoNfMip | None:
    """Executa a validação mais antiga da fila (1 por chamada). Devolve a
    validação processada, ou `None` se a fila estava vazia."""
    with transaction.atomic():
        validacao = (
            ValidacaoNfMip.objects.select_for_update()
            .filter(status=ValidacaoNfMip.NA_FILA)
            .order_by("criado_em")
            .first()
        )
        if validacao is None:
            return None
        validacao.status = ValidacaoNfMip.PROCESSANDO
        validacao.iniciado_em = timezone.now()
        validacao.save(update_fields=["status", "iniciado_em"])

    def reportar_progresso(etapa, percentual):
        with _orm_liberado_dentro_do_playwright():
            ValidacaoNfMip.objects.filter(pk=validacao.pk).update(etapa_atual=etapa, progresso_pct=percentual)

    cards = []
    try:
        from apps.integracoes.eace.rpa_mip import RpaMipIndisponivel, anexar_pdf_mip

        try:
            resultado = anexar_pdf_mip(
                municipio=None, caminho_pdf=None, simular=True, progresso_callback=reportar_progresso,
                pedido=validacao.pedido_solicitado or None,
            )
        except RpaMipIndisponivel:
            logger.exception("Validação MIP (NF) #%s: ambiente sem Playwright/Chromium.", validacao.pk)
            validacao.status, validacao.motivo_erro = ValidacaoNfMip.ERRO, "ambiente_indisponivel"
        else:
            validacao.pedido = resultado.pedido or ""
            cards = resultado.cards_encontrados or []
            if resultado.sucesso:
                validacao.status, validacao.motivo_erro = ValidacaoNfMip.SUCESSO, ""
            else:
                validacao.status, validacao.motivo_erro = ValidacaoNfMip.ERRO, resultado.motivo or "erro_inesperado"
    except Exception:
        logger.exception("Validação MIP (NF) #%s: erro inesperado.", validacao.pk)
        validacao.status, validacao.motivo_erro = ValidacaoNfMip.ERRO, "erro_inesperado"

    with transaction.atomic():
        validacao.finalizado_em = timezone.now()
        if validacao.status == ValidacaoNfMip.SUCESSO:
            validacao.progresso_pct = 100
        validacao.save(update_fields=["status", "motivo_erro", "pedido", "finalizado_em", "progresso_pct"])
        CardValidacaoNfMip.objects.bulk_create([
            CardValidacaoNfMip(
                validacao=validacao,
                ordem=card["posicao"],
                municipio=card["municipio"][:150],
                uf=card["uf"][:10],
                codigo_ibge=card["ibge"][:10],
                status_portal=card["status"][:60],
                valor=_valor_decimal(card["valor"]),
            )
            for card in cards
        ])
    logger.info(
        "Validação MIP (NF) #%s: %s | pedido=%s | %s card(s).",
        validacao.pk, validacao.status, validacao.pedido, len(cards),
    )
    return validacao


def ultima_validacao_com_cards() -> ValidacaoNfMip | None:
    """Última execução com Sucesso - é ela que alimenta o grid (uma
    execução com Erro não apaga o que já foi lido antes)."""
    return ValidacaoNfMip.objects.filter(status=ValidacaoNfMip.SUCESSO).order_by("-finalizado_em").first()
