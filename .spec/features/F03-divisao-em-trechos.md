# F03 — Divisão em trechos

| Campo | Valor |
|---|---|
| **Status da spec** | Aprovada |
| **Status da implementação** | Verificada |
| **Marco** | M1 — Fatia vertical |
| **Depende de** | F02 (consome `Page`/`iter_pages`). Não usa o banco. |
| **Regras de negócio** | R2 (base para citar a página) |
| **Seções da arquitetura** | §5 Chunking, §4 Ingestão (`Page`), §14 Testes |

## 1. Objetivo
Dividir o texto de um documento (páginas vindas da F02) em trechos que **guardam a página e a seção (caminho de títulos)** de onde saíram, para que busca e resposta possam citar documento e página (R2) e para que um trecho como "o limite é R$ 120" não perca a informação de que fala de refeição. Também corrigir as falhas conhecidas das 4 estratégias atuais.

## 2. Escopo

**Inclui**
- Novo tipo `Chunk` e nova estratégia **`structured_chunks`** (padrão), que divide por títulos Markdown, depois parágrafo, sentença e, por último, tamanho.
- `chunk_pages(pages, strategy="structured", **params)`: ponto único de entrada que entrega `Chunk`s, em fluxo (aceita o `iter_pages` da F02 sem carregar o documento inteiro).
- Correções das estratégias existentes (seção 4.4): `recursive_chunks`, `split_sentences` (e, por consequência, `sentence_chunks`) e `semantic_chunks`. `fixed_size_chunks` permanece como está.
- Script de apoio `scripts/chunk_document.py` para ver o resultado no terminal.

**Não inclui**
- Embeddings (F04), gravação no banco (F05), busca (F06).
- Validação do tamanho em **tokens** com o tokenizer do bge-m3 (F04/F11).
- Definição do tamanho/overlap definitivos: os valores abaixo são **iniciais**; a medição (hit rate/MRR) é da F11.
- Remover cabeçalhos/rodapés repetidos de PDF (depende de amostras reais; continua pendente do ROADMAP).
- Migrar `rag.py`, `hybrid_rag.py` e scripts antigos para o novo fluxo (F05/F12). Eles seguem chamando `recursive_chunks`/`sentence_chunks` (agora corrigidas).

## 3. Regras de negócio aplicáveis

| Regra | O que significa nesta feature |
|---|---|
| R2 | Todo trecho carrega o número da página (1-based, igual ao PDF) e a seção, para a fonte poder ser citada. |

**Regras técnicas**
- **T1.** Função pura: não lê arquivo, não escreve em disco, não usa o banco.
- **T2.** Um trecho pertence a **uma única página**. Frase que continua na página seguinte vira dois trechos.
- **T3.** A **seção vale entre páginas**: o título visto na página 3 continua sendo a seção dos trechos da página 4 até aparecer outro título.
- **T4.** Um trecho nunca mistura duas seções, e o overlap só é aplicado entre trechos da mesma seção e mesma página.
- **T5.** `chunk_index` é sequencial no documento, começando em 0 (corresponde a `chunks.chunk_index`).
- **T6.** Mesma entrada produz sempre a mesma saída (sem aleatoriedade), exceto `semantic`, que depende do modelo.

## 4. Comportamento esperado

### 4.1 Fluxo principal (`structured`)
1. Quem chama passa as páginas (`Iterable[Page]`) a `chunk_pages`.
2. Para cada página, o texto Markdown é dividido em **blocos**: título (`#` a `###`), tabela (linhas consecutivas começando com `|`) e parágrafo (separado por linha em branco). Títulos de nível 4 ou mais são tratados como texto comum.
3. Cada título atualiza o **caminho de seção** (ex.: `Manual do Colaborador — Acme Tech > Férias`): um título de nível N substitui o nível N e descarta os mais profundos. O título em si não vira trecho; um título sem texto abaixo não gera trecho.
4. Dentro da seção, na página, os parágrafos são agrupados até o limite `max_chars`. Parágrafo maior que o limite é dividido por sentença; sentença maior que o limite, por palavras, sem cortar palavra.
5. **Tabela** nunca é cortada no meio de uma linha. Se a tabela não couber em um trecho, divide-se **entre linhas**, repetindo o cabeçalho (primeira linha + separador) em cada parte. Uma única linha maior que o limite fica inteira, acima do limite (aceito; ver seção 11).
6. **Overlap** (`overlap_chars`): o fim do trecho de texto anterior, sem cortar palavra, é repetido no início do próximo trecho **da mesma seção e página** (T4). Tabelas não recebem overlap. O tamanho total do trecho (overlap + conteúdo novo) respeita `max_chars`.
7. Cada `Chunk` sai com `chunk_index`, `page`, `section`, `content` (limpo, sem o prefixo de seção).
8. `Chunk.embedding_text` devolve `"<section>\n\n<content>"` (ou só o conteúdo, se não houver seção): é o texto para a F04 (embedding) e, se decidido na F05/F06, para a busca textual. O `content` mostrado à pessoa continua limpo.

