from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


@dataclass
class AirtableClient:
    token: str
    base_id: str
    timeout: int = 30

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def _url(self, table: str) -> str:
        return f"https://api.airtable.com/v0/{self.base_id}/{table}"

    def list_tables(self) -> list[dict[str, Any]]:
        response = requests.get(
            f"https://api.airtable.com/v0/meta/bases/{self.base_id}/tables",
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("tables", [])

    def resolve_table_name(self, table: str) -> str:
        if not table.startswith("tbl"):
            return table
        for table_meta in self.list_tables():
            if table_meta.get("id") == table:
                return table_meta.get("name") or table
        return table

    def list_records(self, table: str, view: str | None = None) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        offset: str | None = None
        while True:
            params: dict[str, Any] = {}
            if view:
                params["view"] = view
            if offset:
                params["offset"] = offset

            response = requests.get(
                self._url(table),
                headers=self._headers,
                params=params,
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            records.extend(payload.get("records", []))
            offset = payload.get("offset")
            if not offset:
                break
        return records

    def update_records(self, table: str, updates: list[dict[str, Any]]) -> None:
        for idx in range(0, len(updates), 10):
            chunk = updates[idx : idx + 10]
            payload = {"records": chunk}
            response = requests.patch(
                self._url(table),
                headers=self._headers,
                data=json.dumps(payload),
                timeout=self.timeout,
            )
            response.raise_for_status()

    def create_records(self, table: str, records: list[dict[str, Any]]) -> None:
        for idx in range(0, len(records), 10):
            chunk = records[idx : idx + 10]
            payload = {"records": [{"fields": row} for row in chunk]}
            response = requests.post(
                self._url(table),
                headers=self._headers,
                data=json.dumps(payload),
                timeout=self.timeout,
            )
            response.raise_for_status()


def write_backup(
    output_dir: Path,
    table: str,
    records: list[dict[str, Any]],
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    backup_path = output_dir / f"{table}.json"
    backup_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    return backup_path


def write_backup_csv(
    output_dir: Path,
    table: str,
    records: list[dict[str, Any]],
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    backup_path = output_dir / f"{table}.csv"

    field_names: set[str] = set()
    for record in records:
        fields = record.get("fields", {})
        field_names.update(fields.keys())

    ordered_fields = ["id", "createdTime", *sorted(field_names)]

    with backup_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=ordered_fields)
        writer.writeheader()
        for record in records:
            row: dict[str, Any] = {
                "id": record.get("id"),
                "createdTime": record.get("createdTime"),
            }
            fields = record.get("fields", {})
            for key in field_names:
                value = fields.get(key)
                if isinstance(value, (dict, list)):
                    row[key] = json.dumps(value, ensure_ascii=False)
                else:
                    row[key] = value
            writer.writerow(row)

    return backup_path


def slugify(name: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", name.strip())
    return normalized.strip("_") or "table"
