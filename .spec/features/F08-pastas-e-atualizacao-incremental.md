# F08 — Pastas e atualização incremental

| Campo | Valor |
|---|---|
| **Status da spec** | Aprovada |
| **Status da implementação** | Verificada |
| **Marco** | M2 — Base completa |
| **Depende de** | F05 (`ingest_file`, `repository`, gravação atômica), F01 (`sources`, `documents.source_id`), F02 (`inspect_document`), F04 (modelo de embeddings) |
| **Regras de negócio** | R4, R5, R6, R7, R9; R10 só para o `--prune` (o resto da R10 é da F09) |
| **Seções da arquitetura** | §4 Ingestão (incremental, várias pastas), §6 (esquema, 6.1 falha isolada), §8 (`ingest`, `reindex`), §14 Testes |

## 1. Objetivo
Cadastrar **pastas** inteiras e mantê-las atualizadas: a pessoa informa uma pasta, a aplicação cadastra os arquivos TXT, MD e PDF, e nas vezes seguintes refaz **só o que é novo ou mudou**. Um arquivo com problema não interrompe os demais, e o que sumiu da pasta só sai da base quando a pessoa pede e confirma. Completa a regra R5 e o resumo por pasta da R7.

## 2. Escopo

**Inclui**
- `ingest <arquivo|pasta>` com `--recursive/--no-recursive`, `--force` e `--prune`. A pasta é registrada em `sources` (caminho absoluto, `recursive`, `last_indexed_at`).
- Novo comando `reindex [<pasta>|--all] [--prune]`: reprocessa as pastas **já registradas**, só o que mudou.
- Atualização incremental por arquivo: novo, igual, alterado, duplicado, vindo de cadastro avulso, ausente, com falha e ignorado (seção 4.1).
- **Substituição de arquivo alterado**, inclusive o arquivo avulso (na F05 isso era erro).
- **Falha isolada** (R7): o arquivo com problema vai para o resumo com o motivo; os demais seguem.
- `--prune`: remove da base, **após confirmação**, os documentos da pasta cujo arquivo não existe mais em disco (R6, R10).
- **Trava por pasta** contra duas atualizações simultâneas da mesma pasta (decisão pendente do ROADMAP, resolvida aqui).
- Resumo por arquivo em `stdout` e progresso em `stderr`.
- Adoção de arquivo avulso (`source_id` nulo) encontrado dentro da pasta.

**Não inclui** (fica para outra feature ou fora de escopo)
- `folders`, `list` e `delete` (F09) e o resto da confirmação da R10.
- Menu interativo (F10).
- **Troca de `EMBEDDING_MODEL`** (reindexar a base com outro modelo): continua bloqueada pela F04. Fica como pendência futura (seção 11).
- Registrar arquivos com falha no banco (`documents.status = 'failed'`): decidido que a falha só aparece no resumo.
- Retomada de uma atualização interrompida (o que já foi concluído fica; o resto é refeito na próxima execução, naturalmente, pelo incremental).
- Limites de tamanho de arquivo e de páginas (decisão pendente do ROADMAP, a medir).
- Detecção de renomeação ou de arquivo movido (é tratado como arquivo novo + ausente/duplicado, ver 4.1).
- Atualização automática por agendamento ou monitoramento da pasta.

## 3. Regras de negócio aplicáveis

| Regra | O que significa nesta feature |
|---|---|
| R4 | Conteúdo igual ao de um documento já cadastrado (qualquer pasta) é ignorado e informado como "duplicado de `<caminho do original>`". |
| R5 | Atualizar a pasta **não refaz tudo**: arquivo novo entra, alterado substitui a versão anterior, igual é mantido. |
| R6 | Arquivo apagado da pasta **só sai da base** com `--prune` explícito. Sem `--prune` ele apenas é apontado no resumo. |
| R7 | Arquivo corrompido, sem texto ou de formato não aceito **não interrompe** os demais. O resumo traz o que deu certo e o que falhou, com o motivo. |
| R9 | Cada documento é gravado ou substituído **por inteiro, numa transação**. Uma interrupção nunca deixa documento ou trechos pela metade. |
| R10 | O `--prune` lista o que será removido e **pede confirmação** antes de remover. |

**Regras técnicas**
- **T1. Classificação de cada arquivo aceito** (caminho `P`, hash `H`; `A` = documento já cadastrado em `P`; `B` = documento já cadastrado com hash `H`):

  | `B` | `A` | Resultado | O que acontece |
  |---|---|---|---|
  | existe, em `P` | — | **sem mudanças** | Nada é feito. Se `B.source_id` é nulo (avulso), vira **vinculado**: recebe o `source_id` da pasta, sem revetorizar. Com `--force`: **atualizado** (revetoriza e substitui os trechos). |
  | existe, em outro caminho | não existe | **duplicado** | Nada é cadastrado. Informa `duplicado de <caminho de B>`. |
  | existe, em outro caminho | existe (arquivo mudou e ficou igual a outro) | **duplicado** | Remove o documento `A` e seus trechos (R5) e informa `duplicado de <caminho de B>` com a nota `(versão anterior removida)`. |
  | não existe | não existe | **cadastrado** | Fluxo da F05. |
  | não existe | existe (arquivo mudou) | **atualizado** | Vetoriza a nova versão e, **numa transação**, troca os dados do documento `A` e apaga seus trechos antigos, gravando os novos. O `id` do documento é mantido. |

