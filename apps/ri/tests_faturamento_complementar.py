"""Faturamento complementar (pedido do usuário, 2026-11-12, v1.6.0): NFs a
mais para um INEP já faturado, com planilha e e-mail próprios
(`RI-AAAAMMDD-INEP-C<n>`), que não mudam o 2º/3º lado nem o status do RI/MIP
e cuja resposta abre só os logs de RPA das NFs do complementar."""
import shutil
import tempfile
from datetime import date, datetime
from email.message import EmailMessage as MensagemEmailMime
from io import BytesIO
from unittest.mock import patch

import openpyxl
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.email_tracking import (
    PADRAO_CODIGO,
    extrair_codigo_complementar,
    extrair_primeiro_inep_rastreio,
    montar_codigo_rastreio,
)
from apps.escolas.models import Escola
from apps.integracoes.eace.rpa import ResultadoRpaEace

from .models import (
    Documento,
    EmailFinanceiroLog,
    FaturamentoComplementar,
    KitPadrao,
    LogRpaEace,
    NfCanceladaFinanceiro,
    Ri,
    RiHistorico,
    RiItemIxc,
    RiItemRelatorioEace,
)
from .services import (
    _documentos_nf_do_ultimo_email_financeiro,
    _processar_mensagem,
    executar_log_rpa_eace,
    notas_fiscais_vigentes_do_financeiro,
    rpa_eace_concluida,
)
from .views import _contexto_logs_rpa_eace

User = get_user_model()
_MEDIA_ROOT = tempfile.mkdtemp()
INEP = "70000001"
EXTRAIR_PDF = "apps.integracoes.eace.extrair_dados_pdf.extrair_dados_nota_fiscal"


def _email_bytes(assunto, anexos, remetente="financeiro@speedcsc.com.br"):
    mensagem = MensagemEmailMime()
    mensagem["Subject"] = assunto
    mensagem["From"] = remetente
    mensagem["To"] = "posvendas@megainfraestrutura.com.br"
    mensagem.set_content("Segue em anexo.")
    for nome, payload in anexos:
        principal, sub = ("application", "pdf") if nome.endswith(".pdf") else ("application", "xml")
        mensagem.add_attachment(payload, maintype=principal, subtype=sub, filename=nome)
    return mensagem.as_bytes()


