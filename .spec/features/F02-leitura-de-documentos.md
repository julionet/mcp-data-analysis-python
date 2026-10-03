# F02 — Leitura de documentos (TXT e PDF)

| Campo | Valor |
|---|---|
| **Status da spec** | Aprovada |
| **Status da implementação** | Verificada |
| **Marco** | M1 — Fatia vertical |
| **Depende de** | Nenhuma (F01 não é necessária: esta feature não usa o banco) |
| **Regras de negócio** | R7, R8 |
| **Seções da arquitetura** | §4 Ingestão de arquivos (`loaders`), §6.1 Arquivos grandes, §14 Testes |

## 1. Objetivo
Ler um arquivo TXT ou PDF e devolver seu texto dividido por página, com o hash do conteúdo, rejeitando com mensagem clara o que não for aceito (outro formato, PDF sem texto, arquivo corrompido). É a base para dividir (F03) e cadastrar (F05) os documentos, e para citar a página nas respostas (R2).

## 2. Escopo

**Inclui**
- Módulo `src/loaders.py` com `inspect_document(path)`, `iter_pages(path)` (leitura **página a página**, para PDFs grandes) e `load_document(path) -> Document` (conveniência: reúne as duas).
- Leitura de **TXT** (UTF-8, com fallback), todo o texto como página 1.
- Leitura de **PDF** com `pymupdf4llm`: cada página convertida em Markdown (títulos e tabelas preservados), com o número da página.
- Cálculo do `sha256` do arquivo (bytes originais).
- Erros claros e tipados para: extensão não aceita, arquivo inexistente, TXT vazio, PDF sem texto, PDF corrompido ou protegido por senha.
- Extensões casadas sem diferenciar maiúsculas (`.PDF`).
- Script de apoio `scripts/read_document.py` para ver o resultado da leitura no terminal (seção 5).

**Não inclui** (fica para outra feature ou fora de escopo)
- Divisão em trechos (F03), embeddings (F04) e gravação no banco (F05).
- Percorrer pastas, listar arquivos ignorados e continuar após falha de um arquivo: o loader trata **um** arquivo e levanta o erro; o resumo da pasta é da F08 (a F05 cobre o arquivo avulso).
- Limites de tamanho de arquivo e de páginas (F05).
- OCR de PDF escaneado (fora de escopo do projeto).
- Remover cabeçalhos e rodapés repetidos dos PDFs (depende de amostras reais; ver Pontos em aberto).

## 3. Regras de negócio aplicáveis

| Regra | O que significa nesta feature |
|---|---|
| R7 | Um arquivo com problema (corrompido, sem texto, formato não aceito) gera um erro com o motivo em português, que quem chama (F05/F08) usa no resumo. O loader nunca derruba o processo com traceback na CLI de apoio. |
| R8 | PDF sem texto selecionável é rejeitado com erro claro. Nada é devolvido. |

**Regras técnicas desta feature**
- **T1.** O loader é uma função pura de leitura: não escreve em disco, não usa o banco e não altera o arquivo.
- **T2.** O `sha256` é calculado sobre os **bytes do arquivo**, não sobre o texto extraído, para que a mesma versão do extrator não influencie a detecção de duplicados/alterações.
- **T3.** O número de página é **1-based** e corresponde à página do PDF (a mesma que a pessoa vê no leitor). Páginas sem texto continuam contando na numeração.

## 4. Comportamento esperado

### 4.1 Fluxo principal
1. Quem chama informa o caminho de um arquivo.
2. `inspect_document` confere que o arquivo existe e que a extensão (sem diferenciar maiúsculas) é `.txt` ou `.pdf`, calcula o `sha256` dos bytes (lendo em blocos) e abre o arquivo. Nesta etapa já são detectados **todos** os erros da seção 4.2 (inclusive PDF sem texto), antes de qualquer página ser convertida. Devolve `DocumentInfo` (nome, tipo, `sha256`, quantidade de páginas).
3. `iter_pages` entrega uma `Page` de cada vez, na ordem:
   **TXT:** uma única página (número 1) com o texto decodificado.
   **PDF:** cada página é convertida em Markdown só quando pedida, e o texto das páginas já entregues não é guardado pelo loader.
4. `load_document` chama os dois e devolve o `Document` completo (todas as páginas em memória). É para arquivos pequenos e para o roteiro de teste; o cadastro de arquivos grandes (F05) usa `inspect_document` + `iter_pages`.

### 4.2 Fluxos alternativos e erros

