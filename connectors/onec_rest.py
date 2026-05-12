"""
REST-клиент для интеграции с 1С через OData API.
Поддерживает автоматический REST сервис 1С.
"""

import os
import logging
import requests
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("zora.connector.1c.rest")

ONEC_API_URL = os.getenv("ONEC_ODATA_URL") or os.getenv("ONEC_API_URL", "")
ONEC_API_USER = os.getenv("ONEC_ODATA_USER") or os.getenv("ONEC_API_USER", "")
ONEC_API_PASSWORD = os.getenv("ONEC_ODATA_PASSWORD") or os.getenv("ONEC_API_PASSWORD", "")


class OneCRestClient:
    """Клиент для работы с 1С через REST API (OData)."""

    def __init__(self, base_url: Optional[str] = None, username: Optional[str] = None,
                 password: Optional[str] = None):
        self.base_url = base_url or ONEC_API_URL
        self.username = username or ONEC_API_USER
        self.password = password or ONEC_API_PASSWORD

        if not self.base_url.endswith('/'):
            self.base_url += '/'

        self.session = requests.Session()
        self.session.auth = (self.username, self.password)
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
        self.session.timeout = 30

        logger.info(f"Инициализирован REST-клиент 1С: {self.base_url}")

    def get_metadata(self) -> Optional[str]:
        try:
            resp = self.session.get(f"{self.base_url}$metadata", timeout=(10, 30))
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            logger.warning(f"Ошибка получения метаданных: {e}")
            return None

    def test_connection(self) -> bool:
        try:
            response = self.session.get(f"{self.base_url}$metadata", timeout=(10, 10))
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
        try:
            response = self.session.get(self.base_url, timeout=(10, 30))
            response.raise_for_status()
            data = response.json()
            if "value" in data:
                entities = []
                for item in data["value"]:
                    if "name" in item:
                        entities.append(item["name"])
                    elif "url" in item:
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
                    top: Optional[int] = None, skip: Optional[int] = None,
                    raw_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        try:
            url = f"{self.base_url}{entity_name}"
            params = {}
            if raw_filter:
                params['$filter'] = raw_filter
            elif filters:
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

            response = self.session.get(url, params=params, timeout=(10, 30))
            response.raise_for_status()
            data = response.json()
            return data.get("value", [])
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка запроса к сущности {entity_name}: {e}")
            return []
        except Exception as e:
            logger.error(f"Неожиданная ошибка при запросе к {entity_name}: {e}")
            return []

    # ============================================================
    # Агрегированные запросы для регистров накопления
    # ============================================================
    def get_register_balances(self, register_name: str,
                              dimensions: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Получить текущие остатки по регистру накопления (виртуальная таблица Остатки).
        Если URL /Остатки не работает, fallback – пустой список.
        """
        url = f"{self.base_url}{register_name}/Остатки"
        try:
            response = self.session.get(url, timeout=(10, 30))
            response.raise_for_status()
            data = response.json()
            return data.get("value", [])
        except Exception as e:
            logger.warning(f"Не удалось получить остатки через {url}: {e}")
            return []

    def get_register_turnovers(self, register_name: str,
                               start_date: str, end_date: str,
                               dimensions: List[str],
                               resource: str = "Количество") -> List[Dict[str, Any]]:
        """
        Получить обороты регистра накопления за период, сгруппированные по измерениям.
        Использует $apply=groupby.
        """
        filter_str = f"Period ge datetime'{start_date}' and Period le datetime'{end_date}'"
        apply_str = f"groupby(({','.join(dimensions)}), aggregate({resource} with sum as СуммаОборот))"
        url = f"{self.base_url}{register_name}?$filter={filter_str}&$apply={apply_str}"
        try:
            response = self.session.get(url, timeout=(10, 60))  # более длительный таймаут для агрегатов
            response.raise_for_status()
            data = response.json()
            return data.get("value", [])
        except Exception as e:
            logger.error(f"Ошибка получения оборотов {register_name}: {e}")
            return []

    def get_document(self, document_type: str, document_id: str) -> Optional[Dict[str, Any]]:
        try:
            url = f"{self.base_url}{document_type}({document_id})"
            response = self.session.get(url, timeout=(10, 30))
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
        try:
            url = f"{self.base_url}{document_type}"
            response = self.session.post(url, json=data, timeout=(10, 30))
            response.raise_for_status()
            if 'Location' in response.headers:
                import re
                match = re.search(r'\((.*?)\)', response.headers['Location'])
                if match:
                    return match.group(1)
            response_data = response.json()
            return response_data.get('Ref_Key') or response_data.get('Id') or "unknown_id"
        except Exception as e:
            logger.error(f"Ошибка создания документа {document_type}: {e}")
            return None

    def update_document(self, document_type: str, document_id: str, data: Dict[str, Any]) -> bool:
        try:
            url = f"{self.base_url}{document_type}({document_id})"
            response = self.session.patch(url, json=data, timeout=(10, 30))
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Ошибка обновления документа {document_type}({document_id}): {e}")
            return False

    def get_accounting_data(self, period_start: str, period_end: str) -> Dict[str, Any]:
        try:
            params = {'StartPeriod': period_start, 'EndPeriod': period_end, '$format': 'json'}
            report_names = [
                "ОборотноСальдоваяВедомость",
                "ОборотноСальдоваяВедомость_Выборка",
                "AccumulationRegister.Обороты"
            ]
            for report_name in report_names:
                url = f"{self.base_url}{report_name}"
                response = self.session.get(url, params=params, timeout=(10, 30))
                if response.status_code == 200:
                    return self._parse_accounting_data(response.json(), period_start, period_end)
            logger.warning(f"Не удалось получить бухгалтерские данные для периода {period_start} - {period_end}")
            return {"period": f"{period_start} - {period_end}", "income": 0.0, "expenses": 0.0, "profit": 0.0, "taxes": 0.0, "status": "not_found"}
        except Exception as e:
            logger.error(f"Ошибка получения бухгалтерских данных: {e}")
            return {"period": f"{period_start} - {period_end}", "income": 0.0, "expenses": 0.0, "profit": 0.0, "taxes": 0.0, "status": "error", "error": str(e)}

    def _parse_accounting_data(self, data: Dict, period_start: str, period_end: str) -> Dict[str, Any]:
        result = {"period": f"{period_start} - {period_end}", "income": 0.0, "expenses": 0.0, "profit": 0.0, "taxes": 0.0, "details": []}
        if "value" in data:
            for item in data["value"]:
                if "СуммаДоход" in item:
                    result["income"] = float(item.get("СуммаДоход", 0))
                if "СуммаРасход" in item:
                    result["expenses"] = float(item.get("СуммаРасход", 0))
                if "СуммаНалог" in item:
                    result["taxes"] = float(item.get("СуммаНалог", 0))
                result["details"].append(item)
        result["profit"] = result["income"] - result["expenses"]
        return result

    def execute_1c_query(self, query_text: str) -> List[Dict[str, Any]]:
        try:
            url = f"{self.base_url}ВыполнитьЗапрос"
            data = {"Query": query_text, "Parameters": {}}
            response = self.session.post(url, json=data, timeout=(10, 30))
            response.raise_for_status()
            result = response.json()
            return result.get("value", [])
        except Exception as e:
            logger.error(f"Ошибка выполнения запроса 1С: {e}")
            return []

    def get_stock_balance(self, warehouse_id: Optional[str] = None) -> Dict[str, int]:
        try:
            entity_name = "AccumulationRegister.ОстаткиТоваров"
            filters = {"Склад_Key": warehouse_id} if warehouse_id else {}
            items = self.query_entity(entity_name, filters=filters)
            balances = {}
            for item in items:
                if "Номенклатура_Key" in item and "Количество" in item:
                    balances[item["Номенклатура_Key"]] = int(float(item["Количество"]))
            return balances
        except Exception as e:
            logger.error(f"Ошибка получения остатков товаров: {e}")
            return {}


# Глобальный экземпляр для использования в проекте
onec_rest_client = OneCRestClient()


def check_onec_rest_available() -> bool:
    return onec_rest_client.test_connection()


def get_onec_entities() -> List[str]:
    return onec_rest_client.get_entities()