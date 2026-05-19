from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from airtable_ops_automation.airtable import AirtableClient, slugify, write_backup, write_backup_csv

LOG = logging.getLogger("lib2k26")


def load_banner(command: str | None = None) -> str:
    _ = command
    art = (
        "   __    __  ___    ___      ___    \n"
        "  / /   / / / o.)  /_  ) /7 /_  ),'7\n"
        " / /_  / / / o \\   ,'c' //_7,'c'/o \\\n"
        "/___/ /_/ /___,'  (___7//\\\\(___7|_,'  ⚡"
    )
    border = "=" * 56
    return f"{border}\n{art}\n{border}\n"


class ColorFormatter(logging.Formatter):
    RESET = "\x1b[0m"
    DIM = "\x1b[2m"
    LEVEL_COLORS = {
        logging.DEBUG: "\x1b[36m",      # cyan
        logging.INFO: "\x1b[33m",       # yellow
        logging.WARNING: "\x1b[33m",    # yellow
        logging.ERROR: "\x1b[31m",      # red
        logging.CRITICAL: "\x1b[41;97m",  # white on red
    }
    LEVEL_LABELS = {
        logging.DEBUG: "DEBUG",
        logging.INFO: "⚡ INFO",
        logging.WARNING: "WARN",
        logging.ERROR: "ERROR",
        logging.CRITICAL: "CRIT",
    }

    def format(self, record: logging.LogRecord) -> str:
        timestamp = self.formatTime(record, self.datefmt)
        level = self.LEVEL_LABELS.get(record.levelno, record.levelname)
        message = record.getMessage()
        level_color = self.LEVEL_COLORS.get(record.levelno, "")
        return (
            f"{self.DIM}{timestamp}{self.RESET} "
            f"{level_color}{level:<8}{self.RESET} "
            f"{record.name} {message}"
        )


class PlainEmojiFormatter(logging.Formatter):
    LEVEL_LABELS = {
        logging.DEBUG: "DEBUG",
        logging.INFO: "⚡ INFO",
        logging.WARNING: "WARN",
        logging.ERROR: "ERROR",
        logging.CRITICAL: "CRIT",
    }

    def format(self, record: logging.LogRecord) -> str:
        timestamp = self.formatTime(record, self.datefmt)
        level = self.LEVEL_LABELS.get(record.levelno, record.levelname)
        message = record.getMessage()
        return f"{timestamp} {level:<8} {record.name} {message}"


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
        handler.setFormatter(PlainEmojiFormatter(datefmt="%Y-%m-%d %H:%M:%S"))

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


def automation_table_name(table_name: str, prefix: str, suffix: str) -> str:
    return f"{prefix}{table_name}{suffix}"


def write_backups_for_format(
    output_dir: Path,
    table_name: str,
    records: list[dict[str, Any]],
    output_format: str,
) -> list[Path]:
    paths: list[Path] = []
    if output_format in {"json", "both"}:
        paths.append(write_backup(output_dir, table=table_name, records=records))
    if output_format in {"csv", "both"}:
        paths.append(write_backup_csv(output_dir, table=table_name, records=records))
    return paths


def cmd_check_access(args: argparse.Namespace) -> int:
    token = env_or_required(args.token, "AIRTABLE_PAT", "--token")
    base_id = env_or_required(args.base_id, "AIRTABLE_BASE_ID", "--base-id")
    table = env_or_required(args.table, "AIRTABLE_TABLE", "--table")
    client = AirtableClient(token=token, base_id=base_id)
    LOG.info("⚡ LIB Ops access check: base=%s table=%s", base_id, table)
    try:
        records = client.list_records(table=table, view=args.view)
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response else "unknown"
        body = exc.response.text if exc.response else str(exc)
        LOG.error("Access check failed: status=%s body=%s", status, body)
        return 1

    LOG.info("⚡ Access is live. Pulled %s records.", len(records))
    if records:
        LOG.info("First record id: %s", records[0].get("id"))
        LOG.info("First record fields: %s", records[0].get("fields", {}))
    return 0


