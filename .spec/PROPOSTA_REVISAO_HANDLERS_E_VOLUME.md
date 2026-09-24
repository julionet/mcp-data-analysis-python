# 📝 Proposta de Revisão — Remoção da Camada de Handlers + Controle de Volume de Dados

**Status:** 🟢 Decisões validadas por Jose (exceto item pendente na §7, item 5) — pronto para aplicar aos documentos oficiais
**Data:** 2026-09-23 (atualizado)
**Origem:** Discussão em chat sobre gap entre "servidor processa a análise via Handlers Python" (documentado) vs. "servidor entrega dado bruto e o LLM cliente faz a análise" (modelo desejado por Jose)
**Próximo passo:** Resolver o item pendente da §7 (tabela `custom_handlers`) e então aplicar as mudanças formalmente em NEGOCIO.md / ARQUITETURA.md / FEATURES_ROADMAP.md, bump de versão em cada um.

---

## 1. Resumo Executivo

A arquitetura documentada (v1.4-1.8) presumia que o **servidor** faria as transformações de dados (agregação, filtro, detecção de anomalia, forecast) via **Handlers Python**, catalogados e descobertos por um `HandlerRegistry` (F3), e devolveria ao cliente MCP um resultado **já pronto**.

Na prática, isso não escala: o espaço de perguntas de análise que um usuário pode fazer é infinito (ex.: "tendência de vendas", "sazonalidade", "correlação entre X e Y") — não é viável pré-programar um handler para cada tipo de análise possível.

**Decisão proposta:** o servidor deixa de "analisar" os dados. Ele só executa a query parametrizada e devolve o **dataset bruto** (JSON) para o cliente MCP. É o **LLM do lado do cliente** (Claude Desktop, Gemini Desktop, etc.) quem interpreta, calcula, agrega, e até gera gráfico — a cada pedido, livremente, sem precisar de handler nenhum.

Para viabilizar isso sem quebrar o cliente com volumes grandes de dados (ex.: 10.000 linhas ≈ centenas de milhares de tokens), o servidor passa a ter uma **camada de controle de volume**: se o resultado estimado excede um limite configurável, o servidor recusa a execução e devolve uma mensagem estruturada pedindo refinamento — ou, se o cliente confirmar explicitamente que aceita o custo de tokens, executa mesmo assim.

---

## 2. O Que Muda — Por Documento

### 2.1 NEGOCIO.md

| Seção | Hoje (v1.5) | Proposta |
|---|---|---|
| RF2 (Execução de Análises) | "Aplica transformações (handlers Python)" | Remove essa linha. Adiciona: "Estima volume do resultado; se exceder limite configurável, recusa com mensagem de refinamento (ou exige confirmação explícita de aceite de custo alto de tokens)" |
| RF4 (Handlers Customizados) | Seção inteira dedicada a handlers de negócio (anomaly_detection etc.) | **Removida.** Não há mais handler de negócio — análise é sempre "busca dado bruto parametrizado". |
| UC2 (Executar Análise) | "Retorna resultado em < 30s" (implícito: resultado já processado) | Ajusta linguagem: "retorna dataset bruto em < 30s (sujeito a limite de volume)" |
| UC4 (Adicionar Handler Customizado) | Caso de uso completo sobre handler de anomalia | **Removido** (não existe mais handler para adicionar) |
| RNF1 (Performance) | — | Adiciona: tempo de resposta do `COUNT(*)` de pré-checagem de volume (rápido, < 500ms esperado) |
| Objetivo O1 | "Zero código novo por mês" via handler reutilizável | Mantém o espírito, mas a "reutilização" agora é 100% no SQL da análise (via `analysis_steps`), não em Python |

### 2.2 ARQUITETURA.md

| Seção | Hoje | Proposta |
|---|---|---|
| §2.1 Diagrama de Componentes | `HandlerRegistry`, pasta `handlers/` (built-in + custom) | **Removidos** do diagrama de componentes |
| §3.2 Fluxo de Execução | STEP 1 (query) → STEP 2 (transform, via Handler) → STEP N | Simplifica para: STEP 1 (query) → checagem de volume → retorno. Não há mais STEP tipo `transform` |
| §4.3 Registry Pattern (Handlers) | Código completo do `HandlerRegistry` | **Removido** |
| §5.2 Estrutura de Pastas | `handlers/`, `repositories/handler_repo.py` | **Removidos** da estrutura |
| §6.1 Startup | "3. Initialize HandlerRegistry" | **Removido** do fluxo de startup |
| Tabela `custom_handlers` (§2.2) | Tabela dedicada a handlers | **Removida** do schema (ou mantida sem uso, para não gerar migration destrutiva — decisão em aberto, ver §4) |
| Tabela `analyses` (§2.2) | Sem campo de limite de volume | Nenhuma mudança de schema necessária aqui — limites de volume (linhas e KB) são 100% globais via `.env` (ver §3.3, decidido) |
| Nova seção | — | Adiciona nova seção descrevendo o mecanismo de controle de volume (ver §3 deste documento) |

