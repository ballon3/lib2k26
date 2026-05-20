from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class FlowConfig:
    source_csv: str
    target_table: str
    field_map: dict[str, str]
    order_key_columns: list[str]
    max_vendors: int

    @classmethod
    def from_file(cls, config_path: Path) -> "FlowConfig":
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        return cls(
            source_csv=payload["source_csv"],
            target_table=payload["target_table"],
            field_map=payload["field_map"],
            order_key_columns=payload.get("order_key_columns", ["artist", "requested_time"]),
            max_vendors=int(payload.get("max_vendors", 2)),
        )


@dataclass
class PreparedRow:
    group_key: tuple[str, ...]
    vendor: str
    fields: dict[str, Any]


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _to_int(value: str) -> int:
    normalized = value.strip()
    if not normalized:
        return 0
    return int(float(normalized))


def load_csv_rows(csv_path: Path) -> list[dict[str, str]]:
    raw = csv_path.read_text(encoding="utf-8-sig")
    try:
        dialect = csv.Sniffer().sniff(raw[:4096], delimiters=",\t;")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    reader = csv.DictReader(raw.splitlines(), delimiter=delimiter)
    return [dict(row) for row in reader]


def prepare_rows(rows: list[dict[str, str]], config: FlowConfig) -> tuple[list[PreparedRow], list[str]]:
    errors: list[str] = []
    prepared: list[PreparedRow] = []

    missing_columns = [name for name in config.field_map if rows and name not in rows[0]]
    if missing_columns:
        raise ValueError(f"Missing required columns in CSV: {', '.join(missing_columns)}")

    for idx, row in enumerate(rows, start=2):
        vendor = _clean(row.get("vendor"))
        item = _clean(row.get("item"))
        qty_raw = _clean(row.get("quantity"))
        if not vendor or not item:
            errors.append(f"Row {idx}: missing vendor or item")
            continue
        try:
            quantity = _to_int(qty_raw)
        except ValueError:
            errors.append(f"Row {idx}: invalid quantity '{qty_raw}'")
            continue
        if quantity <= 0:
            continue

        group_key = tuple(_clean(row.get(col)) for col in config.order_key_columns)
        fields: dict[str, Any] = {}
        for source_col, target_field in config.field_map.items():
            value = _clean(row.get(source_col))
            fields[target_field] = value
        quantity_field = config.field_map.get("quantity")
        if quantity_field:
            fields[quantity_field] = quantity

        prepared.append(PreparedRow(group_key=group_key, vendor=vendor, fields=fields))

    vendors_by_group: dict[tuple[str, ...], set[str]] = {}
    for row in prepared:
        vendors_by_group.setdefault(row.group_key, set()).add(row.vendor)

    invalid_groups = {k for k, vendors in vendors_by_group.items() if len(vendors) > config.max_vendors}
    if invalid_groups:
        for group in sorted(invalid_groups):
            errors.append(
                f"Group {group} has more than {config.max_vendors} vendors. Skipping group."
            )
        prepared = [row for row in prepared if row.group_key not in invalid_groups]

    return prepared, errors


def load_rows_from_source(source_csv: str, config_path: Path) -> list[dict[str, str]]:
    if source_csv.startswith("http://") or source_csv.startswith("https://"):
        raise ValueError(
            "Use a local CSV export path for now. If needed, we can add direct Google Sheets fetch next."
        )
    source_path = Path(source_csv)
    if not source_path.is_absolute():
        source_path = (config_path.parent / source_path).resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"CSV file not found: {source_path}")
    return load_csv_rows(source_path)
