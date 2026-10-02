<!--
TEMPLATE DE FEATURE — copie para `.spec/features/FNN-nome-curto.md` (ex.: F05-cadastro-de-documento.md).
Apague os comentários ao preencher. Seja curto e verificável: se algo não puder ser conferido
em um teste manual, reescreva. Não invente: o que não foi decidido vai em "Pontos em aberto".
Fontes: regras em NEGOCIO.md, decisões técnicas em ARQUITETURA.md, ordem em ROADMAP.md.
-->

# FNN — Nome da feature

| Campo | Valor |
|---|---|
| **Status da spec** | Rascunho / Aprovada |
| **Status da implementação** | Pendente / Em andamento / Verificada |
| **Marco** | M1 / M2 / M3 / M4 (ver ROADMAP) |
| **Depende de** | Fxx, Fyy (ou "nenhuma") |
| **Regras de negócio** | Rx, Ry (de NEGOCIO.md) |
| **Seções da arquitetura** | Ex.: §4 Ingestão, §6 PostgreSQL |

## 1. Objetivo
<!-- Uma ou duas frases: o que a pessoa passa a conseguir fazer, e por quê. -->

## 2. Escopo

**Inclui**
-

**Não inclui** (fica para outra feature ou fora de escopo)
-

## 3. Regras de negócio aplicáveis
<!-- Repita aqui o texto das regras (R1…R11) que esta feature precisa cumprir, e acrescente regras novas, se surgirem. -->

| Regra | O que significa nesta feature |
|---|---|
| Rx | |

## 4. Comportamento esperado

### 4.1 Fluxo principal
<!-- Passo a passo do ponto de vista de quem usa. -->
1.

### 4.2 Fluxos alternativos e erros
<!-- Cada caso de borda com o que a aplicação faz e a mensagem mostrada à pessoa. -->

| Situação | Comportamento esperado | Mensagem / saída |
|---|---|---|
| | | |

### 4.3 Saída para a pessoa
<!-- Exemplo literal do que aparece no terminal (resumo, progresso, tabela, fontes). -->
```
```

## 5. Interface

**Comandos / opções da CLI** (e item de menu, se houver)

| Comando | Argumentos e opções | Descrição |
|---|---|---|
| | | |

**Módulos e funções** (assinaturas principais, entradas e saídas)

| Arquivo | Responsabilidade | Funções / classes |
|---|---|---|
| `src/…` | | |

## 6. Dados
<!-- Tabelas, colunas, índices e migrações que a feature cria ou altera (SQL real quando existir). Se não houver, escreva "Sem mudanças". -->

## 7. Configuração
<!-- Variáveis de `.env`, parâmetros padrão e limites (com os valores), ou "Sem mudanças". -->

| Parâmetro | Padrão | Onde se define |
|---|---|---|
| | | |

## 8. Dependências externas
<!-- Pacotes novos em requirements.txt, serviços, extensões do banco, arquivos de exemplo necessários. -->

## 9. Critérios de aceite — roteiro de teste manual
<!--
Não há testes automatizados (ARQUITETURA §14). Este roteiro É o teste.
Cada linha: passo repetível, comando exato e resultado observável. Inclua caminho feliz, erros e borda.
Informe os dados de teste necessários (arquivo, pasta, estado do banco).
-->

**Pré-condições:**
-

| # | Passo | Comando / ação | Resultado esperado |
|---|---|---|---|
| 1 | | | |

**Consultas úteis para conferir o banco** (se aplicável)
```sql
```

## 10. Impacto em outras features
<!-- O que esta feature pode quebrar. Liste os roteiros de outras features a repetir ao concluir (regressão manual). -->

| Feature | Roteiros a repetir (#) | Motivo |
|---|---|---|
| | | |

## 11. Riscos e decisões
**Decisões tomadas** (com o motivo)
-

**Pontos em aberto** (precisam de resposta antes de implementar)
-

## 12. Documentação a atualizar
<!-- Ex.: README.md, ARQUITETURA.md, .env.example, ROADMAP (status). -->
-

## 13. Definição de pronto
- [ ] Spec aprovada pela pessoa responsável
- [ ] Código implementado somente no que a spec descreve
- [ ] Todos os passos do roteiro (seção 9) executados e aprovados
- [ ] Roteiros de regressão (seção 10) repetidos
- [ ] Documentação da seção 12 atualizada
- [ ] Status atualizado nesta spec e no ROADMAP

## 14. Registro de verificação
<!-- Preenchido ao executar o roteiro manual. -->

| Data | Quem executou | Resultado | Observações / falhas encontradas |
|---|---|---|---|
| | | | |
