# ROADMAP — Ordem de implementação

Documentos relacionados: [NEGOCIO.md](NEGOCIO.md) (o quê e por quê) e [ARQUITETURA.md](ARQUITETURA.md) (como).
Cada feature terá sua especificação em `.spec/features/FNN-nome-curto.md` (ex.: `F05-cadastro-de-documento.md`), sempre criada a partir do template [features/_TEMPLATE.md](features/_TEMPLATE.md).

**Status:** roadmap **aprovado**. Nenhuma feature foi especificada ou implementada.

## Como trabalharemos (SDD)

Para cada feature, nesta ordem:
1. Copiar `.spec/features/_TEMPLATE.md` para `.spec/features/FNN-nome-curto.md` e preenchê-lo por inteiro (objetivo, escopo, regras de negócio, comportamento, interface, dados, configuração, roteiro de teste manual, impacto, riscos). Seção sem mudanças recebe "Sem mudanças", nunca fica em branco. Dúvidas vão em "Pontos em aberto", sem inventar.
2. **Você aprova a spec.**
3. Implementar apenas o que a spec descreve.
4. Executar o **roteiro de teste manual** da spec (seção 9), repetir os roteiros de regressão (seção 10) e registrar o resultado na seção 14 da spec.
5. Atualizar o status na spec e na tabela de status deste roadmap, e confirmar com você antes da próxima.

Se a implementação revelar algo novo, a spec é atualizada **antes** do código.

## Testes: somente manuais

Não haverá testes unitários nem automatizados. Cada spec terá um **roteiro de teste manual** na seção 9 do template (passos, comando e resultado esperado). Ao fechar uma feature, repetimos os roteiros das features anteriores que ela possa ter afetado. Detalhes na seção 14 da ARQUITETURA.

## Estratégia: fatia vertical primeiro

Em vez de construir cada camada inteira, o primeiro marco entrega o caminho completo mais simples (**cadastrar um arquivo e perguntar sobre ele**). Isso valida cedo as decisões de maior risco: PDF, Postgres, busca e resposta. Depois vêm pastas, reindexação, gestão e qualidade.

## Features

| ID | Feature | Objetivo | Regras de negócio | Depende de |
|---|---|---|---|---|
| F01 | **Ambiente e banco de dados** | Banco e usuário criados, extensão vetorial ativa, esquema aplicado, configuração por `.env`, verificação do ambiente. | — | — |
| F02 | **Leitura de documentos (TXT e PDF)** | Ler TXT e PDF página a página, rejeitar formatos não aceitos e PDF sem texto. | R7, R8 | — |
| F03 | **Divisão em trechos** | Dividir o texto em trechos que preservam seção e página; corrigir as falhas atuais do chunking. | R2 (base para citar página) | F02 |
| F04 | **Vetorização dos trechos** | Gerar os vetores de cada trecho e registrar o modelo usado; avisar se o modelo mudar sem reindexar. | — | F01 |
| F05 | **Cadastro de documento** | Gravar um documento e seus trechos no banco numa única transação, ignorar duplicados, tratar arquivos grandes com progresso. | R4, R9 | F01–F04 |
| F06 | **Busca de trechos** | Busca que combina significado e palavras exatas, com filtro opcional por pasta. | — | F05 |
| F07 | **Resposta com fontes** | Gerar a resposta só com os trechos recuperados, citar documento e página, e admitir quando não sabe. | R1, R2, R3, R11 | F06 |
| F08 | **Pastas e atualização incremental** | Cadastrar pastas, atualizar só o que mudou, tratar falhas isoladas, remover ausentes só sob pedido. | R5, R6, R7 | F05 |
| F09 | **Gestão da base** | Listar pastas e documentos, remover com confirmação. | R10 | F05, F08 |
| F10 | **CLI e menu interativo** | Comandos diretos e menu numerado que reúnem todas as operações. | — | F06–F09 |
| F11 | **Avaliação de qualidade** | Conjunto de perguntas de teste e métricas para comparar estratégias de divisão e definir parâmetros padrão (tamanho dos trechos, limiar de relevância). | Critérios da seção 6 do NEGOCIO | F06, F07 |
| F12 | **Limpeza e documentação final** | Remover os módulos antigos substituídos, manter `data/index/`, atualizar o `README.md`. | — | Todas |

### Observações sobre as features
- **Comandos da CLI nascem junto de cada feature** (por exemplo, `ingest` em F05 e `ask` em F07). F10 reúne tudo no menu e na interface final, sem reescrever a lógica.
- **F03 começa com a estratégia estruturada proposta** na ARQUITETURA, mas o tamanho e o padrão definitivos só se decidem em F11, com medição.
- **F08 e F09** separam o "trazer documentos" do "gerenciar a base", para a spec de cada uma ficar curta e verificável.

## Marcos

| Marco | Features | Resultado verificável |
|---|---|---|
| **M1 — Fatia vertical** | F01, F02, F03, F04, F05, F06, F07 | Cadastrar **um** TXT ou PDF e fazer perguntas com resposta, fonte e "não encontrei". |
| **M2 — Base completa** | F08, F09 | Várias pastas cadastradas, atualização incremental, listagem e remoção. |
| **M3 — Uso pela equipe** | F10, F11 | Menu completo e qualidade medida, com parâmetros padrão definidos. |
| **M4 — Encerramento** | F12 | Código legado removido e documentação atualizada. |

## Decisões pendentes que bloqueiam features

| Decisão | Bloqueia | Observação |
|---|---|---|
| **Busca por palavras em português e inglês.** A configuração textual atual do banco é só portuguesa. | F06 | Precisa ser resolvida e testada com documentos nos dois idiomas. |
| **Acesso simultâneo da equipe** (duas pessoas atualizando a mesma pasta ao mesmo tempo). | F05, F08 | Definir proteção contra atualização concorrente. |
| **Limites de tamanho de arquivo e de páginas.** | F05 | Podem ser definidos após medir o tempo real de cadastro em F05. |
| **Idioma da resposta** (acompanha a pergunta ou sempre português). | F07 | Ponto em aberto do NEGOCIO. |
| **Layout real dos PDFs** (colunas, tabelas, cabeçalhos repetidos). | F02, F03 | Exige amostras de PDFs reais. |

## Fora desta fase (evoluções futuras)

Ordem sugerida, a planejar depois de M4:
1. API e/ou interface web para acesso da equipe.
2. Controle de acesso por pessoa, grupo ou documento. Ao especificar F05 e F06, evitaremos decisões de esquema que dificultem isso depois.
3. Reconhecimento de texto em PDFs escaneados.
4. Outros formatos (Word, planilhas).

## Status das features

| ID | Spec | Implementação |
|---|---|---|
| F01 a F12 | Pendente | Pendente |
