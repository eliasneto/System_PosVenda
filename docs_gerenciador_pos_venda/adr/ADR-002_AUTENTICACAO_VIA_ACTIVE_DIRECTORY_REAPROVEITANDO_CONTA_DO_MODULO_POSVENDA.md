# ADR-002 - Autenticação via Active Directory reaproveitando a mesma conta de serviço do `modulo-posVenda`

## Status
Aprovado

## Contexto
`lixo.md` (item 7, criado em 2026-08-20) registrava como decisão em aberto
se o `Sistema_posvenda` teria integração com Active Directory: o sistema
novo nasceu com cadastro de usuário 100% manual (RN-004 — Administrador
cria/edita/desativa), e o módulo `apps/integracoes/ad/ad_sync.py` do
`modulo-posVenda` não foi copiado na criação do repositório (FEAT-001/
FEAT-012) — o Dockerfile atual não instala `libldap2-dev`/`libsasl2-dev` e
o `requirements.txt` não lista `python-ldap`/`django-auth-ldap`, ao
contrário do `modulo-posVenda`, que tem os dois.

Em 2026-08-28 o usuário pediu, via Orquestrador, a criação da integração
com AD. Havia um precedente aparentemente contrário: para o e-mail do
financeiro (RN-009), o usuário já havia recusado explicitamente reaproveitar
o app do Azure AD do `modulo-posVenda`, exigindo um app **exclusivo deste
sistema** (`checklist.md`, pendência de FEAT-009) — e o `.env` deste
repositório já foi limpo duas vezes (2026-08-22) por conter credencial de
AD/IXC/Graph copiada por engano do `modulo-posVenda`.

Perguntado diretamente, o usuário confirmou que, desta vez, quer o oposto:
reaproveitar a mesma conta de serviço e as mesmas variáveis `AD_*` já
configuradas no `.env` do `modulo-posVenda`, em vez de provisionar uma
conta dedicada.

## Decisão
O `Sistema_posvenda` passa a ter dois mecanismos de AD, copiados do
`modulo-posVenda` (RN-043/RN-044, `FEAT-027`):

1. **Autenticação no login** — `django_auth_ldap.backend.LDAPBackend`
   como backend primário (com `ModelBackend` como fallback), condicional a
   `USE_AD_AUTH`. Primeiro login bem-sucedido de um usuário do AD sem
   cadastro local cria o usuário automaticamente, sempre com perfil
   **Analista** (RN-004) — decisão explícita do usuário, nunca
   Administrador.
2. **Sincronização pós-login** — `apps/integracoes/ad/ad_sync.py`
   atualiza e-mail e nome do usuário a partir do AD a cada login, sem
   bloquear o login se o LDAP estiver indisponível.

As variáveis `AD_SERVER_URI`, `AD_BIND_DN`, `AD_BIND_PASSWORD`,
`AD_USER_SEARCH_BASE`, `AD_DEFAULT_DOMAIN` e `USE_AD_AUTH` são configuradas
no `.env` deste repositório com os **mesmos valores** já usados no
`modulo-posVenda` — mesma conta de serviço de bind, mesmo servidor AD.
Nenhum valor real é copiado para documentação versionada; a configuração é
feita diretamente no `.env` (fora do controle de versão), por quem tiver
acesso a ambos os `.env` reais.

## Por que isto não contradiz a decisão do e-mail do financeiro (RN-009)
São credenciais de natureza diferente:

- O app do Azure AD do Graph (RN-009) é uma **identidade de aplicação**
  vinculada a uma caixa de e-mail específica (`posvendas@
  megainfraestrutura.com.br`) — reaproveitar o app do `modulo-posVenda`
  significaria enviar/ler e-mail *como se fosse* aquele outro sistema, na
  caixa de outro sistema. Por isso a exigência de app exclusivo.
