from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("escolas", "0050_nf_bdo_robo"),
    ]

    operations = [
        migrations.AddField(
            model_name="remessanfbdo",
            name="situacao",
            field=models.CharField(
                choices=[("lendo", "Lendo as NFs"), ("concluida", "Lida"), ("erro", "Erro")],
                default="concluida", max_length=10, verbose_name="Situação",
            ),
        ),
        migrations.AddField(
            model_name="remessanfbdo",
            name="erro",
            field=models.CharField(blank=True, max_length=500, verbose_name="Erro da leitura"),
        ),
        migrations.AddField(
            model_name="remessanfbdo",
            name="concluida_em",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Leitura terminada em"),
        ),
    ]
