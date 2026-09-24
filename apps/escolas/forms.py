# import re  # só usado por `_limpar_lista_emails_lote` — e-mail do LOTE comentado (pedido do usuário, 2026-09-15)
import zipfile

from django import forms
# from django.core.validators import validate_email  # idem acima

try:
    import openpyxl
except ImportError:
    openpyxl = None

# `rarfile` (pedido do usuário, 2026-09-24: sistema precisa aceitar
# também .rar, não só .zip) — mesmo padrão de import opcional do
# `openpyxl` acima: `None` quando a lib não está instalada, tratado como
# erro de validação (não erro 500) em `_validar_zip_ou_rar`.
try:
    import rarfile
except ImportError:
    rarfile = None

from .models import PlanilhaRelatorioEaceMip
from .services import aba_relatorio_eace_mip_com_colunas, contar_notas_fiscais_rar, contar_notas_fiscais_zip


def _validar_zip_ou_rar(arquivo):
    """Validação compartilhada por `LoteNotasFiscaisZipUploadForm` e
    `NotasFiscaisMipUploadForm` (pedido do usuário, 2026-09-24: aceitar
    .rar além de .zip) — extensão + conteúdo de verdade (`zipfile.
    is_zipfile`/`rarfile.is_rarfile`). Levanta `forms.ValidationError`;
    quem chama decide se ainda precisa contar as Notas Fiscais depois."""
    nome = arquivo.name.lower()
    if nome.endswith(".zip"):
        if not zipfile.is_zipfile(arquivo):
            raise forms.ValidationError("Não foi possível ler o arquivo — verifique se é um .zip válido.")
        arquivo.seek(0)
        return
    if nome.endswith(".rar"):
        if rarfile is None:
            raise forms.ValidationError("Dependência 'rarfile' não instalada no servidor.")
        if not rarfile.is_rarfile(arquivo):
            raise forms.ValidationError("Não foi possível ler o arquivo — verifique se é um .rar válido.")
        arquivo.seek(0)
        return
    raise forms.ValidationError("Envie um arquivo .zip ou .rar.")


class LoteNotasFiscaisZipUploadForm(forms.Form):
    """Pedido do usuário (2026-09-17): upload do .zip/.rar de Notas
    Fiscais que o financeiro devolve para todo o LOTE de uma vez, tela
    "Projeto > MIP (LOTE)" — 1 arquivo por LOTE, substituível (`Lote.
    substituir_notas_fiscais_zip`). Validação leve (`_validar_zip_ou_rar`
    — extensão + `zipfile.is_zipfile`/`rarfile.is_rarfile`), sem exigir
    nenhum conteúdo/estrutura interna do arquivo — diferente da Planilha
    EACE (MIP), aqui o sistema só guarda o arquivo para download, não lê
    nada de dentro dele."""

    arquivo = forms.FileField(
        label="Notas Fiscais (.zip/.rar)",
        widget=forms.ClearableFileInput(attrs={"class": "sr-only", "accept": ".zip,.rar"}),
    )

    def clean_arquivo(self):
        arquivo = self.cleaned_data["arquivo"]
        _validar_zip_ou_rar(arquivo)
        return arquivo


class NotasFiscaisMipUploadForm(forms.Form):
    """RN-XXX (a formalizar pelo Orquestrador em business_rules.md; pedido
    do usuário, 2026-09-24): upload avulso do .zip/.rar de Notas Fiscais
    do MIP na tela "Administrador > Relatório EACE (MIP)" — 1 arquivo por
    vez, substituível (`NotasFiscaisMip.substituir`). Mesma validação leve
    de `LoteNotasFiscaisZipUploadForm` (`_validar_zip_ou_rar`); a única
    leitura feita aqui é contar quantos .pdf existem dentro do arquivo
    (`apps.escolas.services.contar_notas_fiscais_zip`/
    `contar_notas_fiscais_rar`, conforme a extensão), pra mostrar a
    quantidade de Notas Fiscais lidas depois do upload — nenhum conteúdo
    de PDF é aberto."""

    arquivo = forms.FileField(
        label="Notas Fiscais (.zip/.rar)",
        widget=forms.ClearableFileInput(attrs={"class": "sr-only", "accept": ".zip,.rar"}),
    )

    def clean_arquivo(self):
        arquivo = self.cleaned_data["arquivo"]
        _validar_zip_ou_rar(arquivo)
        nome = arquivo.name.lower()
        if nome.endswith(".zip"):
            quantidade = contar_notas_fiscais_zip(arquivo)
        else:
            quantidade = contar_notas_fiscais_rar(arquivo)
        self.cleaned_data["quantidade_notas_fiscais"] = quantidade
        return arquivo


