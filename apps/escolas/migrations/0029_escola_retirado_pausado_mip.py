from django.db import migrations, models


def marcar_retirados_existentes(apps, schema_editor):
    """INEP já retirado pelo X antes deste campo existir: o único rastro é
    `encontrado_relatorio_eace_mip=False` + o log "Grid do MIP" no histórico."""
    Escola = apps.get_model("escolas", "Escola")
    RiHistorico = apps.get_model("ri", "RiHistorico")
    escola_ids = RiHistorico.objects.filter(campo="Grid do MIP").values_list("ri__escola_id", flat=True)
    Escola.objects.filter(pk__in=set(escola_ids), encontrado_relatorio_eace_mip=False).update(retirado_grid_mip=True)


class Migration(migrations.Migration):

    dependencies = [
        ('escolas', '0028_lote_valores_faturados_planilha'),
        ('ri', '0041_historico_tipo_importacao_massa'),
    ]

    operations = [
        migrations.AddField(
            model_name='escola',
            name='retirado_grid_mip',
            field=models.BooleanField(default=False, verbose_name='Retirado do grid do MIP'),
        ),
        migrations.AddField(
            model_name='escola',
            name='pausado_mip',
            field=models.BooleanField(default=False, verbose_name='Pausado no MIP'),
        ),
        migrations.RunPython(marcar_retirados_existentes, migrations.RunPython.noop),
    ]
