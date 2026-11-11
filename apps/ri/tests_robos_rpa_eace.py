"""ADR-009: robôs do RPA EACE em paralelo (`apps.ri.fila_rpa_eace`,
comando `processar_fila_rpa_eace --robo`, admin "Robôs do RPA EACE"). O
portal nunca é chamado - a execução do RPA é mockada."""

import os
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from apps.core.admin import RoboRpaEaceForm
from apps.core.models import RoboRpaEace
from apps.escolas.models import Escola, LogRpaEaceMip, Lote
from apps.integracoes.eace.config import ConfigEace
from apps.ri.fila_rpa_eace import (
    MIP,
    RI,
    recuperar_envios_de_robos_parados,
    reservar_proximo_envio,
)
from apps.ri.models import LogRpaEace, Ri

CMD = "apps.ri.management.commands.processar_fila_rpa_eace"


class BaseRobos(TestCase):

    def setUp(self):
        self.robo_1 = RoboRpaEace.objects.create(nome="Robô 1", usuario="robo1@teste", senha="s1")
        self.robo_2 = RoboRpaEace.objects.create(nome="Robô 2", usuario="robo2@teste", senha="s2")
        self._segundos = 0

    def _log_ri(self, inep, **extra):
        escola, _ = Escola.objects.get_or_create(inep=inep, defaults={"nome": f"ESCOLA {inep}"})
        ri, _ = Ri.objects.get_or_create(escola=escola)
        self._segundos += 1
        dados = {"resultado": LogRpaEace.NA_FILA,
                 "enfileirado_em": timezone.now() + timezone.timedelta(seconds=self._segundos)}
        dados.update(extra)
        return LogRpaEace.objects.create(ri=ri, **dados)

    def _log_mip(self, ineps, **extra):
        lote = Lote.objects.create(estado="GO", municipio=f"Cidade {ineps[0]}")
        lote.escolas.set([Escola.objects.get_or_create(inep=i, defaults={"nome": i})[0] for i in ineps])
        self._segundos += 1
        dados = {"resultado": LogRpaEaceMip.NA_FILA, "nome_nota_fiscal": "nf.pdf", "municipio": lote.municipio,
                 "enfileirado_em": timezone.now() + timezone.timedelta(seconds=self._segundos)}
        dados.update(extra)
        return LogRpaEaceMip.objects.create(lote=lote, **dados)


class ReservaTests(BaseRobos):

    def test_dois_robos_pegam_itens_diferentes_na_ordem_da_fila(self):
        a = self._log_ri("11000001")
        b = self._log_mip(["11000002"])
        self.assertEqual(reservar_proximo_envio(self.robo_1), (RI, a.pk))
        self.assertEqual(reservar_proximo_envio(self.robo_2), (MIP, b.pk))
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual((a.resultado, a.robo), (LogRpaEace.PROCESSANDO, self.robo_1))
        self.assertEqual((b.resultado, b.robo), (LogRpaEaceMip.PROCESSANDO, self.robo_2))
        self.assertIsNone(reservar_proximo_envio(self.robo_1))

    def test_mesmo_inep_nao_roda_em_2_robos(self):
        a = self._log_ri("11000001")
        self._log_ri("11000001")  # 2ª NF do mesmo INEP/RI
        c = self._log_ri("11000003")
        reservar_proximo_envio(self.robo_1)
        self.assertEqual(reservar_proximo_envio(self.robo_2), (RI, c.pk))
        a.refresh_from_db()
        self.assertEqual(a.robo, self.robo_1)

    def test_so_item_de_inep_ocupado_fica_esperando(self):
        self._log_ri("11000001")
        self._log_ri("11000001")
        reservar_proximo_envio(self.robo_1)
        self.assertIsNone(reservar_proximo_envio(self.robo_2))

    def test_lote_do_mip_com_inep_ocupado_pelo_ri_espera(self):
        self._log_ri("11000001")
        self._log_mip(["11000005", "11000001"])
        reservar_proximo_envio(self.robo_1)
        self.assertIsNone(reservar_proximo_envio(self.robo_2))

    def test_2_nfs_do_mesmo_lote_nao_rodam_juntas(self):
        a = self._log_mip(["11000001"])
        LogRpaEaceMip.objects.create(
            lote=a.lote, resultado=LogRpaEaceMip.NA_FILA, nome_nota_fiscal="nf2.pdf",
            municipio="X", enfileirado_em=timezone.now() + timezone.timedelta(minutes=5),
        )
        reservar_proximo_envio(self.robo_1)
        self.assertIsNone(reservar_proximo_envio(self.robo_2))

    def test_robo_padrao_do_env_fica_sem_robo_no_log(self):
        a = self._log_ri("11000001")
        reservar_proximo_envio(None)
        a.refresh_from_db()
        self.assertEqual(a.resultado, LogRpaEace.PROCESSANDO)
        self.assertIsNone(a.robo)


