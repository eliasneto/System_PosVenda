# Gerenciador Pós Venda

Sistema de faturamento EACE por INEP (processo RI) — v1.0.0.

A documentação funcional (requisitos, arquitetura, regras de negócio,
modelo de dados e checklist) vive, por enquanto, no repositório
`modulo-posVenda`, pasta `docs_gerenciador_pos_venda/` — não duplicar aqui
até que uma decisão explícita mova a documentação para este repositório.

## Rodando localmente

1. `python -m venv .venv` e ativar (`.venv\Scripts\activate` no Windows).
2. `pip install -r requirements.txt`
3. Copiar `.env.example` para `.env` e ajustar os valores (gerar uma
   `SECRET_KEY` própria — nunca reaproveitar a de outro ambiente).
4. `python manage.py migrate`
5. `python manage.py createsuperuser`
6. `python manage.py runserver`

Banco local por padrão: SQLite (arquivo `db.sqlite3`, fora do controle de
versão). Para usar MySQL, definir `DB_ENGINE=mysql` e as credenciais
correspondentes no `.env`.