### 2.3 FEATURES_ROADMAP.md

| Feature | Hoje | Proposta |
|---|---|---|
| **F3** (HandlerRegistry e Discovery) | Crítica, 2d, depende de F2 | **Removida** do Sprint 1 (ou substituída — ver F3-novo abaixo) |
| **F3-novo** (sugestão) | — | "Controle de Volume de Resultado" — Crítica, ~1d, depende de F2. Implementa: pré-checagem via `COUNT(*)`, checagem de tamanho serializado, resposta estruturada de recusa/confirmação. |
| **F4** (Analysis Execution Engine) | Depende de F2, F3 (handlers) | Passa a depender só de F2 e do novo F3 (volume). Remove qualquer menção a "aplicar handler" no fluxo de execução |
| **F14** (Built-in Handlers) — Sprint 2 | aggregation, filtering, normalization, temporal | **Removida inteiramente** do roadmap |
| Renumeração | F4-F24 | Como F14 sai, tudo depois dela desloca -1 (mesma lógica já usada em revisões anteriores do próprio roadmap) |
| Total geral do projeto | 24 features, ~33 dias | Recalcular: -1 feature (F14), esforço de F3 cai de 2d para ~1d → redução líquida estimada de ~3 dias |

---

## 3. Mecanismo Proposto — Controle de Volume de Dados

### 3.1 Fluxo em duas camadas — ✅ Confirmado por Jose

```
1. Cliente MCP chama execute_analysis(id, params)
2. Servidor roda um SELECT COUNT(*) barato com os mesmos filtros da query real
   ├─ Se count > limite_de_linhas (configurável) → RECUSA (ver 3.2), sem nunca buscar os dados completos
   └─ Se count <= limite_de_linhas → segue para o passo 3
3. Servidor executa a query completa, serializa o resultado em JSON
   └─ Confere o tamanho real em KB como segunda checagem de segurança
       (o count de linhas pode não refletir o tamanho real se as colunas forem muito largas)
4. Se dentro do limite: devolve o dataset bruto normalmente
5. Se checagem de KB falhar mesmo com count baixo: RECUSA (mesma mensagem do passo 2)
```

### 3.2 Formato da recusa (parâmetro de confirmação)

Toda análise aceita, implicitamente, um parâmetro reservado adicional (não precisa ser cadastrado em `analyses.parameters` — é global, injetado pelo servidor no schema de toda tool):

```json
{
  "confirmar_volume_alto": {
    "type": "boolean",
    "required": false,
    "default": false,
    "description": "Confirma execução mesmo que o resultado seja grande (maior consumo de tokens)"
  }
}
```

**Resposta quando o volume excede o limite e `confirmar_volume_alto=false` (default):**
```json
{
  "status": "volume_exceeded",
  "estimativa": {
    "linhas": 8400,
    "tamanho_estimado_kb": 510
  },
  "limite": {
    "linhas": 500,
    "tamanho_kb": 150
  },
  "mensagem": "Sua consulta retornaria aproximadamente 8.400 linhas (~510KB), acima do limite de 500 linhas / 150KB. Refine o período ou adicione filtros (ex: região, produto). Se quiser continuar mesmo assim, chame novamente com confirmar_volume_alto=true — atenção: isso pode consumir um volume alto de tokens."
}
```

Se o cliente (a pedido do usuário) chamar de novo com `confirmar_volume_alto=true`, o servidor **ignora o limite** e devolve o dataset completo, incluindo um aviso no payload (`"aviso": "resultado grande, enviado por confirmação explícita"`).

### 3.3 Configuração dos limites — ✅ Decidido: 100% via `.env`, sem override por análise

```
# .env
DEFAULT_MAX_RESULT_ROWS=500
DEFAULT_MAX_RESULT_SIZE_KB=150
```

Confirmado por Jose: ambos os limites (linhas e KB) são globais, configurados só no `.env`. Não há override por análise — portanto **não é necessária** nenhuma coluna nova em `analyses` para isso.

---

## 4. Formato Proposto — `analyses.parameters`

