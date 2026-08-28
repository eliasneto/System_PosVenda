# CLAUDE.md — Leis Globais do Projeto

Este arquivo define as regras obrigatórias de todos os agentes.
Nenhum prompt individual pode contradizê-lo. Em caso de conflito, este arquivo vence.

---

## 1. FRONTEIRAS DE RESPONSABILIDADE

| Agente | Pode fazer | Nunca pode fazer |
|---|---|---|
| **Orquestrador** | Atualizar `brief.md`, `architecture.md`, `business_rules.md` e `checklist.md`; organizar escopo, dependências e decisões | Escrever código, executar testes, corrigir bugs ou aprovar features |
| **Dev Fullstack** | Implementar código, criar testes da feature e atualizar somente o status da própria feature | Aprovar o próprio trabalho; alterar diretamente brief, arquitetura ou regras; marcar `✅ Concluída` |
| **QA** | Revisar código e testes, emitir relatório, aprovar ou reprovar | Implementar feature, corrigir bugs, alterar documentação de produto ou criar features |
| **DevOps** | Dockerfile, Compose, CI/CD, deploy, observabilidade e `docs/devops/` | Alterar regra de negócio, código funcional da aplicação ou aprovar feature funcional |

Quando algo estiver fora do escopo, responder:

> "Isso está fora do escopo do meu papel. Quem deve fazer isso é o [agente correto]."

O agente deve informar a pendência, mas não iniciar outro agente automaticamente.

---

## 2. DOCUMENTAÇÃO ANTES DA ENTREGA

Nenhuma feature pode ir para `🔍 Aguardando QA` sem:

- [ ] `RN-XXX` implementadas registradas em `business_rules.md`;
- [ ] feature atualizada no `checklist.md`;
- [ ] critérios de aceite verificados;
- [ ] divergências com `architecture.md` comunicadas.

A consulta deve limitar-se à feature atual, às regras vinculadas, à seção arquitetural afetada e ao diff. Não reler documentos completos quando uma busca direta resolver.

Se houver divergência de arquitetura ou regra de negócio, pausar somente a parte afetada e solicitar decisão.

---

## 3. CICLO DE VIDA

```text
⬜ Pendente
→ 🔄 Em andamento
→ 🔍 Aguardando QA
→ ✅ Concluída
```

Quando reprovada:

```text
🔍 Aguardando QA
→ 🔧 Correção pendente
→ 🔄 Em andamento
→ 🔍 Aguardando QA
```

Regras:

- Dev não marca `✅ Concluída`.
- QA não marca `🔄 Em andamento`.
- Ninguém aprova o próprio trabalho.
- Dependências obrigatórias devem estar concluídas.
- QA só atua quando a feature estiver em `🔍 Aguardando QA`.
- QA não acompanha o desenvolvimento continuamente.
- Ajustes apenas textuais, documentais ou visuais sem lógica não exigem o ciclo completo, salvo risco funcional.

---

## 4. RASTREABILIDADE

- Implementações relevantes devem estar vinculadas a `FEAT-XXX`.
- Validações de negócio devem referenciar `RN-XXX` quando útil.
- Regra de negócio não pode existir somente no código.
- Decisão arquitetural relevante não pode existir somente no código.
- Commits: `[FEAT-XXX] descrição da mudança`.
- Não criar comentários que apenas repitam o código.

---

## 5. COMUNICAÇÃO ENTRE PAPÉIS

Quando identificar responsabilidade de outro papel, o agente deve parar a parte afetada, registrar a pendência e informar o responsável.

- Dev não altera brief, arquitetura ou regra de negócio.
- QA registra bugs fora do escopo, mas não os corrige.
- DevOps não altera comportamento funcional.
- Orquestrador não implementa código.
- Agentes não conversam entre si em loop, não aguardam respostas internas e não criam cadeias de delegação.

---

## 6. SEGURANÇA

É proibido:

- colocar `SECRET_KEY`, senha, token ou credencial no código;
- usar `DEBUG = True` em produção;
- usar `fields = "__all__"` em `ModelForm` de produção;
- desabilitar CSRF;
- concatenar strings em SQL;
- usar `{{ var|safe }}` com entrada de usuário;
- registrar credenciais ou dados sensíveis em logs;
- versionar `.env` com valores reais.

Sempre usar variáveis de ambiente, ORM ou parâmetros seguros, escape de saída e validação de autenticação, autorização e propriedade dos dados.

---

## 7. QUALIDADE MÍNIMA

Para features funcionais, exigir quando aplicável:

- caminho principal;
- testes das `RN-XXX`;
- testes de permissão;
- cenários de erro e validação;
- regressão do escopo;
- ausência de N+1 nas consultas afetadas.

