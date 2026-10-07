# Guia de uso — ambiente local com Docker

Como subir, configurar, operar, limpar e empacotar a aplicação. Os comandos são para **PowerShell**, executados na **raiz do repositório**, com o compose `docker-compose.local.yml`.

> **Este guia usa HTTP (`http://`) por padrão**, só para uso na sua máquina (`localhost`). O Passo 0 prepara o ambiente para isso. Para HTTPS, veja [Usar com TLS (https)](#usar-com-tls-https).

## Índice

1. [Subir a aplicação (passo a passo)](#1-subir-a-aplicação-passo-a-passo)
   - [Passo 0: preparar o ambiente (.env em HTTP)](#passo-0-preparar-o-ambiente-env-em-http)
   - [Passo 1: subir e criar o Config DB](#passo-1-subir-e-criar-o-config-db)
   - [Passo 2: criar o banco de análises e um usuário só de leitura](#passo-2-criar-o-banco-de-análises-e-um-usuário-só-de-leitura)
   - [Passo 3: inserir usuário e perfil da aplicação](#passo-3-inserir-usuário-e-perfil-da-aplicação)
   - [Passo 4: cifrar a senha do data source](#passo-4-cifrar-a-senha-do-data-source)
   - [Passo 5: cadastrar data source, análise e liberar para o perfil](#passo-5-cadastrar-data-source-análise-e-liberar-para-o-perfil)
   - [Passo 6: emitir o token e testar](#passo-6-emitir-o-token-e-testar)
   - [Detalhes importantes](#detalhes-importantes)
2. [Variações de ambiente](#2-variações-de-ambiente)
   - [Postgres instalado no Windows (sem Docker)](#postgres-instalado-no-windows-sem-docker)
   - [Usar com TLS (https)](#usar-com-tls-https)
3. [Operação do dia a dia](#3-operação-do-dia-a-dia)
   - [Parar sem perder dados](#parar-sem-perder-dados)
   - [Voltar a usar](#voltar-a-usar)
   - [Conferir que os dados continuam lá](#conferir-que-os-dados-continuam-lá)
   - [Executar comando no banco](#executar-comando-no-banco)
   - [O que preservar](#o-que-preservar)
   - [Backup e restauração](#backup-e-restauração)
4. [Recomeçar do zero (limpeza)](#4-recomeçar-do-zero-limpeza)
   - [Ambiente local](#ambiente-local)
   - [Limpar também a imagem do app](#limpar-também-a-imagem-do-app)
   - [Remote e bancos opcionais](#remote-e-bancos-opcionais)
   - [Conferir que ficou limpo](#conferir-que-ficou-limpo)
   - [Recomeçar e o que não é apagado](#recomeçar-e-o-que-não-é-apagado)
   - [Volume órfão do MySQL](#volume-órfão-do-mysql)
   - [Limpeza geral do Docker](#limpeza-geral-do-docker-cuidado)
5. [Pacote de instalação (dist)](#5-pacote-de-instalação-dist)
   - [Gerar o pacote](#gerar-o-pacote)
   - [Conteúdo de dist/](#conteúdo-de-dist)
   - [Instalar em outro computador](#instalar-em-outro-computador)
   - [O que foi conferido e o que não foi testado](#o-que-foi-conferido-e-o-que-não-foi-testado)
   - [Manutenção](#manutenção)

---

## 1. Subir a aplicação (passo a passo)

### Passo 0: preparar o ambiente (.env em HTTP)

```powershell
cp .env.example .env
```

Edite o `.env` e confira estes valores **antes do primeiro `up`**:

| Variável | Valor | Por quê |
|---|---|---|
| `TLS_ENABLED` | `false` | já vem `false` no `.env.example`: o servidor sobe em HTTP puro; com `true` a porta 3000 só aceita TLS e todas as URLs abaixo falhariam |
| `FERNET_KEY` | uma chave sua | cifra as senhas dos data sources; o `scripts/setup-admin.ps1` gera uma no `.env` se estiver com o valor de exemplo (nunca sobrescreve uma real) |
| `POSTGRES_CONFIG_PASSWORD` | uma senha sua | só vale na primeira inicialização do volume |

Com `TLS_ENABLED=false` os certificados de `certs/` **não são necessários** (`TLS_CERT_FILE` e `TLS_KEY_FILE` são ignorados), e o healthcheck do container já usa `http`. Não é preciso mudar o compose nem o código.

> **Cuidado:** em HTTP, senha e token trafegam em **texto puro**. Use só em `localhost`, nunca com acesso pela rede. Clientes MCP como o Claude Desktop podem recusar `http://` (ADR-006 da ARQUITETURA); nesse caso, veja [Usar com TLS (https)](#usar-com-tls-https) ou, no `mcp-remote`, a opção `--allow-http` (confira na versão que você usa).

### Passo 1: subir e criar o Config DB

```powershell
docker compose -f docker-compose.local.yml up -d --build
docker compose -f docker-compose.local.yml ps
docker compose -f docker-compose.local.yml exec app env
docker compose -f docker-compose.local.yml logs -f app
```

Na primeira subida, isso cria sozinho, com os valores do `.env`:

- o usuário do banco: `POSTGRES_CONFIG_USER` (padrão `postgres`);
- o banco `analysis_config`;
- as 9 tabelas, a partir de `src/database/schema.sql`.

Espere `app` e `postgres` ficarem *healthy* (cerca de 1 minuto). Para usar outro usuário, mude `POSTGRES_CONFIG_USER` e `POSTGRES_CONFIG_PASSWORD` no `.env` **antes do primeiro `up`**.

### Passo 2: criar o banco de análises e um usuário só de leitura

O Config DB guarda a estrutura do app. Os dados que você vai analisar ficam num banco à parte, `analysis_data`, no mesmo container. O exemplo cria uma tabela `vendas` com 6 linhas.

```powershell
@'
CREATE ROLE analysis_reader LOGIN PASSWORD 'ReaderPwd_123';
CREATE DATABASE analysis_data;
\c analysis_data
CREATE TABLE vendas (
    id SERIAL PRIMARY KEY,
    data_venda DATE NOT NULL,
    regiao VARCHAR(20) NOT NULL,
    produto VARCHAR(100) NOT NULL,
    valor NUMERIC(12,2) NOT NULL
);
INSERT INTO vendas (data_venda, regiao, produto, valor) VALUES
 ('2026-01-10','Sul','Notebook',4500.00),('2026-01-15','Norte','Monitor',1200.50),
 ('2026-02-03','Sul','Teclado',350.00),('2026-02-20','Leste','Notebook',4700.00),
 ('2026-03-05','Oeste','Mouse',89.90),('2026-03-18','Sul','Monitor',1250.00);
GRANT CONNECT ON DATABASE analysis_data TO analysis_reader;
GRANT USAGE ON SCHEMA public TO analysis_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO analysis_reader;
'@ | docker compose -f docker-compose.local.yml exec -T postgres psql -U postgres -d analysis_config -v ON_ERROR_STOP=1
```

### Passo 3: inserir usuário e perfil da aplicação

O hash bcrypt é gerado pelo próprio Postgres (`pgcrypto`), então não precisa de Python. O e-mail deve estar em **minúsculas**.

```powershell
@'
CREATE EXTENSION IF NOT EXISTS pgcrypto;
INSERT INTO users (name, external_id, password_hash, created_by)
VALUES ('Administrador', 'admin@empresa.com', crypt('Senha@123', gen_salt('bf', 12)), 'setup');
INSERT INTO profiles (name, description) VALUES ('admin', 'Acesso a todas as análises');
INSERT INTO user_profiles (user_id, profile_id)
SELECT u.id, p.id FROM users u, profiles p WHERE u.external_id = 'admin@empresa.com' AND p.name = 'admin';
'@ | docker compose -f docker-compose.local.yml exec -T postgres psql -U postgres -d analysis_config -v ON_ERROR_STOP=1
```

> **Alternativa automática:** no compose local, o `src/database/seed_admin.sh` já cria na criação do banco o perfil `admin` e o usuário `admin` (senha padrão **conhecida** `Senh@123`), e o `scripts/setup-admin.ps1` emite o token em `secrets/admin-token.txt`. Se usar o script, os e-mails/senhas dos passos 3 e 6 abaixo mudam para `admin` / `Senh@123`.

### Passo 4: cifrar a senha do data source

A senha do `connection_config` é guardada cifrada com a `FERNET_KEY` do `.env`. Gere a cifrada:

```powershell
$enc = (docker compose -f docker-compose.local.yml exec -T app python -c "from security.crypto import encrypt_password; print(encrypt_password('ReaderPwd_123'))" 2>&1 | Out-String).Trim(); Write-Host $enc
```

### Passo 5: cadastrar data source, análise e liberar para o perfil

```powershell
@'
INSERT INTO data_sources (name, type, connection_config, created_by)
VALUES ('vendas_pg', 'postgresql',
        jsonb_build_object('host','postgres','port',5432,'database','analysis_data','user','analysis_reader','password',:'enc'),
        'setup');

INSERT INTO analyses (name, description, data_source_id, cache_frequency, parameters, created_by)
SELECT 'vendas_por_regiao', 'Vendas no período, com filtro opcional por região', ds.id, 'daily',
       '{"data_inicial":{"type":"date","required":true,"description":"Data inicial (YYYY-MM-DD)"},
         "data_final":{"type":"date","required":true,"description":"Data final (YYYY-MM-DD)"},
         "regiao":{"type":"string","required":false,"description":"Filtrar por região","enum":["Norte","Sul","Leste","Oeste","Centro"]}}'::jsonb,
       'setup'
FROM data_sources ds WHERE ds.name = 'vendas_pg';

INSERT INTO analysis_steps (analysis_id, step_order, step_type, definition)
SELECT a.id, 1, 'query',
       '{"sql":"SELECT data_venda, regiao, produto, valor FROM vendas WHERE data_venda BETWEEN :data_inicial AND :data_final AND (CAST(:regiao AS VARCHAR) IS NULL OR regiao = :regiao)",
         "params":["data_inicial","data_final","regiao"]}'::jsonb
FROM analyses a WHERE a.name = 'vendas_por_regiao';

INSERT INTO profile_analyses (profile_id, analysis_id)
SELECT p.id, a.id FROM profiles p, analyses a WHERE p.name = 'admin' AND a.name = 'vendas_por_regiao';
'@ | docker compose -f docker-compose.local.yml exec -T postgres psql -U postgres -d analysis_config -v ON_ERROR_STOP=1 -v "enc=$enc"
```

Pontos de atenção:

- O host é `postgres`, o nome do serviço na rede do compose, e a porta é `5432`. **Dentro do container não se usa `localhost`.**
- O `CAST(:regiao AS VARCHAR)` é necessário. Sem ele, o filtro opcional falha com *could not determine data type of parameter* e a análise retorna erro.
- O SQL da análise aceita só um `SELECT`, sem `;`.

### Passo 6: emitir o token e testar

```powershell
$r = curl.exe -sS -X POST http://localhost:3000/auth/token -H "Content-Type: application/json" -d '{\"email\":\"admin@empresa.com\",\"password\":\"Senha@123\",\"label\":\"teste\"}'; $r; $token = ($r | ConvertFrom-Json).token; "TOKEN: $token"
```

Lista as tools (deve aparecer `execute_vendas_por_regiao`):

```powershell
curl.exe -sS -X POST http://localhost:3000/mcp -H "Authorization: Bearer $token" -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}'
```

Executa a análise:

```powershell
curl.exe -sS -X POST http://localhost:3000/mcp -H "Authorization: Bearer $token" -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d '{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{\"name\":\"execute_vendas_por_regiao\",\"arguments\":{\"data_inicial\":\"2026-01-01\",\"data_final\":\"2026-02-28\",\"regiao\":\"Sul\"}}}'
```

Resultado esperado no último comando: `"status": "success"` com **2 linhas** (Notebook e Teclado, região Sul). Sem `regiao`, vêm as 6 linhas do período.

No cliente MCP use a URL `http://localhost:3000/mcp` com `Authorization: Bearer <token>`.

### Detalhes importantes

- O nome da tool é `execute_<nome da análise>`. O nome cadastrado é `vendas_por_regiao`, e o cliente enxerga `execute_vendas_por_regiao`.
- A `FERNET_KEY` **não pode mudar** depois. Os data sources cadastrados ficam ilegíveis se você trocar a chave.
- Os passos 2 a 5 só precisam rodar **uma vez**. Eles gravam no volume `pgdata`, e `down -v` apaga tudo. Sem o `-v`, os dados ficam.
- Para um segundo usuário, repita só os `INSERT` em `users` e `user_profiles` do Passo 3 (com outro e-mail).

---

## 2. Variações de ambiente

### Postgres instalado no Windows (sem Docker)

Substitua o Passo 1 pelos comandos abaixo, no `psql` como superusuário. Depois siga do Passo 2 em diante, trocando `docker compose ... exec -T postgres psql ...` por `psql -h localhost -p 5432 ...`.

```sql
CREATE ROLE analysis_app LOGIN PASSWORD 'troque_esta_senha';
CREATE DATABASE analysis_config OWNER analysis_app;
-- depois, conectado ao analysis_config como analysis_app:
--   \i src/database/schema.sql
```

Aponte também `POSTGRES_CONFIG_HOST=localhost`, a porta, o usuário e a senha no `.env`.

### Usar com TLS (https)

Trocar só a URL **não basta**: o servidor e as URLs precisam estar no mesmo modo.

1. No `.env`, mude `TLS_ENABLED=true`. Confirme que `TLS_CERT_FILE` e `TLS_KEY_FILE` apontam para certificados existentes em `certs/` (ex.: gerados com mkcert).
2. Recrie o app, porque a variável só é lida na subida (`restart` não relê o `.env`, então use `up -d`):

   ```powershell
   docker compose -f docker-compose.local.yml up -d app
   ```

3. Troque `http://` por `https://` em todas as URLs e acrescente `--ssl-no-revoke` nos `curl.exe` (certificado mkcert no Windows):

   ```powershell
   curl.exe --ssl-no-revoke https://localhost:3000/health
   ```

   No cliente MCP, a URL passa a ser `https://localhost:3000/mcp`.

O certificado mkcert só é aceito onde a CA dele está instalada. Para voltar ao HTTP: `TLS_ENABLED=false` e `up -d app` de novo.

---

## 3. Operação do dia a dia

### Parar sem perder dados

**Não use o `-v`**: os dados ficam no volume `pgdata`, e só o `-v` apaga volumes.

Parar e remover os containers, mantendo os dados:

```powershell
docker compose -f docker-compose.local.yml down
```

Remove os containers e a rede, mas o volume `pgdata` permanece. Ao subir de novo, o Postgres reaproveita o volume, com usuários, perfis, data sources, análises e tokens como estavam.

Só pausar (sem remover os containers):

```powershell
docker compose -f docker-compose.local.yml stop
docker compose -f docker-compose.local.yml start    # para retomar
```

### Voltar a usar

```powershell
docker compose -f docker-compose.local.yml up -d
```

**Não rode de novo os Passos 2 a 5.** O `schema.sql` só é aplicado quando o volume está vazio, então ele não recria nada nem duplica os dados.

### Conferir que os dados continuam lá

```powershell
docker volume ls --filter "name=mcp-analysis"          # deve listar mcp-analysis-local_pgdata
docker compose -f docker-compose.local.yml exec -T postgres psql -U postgres -d analysis_config -Atc "select count(*) from users"
```

### Executar comando no banco

```powershell
docker compose -f docker-compose.local.yml exec postgres psql -U postgres -d analysis_config -c "\d execution_history"
```

### O que preservar

- **Não troque a `FERNET_KEY`** do `.env`. A senha do data source (`vendas_pg`) está cifrada com ela; com outra chave a análise para de conectar.
- **Não troque a `POSTGRES_CONFIG_PASSWORD`** do `.env` com o volume já criado. O Postgres só lê essa variável na primeira inicialização, então o banco continua com a senha antiga e o app deixa de conseguir conectar.
- **Evite** estes comandos, que apagam os dados: `down -v`, `docker volume rm mcp-analysis-local_pgdata`, `docker volume prune` e `docker system prune --volumes`.

### Backup e restauração

Antes de mexer em algo arriscado, guarde uma cópia dos dados num arquivo:

```powershell
docker compose -f docker-compose.local.yml exec -T postgres pg_dumpall -U postgres | Out-File -Encoding utf8 backup.sql
```

Inclui o Config DB (`analysis_config`) e o banco de análises (`analysis_data`). Para restaurar, **com um volume novo e vazio**:

```powershell
Get-Content backup.sql -Raw | docker compose -f docker-compose.local.yml exec -T postgres psql -U postgres
```

Restaurar num volume que já tem o `analysis_config` gera erros de objetos já existentes.

---

## 4. Recomeçar do zero (limpeza)

> **Atenção:** os comandos desta seção apagam dados de forma irreversível.

### Ambiente local

```powershell
docker compose -f docker-compose.local.yml down -v --remove-orphans
```

- `down` para e remove os containers e a rede.
- `-v` apaga os volumes, ou seja, o `pgdata` com o Config DB inteiro: usuários, perfis, data sources, análises e tokens. **Irreversível.**
- `--remove-orphans` remove containers que sobraram de serviços que já saíram do compose (o `mysql`, por exemplo, se algum ficou de testes anteriores).

### Limpar também a imagem do app

Para um build do zero:

```powershell
docker compose -f docker-compose.local.yml down -v --remove-orphans --rmi local
```

O `--rmi local` remove a imagem do app (`mcp-analysis-local-app`). A do `postgres:16` fica, porque é baixada do Docker Hub e não precisa ser refeita.

### Remote e bancos opcionais

Cada compose tem o próprio projeto e volumes; limpe cada um que usou:

```powershell
docker compose -f docker-compose.remote.yml down -v --remove-orphans
docker compose -f docker/mysql/docker-compose.mysql.yml down -v
docker compose -f docker/sqlserver/docker-compose.sqlserver.yml down -v
docker compose -f docker/oracle/docker-compose.oracle.yml down -v
```

Os compose de MySQL, SQL Server e Oracle exigem a senha no `down` por causa do `:?` na interpolação. Se der erro de variável, passe a senha na hora, por exemplo `$env:MSSQL_SA_PASSWORD='x'` antes do comando.

### Conferir que ficou limpo

```powershell
docker ps -a --filter "name=mcp-analysis"
docker volume ls --filter "name=mcp-analysis"
```

Os dois devem voltar vazios.

### Recomeçar e o que não é apagado

Para recomeçar, rode o Passo 1 (`docker compose -f docker-compose.local.yml up -d --build`). Como o volume é novo, o Postgres recria o banco e as tabelas, e você refaz os Passos 2 a 6.

**Não são apagados:** o `.env` (inclui a `FERNET_KEY` e as senhas), os certificados em `certs/` e o código.

Se você trocar a `FERNET_KEY` ao recomeçar, nada se perde, já que o banco novo não tem data sources antigos. O contrário só importa quando se mantém o volume.

### Volume órfão do MySQL

Sobrou da época em que o MySQL fazia parte do compose local. Como o compose atual não declara mais o `mysqldata`, o `down -v` não o enxerga e não o remove. Apague direto pelo nome:

```powershell
docker volume rm mcp-analysis-local_mysqldata
```

Se der *volume is in use*, algum container ainda o usa (provavelmente um mysql antigo parado). Veja e remova:

```powershell
docker ps -a --filter "volume=mcp-analysis-local_mysqldata"
docker rm -f <nome-ou-id-do-container>
docker volume rm mcp-analysis-local_mysqldata
```

Depois confira:

```powershell
docker volume ls --filter "name=mcp-analysis"
```

Os dados desse volume eram só do MySQL de teste, não há nada a preservar. `docker volume prune` remove todos os volumes sem uso de uma vez, **inclusive de outros projetos**; prefira o `docker volume rm` pelo nome.

### Limpeza geral do Docker (cuidado)

Apaga todos os containers parados, redes sem uso, imagens sem uso e o cache de build do Docker, **inclusive de outros projetos**. Use só se quiser limpar o Docker inteiro:

```powershell
docker system prune -a --volumes
```

Pede confirmação antes de apagar. Para recomeçar este projeto, o `down -v` acima basta.

---

## 5. Pacote de instalação (dist)

O `docker-compose.dist.yml` e o `scripts/build-dist.ps1` geram a pasta `dist/` com o `.tar` (cerca de 235 MB). Um compose não gera `.tar`: ele só constrói e tagueia as imagens; o `.tar` vem do `docker save`, que o script executa depois do build.

### Gerar o pacote

Na raiz do projeto, no PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-dist.ps1 -Version 1.0.0
```

O `-ExecutionPolicy Bypass` evita o bloqueio de scripts do Windows. Opcionalmente use `-PostgresImage postgres:16.6` para fixar a versão do Postgres.

### Conteúdo de dist/

| Arquivo | Para quê |
|---|---|
| `mcp-analysis-1.0.0.tar` | as duas imagens, app e `postgres:16` |
| `docker-compose.yml` | cópia do `docker-compose.dist.yml` |
| `schema.sql` | o Postgres cria o banco a partir dele na primeira subida |
| `.env.example` | já com `APP_VERSION=1.0.0` e o comando para gerar a `FERNET_KEY` |
| `certs/` | pasta vazia com um `LEIA-ME.txt` |
| `INSTALL.md` | passo a passo de instalação e de atualização |
| `SHA256SUMS.txt` | hash do `.tar`, para conferir a cópia |

### Instalar em outro computador

Copie a pasta `dist/` inteira e, dentro dela:

```powershell
docker load -i mcp-analysis-1.0.0.tar
cp .env.example .env        # preencher a senha do Postgres e a FERNET_KEY
# colocar server.pem e server-key.pem em certs/
docker compose up -d
```

O `INSTALL.md` traz também como atualizar para uma nova versão.

### O que foi conferido e o que não foi testado

**Conferido** (o script rodou de ponta a ponta e gerou o pacote):

- **Conteúdo do `.tar`:** as duas imagens, `mcp-analysis:1.0.0` e `postgres:16`. O outro computador não precisa de internet.
- **Segredos:** a imagem do app não leva `.env` nem `certs/`. Roda como usuário 10001 (não root) e tem só `src/` mais o `requirements.txt`.
- **Compose do pacote:** resolve as duas imagens e o `schema.sql` ao lado do arquivo. O `pull_policy: never` impede o compose de tentar baixar `mcp-analysis` do Docker Hub.
- **Fora do git e do build:** o `dist/` já estava no `.gitignore` e foi acrescentado ao `.dockerignore`, para a pasta não entrar no contexto de build e inflar os próximos builds.

**Não testado:**

- A subida no destino: `docker load` e `docker compose up` numa máquina limpa.
- **TLS:** o certificado mkcert só é aceito onde a CA dele está instalada. Os clientes MCP exigem HTTPS confiável, então no outro computador instale essa CA ou use um certificado de verdade.
- **Arquitetura:** a imagem é `linux/amd64`. Para Mac com chip Apple seria preciso o `docker buildx` com `--platform`.

### Manutenção

O `.env.example` do pacote é gerado dentro do script. Se acrescentar uma variável nova ao compose, inclua-a lá também (há um aviso no cabeçalho do script).
