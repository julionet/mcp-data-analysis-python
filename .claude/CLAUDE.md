# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Estado do projeto e fluxo de trabalho

Aplicação de estudo de RAG (arquivos TXT, base vetorial local em numpy, Claude para gerar respostas). O código em `src/` e `scripts/` é a **versão atual**. Ela está em **evolução planejada** para TXT + PDF com PostgreSQL/pgvector, conduzida por **Spec Driven Development**. Implementada e verificada até agora: **F01** (banco, esquema e CLI `python -m src.cli` com `init-db` e `check`) e **F02** (leitura de TXT e PDF em `src/loaders.py`, com `scripts/read_document.py` de apoio) e **F03** (divisão em trechos em `src/chunking.py`, com `Chunk`, `structured_chunks` e `chunk_pages`, e `scripts/chunk_document.py` de apoio) e **F04** (vetorização dos trechos em `src/embeddings.py`, com `Embedder` e `embed_chunks`; registro e conferência do modelo em `app_meta` via `src/db.py`; `check` ampliado e `scripts/embed_document.py` de apoio); o restante ainda não. Status por feature em `.spec/ROADMAP.md`.

Documentos de especificação (aprovados), em português:
- `.spec/NEGOCIO.md`: regras de negócio R1–R11, escopo e fora de escopo.
- `.spec/ARQUITETURA.md`: decisões técnicas (esquema SQL, busca híbrida em SQL, chunking, loaders, CLI alvo).
- `.spec/ROADMAP.md`: features F01–F12, marcos e decisões pendentes.
- `.spec/features/_TEMPLATE.md`: modelo obrigatório de cada spec (`.spec/features/FNN-nome-curto.md`).

Regras do processo:
- Antes de implementar uma feature, a spec dela deve existir **e ter sido aprovada pelo usuário**. Implemente só o que a spec descreve. Se surgir algo novo, atualize a spec antes do código.
- Trabalhe **uma etapa por vez**: apresente o que foi feito e peça confirmação para a próxima.
- **Se houver dúvida, pergunte; não invente.** O que não foi decidido vai em "Pontos em aberto" da spec.
- **Não há testes automatizados** (sem pytest, sem `tests/`). A validação é um **roteiro de teste manual** na seção 9 de cada spec, com regressão manual na seção 10.
- Decisões já tomadas: só TXT e PDF com texto (sem OCR); duplicados (mesmo `sha256`) são ignorados; `data/index/` e `data/manual_colaborador.txt` **não são removidos**; interface só CLI (API/web e controle de acesso são futuros).
- Banco alvo: PostgreSQL 18.6 (Homebrew) com pgvector 0.8.7; banco `rag_training_db`, usuário `rag_user`. A senha fica **só no `.env`** (ignorado pelo Git), nunca em arquivos versionados.

Documentos e respostas ao usuário em português.
