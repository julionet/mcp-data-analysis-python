# F13 — Suporte a arquivos Markdown (.md)

| Campo | Valor |
|---|---|
| **Status da spec** | Aprovada (pedido direto da pessoa em 2026-10-09; tipo `md` + migração escolhido por ela) |
| **Status da implementação** | Verificada |
| **Marco** | M1 — Fatia vertical (ampliação de F01, F02 e F05) |
| **Depende de** | F01 (esquema, `init-db`, `check`), F02 (`loaders`), F05 (`ingest`) |
| **Regras de negócio** | R7 (formato não aceito segue rejeitado, agora com `.md` na lista de aceitos); amplia "Tipos de documento" do NEGOCIO |
| **Seções da arquitetura** | §4 Ingestão, §6 Esquema, §8 CLI (`init-db`, `check`) |

## 1. Objetivo
Aceitar arquivos `.md` (Markdown) além de `.txt` e `.pdf`. O conteúdo é lido como texto (UTF-8, uma página) e dividido pela estratégia `structured`, que já entende títulos `#`, `##`, `###`; portanto os títulos do Markdown viram a seção de cada trecho.

## 2. Escopo

**Inclui**
- `src/loaders.py`: extensão `.md` aceita, tipo `md`, leitura idêntica à do TXT (UTF-8, fallback `utf-8-sig`/`latin-1`, tudo vira a página 1, arquivo vazio rejeitado).
- Esquema: `documents.file_type` passa a aceitar `'md'`, por **nova migração** `sql/002_file_type_md.sql` (a `001_init.sql` não é alterada).
- `init-db` passa a aplicar **todas** as migrações `sql/NNN_*.sql` em ordem, na mesma transação.
- `check` falha se a restrição de `file_type` do banco não aceitar `md`.
- Mensagens e ajuda da CLI: "TXT, MD ou PDF" / "Use .txt, .md ou .pdf."
- Documentação (NEGOCIO, ARQUITETURA, ROADMAP, CLAUDE.md, specs F01/F02/F05 onde citam os formatos).
- Amostra `data/amostras/guia.md` para o teste.

**Não inclui**
- Renderizar ou converter Markdown (HTML, imagens, links): o texto é usado como está.
- Tratar *front matter* (YAML), blocos de código cercados (``` ```) ou HTML embutido. Linhas `#` dentro de bloco de código serão vistas como títulos (limitação aceita, ver seção 11).
- Outros formatos (`.rst`, `.docx`).
- Mudar o `chunking`: `structured_chunks` já divide Markdown.

## 3. Regras de negócio aplicáveis

| Regra | O que significa nesta feature |
|---|---|
| R4 | Mesmo conteúdo em `.md` e `.txt` (mesmo `sha256`) continua duplicado. |
| R7 | Extensões que não sejam `.txt`, `.md` e `.pdf` seguem rejeitadas, com mensagem listando as três aceitas. |
| R8 | Inalterada (só vale para PDF). |

**Regras técnicas**
- **T1.** `.md` é lido por `_read_txt`; extensões casam sem diferenciar maiúsculas (`.MD`).
- **T2.** `DocumentInfo.file_type` e `documents.file_type` valem `md` para esses arquivos.
- **T3.** As migrações são idempotentes: reaplicar `init-db` não altera nada nem dá erro.
- **T4.** Um banco criado só com a `001` (que aceita `txt` e `pdf`) é corrigido ao rodar `init-db` de novo; um banco novo passa pela `001` e pela `002` na mesma execução.

## 4. Comportamento esperado

### 4.1 Fluxo principal
1. A pessoa roda `python -m src.cli init-db` (uma vez, em bancos já existentes).
2. Roda `python -m src.cli ingest <arquivo>.md`.
3. O arquivo é lido como texto, dividido por títulos Markdown, vetorizado e gravado com `file_type = 'md'`.

### 4.2 Fluxos alternativos e erros

| Situação | Comportamento esperado | Mensagem / saída |
|---|---|---|
| `.md` válido | Cadastrado como `md`. | `Arquivo: … (md, 1 página)` |
| `.MD` (maiúsculas) | Aceito. | idem |
| `.md` vazio ou só espaços | Rejeitado, como o TXT. Código 1. | `Arquivo sem texto: <nome>` |
| `.md` em Latin-1 | Lido com o fallback, como o TXT. | — |
| Outra extensão (ex.: `.docx`) | Rejeitada. Código 1. | `Formato não aceito: ".docx" (nota.docx). Use .txt, .md ou .pdf.` |
| `.md` com o mesmo conteúdo de um `.txt` já cadastrado | Duplicado (R4). | `duplicado de <caminho>` |
| Banco ainda sem a migração 002 | `check` falha; `ingest` de `.md` falha com mensagem clara em vez de erro cru do banco. Código 1. | `check`: `Restrição documents.file_type não aceita "md". Execute init-db.` · `ingest`: `Erro ao gravar o documento (nada foi gravado): …` |
| `init-db` em banco com a 002 já aplicada | Nada muda. | `Esquema já estava atualizado.` |
| `init-db` em banco só com a 001 | Aplica a 002. | `Restrição documents.file_type atualizada (txt, md, pdf).` e `Esquema aplicado com sucesso.` |