- **T2.** A vetorização acontece **antes** da transação (como na F05). Se ela falhar, nada muda: o documento antigo, se houver, **continua intacto** na base (R7, R9).
- **T3.** Um erro de **um** arquivo (leitura, PDF sem texto, formato não aceito, nenhum trecho gerado, falha na gravação) é registrado no resumo como **falhou** e o processamento segue. Já os erros **globais** interrompem a execução inteira, com a mensagem da F04/F01: `EMBEDDING_MODEL` ausente ou divergente do registrado, modelo que não carrega, dimensão ≠ 1024, banco indisponível. Arquivos concluídos antes continuam gravados.
- **T4.** A conferência do modelo (F04) e o carregamento do `Embedder` acontecem **uma vez**, na primeira vez que algum arquivo precisa ser vetorizado. Uma atualização em que nada precisa de vetor (tudo igual, duplicado ou ausente) **não carrega o modelo**.
- **T5. Trava por pasta.** Ao começar a atualizar uma pasta registrada, a aplicação toma um lock consultivo do PostgreSQL (`pg_try_advisory_lock`) com chave derivada do caminho da pasta, mantido na conexão. Se não conseguir, **recusa na hora**, sem esperar. O lock é liberado ao terminar, e sozinho se o processo cair. `ingest` de um **arquivo avulso** não toma lock (vale a proteção da F05, T3).
- **T6. Varredura.** Percorre a pasta em ordem alfabética de caminho. Aceita `.txt`, `.md` e `.pdf` (sem diferenciar maiúsculas). **Ignora**, listando cada um com o motivo: outros formatos (`formato não aceito`), nomes que começam com `.` (`oculto`; pastas ocultas não são percorridas) e links simbólicos (`link simbólico`; não são seguidos). Sem `--recursive`, subpastas não são percorridas.
- **T7. Pasta registrada.** O caminho é absoluto e resolvido. Pastas **não podem se sobrepor**: recusar registrar uma pasta que **contenha** ou **esteja dentro de** outra já registrada. Registrar de novo a mesma pasta é permitido.
- **T8. `--recursive` guardado.** O valor fica em `sources.recursive` (padrão `true` na primeira vez). `reindex` usa o valor guardado. `ingest <pasta>` com `--recursive` ou `--no-recursive` explícito **atualiza** o valor guardado; sem a opção, mantém o guardado.
- **T9. Ausente.** É ausente o documento da pasta (`source_id` da pasta) cujo arquivo **não existe em disco**. Arquivo que existe mas passou a falhar não é ausente. Sem `--prune`, os ausentes só aparecem no resumo. Documentos de **subpastas** que ficaram fora da varredura por a pasta ser não recursiva existem em disco, logo **não** são ausentes e o `--prune` não os remove; o resumo os **avisa** (T13).
- **T10. `--prune`.** Roda **depois** do processamento dos arquivos, só se a execução terminou sem interrupção. Mostra a lista dos ausentes e pergunta `Remover N documento(s) da base? [s/N]`. Só `s` ou `S` confirma. Se a entrada **não** for um terminal interativo, não remove e avisa. Remover um documento apaga seus trechos (cascata). Um duplicado que ficou ignorado porque o original era um dos ausentes **só é cadastrado na próxima execução** (ARQUITETURA §4).
- **T11. `last_indexed_at`** da pasta é atualizado ao **fim de uma execução concluída** (mesmo com arquivos que falharam). Em interrupção ou erro global, não é alterado.
- **T13. Aviso de subpastas fora do escopo.** Se a pasta é não recursiva e há documentos dela (mesmo `source_id`) em subpastas, o resumo traz `Aviso: N documento(s) em subpastas não são mais atualizados (a pasta não é recursiva).` Não afeta o código de saída.
- **T12.** Importar os módulos novos não carrega o modelo, não conecta ao banco e não exige `.env`.

## 4. Comportamento esperado

### 4.1 Fluxo principal — `ingest <pasta>`
1. A pessoa executa `python -m src.cli ingest <pasta>`.
2. A aplicação confere o caminho (existe, é pasta) e a sobreposição com pastas registradas (T7). Registra a pasta em `sources` (ou atualiza `recursive`, T8).
3. Toma a trava da pasta (T5).
4. Varre a pasta (T6) e, para cada arquivo aceito, em ordem, classifica (T1), vetoriza se preciso (T2, T4) e grava. Mostra o andamento em `stderr`.
5. Se `--prune`, apura os ausentes (T9), lista e pede confirmação (T10).
6. Atualiza `last_indexed_at` (T11), libera a trava e mostra o resumo (4.3).

**`reindex <pasta>`** faz o mesmo para uma pasta **já registrada**, com o `recursive` guardado. **`reindex --all`** percorre todas as pastas registradas, uma por vez, em ordem de cadastro. Falha de uma pasta (inexistente em disco, trava ocupada) não impede as outras; o código final é 1 se alguma falhou.

**`ingest <arquivo>`** continua cadastrando um arquivo avulso como na F05, com duas diferenças: arquivo **alterado** no mesmo caminho agora é **substituído** (T1, linha "atualizado") e `--force` é aceito. `--recursive`, `--no-recursive` e `--prune` não se aplicam a arquivo: erro (4.2).

### 4.2 Fluxos alternativos e erros

