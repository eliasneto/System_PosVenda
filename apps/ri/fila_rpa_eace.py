"""Robôs do RPA EACE em paralelo (ADR-009; pedido do usuário, 2026-11-10).

Emenda a RN-058/ADR-008 ("no máximo 1 execução do portal por vez"): cada
robô ativo cadastrado no admin (`apps.core.models.RoboRpaEace`) é 1
processo próprio, com navegador e login próprios, consumindo a MESMA fila
(envios do RI e do MIP, ordem de chegada). Garantias para um não atrapalhar
o outro:

1. **Reserva sob trava** - `reservar_proximo_envio` escolhe e marca o item
   "Processando" dentro de uma transação que trava a linha única de
   `TravaFilaRpaEace`; 2 robôs nunca reservam ao mesmo tempo, então nunca
   pegam o mesmo item. A trava é solta antes de abrir o navegador - a
   execução roda em paralelo.
2. **1 robô por INEP** - um item cujo INEP (ou LOTE, no MIP) já está
   "Processando" em outro robô é pulado; o robô pega o próximo livre. Evita
   2 robôs mexendo no mesmo pedido do portal e a corrida no avanço do
   status do RI (RN-056) entre 2 NFs do mesmo INEP.
3. **Cada robô recupera só o que é seu** - log preso em "Processando" só
   volta para a fila quando o robô dono não está rodando (`robo` no log).
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Q

from apps.core.models import RoboRpaEace, TravaFilaRpaEace
from apps.escolas.models import LogRpaEaceMip
from apps.escolas.rpa_mip_lote import executar_envio_mip, recuperar_envios_mip_interrompidos

from .models import LogRpaEace
from .services import _recuperar_logs_processando_orfaos, executar_log_rpa_eace

RI = "RI"
MIP = "MIP"

# Quantos itens "Na fila" de cada tipo olhar por reserva, procurando um de
# INEP livre - a fila real fica bem abaixo disso.
LIMITE_CANDIDATOS = 300


def filtro_dos_robos(robo_ids) -> Q:
    """Logs cujo robô está em `robo_ids` (`None` = robô padrão do .env)."""
    robo_ids = set(robo_ids)
    filtro = Q(robo_id__in=[pk for pk in robo_ids if pk is not None])
    if None in robo_ids:
        filtro |= Q(robo__isnull=True)
    return filtro


def recuperar_envios_interrompidos(filtro: Q) -> list[str]:
    """Devolve para a fila (ou Erro "interrompido", na 2ª vez - RN-058) os
    envios RI/MIP "Processando" que casam com `filtro`. Devolve os ids
    recuperados, prefixados pelo tipo."""
    with transaction.atomic():
        ri = _recuperar_logs_processando_orfaos(filtro)
    mip = recuperar_envios_mip_interrompidos(filtro)
    return [f"{RI}#{pk}" for pk in ri] + [f"{MIP}#{pk}" for pk in mip]


def recuperar_envios_de_robos_parados(robos_rodando) -> list[str]:
    """Supervisor: tudo "Processando" de um robô que não tem processo
    rodando agora só pode ser resto de um processo que morreu no meio."""
    return recuperar_envios_interrompidos(~filtro_dos_robos(robos_rodando))


def _ineps_ocupados() -> tuple[set[str], set[int]]:
    ineps = set(
        LogRpaEace.objects.filter(resultado=LogRpaEace.PROCESSANDO).values_list("ri__escola__inep", flat=True)
    )
    ineps |= set(
        LogRpaEaceMip.objects.filter(resultado=LogRpaEaceMip.PROCESSANDO).values_list(
            "lote__escolas__inep", flat=True
        )
    )
    lotes = set(
        LogRpaEaceMip.objects.filter(resultado=LogRpaEaceMip.PROCESSANDO).values_list("lote_id", flat=True)
    )
    ineps.discard(None)
    return ineps, lotes


def _candidatos():
    """Itens "Na fila" de RI e MIP em ordem de chegada (`enfileirado_em`;
    no empate o RI vem antes - mesmo critério do worker único anterior)."""
    ris = (
        LogRpaEace.objects.filter(resultado=LogRpaEace.NA_FILA)
        .select_related("ri__escola")
        .order_by("enfileirado_em", "id")[:LIMITE_CANDIDATOS]
    )
    mips = (
        LogRpaEaceMip.objects.filter(resultado=LogRpaEaceMip.NA_FILA)
        .prefetch_related("lote__escolas")
        .order_by("enfileirado_em", "id")[:LIMITE_CANDIDATOS]
    )
    itens = [((log.enfileirado_em or log.criado_em), 0, log.pk, RI, log) for log in ris]
    itens += [((log.enfileirado_em or log.criado_em), 1, log.pk, MIP, log) for log in mips]
    itens.sort(key=lambda item: item[:3])
    for _, _, _, tipo, log in itens:
        if tipo == RI:
            yield tipo, log, {log.ri.escola.inep}
        else:
            yield tipo, log, {escola.inep for escola in log.lote.escolas.all()}


def reservar_proximo_envio(robo: RoboRpaEace | None):
    """Marca "Processando" (com o robô) o envio mais antigo da fila cujo
    INEP/LOTE não esteja com outro robô. Devolve `(tipo, log)` ou `None`
    se não houver nada livre."""
    with transaction.atomic():
        TravaFilaRpaEace.objects.select_for_update().get_or_create(pk=1)
        ineps_ocupados, lotes_ocupados = _ineps_ocupados()
        for tipo, log, ineps in _candidatos():
            if ineps & ineps_ocupados:
                continue
            if tipo == MIP and log.lote_id in lotes_ocupados:
                continue
            modelo = LogRpaEace if tipo == RI else LogRpaEaceMip
            reservado = modelo.objects.filter(pk=log.pk, resultado=modelo.NA_FILA).update(
                resultado=modelo.PROCESSANDO, etapa_atual="", progresso_pct=0, robo=robo,
            )
            if reservado:
                return tipo, log.pk
    return None


def executar_envio_reservado(tipo: str, log_id: int) -> dict:
    """Roda o RPA do envio já reservado - fora da trava, em paralelo com
    os outros robôs."""
    if tipo == RI:
        log = LogRpaEace.objects.select_related(
            "ri", "ri__escola", "documento_pdf", "documento_xml",
        ).get(pk=log_id)
        return executar_log_rpa_eace(log)
    log = LogRpaEaceMip.objects.select_related("lote", "nota_fiscal").get(pk=log_id)
    return executar_envio_mip(log)
