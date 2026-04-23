"""
Унифицированный коннектор к 1С с поддержкой COM (Windows) и REST API.
"""

import logging
import sys
import os
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Пробуем импортировать REST-клиент
try:
    from .onec_rest import OneCRestClient, onec_rest_client, check_onec_rest_available
    REST_AVAILABLE = True
except ImportError:
    REST_AVAILABLE = False
    OneCRestClient = None
    onec_rest_client = None
    check_onec_rest_available = lambda: False

logger = logging.getLogger("zora.connector.1c")


class OneCConnector:
    """Универсальный клиент для работы с 1С (COM или REST)."""

    def __init__(self, connection_string: Optional[str] = None, use_rest: bool = True):
        """
        Инициализация клиента 1С.

        Args:
            connection_string: Строка подключения к 1С (для COM)
            use_rest: Использовать REST API вместо COM (по умолчанию True)
        """
        self.connection_string = connection_string
        self.use_rest = use_rest
        self.logger = logger
        
        # Проверяем, что мы на Windows (COM доступен только на Windows)
        self.is_windows = sys.platform == "win32"
        
        # Инициализируем выбранный клиент
        if use_rest and REST_AVAILABLE:
            self.client_type = "REST"
            self.rest_client = OneCRestClient()
            self.logger.info("Используется REST-клиент для 1С")
        elif self.is_windows:
            self.client_type = "COM"
            self.logger.info("Используется COM-клиент для 1С (только Windows)")
        else:
            self.client_type = "STUB"
            self.logger.warning("Платформа не Windows и REST недоступен - используем заглушки")
        
        # COM-объект (инициализируется при подключении)
        self.com_object = None

    def connect(self) -> bool:
        """
        Подключается к 1С.

        Returns:
            True если успешно, False если ошибка
        """
        self.logger.info(f"Подключение к 1С через {self.client_type}")
        
        if self.client_type == "REST":
            # Для REST проверяем доступность API
            if check_onec_rest_available():
                self.logger.info("REST API 1С доступен")
                return True
            else:
                self.logger.warning("REST API 1С недоступен")
                return False
                
        elif self.client_type == "COM":
            try:
                # Попытка импортировать win32com
                import win32com.client
                # Создаем COM-объект
                if self.connection_string:
                    self.com_object = win32com.client.Dispatch(self.connection_string)
                else:
                    # Пробуем стандартное подключение
                    self.com_object = win32com.client.Dispatch("V83.COMConnector")
                    
                self.logger.info("COM-подключение к 1С успешно")
                return True
            except ImportError:
                self.logger.error("Модуль win32com не установлен. Установите pywin32.")
                return False
            except Exception as e:
                self.logger.error(f"Ошибка COM-подключения к 1С: {e}")
                return False
        else:
            # Заглушка
            self.logger.warning("Используется заглушка для 1С")
            return True

    def execute_query(self, query: str) -> List[Dict[str, Any]]:
        """
        Выполняет запрос к базе 1С.

        Args:
            query: Запрос на языке запросов 1С

        Returns:
            Результаты запроса
        """
        self.logger.info(f"Выполнение запроса к 1С: {query[:100]}...")
        
        if self.client_type == "REST":
            return self.rest_client.execute_1c_query(query)
        elif self.client_type == "COM" and self.com_object:
            try:
                # Пример выполнения запроса через COM
                # Конкретная реализация зависит от вашей конфигурации 1С
                result = self.com_object.Execute(query)
                # Преобразуем результат в список словарей
                return self._com_result_to_dict(result)
            except Exception as e:
                self.logger.error(f"Ошибка выполнения COM-запроса: {e}")
                return []
        else:
            # Заглушка
            return []

    def get_document(self, document_type: str, document_id: str) -> Dict[str, Any]:
        """
        Получает документ из 1С.

        Args:
            document_type: Тип документа (например, "СчетНаОплату")
            document_id: ID документа

        Returns:
            Данные документа
        """
        self.logger.info(f"Получение документа 1С: {document_type} {document_id}")
        
        if self.client_type == "REST":
            result = self.rest_client.get_document(document_type, document_id)
            if result:
                return result
            else:
                # Возвращаем заглушку если документ не найден
                return {
                    "type": document_type,
                    "id": document_id,
                    "number": "000000",
                    "date": "2024-01-01",
                    "sum": 0.0,
                    "status": "not_found"
                }
        elif self.client_type == "COM" and self.com_object:
            try:
                # Пример получения документа через COM
                # Конкретная реализация зависит от вашей конфигурации 1С
                doc = self.com_object.GetObject(document_type, document_id)
                return self._com_object_to_dict(doc)
            except Exception as e:
                self.logger.error(f"Ошибка получения COM-документа: {e}")
                return self._get_stub_document(document_type, document_id)
        else:
            return self._get_stub_document(document_type, document_id)

    def create_document(self, document_type: str, data: Dict[str, Any]) -> Optional[str]:
        """
        Создаёт документ в 1С.

        Args:
            document_type: Тип документа
            data: Данные документа

        Returns:
            ID созданного документа или None при ошибке
        """
        self.logger.info(f"Создание документа 1С: {document_type}")
        
        if self.client_type == "REST":
            return self.rest_client.create_document(document_type, data)
        elif self.client_type == "COM" and self.com_object:
            try:
                # Пример создания документа через COM
                doc = self.com_object.CreateObject(document_type)
                # Заполняем свойства документа
                for key, value in data.items():
                    if hasattr(doc, key):
                        setattr(doc, key, value)
                # Сохраняем документ
                doc.Write()
                return getattr(doc, "Ref_Key", "unknown_id")
            except Exception as e:
                self.logger.error(f"Ошибка создания COM-документа: {e}")
                return None
        else:
            # Заглушка
            return "doc_stub_123"

    def get_accounting_data(self, period_start: str, period_end: str) -> Dict[str, Any]:
        """
        Получает бухгалтерские данные за период.

        Args:
            period_start: Начало периода (YYYY-MM-DD)
            period_end: Конец периода (YYYY-MM-DD)

        Returns:
            Бухгалтерские данные
        """
        self.logger.info(f"Получение бухгалтерских данных 1С с {period_start} по {period_end}")
        
        if self.client_type == "REST":
            return self.rest_client.get_accounting_data(period_start, period_end)
        elif self.client_type == "COM" and self.com_object:
            try:
                # Пример получения бухгалтерских данных через COM
                # Конкретная реализация зависит от вашей конфигурации 1С
                query = f"""
                ВЫБРАТЬ
                    Сумма(Доход) КАК Доход,
                    Сумма(Расход) КАК Расход,
                    Сумма(Налог) КАК Налог
                ИЗ РегистрНакопления.Обороты
                ГДЕ Период МЕЖДУ ДАТАВРЕМЯ('{period_start}') И ДАТАВРЕМЯ('{period_end}')
                """
                result = self.execute_query(query)
                if result:
                    income = float(result[0].get("Доход", 0))
                    expenses = float(result[0].get("Расход", 0))
                    taxes = float(result[0].get("Налог", 0))
                    return {
                        "period": f"{period_start} - {period_end}",
                        "income": income,
                        "expenses": expenses,
                        "profit": income - expenses,
                        "taxes": taxes
                    }
                else:
                    return self._get_stub_accounting_data(period_start, period_end)
            except Exception as e:
                self.logger.error(f"Ошибка получения COM-бухгалтерских данных: {e}")
                return self._get_stub_accounting_data(period_start, period_end)
        else:
            return self._get_stub_accounting_data(period_start, period_end)

    def get_stock_balance(self, warehouse_id: Optional[str] = None) -> Dict[str, int]:
        """
        Получает остатки товаров на складах.

        Args:
            warehouse_id: ID склада (опционально)

        Returns:
            Словарь товар -> остаток
        """
        self.logger.info(f"Получение остатков товаров 1С (склад: {warehouse_id})")
        
        if self.client_type == "REST":
            return self.rest_client.get_stock_balance(warehouse_id)
        elif self.client_type == "COM" and self.com_object:
            try:
                # Пример получения остатков через COM
                query = """
                ВЫБРАТЬ
                    Номенклатура.Ссылка КАК Товар,
                    Сумма(Количество) КАК Остаток
                ИЗ РегистрНакопления.ОстаткиТоваров
                """
                if warehouse_id:
                    query += f" ГДЕ Склад.Ссылка = '{warehouse_id}'"
                query += " СГРУППИРОВАТЬ ПО Номенклатура.Ссылка"
                
                result = self.execute_query(query)
                balances = {}
                for item in result:
                    product_id = item.get("Товар", "")
                    quantity = int(float(item.get("Остаток", 0)))
                    if product_id:
                        balances[product_id] = quantity
                return balances
            except Exception as e:
                self.logger.error(f"Ошибка получения COM-остатков: {e}")
                return {}
        else:
            # Заглушка
            return {}

    # Вспомогательные методы
    
    def _com_result_to_dict(self, com_result) -> List[Dict[str, Any]]:
        """Преобразует COM-результат в список словарей."""
        try:
            result = []
            # Предполагаем, что com_result имеет метод GetRows или подобный
            # Конкретная реализация зависит от структуры данных 1С
            return result
        except Exception as e:
            self.logger.error(f"Ошибка преобразования COM-результата: {e}")
            return []

    def _com_object_to_dict(self, com_object) -> Dict[str, Any]:
        """Преобразует COM-объект в словарь."""
        try:
            result = {}
            # Получаем все свойства объекта
            # Конкретная реализация зависит от структуры объекта 1С
            return result
        except Exception as e:
            self.logger.error(f"Ошибка преобразования COM-объекта: {e}")
            return {}

    def _get_stub_document(self, document_type: str, document_id: str) -> Dict[str, Any]:
        """Возвращает заглушку для документа."""
        return {
            "type": document_type,
            "id": document_id,
            "number": "000000",
            "date": "2024-01-01",
            "sum": 0.0,
            "status": "stub"
        }

    def _get_stub_accounting_data(self, period_start: str, period_end: str) -> Dict[str, Any]:
        """Возвращает заглушку для бухгалтерских данных."""
        return {
            "period": f"{period_start} - {period_end}",
            "income": 0.0,
            "expenses": 0.0,
            "profit": 0.0,
            "taxes": 0.0,
            "status": "stub"
        }


# Глобальный экземпляр для использования в проекте
onec_connector = OneCConnector(use_rest=True)
