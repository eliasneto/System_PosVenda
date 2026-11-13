"""Envio da planilha de faturamento ao financeiro: e-mail primeiro, integração (API) se o e-mail falhar.

Pedido do usuário (2026-11-13): o envio de e-mail caiu depois de um ataque, e o pós-venda não conseguia mandar
as planilhas. O e-mail continua sendo o caminho principal. Quando ele falha, o envio fica disponível ao Módulo
Financeiro em `GET /api/financeiro/envios/` (`api_envio_financeiro.py`), sem o usuário precisar fazer nada.

Duplicidade: o e-mail sai com o Message-ID do envio (`EnvioFinanceiro.message_id`) e a API entrega o mesmo
Message-ID. O financeiro grava cada e-mail por esse id (campo único), então o mesmo envio não entra duas vezes,
nem no caso de o SMTP dar erro depois de o servidor já ter aceitado a mensagem."""

import logging
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.mail import EmailMessage

from .models import EnvioFinanceiro

logger = logging.getLogger(__name__)


def montar_message_id():
    """Message-ID único (uuid: homologação e produção podem mandar para a mesma caixa do financeiro)."""
    dominio = (settings.DEFAULT_FROM_EMAIL or "").rsplit("@", 1)[-1].strip(" >") or "posvenda.local"
    return f"<posvenda-envio-{uuid.uuid4().hex}@{dominio}>"


def enviar_ao_financeiro(*, ri, assunto, corpo, para, copia, nome_planilha, planilha_bytes, tipo_planilha,
                         usuario, complementar=None, anexo_extra=None):
    """Grava o envio e manda o e-mail. Se o e-mail falhar, o envio fica com canal API (o financeiro busca pela
    integração). `anexo_extra`: (nome, conteúdo, content_type) ou None. Devolve o `EnvioFinanceiro`."""
    envio = EnvioFinanceiro(
        ri=ri,
        faturamento_complementar=complementar,
        message_id=montar_message_id(),
        remetente=settings.DEFAULT_FROM_EMAIL,
        destinatarios=", ".join(para),
        copia=", ".join(copia),
        assunto=assunto,
        corpo=corpo,
        nome_planilha=nome_planilha,
        criado_por=usuario,
    )
    envio.planilha.save(nome_planilha, ContentFile(planilha_bytes), save=False)
    if anexo_extra:
        nome_extra, conteudo_extra, tipo_extra = anexo_extra
        envio.nome_anexo_extra = nome_extra[:255]
        envio.tipo_anexo_extra = (tipo_extra or "")[:150]
        envio.anexo_extra.save(nome_extra, ContentFile(conteudo_extra), save=False)
    envio.save()

    email = EmailMessage(
        subject=assunto,
        body=corpo,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=para,
        cc=copia,
        headers={"Message-ID": envio.message_id},
    )
    email.attach(nome_planilha, planilha_bytes, tipo_planilha)
    if anexo_extra:
        email.attach(*anexo_extra)
    try:
        email.send(fail_silently=False)
    except Exception as erro:  # SMTP fora do ar, login recusado, timeout...
        logger.warning("E-mail ao financeiro do RI %s falhou; envio liberado pela integração: %s", ri.pk, erro)
        envio.canal = EnvioFinanceiro.API
        envio.erro_email = f"{type(erro).__name__}: {erro}"[:2000]
        envio.save(update_fields=["canal", "erro_email"])
    return envio


def texto_canal(envio):
    """Complemento da mensagem da linha do tempo/tela quando o e-mail falhou."""
    if envio.canal == EnvioFinanceiro.EMAIL:
        return ""
    return (
        " O e-mail não pôde ser enviado (servidor de e-mail fora do ar); a planilha foi enviada ao financeiro "
        "pela integração direta entre os sistemas."
    )