class RecuperacaoTests(BaseRobos):

    def test_nao_mexe_no_envio_de_robo_que_esta_rodando(self):
        rodando = self._log_ri("11000001", resultado=LogRpaEace.PROCESSANDO, robo=self.robo_1)
        parado = self._log_mip(["11000002"], resultado=LogRpaEaceMip.PROCESSANDO, robo=self.robo_2)
        recuperados = recuperar_envios_de_robos_parados({self.robo_1.pk})
        self.assertEqual(recuperados, [f"MIP#{parado.pk}"])
        rodando.refresh_from_db()
        parado.refresh_from_db()
        self.assertEqual(rodando.resultado, LogRpaEace.PROCESSANDO)
        self.assertEqual(parado.resultado, LogRpaEaceMip.NA_FILA)
        self.assertEqual(parado.motivo_erro, "interrompido")

    def test_supervisor_iniciando_recupera_tudo(self):
        a = self._log_ri("11000001", resultado=LogRpaEace.PROCESSANDO, robo=self.robo_1)
        b = self._log_ri("11000002", resultado=LogRpaEace.PROCESSANDO)
        self.assertEqual(len(recuperar_envios_de_robos_parados(set())), 2)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual((a.resultado, b.resultado), (LogRpaEace.NA_FILA, LogRpaEace.NA_FILA))

    def test_robo_padrao_rodando_nao_perde_o_envio(self):
        a = self._log_ri("11000001", resultado=LogRpaEace.PROCESSANDO)
        self.assertEqual(recuperar_envios_de_robos_parados({None}), [])
        a.refresh_from_db()
        self.assertEqual(a.resultado, LogRpaEace.PROCESSANDO)


class ComandoRoboTests(BaseRobos):

    def setUp(self):
        super().setUp()
        self._env = {k: os.environ.get(k) for k in ("EACE_USUARIO", "EACE_SENHA")}

    def tearDown(self):
        for chave, valor in self._env.items():
            if valor is None:
                os.environ.pop(chave, None)
            else:
                os.environ[chave] = valor

    def test_roda_com_o_login_do_robo(self):
        a = self._log_ri("11000001")
        logins = []

        def _executar(tipo, pk):
            cfg = ConfigEace.carregar()
            logins.append((cfg.usuario, cfg.senha))
            return {"log_id": pk, "resultado": "sucesso", "motivo": ""}

        saida = StringIO()
        with patch(f"{CMD}.executar_envio_reservado", side_effect=_executar):
            call_command("processar_fila_rpa_eace", robo=self.robo_2.pk, stdout=saida)
        self.assertEqual(logins, [("robo2@teste", "s2")])
        self.assertIn(f"[Robô 2] RI - Log {a.pk}", saida.getvalue())

    def test_robo_inativo_nao_roda(self):
        self.robo_1.ativo = False
        self.robo_1.save()
        with self.assertRaises(CommandError):
            call_command("processar_fila_rpa_eace", robo=self.robo_1.pk, stdout=StringIO())

    def test_passada_recupera_so_o_envio_preso_do_proprio_robo(self):
        meu = self._log_ri("11000001", resultado=LogRpaEace.PROCESSANDO, robo=self.robo_1)
        do_outro = self._log_ri("11000002", resultado=LogRpaEace.PROCESSANDO, robo=self.robo_2)
        call_command("processar_fila_rpa_eace", robo=self.robo_1.pk, stdout=StringIO())
        meu.refresh_from_db()
        do_outro.refresh_from_db()
        self.assertEqual(meu.resultado, LogRpaEace.NA_FILA)
        self.assertEqual(do_outro.resultado, LogRpaEace.PROCESSANDO)


class AdminRoboFormTests(TestCase):

    def test_senha_em_branco_na_edicao_mantem_a_atual(self):
        robo = RoboRpaEace.objects.create(nome="Robô 1", usuario="r@t", senha="antiga")
        form = RoboRpaEaceForm(data={"nome": "Robô 1", "usuario": "r@t", "senha": "", "ativo": "on"}, instance=robo)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        robo.refresh_from_db()
        self.assertEqual(robo.senha, "antiga")

    def test_senha_obrigatoria_no_cadastro(self):
        form = RoboRpaEaceForm(data={"nome": "Robô 1", "usuario": "r@t", "senha": "", "ativo": "on"})
        self.assertFalse(form.is_valid())
        self.assertIn("senha", form.errors)


class AdminClonarRoboTests(TestCase):

    def test_clona_com_o_mesmo_login_e_nasce_inativo(self):
        from apps.core.models import User

        admin_user = User.objects.create_superuser(username="adm", password="senha-teste-123", email="a@a.com")
        robo = RoboRpaEace.objects.create(nome="Robô 1", usuario="r@t", senha="segredo")
        RoboRpaEace.objects.create(nome="Robô 2", usuario="r@t", senha="segredo")
        self.client.force_login(admin_user)
        resp = self.client.post(
            "/admin/core/roborpaeace/",
            {"action": "clonar_robos", "_selected_action": [robo.pk]},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        copia = RoboRpaEace.objects.get(nome="Robô 3")
        self.assertEqual((copia.usuario, copia.senha, copia.ativo), ("r@t", "segredo", False))
        self.assertContains(resp, "Robô 3")