### 4.3 Saída para a pessoa
```
$ python -m src.cli init-db
Conectado: localhost:5432/rag_training_db (usuário rag_user)
Extensão vector 0.8.7: OK
Restrição documents.file_type atualizada (txt, md, pdf).
Esquema aplicado com sucesso.

$ python -m src.cli ingest data/amostras/guia.md
Arquivo:    …/data/amostras/guia.md (md, 1 página)
Resultado:  cadastrado
Documento:  id 1 | 3 trechos | páginas 1–1
```

## 5. Interface

**Comandos / opções da CLI**

| Comando | Argumentos e opções | Descrição |
|---|---|---|
| `python -m src.cli ingest` | `<arquivo>` | Passa a aceitar `.md`. Ajuda: "cadastra um arquivo TXT, MD ou PDF". |
| `python -m src.cli init-db` | — | Aplica todas as migrações `sql/NNN_*.sql`. |
| `python -m src.cli check` | — | Confere também a restrição de `file_type`. |
| `scripts/read_document.py`, `chunk_document.py`, `embed_document.py` | — | Só a descrição ("TXT, MD ou PDF"); aceitam `.md` pelo `loaders`. |

**Módulos e funções**

| Arquivo | Responsabilidade | Funções / classes |
|---|---|---|
| `src/loaders.py` | `ACCEPTED_TYPES` ganha `".md": "md"`; `inspect_document` e `_pages` tratam `md` como `txt`; mensagem de formato não aceito. | — |
| `src/db.py` | `init_db` aplica as migrações em ordem; `check_environment` confere a restrição. | `_migrations() -> list[Path]` (ordenadas por nome), `_file_type_allows_md(conn) -> bool` |
| `sql/002_file_type_md.sql` | Troca o CHECK. | — |

## 6. Dados
Nova migração `sql/002_file_type_md.sql` (idempotente):

```sql
ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_file_type_check;
ALTER TABLE documents ADD CONSTRAINT documents_file_type_check
  CHECK (file_type IN ('txt', 'md', 'pdf'));
```
`001_init.sql` fica como está (histórico). Linhas existentes não mudam. Nenhuma tabela ou índice novo, então `EXPECTED_TABLES` e `EXPECTED_INDEXES` não mudam.

## 7. Configuração
Sem mudanças.

## 8. Dependências externas
Nenhuma. Amostra nova (a criar): `data/amostras/guia.md` (Markdown pequeno, com 2–3 títulos e acentos).

## 9. Critérios de aceite — roteiro de teste manual

**Pré-condições:** ambiente virtual ativo; comandos na raiz; banco com a `001` aplicada (estado atual). Anotar `documents` e `chunks` antes.

| # | Passo | Comando / ação | Resultado esperado |
|---|---|---|---|
| 1 | `check` antes da migração | `python -m src.cli check; echo $?` | **Falha** `Restrição documents.file_type não aceita "md". Execute init-db.`; código 1. |
| 2 | Aplicar a migração | `python -m src.cli init-db` | `Restrição documents.file_type atualizada (txt, md, pdf).` e `Esquema aplicado com sucesso.`; código 0. |
| 3 | Restrição no banco | Consulta 1 | Definição com `'txt'`, `'md'` e `'pdf'`. |
| 4 | Idempotência | Repetir o passo 2 | `Esquema já estava atualizado.` Sem erro. |
| 5 | `check` depois | `python -m src.cli check` | Sem falhas; código 0. |
| 6 | Ler `.md` | `python -m scripts.read_document data/amostras/guia.md` | Tipo `md`, 1 página, texto completo; código 0. |
| 7 | Dividir `.md` | `python -m scripts.chunk_document data/amostras/guia.md` | Trechos com a seção igual ao caminho de títulos (ex.: `Guia > Instalação`). |
| 8 | Cadastrar `.md` | `python -m src.cli ingest data/amostras/guia.md; echo $?` | `cadastrado`, `(md, 1 página)`; código 0. |
| 9 | Dados gravados | Consulta 2 | `file_type = 'md'`; trechos com `section` preenchida e vetor de 1024 dimensões. |
| 10 | Repetição | Repetir o passo 8 | `já cadastrado, sem mudanças`. |
| 11 | Duplicado entre tipos | `cp data/amostras/guia.md /tmp/guia_copia.txt && python -m src.cli ingest /tmp/guia_copia.txt` | `duplicado de …/guia.md`; nada novo gravado. |
| 12 | Extensão em maiúsculas | `cp data/amostras/guia.md /tmp/OUTRO.MD` (com uma linha a mais) e cadastrar | Aceito, `file_type = 'md'`. |
| 13 | `.md` vazio | `: > /tmp/vazio.md && python -m src.cli ingest /tmp/vazio.md; echo $?` | `Arquivo sem texto: vazio.md`; código 1; nada gravado. |
| 14 | Formato rejeitado | `python -m src.cli ingest data/amostras/nota.docx; echo $?` | `Formato não aceito: ".docx" (nota.docx). Use .txt, .md ou .pdf.`; código 1. |
| 15 | Banco sem a migração | Em um banco de teste só com a `001`, `ingest` de `.md`; ou reverter o CHECK temporariamente | Erro claro, código 1, nada gravado; `check` falha como no passo 1. (Descrever como foi provocado.) |
| 16 | Regressão TXT e PDF | `ingest` de `data/manual_colaborador.txt` e `data/amostras/com_texto.pdf` | Cadastrados como `txt` e `pdf`, como antes. |
| 17 | Importações | `python -c "import src.ingestion, src.repository, src.rag, src.hybrid_rag"` | Sem erro. |
| 18 | Somente o previsto | `git status` | Só os arquivos previstos. |

