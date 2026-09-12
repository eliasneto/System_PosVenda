"""RN-093/FEAT-040: novo perfil fixo "Visualizador" — só amplia as opções
do campo `perfil` (default continua "analista"); nenhum usuário existente
muda de perfil sozinho com esta migração."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_user_acesso_liberado'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='perfil',
            field=models.CharField(
                choices=[
                    ('administrador', 'Administrador'),
                    ('analista', 'Analista'),
                    ('visualizador', 'Visualizador'),
                ],
                default='analista',
                max_length=20,
                verbose_name='Perfil',
            ),
        ),
    ]
