import csv
import re
import warnings
from collections import Counter
from pathlib import Path

import openpyxl
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.core.services import BackupError, criar_backup_seguranca
from apps.escolas.models import Escola
from apps.ri.models import Ri, RiHistorico
from apps.ri.services import trocar_status_com_log

ARQUIVO_PADRAO = "doc/RelatorioRIBI.xlsx"
COLUNA_DISCRIMINACAO = "DISCRIMINACAO"
INEP_NA_DISCRIMINACAO = re.compile(r"INEP\s*:?\s*(\d{8})\b", re.IGNORECASE)
ITEM_NA_DISCRIMINACAO = re.compile(r"ITEM LPU\s*:?\s*(.*?)\s*MUNIC", re.IGNORECASE)

BAIXADO = "baixado"
JA_CONCLUIDO = "ja_concluido"
NAO_CADASTRADO = "nao_cadastrado"
SEM_RI = "sem_ri"
ROTULOS_RESULTADO = {
    BAIXADO: "Baixado como Faturamento RI Concluído",
    JA_CONCLUIDO: "Já estava em Faturamento RI Concluído (desconsiderado)",
    NAO_CADASTRADO: "INEP não cadastrado no sistema",
    SEM_RI: "INEP sem RI no sistema",
}


class _SimulacaoConcluida(Exception):
    """Desfaz a transação no fim da simulação."""


def _cabecalho(valor):
    return (str(valor) if valor is not None else "").strip().upper()


def _notas_por_inep(caminho):
    """{INEP: [notas]} a partir da coluna DISCRIMINACAO (texto "INEP: <8
    dígitos> ITEM LPU: <item> MUNICIPIO/UF: ..."), na ordem da planilha.
    Cada nota guarda o nº da NF, o item, o Status da nota e o "Empenho"
    (INEP informado em coluna própria) só para o relatório apontar
    divergência — o INEP que vale é sempre o da DISCRIMINACAO."""
    with warnings.catch_warnings():
        # Export do ERP vem sem estilo padrão — aviso inofensivo do openpyxl.
        warnings.simplefilter("ignore", UserWarning)
        workbook = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
    try:
        linhas = list(workbook.worksheets[0].iter_rows(values_only=True))
    finally:
        workbook.close()
    if not linhas:
        raise CommandError("Planilha vazia.")
    indice = {_cabecalho(valor): posicao for posicao, valor in enumerate(linhas[0])}
    if COLUNA_DISCRIMINACAO not in indice:
        raise CommandError(f'Coluna "{COLUNA_DISCRIMINACAO}" não encontrada na 1ª aba.')

    def valor(linha, coluna):
        posicao = indice.get(coluna)
        return linha[posicao] if posicao is not None and posicao < len(linha) else None

    notas = {}
    for linha in linhas[1:]:
        discriminacao = str(valor(linha, COLUNA_DISCRIMINACAO) or "")
        achado = INEP_NA_DISCRIMINACAO.search(discriminacao)
        if not achado:
            continue  # linha em branco / rodapé de filtros do relatório
        item = ITEM_NA_DISCRIMINACAO.search(discriminacao)
        notas.setdefault(achado.group(1), []).append({
            "nf": str(valor(linha, "DOCNUM") or "").strip(),
            "item": item.group(1).strip() if item else "",
            "status_nota": str(valor(linha, "STATUS") or "").strip(),
            "empenho": str(valor(linha, "EMPENHO") or "").strip(),
            "escola": str(valor(linha, "SECRETARIA") or "").strip(),
        })
    return notas


def _mensagem_historico(nome_usuario, quando, nome_arquivo, status_anterior, notas):
    """Texto da entrada "Importação em massa" — cabe nos 250 caracteres de
    `RiHistorico.mensagem` (lista de itens cortada com "..." se precisar)."""
    inicio = (
        f"RI concluído via processamento em massa em {quando:%d/%m/%Y %H:%M} por {nome_usuario} "
        f"(planilha {nome_arquivo}). Status do RI: {status_anterior} → Faturamento RI Concluído. "
        f"{len(notas)} NF(s) faturada(s): "
    )
    itens = ", ".join(dict.fromkeys(nota["item"] for nota in notas if nota["item"])) or "—"
    espaco = RiHistorico._meta.get_field("mensagem").max_length - len(inicio) - 1
    if len(itens) > espaco:
        return f"{inicio}{itens[: espaco - 2].rstrip(', ')}..."
    return f"{inicio}{itens}."