def _xml_nf(numero, valor, item_lpu):
    return (
        f"<nfeProc><NFe><infNFe><ide><nNF>{numero}</nNF></ide>"
        f"<total><ICMSTot><vNF>{valor}</vNF></ICMSTot></total>"
        f"<pag><detPag><tPag>18</tPag></detPag></pag>"
        f"<infAdic><infCpl>INEP: {INEP} ITEM LPU: {item_lpu} MUNICIPIO/UF: Recife/PE VENCIMENTO: 10/12/2026"
        f"</infCpl></infAdic></infNFe></NFe>"
        f"<protNFe><infProt><dhRecbto>2026-11-10T10:00:00-03:00</dhRecbto></infProt></protNFe></nfeProc>"
    ).encode()


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class BaseComplementar(TestCase):

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.escola = Escola.objects.create(
            inep=INEP, nome="Escola Complementar", lote=9, endereco="Rua A, 1", municipio="Recife", estado="PE",
        )
        self.kit = KitPadrao.objects.create(
            descricao="Kit Cobertura Wi-Fi - 4 Access Points (serviços, materiais e equipamentos)",
            unidade="Escola", lote=9, valor_equipamento="1000.00", valor_servico="50.00",
        )
        self.nobreak = KitPadrao.objects.create(
            descricao="Nobreak (serviço, material, equipamento)", unidade="Unidade", lote=9,
            valor_equipamento="300.00",
        )
        self.so_servico = KitPadrao.objects.create(
            descricao="Manutenção de Rede Interna", unidade="Unidade", lote=9, valor_servico="80.00",
        )
        self.ri = self._criar_ri(Ri.ANDAMENTO)
        self.admin = User.objects.create_user("admin-compl", password="x", perfil=User.PERFIL_ADMINISTRADOR)
        self.analista = User.objects.create_user("analista-compl", password="x", perfil=User.PERFIL_ANALISTA)
        self.visualizador = User.objects.create_user("visu-compl", password="x", perfil=User.PERFIL_VISUALIZADOR)

    def _criar_ri(self, status):
        ri = Ri.objects.create(
            escola=self.escola, status=status, data_ativacao=date(2026, 10, 1), municipio_ixc="Recife",
            estado_ixc="PE", cnpj="00.000.000/0001-00", cnpj_ficticio="11.111.111/0001-11", mes_operacao_ixc=11,
        )
        RiItemRelatorioEace.objects.create(
            ri=ri, descricao_item="Kit Cobertura Wi-Fi - 4 Access Points", quantidade=1,
            valor_unitario="1000.00", eh_kit=True, num_osp="1001",
        )
        RiItemRelatorioEace.objects.create(
            ri=ri, descricao_item="Nobreak", quantidade=1, valor_unitario="300.00", num_osp="1002",
        )
        return ri

    def _encerrar(self):
        """INEP em "Processo Concluído" (MIP) - só Administrador mexe."""
        self.ri.status = Ri.FATURAMENTO_RI_CONCLUIDO
        self.ri.save()
        Escola.objects.filter(pk=self.escola.pk).update(status_mip=Escola.FATURAMENTO_CONCLUIDO)
        self.ri.refresh_from_db()

    def _dados(self, acao, cfop="5102-004", itens=None, **extra):
        itens = itens if itens is not None else [(self.kit.pk, 1, "1001"), (self.nobreak.pk, 2, "1002")]
        dados = {
            "acao": acao,
            "cfop": cfop,
            "observacoes": "AP extra",
            "item_produto": [str(i[0]) for i in itens],
            "item_quantidade": [str(i[1]) for i in itens],
            "item_osp": [i[2] for i in itens],
            "para": "financeiro@speedcsc.com.br",
            "cc": "",
            "assunto": "Faturamento EACE complementar",
            "next": f"/inep/{INEP}/",
        }
        dados.update(extra)
        return dados

    def _post(self, usuario, acao, **kwargs):
        self.client.force_login(usuario)
        return self.client.post(
            reverse("ri_faturamento_complementar", kwargs={"pk": self.ri.pk}), self._dados(acao, **kwargs)
        )

    def _complementar_enviado(self, itens=None, numero=1):
        itens = itens or [
            {"kit_padrao_id": self.kit.pk, "descricao": "Kit Cobertura Wi-Fi - 4 Access Points", "eh_kit": True,
             "quantidade": 1, "valor_unitario": "1000.00", "item_lpu": "KIT 4", "aba": "NF KIT", "num_osp": "1001"},
            {"kit_padrao_id": self.nobreak.pk, "descricao": "Nobreak", "eh_kit": False, "quantidade": 2,
             "valor_unitario": "300.00", "item_lpu": "Nobreak", "aba": "Nobreak", "num_osp": "1002"},
        ]
        return FaturamentoComplementar.objects.create(
            ri=self.ri, numero=numero, status=FaturamentoComplementar.ENVIADO, itens=itens, cfop="5117",
            codigo_rastreio=f"{montar_codigo_rastreio(INEP, timezone.localdate())}-C{numero}",
        )


