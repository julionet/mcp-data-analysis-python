# NEGÓCIO — Assistente de consulta a documentos

> Este documento descreve **o que** a aplicação faz e **por quê**, sem detalhes técnicos. Os detalhes técnicos estão em [ARQUITETURA.md](ARQUITETURA.md).

## 1. Problema

A equipe tem muitos documentos (manuais, políticas, material técnico), espalhados em pastas, em formato texto e PDF. Encontrar uma informação específica exige abrir arquivos e ler. Nem sempre se sabe em qual documento está a resposta.

## 2. Solução

Uma aplicação em que a pessoa **faz uma pergunta em linguagem natural** e recebe uma **resposta direta, com a indicação de onde a informação foi encontrada** (documento e página). A resposta se baseia **somente** no conteúdo dos documentos cadastrados.

## 3. Usuários

- **Uma equipe pequena**, que consulta a mesma base de documentos.
- Todos os integrantes podem ver todos os documentos. Não há restrição por pessoa ou grupo nesta fase (ver seção 9).
- Alguém da equipe também cuida da base: adiciona pastas e atualiza os documentos.

## 4. Escopo desta fase

### O que a aplicação faz

1. **Cadastrar documentos** em formato **TXT** e **PDF**, informando uma ou mais pastas, uma de cada vez.
2. **Atualizar a base** de uma pasta quando os documentos mudam, trazendo só o que é novo ou foi alterado.
3. **Consultar** todos os documentos cadastrados de uma vez, ou limitar a consulta a uma pasta.
4. **Responder com fontes**: cada resposta indica o documento e a página de onde veio.
5. **Admitir quando não sabe**: se os documentos não trazem a informação, a aplicação diz isso e não inventa.
6. **Gerenciar a base**: ver quais pastas e documentos estão cadastrados e remover o que não for mais necessário.

### Tipos de documento e idioma

- Aceitos: **TXT** e **PDF com texto selecionável**.
- O conteúdo é **misto**: não há um tipo ou tema único de documento.
- Documentos e perguntas podem estar em **português e em inglês**.
- Tamanho: a base deve comportar **centenas de arquivos**, incluindo PDFs grandes.

## 5. Regras de negócio

- **R1.** A resposta usa **apenas** o que está nos documentos. Conhecimento externo não entra.
- **R2.** Toda resposta com informação indica a **fonte** (documento e página).
- **R3.** Se não houver informação suficiente, a resposta diz exatamente que não encontrou, sem tentar adivinhar.
- **R4.** O **mesmo conteúdo não é cadastrado duas vezes**. Se um arquivo igual existir em outro lugar, ele é ignorado e o resumo informa de qual arquivo ele é cópia.
- **R5.** Atualizar uma pasta **não refaz tudo**: arquivo novo é incluído, arquivo alterado substitui a versão anterior, arquivo igual é mantido.
- **R6.** Um arquivo que foi apagado da pasta **só sai da base se a pessoa pedir** explicitamente.
- **R7.** Um arquivo com problema (corrompido, sem texto, formato não aceito) **não interrompe** o cadastro dos demais. No final, a pessoa recebe um resumo do que deu certo e do que falhou, com o motivo.
- **R8.** PDF sem texto selecionável (por exemplo, escaneado) **não é aceito**, e a pessoa é avisada.
- **R9.** Um documento só aparece nas consultas depois de **cadastrado por completo**. Um cadastro interrompido não deixa resultados pela metade.
- **R10.** Antes de **remover** documentos ou pastas, a aplicação pede confirmação.
- **R11.** Os trechos usados para responder são enviados a um serviço externo de inteligência artificial (Claude). Isso é aceito para os documentos desta base, que não têm restrição de confidencialidade para esse fim.

## 6. Como medir o sucesso

| Critério | Como se verifica |
|---|---|
| Respostas corretas, com fonte | Perguntas de teste sobre documentos conhecidos devolvem a informação certa e apontam o documento e a página certos. |
| Admite quando não sabe | Perguntas sobre assuntos que **não** estão nos documentos recebem a resposta de "não encontrei", e não uma invenção. |
| Base sempre atualizada | Depois de alterar, incluir ou apagar arquivos, atualizar a pasta reflete a mudança sem refazer a base inteira. |

O tempo de cadastro de arquivos grandes **não foi definido como critério de sucesso** nesta fase. Ele será acompanhado, mas sem meta fixa.

## 7. Fluxos principais

**Cadastrar e atualizar**
1. A pessoa informa uma pasta.
2. A aplicação lê os arquivos TXT e PDF, ignora duplicados e informa o que fez com cada um.
3. Quando os documentos mudam, a pessoa atualiza a pasta e só o necessário é refeito.
4. Pode repetir o processo com outras pastas, e todas passam a compor a mesma base.

**Perguntar**
1. A pessoa escreve a pergunta, em português ou inglês.
2. A aplicação procura os trechos mais relevantes em todos os documentos (ou só na pasta escolhida).
3. Devolve a resposta com as fontes, ou diz que não encontrou.

## 8. Fora de escopo nesta fase

- Outros formatos além de TXT e PDF (Word, planilhas, páginas web, imagens).
- PDFs escaneados (que exigem reconhecimento de texto em imagem).
- Edição ou criação de documentos pela aplicação.
- Controle de acesso por pessoa, grupo ou documento.
- Interface web e acesso por API.
- Histórico de conversas entre sessões.

## 9. Evoluções futuras (roadmap de negócio)

Registradas para planejamento posterior, **não** fazem parte desta fase:

1. **Acesso pela equipe via API e/ou interface web**, para que as pessoas consultem sem usar linha de comando.
2. **Controle de acesso**: documentos visíveis apenas para pessoas ou grupos autorizados. Hoje todos veem tudo.
3. Reconhecimento de texto em PDFs escaneados.
4. Outros formatos além de TXT e PDF (Word, planilhas).

## 10. Pontos em aberto

- Quantas pessoas consultam ao mesmo tempo, e se precisam de histórico de perguntas.
- Meta de tempo para cadastrar arquivos grandes, se vier a ser necessária.
- Limites de tamanho de arquivo aceitos.
- Se o idioma da resposta deve acompanhar o da pergunta ou ser sempre português.
