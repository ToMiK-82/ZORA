"""
Универсальный коллектор данных из 1С.
Индексирует все сущности: справочники, документы, регистры сведений и накопления.
Для больших регистров применяются ограничения по времени и количеству записей.
Тип сущности определяется автоматически по метаданным OData или по префиксам.
Дедупликация записей по MD5-хешу.
"""

import json
import logging
import os
import sqlite3
import hashlib
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
import concurrent.futures
from collections import defaultdict

logger = logging.getLogger("ZORA.Collector.1C.Universal")

STATE_FILE = os.path.join("data", "onec_state_universal.json")
HASH_DB_PATH = os.path.join("data", "onec_record_hashes.db")
PAGE_SIZE = int(os.getenv("ONEC_ODATA_PAGE_SIZE", "100"))

NS = {"edm": "http://docs.oasis-open.org/odata/ns/edm"}


def _load_state() -> Dict[str, Any]:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Ошибка загрузки состояния: {e}")
    return {"entities": {}, "last_full_run": None}


def _save_state(state: Dict[str, Any]):
    os.makedirs("data", exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


class RecordHashDB:
    def __init__(self, db_path: str = HASH_DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS record_hashes (
                entity_name TEXT,
                record_id TEXT,
                hash TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (entity_name, record_id)
            )
        """)
        conn.commit()
        conn.close()

    def get_hash(self, entity_name: str, record_id: str) -> Optional[str]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT hash FROM record_hashes WHERE entity_name = ? AND record_id = ?",
            (entity_name, record_id)
        )
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None

    def update_hash(self, entity_name: str, record_id: str, hash_val: str):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO record_hashes (entity_name, record_id, hash, updated_at) VALUES (?, ?, ?, ?)",
            (entity_name, record_id, hash_val, datetime.now().timestamp())
        )
        conn.commit()
        conn.close()

    def clear_entity(self, entity_name: str):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM record_hashes WHERE entity_name = ?", (entity_name,))
        conn.commit()
        conn.close()


class OneCUniversalCollector:

    METADATA_PREFIXES = {
        "Catalog_": "catalog",
        "Document_": "document",
        "InformationRegister_": "information_register",
        "AccumulationRegister_": "accumulation_register",
        "ChartOfCharacteristicTypes_": "chart_of_characteristic_types",
        "ChartOfAccounts_": "chart_of_accounts",
        "ChartOfCalculationTypes_": "chart_of_calculation_types",
        "BusinessProcess_": "business_process",
        "Task_": "task",
        "ExchangePlan_": "exchange_plan",
    }

    def __init__(self, progress_callback=None):
        from connectors.onec_rest import OneCRestClient
        self.client = OneCRestClient()
        self.state = _load_state()
        self.page_size = PAGE_SIZE
        self.logger = logger
        self.progress_callback = progress_callback
        self.hash_db = RecordHashDB()

        self.total_entities = 0
        self.processed_entities = 0
        self.total_indexed_records = 0
        self.current_entity = ""
        self.current_entity_records = 0

        self.entity_meta_types = self._fetch_metadata()

    def get_progress(self) -> Dict[str, Any]:
        return {
            "total_entities": self.total_entities,
            "processed_entities": self.processed_entities,
            "total_indexed_records": self.total_indexed_records,
            "current_entity": self.current_entity,
            "current_entity_records": self.current_entity_records,
        }

    def _fetch_metadata(self) -> Dict[str, str]:
        metadata_xml = self.client.get_metadata()
        if not metadata_xml:
            logger.warning("Метаданные не получены, будет использоваться fallback по префиксам")
            return {}
        types = {}
        try:
            root = ET.fromstring(metadata_xml)
        except ET.ParseError as e:
            logger.error(f"Ошибка парсинга XML метаданных: {e}")
            return {}
        for entity_type_elem in root.findall(".//edm:EntityType", namespaces=NS):
            name = entity_type_elem.get("Name")
            if not name:
                continue
            for prefix, meta_type in self.METADATA_PREFIXES.items():
                if name.startswith(prefix):
                    types[name] = meta_type
                    break
            else:
                types[name] = "unknown"
        logger.info(f"Загружено {len(types)} типов сущностей из метаданных")
        return types

    def _guess_entity_type(self, entity_name: str) -> str:
        if self.entity_meta_types:
            return self.entity_meta_types.get(entity_name, "unknown")
        for prefix, typ in self.METADATA_PREFIXES.items():
            if entity_name.startswith(prefix):
                return typ
        return "unknown"

    def _safe_fetch(self, fetch_func, entity_name, *args):
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(fetch_func, entity_name, *args)
                items = future.result(timeout=120)
                return items
        except concurrent.futures.TimeoutError:
            logger.error(f"Таймаут при получении данных сущности {entity_name}")
            return []
        except Exception as e:
            logger.error(f"Ошибка получения данных {entity_name}: {e}")
            return []

    def _fetch_all(self, entity_name: str, max_records: int = 10000) -> List[Dict[str, Any]]:
        logger.debug(f"Запрос данных сущности {entity_name} (лимит {max_records} записей)...")
        items = []
        skip = 0
        start = time.monotonic()
        while len(items) < max_records:
            if time.monotonic() - start > 120:
                logger.warning(f"  ⏰ Таймаут выгрузки {entity_name} (общий лимит 120с)")
                break
            batch = self.client.query_entity(entity_name, top=self.page_size, skip=skip)
            if not batch:
                break
            items.extend(batch)
            if len(batch) < self.page_size:
                break
            skip += self.page_size
        logger.debug(f"Получено {len(items)} записей для {entity_name}")
        return items[:max_records]

    def _fetch_incremental(self, entity_name: str, last_modified_str: str) -> List[Dict[str, Any]]:
        logger.debug(f"Инкрементальный запрос для {entity_name}...")
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
        logger.debug(f"Инкрементально получено {len(items)} записей для {entity_name}")
        return items

    def _fetch_with_filter(self, entity_name: str, raw_filter: str, max_records: int = 50000) -> List[Dict[str, Any]]:
        logger.debug(f"Запрос данных {entity_name} с фильтром {raw_filter}")
        items = []
        skip = 0
        start = time.monotonic()
        while len(items) < max_records:
            if time.monotonic() - start > 120:
                logger.warning(f"  ⏰ Таймаут выгрузки {entity_name} по фильтру")
                break
            batch = self.client.query_entity(
                entity_name, top=self.page_size, skip=skip, raw_filter=raw_filter
            )
            if not batch:
                break
            items.extend(batch)
            if len(batch) < self.page_size:
                break
            skip += self.page_size
        logger.debug(f"Получено {len(items)} записей для {entity_name} по фильтру")
        return items[:max_records]

    def _has_modified_field(self, entity_name: str) -> bool:
        try:
            items = self.client.query_entity(entity_name, top=1)
            if items:
                keys = set(items[0].keys())
                return "Modified" in keys or "DataVersion" in keys
            return False
        except Exception:
            return False

    def _store_items(self, entity_name: str, items: List[Dict[str, Any]], entity_type: str = None,
                     extra_metadata: Dict[str, Any] = None, skip_hash_check: bool = False) -> Tuple[int, int]:
        try:
            from memory.qdrant_memory import memory as _memory
        except ImportError:
            logger.warning("Qdrant память недоступна")
            return 0, len(items)

        if entity_type is None:
            entity_type = self._guess_entity_type(entity_name)

        indexed = 0
        skipped = 0

        for item in items:
            try:
                record_id = str(item.get("Ref_Key") or item.get("Recorder_Key") or item.get("Key") or "")
                if not record_id:
                    record_id = f"onec_{entity_name}_{indexed}"

                raw_data = json.dumps(item, ensure_ascii=False, sort_keys=True)
                item_hash = hashlib.md5(raw_data.encode()).hexdigest()

                if not skip_hash_check:
                    existing_hash = self.hash_db.get_hash(entity_name, record_id)
                    if existing_hash == item_hash:
                        skipped += 1
                        continue

                name = str(item.get("Description") or item.get("Name") or item.get("Наименование") or "")
                text_parts = []
                for key, val in item.items():
                    if isinstance(val, (str, int, float)) and not key.endswith("_Key"):
                        text_parts.append(f"{key}: {val}")
                text = "\n".join(text_parts) if text_parts else raw_data
                text = text[:2000]

                date = datetime.now().isoformat()
                for date_field in ["Date", "Дата", "Период", "Modified", "DataVersion"]:
                    val = item.get(date_field)
                    if val:
                        try:
                            dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
                            date = dt.isoformat()
                            break
                        except Exception:
                            pass

                metadata = {
                    "source": "1c",
                    "type": entity_type,
                    "entity_id": record_id,
                    "parent_doc_id": record_id,
                    "doc_title": name,
                    "date": date,
                    "chunk_index": 0,
                    "entity_name": entity_name,
                    "raw_data": raw_data,
                }
                if extra_metadata:
                    metadata.update(extra_metadata)

                _memory.store(text=text, metadata=metadata)
                indexed += 1

                if not skip_hash_check:
                    self.hash_db.update_hash(entity_name, record_id, item_hash)

            except Exception as e:
                logger.error(f"Ошибка индексации записи {entity_name}: {e}")

        return indexed, skipped

    # ---------- Обработка регистров сведений ----------
    def _try_slice_last(self, entity_name: str) -> Optional[List[Dict[str, Any]]]:
        try:
            today = datetime.now().strftime("%Y-%m-%dT00:00:00")
            slice_url = f"{entity_name}/СрезПоследних(Period=datetime'{today}')"
            items = self.client.query_entity(slice_url)
            if items is not None:
                return items
        except Exception as e:
            logger.info(f"  Срез последних не поддерживается для {entity_name}: {e}")
        return None

    def _process_information_register(self, entity_name: str) -> Tuple[int, int]:
        slice_items = self._try_slice_last(entity_name)
        if slice_items is not None:
            return self._store_items(entity_name, slice_items)

        items = self._fetch_all(entity_name, max_records=50000)
        return self._store_items(entity_name, items)

    # ---------- Обработка регистров накопления ----------
    def _process_accumulation_register(self, entity_name: str) -> int:
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=365)
        raw_filter = f"Date ge datetime'{start_date.isoformat()}' and Date le datetime'{end_date.isoformat()}'"

        try:
            movements = self._safe_fetch(self._fetch_with_filter, entity_name, raw_filter, 50000)
        except Exception as e:
            logger.error(f"Ошибка загрузки движений {entity_name}: {e}")
            return 0

        if not movements:
            logger.info(f"  {entity_name}: 0 движений за период")
            return 0

        aggregated = defaultdict(lambda: {"in": 0.0, "out": 0.0, "registrars": set()})
        key_fields = ["Номенклатура_Key", "Склад_Key"]

        for move in movements:
            key_parts = []
            for f in key_fields:
                val = move.get(f, "")
                key_parts.append(str(val) if not isinstance(val, str) else val)
            key = tuple(key_parts)

            qty = float(move.get("Количество", 0))
            kind = str(move.get("RecordType", "")).lower()

            if "приход" in kind or "receipt" in kind:
                aggregated[key]["in"] += qty
            else:
                aggregated[key]["out"] += qty

            reg = move.get("Recorder_Key") or move.get("Регистратор_Key")
            if reg:
                aggregated[key]["registrars"].add(str(reg))

        try:
            from memory.qdrant_memory import memory as _memory
        except ImportError:
            return 0

        indexed = 0
        for key, data in aggregated.items():
            balance = data["in"] - data["out"]
            text = (
                f"Товар: {key[0] if len(key)>0 else '—'}, "
                f"Склад: {key[1] if len(key)>1 else '—'}, "
                f"Остаток: {balance:.2f}, "
                f"Приход: {data['in']:.2f}, "
                f"Расход: {data['out']:.2f}"
            )
            record_id = f"{entity_name}_{'_'.join(key)}"
            metadata = {
                "source": "1c",
                "type": "balance_analytics",
                "entity_id": record_id,
                "parent_doc_id": record_id,
                "doc_title": f"Аналитика {entity_name}",
                "date": datetime.now().isoformat(),
                "chunk_index": 0,
                "entity_name": entity_name,
                "Номенклатура_Key": key[0] if len(key) > 0 else "",
                "Склад_Key": key[1] if len(key) > 1 else "",
                "current_balance": balance,
                "in_qty": data["in"],
                "out_qty": data["out"],
                "registrars": list(data["registrars"])[:10],
                "period_start": start_date.isoformat(),
                "period_end": end_date.isoformat(),
            }
            _memory.store(text=text, metadata=metadata)
            indexed += 1

        return indexed

    # ---------- основной метод ----------
    def run(self, mode: str = "incremental", entity_filter: Optional[str] = None) -> Dict[str, Any]:
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

        # Группируем сущности по типам
        catalog = [e for e in entities if e.startswith("Catalog_")]
        documents = [e for e in entities if e.startswith("Document_")]
        info_regs = [e for e in entities if e.startswith("InformationRegister_")]
        accum_regs = [e for e in entities if e.startswith("AccumulationRegister_")]
        others = [e for e in entities if not any(e.startswith(p) for p in (
            "Catalog_", "Document_", "InformationRegister_", "AccumulationRegister_"
        ))]

        all_targets = catalog + documents + info_regs + accum_regs + others
        self.total_entities = len(all_targets)
        logger.info(f"Всего сущностей: {self.total_entities} (catalog: {len(catalog)}, docs: {len(documents)}, "
                    f"info: {len(info_regs)}, accum: {len(accum_regs)}, other: {len(others)})")

        if self.progress_callback:
            self.progress_callback(total_steps=self.total_entities)

        total_processed = 0
        total_indexed = 0
        errors = []

        # 1. Справочники (полная выгрузка с лимитом)
        for ent in catalog:
            self.processed_entities += 1
            self.current_entity = ent
            logger.info(f"Справочник: {ent}")
            try:
                items = self._fetch_all(ent)
                indexed, skipped = self._store_items(ent, items)
                total_processed += len(items)
                total_indexed += indexed
                if self.progress_callback:
                    self.progress_callback(step_increment=1, indexed_increment=indexed,
                                           subject=f"{ent}: {len(items)} записей, {indexed} проиндексировано")
                logger.info(f"  {ent}: {len(items)} записей, проиндексировано {indexed}, пропущено {skipped}")
            except Exception as e:
                logger.error(f"Ошибка справочника {ent}: {e}")
                errors.append(f"{ent}: {str(e)}")

        # 2. Документы (последние 90 дней)
        start_date = (datetime.now().date() - timedelta(days=90)).isoformat()
        end_date = datetime.now().date().isoformat()
        doc_filter = f"Date ge datetime'{start_date}' and Date le datetime'{end_date}'"
        for ent in documents:
            self.processed_entities += 1
            self.current_entity = ent
            logger.info(f"Документ: {ent}")
            try:
                has_mod = self._has_modified_field(ent)
                last_mod = self.state.get("entities", {}).get(ent, {}).get("last_modified")
                if mode == "full":
                    items = self._fetch_with_filter(ent, doc_filter, max_records=20000)
                else:
                    if has_mod and last_mod:
                        items = self._fetch_incremental(ent, last_mod)
                    else:
                        items = self._fetch_with_filter(ent, doc_filter, max_records=20000)
                indexed, skipped = self._store_items(ent, items)
                total_processed += len(items)
                total_indexed += indexed
                if self.progress_callback:
                    self.progress_callback(step_increment=1, indexed_increment=indexed,
                                           subject=f"{ent}: {len(items)} док., {indexed} проиндексировано")
                if "entities" not in self.state:
                    self.state["entities"] = {}
                self.state["entities"][ent] = {
                    "last_run": datetime.now().isoformat(),
                    "count": len(items),
                    "last_modified": datetime.now().isoformat() if has_mod else None,
                    "has_modified_field": has_mod,
                }
                _save_state(self.state)
                logger.info(f"  {ent}: {len(items)} документов, проиндексировано {indexed}")
            except Exception as e:
                logger.error(f"Ошибка документа {ent}: {e}")
                errors.append(f"{ent}: {str(e)}")

        # 3. Регистры сведений (срез последних или ограниченная выгрузка)
        for ent in info_regs:
            self.processed_entities += 1
            self.current_entity = ent
            logger.info(f"Регистр сведений: {ent}")
            try:
                indexed, skipped = self._process_information_register(ent)
                total_indexed += indexed
                if self.progress_callback:
                    self.progress_callback(step_increment=1, indexed_increment=indexed,
                                           subject=f"{ent}: {indexed} записей проиндексировано")
                logger.info(f"  {ent}: проиндексировано {indexed}, пропущено {skipped}")
            except Exception as e:
                logger.error(f"Ошибка регистра сведений {ent}: {e}")
                errors.append(f"{ent}: {str(e)}")

        # 4. Регистры накопления (аналитика за год)
        for ent in accum_regs:
            self.processed_entities += 1
            self.current_entity = ent
            logger.info(f"Регистр накопления: {ent}")
            try:
                indexed = self._process_accumulation_register(ent)
                total_indexed += indexed
                if self.progress_callback:
                    self.progress_callback(step_increment=1, indexed_increment=indexed,
                                           subject=f"{ent}: агрегаты, {indexed} точек")
                logger.info(f"  {ent}: проиндексировано {indexed} аналитических точек")
            except Exception as e:
                logger.error(f"Ошибка регистра накопления {ent}: {e}")
                errors.append(f"{ent}: {str(e)}")

        # 5. Остальные сущности
        for ent in others:
            self.processed_entities += 1
            self.current_entity = ent
            logger.info(f"Прочая сущность: {ent}")
            try:
                items = self._fetch_all(ent)
                indexed, skipped = self._store_items(ent, items)
                total_processed += len(items)
                total_indexed += indexed
                if self.progress_callback:
                    self.progress_callback(step_increment=1, indexed_increment=indexed,
                                           subject=f"{ent}: {len(items)} записей, {indexed} проиндексировано")
                logger.info(f"  {ent}: {len(items)} записей, проиндексировано {indexed}")
            except Exception as e:
                logger.error(f"Ошибка прочей сущности {ent}: {e}")
                errors.append(f"{ent}: {str(e)}")

        if mode == "full":
            self.state["last_full_run"] = datetime.now().isoformat()
            _save_state(self.state)

        result = {
            "success": len(errors) == 0,
            "items_processed": total_processed,
            "items_indexed": total_indexed,
            "errors": errors,
            "entities_processed": self.total_entities,
            "entities_with_errors": len(errors),
            "mode": mode,
        }
        logger.info(f"✅ Сбор 1С завершён: обработано {total_processed} записей, "
                    f"проиндексировано {total_indexed}, ошибок {len(errors)}")
        return result

    def get_status(self) -> Dict[str, Any]:
        state = _load_state()
        entities = state.get("entities", {})
        return {
            "collector": "1C Universal",
            "last_full_run": state.get("last_full_run"),
            "entities_count": len(entities),
            "entities": entities,
            "total_items": sum(e.get("count", 0) for e in entities.values()),
        }


def run(mode: str = "incremental", entity_filter: Optional[str] = None) -> Dict[str, Any]:
    collector = OneCUniversalCollector()
    return collector.run(mode=mode, entity_filter=entity_filter)


def get_status() -> Dict[str, Any]:
    collector = OneCUniversalCollector()
    return collector.get_status()