class NumeracaoEPlanilhaTests(BaseComplementar):

    def test_numeracao_c1_reaproveita_rascunho_e_depois_c2(self):
        self._post(self.analista, "baixar")
        self._post(self.analista, "baixar")
        self.assertEqual(list(self.ri.faturamentos_complementares.values_list("numero", "status")),
                         [(1, FaturamentoComplementar.RASCUNHO)])
        self._post(self.analista, "enviar")
        self._post(self.analista, "baixar")
        self.assertEqual(
            list(self.ri.faturamentos_complementares.order_by("numero").values_list("numero", "status")),
            [(1, FaturamentoComplementar.ENVIADO), (2, FaturamentoComplementar.RASCUNHO)],
        )

    def test_planilha_tem_so_os_itens_do_complementar_com_valor_do_catalogo(self):
        resp = self._post(self.analista, "baixar")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("FATURAMENTO MATERIAS EACE - COMPLEMENTAR C1 - 70000001", resp["Content-Disposition"])
        planilha = openpyxl.load_workbook(BytesIO(resp.content))
        abas = {aba.title.strip(): aba for aba in planilha.worksheets}
        self.assertEqual(set(abas), {"NF KIT", "Nobreak"})
        self.assertEqual(abas["NF KIT"]["H10"].value, 1000.0)
        self.assertEqual(abas["Nobreak"]["H10"].value, 600.0)  # 2 x 300 do catálogo
        self.assertEqual(abas["Nobreak"]["I16"].value, "Nobreak (2)")
        for aba in abas.values():
            self.assertEqual(aba["C10"].value, "5102-004")
            self.assertEqual(aba["D16"].value, "5102-004")
            self.assertEqual(aba["A16"].value, "00.000.000/0001-00")
            self.assertEqual(aba["B16"].value, "11.111.111/0001-11")
            self.assertEqual(aba["C16"].value, "Escola Complementar")
            self.assertEqual(aba["G16"].value, "Recife")
            self.assertEqual(aba["H16"].value, "PE")
            self.assertIn(f"INEP: {INEP}", aba["F10"].value)
        complementar = self.ri.faturamentos_complementares.get()
        self.assertEqual(complementar.itens[1]["valor_unitario"], "300.00")
        self.assertEqual(complementar.itens[0]["item_lpu"], "KIT 4")

    def test_mesma_aba_com_osps_diferentes_ganha_sufixo(self):
        resp = self._post(self.analista, "baixar", itens=[(self.nobreak.pk, 1, "1001"), (self.nobreak.pk, 1, "1002")])
        titulos = {aba.title for aba in openpyxl.load_workbook(BytesIO(resp.content)).worksheets}
        self.assertEqual(titulos, {"Nobreak - OSP 1001", "Nobreak - OSP 1002"})

    def test_osp_obrigatoria_com_mais_de_uma_osp_e_item_so_servico_recusado(self):
        resp = self._post(self.analista, "baixar", itens=[(self.kit.pk, 1, "")])
        self.assertEqual(resp.status_code, 302)
        resp = self._post(self.analista, "baixar", itens=[(self.so_servico.pk, 1, "1001")])
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(FaturamentoComplementar.objects.exists())

    def test_osp_unica_do_ri_e_preenchida_sozinha(self):
        RiItemRelatorioEace.objects.filter(ri=self.ri, num_osp="1002").update(num_osp="1001")
        self._post(self.analista, "baixar", itens=[(self.nobreak.pk, 1, "")])
        self.assertEqual(self.ri.faturamentos_complementares.get().itens[0]["num_osp"], "1001")

    def test_cabecalho_do_lado_ixc_obrigatorio(self):
        Ri.objects.filter(pk=self.ri.pk).update(cnpj="")
        resp = self._post(self.analista, "baixar")
        self.assertEqual(resp.status_code, 302)


