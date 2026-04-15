# Global Cyber Summit

Aplicacao web em Python/HTML para executar a rotina antifraude do desafio usando Oracle e PL/SQL.

## Como executar

1. Instale as dependencias:
   `pip install -r requirements.txt`
2. A conexao Oracle ja esta configurada diretamente em [app.py](C:/Users/johnn/OneDrive/Desktop/Database-2026-1/cp2/app.py:14) com host `oracle.fiap.com.br`, porta `1521`, SID `orcl`, usuario `rm566516` e senha `210806`.
3. Crie a base com [create.sql](C:/Users/johnn/OneDrive/Desktop/Database-2026-1/cp2/create.sql) e popule com [INSERT.sql](C:/Users/johnn/OneDrive/Desktop/Database-2026-1/cp2/INSERT.sql).
4. Rode a aplicacao:
   `python app.py`

## O que a interface faz

- Usa as consultas de [teste.sql](C:/Users/johnn/OneDrive/Desktop/Database-2026-1/cp2/teste.sql) para montar a dashboard.
- Executa o bloco anonimo exatamente a partir de [CyberSummit.sql](C:/Users/johnn/OneDrive/Desktop/Database-2026-1/cp2/CyberSummit.sql).
- Mantem apenas melhorias de tratamento de excecao no Python com `oracledb.DatabaseError`, `commit` e `rollback`.