Todos os erros são `LoaderError` (ou subclasse) com a mensagem abaixo. A mensagem inclui o nome do arquivo.

| Situação | Comportamento esperado | Mensagem / saída |
|---|---|---|
| Arquivo não existe ou é uma pasta | Erro, nada lido. | `Arquivo não encontrado: <caminho>` |
| Extensão não é `.txt` nem `.pdf` | Erro, arquivo nem é aberto. | `Formato não aceito: "<extensão>" (<arquivo>). Use .txt ou .pdf.` |
| Arquivo sem extensão | Mesmo caso acima. | `Formato não aceito: sem extensão (<arquivo>). Use .txt ou .pdf.` |
| Extensão em maiúsculas (`.PDF`, `.TXT`) | Aceita normalmente; `file_type` sai em minúsculas. | — |
| TXT em UTF-8 com BOM | Lido sem o BOM no texto. | — |
| TXT em UTF-8 | Lido normalmente. | — |
| TXT em Latin-1 (não decodifica como UTF-8) | Lido com fallback `latin-1`. | — |
| TXT vazio ou só com espaços e quebras de linha | Rejeitado. | `Arquivo sem texto: <arquivo>` |
| PDF com texto em todas ou em algumas páginas | Aceito. Páginas sem texto saem com `text=""`, mantêm o número e são ignoradas **em silêncio** (sem aviso). | — |
| PDF sem nenhum texto extraível (provável escaneado) | Rejeitado (R8) em `inspect_document`, antes de converter qualquer página. A checagem usa uma extração de texto simples e rápida de todas as páginas (sem Markdown). | `PDF sem texto selecionável (provavelmente escaneado): <arquivo>. Não há suporte a OCR.` |
| PDF corrompido ou que não abre | Rejeitado. | `Não foi possível ler o PDF: <arquivo> (arquivo corrompido ou inválido).` |
| PDF protegido por senha | Rejeitado. | `PDF protegido por senha: <arquivo>.` |
| Arquivo `.pdf` que na verdade é outro formato (ex.: texto renomeado) | Tratado como PDF corrompido. | Mesma mensagem do PDF corrompido. |
| Arquivo sem permissão de leitura | Erro. | `Sem permissão para ler: <arquivo>` |

### 4.3 Saída para a pessoa

O loader em si não imprime nada. Para conferir a leitura manualmente (ver seção 5):

```
$ python -m scripts.read_document data/manual_colaborador.txt
Arquivo:  manual_colaborador.txt
Tipo:     txt
SHA-256:  3f2a…c91b
Páginas:  1
--- Página 1 (1.234 caracteres) ---
<primeiros 300 caracteres do texto>…
```

```
$ python -m scripts.read_document data/amostras/relatorio.pdf
Arquivo:  relatorio.pdf
Tipo:     pdf
SHA-256:  9b10…77ad
Páginas:  12 (2 sem texto)
--- Página 1 (2.410 caracteres) ---
# Relatório anual
…
```

Erro:
```
$ python -m scripts.read_document data/amostras/escaneado.pdf; echo $?
PDF sem texto selecionável (provavelmente escaneado): escaneado.pdf. Não há suporte a OCR.
1
```

Opção `--page N` mostra o texto completo da página N em vez dos primeiros 300 caracteres.

## 5. Interface

**Comandos / opções da CLI**

Nenhum comando novo em `python -m src.cli`: o cadastro (`ingest`) nasce na F05. Para permitir o teste manual desta feature antes disso, usa-se um script de apoio (decisão aprovada):

| Comando | Argumentos e opções | Descrição |
|---|---|---|
| `python -m scripts.read_document` | `<arquivo>` `[--page N]` | Lê o arquivo com `load_document` e mostra o resumo da seção 4.3. Código 0 se leu, 1 se houve `LoaderError`. |

**Módulos e funções**

| Arquivo | Responsabilidade | Funções / classes |
|---|---|---|
| `src/loaders.py` | Leitura de TXT e PDF e tipos de dados. | `Page(number: int, text: str)`, `DocumentInfo(filename, file_type, sha256, page_count)`, `Document(filename, file_type, sha256, pages: list[Page])`, `inspect_document(path) -> DocumentInfo`, `iter_pages(path) -> Iterator[Page]`, `load_document(path) -> Document`, `LoaderError(Exception)` |
| `scripts/read_document.py` | Apoio ao teste manual (descartável; pode ser removido na F12). Usa `inspect_document` e `iter_pages`; com `--page N` para de iterar ao chegar na página N. | `main()` |

