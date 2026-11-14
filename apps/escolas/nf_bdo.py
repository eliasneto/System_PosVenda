"""Notas Fiscais do BDO no portal EACE (pedido do usuário, 2026-11-13; RN a
formalizar pelo Orquestrador em business_rules.md).

O financeiro devolve um .zip (ou .rar) com as NFs do Boletim: uma NFCom por
município, de RE e de RI (cada tipo é um Boletim). Cada PDF traz em
"INFORMAÇÕES COMPLEMENTARES" o número do Boletim e o município:
"CODIGO DE LIBERACAO 3657 UF ITOBI/SP", e o valor em "TOTAL A PAGAR".

- `processar_remessa`: lê o arquivo, guarda cada PDF (`NotaFiscalBdo`) e o
  liga ao Boletim e ao município. Só fica "Pronta" quando o município
  escrito na NF e o valor do card no portal concordam - nas NFs reais do
  3657 o financeiro errou o município em algumas (NF 218 "HEITORAI" com o
  valor do card de Cândido Rodrigues): aí a NF espera a decisão do usuário,
  nunca vai sozinha para o card errado.
- `decidir_nota`: o usuário escolhe o município (ou descarta a NF).
- `enfileirar_notas`: as prontas do Boletim entram na fila do RPA EACE.
- `processar_proximo_envio_nf_bdo`: o worker da fila anexa 1 NF por vez
  (`rpa_bdo.anexar_pdf_bdo`); anexada = baixa do município no Boletim.
"""

from __future__ import annotations

import difflib
import io
import logging
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
import zipfile
from datetime import timedelta
from decimal import Decimal

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from .models import BoletimBdo, MunicipioBdo, NotaFiscalBdo, RemessaNfBdo
from .validacao_nf_mip import _orm_liberado_dentro_do_playwright

logger = logging.getLogger(__name__)

TEMPO_MAXIMO_PROCESSANDO = timedelta(minutes=30)
SEMELHANCA_MINIMA_NOME = 0.85  # erro de digitação no nome ("CHAPADA DA NATVIDADE")
TAMANHO_MINIMO_NOME_CONTIDO = 5  # "LENCOIS ABADIANIA" contém "ABADIANIA"

_RE_LIBERACAO = re.compile(r"CODIGO DE LIBERACAO\s+(\d+)\s+UF\s+(.+?)\s*/\s*([A-Z]{2})\b")
_RE_NUMERO = re.compile(r"NOTA FISCAL N\S*\s*(\d+)")
_RE_VALORES = (
    re.compile(r"TOTAL A PAGAR:\s*R\$\s*([\d.]+,\d{2})"),
    re.compile(r"VALOR TOTAL NF\s+([\d.]+,\d{2})"),
)


class RemessaNfBdoError(Exception):
    """Arquivo que não dá para ler (não é .zip/.rar, sem PDF, .rar sem `unar`)."""


def _normalizar(texto):
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    return " ".join("".join(c for c in sem_acento if not unicodedata.combining(c)).upper().split())


def _chave(texto):
    """Só letras e números: "Santa Bárbara d'Oeste" = "SANTA BARBARA DOESTE"."""
    return "".join(c for c in _normalizar(texto) if c.isalnum())


def ler_texto_pdf(conteudo):
    import pdfplumber

    with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
        return "\n".join(pagina.extract_text() or "" for pagina in pdf.pages)


def ler_nf(texto):
    """O que interessa da NFCom do BDO: {"numero", "valor", "boletim", "municipio", "uf"} (vazios se não achar)."""
    normalizado = _normalizar(texto)
    liberacao = _RE_LIBERACAO.search(normalizado)
    numero = _RE_NUMERO.search(normalizado)
    valor = next((r.search(texto or "") for r in _RE_VALORES if r.search(texto or "")), None)
    return {
        "numero": numero.group(1) if numero else "",
        "valor": Decimal(valor.group(1).replace(".", "").replace(",", ".")) if valor else None,
        "boletim": liberacao.group(1) if liberacao else "",
        "municipio": liberacao.group(2).strip() if liberacao else "",
        "uf": liberacao.group(3) if liberacao else "",
    }