**Parâmetros iniciais** (constantes em `src/chunking.py`, definitivos só na F11): `max_chars=900`, `overlap_chars=110` (~12%).

### 4.2 Fluxos alternativos e erros

| Situação | Comportamento esperado | Saída |
|---|---|---|
| TXT sem nenhum título | Um documento de seção `None`, dividido por parágrafo/sentença/tamanho. | Trechos com `section=None`, `page=1`. |
| TXT com `##` (ex.: manual) | Os títulos definem a seção como em PDF. | `section` = `Manual do Colaborador — Acme Tech > Férias` etc. |
| Página sem texto (`text=""`) | Ignorada em silêncio; a numeração das demais não muda. | Nenhum trecho dessa página. |
| Todas as páginas sem texto | Sem erro: devolve zero trechos (a F02 já rejeita antes). | Lista vazia. |
| Seção curta (menor que um trecho) | Vira um trecho próprio, **sem juntar com a seção vizinha** (T4). | Trecho menor que `max_chars`. |
| Título no fim de uma página, texto na seguinte | Os trechos da página seguinte herdam a seção (T3). | `section` herdada. |
| `overlap_chars >= max_chars` ou `max_chars <= 0` | `ValueError` com mensagem clara. | `overlap_chars deve ser menor que max_chars`. |
| Estratégia desconhecida | `ValueError`. | `Estratégia desconhecida: "x". Use: structured, fixed, sentence, recursive, semantic.` |
| `strategy="semantic"` sem `model` | `ValueError`. | `A estratégia semantic exige o parâmetro model.` |
| Linha de tabela maior que `max_chars` | Mantida inteira, acima do limite. | Aparece em "acima do limite" no script. |

### 4.3 Saída para a pessoa
```
$ python -m scripts.chunk_document data/manual_colaborador.txt
Arquivo:    manual_colaborador.txt (txt, 1 página)
Estratégia: structured (max_chars=900, overlap_chars=110)
Trechos:    7 | tamanho mín 214 · média 412 · máx 655 | acima do limite: 0
--- Trecho 0 | página 1 | seção: Manual do Colaborador — Acme Tech > Férias | 389 caracteres ---
Colaboradores CLT têm direito a 30 dias corridos de férias…
--- Trecho 1 | página 1 | seção: Manual do Colaborador — Acme Tech > Trabalho remoto | 301 caracteres ---
…
```
Opções: `--strategy`, `--max-chars`, `--overlap`, `--show N` (padrão 5, `--show all` mostra todos). Erro de leitura (`LoaderError`): mensagem e código 1, sem traceback.

### 4.4 Correções das estratégias existentes

| Função | Falha atual | Correção |
|---|---|---|
| `recursive_chunks` | Ao dividir por `". "` o ponto é descartado (pontuação perdida). Texto vazio causa `IndexError` em `chunks[0]`. | O ponto fica no fim da frase anterior. Texto vazio devolve `[]`. |
| `split_sentences` | Divide em "Sr. Silva", "Dra. Ana", "etc." e em itens numerados ("1. Item"). | Não divide após abreviações comuns (lista fixa: Sr., Sra., Dr., Dra., Prof., Profa., Eng., Av., Ex., etc., vs., Mr., Mrs., Ms., St., nº/n.º) nem após número de item isolado (`1.`, `2)`); só divide se a próxima sentença começar com maiúscula, dígito, aspas ou marcador. Valores como `R$ 1.000,00` e `3,5` nunca são divididos. |
| `semantic_chunks` | Sem limite de tamanho: pode gerar trechos minúsculos ou enormes. | Novos parâmetros `min_chars=200` e `max_chars=1000`: trecho menor que o mínimo é unido ao vizinho; maior que o máximo é redividido (lógica recursiva). |
| `fixed_size_chunks` | (corta palavras de propósito, é a estratégia "ingênua" de comparação) | Sem mudanças. |

