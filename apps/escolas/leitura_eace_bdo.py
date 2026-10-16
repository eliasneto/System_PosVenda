"""Leitura EACE do BDO (pedido do usuário, 2026-10-16; RN-XXX a formalizar
pelo Orquestrador em business_rules.md).

Lê, no portal EACE, os cards de município da seção "Notas Fiscais" do
Boletim (o número do Boletim é o "Pedido" do grid de BDOs) e grava, em
cada `MunicipioBdo` do Boletim, Status, "Valor total a ser emitido" e o
arquivo da Nota Fiscal - para o grid "Por Município" da tela BDO mostrar
o mesmo que o portal. Nunca anexa nada (`rpa_bdo.ler_cards_bdo`).

- `enfileirar_leitura_eace_bdo`: botão "Atualizar do portal EACE" - só
  entra na fila; se o Boletim já tiver uma na fila/processando, reaproveita.
- `processar_proxima_leitura_eace_bdo`: executa a próxima da fila - quem
  chama é o worker da fila do RPA EACE (`processar_fila_rpa_eace`), quando
  não há envio de NF (RI/MIP) esperando, 1 login no portal por vez.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.integracoes.eace.rpa_mip import normalizar_texto

from .models import LeituraEaceBdo, MunicipioBdo
from .validacao_nf_mip import _orm_liberado_dentro_do_playwright, _valor_decimal, mensagem_motivo

logger = logging.getLogger(__name__)

TEMPO_MAXIMO_PROCESSANDO = timedelta(minutes=30)

MENSAGENS_MOTIVO_BDO = {
    "abrir_bdos": "Botão \"Ver BDOs\" não encontrado no portal.",
    "pedidos_nao_encontrados": "Nenhum pedido encontrado no grid de BDOs.",
    "pedido_nao_encontrado": "O Boletim não está no grid de BDOs do portal.",
    "abrir_notas_fiscais": "Não foi possível abrir a seção \"Notas Fiscais\" do Boletim.",
    "notas_fiscais_sem_cards": "A seção \"Notas Fiscais\" do Boletim ainda não tem nenhum card de município.",
}


def mensagem_motivo_bdo(motivo: str) -> str:
    return MENSAGENS_MOTIVO_BDO.get(motivo) or mensagem_motivo(motivo)


def enfileirar_leitura_eace_bdo(boletim, usuario=None) -> tuple[LeituraEaceBdo, bool]:
    with transaction.atomic():
        existente = (
            LeituraEaceBdo.objects.select_for_update()
            .filter(boletim=boletim, status__in=(LeituraEaceBdo.NA_FILA, LeituraEaceBdo.PROCESSANDO))
            .first()
        )
        if existente:
            return existente, False
        return LeituraEaceBdo.objects.create(boletim=boletim, solicitado_por=usuario), True


def recuperar_leituras_interrompidas(agora=None) -> int:
    """Marca como Erro as que ficaram "Processando" além do tempo máximo
    (worker reiniciado no meio) - senão o botão ficaria travado."""
    agora = agora or timezone.now()
    return LeituraEaceBdo.objects.filter(
        status=LeituraEaceBdo.PROCESSANDO, iniciado_em__lt=agora - TEMPO_MAXIMO_PROCESSANDO,
    ).update(status=LeituraEaceBdo.ERRO, motivo_erro="interrompida", finalizado_em=agora)


def _chave(municipio: str, uf: str) -> tuple[str, str]:
    return normalizar_texto(municipio), normalizar_texto(uf)


def aplicar_cards_no_boletim(boletim, cards: list[dict], agora=None) -> tuple[int, list[str]]:
    """Grava cada card no `MunicipioBdo` de mesmo Município/UF (sem acento
    e maiúscula). O mesmo município em 2+ cards: vale o de valor igual ao
    Valor total da planilha, senão o 1º. Município sem card fica com os
    campos vazios. Devolve (municípios atualizados, cards sem município
    no Boletim)."""
    agora = agora or timezone.now()
    livres: dict[tuple[str, str], list[dict]] = {}
    for card in cards:
        livres.setdefault(_chave(card["municipio"], card["uf"]), []).append(card)

    municipios = list(boletim.municipios.all())
    atualizados = 0
    for municipio in municipios:
        candidatos = livres.get(_chave(municipio.municipio, municipio.uf)) or []
        card = next(
            (c for c in candidatos if _valor_decimal(c["valor"]) == municipio.valor_total),
            candidatos[0] if candidatos else None,
        )
        if card:
            candidatos.remove(card)
            atualizados += 1
        municipio.status_eace = card["status"][:60] if card else ""
        municipio.valor_eace = _valor_decimal(card["valor"]) if card else None
        municipio.arquivo_nf_eace = (card.get("arquivo") or "")[:255] if card else ""
        municipio.eace_lido_em = agora
    MunicipioBdo.objects.bulk_update(
        municipios, ["status_eace", "valor_eace", "arquivo_nf_eace", "eace_lido_em"],
    )
    sobras = [f"{c['municipio']}/{c['uf']}" for restantes in livres.values() for c in restantes]
    return atualizados, sobras


def processar_proxima_leitura_eace_bdo() -> LeituraEaceBdo | None:
    """Executa a leitura mais antiga da fila (1 por chamada). Devolve a
    leitura processada, ou `None` se a fila estava vazia."""
    with transaction.atomic():
        leitura = (
            LeituraEaceBdo.objects.select_for_update()
            .filter(status=LeituraEaceBdo.NA_FILA)
            .select_related("boletim")
            .order_by("criado_em")
            .first()
        )
        if leitura is None:
            return None
        leitura.status = LeituraEaceBdo.PROCESSANDO
        leitura.iniciado_em = timezone.now()
        leitura.save(update_fields=["status", "iniciado_em"])

    def reportar_progresso(etapa, percentual):
        with _orm_liberado_dentro_do_playwright():
            LeituraEaceBdo.objects.filter(pk=leitura.pk).update(etapa_atual=etapa, progresso_pct=percentual)

    cards = []
    try:
        from apps.integracoes.eace.rpa_bdo import RpaBdoIndisponivel, ler_cards_bdo

        try:
            resultado = ler_cards_bdo(leitura.boletim.numero, progresso_callback=reportar_progresso)
        except RpaBdoIndisponivel:
            logger.exception("Leitura EACE do BDO #%s: ambiente sem Playwright/Chromium.", leitura.pk)
            leitura.status, leitura.motivo_erro = LeituraEaceBdo.ERRO, "ambiente_indisponivel"
        except ValueError:
            leitura.status, leitura.motivo_erro = LeituraEaceBdo.ERRO, "pedido_nao_encontrado"
        else:
            cards = resultado.cards_encontrados or []
            if resultado.sucesso:
                leitura.status, leitura.motivo_erro = LeituraEaceBdo.SUCESSO, ""
            else:
                leitura.status, leitura.motivo_erro = LeituraEaceBdo.ERRO, resultado.motivo or "erro_inesperado"
    except Exception:
        logger.exception("Leitura EACE do BDO #%s: erro inesperado.", leitura.pk)
        leitura.status, leitura.motivo_erro = LeituraEaceBdo.ERRO, "erro_inesperado"

    with transaction.atomic():
        leitura.finalizado_em = timezone.now()
        campos = ["status", "motivo_erro", "finalizado_em"]
        if leitura.status == LeituraEaceBdo.SUCESSO:
            atualizados, sobras = aplicar_cards_no_boletim(leitura.boletim, cards, leitura.finalizado_em)
            leitura.progresso_pct = 100
            leitura.cards_lidos = len(cards)
            leitura.municipios_atualizados = atualizados
            leitura.cards_sem_municipio = ", ".join(sobras)
            campos += ["progresso_pct", "cards_lidos", "municipios_atualizados", "cards_sem_municipio"]
        leitura.save(update_fields=campos)
    logger.info(
        "Leitura EACE do BDO #%s (Boletim %s): %s | %s card(s).",
        leitura.pk, leitura.boletim.numero, leitura.status, len(cards),
    )
    return leitura


def conferencia_eace_boletim(boletim) -> dict:
    """Pedido do usuário (2026-10-16): a quantidade de municípios da
    planilha importada tem que ser a mesma de cards no portal EACE, e o
    valor de cada município no Recebíveis/Medição é o do card. Usa a última
    leitura com Sucesso do Boletim (uma com Erro não apaga a anterior)."""
    leitura = boletim.leituras_eace.filter(status=LeituraEaceBdo.SUCESSO).first()
    total_planilha = boletim.municipios.count()
    sem_valor = boletim.municipios.filter(valor_eace__isnull=True).count()
    if leitura is None:
        mensagem = f"Boletim {boletim.numero} ainda não lido do portal EACE."
    elif leitura.cards_lidos != total_planilha:
        mensagem = (
            f"Boletim {boletim.numero}: {total_planilha} município(s) na planilha importada e "
            f"{leitura.cards_lidos} card(s) no portal EACE - a quantidade tem que ser a mesma."
        )
    elif sem_valor:
        mensagem = f"Boletim {boletim.numero}: {sem_valor} município(s) da planilha sem card no portal EACE."
    else:
        mensagem = ""
    return {
        "boletim": boletim,
        "leitura": leitura,
        "total_planilha": total_planilha,
        "cards_eace": leitura.cards_lidos if leitura else None,
        "confere": not mensagem,
        "mensagem": mensagem,
    }