def _pdfs_do_zip(arquivo_zip):
    for info in arquivo_zip.infolist():
        nome = info.filename
        if info.is_dir() or nome.startswith("__MACOSX/"):
            continue
        if nome.lower().endswith(".zip"):  # o financeiro manda .zip dentro do .zip
            yield from _pdfs_do_zip(zipfile.ZipFile(io.BytesIO(arquivo_zip.read(nome))))
        elif nome.lower().endswith(".pdf"):
            yield nome.rsplit("/", 1)[-1], arquivo_zip.read(nome)


def iterar_pdfs(conteudo, nome_arquivo):
    """(nome, bytes) de cada PDF do .zip (inclusive de .zip dentro dele) ou do .rar (precisa do `unar`, como no MIP)."""
    if nome_arquivo.lower().endswith(".zip"):
        try:
            yield from _pdfs_do_zip(zipfile.ZipFile(io.BytesIO(conteudo)))
        except zipfile.BadZipFile as exc:
            raise RemessaNfBdoError("O arquivo não é um .zip válido.") from exc
        return
    if not nome_arquivo.lower().endswith(".rar"):
        raise RemessaNfBdoError("Envie o arquivo do financeiro em .zip ou .rar.")
    if shutil.which("unar") is None:
        raise RemessaNfBdoError("O servidor não tem a ferramenta 'unar' para abrir .rar: reenvie em .zip.")
    with tempfile.TemporaryDirectory() as pasta:
        caminho = os.path.join(pasta, "remessa.rar")
        with open(caminho, "wb") as arquivo:
            arquivo.write(conteudo)
        saida = os.path.join(pasta, "x")
        resultado = subprocess.run(["unar", "-q", "-f", "-o", saida, caminho], capture_output=True)
        if resultado.returncode != 0:
            raise RemessaNfBdoError("Não foi possível abrir o .rar: "
                                    + (resultado.stderr.decode("utf-8", "replace").strip() or "erro do 'unar'."))
        for raiz, _pastas, nomes in os.walk(saida):
            for nome in sorted(nomes):
                if nome.lower().endswith(".pdf"):
                    with open(os.path.join(raiz, nome), "rb") as pdf:
                        yield nome, pdf.read()


def valor_do_card(municipio):
    return municipio.valor_eace if municipio.valor_eace is not None else municipio.valor_total


def card_ja_com_nf(municipio):
    """O card do município no portal já recebeu NF (Aguardando aprovação, Aprovado, NF anexada): o robô não anexa."""
    from apps.integracoes.eace.rpa_mip import status_enviado

    return bool(municipio.status_eace) and status_enviado(municipio.status_eace)


def _municipios_pelo_nome(nome, uf, municipios):
    """Municípios do Boletim (na `uf`) com o nome da NF: igual (sem acento/pontuação); senão o nome do
    município contido no da NF ("LENCOIS ABADIANIA"); senão o mais parecido, se bem parecido."""
    alvo = _chave(nome)
    da_uf = [m for m in municipios if m.uf == uf]
    iguais = [m for m in da_uf if _chave(m.municipio) == alvo]
    if iguais or not alvo:
        return iguais
    contidos = [m for m in da_uf if len(_chave(m.municipio)) >= TAMANHO_MINIMO_NOME_CONTIDO and _chave(m.municipio) in alvo]
    if len({_chave(m.municipio) for m in contidos}) == 1:
        return contidos
    notas = sorted(((difflib.SequenceMatcher(None, alvo, _chave(m.municipio)).ratio(), m) for m in da_uf),
                   key=lambda par: -par[0])
    if notas and notas[0][0] >= SEMELHANCA_MINIMA_NOME:
        melhor = _chave(notas[0][1].municipio)
        return [m for _, m in notas if _chave(m.municipio) == melhor]
    return []


def _rotulo(municipio):
    return f"{municipio.municipio}/{municipio.uf}"


def _brl(valor):
    texto = f"{valor:,.2f}"
    return "R$ " + texto.replace(",", "X").replace(".", ",").replace("X", ".")


