"""Script para criptografar strings com Fernet usando chave do .env.

Uso:
    python scripts/encrypt_credential.py "minha_senha_confidencial"
    python scripts/encrypt_credential.py "senha_banco_dados"

A chave Fernet deve estar em .env como FERNET_KEY.
"""

import sys
import os
import io

# Redirecionar stdout para UTF-8 no Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Adicionar parent directory ao path para importar security
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from security.crypto import encrypt_password


def main():
    if len(sys.argv) < 2:
        print("[!] Uso: python scripts/encrypt_credential.py '<string_para_criptografar>'")
        print("\nExemplo:")
        print("  python scripts/encrypt_credential.py 'minha_senha_secreta'")
        print("  python scripts/encrypt_credential.py 'senha_banco_dados'")
        sys.exit(1)

    credential = sys.argv[1]

    try:
        encrypted = encrypt_password(credential)
        print("\n[OK] Criptografia bem-sucedida!\n")
        print(f"Original:       {credential}")
        print(f"Criptografada:  {encrypted}")
        print("\n[*] Copie a string criptografada para usar em connection_config.password")
        print("    ou em qualquer lugar que precise de credencial cifrada.\n")
    except Exception as e:
        print(f"\n[ERRO] Falha ao criptografar: {e}")
        print("\nVerifique se:")
        print("  1. A variável FERNET_KEY está presente em .env")
        print("  2. A chave é válida (gerada com cryptography.fernet.Fernet.generate_key())")
        sys.exit(1)


if __name__ == "__main__":
    main()
