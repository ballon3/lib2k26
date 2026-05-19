# lib2k26

```text
   __    __  ___    ___      ___    
  / /   / / / o.)  /_  ) /7 /_  ),'7
 / /_  / / / o \   ,'c' //_7,'c'/o \
/___/ /_/ /___,'  (___7//\\(___7|_,'
                                    
```

LIGHTING IN A BOTTLE - ⚡

Lightning in a Bottle Ops automation for credential and camp workflows. ⚡

## Setup

```bash
uv sync
```

Set env vars (recommended):

```bash
export AIRTABLE_PAT="pat..."
export AIRTABLE_BASE_ID="app..."
export AIRTABLE_TABLE="Your Table"
```

## Verify API access

```bash
uv run lib2k26 check-access --view "Grid view"
```

## Backup a single table (safe first step)

```bash
uv run lib2k26 backup-table \
  --table "Credentials_automation" \
  --working-copy
```

By default, backups write both `CSV` and `JSON`. You can override:

```bash
uv run lib2k26 backup-table --table "Credentials_automation" --output-format csv
uv run lib2k26 backup-table --table "Credentials_automation" --output-format json
uv run lib2k26 backup-table --table "Credentials_automation" --output-format both
```

If `--table` is a table id (for example `tbl...`), backup files are named using
the resolved table name plus `_automation` by default. Customize with:

- `--table-name-prefix`
- `--table-name-suffix`

## Snapshot an entire base

```bash
uv run lib2k26 snapshot-base
```

Optional filter for specific tables:

```bash
uv run lib2k26 snapshot-base --include "Credentials_automation,Artists"
```

## Fill group name into another column

This copies values from a source field (often the same field used to group a view)
into a target field.

Dry run first (non-destructive):

```bash
uv run lib2k26 fill-group-column \
  --view "Grid view" \
  --source-field "Subtable / Group Field" \
  --target-field "Group Name" \
  --only-blank \
  --dry-run
```

Apply changes:

```bash
uv run lib2k26 fill-group-column \
  --view "Grid view" \
  --source-field "Subtable / Group Field" \
  --target-field "Group Name" \
  --only-blank
```

## Backups

Every `fill-group-column` run writes CSV + JSON backups before any updates (default):

- `backups/<table>_<timestamp>/<table>.csv`
- `backups/<table>_<timestamp>/<table>.json`

Keep these backups in git-ignored local storage or sync to your internal backup location.

## Recommended safe rollout

1. Duplicate your Airtable table/base for testing.
2. Run `check-access` against the test copy.
3. Run `fill-group-column --dry-run` and inspect logs + backup CSV.
4. Run apply mode on test copy.
5. Validate records, then run same command on production table.
