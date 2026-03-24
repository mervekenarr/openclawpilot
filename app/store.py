from datetime import datetime, timezone


keywords: list[dict] = []
raw_leads: list[dict] = []
leads: list[dict] = []

_counters = {
    "keyword": 1,
    "raw_lead": 1,
    "lead": 1,
}


def next_id(counter_name: str) -> int:
    current_value = _counters[counter_name]
    _counters[counter_name] += 1
    return current_value


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
