import csv
import io
import re

from django import forms
from django.core.validators import validate_email
from django.db.models import F

from .models import KitPadrao, PlanilhaEace, Ri, RiHistorico, RiItemIxc, RiItemRelatorioEace

CAMPO_TEXTO = (
    "w-full px-4 py-3 bg-gray-50 dark:bg-gray-800 border-none rounded-xl outline-none "
    "focus:ring-2 focus:ring-amber-400 transition-all font-bold text-xs text-gray-800 dark:text-gray-100"
)

# RN-011 (2026-08-24): campo usado dentro de uma "linha" com fundo cinza
# (ex.: cada produto do bloco "+" do Lado IXC) — CAMPO_TEXTO tem o mesmo
# fundo cinza do card que o envolve nesses casos, então o campo fica sem
# contraste (usuário apontou com print: "sem separação visual"). Aqui o
# fundo inverte (branco/escuro) e ganha borda, mesmo padrão já usado no
# formulário de edição do item IXC (ri_detail.html).
CAMPO_TEXTO_LINHA = (
    "w-full px-4 py-3 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 "
    "rounded-xl outline-none focus:ring-2 focus:ring-amber-400 transition-all font-bold text-xs "
    "text-gray-800 dark:text-gray-100"
)

CAMPO_ARQUIVO = (
    # O botão e o texto nativos do input (ex.: "Choose File"/"No file
    # chosen") vêm do idioma do navegador e não podem ser trocados por CSS
    # (nem "content", nem o "lang" da página mudam esse texto). Por isso o
    # input fica oculto (mas acessível/navegável por teclado) e o gatilho
    # visível é um <label> com texto em português — ver _historico_panel.html.
    "sr-only"
)


class RiItemIxcForm(forms.ModelForm):
    """Edição de item já lançado do atendimento IXC (2º lado) — RN-011
    substitui o lançamento por Descrição livre (ver `RiItemIxcKitForm`/
    `RiItemIxcProdutoFormSet`), mas a edição de um item existente continua
    por aqui, sem mudança (fora do escopo pedido pelo usuário)."""

    class Meta:
        model = RiItemIxc
        fields = ["descricao_item", "quantidade", "valor_unitario"]
        widgets = {
            "descricao_item": forms.TextInput(
                attrs={"class": CAMPO_TEXTO, "placeholder": "Ex.: Kit Wi-Fi"}
            ),
            "quantidade": forms.NumberInput(attrs={"class": CAMPO_TEXTO, "min": 1}),
            "valor_unitario": forms.NumberInput(
                attrs={"class": CAMPO_TEXTO, "min": 0, "step": "0.01"}
            ),
        }


def _catalogo_ixc(escola, kit):
    """RN-011 (3ª correção, 2026-08-24): opções do Lado IXC vêm do
    catálogo `KitPadrao` importado da aba LPU do `CONSOLIDADO EACE.xlsx`
    (RN-010/FEAT-015). "KIT Instalado" (`kit=True`) mostra só as entradas
    cuja coluna Unidade é "Escola" (mesmo critério de
    `KitPadrao.kit_fechado_por_escola`/RN-010, que também aceita
    "Escola/Mês"); "Produtos" (`kit=False`) mostra as demais entradas
    (itens avulsos). Filtra também por `Escola.lote` quando ela tiver um
    valor definido; sem lote definido, mostra todo o catálogo daquele
    grupo (evita lista vazia).

    RN-018 (2026-08-26): mesmo catálogo reaproveitado pelo Lado Relatório
    EACE (`RiItemRelatorioEaceKitForm`/`RiItemRelatorioEaceProdutoForm`) —
    nome mantido por ser decisão técnica reversível e de baixo risco
    (CLAUDE.md §9).

    Ordenação (2026-08-27, ajuste do usuário): por `numero_access_points`
    crescente (KIT 1, 2, 4, 8...), não mais por `descricao` — ordem
    alfabética de texto colocava "16 Access Points" antes de "2 Access
    Points". Itens sem número extraído (avulsos: km, enlace, metro, par)
    vão para o final, por `descricao` entre si."""
    qs = KitPadrao.objects.all()
    qs = qs.filter(unidade__istartswith="escola") if kit else qs.exclude(unidade__istartswith="escola")
    if escola and escola.lote is not None:
        qs = qs.filter(lote=escola.lote)
    return qs.order_by(F("numero_access_points").asc(nulls_last=True), "descricao")


