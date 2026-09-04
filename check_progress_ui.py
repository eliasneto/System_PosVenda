import django, os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.test import Client
from django.contrib.auth import get_user_model
from apps.escolas.models import Escola
from apps.ri.models import Ri, LogRpaEace, Documento
from django.core.files.uploadedfile import SimpleUploadedFile

User = get_user_model()

user, _ = User.objects.get_or_create(username="_visual_qa_temp", defaults={"perfil": User.PERFIL_ANALISTA})
user.set_password("senha-temp-123")
user.save()

escola, _ = Escola.objects.get_or_create(inep="12345678", defaults={"nome": "Escola QA Progresso"})
ri, _ = Ri.objects.get_or_create(escola=escola, defaults={"status": Ri.AGUARDANDO_ANEXO_PORTAL_EACE})
ri.status = Ri.AGUARDANDO_ANEXO_PORTAL_EACE
ri.save()

LogRpaEace.objects.filter(ri=ri).delete()
log = LogRpaEace.objects.create(
    ri=ri, resultado=LogRpaEace.PROCESSANDO,
    etapa_atual="Anexando o PDF e o XML", progresso_pct=88,
)

client = Client()
client.force_login(user)
resp = client.get(f"/ri/{escola.inep}/")
html = resp.content.decode("utf-8")

idx = html.find("Rodando agora no portal EACE")
print("STATUS:", resp.status_code)
print("TRECHO:")
print(html[idx-200:idx+600] if idx != -1 else "NAO ENCONTRADO O BLOCO 'PROCESSANDO'")

# cleanup
log.delete()
ri.delete()
escola.delete()
user.delete()
