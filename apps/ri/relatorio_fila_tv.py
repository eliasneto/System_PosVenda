"""Planilha de relatório do processamento do RPA EACE (pedido do usuário,
2026-11-11): botão "Baixar planilha" no painel da TV (`/fila-tv/<token>/`).

Abas: Resumo (totais por resultado, processo e dia), Robôs (produção por
robô), Notas RI, Envios MIP e NFs BDO (1 linha por item já executado).
Filtros opcionais: período de execução (De/Até, datas locais) e processo
(RI, MIP ou BDO - pedido do usuário, 2026-11-16). Escrita em modo
`write_only` do openpyxl - não monta a planilha inteira na memória.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from io import BytesIO

from django.utils import timezone
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Font, PatternFill

from apps.escolas.models import LogRpaEaceMip, NotaFiscalBdo

from .models import LogRpaEace

ROBO_PADRAO = "Robô padrão (.env)"
TIPOS = ("RI", "MIP", "BDO")
# A NF do BDO guarda só a última tentativa: executada = anexada ou com erro.
_RESULTADO_BDO = {NotaFiscalBdo.ANEXADA: LogRpaEace.SUCESSO, NotaFiscalBdo.ERRO: LogRpaEace.ERRO}
_ROTULO_RESULTADO = dict(LogRpaEace.RESULTADO_CHOICES)
_CABECALHO_FONTE = Font(bold=True, color="FFFFFF")
_CABECALHO_FUNDO = PatternFill("solid", fgColor="1F2937")
_TITULO_FONTE = Font(bold=True, size=13)


def _local(valor: datetime | None) -> datetime | None:
    """Data/hora local sem fuso (o Excel não guarda fuso)."""
    return timezone.localtime(valor).replace(tzinfo=None) if valor else None


def _periodo(de: date | None, ate: date | None, campo: str = "executado_em") -> dict:
    filtro = {f"{campo}__isnull": False}
    if de:
        filtro[f"{campo}__gte"] = timezone.make_aware(datetime.combine(de, time.min))
    if ate:
        filtro[f"{campo}__lt"] = timezone.make_aware(datetime.combine(ate + timedelta(days=1), time.min))
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


def gerar_planilha(de: date | None = None, ate: date | None = None, tipo: str = "") -> bytes:
    """`tipo` "RI", "MIP" ou "BDO": só esse processo; vazio = todos."""
    tipos = (tipo,) if tipo in TIPOS else TIPOS
    filtro = _periodo(de, ate)
    logs_ri = list(
        LogRpaEace.objects.filter(**filtro)
        .select_related("ri__escola", "documento_pdf", "robo")
        .order_by("executado_em")
    ) if "RI" in tipos else []
    logs_mip = list(
        LogRpaEaceMip.objects.filter(**filtro).select_related("lote", "robo").order_by("executado_em")
    ) if "MIP" in tipos else []
    notas_bdo = list(
        NotaFiscalBdo.objects.filter(situacao__in=_RESULTADO_BDO, **_periodo(de, ate, "finalizado_em"))
        .select_related("boletim", "municipio_bdo", "robo").order_by("finalizado_em")
    ) if "BDO" in tipos else []
    # (processo, resultado, executado em, robô) de tudo que foi processado: base do Resumo e dos Robôs
    registros = (
        [("RI", log.resultado, log.executado_em, _robo(log)) for log in logs_ri]
        + [("MIP", log.resultado, log.executado_em, _robo(log)) for log in logs_mip]
        + [("BDO", _RESULTADO_BDO[nota.situacao], nota.finalizado_em, _robo(nota)) for nota in notas_bdo]
    )

    livro = Workbook(write_only=True)
    _aba_resumo(livro, de, ate, tipos, registros)
    _aba_robos(livro, registros)
    if "RI" in tipos:
        _aba_ri(livro, logs_ri)
    if "MIP" in tipos:
        _aba_mip(livro, logs_mip)
    if "BDO" in tipos:
        _aba_bdo(livro, notas_bdo)

    saida = BytesIO()
    livro.save(saida)
    return saida.getvalue()


def _aba_resumo(livro, de, ate, tipos, registros):
    resumo = livro.create_sheet("Resumo")
    _larguras(resumo, [34, 14, 14, 14, 14, 14])
    titulo = WriteOnlyCell(resumo, value="Relatório do RPA EACE")
    titulo.font = _TITULO_FONTE
    resumo.append([titulo])
    periodo = (
        f"{de.strftime('%d/%m/%Y') if de else 'início'} a {ate.strftime('%d/%m/%Y') if ate else 'hoje'}"
    )
    resumo.append(["Período (data de execução)", periodo])
    resumo.append(["Processo", " + ".join(tipos)])
    resumo.append(["Gerado em", _local(timezone.now())])
    na_fila = {
        "RI": lambda: LogRpaEace.objects.filter(resultado=LogRpaEace.NA_FILA).count(),
        "MIP": lambda: LogRpaEaceMip.objects.filter(resultado=LogRpaEaceMip.NA_FILA).count(),
        "BDO": lambda: NotaFiscalBdo.objects.filter(situacao=NotaFiscalBdo.NA_FILA).count(),
    }
    resumo.append([f"Na fila agora ({' + '.join(tipos)})", sum(na_fila[t]() for t in tipos)])
    resumo.append([])
    _linha_cabecalho(resumo, ["Resultado", *tipos, "Total"])
    por_resultado = defaultdict(Counter)
    for processo, resultado, _, _ in registros:
        por_resultado[_ROTULO_RESULTADO.get(resultado, resultado)][processo] += 1
    for nome in sorted(por_resultado):
        cont = por_resultado[nome]
        resumo.append([nome, *(cont[t] for t in tipos), sum(cont.values())])
    por_processo = Counter(registro[0] for registro in registros)
    resumo.append(["Total", *(por_processo[t] for t in tipos), len(registros)])
    resumo.append([])
    _linha_cabecalho(resumo, ["Dia", "Sucesso", "Atenção", "Erro", "Nova tentativa", "Total"])
    por_dia = defaultdict(Counter)
    for _, resultado, executado_em, _ in registros:
        por_dia[_local(executado_em).date()][resultado] += 1
    for dia in sorted(por_dia):
        cont = por_dia[dia]
        resumo.append([dia, cont["sucesso"], cont["atencao"], cont["erro"], cont["na_fila"], sum(cont.values())])


def _aba_robos(livro, registros):
    robos = livro.create_sheet("Robôs")
    _larguras(robos, [24, 12, 12, 12, 12, 16, 14, 22])
    _linha_cabecalho(robos, ["Robô", "Notas", "Sucesso", "Atenção", "Erro", "Nova tentativa", "% sucesso",
                             "Última execução"])
    por_robo = defaultdict(Counter)
    ultima = {}
    for _, resultado, executado_em, nome in registros:
        por_robo[nome][resultado] += 1
        ultima[nome] = max(ultima.get(nome) or executado_em, executado_em)

    def _ordem(nome):
        numero = nome.rsplit(" ", 1)[-1]
        return (0, int(numero)) if numero.isdigit() else (1, nome)

    for nome in sorted(por_robo, key=_ordem):
        cont = por_robo[nome]
        total = sum(cont.values())
        enviadas = cont["sucesso"] + cont["atencao"]
        robos.append([nome, total, cont["sucesso"], cont["atencao"], cont["erro"], cont["na_fila"],
                      round(100 * enviadas / total, 1) if total else 0, _local(ultima[nome])])


def _aba_ri(livro, logs_ri):
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


def _aba_mip(livro, logs_mip):
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


def _aba_bdo(livro, notas_bdo):
    from apps.escolas.leitura_eace_bdo import mensagem_motivo_bdo

    bdo = livro.create_sheet("NFs BDO")
    _larguras(bdo, [9, 10, 6, 6, 28, 10, 40, 14, 14, 50, 18, 20, 20, 20])
    _linha_cabecalho(bdo, ["NF (id)", "Boletim", "Tipo", "UF", "Município", "Nº NF", "PDF", "Valor NF", "Resultado",
                           "Motivo", "Robô", "Status no portal", "Executado em", "Entrou na fila em"])
    for nota in notas_bdo:
        municipio = nota.municipio_bdo
        bdo.append([
            nota.pk, nota.boletim.numero if nota.boletim else nota.boletim_lido,
            nota.boletim.tipo if nota.boletim else "", municipio.uf if municipio else nota.uf_lida,
            municipio.municipio if municipio else nota.municipio_lido, nota.numero_nf, nota.nome_arquivo, nota.valor,
            _ROTULO_RESULTADO[_RESULTADO_BDO[nota.situacao]],
            mensagem_motivo_bdo(nota.motivo_erro) if nota.motivo_erro else "", _robo(nota), nota.status_portal,
            _local(nota.finalizado_em), _local(nota.enfileirado_em),
        ])
