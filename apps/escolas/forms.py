from django import forms

try:
    import openpyxl
except ImportError:
    openpyxl = None

from .models import PlanilhaRelatorioEaceMip
from .services import aba_relatorio_eace_mip_com_colunas


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