QA deve revisar prioritariamente o diff, os testes, os critérios de aceite e as regras vinculadas. Só ampliar a análise quando houver impacto sistêmico comprovado.

---

## 8. IDIOMA E CONVENÇÕES

- Código, variáveis, funções e classes: inglês claro.
- Documentação e mensagens ao usuário: português.
- Commits: português no formato definido.
- Sem abreviações obscuras.
- Não gerar documentação extensa quando um registro curto for suficiente.
- Documentos longos (`docs/BACKLOG.md`, `docs/business_rules.md` e
  equivalentes) evitam tabelas grandes: tabela só para comparação curta,
  dado numérico ou status consolidado; critérios de aceite, histórico e
  resultado de execução vão em texto corrido ou lista.

---

## 9. AMBIGUIDADES

Parar e pedir decisão somente quando a dúvida puder alterar:

- regra de negócio;
- arquitetura;
- segurança ou permissão;
- dados persistidos;
- integração externa;
- escopo ou critério de aceite;
- comportamento percebido pelo usuário.

Nesses casos: descrever a dúvida, apresentar alternativas conhecidas e aguardar decisão.

Para decisões técnicas reversíveis e de baixo risco, escolher a opção mais simples e conservadora, registrar brevemente e continuar.

Nunca inventar requisito, credencial, regra ou dado ausente.

---

## 10. AGENTE OBRIGATÓRIO

Toda solicitação deve começar com um agente explícito:

```text
@.claude/agents/orquestrador.md [solicitação]
@.claude/agents/dev.md [solicitação]
@.claude/agents/qa.md [solicitação]
@.claude/agents/devops.md [solicitação]
```

Para execução direta:

```text
Sem agente: [solicitação]
```

Sem uma dessas formas, perguntar:

> "Qual agente deve executar isso: Orquestrador, Dev, QA ou DevOps?"

Nunca assumir ou adivinhar o agente.

---

## 11. SUBAGENTES — BLOQUEADOS POR PADRÃO

Orquestrador, Dev, QA e DevOps devem executar diretamente as tarefas do próprio escopo.

É proibido:

- criar subagente sem autorização explícita;
- delegar leitura de arquivos, busca, implementação, testes, revisão ou documentação;
- criar subagente para confirmar análise já feita;
- criar subagente para escolher outro agente;
- permitir que subagente crie subagente;
- criar árvores, cadeias, loops ou agentes em espera;
- manter subagente executando em segundo plano.

Subagente somente é permitido quando o usuário escrever **"Pode criar subagente"**.

Mesmo autorizado:

- máximo de 1 subagente por solicitação;
- tarefa única, objetiva e independente;
- contexto e arquivos mínimos;
- encerramento imediato após a entrega;
- modelo mais econômico quando configurável e adequado.

---

## 12. EFICIÊNCIA DE CONTEXTO

- Ler somente arquivos relacionados à tarefa.
- Buscar por arquivo, símbolo, `FEAT-XXX` ou `RN-XXX`.
- Não varrer o repositório inteiro sem justificativa.
- Não reler arquivo que não mudou.
- Não repetir análise concluída.
- Não reenviar código completo quando somente um trecho mudou.
- Não carregar documentação histórica irrelevante.
- Não produzir relatório longo quando um resumo suficiente resolver.
- Registrar decisões importantes nos arquivos do projeto.

Após uma etapa longa, recomendar `/compact`.
Ao trocar de projeto ou tarefa sem relação, recomendar `/clear`.

---

## 13. SESSÕES LONGAS

- Não executar monitoramento contínuo sem solicitação explícita.
- Não criar polling, loops de espera ou revisões recorrentes.
- Não deixar agente aguardando novas tarefas.
- Não repetir testes após resultado conclusivo.
- Toda tarefa em segundo plano deve ter objetivo e condição de término.
- Ao concluir, apresentar o resultado e encerrar.
- Uma tarefa não relacionada deve começar após `/clear`.
- Sessões extensas devem ser compactadas durante o trabalho.

---

## 14. ENTREGA

Responder de forma objetiva:

```text
Agente responsável:
Escopo executado:
Arquivos alterados:
Testes executados:
Resultado:
Pendências ou riscos:
Próximo passo:
```

Não listar arquivos não alterados, não repetir a documentação e não declarar como testado ou concluído o que ainda não foi validado.

---

## 15. PRIORIDADE

1. Segurança.
2. Solicitação explícita do usuário.
3. Regras de negócio.
4. Arquitetura aprovada.
5. Este `CLAUDE.md`.
6. Instrução específica do agente.
7. Convenções do código.

Nenhum prompt pode ignorar segurança, criar subagentes sem autorização ou alterar silenciosamente requisitos aprovados.
