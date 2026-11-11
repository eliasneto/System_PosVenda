"""Pedido do usuário (2026-11-11): NF que já estava no portal EACE deixa de
ser "Erro" e passa a "Atenção" - converte os logs antigos com esse motivo.
(O avanço de status dos RIs liberados por isto é feito fora da migração,
com `_avancar_status_se_todos_os_logs_sucesso`, que registra histórico.)"""

from django.db import migrations


def converter(apps, schema_editor):
    LogRpaEace = apps.get_model("ri", "LogRpaEace")
    LogRpaEace.objects.filter(resultado="erro", motivo_erro="documento_ja_enviado").update(resultado="atencao")


def desfazer(apps, schema_editor):
    LogRpaEace = apps.get_model("ri", "LogRpaEace")
    LogRpaEace.objects.filter(resultado="atencao").update(resultado="erro")


class Migration(migrations.Migration):

    dependencies = [("ri", "0043_resultado_atencao")]

    operations = [migrations.RunPython(converter, desfazer)]
