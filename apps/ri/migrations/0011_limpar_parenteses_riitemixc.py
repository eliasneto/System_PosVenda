"""Correção (2026-08-25): itens já lançados no Lado IXC (`RiItemIxc`)
gravavam a Descrição completa do catálogo (`KitPadrao.descricao`), com o
qualificador entre parênteses da planilha (ex.: "(serviços, materiais e
equipamentos)"), em vez da Descrição curta (RN-011) que o select já
mostra — não era o comportamento pretendido. `forms.py`/`views.py`
corrigidos para os próximos lançamentos; esta migration limpa os itens já
salvos. Não toca em `KitPadrao.descricao` (fonte da planilha, usada pelo
comando `importar_catalogo_lpu` para não duplicar em reimportação) nem em
`RiItemEace`/`RiItemRelatorioEace` (nenhum registro real tinha
parênteses)."""
import re

from django.db import migrations

_SUFIXO_ENTRE_PARENTESES = re.compile(r"\s*\([^)]*\)\s*$")


def limpar_parenteses(apps, schema_editor):
    RiItemIxc = apps.get_model("ri", "RiItemIxc")
    for item in RiItemIxc.objects.filter(descricao_item__contains="("):
        limpo = _SUFIXO_ENTRE_PARENTESES.sub("", item.descricao_item).strip()
        if limpo and limpo != item.descricao_item:
            item.descricao_item = limpo
            item.save(update_fields=["descricao_item"])


def reverter(apps, schema_editor):
    """Não recupera o texto entre parênteses removido — informação
    descartada de propósito (qualificador da planilha, sem uso na tela)."""


class Migration(migrations.Migration):

    dependencies = [
        ('ri', '0010_backfill_numero_access_points'),
    ]

    operations = [
        migrations.RunPython(limpar_parenteses, reverter),
    ]
