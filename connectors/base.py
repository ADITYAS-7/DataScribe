"""Shared interface for all data sources (Snowflake, CSV, Excel, ...)."""

from abc import ABC, abstractmethod

import pandas as pd


class DataSource(ABC):
    """Common contract every connector must implement.

    Anything that can produce a pandas DataFrame representing a dataset
    (a Snowflake table/query, a CSV file, an Excel sheet, ...) implements
    this interface so the diff engine and UI never need to know which
    concrete source they're dealing with.
    """

    @abstractmethod
    def fetch(self) -> pd.DataFrame:
        """Return the dataset as a pandas DataFrame."""
        raise NotImplementedError

    def describe(self) -> str:
        """Human-readable description of this source, for logs/UI display."""
        return self.__class__.__name__
