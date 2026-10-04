# Como subir a aplicação em produção

## Passo 1: subir e criar banco, usuário do banco e tabelas

docker compose -f docker-compose.local.yml up -d --build
docker compose -f docker-compose.local.yml ps
docker compose -f docker-compose.local.yml exec app env
docker compose -f docker-compose.local.yml logs -f app
Isso cria sozinho, na primeira subida, com os valores do .env:
- O usuário do banco: POSTGRES_CONFIG_USER, que é postgres.
- O banco: analysis_config.
- As 9 tabelas, a partir de src/database/schema.sql.

Espere app e postgres ficarem healthy (cerca de 1 minuto). Para usar outro usuário, mude POSTGRES_CONFIG_USER e
POSTGRES_CONFIG_PASSWORD no .env antes do primeiro up.

## Passo 2: criar o banco de análises (dados) e um usuário só de leitura

O Config DB guarda a estrutura do app. Os dados que você vai analisar ficam num banco à parte, analysis_data, no mesmo
container. O exemplo cria uma tabela vendas com 6 linhas.
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

## Passo 3: inserir usuário e perfil da aplicação

O hash bcrypt é gerado pelo próprio Postgres (pgcrypto), então não precisa de Python. O e-mail deve estar em minúsculas.
@'
CREATE EXTENSION IF NOT EXISTS pgcrypto;
INSERT INTO users (name, external_id, password_hash, created_by)
VALUES ('Administrador', 'admin@empresa.com', crypt('Senha@123', gen_salt('bf', 12)), 'setup');
INSERT INTO profiles (name, description) VALUES ('admin', 'Acesso a todas as análises');
INSERT INTO user_profiles (user_id, profile_id)
SELECT u.id, p.id FROM users u, profiles p WHERE u.external_id = 'admin@empresa.com' AND p.name = 'admin';
'@ | docker compose -f docker-compose.local.yml exec -T postgres psql -U postgres -d analysis_config -v ON_ERROR_STOP=1

## Passo 4: cifrar a senha do data source

A senha do connection_config é guardada cifrada com a FERNET_KEY do .env. Gere a cifrada:
$enc = (docker compose -f docker-compose.local.yml exec -T app python -c "from security.crypto import encrypt_password; print(encrypt_password('ReaderPwd_123'))" 2>&1 | Out-String).Trim(); Write-Host $enc

## Passo 5: cadastrar data source, análise e liberar para o perfil

 @'
>> INSERT INTO data_sources (name, type, connection_config, created_by)
>> VALUES ('vendas_pg', 'postgresql',
>>         jsonb_build_object('host','postgres','port',5432,'database','analysis_data','user','analysis_reader','password',:'enc'),
>>         'setup');
>>
>> INSERT INTO analyses (name, description, data_source_id, cache_frequency, parameters, created_by)
>> SELECT 'vendas_por_regiao', 'Vendas no período, com filtro opcional por região', ds.id, 'daily',
>>        '{"data_inicial":{"type":"date","required":true,"description":"Data inicial (YYYY-MM-DD)"},
>>          "data_final":{"type":"date","required":true,"description":"Data final (YYYY-MM-DD)"},
>>          "regiao":{"type":"string","required":false,"description":"Filtrar por região","enum":["Norte","Sul","Leste","Oeste","Centro"]}}'::jsonb,
>>        'setup'
>> FROM data_sources ds WHERE ds.name = 'vendas_pg';
>>
>> INSERT INTO analysis_steps (analysis_id, step_order, step_type, definition)
>> SELECT a.id, 1, 'query',
>>        '{"sql":"SELECT data_venda, regiao, produto, valor FROM vendas WHERE data_venda BETWEEN :data_inicial AND :data_final AND (CAST(:regiao AS VARCHAR) IS NULL OR regiao = :regiao)",
>>          "params":["data_inicial","data_final","regiao"]}'::jsonb
>> FROM analyses a WHERE a.name = 'vendas_por_regiao';
>>
>> INSERT INTO profile_analyses (profile_id, analysis_id)
>> SELECT p.id, a.id FROM profiles p, analyses a WHERE p.name = 'admin' AND a.name = 'vendas_por_regiao';
>> '@ | docker compose -f docker-compose.local.yml exec -T postgres psql -U postgres -d analysis_config -v ON_ERROR_STOP=1 -v "enc=$enc"                                                                                                             
- O host é postgres, o nome do serviço na rede do compose, e a porta é 5432. Dentro do container não se usa localhost.
- O CAST(:regiao AS VARCHAR) é necessário. Sem ele, o filtro opcional falhava com could not determine data type of parameter   a análise retornava erro. Essa falha apareceu no meu primeiro teste.
- O SQL da análise aceita só um SELECT, sem ;.                                                                               

## Executar comando no banco

docker compose -f docker-compose.local.yml exec postgres psql -U postgres -d analysis_config -c "\d execution_history"

## Passo 6: emitir o token e testar

