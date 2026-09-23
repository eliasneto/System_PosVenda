"""Automação **Criação de Atendimento IXC** — trazida de
`IXC/automacoes/criacao_atendimento_ixc.py` (cópia de referência do projeto
sgpspeed) em 2026-09-23. Abre o ticket no IXC via endpoint `su_ticket`.
Lógica de negócio mantida como veio (validada em produção no sistema de
origem) — só a dependência de `pandas` foi trocada por `_isna` local (ver
`criacao_login_ixc.py`).

`USUARIO_IXC_PADRAO = "76"` (usuário do IXC responsável pelo ticket):
decisão confirmada pelo usuário (2026-09-23) — manter o mesmo ID já usado
no sistema de origem (RN a formalizar pelo Orquestrador)."""

import json
import re
from datetime import datetime

from apps.integracoes.ixc.client import IXCClient

USUARIO_IXC_PADRAO = "76"
MENSAGEM_CAMPO_ID_NUMERICO = (
    "deve conter apenas o ID numerico do IXC. Nao use endereco, nome ou outro texto."
)

TIPOS_PROCESSO = ["Avulso", "Cotacao Parceiro", "Outro"]
WORKFLOW_COTACAO_PARCEIRO = "18"


def _isna(valor):
    """Equivalente local a `pandas.isna` para valor escalar — ver
    `criacao_login_ixc._isna` (mesmo projeto lê `.xlsx` com openpyxl, não
    pandas)."""
    if valor is None:
        return True
    if isinstance(valor, float):
        return valor != valor
    return False


def limpar_id(valor):
    if _isna(valor) or str(valor).strip().lower() == "nan" or valor in ("", None):
        return ""
    return str(valor).split(".")[0].strip()


def normalizar_id_numerico(valor, nome_campo, *, obrigatorio=False):
    if _isna(valor) or valor in ("", None):
        if obrigatorio:
            return None, f"{nome_campo} invalido"
        return "", None

    texto = str(valor).strip()
    if not texto or texto.lower() == "nan":
        if obrigatorio:
            return None, f"{nome_campo} invalido"
        return "", None

    if isinstance(valor, float) and not valor.is_integer():
        return None, f"{nome_campo} {MENSAGEM_CAMPO_ID_NUMERICO}"

    if not re.fullmatch(r"\d+(?:\.0+)?", texto):
        return None, f"{nome_campo} {MENSAGEM_CAMPO_ID_NUMERICO}"

    return texto.split(".")[0].strip(), None


def limpar_texto(valor):
    if _isna(valor) or str(valor).strip().lower() == "nan" or valor is None:
        return ""
    return str(valor).strip()


def montar_identificacao_usuario_importacao(usuario_sistema=None):
    if not usuario_sistema or not getattr(usuario_sistema, "is_authenticated", False):
        return ""

    nome = (getattr(usuario_sistema, "get_full_name", lambda: "")() or "").strip()
    username = (getattr(usuario_sistema, "username", "") or "").strip()
    identificador = nome or username
    if not identificador:
        return ""

    if nome and username and nome != username:
        identificador = f"{nome} ({username})"

    momento = datetime.now().strftime("%d/%m/%Y %H:%M")
    return f"Importado por: {identificador} em {momento}"


def validar_tipo_processo(linha):
    tipo = limpar_texto(linha.get("Tipo_Processo"))

    if not tipo:
        return False, "Tipo_Processo e obrigatorio. Use: Avulso, Cotacao Parceiro ou Outro."

    if tipo not in TIPOS_PROCESSO:
        return False, f"Tipo_Processo invalido: '{tipo}'. Use: Avulso, Cotacao Parceiro ou Outro."

    workflow_raw = linha.get("Workflow_ID")
    workflow_id, erro = normalizar_id_numerico(workflow_raw, "Workflow_ID")
    if erro:
        return False, erro

    if tipo == "Avulso":
        if workflow_id:
            return False, (
                f"Tipo_Processo 'Avulso' exige Workflow_ID vazio, "
                f"mas foi informado '{workflow_id}'."
            )
    elif tipo == "Cotacao Parceiro":
        if workflow_id != WORKFLOW_COTACAO_PARCEIRO:
            detalhe = f"'{workflow_id}'" if workflow_id else "vazio"
            return False, (
                f"Tipo_Processo 'Cotacao Parceiro' exige Workflow_ID={WORKFLOW_COTACAO_PARCEIRO}, "
                f"mas foi informado {detalhe}."
            )
    elif tipo == "Outro":
        if not workflow_id:
            return False, "Tipo_Processo 'Outro' exige Workflow_ID preenchido."

    return True, None