def ligar_nota(nota, municipios, usados):
    """Liga a NF ao município do Boletim e decide a situação. `usados`: ids de municípios que já têm NF
    nesta leitura ou no portal pelo sistema (um município, uma NF por Boletim)."""
    nota.municipio_bdo, nota.ligada_por, nota.motivo = None, "", ""
    if not nota.boletim_lido:
        # sem o codigo (NF 205 do 3657): sugere pelo valor, se so um card de um Boletim tem esse valor
        candidatos = [m for m in MunicipioBdo.objects.select_related("boletim")
                      if nota.valor is not None and valor_do_card(m) == nota.valor and m.pk not in usados]
        nota.situacao = NotaFiscalBdo.SEM_MUNICIPIO
        nota.motivo = "A NF não tem o \"CODIGO DE LIBERACAO\": escolha o município."
        if len(candidatos) == 1:
            nota.boletim, nota.municipio_bdo, nota.situacao = candidatos[0].boletim, candidatos[0], NotaFiscalBdo.DIVERGENTE
            nota.motivo = (f"A NF não tem o \"CODIGO DE LIBERACAO\"; o valor ({_brl(nota.valor)}) bate só com o card de "
                           f"{_rotulo(candidatos[0])} do Boletim {candidatos[0].boletim.numero}. Confirme.")
        return
    if nota.boletim is None:
        nota.situacao = NotaFiscalBdo.FORA_DO_BOLETIM
        nota.motivo = f"Boletim {nota.boletim_lido} não importado no sistema (importe em Administrador > Relatório BDO)."
        return
    pelo_nome = _municipios_pelo_nome(nota.municipio_lido, nota.uf_lida, municipios)
    pelo_valor = [m for m in municipios if nota.valor is not None and valor_do_card(m) == nota.valor]
    livres = [m for m in pelo_nome if valor_do_card(m) == nota.valor and m.pk not in usados]
    escrito = f"{nota.municipio_lido}/{nota.uf_lida}"
    if livres:
        nota.municipio_bdo, nota.ligada_por = livres[0], "texto"
        if card_ja_com_nf(livres[0]):
            nota.situacao = NotaFiscalBdo.JA_NO_PORTAL
            nota.motivo = f"O card de {_rotulo(livres[0])} no portal já está \"{livres[0].status_eace}\"."
        else:
            nota.situacao = NotaFiscalBdo.PRONTA
        usados.add(livres[0].pk)
        return
    nota.situacao = NotaFiscalBdo.DIVERGENTE
    outros = [m for m in pelo_valor if m.pk not in usados and m not in pelo_nome]
    sugestao = f" O valor bate com o card de {_rotulo(outros[0])}." if len(outros) == 1 else ""
    if pelo_nome and any(valor_do_card(m) == nota.valor for m in pelo_nome):
        nota.municipio_bdo = pelo_nome[0]
        nota.motivo = f"{_rotulo(pelo_nome[0])} já tem outra NF deste Boletim."
    elif pelo_nome:
        nota.municipio_bdo = pelo_nome[0]
        nota.motivo = (f"A NF diz {escrito}, mas o valor ({_brl(nota.valor) if nota.valor is not None else 'sem valor'}) "
                       f"é diferente do card de {_rotulo(pelo_nome[0])} ({_brl(valor_do_card(pelo_nome[0]))}).{sugestao}")
    elif len(outros) == 1:
        nota.municipio_bdo = outros[0]
        nota.motivo = f"A NF diz {escrito}, que não está no Boletim {nota.boletim.numero}.{sugestao} Confirme."
    else:
        nota.situacao = NotaFiscalBdo.SEM_MUNICIPIO
        nota.motivo = f"A NF diz {escrito}, que não está no Boletim {nota.boletim.numero}: escolha o município."


