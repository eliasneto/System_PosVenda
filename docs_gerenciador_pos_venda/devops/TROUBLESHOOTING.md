# Troubleshooting — Gerenciador Pós-Venda
_Última atualização: 2026-08-31_

### Banco vazio depois do deploy em produção (`migrate` aplica tudo do zero, escolas somem)

**Caso real confirmado (2026-08-31, servidor `192.168.90.109:8000`):**
deploy manual rodado só com `docker compose -f docker-compose.hml.yml
--env-file .env.hml up -d --build` (sem o
`docker-compose.hml.override.yml`) — o log mostrou `Volume
sistema_posvenda_hml_posvenda_db_data_hml Created` (volume **novo**) e o
`migrate` seguinte aplicou todas as migrations desde
`contenttypes.0001_initial`, sinal inequívoco de banco vazio (um banco
real, já em uso, não teria essas migrations pendentes). Sintoma
associado: 502 Bad Gateway do Nginx durante a troca de container.

**Causa:** este servidor reaproveita um volume de banco de antes da
FEAT-012 (`sistema_posvenda_posvenda_db_data`, sem sufixo `_hml`), via
`docker-compose.hml.override.yml` — arquivo local do servidor, não
commitado (ver `DEPLOYMENT.md`). Rodar `docker compose` sem incluir esse
arquivo faz o Docker criar um volume novo (nome derivado do
`docker-compose.hml.yml` puro) em vez de usar o existente.

**Os dados não foram perdidos** — o volume antigo não é apagado por um
`up`, só fica sem uso. Recuperação: `docker compose ... down` (sem `-v`),
recriar o `docker-compose.hml.override.yml` (conteúdo em
`DEPLOYMENT.md`) e subir de novo incluindo os dois `-f`. Confirmar com
`migrate` (só as migrations realmente novas devem aparecer) e com a
contagem de `Escola` (2.622).

**Prevenção:** todo comando `docker compose` neste servidor usa os dois
`-f` (`docker-compose.hml.yml` **e** `docker-compose.hml.override.yml`)
— nunca só o primeiro. Ver `DEPLOYMENT.md`, seção "Produção".

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

### Login via Active Directory não funciona em homologação (FEAT-027/RN-043)

**Caso real confirmado (2026-08-31, servidor `192.168.90.109:8000`):** login
com conta do AD falhava silenciosamente (formulário recarregava com erro,
sem 500) mesmo com `python-ldap`/`django-auth-ldap` instalados e rede
liberada até o AD.

**Causa:** as credenciais reais de AD (`AD_SERVER_URI`, `AD_BIND_DN`,
`AD_BIND_PASSWORD`, `AD_USER_SEARCH_BASE`, `AD_DEFAULT_DOMAIN`,
`USE_AD_AUTH=true`) tinham sido preenchidas só no `.env` (usado pelo stack
`docker-compose.yml` "plain"), não no `.env.hml` (usado pelo stack que
efetivamente serve `:8000`, via `docker-compose.hml.yml`). Com
`USE_AD_AUTH=false`/valores `TODO` no `.env.hml`, `config/settings.py`
(linha ~140) nunca ativa o `LDAPBackend` — login cai só no `ModelBackend`
local, sem erro visível (comportamento intencional do `except ImportError`
e do fallback, ver comentário no próprio `settings.py`).

**Diagnóstico:** `docker exec <container-web> printenv | grep AD_` mostra
os valores efetivamente carregados pelo container — comparar com o que
está em `.env.hml` no host, não assumir que bate com o `.env`.

**Correção:** copiar as mesmas chaves `AD_*`/`USE_AD_AUTH` do `.env` para o
`.env.hml` (mesma conta de serviço, decisão já registrada em
`architecture.md`/ADR-002) e recriar o `web`:
`docker compose -f docker-compose.hml.yml -f docker-compose.hml.override.yml --env-file .env.hml up -d --force-recreate web`.
Validar com um bind de teste da conta de serviço (não usar credencial de
usuário real no teste) antes de considerar resolvido.

**Atenção ao recriar `web`/`db` neste servidor:** `--force-recreate` num
serviço pode arrastar o `db` junto se o hash de config mudar — sempre usar
os dois `-f` (ver entrada abaixo e a de "Banco vazio depois do deploy").

### Dois stacks (`sistema_posvenda-*` "plain" e `sistema_posvenda_hml-*`) disputando o mesmo volume de banco

**Caso real confirmado (2026-08-31):** ao recriar `sistema_posvenda_hml-db-1`
depois de uma correção de `.env.hml`, o container ficou `unhealthy` com
`[ERROR] [InnoDB] Unable to lock ./ibdata1 error: 11` em loop.

**Causa:** o projeto "plain" (`docker-compose.yml`, sem `_hml` no nome do
container) e o projeto de homologação (`docker-compose.hml.yml` +
`docker-compose.hml.override.yml`) estavam **os dois** apontando para o
mesmo volume externo `sistema_posvenda_posvenda_db_data`. MySQL/InnoDB só
permite um processo com o arquivo `ibdata1` travado por vez — o segundo
container a tentar abrir o banco fica em loop de retry até desistir. Não há
corrupção de dado (InnoDB só lê o lock, não escreve nada além disso).

