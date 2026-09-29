# Scripts de Utilitários

Pasta com scripts auxiliares para operações comuns na plataforma.

---

## `encrypt_credential.py` — Criptografar Credenciais com Fernet

Script para criptografar strings (senhas, tokens, etc.) usando Fernet com a chave do `.env`.

### Uso

```bash
python scripts/encrypt_credential.py "<string_para_criptografar>"
```

### Exemplos

**Criptografar uma senha de banco MySQL:**
```bash
python scripts/encrypt_credential.py "senha_super_secreta_123"
```

**Saída:**
```
[OK] Criptografia bem-sucedida!

Original:       senha_super_secreta_123
Criptografada:  gAAAAABquwPpMhfxgytX8pcXyocJmB-0BHQGYUPSEiC_3FRfbdyT6_jD8iMfXpv...

[*] Copie a string criptografada para usar em connection_config.password
    ou em qualquer lugar que precise de credencial cifrada.
```

### Quando Usar

Use este script para criptografar credenciais que serão armazenadas em `data_sources.connection_config`:

```json
{
  "host": "192.168.1.20",
  "port": 3306,
  "database": "vendas_db",
  "user": "readonly",
  "password": "gAAAAABquwPpMhfxgytX8pcXyocJmB-0BHQGYUPSEiC_3FRfbdyT6_jD8iMfXpv...",
  "sslmode": "prefer"
}
```

### Requisitos

- ✅ Arquivo `.env` com variável `FERNET_KEY` configurada
- ✅ Python 3.11+
- ✅ Dependências: `cryptography` (já em `requirements.txt`)

### Se FERNET_KEY Não Existe

Se o script falhar com "FERNET_KEY not found", você precisa gerar uma nova chave:

```python
from cryptography.fernet import Fernet
key = Fernet.generate_key()
print(key.decode())
# gAAAAABquwPpMhfxgytX8pcXyocJmB0BHQGYUPSEiC_3FRfbdyT6_jD8iMfXpv...
```

Copie a saída e adicione ao `.env`:
```
FERNET_KEY=gAAAAABquwPpMhfxgytX8pcXyocJmB0BHQGYUPSEiC_3FRfbdyT6_jD8iMfXpv...
```

---

## Versão

- **Última atualização:** 2026-09-28
- **Python:** 3.11+
- **Dependências:** `cryptography>=3.0`