@transaction.atomic
def processar_remessa(arquivo, usuario=None):
    """Grava a remessa e cada NF dela, ligada ao Boletim e ao município. A mesma NF (número + Boletim) que já
    foi para o portal fica de fora; a que ainda não foi é substituída pela nova. Devolve a remessa (com `resumo`).
    Arquivo ilegível: RemessaNfBdoError (nada é gravado)."""
    conteudo = arquivo.read()
    lidas = {}
    for nome, pdf in iterar_pdfs(conteudo, arquivo.name):
        dados = ler_nf(ler_texto_pdf(pdf))
        lidas.setdefault(dados["numero"] or nome, (nome, pdf, dados))  # o .zip de dentro repete as NFs
    if not lidas:
        raise RemessaNfBdoError("Nenhum PDF de Nota Fiscal dentro do arquivo.")
    remessa = RemessaNfBdo(nome_original=arquivo.name[:255], enviado_por=usuario)
    remessa.arquivo.save(arquivo.name, ContentFile(conteudo), save=False)
    remessa.save()

    boletins = {b.numero: b for b in BoletimBdo.objects.filter(numero__in={d["boletim"] for _, _, d in lidas.values()})}
    ja_enviadas = 0
    notas = []
    for nome, pdf, dados in lidas.values():
        boletim = boletins.get(dados["boletim"])
        anteriores = NotaFiscalBdo.objects.filter(numero_nf=dados["numero"], boletim=boletim) if dados["numero"] else None
        if anteriores is not None and anteriores.exclude(situacao__in=NotaFiscalBdo.SITUACOES_ABERTAS).exclude(
                situacao=NotaFiscalBdo.DESCARTADA).exists():
            ja_enviadas += 1
            continue
        if anteriores is not None:
            anteriores.filter(situacao__in=NotaFiscalBdo.SITUACOES_ABERTAS).delete()
        nota = NotaFiscalBdo(remessa=remessa, boletim=boletim, nome_arquivo=nome[:255], numero_nf=dados["numero"],
                             valor=dados["valor"], boletim_lido=dados["boletim"], municipio_lido=dados["municipio"][:120],
                             uf_lida=dados["uf"])
        nota.arquivo.save(nome, ContentFile(pdf), save=False)
        notas.append(nota)

    por_boletim = {}
    for nota in notas:
        por_boletim.setdefault(nota.boletim_id, []).append(nota)
    for boletim_id, do_boletim in por_boletim.items():
        municipios = list(MunicipioBdo.objects.filter(boletim_id=boletim_id)) if boletim_id else []
        usados = set(NotaFiscalBdo.objects.filter(boletim_id=boletim_id, municipio_bdo__isnull=False)
                     .exclude(situacao__in=(NotaFiscalBdo.DESCARTADA, *NotaFiscalBdo.SITUACOES_ABERTAS))
                     .values_list("municipio_bdo_id", flat=True)) if boletim_id else set()
        usados |= set(NotaFiscalBdo.objects.filter(boletim_id=boletim_id, situacao__in=(
            NotaFiscalBdo.PRONTA, NotaFiscalBdo.JA_NO_PORTAL)).values_list("municipio_bdo_id", flat=True))
        # as que casam por nome e valor primeiro: a divergente não toma o município de uma certa
        def prioridade(nota):
            certa = any(valor_do_card(m) == nota.valor
                        for m in _municipios_pelo_nome(nota.municipio_lido, nota.uf_lida, municipios))
            return (not certa, len(nota.numero_nf), nota.numero_nf)

        for nota in sorted(do_boletim, key=prioridade):
            ligar_nota(nota, municipios, usados)
        for nota in do_boletim:
            nota.save()

    contagem = {}
    for nota in notas:
        contagem[nota.situacao] = contagem.get(nota.situacao, 0) + 1
    remessa.resumo = {"pdfs": len(lidas), "gravadas": len(notas), "ja_enviadas": ja_enviadas,
                      "boletins": sorted({n.boletim.numero for n in notas if n.boletim}), "situacoes": contagem}
    remessa.save(update_fields=["resumo"])
    return remessa


def decidir_nota(nota, municipio_id, usuario):
    """O usuário escolhe o município da NF (`municipio_id`) ou descarta (`None`). O município não pode ter outra NF
    deste Boletim pronta, na fila ou anexada."""
    if nota.situacao in (NotaFiscalBdo.NA_FILA, NotaFiscalBdo.PROCESSANDO, NotaFiscalBdo.ANEXADA):
        raise ValueError("Esta NF já foi para o portal.")
    agora = timezone.now()
    if municipio_id is None:
        nota.situacao, nota.municipio_bdo, nota.motivo = NotaFiscalBdo.DESCARTADA, None, "Descartada pelo usuário."
    else:
        if nota.boletim is None:
            raise ValueError("A NF não é de um Boletim importado.")
        municipio = MunicipioBdo.objects.filter(pk=municipio_id, boletim=nota.boletim).first()
        if municipio is None:
            raise ValueError("Escolha um município deste Boletim.")
        outra = NotaFiscalBdo.objects.filter(boletim=nota.boletim, municipio_bdo=municipio).exclude(pk=nota.pk).filter(
            situacao__in=(NotaFiscalBdo.PRONTA, NotaFiscalBdo.NA_FILA, NotaFiscalBdo.PROCESSANDO, NotaFiscalBdo.ANEXADA)).first()
        if outra:
            raise ValueError(f"{_rotulo(municipio)} já tem a NF {outra.numero_nf} ({outra.get_situacao_display()}).")
        nota.municipio_bdo, nota.ligada_por = municipio, "manual"
        if card_ja_com_nf(municipio):
            nota.situacao = NotaFiscalBdo.JA_NO_PORTAL
            nota.motivo = f"O card de {_rotulo(municipio)} no portal já está \"{municipio.status_eace}\"."
        else:
            nota.situacao, nota.motivo = NotaFiscalBdo.PRONTA, ""
            if nota.valor is not None and nota.valor != valor_do_card(municipio):
                nota.motivo = (f"Valor da NF ({_brl(nota.valor)}) diferente do card ({_brl(valor_do_card(municipio))}): "
                               "o robô vai recusar se o portal não mudar.")
    nota.decidido_por, nota.decidido_em = usuario, agora
    nota.save()
    return nota


