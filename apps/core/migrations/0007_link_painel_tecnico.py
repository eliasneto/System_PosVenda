from django.db import migrations, models

import apps.core.models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_estado_robos_freio_aviso_ate"),
    ]

    operations = [
        migrations.CreateModel(
            name="LinkPainelTecnico",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nome", models.CharField(max_length=100, verbose_name="Para quem")),
                ("codigo", models.CharField(default=apps.core.models._novo_codigo_painel, editable=False, max_length=64,
                                            unique=True, verbose_name="Código do link")),
                ("ativo", models.BooleanField(default=True, verbose_name="Ativo")),
                ("criado_em", models.DateTimeField(auto_now_add=True, verbose_name="Criado em")),
            ],
            options={
                "verbose_name": "Link do painel técnico",
                "verbose_name_plural": "Links do painel técnico",
                "ordering": ["nome"],
            },
        ),
    ]
