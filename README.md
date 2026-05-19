# Airtable Ops Automation

Safety-first Airtable automation for ops workflows.

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
uv run airtable-ops-automation check-access --view "Grid view"
```

## Fill group name into another column

This copies values from a source field (often the same field used to group a view)
into a target field.

Dry run first (non-destructive):

```bash
uv run airtable-ops-automation fill-group-column \
  --view "Grid view" \
  --source-field "Subtable / Group Field" \
  --target-field "Group Name" \
  --only-blank \
  --dry-run
```

Apply changes:

```bash
uv run airtable-ops-automation fill-group-column \
  --view "Grid view" \
  --source-field "Subtable / Group Field" \
  --target-field "Group Name" \
  --only-blank
```

## Backups

Every `fill-group-column` run writes a JSON backup before any updates:

- `backups/<table>_<timestamp>/<table>.json`

Keep these backups in git-ignored local storage or sync to your internal backup location.

## Recommended safe rollout

1. Duplicate your Airtable table/base for testing.
2. Run `check-access` against the test copy.
3. Run `fill-group-column --dry-run` and inspect logs + backup JSON.
4. Run apply mode on test copy.
5. Validate records, then run same command on production table.
