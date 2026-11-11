"""One-time, idempotence-protected migration from local SQLite into hosted storage."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from app import AUTH_REQUIRED, DB, PDF_DIR, connect, init_db, valid_email
from database import hosted_database_enabled, table_column_names
from file_store import delete_object, hosted_storage_enabled, store_statement_pdf

TABLE_ORDER = (
    "merchants", "statements", "merchant_discoveries", "transactions", "users", "audit",
)
SKIP_TABLES = {"auth_sessions", "auth_login_attempts", "ledger_backups"}


def _source_rows(source, table):
    existing = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if table not in existing:
        return [], []
    columns = [row[1] for row in source.execute("PRAGMA table_info(" + table + ")")]
    rows = source.execute("SELECT * FROM " + table).fetchall()
    return columns, rows


def migrate():
    if not hosted_database_enabled():
        raise RuntimeError("Set DATABASE_URL or POSTGRES_URL_NON_POOLING before running the hosted migration")
    if not hosted_storage_enabled():
        raise RuntimeError("Set Supabase URL, server secret key, and a private statement bucket before migrating PDFs")
    if not DB.is_file():
        raise RuntimeError("Local ledger database not found at " + str(DB))
    if not AUTH_REQUIRED or not valid_email(os.environ.get("LEDGER_BOOTSTRAP_ADMIN_EMAIL", "")):
        raise RuntimeError("Set LEDGER_AUTH_REQUIRED=1 and a valid LEDGER_BOOTSTRAP_ADMIN_EMAIL")
    if len(os.environ.get("LEDGER_BOOTSTRAP_ADMIN_PASSWORD", "")) < 16:
        raise RuntimeError("Set a 16+ character LEDGER_BOOTSTRAP_ADMIN_PASSWORD before migrating")

    init_db(seed_merchants=False, bootstrap_admin=False)
    with connect() as target:
        for table in ("transactions", "statements", "merchants", "merchant_discoveries", "users"):
            if target.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]:
                raise RuntimeError("The hosted database already contains ledger data; migration stopped without changing it")

    uploaded = []
    source = sqlite3.connect(DB)
    source.row_factory = sqlite3.Row
    counts = {}
    try:
        with connect() as target:
            for table in TABLE_ORDER:
                columns, rows = _source_rows(source, table)
                if not rows:
                    counts[table] = 0
                    continue
                target_columns = table_column_names(target, table)
                chosen = [name for name in columns if name in target_columns]
                if table == "statements":
                    for row in rows:
                        values = dict(row)
                        old_path = Path(values["file_path"])
                        if not old_path.is_file():
                            old_path = PDF_DIR / old_path.name
                        if not old_path.is_file():
                            raise FileNotFoundError("A statement PDF referenced by the local ledger is missing")
                        raw = old_path.read_bytes()
                        reference, _ = store_statement_pdf(values["id"], values["filename"], raw, PDF_DIR)
                        values["file_path"] = reference
                        uploaded.append(reference.removeprefix("supabase://"))
                        statement_columns = [name for name in chosen if name != "file_path"] + ["file_path"]
                        placeholders = ",".join("?" for _ in statement_columns)
                        target.execute(
                            "INSERT INTO statements ({}) VALUES ({})".format(",".join(statement_columns), placeholders),
                            tuple(values[name] for name in statement_columns),
                        )
                    counts[table] = len(rows)
                    continue

                placeholders = ",".join("?" for _ in chosen)
                statement = "INSERT INTO {} ({}) VALUES ({})".format(table, ",".join(chosen), placeholders)
                values = [tuple(row[name] for name in chosen) for row in rows]
                target.executemany(statement, values)
                counts[table] = len(rows)
    except Exception:
        for path in uploaded:
            try:
                delete_object(path)
            except Exception:
                pass
        raise
    finally:
        source.close()

    init_db(seed_merchants=True, bootstrap_admin=True)
    with connect() as target:
        for table in ("transactions", "statements", "merchants"):
            actual = target.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
            if actual != counts.get(table, 0):
                raise RuntimeError("Hosted verification failed for {} (expected {}, got {})".format(
                    table, counts.get(table, 0), actual))
        pdfs = target.execute("SELECT file_path FROM statements").fetchall()
    for row in pdfs:
        data = __import__("file_store").statement_bytes(row["file_path"])
        if not data.startswith(b"%PDF-"):
            raise RuntimeError("Hosted statement verification failed: an object is not a PDF")
    print(json.dumps({"migrated": counts, "pdf_files_verified": len(pdfs)}, sort_keys=True))


if __name__ == "__main__":
    migrate()
