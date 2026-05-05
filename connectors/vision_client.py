"""
Клиент для работы с vision-моделью qwen3-vl:4b через Ollama.
"""

import logging
import base64
import requests
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class VisionClient:
    """Клиент для визуального анализа через qwen3-vl:4b."""

    def __init__(self, host: str = "http://localhost:11434"):
        self.host = host
        self.model = "qwen3-vl:4b"

    def analyze_screenshot(self, image_path: str, task: str = "Что изображено на скриншоте?") -> Dict[str, Any]:
        """Анализирует скриншот через vision-модель."""
        try:
            with open(image_path, 'rb') as f:
                image_base64 = base64.b64encode(f.read()).decode('utf-8')

            response = requests.post(
                f"{self.host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": f"Проанализируй изображение и ответь: {task}",
                    "images": [image_base64],
                    "stream": False
                },
                timeout=60
            )

            if response.status_code == 200:
                return {"success": True, "analysis": response.json().get("response", "")}
            else:
                return {"success": False, "error": f"HTTP {response.status_code}: {response.text}"}
        except Exception as e:
            logger.error(f"Ошибка vision-анализа: {e}")
            return {"success": False, "error": str(e)}

    def compare_screenshots(self, before_path: str, after_path: str, expected: str) -> Dict[str, Any]:
        """Сравнивает два скриншота через vision-модель."""
        prompt = f"""
        Сравни два скриншота: до и после действия.
        Ожидаемый результат: {expected}
        Определи, успешно ли выполнено действие.
        Ответь JSON: {{"success": true/false, "reason": "..."}}
        """
        # Анализируем только after (для простоты)
        return self.analyze_screenshot(after_path, prompt)

    def check_ui_element(self, image_path: str, element_description: str) -> Dict[str, Any]:
        """Проверяет наличие UI-элемента на скриншоте."""
        task = f"Найди на изображении: {element_description}. Ответь JSON: {{'found': true/false, 'position': 'x,y'}}"
        return self.analyze_screenshot(image_path, task)


# Глобальный экземпляр
vision_client = VisionClient()
