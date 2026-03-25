import json
import sqlite3
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "openclaw_pilot.db"

_initialized = False


def init_db() -> None:
    global _initialized

    if _initialized:
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS keywords (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS raw_leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT NOT NULL,
                sector TEXT NOT NULL,
                company_name TEXT NOT NULL,
                website TEXT NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                research_status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                reviewed_at TEXT,
                review_note TEXT,
                company_summary TEXT,
                recent_signal TEXT,
                fit_reason TEXT,
                summary TEXT,
                priority TEXT,
                confidence TEXT,
                data_reliability TEXT,
                decision_maker_json TEXT,
                missing_fields_json TEXT,
                personal_notes_json TEXT,
                research_bundle_json TEXT
            );

            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_lead_id INTEGER NOT NULL,
                company_name TEXT NOT NULL,
                keyword TEXT NOT NULL,
                sector TEXT NOT NULL,
                website TEXT NOT NULL,
                status TEXT NOT NULL,
                crm_status TEXT NOT NULL,
                outreach_status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                sales_owner TEXT,
                company_summary TEXT,
                recent_signal TEXT,
                fit_reason TEXT,
                summary TEXT,
                priority TEXT,
                confidence TEXT,
                data_reliability TEXT,
                decision_maker_json TEXT,
                missing_fields_json TEXT,
                first_message_json TEXT,
                follow_up_message_json TEXT,
                activity_log_json TEXT,
                crm_record_json TEXT,
                last_reply_json TEXT,
                FOREIGN KEY(raw_lead_id) REFERENCES raw_leads(id)
            );

            CREATE TABLE IF NOT EXISTS ai_drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                entity_id INTEGER NOT NULL,
                draft_type TEXT NOT NULL,
                provider TEXT NOT NULL,
                status TEXT NOT NULL,
                actor_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                approved_at TEXT,
                approved_by TEXT,
                request_payload_json TEXT NOT NULL,
                response_payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS research_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_lead_id INTEGER NOT NULL,
                actor_name TEXT NOT NULL,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                request_payload_json TEXT NOT NULL,
                result_payload_json TEXT,
                error_message TEXT,
                FOREIGN KEY(raw_lead_id) REFERENCES raw_leads(id)
            );
            """
        )
        _ensure_column_exists(connection, "raw_leads", "research_bundle_json", "TEXT")

    _initialized = True


def get_connection() -> sqlite3.Connection:
    init_db()
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def connection_scope():
    connection = get_connection()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def healthcheck() -> dict:
    with connection_scope() as connection:
        row = connection.execute("SELECT 1 AS ok").fetchone()

    return {
        "ok": bool(row["ok"]),
        "backend": "sqlite",
        "database": str(DB_PATH),
    }


def create_keyword(keyword: str, created_at: str) -> dict:
    with connection_scope() as connection:
        cursor = connection.execute(
            """
            INSERT INTO keywords (keyword, created_at)
            VALUES (?, ?)
            """,
            (keyword, created_at),
        )
        keyword_id = cursor.lastrowid
        row = connection.execute(
            "SELECT id, keyword, created_at FROM keywords WHERE id = ?",
            (keyword_id,),
        ).fetchone()

    return _keyword_from_row(row)


def list_keywords() -> list[dict]:
    with connection_scope() as connection:
        rows = connection.execute(
            """
            SELECT id, keyword, created_at
            FROM keywords
            ORDER BY id DESC
            """
        ).fetchall()

    return [_keyword_from_row(row) for row in rows]


def next_raw_lead_id() -> int:
    with connection_scope() as connection:
        row = connection.execute(
            "SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM raw_leads"
        ).fetchone()

    return int(row["next_id"])


def create_raw_lead(record: dict) -> dict:
    with connection_scope() as connection:
        cursor = connection.execute(
            """
            INSERT INTO raw_leads (
                keyword,
                sector,
                company_name,
                website,
                source,
                status,
                research_status,
                created_at,
                updated_at,
                reviewed_at,
                review_note,
                company_summary,
                recent_signal,
                fit_reason,
                summary,
                priority,
                confidence,
                data_reliability,
                decision_maker_json,
                missing_fields_json,
                personal_notes_json,
                research_bundle_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            _raw_lead_values(record),
        )
        raw_lead_id = cursor.lastrowid
        row = connection.execute(
            "SELECT * FROM raw_leads WHERE id = ?",
            (raw_lead_id,),
        ).fetchone()

    return _raw_lead_from_row(row)


def list_raw_leads(status: str | None = None) -> list[dict]:
    query = "SELECT * FROM raw_leads"
    params: tuple = ()

    if status:
        query += " WHERE status = ?"
        params = (status,)

    query += " ORDER BY id DESC"

    with connection_scope() as connection:
        rows = connection.execute(query, params).fetchall()

    return [_raw_lead_from_row(row) for row in rows]