**Diagnóstico:**
`docker inspect <container-db> --format '{{range .Mounts}}{{.Name}}{{end}}'`
nos dois containers de banco — se o `.Name` do volume for igual nos dois,
é disputa de lock, não problema de configuração do MySQL em si.

**Correção aplicada:** `docker compose -f docker-compose.yml stop db` no
projeto "plain" (não remove container nem volume — reversível com `start`
a qualquer momento), liberando o lock para o `db` de homologação assumir o
volume real. Confirmar dado intacto depois:
`docker exec <web> python manage.py shell -c "from apps.core... Escola.objects.count()"`
(esperado: 2.622, mesma contagem da entrada "Banco vazio depois do deploy"
acima).

**Pendência:** os dois stacks não deveriam coexistir usando o mesmo volume
— decidir com o Orquestrador/usuário se o stack "plain" ainda é necessário
neste servidor (seu `web` já estava parado, só `db` e `email_scheduler`
ligados) ou se deve ser desativado definitivamente. Enquanto o `db` do
stack "plain" ficar parado, o `email_scheduler` desse stack roda sem banco.

### Erro 500 ao baixar/enviar a planilha de faturamento (`FileNotFoundError: doc/FATURAMENTO MATERIAS EACE.xlsx`)

**Caso real confirmado (2026-08-31, servidor `192.168.90.109:8000`):**
`GET /ri/<id>/financeiro/planilha/` e `POST /ri/<id>/financeiro/enviar/`
devolviam 500. Traceback do `web`:
`FileNotFoundError: [Errno 2] No such file or directory: '/app/doc/FATURAMENTO MATERIAS EACE.xlsx'`.

**Não é configuração de `.env`/`.env.hml`** — o caminho é fixo no código
(`apps/ri/services.py`, `CAMINHO_PLANILHA_FATURAMENTO_MODELO =
settings.BASE_DIR / "doc" / "FATURAMENTO MATERIAS EACE.xlsx"`), sem
variável de ambiente envolvida.

**Causa:** `doc/FATURAMENTO MATERIAS EACE.xlsx` está no `.gitignore` (é a
planilha-modelo real de faturamento, tratada como dado sensível/local, não
código). Como o deploy faz `git reset --hard origin/homolog`, esse arquivo
nunca chega ao servidor — e sem volume dedicado, some a cada rebuild da
imagem.

**Correção aplicada:** volume nomeado `doc_hml` montado em `/app/doc` no
serviço `web`, adicionado ao `docker-compose.hml.override.yml` (arquivo
local do servidor, não versionado — mesmo padrão já usado para o volume
externo do banco). O arquivo real foi copiado uma vez para dentro do volume
via `docker cp`. Validado rodando `gerar_planilha_faturamento()` direto
pelo `manage.py shell` (sem depender de sessão autenticada no navegador).

**Atenção:** `scripts/deploy_homolog.sh` só incluía `-f
docker-compose.hml.yml` nos comandos — sem o `-f
docker-compose.hml.override.yml`, o próximo deploy automático recriaria os
containers **sem** `doc_hml` nem o volume externo do banco, revertendo os
dois problemas desta página. Corrigido no script (inclui o override
automaticamente quando o arquivo existe no servidor) — mas essa correção
só entra em vigor depois de mergeada/publicada na branch `homolog`.

**Se o modelo da planilha mudar no futuro:** repetir o `docker cp` do
arquivo novo para dentro do container `web` em `/app/doc/` (o volume
`doc_hml` é persistente entre deploys, não precisa recriar o volume).

**O mesmo erro se repete no stack "plain" (produção), por um motivo
diferente:** esse `web` usa bind mount do diretório do servidor
(`.:/app` no `docker-compose.yml`), não uma imagem buildada — então não é
o volume `doc_hml` que falta, é o próprio `doc/` nem existir em
`/home/Sistem_PosVenda/` (nunca foi versionado, nunca foi copiado pra lá
manualmente). Correção: `mkdir -p /home/Sistem_PosVenda/doc` e colocar o
arquivo real ali direto (sem precisar de `docker cp` nem reiniciar
container — o bind mount reflete na hora). Resumindo: **stack hml usa
volume Docker nomeado (`docker cp`), stack "plain" usa arquivo direto no
host** — são dois lugares diferentes para o mesmo arquivo.

### Erro 500 ao enviar e-mail do financeiro (`SMTPAuthenticationError: 535`)

**Caso real confirmado (2026-08-31, servidor `192.168.90.109:8000`):**
`POST /ri/<id>/financeiro/enviar/` devolvia 500. Traceback do `web`:
`smtplib.SMTPAuthenticationError: (535, b'5.7.3 Authentication
unsuccessful ...')` no `smtp.office365.com`.

**Mesmo padrão do caso de AD acima:** `EMAIL_HOST_USER` no `.env.hml`
estava com o placeholder `TODO-preencher-usuario-real` (nunca preenchido)
— o Office365 rejeita autenticação com um usuário que não existe. A conta
real só tinha sido configurada no `.env` local de desenvolvimento do
usuário, nunca propagada para o `.env.hml` do servidor.

