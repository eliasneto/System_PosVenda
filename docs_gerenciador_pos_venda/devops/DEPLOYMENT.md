# Deploy — Gerenciador Pós-Venda
_Última atualização: 2026-09-03_

> Este documento só prepara/registra os comandos. Executar em produção
> exige autorização explícita do Orquestrador antes de cada rodada
> (regra do DevOps, `.claude/agents/devops.md`, "Regra de Produção") — o
> agente DevOps nunca dispara isso sozinho, mesmo tendo o passo a passo
> pronto.

## Homologação — fluxo automático (quando o servidor existir)

Pipeline `.github/workflows/homolog.yml`: push direto na branch `homolog`
→ CI (`check`/`test`/build) → se passar, conecta via SSH e roda
`scripts/deploy_homolog.sh` no servidor. Secrets necessários no GitHub:
`HML_HOST`, `HML_USER`, `HML_PORT`, `HML_SSH_KEY` (ver `CI_CD.md`).

Hoje isso ainda não roda de ponta a ponta: não há servidor de
homologação dedicado provisionado (pendência aberta em
`architecture.md`, "Decisões Pendentes"). O que existe em produção
(`192.168.90.109`) foi uma correção pontual (`ADR-003`), não este
pipeline.

Equivalente manual do que o script faz, para rodar direto num servidor
com `.env.hml` já preenchido — um servidor de homologação **novo**, sem
o histórico de volume do `192.168.90.109` (seção abaixo), não precisa do
`docker-compose.hml.override.yml`:

```bash
cd /home/Sistem_PosVenda   # ou o caminho real do checkout
git fetch origin homolog
git reset --hard origin/homolog
docker compose -f docker-compose.hml.yml --env-file .env.hml up -d --build
docker compose -f docker-compose.hml.yml --env-file .env.hml up -d --wait db
docker compose -f docker-compose.hml.yml --env-file .env.hml exec -T web python manage.py migrate --noinput
docker compose -f docker-compose.hml.yml --env-file .env.hml exec -T web python manage.py collectstatic --noinput
docker compose -f docker-compose.hml.yml --env-file .env.hml ps
```

---

## Produção (`192.168.90.109`) — deploy manual, passo a passo

**Não existe pipeline automático para este servidor.** Toda alteração
até hoje foi manual, sob autorização explícita do usuário/Orquestrador
(`ADR-003`). Credenciais de acesso (SSH e login da aplicação) ficam no
arquivo local `ServidorEACE` (raiz do repositório, **não versionado** —
já sinalizado como risco de segurança em `CONTAINERS.md`/`checklist.md`;
nunca copiar o conteúdo dele para um arquivo commitado).

**Confirmado em 2026-09-02: o stack `hml` (com Nginx) é o único no ar.**
O stack "plain" (`docker-compose.yml`, `sistema_posvenda-*`) chegou a
assumir a produção sozinho por causa de um incidente (ver
`TROUBLESHOOTING.md`, "Stack 'plain' assumiu a produção sozinho") — está
parado e com `restart: no` desde então, para não voltar a acontecer num
reboot. Antes de qualquer deploy, confirmar com `docker ps -a | grep
sistema_posvenda` que `sistema_posvenda-db-1`/`sistema_posvenda-web-1`
(sem `_hml`) continuam parados.

Caminho no servidor: `/home/Sistem_PosVenda`. Branch do checkout real:
**`feat-002-importar-escolas-planilha`**, não `homolog` — confirme com
`git branch --show-current` antes de qualquer comando, porque isso pode
mudar. Stack em uso desde a `ADR-003`: `docker-compose.hml.yml` (não
mais o `docker-compose.yml` de desenvolvimento). Porta publicada nesse
servidor: `8000` (via `HML_HTTP_PORT` no `.env.hml` de lá — diferente do
padrão `8010` do `docker-compose.hml.yml`, para preservar a URL que já
estava em uso).

**Obrigatório em todo deploy neste servidor — `docker-compose.hml.override.yml`.**
Sem ele, o `docker compose up` cria um volume de banco **novo e vazio**
em vez de usar o volume real (incidente confirmado em 2026-08-31, ver
`TROUBLESHOOTING.md`). Se o arquivo não existir mais em
`/home/Sistem_PosVenda` (ele não é commitado — é local do servidor),
recriar antes de qualquer `up`:

```bash
cat > /home/Sistem_PosVenda/docker-compose.hml.override.yml <<'EOF'
volumes:
  posvenda_db_data_hml:
    external: true
    name: sistema_posvenda_posvenda_db_data
EOF
```