def cmd_fill_group_column(args: argparse.Namespace) -> int:
    token = env_or_required(args.token, "AIRTABLE_PAT", "--token")
    base_id = env_or_required(args.base_id, "AIRTABLE_BASE_ID", "--base-id")
    table = env_or_required(args.table, "AIRTABLE_TABLE", "--table")

    client = AirtableClient(token=token, base_id=base_id)
    resolved_name = client.resolve_table_name(table)
    automation_name = automation_table_name(resolved_name, args.table_name_prefix, args.table_name_suffix)
    LOG.info("Reading records from table=%s view=%s", table, args.view or "<all>")
    LOG.info("⚡ Automation table label: %s", automation_name)
    records = client.list_records(table=table, view=args.view)
    LOG.info("Loaded %s records", len(records))

    ts = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = Path(args.backup_dir) / f"{slugify(automation_name)}_{ts}"
    backup_paths = write_backups_for_format(
        output_dir=backup_dir,
        table_name=slugify(automation_name),
        records=records,
        output_format=args.output_format,
    )
    for backup_path in backup_paths:
        LOG.info("⚡ Safety backup saved to %s", backup_path)
    if args.working_copy:
        for backup_path in backup_paths:
            working_copy_path = backup_path.with_name(f"{backup_path.stem}.working{backup_path.suffix}")
            shutil.copy2(backup_path, working_copy_path)
            LOG.info("⚡ Working copy created at %s", working_copy_path)

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

    LOG.info("⚡ Queued %s ops updates for '%s'", len(updates), args.target_field)
    if not updates:
        LOG.info("⚡ No updates needed. Data is already in sync.")
        return 0

    if args.dry_run:
        LOG.info("⚡ Dry run mode enabled. No updates sent.")
        return 0

    client.update_records(table=table, updates=updates)
    LOG.info("⚡ Applied %s updates to Airtable.", len(updates))
    return 0


def cmd_backup_table(args: argparse.Namespace) -> int:
    token = env_or_required(args.token, "AIRTABLE_PAT", "--token")
    base_id = env_or_required(args.base_id, "AIRTABLE_BASE_ID", "--base-id")
    table = env_or_required(args.table, "AIRTABLE_TABLE", "--table")

    client = AirtableClient(token=token, base_id=base_id)
    resolved_name = client.resolve_table_name(table)
    automation_name = automation_table_name(resolved_name, args.table_name_prefix, args.table_name_suffix)
    LOG.info("⚡ Backing up table=%s view=%s", table, args.view or "<all>")
    LOG.info("⚡ Automation table label: %s", automation_name)
    records = client.list_records(table=table, view=args.view)
    ts = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = Path(args.backup_dir) / f"{slugify(automation_name)}_{ts}"
    backup_paths = write_backups_for_format(
        output_dir=backup_dir,
        table_name=slugify(automation_name),
        records=records,
        output_format=args.output_format,
    )
    for backup_path in backup_paths:
        LOG.info("⚡ Table backup complete: %s (%s records)", backup_path, len(records))
    if args.working_copy:
        for backup_path in backup_paths:
            working_copy_path = backup_path.with_name(f"{backup_path.stem}.working{backup_path.suffix}")
            shutil.copy2(backup_path, working_copy_path)
            LOG.info("⚡ Working copy created at %s", working_copy_path)
    return 0


def cmd_snapshot_base(args: argparse.Namespace) -> int:
    token = env_or_required(args.token, "AIRTABLE_PAT", "--token")
    base_id = env_or_required(args.base_id, "AIRTABLE_BASE_ID", "--base-id")
    client = AirtableClient(token=token, base_id=base_id)

    ts = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    snapshot_dir = Path(args.backup_dir) / f"base_snapshot_{base_id}_{ts}"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    LOG.info("⚡ Fetching table list for base=%s", base_id)
    tables = client.list_tables()
    if args.include:
        include_set = {name.strip() for name in args.include.split(",") if name.strip()}
        tables = [t for t in tables if t.get("name") in include_set or t.get("id") in include_set]

    if not tables:
        LOG.warning("No tables matched snapshot filter.")
        return 0

    manifest: list[dict[str, Any]] = []
    for table_meta in tables:
        table_name = table_meta.get("name") or table_meta.get("id")
        table_id = table_meta.get("id")
        if not table_name or not table_id:
            continue

        LOG.info("⚡ Snapshotting table %s (%s)", table_name, table_id)
        records = client.list_records(table=table_id, view=args.view)
        table_slug = slugify(table_name)
        table_paths = write_backups_for_format(
            output_dir=snapshot_dir,
            table_name=table_slug,
            records=records,
            output_format=args.output_format,
        )
        manifest.append(
            {
                "table_name": table_name,
                "table_id": table_id,
                "record_count": len(records),
                "backup_files": [path.name for path in table_paths],
            }
        )

    manifest_path = snapshot_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    LOG.info("⚡ Base snapshot complete: %s (%s tables)", snapshot_dir, len(manifest))
    return 0


