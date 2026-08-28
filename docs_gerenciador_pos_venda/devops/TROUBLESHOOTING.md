# Troubleshooting — Gerenciador Pós-Venda
_Última atualização: 2026-08-28_

### Imagem/logo/CSS não aparece em homologação ou produção (ícone de imagem quebrada)

**Caso real confirmado (2026-08-28, servidor `192.168.90.109:8000`):**
`curl` direto no servidor mostrou `Server: WSGIServer/0.2` (é o
`manage.py runserver`, não Gunicorn) e `/static/img/logo1.png` devolvendo
404 no formato de página de erro simples (não a de debug) — ou seja,
`DEBUG=False` nesse `runserver`. `runserver` só serve estático sozinho com
`DEBUG=True` (proibido fora do local, CLAUDE.md Sec. 6) ou com a flag
`--insecure`; sem nenhum dos dois, e sem Nginx/WhiteNoise, `/static/`
nunca é servido. Esse servidor ainda roda o `docker-compose.yml` local
(pensado só para desenvolvimento) em vez do `docker-compose.hml.yml` —
migração pendente, ver `DEPLOYMENT.md`.

Causa mais comum, de forma geral: nada servindo `/static/` na frente da
aplicação. No ambiente local isso não acontece porque o
`docker-compose.yml` roda `runserver` com `DEBUG=True`; em
homologação/produção (`docker-compose.hml.yml`) quem serve é o serviço
`nginx` (`docker/nginx/homolog.conf`), lendo os volumes
`staticfiles_hml`/`media_hml`.

Checar, nessa ordem:
1. `docker compose -f docker-compose.hml.yml ps` — o serviço `nginx` está
   `Up`?
2. O `collectstatic` já rodou depois do último deploy? (`scripts/
   deploy_homolog.sh` roda isso — se o deploy foi feito na mão sem passar
   pelo script, o volume `staticfiles_hml` pode estar vazio ou
   desatualizado.) Rodar manualmente: `docker compose -f
   docker-compose.hml.yml exec web python manage.py collectstatic
   --noinput`.
3. `docker compose -f docker-compose.hml.yml exec nginx ls /app/staticfiles`
   — os arquivos estão lá?
4. Testar a URL direto: `curl -I http://<host>:<HML_HTTP_PORT>/static/img/logo1.png`
   — deve vir `200`, `Content-Type: image/png`.

### `db` nunca fica saudável / `web` reinicia em loop esperando o banco

`docker-compose.hml.yml` só sobe `web`/`email_scheduler` depois do
healthcheck do `db` passar (`condition: service_healthy`). Se travar:
`docker compose -f docker-compose.hml.yml logs db` — geralmente é
`MYSQL_ROOT_PASSWORD`/`DB_PASSWORD` divergente entre um volume de dado já
existente (senha antiga) e o `.env.hml` atual (senha nova). Não há reset
automático do volume — decisão de apagar `posvenda_db_data_hml` é
destrutiva e exige autorização explícita (regra do DevOps).

### Deploy automático (push na branch `homolog`) não dispara ou falha no job "deploy"

Confirmar que os secrets (`HML_HOST`, `HML_USER`, `HML_PORT`,
`HML_SSH_KEY`) estão cadastrados no GitHub (`CI_CD.md`) — sem eles o job
"deploy" falha na conexão SSH, mesmo com o "ci" verde. O job "deploy" só
roda em push direto na branch `homolog`, nunca em Pull Request.
