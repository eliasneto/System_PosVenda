"""Painel da fila do RPA EACE para TV (pedido do usuário, 2026-11-11).

Link direto, sem login, para deixar aberto numa televisão acompanhando o
processamento: `/fila-tv/<FILA_TV_TOKEN>/`. Só leitura - nenhuma ação, nenhum
link para dentro do sistema. A página se atualiza sozinha a cada 10 s
buscando só o conteúdo (`/conteudo/`), sem recarregar a página inteira.

Sem `FILA_TV_TOKEN` configurado, ou com o código errado no endereço, responde
404 (não revela que o painel existe).
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from django.conf import settings
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache

from apps.core.models import RoboRpaEace
from apps.escolas.models import LogRpaEaceMip

from .models import LogRpaEace

INTERVALO_SEGUNDOS = 10
QTD_PROXIMOS = 8
QTD_ULTIMOS = 8


def _validar_token(token: str) -> None:
    esperado = settings.FILA_TV_TOKEN
    if not esperado or not secrets.compare_digest(token.encode(), esperado.encode()):
        raise Http404


def _item_ri(log: LogRpaEace) -> dict:
    escola = log.ri.escola
    return {
        "tipo": "RI",
        "inep": escola.inep,
        "nome": escola.nome,
        "nota": log.documento_pdf.arquivo.name.rsplit("/", 1)[-1] if log.documento_pdf else "",
        "log": log,
    }


def _item_mip(log: LogRpaEaceMip) -> dict:
    return {
        "tipo": "MIP",
        "inep": f"LOTE {log.lote.estado}",
        "nome": log.lote.municipio,
        "nota": log.nome_nota_fiscal,
        "log": log,
    }


def _quando(item: dict):
    log = item["log"]
    return log.executado_em or log.enfileirado_em or log.criado_em


def contexto_fila_tv(agora=None) -> dict:
    agora = agora or timezone.now()
    inicio_do_dia = timezone.localtime(agora).replace(hour=0, minute=0, second=0, microsecond=0)
    uma_hora = agora - timedelta(hours=1)

    ri = LogRpaEace.objects.select_related("ri__escola", "documento_pdf", "robo")
    mip = LogRpaEaceMip.objects.select_related("lote", "robo")

    processando = [_item_ri(log) for log in ri.filter(resultado=LogRpaEace.PROCESSANDO)]
    processando += [_item_mip(log) for log in mip.filter(resultado=LogRpaEaceMip.PROCESSANDO)]
    processando.sort(key=lambda item: (item["log"].robo.nome if item["log"].robo else ""))

    proximos = [_item_ri(log) for log in ri.filter(resultado=LogRpaEace.NA_FILA).order_by("enfileirado_em", "id")[:QTD_PROXIMOS]]
    proximos += [_item_mip(log) for log in mip.filter(resultado=LogRpaEaceMip.NA_FILA).order_by("enfileirado_em", "id")[:QTD_PROXIMOS]]
    proximos.sort(key=_quando)
    proximos = proximos[:QTD_PROXIMOS]

    # "Últimas execuções": toda tentativa grava `executado_em`, inclusive a
    # que falhou e voltou para a fila (resultado "Na fila" com motivo).
    ultimos = [_item_ri(log) for log in ri.filter(executado_em__isnull=False).order_by("-executado_em")[:QTD_ULTIMOS]]
    ultimos += [_item_mip(log) for log in mip.filter(executado_em__isnull=False).order_by("-executado_em")[:QTD_ULTIMOS]]
    ultimos.sort(key=_quando, reverse=True)
    ultimos = ultimos[:QTD_ULTIMOS]

    def contar(qs_ri, qs_mip):
        return qs_ri.count() + qs_mip.count()

    sucesso_hoje = contar(
        LogRpaEace.objects.filter(resultado=LogRpaEace.SUCESSO, executado_em__gte=inicio_do_dia,
                                  concluido_manualmente=False),
        LogRpaEaceMip.objects.filter(resultado=LogRpaEaceMip.SUCESSO, executado_em__gte=inicio_do_dia),
    )
    erro_hoje = contar(
        LogRpaEace.objects.filter(resultado=LogRpaEace.ERRO, executado_em__gte=inicio_do_dia),
        LogRpaEaceMip.objects.filter(resultado=LogRpaEaceMip.ERRO, executado_em__gte=inicio_do_dia),
    )
    tentativas_hora = contar(
        LogRpaEace.objects.filter(executado_em__gte=uma_hora),
        LogRpaEaceMip.objects.filter(executado_em__gte=uma_hora),
    )
    sucesso_hora = contar(
        LogRpaEace.objects.filter(executado_em__gte=uma_hora, resultado=LogRpaEace.SUCESSO),
        LogRpaEaceMip.objects.filter(executado_em__gte=uma_hora, resultado=LogRpaEaceMip.SUCESSO),
    )

    ocupados = {item["log"].robo_id for item in processando}
    robos = [
        {"nome": robo.nome, "trabalhando": robo.pk in ocupados}
        for robo in RoboRpaEace.objects.filter(ativo=True).order_by("pk")
    ]
    if not robos:
        robos = [{"nome": "Robô padrão", "trabalhando": bool(processando)}]

    return {
        "agora": agora,
        "processando": processando,
        "proximos": proximos,
        "ultimos": ultimos,
        "robos": robos,
        "total_na_fila": contar(
            LogRpaEace.objects.filter(resultado=LogRpaEace.NA_FILA),
            LogRpaEaceMip.objects.filter(resultado=LogRpaEaceMip.NA_FILA),
        ),
        "total_processando": len(processando),
        "sucesso_hoje": sucesso_hoje,
        "erro_hoje": erro_hoje,
        "sucesso_hora": sucesso_hora,
        "falha_hora": tentativas_hora - sucesso_hora,
        "taxa_hora": round(100 * sucesso_hora / tentativas_hora) if tentativas_hora else None,
        "intervalo_segundos": INTERVALO_SEGUNDOS,
    }


@never_cache
def fila_tv_view(request, token):
    _validar_token(token)
    return render(request, "ri/fila_tv.html", {**contexto_fila_tv(), "token": token})


@never_cache
def fila_tv_conteudo_view(request, token):
    _validar_token(token)
    return render(request, "ri/_fila_tv_conteudo.html", contexto_fila_tv())