def enfileirar_notas(boletim, usuario, ids=None):
    """As NFs Prontas do Boletim (ou só as `ids`, ou as com Erro escolhidas para reenviar) entram na fila do RPA
    EACE. Devolve quantas."""
    notas = NotaFiscalBdo.objects.filter(boletim=boletim, municipio_bdo__isnull=False)
    if ids is None:
        notas = notas.filter(situacao=NotaFiscalBdo.PRONTA)
    else:
        notas = notas.filter(pk__in=ids, situacao__in=(NotaFiscalBdo.PRONTA, NotaFiscalBdo.ERRO))
    return notas.update(situacao=NotaFiscalBdo.NA_FILA, enfileirado_por=usuario, enfileirado_em=timezone.now(),
                        motivo_erro="", etapa_atual="", iniciado_em=None, finalizado_em=None)


def recuperar_envios_interrompidos(agora=None) -> int:
    """Os que ficaram "Anexando" além do tempo máximo (worker reiniciado no meio) viram Erro."""
    agora = agora or timezone.now()
    return NotaFiscalBdo.objects.filter(
        situacao=NotaFiscalBdo.PROCESSANDO, iniciado_em__lt=agora - TEMPO_MAXIMO_PROCESSANDO,
    ).update(situacao=NotaFiscalBdo.ERRO, motivo_erro="interrompida", finalizado_em=agora)


def processar_proximo_envio_nf_bdo(robo=None):
    """Anexa no portal a NF mais antiga da fila (1 por chamada; quem chama é o worker do RPA EACE). Devolve a NF
    processada, ou None se a fila estava vazia."""
    with transaction.atomic():
        nota = (NotaFiscalBdo.objects.select_for_update().filter(situacao=NotaFiscalBdo.NA_FILA)
                .select_related("boletim", "municipio_bdo").order_by("enfileirado_em", "pk").first())
        if nota is None:
            return None
        agora = timezone.now()
        # ADR-009 (robôs em paralelo): troca condicional - outro robô já pegou, este não executa.
        if not NotaFiscalBdo.objects.filter(pk=nota.pk, situacao=NotaFiscalBdo.NA_FILA).update(
                situacao=NotaFiscalBdo.PROCESSANDO, iniciado_em=agora, robo=robo, progresso_pct=0, etapa_atual=""):
            return None
        nota.situacao, nota.iniciado_em, nota.robo = NotaFiscalBdo.PROCESSANDO, agora, robo

    def progresso(etapa, percentual):
        with _orm_liberado_dentro_do_playwright():
            NotaFiscalBdo.objects.filter(pk=nota.pk).update(etapa_atual=etapa[:100], progresso_pct=min(int(percentual or 0), 100))

    situacao, motivo, status_portal = NotaFiscalBdo.ERRO, "", ""
    try:
        from apps.integracoes.eace.rpa_bdo import RpaBdoIndisponivel, anexar_pdf_bdo

        resultado = anexar_pdf_bdo(pedido=nota.boletim.numero, municipio=nota.municipio_bdo.municipio,
                                   uf=nota.municipio_bdo.uf, caminho_pdf=nota.arquivo.path, progresso_callback=progresso)
    except RpaBdoIndisponivel:
        logger.exception("NF do BDO #%s: ambiente sem Playwright/Chromium.", nota.pk)
        motivo = "ambiente_indisponivel"
    except Exception:  # noqa: BLE001 - qualquer falha vira Erro com motivo, a fila continua
        logger.exception("NF do BDO #%s: erro inesperado.", nota.pk)
        motivo = "erro_inesperado"
    else:
        status_portal = resultado.status_portal or ""
        if resultado.sucesso:
            situacao = NotaFiscalBdo.ANEXADA
        else:
            motivo = resultado.motivo or "erro_inesperado"
    with transaction.atomic():
        nota.situacao, nota.motivo_erro, nota.status_portal = situacao, motivo[:60], status_portal[:60]
        nota.finalizado_em = timezone.now()
        nota.progresso_pct = 100 if situacao == NotaFiscalBdo.ANEXADA else nota.progresso_pct
        nota.save(update_fields=["situacao", "motivo_erro", "status_portal", "finalizado_em", "progresso_pct"])
        if situacao == NotaFiscalBdo.ANEXADA:  # baixa do município: o card recebeu a NF
            municipio = nota.municipio_bdo
            municipio.arquivo_nf_eace = nota.nome_arquivo[:255]
            municipio.status_eace = status_portal or "NF anexada"
            municipio.save(update_fields=["arquivo_nf_eace", "status_eace"])
    logger.info("NF do BDO #%s (Boletim %s, %s): %s %s", nota.pk, nota.boletim.numero, nota.municipio_bdo,
                situacao, motivo)
    return nota


