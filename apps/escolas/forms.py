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
    Só o arquivo — o período (Data inicial/Data final) deixou de ser
    exigido aqui (RN-069 alterada): usuário pediu para editar a data
    direto no card do Sincronizador, sem precisar reimportar o arquivo só
    por isso (`PlanilhaRelatorioEaceMipPeriodoForm`, abaixo)."""

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


_DATE_INPUT_ATTRS = {
    "type": "date",
    "class": (
        "w-full px-4 py-2.5 rounded-xl border border-gray-200 "
        "dark:border-gray-700 bg-white dark:bg-gray-800 text-sm "
        "font-semibold text-gray-800 dark:text-gray-100 "
        "focus:outline-none focus:ring-2 focus:ring-pv-yellow"
    ),
}


class PlanilhaRelatorioEaceMipPeriodoForm(forms.Form):
    """RN-073: período (Data inicial/Data final) do Relatório EACE (MIP)
    ativo — editado direto no card "Arquivo ativo" (Sincronizador), sem
    precisar de um novo upload (RN-069 alterada, pedido do usuário).
    Formato ISO (`%Y-%m-%d`) explícito no widget: é o formato que o
    input HTML `type="date"` exige para pré-preencher o valor atual —
    o formato padrão de `pt-br` (`dd/mm/aaaa`) não é reconhecido por ele."""

    data_inicial = forms.DateField(
        label="Data inicial",
        widget=forms.DateInput(format="%Y-%m-%d", attrs=_DATE_INPUT_ATTRS),
    )
    data_final = forms.DateField(
        label="Data final",
        widget=forms.DateInput(format="%Y-%m-%d", attrs=_DATE_INPUT_ATTRS),
    )

    def clean(self):
        cleaned = super().clean()
        data_inicial = cleaned.get("data_inicial")
        data_final = cleaned.get("data_final")
        if data_inicial and data_final and data_inicial > data_final:
            raise forms.ValidationError("A data inicial não pode ser depois da data final.")
        return cleaned
