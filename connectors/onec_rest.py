"""
REST-клиент для интеграции с 1С через OData API.
Поддерживает автоматический REST сервис 1С.
"""

import os
import logging
import requests
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

logger = logging.getLogger("zora.connector.1c.rest")

# Конфигурация из переменных окружения
ONEC_API_URL = os.getenv("ONEC_API_URL", "http://localhost:8080/1c/ws/odata/standard.odata/")
ONEC_API_USER = os.getenv("ONEC_API_USER", "ZORA")
ONEC_API_PASSWORD = os.getenv("ONEC_API_PASSWORD", "Globus")


class OneCRestClient:
    """Клиент для работы с 1С через REST API (OData)."""
    
    def __init__(self, base_url: Optional[str] = None, username: Optional[str] = None, 
                 password: Optional[str] = None):
        """
        Инициализация REST-клиента для 1С.
        
        Args:
            base_url: Базовый URL API 1С (например, http://server:port/1c/ws/odata/standard.odata/)
            username: Имя пользователя для аутентификации
            password: Пароль для аутентификации
        """
        self.base_url = base_url or ONEC_API_URL
        self.username = username or ONEC_API_USER
        self.password = password or ONEC_API_PASSWORD
        
        # Убедимся, что URL заканчивается на /
        if not self.base_url.endswith('/'):
            self.base_url += '/'
            
        self.session = requests.Session()
        self.session.auth = (self.username, self.password)
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
        
        logger.info(f"Инициализирован REST-клиент 1С: {self.base_url}")
        
    def test_connection(self) -> bool:
        """
        Проверка подключения к API 1С.
        
        Returns:
            True если подключение успешно, False в противном случае
        """
        try:
            # Пробуем получить метаданные OData
            response = self.session.get(f"{self.base_url}$metadata", timeout=10)
            if response.status_code == 200:
                logger.info("Подключение к 1С REST API успешно")
                return True
            else:
                logger.warning(f"Ошибка подключения к 1С: статус {response.status_code}")
                return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка подключения к 1С REST API: {e}")
            return False
    
    def get_entities(self) -> List[str]:
        """
        Получение списка доступных сущностей (таблиц) в 1С.
        
        Returns:
            Список имен сущностей
        """
        try:
            response = self.session.get(self.base_url, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # OData сервис возвращает список сущностей в формате {"value": [...]}
            if "value" in data:
                entities = []
                for item in data["value"]:
                    if "name" in item:
                        entities.append(item["name"])
                    elif "url" in item:
                        # Извлекаем имя сущности из URL
                        url = item["url"]
                        if url.startswith(self.base_url):
                            entity_name = url[len(self.base_url):].split('(')[0]
                            entities.append(entity_name)
                return entities
            return []
        except Exception as e:
            logger.error(f"Ошибка получения списка сущностей 1С: {e}")
            return []
    
    def query_entity(self, entity_name: str, filters: Optional[Dict] = None, 
                    top: Optional[int] = None, skip: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Выполнение запроса к сущности 1С.
        
        Args:
            entity_name: Имя сущности (например, "Справочник.Контрагенты")
            filters: Словарь фильтров {поле: значение}
            top: Количество записей для возврата
            skip: Количество записей для пропуска
            
        Returns:
            Список записей сущности
        """
        try:
            url = f"{self.base_url}{entity_name}"
            
            # Добавляем параметры запроса
            params = {}
            if filters:
                # Простая реализация фильтров - можно расширить для сложных условий
                filter_parts = []
                for key, value in filters.items():
                    if isinstance(value, str):
                        filter_parts.append(f"{key} eq '{value}'")
                    else:
                        filter_parts.append(f"{key} eq {value}")
                if filter_parts:
                    params['$filter'] = ' and '.join(filter_parts)
            
            if top:
                params['$top'] = top
            if skip:
                params['$skip'] = skip
            
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if "value" in data:
                return data["value"]
            else:
                logger.warning(f"Неожиданный формат ответа от 1С для сущности {entity_name}")
                return []
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка запроса к сущности {entity_name}: {e}")
            return []
        except Exception as e:
            logger.error(f"Неожиданная ошибка при запросе к {entity_name}: {e}")
            return []
    
    def get_document(self, document_type: str, document_id: str) -> Optional[Dict[str, Any]]:
        """
        Получение документа по ID.
        
        Args:
            document_type: Тип документа (например, "Документ.СчетНаОплату")
            document_id: ID документа
            
        Returns:
            Данные документа или None если не найден
        """
        try:
            url = f"{self.base_url}{document_type}({document_id})"
            response = self.session.get(url, timeout=30)
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                logger.warning(f"Документ {document_type} с ID {document_id} не найден")
                return None
            else:
                response.raise_for_status()
                return None
                
        except Exception as e:
            logger.error(f"Ошибка получения документа {document_type}({document_id}): {e}")
            return None
    
    def create_document(self, document_type: str, data: Dict[str, Any]) -> Optional[str]:
        """
        Создание нового документа.
        
        Args:
            document_type: Тип документа
            data: Данные документа
            
        Returns:
            ID созданного документа или None при ошибке
        """
        try:
            url = f"{self.base_url}{document_type}"
            response = self.session.post(url, json=data, timeout=30)
            response.raise_for_status()
            
            # В ответе может быть Location header с URL созданного документа
            if 'Location' in response.headers:
                location = response.headers['Location']
                # Извлекаем ID из URL
                import re
                match = re.search(r'\((.*?)\)', location)
                if match:
                    return match.group(1)
            
            # Или ID может быть в теле ответа
            response_data = response.json()
            if 'Ref_Key' in response_data:
                return response_data['Ref_Key']
            elif 'Id' in response_data:
                return response_data['Id']
            else:
                logger.warning(f"Не удалось извлечь ID созданного документа из ответа: {response_data}")
                return "unknown_id"
                
        except Exception as e:
            logger.error(f"Ошибка создания документа {document_type}: {e}")
            return None
    
    def update_document(self, document_type: str, document_id: str, data: Dict[str, Any]) -> bool:
        """
        Обновление существующего документа.
        
        Args:
            document_type: Тип документа
            document_id: ID документа
            data: Данные для обновления
            
        Returns:
            True если успешно, False если ошибка
        """
        try:
            url = f"{self.base_url}{document_type}({document_id})"
            response = self.session.patch(url, json=data, timeout=30)
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Ошибка обновления документа {document_type}({document_id}): {e}")
            return False
    
    def get_accounting_data(self, period_start: str, period_end: str) -> Dict[str, Any]:
        """
        Получение бухгалтерских данных за период.
        
        Args:
            period_start: Начало периода (YYYY-MM-DD)
            period_end: Конец периода (YYYY-MM-DD)
            
        Returns:
            Бухгалтерские данные
        """
        try:
            # Пример запроса к отчету "Оборотно-сальдовая ведомость"
            # Конкретная реализация зависит от структуры вашей 1С
            params = {
                'StartPeriod': period_start,
                'EndPeriod': period_end,
                '$format': 'json'
            }
            
            # Пробуем разные возможные имена отчетов
            report_names = [
                "ОборотноСальдоваяВедомость",
                "ОборотноСальдоваяВедомость_Выборка",
                "AccumulationRegister.Обороты"
            ]
            
            for report_name in report_names:
                url = f"{self.base_url}{report_name}"
                response = self.session.get(url, params=params, timeout=30)
                if response.status_code == 200:
                    data = response.json()
                    return self._parse_accounting_data(data, period_start, period_end)
            
            logger.warning(f"Не удалось получить бухгалтерские данные для периода {period_start} - {period_end}")
            return {
                "period": f"{period_start} - {period_end}",
                "income": 0.0,
                "expenses": 0.0,
                "profit": 0.0,
                "taxes": 0.0,
                "status": "not_found"
            }
            
        except Exception as e:
            logger.error(f"Ошибка получения бухгалтерских данных: {e}")
            return {
                "period": f"{period_start} - {period_end}",
                "income": 0.0,
                "expenses": 0.0,
                "profit": 0.0,
                "taxes": 0.0,
                "status": "error",
                "error": str(e)
            }
    
    def _parse_accounting_data(self, data: Dict, period_start: str, period_end: str) -> Dict[str, Any]:
        """
        Парсинг бухгалтерских данных из ответа 1С.
        
        Args:
            data: Данные от 1С
            period_start: Начало периода
            period_end: Конец периода
            
        Returns:
            Структурированные бухгалтерские данные
        """
        # Базовая реализация парсинга
        # В реальном проекте нужно адаптировать под структуру вашей 1С
        
        result = {
            "period": f"{period_start} - {period_end}",
            "income": 0.0,
            "expenses": 0.0,
            "profit": 0.0,
            "taxes": 0.0,
            "details": []
        }
        
        if "value" in data:
            for item in data["value"]:
                # Пример парсинга - зависит от структуры данных 1С
                if "СуммаДоход" in item:
                    result["income"] = float(item.get("СуммаДоход", 0))
                if "СуммаРасход" in item:
                    result["expenses"] = float(item.get("СуммаРасход", 0))
                if "СуммаНалог" in item:
                    result["taxes"] = float(item.get("СуммаНалог", 0))
                
                result["details"].append(item)
        
        result["profit"] = result["income"] - result["expenses"]
        return result
    
    def get_stock_balance(self, warehouse_id: Optional[str] = None) -> Dict[str, int]:
        """
        Получение остатков товаров на складах.
        
        Args:
            warehouse_id: ID склада (опционально)
            
        Returns:
            Словарь товар -> остаток
        """
        try:
            # Запрос к регистру остатков товаров
            entity_name = "AccumulationRegister.ОстаткиТоваров"
            filters = {}
            if warehouse_id:
                filters["Склад_Key"] = warehouse_id
            
            items = self.query_entity(entity_name, filters=filters)
            
            balances = {}
            for item in items:
                if "Номенклатура_Key" in item and "Количество" in item:
                    product_id = item["Номенклатура_Key"]
                    quantity = int(float(item["Количество"]))
                    balances[product_id] = quantity
            
            return balances
            
        except Exception as e:
            logger.error(f"Ошибка получения остатков товаров: {e}")
            return {}
    
    def execute_1c_query(self, query_text: str) -> List[Dict[str, Any]]:
        """
        Выполнение запроса на языке запросов 1С.
        
        Args:
            query_text: Текст запроса на языке 1С
            
        Returns:
            Результаты запроса
        """
        try:
            # Для выполнения произвольных запросов может потребоваться специальный endpoint
            # или использование сервиса выполнения запросов
            url = f"{self.base_url}ВыполнитьЗапрос"
            data = {
                "Query": query_text,
                "Parameters": {}
            }
            
            response = self.session.post(url, json=data, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            if "value" in result:
                return result["value"]
            else:
                return []
                
        except Exception as e:
            logger.error(f"Ошибка выполнения запроса 1С: {e}")
            # Пробуем альтернативный подход - через OData фильтрацию
            logger.info(f"Текст запроса: {query_text[:100]}...")
            return []


# Глобальный экземпляр для использования в проекте
onec_rest_client = OneCRestClient()

# Функция для проверки доступности 1С REST API
def check_onec_rest_available() -> bool:
    """Проверка доступности REST API 1С."""
    return onec_rest_client.test_connection()

# Функция для получения списка сущностей
def get_onec_entities() -> List[str]:
    """Получение списка доступных сущностей в 1С."""
    return onec_rest_client.get_entities()