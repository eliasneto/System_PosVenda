# Deploy rápido — commit, push e pull no servidor

Roteiro fixo para quando o usuário pedir **"commit, push e pull"** (ou
"pull, build e valida"). Não precisa analisar o projeto nem rodar a suíte de
testes: siga os passos abaixo na ordem. Credenciais ficam só em
`ServidorEACE.md` (raiz, fora do git) — nunca copiar para cá, para commit
ou para a resposta.

## 1. Commit (máquina local)

```bash
git add -A
git reset -q -- doc/apresentacao "doc/EU preciso criar uma apresentação p.txt"
git diff --cached --name-only | grep -i -E "servidor|\.env|sqlite|media/|backups/"   # tem que sair vazio
git commit -F - <<'EOF'
<Resumo em português, 1 linha>

- <o que mudou, em tópicos curtos>

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
```

- Nunca versionar: `ServidorEACE.md`, `.env*` com valores reais, `db.sqlite3`,
  `media/`, `backups/`, planilhas/PDFs/prints com dado real de negócio
  (`doc/apresentacao/`, prints de NF/e-mail/planilha do financeiro).
- Mensagem em português; `[FEAT-XXX]` no início quando existir a feature.

## 2. Push

```bash
git push origin "$(git branch --show-current)"
```

O servidor usa a **mesma branch** que estiver com checkout lá (hoje
`feat-002-importar-escolas-planilha`).

## 3. Backup do banco (servidor) — sempre antes do deploy

O deploy roda `migrate`, e migração de dado não tem volta simples. Leva ~10 s:

```bash
python scripts/ssh_eace.py "cd /home/Sistem_PosVenda && mkdir -p backups && ARQ=backups/pre_deploy_\$(git rev-parse --short origin/\$(git rev-parse --abbrev-ref HEAD))_\$(date +%Y%m%d_%H%M%S).sql.gz && docker exec sistema_posvenda_hml-db-1 sh -c 'exec mysqldump --single-transaction --routines --triggers -uroot -p\"\$MYSQL_ROOT_PASSWORD\" --all-databases' 2>/dev/null | gzip > \$ARQ && ls -la \$ARQ && gunzip -c \$ARQ | tail -1"
```

A última linha precisa ser `-- Dump completed on ...`.

## 4. Pull + build + migrate (servidor)

Script oficial (`scripts/deploy_homolog.sh`): `git reset --hard` para o
commit publicado, `up -d --build`, restart do Nginx, `migrate`,
`collectstatic`.

```bash
python scripts/ssh_eace.py "cd /home/Sistem_PosVenda && bash scripts/deploy_homolog.sh 2>&1 | tail -40"
```

## 5. Validação (servidor)

```bash
python scripts/ssh_eace.py "cd /home/Sistem_PosVenda && C='docker compose -f docker-compose.hml.yml -f docker-compose.hml.override.yml --env-file .env.hml' && git log --oneline -1 && curl -s -o /dev/null -w 'login %{http_code}\n' http://127.0.0.1:8000/login/ && \$C ps && \$C exec -T web python manage.py showmigrations 2>/dev/null | grep -c '\[ \]' && \$C logs --since 2m rpa_eace_worker 2>&1 | tail -3"
```

Esperado: commit novo no topo, `login 200`, todos os containers `Up`
(`db` healthy), `0` migrações pendentes, worker mostrando
`Fila vazia - nada para processar.` (ou processando algo).

## Alarmes falsos já conhecidos

- **Erro "Table ... doesn't exist" / "Unknown column" no log do `web`
  logo depois do deploy**: requisição que caiu entre o container novo subir
  e o `migrate` rodar. Só é problema se continuar acontecendo depois do
  horário da migração.
- **502 Bad Gateway**: Nginx apontando para o IP antigo do `web` — o script
  já reinicia o Nginx; se aparecer, rodar `docker compose -f docker-compose.hml.yml -f docker-compose.hml.override.yml --env-file .env.hml restart nginx` no servidor.

## Se der errado

- Código: no servidor, `git reset --hard <commit anterior>` e depois
  `up -d --build` + `restart nginx` com os mesmos `-f`/`--env-file` do
  passo 5 (não rodar o `deploy_homolog.sh`, que volta para o último commit
  da branch). Ou, melhor: `git revert` local + push + passo 4.
- Banco: restaurar o `.sql.gz` do passo 3
  (`gunzip -c <arquivo> | docker exec -i sistema_posvenda_hml-db-1 sh -c 'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD"'`)
  — só com autorização explícita do usuário.
