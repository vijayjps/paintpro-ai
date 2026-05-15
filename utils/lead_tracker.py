"""
CRM-lite lead tracker — persists lead status to a local JSON file.
Zero cost, zero dependencies beyond stdlib.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "leads_db.json"

STATUSES = ["New", "Contacted", "Quoted", "Won", "Lost"]


def _load() -> dict:
    DB_PATH.parent.mkdir(exist_ok=True)
    if DB_PATH.exists():
        try:
            return json.loads(DB_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"leads": []}


def _save(db: dict):
    DB_PATH.parent.mkdir(exist_ok=True)
    DB_PATH.write_text(json.dumps(db, indent=2, ensure_ascii=False), encoding="utf-8")


def save_leads(leads: list[str], location: str, run_id: str):
    """Persist a list of address strings as new leads (status=New)."""
    db = _load()
    existing = {l["address"] for l in db["leads"]}
    added = 0
    for addr in leads:
        if addr not in existing:
            db["leads"].append({
                "id": f"{run_id}_{added}",
                "address": addr,
                "location": location,
                "status": "New",
                "notes": "",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            added += 1
    _save(db)
    return added


def update_lead(address: str, status: str = None, notes: str = None):
    db = _load()
    for lead in db["leads"]:
        if lead["address"] == address:
            if status:
                lead["status"] = status
            if notes is not None:
                lead["notes"] = notes
            lead["updated_at"] = datetime.now(timezone.utc).isoformat()
            break
    _save(db)


def get_all_leads() -> list[dict]:
    return _load()["leads"]


def get_pipeline_summary() -> dict:
    leads = get_all_leads()
    summary = {s: 0 for s in STATUSES}
    for lead in leads:
        summary[lead.get("status", "New")] = summary.get(lead.get("status", "New"), 0) + 1
    return summary


def delete_lead(address: str):
    db = _load()
    db["leads"] = [l for l in db["leads"] if l["address"] != address]
    _save(db)