| Situação | Comportamento esperado | Mensagem / saída |
|---|---|---|
| Caminho inexistente | Erro, nada registrado. Código 1. | Mensagem da F02 para arquivo inexistente |
| Pasta sem nenhum TXT, MD ou PDF | Registra a pasta. Código 0. | `Nenhum arquivo TXT, MD ou PDF encontrado em <pasta>.` (ignorados, se houver, são listados) |
| Pasta se sobrepõe a outra registrada | Recusa, nada registrado nem alterado. Código 1. | `<pasta> se sobrepõe à pasta já registrada <outra>. Use uma delas.` |
| Já existe atualização da mesma pasta (T5) | Recusa na hora. Código 1. | `Já existe uma atualização da pasta <pasta> em andamento. Tente novamente quando ela terminar.` |
| Arquivo com falha (corrompido, sem texto, não lido) | Falha **isolada**; segue. Código final 1. | Linha `falhou` com o motivo da F02 no resumo |
| Arquivo já cadastrado cuja nova versão falha | Mantém a versão anterior (T2). Falha isolada. | `falhou … (mantida a versão anterior)` |
| Arquivo em formato não aceito, oculto ou link simbólico | Ignorado, listado. Não afeta o código. | Linha `ignorado` com o motivo |
| Duplicado | Informa o original. Não afeta o código. | `duplicado de <caminho>` |
| Arquivo sumiu da pasta, sem `--prune` | Fica na base; aparece no resumo. Não afeta o código. | `ausente … (use --prune para remover da base)` |
| `--prune` com ausentes, em terminal | Lista e pede confirmação (T10). `n` ou Enter: nada removido. | `Remover N documento(s) da base? [s/N]` |
| `--prune` sem terminal interativo | Nada removido. Código 1. | `--prune exige confirmação em um terminal interativo; nada foi removido.` |
| `--prune` sem ausentes | Nada a fazer. | `Nenhum documento ausente.` |
| `reindex` sem `<pasta>` e sem `--all`, ou com os dois | Erro de argumento (`argparse`). Código 2. | `Informe <pasta> ou --all.` / `Use <pasta> ou --all, não os dois.` |
| `reindex <pasta>` de pasta não registrada | Erro. Código 1. | `<pasta> não está registrada. Cadastre com: python -m src.cli ingest <pasta>` |
| `reindex --all` sem pastas registradas | Código 0. | `Nenhuma pasta registrada. Cadastre com: python -m src.cli ingest <pasta>` |
| Pasta registrada **não existe mais em disco**, sem `--prune` | Erro para essa pasta, **nada é removido**. Código 1. | `A pasta <pasta> não foi encontrada em disco. Nada foi alterado.` |
| Pasta registrada **não existe mais em disco**, com `--prune` | Todos os documentos da pasta contam como ausentes; a confirmação destaca o motivo. A pasta continua registrada (sua remoção é da F09). | `A pasta <pasta> não foi encontrada em disco (unidade desmontada?). Todos os N documentos dela seriam removidos. Remover? [s/N]` |
| `--recursive`, `--no-recursive` ou `--prune` com um **arquivo** | Erro, nada feito. Código 1. | `<opção> só se aplica a pastas.` |
| Pergunta de confirmação do `--prune` recebe `Ctrl+C` | Nada removido. Código 1. | `Remoção cancelada.` |
| `Ctrl+C` durante a atualização | Para na hora. Arquivo em andamento: nada gravado (R9). Concluídos ficam. `--prune` não roda. `last_indexed_at` não muda. Mostra o resumo parcial. Código 1. | `Atualização interrompida; os arquivos já concluídos foram mantidos.` |
| Erro global (T3) | Interrompe a execução inteira. Resumo parcial. Código 1. | Mensagem da F04/F01 |
| Pasta não recursiva com documentos já cadastrados em subpastas | Os documentos ficam na base, sem atualização, e o `--prune` não os remove (T9). Resumo avisa (T13). Código não muda. | `Aviso: N documento(s) em subpastas não são mais atualizados (a pasta não é recursiva).` |
| Dois arquivos novos com o mesmo conteúdo na mesma pasta | O 1º (ordem alfabética) é cadastrado; o 2º é `duplicado de` o 1º. | — |
| Arquivo avulso (`source_id` nulo) no mesmo caminho e conteúdo | Vinculado à pasta (T1). | `vinculado à pasta` |

### 4.3 Saída para a pessoa
Progresso em `stderr` (uma linha por arquivo; arquivos grandes reaproveitam a linha de páginas da F05):
```
[3/9] sub/politica.pdf
Lendo e vetorizando: página 12/40 | trechos 61 | 4,8 trechos/s | restante ~6 s
```
Resumo em `stdout`:
```
$ python -m src.cli ingest /Users/.../docs
Pasta:      /Users/.../docs (registrada agora | recursiva: sim)
Arquivos:   9 aceitos | 3 ignorados

  cadastrado    manual.txt                 7 trechos
  atualizado    guia.md                    5 trechos (versão anterior substituída)
  sem mudanças  politica.md
  vinculado     avulso.txt                 arquivo avulso adotado pela pasta
  duplicado     manual_copia.txt           duplicado de /Users/.../docs/manual.txt
  ausente       velho.txt                  não existe mais em disco (use --prune para remover da base)
  falhou        escaneado.pdf              <motivo da F02>
  falhou        corrompido.pdf             <motivo da F02>
  ignorado      nota.docx                  formato não aceito
  ignorado      .oculto.txt                oculto
  ignorado      link.txt                   link simbólico

Resumo:     1 cadastrado, 1 atualizado, 1 sem mudanças, 1 vinculado, 1 duplicado, 1 ausente, 2 falharam, 3 ignorados
Aviso:      2 documento(s) em subpastas não são mais atualizados (a pasta não é recursiva).   # só em pasta não recursiva
Tempo:      14,2 s
```
Com `--prune` e ausentes:
```
Documentos ausentes da pasta (arquivo não existe mais em disco):
  /Users/.../docs/velho.txt
Remover 1 documento(s) da base? [s/N] s
Removido:   1 documento(s)
```
- Caminhos aparecem **relativos à pasta** na lista por arquivo, e absolutos nos avisos e na confirmação.
- Erros globais e de pasta (trava, sobreposição, não encontrada) vão para `stderr`, sem traceback.
- Código de saída: **0** se tudo deu certo, mesmo com duplicados, ausentes e ignorados; **1** se algum arquivo falhou, houve erro global ou de pasta, ou o `--prune` não pôde ser confirmado.