def cmd_snapshot_base_if_stale(args: argparse.Namespace) -> int:
    backup_root = Path(args.backup_dir)
    backup_root.mkdir(parents=True, exist_ok=True)

    latest_mtime = 0.0
    for path in backup_root.glob("base_snapshot_*"):
        if path.is_dir():
            latest_mtime = max(latest_mtime, path.stat().st_mtime)

    now = time.time()
    max_age_seconds = args.max_age_minutes * 60
    age_seconds = now - latest_mtime if latest_mtime else None

    if age_seconds is not None and age_seconds < max_age_seconds:
        LOG.info(
            "⚡ Snapshot is fresh (%s min old). Skipping.",
            round(age_seconds / 60, 1),
        )
        return 0

    LOG.info("⚡ Snapshot is stale or missing. Running snapshot now.")
    return cmd_snapshot_base(args)


def cmd_split_csv_by_artist(args: argparse.Namespace) -> int:
    token = env_or_required(args.token, "AIRTABLE_PAT", "--token")
    base_id = env_or_required(args.base_id, "AIRTABLE_BASE_ID", "--base-id")
    table = env_or_required(args.table, "AIRTABLE_TABLE", "--table")

    client = AirtableClient(token=token, base_id=base_id)
    LOG.info("⚡ Loading records for per-artist CSV split: table=%s", table)
    records = client.list_records(table=table, view=args.view)

    out_root = Path(args.output_dir)
    ts = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    split_dir = out_root / f"artist_split_{slugify(client.resolve_table_name(table))}_{ts}"
    split_dir.mkdir(parents=True, exist_ok=True)

    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        fields = record.get("fields", {})
        display_artist = extract_group_label(fields.get(args.artist_name_field))
        raw_artist = fields.get(args.artist_field)
        grouped_artist = extract_group_label(raw_artist)

        artist_label = display_artist or grouped_artist or args.unknown_artist_label
        if isinstance(artist_label, str) and artist_label.startswith("rec") and display_artist:
            artist_label = display_artist
        grouped.setdefault(artist_label, []).append(record)

    if args.print_friendly:
        field_specs: list[tuple[str, str]] = [
            ("Artist [Stage Name]", "Artist"),
            ("Credential Name", "Credential Name"),
            ("Credential Type", "Credential Type"),
            ("Role", "Role"),
            ("Parking Passes Requested", "Parking Passes"),
            ("Legal Names", "Legal Name"),
            ("Date of Birth", "DOB"),
        ]

        if args.extra_fields:
            for name in [x.strip() for x in args.extra_fields.split(",") if x.strip()]:
                field_specs.append((name, name))

        headers = [label for _, label in field_specs]
        for artist_name, artist_records in sorted(grouped.items(), key=lambda kv: kv[0].lower()):
            file_name = f"TEAM_{slugify(artist_name)}"
            path = split_dir / f"{file_name}.csv"
            with path.open("w", encoding="utf-8", newline="") as fp:
                writer = csv.DictWriter(fp, fieldnames=headers)
                writer.writeheader()
                for record in artist_records:
                    fields = record.get("fields", {})
                    row: dict[str, Any] = {}
                    for src, label in field_specs:
                        value = fields.get(src, "")
                        if isinstance(value, list):
                            row[label] = ", ".join(str(v) for v in value)
                        elif isinstance(value, dict):
                            row[label] = json.dumps(value, ensure_ascii=False)
                        else:
                            row[label] = value
                    writer.writerow(row)
            LOG.info("⚡ Wrote %s records for %s -> %s", len(artist_records), artist_name, path.name)
    else:
        for artist_name, artist_records in sorted(grouped.items(), key=lambda kv: kv[0].lower()):
            file_name = f"TEAM_{slugify(artist_name)}"
            path = write_backup_csv(split_dir, file_name, artist_records)
            LOG.info("⚡ Wrote %s records for %s -> %s", len(artist_records), artist_name, path.name)

    LOG.info("⚡ Artist CSV split complete: %s (%s files)", split_dir, len(grouped))
    return 0


