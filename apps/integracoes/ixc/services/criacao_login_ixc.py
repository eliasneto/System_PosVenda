"""Automação **Criação de Login IXC** — trazida de
`IXC/automacoes/criacao_login_ixc.py` (cópia de referência do projeto
sgpspeed) em 2026-09-23. Cria o login (radusuário) do cliente no IXC via
endpoint `radusuarios`. Lógica de negócio (payload, limpeza de campos)
mantida como veio — validada em produção no sistema de origem — só a
dependência de `pandas` foi trocada por `_isna` local, já que este projeto
lê `.xlsx` com `openpyxl` (`apps/ixc/services.py`), não com pandas."""

import re
import unicodedata
import json  # Importado para conseguirmos ver o Raio-X no terminal

from apps.integracoes.ixc.client import IXCClient


def _isna(valor):
    """Equivalente local a `pandas.isna` para valor escalar — só `None` e
    `float('nan')` contam como vazio (openpyxl nunca devolve NaN de string,
    só de fato `None` em célula vazia ou `float('nan')` em fórmula quebrada)."""
    if valor is None:
        return True
    if isinstance(valor, float):
        return valor != valor
    return False


def _parse_campos_tecnicos_obs(obs_texto):
    campos = {}
    if not obs_texto:
        return campos

    mapa = {
        'VELOCIDADE': 'velocidade',
        'TIPO DE ACESSO': 'tipo_acesso',
        'BLOCO IP': 'ipv4_bloco',
        'DUPLA ABORDAGEM': 'dupla_abordagem',
        'ENTREGA RB': 'entrega_rb',
    }

    for linha in str(obs_texto).splitlines():
        linha_limpa = linha.strip()
        if not linha_limpa or ':' not in linha_limpa:
            continue

        chave_bruta, valor_bruto = linha_limpa.split(':', 1)
        chave = chave_bruta.strip().upper()
        valor = valor_bruto.strip()

        campo_destino = mapa.get(chave)
        if campo_destino and valor:
            campos[campo_destino] = valor

    return campos


def _atualizar_endereco_tecnico(linha, observacao):
    # Integração opcional com `apps.clientes.models.Endereco` (projeto de
    # origem, sgpspeed) — este projeto não tem esse model; o except abaixo
    # já faz esta função não fazer nada, de propósito (README trazido em
    # 2026-09-23: "nenhuma ação necessária, a menos que se queira replicar
    # esse comportamento com o model equivalente daqui").
    try:
        from apps.clientes.models import Endereco
        from django.db.models import Q
    except Exception:
        return

    campos_tecnicos = _parse_campos_tecnicos_obs(observacao)
    if not campos_tecnicos:
        return

    login = str(linha.get('Login_Login') or '').strip()
    cliente_id_ixc = str(linha.get('Cliente_ID') or '').split('.')[0].strip()
    logradouro = str(linha.get('End_Logradouro') or '').strip()
    numero = str(linha.get('End_Numero') or '').split('.')[0].strip()
    bairro = str(linha.get('End_Bairro') or '').strip()
    cidade_id_ixc = str(
        linha.get('End_Cidade_ID_IXC')
        or linha.get('End_Cidade_ID')
        or linha.get('End_Cidade')
        or ''
    ).split('.')[0].strip()

    endereco = None

    if login:
        endereco = Endereco.objects.filter(login_ixc=login).order_by('-id').first()

    if not endereco and cliente_id_ixc:
        filtros = Q(cliente__id_ixc=cliente_id_ixc)
        if logradouro:
            filtros &= Q(logradouro__iexact=logradouro)
        if numero:
            filtros &= Q(numero__iexact=numero)
        if bairro:
            filtros &= Q(bairro__iexact=bairro)

        endereco = Endereco.objects.filter(filtros).order_by('-id').first()

    if not endereco:
        return

    update_fields = []

    if login and endereco.login_ixc != login:
        endereco.login_ixc = login
        update_fields.append('login_ixc')

    if cidade_id_ixc and getattr(endereco, 'cidade_id_ixc', None) != cidade_id_ixc:
        endereco.cidade_id_ixc = cidade_id_ixc
        update_fields.append('cidade_id_ixc')

    for campo, valor in campos_tecnicos.items():
        if getattr(endereco, campo) != valor:
            setattr(endereco, campo, valor)
            update_fields.append(campo)

    if update_fields:
        endereco.save(update_fields=update_fields)