**Consultas úteis para conferir o banco**
```sql
-- 1) restrição
SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'documents_file_type_check';
-- 2) documentos e trechos .md
SELECT d.id, d.file_type, d.source_path, count(c.id) FROM documents d LEFT JOIN chunks c ON c.document_id = d.id GROUP BY d.id ORDER BY d.id;
SELECT chunk_index, page, section, vector_dims(embedding) FROM chunks WHERE document_id = (SELECT id FROM documents WHERE file_type = 'md' LIMIT 1) ORDER BY chunk_index;
```

## 10. Impacto em outras features

| Feature | Roteiros a repetir (#) | Motivo |
|---|---|---|
| F01 | `init-db` e `check` | `init-db` aplica mais de uma migração e `check` confere a restrição. |
| F02 | Roteiro de rejeição de formato (`.docx`) | A mensagem de formato não aceito mudou. |
| F03 | 1 | `chunk_pages` só consumida. |
| F05 | 1, 6, 11 | Cadastro de TXT e PDF e duplicado seguem iguais. |
| F06 a F09 | — | O tipo `md` aparecerá em listagens (F09). |

## 11. Riscos e decisões

**Decisões tomadas**
- **Tipo próprio `md` no banco, com nova migração** (escolha da pessoa): mantém a origem fiel e as listagens corretas.
- **Migração em arquivo novo `002`** (e não edição da `001`): a `001` usa `CREATE TABLE IF NOT EXISTS` e não alteraria um banco que já existe.
- **`init-db` aplica todas as `sql/NNN_*.sql` em ordem**, na mesma transação.
- **`.md` lido como texto simples**, sem converter: o `structured_chunks` já entende `#`.
- **`check` falha** (e não só avisa) se o banco não aceitar `md`, para o erro aparecer antes do `ingest`.

**Riscos aceitos**
- Linhas começando com `#` dentro de blocos de código cercados viram títulos (seção errada). Tratar blocos de código e *front matter* fica para depois, se a medição (F11) mostrar necessidade.

**Pontos em aberto**
Nenhum.

## 12. Documentação a atualizar
- `.spec/NEGOCIO.md`: formatos aceitos (TXT, MD e PDF).
- `.spec/ARQUITETURA.md`: objetivos, §4 (loaders), §6 (esquema e migração 002), §8 (`init-db`, `check`).
- `.spec/ROADMAP.md`: linha F13 e tabela de status; F02 (formatos).
- `.spec/features/F01…F05`: nota curta nos pontos que citam só TXT/PDF.
- `.claude/CLAUDE.md`: formatos aceitos e F13.
- `README.md`: sem mudanças (descreve o código legado; revisão na F12).

## 13. Definição de pronto
- [x] Spec aprovada pela pessoa responsável
- [x] Código implementado somente no que a spec descreve
- [x] Todos os passos do roteiro (seção 9) executados e aprovados
- [x] Roteiros de regressão (seção 10) repetidos
- [x] Documentação da seção 12 atualizada
- [x] Status atualizado nesta spec e no ROADMAP

## 14. Registro de verificação

| Data | Quem executou | Resultado | Observações / falhas encontradas |
|---|---|---|---|
| 2026-10-09 | Claude (pré-verificação na implementação) | Passos 1–18 executados sem falhas | Aguarda execução e aprovação da pessoa. Passo 1: `check` falhou com a mensagem esperada antes do `init-db`. Passo 2: restrição atualizada; passo 4: idempotente. `guia.md` cadastrado como `md` com 3 trechos e seções `Guia de Instalação > Instalação` etc.; `.MD` aceito; cópia `.txt` do mesmo conteúdo detectada como duplicado; `.md` vazio e `.docx` rejeitados (código 1). **Passo 15** provocado recriando o CHECK antigo (`txt`,`pdf`) com a tabela vazia: `ingest` de `.md` falhou com `Erro ao gravar o documento (nada foi gravado): … violates check constraint`, `check` falhou, nada gravado; `init-db` restaurou a restrição. **Banco novo (T4):** 001+002 aplicadas em um schema temporário revertido: CHECK final `('txt','md','pdf')`. Dados de teste removidos do banco ao final (`documents` vazia). |
| 2026-10-09 | Jose Julio | Aprovado | Roteiro da seção 9 aprovado, conforme relato da pessoa. |
