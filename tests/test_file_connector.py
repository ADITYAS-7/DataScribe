from pathlib import Path

import pandas as pd
import pytest

from connectors.file_connector import FileDataSource

SAMPLE_DIR = Path(__file__).parent / "sample_data"


def test_csv_headers_are_stripped():
    source = FileDataSource(SAMPLE_DIR / "messy_customers.csv")
    df = source.fetch()
    assert list(df.columns) == ["customer_id", "customer_name", "signup_date", "zip_code"]


def test_csv_string_cells_are_stripped():
    source = FileDataSource(SAMPLE_DIR / "messy_customers.csv")
    df = source.fetch()
    assert df["customer_name"].tolist() == ["John Doe", "Jane Roe", "Sam Lee"]


def test_csv_date_column_is_inferred():
    source = FileDataSource(SAMPLE_DIR / "messy_customers.csv")
    df = source.fetch()
    assert pd.api.types.is_datetime64_any_dtype(df["signup_date"])


def test_zip_code_not_misinterpreted_as_date():
    source = FileDataSource(SAMPLE_DIR / "messy_customers.csv")
    df = source.fetch()
    # zip codes are plain numeric strings and must NOT be coerced to dates
    assert not pd.api.types.is_datetime64_any_dtype(df["zip_code"])
    assert df["zip_code"].tolist() == [2139, 10001, 94107]


def test_excel_round_trip(tmp_path):
    original = pd.DataFrame(
        {
            " Order ID ": [1, 2],
            "Amount": [10.5, 20.25],
        }
    )
    xlsx_path = tmp_path / "sample.xlsx"
    original.to_excel(xlsx_path, index=False)

    source = FileDataSource(xlsx_path)
    df = source.fetch()
    assert list(df.columns) == ["Order ID", "Amount"]
    assert df["Amount"].tolist() == [10.5, 20.25]


def test_unsupported_extension_raises(tmp_path):
    bad_path = tmp_path / "data.json"
    bad_path.write_text("{}")
    with pytest.raises(ValueError):
        FileDataSource(bad_path)
