from django.core.management.base import BaseCommand

from apps.ri.services import (
    copiar_itens_lado3_para_lado2,
    identificar_ris_lado3_com_nf_sem_lado2,
)


class Command(BaseCommand):
    """Correção pontual de dados (2026-08-31, a pedido do usuário) — não é
    um Sincronizador novo nem altera RN-022/RN-023 daqui pra frente
    (CLAUDE.md §9, decisão confirmada). Roda uma única vez para copiar,
    para o Lado IXC (2º lado), os itens de RI "Faturamento Concluído"
    (conectado, RN-024) que já estão sincronizados no Lado Relatório EACE
    (3º lado) com Nota Fiscal preenchida em todos os itens, e que ainda não
    têm nenhum item lançado no Lado IXC.

    Por padrão roda em modo simulação (não grava nada) — use --aplicar
    para gravar de fato.
    """

    help = (
        "Copia para o Lado IXC os itens de RI Faturamento Concluido (conectado) "
        "com NF preenchida no Lado Relatorio EACE (correcao pontual, nao repete "
        "se ja houver item no Lado IXC). Por padrao so simula; use --aplicar para gravar."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--aplicar", action="store_true",
            help="Grava os itens no Lado IXC. Sem esta flag, só mostra o que seria feito.",
        )

    def handle(self, *args, **options):
        elegiveis, pulados_status_incompleto, pulados_ja_tem_lado2 = (
            identificar_ris_lado3_com_nf_sem_lado2()
        )

        self.stdout.write(
            f"RIs elegíveis (Faturamento Concluído + NF em todos os itens do Lado 3, "
            f"sem item no Lado IXC): {len(elegiveis)}"
        )
        self.stdout.write(
            f"RIs pulados (pelo menos 1 item do Lado 3 sem Nota Fiscal): "
            f"{pulados_status_incompleto}"
        )
        self.stdout.write(
            f"RIs pulados (já têm item lançado no Lado IXC): {pulados_ja_tem_lado2}"
        )

        if not options["aplicar"]:
            self.stdout.write(self.style.WARNING(
                "Simulação (nada foi gravado). Rode novamente com --aplicar para gravar."
            ))
            return

        total_itens = copiar_itens_lado3_para_lado2(elegiveis)
        self.stdout.write(self.style.SUCCESS(
            f"{len(elegiveis)} RI(s) atualizado(s), {total_itens} item(ns) criado(s) no Lado IXC."
        ))
