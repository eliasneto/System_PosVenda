"""Administrador > Backup: exportar/importar o banco inteiro (mysqldump/
mysql), pedido do usuário para poder levar um retrato real de produção
para homologação. Usa o mesmo usuário de banco do Django (`DB_USER`,
escopo do banco atual) — nunca root, e nunca a senha no argv do processo
(`ps aux` mostraria) — sempre via variável de ambiente `MYSQL_PWD`.

Lê `connections["default"].settings_dict` (não `settings.DATABASES`
direto): o runner de teste do Django troca o nome do banco só ali
(`test_gerenciador_posvenda`) — ler `settings.DATABASES` faria os testes
desta feature rodarem `mysqldump`/`mysql` contra o banco de verdade.

Cliente MySQL/MariaDB desta imagem (ver `Dockerfile`, já instalado antes
desta feature) exige `--skip-ssl` para falar com o MariaDB do container
`db` (certificado autoassinado) e `--no-tablespaces` para não tentar um
privilégio (`PROCESS`) que o usuário do app não tem — nenhum dos dois
muda o conteúdo do dump, só evitam erro/aviso de conexão."""

import gzip
import json
import os
import re
import shutil
import subprocess
import zlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.db import connections

_NOME_ARQUIVO_VALIDO = re.compile(r"^[A-Za-z0-9_.-]+\.sql\.gz$")
_TAMANHO_PEDACO = 1024 * 256

_MYSQLDUMP_FLAGS = [
    "--skip-ssl",
    "--no-tablespaces",
    "--single-transaction",
    "--routines",
    "--triggers",
]
_MYSQL_FLAGS = ["--skip-ssl"]


class BackupError(Exception):
    """Erro ao exportar, importar ou manipular um backup do banco —
    mensagem já pronta para mostrar ao Administrador (nunca inclui a
    senha do banco, só o retorno de erro do próprio mysqldump/mysql)."""


@dataclass
class ArquivoBackup:
    nome: str
    tamanho_bytes: int
    criado_em: datetime
    usuario: str


def _configuracao_banco():
    banco = connections["default"].settings_dict
    if banco["ENGINE"] != "django.db.backends.mysql":
        raise BackupError("Este ambiente não usa MySQL — backup indisponível (só SQLite local).")
    return banco


def _env_mysql(senha):
    env = os.environ.copy()
    env["MYSQL_PWD"] = senha
    return env


def _pasta_backups():
    pasta = Path(settings.BACKUP_ROOT)
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def _caminho_metadado(caminho_backup):
    return caminho_backup.with_name(caminho_backup.name + ".meta.json")


def _gravar_metadado(caminho_backup, usuario):
    _caminho_metadado(caminho_backup).write_text(
        json.dumps({"usuario": usuario or ""}), encoding="utf-8"
    )