```json
{
  "<nome_parametro>": {
    "type": "string | integer | number | boolean | date | datetime",
    "required": true,
    "description": "Texto que explica o parâmetro — usado pelo LLM pra saber o que perguntar ao usuário",
    "default": null,
    "enum": ["valor1", "valor2"],
    "min": null,
    "max": null
  }
}
```

**Exemplo real (`vendas_por_regiao`):**
```json
{
  "data_inicial": {
    "type": "date",
    "required": true,
    "description": "Data inicial do período de vendas (YYYY-MM-DD)"
  },
  "data_final": {
    "type": "date",
    "required": true,
    "description": "Data final do período de vendas (YYYY-MM-DD)"
  },
  "regiao": {
    "type": "string",
    "required": false,
    "description": "Filtrar por uma região específica",
    "enum": ["Norte", "Sul", "Leste", "Oeste", "Centro"]
  }
}
```

---

## 5. Lógica de Conversão `parameters` → JSON Schema MCP

Novo módulo compartilhado (usado tanto por F5 quanto pelo Execution Engine):

```
schemas/
└── analysis_parameters.py   # novo
    ├─ to_json_schema(parameters: dict) -> dict
    │     # usado por F5 (list_tools) — gera o inputSchema padrão MCP
    └─ to_pydantic_model(parameters: dict) -> Type[BaseModel]
          # usado pelo Execution Engine (F4) — valida antes de executar,
          # mesma fonte de verdade dos tipos, sem duplicar regras
```

Mapeamento de tipos (`type` interno → JSON Schema):

| `type` (interno) | JSON Schema `type` | JSON Schema `format` |
|---|---|---|
| string | string | — |
| integer | integer | — |
| number | number | — |
| boolean | boolean | — |
| date | string | date |
| datetime | string | date-time |

---

## 6. Connection String — Sem Gap, Já Documentado

Não é uma mudança — apenas fechando o formato que já existe em `data_sources.connection_config` (ARQUITETURA.md §2.2, Tabela 1), hoje um placeholder (`{host, port, database, ...}`):

```json
{
  "host": "192.168.1.10",
  "port": 5432,
  "database": "vendas_db",
  "user": "readonly_user",
  "password": "***",
  "sslmode": "prefer"
}
```

NEGOCIO.md §8.2 já exige criptografia em repouso desse campo — **decidido: usar Fernet (biblioteca `cryptography` do Python)** para cifrar o campo `password` (e demais credenciais sensíveis) dentro de `connection_config` antes de persistir.

---

## 7. Pontos em Aberto — Status Atualizado

1. ✅ **Cadastro manual confirmado** — V1.0 é 100% `INSERT` manual no banco (sem tooling/admin UI).
2. ✅ **Limites de linhas e KB** — decidido: ambos 100% globais via `.env`, sem override por análise. Nenhuma coluna nova em `analyses`.
3. ✅ **Mecanismo de criptografia** — decidido: Fernet (biblioteca `cryptography` do Python) para `connection_config.password` e demais credenciais.
4. ✅ **`analysis_steps.step_type`** — decidido: mantém a tabela como está (permite múltiplas queries por análise), mesmo que só o tipo `query` continue em uso.
5. ⬜ **Ainda em aberto — Tabela `custom_handlers`**: remove do schema físico (migration destrutiva) ou mantém a tabela sem uso, para não gerar DROP TABLE em produção depois? *(Não foi respondida ainda — preciso da decisão do Jose antes de aplicar a mudança de schema em ARQUITETURA.md §2.2.)*
6. ✅ **Confirmação do fluxo de "volume alto"** — decidido: usar o parâmetro reservado `confirmar_volume_alto`, conforme §3.2.

---

## 8. Impacto no F3 Especificamente

O F3 original ("HandlerRegistry e Discovery") deixa de existir como estava. Nesta proposta, ele é **substituído** por uma feature bem mais estreita — algo como:

> **F3 (novo): Controle de Volume de Resultado**
> Implementa a pré-checagem de `COUNT(*)`, a checagem de tamanho serializado, e a resposta estruturada de recusa/confirmação descritas na §3 deste documento. Sem Registry Pattern, sem discovery de filesystem/banco, sem classes de handler — é uma validação dentro do próprio Execution Engine (ou um serviço leve, `services/volume_guard_service.py`).

---

**Fim da proposta. Decisões da §7 validadas por Jose, exceto o item 5 (tabela `custom_handlers`) — resolver esse ponto e então aplicar as mudanças formalmente em NEGOCIO.md, ARQUITETURA.md e FEATURES_ROADMAP.md.**
