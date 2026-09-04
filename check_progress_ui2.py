import django, os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from apps.escolas.models import Escola
from apps.ri.models import Ri, LogRpaEace
from apps.ri.views import _contexto_logs_rpa_eace
from django.template.loader import render_to_string

escola, _ = Escola.objects.get_or_create(inep="12345678", defaults={"nome": "Escola QA Progresso"})
ri, _ = Ri.objects.get_or_create(escola=escola, defaults={"status": Ri.AGUARDANDO_ANEXO_PORTAL_EACE})
ri.status = Ri.AGUARDANDO_ANEXO_PORTAL_EACE
ri.save()

LogRpaEace.objects.filter(ri=ri).delete()
log = LogRpaEace.objects.create(
    ri=ri, resultado=LogRpaEace.PROCESSANDO,
    etapa_atual="Anexando o PDF e o XML", progresso_pct=88,
)

ctx = _contexto_logs_rpa_eace(ri, next_url="/")
html = render_to_string("ri/_logs_rpa_eace_detail.html", ctx)

idx = html.find("Rodando agora no portal EACE")
print("TRECHO:")
print(html[idx-200:idx+700] if idx != -1 else "NAO ENCONTRADO O BLOCO 'PROCESSANDO'")

log.delete()
ri.delete()
escola.delete()
