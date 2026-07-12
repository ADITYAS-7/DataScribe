"""Pydantic models describing a reconciliation job.

A recon job is fully described by a YAML/JSON document: where the source
and target datasets live, which columns form the key, how source columns
map to target columns, and any per-column comparison rules. This is what
makes the tool generic instead of hardcoded per client.

Load a job with :func:`load_job` and turn its source/target definitions
into connectors with :func:`build_data_source`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Union

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from connectors.base import DataSource
from connectors.file_connector import FileDataSource
from connectors.snowflake_connector import SnowflakeDataSource


class ColumnRule(BaseModel):
    """Per-column comparison rule. All fields optional; combine as needed."""

    tolerance: float | None = Field(
        default=None, ge=0, description="Absolute numeric tolerance."
    )
    rel_tolerance: float | None = Field(
        default=None, ge=0, description="Relative numeric tolerance."
    )
    case_insensitive: bool = Field(
        default=False, description="Case/whitespace-insensitive string compare."
    )
    date_only: bool = Field(
        default=False, description="Compare calendar date, ignoring time."
    )
    date_format: str | None = Field(
        default=None, description="Normalize both sides to this strftime format."
    )

    def to_engine_rule(self) -> dict:
        """Convert to the plain dict format ``compare_datasets`` expects."""
        rule: dict = {}
        if self.tolerance is not None:
            rule["tolerance"] = self.tolerance
        if self.rel_tolerance is not None:
            rule["rel_tolerance"] = self.rel_tolerance
        if self.case_insensitive:
            rule["case_insensitive"] = True
        if self.date_only:
            rule["date_only"] = True
        if self.date_format:
            rule["date_format"] = self.date_format
        return rule


class SnowflakeSource(BaseModel):
    """A Snowflake table or query. Credentials come from env vars/.env —
    never from the job file."""

    type: Literal["snowflake"]
    table: str | None = None
    query: str | None = None
    # Optional per-job overrides of the env-var connection context.
    database: str | None = None
    schema_: str | None = Field(default=None, alias="schema")
    warehouse: str | None = None
    role: str | None = None
    authenticator: str | None = Field(
        default=None,
        description='e.g. "externalbrowser" for workplace SSO via the browser.',
    )

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _table_xor_query(self) -> "SnowflakeSource":
        if bool(self.table) == bool(self.query):
            raise ValueError("Specify exactly one of 'table' or 'query'.")
        return self


class FileSource(BaseModel):
    """A CSV or Excel file on disk."""

    type: Literal["csv", "excel"]
    path: str
    sheet_name: str | int = Field(
        default=0, description="Excel only: sheet name or index."
    )

    @field_validator("path")
    @classmethod
    def _path_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("path must not be empty")
        return v


SourceConfig = Union[SnowflakeSource, FileSource]


class ReconJobConfig(BaseModel):
    """Complete definition of one reconciliation job."""

    name: str = Field(description="Human-readable job name.")
    source: SourceConfig = Field(discriminator="type")
    target: SourceConfig = Field(discriminator="type")
    key_columns: list[str] = Field(
        min_length=1, description="Source-side column names forming the unique key."
    )
    column_mapping: dict[str, str] = Field(
        description="Source column name -> target column name."
    )
    column_rules: dict[str, ColumnRule] = Field(
        default_factory=dict,
        description="Optional per-source-column comparison rules.",
    )

    @model_validator(mode="after")
    def _rules_reference_mapped_columns(self) -> "ReconJobConfig":
        unknown = [c for c in self.column_rules if c not in self.column_mapping]
        if unknown:
            raise ValueError(
                f"column_rules reference columns not in column_mapping: {unknown}"
            )
        return self

    def engine_rules(self) -> dict[str, dict]:
        """Column rules in the plain-dict form ``compare_datasets`` expects."""
        return {
            col: rule.to_engine_rule()
            for col, rule in self.column_rules.items()
            if rule.to_engine_rule()
        }


def build_data_source(config: SourceConfig) -> DataSource:
    """Instantiate the right connector for a source/target config block."""
    if isinstance(config, SnowflakeSource):
        return SnowflakeDataSource(
            table=config.table,
            query=config.query,
            database=config.database,
            schema=config.schema_,
            warehouse=config.warehouse,
            role=config.role,
            authenticator=config.authenticator,
        )
    if isinstance(config, FileSource):
        return FileDataSource(config.path, sheet_name=config.sheet_name)
    raise TypeError(f"Unsupported source config: {type(config).__name__}")


def load_job(path: str | Path) -> ReconJobConfig:
    """Load and validate a recon job from a YAML file."""
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"Job file {path} must contain a YAML mapping at the top level.")
    return ReconJobConfig.model_validate(raw)
