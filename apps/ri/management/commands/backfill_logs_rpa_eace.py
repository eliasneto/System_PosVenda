from django.core.management.base import BaseCommand
from django.db.models import Count

from apps.ri.models import Documento, LogRpaEace, Ri


class Command(BaseCommand):
    """Correção (2026-09-04): RIs que chegaram em "Resposta Financeiro"
    (RN-016) ANTES do log por Nota Fiscal existir (LogRpaEace, RN-056/
    FEAT-033) já têm os `Documento` (PDF+XML) recebidos, mas nenhum log -
    a seção "Notas Fiscais para anexar no portal EACE" fica escondida
    (`_contexto_logs_rpa_eace` só mostra a seção quando `logs_rpa_eace`
    não é vazio), mesmo com tudo pronto pra disparar a RPA. Usuário
    reportou em produção: "vários INEPs... não aparece os inputs do
    RPA" - confirmado, 22 RIs nessa situação (4 documentos = 2 NFs, 0
    logs).

    Cria 1 `LogRpaEace` por Nota Fiscal (mesma contagem de RN-056: 1 por
    PDF) só para RI em "Resposta Financeiro" com PDF recebido e ZERO
    logs ainda - nunca mexe em RI que já tem pelo menos 1 log (evita
    duplicar em quem já foi processado pelo fluxo normal)."""

    help = (
        "Cria os LogRpaEace que faltam para RIs em 'Resposta Financeiro' que já "
        "têm Documento (PDF+XML) mas nasceram antes do log por Nota Fiscal existir."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Só mostra o que seria criado, sem gravar nada.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        candidatos = (
            Ri.objects.filter(status=Ri.AGUARDANDO_ANEXO_PORTAL_EACE)
            .annotate(n_logs=Count("logs_rpa_eace", distinct=True))
            .filter(n_logs=0)
            .select_related("escola")
        )

        total_ris = 0
        total_logs = 0
        for ri in candidatos:
            n_pdfs = Documento.objects.filter(ri=ri, tipo=Documento.NOTA_FISCAL_PDF).count()
            if not n_pdfs:
                continue  # RN-016 "fora do padrão" - sem anexo recebido, nada a criar

            total_ris += 1
            total_logs += n_pdfs
            self.stdout.write(f"RI {ri.pk} (INEP {ri.escola.inep}): {n_pdfs} log(s) a criar")
            if not dry_run:
                LogRpaEace.objects.bulk_create([LogRpaEace(ri=ri) for _ in range(n_pdfs)])

        acao = "seriam criados" if dry_run else "criados"
        self.stdout.write(
            self.style.SUCCESS(
                f"{total_logs} log(s) {acao} em {total_ris} RI(s)."
                + (" (--dry-run, nada foi gravado)" if dry_run else "")
            )
        )
