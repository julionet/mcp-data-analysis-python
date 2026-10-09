# Guia de uso — ambiente local com Docker (macOS)

Como subir, configurar, operar, limpar e empacotar a aplicação. Os comandos são para **zsh/bash** (o terminal padrão do macOS), executados na **raiz do repositório**, com o compose `docker-compose.local.yml`.

> Em Windows, os scripts equivalentes são `scripts/setup-admin.ps1` e `scripts/build-dist.ps1` (PowerShell). Os passos com SQL e `curl` são os mesmos.

> **Este guia usa HTTP (`http://`) por padrão**, só para uso na sua máquina (`localhost`). O Passo 0 prepara o ambiente para isso. Para HTTPS, veja [Usar com TLS (https)](#usar-com-tls-https).

## Índice

1. [Subir a aplicação (passo a passo)](#1-subir-a-aplicação-passo-a-passo)
   - [Passo 0: preparar o ambiente (.env em HTTP)](#passo-0-preparar-o-ambiente-env-em-http)
   - [Passo 1: subir e criar o Config DB](#passo-1-subir-e-criar-o-config-db)
   - [Passo 2: criar o banco de análises e um usuário só de leitura](#passo-2-criar-o-banco-de-análises-e-um-usuário-só-de-leitura)
   - [Passo 3: criar o administrador (escolha uma opção)](#passo-3-criar-o-administrador-escolha-uma-opção)
     - [Opção A (recomendada): script setup-admin.sh](#opção-a-recomendada-script-setup-adminsh)
     - [Opção B: manual, com SQL](#opção-b-manual-com-sql)
   - [Passo 4: cifrar a senha do data source](#passo-4-cifrar-a-senha-do-data-source)
   - [Passo 5: cadastrar data source, análise e liberar para o perfil](#passo-5-cadastrar-data-source-análise-e-liberar-para-o-perfil)
   - [Passo 6: emitir o token e testar](#passo-6-emitir-o-token-e-testar)
   - [Detalhes importantes](#detalhes-importantes)
   - [Opções do setup-admin.sh](#opções-do-setup-adminsh)
   - [Mudar a senha do admin](#mudar-a-senha-do-admin)
2. [Variações de ambiente](#2-variações-de-ambiente)
   - [Postgres instalado no Mac (sem Docker)](#postgres-instalado-no-mac-sem-docker)
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
6. [Conectar ao Claude Code](#6-conectar-ao-claude-code)
   - [Adicionar o servidor MCP](#adicionar-o-servidor-mcp)
   - [Conferir](#conferir)
   - [Se já existir uma entrada analise-dados](#se-já-existir-uma-entrada-analise-dados)
   - [Pontos de atenção](#pontos-de-atenção)
7. [Testes e cobertura](#7-testes-e-cobertura)
   - [Rodar os testes](#rodar-os-testes)
   - [Medir a cobertura](#medir-a-cobertura)

---

## 1. Subir a aplicação (passo a passo)

### Passo 0: preparar o ambiente (.env em HTTP)

```bash
cp .env.example .env
```

Edite o `.env` e confira estes valores **antes do primeiro `up`**:

| Variável | Valor | Por quê |
|---|---|---|
| `TLS_ENABLED` | `false` | já vem `false` no `.env.example`: o servidor sobe em HTTP puro; com `true` a porta 3000 só aceita TLS e todas as URLs abaixo falhariam |
| `FERNET_KEY` | uma chave sua | cifra as senhas dos data sources; o `scripts/setup-admin.sh` gera uma no `.env` se estiver com o valor de exemplo (nunca sobrescreve uma real) |
| `POSTGRES_CONFIG_PASSWORD` | uma senha sua | só vale na primeira inicialização do volume |

Com `TLS_ENABLED=false` os certificados de `certs/` **não são necessários** (`TLS_CERT_FILE` e `TLS_KEY_FILE` são ignorados), e o healthcheck do container já usa `http`. Não é preciso mudar o compose nem o código.

> **Cuidado:** em HTTP, senha e token trafegam em **texto puro**. Use só em `localhost`, nunca com acesso pela rede. Clientes MCP como o Claude Desktop podem recusar `http://` (ADR-006 da ARQUITETURA); nesse caso, veja [Usar com TLS (https)](#usar-com-tls-https) ou, no `mcp-remote`, a opção `--allow-http` (confira na versão que você usa).

### Passo 1: subir e criar o Config DB

Antes de subir, confirme que o Docker Desktop está aberto.

```bash
docker compose -f docker-compose.local.yml up -d --build
docker compose -f docker-compose.local.yml ps
docker compose -f docker-compose.local.yml exec app env
docker compose -f docker-compose.local.yml logs -f app
```

Na primeira subida, isso cria sozinho, com os valores do `.env`:

- o usuário do banco: `POSTGRES_CONFIG_USER` (padrão `postgres`);
- o banco `analysis_config`;
- as tabelas, a partir de `src/database/schema.sql`.

Espere `app` e `postgres` ficarem *healthy* (cerca de 1 minuto). Para usar outro usuário, mude `POSTGRES_CONFIG_USER` e `POSTGRES_CONFIG_PASSWORD` no `.env` **antes do primeiro `up`**.

### Passo 2: criar o banco de análises e um usuário só de leitura

O Config DB guarda a estrutura do app. Os dados que você vai analisar ficam num banco à parte, `analysis_data`, no mesmo container. O exemplo cria uma tabela `vendas` com 6 linhas.

```bash
docker compose -f docker-compose.local.yml exec -T postgres psql -U postgres -d analysis_config -v ON_ERROR_STOP=1 <<'SQL'
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
SQL
```

Se o comando já foi rodado antes, `CREATE ROLE` e `CREATE DATABASE` falham por já existirem. Não rode de novo.

### Passo 3: criar o administrador (escolha uma opção)

Faça **uma** das duas opções. Elas criam o mesmo perfil `admin`, que é único no banco; rodar as duas gera conflito.

#### Opção A (recomendada): script setup-admin.sh

Após o Passo 1, com o app e o postgres *healthy*:

```bash
./scripts/setup-admin.sh --no-up
```

O script faz, nesta ordem:

1. **Gera a `FERNET_KEY`** no `.env`, se ela estiver vazia ou com o valor de exemplo (nunca sobrescreve uma chave real).
2. **Aguarda o `/health`** do app em `http://localhost:3000`. Com `--no-up` ele não sobe o compose, porque o Passo 1 já subiu.
3. **Cria o administrador** pelo seed (`src/database/seed_admin.sh`): o perfil `admin`, o usuário `admin` com senha `Senh@123` (conhecida) e o vínculo entre eles. O perfil também é ligado às análises que já existirem.
4. **Emite o token** por `POST /auth/token` e salva em `secrets/admin-token.txt` (permissão `600`).

No fim, o script mostra o token e o trecho de configuração do cliente MCP. O token aparece **uma única vez**; o arquivo é a única cópia.

O script **não** cria o banco de análises, o data source nem a análise. Isso continua nos Passos 2, 4 e 5.

Se o app e o banco ainda não estiverem no ar, remova `--no-up` para que o script suba o compose.

#### Opção B: manual, com SQL

O hash bcrypt é gerado pelo próprio Postgres (`pgcrypto`), então não precisa de Python. O e-mail deve estar em **minúsculas**.

```bash
docker compose -f docker-compose.local.yml exec -T postgres psql -U postgres -d analysis_config -v ON_ERROR_STOP=1 <<'SQL'
CREATE EXTENSION IF NOT EXISTS pgcrypto;
INSERT INTO users (name, external_id, password_hash, created_by)
VALUES ('Administrador', 'admin@empresa.com', crypt('Senha@123', gen_salt('bf', 12)), 'setup');
INSERT INTO profiles (name, description) VALUES ('admin', 'Acesso a todas as análises');
INSERT INTO user_profiles (user_id, profile_id)
SELECT u.id, p.id FROM users u, profiles p WHERE u.external_id = 'admin@empresa.com' AND p.name = 'admin';
SQL
```

Com esta opção, o login do Passo 6 é `admin@empresa.com`, e não `admin`.

### Passo 4: cifrar a senha do data source

A senha do `connection_config` é guardada cifrada com a `FERNET_KEY` do `.env`. Gere a cifrada:

```bash
enc=$(docker compose -f docker-compose.local.yml exec -T app python -c "from security.crypto import encrypt_password; print(encrypt_password('ReaderPwd_123'))")
echo "$enc"
```

A variável `enc` fica disponível só nesta sessão do terminal. Se você abrir outro terminal antes do Passo 5, rode este passo de novo. Confirme que ela não está vazia: `echo ${#enc}` deve mostrar `100`.

### Passo 5: cadastrar data source, análise e liberar para o perfil

```bash
docker compose -f docker-compose.local.yml exec -T postgres psql -U postgres -d analysis_config -v ON_ERROR_STOP=1 -v "enc=$enc" <<'SQL'
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
SQL
```

Pontos de atenção:

- O host é `postgres`, o nome do serviço na rede do compose, e a porta é `5432`. **Dentro do container não se usa `localhost`.**
- O `CAST(:regiao AS VARCHAR)` é necessário. Sem ele, o filtro opcional falha com *could not determine data type of parameter* e a análise retorna erro.
- O SQL da análise aceita só um `SELECT`, sem `;`.
- Se a análise responder `DATA_SOURCE_UNAVAILABLE` com `"retryable": true`, quase sempre a senha do data source ficou vazia (a variável `enc` estava vazia no Passo 5). Confira com `docker compose -f docker-compose.local.yml exec -T postgres psql -U postgres -d analysis_config -Atc "select coalesce(length(connection_config->>'password'),-1) from data_sources where name='vendas_pg'"`: o resultado deve ser `100`. Se for `0`, rode o Passo 4 e depois este UPDATE:

  ```bash
  docker compose -f docker-compose.local.yml exec -T postgres psql -U postgres -d analysis_config -v ON_ERROR_STOP=1 -v "enc=$enc" <<'SQL'
  UPDATE data_sources SET connection_config = jsonb_set(connection_config, '{password}', to_jsonb(:'enc'::text)) WHERE name = 'vendas_pg';
  SQL
  ```

  Os detalhes ficam no log: `docker compose -f docker-compose.local.yml logs app | grep -i InvalidToken`.

### Passo 6: emitir o token e testar

Se usou a **Opção A**, o token já está no arquivo:

```bash
TOKEN=$(cat secrets/admin-token.txt)
```

Se usou a **Opção B**, emita o token agora:

```bash
TOKEN=$(curl -sS -X POST http://localhost:3000/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@empresa.com","password":"Senha@123","label":"teste"}' \
  | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')
echo "TOKEN: $TOKEN"
```

Lista as tools (deve aparecer `execute_vendas_por_regiao`):

```bash
curl -sS -X POST http://localhost:3000/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Executa a análise:

```bash
curl -sS -X POST http://localhost:3000/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"execute_vendas_por_regiao","arguments":{"data_inicial":"2026-01-01","data_final":"2026-02-28","regiao":"Sul"}}}'
```

Resultado esperado no último comando: `"status": "success"` com **2 linhas** (Notebook e Teclado, região Sul). Sem `regiao`, vêm as 6 linhas do período.

No cliente MCP use a URL `http://localhost:3000/mcp` com `Authorization: Bearer <token>`.

### Detalhes importantes

- O nome da tool é `execute_<nome da análise>`. O nome cadastrado é `vendas_por_regiao`, e o cliente enxerga `execute_vendas_por_regiao`.
- A `FERNET_KEY` **não pode mudar** depois. Os data sources cadastrados ficam ilegíveis se você trocar a chave.
- Os Passos 2, 4 e 5 só precisam rodar **uma vez**. Eles gravam no volume `pgdata`, e `down -v` apaga tudo. Sem o `-v`, os dados ficam.
- **Análise criada depois do admin:** o seed liga o perfil `admin` só às análises que já existem no momento em que roda. Depois de criar uma análise nova, reexecute o script (é idempotente): `./scripts/setup-admin.sh --no-up --skip-token`. Se o admin foi criado pela Opção B, o Passo 5 já faz esse vínculo.
- Para um segundo usuário, use a Opção B com outro e-mail (repita só os `INSERT` em `users` e `user_profiles`, sem recriar o perfil `admin`).

### Opções do setup-admin.sh

Rode da raiz do repositório com `./scripts/setup-admin.sh [opções]`. `--help` mostra a lista.

| Opção (bash) | Opção (PowerShell) | Padrão | Descrição |
|---|---|---|---|
| `--no-up` | `-NoUp` | (não usa) | não roda `docker compose up -d` (os containers já estão no ar) |
| `--password <senha>` | `-Password <senha>` | `Senh@123` | senha do admin |
| `--reset-password` | `-ResetPassword` | (não usa) | regrava a senha de um admin que já existe |
| `--skip-token` | `-SkipToken` | (não usa) | não emite o token (só cria o admin e vincula as análises) |
| `--expire-days <n>` | `-ExpireDays <n>` | `0` (padrão do servidor) | validade do token, em dias |
| `--token-label <texto>` | `-TokenLabel <texto>` | `admin-mcp` | rótulo do token |
| `--login <email>` | `-Login <email>` | `admin` | login do admin |
| `--api-url <url>` | `-ApiUrl <url>` | `http(s)://localhost:<SERVER_PORT>` | URL da API, se não for a do `.env` |
| `--token-file <arquivo>` | `-TokenFile <arquivo>` | `secrets/admin-token.txt` | onde salvar o token |
| `--compose-file <arquivo>` | `-ComposeFile <arquivo>` | `docker-compose.local.yml` | compose usado |
| `--env-file <arquivo>` | `-EnvFile <arquivo>` | `.env` | arquivo de variáveis |
| `--project-name <nome>` | `-ProjectName <nome>` | (não usa) | nome do projeto do compose (`-p`) |
| `--force-new-fernet-key` | `-ForceNewFernetKey` | (não usa) | gera nova `FERNET_KEY` (torna ilegíveis os data sources já gravados) |

Exemplos:

```bash
./scripts/setup-admin.sh --no-up --expire-days 365 --token-label "Claude Desktop"
./scripts/setup-admin.sh --no-up --skip-token
```

### Mudar a senha do admin

A senha padrão `Senh@123` é **conhecida** e serve só para desenvolvimento. Para trocar, com o app no ar:

```bash
./scripts/setup-admin.sh --no-up --password 'SuaNovaSenha!1' --reset-password
```

O comando regrava a senha e emite um novo token. Com a senha de um admin já existente, sem `--reset-password` o banco não é alterado.

Se a senha informada não bater com a do banco, o script para com a mensagem `401`, sem trocar a senha nem emitir token. Para trocar a senha de um admin que você não lembra, use `--reset-password` com a nova senha.

---

## 2. Variações de ambiente

### Postgres instalado no Mac (sem Docker)

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

   ```bash
   docker compose -f docker-compose.local.yml up -d app
   ```

3. Troque `http://` por `https://` em todas as URLs e teste:

   ```bash
   curl https://localhost:3000/health
   ```

   No cliente MCP, a URL passa a ser `https://localhost:3000/mcp`.

No macOS, `mkcert -install` instala a CA no Keychain do sistema, e o `curl` do Mac confia nela. Se mesmo assim o certificado for recusado, rode `mkcert -install` de novo e confira a CA no Keychain. Para voltar ao HTTP: `TLS_ENABLED=false` e `up -d app` de novo.

---

## 3. Operação do dia a dia

### Parar sem perder dados

**Não use o `-v`**: os dados ficam no volume `pgdata`, e só o `-v` apaga volumes.

Parar e remover os containers, mantendo os dados:

```bash
docker compose -f docker-compose.local.yml down
```

Remove os containers e a rede, mas o volume `pgdata` permanece. Ao subir de novo, o Postgres reaproveita o volume, com usuários, perfis, data sources, análises e tokens como estavam.

Só pausar (sem remover os containers):

```bash
docker compose -f docker-compose.local.yml stop
docker compose -f docker-compose.local.yml start    # para retomar
```

### Voltar a usar

```bash
docker compose -f docker-compose.local.yml up -d
```

**Não rode de novo os Passos 2, 4 e 5.** O `schema.sql` só é aplicado quando o volume está vazio, então ele não recria nada nem duplica os dados. O mesmo vale para o `setup-admin.sh`, que é idempotente.

### Conferir que os dados continuam lá

```bash
docker volume ls --filter "name=mcp-analysis"          # deve listar mcp-analysis-local_pgdata
docker compose -f docker-compose.local.yml exec -T postgres psql -U postgres -d analysis_config -Atc "select count(*) from users"
```

### Executar comando no banco

```bash
docker compose -f docker-compose.local.yml exec postgres psql -U postgres -d analysis_config -c "\d execution_history"
```

### O que preservar

- **Não troque a `FERNET_KEY`** do `.env`. A senha do data source (`vendas_pg`) está cifrada com ela; com outra chave a análise para de conectar.
- **Não troque a `POSTGRES_CONFIG_PASSWORD`** do `.env` com o volume já criado. O Postgres só lê essa variável na primeira inicialização, então o banco continua com a senha antiga e o app deixa de conseguir conectar.
- **Guarde o `secrets/admin-token.txt`** se for usá-lo no cliente MCP. O token não pode ser recuperado do banco; só o hash fica guardado.
- **Evite** estes comandos, que apagam os dados: `down -v`, `docker volume rm mcp-analysis-local_pgdata`, `docker volume prune` e `docker system prune --volumes`.

### Backup e restauração

Antes de mexer em algo arriscado, guarde uma cópia dos dados num arquivo:

```bash
docker compose -f docker-compose.local.yml exec -T postgres pg_dumpall -U postgres > backup.sql
```

Inclui o Config DB (`analysis_config`) e o banco de análises (`analysis_data`). Para restaurar, **com um volume novo e vazio**:

```bash
docker compose -f docker-compose.local.yml exec -T postgres psql -U postgres < backup.sql
```

Restaurar num volume que já tem o `analysis_config` gera erros de objetos já existentes.

---

## 4. Recomeçar do zero (limpeza)

> **Atenção:** os comandos desta seção apagam dados de forma irreversível.

### Ambiente local

```bash
docker compose -f docker-compose.local.yml down -v --remove-orphans
```

- `down` para e remove os containers e a rede.
- `-v` apaga os volumes, ou seja, o `pgdata` com o Config DB inteiro: usuários, perfis, data sources, análises e tokens. **Irreversível.**
- `--remove-orphans` remove containers que sobraram de serviços que já saíram do compose (o `mysql`, por exemplo, se algum ficou de testes anteriores).

### Limpar também a imagem do app

Para um build do zero:

```bash
docker compose -f docker-compose.local.yml down -v --remove-orphans --rmi local
```

O `--rmi local` remove a imagem do app (`mcp-analysis-local-app`). A do `postgres:16` fica, porque é baixada do Docker Hub e não precisa ser refeita.

### Remote e bancos opcionais

Cada compose tem o próprio projeto e volumes; limpe cada um que usou:

```bash
docker compose -f docker-compose.remote.yml down -v --remove-orphans
docker compose -f docker/mysql/docker-compose.mysql.yml down -v
docker compose -f docker/sqlserver/docker-compose.sqlserver.yml down -v
docker compose -f docker/oracle/docker-compose.oracle.yml down -v
```

Os compose de MySQL, SQL Server e Oracle exigem a senha no `down` por causa do `:?` na interpolação. Se der erro de variável, passe a senha na hora, por exemplo `MSSQL_SA_PASSWORD='x' docker compose -f docker/sqlserver/docker-compose.sqlserver.yml down -v`.

### Conferir que ficou limpo

```bash
docker ps -a --filter "name=mcp-analysis"
docker volume ls --filter "name=mcp-analysis"
```

Os dois devem voltar vazios.

### Recomeçar e o que não é apagado

Para recomeçar, rode o Passo 1 (`docker compose -f docker-compose.local.yml up -d --build`). Como o volume é novo, o Postgres recria o banco e as tabelas, e você refaz os Passos 2 a 6.

**Não são apagados:** o `.env` (inclui a `FERNET_KEY` e as senhas), os certificados em `certs/`, o `secrets/admin-token.txt` (o token antigo deixa de valer, mas o arquivo fica) e o código.

Se você trocar a `FERNET_KEY` ao recomeçar, nada se perde, já que o banco novo não tem data sources antigos. O contrário só importa quando se mantém o volume.

### Volume órfão do MySQL

Sobrou da época em que o MySQL fazia parte do compose local. Como o compose atual não declara mais o `mysqldata`, o `down -v` não o enxerga e não o remove. Apague direto pelo nome:

```bash
docker volume rm mcp-analysis-local_mysqldata
```

Se der *volume is in use*, algum container ainda o usa (provavelmente um mysql antigo parado). Veja e remova:

```bash
docker ps -a --filter "volume=mcp-analysis-local_mysqldata"
docker rm -f <nome-ou-id-do-container>
docker volume rm mcp-analysis-local_mysqldata
```

Depois confira:

```bash
docker volume ls --filter "name=mcp-analysis"
```

Os dados desse volume eram só do MySQL de teste, não há nada a preservar. `docker volume prune` remove todos os volumes sem uso de uma vez, **inclusive de outros projetos**; prefira o `docker volume rm` pelo nome.

### Limpeza geral do Docker (cuidado)

Apaga todos os containers parados, redes sem uso, imagens sem uso e o cache de build do Docker, **inclusive de outros projetos**. Use só se quiser limpar o Docker inteiro:

```bash
docker system prune -a --volumes
```

Pede confirmação antes de apagar. Para recomeçar este projeto, o `down -v` acima basta.

---

## 5. Pacote de instalação (dist)

O `docker-compose.dist.yml` e o `scripts/build-dist.sh` geram a pasta `dist/` com o `.tar` (cerca de 235 MB). Um compose não gera `.tar`: ele só constrói e tagueia as imagens; o `.tar` vem do `docker save`, que o script executa depois do build.

### Gerar o pacote

Na raiz do projeto, com o Docker Desktop aberto:

```bash
./scripts/build-dist.sh --version 1.0.0
```

Opcionalmente use `--postgres-image postgres:16.6` para fixar a versão do Postgres. `./scripts/build-dist.sh --help` mostra as opções.

### Conteúdo de dist/

| Arquivo | Para quê |
|---|---|
| `mcp-analysis-1.0.0.tar` | as duas imagens, app e `postgres:16` |
| `docker-compose.yml` | cópia do `docker-compose.dist.yml` |
| `schema.sql` | o Postgres cria o banco a partir dele na primeira subida |
| `seed_admin.sh` | cria o admin na criação do banco |
| `setup-admin.sh` | equivalente do script para macOS/Linux (PowerShell: `setup-admin.ps1`) |
| `.env.example` | já com `APP_VERSION=1.0.0` e o comando para gerar a `FERNET_KEY` |
| `certs/` | pasta vazia com um `LEIA-ME.txt` |
| `INSTALL.md` | passo a passo de instalação e de atualização |
| `SHA256SUMS.txt` | hash do `.tar`, para conferir a cópia |

### Instalar em outro computador

Copie a pasta `dist/` inteira e, dentro dela:

```bash
docker load -i mcp-analysis-1.0.0.tar
cp .env.example .env        # preencher POSTGRES_CONFIG_PASSWORD
# colocar server.pem e server-key.pem em certs/
./setup-admin.sh            # gera a FERNET_KEY, sobe o compose, cria o admin e emite o token
```

O `INSTALL.md` traz também como atualizar para uma nova versão. O pacote usa TLS (`TLS_ENABLED=true`), então o `setup-admin.sh` acessa a API em `https://localhost:3000`.

### O que foi conferido e o que não foi testado

**Conferido:**

- **Build no macOS:** `scripts/build-dist.sh` rodou de ponta a ponta e gerou o `.tar` (234 MB) e a pasta `dist/`.
- **Integridade:** `shasum -a 256 -c SHA256SUMS.txt` confere.
- **Segredos:** a imagem do app não leva `.env` nem `certs/`. Roda como usuário 10001 (não root) e tem só `src/` mais o `requirements.txt`.
- **Fora do git e do build:** o `dist/` já estava no `.gitignore` e foi acrescentado ao `.dockerignore`, para a pasta não entrar no contexto de build e inflar os próximos builds.

**Não testado:**

- A subida no destino: `docker load`, `setup-admin.sh` e `docker compose up -d` numa máquina limpa.
- **TLS:** o certificado mkcert só é aceito onde a CA dele está instalada. Os clientes MCP exigem HTTPS confiável, então no outro computador instale essa CA ou use um certificado de verdade.
- **Arquitetura:** a imagem sai na arquitetura da máquina de build. No Mac com Apple Silicon ela é `arm64`; para um destino `amd64` é preciso gerar com `docker buildx build --platform linux/amd64`, o que o script ainda não faz.

### Manutenção

O `.env.example` do pacote é gerado dentro do script `build-dist.sh` (e no `build-dist.ps1`). Se acrescentar uma variável nova ao compose, inclua-a nos dois scripts (há um aviso no cabeçalho deles).

---

## 6. Conectar ao Claude Code

Pré-requisito: o app no ar em HTTP (Passo 1) e um token emitido (Passo 3 ou 6).

### Adicionar o servidor MCP

Com o token no arquivo gerado pelo script (Opção A):

```bash
TOKEN=$(cat secrets/admin-token.txt)
claude mcp add --transport http --scope user analise-dados http://localhost:3000/mcp --header "Authorization: Bearer $TOKEN"
```

Se o token foi emitido pelo `curl` do Passo 6 (Opção B), use a mesma linha depois de definir `TOKEN` como no Passo 6.

- `--scope user` deixa o servidor disponível em todos os projetos do seu usuário. Sem a opção, o padrão é `local`, que vale só para a pasta atual.
- O nome `analise-dados` é o que aparece no Claude Code. Se você mudar, ajuste também a documentação do cliente.

### Conferir

```bash
claude mcp list
claude mcp get analise-dados
```

`claude mcp list` deve mostrar `analise-dados` como `✓ Connected`. Dentro do Claude Code, o comando `/mcp` lista o servidor, e a tool aparece como `execute_vendas_por_regiao`.

### Se já existir uma entrada `analise-dados`

Uma tentativa anterior pode ter deixado a entrada com `https://127.0.0.1:3000/mcp`, que falha com `EPROTO` quando o app está em HTTP. Nesse caso, remova a entrada antiga antes de adicionar a nova:

```bash
claude mcp remove analise-dados
```

Se o `remove` não encontrar a entrada, confira em qual escopo ela está com `claude mcp list` e use `--scope user` ou `--scope local` no comando.

### Pontos de atenção

- O token fica **em texto puro** na configuração do Claude Code (`~/.claude.json`). Não compartilhe esse arquivo, e revogue o token se ele vazar.
- Com HTTP, o token trafega sem criptografia. Use só em `localhost`.
- Para o servidor em HTTPS (ver [Usar com TLS (https)](#usar-com-tls-https)), troque a URL para `https://localhost:3000/mcp`. Como o Claude Code roda sobre Node, ele não usa o Keychain do Mac, então o certificado mkcert precisa ser informado à parte. Antes de abrir o Claude Code:

  ```bash
  export NODE_EXTRA_CA_CERTS="$(mkcert -CAROOT)/rootCA.pem"
  ```

- Para remover o servidor depois: `claude mcp remove analise-dados --scope user`.

### Documentação da API (Swagger, só local)

Com `DOCS_ENABLED=true` (padrão no `.env.example` e no compose local), o app serve `http://localhost:3000/docs` (Swagger UI), `/redoc` e `/openapi.json`. Fora do ambiente local a variável fica ausente (`false`) e as três URLs respondem 404; os compose remote e dist não a repassam.

1. Em `POST /auth/token`, use **Try it out** com e-mail e senha e copie o `token` da resposta.
2. Clique em **Authorize**, cole só o token (o Swagger acrescenta `Bearer`) e confirme.
3. Execute qualquer rota; as de `/admin/*` exigem um usuário administrador.

O contrato HTTP versionado está em [`docs/openapi.json`](docs/openapi.json) (para geradores de cliente, Postman etc.) e o do `/mcp`, que o OpenAPI não descreve, em [`docs/MCP.md`](docs/MCP.md). Depois de mudar rotas ou schemas, regenere o arquivo (um teste falha se ele ficar desatualizado):

```bash
.venv/bin/python scripts/export_openapi.py
```

---

## 7. Testes e cobertura

Use o Python do `.venv` (o Python global pode ter outra versão do pacote `mcp`, incompatível). No Windows: `.venv\Scripts\python`. Instale as dependências de desenvolvimento uma vez: `.venv/bin/python -m pip install -r requirements-dev.txt`.

### Rodar os testes

```bash
# unitários — não precisam de banco (referência do critério de cobertura)
.venv/bin/python -m pytest tests -m "not integration"

# tudo, inclusive integração (Config DB do compose local no ar, localhost:5433)
.venv/bin/python -m pytest tests
```

Os testes marcados `integration` (`tests/test_*_integration.py`) exigem o Postgres do compose e se pulam sozinhos quando o banco não está disponível. Teste novo que precisa de banco real recebe `pytestmark = pytest.mark.integration`; os demais não podem depender de rede nem de banco.

### Medir a cobertura

```bash
# só unitários, sem banco: falha se a cobertura (linhas + branches de src/) ficar abaixo de 90%
.venv/bin/python -m pytest tests -m "not integration" --cov

# mesma medição com o Config DB no ar
.venv/bin/python -m pytest tests --cov

# relatório HTML opcional em htmlcov/index.html
.venv/bin/python -m pytest tests -m "not integration" --cov --cov-report=html
```

A configuração está em `.coveragerc` (`source = src`, branch coverage, `fail_under = 90`). A meta do projeto é 80%; o limite de 90% protege contra regressão. Linhas faltantes aparecem na coluna `Missing` do relatório. Todo `# pragma: no cover` precisa de um comentário com o motivo.

