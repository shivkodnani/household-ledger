"""Encrypted remote database and statement backup helpers for hosted mode."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import argparse
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from pathlib import PurePosixPath

from backup import _key_value
from database import connect, pg_dump_url, postgres_url
from file_store import download_object, statement_bytes, upload_object

MAGIC = b"HLBK2\n"
KEEP_BACKUPS = 30


def _timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def list_hosted_backups():
    with connect() as db:
        rows = db.execute(
            "SELECT name,created_at,size_bytes FROM ledger_backups ORDER BY created_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def create_hosted_backup(reason="scheduled"):
    key = os.environ.get("LEDGER_BACKUP_FERNET_KEY", "").strip()
    if not key:
        raise RuntimeError("Set LEDGER_BACKUP_FERNET_KEY before creating encrypted backups")
    if not postgres_url():
        raise RuntimeError("A PostgreSQL connection is required for hosted backups")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = "ledger-{}-{}.hlb".format(stamp, os.urandom(3).hex())
    with tempfile.TemporaryDirectory(prefix="ledger-cloud-backup-") as temp_name:
        temp = Path(temp_name)
        dump_path = temp / "database.dump"
        try:
            with dump_path.open("wb") as dump_file:
                subprocess.run(
                    ["pg_dump", "--no-owner", "--no-privileges", "--format=custom", pg_dump_url()],
                    check=True, stdout=dump_file, stderr=subprocess.PIPE, timeout=150,
                )
        except FileNotFoundError as exc:
            raise RuntimeError("pg_dump is not installed in this deployment") from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError("PostgreSQL backup failed: " + exc.stderr.decode("utf-8", "replace")[-400:]) from exc

        with connect() as db:
            statements = db.execute("SELECT id,filename,file_path FROM statements ORDER BY id").fetchall()

        file_map = []
        for row in statements:
            safe_name = "{}_{}".format(row["id"], Path(row["filename"]).name)
            content = statement_bytes(row["file_path"])
            (temp / safe_name).write_bytes(content)
            file_map.append({"id": row["id"], "filename": safe_name,
                             "sha256": hashlib.sha256(content).hexdigest()})

        manifest = {
            "format": 2,
            "created_at": _timestamp(),
            "reason": reason,
            "database_sha256": hashlib.sha256(dump_path.read_bytes()).hexdigest(),
            "statement_files": file_map,
        }
        archive_path = temp / "backup.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.write(dump_path, "database.dump")
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, sort_keys=True))
            for file in file_map:
                archive.write(temp / file["filename"], "statements/" + file["filename"])
        encrypted = MAGIC + _key_value(key).encrypt(archive_path.read_bytes())

    upload_object("backups/" + name, encrypted, "application/octet-stream")
    created_at = _timestamp()
    with connect() as db:
        db.execute("INSERT INTO ledger_backups(name,created_at,size_bytes) VALUES(?,?,?)",
                   (name, created_at, len(encrypted)))
        old = db.execute(
            "SELECT name FROM ledger_backups ORDER BY created_at DESC OFFSET ?", (KEEP_BACKUPS,)
        ).fetchall()
        if old:
            from file_store import delete_object
            for row in old:
                delete_object("backups/" + row["name"])
                db.execute("DELETE FROM ledger_backups WHERE name=?", (row["name"],))
    return {"name": name, "created_at": created_at, "size_bytes": len(encrypted)}


def download_hosted_backup(name: str) -> bytes:
    if Path(name).name != name or not name.startswith("ledger-") or not name.endswith(".hlb"):
        raise ValueError("Invalid backup name")
    with connect() as db:
        found = db.execute("SELECT 1 FROM ledger_backups WHERE name=?", (name,)).fetchone()
    if not found:
        raise FileNotFoundError("Backup not found")
    return download_object("backups/" + name)


def restore_hosted_backup(path: str, confirm=False):
    if not confirm:
        raise RuntimeError("Hosted restore requires explicit confirmation")
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError("Backup file not found")
    encrypted = source.read_bytes()
    if not encrypted.startswith(MAGIC):
        raise ValueError("This is not a hosted household ledger backup")
    archive_bytes = _key_value().decrypt(encrypted[len(MAGIC):])
    with tempfile.TemporaryDirectory(prefix="ledger-cloud-restore-") as temp_name:
        temp = Path(temp_name)
        archive_path = temp / "backup.zip"
        archive_path.write_bytes(archive_bytes)
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            if sum(item.file_size for item in members) > 2 * 1024 * 1024 * 1024:
                raise ValueError("Backup exceeds the 2 GB restore limit")
            for member in members:
                safe_name = PurePosixPath(member.filename)
                if safe_name.is_absolute() or ".." in safe_name.parts:
                    raise ValueError("Unsafe path inside backup")
                if member.filename not in ("database.dump", "manifest.json") and not member.filename.startswith("statements/"):
                    raise ValueError("Unexpected file inside backup")
                if member.is_dir():
                    continue
                target = temp.joinpath(*safe_name.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as src, target.open("wb") as dst:
                    dst.write(src.read())
        manifest_path = temp / "manifest.json"
        dump_path = temp / "database.dump"
        if not manifest_path.is_file() or not dump_path.is_file():
            raise ValueError("Backup is missing its database or manifest")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("format") != 2 or hashlib.sha256(dump_path.read_bytes()).hexdigest() != manifest.get("database_sha256"):
            raise ValueError("Backup database verification failed")
        for item in manifest.get("statement_files", []):
            name = item.get("filename", "")
            relative = PurePosixPath("statements") / name
            if PurePosixPath(name).name != name or ".." in relative.parts:
                raise ValueError("Unsafe statement filename in manifest")
            statement_path = temp.joinpath(*relative.parts)
            if not statement_path.is_file() or hashlib.sha256(statement_path.read_bytes()).hexdigest() != item.get("sha256"):
                raise ValueError("Statement PDF verification failed")

        subprocess.run(
            ["pg_restore", "--exit-on-error", "--clean", "--if-exists", "--no-owner",
             "--no-privileges", "--dbname", pg_dump_url(), str(dump_path)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=300,
        )
        from file_store import upload_object
        for item in manifest.get("statement_files", []):
            filename = item["filename"]
            statement_path = temp / "statements" / filename
            upload_object("statements/" + filename, statement_path.read_bytes(), "application/pdf", upsert=True)


def main():
    parser = argparse.ArgumentParser(description="Hosted household ledger backup utility")
    parser.add_argument("command", choices=("restore",))
    parser.add_argument("backup_file")
    args = parser.parse_args()
    print("This replaces the hosted PostgreSQL database and all backed-up statement PDFs.")
    if input("Type RESTORE to continue: ").strip() != "RESTORE":
        print("Restore cancelled")
        return
    restore_hosted_backup(args.backup_file, confirm=True)
    print("Hosted restore complete")


if __name__ == "__main__":
    main()