Detalhes:
- `iter_pages` chama `inspect_document` antes de entregar a primeira página (então levanta os mesmos erros, uma única vez) e mantém o arquivo aberto só durante a iteração, fechando-o também se quem chama parar antes do fim.
- `page_count` do TXT é 1; do PDF, o total de páginas do arquivo (inclusive as vazias).
- `filename` é só o nome do arquivo (sem pasta); o caminho absoluto fica com quem cadastra (F05).
- `file_type` é `"txt"` ou `"pdf"`.
- `pages` tem uma `Page` por página do PDF (inclusive as vazias) ou uma única página para TXT.
- PDF: abre o documento com PyMuPDF e converte **uma página por vez** com `pymupdf4llm.to_markdown(doc, pages=[i])`; o número da página é `i + 1`.
- Texto das páginas: sem espaços/linhas em branco sobrando no começo e no fim (`strip()`); quebras internas são preservadas.
- Decodificação do TXT: tenta `utf-8-sig` (cobre UTF-8 com e sem BOM) e, em caso de erro, `latin-1`.
- Erros internos do PyMuPDF são capturados e convertidos em `LoaderError`; o tipo original não vaza.

## 6. Dados
Sem mudanças. Esta feature não toca o banco; `Document` e `Page` são só estruturas em memória. Os campos `sha256`, `file_type` e `pages` (quantidade) já existem em `documents` (F01) e serão gravados na F05.

## 7. Configuração
Sem mudanças. Nenhuma variável de `.env` nova e nenhum limite (tamanho e páginas máximos entram na F05).

## 8. Dependências externas
- **Python:** `pymupdf4llm` (traz o `pymupdf`), adicionado ao `requirements.txt`.
- **Arquivos de exemplo** em `data/amostras/` (o PDF real é fornecido pela pessoa e não é versionado; os sintéticos são gerados por nós e versionados):
  - `data/manual_colaborador.txt` (já existe).
  - `real.pdf`: PDF real da equipe, fornecido pela pessoa (para avaliar o layout).
  - `grande.pdf`: PDF com 100 páginas ou mais (pode ser o próprio `real.pdf`, se tiver o tamanho).
  - `texto_latin1.txt`: TXT salvo em Latin-1 com acentos.
  - `vazio.txt`: arquivo vazio.
  - `com_texto.pdf`: PDF de 2 ou 3 páginas com títulos e uma tabela.
  - `parcial.pdf`: PDF com uma página em branco no meio.
  - `escaneado.pdf`: PDF só com imagem (sem texto).
  - `corrompido.pdf`: arquivo truncado ou com bytes aleatórios.
  - `protegido.pdf`: PDF com senha (opcional, se a pessoa conseguir gerar).
  - `nota.docx`: qualquer arquivo com outra extensão.

## 9. Critérios de aceite — roteiro de teste manual

**Pré-condições:** ambiente virtual ativo com `pip install -r requirements.txt`; comandos executados da raiz do projeto; arquivos de exemplo da seção 8 em `data/amostras/`. Não precisa de banco.

