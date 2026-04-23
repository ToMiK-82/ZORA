# scripts/test_ollama.py
"""
Тест Ollama клиента — с улучшенным стилем ответа
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from connectors.ollama_client import generate


def test_model():
    response = generate(
        prompt="Представься коротко",
        model="llama3.1:8b-instruct-q5_K_M",
        system=(
            "Ты — Зора, женского рода. Ты — ИИ-помощник предприятия. "
            "Говори от первого лица, используя женский род: «готова», «проверила», «рекомендую». "
            "Не называй себя 'он'. Не используй мужские формы. "
            "Отвечай кратко, по делу, вежливо, на русском языке."
        )
    )
    print("💬 Ответ модели:")
    print(response)

if __name__ == "__main__":
    test_model()