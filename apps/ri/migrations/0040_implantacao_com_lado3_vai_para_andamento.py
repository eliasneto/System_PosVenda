from django.db import migrations

# Pedido do usuário (2026-09-26): todo RI em "Implantação EACE" com o Lado
# Relatório EACE (3º lado) preenchido passa para "Em Andamento" — daqui para
# frente isso é automático (`apps.ri.services.avancar_implantacao_com_lado3`).


def mover_para_andamento(apps, schema_editor):
    Ri = apps.get_model("ri", "Ri")
    RiHistorico = apps.get_model("ri", "RiHistorico")
    ri_ids = list(
        Ri.objects.filter(status="implantacao_eace", itens_relatorio_eace__isnull=False)
        .values_list("pk", flat=True)
        .distinct()
    )
    Ri.objects.filter(pk__in=ri_ids).update(status="andamento")
    RiHistorico.objects.bulk_create(
        RiHistorico(
            ri_id=ri_id,
            tipo="log_status",
            campo="Status do RI",
            valor_anterior="Implantação EACE",
            valor_novo="Em Andamento",
        )
        for ri_id in ri_ids
    )


class Migration(migrations.Migration):

    dependencies = [
        ("ri", "0039_ri_remove_status_faturamento_concluido"),
    ]

    operations = [
        migrations.RunPython(mover_para_andamento, migrations.RunPython.noop),
    ]
