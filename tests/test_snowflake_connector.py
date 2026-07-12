"""Validation-level tests for the Snowflake connector (no live connection)."""

import pytest

from connectors.snowflake_connector import SnowflakeConfigError, SnowflakeDataSource

BASE = {
    "account": "myorg-myaccount",
    "user": "me@example.com",
    "warehouse": "WH",
    "load_env": False,
}


@pytest.fixture(autouse=True)
def _no_ambient_snowflake_env(monkeypatch):
    for var in (
        "SNOWFLAKE_ACCOUNT",
        "SNOWFLAKE_USER",
        "SNOWFLAKE_PASSWORD",
        "SNOWFLAKE_PRIVATE_KEY_PATH",
        "SNOWFLAKE_PRIVATE_KEY_PASSPHRASE",
        "SNOWFLAKE_AUTHENTICATOR",
        "SNOWFLAKE_WAREHOUSE",
        "SNOWFLAKE_DATABASE",
        "SNOWFLAKE_SCHEMA",
        "SNOWFLAKE_ROLE",
    ):
        monkeypatch.delenv(var, raising=False)


def test_password_auth_requires_a_secret():
    with pytest.raises(SnowflakeConfigError, match="password or private_key_path"):
        SnowflakeDataSource(table="ORDERS", **BASE)


def test_sso_needs_no_password():
    src = SnowflakeDataSource(table="ORDERS", authenticator="externalbrowser", **BASE)
    kwargs = src._build_connect_kwargs()
    assert kwargs["authenticator"] == "externalbrowser"
    assert "password" not in kwargs
    assert "private_key" not in kwargs


def test_sso_authenticator_is_case_insensitive():
    src = SnowflakeDataSource(table="ORDERS", authenticator="ExternalBrowser", **BASE)
    assert "password" not in src._build_connect_kwargs()


def test_native_okta_still_requires_password():
    with pytest.raises(SnowflakeConfigError, match="password or private_key_path"):
        SnowflakeDataSource(
            table="ORDERS", authenticator="https://myorg.okta.com", **BASE
        )


def test_password_never_in_describe_or_repr():
    src = SnowflakeDataSource(table="ORDERS", password="s3cret!", **BASE)
    assert "s3cret" not in src.describe()
    assert "s3cret" not in repr(src)


def test_authenticator_shown_in_describe():
    src = SnowflakeDataSource(table="ORDERS", authenticator="externalbrowser", **BASE)
    assert "externalbrowser" in src.describe()