Assinaturas e retorno (`list[str]`) das 4 estratégias antigas não mudam, só ganham parâmetros opcionais.

## 5. Interface

**Comandos / opções da CLI**

Nenhum comando novo em `python -m src.cli` (o `ingest` nasce na F05). Para o teste manual, usa-se um script de apoio, como na F02:

| Comando | Argumentos e opções | Descrição |
|---|---|---|
| `python -m scripts.chunk_document` | `<arquivo>` `[--strategy structured\|fixed\|sentence\|recursive\|semantic]` `[--max-chars N]` `[--overlap N]` `[--show N\|all]` | Lê com `iter_pages` (F02), divide com `chunk_pages` e mostra o resumo da 4.3. Código 0 se ok, 1 se `LoaderError` ou parâmetro inválido. |

**Módulos e funções**

| Arquivo | Responsabilidade | Funções / classes |
|---|---|---|
| `src/chunking.py` | Estratégias de divisão e tipo `Chunk`. | `Chunk(chunk_index: int, page: int, section: str \| None, content: str)` com propriedade `embedding_text`; `structured_chunks(pages: Iterable[Page], max_chars=900, overlap_chars=110) -> Iterator[Chunk]`; `chunk_pages(pages, strategy="structured", model=None, **params) -> Iterator[Chunk]`; as 4 antigas corrigidas. |
| `scripts/chunk_document.py` | Apoio ao teste manual (descartável; pode sair na F12). | `main()` |

Detalhes:
- `chunk_pages` com estratégia antiga aplica a função **página a página** e devolve `Chunk` com `section=None`; assim F05 e F11 usam a mesma interface para todas.
- `structured_chunks` mantém em memória só o caminho de seção atual e a página corrente (processamento em fluxo, ARQUITETURA §6.1).
- `semantic` exige `model` (SentenceTransformer); no script, o modelo é carregado só quando a estratégia é essa.
- Importar `src.chunking` não pode exigir `.env`, banco nem carregar modelo.

## 6. Dados
Sem mudanças. O `Chunk` mapeia para `chunks.chunk_index`, `page`, `section` e `content` (F01). Observação para F05/F06: a coluna `tsv` hoje é gerada só de `content`; se a busca textual deve enxergar a seção (ARQUITETURA §5, item 3), será preciso uma migração. Decisão adiada para a F05/F06.

## 7. Configuração
Sem mudanças no `.env`.

| Parâmetro | Padrão | Onde se define |
|---|---|---|
| `max_chars` | 900 | Constante em `src/chunking.py`; opção `--max-chars` no script |
| `overlap_chars` | 110 | Constante em `src/chunking.py`; opção `--overlap` |
| `min_chars` / `max_chars` (semantic) | 200 / 1000 | Parâmetros de `semantic_chunks` |

## 8. Dependências externas
- Nenhum pacote novo.
- **Arquivos de exemplo** em `data/amostras/` (sintéticos, gerados por script descartável fora do projeto e versionados, como na F02):
  - já existem: `data/manual_colaborador.txt`, `com_texto.pdf` (títulos + tabela), `parcial.pdf` (página em branco), `escaneado.pdf`, `real.pdf`, `grande.pdf` (os dois últimos fora do Git);
  - novos: `sem_titulos.txt` (texto corrido, sem `#`), `abreviacoes.txt` (frases com "Sr.", "Dra.", "R$ 1.000,00", "3,5", itens "1. …"), `secao_multipagina.pdf` (título na p.1 e texto longo que continua na p.2), `tabela_grande.pdf` (tabela maior que 900 caracteres, com cabeçalho).

## 9. Critérios de aceite — roteiro de teste manual

**Pré-condições:** ambiente virtual ativo; comandos da raiz do projeto; arquivos da seção 8 presentes. Não precisa de banco. Os passos de `semantic` carregam o bge-m3 (lento na primeira vez).