$r = curl.exe -sS -X POST http://localhost:3000/auth/token -H "Content-Type: application/json" -d '{\"email\":\"admin@empresa.com\",\"password\":\"Senha@123\",\"label\":\"teste\"}'; $r; $token = ($r | ConvertFrom-Json).token; "TOKEN: $token"

# lista as tools (deve aparecer execute_vendas_por_regiao)
curl.exe -sS --ssl-no-revoke -X POST https://localhost:3000/mcp -H "Authorization: Bearer $token" -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}'

# executa a análise
curl.exe -sS --ssl-no-revoke -X POST https://localhost:3000/mcp -H "Authorization: Bearer $token" -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d '{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{\"name\":\"execute_vendas_por_regiao\",\"arguments\":{\"data_inicial\":\"2026-01-01\",\"data_final\":\"2026-02-28\",\"regiao\":\"Sul\"}}}'
Resultado esperado no último comando: "status": "success" com 2 linhas (Notebook e Teclado, região Sul). Sem regiao, vêm as 6 linhas do período.

No cliente MCP use a URL https://localhost:3000/mcp com Authorization: Bearer <token>.

Se o Postgres for o instalado no Windows (sem Docker)

Substitua o Passo 1 por estes comandos, no psql como superusuário. Depois siga do Passo 2 em diante, trocando docker compose ... exec -T postgres psql ... por psql -h localhost -p 5432 ....
CREATE ROLE analysis_app LOGIN PASSWORD 'troque_esta_senha';
CREATE DATABASE analysis_config OWNER analysis_app;
-- depois, conectado ao analysis_config como analysis_app:
--   \i src/database/schema.sql
Aponte também POSTGRES_CONFIG_HOST=localhost, a porta, o usuário e a senha no .env.

Detalhes importantes

- O nome da tool é execute_<nome da análise>. O nome cadastrado é vendas_por_regiao, e o cliente enxerga execute_vendas_por_regiao.
- A FERNET_KEY não pode mudar depois. Os data sources cadastrados ficam ilegíveis se você trocar a chave.
- Os Passos 2 a 5 só precisam rodar uma vez. Eles gravam no volume pgdata, e down -v apaga tudo. Sem o -v, os dados ficam.
- Para um segundo usuário, repita só os INSERT em users e user_profiles do Passo 3 (e use outro e-mail).

## Usar sem TLS

Não, só trocar a URL não basta. Com TLS_ENABLED=true (o padrão), a porta 3000 só aceita TLS. Uma requisição http://localhost:3000 falha, porque o servidor espera o handshake TLS. É preciso desligar o TLS no servidor também.

Como ficar só em HTTP

1. No .env da raiz, mude:
TLS_ENABLED=false
   Os caminhos TLS_CERT_FILE e TLS_KEY_FILE deixam de ser usados e podem ficar como estão.
2. Recrie o app, porque a variável só é lida na subida:
docker compose -f docker-compose.local.yml up -d app
   Se o container não for recriado, restart não relê o .env, então use o up -d.
3. Use http:// na mesma porta:
curl.exe http://localhost:3000/health
curl.exe -X POST http://localhost:3000/auth/token -H "Content-Type: application/json" -d '{\"email\":\"admin@empresa.com\",\"password\":\"Senha@123\"}'
   O --ssl-no-revoke deixa de ser necessário. No cliente MCP, a URL passa a ser http://localhost:3000/mcp.

Não precisa mudar o compose nem o código. O run_https.py já sobe em HTTP puro quando TLS_ENABLED=false, e o healthcheck do container escolhe http ou https pela mesma variável. Não testei esse modo agora, só li o código.

Cuidados

- Senha e token trafegam em texto puro. Use só na sua máquina (localhost). Não faça isso com acesso pela rede.
- O cliente MCP pode recusar http://. A ARQUITETURA (ADR-006) registra que clientes reais como o Claude Desktop recusam conector remoto sem https, mesmo em rede interna. Se o seu cliente recusar, o servidor em http não adianta. O mcp-remote costuma ter uma opção para permitir http, a --allow-http. Confira na versão que você usa.
- Para voltar ao https: troque para TLS_ENABLED=true e rode o up -d app de novo. Os certificados em certs/ continuam valendo.

# Para começar do zero, apague o que o compose criou. Rode na raiz do repositório.

Ambiente local (o que você usa)

docker compose -f docker-compose.local.yml down -v --remove-orphans
- down para e remove os containers e a rede.
- -v apaga os volumes, ou seja, o pgdata com o Config DB inteiro: usuários, perfis, data sources, análises e tokens. É
  irreversível.
- --remove-orphans remove containers que sobraram de serviços que já saíram do compose (o mysql, por exemplo, se algum ficou
  de testes anteriores).

Também limpar a imagem do app (build do zero)

