"""Planilha de relatório do processamento do RPA EACE (pedido do usuário,
2026-11-11): botão "Baixar planilha" no painel da TV (`/fila-tv/<token>/`).

Abas: Resumo (totais por resultado, tipo e dia), Robôs (produção por robô),
Notas RI e Envios MIP (1 linha por log já executado). Filtro opcional por
período de execução (De/Até, datas locais). Escrita em modo `write_only` do
openpyxl - não monta a planilha inteira na memória.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from io import BytesIO

from django.utils import timezone
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Font, PatternFill

from apps.escolas.models import LogRpaEaceMip

from .models import LogRpaEace

ROBO_PADRAO = "Robô padrão (.env)"
_CABECALHO_FONTE = Font(bold=True, color="FFFFFF")
_CABECALHO_FUNDO = PatternFill("solid", fgColor="1F2937")
_TITULO_FONTE = Font(bold=True, size=13)


def _local(valor: datetime | None) -> datetime | None:
    """Data/hora local sem fuso (o Excel não guarda fuso)."""
    return timezone.localtime(valor).replace(tzinfo=None) if valor else None


def _periodo(de: date | None, ate: date | None) -> dict:
    filtro = {"executado_em__isnull": False}
    if de:
        filtro["executado_em__gte"] = timezone.make_aware(datetime.combine(de, time.min))
    if ate:
        filtro["executado_em__lt"] = timezone.make_aware(datetime.combine(ate + timedelta(days=1), time.min))
    return filtro


def _robo(log) -> str:
    return log.robo.nome if log.robo_id else ROBO_PADRAO


def _linha_cabecalho(planilha, titulos: list[str]):
    linha = []
    for titulo in titulos:
        celula = WriteOnlyCell(planilha, value=titulo)
        celula.font, celula.fill = _CABECALHO_FONTE, _CABECALHO_FUNDO
        celula.alignment = Alignment(vertical="center")
        linha.append(celula)
    planilha.append(linha)


def _larguras(planilha, larguras: list[int]):
    for indice, largura in enumerate(larguras):
        planilha.column_dimensions[chr(ord("A") + indice)].width = largura


def gerar_planilha(de: date | None = None, ate: date | None = None) -> bytes:
    filtro = _periodo(de, ate)
    logs_ri = list(
        LogRpaEace.objects.filter(**filtro)
        .select_related("ri__escola", "documento_pdf", "robo")
        .order_by("executado_em")
    )
    logs_mip = list(
        LogRpaEaceMip.objects.filter(**filtro).select_related("lote", "robo").order_by("executado_em")
    )

    livro = Workbook(write_only=True)

    # ---- Resumo
    resumo = livro.create_sheet("Resumo")
    _larguras(resumo, [34, 14, 14, 14, 14, 14])
    titulo = WriteOnlyCell(resumo, value="Relatório do RPA EACE")
    titulo.font = _TITULO_FONTE
    resumo.append([titulo])
    periodo = (
        f"{de.strftime('%d/%m/%Y') if de else 'início'} a {ate.strftime('%d/%m/%Y') if ate else 'hoje'}"
    )
    resumo.append(["Período (data de execução)", periodo])
    resumo.append(["Gerado em", _local(timezone.now())])
    resumo.append(["Na fila agora (RI + MIP)",
                   LogRpaEace.objects.filter(resultado=LogRpaEace.NA_FILA).count()
                   + LogRpaEaceMip.objects.filter(resultado=LogRpaEaceMip.NA_FILA).count()])
    resumo.append([])
    _linha_cabecalho(resumo, ["Resultado", "RI", "MIP", "Total"])
    ri_por_resultado = Counter(log.get_resultado_display() for log in logs_ri)
    mip_por_resultado = Counter(log.get_resultado_display() for log in logs_mip)
    for nome in sorted(set(ri_por_resultado) | set(mip_por_resultado)):
        resumo.append([nome, ri_por_resultado[nome], mip_por_resultado[nome],
                       ri_por_resultado[nome] + mip_por_resultado[nome]])
    resumo.append(["Total", len(logs_ri), len(logs_mip), len(logs_ri) + len(logs_mip)])
    resumo.append([])
    _linha_cabecalho(resumo, ["Dia", "Sucesso", "Atenção", "Erro", "Nova tentativa", "Total"])
    por_dia = defaultdict(Counter)
    for log in [*logs_ri, *logs_mip]:
        por_dia[_local(log.executado_em).date()][log.resultado] += 1
    for dia in sorted(por_dia):
        cont = por_dia[dia]
        resumo.append([dia, cont["sucesso"], cont["atencao"], cont["erro"], cont["na_fila"], sum(cont.values())])

    # ---- Robôs
    robos = livro.create_sheet("Robôs")
    _larguras(robos, [24, 12, 12, 12, 12, 16, 14, 22])
    _linha_cabecalho(robos, ["Robô", "Notas", "Sucesso", "Atenção", "Erro", "Nova tentativa", "% sucesso",
                             "Última execução"])
    por_robo = defaultdict(Counter)
    ultima = {}
    for log in [*logs_ri, *logs_mip]:
        nome = _robo(log)
        por_robo[nome][log.resultado] += 1
        ultima[nome] = max(ultima.get(nome) or log.executado_em, log.executado_em)

    def _ordem(nome):
        numero = nome.rsplit(" ", 1)[-1]
        return (0, int(numero)) if numero.isdigit() else (1, nome)

    for nome in sorted(por_robo, key=_ordem):
        cont = por_robo[nome]
        total = sum(cont.values())
        enviadas = cont["sucesso"] + cont["atencao"]
        robos.append([nome, total, cont["sucesso"], cont["atencao"], cont["erro"], cont["na_fila"],
                      round(100 * enviadas / total, 1) if total else 0, _local(ultima[nome])])

    # ---- Notas RI
    notas = livro.create_sheet("Notas RI")
    _larguras(notas, [9, 11, 40, 38, 16, 50, 11, 18, 14, 14, 40, 20, 20, 12])
    _linha_cabecalho(notas, ["Log", "INEP", "Escola", "Nota fiscal (PDF)", "Resultado", "Motivo", "Tentativas",
                             "Robô", "Valor PDF", "Valor portal", "Produto (PDF)", "Executado em",
                             "Entrou na fila em", "Manual"])
    for log in logs_ri:
        escola = log.ri.escola
        notas.append([
            log.pk, escola.inep, escola.nome,
            log.documento_pdf.arquivo.name.rsplit("/", 1)[-1] if log.documento_pdf else "",
            log.get_resultado_display(), log.motivo_erro_legivel if log.motivo_erro else "", log.tentativas,
            _robo(log), log.valor_pdf, log.valor_portal, log.produto_pdf,
            _local(log.executado_em), _local(log.enfileirado_em), "Sim" if log.concluido_manualmente else "",
        ])

    # ---- Envios MIP
    mip = livro.create_sheet("Envios MIP")
    _larguras(mip, [9, 6, 28, 40, 16, 50, 11, 18, 14, 14, 20, 12, 20])
    _linha_cabecalho(mip, ["Log", "UF", "Município", "Nota fiscal", "Resultado", "Motivo", "Tentativas", "Robô",
                           "Valor PDF", "Valor portal", "Status no portal", "Pedido", "Executado em"])
    for log in logs_mip:
        mip.append([
            log.pk, log.lote.estado, log.municipio, log.nome_nota_fiscal, log.get_resultado_display(),
            log.motivo_erro_legivel if log.motivo_erro else "", log.tentativas, _robo(log), log.valor_pdf,
            log.valor_portal, log.status_portal, log.pedido, _local(log.executado_em),
        ])

    saida = BytesIO()
    livro.save(saida)
    return saida.getvalue()