def resumo_notas_boletim(boletim):
    """Contagem das NFs do Boletim por situação e dos municípios com NF anexada (pelo sistema ou já no portal)."""
    contagem = {}
    for situacao in NotaFiscalBdo.objects.filter(boletim=boletim).values_list("situacao", flat=True):
        contagem[situacao] = contagem.get(situacao, 0) + 1
    municipios = list(boletim.municipios.all())
    com_nf = sum(1 for m in municipios if card_ja_com_nf(m))
    return {"contagem": contagem, "total_municipios": len(municipios), "municipios_com_nf": com_nf,
            "pendentes_decisao": contagem.get(NotaFiscalBdo.DIVERGENTE, 0) + contagem.get(NotaFiscalBdo.SEM_MUNICIPIO, 0),
            "prontas": contagem.get(NotaFiscalBdo.PRONTA, 0), "na_fila": contagem.get(NotaFiscalBdo.NA_FILA, 0)
            + contagem.get(NotaFiscalBdo.PROCESSANDO, 0), "anexadas": contagem.get(NotaFiscalBdo.ANEXADA, 0),
            "erros": contagem.get(NotaFiscalBdo.ERRO, 0)}


def notas_para_fila(status_filtro, data_processamento=None):
    """NFs do BDO na tela "Projeto > Fila" (mesmos filtros de Status/Data do RI e do MIP; o BDO nao e por INEP).
    `status_filtro` usa os valores do `LogRpaEace` ("andamento", "todos", "na_fila", "processando", "sucesso",
    "atencao", "erro")."""
    from django.db.models import Case, IntegerField, Value, When
    from django.db.models.functions import Coalesce

    por_status = {
        "andamento": (NotaFiscalBdo.NA_FILA, NotaFiscalBdo.PROCESSANDO),
        "todos": (NotaFiscalBdo.NA_FILA, NotaFiscalBdo.PROCESSANDO, NotaFiscalBdo.ANEXADA, NotaFiscalBdo.ERRO),
        "na_fila": (NotaFiscalBdo.NA_FILA,), "processando": (NotaFiscalBdo.PROCESSANDO,),
        "sucesso": (NotaFiscalBdo.ANEXADA,), "erro": (NotaFiscalBdo.ERRO,), "atencao": (),
    }
    notas = NotaFiscalBdo.objects.filter(situacao__in=por_status.get(status_filtro, por_status["andamento"])).select_related(
        "boletim", "municipio_bdo")
    if data_processamento:
        notas = notas.annotate(data_efetiva=Coalesce("finalizado_em", "enfileirado_em", "criado_em")).filter(
            data_efetiva__date=data_processamento)
    return notas.annotate(prioridade=Case(
        When(situacao=NotaFiscalBdo.PROCESSANDO, then=Value(0)), When(situacao=NotaFiscalBdo.NA_FILA, then=Value(1)),
        default=Value(2), output_field=IntegerField(),
    )).order_by("prioridade", "-finalizado_em", "enfileirado_em", "pk")