def executar_abertura_atendimento(dados, usuario_sistema=None):
    linha = {str(k).replace("﻿", "").strip(): v for k, v in dados.items()}

    id_cliente, erro = normalizar_id_numerico(
        linha.get("Cliente_ID"), "Cliente_ID", obrigatorio=True
    )
    if erro:
        return False, erro

    id_login, erro = normalizar_id_numerico(linha.get("Login_ID"), "Login_ID")
    if erro:
        return False, erro

    id_contrato, erro = normalizar_id_numerico(
        linha.get("Contrato_ID"), "Contrato_ID", obrigatorio=True
    )
    if erro:
        return False, erro

    id_assunto, erro = normalizar_id_numerico(
        linha.get("Assunto_ID"), "Assunto_ID", obrigatorio=True
    )
    if erro:
        return False, erro

    id_filial, erro = normalizar_id_numerico(
        linha.get("Filial_ID"), "Filial_ID", obrigatorio=True
    )
    if erro:
        return False, erro

    id_ticket_setor, erro = normalizar_id_numerico(
        linha.get("Departamento_ID"), "Departamento_ID", obrigatorio=True
    )
    if erro:
        return False, erro

    titulo = limpar_texto(linha.get("Assunto_Descricao"))
    mensagem = limpar_texto(linha.get("Descricao"))
    endereco = limpar_texto(linha.get("Endereco"))

    id_wfl_processo, erro = normalizar_id_numerico(linha.get("Workflow_ID"), "Workflow_ID")
    if erro:
        return False, erro

    if not id_login:
        id_login, erro = normalizar_id_numerico(
            linha.get("Login_Contrato_ID"), "Login_ID"
        )
        if erro:
            return False, erro

    if not id_login:
        return False, f"Login_ID invalido para cliente {id_cliente}"

    if not id_assunto:
        return False, f"Assunto_ID invalido para cliente {id_cliente}"

    if not id_filial:
        return False, f"Filial_ID invalido para cliente {id_cliente}"

    if not id_ticket_setor:
        return False, f"Departamento_ID invalido para cliente {id_cliente}"

    if not titulo:
        return False, f"Assunto_Descricao vazio para cliente {id_cliente}"

    if not mensagem:
        return False, f"Descricao vazia para cliente {id_cliente}"

    identificacao_usuario = montar_identificacao_usuario_importacao(usuario_sistema)
    if identificacao_usuario:
        mensagem = f"{mensagem}\n\n{identificacao_usuario}"

    payload = {
        "action": "novo",
        "tipo": "C",
        "id_cliente": id_cliente,
        "id_login": id_login,
        "id_contrato": id_contrato,
        "id_filial": id_filial,
        "id_assunto": id_assunto,
        "titulo": titulo,
        "origem_endereco": "L",
        "origem_endereco_estrutura": "E",
        "endereco": endereco,
        "id_wfl_processo": id_wfl_processo,
        "id_ticket_setor": id_ticket_setor,
        "id_usuarios": USUARIO_IXC_PADRAO,
        "prioridade": "M",
        "menssagem": mensagem,
        "interacao_pendente": "N",
        "su_status": "N",
        "status": "T",
        "finalizar_atendimento": "N",
        "origem_cadastro": "P",
        "mensagens_nao_lida_cli": "0",
        "mensagens_nao_lida_sup": "0",
        "id_ticket_origem": "I",
        "melhor_horario_reserva": "Q",
    }

    payload = {k: v for k, v in payload.items() if v not in ("", None)}

    print("\n--- DEBUG TICKET PAYLOAD ---")
    print("id_cliente:", id_cliente)
    print("id_login:", id_login)
    print("id_contrato:", id_contrato)
    print("id_assunto:", id_assunto)
    print("id_filial:", id_filial)
    print("id_ticket_setor:", id_ticket_setor)
    print("id_usuarios:", USUARIO_IXC_PADRAO)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print("----------------------------\n")

    try:
        status_code, resposta = IXCClient().escrever("su_ticket", payload)

        print("STATUS TICKET:", status_code)
        print("RESPOSTA BRUTA TICKET:", resposta)

        if not isinstance(resposta, dict):
            return False, f"Erro HTTP {status_code}"

        if 'raw' in resposta:
            return False, f"Erro HTTP {status_code}: {str(resposta['raw'])[:500]}"

        if status_code == 401:
            return False, "Erro 401: token invalido ou sem permissao"

        if status_code != 200:
            mensagem_erro = resposta.get("message")
            detalhe = f": {mensagem_erro}" if mensagem_erro else ""
            return False, f"Erro HTTP {status_code}{detalhe}"

        if resposta.get("type") != "success":
            return False, f"IXC negou o ticket: {resposta.get('message')}"

        id_ticket = resposta.get("id")

        if not id_ticket:
            return False, "Ticket criado sem ID retornado pela API"

        print(f"[+] Ticket criado com sucesso. ID: {id_ticket}")

        return True, f"Atendimento aberto com sucesso! ID: {id_ticket}"

    except Exception as e:
        return False, f"Erro Tecnico: {str(e)}"