docker compose -f docker-compose.local.yml down -v --remove-orphans --rmi local
O --rmi local remove a imagem do app (mcp-analysis-local-app). A do postgres:16 fica, porque é baixada do Docker Hub e não precisa ser refeita.

Se você subiu o remote ou os bancos opcionais

Cada compose tem o próprio projeto e volumes, então limpe cada um que usou:
docker compose -f docker-compose.remote.yml down -v --remove-orphans
docker compose -f docker/mysql/docker-compose.mysql.yml down -v
docker compose -f docker/sqlserver/docker-compose.sqlserver.yml down -v
docker compose -f docker/oracle/docker-compose.oracle.yml down -v
Os compose de MySQL, SQL Server e Oracle exigem a senha no down por causa do :? na interpolação. Se der erro de variável, passe a senha na hora, por exemplo $env:MSSQL_SA_PASSWORD='x' antes do comando.

Conferir que ficou limpo

docker ps -a --filter "name=mcp-analysis"
docker volume ls --filter "name=mcp-analysis"
Os dois devem voltar vazios.

Para recomeçar

Rode o Passo 1 do guia (docker compose -f docker-compose.local.yml up -d --build). Como o volume é novo, o Postgres recria o banco e as tabelas, e você refaz os Passos 2 a 6.

O que não é apagado

- O .env, o que inclui a FERNET_KEY e as senhas.
- Os certificados em certs/.
- O código.

Se você trocar a FERNET_KEY ao recomeçar, nada se perde, já que o banco novo não tem data sources antigos. O contrário só importa quando se mantém o volume.

Limpeza geral (cuidado)

Este comando apaga todos os containers parados, redes sem uso, imagens sem uso e o cache de build do Docker, inclusive de outros projetos. Use só se quiser limpar o Docker inteiro:
docker system prune -a --volumes
Ele pede confirmação antes de apagar. Para a sua necessidade, o down -v acima basta.

Esse volume sobrou da época em que o MySQL fazia parte do compose local. Como o compose atual não declara mais o mysqldata, o down -v não o enxerga e não o remove. Apague direto pelo nome:

docker volume rm mcp-analysis-local_mysqldata

Se der volume is in use, algum container ainda o usa (provavelmente um mysql antigo parado). Veja e remova:
docker ps -a --filter "volume=mcp-analysis-local_mysqldata"
docker rm -f <nome-ou-id-do-container>
docker volume rm mcp-analysis-local_mysqldata

Depois confira:
docker volume ls --filter "name=mcp-analysis"

Dá para remover todos os volumes sem uso de uma vez com docker volume prune. Cuidado: ele apaga qualquer volume que nenhum container esteja usando, inclusive de outros projetos seus. Prefira o docker volume rm pelo nome.

Os dados desse volume eram só do MySQL de teste, então não há nada a preservar.

## Para finalizar sem perder dados, não use o -v. Os dados ficam no volume pgdata, e só o -v apaga volumes.

Parar e remover os containers, mantendo os dados

docker compose -f docker-compose.local.yml down
Isso remove os containers e a rede, mas o volume pgdata permanece. Quando subir de novo, o Postgres reaproveita o volume, com usuários, perfis, data sources, análises e tokens como estavam.

Só pausar (sem remover os containers)

docker compose -f docker-compose.local.yml stop
docker compose -f docker-compose.local.yml start    # para retomar

Para voltar a usar

docker compose -f docker-compose.local.yml up -d
Não rode de novo os Passos 2 a 5 do guia. O schema.sql só é aplicado quando o volume está vazio, então ele não recria nada nem duplica os dados.

Conferir que os dados continuam lá

docker volume ls --filter "name=mcp-analysis"          # deve listar mcp-analysis-local_pgdata
docker compose -f docker-compose.local.yml exec -T postgres psql -U postgres -d analysis_config -Atc "select count(*) from users"

O que preservar para os dados continuarem utilizáveis

- Não troque a FERNET_KEY do .env. A senha do data source (vendas_pg) está cifrada com ela, e com outra chave a análise para de conectar.
- Não troque a POSTGRES_CONFIG_PASSWORD do .env com o volume já criado. O Postgres só lê essa variável na primeira inicialização, então o banco continua com a senha antiga e o app deixa de conseguir conectar.
- Evite estes comandos, que apagam os dados: down -v, docker volume rm mcp-analysis-local_pgdata, docker volume prune e docker system prune --volumes.

Backup antes de mexer em algo arriscado

Para guardar uma cópia dos dados num arquivo:
docker compose -f docker-compose.local.yml exec -T postgres pg_dumpall -U postgres | Out-File -Encoding utf8 backup.sql
Isso inclui o Config DB (analysis_config) e o banco de análises (analysis_data). Para restaurar, com um volume novo e vazio:
Get-Content backup.sql -Raw | docker compose -f docker-compose.local.yml exec -T postgres psql -U postgres
Se o backup.sql for restaurado num volume que já tem o analysis_config, haverá erros de objetos já existentes. Restaure só em volume vazio.