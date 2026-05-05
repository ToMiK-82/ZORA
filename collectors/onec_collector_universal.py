"""
Универсальный коллектор данных из 1С.
Динамически получает список всех сущностей через OData,
выгружает записи с пагинацией и индексирует в Qdrant.

Режимы:
  - full: полная перезагрузка всех сущностей
  - incremental: обновление изменённых (если есть поле Modified/DataVersion)

Состояние сохраняется в data/onec_state_universal.json
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("ZORA.Collector.1C.Universal")

STATE_FILE = os.path.join("data", "onec_state_universal.json")
PAGE_SIZE = int(os.getenv("ONEC_ODATA_PAGE_SIZE", "100"))


def _load_state() -> Dict[str, Any]:
    """Загружает состояние последнего запуска."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Ошибка загрузки состояния: {e}")
    return {"entities": {}, "last_full_run": None}


def _save_state(state: Dict[str, Any]):
    """Сохраняет состояние."""
    os.makedirs("data", exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


class OneCUniversalCollector:
    """Универсальный коллектор данных из 1С."""

    def __init__(self):
        from connectors.onec_rest import OneCRestClient
        self.client = OneCRestClient()
        self.state = _load_state()
        self.page_size = PAGE_SIZE
        self.logger = logger

    # ------------------------------------------------------------------
    # Определение наличия поля Modified
    # ------------------------------------------------------------------

    def _has_modified_field(self, entity_name: str) -> bool:
        """
        Проверяет, есть ли у сущности поле Modified или DataVersion.
        Запрашивает 1 запись и смотрит ключи.
        """
        try:
            items = self.client.query_entity(entity_name, top=1)
            if items:
                keys = set(items[0].keys())
                if "Modified" in keys or "DataVersion" in keys:
                    return True
            return False
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Выгрузка данных
    # ------------------------------------------------------------------

    def _fetch_all(self, entity_name: str) -> List[Dict[str, Any]]:
        """Полная выгрузка всех записей сущности с пагинацией."""
        items = []
        skip = 0
        while True:
            batch = self.client.query_entity(entity_name, top=self.page_size, skip=skip)
            if not batch:
                break
            items.extend(batch)
            if len(batch) < self.page_size:
                break
            skip += self.page_size
        return items

    def _fetch_incremental(self, entity_name: str, last_modified_str: str) -> List[Dict[str, Any]]:
        """
        Инкрементальная выгрузка: только записи, изменённые после last_modified_str.
        Использует OData $filter с полем Modified.
        """
        items = []
        skip = 0
        raw_filter = f"Modified gt datetime'{last_modified_str}'"
        while True:
            batch = self.client.query_entity(
                entity_name, top=self.page_size, skip=skip, raw_filter=raw_filter
            )
            if not batch:
                break
            items.extend(batch)
            if len(batch) < self.page_size:
                break
            skip += self.page_size
        return items

    # ------------------------------------------------------------------
    # Индексация в Qdrant
    # ------------------------------------------------------------------

    def _store_items(self, entity_name: str, items: List[Dict[str, Any]]) -> int:
        """Сохраняет записи в Qdrant с метаданными."""
        try:
            from memory.qdrant_memory import memory as _memory
        except ImportError:
            logger.warning("Qdrant память недоступна")
            return 0

        indexed = 0
        for item in items:
            try:
                # Определяем ID записи
                record_id = (
                    item.get("Ref_Key")
                    or item.get("Recorder_Key")
                    or item.get("Key")
                    or str(item.get("LineNumber", ""))
                    or str(indexed)
                )

                # Определяем имя/название
                name = item.get("Description") or item.get("Name") or item.get("Наименование") or ""

                # Формируем text для поиска
                text_parts = []
                for key in item:
                    val = item[key]
                    if isinstance(val, (str, int, float)) and not key.endswith("_Key"):
                        text_parts.append(f"{key}: {val}")
                text = "\n".join(text_parts) if text_parts else json.dumps(item, ensure_ascii=False)
                # Ограничиваем длину text
                text = text[:2000]

                metadata = {
                    "source": "1c",
                    "entity_type": entity_name,
                    "id": str(record_id),
                    "name": str(name),
                    "timestamp": datetime.now().isoformat(),
                    "raw_data": json.dumps(item, ensure_ascii=False),
                }

                _memory.store(text=text, metadata=metadata)
                indexed += 1
            except Exception as e:
                logger.error(f"Ошибка индексации записи {entity_name}: {e}")
        return indexed

    # ------------------------------------------------------------------
    # Основной метод
    # ------------------------------------------------------------------

    def run(self, mode: str = "incremental", entity_filter: Optional[str] = None) -> Dict[str, Any]:
        """
        Запускает сбор данных из 1С.

        Args:
            mode: "full" — полная перезагрузка, "incremental" — инкремент
            entity_filter: Если указано, обрабатывается только одна сущность (для отладки)

        Returns:
            Словарь со статистикой
        """
        # Получаем список всех сущностей
        entities = self.client.get_entities()
        if not entities:
            logger.warning("Не удалось получить список сущностей из 1С")
            return {
                "success": False,
                "error": "Не удалось получить список сущностей из 1С",
                "items_processed": 0,
                "items_indexed": 0,
                "errors": ["Список сущностей пуст"],
                "entities_processed": 0,
            }

        # Фильтр для отладки
        if entity_filter:
            entities = [e for e in entities if entity_filter.lower() in e.lower()]
            if not entities:
                return {
                    "success": False,
                    "error": f"Сущность '{entity_filter}' не найдена",
                    "items_processed": 0,
                    "items_indexed": 0,
                    "errors": [f"Сущность '{entity_filter}' не найдена"],
                    "entities_processed": 0,
                }

        logger.info(f"Найдено {len(entities)} сущностей в 1С")
        logger.debug(f"Сущности: {', '.join(entities[:30])}{'...' if len(entities) > 30 else ''}")

        total_processed = 0
        total_indexed = 0
        errors = []

        for ent in entities:
            logger.info(f"Обработка сущности: {ent} (режим: {mode})")
            try:
                has_mod = self._has_modified_field(ent)
                last_mod = self.state.get("entities", {}).get(ent, {}).get("last_modified")

                if mode == "full":
                    items = self._fetch_all(ent)
                else:  # incremental
                    if has_mod and last_mod:
                        items = self._fetch_incremental(ent, last_mod)
                        logger.info(f"  Инкремент для {ent}: {len(items)} изменённых записей")
                    else:
                        items = self._fetch_all(ent)
                        if not has_mod:
                            logger.warning(
                                f"  У сущности {ent} нет поля Modified/DataVersion. "
                                "Инкремент невозможен, выполнена полная выгрузка."
                            )

                indexed = self._store_items(ent, items)
                total_processed += len(items)
                total_indexed += indexed

                # Обновляем состояние
                if "entities" not in self.state:
                    self.state["entities"] = {}
                self.state["entities"][ent] = {
                    "last_run": datetime.now().isoformat(),
                    "count": len(items),
                    "last_modified": datetime.now().isoformat() if has_mod else None,
                    "has_modified_field": has_mod,
                }
                _save_state(self.state)

                logger.info(f"  {ent}: {len(items)} записей, {indexed} проиндексировано")

            except Exception as e:
                logger.error(f"Ошибка при обработке сущности {ent}: {e}")
                errors.append(f"{ent}: {str(e)}")

        # Обновляем время полного запуска
        if mode == "full":
            self.state["last_full_run"] = datetime.now().isoformat()
            _save_state(self.state)

        result = {
            "success": len(errors) == 0,
            "items_processed": total_processed,
            "items_indexed": total_indexed,
            "errors": errors,
            "entities_processed": len(entities),
            "entities_with_errors": len(errors),
            "mode": mode,
        }

        logger.info(
            f"✅ Универсальный сбор 1С завершён: "
            f"{total_processed} записей, {total_indexed} проиндексировано, "
            f"{len(errors)} ошибок"
        )
        return result

    def get_status(self) -> Dict[str, Any]:
        """Возвращает статус коллектора."""
        state = _load_state()
        entities = state.get("entities", {})
        return {
            "collector": "1C Universal",
            "last_full_run": state.get("last_full_run"),
            "entities_count": len(entities),
            "entities": entities,
            "total_items": sum(e.get("count", 0) for e in entities.values()),
        }


# Функция для прямого вызова
def run(mode: str = "incremental", entity_filter: Optional[str] = None) -> Dict[str, Any]:
    """Удобная функция для запуска универсального коллектора."""
    collector = OneCUniversalCollector()
    return collector.run(mode=mode, entity_filter=entity_filter)


def get_status() -> Dict[str, Any]:
    """Возвращает статус универсального коллектора."""
    collector = OneCUniversalCollector()
    return collector.get_status()
