"""
Коллектор данных из 1С.
Генерирует тестовые данные для всех сущностей и индексирует их в Qdrant.
В будущем — реальные запросы к 1С через REST API.
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger("ZORA.Collector.1C")

# Файл состояния
STATE_FILE = os.path.join("data", "onec_state.json")

# Доступные типы сущностей
ENTITY_TYPES = [
    "product", "balance", "bank_account", "credit", "lease", "order"
]


def _load_state() -> Dict[str, Any]:
    """Загружает состояние последнего запуска."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Ошибка загрузки состояния: {e}")
    return {"last_run": None, "items_indexed": 0}


def _save_state(state: Dict[str, Any]):
    """Сохраняет состояние."""
    os.makedirs("data", exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _generate_test_data(entity_type: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Генерирует тестовые данные для указанного типа сущности."""
    now = datetime.now()
    timestamp = now.isoformat()
    date_str = now.strftime("%Y-%m-%d")

    test_data = {
        "product": [
            {
                "source": "1c",
                "entity_type": "product",
                "id": f"prod-{i:04d}",
                "name": names[i] if i < len(names) else f"Товар {i}",
                "article": f"ART-{1000+i}",
                "price": round(100.0 + i * 50.5, 2),
                "currency": "RUB",
                "unit": "шт",
                "category": "Электроника" if i % 3 == 0 else ("Одежда" if i % 3 == 1 else "Продукты"),
                "description": f"Описание товара {names[i] if i < len(names) else f'Товар {i}'}. Подходит для повседневного использования.",
                "date": date_str,
                "timestamp": timestamp
            }
            for i in range(limit)
        ],
        "balance": [
            {
                "source": "1c",
                "entity_type": "balance",
                "id": f"bal-{i:04d}",
                "name": f"Склад №{i+1}",
                "value": round(100000.0 + i * 25000.0, 2),
                "currency": "RUB",
                "date": date_str,
                "description": f"Остаток на складе №{i+1}",
                "timestamp": timestamp
            }
            for i in range(limit)
        ],
        "bank_account": [
            {
                "source": "1c",
                "entity_type": "bank_account",
                "id": f"acc-{i:04d}",
                "name": f"Расчётный счёт {4081781000000+i:013d}",
                "value": round(500000.0 + i * 100000.0, 2),
                "currency": "RUB",
                "bank": "Сбербанк" if i % 2 == 0 else "ВТБ",
                "date": date_str,
                "description": f"Основной расчётный счёт #{i+1}",
                "timestamp": timestamp
            }
            for i in range(limit)
        ],
        "credit": [
            {
                "source": "1c",
                "entity_type": "credit",
                "id": f"cred-{i:04d}",
                "name": f"Кредитный договор №КД-{2026}-{i+1:04d}",
                "value": round(1000000.0 + i * 500000.0, 2),
                "currency": "RUB",
                "interest_rate": 12.5 + i * 0.5,
                "term_months": 12 + i * 6,
                "bank": "Сбербанк",
                "start_date": date_str,
                "end_date": f"{now.year + 1}-{now.month:02d}-{now.day:02d}",
                "description": f"Кредит на развитие бизнеса",
                "timestamp": timestamp
            }
            for i in range(limit)
        ],
        "lease": [
            {
                "source": "1c",
                "entity_type": "lease",
                "id": f"lease-{i:04d}",
                "name": f"Договор лизинга №Л-{2026}-{i+1:04d}",
                "value": round(2000000.0 + i * 300000.0, 2),
                "currency": "RUB",
                "asset": f"Оборудование {i+1}",
                "term_months": 24 + i * 6,
                "monthly_payment": round(50000.0 + i * 10000.0, 2),
                "lessor": "ВТБ Лизинг",
                "start_date": date_str,
                "description": f"Лизинг оборудования для производства",
                "timestamp": timestamp
            }
            for i in range(limit)
        ],
        "order": [
            {
                "source": "1c",
                "entity_type": "order",
                "id": f"ord-{i:04d}",
                "name": f"Заказ покупателя №ЗП-{2026}-{i+1:04d}",
                "value": round(15000.0 + i * 5000.0, 2),
                "currency": "RUB",
                "customer": f"Клиент {i+1}",
                "status": "Выполнен" if i % 2 == 0 else "В обработке",
                "date": date_str,
                "items_count": 3 + i % 5,
                "description": f"Заказ от клиента {i+1}",
                "timestamp": timestamp
            }
            for i in range(limit)
        ],
    }

    return test_data.get(entity_type, [])


names = [
    "Смартфон Galaxy S25", "Ноутбук ThinkPad X1", "Планшет iPad Pro",
    "Наушники AirPods Pro", "Клавиатура Mechanical", "Мышь Logitech MX",
    "Монитор Dell 4K", "Принтер HP LaserJet", "Веб-камера Logitech",
    "Внешний диск 2TB"
]


def _index_in_qdrant(items: List[Dict[str, Any]]) -> int:
    """Индексирует элементы в Qdrant."""
    try:
        from memory.qdrant_memory import memory as _memory
    except ImportError:
        logger.warning("Qdrant память недоступна")
        return 0

    indexed = 0
    for item in items:
        try:
            # Формируем text из всех значимых полей
            text_parts = []
            for key in ["name", "description", "article", "category", "bank", "asset", "customer", "status"]:
                val = item.get(key)
                if val:
                    text_parts.append(str(val))
            text = " - ".join(text_parts) if text_parts else json.dumps(item, ensure_ascii=False)

            # Добавляем raw_data в metadata
            metadata = {k: v for k, v in item.items() if k not in ("name", "description")}
            metadata["raw_data"] = json.dumps(item, ensure_ascii=False)

            _memory.store(text=text, metadata=metadata)
            indexed += 1
        except Exception as e:
            logger.warning(f"Ошибка индексации {item.get('id')}: {e}")
    return indexed


def run(types: Optional[List[str]] = None, limit: int = 10) -> Dict[str, Any]:
    """
    Основной метод сбора данных из 1С.

    Args:
        types: Список типов сущностей (например, ['product', 'balance']).
               Если None, собираются все типы.
        limit: Количество записей каждого типа.

    Returns:
        Словарь с результатами.
    """
    logger.info(f"Запуск сбора данных 1С: types={types or 'all'}, limit={limit}")

    if types is None:
        types = ENTITY_TYPES

    all_items = []
    errors = []
    total_indexed = 0

    for entity_type in types:
        if entity_type not in ENTITY_TYPES:
            errors.append(f"Неизвестный тип сущности: {entity_type}")
            continue

        try:
            items = _generate_test_data(entity_type, limit=limit)
            all_items.extend(items)
            indexed = _index_in_qdrant(items)
            total_indexed += indexed
            logger.info(f"  {entity_type}: {len(items)} записей, {indexed} проиндексировано")
        except Exception as e:
            logger.error(f"Ошибка обработки {entity_type}: {e}")
            errors.append(f"{entity_type}: {str(e)}")

    # Сохраняем состояние
    state = _load_state()
    state["last_run"] = datetime.now().isoformat()
    state["items_indexed"] = state.get("items_indexed", 0) + total_indexed
    state["last_types"] = types
    _save_state(state)

    result = {
        "success": len(errors) == 0,
        "items_processed": len(all_items),
        "items_indexed": total_indexed,
        "errors": errors,
        "types_processed": types
    }

    logger.info(f"✅ Сбор данных 1С завершён: {result}")
    return result


def get_status() -> Dict[str, Any]:
    """Возвращает статус коллектора."""
    state = _load_state()
    return {
        "collector": "1C",
        "last_run": state.get("last_run"),
        "items_indexed": state.get("items_indexed", 0),
        "available_types": ENTITY_TYPES
    }