def _ler_metadado(caminho_backup):
    caminho_meta = _caminho_metadado(caminho_backup)
    if not caminho_meta.is_file():
        return {}
    try:
        return json.loads(caminho_meta.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def _mysqldump_bruto():
    """Roda o `mysqldump` e devolve (gerador de bytes crus, função a
    chamar no final para conferir o código de saída) — usado tanto pelo
    export em streaming quanto pelo backup de segurança gravado em
    disco, cada um decidindo separadamente como comprimir/gravar."""
    banco = _configuracao_banco()
    comando = [
        "mysqldump",
        *_MYSQLDUMP_FLAGS,
        "-h", banco["HOST"] or "127.0.0.1",
        "-P", str(banco["PORT"] or "3306"),
        "-u", banco["USER"],
        banco["NAME"],
    ]
    processo = subprocess.Popen(
        comando,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_env_mysql(banco["PASSWORD"]),
    )

    def pedacos():
        try:
            yield from iter(lambda: processo.stdout.read(_TAMANHO_PEDACO), b"")
        finally:
            processo.stdout.close()

    def conferir_saida():
        codigo = processo.wait()
        if codigo != 0:
            erro = processo.stderr.read().decode("utf-8", errors="replace")
            raise BackupError(f"mysqldump terminou com erro (código {codigo}): {erro.strip()}")

    return pedacos(), conferir_saida


def exportar_backup_chunks():
    """Gera os bytes .sql.gz do banco inteiro, sob demanda (usado pela
    view de download, `StreamingHttpResponse`) — nunca grava nada em
    disco, nada fica retido no servidor por essa ação. Comprime com
    `zlib` (`wbits=31` = formato gzip, RFC 1952) em vez de um 2º
    processo (`gzip`), só para não depender de outro binário externo só
    para comprimir o que já está sendo lido."""
    pedacos, conferir_saida = _mysqldump_bruto()
    compressor = zlib.compressobj(level=6, wbits=31)
    for bruto in pedacos:
        comprimido = compressor.compress(bruto)
        if comprimido:
            yield comprimido
    conferir_saida()
    yield compressor.flush()


def criar_backup_seguranca(usuario):
    """Backup automático ANTES de qualquer importação (proteção pedida
    pelo usuário) — grava em `settings.BACKUP_ROOT` (fora de
    `MEDIA_ROOT`, nunca servido pelo Nginx). Levanta `BackupError` sem
    deixar arquivo parcial quando o dump falha — a importação que chamou
    isto deve abortar também, nunca sobrescrever o banco sem essa rede
    de segurança confirmada.

    `usuario` (username de quem disparou a importação) fica gravado num
    arquivo `.meta.json` ao lado do `.sql.gz` — pedido do usuário
    (2026-09-17): a tela precisa mostrar quem fez cada importação."""
    pasta = _pasta_backups()
    agora = datetime.now()
    nome = f"seguranca_{agora:%Y%m%d_%H%M%S}.sql.gz"
    caminho = pasta / nome
    caminho_temporario = pasta / f".{nome}.tmp"
    pedacos, conferir_saida = _mysqldump_bruto()
    try:
        with gzip.open(caminho_temporario, "wb") as destino:
            for bruto in pedacos:
                destino.write(bruto)
        conferir_saida()
    except Exception:
        caminho_temporario.unlink(missing_ok=True)
        raise
    caminho_temporario.rename(caminho)
    _gravar_metadado(caminho, usuario)
    return caminho


def restaurar_backup(arquivo_upload):
    """Restaura `arquivo_upload` (Django `UploadedFile`, `.sql` ou
    `.sql.gz`) por cima do banco atual — SOBRESCREVE todo o conteúdo
    (o dump do `mysqldump` já inclui `DROP TABLE`/`CREATE TABLE` por
    tabela). Ao final, roda `migrate` (idempotente) para o schema ficar
    coerente com a versão do código deste ambiente, caso o backup seja
    de uma versão diferente. Levanta `BackupError` com a saída de erro
    do `mysql` quando a restauração falha — quem chamar decide se já
    rodou `criar_backup_seguranca` antes (a view de import garante isso)."""
    banco = _configuracao_banco()
    comando = [
        "mysql",
        *_MYSQL_FLAGS,
        "-h", banco["HOST"] or "127.0.0.1",
        "-P", str(banco["PORT"] or "3306"),
        "-u", banco["USER"],
        banco["NAME"],
    ]
    comprimido = arquivo_upload.name.lower().endswith(".gz")
    origem = gzip.GzipFile(fileobj=arquivo_upload) if comprimido else arquivo_upload
    conteudo_sql = origem.read()

    # `communicate(input=...)` (não escrever/fechar `stdin` na mão) evita
    # 2 problemas do jeito manual: deadlock se o `mysql` produzir mais
    # saída (avisos) do que cabe no buffer do pipe antes de eu terminar
    # de escrever, e o `ValueError: flush of closed file` que
    # `communicate()` dá quando `stdin` já foi fechado por fora antes de
    # chamá-lo (achado rodando a suíte de testes desta feature).
    processo = subprocess.Popen(
        comando,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_env_mysql(banco["PASSWORD"]),
    )
    _saida, erro = processo.communicate(input=conteudo_sql)
    codigo = processo.returncode
    if codigo != 0:
        raise BackupError(
            f"Falha ao importar o backup (código {codigo}): {erro.decode('utf-8', errors='replace').strip()}"
        )
    call_command("migrate", interactive=False, verbosity=0)


def listar_backups_seguranca():
    """Backups de segurança já gravados (mais recente primeiro) — só os
    criados por `criar_backup_seguranca`, nunca um `.tmp` de dump em
    andamento/abortado. `usuario` vem do `.meta.json` gravado junto;
    backup de antes desta feature (sem metadado) mostra "—"."""
    pasta = _pasta_backups()
    arquivos = []
    for caminho in pasta.glob("seguranca_*.sql.gz"):
        stat = caminho.stat()
        metadado = _ler_metadado(caminho)
        arquivos.append(
            ArquivoBackup(
                nome=caminho.name,
                tamanho_bytes=stat.st_size,
                criado_em=datetime.fromtimestamp(stat.st_mtime),
                usuario=metadado.get("usuario") or "—",
            )
        )
    arquivos.sort(key=lambda arquivo: arquivo.criado_em, reverse=True)
    return arquivos


def resolver_caminho_backup_seguranca(nome):
    """Valida `nome` contra o padrão esperado e garante que o caminho
    final continua dentro de `BACKUP_ROOT` — bloqueia path traversal
    (`../`) mesmo que o nome venha direto da URL, sem confiar só no
    regex."""
    if not _NOME_ARQUIVO_VALIDO.match(nome):
        return None
    pasta = _pasta_backups().resolve()
    caminho = (pasta / nome).resolve()
    if pasta != caminho.parent:
        return None
    if not caminho.is_file():
        return None
    return caminho


def excluir_backup_seguranca(nome):
    """Apaga um backup de segurança e seu `.meta.json`. NÃO exposto na
    tela (pedido do usuário, 2026-09-17: "feito tá feito" — um backup de
    segurança gravado nunca deve poder ser apagado pela interface); esta
    função existe só para uso interno (limpeza de testes, um futuro
    comando de manutenção de retenção)."""
    caminho = resolver_caminho_backup_seguranca(nome)
    if caminho is None:
        return False
    caminho.unlink()
    _caminho_metadado(caminho).unlink(missing_ok=True)
    return True


def espaco_livre_bytes():
    """Espaço livre no volume de `BACKUP_ROOT` — mostrado na tela para o
    Administrador ter noção se cabe importar um backup grande."""
    uso = shutil.disk_usage(_pasta_backups())
    return uso.free
