"""RPA de anexo de Nota Fiscal (PDF+XML) no portal EACE (FEAT-033,
`ADR-004`, `RN-056`). Nucleo reaproveitado do prototipo
`doc/auto_eace_nf_servidor` (Playwright), sem a camada de frontend do
prototipo (dashboard FastAPI descartado).

Fase 1 (atual): so o nucleo da automacao, chamado via management command
de terminal, sem model de log nem tela. Fase 2 acrescenta o log por Nota
Fiscal com selecao manual de PDF/XML (RN-056).

`apps.integracoes` ainda nao e um app Django instalado (so um pacote de
utilitarios, mesmo padrao de `apps/integracoes/ad/`) - por isso o
management command desta automacao fica em `apps/ri/management/commands/`
(app ja instalado), so importando deste pacote.
"""
