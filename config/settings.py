"""
Configuracoes do Gerenciador Pos-Venda (v1.0.0).

Reaproveita o padrao de configuracao via variaveis de ambiente do
`modulo-posVenda` original (python-decouple + .env, RNF-05), mas com banco
de dados proprio e independente daquele sistema (requisitos.md, bloco 0).

Decisao tecnica (CLAUDE.md Sec. 9 - reversivel e de baixo risco): o banco
local de desenvolvimento e SQLite por padrao, para o projeto "subir
localmente" (FEAT-001) sem depender de um servidor MySQL configurado. O
schema documentado em docs_gerenciador_pos_venda/modelo-dados.md usa sintaxe
MySQL (ponto de partida do modulo-posVenda) - basta definir DB_ENGINE=mysql
no .env, com as credenciais correspondentes, para apontar para MySQL em
outros ambientes (decisao final de infraestrutura fica com o DevOps,
FEAT-012).
"""

from pathlib import Path

from decouple import config
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config("SECRET_KEY")

# SEGURANCA: nunca True em producao (CLAUDE.md Sec. 6).
DEBUG = config("DEBUG", default=False, cast=bool)

ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",  # FEAT-026: separador de milhar em R$ (filtro intcomma)

    # Apps do Gerenciador Pos-Venda
    "apps.core",
    "apps.escolas",
    "apps.ri",
    "apps.auditoria",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # FEAT-029/RN-045: precisa vir depois de AuthenticationMiddleware
    # (usa request.user).
    "apps.core.middleware.AcessoLiberadoMiddleware",
    # FEAT-011/RN-006: precisa vir depois de AuthenticationMiddleware
    # (usa request.user) — registra em auditoria qualquer erro não
    # tratado durante uma requisição.
    "apps.auditoria.middleware.AuditoriaErroMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ==========================================
# BANCO DE DADOS
# ==========================================
DB_ENGINE = config("DB_ENGINE", default="sqlite")

if DB_ENGINE == "mysql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": config("DB_NAME", default="gerenciador_posvenda"),
            "USER": config("DB_USER", default="posvenda_app"),
            "PASSWORD": config("DB_PASSWORD", default=""),
            "HOST": config("DB_HOST", default="127.0.0.1"),
            "PORT": config("DB_PORT", default="3306"),
            "OPTIONS": {
                "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
                "charset": "utf8mb4",
            },
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_USER_MODEL = "core.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"

# ==========================================
# AUTENTICACAO VIA ACTIVE DIRECTORY (RN-043, FEAT-027)
# ==========================================
# `django_auth_ldap`/`python-ldap` reaproveitados do `modulo-posVenda`
# (ADR-002), com `ModelBackend` como fallback. `USE_AD_AUTH=false`
# (padrao) mantem 100% login local, sem nenhuma chamada ao AD. Import
# feito dentro do `if` (nao no topo do arquivo) para nao quebrar o projeto
# enquanto as libs de sistema/pip ainda nao forem reintroduzidas pelo
# DevOps (`requirements.txt`/`Dockerfile`, pendencia registrada na
# ADR-002/checklist FEAT-027).
USE_AD_AUTH = config("USE_AD_AUTH", default=False, cast=bool)