def executar_cadastro_ixc(dados):
    # 🚀 BLINDAGEM CONTRA O EXCEL:
    # Remove qualquer espaço invisível do nome das colunas lidas da planilha
    # Exemplo: Transforma 'Plano_ID ' em 'Plano_ID' para o Python não se perder
    linha = {str(k).strip(): v for k, v in dados.items()}

    # FUNÇÃO DE LIMPEZA:
    # O Excel transforma números em decimais (ex: 4 vira "4.0").
    # Essa função remove o ".0" e tira espaços vazios ao redor do número.
    def limpar_id(valor):
        if _isna(valor) or str(valor).strip().lower() == 'nan' or valor == '' or valor is None:
            return ''
        return str(valor).split('.')[0].strip()

    def obter_cidade_id_ixc():
        cidade_id = limpar_id(
            linha.get('End_Cidade_ID_IXC')
            or linha.get('End_Cidade_ID')
            or linha.get('End_Cidade')
        )

        if not cidade_id:
            return ''

        if not cidade_id.isdigit():
            return None

        return cidade_id

    def limpar_login(texto):
        if _isna(texto) or texto is None:
            return ''

        texto = str(texto).strip() # Tira espaços das pontas
        texto = texto.replace(' ', '') # Tira espaços do meio

        # Remove acentos (ex: á vira a, ç vira c, õ vira o)
        texto = unicodedata.normalize('NFKD', texto).encode('ASCII', 'ignore').decode('utf-8')

        # Remove QUALQUER símbolo que não seja letra, número, traço (-) ou underline (_)
        texto = re.sub(r'[^a-zA-Z0-9_-]', '', texto)

        return texto

    # Garante que só passem NÚMEROS (Remove .0, traços, etc)
    # Garante que o CEP vá perfeito para o IXC
    def somente_numeros(valor):
        if _isna(valor) or str(valor).strip().lower() == 'nan' or valor == '' or valor is None:
            return ''

        texto = str(valor).strip()

        # Se o Excel mandar como decimal (ex: 60346165.0), tira o .0
        if texto.endswith('.0'):
            texto = texto[:-2]

        # Arranca qualquer traço, ponto ou espaço (ex: 60.346-165 vira 60346165)
        numeros = re.sub(r'[^0-9]', '', texto)

        # CEP no Brasil TEM que ter 8 dígitos. AQUI ESTÁ A CORREÇÃO DA MÁSCARA:
        # Forçamos o traço no CEP porque o IXC na verdade exige XXXXX-XXX
        if len(numeros) == 8:
            return f"{numeros[:5]}-{numeros[5:]}"
        elif len(numeros) > 0:
            return numeros.zfill(8) # Devolve os zeros perdidos

        return ''

    def limpar_texto(valor):
        if _isna(valor) or str(valor).strip().lower() == 'nan' or valor is None:
            return ''
        return str(valor).strip()

    def normalizar_sim_nao(valor):
        texto = limpar_texto(valor).lower()
        if texto in {'sim', 's', 'yes', 'y', 'true', '1'}:
            return 'Sim'
        if texto in {'nao', 'não', 'n', 'no', 'false', '0'}:
            return 'Não'
        return limpar_texto(valor)

    def montar_observacao_cliente():
        observacao_manual = limpar_texto(linha.get('Obs_Cliente'))
        linhas = []

        if observacao_manual:
            linhas.append(observacao_manual)

        mapa_campos_tecnicos = [
            ('VELOCIDADE', 'VELOCIDADE'),
            ('TIPO DE ACESSO', 'TIPO DE ACESSO'),
            ('BLOCO IP', 'BLOCO IP'),
            ('DUPLA ABORDAGEM', 'DUPLA ABORDAGEM'),
            ('ENTREGA RB', 'ENTREGA RB'),
        ]

        for coluna, rotulo in mapa_campos_tecnicos:
            valor = limpar_texto(linha.get(coluna))
            if not valor:
                continue
            if coluna in {'DUPLA ABORDAGEM', 'ENTREGA RB'}:
                valor = normalizar_sim_nao(valor)
            linhas.append(f"{rotulo}: {valor}")

        return "\n".join(linhas) if linhas else "Importado via Automações IXC"

    # Resgata o ID do plano e já passa pela limpeza
    plano_id = limpar_id(linha.get('Plano_ID'))

    logradouro = limpar_texto(linha.get('End_Logradouro'))
    numero = limpar_id(linha.get('End_Numero'))

    # MONTAGEM DO PACOTE DE DADOS (PAYLOAD):
    observacao_cliente = montar_observacao_cliente()
    cidade_id_ixc = obter_cidade_id_ixc()

    if cidade_id_ixc is None:
        return False, "Campo End_Cidade_ID_IXC invalido. Informe o ID numerico da cidade no IXC.", None

    payload = {
        "id_cliente": limpar_id(linha.get('Cliente_ID')),
        "id_contrato": limpar_id(linha.get('Login_Contrato_ID')),

        # --- A CORREÇÃO FINAL DO PLANO ---
        # O IXC possui duas tabelas que se cruzam: Planos e Grupos.
        # Estamos enviando nos dois campos para garantir que ele aceite.
        "id_plano": plano_id,
        "id_grupo": plano_id,

        "login": limpar_login(linha.get('Login_Login')),
        "senha": str(linha.get('Login_Senha_Cliente', '')).strip(),
        "confirmar_senha": str(linha.get('Login_Senha_Cliente', '')).strip(),

        # --- TIPO DE CONEXÃO ---
        # F = Fibra. Também enviamos duplicado para cobrir qualquer versão do IXC.
        "tipo_conexao": "F",
        "tipo_conexao_mapa": "F",

        # --- CAMPOS TÉCNICOS OBRIGATÓRIOS DO IXC ---
        "autenticacao_por_mac": "P",  # P = Padrão
        "ativo": "S",                 # S = Sim
        "autenticacao": "L",          # L = Autenticação por Login/Senha
        "login_simultaneo": "1",      # Apenas 1 conexão por vez permitida
        "senha_md5": "N",             # N = Não
        "fixar_ip": "H",              # H = Herdar do plano
        "auto_preencher_ip": "H",     # H = Herdar
        "auto_preencher_mac": "H",    # H = Herdar
        "relacionar_ip_ao_login": "H",# H = Herdar
        "relacionar_mac_ao_login": "H",# H = Herdar
        "tipo_vinculo_plano": "D",    # D = Vinculado diretamente
        "endereco_padrao_cliente": "N", # N = Não (Força o IXC a ler o nosso CEP perfeito)

        # --- DADOS DE ENDEREÇO ---
        "cep": somente_numeros(linha.get('End_CEP')),
        "bairro": limpar_texto(linha.get('End_Bairro')),
        "cidade": cidade_id_ixc,
        "endereco": logradouro,
        "numero": numero,
        "referencia": limpar_texto(linha.get('End_Referencia')),
        "obs": observacao_cliente
    }

    # 🚀 RAIO-X NO TERMINAL:
    # Isso vai imprimir no seu log do Docker EXATAMENTE o que está indo para o IXC.
    print(f"\n--- DEBUG: ENVIANDO LOGIN {payload['login']} ---")
    print(json.dumps(payload, indent=2))
    print("---------------------------------------------------\n")

    try:
        # Envio da requisição (POST) ao IXC via IXCClient
        status_code, resposta_json = IXCClient().escrever("radusuarios", payload)

        # Se o servidor respondeu (Status 200 = OK)
        if status_code == 200 and isinstance(resposta_json, dict):
            if resposta_json.get('type') == 'success':
                id_ixc = resposta_json.get('id')
                _atualizar_endereco_tecnico(linha, observacao_cliente)
                return True, "Criado com sucesso!", id_ixc

            # Se a requisição chegou, mas o IXC negou
            return False, f"IXC Negou: {resposta_json.get('message')}", resposta_json.get('id')

        # Erro de rota ou indisponibilidade
        return False, f"Erro HTTP {status_code}", None

    except Exception as e:
        # Erro de execução do Python
        return False, f"Erro Técnico: {str(e)}", None
