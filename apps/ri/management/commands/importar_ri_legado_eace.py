from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.escolas.models import Escola
from apps.escolas.services import (
    RelatorioEaceMipSincronizacaoError,
    sincronizar_relatorio_eace_mip_de_todas_as_escolas,
)
from apps.ri.models import KitPadrao, Ri, RiHistorico, RiItemIxc
from apps.ri.services import sincronizar_divergencia_kit_relatorio

try:
    import openpyxl
except ImportError:
    openpyxl = None


COLUNAS_OBRIGATORIAS = (
    "LOTE",
    "UF",
    "MUNICIPIO",
    "INEP",
    "UNIDADE ESCOLAR",
    "ENDEREÇO UNIDADE ESCOLAR",
    "VELOCIDADE",
    "KIT WIFI ESTIMADO",
    "KIT WIFI INSTALADO",
    "AP ADICIONAL ESTIMADO",
    "NOBREAK",
    "SWITCH",
    "CONVERSOR",
    "RACK",
    "STATUS",
    "DATA DE ATIVAÇÃO",
)

# Pedido do usuário (2026-09-10) — texto gravado em `RiHistorico.mensagem`
# (limite de 250 caracteres do campo) para cada RI tocado por este comando.
MENSAGEM_HISTORICO = (
    'Equipamento (Lado IXC) e status iniciados a partir da planilha '
    'histórica do pós-venda ("CONSOLIDADO EACE Atualizado.xlsx") — '
    'atendimento já realizado antes deste sistema existir, sem '
    'lançamento manual pela tela.'
)


def _normalizar_cabecalho(valor):
    return (str(valor) if valor is not None else "").strip().upper()


def _texto(valor):
    return str(valor).strip() if valor not in (None, "") else ""


def _inteiro(valor):
    try:
        return int(valor) if valor not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _quantidade_valida(valor):
    qtd = _inteiro(valor)
    return qtd if qtd and qtd > 0 else None


