-- Preparação do ambiente (rodar UMA vez, como superusuário do Postgres).
-- Uso: psql -d postgres -v rag_password='<SENHA>' -f sql/setup_admin.sql
-- Idempotente. Se rag_user já existir, a senha NÃO é alterada (use ALTER ROLE manualmente).
\if :{?rag_password}
\else
  \echo 'Informe a senha: psql -v rag_password=''...'' -f sql/setup_admin.sql'
  \quit
\endif
\set ON_ERROR_STOP on

SELECT format('CREATE ROLE rag_user LOGIN PASSWORD %L', :'rag_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rag_user') \gexec

SELECT 'CREATE DATABASE rag_training_db OWNER rag_user'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'rag_training_db') \gexec

\connect rag_training_db
CREATE EXTENSION IF NOT EXISTS vector;