def baixar_ris(notas_por_inep, usuario, nome_arquivo):
    """Passa para "Faturamento RI Concluído" o RI atual de cada INEP da
    planilha que ainda não está nesse status, com log de status/auditoria
    (`trocar_status_com_log`) e 1 entrada "Importação em massa" no
    histórico do RI. INEP já concluído não é tocado — rodar de novo não
    duplica nada. Devolve 1 registro por INEP para o relatório."""
    quando = timezone.localtime()
    nome_usuario = usuario.get_full_name() or usuario.username
    escolas = {escola.inep: escola for escola in Escola.objects.filter(inep__in=list(notas_por_inep))}
    registros = []
    for inep, notas in notas_por_inep.items():
        registro = {"inep": inep, "notas": notas, "status_antes": "", "status_mip_antes": "", "status_mip_depois": ""}
        registros.append(registro)
        escola = escolas.get(inep)
        if escola is None:
            registro["resultado"] = NAO_CADASTRADO
            continue
        registro["escola"] = escola.nome
        ri = Ri.objects.filter(escola=escola).order_by("-criado_em").first()
        if ri is None:
            registro["resultado"] = SEM_RI
            continue
        registro["status_antes"] = ri.get_status_display()
        registro["status_mip_antes"] = escola.get_status_mip_display() if escola.status_mip else ""
        if ri.status == Ri.FATURAMENTO_RI_CONCLUIDO:
            registro["resultado"] = JA_CONCLUIDO
            continue
        trocar_status_com_log(ri, Ri.FATURAMENTO_RI_CONCLUIDO, usuario)
        RiHistorico.objects.create(
            ri=ri,
            tipo=RiHistorico.IMPORTACAO_MASSA,
            autor=usuario,
            mensagem=_mensagem_historico(nome_usuario, quando, nome_arquivo, registro["status_antes"], notas),
        )
        escola.refresh_from_db(fields=["status_mip"])
        registro["status_mip_depois"] = escola.get_status_mip_display() if escola.status_mip else ""
        registro["resultado"] = BAIXADO
    return registros


