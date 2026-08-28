"""RN-045/FEAT-029: novo controle "Acesso liberado", independente do
perfil. O campo nasce com `default=False` (nova conta, a partir de agora,
entra Desligada) — mas usuário que já existia antes desta feature não pode
ficar retroativamente sem acesso, então esta migração liga todo usuário já
cadastrado no momento em que ela roda (mesmo padrão de
`ri.migrations.0010_backfill_numero_access_points`: schema e dado na mesma
leva, migração autônoma, sem importar de `models.py`)."""
from django.db import migrations, models


def ligar_usuarios_existentes(apps, schema_editor):
    User = apps.get_model("core", "User")
    User.objects.update(acesso_liberado=True)


def reverter(apps, schema_editor):
    """Não reverte para Desligado — reversão da migração de schema já
    remove o campo; nada a desfazer no dado em si."""


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='acesso_liberado',
            field=models.BooleanField(default=False, verbose_name='Acesso liberado'),
        ),
        migrations.RunPython(ligar_usuarios_existentes, reverter),
    ]
