from django.core.management.base import BaseCommand

from apps.ri.services import (
    corrigir_valor_itens_relatorio_eace,
    identificar_itens_relatorio_eace_valor_desatualizado,
)


class Command(BaseCommand):
    """Correção pontual de dados (2026-08-31, a pedido do usuário) — o
    commit que criou `KitPadrao.valor_faturavel` (só equipamento, sem
    servico) corrigiu a resolução de preço só para itens NOVOS. Este
    comando corrige o Valor Unitário já gravado nos itens do Lado
    Relatório EACE lançados/sincronizados antes dessa correção, que
    continuam com o valor antigo (equipamento + serviço).

    Por padrão roda em modo simulação (não grava nada) — use --aplicar
    para gravar de fato.
    """

    help = (
        "Corrige o Valor Unitario ja gravado nos itens do Lado Relatorio EACE "
        "para o valor certo do catalogo (so equipamento, KitPadrao.valor_faturavel). "
        "Por padrao so simula; use --aplicar para gravar."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--aplicar", action="store_true",
            help="Grava o valor corrigido. Sem esta flag, só mostra o que seria feito.",
        )

    def handle(self, *args, **options):
        desatualizados, sem_catalogo = identificar_itens_relatorio_eace_valor_desatualizado()

        self.stdout.write(f"Itens com valor desatualizado (serão corrigidos): {len(desatualizados)}")
        self.stdout.write(
            f"Itens sem catálogo encontrado (não dá pra saber o valor certo, ficam de fora): "
            f"{len(sem_catalogo)}"
        )
        if sem_catalogo:
            self.stdout.write(self.style.WARNING("Itens sem catálogo (revisar manualmente):"))
            for item in sem_catalogo[:20]:
                self.stdout.write(
                    f"  RI {item.ri_id} (INEP {item.ri.escola.inep}): "
                    f"{item.descricao_item!r} (eh_kit={item.eh_kit})"
                )
            if len(sem_catalogo) > 20:
                self.stdout.write(f"  ... e mais {len(sem_catalogo) - 20}.")

        if desatualizados:
            total_antes = sum(item.valor_unitario * item.quantidade for item, _ in desatualizados)
            total_depois = sum(correto * item.quantidade for item, correto in desatualizados)
            self.stdout.write(
                f"Soma (quantidade x valor) desses itens: R$ {total_antes:.2f} -> R$ {total_depois:.2f} "
                f"(diferença: R$ {total_antes - total_depois:.2f})"
            )

        if not options["aplicar"]:
            self.stdout.write(self.style.WARNING(
                "Simulação (nada foi gravado). Rode novamente com --aplicar para gravar."
            ))
            return

        total = corrigir_valor_itens_relatorio_eace(desatualizados)
        self.stdout.write(self.style.SUCCESS(f"{total} item(ns) corrigido(s) no Lado Relatório EACE."))
