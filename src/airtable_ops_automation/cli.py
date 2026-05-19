from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from airtable_ops_automation.airtable import AirtableClient, write_backup

LOG = logging.getLogger("airtable_ops_automation")


class ColorFormatter(logging.Formatter):
    RESET = "\x1b[0m"
    DIM = "\x1b[2m"
    LEVEL_COLORS = {
        logging.DEBUG: "\x1b[36m",      # cyan
        logging.INFO: "\x1b[32m",       # green
        logging.WARNING: "\x1b[33m",    # yellow
        logging.ERROR: "\x1b[31m",      # red
        logging.CRITICAL: "\x1b[41;97m",  # white on red
    }

    def format(self, record: logging.LogRecord) -> str:
        timestamp = self.formatTime(record, self.datefmt)
        level = record.levelname
        message = record.getMessage()
        level_color = self.LEVEL_COLORS.get(record.levelno, "")
        return (
            f"{self.DIM}{timestamp}{self.RESET} "
            f"{level_color}{level:<8}{self.RESET} "
            f"{record.name} {message}"
        )


def _use_color() -> bool:
    if os.getenv("NO_COLOR"):
        return False
    return sys.stderr.isatty()


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    handler = logging.StreamHandler()
    if _use_color():
        handler.setFormatter(ColorFormatter(datefmt="%Y-%m-%d %H:%M:%S"))
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))

    root.addHandler(handler)


def env_or_required(value: str | None, env_name: str, cli_flag: str) -> str:
    if value:
        return value
    from_env = os.getenv(env_name)
    if from_env:
        return from_env
    raise SystemExit(f"Missing value. Provide {cli_flag} or set {env_name}.")


def extract_group_label(raw_value: Any) -> str | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, str):
        return raw_value
    if isinstance(raw_value, list):
        if not raw_value:
            return None
        first = raw_value[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            return first.get("name") or first.get("id")
    if isinstance(raw_value, dict):
        return raw_value.get("name") or raw_value.get("id")
    return str(raw_value)


def cmd_check_access(args: argparse.Namespace) -> int:
    token = env_or_required(args.token, "AIRTABLE_PAT", "--token")
    base_id = env_or_required(args.base_id, "AIRTABLE_BASE_ID", "--base-id")
    table = env_or_required(args.table, "AIRTABLE_TABLE", "--table")
    client = AirtableClient(token=token, base_id=base_id)
    LOG.info("Checking API access to base=%s table=%s", base_id, table)
    try:
        records = client.list_records(table=table, view=args.view)
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response else "unknown"
        body = exc.response.text if exc.response else str(exc)
        LOG.error("Access check failed: status=%s body=%s", status, body)
        return 1

    LOG.info("Access OK. Retrieved %s records.", len(records))
    if records:
        LOG.info("First record id: %s", records[0].get("id"))
        LOG.info("First record fields: %s", records[0].get("fields", {}))
    return 0


def cmd_fill_group_column(args: argparse.Namespace) -> int:
    token = env_or_required(args.token, "AIRTABLE_PAT", "--token")
    base_id = env_or_required(args.base_id, "AIRTABLE_BASE_ID", "--base-id")
    table = env_or_required(args.table, "AIRTABLE_TABLE", "--table")

    client = AirtableClient(token=token, base_id=base_id)
    LOG.info("Reading records from table=%s view=%s", table, args.view or "<all>")
    records = client.list_records(table=table, view=args.view)
    LOG.info("Loaded %s records", len(records))

    ts = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = Path(args.backup_dir) / f"{table}_{ts}"
    backup_path = write_backup(backup_dir, table=table, records=records)
    LOG.info("Backup written to %s", backup_path)

    updates: list[dict[str, Any]] = []
    for record in records:
        fields = record.get("fields", {})
        source = extract_group_label(fields.get(args.source_field))
        if source is None:
            continue

        current_value = fields.get(args.target_field)
        if args.only_blank and current_value not in (None, ""):
            continue
        if current_value == source:
            continue

        updates.append({"id": record["id"], "fields": {args.target_field: source}})

    LOG.info("Prepared %s updates for target field '%s'", len(updates), args.target_field)
    if not updates:
        LOG.info("No changes needed.")
        return 0

    if args.dry_run:
        LOG.info("Dry run enabled. No updates sent.")
        return 0

    client.update_records(table=table, updates=updates)
    LOG.info("Applied %s updates.", len(updates))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Airtable ops automation CLI")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--token", help="Airtable PAT. Defaults to AIRTABLE_PAT")
    common.add_argument("--base-id", help="Airtable base id. Defaults to AIRTABLE_BASE_ID")
    common.add_argument("--table", help="Airtable table name or id. Defaults to AIRTABLE_TABLE")
    common.add_argument("--view", help="Airtable view name (optional)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    check_cmd = subparsers.add_parser("check-access", parents=[common], help="Verify API access")
    check_cmd.set_defaults(func=cmd_check_access)

    fill_cmd = subparsers.add_parser(
        "fill-group-column",
        parents=[common],
        help="Fill a target field from a source grouping field",
    )
    fill_cmd.add_argument("--source-field", required=True, help="Field containing group/linked value")
    fill_cmd.add_argument("--target-field", required=True, help="Field to populate")
    fill_cmd.add_argument(
        "--backup-dir",
        default="backups",
        help="Directory to store JSON backups (default: backups)",
    )
    fill_cmd.add_argument(
        "--only-blank",
        action="store_true",
        help="Update only records where target field is blank",
    )
    fill_cmd.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and log changes without updating Airtable",
    )
    fill_cmd.set_defaults(func=cmd_fill_group_column)

    return parser


def main() -> None:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()
    configure_logging(verbose=args.verbose)
    exit_code = args.func(args)
    raise SystemExit(exit_code)
