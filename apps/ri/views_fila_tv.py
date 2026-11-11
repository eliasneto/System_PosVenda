"""Painel da fila do RPA EACE para TV (pedido do usuário, 2026-11-11).

Link direto, sem login, para deixar aberto numa televisão acompanhando o
processamento: `/fila-tv/<FILA_TV_TOKEN>/`. Só leitura - nenhuma ação, nenhum
link para dentro do sistema. A página se atualiza sozinha a cada 10 s
buscando só o conteúdo (`/conteudo/`), sem recarregar a página inteira.

Sem `FILA_TV_TOKEN` configurado, ou com o código errado no endereço, responde
404 (não revela que o painel existe).
"""

from __future__ import annotations

import math
import os
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


# Saúde do servidor no painel (pedido do usuário, 2026-11-11): o container
# lê /proc do Linux, que mostra a memória e a carga da máquina inteira (não
# só do container). Limites calibrados no incidente de 2026-11-11 (3,8 GB,
# swap cheio, metade das notas falhando): abaixo de 1 GB livre o Chromium
# dos robôs começa a ficar lento.
MEMORIA_CRITICA_MB = 1024
MEMORIA_ATENCAO_MB = 2048
CARGA_ATENCAO = 0.9  # carga média de 1 min / núcleos
CARGA_CRITICA = 1.5


def _ler_meminfo(caminho="/proc/meminfo") -> dict[str, int]:
    valores = {}
    with open(caminho, encoding="ascii") as arquivo:
        for linha in arquivo:
            nome, _, resto = linha.partition(":")
            partes = resto.split()
            if partes:
                valores[nome] = int(partes[0])  # kB
    return valores


def saude_servidor(meminfo="/proc/meminfo", loadavg="/proc/loadavg") -> dict | None:
    """Memória livre e carga do processador do servidor, com o nível
    ("ok"/"atencao"/"critico") de cada uma e a mensagem do alerta. `None`
    fora do Linux (ex.: rodando direto no Windows)."""
    try:
        mem = _ler_meminfo(meminfo)
        with open(loadavg, encoding="ascii") as arquivo:
            carga_1min = float(arquivo.read().split()[0])
    except (OSError, ValueError, IndexError):
        return None
    nucleos = os.cpu_count() or 1
    livre_mb = mem.get("MemAvailable", 0) // 1024
    total_mb = mem.get("MemTotal", 0) // 1024
    swap_usado_mb = (mem.get("SwapTotal", 0) - mem.get("SwapFree", 0)) // 1024
    carga = carga_1min / nucleos

    nivel_memoria = (
        "critico" if livre_mb < MEMORIA_CRITICA_MB else "atencao" if livre_mb < MEMORIA_ATENCAO_MB else "ok"
    )
    nivel_cpu = "critico" if carga >= CARGA_CRITICA else "atencao" if carga >= CARGA_ATENCAO else "ok"
    alertas = []
    if nivel_memoria == "critico":
        alertas.append(
            f"Memória do servidor quase no fim ({livre_mb / 1024:.1f} GB livre) - os robôs vão ficar lentos "
            "e falhar. Desative um robô no admin."
        )
    if nivel_cpu == "critico":
        alertas.append(
            f"Processador do servidor sobrecarregado ({round(carga * 100)}%) - as notas vão demorar mais. "
            "Se continuar, desative um robô no admin."
        )
    return {
        "livre_gb": f"{livre_mb / 1024:.1f}".replace(".", ","),
        "total_gb": f"{total_mb / 1024:.0f}",
        "swap_usado_gb": f"{swap_usado_mb / 1024:.1f}".replace(".", ",") if swap_usado_mb > 256 else "",
        "nivel_memoria": nivel_memoria,
        "cpu_pct": round(carga * 100),
        "nivel_cpu": nivel_cpu,
        "alertas": alertas,
    }


