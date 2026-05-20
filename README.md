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

## Reusable Google Sheet CSV -> Airtable flow

This flow is designed as a reusable config-driven command for new ops automations.

1. Export your Google Sheet tab as CSV and place it in this repo.
2. Copy `config/sheet_to_airtable.flow.example.json` to a new config file.
3. Update `source_csv`, `target_table`, and the `field_map` keys to match your sheet columns and Airtable fields.

Dry run (recommended first):

```bash
uv run lib2k26 sync-sheet-to-airtable \
  --config config/sheet_to_airtable.flow.example.json \
  --dry-run
```

Apply with target backup:

```bash
uv run lib2k26 sync-sheet-to-airtable \
  --config config/sheet_to_airtable.flow.example.json \
  --backup-target
```

Behavior:

- Enforces max vendor count per order key (`max_vendors`, default `2`).
- Skips invalid rows and logs warnings.
- Optional target-table backup before write.
- Creates one Airtable record per valid line item.

## React + FastAPI order app

If Google Forms is too limiting, use this lightweight stack:

- FastAPI backend reads menu options from `config/lib26_vendor_options.csv`
- React frontend enforces max 2 vendors and quantity per item
- Backend validates each item belongs to the selected vendor and writes to Airtable

### Environment

Set these in `.env`:

```bash
AIRTABLE_PAT="pat..."
AIRTABLE_BASE_ID="app..."
AIRTABLE_ORDER_TABLE="Artist Food Orders"
MENU_CSV_PATH="config/lib26_vendor_options.csv"
ORDER_API_HOST="0.0.0.0"
ORDER_API_PORT="8000"
```

### Run backend

```bash
uv sync
uv run lib2k26-api
```

### Run frontend

```bash
cd web/order-form
npm install
npm run dev
```

If your API is on a different host/port:

```bash
VITE_API_BASE="http://localhost:8000" npm run dev
```

### Core endpoints

- `GET /api/vendors`
- `GET /api/vendors/{vendor}/items`
- `POST /api/orders`

thurs,friday,saturday,sunday (start/end)
11/12am, 11/2am,11/3am,11/3am - Kaliko's Hawaiian Kitchen
9/11pm,9/2am,9/2am,9/2am, - Asana Foods - California Cuisine
24hr,24hr,24hr,24hr - Bombay Burritos
8/10pm,8/10pm,8/10pm,8/12am- Senor Corn - Lightning
9am/4am,9am/4am,9am/4am,9am/4am - Connection Cafe
11am/10pm,10am/12am,12am/12am,12am/12am - Stay Cheesy