## 5. Interface

**Comandos / opções da CLI**

| Comando | Argumentos e opções | Descrição |
|---|---|---|
| `python -m src.cli ingest` | `<arquivo\|pasta>` `[--recursive\|--no-recursive]` `[--force]` `[--prune]` | Cadastra um arquivo avulso ou uma pasta (4.1). `--force` revetoriza e substitui os trechos dos arquivos mesmo sem mudança (duplicados continuam duplicados). Opções de pasta com arquivo: erro. |
| `python -m src.cli reindex` | `[<pasta> \| --all]` `[--prune]` | Reprocessa pastas registradas, só o que mudou, com o `recursive` guardado. Exige `<pasta>` **ou** `--all`. |

Sem item de menu (F10).

**Módulos e funções**

| Arquivo | Responsabilidade | Funções / classes |
|---|---|---|
| `src/folder_ingestion.py` (novo) | Varredura, trava, classificação por arquivo, `--prune` e resumo. Não imprime; devolve o resultado. | `ingest_folder(path, recursive=None, force=False, prune=False, progress=None, confirm=None) -> FolderResult`; `reindex_folders(path=None, prune=False, progress=None, confirm=None) -> list[FolderResult]`; `scan_folder(path, recursive) -> Scan(files, ignored)`; `FileResult(path, outcome, chunk_count, detail)`; `FolderResult(folder, registered_now, recursive, files, ignored, absent, removed, interrupted, error, elapsed)`; `FolderError` (mensagem pronta). `confirm(pasta, ausentes, pasta_nao_encontrada) -> bool` é fornecido pela CLI e levanta `ConfirmUnavailable` fora de um terminal interativo. `Reporter` (ganchos de andamento: `file_start`, `file_end`, `before_prune`) também é da CLI; `reindex_folders` é um gerador que entrega um `FolderResult` por pasta. |
| `src/ingestion.py` | Fluxo por arquivo, agora reaproveitado pela pasta. | `ingest_file(path, progress=None, force=False)` (substitui arquivo alterado, T1); `process_file(conn, path, source_id, provider, force, progress, info)`, o fluxo de um arquivo, que recebe a conexão, o `source_id` e um `ModelProvider` (confere o modelo e carrega o `Embedder` só na primeira necessidade, T4). `IngestResult.outcome` ganha `updated` e `adopted`. |
| `src/repository.py` | SQL, sem regra de negócio. | `DocumentRow` ganha `source_id`; `add_document(..., source_id=None)`; `replace_document(conn, document_id, info, chunks)` (uma transação); `remove_document(conn, document_id)`; `adopt_document(conn, document_id, source_id)`; `list_documents_of_source(conn, source_id)`; `SourceRow(id, path, recursive, last_indexed_at)`; `get_source(conn, path)`; `add_source(conn, path, recursive)`; `update_source(conn, source_id, recursive=None, indexed_now=False)`; `list_sources(conn)`; `find_overlap(conn, path) -> str \| None`; `try_lock_folder(conn, path) -> bool`. |
| `src/cli.py` | Subcomandos `ingest` (ampliado) e `reindex`, formatação do resumo, progresso e confirmação. | `cmd_ingest`, `cmd_reindex`, `_confirm_prune` (só pergunta se `stdin` for terminal) |

Detalhes:
- A chave do lock é `hashtextextended('rag-folder:' || <caminho>, 0)`, usada com `pg_try_advisory_lock`; a conexão da execução fica aberta até o fim.
- Cada arquivo usa **sua** transação (R9). A conexão é única na execução; nenhuma transação fica aberta durante a vetorização (como na F05, T1).
- A substituição (`replace_document`) faz, numa transação: `SELECT … FOR UPDATE` do documento, `UPDATE` de `sha256`, `pages`, `file_type`, `filename` e `updated_at`, `DELETE` dos trechos antigos e `INSERT` dos novos. Se o índice único de `sha256` disparar, a execução reclassifica o arquivo (como duplicado).
- O `--prune` só considera documentos com `source_id` da pasta (T9). Documentos avulsos e de outras pastas nunca entram.

## 6. Dados
**Sem migração nova.** Usa o esquema existente (`sql/001_init.sql`), sem mudar colunas ou índices.

| Tabela | O que a F08 faz |
|---|---|
| `sources` | Insere a pasta (`path` absoluto e resolvido, `recursive`), atualiza `recursive` e `last_indexed_at`. `path` já é `UNIQUE`. |
| `documents` | Passa a gravar `source_id` da pasta. Atualiza `sha256`, `pages`, `file_type`, `filename` e `updated_at` na substituição. `source_id` de avulso recebe o da pasta na adoção. Remove linhas em `--prune` e em duplicado que substitui versão anterior. |
| `chunks` | Apagados e regravados na substituição; apagados em cascata na remoção. |

`documents.source_id` já é `ON DELETE CASCADE` em relação a `sources`: apagar uma pasta de `sources` apaga seus documentos. Isso **não** é usado na F08 (remoção de pasta é da F09). `documents.status` `indexing` e `failed` continuam sem uso.

## 7. Configuração
Sem variáveis novas no `.env`.

| Parâmetro | Padrão | Onde se define |
|---|---|---|
| `--recursive` | `true` na primeira vez; depois, o valor guardado em `sources.recursive` | CLI (T8) |
| Extensões aceitas | `.txt`, `.md`, `.pdf` | `src/loaders.py` (existente) |
| Confirmação do `--prune` | Sempre exigida, em terminal interativo | Fixo (R10) |
| Limite de tamanho de arquivo / de páginas | Sem limite | ROADMAP (decisão pendente, a medir) |