def _previsao_fila_zerar(pendentes: int, saida_hora: int, agora) -> dict | None:
    """{"texto": "~2 h 30 min", "as": "16:40"} - `None` quando a fila já está
    vazia; {"texto": None} quando nada saiu da fila na última hora (sem
    ritmo para calcular)."""
    if not pendentes:
        return None
    if not saida_hora:
        return {"texto": None, "as": None}
    minutos = max(1, math.ceil(pendentes * 60 / saida_hora))
    horas, resto = divmod(minutos, 60)
    if not horas:
        texto = f"~{resto} min"
    elif horas >= 24:
        texto = f"~{math.ceil(minutos / 1440 * 10) / 10:g} dia(s)".replace(".", ",")
    else:
        texto = f"~{horas} h" + (f" {resto:02d} min" if resto else "")
    fim = timezone.localtime(agora + timedelta(minutes=minutos))
    mesmo_dia = fim.date() == timezone.localtime(agora).date()
    return {"texto": texto, "as": fim.strftime("%H:%M") if mesmo_dia else fim.strftime("%d/%m %H:%M")}


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
    atencao_hoje = contar(
        LogRpaEace.objects.filter(resultado=LogRpaEace.ATENCAO, executado_em__gte=inicio_do_dia),
        LogRpaEaceMip.objects.filter(resultado=LogRpaEaceMip.ATENCAO, executado_em__gte=inicio_do_dia),
    )
    erro_hoje = contar(
        LogRpaEace.objects.filter(resultado=LogRpaEace.ERRO, executado_em__gte=inicio_do_dia),
        LogRpaEaceMip.objects.filter(resultado=LogRpaEaceMip.ERRO, executado_em__gte=inicio_do_dia),
    )
    # Pedido do usuário (2026-11-11): o que está sendo reprocessado agora
    # ("Processando") não conta como falha - só conta o que terminou mal
    # (Erro) ou ainda espera a nova tentativa (Na fila); assim que a nova
    # tentativa dá certo, o log vira Sucesso e sai da contagem.
    tentativas_hora = contar(
        LogRpaEace.objects.filter(executado_em__gte=uma_hora).exclude(resultado=LogRpaEace.PROCESSANDO),
        LogRpaEaceMip.objects.filter(executado_em__gte=uma_hora).exclude(resultado=LogRpaEaceMip.PROCESSANDO),
    )
    sucesso_hora = contar(
        LogRpaEace.objects.filter(executado_em__gte=uma_hora, resultado__in=LogRpaEace.RESULTADOS_ENVIADOS),
        LogRpaEaceMip.objects.filter(executado_em__gte=uma_hora, resultado__in=(LogRpaEaceMip.SUCESSO, LogRpaEaceMip.ATENCAO)),
    )

    # Previsão de quando a fila zera (pedido do usuário, 2026-11-11): no
    # ritmo da última hora, contando só o que SAIU da fila (Sucesso, Atenção
    # ou Erro definitivo) - a nova tentativa volta para a fila, não conta.
    saida_hora = contar(
        LogRpaEace.objects.filter(
            executado_em__gte=uma_hora,
            resultado__in=(LogRpaEace.SUCESSO, LogRpaEace.ATENCAO, LogRpaEace.ERRO),
        ),
        LogRpaEaceMip.objects.filter(
            executado_em__gte=uma_hora,
            resultado__in=(LogRpaEaceMip.SUCESSO, LogRpaEaceMip.ATENCAO, LogRpaEaceMip.ERRO),
        ),
    )
    total_na_fila = contar(
        LogRpaEace.objects.filter(resultado=LogRpaEace.NA_FILA),
        LogRpaEaceMip.objects.filter(resultado=LogRpaEaceMip.NA_FILA),
    )
    previsao = _previsao_fila_zerar(total_na_fila + len(processando), saida_hora, agora)

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
        "total_na_fila": total_na_fila,
        "saida_hora": saida_hora,
        "previsao": previsao,
        "total_processando": len(processando),
        "sucesso_hoje": sucesso_hoje,
        "erro_hoje": erro_hoje,
        "atencao_hoje": atencao_hoje,
        "sucesso_hora": sucesso_hora,
        "falha_hora": tentativas_hora - sucesso_hora,
        "taxa_hora": round(100 * sucesso_hora / tentativas_hora) if tentativas_hora else None,
        "intervalo_segundos": INTERVALO_SEGUNDOS,
        "servidor": saude_servidor(),
    }


@never_cache
def fila_tv_view(request, token):
    _validar_token(token)
    return render(request, "ri/fila_tv.html", {**contexto_fila_tv(), "token": token})


@never_cache
def fila_tv_conteudo_view(request, token):
    _validar_token(token)
    return render(request, "ri/_fila_tv_conteudo.html", contexto_fila_tv())
