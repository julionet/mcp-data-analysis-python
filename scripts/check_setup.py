import anthropic
from sentence_transformers import SentenceTransformer, util

from src.config import ANTHROPIC_API_KEY, LLM_MODEL, EMBEDDING_MODEL, HF_TOKEN


def check_claude():
    if not ANTHROPIC_API_KEY:
        print("[Claude] ANTHROPIC_API_KEY não encontrada no .env")
        return
    
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=LLM_MODEL,
        max_tokens=50,
        messages=[{"role": "user", "content": "Responda apenas: OK"}],
    )
    print(f"[Claude] OK -> {response.content[0].text.strip()}")

def check_embeddings():
    print(f"[Embeddings] Carregando '{EMBEDDING_MODEL}' (o primeiro uso baixa o modelo)...")
    model = SentenceTransformer(EMBEDDING_MODEL, token=HF_TOKEN)
    print(f"[Embeddings] Dispositivo em uso: {model.device}")

    frases = [
        "O carro está na garagem.",
        "O automóvel está estacionado na garagem de casa.",
        "A receita de bolo leva três ovos.",
    ]
    vetores = model.encode(frases, normalize_embeddings=True)

    print(f"[Embeddings] OK -> vetor com {vetores.shape[1]} dimensões")
    print(f"[Embeddings] primeiros 5 valores: {vetores[0][:5]}")

    sim_parecidas = util.cos_sim(vetores[0], vetores[1]).item()
    sim_diferentes = util.cos_sim(vetores[0], vetores[2]).item()
    print(f"[Similaridade] carro vs automóvel: {sim_parecidas:.3f}")
    print(f"[Similaridade] carro vs bolo:      {sim_diferentes:.3f}")

if __name__ == "__main__":
    check_claude()
    check_embeddings()
