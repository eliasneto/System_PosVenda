"""Upload das planilhas das Automações IXC — mesmo padrão de validação de
`.xlsx` usado em `apps.escolas.forms.PlanilhaRelatorioEaceMipUploadForm`
(extensão + colunas obrigatórias na 1ª linha da 1ª aba)."""

import openpyxl
from django import forms

from . import services


class _PlanilhaIxcUploadForm(forms.Form):
    arquivo = forms.FileField(
        label="Arquivo (.xlsx)",
        widget=forms.ClearableFileInput(attrs={"class": "sr-only", "accept": ".xlsx"}),
    )

    # Sobrescrito pelas subclasses.
    colunas_obrigatorias = ()

    def clean_arquivo(self):
        arquivo = self.cleaned_data["arquivo"]
        if not arquivo.name.lower().endswith(".xlsx"):
            raise forms.ValidationError("Envie um arquivo .xlsx.")

        try:
            workbook = openpyxl.load_workbook(arquivo, read_only=True, data_only=True)
        except Exception:
            raise forms.ValidationError(
                "Não foi possível ler o arquivo — verifique se é um .xlsx válido."
            )

        try:
            faltando = [
                coluna for coluna in self.colunas_obrigatorias
                if coluna not in services.colunas_presentes(workbook)
            ]
        finally:
            workbook.close()
            arquivo.seek(0)

        if faltando:
            raise forms.ValidationError(
                "Colunas obrigatórias ausentes: " + ", ".join(faltando) + "."
            )
        return arquivo


class PlanilhaIxcLoginEnderecosUploadForm(_PlanilhaIxcUploadForm):
    colunas_obrigatorias = services.COLUNAS_OBRIGATORIAS_LOGIN_ENDERECOS


class PlanilhaIxcAtendimentosUploadForm(_PlanilhaIxcUploadForm):
    """RN a formalizar (regra "tudo ou nada", README trazido em
    2026-09-23): além das colunas obrigatórias, TODAS as linhas precisam
    passar em `validar_tipo_processo` — 1 linha inválida rejeita a
    planilha inteira, nenhuma é enviada ao IXC."""

    colunas_obrigatorias = services.COLUNAS_OBRIGATORIAS_ATENDIMENTOS

    def clean_arquivo(self):
        arquivo = super().clean_arquivo()

        workbook = openpyxl.load_workbook(arquivo, read_only=True, data_only=True)
        try:
            erros = services.validar_tudo_ou_nada_atendimentos(workbook)
        finally:
            workbook.close()
            arquivo.seek(0)

        if erros:
            raise forms.ValidationError(
                ["Corrija a planilha antes de enviar (nenhuma linha foi enviada ao IXC):"] + erros
            )
        return arquivo