def cmd_split_local_csv(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    raw = input_path.read_text(encoding="utf-8-sig")
    try:
        dialect = csv.Sniffer().sniff(raw[:4096], delimiters=",\t;")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","

    reader = csv.DictReader(raw.splitlines(), delimiter=delimiter)
    if not reader.fieldnames:
        raise SystemExit("Input CSV has no headers")

    artist_col = args.artist_column
    if artist_col not in reader.fieldnames:
        raise SystemExit(
            f"Artist column '{artist_col}' not found. Available: {', '.join(reader.fieldnames)}"
        )

    keep_columns = reader.fieldnames
    if args.keep_columns:
        requested = [c.strip() for c in args.keep_columns.split(",") if c.strip()]
        missing = [c for c in requested if c not in reader.fieldnames]
        if missing:
            raise SystemExit(f"Requested keep columns not found: {', '.join(missing)}")
        keep_columns = requested

    rows_by_artist: dict[str, list[dict[str, Any]]] = {}
    for row in reader:
        artist_name = (row.get(artist_col) or "").strip() or args.unknown_artist_label
        slim_row = {k: row.get(k, "") for k in keep_columns}
        rows_by_artist.setdefault(artist_name, []).append(slim_row)

    ts = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.output_dir) / f"artist_packets_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    for artist_name, rows in sorted(rows_by_artist.items(), key=lambda kv: kv[0].lower()):
        filename = f"TEAM_{slugify(artist_name)}.csv"
        out_path = out_dir / filename
        with out_path.open("w", encoding="utf-8", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=keep_columns)
            writer.writeheader()
            writer.writerows(rows)
        LOG.info("⚡ Wrote %s rows for %s -> %s", len(rows), artist_name, out_path.name)

    LOG.info("⚡ Local split complete: %s (%s files)", out_dir, len(rows_by_artist))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LIB ⚡ OPS CLI ⚡")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--token", help="Airtable PAT. Defaults to AIRTABLE_PAT")
    common.add_argument("--base-id", help="Airtable base id. Defaults to AIRTABLE_BASE_ID")
    common.add_argument("--table", help="Airtable table name or id. Defaults to AIRTABLE_TABLE")
    common.add_argument("--view", help="Airtable view name (optional)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    check_cmd = subparsers.add_parser("check-access", parents=[common], help="Verify LIB ops Airtable access")
    check_cmd.set_defaults(func=cmd_check_access)

    fill_cmd = subparsers.add_parser(
        "fill-group-column",
        parents=[common],
        help="Backfill an ops field from a source grouping field",
    )
    fill_cmd.add_argument("--source-field", required=True, help="Field containing group/linked value")
    fill_cmd.add_argument("--target-field", required=True, help="Field to populate")
    fill_cmd.add_argument(
        "--backup-dir",
        default="backups",
        help="Directory to store backup files (default: backups)",
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
    fill_cmd.add_argument(
        "--working-copy",
        action="store_true",
        help="Create an extra .working copy next to each safety backup file",
    )
    fill_cmd.add_argument(
        "--output-format",
        choices=["csv", "json", "both"],
        default="both",
        help="Backup output format (default: both)",
    )
    fill_cmd.add_argument(
        "--table-name-prefix",
        default="",
        help="Prefix for automation backup naming (default: empty)",
    )
    fill_cmd.add_argument(
        "--table-name-suffix",
        default="_automation",
        help="Suffix for automation backup naming (default: _automation)",
    )
    fill_cmd.set_defaults(func=cmd_fill_group_column)

    backup_cmd = subparsers.add_parser(
        "backup-table",
        parents=[common],
        help="Create a single-table backup CSV",
    )
    backup_cmd.add_argument(
        "--backup-dir",
        default="backups",
        help="Directory to store backup files (default: backups)",
    )
    backup_cmd.add_argument(
        "--working-copy",
        action="store_true",
        help="Create an extra .working copy next to each backup file",
    )
    backup_cmd.add_argument(
        "--output-format",
        choices=["csv", "json", "both"],
        default="both",
        help="Backup output format (default: both)",
    )
    backup_cmd.add_argument(
        "--table-name-prefix",
        default="",
        help="Prefix for automation backup naming (default: empty)",
    )
    backup_cmd.add_argument(
        "--table-name-suffix",
        default="_automation",
        help="Suffix for automation backup naming (default: _automation)",
    )
    backup_cmd.set_defaults(func=cmd_backup_table)

    snapshot_cmd = subparsers.add_parser(
        "snapshot-base",
        parents=[common],
        help="Create a full base snapshot of all tables",
    )
    snapshot_cmd.add_argument(
        "--backup-dir",
        default="backups",
        help="Directory to store snapshot files (default: backups)",
    )
    snapshot_cmd.add_argument(
        "--include",
        help="Optional comma-separated table names/ids to snapshot",
    )
    snapshot_cmd.add_argument(
        "--output-format",
        choices=["csv", "json", "both"],
        default="both",
        help="Snapshot output format (default: both)",
    )
    snapshot_cmd.set_defaults(func=cmd_snapshot_base)

    snapshot_if_stale_cmd = subparsers.add_parser(
        "snapshot-base-if-stale",
        parents=[common],
        help="Run base snapshot only when older than threshold",
    )
    snapshot_if_stale_cmd.add_argument(
        "--backup-dir",
        default="backups",
        help="Directory to store snapshot files (default: backups)",
    )
    snapshot_if_stale_cmd.add_argument(
        "--include",
        help="Optional comma-separated table names/ids to snapshot",
    )
    snapshot_if_stale_cmd.add_argument(
        "--output-format",
        choices=["csv", "json", "both"],
        default="both",
        help="Snapshot output format (default: both)",
    )
    snapshot_if_stale_cmd.add_argument(
        "--max-age-minutes",
        type=int,
        default=60,
        help="Only snapshot if older than this many minutes (default: 60)",
    )
    snapshot_if_stale_cmd.set_defaults(func=cmd_snapshot_base_if_stale)

    split_cmd = subparsers.add_parser(
        "split-artist-csv",
        parents=[common],
        help="Split one table into one CSV per artist",
    )
    split_cmd.add_argument(
        "--artist-field",
        default="Artist",
        help="Field used to group records (default: Artist)",
    )
    split_cmd.add_argument(
        "--artist-name-field",
        default="Artist [Stage Name]",
        help="Field used for artist display name in filenames (default: Artist [Stage Name])",
    )
    split_cmd.add_argument(
        "--unknown-artist-label",
        default="unknown_artist",
        help="Fallback artist label when field is blank (default: unknown_artist)",
    )
    split_cmd.add_argument(
        "--output-dir",
        default="backups",
        help="Directory to store split CSV files (default: backups)",
    )
    split_cmd.add_argument(
        "--print-friendly",
        action="store_true",
        help="Use team-friendly filenames and simplified print headers",
    )
    split_cmd.add_argument(
        "--extra-fields",
        help="Optional comma-separated extra field names to include in print-friendly output",
    )
    split_cmd.set_defaults(func=cmd_split_csv_by_artist)

    split_local_cmd = subparsers.add_parser(
        "split-local-csv",
        help="Split a local cleaned CSV/TSV into one file per artist",
    )
    split_local_cmd.add_argument("--input", required=True, help="Path to cleaned CSV/TSV file")
    split_local_cmd.add_argument(
        "--artist-column",
        default="Artist [Stage Name]",
        help="Column used to split files (default: Artist [Stage Name])",
    )
    split_local_cmd.add_argument(
        "--keep-columns",
        help="Optional comma-separated columns to keep in output",
    )
    split_local_cmd.add_argument(
        "--unknown-artist-label",
        default="unknown_artist",
        help="Fallback label when artist is blank",
    )
    split_local_cmd.add_argument(
        "--output-dir",
        default="backups",
        help="Directory to store split files (default: backups)",
    )
    split_local_cmd.set_defaults(func=cmd_split_local_csv)

    return parser


def main() -> None:
    load_dotenv()
    parser = build_parser()
    if len(sys.argv) == 1:
        print(load_banner())
        parser.print_help()
        raise SystemExit(0)

    if "-h" in sys.argv[1:] or "--help" in sys.argv[1:]:
        print(load_banner())
    args = parser.parse_args()
    configure_logging(verbose=args.verbose)
    LOG.info("\n%s", load_banner(args.command))
    exit_code = args.func(args)
    raise SystemExit(exit_code)