class EnvioTests(BaseComplementar):

    def test_envio_em_ri_concluido_nao_muda_status_nem_mip_nem_lados(self):
        self._encerrar()
        RiItemIxc.objects.create(ri=self.ri, descricao_item="Kit", quantidade=1, valor_unitario=0, eh_kit=True)
        resp = self._post(self.admin, "enviar")
        self.assertEqual(resp.status_code, 302)
        self.ri.refresh_from_db()
        self.escola.refresh_from_db()
        self.assertEqual(self.ri.status, Ri.FATURAMENTO_RI_CONCLUIDO)
        self.assertEqual(self.escola.status_mip, Escola.FATURAMENTO_CONCLUIDO)
        self.assertEqual(self.ri.itens_ixc.count(), 1)
        self.assertEqual(self.ri.itens_relatorio_eace.count(), 2)

        complementar = self.ri.faturamentos_complementares.get()
        codigo = f"{montar_codigo_rastreio(INEP, timezone.localdate())}-C1"
        self.assertEqual(complementar.status, FaturamentoComplementar.ENVIADO)
        self.assertEqual(complementar.codigo_rastreio, codigo)
        self.assertEqual(len(mail.outbox), 1)
        assunto = mail.outbox[0].subject
        self.assertTrue(assunto.startswith(f"#{codigo} - "))
        # O Módulo Financeiro (regex do código normal) continua achando o INEP.
        self.assertIsNotNone(PADRAO_CODIGO.search(assunto))
        self.assertEqual(extrair_primeiro_inep_rastreio(f"RE: {assunto}"), INEP)
        self.assertEqual(extrair_codigo_complementar(f"RE: {assunto}"), codigo)
        self.assertIn("COMPLEMENTAR C1", mail.outbox[0].attachments[0][0])

        entrada = RiHistorico.objects.get(ri=self.ri, tipo=RiHistorico.EMAIL)
        self.assertEqual(entrada.faturamento_complementar, complementar)
        self.assertTrue(entrada.anexo.name)
        self.assertEqual(complementar.historico_envio, entrada)
        self.assertTrue(EmailFinanceiroLog.objects.filter(
            ri=self.ri, direcao=EmailFinanceiroLog.ENVIADO, faturamento_complementar=complementar).exists())
        self.assertFalse(RiHistorico.objects.filter(ri=self.ri, tipo=RiHistorico.LOG_STATUS).exists())

    def test_assunto_editado_sem_codigo_recebe_o_codigo(self):
        self._post(self.analista, "enviar", assunto="Outro assunto")
        codigo = f"{montar_codigo_rastreio(INEP, timezone.localdate())}-C1"
        self.assertEqual(mail.outbox[0].subject, f"#{codigo} - Outro assunto")


class PermissaoTests(BaseComplementar):

    def test_analista_pode_em_ri_nao_encerrado(self):
        self._post(self.analista, "enviar")
        self.assertEqual(len(mail.outbox), 1)

    def test_ri_encerrado_so_administrador(self):
        self._encerrar()
        self._post(self.analista, "enviar")
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(FaturamentoComplementar.objects.exists())
        self._post(self.admin, "enviar")
        self.assertEqual(len(mail.outbox), 1)

    def test_visualizador_nao_pode(self):
        self._post(self.visualizador, "enviar")
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(FaturamentoComplementar.objects.exists())

    def test_botao_aparece_so_para_quem_pode(self):
        self.client.force_login(self.analista)
        self.assertContains(self.client.get(reverse("ri_detail", kwargs={"inep": INEP})), "Faturamento complementar")
        self._encerrar()
        self.assertNotContains(self.client.get(reverse("ri_detail", kwargs={"inep": INEP})),
                               "data-abrir-modal-email=\"modal-complementar-")
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("ri_detail", kwargs={"inep": INEP})),
                            "data-abrir-modal-email=\"modal-complementar-")


