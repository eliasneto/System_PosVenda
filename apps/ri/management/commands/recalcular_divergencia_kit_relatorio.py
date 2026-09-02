from django.core.management.base import BaseCommand

from apps.ri.models import RiDivergencia
from apps.ri.services import (
    comparar_kit_e_produtos_ixc_relatorio,
    sincronizar_divergencia_kit_relatorio,
)


class Command(BaseCommand):
    """Correção pontual de dados (2026-09-02, a pedido do usuário) — a
    RN-003 (confronto Lado IXC × Lado Relatório EACE) foi ajustada: um dos
    dois lados totalmente vazio deixou de contar como divergência (antes,
    acusava divergência à toa sempre que só um dos dois lados já tinha
    algum item lançado). Este comando recalcula, uma única vez, todas as
    divergências "Com divergência" (`RiDivergencia.tipo=kit_relatorio`)
    hoje abertas contra a regra nova — resolve as que eram falso positivo
    (lado vazio), mantém abertas as divergências reais (os dois lados com
    algum item, mas diferentes). Não é um recálculo novo nem altera
    RN-003 daqui pra frente: `sincronizar_divergencia_kit_relatorio` é a
    mesma função já chamada a cada lançamento/edição/exclusão de item nos
    dois lados — aqui só é reaproveitada para reprocessar o que já existe.

    Por padrão roda em modo simulação (não grava nada) — use --aplicar
    para gravar de fato.
    """

    help = (
        "Recalcula as divergencias 'Com divergencia' (kit_relatorio) abertas contra a "
        "regra nova da RN-003 (lado vazio deixa de ser divergencia). Por padrao so "
        "simula; use --aplicar para gravar."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--aplicar", action="store_true",
            help="Resolve as divergências que eram falso positivo. Sem esta flag, só mostra o que seria feito.",
        )

    def handle(self, *args, **options):
        abertas = list(
            RiDivergencia.objects.filter(
                tipo=RiDivergencia.TIPO_KIT_RELATORIO, resolvida_em__isnull=True
            ).select_related("ri__escola")
        )
        falsos_positivos = [
            divergencia
            for divergencia in abertas
            if not comparar_kit_e_produtos_ixc_relatorio(divergencia.ri)["diverge"]
        ]

        self.stdout.write(f'Divergências "Com divergência" abertas hoje: {len(abertas)}')
        self.stdout.write(
            "Seriam resolvidas pela regra nova (lado vazio, falso positivo): "
            f"{len(falsos_positivos)}"
        )
        self.stdout.write(
            f"Continuam abertas (divergência real, os 2 lados com algum item): "
            f"{len(abertas) - len(falsos_positivos)}"
        )

        if not options["aplicar"]:
            self.stdout.write(self.style.WARNING(
                "Simulação (nada foi gravado). Rode novamente com --aplicar para gravar."
            ))
            return

        for divergencia in falsos_positivos:
            sincronizar_divergencia_kit_relatorio(divergencia.ri)

        self.stdout.write(self.style.SUCCESS(
            f"{len(falsos_positivos)} divergência(s) resolvida(s)."
        ))
