# [F#] [Nome da Feature]

## Feature Spec Template

**ID:** F#
**Nome:** [Nome descritivo]
**Prioridade:** 🔴 Crítica / 🟠 Alta / 🟡 Média / 🟢 Baixa
**Esforço Estimado:** Xd (Xh)
**Status:** ⬜ Todo / 🟨 In Progress / 🟩 Done / 🟪 Blocked

---

## 1. Visão
[1-2 frases sobre o que a feature faz e por que é importante]

## 2. Objetivo
[O que você quer alcançar com essa feature?]

**Métrica de Sucesso:**
- ✅ Critério 1
- ✅ Critério 2

## 3. Contexto
**Depende de:** F# [Nome da feature anterior]
**É dependência de:** F# [Nome da feature que vem depois]

## 4. Descrição Técnica

### 4.1 Componentes Afetados
```
Componentes que serão criados/modificados:
├─ services/xxx_service.py (novo/modificado)
├─ repositories/xxx_repo.py (novo/modificado)
├─ schemas/xxx.py (novo/modificado)
└─ adapters/xxx_adapter.py (novo/modificado)
```

### 4.2 Fluxo de Dados
[Descreva o fluxo passo a passo. Use ASCII diagrams se necessário]

### 4.3 Banco de Dados
**Tabelas Novas / Modificações:**
```sql
CREATE TABLE xxx (...);
ALTER TABLE yyy ADD COLUMN zzz TYPE ...;
```

### 4.4 Endpoints/Interfaces
```python
async def xxx(self, param1: str, param2: int) -> XxxResult:
    """Descrição do que faz"""
    ...
```

## 5. Critérios de Aceitação
```gherkin
Feature: [Nome da Feature]

Scenario: [Caso de Uso 1]
  Given [Situação inicial]
  When [Ação]
  Then [Resultado esperado]

Scenario: [Caso de Erro]
  Given [Situação inicial]
  When [Ação que gera erro]
  Then [Erro tratado corretamente]
```

## 6. Testes

### 6.1 Testes Unitários
```python
class TestXxx:
    @pytest.mark.asyncio
    async def test_xxx_success(self):
        ...

    @pytest.mark.asyncio
    async def test_xxx_error_handling(self):
        ...
```

### 6.2 Checklist de Testes
- [ ] Teste unitário: caso de sucesso
- [ ] Teste unitário: validação de entrada
- [ ] Teste unitário: tratamento de erro
- [ ] Teste de integração: fluxo completo
- [ ] Manual: testar via pelo menos 1 cliente MCP real

## 7. Mudanças na Configuração
**Variáveis de Environment (.env):**
```
XXX_PARAM=value
```

## 8. Documentação
### 8.1 Como a feature aparece no MCP
### 8.2 Como o usuário usa essa feature
### 8.3 Como outros desenvolvedores estenderão isso

## 9. Checklist de Implementação
**Código:**
- [ ] Componentes implementados
- [ ] Code review completo
- [ ] Testes passing (100% dos casos)
- [ ] Docstrings

**QA:**
- [ ] Code review aprovado
- [ ] PR merge aprovado