class RespostaTests(BaseComplementar):

    def test_resposta_complementar_abre_so_os_logs_dele_com_a_osp_certa(self):
        self.ri.status = Ri.AGUARDANDO_FINANCEIRO
        self.ri.save()
        complementar = self._complementar_enviado()
        anexos = [
            ("4001_10-11-2026_NOME.pdf", b"%PDF-1"), ("4002_10-11-2026_NOME.pdf", b"%PDF-2"),
            ("4002_10-11-2026_NOME.xml", b"<nfe>2</nfe>"), ("4001_10-11-2026_NOME.xml", b"<nfe>1</nfe>"),
        ]
        bruto = _email_bytes(f"RE: #{complementar.codigo_rastreio} - Faturamento EACE complementar", anexos)

        def _valor(caminho):
            return {"valor": "1.000,00"} if "4001" in caminho else {"valor": "600,00"}

        with patch(EXTRAIR_PDF, side_effect=_valor):
            self.assertEqual(_processar_mensagem(bruto, "msg-compl-1"), "identificados")

        self.ri.refresh_from_db()
        self.assertEqual(self.ri.status, Ri.AGUARDANDO_FINANCEIRO)  # não avançou
        logs = list(self.ri.logs_rpa_eace.order_by("id"))
        self.assertEqual(len(logs), 2)
        self.assertTrue(all(log.faturamento_complementar_id == complementar.pk for log in logs))
        self.assertEqual([log.num_osp for log in logs], ["1001", "1002"])
        for log in logs:
            numero = log.documento_pdf.arquivo.name.split("/")[-1][:4]
            self.assertTrue(log.documento_xml.arquivo.name.split("/")[-1].startswith(numero))
        complementar.refresh_from_db()
        self.assertEqual(complementar.status, FaturamentoComplementar.RESPONDIDO)
        entrada = complementar.historico_resposta
        self.assertEqual(entrada.faturamento_complementar, complementar)
        self.assertIn("Resposta do faturamento complementar C1", entrada.mensagem)
        self.assertEqual(entrada.documentos.count(), 4)
        self.assertTrue(EmailFinanceiroLog.objects.filter(
            direcao=EmailFinanceiroLog.RECEBIDO, faturamento_complementar=complementar).exists())

    def test_resposta_normal_continua_igual(self):
        self.ri.status = Ri.AGUARDANDO_FINANCEIRO
        self.ri.save()
        self._complementar_enviado()
        codigo = montar_codigo_rastreio(INEP, timezone.localdate())
        bruto = _email_bytes(f"RE: #{codigo} - Faturamento EACE", [("1.pdf", b"%PDF"), ("1.xml", b"<nfe/>")])
        self.assertEqual(_processar_mensagem(bruto, "msg-normal-1"), "identificados")
        self.ri.refresh_from_db()
        self.assertEqual(self.ri.status, Ri.AGUARDANDO_ANEXO_PORTAL_EACE)
        log = self.ri.logs_rpa_eace.get()
        self.assertIsNone(log.faturamento_complementar_id)
        self.assertIsNone(log.documento_pdf_id)
        self.assertFalse(RiHistorico.objects.filter(faturamento_complementar__isnull=False).exists())