| # | Passo | Comando / ação | Resultado esperado |
|---|---|---|---|
| 1 | TXT com títulos | `python -m scripts.chunk_document data/manual_colaborador.txt --show all` | Um trecho (ou mais) por seção; `seção:` mostra `Manual do Colaborador — Acme Tech > Férias`, `> Trabalho remoto` etc.; `página 1`; `acima do limite: 0`. Código 0. |
| 2 | Conteúdo limpo | Observar o texto dos trechos do passo 1 | O texto do trecho não repete o caminho da seção nem o `##`. |
| 3 | Nada se perde | Comparar o texto do manual com a soma dos trechos (descontando overlap) | Todas as frases do manual aparecem em algum trecho; E-5107 e "R$ 120,00" presentes. |
| 4 | Tamanho | Passo 1 com `--max-chars 300 --overlap 40` | Nenhum trecho passa de 300; `acima do limite: 0`; mais trechos que no passo 1. |
| 5 | Overlap só dentro da seção | Passo 4: olhar a transição entre duas seções | O primeiro trecho de uma nova seção **não** começa com texto da seção anterior. |
| 6 | Overlap aplicado | Passo 4: dois trechos seguidos da mesma seção | O início do segundo repete o fim do primeiro, sem palavra cortada. |
| 7 | TXT sem títulos | `python -m scripts.chunk_document data/amostras/sem_titulos.txt --show all` | `seção: —` (vazia) em todos; divisão por parágrafo; `página 1`. |
| 8 | PDF com títulos e tabela | `python -m scripts.chunk_document data/amostras/com_texto.pdf --show all` | Seções com caminho de títulos; páginas corretas conforme o leitor de PDF. |
| 9 | Tabela inteira | Mesmo comando, trecho com a tabela | Linhas da tabela completas (`\|`), nenhuma linha cortada no meio. |
| 10 | Tabela grande | `python -m scripts.chunk_document data/amostras/tabela_grande.pdf --show all` | A tabela é dividida **entre linhas**; cada parte começa com o cabeçalho; nenhuma linha cortada. |
| 11 | Seção entre páginas | `python -m scripts.chunk_document data/amostras/secao_multipagina.pdf --show all` | Trechos da página 2 têm a **mesma seção** do título da página 1 (T3). |
| 12 | Trecho não cruza página | Mesmo comando, olhar o último trecho da p.1 e o primeiro da p.2 | Páginas diferentes; nenhum trecho com texto das duas; sem overlap entre eles (T2/T4). |
| 13 | Página em branco | `python -m scripts.chunk_document data/amostras/parcial.pdf --show all` | Sem trecho da página em branco; as páginas seguintes mantêm o número original. |
| 14 | `chunk_index` | Ver os índices em qualquer passo anterior | Sequenciais a partir de 0, sem repetir nem pular. |
| 15 | PDF real | `python -m scripts.chunk_document data/amostras/real.pdf --show 10` | Roda sem erro; anotar no registro (seção 14) como ficaram seções, tabelas e cabeçalhos/rodapés repetidos. |
| 16 | PDF grande, em fluxo | `/usr/bin/time -l python -m scripts.chunk_document data/amostras/grande.pdf --show 0` | Termina sem erro; pico de memória anotado, sem crescer de forma proporcional ao nº de páginas. |
| 17 | Estratégias antigas | Passo 1 com `--strategy fixed`, `sentence`, `recursive` | Cada uma roda; `seção: —`; `página` correta; contagens diferentes entre elas. |
| 18 | Semântica | `--strategy semantic` no manual | Roda; nenhum trecho com menos de 200 nem mais de 1000 caracteres (salvo texto menor que 200 no total). |
| 19 | Correção: pontuação | `--strategy recursive --max-chars 120 --overlap 0` no manual | Os pontos finais não somem: cada trecho que termina uma frase termina com `.` (comparar com a versão anterior via `git stash`, opcional). |
| 20 | Correção: abreviações | `python -m scripts.chunk_document data/amostras/abreviacoes.txt --strategy sentence --max-chars 60 --overlap 0 --show all` | Nenhum corte entre "Sr." e o nome, "Dra." e o nome, nem dentro de "R$ 1.000,00" ou "3,5"; itens "1. …" não viram trechos soltos de 2 caracteres. |
| 21 | Texto vazio | `python -c "from src.chunking import recursive_chunks; print(recursive_chunks(''))"` | Imprime `[]`, sem `IndexError`. |
| 22 | Parâmetro inválido | `python -m scripts.chunk_document data/manual_colaborador.txt --max-chars 100 --overlap 100; echo $?` | `overlap_chars deve ser menor que max_chars`. Código 1. Sem traceback. |
| 23 | Estratégia inválida | `python -c "from src.chunking import chunk_pages; list(chunk_pages([], strategy='x'))"` | `ValueError` com a lista de estratégias. |
| 24 | Erro de leitura | `python -m scripts.chunk_document data/amostras/escaneado.pdf; echo $?` | Mensagem da F02 (PDF sem texto). Código 1. Sem traceback. |
| 25 | Importação sem efeitos | `python -c "from src.chunking import Chunk, chunk_pages, structured_chunks"` | Sem saída, sem erro, sem exigir `.env`, banco ou modelo. |
| 26 | Somente leitura | `git status` ao final | Só os arquivos previstos na spec (código, script, amostras sintéticas, docs). |

