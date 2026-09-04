# auto_eace_nf

RPA em Python para automação do portal **EACE** (https://eace.org.br/login?login=login),
usando [Playwright](https://playwright.dev/python/) para controlar o navegador.

> O portal EACE é uma aplicação Bubble.io (SPA com bastante JavaScript). Por isso a
> automação é feita via navegador real (Chromium), e não por chamadas diretas de API.

## Requisitos

- Python 3.12+ (testado com 3.14)
- Windows (PowerShell)

## Instalação

```powershell
# 1. Criar e ativar o ambiente virtual
py -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Instalar dependências
pip install -r requirements.txt

# 3. Instalar o navegador do Playwright
python -m playwright install chromium
```

## Configuração

Copie o arquivo de exemplo e preencha com suas credenciais:

```powershell
Copy-Item .env.example .env
```

Edite o `.env`:

| Variável        | Descrição                                              |
|-----------------|--------------------------------------------------------|
| `EACE_URL`      | URL de login do portal                                 |
| `EACE_USUARIO`  | Usuário de acesso                                      |
| `EACE_SENHA`    | Senha de acesso                                        |
| `HEADLESS`      | `false` mostra o navegador, `true` roda em segundo plano |
| `TIMEOUT_MS`    | Timeout padrão das ações (ms)                          |

> O `.env` contém credenciais e **não deve ser versionado** (já está no `.gitignore`).

## Execução

```powershell
.\.venv\Scripts\Activate.ps1
python src\main.py
```

Atualmente o script abre a página de login, aguarda o carregamento e salva um
print em `screenshots/login.png`. Próximos passos: preencher o login, navegar
no portal e automatizar as tarefas de NF.

## Estrutura

```
auto_eace_nf/
├── .venv/                # ambiente virtual (não versionado)
├── src/
│   ├── config.py         # carrega configurações do .env
│   ├── logger.py         # configuração de logs (loguru)
│   └── main.py           # ponto de entrada do RPA
├── logs/                 # logs de execução (não versionado)
├── screenshots/          # prints de tela (não versionado)
├── output/               # arquivos gerados (não versionado)
├── .env.example          # modelo de configuração
├── requirements.txt
└── README.md
```