def _data(valor):
    """Aceita tanto `datetime.datetime` (o que o Excel/openpyxl devolve na
    pratica para uma celula de data) quanto `datetime.date` puro — nunca
    inventa uma data a partir de outro tipo de valor."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return None


def _valor_equipamento(kit_padrao):
    if kit_padrao is None or kit_padrao.valor_equipamento in (None, ""):
        return Decimal("0")
    return Decimal(str(kit_padrao.valor_equipamento))


def _montar_itens_equipamento(escola, linha, indice_coluna):
    """Resolve os itens de equipamento desta linha contra o catálogo LPU
    (`KitPadrao`), por Lote (pedido do usuário: "todos os valores de
    equipamentos é o que está na LPU de acordo com o LOTE") — retorna
    `(itens, avisos)`. Nunca inventa um item sem correspondência exata no
    catálogo (CLAUDE.md §9): KIT/Nobreak/AP Adicional/Conversor sem
    correspondência, e Switch/Rack (a planilha só informa "tem 1 unidade",
    sem tamanho/modelo, e a LPU tem várias variantes de cada um) viram
    aviso para lançamento manual, nunca um item inventado."""
    itens = []
    avisos = []
    lote = escola.lote

    kit_valor = linha[indice_coluna["KIT WIFI INSTALADO"]]
    if kit_valor not in (None, ""):
        kit_padrao = KitPadrao.resolver_kit_declarado(str(kit_valor), lote=lote)
        if kit_padrao is None:
            avisos.append(f"KIT Instalado ({kit_valor} AP) sem correspondência na LPU (Lote {lote}) - não lançado")
        else:
            itens.append(dict(
                descricao_item=kit_padrao.descricao_curta or kit_padrao.descricao,
                quantidade=1, valor_unitario=_valor_equipamento(kit_padrao), eh_kit=True,
            ))

    nobreak_valor = linha[indice_coluna["NOBREAK"]]
    qtd = _quantidade_valida(nobreak_valor)
    if nobreak_valor not in (None, "") and qtd:
        nobreak_padrao = KitPadrao.resolver_nobreak_declarado("Nobreak", lote=lote)
        if nobreak_padrao is None:
            avisos.append(f"Nobreak ({nobreak_valor}x) sem correspondência na LPU (Lote {lote}) - não lançado")
        else:
            itens.append(dict(
                descricao_item=nobreak_padrao.descricao_curta or nobreak_padrao.descricao,
                quantidade=qtd, valor_unitario=_valor_equipamento(nobreak_padrao), eh_kit=False,
            ))

    ap_valor = linha[indice_coluna["AP ADICIONAL ESTIMADO"]]
    qtd = _quantidade_valida(ap_valor)
    if ap_valor not in (None, "") and qtd:
        ap_padrao = KitPadrao.objects.filter(lote=lote, descricao_curta="Access Point adicional Indoor").first()
        if ap_padrao is None:
            avisos.append(f"AP Adicional ({ap_valor}x) sem correspondência na LPU (Lote {lote}) - não lançado")
        else:
            itens.append(dict(
                descricao_item=ap_padrao.descricao_curta or ap_padrao.descricao,
                quantidade=qtd, valor_unitario=_valor_equipamento(ap_padrao), eh_kit=False,
            ))

    conversor_valor = linha[indice_coluna["CONVERSOR"]]
    qtd = _quantidade_valida(conversor_valor)
    if conversor_valor not in (None, "") and qtd:
        conversor_padrao = KitPadrao.objects.filter(
            lote=lote, descricao_curta="Conversor de mídia Gigabit Ethernet"
        ).first()
        if conversor_padrao is None:
            avisos.append(f"Conversor ({conversor_valor}x) sem correspondência na LPU (Lote {lote}) - não lançado")
        else:
            itens.append(dict(
                descricao_item=conversor_padrao.descricao_curta or conversor_padrao.descricao,
                quantidade=qtd, valor_unitario=_valor_equipamento(conversor_padrao), eh_kit=False,
            ))

    for rotulo, coluna in (("Switch", "SWITCH"), ("Rack", "RACK")):
        valor = linha[indice_coluna[coluna]]
        if valor not in (None, ""):
            avisos.append(
                f"{rotulo} ({valor}x) tem mais de um modelo na LPU e a planilha não informa qual - "
                "não lançado, lançar manualmente no Lado IXC"
            )

    return itens, avisos


class Command(BaseCommand):
    """Pedido do usuário (2026-09-10): traz para o sistema, como histórico,
    os INEPs "ATIVO" da planilha "CONSOLIDADO EACE Atualizado.xlsx" (aba
    FATURAMENTO MATERIAIS) cujo RI ainda está 100% intocado — nunca
    lançado, criado ou trabalhado pela tela. Cada um desses RI:

    - nasce/passa para o status "Aguardando validação EACE";
    - ganha os itens de equipamento (KIT Instalado, Nobreak, AP Adicional,
      Conversor) no Lado IXC (2º lado), com nomenclatura do catálogo LPU
      (`KitPadrao`) e Valor Unitário = valor de Equipamento da LPU por
      Lote — exceção pontual pedida pelo usuário para este comando: o
      lançamento manual normal do Lado IXC nasce sempre com R$ 0,00
      (RN-011), mas aqui o valor real já é conhecido (dado histórico, não
      lançamento novo);
    - ganha uma entrada no Histórico do RI avisando que os dados de
      equipamento vieram desta planilha, de antes do sistema existir;
    - tem o nome do INEP marcado (`Escola.legado=True`), exibido em
      negrito/amarelo no Grid de INEPs (FEAT-007) e no MIP.

    Pedido do usuário (2026-09-10, correção): um INEP novo nasce com
    `Escola.encontrado_relatorio_eace_mip=None` — sem bolinha nenhuma no
    grid Projeto > MIP até rodar "Sincronizar todos os INEPs" (RN-081).
    Por isso, ao final (só quando --aplicar tocou pelo menos 1 INEP), este
    comando também roda essa mesma sincronização do MIP para TODA Escola
    (`sincronizar_relatorio_eace_mip_de_todas_as_escolas`, já existente,
    apps.escolas.services) — os INEPs legados entram na regra normal da
    bolinha (verde/vermelha), igual a qualquer outro INEP. Sem Relatório
    EACE (MIP) ativo, só avisa (não falha a importação por causa de um
    upload de outra tela).

    O Lado Relatório EACE (3º lado) NUNCA é tocado por este comando — fica
    em branco, e por isso não entra na regra de bloqueio por divergência
    (RN-003 já trata lado vazio como "sem divergência").

    Só entra no escopo o INEP com STATUS="ATIVO" na planilha. Por padrão,
    só é tocado o RI 100% intocado: status "Implantação EACE", sem Data
    de Ativação e sem nenhum item lançado em qualquer um dos 3 lados —
    RI com progresso real (outro status, ou algum dado já lançado) é
    IGNORADO, nunca sobrescrito (decisão do usuário, 2026-09-10, dado o
    volume real de RI já em "Faturamento Concluído"/andamento encontrado
    na base local).

    `--incluir-com-progresso` (pedido do usuário, mesmo dia, ampliação
    depois de conferir que só 14 dos 550 INEPs "ATIVO" da planilha
    passavam no critério acima): estende o mesmo tratamento para TODOS os
    550, **independente do status atual do RI** — inclusive revertendo um
    RI já "Faturamento Concluído" de volta para "Aguardando validação
    EACE". Nesse modo, o comando nunca duplica dado já lançado: só cria o
    KIT Instalado se o RI ainda não tiver nenhum (`eh_kit=True`) e só cria
    Nobreak/AP Adicional/Conversor se a mesma Descrição ainda não existir
    no Lado IXC daquele RI; Data de Ativação só é gravada num RI novo,
    nunca sobrescreve uma já existente. Aviso: reverter "Faturamento
    Concluído" tira esses RIs dos cards financeiros do dashboard
    (RN-025/026, calculados só sobre RI nesse status) e os torna
    visitáveis de novo pelo Sincronizador em lote (RN-024) — efeito
    esperado da correção pedida, não um bug.

    SWITCH e RACK têm mais de uma variante no catálogo LPU (ex.: Switch de
    8/16/24/36 portas, Rack 3U/5U/7U/9U/Outdoor) e a planilha não informa
    qual — o comando NUNCA inventa o modelo: se uma dessas colunas vier
    preenchida, o item fica de fora e é listado no resumo para lançamento
    manual (CLAUDE.md §9).

    Por padrão roda em modo simulação (não grava nada) — use --aplicar
    para gravar de fato (mesmo padrão de `importar_nova_base_eace`).

    Pendência (fora do escopo do Dev, CLAUDE.md §1): esta regra ainda não
    tem `RN-XXX`/`FEAT-XXX` formalizada em `business_rules.md`/
    `checklist.md` — cabe ao Orquestrador registrar.
    """

    help = (
        "Importa como legado os INEPs 'ATIVO' da planilha CONSOLIDADO EACE "
        "Atualizado.xlsx (aba FATURAMENTO MATERIAIS): status Aguardando "
        "validacao EACE, equipamento no Lado IXC (2o lado) com nomenclatura/"
        "valor da LPU, historico e nome do INEP marcado como legado. Por "
        "padrao so toca RI 100% intocado; use --incluir-com-progresso para "
        "estender a todos, mesmo com progresso real. Por padrao so simula; "
        "use --aplicar para gravar."
    )

    def add_arguments(self, parser):
        parser.add_argument("arquivo", type=str, help="Caminho para 'CONSOLIDADO EACE Atualizado.xlsx'.")
        parser.add_argument(
            "--aba", default="FATURAMENTO MATERIAIS",
            help="Nome da aba com os dados (padrao: FATURAMENTO MATERIAIS).",
        )
        parser.add_argument(
            "--linha-cabecalho", type=int, default=13,
            help="Numero da linha (1-based) com os titulos das colunas (padrao: 13).",
        )
        parser.add_argument(
            "--aplicar", action="store_true",
            help="Grava as alteracoes no banco. Sem esta flag, so mostra o que seria feito.",
        )
        parser.add_argument(
            "--incluir-com-progresso", action="store_true",
            help=(
                "Estende o tratamento a TODOS os INEPs 'ATIVO' da planilha, mesmo com RI ja em "
                "progresso real (inclusive 'Faturamento Concluido', revertido para 'Aguardando "
                "validacao EACE'). Sem esta flag, so toca RI 100 por cento intocado (padrao)."
            ),
        )

    def handle(self, *args, **options):
        if openpyxl is None:
            raise CommandError(
                "Dependencia 'openpyxl' nao instalada. Adicione 'openpyxl' ao requirements.txt "
                "e reinstale as dependencias."
            )

        caminho = Path(options["arquivo"])
        if not caminho.exists():
            raise CommandError(f"Arquivo nao encontrado: {caminho}")

        try:
            planilha = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
        except Exception as erro:
            raise CommandError(f"Nao foi possivel abrir '{caminho}': {erro}")

        aba = options["aba"]
        if aba not in planilha.sheetnames:
            raise CommandError(f"Aba '{aba}' nao encontrada. Abas disponiveis: {planilha.sheetnames}")

        planilha_aba = planilha[aba]
        linha_cabecalho = options["linha_cabecalho"]

        cabecalho = next(
            planilha_aba.iter_rows(min_row=linha_cabecalho, max_row=linha_cabecalho, values_only=True), None
        )
        if cabecalho is None:
            raise CommandError(f"Linha de cabecalho {linha_cabecalho} vazia ou inexistente na aba '{aba}'.")

        indice_coluna = {_normalizar_cabecalho(valor): posicao for posicao, valor in enumerate(cabecalho)}
        faltando = [coluna for coluna in COLUNAS_OBRIGATORIAS if coluna not in indice_coluna]
        if faltando:
            raise CommandError(f"Colunas obrigatorias ausentes na planilha: {faltando}")

        aplicar = options["aplicar"]
        incluir_com_progresso = options["incluir_com_progresso"]

        vistos = set()
        ignoradas_invalidas = 0
        ignoradas_nao_ativo = 0
        ignoradas_com_progresso = 0
        escolas_novas = 0
        ris_novos = 0
        ris_atualizados = 0
        ris_ja_no_status_correto = 0
        itens_criados = 0
        avisos_gerais = []  # [(inep, aviso), ...]

        with transaction.atomic():
            linhas = planilha_aba.iter_rows(min_row=linha_cabecalho + 1, values_only=True)
            for numero_linha, linha in enumerate(linhas, start=linha_cabecalho + 1):
                inep_bruto = linha[indice_coluna["INEP"]]
                if inep_bruto in (None, ""):
                    continue  # linha em branco (rodape da planilha)

                try:
                    inep = str(int(inep_bruto)).zfill(8)
                except (TypeError, ValueError):
                    self.stderr.write(self.style.WARNING(
                        f"Linha {numero_linha}: INEP invalido ({inep_bruto!r}) - ignorada."
                    ))
                    ignoradas_invalidas += 1
                    continue
                if len(inep) != 8:
                    self.stderr.write(self.style.WARNING(
                        f"Linha {numero_linha}: INEP com {len(inep)} digito(s) ({inep}) - ignorada."
                    ))
                    ignoradas_invalidas += 1
                    continue
                if inep in vistos:
                    continue  # mesmo INEP repetido no arquivo - so a 1a linha conta
                vistos.add(inep)

                status = _texto(linha[indice_coluna["STATUS"]]).upper()
                if status != "ATIVO":
                    ignoradas_nao_ativo += 1
                    continue

                escola = Escola.objects.filter(inep=inep).first()
                escola_e_nova = escola is None
                if escola_e_nova:
                    escola = Escola(
                        inep=inep,
                        nome=_texto(linha[indice_coluna["UNIDADE ESCOLAR"]]),
                        endereco=_texto(linha[indice_coluna["ENDEREÇO UNIDADE ESCOLAR"]]),
                        lote=_inteiro(linha[indice_coluna["LOTE"]]),
                        estado=_texto(linha[indice_coluna["UF"]]).upper(),
                        municipio=_texto(linha[indice_coluna["MUNICIPIO"]]),
                        kit_inicial=_texto(linha[indice_coluna["KIT WIFI ESTIMADO"]]),
                        velocidade_dl_minima=_texto(linha[indice_coluna["VELOCIDADE"]]),
                    )

                ri = None if escola_e_nova else Ri.objects.filter(escola=escola).first()
                ri_e_novo = ri is None
                if not ri_e_novo and not incluir_com_progresso:
                    intocado = (
                        ri.status == Ri.IMPLANTACAO_EACE
                        and ri.data_ativacao is None
                        and not ri.itens_ixc.exists()
                        and not ri.itens_eace.exists()
                        and not ri.itens_relatorio_eace.exists()
                    )
                    if not intocado:
                        ignoradas_com_progresso += 1
                        continue  # RI com progresso real - nunca sobrescrito por este comando

                itens_da_linha, avisos = _montar_itens_equipamento(escola, linha, indice_coluna)
                for aviso in avisos:
                    avisos_gerais.append((inep, aviso))

                # `--incluir-com-progresso`: nunca duplica dado já lançado
                # — só entra o que ainda não existe no Lado IXC deste RI
                # (KIT: no máximo 1 por RI, RN-015; Produto: por Descrição
                # exata). Em modo padrão (RI sempre 100% intocado aqui),
                # isto é sempre um no-op — não muda o comportamento já
                # validado.
                ja_tem_kit = bool(ri and ri.itens_ixc.filter(eh_kit=True).exists())
                descricoes_ja_lancadas = (
                    set(ri.itens_ixc.values_list("descricao_item", flat=True)) if ri else set()
                )
                itens = [
                    dados for dados in itens_da_linha
                    if not (dados["eh_kit"] and ja_tem_kit)
                    and not (not dados["eh_kit"] and dados["descricao_item"] in descricoes_ja_lancadas)
                ]

                if escola_e_nova:
                    escolas_novas += 1
                if ri_e_novo:
                    ris_novos += 1
                elif ri.status != Ri.AGUARDANDO_VALIDACAO_EACE:
                    ris_atualizados += 1
                else:
                    ris_ja_no_status_correto += 1
                itens_criados += len(itens)

                if not aplicar:
                    continue

                data_ativacao = _data(linha[indice_coluna["DATA DE ATIVAÇÃO"]])

                if escola_e_nova or not escola.legado:
                    escola.legado = True
                    escola.save()

                # RN-092 (2026-09-10): `Ri.save()` (models.py) já faz o
                # handoff pro MIP sozinho (`Escola.status_mip`) sempre que
                # o status gravado é "Aguardando validação EACE" — cobre
                # tanto a criação direta abaixo quanto a troca manual,
                # sem precisar repetir a lógica aqui.
                if ri_e_novo:
                    ri = Ri.objects.create(
                        escola=escola, status=Ri.AGUARDANDO_VALIDACAO_EACE, data_ativacao=data_ativacao,
                    )
                elif ri.status != Ri.AGUARDANDO_VALIDACAO_EACE:
                    ri.status = Ri.AGUARDANDO_VALIDACAO_EACE
                    # Data de Ativação só é gravada num RI novo — nunca
                    # sobrescreve uma já existente (RI com progresso real
                    # pode já ter a dela própria, verdadeira).
                    if ri.data_ativacao is None:
                        ri.data_ativacao = data_ativacao
                    ri.save()

                for dados_item in itens:
                    RiItemIxc.objects.create(ri=ri, **dados_item)

                if not ri.historico.filter(tipo=RiHistorico.MENSAGEM, mensagem=MENSAGEM_HISTORICO).exists():
                    RiHistorico.objects.create(ri=ri, tipo=RiHistorico.MENSAGEM, mensagem=MENSAGEM_HISTORICO)
                sincronizar_divergencia_kit_relatorio(ri)

            if not aplicar:
                transaction.set_rollback(True)

        self.stdout.write(
            f"INEPs 'ATIVO' elegiveis: {ris_novos + ris_atualizados + ris_ja_no_status_correto} "
            f"({ris_novos} RI novo(s), dos quais {escolas_novas} com Escola tambem nova; "
            f"{ris_atualizados} RI existente(s) com status alterado para Aguardando validacao EACE; "
            f"{ris_ja_no_status_correto} ja estavam nesse status, so item/legado conferidos)."
        )
        self.stdout.write(f"Itens de equipamento a lancar no Lado IXC (2o lado): {itens_criados}")
        self.stdout.write(
            f"Ignoradas: {ignoradas_invalidas} INEP invalido, {ignoradas_nao_ativo} sem STATUS=ATIVO, "
            f"{ignoradas_com_progresso} com RI ja em progresso real (nao mexido"
            f"{' - use --incluir-com-progresso' if ignoradas_com_progresso and not incluir_com_progresso else ''})."
        )
        if avisos_gerais:
            self.stdout.write(self.style.WARNING(f"Avisos ({len(avisos_gerais)}) - lancamento manual necessario:"))
            for inep, aviso in avisos_gerais[:30]:
                self.stdout.write(f"  - {inep}: {aviso}")
            if len(avisos_gerais) > 30:
                self.stdout.write(f"  ... e mais {len(avisos_gerais) - 30} aviso(s).")

        if not aplicar:
            self.stdout.write(self.style.WARNING(
                "Simulacao (nada foi gravado). Rode novamente com --aplicar para gravar."
            ))
            return

        self.stdout.write(self.style.SUCCESS("Importacao aplicada com sucesso."))

        if ris_novos == 0:
            return

        # Pedido do usuario (2026-09-10): sem isso, INEP novo fica com
        # `encontrado_relatorio_eace_mip=None` (sem bolinha nenhuma no grid
        # Projeto > MIP) ate alguem clicar "Sincronizar todos os INEPs" na
        # tela do MIP - roda a mesma sincronizacao aqui, pra ja entrar na
        # regra normal (verde/vermelha) igual a qualquer outro INEP.
        try:
            resultado_mip = sincronizar_relatorio_eace_mip_de_todas_as_escolas()
        except RelatorioEaceMipSincronizacaoError as erro:
            self.stdout.write(self.style.WARNING(
                f"Nao foi possivel sincronizar o Relatorio EACE (MIP) para atualizar a "
                f"bolinha dos INEPs legados: {erro}. Rode 'Sincronizar todos os INEPs' "
                f"manualmente (Administrador > Relatorio EACE (MIP)) quando houver planilha ativa."
            ))
        else:
            self.stdout.write(
                "Relatorio EACE (MIP) sincronizado para refletir a bolinha dos INEPs legados "
                f"({resultado_mip['escolas_atualizadas']} escola(s) com item atualizado)."
            )
