Layout proposto (opção A: rename simples)

mcp-data-analysis-python/
├── src/                      ← era analysis_app/ (módulos continuam planos)
│   ├── main.py, run_https.py, config.py
│   ├── adapters/ database/ mcp_transport/ repositories/
│   ├── routes/ schemas/ security/ services/
├── tests/                    ← sobe de analysis_app/tests/
├── docker/                   ← postgres, mysql, sqlserver, oracle, nginx
├── docker-compose.local.yml
├── docker-compose.remote.yml
├── Dockerfile                ← sai de src/ (veja abaixo)
├── .dockerignore
├── .env.example
├── requirements.txt / requirements-dev.txt
├── pytest.ini
├── certs/                    ← já está no .gitignore
├── .spec/  .claude/  .vscode/

Por quê

- Os imports não mudam. O código usa imports planos (from config import settings, from database.connection import ...). Renomear a pasta e apontar o Python para ela (pythonpath = src no pytest.ini, WORKDIR /app com COPY src/ . no Dockerfile) não exige alterar nenhum .py.
- A raiz fica limpa. Infra (Docker, compose, nginx, certs, .env.example) fica separada do código, e o Dockerfile e o compose ficam no mesmo nível de requirements.txt. Isso simplifica o contexto de build, que passa a ser a raiz.
- tests/ na raiz é o padrão do mercado. Ele deixa de ficar misturado ao código e fica fora da imagem sem precisar de regra especial.

Alternativa (opção B: pacote de verdade)

src/analysis_mcp/… com imports from analysis_mcp.config import settings. É o src-layout "puro", mas exige reescrever todos os imports (código e testes) e os patch("...") dos mocks. Isso é refatoração grande, sem relação com Docker, e arriscada para os 334 testes. Recomendo deixar para depois, se um dia quiser publicar como pacote.

O que muda ao mover (opção A)

1. git mv analysis_app src, depois git mv src/tests tests e git mv src/requirements*.txt .. Também sobem pytest.ini e .env.example.
2. pytest.ini ganha pythonpath = src. Os testes que dependem do cwd (por exemplo env_file=".env" no config.py) precisam ser verificados: o .env passa a ficar na raiz, e o Settings o lê relativo ao cwd.
3. Caminhos do .env.example: TLS_CERT_FILE=certs/server.pem continua válido se o servidor rodar a partir da raiz (python src/run_https.py). No Docker, uso caminhos absolutos montados.
4. Atualizar as referências a analysis_app/ em CLAUDE.md, ARQUITETURA.md, NEGOCIO.md, ROADMAP e specs (F1, F9, F10, F11, F13).
5. A pasta src/scripts/ só tem __pycache__, então pode ir embora.
6. Rodar pytest para confirmar os 334 testes antes de seguir com a F13.

Depois do rename, a spec da F13 fica simplificada: Dockerfile e .env.example na raiz, com contexto de build na raiz.

Sobre a execução: você disse que vai remover o mcp_prototype manualmente. Quer que eu faça também o rename e a atualização dos docs (itens 1–6), ou prefere mover as pastas você mesmo e eu só ajusto pytest.ini, docs e a spec da F13? Se eu fizer, só mexo depois do seu OK, porque é uma mudança ampla.