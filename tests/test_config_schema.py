from pathlib import Path

import pytest
from pydantic import ValidationError

from core.config_schema import (
    FileSource,
    ReconJobConfig,
    SnowflakeSource,
    build_data_source,
    load_job,
)
from core.job_runner import run_job

PROJECT_ROOT = Path(__file__).parent.parent
EXAMPLE_JOB = PROJECT_ROOT / "config" / "example_job.yaml"


def test_example_job_loads_and_validates():
    job = load_job(EXAMPLE_JOB)
    assert job.name == "orders-recon-example"
    assert isinstance(job.source, FileSource)
    assert job.key_columns == ["order_id"]
    assert job.column_mapping["amount"] == "Amt"
    assert job.engine_rules()["amount"] == {"tolerance": 0.01}
    assert job.engine_rules()["customer_name"] == {"case_insensitive": True}


def test_example_job_runs_end_to_end(monkeypatch):
    # example job uses paths relative to the project root
    monkeypatch.chdir(PROJECT_ROOT)
    result = run_job(EXAMPLE_JOB)
    assert result.summary["matched"] == 2
    assert result.summary["mismatched"] == 2
    assert result.summary["missing_in_target"] == 1
    assert result.summary["missing_in_source"] == 1


def test_snowflake_source_requires_table_xor_query():
    with pytest.raises(ValidationError, match="exactly one"):
        SnowflakeSource(type="snowflake")
    with pytest.raises(ValidationError, match="exactly one"):
        SnowflakeSource(type="snowflake", table="T", query="SELECT 1")
    ok = SnowflakeSource(type="snowflake", table="ORDERS", schema="PUBLIC")
    assert ok.schema_ == "PUBLIC"


def test_column_rules_must_reference_mapped_columns():
    with pytest.raises(ValidationError, match="not in column_mapping"):
        ReconJobConfig(
            name="bad",
            source={"type": "csv", "path": "a.csv"},
            target={"type": "csv", "path": "b.csv"},
            key_columns=["id"],
            column_mapping={"id": "id"},
            column_rules={"nonexistent": {"tolerance": 1}},
        )


def test_discriminator_rejects_unknown_type():
    with pytest.raises(ValidationError):
        ReconJobConfig(
            name="bad",
            source={"type": "parquet", "path": "a.parquet"},
            target={"type": "csv", "path": "b.csv"},
            key_columns=["id"],
            column_mapping={"id": "id"},
        )


def test_build_data_source_for_file():
    src = build_data_source(FileSource(type="csv", path="tests/sample_data/source_orders.csv"))
    assert src.file_type == "csv"