class PlanilhaRelatorioEaceMipUploadForm(forms.Form):
    """FEAT-034/FEAT-035: upload da planilha de origem do Lado 3
    (Relatório EACE) do MIP, tela "Administrador > Relatório EACE (MIP)".
    Fonte real: "Base MIP.xlsx" — exige que alguma aba do arquivo tenha as
    colunas de `PlanilhaRelatorioEaceMip.COLUNAS_OBRIGATORIAS` na 1ª linha
    (não fixa o nome da aba — o arquivo real usa uma aba de nome interno,
    "_Base contrato_taxa_instalação", que pode variar entre exportações).
    Só o arquivo — sem período (Data inicial/Data final): a tela deixou
    de pedir/editar essa data (RN-090, revoga a edição de período trazida
    pela RN-069/RN-073 — usuário pediu para tirar as datas da tela de
    importar/sincronizar). O modelo continua com os campos
    `data_inicial`/`data_final` só porque o card "No período" do Grid do
    MIP ainda os lê (RN-073, mantido como está por pedido do usuário);
    eles simplesmente não são mais preenchidos por nenhuma tela."""

    arquivo = forms.FileField(
        label="Arquivo (.xlsx)",
        widget=forms.ClearableFileInput(attrs={
            # Input nativo fica só visualmente escondido (sr-only) — o
            # rótulo "CHOOSE FILE"/"No file chosen" do navegador não dá
            # para traduzir por CSS; a tela usa um botão + texto próprios
            # (escolas/relatorio_eace_mip.html), o input continua
            # acessível pelo <label for=...> e pelo teclado.
            "class": "sr-only",
            "accept": ".xlsx",
        }),
    )

    def clean_arquivo(self):
        arquivo = self.cleaned_data["arquivo"]
        if not arquivo.name.lower().endswith(".xlsx"):
            raise forms.ValidationError("Envie um arquivo .xlsx.")
        if openpyxl is None:
            raise forms.ValidationError("Dependência 'openpyxl' não instalada no servidor.")

        try:
            planilha = openpyxl.load_workbook(arquivo, read_only=True, data_only=True)
        except Exception:
            raise forms.ValidationError(
                "Não foi possível ler o arquivo — verifique se é um .xlsx válido."
            )

        try:
            aba_com_colunas = aba_relatorio_eace_mip_com_colunas(planilha)
        finally:
            planilha.close()
            arquivo.seek(0)

        if aba_com_colunas is None:
            raise forms.ValidationError(
                "Nenhuma aba do arquivo tem as colunas obrigatórias: "
                + ", ".join(PlanilhaRelatorioEaceMip.COLUNAS_OBRIGATORIAS) + "."
            )
        return arquivo


# Pedido do usuário (2026-09-15): envio de e-mail do LOTE comentado (não
# será usado por enquanto) — `_limpar_lista_emails_lote`/`LoteEmailForm`
# mantidos comentados (não apagados) para reativação futura.
#
# def _limpar_lista_emails_lote(valor):
    # """Mesmo padrão de `apps.ri.forms._limpar_lista_emails` (FEAT-008) —
    # duplicada aqui (função pequena, evita importar símbolo privado de
    # outro módulo, mesmo critério já usado por `apps.escolas.views.
    # _registrar_log_campo_mip`) para o campo "Para" do e-mail do LOTE
    # (FEAT-045). Diferença do RI: nunca obrigatório aqui — pedido explícito
    # do usuário ("o PARA pode deixar em branco")."""
    # enderecos = [endereco.strip() for endereco in re.split(r"[,;]", valor or "") if endereco.strip()]
    # for endereco in enderecos:
        # validate_email(endereco)
    # return enderecos


# class LoteEmailForm(forms.Form):
    # """FEAT-045 (a formalizar pelo Orquestrador em business_rules.md;
    # pedido do usuário, 2026-09-14): composição do e-mail do LOTE — mesmo
    # padrão da tela de e-mail do RI (`apps.ri.forms.RiEmailFinanceiroForm`,
    # FEAT-008), com as diferenças pedidas pelo usuário: "De" é automático
    # (não entra neste form, igual ao RI); "Para" é OPCIONAL aqui (no RI é
    # obrigatório); sem "Cc" (não pedido para o LOTE); "anexo_extra" é
    # opcional — mesmo nome/papel do `RiEmailFinanceiroForm.anexo_extra`: o
    # anexo OFICIAL (planilha de faturamento de implantação por Município,
    # `apps.escolas.services.gerar_planilha_faturamento_implantacao_lote`) é
    # sempre gerado e anexado automaticamente por `enviar_email_lote`; este
    # campo só serve para somar mais um arquivo ao e-mail."""

    # para = forms.CharField(label="Para", required=False)
    # assunto = forms.CharField(label="Assunto", max_length=255)
    # mensagem = forms.CharField(label="Mensagem", required=False, widget=forms.Textarea)
    # anexo_extra = forms.FileField(label="Anexo extra", required=False)

    # def clean_para(self):
        # return _limpar_lista_emails_lote(self.cleaned_data.get("para"))
