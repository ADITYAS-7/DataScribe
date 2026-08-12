# DataScribe

Generic data reconciliation tool: compares a source dataset against a target
dataset (Snowflake tables, CSV, or Excel) and reports matches, mismatches,
and missing rows.

## Status

- **Phase 1 — Connectors**: done. `connectors/base.py` defines the
  `DataSource` interface; `connectors/file_connector.py` (CSV/Excel) and
  `connectors/snowflake_connector.py` (Snowflake) implement it.
- **Phase 2 — Diff engine**: done. `core/diff_engine.py` (`compare_datasets`)
  does vectorized key-based comparison with per-column rules.
- **Phase 3 — Config-driven jobs**: done. `core/config_schema.py` (pydantic
  models), `config/example_job.yaml` (runnable sample), and
  `core/job_runner.py` (CLI + programmatic runner).
- **Phase 4 — Streamlit UI**: done. `ui/app.py` — 5-step wizard with
  auto-suggested column mapping and Excel export.

## Running the UI

```
streamlit run ui/app.py
```

## Running a config-driven job (no UI)

```
python -m core.job_runner config/example_job.yaml --export report.xlsx
```

## Setup

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # fill in Snowflake credentials if using it
```

## Deploying to Streamlit in Snowflake (SiS)

SiS is the recommended production path: the app runs **inside** Snowflake and
reuses each viewer's already-authenticated Snowsight session, so corporate SSO
works with zero extra wiring and **no credentials or `.env` are deployed**. The
connector auto-detects the ambient Snowpark session and skips the credentials
path entirely (`connectors/snowflake_connector.py`), and the UI hides the
credentials form when it detects SiS (`ui/app.py`, `_in_sis()`).

### Prerequisites

- **Snowflake CLI** (`snow`): `pip install snowflake-cli-labs`, then configure a
  connection (`snow connection add`). For SSO, choose
  `authenticator=externalbrowser`.
- A **role with `CREATE STREAMLIT`** on the target database/schema.
- A **warehouse** you have `USAGE` on (used as the app's `query_warehouse`).
- A **database + schema** to host the Streamlit object and its stage.
- **`SELECT`** on the tables users will reconcile (this is the app's *runtime*
  privilege, separate from the deploy privilege above).

### One required edit

Set a real warehouse in `snowflake.yml`:

```yaml
query_warehouse: <WAREHOUSE_NAME>   # replace before deploying
```

Everything else in `snowflake.yml` is ready: it bundles `ui/`, `connectors/`,
`core/`, and `assets/`, and remaps `sis/environment.yml` → `environment.yml` at
the stage root.

### Dependencies in SiS

SiS installs packages from the **Snowflake Anaconda channel only** — not
`requirements.txt`. That list lives in `sis/environment.yml` (pandas, openpyxl,
pydantic, pyyaml, cryptography). It intentionally omits packages SiS provides
natively (`streamlit`, `snowflake-snowpark-python`) or that don't apply inside
Snowflake (`snowflake-connector-python`, `python-dotenv`).

> **Do not move `environment.yml` to the repo root.** A root-level copy makes
> Streamlit Community Cloud build the wrong env and the app fails to boot. It
> stays under `sis/`; `snowflake.yml` maps it back at deploy time.

### Deploy

```
snow connection test --connection <name>

snow streamlit deploy --replace \
  --database <APP_DB> --schema <APP_SCHEMA> --role <ROLE_WITH_CREATE_STREAMLIT>
```

`--replace` makes redeploys idempotent. On success `snow` prints the app URL;
the app also appears under **Projects → Streamlit** in Snowsight.

### Verify

- Open the app in Snowsight — it should load with **no credentials form**
  (confirms SiS session detection).
- Reconcile two tables you have `SELECT` on; confirm the summary and Excel
  export work.
- Have a second user open it to confirm SSO/session inheritance (they need
  `USAGE` on the Streamlit object and read access to the data).

### Notes / limitations

- The app runs with the **owner's rights** by default — the owner's role must be
  able to read every schema users reconcile.
- **Cross-account** Snowflake-to-Snowflake reconciliation isn't supported; both
  sides must be in the same account.
- SiS is the interactive UI only. Scheduled/unattended recon is a separate path
  (`run_job()` driven from Airflow/cron) and is not part of the SiS deployment.

## Running tests

```
pytest -v
```

## Quick example

```python
from connectors.file_connector import FileDataSource
from core.diff_engine import compare_datasets

source_df = FileDataSource("source.csv").fetch()
target_df = FileDataSource("target.xlsx").fetch()

result = compare_datasets(
    source_df, target_df,
    key_columns=["order_id"],
    column_mapping={
        "order_id": "OrderID",
        "amount": "Amt",
        "status": "Status",
    },
    column_rules={
        "amount": {"tolerance": 0.01},
    },
)

print(result.summary)
result.to_excel("recon_report.xlsx")
```

Snowflake works the same way — swap `FileDataSource` for `SnowflakeDataSource`:

```python
from connectors.snowflake_connector import SnowflakeDataSource

source_df = SnowflakeDataSource(table="ORDERS").fetch()          # full table
target_df = SnowflakeDataSource(query="SELECT * FROM ORDERS_V2").fetch()  # custom SQL
```

Credentials are read from environment variables (see `.env.example`) unless
passed explicitly to the constructor. Password/key material is never logged
or included in `repr()`.

## Column rules

Per-column comparison rules passed to `compare_datasets(column_rules=...)`:

| Rule | Effect |
|---|---|
| `{"tolerance": 0.01}` | numeric compare within absolute tolerance |
| `{"rel_tolerance": 0.001}` | numeric compare within relative tolerance |
| `{"case_insensitive": True}` | case/whitespace-insensitive string compare |
| `{"date_only": True}` | compare calendar date, ignoring time |
| `{"date_format": "%Y-%m-%d"}` | normalize both sides to this format before comparing |

Columns without a rule are compared with exact equality (`NaN == NaN` counts
as a match).
