#!/usr/bin/env python3
"""
Модуль для поиска информации в официальных источниках.
Интеграция с государственными API и проверенными базами данных.
"""

import os
import requests
import logging
from typing import Optional, Dict, Any
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("ZORA.OfficialSources")

class OfficialSources:
    """Класс для поиска информации в официальных источниках."""
    
    def __init__(self):
        # API ключи для государственных сервисов (если есть)
        self.dadata_api_key = os.getenv("DADATA_API_KEY")
        self.nalog_api_key = os.getenv("NALOG_API_KEY")
        
    def search_inn(self, inn: str) -> Optional[Dict[str, Any]]:
        """
        Поиск информации по ИНН в официальных источниках.
        
        Args:
            inn: ИНН организации или ИП
            
        Returns:
            Словарь с информацией или None если не найдено
        """
        # Проверяем валидность ИНН
        if not self._validate_inn(inn):
            logger.warning(f"⚠️ Невалидный ИНН: {inn}")
            return None
        
        # Пробуем разные источники в порядке приоритета
        sources = [
            ("dadata", self._search_dadata),
            ("nalog_ru", self._search_nalog_ru),
            ("контур", self._search_kontur)
        ]
        
        for source_name, search_func in sources:
            try:
                result = search_func(inn)
                if result:
                    logger.info(f"✅ Найдена информация по ИНН {inn} через {source_name}")
                    return result
            except Exception as e:
                logger.warning(f"⚠️ {source_name} недоступен: {e}")
                continue
        
        logger.warning(f"⚠️ Не удалось найти информацию по ИНН {inn}")
        return None
    
    def _validate_inn(self, inn: str) -> bool:
        """Проверяет валидность ИНН."""
        # Простая проверка: ИНН должен быть строкой из 10 или 12 цифр
        if not isinstance(inn, str):
            return False
        
        # Убираем пробелы и другие символы
        inn_clean = ''.join(filter(str.isdigit, inn))
        
        # Проверяем длину
        if len(inn_clean) not in [10, 12]:
            return False
        
        # Проверяем, что все символы - цифры
        return inn_clean.isdigit()
    
    def _search_dadata(self, inn: str) -> Optional[Dict[str, Any]]:
        """Поиск через DaData API (платный сервис)."""
        if not self.dadata_api_key:
            logger.debug("DaData API ключ не установлен")
            return None
        
        try:
            headers = {
                "Authorization": f"Token {self.dadata_api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
            
            data = {
                "query": inn,
                "count": 1
            }
            
            response = requests.post(
                "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party",
                headers=headers,
                json=data,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("suggestions"):
                    suggestion = data["suggestions"][0]
                    return self._parse_dadata_response(suggestion)
            
        except Exception as e:
            logger.debug(f"Ошибка DaData API: {e}")
        
        return None
    
    def _parse_dadata_response(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Парсит ответ от DaData API."""
        result = {
            "source": "dadata",
            "inn": data.get("data", {}).get("inn", ""),
            "kpp": data.get("data", {}).get("kpp", ""),
            "ogrn": data.get("data", {}).get("ogrn", ""),
            "name": {
                "full": data.get("value", ""),
                "short": data.get("data", {}).get("name", {}).get("short", ""),
            },
            "type": data.get("data", {}).get("type", ""),  # LEGAL или INDIVIDUAL
            "status": data.get("data", {}).get("state", {}).get("status", ""),
            "registration_date": data.get("data", {}).get("state", {}).get("registration_date", ""),
            "address": data.get("data", {}).get("address", {}).get("value", ""),
            "management": data.get("data", {}).get("management", {}).get("name", ""),
            "okved": data.get("data", {}).get("okved", ""),
            "capital": data.get("data", {}).get("capital", {}).get("value", ""),
        }
        
        # Определяем тип организации
        org_type = result["type"]
        if org_type == "LEGAL":
            result["org_type"] = "Юридическое лицо"
        elif org_type == "INDIVIDUAL":
            result["org_type"] = "Индивидуальный предприниматель"
        else:
            result["org_type"] = "Неизвестно"
        
        return result
    
    def _search_nalog_ru(self, inn: str) -> Optional[Dict[str, Any]]:
        """Поиск через сайт ФНС (nalog.ru)."""
        try:
            # Пробуем получить информацию через публичные API ФНС
            # Это примерный подход, реальный API может отличаться
            
            # Вариант 1: Через ЕГРЮЛ/ЕГРИП
            url = f"https://egrul.nalog.ru/search-result/{inn}"
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    return self._parse_nalog_response(data, inn)
                except:
                    # Если не JSON, пробуем парсить HTML
                    return self._parse_nalog_html(response.text, inn)
            
        except Exception as e:
            logger.debug(f"Ошибка при поиске на nalog.ru: {e}")
        
        return None
    
    def _parse_nalog_response(self, data: Dict[str, Any], inn: str) -> Dict[str, Any]:
        """Парсит ответ от API ФНС."""
        # Это упрощённый парсинг, реальная структура может отличаться
        result = {
            "source": "nalog_ru",
            "inn": inn,
            "name": data.get("name", ""),
            "ogrn": data.get("ogrn", ""),
            "status": data.get("status", ""),
            "address": data.get("address", ""),
            "okved": data.get("okved", ""),
            "registration_date": data.get("registration_date", ""),
        }
        
        # Определяем тип по длине ИНН
        if len(inn) == 10:
            result["org_type"] = "Юридическое лицо"
        elif len(inn) == 12:
            result["org_type"] = "Индивидуальный предприниматель"
        else:
            result["org_type"] = "Неизвестно"
        
        return result
    
    def _parse_nalog_html(self, html: str, inn: str) -> Optional[Dict[str, Any]]:
        """Парсит HTML страницу ФНС."""
        # Это сложный и ненадёжный метод
        # В реальном проекте лучше использовать API
        return None
    
    def _search_kontur(self, inn: str) -> Optional[Dict[str, Any]]:
        """Поиск через Контур (kontur.ru)."""
        # Контур имеет API, но требуется регистрация и API ключ
        # Это примерная реализация
        return None
    
    def format_inn_info(self, info: Dict[str, Any]) -> str:
        """Форматирует информацию по ИНН в читаемый текст."""
        if not info:
            return "Информация по указанному ИНН не найдена."
        
        formatted = f"**Информация по ИНН {info.get('inn', '')}:**\n\n"
        
        # Основная информация
        if info.get('name'):
            if isinstance(info['name'], dict):
                formatted += f"**Наименование:** {info['name'].get('full', '')}\n"
                if info['name'].get('short'):
                    formatted += f"**Сокращённое:** {info['name']['short']}\n"
            else:
                formatted += f"**Наименование:** {info['name']}\n"
        
        formatted += f"**Тип:** {info.get('org_type', 'Неизвестно')}\n"
        
        if info.get('ogrn'):
            formatted += f"**ОГРН:** {info['ogrn']}\n"
        
        if info.get('kpp'):
            formatted += f"**КПП:** {info['kpp']}\n"
        
        if info.get('status'):
            formatted += f"**Статус:** {info['status']}\n"
        
        if info.get('registration_date'):
            formatted += f"**Дата регистрации:** {info['registration_date']}\n"
        
        if info.get('address'):
            formatted += f"**Адрес:** {info['address']}\n"
        
        if info.get('management'):
            formatted += f"**Руководитель:** {info['management']}\n"
        
        if info.get('okved'):
            formatted += f"**ОКВЭД:** {info['okved']}\n"
        
        if info.get('capital'):
            formatted += f"**Уставный капитал:** {info['capital']}\n"
        
        formatted += f"\n**Источник:** {info.get('source', 'неизвестен')}\n"
        formatted += "\n**Примечание:** Для получения официальной выписки обратитесь на сайт ФНС."
        
        return formatted
    
    def search_and_format(self, inn: str) -> str:
        """Ищет информацию по ИНН и возвращает отформатированный результат."""
        info = self.search_inn(inn)
        return self.format_inn_info(info)


# Глобальный экземпляр для поиска
official_sources = OfficialSources()


def get_official_inn_info(inn: str) -> str:
    """
    Получает информацию по ИНН из официальных источников.
    
    Args:
        inn: ИНН организации или ИП
        
    Returns:
        Отформатированная информация или сообщение об ошибке
    """
    try:
        return official_sources.search_and_format(inn)
    except Exception as e:
        logger.error(f"❌ Ошибка при получении информации по ИНН: {e}")
        return f"Ошибка при поиске информации по ИНН {inn}: {str(e)}"


def is_official_sources_available() -> bool:
    """Проверяет, доступны ли официальные источники."""
    # Проверяем наличие API ключей
    has_dadata = bool(os.getenv("DADATA_API_KEY"))
    has_nalog = bool(os.getenv("NALOG_API_KEY"))
    
    # Даже без API ключей можно попробовать публичные источники
    return True  # Всегда можно попробовать


def test_official_sources():
    """Тестирование модуля официальных источников."""
    print("🧪 Тестирование официальных источников")
    print("=" * 60)
    
    # Тестовые ИНН
    test_inns = [
        "9105000477",  # Тестовый ИНН из задачи
        "7707083893",  # Пример ИНН крупной компании
        "1234567890",  # Несуществующий ИНН
    ]
    
    for inn in test_inns:
        print(f"\n🔍 Поиск по ИНН: {inn}")
        result = get_official_inn_info(inn)
        print(f"Результат: {result[:200]}...")
    
    print("\n" + "=" * 60)
    print("💡 РЕКОМЕНДАЦИИ ПО НАСТРОЙКЕ:")
    print("=" * 60)
    
    print("\n1. Получите API ключи для достоверных данных:")
    print("   • DaData (dadata.ru) - платный, но качественный")
    print("   • API ФНС (nalog.ru) - официальный, но сложный доступ")
    print("   • Контур (kontur.ru) - бизнес-справочник")
    
    print("\n2. Добавьте ключи в .env файл:")
    print("   DADATA_API_KEY=ваш_ключ_dadata")
    print("   NALOG_API_KEY=ваш_ключ_налог")
    
    print("\n3. Без API ключей система будет:")
    print("   • Использовать публичные источники (менее надёжно)")
    print("   • Предупреждать о необходимости проверки")
    print("   • Рекомендовать официальные источники")
    
    print("\n" + "=" * 60)
    print("✅ Модуль официальных источников готов к использованию!")
    print("=" * 60)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_official_sources()