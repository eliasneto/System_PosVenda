"""Processo do RI cancelado pela EACE depois do envio ao financeiro (pedido do usuário, 2026-11-13).

O usuário informa o motivo na tela do RI e o RI volta para "Implantação EACE". Tudo o que o envio gerou fica no
banco ligado ao `CancelamentoEace` (auditoria) e deixa de contar no sistema: o e-mail ao financeiro, a resposta
(PDF/XML das NFs), os logs do RPA EACE, o envio pela integração e as divergências de NF em aberto. Os itens dos 3
lados e os dados preenchidos ficam como estavam (decisão do usuário: só o faturamento).

O financeiro fica sabendo pela integração (`GET /api/financeiro/cancelamentos/`): marca os e-mails dele como
"Cancelado pela EACE" e eles não geram mais NF. Se a resposta do financeiro chegar depois do cancelamento, ela é
ignorada (`resposta_de_processo_cancelado`)."""

from django.db import transaction
from django.utils import timezone

from apps.auditoria.models import Auditoria
from apps.auditoria.services import registrar as auditar
from apps.core.email_tracking import extrair_codigos_rastreio

from .models import (
    CancelamentoEace,
    Documento,
    EmailFinanceiroLog,
    EnvioFinanceiro,
    FaturamentoComplementar,
    LogRpaEace,
    Ri,
    RiDivergencia,
    RiHistorico,
)
from .services import trocar_status_com_log


class CancelamentoEaceError(Exception):
    """O processo do RI não pode ser cancelado agora (a mensagem vai para a tela)."""


def _envios_ativos(ri):
    return EmailFinanceiroLog.objects.filter(
        ri=ri, direcao=EmailFinanceiroLog.ENVIADO, faturamento_complementar__isnull=True
    )


def motivo_bloqueio_cancelamento(ri):
    """Por que o processo do RI não pode ser cancelado pela EACE agora (texto), ou "" se pode."""
    if not _envios_ativos(ri).exists():
        return "Este RI não tem e-mail enviado ao financeiro para cancelar."
    if ri.escola.status_mip:
        return ('O INEP já está no MIP: o cancelamento pela EACE só pode ser feito antes do "Faturamento RI '
                'Concluído".')
    if ri.faturamentos_complementares.exclude(status=FaturamentoComplementar.RASCUNHO).exists():
        return "O RI tem faturamento complementar enviado: o cancelamento automático não é seguro. Avise o administrador."
    if LogRpaEace.objects.filter(ri=ri, resultado=LogRpaEace.PROCESSANDO).exists():
        return "Um robô do RPA EACE está anexando NF deste RI agora. Aguarde ele terminar e tente de novo."
    return ""


def cancelar_pela_eace(ri, motivo, usuario, ip_origem=None):
    """Cancela o processo do RI (ver o docstring do módulo). Devolve o `CancelamentoEace`. Bloqueio:
    CancelamentoEaceError."""
    motivo = (motivo or "").strip()
    if not motivo:
        raise CancelamentoEaceError("Informe o motivo do cancelamento pela EACE.")
    with transaction.atomic():
        ri = Ri.objects.select_for_update().select_related("escola").get(pk=ri.pk)
        bloqueio = motivo_bloqueio_cancelamento(ri)
        if bloqueio:
            raise CancelamentoEaceError(bloqueio)

        emails = EmailFinanceiroLog.objects.filter(ri=ri, faturamento_complementar__isnull=True)
        documentos = Documento.objects.filter(ri=ri)
        logs_rpa = LogRpaEace.objects.filter(ri=ri, faturamento_complementar__isnull=True)
        envios = EnvioFinanceiro.objects.filter(ri=ri, faturamento_complementar__isnull=True,
                                                cancelamento_eace__isnull=True)
        codigos = sorted({codigo for assunto in _envios_ativos(ri).values_list("assunto", flat=True)
                          for codigo in extrair_codigos_rastreio(assunto)})
        resumo = {
            "emails_enviados": emails.filter(direcao=EmailFinanceiroLog.ENVIADO).count(),
            "respostas": emails.filter(direcao=EmailFinanceiroLog.RECEBIDO).count(),
            "documentos": documentos.count(),
            "logs_rpa": logs_rpa.count(),
        }
        cancelamento = CancelamentoEace.objects.create(
            ri=ri, motivo=motivo, status_anterior=ri.status, codigos_rastreio=codigos,
            message_ids=list(envios.values_list("message_id", flat=True)), resumo=resumo, criado_por=usuario,
        )
        for consulta in (emails, documentos, logs_rpa, envios):
            consulta.update(cancelamento_eace=cancelamento)
        RiDivergencia.objects.filter(ri=ri, tipo=RiDivergencia.TIPO_NF_FINANCEIRO, resolvida_em__isnull=True).update(
            resolvida_em=timezone.now())

        ri.dados_financeiro_confirmados_em = None
        ri.observacoes_envio_financeiro = ""
        ri.save(update_fields=["dados_financeiro_confirmados_em", "observacoes_envio_financeiro", "atualizado_em"])
        RiHistorico.objects.create(
            ri=ri, tipo=RiHistorico.MENSAGEM, autor=usuario,
            mensagem=(f"Processo cancelado pela EACE. Motivo: {motivo}"[:180]
                      + f" | Desconsiderados: {resumo['emails_enviados']} e-mail(s) enviado(s), "
                      f"{resumo['respostas']} resposta(s), {resumo['documentos']} PDF/XML, "
                      f"{resumo['logs_rpa']} log(s) RPA.")[:250],
        )
        trocar_status_com_log(ri, Ri.IMPLANTACAO_EACE, usuario)
        auditar(usuario, Auditoria.ALTERACAO_CAMPO, entidade="Ri", entidade_id=ri.pk, campo="cancelamento_eace",
                valor_anterior=cancelamento.status_anterior, valor_novo=f"Cancelado pela EACE: {motivo}"[:255],
                ip_origem=ip_origem)
    return cancelamento


def resposta_de_processo_cancelado(ri, assunto):
    """`CancelamentoEace` cuja resposta é esta (código de rastreio do assunto de um processo cancelado e sem envio
    novo com o mesmo código), ou None. O mesmo código volta se o RI for reenviado no mesmo dia: aí a resposta é do
    processo novo."""
    codigos = set(extrair_codigos_rastreio(assunto))
    if not codigos:
        return None
    for cancelamento in ri.cancelamentos_eace.order_by("-criado_em"):
        if codigos & set(cancelamento.codigos_rastreio):
            reenviado = any(codigos & set(extrair_codigos_rastreio(assunto_novo))
                            for assunto_novo in _envios_ativos(ri).values_list("assunto", flat=True))
            return None if reenviado else cancelamento
    return None
