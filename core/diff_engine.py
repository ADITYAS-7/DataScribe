"""Vectorized source-vs-target reconciliation engine.

The public entry point is :func:`compare_datasets`, which takes two
DataFrames plus a key/column mapping and returns a :class:`ReconResult`
with matched/mismatched/missing breakdowns. Everything is done with
pandas merge + boolean masks (no row-by-row Python loops) so it scales to
reasonably large datasets.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

ColumnRule = dict  # e.g. {"tolerance": 0.01} / {"case_insensitive": True} / {"date_only": True}


class ReconError(ValueError):
    """Raised for invalid recon inputs (bad mapping, duplicate keys, ...)."""


@dataclass
class ReconResult:
    matched_count: int
    mismatched_rows: pd.DataFrame
    missing_in_target: pd.DataFrame
    missing_in_source: pd.DataFrame
    summary: dict = field(default_factory=dict)

    @property
    def mismatched_count(self) -> int:
        return len(self.mismatched_rows)

    @property
    def missing_in_target_count(self) -> int:
        return len(self.missing_in_target)

    @property
    def missing_in_source_count(self) -> int:
        return len(self.missing_in_source)

    def to_excel(self, path: str) -> None:
        """Write a multi-sheet report: Summary, Mismatches, Missing In Target/Source."""
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            pd.DataFrame([self.summary]).to_excel(writer, sheet_name="Summary", index=False)
            self.mismatched_rows.to_excel(writer, sheet_name="Mismatches", index=False)
            self.missing_in_target.to_excel(writer, sheet_name="Missing In Target", index=False)
            self.missing_in_source.to_excel(writer, sheet_name="Missing In Source", index=False)


def compare_datasets(
    source_df: pd.DataFrame,
    target_df: pd.DataFrame,
    key_columns: list[str],
    column_mapping: dict[str, str],
    column_rules: dict[str, ColumnRule] | None = None,
) -> ReconResult:
    """Compare ``source_df`` against ``target_df``.

    Args:
        source_df: source dataset.
        target_df: target dataset.
        key_columns: source-side column names forming the unique row key
            (composite keys supported — pass multiple names).
        column_mapping: source column name -> target column name. Must
            cover every column you want compared, including key columns
            whose name differs between source and target. Key columns
            with an identical name in both frames may be omitted.
        column_rules: optional per-source-column comparison rules:
            - {"tolerance": 0.01} and/or {"rel_tolerance": 0.001} -> numeric
              compare within absolute/relative tolerance.
            - {"case_insensitive": True} -> case/whitespace-insensitive
              string compare.
            - {"date_only": True} -> compare calendar date, ignoring time.
            - {"date_format": "%Y-%m-%d"} -> normalize both sides to this
              strftime format before comparing.
            Columns without a rule are compared with exact equality
            (NaN == NaN counts as a match).

    Returns:
        ReconResult with matched/mismatched/missing breakdowns.
    """
    column_rules = column_rules or {}
    column_mapping = _fill_identity_key_mappings(key_columns, column_mapping, source_df, target_df)
    _validate_inputs(source_df, target_df, key_columns, column_mapping)

    compare_columns = [c for c in column_mapping if c not in key_columns]

    source_canon = source_df[list(column_mapping.keys())].copy()
    target_canon = target_df[list(column_mapping.values())].rename(
        columns={v: k for k, v in column_mapping.items()}
    )

    _assert_unique_keys(source_canon, key_columns, "source")
    _assert_unique_keys(target_canon, key_columns, "target")

    merged = pd.merge(
        source_canon,
        target_canon,
        on=key_columns,
        how="outer",
        suffixes=("_source", "_target"),
        indicator=True,
    )

    missing_in_target = merged[merged["_merge"] == "left_only"]
    missing_in_source = merged[merged["_merge"] == "right_only"]
    both = merged[merged["_merge"] == "both"]

    missing_in_target = _select_side(missing_in_target, key_columns, compare_columns, "source")
    missing_in_source = _select_side(missing_in_source, key_columns, compare_columns, "target")

    match_masks = {}
    for col in compare_columns:
        rule = column_rules.get(col)
        match_masks[col] = _compare_series(
            both[f"{col}_source"], both[f"{col}_target"], rule
        )

    if compare_columns:
        overall_match = np.logical_and.reduce(
            [match_masks[c].to_numpy() for c in compare_columns]
        )
    else:
        overall_match = np.ones(len(both), dtype=bool)

    matched = both[overall_match]
    mismatched = both[~overall_match].copy()

    for col in compare_columns:
        mismatched[f"{col}_match"] = match_masks[col][~overall_match].to_numpy()

    if len(mismatched) and compare_columns:
        match_cols = [f"{c}_match" for c in compare_columns]
        mismatched["differing_columns"] = mismatched[match_cols].apply(
            lambda row: [c for c, m in zip(compare_columns, row) if not m], axis=1
        )
    else:
        mismatched["differing_columns"] = [[] for _ in range(len(mismatched))]

    output_cols = (
        key_columns
        + [f"{c}_source" for c in compare_columns]
        + [f"{c}_target" for c in compare_columns]
        + ["differing_columns"]
    )
    mismatched_rows = mismatched[output_cols].reset_index(drop=True)

    matched_count = len(matched)
    summary = {
        "total_source_rows": len(source_df),
        "total_target_rows": len(target_df),
        "matched": matched_count,
        "mismatched": len(mismatched_rows),
        "missing_in_target": len(missing_in_target),
        "missing_in_source": len(missing_in_source),
        "match_rate": (matched_count / len(both)) if len(both) else None,
    }

    return ReconResult(
        matched_count=matched_count,
        mismatched_rows=mismatched_rows,
        missing_in_target=missing_in_target.reset_index(drop=True),
        missing_in_source=missing_in_source.reset_index(drop=True),
        summary=summary,
    )


def _fill_identity_key_mappings(
    key_columns: list[str],
    column_mapping: dict[str, str],
    source_df: pd.DataFrame,
    target_df: pd.DataFrame,
) -> dict[str, str]:
    """Auto-add source->target identity entries for key columns the caller omitted."""
    column_mapping = dict(column_mapping)
    for key in key_columns:
        if key not in column_mapping:
            if key in source_df.columns and key in target_df.columns:
                column_mapping[key] = key
    return column_mapping


def _validate_inputs(
    source_df: pd.DataFrame,
    target_df: pd.DataFrame,
    key_columns: list[str],
    column_mapping: dict[str, str],
) -> None:
    if not key_columns:
        raise ReconError("key_columns must contain at least one column.")

    missing_keys = [k for k in key_columns if k not in column_mapping]
    if missing_keys:
        raise ReconError(
            f"key_columns {missing_keys} are not in column_mapping and have no "
            "identically-named column in both source and target. Add them to "
            "column_mapping explicitly."
        )

    missing_source_cols = [c for c in column_mapping if c not in source_df.columns]
    if missing_source_cols:
        raise ReconError(f"column_mapping references missing source columns: {missing_source_cols}")

    missing_target_cols = [c for c in column_mapping.values() if c not in target_df.columns]
    if missing_target_cols:
        raise ReconError(f"column_mapping references missing target columns: {missing_target_cols}")

    target_values = list(column_mapping.values())
    dupes = {v for v in target_values if target_values.count(v) > 1}
    if dupes:
        raise ReconError(f"column_mapping maps multiple source columns to the same target column: {dupes}")


def _assert_unique_keys(df: pd.DataFrame, key_columns: list[str], label: str) -> None:
    dupe_mask = df.duplicated(subset=key_columns, keep=False)
    if dupe_mask.any():
        sample = df.loc[dupe_mask, key_columns].drop_duplicates().head(5).to_dict("records")
        raise ReconError(
            f"{label} dataset has {dupe_mask.sum()} rows with duplicate keys "
            f"{key_columns}. Recon requires unique keys per side. Example duplicate "
            f"key(s): {sample}"
        )


def _select_side(
    df: pd.DataFrame, key_columns: list[str], compare_columns: list[str], side: str
) -> pd.DataFrame:
    cols = key_columns + [f"{c}_{side}" for c in compare_columns]
    out = df[cols].copy()
    return out.rename(columns={f"{c}_{side}": c for c in compare_columns})


def _eq_with_nan(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a == b) | (a.isna() & b.isna())


def _compare_series(s_source: pd.Series, s_target: pd.Series, rule: ColumnRule | None) -> pd.Series:
    rule = rule or {}

    if "tolerance" in rule or "rel_tolerance" in rule:
        a = pd.to_numeric(s_source, errors="coerce")
        b = pd.to_numeric(s_target, errors="coerce")
        atol = rule.get("tolerance", 0) or 0
        rtol = rule.get("rel_tolerance", 0) or 0
        close = np.isclose(a.to_numpy(dtype=float), b.to_numpy(dtype=float), atol=atol, rtol=rtol, equal_nan=True)
        return pd.Series(close, index=s_source.index)

    if rule.get("date_only") or rule.get("date_format"):
        a = pd.to_datetime(s_source, errors="coerce")
        b = pd.to_datetime(s_target, errors="coerce")
        if rule.get("date_only"):
            a, b = a.dt.date, b.dt.date
        else:
            fmt = rule["date_format"]
            a = a.dt.strftime(fmt).where(a.notna(), None)
            b = b.dt.strftime(fmt).where(b.notna(), None)
        return _eq_with_nan(pd.Series(a, index=s_source.index), pd.Series(b, index=s_target.index))

    if rule.get("case_insensitive"):
        a = s_source.mask(s_source.notna(), s_source.astype(str).str.strip().str.lower())
        b = s_target.mask(s_target.notna(), s_target.astype(str).str.strip().str.lower())
        return _eq_with_nan(a, b)

    return _eq_with_nan(s_source, s_target)
