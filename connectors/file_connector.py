"""CSV / Excel connector.

Loads tabular files into a pandas DataFrame and cleans up the common
gremlins that break key-based reconciliation: whitespace-padded headers,
whitespace-padded string cells, and dates that pandas left as plain
strings because a column had mixed formatting.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import IO

import pandas as pd

from connectors.base import DataSource

_DATE_INFER_SAMPLE_SIZE = 200
_DATE_INFER_MIN_SUCCESS_RATIO = 0.9
_PURE_NUMERIC_RE = re.compile(r"^\s*-?\d+(\.\d+)?\s*$")


class FileDataSource(DataSource):
    """Loads a CSV or Excel file into a DataFrame.

    ``path`` can be a filesystem path or a file-like object (e.g. a
    Streamlit ``UploadedFile``). When passing a file-like object without a
    ``.name`` attribute, pass ``file_type`` explicitly ("csv" or "excel").
    """

    def __init__(
        self,
        path: str | Path | IO,
        sheet_name: str | int | None = 0,
        file_type: str | None = None,
        infer_dates: bool = True,
        strip_whitespace: bool = True,
        dtype: dict | None = None,
    ):
        self.path = path
        self.sheet_name = sheet_name
        self.file_type = file_type or self._infer_file_type(path)
        self.infer_dates = infer_dates
        self.strip_whitespace = strip_whitespace
        self.dtype = dtype

    def describe(self) -> str:
        name = getattr(self.path, "name", self.path)
        return f"FileDataSource({name}, type={self.file_type})"

    def fetch(self) -> pd.DataFrame:
        if self.file_type == "csv":
            df = pd.read_csv(self.path, dtype=self.dtype)
        elif self.file_type == "excel":
            df = pd.read_excel(self.path, sheet_name=self.sheet_name, dtype=self.dtype)
        else:
            raise ValueError(
                f"Unsupported file_type '{self.file_type}'. Expected 'csv' or 'excel'."
            )

        df = self._clean_headers(df)
        if self.strip_whitespace:
            df = self._strip_string_cells(df)
        if self.infer_dates:
            df = self._infer_date_columns(df)
        return df

    @staticmethod
    def _infer_file_type(path: str | Path | IO) -> str:
        name = getattr(path, "name", path)
        suffix = Path(str(name)).suffix.lower()
        if suffix in (".csv", ".txt", ".tsv"):
            return "csv"
        if suffix in (".xlsx", ".xls", ".xlsm"):
            return "excel"
        raise ValueError(
            f"Could not infer file type from '{name}'. Pass file_type='csv' or 'excel' explicitly."
        )

    @staticmethod
    def _clean_headers(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df.columns = [str(c).strip() for c in df.columns]
        return df

    @staticmethod
    def _strip_string_cells(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        obj_cols = df.select_dtypes(include="object").columns
        for col in obj_cols:
            df[col] = df[col].apply(lambda v: v.strip() if isinstance(v, str) else v)
        return df

    @staticmethod
    def _infer_date_columns(df: pd.DataFrame) -> pd.DataFrame:
        """Promote object columns that look like dates to real datetimes.

        Only converts a column when a large majority of its non-null values
        parse successfully, so we don't accidentally mangle free-text
        columns that merely contain a few date-like tokens.
        """
        df = df.copy()
        obj_cols = df.select_dtypes(include="object").columns
        for col in obj_cols:
            sample = df[col].dropna().head(_DATE_INFER_SAMPLE_SIZE)
            if sample.empty:
                continue
            if sample.apply(lambda v: bool(_PURE_NUMERIC_RE.match(str(v)))).all():
                continue  # plain numeric strings (IDs, zip codes) aren't dates
            parsed_sample = pd.to_datetime(sample, errors="coerce", format="mixed")
            success_ratio = parsed_sample.notna().mean()
            if success_ratio >= _DATE_INFER_MIN_SUCCESS_RATIO:
                parsed_full = pd.to_datetime(df[col], errors="coerce", format="mixed")
                df[col] = parsed_full
        return df