- A conta de bind do AD/LDAP é uma **conta de serviço de leitura do
  diretório** (busca `sAMAccountName`/`mail`/`displayName` etc.), sem
  vínculo com uma caixa de e-mail ou identidade de aplicação. Dois sistemas
  usando a mesma conta de leitura contra o mesmo diretório corporativo é
  equivalente a dois sistemas apontando para o mesmo DNS ou NTP da empresa
  — não é comunicação entre os dois sistemas em tempo de execução, e não
  contradiz `ADR-001` ("os dois sistemas não se comunicam depois de
  prontos"): ambos falam independentemente com uma terceira infraestrutura
  (o Active Directory da empresa), nunca um com o outro.

## Consequências positivas
- Sem provisionamento novo — usa a conta de bind já validada em produção
  no `modulo-posVenda`.
- Elimina cadastro manual de usuário para quem já está no domínio AD,
  mantendo o controle de perfil (sempre Analista na criação automática).
- Consistente com o restante do reaproveitamento de código já decidido em
  `ADR-001` (frontend, permissão, padrão de e-mail).

## Consequências negativas / riscos
- **Acoplamento operacional real, mesmo sem chamada em tempo de execução
  entre os sistemas:** se a conta de serviço de bind for desativada,
  rotacionada ou tiver a senha trocada por causa de uma necessidade do
  `modulo-posVenda`, o login via AD do `Sistema_posvenda` quebra junto, sem
  aviso prévio a quem administra este repositório.
- Quando o `modulo-posVenda` for eliminado ao final da convergência
  (`ADR-001`), a conta de bind precisa ser identificada e preservada (ou
  recriada) separadamente — não pode ser desativada junto com o resto do
  repositório por engano.
- Criação automática de usuário via AD (perfil Analista) é uma exceção
  nova à RN-004; qualquer extensão futura de permissão por perfil precisa
  considerar os dois caminhos de criação de usuário (manual e automático).
- **Verificação de certificado TLS desativada na conexão LDAPS** (decisão
  de 2026-08-28, ver "Pendências" abaixo) — mesma solução já usada em
  produção no `modulo-posVenda`, necessária porque a CA interna do AD não
  está na cadeia de confiança do container. A conexão continua
  criptografada, mas sem validar a identidade do servidor — aceitável só
  porque a rede entre o container e o AD é a rede corporativa interna, não
  a internet pública.

## Alternativas consideradas
- **Conta de serviço de bind dedicada ao `Sistema_posvenda`** (mesmo
  padrão usado para o app do Graph do financeiro, RN-009) — era a opção
  recomendada pelo Orquestrador; rejeitada pelo usuário, que optou
  explicitamente por reaproveitar a mesma conta e configuração do
  `modulo-posVenda`.
- **Somente sincronização pós-login, sem autenticação via AD** (login
  continua local) — rejeitada; o usuário confirmou querer os dois
  mecanismos.
- **Criação automática de usuário com perfil Administrador** — não
  considerada; o usuário determinou perfil Analista desde a primeira
  pergunta.

## Pendências
- ~~DevOps precisa reintroduzir `python-ldap==3.4.3` e
  `django-auth-ldap==4.8.0` (`requirements.txt`) e as libs de sistema
  `libldap2-dev`/`libsasl2-dev` (`Dockerfile`)~~ — feito em 2026-08-28
  (DevOps): versões reintroduzidas no `requirements.txt`, libs no
  `Dockerfile`, e as 6 variáveis `AD_*`/`USE_AD_AUTH` adicionadas também ao
  `docker-compose.yml` (serviço `web` só recebia variáveis explicitamente
  listadas, não herdava o `.env` inteiro).
- ~~Valores reais de `AD_SERVER_URI`/`AD_BIND_DN`/`AD_BIND_PASSWORD`/
  `AD_USER_SEARCH_BASE`/`AD_DEFAULT_DOMAIN`/`USE_AD_AUTH` no `.env` deste
  repositório~~ — feito em 2026-08-28, a pedido explícito do usuário:
  copiados do `.env` real do `modulo-posVenda` para o `.env` deste
  repositório (fora do controle de versão), sem exibir os valores em chat
  nem gravá-los em nenhum arquivo versionado.
- **Certificado TLS da conexão LDAPS — decisão tomada em 2026-08-28:**
  testando o login de verdade, o bind falhou com "certificate verify
  failed (unable to get local issuer certificate)" — a CA interna que
  emite o certificado do AD não está na cadeia de confiança do container,
  mesmo problema que o `modulo-posVenda` já tinha resolvido desativando a
  verificação de certificado (`OPT_X_TLS_REQUIRE_CERT = OPT_X_TLS_NEVER`).
  Perguntado diretamente (CLAUDE.md §9 — decisão de segurança), o usuário
  confirmou reaproveitar a mesma solução, em vez de instalar a CA interna
  no container. Aplicado em `config/settings.py` (bloco `USE_AD_AUTH`).
  Risco aceito: a conexão continua criptografada (LDAPS), mas sem validar
  a cadeia do certificado — suscetível a man-in-the-middle numa rede não
  confiável entre o container e o AD.
- **Validação end-to-end realizada em 2026-08-28** (conta real do usuário,
  senha nunca gravada em arquivo): login válido cria o usuário
  automaticamente com perfil Analista (nunca Administrador), sincroniza
  e-mail/nome do AD (RN-044), senha errada é recusada, e usuário local
  desativado (`is_active=False`) não loga mesmo com a senha certa do AD.
- Nenhum valor real de credencial deve ser colocado em `checklist.md`,
  `business_rules.md`, `architecture.md` ou nesta ADR — apenas em `.env`,
  fora do controle de versão (CLAUDE.md §6).