class _CatalogoIxcChoiceField(forms.ModelChoiceField):
    """RN-011 (2026-08-24): mostra `descricao_curta` no select — a
    Descrição completa da LPU é grande demais para uma lista (ex.:
    "Kit Cobertura Wi-Fi - 8 Access Points (serviços, materiais e
    equipamentos)" vira só "Kit Cobertura Wi-Fi - 8 Access Points")."""

    def label_from_instance(self, obj):
        return obj.descricao_curta or obj.descricao


class RiItemIxcKitForm(forms.Form):
    """RN-011: bloco "KIT Instalado" do Lado IXC — descrição escolhida no
    catálogo `KitPadrao` (LPU), não texto livre. Quantidade é sempre 1
    (kit fechado da escola, não é campo do formulário). Valor unitário
    (2026-08-24, ajuste do usuário): tirado do formulário — não é
    informação necessária agora; o item nasce com valor 0 e é corrigido
    depois editando o item (RiItemIxcForm, RN-004), se um dia precisar.

    RN-011 (2026-08-24 — opção "Outro"): quando o kit instalado é
    diferente de tudo que está no catálogo, a pessoa escolhe "Outro" e
    digita o número de Access Points; a descrição gravada segue o mesmo
    padrão de nome do catálogo ("Kit Cobertura Wi-Fi - N Access Points"),
    decisão do usuário.

    RN-011 (2026-08-24 — formulário único): o KIT não é mais obrigatório
    a cada submissão — o botão "Salvar" do Lado IXC é único para KIT,
    Produtos e Data Ativação juntos (usuário pediu para não ter dois
    botões de salvar no mesmo bloco); deixar o KIT em branco só significa
    que esta submissão não lança nenhum KIT novo."""

    OUTRO = "outro"

    kit = forms.ChoiceField(
        choices=[],
        label="KIT Instalado",
        required=False,
        widget=forms.Select(attrs={"class": CAMPO_TEXTO}),
    )
    kit_outro_numero = forms.IntegerField(
        label="Número de Access Points",
        required=False,
        min_value=1,
        widget=forms.NumberInput(attrs={"class": CAMPO_TEXTO, "min": 1}),
    )

    def __init__(self, *args, escola=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._catalogo = {
            str(item.pk): item for item in _catalogo_ixc(escola, kit=True)
        }
        self.fields["kit"].choices = (
            [("", "Selecione o kit instalado")]
            + [(pk, item.descricao_curta or item.descricao) for pk, item in self._catalogo.items()]
            + [(self.OUTRO, "Outro — kit não cadastrado")]
        )

    def clean(self):
        cleaned = super().clean()
        escolhido = cleaned.get("kit")
        if escolhido == self.OUTRO:
            if not cleaned.get("kit_outro_numero"):
                self.add_error(
                    "kit_outro_numero", "Informe o número de Access Points do kit instalado."
                )
        elif escolhido and escolhido not in self._catalogo:
            self.add_error("kit", "Selecione um kit válido.")
        return cleaned

    @property
    def tem_catalogo(self):
        """Usado pelo template para avisar quando não há nenhum KIT
        (Unidade "Escola") cadastrado para o Lote desta escola — "Outro"
        continua disponível mesmo assim, então isso não bloqueia o
        lançamento, só avisa."""
        return bool(self._catalogo)

    @property
    def kit_selecionado(self):
        """True quando esta submissão escolheu um KIT (catálogo ou
        "Outro") — só chamar depois de `is_valid()` ter passado."""
        return bool(self.cleaned_data.get("kit"))

    @property
    def descricao_selecionada(self):
        """Descrição a gravar no `RiItemIxc` — só chamar quando
        `kit_selecionado` for True. Usa a Descrição curta (RN-011), sem o
        qualificador entre parênteses do catálogo — mesmo texto já
        mostrado no select; a Descrição completa é só a fonte da planilha
        (`KitPadrao.descricao`), não o que aparece na tela."""
        escolhido = self.cleaned_data["kit"]
        if escolhido == self.OUTRO:
            numero = self.cleaned_data["kit_outro_numero"]
            return f"Kit Cobertura Wi-Fi - {numero} Access Points"
        item = self._catalogo[escolhido]
        return item.descricao_curta or item.descricao


class RiItemIxcProdutoForm(forms.Form):
    """RN-011: cada linha individual do Lado IXC, lançada pelo botão "+" —
    "Produto" escolhido no mesmo catálogo `KitPadrao` do KIT Instalado;
    Quantidade digitada manualmente. Valor unitário (2026-08-24, ajuste do
    usuário): tirado do formulário — não é informação necessária agora; o
    item nasce com valor 0 e é corrigido depois editando o item
    (RiItemIxcForm, RN-004), se um dia precisar."""

    produto = _CatalogoIxcChoiceField(
        queryset=KitPadrao.objects.none(),
        label="Produto",
        empty_label="Selecione o produto",
        widget=forms.Select(attrs={"class": CAMPO_TEXTO_LINHA}),
    )
    quantidade = forms.IntegerField(
        label="Quantidade",
        min_value=1,
        widget=forms.NumberInput(attrs={"class": CAMPO_TEXTO_LINHA, "min": 1}),
    )

    def __init__(self, *args, escola=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["produto"].queryset = _catalogo_ixc(escola, kit=False)


# RN-011: "+" do Lado IXC — nasce sem nenhuma linha visível (extra=0); cada
# clique no "+" (JS, ver ri_detail.html) adiciona uma linha incrementando o
# management form. Permite lançar 0 ou mais produtos numa única submissão.
RiItemIxcProdutoFormSet = forms.formset_factory(RiItemIxcProdutoForm, extra=0, can_delete=False)


class RiDataAtivacaoForm(forms.ModelForm):
    """RN-011 (2026-08-24): "Data Ativação" — um valor só por RI (não por
    item), exibido e editado no bloco "Produtos" do Lado IXC. Salva junto
    com o lançamento de produtos, mesmo quando nenhum produto é lançado
    na mesma submissão.

    RN-014 (2026-08-26): mesmo formulário ganha Município/Estado do Lado
    IXC — preenchimento manual, usado na planilha de faturamento
    (RN-013); nome da classe mantido por ser decisão técnica reversível e
    de baixo risco (CLAUDE.md §9).

    RN-014 (2026-08-26; revista no mesmo dia): Município/Estado ganham o
    campo, mas continuam OPCIONAIS aqui — não travam o "Salvar" do Lado
    IXC. Chegou a existir uma versão que travava aqui (e o KIT/Data de
    Ativação quase ganharam a mesma trava), mas o usuário esclareceu que a
    exigência é só na hora de enviar o e-mail/baixar a planilha para o
    financeiro, não a cada "Salvar" do Lado IXC — do contrário, lançar só
    um Produto novo depois do KIT já lançado ficaria bloqueado por um
    campo sem relação nenhuma com aquela ação. Ver RN-013/`services.py`
    (`gerar_planilha_faturamento`), onde a exigência de fato mora.

    RN-048 (2026-09-01): mesmo formulário ganha CNPJ/CNPJ Fictício, mesmo
    padrão opcional aqui — mesma exigência só na hora de gerar a planilha."""

    class Meta:
        model = Ri
        fields = ["data_ativacao", "municipio_ixc", "estado_ixc", "cnpj", "cnpj_ficticio"]
        widgets = {
            "data_ativacao": forms.DateInput(
                attrs={"class": CAMPO_TEXTO, "type": "date"}, format="%Y-%m-%d"
            ),
            "municipio_ixc": forms.TextInput(
                attrs={"class": CAMPO_TEXTO, "placeholder": "Ex.: Fortaleza"}
            ),
            "estado_ixc": forms.TextInput(
                attrs={"class": CAMPO_TEXTO, "placeholder": "Ex.: CE", "maxlength": 2}
            ),
            # RN-048: mesmo padrão opcional de município/estado — texto
            # livre, sem validação de dígito verificador (não pedido pelo
            # usuário); "obrigatório" é só na hora de gerar a planilha/
            # enviar o e-mail (RN-013, `gerar_planilha_faturamento`).
            "cnpj": forms.TextInput(
                attrs={"class": CAMPO_TEXTO, "placeholder": "Ex.: 00.000.000/0000-00"}
            ),
            "cnpj_ficticio": forms.TextInput(
                attrs={"class": CAMPO_TEXTO, "placeholder": "Ex.: 00.000.000/0000-00"}
            ),
        }

    def clean_cnpj(self):
        return (self.cleaned_data.get("cnpj") or "").strip()

    def clean_cnpj_ficticio(self):
        return (self.cleaned_data.get("cnpj_ficticio") or "").strip()

    def clean_estado_ixc(self):
        # RN-014: sempre 2 letras (UF), maiúsculas — mesmo padrão de
        # Escola.estado, para a comparação de divergência não acusar falso
        # positivo só por causa de caixa. Formato errado continua sendo
        # rejeitado aqui mesmo com o campo opcional — só valor vazio passa.
        valor = (self.cleaned_data.get("estado_ixc") or "").strip().upper()
        if valor and (len(valor) != 2 or not valor.isalpha()):
            raise forms.ValidationError("Informe a UF com 2 letras (ex.: CE).")
        return valor

    def clean_municipio_ixc(self):
        return (self.cleaned_data.get("municipio_ixc") or "").strip()


class RiHistoricoForm(forms.ModelForm):
    """FEAT-014/RN-008: usuário escreve uma mensagem, anexa um arquivo, ou
    os dois juntos — pelo menos um dos dois é obrigatório. O tipo
    (mensagem ou anexo isolado) é decidido na view a partir do que foi
    preenchido."""

    class Meta:
        model = RiHistorico
        fields = ["mensagem", "anexo"]
        widgets = {
            "mensagem": forms.Textarea(
                attrs={
                    "class": CAMPO_TEXTO + " resize-none",
                    "placeholder": "Escreva uma mensagem...",
                    "rows": 3,
                }
            ),
            "anexo": forms.ClearableFileInput(
                attrs={
                    "class": CAMPO_ARQUIVO,
                    # Mostra o nome do arquivo escolhido no <span> ao lado do
                    # botão em português (o rótulo do input é oculto — ver
                    # comentário de CAMPO_ARQUIVO acima).
                    "onchange": (
                        "document.getElementById('historico-anexo-nome').textContent = "
                        "this.files.length ? this.files[0].name : 'Nenhum arquivo selecionado';"
                    ),
                }
            ),
        }

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("mensagem") and not cleaned.get("anexo"):
            raise forms.ValidationError("Escreva uma mensagem ou anexe um arquivo.")
        return cleaned


def _limpar_lista_emails(valor, obrigatorio):
    """Aceita e-mails separados por vírgula ou ponto e vírgula — usada pelos
    campos Para/Cc da tela de composição de e-mail (FEAT-008)."""
    enderecos = [endereco.strip() for endereco in re.split(r"[,;]", valor or "") if endereco.strip()]
    if obrigatorio and not enderecos:
        raise forms.ValidationError("Informe ao menos um destinatário.")
    for endereco in enderecos:
        validate_email(endereco)
    return enderecos


class RiEmailFinanceiroForm(forms.Form):
    """FEAT-008/RF-16-18: tela de composição do e-mail ao financeiro,
    aberta a partir do botão único do grid. "De" é automático (remetente
    do sistema) e não faz parte deste form. Para/Cc/Assunto chegam
    pré-preenchidos no template, mas o usuário pode editá-los antes de
    enviar. "Anexo" aqui é só o arquivo adicional — o PDF com os itens do
    lado IXC continua gerado e anexado automaticamente (RN-008), à parte
    deste form. "Mensagem" substitui o antigo campo único "Observação"."""

    para = forms.CharField(label="Para")
    cc = forms.CharField(label="Cc", required=False)
    assunto = forms.CharField(label="Assunto", max_length=255)
    mensagem = forms.CharField(label="Mensagem", required=False, widget=forms.Textarea)
    anexo_extra = forms.FileField(label="Anexo", required=False)

    def clean_para(self):
        return _limpar_lista_emails(self.cleaned_data.get("para"), obrigatorio=True)

    def clean_cc(self):
        return _limpar_lista_emails(self.cleaned_data.get("cc"), obrigatorio=False)


class RiItemRelatorioEaceForm(forms.ModelForm):
    """FEAT-004 (3º lado, 2026-08-22): usada para lançamento livre até a
    RN-018 (2026-08-26) substituir o lançamento novo pelo mesmo mecanismo
    de catálogo do Lado IXC (`RiItemRelatorioEaceKitForm`/
    `RiItemRelatorioEaceProdutoFormSet`). Continua em uso só para a edição
    do item marcado como KIT (`ri_item_relatorio_eace_update`) — exceção
    pontual à imutabilidade da RN-003, mesmo padrão de `RiItemIxcForm`."""

    class Meta:
        model = RiItemRelatorioEace
        fields = ["descricao_item", "quantidade", "valor_unitario"]
        widgets = {
            "descricao_item": forms.TextInput(
                attrs={"class": CAMPO_TEXTO, "placeholder": "Ex.: Kit Wi-Fi"}
            ),
            "quantidade": forms.NumberInput(attrs={"class": CAMPO_TEXTO, "min": 1}),
            "valor_unitario": forms.NumberInput(
                attrs={"class": CAMPO_TEXTO, "min": 0, "step": "0.01"}
            ),
        }


class RiItemRelatorioEaceKitForm(forms.Form):
    """RN-018 (2026-08-26): bloco "KIT Instalado" do Lado Relatório EACE —
    mesmo mecanismo do Lado IXC (`RiItemIxcKitForm`/RN-011), mesmo
    catálogo `_catalogo_ixc` (`KitPadrao`, Unidade "Escola"/"Escola-Mês",
    filtrado por Lote). Diferença: Valor Unitário deste lado não nasce
    0,00 — a view lê o preço direto da instância escolhida do catálogo
    (`instancia_selecionada`), porque aqui a informação tem uso real
    (confronto RN-003), diferente do Lado IXC (RN-011). Para a opção
    "Outro" (sem instância — kit fora do catálogo), a view cai de volta
    para a mesma resolução por número de Access Points já usada na
    planilha de faturamento (`_resolver_catalogo_ixc`, RN-013)."""

    OUTRO = "outro"

    kit = forms.ChoiceField(
        choices=[],
        label="KIT Instalado",
        required=False,
        widget=forms.Select(attrs={"class": CAMPO_TEXTO}),
    )
    kit_outro_numero = forms.IntegerField(
        label="Número de Access Points",
        required=False,
        min_value=1,
        widget=forms.NumberInput(attrs={"class": CAMPO_TEXTO, "min": 1}),
    )

    def __init__(self, *args, escola=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._catalogo = {
            str(item.pk): item for item in _catalogo_ixc(escola, kit=True)
        }
        self.fields["kit"].choices = (
            [("", "Selecione o kit instalado")]
            + [(pk, item.descricao_curta or item.descricao) for pk, item in self._catalogo.items()]
            + [(self.OUTRO, "Outro — kit não cadastrado")]
        )

    def clean(self):
        cleaned = super().clean()
        escolhido = cleaned.get("kit")
        if escolhido == self.OUTRO:
            if not cleaned.get("kit_outro_numero"):
                self.add_error(
                    "kit_outro_numero", "Informe o número de Access Points do kit instalado."
                )
        elif escolhido and escolhido not in self._catalogo:
            self.add_error("kit", "Selecione um kit válido.")
        return cleaned

    @property
    def tem_catalogo(self):
        """Usado pelo template para avisar quando não há nenhum KIT
        (Unidade "Escola") cadastrado para o Lote desta escola — "Outro"
        continua disponível mesmo assim, então isso não bloqueia o
        lançamento, só avisa."""
        return bool(self._catalogo)

    @property
    def kit_selecionado(self):
        """True quando esta submissão escolheu um KIT (catálogo ou
        "Outro") — só chamar depois de `is_valid()` ter passado."""
        return bool(self.cleaned_data.get("kit"))

    @property
    def descricao_selecionada(self):
        """Descrição a gravar no `RiItemRelatorioEace` — só chamar quando
        `kit_selecionado` for True. Mesma regra do Lado IXC: Descrição
        curta, sem o qualificador entre parênteses do catálogo."""
        escolhido = self.cleaned_data["kit"]
        if escolhido == self.OUTRO:
            numero = self.cleaned_data["kit_outro_numero"]
            return f"Kit Cobertura Wi-Fi - {numero} Access Points"
        item = self._catalogo[escolhido]
        return item.descricao_curta or item.descricao

    @property
    def instancia_selecionada(self):
        """`KitPadrao` escolhido no catálogo — `None` para a opção "Outro"
        (kit fora do catálogo, sem instância). Usada pela view para ler o
        Valor Unitário direto (`instancia.valor_faturavel`), sem precisar
        resolver de novo por descrição/número de Access Points."""
        escolhido = self.cleaned_data["kit"]
        return self._catalogo.get(escolhido)


class RiItemRelatorioEaceProdutoForm(forms.Form):
    """RN-018: cada linha individual do Lado Relatório EACE, lançada pelo
    botão "+" — mesmo mecanismo do Lado IXC (`RiItemIxcProdutoForm`/
    RN-011), mesmo catálogo `_catalogo_ixc`. Valor Unitário resolvido do
    catálogo na view, não digitado (mesma diferença do KIT acima)."""

    produto = _CatalogoIxcChoiceField(
        queryset=KitPadrao.objects.none(),
        label="Produto",
        empty_label="Selecione o produto",
        widget=forms.Select(attrs={"class": CAMPO_TEXTO_LINHA}),
    )
    quantidade = forms.IntegerField(
        label="Quantidade",
        min_value=1,
        widget=forms.NumberInput(attrs={"class": CAMPO_TEXTO_LINHA, "min": 1}),
    )

    def __init__(self, *args, escola=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["produto"].queryset = _catalogo_ixc(escola, kit=False)


# RN-018: "+" do Lado Relatório EACE — mesmo padrão do Lado IXC (RN-011):
# nasce sem nenhuma linha visível (extra=0), cada clique no "+" adiciona
# uma linha incrementando o management form.
RiItemRelatorioEaceProdutoFormSet = forms.formset_factory(
    RiItemRelatorioEaceProdutoForm, extra=0, can_delete=False
)


class PlanilhaEaceUploadForm(forms.Form):
    """RN-021: upload da Planilha EACE (tela "Administrador > Planilha
    EACE", FEAT-023). Valida extensão e colunas mínimas antes de aceitar —
    arquivo inválido não é gravado."""

    arquivo = forms.FileField(
        label="Arquivo (.csv)",
        widget=forms.ClearableFileInput(attrs={
            # Input nativo fica só visualmente escondido (sr-only) — o
            # rótulo "CHOOSE FILE"/"No file chosen" do navegador não dá
            # para traduzir por CSS; a tela usa um botão + texto próprios
            # (ri/planilha_eace.html), o input continua acessível pelo
            # <label for=...> e pelo teclado.
            "class": "sr-only",
            "accept": ".csv",
        }),
    )

    def clean_arquivo(self):
        arquivo = self.cleaned_data["arquivo"]
        if not arquivo.name.lower().endswith(".csv"):
            raise forms.ValidationError("Envie um arquivo .csv.")
        try:
            texto = arquivo.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            raise forms.ValidationError(
                "Não foi possível ler o arquivo — verifique se a codificação é UTF-8."
            )
        finally:
            arquivo.seek(0)
        cabecalho = next(csv.reader(io.StringIO(texto), delimiter=";"), None)
        if not cabecalho:
            raise forms.ValidationError("Arquivo vazio.")
        colunas = {coluna.strip() for coluna in cabecalho}
        faltando = [
            coluna for coluna in PlanilhaEace.COLUNAS_OBRIGATORIAS if coluna not in colunas
        ]
        if faltando:
            raise forms.ValidationError(
                f"Colunas obrigatórias ausentes: {', '.join(faltando)}."
            )
        return arquivo