**Diagnóstico:** `docker exec <container-web> printenv | grep EMAIL_` —
comparar com o `.env.hml` do host; qualquer valor ainda `TODO` é a causa
mais provável de 535/401 em integração de e-mail.

**Correção:** sincronizar `EMAIL_HOST_USER`/`EMAIL_HOST_PASSWORD` (mesma
conta que já funciona localmente) para o `.env.hml` e recriar `web`/
`email_scheduler`:
`docker compose -f docker-compose.hml.yml -f docker-compose.hml.override.yml --env-file .env.hml up -d`.

**Validar sem enviar e-mail de verdade:** login SMTP isolado
(`smtplib.SMTP(...).login(user, senha)`, sem `sendmail`) direto no
container — confirma a credencial sem disparar mensagem real.

### Stack "plain" assumiu a produção sozinho, sem ninguém rodar `up` nele (logo/estático quebrado)

**Caso real confirmado (2026-09-02, servidor `192.168.90.109:8000`):** o
site em produção estava sendo servido pelo stack **"plain"**
(`sistema_posvenda-*`, sem Nginx) havia mais de 1 dia — não pelo stack
`hml` (`sistema_posvenda_hml-*`, com Nginx) que `DEPLOYMENT.md` documenta
como o real. Sintoma: `/static/img/logo1.png` devolvia erro — mesma causa
já registrada na entrada "Imagem/logo/CSS não aparece" acima
(`runserver` do stack "plain" não serve `/static/` com `DEBUG=False`, sem
Nginx na frente).

**Causa raiz:** os dois stacks apontam para o **mesmo volume de banco**
(`sistema_posvenda_posvenda_db_data`, ver entrada "Dois stacks... "
acima). Em algum momento o `db` do stack `hml` saiu do ar (`Exited (137)`,
provável falta de memória) e nunca foi religado manualmente. Como o `db`
e o `web` do stack "plain" estão com `restart: always` no
`docker-compose.yml`, **um simples reboot do host, ou o Docker reiniciar
sozinho, é suficiente para o stack "plain" voltar a subir e retomar o
lock do volume** — sem nenhum `git push`/deploy envolvido. Foi assim que
ele assumiu a produção silenciosamente.

**Correção aplicada:** cutover manual, autorizado pelo usuário
diretamente ao DevOps (produção, sem servidor de homologação dedicado
provisionado — ver `architecture.md`):
1. Backup real do banco a partir do stack "plain" (o que estava ao vivo).
2. `docker compose -f docker-compose.yml stop` (não destrutivo) parou
   `db`/`web`/`email_scheduler` do stack "plain".
3. `docker update --restart=no sistema_posvenda-db-1 sistema_posvenda-web-1
   sistema_posvenda-email_scheduler-1` — **essencial**: sem isso, o
   incidente se repetiria no próximo reboot do host, mesmo sem deploy
   novo. Os 3 containers do stack "plain" continuam existindo (parados),
   não foram removidos — reversível com `docker compose -f
   docker-compose.yml start` se um dia precisar.
4. `docker compose -f docker-compose.hml.yml -f
   docker-compose.hml.override.yml --env-file .env.hml up -d --build`,
   `migrate`, `collectstatic` — stack `hml` (com Nginx) assumiu o volume
   real (só a migration nova apareceu no `migrate`, confirmando volume
   certo) e passou a responder em `:8000`.
5. Validado: `/login/` e `/static/img/logo1.png` devolvendo `200`;
   `Escola.objects.count()` batendo com o esperado (2.718, já contando as
   96 escolas da "Nova BASE EACE.xlsx").

**Prevenção:** checar periodicamente (ou antes de qualquer deploy)
`docker ps -a | grep sistema_posvenda` — se `sistema_posvenda-db-1`/
`sistema_posvenda-web-1` (sem `_hml`) aparecerem `Up`, o stack errado
assumiu de novo; investigar antes de continuar. Os 3 containers do stack
"plain" ficam com `restart: no` a partir desta correção — se alguém
precisar deles de volta (ex.: emergência), religar manualmente já muda
esse comportamento, então reaplicar o `docker update --restart=no` depois
de terminar.

**Pendência (não bloqueia o site, mas falta preencher):**
`GRAPH_FINANCEIRO_CLIENT_ID`/`_SECRET`/`_TENANT_ID` em `.env.hml`
continuam com `TODO` — envio de e-mail do financeiro via Graph API
(FEAT-008) não deve funcionar no stack `hml` até alguém preencher essas 3
chaves com a credencial real (mesmo padrão dos casos de AD/SMTP
documentados acima); DevOps não inventa esse valor.

### Deploy automático (push na branch `homolog`) não dispara ou falha no job "deploy"

Confirmar que os secrets (`HML_HOST`, `HML_USER`, `HML_PORT`,
`HML_SSH_KEY`) estão cadastrados no GitHub (`CI_CD.md`) — sem eles o job
"deploy" falha na conexão SSH, mesmo com o "ci" verde. O job "deploy" só
roda em push direto na branch `homolog`, nunca em Pull Request.
