"""Validation-level tests for the Snowflake connector (no live connection)."""

import pandas as pd
import pytest

import connectors.snowflake_connector as sf_connector
from connectors.snowflake_connector import SnowflakeConfigError, SnowflakeDataSource


class _FakeSession:
    """Stand-in for a Snowpark session (as returned by get_active_session())."""

    def __init__(self):
        self.executed: list[str] = []

    def sql(self, statement):
        self.executed.append(statement)
        return self

    def collect(self):
        return []

    def to_pandas(self):
        return pd.DataFrame({"A": [1, 2]})

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


def test_active_session_used_when_no_explicit_creds():
    """SiS path: an injected session with no account/user/password is enough."""
    session = _FakeSession()
    src = SnowflakeDataSource(table="ORDERS", load_env=False, session=session)
    assert src._uses_active_session
    df = src.fetch()
    assert list(df["A"]) == [1, 2]
    assert session.executed == ["SELECT * FROM ORDERS"]


def test_explicit_creds_take_precedence_over_auto_detected_session(monkeypatch):
    """Explicit account/user/password means "connect elsewhere", even if an
    active session is ambient (e.g. cross-account target from within SiS)."""
    session = _FakeSession()
    monkeypatch.setattr(sf_connector, "_active_session", lambda: session)
    src = SnowflakeDataSource(table="ORDERS", **BASE, password="s3cret!")
    assert not src._uses_active_session
    assert src._session is None


def test_auto_detected_session_used_when_no_explicit_creds(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(sf_connector, "_active_session", lambda: session)
    src = SnowflakeDataSource(table="ORDERS", load_env=False)
    assert src._uses_active_session
    src.fetch()
    assert session.executed == ["SELECT * FROM ORDERS"]


def test_session_fetch_applies_warehouse_and_role_overrides():
    session = _FakeSession()
    src = SnowflakeDataSource(
        table="ORDERS", load_env=False, session=session, warehouse="WH1", role="ROLE1"
    )
    src.fetch()
    assert session.executed == [
        "USE WAREHOUSE WH1",
        "USE ROLE ROLE1",
        "SELECT * FROM ORDERS",
    ]


def test_session_fetch_rejects_invalid_warehouse_identifier():
    session = _FakeSession()
    src = SnowflakeDataSource(
        table="ORDERS", load_env=False, session=session, warehouse="wh1; DROP TABLE x"
    )
    with pytest.raises(SnowflakeConfigError, match="Invalid warehouse identifier"):
        src.fetch()
    assert session.executed == []


def test_session_fetch_rejects_invalid_role_identifier():
    session = _FakeSession()
    src = SnowflakeDataSource(
        table="ORDERS", load_env=False, session=session, role="role1; DROP TABLE x"
    )
    with pytest.raises(SnowflakeConfigError, match="Invalid role identifier"):
        src.fetch()
