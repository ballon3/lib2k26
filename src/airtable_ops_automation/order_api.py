from __future__ import annotations

import csv
import datetime as dt
import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from airtable_ops_automation.airtable import AirtableClient


REPO_ROOT = Path(__file__).resolve().parents[2]


def _resolve_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path

    cwd_path = Path.cwd() / path
    if cwd_path.exists():
        return cwd_path

    repo_path = REPO_ROOT / path
    if repo_path.exists():
        return repo_path

    return repo_path


class OrderItemRequest(BaseModel):
    name: str
    quantity: int = Field(ge=1)


class VendorSelectionRequest(BaseModel):
    vendor: str
    requested_time: str
    items: list[OrderItemRequest]


class SubmitOrderRequest(BaseModel):
    artist_name: str
    artist_email: str | None = None
    requested_time: str
    notes: str | None = None
    selections: list[VendorSelectionRequest]


def _menu_path() -> Path:
    value = os.getenv("MENU_CSV_PATH", "config/lib26_vendor_options.csv")
    return _resolve_path(value)


def _load_menu() -> dict[str, list[dict[str, str]]]:
    path = _menu_path()
    if not path.exists():
        raise FileNotFoundError(f"Menu CSV not found: {path}")

    by_vendor: dict[str, list[dict[str, str]]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.reader(fp)
        for row in reader:
            if len(row) < 8:
                continue
            vendor, _zone, category, item, description, diet1, diet2, price = row[:8]
            entry = {
                "category": category.strip(),
                "item": item.strip(),
                "description": description.strip(),
                "dietary": ", ".join(x for x in [diet1.strip(), diet2.strip()] if x and x.lower() != "none"),
                "price": price.strip(),
            }
            by_vendor.setdefault(vendor.strip(), []).append(entry)
    return by_vendor


def _vendor_schedule_path() -> Path:
    value = os.getenv("VENDOR_SCHEDULE_PATH", "config/vendor_schedule.json")
    return _resolve_path(value)


def _parse_hhmm(value: str) -> dt.time:
    return dt.datetime.strptime(value.strip(), "%H:%M").time()


def _format_hhmm(value: dt.time) -> str:
    return value.strftime("%H:%M")


def _generate_slots(ranges: list[str], interval_minutes: int) -> list[str]:
    slots: list[str] = []
    for window in ranges:
        parts = window.split("-")
        if len(parts) != 2:
            continue
        start = _parse_hhmm(parts[0])
        end = _parse_hhmm(parts[1])
        cursor = dt.datetime.combine(dt.date.today(), start)
        limit = dt.datetime.combine(dt.date.today(), end)
        while cursor <= limit:
            slots.append(_format_hhmm(cursor.time()))
            cursor += dt.timedelta(minutes=interval_minutes)
    return slots


def _load_vendor_schedule() -> dict[str, dict[str, list[str] | int]]:
    path = _vendor_schedule_path()
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as fp:
        data = json.load(fp)

    schedule: dict[str, dict[str, list[str] | int]] = {}
    for vendor, raw in data.items():
        windows = raw.get("windows", [])
        interval = int(raw.get("interval_minutes", 15))
        schedule[vendor] = {
            "windows": windows,
            "interval_minutes": interval,
            "slots": _generate_slots(windows, interval),
        }
    return schedule


def create_app() -> FastAPI:
    app = FastAPI(title="LIB Artist Meals API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/vendors")
    def list_vendors() -> list[str]:
        menu = _load_menu()
        return sorted(menu.keys())

    @app.get("/api/vendors/meta")
    def vendor_meta() -> dict[str, dict[str, list[str]]]:
        menu = _load_menu()
        schedule = _load_vendor_schedule()
        response: dict[str, dict[str, list[str]]] = {}
        for vendor in sorted(menu.keys()):
            response[vendor] = {
                "available_slots": schedule.get(vendor, {}).get("slots", []),
                "open_windows": schedule.get(vendor, {}).get("windows", []),
            }
        return response

    @app.get("/api/vendors/{vendor}/items")
    def list_items(vendor: str) -> list[dict[str, str]]:
        menu = _load_menu()
        if vendor not in menu:
            raise HTTPException(status_code=404, detail="Vendor not found")
        return menu[vendor]

    @app.post("/api/orders")
    def submit_order(payload: SubmitOrderRequest) -> dict[str, int]:
        unique_vendors = sorted({s.vendor for s in payload.selections if s.items})
        if not unique_vendors:
            raise HTTPException(status_code=400, detail="At least one vendor selection is required")
        if len(unique_vendors) > 2:
            raise HTTPException(status_code=400, detail="Only two vendors are allowed")

        menu = _load_menu()
        schedule = _load_vendor_schedule()
        allowed_items = {vendor: {row["item"] for row in items} for vendor, items in menu.items()}

        records: list[dict[str, str | int]] = []
        for selection in payload.selections:
            if selection.vendor not in allowed_items:
                raise HTTPException(status_code=400, detail=f"Unknown vendor: {selection.vendor}")

            vendor_slots = schedule.get(selection.vendor, {}).get("slots", [])
            if vendor_slots and selection.requested_time not in vendor_slots:
                raise HTTPException(
                    status_code=400,
                    detail=f"Requested time '{selection.requested_time}' is outside '{selection.vendor}' availability",
                )

            for item in selection.items:
                if item.name not in allowed_items[selection.vendor]:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Item '{item.name}' is not offered by '{selection.vendor}'",
                    )
                records.append(
                    {
                        "Artist": payload.artist_name.strip(),
                        "Artist Email": (payload.artist_email or "").strip(),
                        "Requested Time": selection.requested_time.strip(),
                        "Requested Time (Global)": payload.requested_time.strip(),
                        "Vendor": selection.vendor,
                        "Item": item.name,
                        "Quantity": item.quantity,
                        "Notes": (payload.notes or "").strip(),
                        "Submitted At": dt.datetime.now(dt.UTC).isoformat(),
                    }
                )

        token = os.getenv("AIRTABLE_PAT")
        base_id = os.getenv("AIRTABLE_BASE_ID")
        table = os.getenv("AIRTABLE_ORDER_TABLE", "Artist Food Orders")
        if not token or not base_id:
            raise HTTPException(status_code=500, detail="Missing AIRTABLE_PAT or AIRTABLE_BASE_ID")

        client = AirtableClient(token=token, base_id=base_id)
        client.create_records(table=table, records=records)
        return {"created_records": len(records)}

    return app


app = create_app()
