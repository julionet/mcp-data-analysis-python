-- F12 — Seed: usuário administrador + perfil "Analises de vendas" + vínculos.
-- Pré-requisito: database/migrations/f12_autenticacao.sql já aplicado.
-- Senha: hash bcrypt (custo 12) — a senha em texto puro nunca é gravada.
-- E-mail SEMPRE em minúsculas (a aplicação normaliza o login com strip().lower()).
-- Idempotente: pode ser executado mais de uma vez.

BEGIN;

INSERT INTO users (name, external_id, password_hash)
VALUES (
    'Usuário Administrador',
    'julio.net@gmail.com',
    '$2b$12$nieI9XK3F94SrRqoYc.c3uz/UAwyymsMV4B.75klkoDd.nWX.IrGy'
)
ON CONFLICT (external_id) DO UPDATE
    SET name = EXCLUDED.name,
        password_hash = EXCLUDED.password_hash,
        updated_at = NOW();

INSERT INTO profiles (name, description)
VALUES ('Analises de vendas', 'Analise de vendas')
ON CONFLICT (name) DO UPDATE
    SET description = EXCLUDED.description,
        updated_at = NOW();

-- Usuário ↔ perfil
INSERT INTO user_profiles (user_id, profile_id)
SELECT u.id, p.id
FROM users u, profiles p
WHERE u.external_id = 'julio.net@gmail.com'
  AND p.name = 'Analises de vendas'
ON CONFLICT DO NOTHING;

-- Perfil ↔ analyses (falha se algum UUID não existir em analyses, por causa da FK)
INSERT INTO profile_analyses (profile_id, analysis_id)
SELECT p.id, a.analysis_id
FROM profiles p,
     (VALUES
        ('5e949539-6763-4bdc-b108-0504d8390d1a'::uuid),
        ('ced83edf-8585-4e6e-a6dd-86460f53fad2'::uuid),
        ('e1410687-7432-4692-9887-ec7a1ff0621f'::uuid)
     ) AS a(analysis_id)
WHERE p.name = 'Analises de vendas'
ON CONFLICT DO NOTHING;

COMMIT;

-- Conferência:
-- SELECT u.external_id, p.name AS perfil, an.name AS analysis
-- FROM users u
-- JOIN user_profiles up ON up.user_id = u.id
-- JOIN profiles p ON p.id = up.profile_id
-- JOIN profile_analyses pa ON pa.profile_id = p.id
-- JOIN analyses an ON an.id = pa.analysis_id
-- WHERE u.external_id = 'julio.net@gmail.com';
