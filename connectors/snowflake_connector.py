"""Snowflake connector.

Authenticates using credentials read from environment variables (loaded via
python-dotenv from a local .env file) or explicit constructor arguments.
Passwords and private key material are never logged or included in
``repr()``/``describe()`` output.

Supports either:
  - a full table fetch (``table=...``), or
  - a custom SQL query (``query=...``)
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pandas as pd
import snowflake.connector
from dotenv import load_dotenv
from snowflake.connector.errors import NotSupportedError

from connectors.base import DataSource

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


class SnowflakeConfigError(ValueError):
    """Raised when required Snowflake connection settings are missing/invalid."""


class SnowflakeDataSource(DataSource):
    def __init__(
        self,
        table: str | None = None,
        query: str | None = None,
        account: str | None = None,
        user: str | None = None,
        password: str | None = None,
        private_key_path: str | None = None,
        private_key_passphrase: str | None = None,
        warehouse: str | None = None,
        database: str | None = None,
        schema: str | None = None,
        role: str | None = None,
        authenticator: str | None = None,
        load_env: bool = True,
    ):
        if load_env:
            load_dotenv()

        self.account = account or os.getenv("SNOWFLAKE_ACCOUNT")
        self.user = user or os.getenv("SNOWFLAKE_USER")
        self.warehouse = warehouse or os.getenv("SNOWFLAKE_WAREHOUSE")
        self.database = database or os.getenv("SNOWFLAKE_DATABASE")
        self.schema = schema or os.getenv("SNOWFLAKE_SCHEMA")
        self.role = role or os.getenv("SNOWFLAKE_ROLE")

        # Auth methods, in order of precedence:
        #   - authenticator="externalbrowser": SSO via the identity provider
        #     (Okta, Azure AD, ...) in a browser window; no password needed.
        #   - authenticator="https://<org>.okta.com": native Okta (password required).
        #   - key-pair / password (default "snowflake" authenticator).
        # Secrets are never stored beyond what's needed to connect.
        self.authenticator = authenticator or os.getenv("SNOWFLAKE_AUTHENTICATOR")
        self._password = password or os.getenv("SNOWFLAKE_PASSWORD")
        self._private_key_path = private_key_path or os.getenv("SNOWFLAKE_PRIVATE_KEY_PATH")
        self._private_key_passphrase = private_key_passphrase or os.getenv(
            "SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"
        )

        if table and query:
            raise ValueError("Pass either 'table' or 'query', not both.")
        if not table and not query:
            raise ValueError("Must pass either 'table' or 'query'.")
        if table and not _IDENTIFIER_RE.match(table.split(".")[-1]):
            raise ValueError(f"Invalid table identifier: {table!r}")

        self.table = table
        self.query = query

        self._validate_required_settings()

    @property
    def _uses_browser_sso(self) -> bool:
        return (self.authenticator or "").lower() == "externalbrowser"

    def _validate_required_settings(self) -> None:
        missing = [
            name
            for name, value in (
                ("account", self.account),
                ("user", self.user),
                ("warehouse", self.warehouse),
            )
            if not value
        ]
        # Browser SSO authenticates through the identity provider — no local
        # secret required. Every other method needs a password or key pair.
        if not self._uses_browser_sso and not self._password and not self._private_key_path:
            missing.append("password or private_key_path")
        if missing:
            raise SnowflakeConfigError(
                "Missing required Snowflake settings: "
                f"{', '.join(missing)}. Set them via environment variables "
                "(see .env.example) or constructor arguments."
            )

    def describe(self) -> str:
        target = self.table or "<custom query>"
        return (
            f"SnowflakeDataSource(account={self.account}, user={self.user}, "
            f"warehouse={self.warehouse}, database={self.database}, "
            f"schema={self.schema}, role={self.role}, "
            f"authenticator={self.authenticator or 'snowflake'}, target={target})"
        )

    def __repr__(self) -> str:
        return self.describe()

    def _build_connect_kwargs(self) -> dict:
        kwargs: dict = {
            "account": self.account,
            "user": self.user,
            "warehouse": self.warehouse,
        }
        if self.database:
            kwargs["database"] = self.database
        if self.schema:
            kwargs["schema"] = self.schema
        if self.role:
            kwargs["role"] = self.role

        if self.authenticator:
            kwargs["authenticator"] = self.authenticator

        if self._uses_browser_sso:
            pass  # SSO: the browser flow handles credentials
        elif self._private_key_path:
            kwargs["private_key"] = self._load_private_key_bytes()
        else:
            kwargs["password"] = self._password
        return kwargs

    def _load_private_key_bytes(self) -> bytes:
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives import serialization

        key_path = Path(self._private_key_path)
        if not key_path.exists():
            raise SnowflakeConfigError(f"Private key file not found: {key_path}")

        passphrase = (
            self._private_key_passphrase.encode() if self._private_key_passphrase else None
        )
        with open(key_path, "rb") as f:
            private_key = serialization.load_pem_private_key(
                f.read(), password=passphrase, backend=default_backend()
            )
        return private_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

    def _build_sql(self) -> str:
        if self.query:
            return self.query
        parts = [p for p in (self.database, self.schema, self.table) if p]
        # table may already be schema-qualified; only prefix with what's missing
        if "." in self.table:
            qualified = self.table
        else:
            qualified = ".".join(parts)
        return f"SELECT * FROM {qualified}"

    def fetch(self) -> pd.DataFrame:
        conn = snowflake.connector.connect(**self._build_connect_kwargs())
        try:
            cursor = conn.cursor()
            try:
                cursor.execute(self._build_sql())
                try:
                    return cursor.fetch_pandas_all()
                except NotSupportedError:
                    columns = [desc[0] for desc in cursor.description]
                    rows = cursor.fetchall()
                    return pd.DataFrame(rows, columns=columns)
            finally:
                cursor.close()
        finally:
            conn.close()