class RelatoriosTests(BaseComplementar):

    def _remessa(self, notas, quando, complementar=None):
        documentos = []
        for numero, valor, item_lpu in notas:
            documentos.append(Documento.objects.create(
                ri=self.ri, tipo=Documento.XML, recebido_em=quando,
                arquivo=ContentFile(_xml_nf(numero, valor, item_lpu), f"{numero}_10-11-2026_X.xml")))
            documentos.append(Documento.objects.create(
                ri=self.ri, tipo=Documento.NOTA_FISCAL_PDF, recebido_em=quando,
                arquivo=ContentFile(b"%PDF", f"{numero}_10-11-2026_X.pdf")))
        entrada = RiHistorico.objects.create(ri=self.ri, tipo=RiHistorico.EMAIL, mensagem="Resposta",
                                             faturamento_complementar=complementar)
        entrada.documentos.set(documentos)
        RiHistorico.objects.filter(pk=entrada.pk).update(criado_em=quando)
        return documentos

    def _quando(self, dia):
        return timezone.make_aware(datetime(2026, 11, dia, 10, 0))

    def test_complementar_soma_e_refaturada_normal_substitui(self):
        complementar = self._complementar_enviado()
        self._remessa([("100", "1000.00", "KIT 4")], self._quando(9))
        self._remessa([("200", "1000.00", "KIT 4")], self._quando(10), complementar=complementar)
        numeros = [nota["numero_nf"] for nota in notas_fiscais_vigentes_do_financeiro(self.ri)]
        self.assertEqual(numeros, ["100", "200"])
        # NF normal refaturada substitui a normal; a complementar continua.
        self._remessa([("101", "1000.00", "KIT 4")], self._quando(11))
        numeros = [nota["numero_nf"] for nota in notas_fiscais_vigentes_do_financeiro(self.ri)]
        self.assertEqual(numeros, ["101", "200"])

    def test_nf_complementar_baixada_sai_do_relatorio(self):
        complementar = self._complementar_enviado()
        self._remessa([("100", "1000.00", "KIT 4")], self._quando(9))
        self._remessa([("200", "1000.00", "KIT 4")], self._quando(10), complementar=complementar)
        NfCanceladaFinanceiro.objects.create(id_financeiro="x1", numero_nf="200", inep=INEP,
                                             baixada_em=timezone.now())
        numeros = [nota["numero_nf"] for nota in notas_fiscais_vigentes_do_financeiro(self.ri)]
        self.assertEqual(numeros, ["100"])

    def test_ultimo_email_do_financeiro_ignora_o_complementar(self):
        complementar = self._complementar_enviado()
        normais = self._remessa([("100", "1000.00", "KIT 4")], self._quando(9))
        self._remessa([("200", "1000.00", "KIT 4")], self._quando(10), complementar=complementar)
        pdfs = _documentos_nf_do_ultimo_email_financeiro(self.ri)
        self.assertEqual([doc.pk for doc in pdfs], [normais[1].pk])

    def test_data_faturamento_do_grid_ignora_resposta_complementar(self):
        complementar = self._complementar_enviado()
        EmailFinanceiroLog.objects.create(ri=self.ri, direcao=EmailFinanceiroLog.RECEBIDO,
                                          faturamento_complementar=complementar)
        self.client.force_login(self.analista)
        resp = self.client.get(reverse("grid_inep"), {"q": INEP})
        linha = next(linha for linha in resp.context["page_obj"] if linha["escola"].inep == INEP)
        self.assertIsNone(linha["data_resposta_financeiro"])
        EmailFinanceiroLog.objects.create(ri=self.ri, direcao=EmailFinanceiroLog.RECEBIDO)
        resp = self.client.get(reverse("grid_inep"), {"q": INEP})
        linha = next(linha for linha in resp.context["page_obj"] if linha["escola"].inep == INEP)
        self.assertIsNotNone(linha["data_resposta_financeiro"])