def get_raw_lead(raw_lead_id: int) -> dict | None:
    with connection_scope() as connection:
        row = connection.execute(
            "SELECT * FROM raw_leads WHERE id = ?",
            (raw_lead_id,),
        ).fetchone()

    if not row:
        return None

    return _raw_lead_from_row(row)


def save_raw_lead(record: dict) -> dict:
    with connection_scope() as connection:
        connection.execute(
            """
            UPDATE raw_leads
            SET keyword = ?,
                sector = ?,
                company_name = ?,
                website = ?,
                source = ?,
                status = ?,
                research_status = ?,
                created_at = ?,
                updated_at = ?,
                reviewed_at = ?,
                review_note = ?,
                company_summary = ?,
                recent_signal = ?,
                fit_reason = ?,
                summary = ?,
                priority = ?,
                confidence = ?,
                data_reliability = ?,
                decision_maker_json = ?,
                missing_fields_json = ?,
                personal_notes_json = ?,
                research_bundle_json = ?
            WHERE id = ?
            """,
            _raw_lead_values(record) + (record["id"],),
        )
        row = connection.execute(
            "SELECT * FROM raw_leads WHERE id = ?",
            (record["id"],),
        ).fetchone()

    return _raw_lead_from_row(row)


def create_research_run(record: dict) -> dict:
    with connection_scope() as connection:
        cursor = connection.execute(
            """
            INSERT INTO research_runs (
                raw_lead_id,
                actor_name,
                mode,
                status,
                created_at,
                completed_at,
                request_payload_json,
                result_payload_json,
                error_message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            _research_run_values(record),
        )
        research_run_id = cursor.lastrowid
        row = connection.execute(
            "SELECT * FROM research_runs WHERE id = ?",
            (research_run_id,),
        ).fetchone()

    return _research_run_from_row(row)


def list_research_runs(raw_lead_id: int | None = None) -> list[dict]:
    query = "SELECT * FROM research_runs"
    params: tuple = ()

    if raw_lead_id is not None:
        query += " WHERE raw_lead_id = ?"
        params = (raw_lead_id,)

    query += " ORDER BY id DESC"

    with connection_scope() as connection:
        rows = connection.execute(query, params).fetchall()

    return [_research_run_from_row(row) for row in rows]


def create_lead(record: dict) -> dict:
    with connection_scope() as connection:
        cursor = connection.execute(
            """
            INSERT INTO leads (
                raw_lead_id,
                company_name,
                keyword,
                sector,
                website,
                status,
                crm_status,
                outreach_status,
                created_at,
                sales_owner,
                company_summary,
                recent_signal,
                fit_reason,
                summary,
                priority,
                confidence,
                data_reliability,
                decision_maker_json,
                missing_fields_json,
                first_message_json,
                follow_up_message_json,
                activity_log_json,
                crm_record_json,
                last_reply_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            _lead_values(record),
        )
        lead_id = cursor.lastrowid
        row = connection.execute(
            "SELECT * FROM leads WHERE id = ?",
            (lead_id,),
        ).fetchone()

    return _lead_from_row(row)


def list_leads(status: str | None = None) -> list[dict]:
    query = "SELECT * FROM leads"
    params: tuple = ()

    if status:
        query += " WHERE status = ?"
        params = (status,)

    query += " ORDER BY id DESC"

    with connection_scope() as connection:
        rows = connection.execute(query, params).fetchall()

    return [_lead_from_row(row) for row in rows]


def get_lead(lead_id: int) -> dict | None:
    with connection_scope() as connection:
        row = connection.execute(
            "SELECT * FROM leads WHERE id = ?",
            (lead_id,),
        ).fetchone()

    if not row:
        return None

    return _lead_from_row(row)


def save_lead(record: dict) -> dict:
    with connection_scope() as connection:
        connection.execute(
            """
            UPDATE leads
            SET raw_lead_id = ?,
                company_name = ?,
                keyword = ?,
                sector = ?,
                website = ?,
                status = ?,
                crm_status = ?,
                outreach_status = ?,
                created_at = ?,
                sales_owner = ?,
                company_summary = ?,
                recent_signal = ?,
                fit_reason = ?,
                summary = ?,
                priority = ?,
                confidence = ?,
                data_reliability = ?,
                decision_maker_json = ?,
                missing_fields_json = ?,
                first_message_json = ?,
                follow_up_message_json = ?,
                activity_log_json = ?,
                crm_record_json = ?,
                last_reply_json = ?
            WHERE id = ?
            """,
            _lead_values(record) + (record["id"],),
        )
        row = connection.execute(
            "SELECT * FROM leads WHERE id = ?",
            (record["id"],),
        ).fetchone()

    return _lead_from_row(row)


def create_ai_draft(record: dict) -> dict:
    with connection_scope() as connection:
        cursor = connection.execute(
            """
            INSERT INTO ai_drafts (
                entity_type,
                entity_id,
                draft_type,
                provider,
                status,
                actor_name,
                created_at,
                updated_at,
                approved_at,
                approved_by,
                request_payload_json,
                response_payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            _ai_draft_values(record),
        )
        draft_id = cursor.lastrowid
        row = connection.execute(
            "SELECT * FROM ai_drafts WHERE id = ?",
            (draft_id,),
        ).fetchone()

    return _ai_draft_from_row(row)


def list_ai_drafts(
    entity_type: str | None = None,
    entity_id: int | None = None,
    draft_type: str | None = None,
    status: str | None = None,
) -> list[dict]:
    query = "SELECT * FROM ai_drafts"
    clauses = []
    params = []

    if entity_type:
        clauses.append("entity_type = ?")
        params.append(entity_type)
    if entity_id is not None:
        clauses.append("entity_id = ?")
        params.append(entity_id)
    if draft_type:
        clauses.append("draft_type = ?")
        params.append(draft_type)
    if status:
        clauses.append("status = ?")
        params.append(status)

    if clauses:
        query += " WHERE " + " AND ".join(clauses)

    query += " ORDER BY id DESC"

    with connection_scope() as connection:
        rows = connection.execute(query, tuple(params)).fetchall()

    return [_ai_draft_from_row(row) for row in rows]


def get_ai_draft(draft_id: int) -> dict | None:
    with connection_scope() as connection:
        row = connection.execute(
            "SELECT * FROM ai_drafts WHERE id = ?",
            (draft_id,),
        ).fetchone()

    if not row:
        return None

    return _ai_draft_from_row(row)


def save_ai_draft(record: dict) -> dict:
    with connection_scope() as connection:
        connection.execute(
            """
            UPDATE ai_drafts
            SET entity_type = ?,
                entity_id = ?,
                draft_type = ?,
                provider = ?,
                status = ?,
                actor_name = ?,
                created_at = ?,
                updated_at = ?,
                approved_at = ?,
                approved_by = ?,
                request_payload_json = ?,
                response_payload_json = ?
            WHERE id = ?
            """,
            _ai_draft_values(record) + (record["id"],),
        )
        row = connection.execute(
            "SELECT * FROM ai_drafts WHERE id = ?",
            (record["id"],),
        ).fetchone()

    return _ai_draft_from_row(row)


def get_pipeline_summary() -> dict:
    with connection_scope() as connection:
        keyword_total = connection.execute(
            "SELECT COUNT(*) AS total FROM keywords"
        ).fetchone()["total"]
        raw_lead_total = connection.execute(
            "SELECT COUNT(*) AS total FROM raw_leads"
        ).fetchone()["total"]
        approved_leads_total = connection.execute(
            "SELECT COUNT(*) AS total FROM leads"
        ).fetchone()["total"]

        return {
            "keywords_total": int(keyword_total),
            "raw_leads_total": int(raw_lead_total),
            "approved_leads_total": int(approved_leads_total),
            "raw_lead_status": _counter_from_query(connection, "raw_leads", "status"),
            "lead_status": _counter_from_query(connection, "leads", "status"),
            "outreach_status": _counter_from_query(connection, "leads", "outreach_status"),
            "crm_status": _counter_from_query(connection, "leads", "crm_status"),
        }


def _keyword_from_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "keyword": row["keyword"],
        "created_at": row["created_at"],
    }


def _raw_lead_values(record: dict) -> tuple:
    return (
        record["keyword"],
        record["sector"],
        record["company_name"],
        record["website"],
        record["source"],
        record["status"],
        record["research_status"],
        record["created_at"],
        record.get("updated_at"),
        record.get("reviewed_at"),
        record.get("review_note"),
        record.get("company_summary"),
        record.get("recent_signal"),
        record.get("fit_reason"),
        record.get("summary"),
        record.get("priority"),
        record.get("confidence"),
        record.get("data_reliability"),
        _json_dumps(record.get("decision_maker")),
        _json_dumps(record.get("missing_fields", [])),
        _json_dumps(record.get("personal_notes", [])),
        _json_dumps(record.get("research_bundle")),
    )


def _lead_values(record: dict) -> tuple:
    return (
        record["raw_lead_id"],
        record["company_name"],
        record["keyword"],
        record["sector"],
        record["website"],
        record["status"],
        record["crm_status"],
        record["outreach_status"],
        record["created_at"],
        record.get("sales_owner"),
        record.get("company_summary"),
        record.get("recent_signal"),
        record.get("fit_reason"),
        record.get("summary"),
        record.get("priority"),
        record.get("confidence"),
        record.get("data_reliability"),
        _json_dumps(record.get("decision_maker")),
        _json_dumps(record.get("missing_fields", [])),
        _json_dumps(record.get("first_message")),
        _json_dumps(record.get("follow_up_message")),
        _json_dumps(record.get("activity_log", [])),
        _json_dumps(record.get("crm_record")),
        _json_dumps(record.get("last_reply")),
    )


def _ai_draft_values(record: dict) -> tuple:
    return (
        record["entity_type"],
        record["entity_id"],
        record["draft_type"],
        record["provider"],
        record["status"],
        record["actor_name"],
        record["created_at"],
        record.get("updated_at"),
        record.get("approved_at"),
        record.get("approved_by"),
        _json_dumps(record.get("request_payload", {})),
        _json_dumps(record.get("response_payload", {})),
    )


def _research_run_values(record: dict) -> tuple:
    return (
        record["raw_lead_id"],
        record["actor_name"],
        record["mode"],
        record["status"],
        record["created_at"],
        record.get("completed_at"),
        _json_dumps(record.get("request_payload", {})),
        _json_dumps(record.get("result_payload")),
        record.get("error_message"),
    )


def _raw_lead_from_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "keyword": row["keyword"],
        "sector": row["sector"],
        "company_name": row["company_name"],
        "website": row["website"],
        "source": row["source"],
        "status": row["status"],
        "research_status": row["research_status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "reviewed_at": row["reviewed_at"],
        "review_note": row["review_note"],
        "company_summary": row["company_summary"],
        "recent_signal": row["recent_signal"],
        "fit_reason": row["fit_reason"],
        "summary": row["summary"],
        "priority": row["priority"],
        "confidence": row["confidence"],
        "data_reliability": row["data_reliability"],
        "decision_maker": _json_loads(row["decision_maker_json"], {}),
        "missing_fields": _json_loads(row["missing_fields_json"], []),
        "personal_notes": _json_loads(row["personal_notes_json"], []),
        "research_bundle": _json_loads(row["research_bundle_json"], None),
    }


def _lead_from_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "raw_lead_id": row["raw_lead_id"],
        "company_name": row["company_name"],
        "keyword": row["keyword"],
        "sector": row["sector"],
        "website": row["website"],
        "status": row["status"],
        "crm_status": row["crm_status"],
        "outreach_status": row["outreach_status"],
        "created_at": row["created_at"],
        "sales_owner": row["sales_owner"],
        "company_summary": row["company_summary"],
        "recent_signal": row["recent_signal"],
        "fit_reason": row["fit_reason"],
        "summary": row["summary"],
        "priority": row["priority"],
        "confidence": row["confidence"],
        "data_reliability": row["data_reliability"],
        "decision_maker": _json_loads(row["decision_maker_json"], {}),
        "missing_fields": _json_loads(row["missing_fields_json"], []),
        "first_message": _json_loads(row["first_message_json"], None),
        "follow_up_message": _json_loads(row["follow_up_message_json"], None),
        "activity_log": _json_loads(row["activity_log_json"], []),
        "crm_record": _json_loads(row["crm_record_json"], None),
        "last_reply": _json_loads(row["last_reply_json"], None),
    }


def _ai_draft_from_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "entity_type": row["entity_type"],
        "entity_id": row["entity_id"],
        "draft_type": row["draft_type"],
        "provider": row["provider"],
        "status": row["status"],
        "actor_name": row["actor_name"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "approved_at": row["approved_at"],
        "approved_by": row["approved_by"],
        "request_payload": _json_loads(row["request_payload_json"], {}),
        "response_payload": _json_loads(row["response_payload_json"], {}),
    }


def _research_run_from_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "raw_lead_id": row["raw_lead_id"],
        "actor_name": row["actor_name"],
        "mode": row["mode"],
        "status": row["status"],
        "created_at": row["created_at"],
        "completed_at": row["completed_at"],
        "request_payload": _json_loads(row["request_payload_json"], {}),
        "result_payload": _json_loads(row["result_payload_json"], None),
        "error_message": row["error_message"],
    }


def _counter_from_query(connection: sqlite3.Connection, table_name: str, column_name: str) -> dict:
    rows = connection.execute(
        f"""
        SELECT {column_name} AS label, COUNT(*) AS total
        FROM {table_name}
        GROUP BY {column_name}
        ORDER BY {column_name}
        """
    ).fetchall()

    return {
        row["label"]: row["total"]
        for row in rows
        if row["label"] is not None
    }


def _ensure_column_exists(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> None:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    existing_columns = {row[1] for row in rows}
    if column_name in existing_columns:
        return

    connection.execute(
        f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
    )


def _json_dumps(value):
    if value is None:
        return None

    return json.dumps(value)


def _json_loads(value, fallback):
    if value is None:
        return deepcopy(fallback)

    return json.loads(value)