if USE_AD_AUTH:
    try:
        import ldap
        from django_auth_ldap.config import LDAPSearch

        # Certificado do AD e emitido por CA interna, ausente na cadeia de
        # confianca do container (confirmado em 2026-08-28: bind falhava com
        # "certificate verify failed (unable to get local issuer
        # certificate)"). Para URI ldaps://, o handshake TLS ocorre dentro
        # de ldap.initialize(), antes de AUTH_LDAP_CONNECTION_OPTIONS ser
        # aplicado na conexao - por isso a verificacao precisa ser
        # desativada aqui tambem, como opcao global do modulo ldap (mesma
        # solucao ja usada em producao no modulo-posVenda, decisao
        # confirmada pelo usuario - mantem a conexao criptografada via
        # LDAPS, so nao valida a cadeia do certificado).
        ldap.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_NEVER)
        ldap.set_option(ldap.OPT_X_TLS_NEWCTX, 0)

        AUTHENTICATION_BACKENDS = [
            "django_auth_ldap.backend.LDAPBackend",
            "django.contrib.auth.backends.ModelBackend",
        ]

        AUTH_LDAP_SERVER_URI = config("AD_SERVER_URI", default="")
        AUTH_LDAP_BIND_DN = config("AD_BIND_DN", default="")
        AUTH_LDAP_BIND_PASSWORD = config("AD_BIND_PASSWORD", default="")
        AUTH_LDAP_USER_SEARCH = LDAPSearch(
            config("AD_USER_SEARCH_BASE", default=""),
            ldap.SCOPE_SUBTREE,
            "(sAMAccountName=%(user)s)",
        )
        AUTH_LDAP_USER_DOMAIN = config("AD_DEFAULT_DOMAIN", default="")

        # A sincronizacao de e-mail/nome pos-login e feita pela RN-044
        # (apps/integracoes/ad/ad_sync.py), nao pelo mapeamento automatico
        # do django-auth-ldap - por isso nao atualiza o usuario a cada
        # autenticacao aqui. O perfil (RN-004/RN-043) nao vem do AD: o
        # usuario criado automaticamente recebe o valor padrao do campo
        # `perfil` (Analista, apps/core/models.py), nunca Administrador.
        AUTH_LDAP_ALWAYS_UPDATE_USER = False
        AUTH_LDAP_MIRROR_GROUPS = False
        AUTH_LDAP_CONNECTION_OPTIONS = {
            ldap.OPT_REFERRALS: 0,
            ldap.OPT_X_TLS_REQUIRE_CERT: ldap.OPT_X_TLS_NEVER,
            ldap.OPT_X_TLS_NEWCTX: 0,
        }
    except ImportError:
        # Bibliotecas ainda nao instaladas (pendencia de DevOps) - degrada
        # para login local, sem erro visivel ao usuario.
        USE_AD_AUTH = False
        AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]
else:
    AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Fortaleza"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS", default="http://localhost:8000,http://127.0.0.1:8000"
).split(",")

# ==========================================
# E-MAIL (RF-07/RF-08 - caixa propria do financeiro; implementado no
# FEAT-008/FEAT-009 do checklist)
# ==========================================
EMAIL_BACKEND = config("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = config("EMAIL_HOST", default="")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="posvendas@megainfraestrutura.com.br")

# FEAT-009 (RF-08/RF-19): leitura da resposta do financeiro na mesma caixa,
# por polling (~5 min, architecture.md) via Microsoft Graph — IMAP com
# usuário/senha não funciona mais nessa caixa (Basic Auth aposentada pela
# Microsoft; confirmado em 2026-08-25 com a caixa real). Reaproveita só o
# *padrão* de código do modulo-posVenda; app do Azure é exclusivo deste
# sistema — nunca as credenciais de GRAPH_EMAIL_REPLIES_* (aquelas são do
# modulo-posVenda; usar as duas juntas violaria a independência entre os
# dois sistemas, decisão confirmada pelo usuário).
GRAPH_FINANCEIRO_ENABLED = config("GRAPH_FINANCEIRO_ENABLED", default=False, cast=bool)
GRAPH_FINANCEIRO_CLIENT_ID = config("GRAPH_FINANCEIRO_CLIENT_ID", default="")
GRAPH_FINANCEIRO_CLIENT_SECRET = config("GRAPH_FINANCEIRO_CLIENT_SECRET", default="")
GRAPH_FINANCEIRO_TENANT_ID = config("GRAPH_FINANCEIRO_TENANT_ID", default="")
GRAPH_FINANCEIRO_MAILBOX = config("GRAPH_FINANCEIRO_MAILBOX", default="")
GRAPH_FINANCEIRO_TIMEOUT = config("GRAPH_FINANCEIRO_TIMEOUT", default=30, cast=int)
GRAPH_FINANCEIRO_INITIAL_LOOKBACK_DAYS = config("GRAPH_FINANCEIRO_INITIAL_LOOKBACK_DAYS", default=15, cast=int)
GRAPH_FINANCEIRO_MAX_PAGES_PER_RUN = config("GRAPH_FINANCEIRO_MAX_PAGES_PER_RUN", default=20, cast=int)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
        # FEAT-033 (ADR-004/RN-056): progresso do RPA EACE no terminal
        # (login, navegacao, upload) - sem isso INFO nao aparece no console.
        "apps.integracoes.eace": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