Todo comando `docker compose` deste servidor, **sempre**, com os dois
arquivos:
```
docker compose -f docker-compose.hml.yml -f docker-compose.hml.override.yml --env-file .env.hml ...
```

### 0. Autorização (não pular)

Confirmar, antes de qualquer comando: quem autorizou, o que exatamente
está sendo alterado, e que as condições abaixo (backup, sem comando
destrutivo) foram aceitas — mesmo padrão da `ADR-003`. Sem isso, parar
aqui.

### 1. Backup do banco (obrigatório, sempre)

```bash
cd /home/Sistem_PosVenda
mkdir -p backups
docker compose -f docker-compose.hml.yml -f docker-compose.hml.override.yml --env-file .env.hml exec -T db \
  sh -c 'mysqldump --all-databases -u root -p"$MYSQL_ROOT_PASSWORD"' \
  | gzip > backups/backup_pre_deploy_$(date +%Y%m%d_%H%M%S).sql.gz

# Valida que o backup não está corrompido antes de seguir:
gzip -t backups/backup_pre_deploy_*.sql.gz
```

Não seguir para o passo 2 se o `gzip -t` falhar.

### 2. Atualizar código

```bash
git status --short          # confirma que não há alteração local não commitada
git fetch origin feat-002-importar-escolas-planilha
git reset --hard origin/feat-002-importar-escolas-planilha
git log --oneline -3        # confere que o commit esperado chegou
```

Se `git status --short` mostrar algo, **parar** — investigar antes de
sobrescrever (o `reset --hard` descarta qualquer alteração local).

### 3. Subir/atualizar containers (reaproveitando o volume existente)

```bash
docker compose -f docker-compose.hml.yml -f docker-compose.hml.override.yml --env-file .env.hml up -d --build
docker compose -f docker-compose.hml.yml -f docker-compose.hml.override.yml --env-file .env.hml up -d --wait db
docker compose -f docker-compose.hml.yml -f docker-compose.hml.override.yml --env-file .env.hml restart nginx
```

Nunca usar `down -v` nem remover volume nesta etapa — o dado real do
projeto (2.622 escolas, RIs, faturamento) está nele.

**O `restart nginx` no final não é opcional** — o Nginx resolve o
hostname `web` (DNS interno do Docker) só uma vez, quando o próprio
processo dele inicia, e guarda esse IP em memória. Como o `web` quase
sempre é recriado no `up --build` (o Nginx normalmente não, se a imagem
dele não mudou), sem esse `restart` o Nginx continua apontando pro IP
antigo e o site responde `502 Bad Gateway` (incidente confirmado em
2026-09-02, ver `TROUBLESHOOTING.md`).

### 4. Migrations

```bash
docker compose -f docker-compose.hml.yml -f docker-compose.hml.override.yml --env-file .env.hml exec -T web python manage.py migrate --noinput
```

Ler a saída com atenção — é o principal sinal de que o volume certo foi
usado:
- Só as migrations realmente novas devem aparecer com `Applying ...
  OK` (ex.: `ri.0022_riitemrelatorioeace_status_escola`).
- Se aparecer a lista inteira desde `contenttypes.0001_initial`/
  `auth.0001_initial`, o banco está **vazio** — sinal de que o
  `docker-compose.hml.override.yml` não foi incluído no comando (ver
  aviso no topo desta seção). Parar e corrigir antes de seguir; não
  confiar num deploy que migrou do zero neste servidor.

### 5. Collectstatic

```bash
docker compose -f docker-compose.hml.yml -f docker-compose.hml.override.yml --env-file .env.hml exec -T web python manage.py collectstatic --noinput
```

### 6. Validar

```bash
docker compose -f docker-compose.hml.yml -f docker-compose.hml.override.yml --env-file .env.hml ps
curl -I http://192.168.90.109:8000/login/
curl -I http://192.168.90.109:8000/static/img/logo1.png
```

Confirmar: os 5 serviços (`db`, `web`, `nginx`, `email_scheduler`,
`rpa_eace_worker` — este último a partir da FEAT-033/`ADR-005`, ver
`CONTAINERS.md`) como `Up`; `/login/` e a logo devolvendo `200`. Login
real na aplicação (credencial em `ServidorEACE`) para conferir uma tela
com dado (ex.: grid de INEPs) antes de considerar concluído.

