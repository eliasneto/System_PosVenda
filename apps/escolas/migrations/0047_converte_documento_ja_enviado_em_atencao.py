"""Pedido do usuário (2026-11-11): envio do MIP cuja NF já estava no portal
(card fora de "Pendente", com o status lido) passa de "Erro" a "Atenção"."""

from django.db import migrations


def converter(apps, schema_editor):
    LogRpaEaceMip = apps.get_model("escolas", "LogRpaEaceMip")
    LogRpaEaceMip.objects.filter(resultado="erro", motivo_erro="documento_ja_enviado").exclude(
        status_portal=""
    ).update(resultado="atencao")


def desfazer(apps, schema_editor):
    LogRpaEaceMip = apps.get_model("escolas", "LogRpaEaceMip")
    LogRpaEaceMip.objects.filter(resultado="atencao").update(resultado="erro")


class Migration(migrations.Migration):

    dependencies = [("escolas", "0046_resultado_atencao")]

    operations = [migrations.RunPython(converter, desfazer)]