| # | Passo | Comando / ação | Resultado esperado |
|---|---|---|---|
| 1 | TXT UTF-8 | `python -m scripts.read_document data/manual_colaborador.txt; echo $?` | Tipo `txt`, `Páginas: 1`, SHA-256 de 64 caracteres hexadecimais, início do texto legível. Código 0. |
| 2 | Hash confere | `shasum -a 256 data/manual_colaborador.txt` | Mesmo valor mostrado no passo 1. |
| 3 | Hash estável | Repetir o passo 1 | Mesmo SHA-256. |
| 4 | Hash muda com o conteúdo | Copiar o arquivo para a pasta do scratchpad, acrescentar uma linha e rodar o comando na cópia | SHA-256 diferente do passo 1. Original intacto (`git status` limpo). |
| 5 | TXT Latin-1 | `python -m scripts.read_document data/amostras/texto_latin1.txt` | Acentos corretos (sem `Ã©` nem `�`). Código 0. |
| 6 | TXT com BOM | Criar cópia com BOM (`printf '\xef\xbb\xbfolá' > <scratchpad>/bom.txt`) e ler | Texto começa em `olá`, sem caractere estranho. |
| 7 | TXT vazio | `python -m scripts.read_document data/amostras/vazio.txt; echo $?` | `Arquivo sem texto: vazio.txt`. Código 1. Sem traceback. |
| 8 | PDF com texto | `python -m scripts.read_document data/amostras/com_texto.pdf` | Tipo `pdf`, número de páginas igual ao do arquivo (conferir no leitor de PDF). Páginas numeradas a partir de 1. |
| 9 | Markdown no PDF | `python -m scripts.read_document data/amostras/com_texto.pdf --page 1` | Títulos aparecem com `#`; a tabela aparece em formato de tabela Markdown (`\|`). |
| 10 | Numeração de páginas | `--page 2` e `--page 3` do mesmo PDF | O texto mostrado é o da página correspondente no leitor de PDF. |
| 11 | Página inexistente | `--page 99` | Mensagem `Página 99 não existe (o documento tem <N>).` Código 1. |
| 11a | PDF real | `python -m scripts.read_document data/amostras/real.pdf` | Lê sem erro. Número de páginas igual ao do leitor de PDF. Anotar no registro (seção 14) como ficaram colunas, tabelas e cabeçalhos/rodapés. |
| 11b | Leitura em fluxo | `python -c "from src.loaders import iter_pages; it = iter_pages('data/amostras/grande.pdf'); print(type(it).__name__, next(it).number)"` | Mostra `generator 1` rapidamente, sem converter o PDF inteiro. |
| 11c | Parar antes do fim | `python -m scripts.read_document data/amostras/grande.pdf --page 2` | Mostra a página 2 muito mais rápido do que a leitura completa do arquivo. |
| 11d | Memória estável | Em `grande.pdf`: `/usr/bin/time -l python -c "from src.loaders import iter_pages; [len(p.text) for p in iter_pages('data/amostras/grande.pdf')]"` | Termina sem erro. O pico de memória (`maximum resident set size`) é anotado no registro; não deve crescer de forma proporcional ao número de páginas ao comparar com um PDF menor. |
| 11e | Erro antes da 1ª página | `python -c "from src.loaders import iter_pages; next(iter_pages('data/amostras/escaneado.pdf'))"` | Levanta `LoaderError` (PDF sem texto) já na primeira chamada. |
| 12 | Página em branco | `python -m scripts.read_document data/amostras/parcial.pdf` | Aceito; resumo indica `(1 sem texto)`; a página em branco mantém o número e as seguintes não são renumeradas. |
| 13 | PDF escaneado | `python -m scripts.read_document data/amostras/escaneado.pdf; echo $?` | Mensagem de PDF sem texto selecionável (4.2). Código 1. Sem traceback. |
| 14 | PDF corrompido | `python -m scripts.read_document data/amostras/corrompido.pdf; echo $?` | Mensagem de PDF corrompido. Código 1. Sem traceback. |
| 15 | Texto renomeado para `.pdf` | `cp data/manual_colaborador.txt <scratchpad>/falso.pdf` e ler | Mesma mensagem do passo 14. |
| 16 | PDF com senha | `python -m scripts.read_document data/amostras/protegido.pdf` | Mensagem de PDF protegido por senha. Código 1. (Pular se não houver o arquivo.) |
| 17 | Formato não aceito | `python -m scripts.read_document data/amostras/nota.docx; echo $?` | `Formato não aceito: ".docx"…`. Código 1. |
| 18 | Sem extensão | `cp data/manual_colaborador.txt <scratchpad>/semext` e ler | `Formato não aceito: sem extensão…`. Código 1. |
| 19 | Maiúsculas | `cp data/amostras/com_texto.pdf <scratchpad>/COM_TEXTO.PDF` e ler | Aceito, `Tipo: pdf`. |
| 20 | Arquivo inexistente | `python -m scripts.read_document data/nao_existe.txt; echo $?` | `Arquivo não encontrado: …`. Código 1. |
| 21 | Pasta no lugar de arquivo | `python -m scripts.read_document data/` | Mesma mensagem do passo 20. Código 1. |
| 22 | Sem permissão | `chmod 000` em uma cópia, ler, depois `chmod 644` | `Sem permissão para ler: …`. Código 1. |
| 23 | Somente leitura | `git status` após todos os passos | Nenhum arquivo versionado alterado, fora os sintéticos adicionados em `data/amostras/`. `real.pdf` e `grande.pdf` não aparecem como novos (estão no `.gitignore`; conferir com `git check-ignore data/amostras/real.pdf`). |
| 24 | Importação sem efeitos | `python -c "from src.loaders import load_document, Document, Page, LoaderError"` | Sem saída e sem erro. Não exige `.env` nem banco. |

## 10. Impacto em outras features