## 8. Dependências externas
- Nenhum pacote novo.
- PostgreSQL com o esquema aplicado (`init-db`); funções de lock consultivo (nativas).
- **Amostras:** o roteiro monta pastas **temporárias fora do repositório**, a partir de `data/manual_colaborador.txt` e de `data/amostras/` (`guia.md`, `remote_policy.md`, `com_texto.pdf`, `escaneado.pdf`, `corrompido.pdf`, `nota.docx`, `grande.pdf`). Nenhum arquivo novo em `data/`.

## 9. Critérios de aceite — roteiro de teste manual

**Pré-condições:** ambiente virtual ativo; comandos na raiz do projeto; `init-db` aplicado; `.env` completo. As amostras do repositório **não podem estar cadastradas** em outro caminho (apareceriam como duplicadas): confira com a consulta 1 e, se for o caso, remova **só** os documentos de teste com `DELETE FROM documents WHERE source_path LIKE '<raiz do projeto>/data/%';` (**sem** `DELETE` geral: a base pode ter documentos reais). Os passos que pedem confirmação do `--prune` exigem **terminal interativo** (para automatizar, use um pty, não `script`, que injeta um `^D`). O `Ctrl+C` do passo 31 deve ser enviado por um processo que não seja um job em segundo plano do shell (que ignora `SIGINT`). No macOS, `/tmp` é `/private/tmp`: é esse o caminho gravado na base.

Montagem das pastas de teste (`T=/tmp/f08`):
```
rm -rf $T && mkdir -p $T/docs/sub $T/docs2/sub $T/avulso
cp data/manual_colaborador.txt $T/docs/manual.txt
cp data/manual_colaborador.txt $T/docs/manual_copia.txt          # duplicado
cp data/amostras/guia.md data/amostras/com_texto.pdf $T/docs/
cp data/amostras/escaneado.pdf data/amostras/corrompido.pdf data/amostras/nota.docx $T/docs/
cp data/amostras/remote_policy.md $T/docs/sub/
touch $T/docs/.oculto.txt && ln -s $T/docs/manual.txt $T/docs/link.txt
```

