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
