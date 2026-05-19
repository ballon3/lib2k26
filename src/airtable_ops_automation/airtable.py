from __future__ import annotations

import json
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


def write_backup(
    output_dir: Path,
    table: str,
    records: list[dict[str, Any]],
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    backup_path = output_dir / f"{table}.json"
    backup_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    return backup_path