## 10. Impacto em outras features

| Feature | Roteiros a repetir (#) | Motivo |
|---|---|---|
| F02 | 1, 8, 12 | Confirmar que `Page`/`iter_pages` seguem intactos (F03 só consome). |
| Código atual (`rag.py`, `hybrid_rag.py`, `scripts/compare_*.py`, `semantic_search.py`) | `python -m scripts.compare_chunking` e `python -c "import src.rag, src.hybrid_rag"` | Usam `recursive_chunks`/`sentence_chunks`, cujo resultado muda com as correções. Conferir que ainda rodam. O índice em `data/index/` **não é reconstruído** (e não é removido). |
| F01 | `python -m src.cli check` | Sanidade do ambiente (nada muda, mas é barato). |
| F04, F05, F11 | — | Passam a consumir `Chunk`/`chunk_pages`. Mudança futura neles exige repetir os passos 1, 8, 11 e 14. |

## 11. Riscos e decisões

**Decisões tomadas** (com o motivo)
- **Estruturada como padrão + correção das 4 antigas** (decisão da pessoa): padrão novo para o produto, antigas mantidas para estudo e comparação (ARQUITETURA §5).
- **Trecho nunca cruza página** (decisão da pessoa): citação de página exata (R2) sem mudar o esquema do banco. Custo: frases que atravessam a página são divididas.
- **Só caracteres** (decisão da pessoa): evita carregar tokenizer na F03; o bge-m3 aceita 8192 tokens, então 900 caracteres têm folga ampla. Validação em tokens fica para F04/F11.
- **Script de apoio `scripts/chunk_document.py`** (decisão da pessoa), no mesmo molde do `read_document` da F02.
- **Seção vale entre páginas (T3)**: PDFs trazem o título em uma página e o conteúdo nas seguintes.
- **Título não vira trecho** e **seção curta não é juntada à vizinha (T4)**: evita que um trecho misture assuntos e cite a seção errada. Custo: trechos pequenos.
- **Títulos só até o nível 3** (ARQUITETURA §5); níveis mais fundos ficam como texto.
- **Tabela dividida entre linhas com o cabeçalho repetido**: cada parte é compreensível sozinha. Linha única maior que o limite fica inteira (o limite de 8192 tokens do modelo não é atingido na prática).
- **`chunk_pages` único para todas as estratégias**: F05 e F11 trocam de estratégia por parâmetro, sem código novo.
- **`tsv` e prefixo de seção**: a F03 só entrega `embedding_text`; se a busca textual deve enxergar a seção, decide-se na F05/F06 (pode exigir migração).
- **Tamanho 900/overlap 110 são iniciais**: o valor definitivo vem da F11, com medição.
- **Risco aceito:** o `pymupdf4llm` infere títulos pelo tamanho da fonte. PDFs sem hierarquia visual vão sair com `section=None`; só dá para avaliar com `real.pdf` (passo 15).

**Pontos em aberto** (precisam de resposta antes de implementar)
- Nenhum.

## 12. Documentação a atualizar
- `.spec/ROADMAP.md`: status da F03 (spec e implementação).
- `.spec/ARQUITETURA.md` §5: registrar `Chunk`, `chunk_pages`, `embedding_text` e a regra de "trecho não cruza página".
- `.claude/CLAUDE.md`: acrescentar F03 ao "implementada e verificada" quando concluída.
- `README.md`: fica para a F12.

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
| 2026-10-03 | Claude (pré-verificação na implementação) | Passos 1–25 executados, sem falhas | Aguarda execução e aprovação da pessoa. Observações: passo 16 (`grande.pdf`, 143 trechos) com pico ~419 MB, estável frente à F02. Passo 15 (`real.pdf`, contrato de 10 páginas, 37 trechos): marcadores `**` do Markdown permanecem no texto; rodapés (`1 / 8`, "Versão documento 7", hash) entram como texto no fim de trechos; seções vêm de linhas em caixa alta detectadas como título. Passo 20: com `--max-chars 60` as estratégias antigas mantêm sentença inteira acima do limite (comportamento já existente). Tabelas formam sempre trechos próprios (não dividem trecho com parágrafo). |
| 2026-10-03 | Jose Julio | Aprovado | Roteiro da seção 9 executado e aprovado, conforme relato da pessoa. |
