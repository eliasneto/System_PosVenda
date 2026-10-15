"""Envio da Nota Fiscal de um LOTE (MIP) ao portal EACE (RN-XXX, a
formalizar pelo Orquestrador em business_rules.md; pedido do usuário,
2026-09-29).

Botão "Enviar ao portal EACE" de cada LOTE ("Projeto > MIP (LOTE)") ->
`enfileirar_rpa_mip_lote` cria 1 `LogRpaEaceMip` "Na fila" por NF a enviar.
Quem executa é o mesmo worker da fila do RPA EACE do RI (`manage.py
processar_fila_rpa_eace`, 1 por vez em todo o sistema - RN-058), que chama
`processar_proximo_rpa_mip` quando o item mais antigo da fila é do MIP.

A NF enviada é a comum a TODOS os INEPs do LOTE (decisão do usuário,
2026-09-29 - a NF é por município e o mesmo PDF é gravado em cada INEP que
ela referencia); INEP rateado pode ter NF de outro município também, por
isso "comum a todos", não "qualquer uma".

Rateio manual (decisão do usuário, 2026-10-15): cada parte do INEP vira
1 NF própria, então o LOTE pode ter mais de 1 NF - 1 envio por NF, todas
enfileiradas no mesmo clique; o valor do PDF escolhe o card no portal.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import timedelta

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


def _por_nome(notas: list[NotaFiscalMip]) -> dict[str, NotaFiscalMip]:
    """{chave do nome: NF} - entre registros duplicados da mesma NF, vale a
    sincronização mais recente."""
    da_escola = {}
    for nota in notas:
        chave = _chave_nome_nf(nota.nome_original)
        atual = da_escola.get(chave)
        if atual is None or (nota.sincronizada_em or 0) > (atual.sincronizada_em or 0):
            da_escola[chave] = nota
    return da_escola


def nota_fiscal_comum_do_lote(notas_por_escola: list[list[NotaFiscalMip]]) -> tuple[NotaFiscalMip | None, str]:
    """A NF (pelo nome do PDF, `_chave_nome_nf`) presente em todos os INEPs
    do LOTE. Devolve `(nota, "")`, ou `(None, motivo)` quando não há
    exatamente 1."""
    if not notas_por_escola:
        return None, "O LOTE não tem INEPs."
    por_nome = [_por_nome(notas) for notas in notas_por_escola]
    if any(not notas for notas in por_nome):
        return None, "Há INEP do LOTE sem Nota Fiscal sincronizada."
    comuns = set(por_nome[0]).intersection(*por_nome[1:])
    if not comuns:
        return None, "Nenhuma Nota Fiscal é comum a todos os INEPs do LOTE."
    if len(comuns) > 1:
        return None, f"{len(comuns)} Notas Fiscais são comuns a todos os INEPs do LOTE - não dá para escolher uma."
    return por_nome[0][comuns.pop()], ""


def notas_fiscais_do_lote(lote: Lote) -> tuple[list[NotaFiscalMip], str]:
    """NFs que o LOTE envia ao portal: a comum aos INEPs sem rateio manual
    (`nota_fiscal_comum_do_lote`) + 1 por parte de cada INEP com rateio
    manual (`Lote.rateio_manual`). Devolve `(notas, "")`, ou `([], motivo)`
    quando faltar ou sobrar NF. Usa o prefetch da tela (`escolas` +
    `notas_fiscais_mip`) quando houver - sem consulta extra por LOTE."""
    escolas = list(lote.escolas.all())
    if not escolas:
        return [], "O LOTE não tem INEPs."
    rateio_manual = lote.rateio_manual or {}
    sem_rateio = [escola for escola in escolas if not rateio_manual.get(escola.inep)]
    notas = {}
    if sem_rateio:
        nota, motivo = nota_fiscal_comum_do_lote([lote.notas_fiscais_da_escola(escola) for escola in sem_rateio])
        if nota is None:
            return [], motivo
        notas[_chave_nome_nf(nota.nome_original)] = nota
    for escola in escolas:
        partes = len(rateio_manual.get(escola.inep) or [])
        if not partes:
            continue
        das_partes = {
            chave: nota for chave, nota in _por_nome(lote.notas_fiscais_da_escola(escola)).items()
            if chave not in notas
        }
        if len(das_partes) != partes:
            return [], (
                f"O INEP {escola.inep} tem rateio em {partes} partes, mas {len(das_partes)} "
                "Nota(s) Fiscal(is) sincronizada(s) - precisa de 1 por parte."
            )
        notas.update(das_partes)
    return sorted(notas.values(), key=lambda nota: nota.nome_original), ""


@dataclass
class EstadoRpaMipLote:
    """O que o botão do LOTE mostra (`_rpa_mip_lote_acao.html`).
    `ultimo_log_por_nota`: último envio de cada NF do LOTE (chave
    `_chave_nome_nf`); `ultimo_log_do_lote`: o mais recente de todos."""

    notas_fiscais: list[NotaFiscalMip]
    motivo_sem_nota: str
    ultimo_log_por_nota: dict[str, LogRpaEaceMip] = field(default_factory=dict)
    ultimo_log_do_lote: LogRpaEaceMip | None = None

    def _ultimo_log(self, nota) -> LogRpaEaceMip | None:
        return self.ultimo_log_por_nota.get(_chave_nome_nf(nota.nome_original))

    @staticmethod
    def _log_enviado(log) -> bool:
        """Sucesso, ou o card já não estava Pendente ("documento já
        enviado") - nos 2 casos a NF não vai de novo."""
        return bool(log and (log.resultado == LogRpaEaceMip.SUCESSO or log.ja_estava_no_portal))

    @property
    def em_andamento(self) -> bool:
        return any(log.em_andamento for log in self.ultimo_log_por_nota.values())

    @property
    def notas_a_enviar(self) -> list[NotaFiscalMip]:
        return [
            nota for nota in self.notas_fiscais
            if not self._log_enviado(self._ultimo_log(nota))
            and not (self._ultimo_log(nota) and self._ultimo_log(nota).em_andamento)
        ]

    @property
    def enviado(self) -> bool:
        """Todas as NFs do LOTE enviadas - o ícone fica desabilitado de
        vez. Sem NF calculável (ex.: LOTE antigo), vale o último envio."""
        if self.notas_fiscais:
            return all(self._log_enviado(self._ultimo_log(nota)) for nota in self.notas_fiscais)
        return self._log_enviado(self.ultimo_log_do_lote)

    @property
    def ultimo_log(self) -> LogRpaEaceMip | None:
        """O envio que o botão descreve: o que está na fila/processando,
        senão o mais recente das NFs do LOTE."""
        andamento = [log for log in self.ultimo_log_por_nota.values() if log.em_andamento]
        if andamento:
            return next((log for log in andamento if log.resultado == LogRpaEaceMip.PROCESSANDO), andamento[0])
        logs = [log for log in map(self._ultimo_log, self.notas_fiscais) if log]
        return max(logs, key=lambda log: log.criado_em) if logs else self.ultimo_log_do_lote

    @property
    def ja_estava_no_portal(self) -> bool:
        return bool(self.ultimo_log and self.ultimo_log.ja_estava_no_portal)

    @property
    def nota_fiscal(self) -> NotaFiscalMip | None:
        """1ª NF ainda a enviar (o template habilita o botão com ela)."""
        return next(iter(self.notas_a_enviar), None)

    @property
    def pode_enviar(self) -> bool:
        return not self.em_andamento and not self.enviado and self.nota_fiscal is not None

    @property
    def motivo_erro_legivel(self) -> str:
        erros = [
            log for log in map(self._ultimo_log, self.notas_a_enviar)
            if log and log.resultado == LogRpaEaceMip.ERRO and not log.ja_estava_no_portal
        ]
        return max(erros, key=lambda log: log.criado_em).motivo_erro_legivel if erros else ""


def estados_rpa_mip_dos_lotes(lotes: list[Lote]) -> dict[int, EstadoRpaMipLote]:
    """Estado do botão de cada LOTE - 1 consulta só para os logs de todos
    os LOTEs da página (sem N+1)."""
    ultimo_por_lote: dict[int, LogRpaEaceMip] = {}
    ultimo_por_nota: dict[int, dict[str, LogRpaEaceMip]] = {}
    for log in LogRpaEaceMip.objects.filter(lote__in=lotes).order_by("lote_id", "-criado_em"):
        ultimo_por_lote.setdefault(log.lote_id, log)
        ultimo_por_nota.setdefault(log.lote_id, {}).setdefault(_chave_nome_nf(log.nome_nota_fiscal), log)
    estados = {}
    for lote in lotes:
        notas, motivo = notas_fiscais_do_lote(lote)
        estados[lote.pk] = EstadoRpaMipLote(
            notas, motivo, ultimo_por_nota.get(lote.pk, {}), ultimo_por_lote.get(lote.pk)
        )
    return estados


def estado_rpa_mip_do_lote(lote: Lote) -> EstadoRpaMipLote:
    return estados_rpa_mip_dos_lotes([lote])[lote.pk]


class EnvioRpaMipRecusado(Exception):
    """Motivo (em português) de o botão não poder enfileirar agora."""


def enfileirar_rpa_mip_lote(lote: Lote, usuario) -> list[LogRpaEaceMip]:
    """Coloca na fila 1 envio por NF do LOTE ainda não enviada. Recusa
    (`EnvioRpaMipRecusado`) se já houver envio na fila/processando, se
    todas as NFs já foram enviadas, ou se faltar/sobrar NF
    (`notas_fiscais_do_lote`)."""
    with transaction.atomic():
        Lote.objects.select_for_update().filter(pk=lote.pk).first()
        if lote.status == Lote.REPROVADO:
            raise EnvioRpaMipRecusado("LOTE reprovado pelo cliente — a NF dele não vai ao portal.")
        estado = estado_rpa_mip_do_lote(lote)
        if estado.em_andamento:
            raise EnvioRpaMipRecusado("O envio da NF deste LOTE já está na fila.")
        if estado.enviado:
            if estado.ja_estava_no_portal:
                raise EnvioRpaMipRecusado(estado.ultimo_log.motivo_erro_legivel)
            raise EnvioRpaMipRecusado("A NF deste LOTE já foi enviada ao portal com sucesso.")
        if not estado.notas_a_enviar:
            raise EnvioRpaMipRecusado(estado.motivo_sem_nota)
        agora = timezone.now()
        logs = [
            LogRpaEaceMip.objects.create(
                lote=lote,
                nota_fiscal=nota,
                nome_nota_fiscal=nota.nome_original[:255],
                municipio=lote.municipio,
                solicitado_por=usuario,
                # Mesma ordem de chegada na fila que a ordem das NFs.
                enfileirado_em=agora + timedelta(microseconds=ordem),
            )
            for ordem, nota in enumerate(estado.notas_a_enviar)
        ]
    for log in logs:
        auditar(
            usuario,
            Auditoria.EXECUCAO_RPA_EACE,
            entidade="Lote",
            entidade_id=lote.pk,
            campo="Envio da NF ao portal EACE (MIP)",
            valor_novo=f"Na fila - {log.nome_nota_fiscal}",
        )
    return logs


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
