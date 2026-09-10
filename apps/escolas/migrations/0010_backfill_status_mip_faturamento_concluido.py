"""Pedido do usuário (2026-09-10, RN-092): Escola cujo RI mais recente já
estava em "Aguardando validação EACE" ou "Faturamento Concluído" antes
desta feature existir ganha o `status_mip` correspondente de uma vez —
sem isso, ela nunca teria passado pelo gancho automático de
`trocar_status_com_log` (apps.ri.services) que passa a gravar esse
campo, e sumiria incorretamente do grid de Equipamentos (FEAT-007) sem
nunca aparecer no MIP. Resolvido com 2 consultas (RI mais recente por
Escola, calculado em memória) + 2 UPDATEs em lote, em vez de 1 consulta
por Escola."""
from django.db import migrations

# Mesmos valores de apps.escolas.models.Escola (migração não importa de
# models.py, que pode mudar no futuro — mesma regra já seguida pela
# migração 0010_backfill_numero_access_points, apps.ri).
_AGUARDANDO_VALIDACAO_EACE = "aguardando_validacao_eace"
_FATURAMENTO_CONCLUIDO = "faturamento_concluido"


def backfill_status_mip(apps, schema_editor):
    Escola = apps.get_model("escolas", "Escola")
    Ri = apps.get_model("ri", "Ri")

    status_do_ri_mais_recente_por_escola = {}
    for escola_id, status in (
        Ri.objects.order_by("escola_id", "-criado_em").values_list("escola_id", "status")
    ):
        # 1ª ocorrência de cada escola_id, na ordenação acima, já é o RI
        # mais recente dela (mesmo critério de "RI atual" usado em
        # RN-068/RN-072/RN-074).
        status_do_ri_mais_recente_por_escola.setdefault(escola_id, status)

    for status_ri, status_mip in (
        (_AGUARDANDO_VALIDACAO_EACE, _AGUARDANDO_VALIDACAO_EACE),
        (_FATURAMENTO_CONCLUIDO, _FATURAMENTO_CONCLUIDO),
    ):
        escola_ids = [
            escola_id
            for escola_id, status in status_do_ri_mais_recente_por_escola.items()
            if status == status_ri
        ]
        Escola.objects.filter(pk__in=escola_ids, status_mip__isnull=True).update(
            status_mip=status_mip
        )


def reverter(apps, schema_editor):
    """Não reverte para None — dado histórico real, sem perda relevante em
    manter preenchido."""


class Migration(migrations.Migration):

    dependencies = [
        ("escolas", "0009_escola_status_mip"),
        ("ri", "0034_logrpaeace_concluido_manualmente"),
    ]

    operations = [
        migrations.RunPython(backfill_status_mip, reverter),
    ]