class Command(BaseCommand):
    """Pedido do usuário (2026-10-07): dá baixa como "Faturamento RI
    Concluído" nos RIs dos INEPs já faturados antes do sistema, a partir do
    relatório de NFs do ERP ("RelatorioRIBI.xlsx", coluna DISCRIMINACAO com
    INEP, item e faturado). INEP que já está nesse status é desconsiderado.
    Cada RI baixado ganha o log de status de sempre e 1 entrada "Importação
    em massa" no histórico dizendo que foi processamento em massa, por quem
    e quando. Como em toda conclusão de RI, `Ri.save()` coloca o INEP no
    MIP ("Aguardando Validação EACE") se ele ainda não estiver lá.

    Simulação por padrão (faz tudo e desfaz no fim, para o relatório ser
    exatamente o que seria gravado); `--aplicar` faz antes o backup de
    segurança do banco (`criar_backup_seguranca`, aborta se falhar) e grava
    de verdade, tudo numa transação só (tudo ou nada). Rodar de novo é seguro: o que já foi
    baixado aparece como "já estava concluído".

    Pendência (CLAUDE.md §1): formalizar RN/FEAT em business_rules.md/
    checklist.md — cabe ao Orquestrador."""

    help = (
        "Baixa como 'Faturamento RI Concluido' os RIs dos INEPs do RelatorioRIBI.xlsx (coluna DISCRIMINACAO). "
        "Simulacao por padrao; use --aplicar para gravar."
    )

    def add_arguments(self, parser):
        parser.add_argument("arquivo", nargs="?", default=ARQUIVO_PADRAO, help=f"Planilha (padrão: {ARQUIVO_PADRAO}).")
        parser.add_argument("--usuario", required=True, help="Username gravado como autor nos históricos.")
        parser.add_argument("--relatorio", help="Caminho de um .csv com o resultado de cada INEP.")
        parser.add_argument("--aplicar", action="store_true", help="Grava de verdade (sem isto, só simula).")

    def handle(self, *args, **opcoes):
        caminho = Path(opcoes["arquivo"])
        if not caminho.is_file():
            raise CommandError(f"Arquivo não encontrado: {caminho}")
        try:
            usuario = get_user_model().objects.get(username=opcoes["usuario"])
        except get_user_model().DoesNotExist:
            raise CommandError(f"Usuário não encontrado: {opcoes['usuario']}")

        notas_por_inep = _notas_por_inep(caminho)
        if not notas_por_inep:
            raise CommandError("Nenhum INEP encontrado na coluna DISCRIMINACAO.")
        aplicar = opcoes["aplicar"]
        self.stdout.write(
            f"Arquivo: {caminho.name} | NFs: {sum(len(n) for n in notas_por_inep.values())} | "
            f"INEPs distintos: {len(notas_por_inep)} | usuário: {usuario.username}\n"
            f"Modo: {'APLICAR (grava de verdade)' if aplicar else 'SIMULACAO (nada é gravado)'}"
        )

        if aplicar:
            # Mesmo backup de segurança da tela Administrador > Backup (aparece
            # lá e pode ser restaurado por ela) — sem backup confirmado, não grava.
            try:
                backup = criar_backup_seguranca(usuario.username)
            except BackupError as erro:
                raise CommandError(f"Backup do banco falhou - nada foi gravado: {erro}")
            self.stdout.write(f"Backup de segurança: {backup}")

        try:
            with transaction.atomic():
                registros = baixar_ris(notas_por_inep, usuario, caminho.name)
                if not aplicar:
                    raise _SimulacaoConcluida
        except _SimulacaoConcluida:
            pass

        contagem = Counter(registro["resultado"] for registro in registros)
        self.stdout.write("\nResumo por INEP:")
        for resultado, rotulo in ROTULOS_RESULTADO.items():
            self.stdout.write(f"  {rotulo}: {contagem.get(resultado, 0)}")
        baixados = [registro for registro in registros if registro["resultado"] == BAIXADO]
        self.stdout.write("\nStatus do RI antes da baixa:")
        for status, quantidade in Counter(registro["status_antes"] for registro in baixados).most_common():
            self.stdout.write(f"  {status}: {quantidade}")
        entraram_mip = sum(1 for registro in baixados if not registro["status_mip_antes"] and registro["status_mip_depois"])
        self.stdout.write(f"  (entram no MIP como \"Aguardando Validação EACE\": {entraram_mip})")

        fora = [registro for registro in registros if registro["resultado"] in (NAO_CADASTRADO, SEM_RI)]
        if fora:
            self.stdout.write(self.style.WARNING("\nINEPs que ficaram de fora:"))
            for registro in fora:
                self.stdout.write(f"  {registro['inep']} — {ROTULOS_RESULTADO[registro['resultado']]}")

        avisos = [
            (registro["inep"], nota)
            for registro in registros
            for nota in registro["notas"]
            if nota["empenho"] != registro["inep"] or nota["status_nota"].upper() != "FECHADO"
        ]
        if avisos:
            self.stdout.write(self.style.WARNING("\nAvisos (só informativos, não impedem a baixa):"))
            for inep, nota in avisos:
                if nota["empenho"] != inep:
                    self.stdout.write(f"  NF {nota['nf']}: DISCRIMINACAO diz INEP {inep}, coluna Empenho diz {nota['empenho']} ({nota['escola']})")
                if nota["status_nota"].upper() != "FECHADO":
                    self.stdout.write(f"  NF {nota['nf']} do INEP {inep}: Status da nota \"{nota['status_nota']}\"")

        if opcoes["relatorio"]:
            with open(opcoes["relatorio"], "w", newline="", encoding="utf-8-sig") as arquivo_csv:
                escritor = csv.writer(arquivo_csv, delimiter=";")
                escritor.writerow([
                    "INEP", "Escola", "Resultado", "Status do RI antes", "Status (MIP) antes", "Status (MIP) depois",
                    "Qtd NFs", "NFs", "Itens",
                ])
                for registro in registros:
                    escritor.writerow([
                        registro["inep"], registro.get("escola") or registro["notas"][0]["escola"],
                        ROTULOS_RESULTADO[registro["resultado"]], registro["status_antes"],
                        registro["status_mip_antes"], registro["status_mip_depois"], len(registro["notas"]),
                        ", ".join(nota["nf"] for nota in registro["notas"]),
                        ", ".join(nota["item"] for nota in registro["notas"]),
                    ])
            self.stdout.write(f"\nRelatório: {opcoes['relatorio']}")

        if aplicar:
            self.stdout.write(self.style.SUCCESS(f"\nBaixa aplicada: {len(baixados)} RI(s) concluído(s)."))
        else:
            self.stdout.write(self.style.WARNING("\nSimulação (nada foi gravado). Rode com --aplicar para gravar."))