| # | Passo | Comando / ação | Resultado esperado |
|---|---|---|---|
| 1 | Pasta nova | `python -m src.cli ingest $T/docs; echo $?` | Registrada agora, recursiva. `manual.txt`, `guia.md`, `com_texto.pdf` e `sub/remote_policy.md` **cadastrados**; `manual_copia.txt` **duplicado de** `…/docs/manual.txt`; `escaneado.pdf` e `corrompido.pdf` **falhou** com o motivo da F02; `nota.docx`, `.oculto.txt` e `link.txt` **ignorados** (formato, oculto, link). Resumo com as contagens. **Código 1** (houve falhas). |
| 2 | Banco após o passo 1 | Consultas 1 a 3 | `sources` com a pasta (`recursive = true`, `last_indexed_at` preenchido); 4 documentos com `source_id` da pasta, `indexed`; nenhum documento para os arquivos que falharam, duplicado e ignorados; 0 órfãos. |
| 3 | Reexecução sem mudanças | `python -m src.cli ingest $T/docs` | Os 4 **sem mudanças**; duplicado e falhas reportados de novo (as falhas são tentadas outra vez); **não carrega o modelo** (sem "Loading weights"); documentos e trechos inalterados. |
| 4 | `reindex` equivale | `python -m src.cli reindex $T/docs` | Mesmo resultado do passo 3. |
| 5 | Arquivo alterado | `echo "Linha nova." >> $T/docs/guia.md` e `reindex $T/docs` | `guia.md` **atualizado**; o `id` do documento é o mesmo; os trechos antigos sumiram (consulta 4: 0 órfãos e contagem coerente); os demais **sem mudanças**. |
| 6 | Arquivo novo | `echo "texto novo f08" > $T/docs/novo.txt` e `reindex $T/docs` | `novo.txt` **cadastrado**; os demais sem mudanças. |
| 7 | Alterado que vira duplicado | `cp $T/docs/manual.txt $T/docs/novo.txt` e `reindex $T/docs` | `novo.txt` **duplicado de** `manual.txt` `(versão anterior removida)`; o documento `novo.txt` e seus trechos saem da base (consulta 1). |
| 8 | Ausente sem `--prune` (R6) | `rm $T/docs/guia.md` e `reindex $T/docs; echo $?` | `guia.md` **ausente** (use `--prune`); o documento **continua** na base com seus trechos. O código é 1 só porque `escaneado.pdf` e `corrompido.pdf` seguem falhando na pasta; o ausente não influi no código. |
| 9 | `--prune` sem terminal | `reindex $T/docs --prune < /dev/null; echo $?` | `--prune exige confirmação em um terminal interativo; nada foi removido.`; código 1; nada removido. |
| 10 | `--prune`, responder `n` (terminal) | `reindex $T/docs --prune` e responder `n` (ou Enter) | Lista `guia.md`, pergunta `[s/N]`; nada removido. |
| 11 | `--prune`, responder `s` (terminal) | Repetir e responder `s` | `Removido: 1 documento(s)`; `guia.md` e seus trechos saem (0 órfãos); **só** documentos desta pasta. |
| 12 | Original removido libera duplicado | `rm $T/docs/manual.txt`; `reindex $T/docs --prune` (`s`); depois `reindex $T/docs` | Na 1ª execução `manual_copia.txt` ainda aparece **duplicado de** `manual.txt` e `manual.txt` é removido pelo `--prune`; na 2ª, `manual_copia.txt` é **cadastrado**. |
| 13 | `--no-recursive` | `cp data/amostras/sem_titulos.txt $T/docs2/sub/ ; cp data/amostras/guia.md $T/docs2/raiz.md` (conteúdos diferentes dos de `$T/docs`, senão viram duplicados); `ingest $T/docs2 --no-recursive` | Só `raiz.md` cadastrado; `sub/` não é percorrida; `sources.recursive = false`. |
| 14 | `recursive` guardado | `reindex $T/docs2` | Continua sem percorrer `sub/` (usa o valor guardado). |
| 15 | Mudar para recursiva | `ingest $T/docs2 --recursive` | `sub/sem_titulos.txt` **cadastrado**; `sources.recursive = true`. Depois `ingest $T/docs2` (sem opção) mantém `true`. |
| 15b | Subpastas fora do escopo (T13) | Com `$T/docs` já cadastrada de forma recursiva (passo 1): `ingest $T/docs --no-recursive`; depois `reindex $T/docs --prune` (`s` se perguntar) | Resumo traz `Aviso: 1 documento(s) em subpastas não são mais atualizados…` (`sub/remote_policy.md`); o documento **continua** na base e **não** é removido pelo `--prune`; código não muda. Restaurar com `ingest $T/docs --recursive`. |
| 16 | `--force` | Anotar os `chunks.id` de um documento (consulta 5); `ingest $T/docs2 --force` | Arquivos **atualizados** (mesmo hash); os `chunks.id` mudaram; o modelo é carregado; nenhum duplicado "forçado". |
| 17 | Avulso adotado | `echo "texto avulso a f08" > $T/avulso/a.txt`; `ingest $T/avulso/a.txt` (avulso, `source_id` nulo); depois `ingest $T/avulso` (uma única vez) | Na pasta, `a.txt` **vinculado à pasta**, **sem carregar o modelo**; `source_id` agora preenchido; mesmo `id` e trechos. |
| 18 | Adotado entra no `--prune` | `rm $T/avulso/a.txt`; `reindex $T/avulso --prune` (`s`) | `a.txt` é **ausente** e removido. |
| 19 | Avulso alterado | `echo "texto avulso f08" > /tmp/b.txt`; `ingest /tmp/b.txt`; `echo "mais" >> /tmp/b.txt`; `ingest /tmp/b.txt` de novo | Segunda vez: **atualizado** (na F05 era erro); código 0. |
| 20 | Falha mantém a versão anterior | `cp data/amostras/corrompido.pdf $T/docs/com_texto.pdf`; `reindex $T/docs; echo $?` | `com_texto.pdf` **falhou** `(mantida a versão anterior)`; código 1; o documento continua `indexed` com os trechos antigos; `search` ainda os encontra. Restaurar o arquivo original em seguida. |
| 21 | Pastas sobrepostas | `ingest $T/docs/sub; echo $?` e `ingest $T; echo $?` | Ambas recusadas (`se sobrepõe à pasta já registrada`); código 1; nada registrado. |
| 22 | Caminho inexistente | `ingest $T/nao_existe; echo $?` | Mensagem da F02; código 1; **não** aparece em `sources`. |
| 23 | Pasta sem formatos aceitos | `mkdir $T/vazia && touch $T/vazia/.x`; `ingest $T/vazia` | `Nenhum arquivo TXT, MD ou PDF encontrado…`; código 0; pasta registrada. |
| 24 | `reindex` sem argumentos | `reindex; echo $?` e `reindex $T/docs --all; echo $?` | Erro de argumento; código 2. |
| 25 | `reindex` de pasta não registrada | `reindex /tmp/outra; echo $?` | `não está registrada…`; código 1. |
| 26 | `reindex --all` | `reindex --all` | Percorre todas as pastas registradas em ordem de cadastro, com um resumo por pasta; código reflete falhas (as de `docs`). |
| 27 | Pasta registrada sumiu, sem `--prune` | `mv $T/docs2 $T/docs2_x`; `reindex $T/docs2; echo $?` | `A pasta … não foi encontrada em disco. Nada foi alterado.`; código 1; documentos intactos. Em `reindex --all`, as outras pastas **são** processadas. |
| 28 | Pasta sumiu, com `--prune` (terminal) | `reindex $T/docs2 --prune`, responder `n` | Mensagem destaca que a pasta não foi encontrada e quantos documentos seriam removidos; `n` mantém tudo. Restaurar: `mv $T/docs2_x $T/docs2`. |
| 29 | Trava por pasta (T5) | `mkdir $T/grande && cp data/amostras/grande.pdf $T/grande/`; em dois terminais, `ingest $T/grande` quase juntos | Um segue; o outro: `Já existe uma atualização da pasta … em andamento…`, código 1, na hora. Depois de terminar, nova execução funciona. |
| 30 | Trava liberada se o processo cair | Iniciar `ingest` de uma pasta com PDF grande não cadastrado, `kill -9` do processo, executar de novo | A nova execução **não** é recusada (consulta 6 sem lock pendente) e conclui. |
| 31 | `Ctrl+C` no meio | Pasta com vários arquivos novos e `grande.pdf`; `Ctrl+C` durante o PDF grande | `Atualização interrompida; os arquivos já concluídos foram mantidos.`; resumo parcial; código 1; 0 órfãos; `last_indexed_at` não mudou; `--prune` não rodou. |
| 32 | Erro global: modelo divergente | `EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 python -m src.cli ingest $T/docs` com um arquivo novo na pasta | Mensagem da F04, **sem carregar** o outro modelo; código 1; nada gravado; com **tudo sem mudanças** o comando conclui normalmente (T4). |
| 33 | Opções de pasta com arquivo | `ingest $T/avulso/b.txt --prune; echo $?` e com `--no-recursive` | `<opção> só se aplica a pastas.`; código 1; nada feito. |
| 34 | Consulta enxerga a pasta (F06/F07) | `search "trabalho remoto"` e `ask "posso trabalhar de casa?"` | Trechos da pasta aparecem com arquivo e página; documentos removidos não aparecem mais. |
| 35 | Banco sem esquema | Renomear `sources` em banco de teste e `ingest $T/docs` | Erro claro (`Execute init-db`); código 1; sem traceback. |
| 36 | Importação sem efeitos | `python -c "import src.folder_ingestion"` | Sem saída; sem conectar nem carregar modelo. |
| 37 | Somente o previsto | `git status` | Só os arquivos previstos (seção 5) e as docs; nada novo em `data/`. |
| 38 | Limpeza | Remover os documentos de teste e `rm -rf $T` | Base sem resíduos do teste (consulta 1). |

