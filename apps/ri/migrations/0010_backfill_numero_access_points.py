"""RN-010 ampliada/FEAT-016: os 80 registros do catálogo já existiam antes
do campo `numero_access_points` (migration 0009) e nunca foram salvos de
novo, então a derivação automática (só roda no `save()`) nunca rodou para
eles. Preenche o valor para as linhas já cadastradas, sem depender do
Excel de origem — regex inline (migração deve ser autônoma, não importar
de `models.py`, que pode mudar no futuro)."""
import re

from django.db import migrations

_NUMERO_ACCESS_POINTS = re.compile(r"(\d+)\s*Access Points?", re.IGNORECASE)


def preencher_numero_access_points(apps, schema_editor):
    KitPadrao = apps.get_model("ri", "KitPadrao")
    for item in KitPadrao.objects.filter(numero_access_points__isnull=True):
        correspondencia = _NUMERO_ACCESS_POINTS.search(item.descricao or "")
        if correspondencia:
            item.numero_access_points = int(correspondencia.group(1))
            item.save(update_fields=["numero_access_points"])


def reverter(apps, schema_editor):
    """Não reverte para None — dado só derivado da Descrição, sem perda
    relevante em manter preenchido."""


class Migration(migrations.Migration):

    dependencies = [
        ('ri', '0009_kitpadrao_numero_access_points'),
    ]

    operations = [
        migrations.RunPython(preencher_numero_access_points, reverter),
    ]
