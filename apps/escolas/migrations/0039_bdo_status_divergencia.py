"""Pedido do usuário (2026-10-15): a aprovação da divergência do INEP no BDO
vira um status (Aprovado, Contestando, Reprovado; vazio = pendente) e o log
passa a guardar o status anterior e o novo. O que já foi aprovado vira
"Aprovado" e o log antigo é convertido."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

STATUS_CHOICES = [("APROVADO", "Aprovado"), ("CONTESTANDO", "Contestando"), ("REPROVADO", "Reprovado")]


def converter(apps, schema_editor):
    InepBdo = apps.get_model("escolas", "InepBdo")
    Log = apps.get_model("escolas", "LogStatusDivergenciaBdo")
    InepBdo.objects.filter(divergencia_aprovada_em__isnull=False).update(
        status_divergencia="APROVADO",
        status_divergencia_em=models.F("divergencia_aprovada_em"),
        status_divergencia_por=models.F("divergencia_aprovada_por"),
    )
    Log.objects.filter(acao="APROVADA").update(acao="ALTERADO", status="APROVADO")
    Log.objects.filter(acao="DESFEITA").update(acao="ALTERADO", status_anterior="APROVADO")
    Log.objects.filter(acao="RETIRADA_PRO_RATA").update(acao="RETIRADO_PRO_RATA", status_anterior="APROVADO")


def reverter(apps, schema_editor):
    InepBdo = apps.get_model("escolas", "InepBdo")
    Log = apps.get_model("escolas", "LogStatusDivergenciaBdo")
    InepBdo.objects.filter(status_divergencia="APROVADO").update(
        divergencia_aprovada_em=models.F("status_divergencia_em"),
        divergencia_aprovada_por=models.F("status_divergencia_por"),
    )
    Log.objects.filter(acao="ALTERADO", status="APROVADO").update(acao="APROVADA")
    Log.objects.filter(acao="ALTERADO").exclude(status="APROVADO").update(acao="DESFEITA")
    Log.objects.filter(acao="RETIRADO_PRO_RATA").update(acao="RETIRADA_PRO_RATA")


class Migration(migrations.Migration):

    dependencies = [
        ("escolas", "0038_bdo_aprovacao_divergencia"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RenameModel("AprovacaoDivergenciaBdo", "LogStatusDivergenciaBdo"),
        migrations.AlterModelOptions(
            name="logstatusdivergenciabdo",
            options={
                "ordering": ["-criado_em", "-pk"],
                "verbose_name": "Log de status de divergência BDO",
                "verbose_name_plural": "Logs de status de divergência BDO",
            },
        ),
        migrations.AlterField(
            model_name="logstatusdivergenciabdo",
            name="inep_bdo",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="logs_status_divergencia", to="escolas.inepbdo",
            ),
        ),
        migrations.AlterField(
            model_name="logstatusdivergenciabdo",
            name="acao",
            field=models.CharField(
                choices=[
                    ("ALTERADO", "Status alterado"),
                    ("RETIRADO_PRO_RATA", "Status retirado pelo reenvio da Pro rata"),
                    # valores antigos, só até o `converter`
                    ("APROVADA", "Aprovada"), ("DESFEITA", "Desfeita"), ("RETIRADA_PRO_RATA", "Retirada"),
                ],
                max_length=20, verbose_name="Ação",
            ),
        ),
        migrations.AddField(
            model_name="logstatusdivergenciabdo",
            name="status_anterior",
            field=models.CharField(blank=True, choices=STATUS_CHOICES, max_length=12, verbose_name="Status anterior"),
        ),
        migrations.AddField(
            model_name="logstatusdivergenciabdo",
            name="status",
            field=models.CharField(blank=True, choices=STATUS_CHOICES, max_length=12, verbose_name="Status"),
        ),
        migrations.AddField(
            model_name="logstatusdivergenciabdo",
            name="em_massa",
            field=models.BooleanField(default=False, verbose_name="Em massa"),
        ),
        migrations.AddField(
            model_name="inepbdo",
            name="status_divergencia",
            field=models.CharField(blank=True, choices=STATUS_CHOICES, max_length=12, verbose_name="Status da divergência"),
        ),
        migrations.AddField(
            model_name="inepbdo",
            name="status_divergencia_em",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Status da divergência em"),
        ),
        migrations.AddField(
            model_name="inepbdo",
            name="status_divergencia_por",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(converter, reverter),
        migrations.AlterField(
            model_name="logstatusdivergenciabdo",
            name="acao",
            field=models.CharField(
                choices=[
                    ("ALTERADO", "Status alterado"),
                    ("RETIRADO_PRO_RATA", "Status retirado pelo reenvio da Pro rata"),
                ],
                max_length=20, verbose_name="Ação",
            ),
        ),
        migrations.RemoveField(model_name="inepbdo", name="divergencia_aprovada_em"),
        migrations.RemoveField(model_name="inepbdo", name="divergencia_aprovada_por"),
    ]
