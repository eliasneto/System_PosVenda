"""RN a formalizar pelo Orquestrador em business_rules.md (pedido do
usuário, 2026-09-24) — bug real reportado pelo usuário: um INEP rateado
(mesmo INEP com mais de 1 Cidade na planilha da EACE) recebe mais de 1
Nota Fiscal do financeiro (1 por fração/Cidade); o campo único antigo
`Escola.nota_fiscal_mip` perdia silenciosamente toda NF exceto a última
sincronizada. Substituído pelo modelo `NotaFiscalMip` (1 Escola pode ter
várias). `copiar_notas_fiscais_existentes` preserva as NFs já
sincronizadas antes desta migração (dado real de negócio, nunca perdido)
— roda ANTES do `RemoveField` dos campos antigos, na mesma migração."""
import django.db.models.deletion
from django.db import migrations, models


def copiar_notas_fiscais_existentes(apps, schema_editor):
    Escola = apps.get_model("escolas", "Escola")
    NotaFiscalMip = apps.get_model("escolas", "NotaFiscalMip")
    for escola in Escola.objects.exclude(nota_fiscal_mip=""):
        NotaFiscalMip.objects.create(
            escola=escola,
            arquivo=escola.nota_fiscal_mip.name,
            nome_original=escola.nota_fiscal_mip.name.rsplit("/", 1)[-1],
            sincronizada_em=escola.nota_fiscal_mip_sincronizada_em,
        )


def reverter(apps, schema_editor):
    """Não reverte para o campo único — dado histórico real, sem perda
    relevante em manter só no modelo novo (mesmo critério já usado em
    escolas.0010_backfill_status_mip_faturamento_concluido)."""


class Migration(migrations.Migration):

    dependencies = [
        ('escolas', '0019_escola_nota_fiscal_mip'),
    ]

    operations = [
        migrations.CreateModel(
            name='NotaFiscalMip',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('arquivo', models.FileField(max_length=255, upload_to='notas_fiscais_mip/escolas/%Y/%m/', verbose_name='Arquivo')),
                ('nome_original', models.CharField(help_text='Nome do PDF dentro do .zip/.rar sincronizado — usado para reconhecer a mesma Nota numa rodada nova.', max_length=255, verbose_name='Nome do arquivo')),
                ('sincronizada_em', models.DateTimeField(verbose_name='Sincronizada em')),
                ('escola', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='notas_fiscais_mip', to='escolas.escola')),
            ],
            options={
                'verbose_name': 'Nota Fiscal (MIP)',
                'verbose_name_plural': 'Notas Fiscais (MIP)',
                'ordering': ['sincronizada_em'],
            },
        ),
        migrations.RunPython(copiar_notas_fiscais_existentes, reverter),
        migrations.RemoveField(
            model_name='escola',
            name='nota_fiscal_mip',
        ),
        migrations.RemoveField(
            model_name='escola',
            name='nota_fiscal_mip_sincronizada_em',
        ),
    ]
