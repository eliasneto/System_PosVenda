# ADR-010 - Servidor web (gunicorn) com vários processos e threads

## Status
`Aprovado e aplicado` em 2026-11-11 (incidente em produção; correção no
`.env.hml` do servidor na hora e no `Dockerfile` para as próximas versões).

## Contexto
O container `web` subia com o comando padrão do `Dockerfile`:

```
gunicorn --bind 0.0.0.0:8000 --timeout 120 config.wsgi:application
```

Sem `--workers`, o gunicorn sobe **1 único processo, síncrono** - atende **1
pedido por vez**. Enquanto ele processa um pedido, todos os outros ficam
esperando na fila.

Isso passou despercebido enquanto o sistema tinha poucos acessos. Em
2026-11-11 o uso mudou:

- painel da fila na TV (`/fila-tv/`) atualizando a cada 10 s, em mais de uma
  tela, cada atualização lendo memória/processador e várias contagens;
- tela "Projeto > Fila" atualizando sozinha a cada 10 s (HTMX) em cada
  navegador aberto;
- planilha de relatório (pode levar alguns segundos) e usuários navegando.

**Sintoma (incidente):** "o sistema caiu" - da rede, o login não respondia em
20 s (timeout), mas **todos os containers estavam de pé**, o servidor tinha 38
GB de memória livre e o processador folgado, e de dentro do servidor o login
às vezes respondia rápido (0,004 s) e às vezes em 10 s. Não era falta de
recurso da máquina: era a fila de pedidos atrás de um processo só.

## Decisão
O site roda com **5 processos x 4 threads** (worker `gthread`) = até ~20
pedidos ao mesmo tempo:

```
gunicorn --bind 0.0.0.0:8000 --timeout 120 --workers 5 --threads 4 config.wsgi:application
```

- `Dockerfile` (CMD) - vale para todo deploy a partir da v1.4.1.
- Produção, na hora do incidente: `GUNICORN_CMD_ARGS=--workers 5 --threads 4`
  no `.env.hml` e recriação só do `web` (`up -d --no-deps web` + `restart
  nginx`) - sem tocar no container dos robôs. Quando a imagem nova (com o CMD
  acima) estiver no ar, os argumentos de linha de comando prevalecem sobre a
  variável.

Por que 5 x 4: a regra usual do gunicorn é `(2 x núcleos) + 1` processos,
mas o servidor é compartilhado com os robôs do RPA (que usam a maior parte da
memória/processador); 5 processos com 4 threads cada cobre com folga o
acesso atual (poucas dezenas de usuários + telas de TV) gastando ~1 GB de
memória. As threads ajudam porque a maior parte do tempo de um pedido é
espera de banco/disco.

## Consequências positivas
- Um pedido lento (planilha, Fila com muitos itens) não trava os demais.
- Login voltou a responder em 0,03-0,5 s logo após a correção.

## Consequências negativas / riscos
- ~5x mais memória do `web` (ainda pequena perto dos robôs).
- Código que guarda estado em memória de processo (cache local, variáveis
  globais) passa a ter 1 cópia por processo - ex.: a última leitura de
  processador do painel da TV (`views_fila_tv._ULTIMA_AMOSTRA_CPU`) é por
  processo, sem problema para o cálculo.

## Regra para outros sistemas (lição aprendida)
Todo sistema Django/Flask servido por gunicorn **deve declarar
`--workers` (e de preferência `--threads`) explicitamente** no comando de
subida (Dockerfile/compose). O padrão de 1 processo síncrono só serve para
teste. Sintoma típico de esquecer: "sistema fora do ar" com containers de pé,
máquina folgada e lentidão intermitente - piora quando entra qualquer tela com
atualização automática (polling).