**Antes do primeiro deploy com o `rpa_eace_worker`:** preencher
`EACE_URL`/`EACE_USUARIO`/`EACE_SENHA` reais no `.env.hml` do servidor —
sem isso o container sobe, mas a fila nunca processa nada (log mostra erro
de credencial ausente a cada passada). Ver `.env.hml.example`.

### Rollback

Se algo quebrar depois do passo 3:

```bash
# Código: volta pro commit anterior e reconstrói
git reset --hard <commit_anterior_confirmado_no_passo_2>
docker compose -f docker-compose.hml.yml -f docker-compose.hml.override.yml --env-file .env.hml up -d --build

# Banco, só se a migração corrompeu dado (último recurso — derruba o
# estado atual do banco, use o backup do passo 1):
gunzip < backups/backup_pre_deploy_TIMESTAMP.sql.gz | \
  docker compose -f docker-compose.hml.yml -f docker-compose.hml.override.yml --env-file .env.hml exec -T db \
  sh -c 'mysql -u root -p"$MYSQL_ROOT_PASSWORD"'
```

Restaurar o banco é destrutivo (sobrescreve o estado atual) — só depois
de confirmar com quem autorizou o deploy.

## Acesso de consulta para terceiro (só leitura)

Pedido do usuário (2026-09-04): consultor externo precisa consultar dados
do banco de produção. Nunca compartilhar a credencial da própria
aplicação (`DB_USER`/`DB_PASSWORD` do `.env.hml`) para isso — usuário
próprio, só `SELECT`, fácil de revogar depois sem afetar o sistema. A
porta do MySQL nunca é exposta na interface externa do servidor — só no
loopback (`127.0.0.1:${HML_DB_DIAGNOSTICO_PORT:-3316}`, ver
`docker-compose.hml.yml`), alcançável de fora só via túnel SSH.

**1. Usuário do banco (rodar dentro do MySQL do servidor):**
```sql
CREATE USER '<usuario_consulta>'@'%' IDENTIFIED BY '<senha_forte_gerada>';
GRANT SELECT ON <NOME_DO_BANCO_REAL>.* TO '<usuario_consulta>'@'%';
FLUSH PRIVILEGES;
```
Conectar com (senha root em `.env.hml`, no servidor):
```bash
docker compose -f docker-compose.hml.yml -f docker-compose.hml.override.yml --env-file .env.hml exec db mysql -u root -p
```

**2. Publicar a porta de diagnóstico** (se ainda não estiver publicada —
depende do `up -d` mais recente já ter aplicado a mudança do
`docker-compose.hml.yml` que adicionou este `ports:` ao serviço `db`):
```bash
docker compose -f docker-compose.hml.yml -f docker-compose.hml.override.yml --env-file .env.hml up -d db
```

**3. Login SSH restrito, só para túnel (sem shell)** — no servidor, com a
chave pública do consultor:
```bash
sudo useradd -m -s /usr/sbin/nologin <usuario_consulta>
sudo mkdir -p /home/<usuario_consulta>/.ssh
sudo tee /home/<usuario_consulta>/.ssh/authorized_keys > /dev/null <<'EOF'
command="/bin/false",no-agent-forwarding,no-X11-forwarding,no-pty,permitopen="127.0.0.1:3316" <chave_publica_do_consultor>
EOF
sudo chown -R <usuario_consulta>:<usuario_consulta> /home/<usuario_consulta>/.ssh
sudo chmod 700 /home/<usuario_consulta>/.ssh
sudo chmod 600 /home/<usuario_consulta>/.ssh/authorized_keys
```
A restrição `command="/bin/false",...,permitopen="127.0.0.1:3316"` no
`authorized_keys` (não o shell `nologin` sozinho) é o que garante: essa
chave só abre túnel para a porta do banco, nunca um shell interativo nem
outro destino.

**4. O consultor conecta assim** (do lado dele):
```bash
ssh -N -L 3306:127.0.0.1:3316 <usuario_consulta>@192.168.90.109
```
e aponta o cliente MySQL dele para `127.0.0.1:3306` (local, do lado dele)
com o usuário/senha do passo 1, enquanto o túnel estiver aberto.

**Revogar depois:**
```sql
DROP USER '<usuario_consulta>'@'%';
```
```bash
sudo userdel -r <usuario_consulta>
```

## Ver também

- `CONTAINERS.md` — o que cada serviço faz e por quê.
- `CI_CD.md` — secrets e o pipeline de homologação.
- `TROUBLESHOOTING.md` — sintomas comuns (estático quebrado, `db` não
  sobe) e como diagnosticar.