class RpaComplementarTests(BaseComplementar):

    def _log(self, complementar, num_osp="1002"):
        pdf = Documento.objects.create(ri=self.ri, tipo=Documento.NOTA_FISCAL_PDF,
                                       arquivo=ContentFile(b"%PDF", "4002.pdf"))
        xml = Documento.objects.create(ri=self.ri, tipo=Documento.XML, arquivo=ContentFile(b"<nfe/>", "4002.xml"))
        return LogRpaEace.objects.create(ri=self.ri, faturamento_complementar=complementar, documento_pdf=pdf,
                                         documento_xml=xml, num_osp=num_osp, resultado=LogRpaEace.PROCESSANDO)

    def test_documento_ja_enviado_em_log_complementar_vira_erro(self):
        self.ri.status = Ri.AGUARDANDO_ANEXO_PORTAL_EACE
        self.ri.save()
        log = self._log(self._complementar_enviado())
        resultado = ResultadoRpaEace(sucesso=False, motivo="documento_ja_enviado", dados_pdf={"inep": INEP})
        with patch("apps.integracoes.eace.rpa.anexar_nota_fiscal", return_value=resultado) as mock_rpa:
            executar_log_rpa_eace(log)
        self.assertEqual(mock_rpa.call_args.kwargs["osp"], "1002")  # OSP do complementar, não a 1ª do 3º lado
        log.refresh_from_db()
        self.assertEqual(log.resultado, LogRpaEace.ERRO)
        self.assertEqual(log.motivo_erro, "complementar_sem_linha_pendente")
        self.assertIn("NF complementar", log.motivo_erro_legivel)
        self.assertFalse(log.erro_do_portal)

    def test_sucesso_do_complementar_nao_avanca_o_ri(self):
        self.ri.status = Ri.AGUARDANDO_ANEXO_PORTAL_EACE
        self.ri.save()
        log = self._log(self._complementar_enviado())
        with patch("apps.integracoes.eace.rpa.anexar_nota_fiscal",
                   return_value=ResultadoRpaEace(sucesso=True, dados_pdf={"inep": INEP})):
            executar_log_rpa_eace(log)
        self.ri.refresh_from_db()
        self.assertEqual(self.ri.status, Ri.AGUARDANDO_ANEXO_PORTAL_EACE)
        self.assertFalse(rpa_eace_concluida(self.ri))

    def test_log_complementar_pendente_nao_segura_o_normal(self):
        LogRpaEace.objects.create(ri=self.ri, resultado=LogRpaEace.SUCESSO)
        LogRpaEace.objects.create(ri=self.ri, faturamento_complementar=self._complementar_enviado())
        self.assertTrue(rpa_eace_concluida(self.ri))

    def test_card_do_complementar_tem_bloco_proprio_e_nao_desalinha_a_referencia(self):
        complementar = self._complementar_enviado()
        log_compl = LogRpaEace.objects.create(ri=self.ri, faturamento_complementar=complementar, num_osp="1002")
        log_normal = LogRpaEace.objects.create(ri=self.ri)
        contexto = _contexto_logs_rpa_eace(self.ri, "/")
        self.assertEqual([log.pk for log in contexto["logs_rpa_eace_normais"]], [log_normal.pk])
        self.assertEqual([log.pk for log in contexto["logs_rpa_eace_complementares"]], [log_compl.pk])
        normal = contexto["logs_rpa_eace_normais"][0]
        self.assertEqual(normal.numero_nf, 1)
        self.assertEqual(normal.item_referencia.num_osp, "1001")
        self.assertFalse(hasattr(contexto["logs_rpa_eace_complementares"][0], "item_referencia"))
        self.client.force_login(self.analista)
        resp = self.client.get(reverse("ri_detail", kwargs={"inep": INEP}))
        self.assertContains(resp, "NF complementar C1 #1")
        self.assertContains(resp, "Notas Fiscais complementares")


class ComandoSimularRespostaTests(BaseComplementar):

    def test_bloqueado_sem_debug(self):
        from django.core.management import CommandError, call_command

        with self.assertRaises(CommandError):
            call_command("simular_resposta_financeiro", "--complementar", INEP, "1")

    def test_simula_resposta_do_complementar_em_dev(self):
        from django.core.management import call_command

        complementar = self._complementar_enviado(itens=[
            {"kit_padrao_id": self.nobreak.pk, "descricao": "Nobreak", "eh_kit": False, "quantidade": 1,
             "valor_unitario": "300.00", "item_lpu": "Nobreak", "aba": "Nobreak", "num_osp": "1002"},
        ])
        pasta = tempfile.mkdtemp()
        try:
            for nome, conteudo in (("9_10-11-2026_X.pdf", b"%PDF"), ("9_10-11-2026_X.xml", b"<nfe/>")):
                with open(f"{pasta}/{nome}", "wb") as arquivo:
                    arquivo.write(conteudo)
            with override_settings(DEBUG=True):
                call_command("simular_resposta_financeiro", "--complementar", INEP, "1",
                             "--arquivo", f"{pasta}/9_10-11-2026_X.pdf", "--arquivo", f"{pasta}/9_10-11-2026_X.xml",
                             stdout=open(f"{pasta}/saida.txt", "w"))
        finally:
            shutil.rmtree(pasta, ignore_errors=True)
        log = LogRpaEace.objects.get(faturamento_complementar=complementar)
        self.assertEqual(log.num_osp, "1002")
