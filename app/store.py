import json
import os
from datetime import datetime, timezone
from urllib.parse import urlparse

from app import sqlite_store


_backend = None
_database_url = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_database_url(value: str | None) -> str | None:
    if not value:
        return None

    if value.startswith("postgres://"):
        return "postgresql://" + value[len("postgres://") :]

    return value


def _get_backend():
    global _backend
    global _database_url

    if _backend is not None:
        return _backend

    _database_url = _normalize_database_url(os.getenv("DATABASE_URL"))

    if _database_url and _database_url.startswith("postgresql://"):
        try:
            from app import postgres_store
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "PostgreSQL icin psycopg kurulu degil. `pip install psycopg[binary]` gereklidir."
            ) from exc

        _backend = ("postgres", postgres_store)
        return _backend

    _backend = ("sqlite", sqlite_store)
    return _backend


def init_db() -> None:
    backend_name, backend = _get_backend()

    if backend_name == "postgres":
        backend.init_db(_database_url)
        return

    backend.init_db()


def create_keyword(keyword: str) -> dict:
    backend_name, backend = _get_backend()
    created_at = utc_now()

    if backend_name == "postgres":
        return backend.create_keyword(_database_url, keyword, created_at)

    return backend.create_keyword(keyword, created_at)


def list_keywords() -> list[dict]:
    backend_name, backend = _get_backend()

    if backend_name == "postgres":
        return backend.list_keywords(_database_url)

    return backend.list_keywords()


def next_raw_lead_id() -> int:
    backend_name, backend = _get_backend()

    if backend_name == "postgres":
        return backend.next_raw_lead_id(_database_url)

    return backend.next_raw_lead_id()


def create_raw_lead(record: dict) -> dict:
    backend_name, backend = _get_backend()

    if backend_name == "postgres":
        return backend.create_raw_lead(_database_url, record)

    return backend.create_raw_lead(record)


def list_raw_leads(
    status: str | None = None,
    research_status: str | None = None,
    priority: str | None = None,
    data_reliability: str | None = None,
    search: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict]:
    backend_name, backend = _get_backend()

    if backend_name == "postgres":
        records = backend.list_raw_leads(_database_url, status=status)
    else:
        records = backend.list_raw_leads(status=status)

    filtered_records = [
        record
        for record in records
        if _matches_optional_value(record.get("research_status"), research_status)
        and _matches_optional_value(record.get("priority"), priority)
        and _matches_optional_value(record.get("data_reliability"), data_reliability)
        and _matches_search(record, search)
    ]

    return _paginate(filtered_records, limit=limit, offset=offset)


def get_raw_lead(raw_lead_id: int) -> dict | None:
    backend_name, backend = _get_backend()

    if backend_name == "postgres":
        return backend.get_raw_lead(_database_url, raw_lead_id)

    return backend.get_raw_lead(raw_lead_id)


def save_raw_lead(record: dict) -> dict:
    backend_name, backend = _get_backend()

    if backend_name == "postgres":
        return backend.save_raw_lead(_database_url, record)

    return backend.save_raw_lead(record)


def create_ai_draft(record: dict) -> dict:
    backend_name, backend = _get_backend()

    if backend_name == "postgres":
        return backend.create_ai_draft(_database_url, record)

    return backend.create_ai_draft(record)


def list_ai_drafts(
    entity_type: str | None = None,
    entity_id: int | None = None,
    draft_type: str | None = None,
    status: str | None = None,
) -> list[dict]:
    backend_name, backend = _get_backend()

    if backend_name == "postgres":
        return backend.list_ai_drafts(
            _database_url,
            entity_type=entity_type,
            entity_id=entity_id,
            draft_type=draft_type,
            status=status,
        )

    return backend.list_ai_drafts(
        entity_type=entity_type,
        entity_id=entity_id,
        draft_type=draft_type,
        status=status,
    )


def get_ai_draft(draft_id: int) -> dict | None:
    backend_name, backend = _get_backend()

    if backend_name == "postgres":
        return backend.get_ai_draft(_database_url, draft_id)

    return backend.get_ai_draft(draft_id)


def save_ai_draft(record: dict) -> dict:
    backend_name, backend = _get_backend()

    if backend_name == "postgres":
        return backend.save_ai_draft(_database_url, record)

    return backend.save_ai_draft(record)


def create_lead(record: dict) -> dict:
    backend_name, backend = _get_backend()

    if backend_name == "postgres":
        return backend.create_lead(_database_url, record)

    return backend.create_lead(record)


def list_leads(
    status: str | None = None,
    crm_status: str | None = None,
    outreach_status: str | None = None,
    priority: str | None = None,
    owner: str | None = None,
    search: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict]:
    backend_name, backend = _get_backend()

    if backend_name == "postgres":
        records = backend.list_leads(_database_url, status=status)
    else:
        records = backend.list_leads(status=status)

    filtered_records = [
        record
        for record in records
        if _matches_optional_value(record.get("crm_status"), crm_status)
        and _matches_optional_value(record.get("outreach_status"), outreach_status)
        and _matches_optional_value(record.get("priority"), priority)
        and _matches_optional_value(record.get("sales_owner"), owner)
        and _matches_search(record, search)
    ]

    return _paginate(filtered_records, limit=limit, offset=offset)


def get_lead(lead_id: int) -> dict | None:
    backend_name, backend = _get_backend()

    if backend_name == "postgres":
        return backend.get_lead(_database_url, lead_id)

    return backend.get_lead(lead_id)


def save_lead(record: dict) -> dict:
    backend_name, backend = _get_backend()

    if backend_name == "postgres":
        return backend.save_lead(_database_url, record)

    return backend.save_lead(record)


def get_pipeline_summary() -> dict:
    backend_name, backend = _get_backend()

    if backend_name == "postgres":
        return backend.get_pipeline_summary(_database_url)

    return backend.get_pipeline_summary()


def healthcheck() -> dict:
    backend_name, backend = _get_backend()

    if backend_name == "postgres":
        details = backend.healthcheck(_database_url)
        details["connection"] = _postgres_runtime_info(_database_url)
        return details

    return backend.healthcheck()


def get_runtime_info() -> dict:
    backend_name, _backend = _get_backend()

    if backend_name == "postgres":
        return {
            "backend": "postgres",
            "connection": _postgres_runtime_info(_database_url),
        }

    return {
        "backend": "sqlite",
        "connection": {
            "database": str(sqlite_store.DB_PATH),
        },
    }


def _postgres_runtime_info(database_url: str | None) -> dict:
    if not database_url:
        return {}

    parsed = urlparse(database_url)
    database_name = parsed.path.lstrip("/")

    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "database": database_name,
        "user": parsed.username or "unknown",
    }


def _matches_optional_value(actual_value: str | None, expected_value: str | None) -> bool:
    if not expected_value:
        return True

    if actual_value is None:
        return False

    return actual_value.lower() == expected_value.lower()


def _matches_search(record: dict, search: str | None) -> bool:
    if not search:
        return True

    haystack = json.dumps(record, ensure_ascii=False, sort_keys=True).lower()
    return search.lower() in haystack


def _paginate(records: list[dict], limit: int | None, offset: int) -> list[dict]:
    if offset > 0:
        records = records[offset:]

    if limit is not None:
        records = records[:limit]

    return records
