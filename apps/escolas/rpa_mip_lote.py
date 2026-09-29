"""Envio da Nota Fiscal de um LOTE (MIP) ao portal EACE (RN-XXX, a
formalizar pelo Orquestrador em business_rules.md; pedido do usuário,
2026-09-29).

Botão "Enviar ao portal EACE" de cada LOTE ("Projeto > MIP (LOTE)") ->
`enfileirar_rpa_mip_lote` cria 1 `LogRpaEaceMip` "Na fila". Quem executa
é o mesmo worker da fila do RPA EACE do RI (`manage.py
processar_fila_rpa_eace`, 1 por vez em todo o sistema - RN-058), que chama
`processar_proximo_rpa_mip` quando o item mais antigo da fila é do MIP.

A NF enviada é a comum a TODOS os INEPs do LOTE (decisão do usuário,
2026-09-29 - a NF é por município e o mesmo PDF é gravado em cada INEP que
ela referencia); INEP rateado pode ter NF de outro município também, por
isso "comum a todos", não "qualquer uma".
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.auditoria.models import Auditoria
from apps.auditoria.services import registrar as auditar

from .models import Lote, LogRpaEaceMip, NotaFiscalMip
from .validacao_nf_mip import _orm_liberado_dentro_do_playwright

logger = logging.getLogger(__name__)


def _chave_nome_nf(nome: str) -> str:
    """Mesma NF com nome gravado diferente em sincronizações diferentes
    (dado real, 2026-09-29: "377_..._NOME_MEGA_INFRA.pdf" de 24/09 e
    "377_..._NOME_MEGA INFRA.pdf" de 25/09, mesmo arquivo) - espaço e "_"
    contam como iguais, sem diferença de maiúscula."""
    return re.sub(r"[\s_]+", "_", nome.strip().lower())


def nota_fiscal_comum_do_lote(notas_por_escola: list[list[NotaFiscalMip]]) -> tuple[NotaFiscalMip | None, str]:
    """A NF (pelo nome do PDF, `_chave_nome_nf`) presente em todos os INEPs
    do LOTE - entre registros duplicados da mesma NF, vale a sincronização
    mais recente. Devolve `(nota, "")`, ou `(None, motivo)` quando não há
    exatamente 1."""
    if not notas_por_escola:
        return None, "O LOTE não tem INEPs."
    por_nome = []
    for notas in notas_por_escola:
        da_escola = {}
        for nota in notas:
            chave = _chave_nome_nf(nota.nome_original)
            atual = da_escola.get(chave)
            if atual is None or (nota.sincronizada_em or 0) > (atual.sincronizada_em or 0):
                da_escola[chave] = nota
        por_nome.append(da_escola)
    if any(not notas for notas in por_nome):
        return None, "Há INEP do LOTE sem Nota Fiscal sincronizada."
    comuns = set(por_nome[0]).intersection(*por_nome[1:])
    if not comuns:
        return None, "Nenhuma Nota Fiscal é comum a todos os INEPs do LOTE."
    if len(comuns) > 1:
        return None, f"{len(comuns)} Notas Fiscais são comuns a todos os INEPs do LOTE - não dá para escolher uma."
    return por_nome[0][comuns.pop()], ""


def _notas_por_escola(lote: Lote) -> list[list[NotaFiscalMip]]:
    """Usa o prefetch da tela (`escolas` + `notas_fiscais_mip`) quando
    houver - sem consulta extra por LOTE."""
    return [list(escola.notas_fiscais_mip.all()) for escola in lote.escolas.all()]


@dataclass
class EstadoRpaMipLote:
    """O que o botão do LOTE mostra (`_rpa_mip_lote_acao.html`)."""

    ultimo_log: LogRpaEaceMip | None
    nota_fiscal: NotaFiscalMip | None
    motivo_sem_nota: str

    @property
    def em_andamento(self) -> bool:
        return bool(self.ultimo_log and self.ultimo_log.em_andamento)

    @property
    def ja_estava_no_portal(self) -> bool:
        return bool(self.ultimo_log and self.ultimo_log.ja_estava_no_portal)

    @property
    def enviado(self) -> bool:
        """Sucesso, ou o card já não estava Pendente ("documento já
        enviado") - nos 2 casos o ícone fica desabilitado de vez."""
        return bool(
            self.ultimo_log and (self.ultimo_log.resultado == LogRpaEaceMip.SUCESSO or self.ja_estava_no_portal)
        )

    @property
    def pode_enviar(self) -> bool:
        return not self.em_andamento and not self.enviado and self.nota_fiscal is not None

    @property
    def motivo_erro_legivel(self) -> str:
        if self.ultimo_log and self.ultimo_log.resultado == LogRpaEaceMip.ERRO and not self.ja_estava_no_portal:
            return self.ultimo_log.motivo_erro_legivel
        return ""


def estados_rpa_mip_dos_lotes(lotes: list[Lote]) -> dict[int, EstadoRpaMipLote]:
    """Estado do botão de cada LOTE - 1 consulta só para os últimos logs
    de todos os LOTEs da página (sem N+1)."""
    ultimo_por_lote: dict[int, LogRpaEaceMip] = {}
    for log in LogRpaEaceMip.objects.filter(lote__in=lotes).order_by("lote_id", "-criado_em"):
        ultimo_por_lote.setdefault(log.lote_id, log)
    estados = {}
    for lote in lotes:
        nota, motivo = nota_fiscal_comum_do_lote(_notas_por_escola(lote))
        estados[lote.pk] = EstadoRpaMipLote(ultimo_por_lote.get(lote.pk), nota, motivo)
    return estados


def estado_rpa_mip_do_lote(lote: Lote) -> EstadoRpaMipLote:
    return estados_rpa_mip_dos_lotes([lote])[lote.pk]


class EnvioRpaMipRecusado(Exception):
    """Motivo (em português) de o botão não poder enfileirar agora."""


def enfileirar_rpa_mip_lote(lote: Lote, usuario) -> LogRpaEaceMip:
    """Coloca o envio da NF do LOTE na fila. Recusa (`EnvioRpaMipRecusado`)
    se já houver um envio na fila/processando, se o último envio já deu
    Sucesso, ou se o LOTE não tiver 1 NF comum a todos os INEPs."""
    with transaction.atomic():
        Lote.objects.select_for_update().filter(pk=lote.pk).first()
        ultimo = LogRpaEaceMip.objects.filter(lote=lote).order_by("-criado_em").first()
        if ultimo and ultimo.em_andamento:
            raise EnvioRpaMipRecusado("O envio da NF deste LOTE já está na fila.")
        if ultimo and ultimo.resultado == LogRpaEaceMip.SUCESSO:
            raise EnvioRpaMipRecusado("A NF deste LOTE já foi enviada ao portal com sucesso.")
        if ultimo and ultimo.ja_estava_no_portal:
            raise EnvioRpaMipRecusado(ultimo.motivo_erro_legivel)
        nota, motivo = nota_fiscal_comum_do_lote(_notas_por_escola(lote))
        if nota is None:
            raise EnvioRpaMipRecusado(motivo)
        log = LogRpaEaceMip.objects.create(
            lote=lote,
            nota_fiscal=nota,
            nome_nota_fiscal=nota.nome_original[:255],
            municipio=lote.municipio,
            solicitado_por=usuario,
            enfileirado_em=timezone.now(),
        )
    auditar(
        usuario,
        Auditoria.EXECUCAO_RPA_EACE,
        entidade="Lote",
        entidade_id=lote.pk,
        campo="Envio da NF ao portal EACE (MIP)",
        valor_novo=f"Na fila - {log.nome_nota_fiscal}",
    )
    return log


def proximo_enfileirado_rpa_mip_em():
    """`enfileirado_em` do envio do MIP mais antigo na fila (ou `None`) -
    o worker compara com o mais antigo do RI para respeitar a ordem de
    chegada da fila única."""
    log = LogRpaEaceMip.objects.filter(resultado=LogRpaEaceMip.NA_FILA).order_by("enfileirado_em").first()
    return log.enfileirado_em if log else None


def _registrar_execucao(log: LogRpaEaceMip) -> None:
    detalhe = log.get_resultado_display()
    if log.motivo_erro:
        detalhe += f" ({log.motivo_erro})"
    auditar(
        None,
        Auditoria.EXECUCAO_RPA_EACE,
        entidade="Lote",
        entidade_id=log.lote_id,
        campo="Envio da NF ao portal EACE (MIP)",
        valor_novo=f"{detalhe} - tentativa {log.tentativas} - {log.nome_nota_fiscal}",
    )


def recuperar_envios_mip_interrompidos() -> list[int]:
    """Mesmo critério de `apps.ri.services._recuperar_logs_processando_
    orfaos` (RN-058): um envio ainda "Processando" no começo de uma passada
    só pode ser de uma passada anterior que morreu no meio - volta para a
    fila 1 vez, ou vira Erro ("interrompido") na 2ª."""
    with transaction.atomic():
        orfaos = list(LogRpaEaceMip.objects.select_for_update().filter(resultado=LogRpaEaceMip.PROCESSANDO))
        for log in orfaos:
            log.tentativas += 1
            if log.tentativas < 2:
                log.resultado = LogRpaEaceMip.NA_FILA
                log.enfileirado_em = timezone.now()
            else:
                log.resultado = LogRpaEaceMip.ERRO
            log.motivo_erro = "interrompido"
            log.etapa_atual = ""
            log.progresso_pct = 0
            log.save(update_fields=[
                "resultado", "motivo_erro", "tentativas", "enfileirado_em", "etapa_atual", "progresso_pct",
            ])
    for log in orfaos:
        _registrar_execucao(log)
    return [log.pk for log in orfaos]


def processar_proximo_rpa_mip() -> dict | None:
    """Executa o envio do MIP mais antigo da fila (1 por chamada) e decide
    o próximo estado (RN-058): Sucesso; erro de regra de negócio
    (`MOTIVOS_REGRA_DE_NEGOCIO_MIP`) -> Erro definitivo; erro técnico com
    menos de 2 tentativas -> volta para o fim da fila; senão Erro.
    Devolve um dict do que aconteceu, ou `None` se não havia nada na fila."""
    from apps.integracoes.eace.rpa_mip import MOTIVOS_REGRA_DE_NEGOCIO_MIP, RpaMipIndisponivel, anexar_pdf_mip

    with transaction.atomic():
        log = (
            LogRpaEaceMip.objects.select_for_update(skip_locked=True)
            .select_related("lote", "nota_fiscal")
            .filter(resultado=LogRpaEaceMip.NA_FILA)
            .order_by("enfileirado_em")
            .first()
        )
        if log is None:
            return None
        log.resultado = LogRpaEaceMip.PROCESSANDO
        log.etapa_atual = ""
        log.progresso_pct = 0
        log.save(update_fields=["resultado", "etapa_atual", "progresso_pct"])

    def reportar_progresso(etapa, percentual):
        with _orm_liberado_dentro_do_playwright():
            LogRpaEaceMip.objects.filter(pk=log.pk).update(etapa_atual=etapa, progresso_pct=percentual)

    resultado_rpa = None
    caminho_pdf = None
    if log.nota_fiscal and log.nota_fiscal.arquivo:
        try:
            caminho_pdf = log.nota_fiscal.arquivo.path
        except (ValueError, NotImplementedError):
            caminho_pdf = None

    if not caminho_pdf:
        motivo = "nota_fiscal_ausente"
    else:
        try:
            resultado_rpa = anexar_pdf_mip(
                municipio=log.municipio, caminho_pdf=caminho_pdf, progresso_callback=reportar_progresso,
            )
        except RpaMipIndisponivel:
            motivo = "ambiente_indisponivel"
        except Exception:
            logger.exception("Erro inesperado no envio da NF do LOTE (log MIP %s).", log.pk)
            motivo = "erro_inesperado"
        else:
            motivo = resultado_rpa.motivo

    log.tentativas += 1
    log.executado_em = timezone.now()
    if resultado_rpa is not None:
        log.valor_pdf = (resultado_rpa.dados_pdf or {}).get("valor") or ""
        log.valor_portal = resultado_rpa.valor_portal or ""
        log.pedido = resultado_rpa.pedido or ""
        log.status_portal = (resultado_rpa.status_portal or "")[:60]

    if resultado_rpa is not None and resultado_rpa.sucesso:
        log.resultado = LogRpaEaceMip.SUCESSO
        log.motivo_erro = ""
        log.progresso_pct = 100
    elif motivo == "nota_fiscal_ausente" or motivo in MOTIVOS_REGRA_DE_NEGOCIO_MIP or log.tentativas >= 2:
        log.resultado = LogRpaEaceMip.ERRO
        log.motivo_erro = motivo or "erro_inesperado"
    else:
        log.resultado = LogRpaEaceMip.NA_FILA
        log.motivo_erro = motivo or "erro_inesperado"
        log.enfileirado_em = timezone.now()

    log.save()
    _registrar_execucao(log)
    return {"log_id": log.pk, "resultado": log.resultado, "motivo": log.motivo_erro}


def logs_mip_para_fila(status_filtro: str, inep_filtro: str = "", data_processamento=None):
    """Envios do MIP para a tela "Projeto > Fila" (mesma fila do RI) com os
    mesmos filtros dela: "andamento" (padrão) = Na fila/Processando,
    "todos" = os 4 resultados, ou um resultado específico (o que não
    existir no MIP, ex.: "Cancelado", não traz nada). INEP filtra os LOTEs
    que têm aquele INEP. Mesma ordenação da fila do RI."""
    from django.db.models import Case, IntegerField, Value, When
    from django.db.models.functions import Coalesce

    qs = LogRpaEaceMip.objects.select_related("lote", "solicitado_por")
    if status_filtro == "todos":
        pass
    elif status_filtro == "andamento":
        qs = qs.filter(resultado__in=(LogRpaEaceMip.NA_FILA, LogRpaEaceMip.PROCESSANDO))
    else:
        qs = qs.filter(resultado=status_filtro)
    if inep_filtro:
        qs = qs.filter(lote__escolas__inep__icontains=inep_filtro).distinct()
    if data_processamento:
        qs = qs.annotate(data_efetiva=Coalesce("executado_em", "enfileirado_em", "criado_em")).filter(
            data_efetiva__date=data_processamento
        )
    if status_filtro in ("andamento", "todos"):
        return qs.annotate(
            prioridade=Case(
                When(resultado=LogRpaEaceMip.PROCESSANDO, then=Value(0)),
                When(resultado=LogRpaEaceMip.NA_FILA, then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            )
        ).order_by("prioridade", "enfileirado_em")
    if status_filtro in (LogRpaEaceMip.SUCESSO, LogRpaEaceMip.ERRO):
        return qs.order_by("-executado_em", "-criado_em")
    return qs.order_by("enfileirado_em")
