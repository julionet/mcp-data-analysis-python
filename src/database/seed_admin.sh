#!/bin/sh
# Seed do administrador — roda UMA vez, quando o banco é criado (docker-entrypoint-initdb.d, depois do
# 01-schema.sql), e pode ser reexecutado à mão: é idempotente (scripts/setup-admin.ps1 faz isso em bancos
# que já existiam antes deste seed).
#
# Cria: o perfil "admin"; o usuário (login = ADMIN_LOGIN, senha = ADMIN_PASSWORD, hash bcrypt gerado
# pelo pgcrypto); o vínculo usuário↔perfil; e o vínculo do perfil com TODAS as análises que já existem
# (análises cadastradas depois exigem reexecutar este script, ou um INSERT em profile_analyses).
# NÃO emite token: o token só existe na resposta de POST /auth/token (ver scripts/setup-admin.ps1).
# O usuário é marcado com is_admin = true (papel da API administrativa /admin/*, F23 — ADR-008). Em bancos
# criados antes dessa coluna, rode uma vez: ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT false;
# (sem ela este script falha). Reexecutar o seed volta a marcar is_admin = true no usuário ADMIN_LOGIN.
#
# Variáveis (vêm do compose; padrões abaixo):
#   ADMIN_LOGIN=admin  ADMIN_PASSWORD=Senh@123  ADMIN_RESET_PASSWORD=0 (1 = regrava a senha de um admin existente)
# SENHA PADRÃO CONHECIDA: troque em qualquer ambiente acessível por outras pessoas.
#
# NÃO use `set -e` aqui: o entrypoint do postgres executa .sh sem bit de execução com `.` (source) e o
# `set -e` vazaria para ele. O psql com ON_ERROR_STOP já aborta a inicialização se algo falhar.
# Mantenha este arquivo com final de linha LF (ver .gitattributes).

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v admin_login="${ADMIN_LOGIN:-admin}" \
  -v admin_password="${ADMIN_PASSWORD:-Senh@123}" \
  -v reset_password="${ADMIN_RESET_PASSWORD:-0}" <<'SQL'
CREATE EXTENSION IF NOT EXISTS pgcrypto;

INSERT INTO profiles (name, description)
VALUES ('admin', 'Administrador: acesso a todas as análises (seed_admin)')
ON CONFLICT (name) DO NOTHING;

-- external_id é o login e vai SEMPRE em minúsculas (a aplicação normaliza o login recebido).
INSERT INTO users (name, external_id, password_hash, is_admin, created_by)
VALUES ('Administrador', lower(:'admin_login'), crypt(:'admin_password', gen_salt('bf', 12)), true, 'seed_admin')
ON CONFLICT (external_id) DO NOTHING;

-- Admin que já existia (criado antes do is_admin): garante o papel administrativo.
UPDATE users
   SET is_admin = true, updated_at = NOW()
 WHERE external_id = lower(:'admin_login') AND is_admin = false;

-- Só com ADMIN_RESET_PASSWORD=1: regrava a senha de um admin que já existia.
UPDATE users
   SET password_hash = crypt(:'admin_password', gen_salt('bf', 12)), updated_at = NOW()
 WHERE external_id = lower(:'admin_login') AND :'reset_password' = '1';

INSERT INTO user_profiles (user_id, profile_id)
SELECT u.id, p.id
  FROM users u, profiles p
 WHERE u.external_id = lower(:'admin_login') AND p.name = 'admin'
ON CONFLICT DO NOTHING;

INSERT INTO profile_analyses (profile_id, analysis_id)
SELECT p.id, a.id
  FROM profiles p, analyses a
 WHERE p.name = 'admin'
ON CONFLICT DO NOTHING;
SQL