| Feature | Roteiros a repetir (#) | Motivo |
|---|---|---|
| F01 | 1 e 10 (`python -m src.cli` e `check`) | `requirements.txt` é alterado (novo pacote `pymupdf4llm`). Conferir que a instalação não quebrou o `psycopg`. |
| Código atual (`scripts/`) | `python -c "from src.config import LLM_MODEL, EMBEDDING_MODEL; print(LLM_MODEL, EMBEDDING_MODEL)"` | Conferir que o ambiente continua importando normalmente. A leitura de TXT dos pipelines antigos **não é alterada** nesta feature (a troca ocorre na F05/F12). |
| F03, F05 | — | Passam a consumir `Page`/`iter_pages` (e `Document` para arquivos pequenos). Qualquer mudança futura nessas estruturas exige repetir os passos 1, 8, 11b e 12. |

## 11. Riscos e decisões

**Decisões tomadas** (com o motivo)
- **Um loader por arquivo, sem lógica de pasta**: mantém a spec curta e verificável; o resumo de pasta e as falhas isoladas são da F08 (R7).
- **`sha256` dos bytes do arquivo (T2)**: independe da versão do extrator e permite saber se o arquivo mudou sem precisar extrair o texto.
- **Páginas vazias permanecem na lista**: mantém a numeração fiel ao PDF, necessária para citar a página (R2).
- **PDF é rejeitado só quando nenhuma página tem texto**: PDFs mistos são aceitos e as páginas vazias ficam para trás sem erro.
- **TXT = página 1**: conforme ARQUITETURA §4.
- **Fallback de encoding só `utf-8-sig` → `latin-1`**: conforme ARQUITETURA §4. Como `latin-1` decodifica qualquer byte, ele nunca falha; um arquivo em outra codificação sairia com caracteres errados. Risco aceito.
- **Script de apoio `scripts/read_document.py`** em vez de novo comando na CLI (decisão da pessoa): a CLI de produção ganha comandos junto de cada feature (`ingest` na F05). O script pode ser removido na F12.
- **Leitura em fluxo com `iter_pages`** (decisão da pessoa), para PDFs grandes (ARQUITETURA §6.1). `load_document` continua existindo para arquivos pequenos e testes. Os erros são todos detectados antes da primeira página, para que o cadastro não comece e falhe no meio por um PDF sem texto.
- **Conferência `is_pdf`:** o PyMuPDF abre arquivos pelo conteúdo e ignora a extensão (um TXT renomeado para `.pdf` abriria como "documento Markdown"). O loader exige `doc.is_pdf`; caso contrário, devolve a mensagem de PDF corrompido (passo 15 do roteiro). Descoberto durante a implementação.
- **PDF parcialmente escaneado:** aceito; páginas sem texto são ignoradas em silêncio (decisão da pessoa).
- **`real.pdf` e `grande.pdf` ficam fora do Git** (decisão da pessoa), por poderem ter conteúdo da equipe: são listados no `.gitignore`. Os arquivos sintéticos do roteiro são gerados por nós (decisão da pessoa) e **versionados**, pois não têm conteúdo sensível. Eles são gerados com um script descartável fora do projeto (PyMuPDF já vem com o `pymupdf4llm`), sem dependência nova.
- **Cabeçalhos e rodapés repetidos:** não tratados aqui; fica para depois de analisar PDFs reais (decisão da pessoa).
- **Risco aceito:** a qualidade da extração de PDFs reais (colunas, tabelas complexas, cabeçalhos repetidos) só pode ser avaliada com amostras do usuário.

**Pontos em aberto**
- Nenhum.

## 12. Documentação a atualizar
- `requirements.txt`: acrescentar `pymupdf4llm`.
- `.gitignore`: acrescentar `data/amostras/real.pdf` e `data/amostras/grande.pdf`.
- `.spec/ROADMAP.md`: status da F02 (spec e implementação).
- `.claude/CLAUDE.md`: acrescentar F02 ao "implementada e verificada" quando concluída.
- `README.md`: fica para a F12.
- `ARQUITETURA.md` §4: acrescentar `inspect_document` e `iter_pages` ao módulo `loaders`, e `DocumentInfo` junto de `Document`.

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
| 2026-10-02 | Jose Julio | Aprovado | Roteiro da seção 9 executado, sem falhas, conforme relato da pessoa. Verificação prévia na implementação: `grande.pdf` com 36 páginas (menos que as 100 pedidas); pico de memória estável (~415 MB) entre `real.pdf` (10 páginas) e `grande.pdf`. Regressão da F01 (`check`) com código 0. |
