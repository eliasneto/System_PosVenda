from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_estado_robos_rpa_eace"),
    ]

    operations = [
        migrations.AddField(
            model_name="estadorobosrpaeace",
            name="freio_aviso_ate",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Aviso do freio até"),
        ),
        migrations.AddField(
            model_name="estadorobosrpaeace",
            name="robos_uso",
            field=models.JSONField(blank=True, default=dict, verbose_name="Uso de cada robô"),
        ),
    ]
