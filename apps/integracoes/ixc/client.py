"""Cliente HTTP único para a API do IXC — trazido de `IXC/client.py`
(cópia de referência do projeto sgpspeed) em 2026-09-23 para as automações
de Login (Endereços) e Atendimentos (`apps/ixc/`). Lê `IXC_URL`, `IXC_TOKEN`,
`IXC_SSL_VERIFY` e `IXC_TIMEOUT` do ambiente (`.env`, CLAUDE.md Sec. 6 —
nunca versionado com valor real)."""

import base64
import json
import os

import requests
import urllib3


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


DEFAULT_IXC_URL = "https://ixc.megainfraestrutura.com.br/webservice/v1"


def _parse_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "t", "sim", "s", "yes", "y"}


class IXCClient:
    def __init__(self, base_url=None, token=None, verify_ssl=None, timeout=None):
        self.base_url = (base_url or os.getenv("IXC_URL") or DEFAULT_IXC_URL).rstrip("/")
        self.token = token or os.getenv("IXC_TOKEN")
        if not self.token:
            raise RuntimeError(
                "IXC_TOKEN nao configurado. Defina a variavel de ambiente IXC_TOKEN "
                "ou informe o parametro token."
            )
        self.verify_ssl = (
            verify_ssl if verify_ssl is not None
            else _parse_bool(os.getenv("IXC_SSL_VERIFY"), default=False)
        )
        self.timeout = int(timeout or os.getenv("IXC_TIMEOUT") or 30)

    @property
    def headers_listar(self):
        token_b64 = base64.b64encode(self.token.encode("utf-8")).decode("utf-8")
        return {
            "Authorization": f"Basic {token_b64}",
            "Content-Type": "application/json; charset=utf-8",
            "ixcsoft": "listar",
        }

    @property
    def headers_write(self):
        token_b64 = base64.b64encode(self.token.encode("utf-8")).decode("utf-8")
        return {
            "Authorization": f"Basic {token_b64}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def post(self, endpoint, payload, include_ixcsoft=False):
        url = f"{self.base_url}/{str(endpoint).lstrip('/')}"
        try:
            response = requests.post(
                url,
                headers=self.headers_listar if include_ixcsoft else self.headers_write,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
        except requests.exceptions.Timeout:
            return 408, {"type": "error", "message": f"Timeout ao conectar com o IXC ({self.timeout}s)."}
        except requests.exceptions.ConnectionError as exc:
            return 503, {"type": "error", "message": f"Falha de conexao com o IXC: {exc}"}
        except requests.exceptions.RequestException as exc:
            return 500, {"type": "error", "message": f"Erro de rede ao acessar o IXC: {exc}"}

        try:
            body = response.json()
        except Exception:
            body = {"raw": response.text}

        return response.status_code, body

    def listar(self, endpoint, payload):
        return self.post(endpoint, payload, include_ixcsoft=True)

    def escrever(self, endpoint, payload):
        return self.post(endpoint, payload, include_ixcsoft=False)

    def put(self, endpoint, payload):
        url = f"{self.base_url}/{str(endpoint).lstrip('/')}"
        response = requests.put(
            url,
            headers=self.headers_write,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            verify=self.verify_ssl,
            timeout=self.timeout,
        )

        try:
            body = response.json()
        except Exception:
            body = {"raw": response.text}

        return response.status_code, body

    def delete(self, endpoint, payload=None):
        url = f"{self.base_url}/{str(endpoint).lstrip('/')}"
        response = requests.delete(
            url,
            headers=self.headers_write,
            data=json.dumps(payload or {}, ensure_ascii=False).encode("utf-8"),
            verify=self.verify_ssl,
            timeout=self.timeout,
        )

        try:
            body = response.json()
        except Exception:
            body = {"raw": response.text}

        return response.status_code, body