**Consultas úteis para conferir o banco**
```sql
-- 1) documentos e pastas
SELECT d.id, d.source_path, d.source_id, d.status, d.pages, d.updated_at FROM documents d ORDER BY d.source_path;
-- 2) pastas registradas
SELECT id, path, recursive, last_indexed_at FROM sources ORDER BY id;
-- 3) documentos e trechos por pasta
SELECT d.source_id, d.id, count(c.id) AS trechos FROM documents d LEFT JOIN chunks c ON c.document_id = d.id GROUP BY d.source_id, d.id ORDER BY 1, 2;
-- 4) órfãos / documentos sem trechos (devem ser 0)
SELECT count(*) FROM chunks c LEFT JOIN documents d ON d.id = c.document_id WHERE d.id IS NULL;
SELECT count(*) FROM documents d LEFT JOIN chunks c ON c.document_id = d.id WHERE c.id IS NULL;
-- 5) ids dos trechos de um documento (passo 16)
SELECT id FROM chunks WHERE document_id = <id> ORDER BY chunk_index;
-- 6) locks consultivos pendentes (passo 30)
SELECT pid, objid FROM pg_locks WHERE locktype = 'advisory';
```

## 10. Impacto em outras features

| Feature | Roteiros a repetir (#) | Motivo |
|---|---|---|
| F05 | 1, 3, 4, 5, 8, 14 | `ingest` e `ingestion.py` foram alterados. **Os passos 12 (pasta é erro) e 13 (arquivo alterado é erro) deixam de valer, de propósito**: passam a cadastrar a pasta e a substituir o arquivo. A F05 recebe uma nota de atualização. |
| F06 | 3, 4, 25 | `DocumentRow` e a gravação ganharam `source_id`; a busca segue igual. |
| F07 | 1, 5 | `ask` sobre documentos cadastrados pela pasta. |
| F01 | `init-db` e `check` | Sem mudança de esquema; confirmar. |
| F04 | 4 | Registro e conferência do modelo agora acontecem uma vez por execução de pasta. |
| F13 | 1 | `.md` aceito na pasta. |
| F09, F10 | — | Passam a usar `sources`, `source_id` e `reindex_folders`. |

## 11. Riscos e decisões

**Decisões tomadas** (confirmadas pela pessoa)
- **Concorrência: trava por pasta que recusa a segunda execução** (lock consultivo do PostgreSQL). Resolve a decisão pendente do ROADMAP sobre acesso simultâneo.
- **Falhas só no resumo, nada no banco.** O arquivo é tentado de novo a cada execução. Evita linha `failed` que bloquearia uma cópia boa do mesmo conteúdo pelo índice único de `sha256`. **Revoga o previsto na ARQUITETURA §6.1** (`failed` com `error`).
- **`--force` refaz os arquivos com o modelo registrado.** A **troca de `EMBEDDING_MODEL`** continua bloqueada pela F04 e fica como pendência futura: a mensagem da F04 manda "reindexar", mas nenhuma feature planejada implementa a troca.
- **Avulso dentro da pasta é adotado** (vinculado, sem revetorizar) e passa a valer para `reindex` e `--prune`.
- **Código de saída 1** com falha de arquivo, erro global ou de pasta, ou `--prune` sem confirmação possível; 0 caso contrário.
- **`--prune` antecipa a confirmação da R10** (a R10 era da F09): lista o que será removido e pede `s/N`; sem terminal interativo, não remove.
- **Pastas não podem se sobrepor** (T7).
- **Ocultos e links simbólicos são ignorados e listados** (T6).
- **Pasta registrada que sumiu:** erro sem apagar nada; com `--prune`, todos os documentos dela contam como ausentes, com confirmação que destaca o motivo.
- **`recursive` guardado em `sources`** e atualizado só por opção explícita (T8).

**Detalhes confirmados pela pessoa, item a item**
- `reindex` exige `<pasta>` **ou** `--all`; sem nenhum dos dois, erro (código 2). A ARQUITETURA lista `[<pasta>|--all]` sem dizer o que acontece se faltar. `reindex` **não** tem `--force`: ele existe só em `ingest <pasta>`, como na ARQUITETURA.
- O `--prune` roda **depois** dos arquivos (T10), como a ARQUITETURA descreve ("passa a ser indexado na próxima ingestão"): um duplicado cujo original é removido nessa mesma execução só é cadastrado na seguinte.
- Documentos que ficaram fora da varredura por mudança para `--no-recursive` **permanecem** na base (existem em disco, logo não são ausentes), deixam de ser atualizados e o resumo **avisa** (T13).
- `ingest <arquivo>` não toma trava (a substituição é atômica e vale a proteção da F05); uma corrida entre um arquivo avulso e uma atualização da pasta que o contém resulta em uma das duas versões, nunca em trechos pela metade.
- Pasta registrada que sumiu, com `--prune`: confirmação `s/N` destacada (mensagem cita o total e "unidade desmontada?"), sem confirmação reforçada. Sem `--prune`, só erro.

**Riscos aceitos**
- Arquivos que falham são tentados de novo a cada execução (leitura de PDF grande corrompido repetida). Sem registro no banco, não há "lembrar a falha".
- Sem retomada: uma interrupção no meio de **um arquivo grande** refaz esse arquivo inteiro.
- Arquivo **movido** para outra pasta registrada é visto como novo (duplicado do original, até o original ser removido com `--prune`) e depende de duas execuções.
- O hash do arquivo é recalculado a cada execução (leitura inteira de cada arquivo, mesmo sem mudança). Em pastas com centenas de PDFs isso custa tempo de disco; medir e, se preciso, comparar antes `tamanho` e `mtime` (decisão futura).
- A troca de `EMBEDDING_MODEL` continua sem procedimento; só um novo cadastro do zero a resolve por ora.

**Pontos em aberto**
- Nenhum para implementar; a troca de modelo e os limites de tamanho seguem no ROADMAP como pendências.

## 12. Documentação a atualizar
- `.spec/ROADMAP.md`: status da F08; a decisão pendente "Acesso simultâneo da equipe" passa a **resolvida** (trava por pasta); incluir a pendência futura "Troca de `EMBEDDING_MODEL` (reindexar a base)".
- `.spec/ARQUITETURA.md` §4 (trava por pasta, ocultos e links, pastas sem sobreposição, `recursive` guardado, `--prune` com confirmação, duplicado com versão anterior removida), §6.1 (falha isolada **sem** gravar `failed`) e §8 (`ingest` e `reindex` implementados, `--prune` pede confirmação); estrutura alvo (§10) com `folder_ingestion.py`.
- `.spec/features/F05-cadastro-de-documento.md`: nota de atualização (F08): pasta aceita, arquivo alterado substituído, passos 12 e 13 superados.
- `.claude/CLAUDE.md`: acrescentar F08 ao "implementada e verificada" ao concluir.
- `README.md`: sem mudanças (F12). `.env.example`: sem mudanças.

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
| 2026-10-09 | Claude (pré-verificação na implementação) | Passos executados abaixo | Aguarda execução e aprovação da pessoa. **Adaptação:** os documentos de teste das F06 e F07 (ids 39 e 41 a 44, em `data/`) foram removidos conforme a pré-condição e **restaurados ao final** com `ingest`; os 12 documentos reais não foram tocados; no fim a base voltou a 17 documentos, 0 pastas e 0 órfãos. Pastas de teste em `/tmp/f08` (gravado como `/private/tmp/f08`), removidas ao final. **Executados e conformes:** 1 e 2 (pasta nova: 4 cadastrados, 1 duplicado, 2 falharam com motivo da F02, 3 ignorados; código 1; `source_id` preenchido; 0 órfãos); 3 e 4 (reexecução e `reindex`: tudo sem mudanças, **sem carregar o modelo**); 5 (guia.md atualizado, mesmo id, 0 órfãos); 6; 7 (alterado que vira duplicado: versão anterior removida, 0 linhas); 8 (ausente permanece na base); 9 (`--prune` sem terminal: nada removido, código 1); 10 e 11 (respostas `n` e `s` com terminal simulado por pty: nada removido / removido, 0 órfãos); 12 (original removido: duplicado na 1ª execução, cadastrado na 2ª); 13 a 15 (`--no-recursive` guardado, reindex usa o guardado, `--recursive` atualiza, sem opção mantém); 15b (aviso de 1 documento em subpastas; `--prune` diz `Nenhum documento ausente` e não o remove); 16 (`--force`: `chunks.id` mudaram); 17 (avulso vinculado sem carregar o modelo; `source_id` de nulo para o da pasta); 18 (adotado entra no `--prune`); 19 (avulso alterado: atualizado, código 0); 20 (arquivo que passa a falhar: `mantida a versão anterior`, documento `indexed` com 3 trechos); 21 (sobreposição recusada nos dois sentidos); 22 (inexistente não registra); 23 (pasta sem formatos aceitos, código 0); 24 (argumentos, código 2); 25; 26 (`--all` percorre todas e sai com 1 pelas falhas de `docs`); 27 e 28 (pasta sumiu: erro sem apagar, `--all` segue nas outras, confirmação destacada com `n` mantém os 2 documentos); 29 (2ª execução recusada na hora, lock liberado ao fim); 30 (`kill -9`: 0 locks pendentes e nova execução conclui); 31 (SIGINT no PDF grande: 2 concluídos mantidos, PDF não gravado, `last_indexed_at` nulo, `--prune` não rodou, 0 órfãos); 32 (modelo divergente: erro global da F04 sem carregar o modelo, nada gravado; com tudo sem mudanças conclui); 33; 34; 35 (simulado em transação revertida: `Tabela sources ausente. Execute init-db.`); 36; 37. Regressão: F05 (cadastro avulso, já cadastrado, duplicado, PDF sem texto, formato, inexistente), F06 (`search` lexical), F07 (`ask` com fonte), `check`, `init-db` e importação do legado. **Ajustes de roteiro (não de comportamento):** passo 8 devolve código 1 porque a pasta tem arquivos que falham; passos 13/15 e 17 usam outros arquivos para não gerarem duplicados; confirmação testada por pty (o `script` injeta `^D`); `SIGINT` enviado por processo Python (job em segundo plano do shell ignora o sinal). **Tempos (sem meta fixa):** pasta com um PDF de 36 páginas e 143 trechos (`grande.pdf`) ~35 s; reexecução sem mudanças ~0,1 s e sem carregar o modelo. |
| 2026-10-09 | Jose Julio | Aprovado | Implementação e roteiro da seção 9 aprovados, conforme relato da pessoa. |
