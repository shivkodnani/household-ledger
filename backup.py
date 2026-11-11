"""Authenticated, encrypted SQLite + statement-PDF backup and restore utility."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from io import BytesIO

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DB = DATA / "ledger.sqlite3"
PDF_DIR = DATA / "statements"
BACKUP_DIR = DATA / "backups"
MAGIC = b"HLBK1\n"
KEEP_BACKUPS = 30
MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024


def _load_local_env():
    for env_file in (ROOT / ".env", ROOT / ".env.local"):
        if not env_file.is_file(): continue
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line=line.strip()
            if not line or line.startswith("#") or "=" not in line: continue
            name,value=line.split("=",1); name=name.strip(); value=value.strip()
            if len(value)>=2 and value[0]==value[-1] and value[0] in "'\"": value=value[1:-1]
            if name and name not in os.environ: os.environ[name]=value


_load_local_env()


def _key_value(key=None):
    key = key or os.environ.get("LEDGER_BACKUP_FERNET_KEY", "").strip()
    if not key:
        raise RuntimeError("Set LEDGER_BACKUP_FERNET_KEY before creating or restoring encrypted backups")
    try:
        from cryptography.fernet import Fernet
        return Fernet(key.encode("ascii"))
    except ImportError as exc:
        raise RuntimeError("Install Python dependencies from requirements.txt to use encrypted backups") from exc
    except Exception as exc:
        raise RuntimeError("LEDGER_BACKUP_FERNET_KEY is not a valid Fernet key") from exc


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_backup(key=None, reason="scheduled"):
    """Take a consistent SQLite snapshot, include retained PDFs, then encrypt it."""
    fernet = _key_value(key)
    if not DB.is_file():
        raise RuntimeError("The ledger database does not exist yet")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ledger-backup-") as temp_name:
        temp = Path(temp_name)
        snapshot = temp / "ledger.sqlite3"
        with sqlite3.connect(DB) as source, sqlite3.connect(snapshot) as target:
            source.backup(target)
        statements = []
        with sqlite3.connect(snapshot) as snap:
            snap.row_factory = sqlite3.Row
            rows = snap.execute("SELECT id,file_path,filename FROM statements").fetchall()
            for row in rows:
                path = Path(row["file_path"])
                candidate = path if path.is_file() else PDF_DIR / path.name
                if candidate.is_file():
                    statements.append(candidate)
                    snap.execute("UPDATE statements SET file_path=? WHERE id=?", (str(PDF_DIR / candidate.name), row["id"]))
        with sqlite3.connect(snapshot) as snap:
            snap.commit()
        file_names = sorted({p.name for p in statements})
        manifest = {
            "format": 1,
            "created_at": _utc(),
            "reason": reason,
            "database_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
            "statement_files": file_names,
        }
        archive_buffer = BytesIO()
        with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.write(snapshot, "ledger.sqlite3")
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, sort_keys=True))
            for path in statements:
                archive.write(path, "statements/" + path.name)
        encrypted = MAGIC + fernet.encrypt(archive_buffer.getvalue())
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = BACKUP_DIR / f"ledger-{stamp}-{os.urandom(3).hex()}.hlb"
    temp_target = target.with_suffix(".tmp")
    temp_target.write_bytes(encrypted)
    try:
        os.chmod(temp_target, 0o600)
    except OSError:
        pass
    os.replace(temp_target, target)
    _prune_backups()
    return target


def _prune_backups():
    files = sorted(BACKUP_DIR.glob("ledger-*.hlb"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[KEEP_BACKUPS:]:
        old.unlink(missing_ok=True)


def list_backups():
    if not BACKUP_DIR.exists(): return []
    result = []
    for path in sorted(BACKUP_DIR.glob("ledger-*.hlb"), key=lambda p: p.stat().st_mtime, reverse=True):
        stat = path.stat()
        result.append({"name":path.name,"created_at":datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"),"size_bytes":stat.st_size})
    return result


def read_backup(name, key=None):
    if Path(name).name != name or not name.startswith("ledger-") or not name.endswith(".hlb"):
        raise ValueError("Invalid backup name")
    path = BACKUP_DIR / name
    if not path.is_file(): raise FileNotFoundError("Backup not found")
    raw = path.read_bytes()
    if not raw.startswith(MAGIC): raise ValueError("Unrecognized backup format")
    return _key_value(key).decrypt(raw[len(MAGIC):])


def restore_backup(name, key=None, confirm=False):
    """Replace the current database and PDF tree after validation and a safety snapshot."""
    if not confirm:
        raise RuntimeError("Restore requires explicit confirmation")
    archive_data = read_backup(name, key)
    with tempfile.TemporaryDirectory(prefix="ledger-restore-", dir=str(DATA.parent)) as temp_name:
        temp = Path(temp_name)
        archive_path = temp / "backup.zip"
        archive_path.write_bytes(archive_data)
        extracted = temp / "extracted"
        extracted.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            total = sum(member.file_size for member in members)
            if total > MAX_UNCOMPRESSED_BYTES: raise ValueError("Backup exceeds the restore size limit")
            for member in members:
                name_path = PurePosixPath(member.filename)
                if name_path.is_absolute() or ".." in name_path.parts: raise ValueError("Unsafe path in backup")
                if member.filename not in ("ledger.sqlite3", "manifest.json") and not member.filename.startswith("statements/"):
                    raise ValueError("Unexpected file in backup")
                if member.is_dir(): continue
                destination = extracted.joinpath(*name_path.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target)
        db_file = extracted / "ledger.sqlite3"
        manifest_file = extracted / "manifest.json"
        if not db_file.is_file() or not manifest_file.is_file(): raise ValueError("Backup is missing required files")
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        if manifest.get("format") != 1 or hashlib.sha256(db_file.read_bytes()).hexdigest() != manifest.get("database_sha256"):
            raise ValueError("Backup verification failed")
        with sqlite3.connect(db_file) as check:
            if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok": raise ValueError("Backup database failed integrity check")
            tables = {row[0] for row in check.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"transactions","statements","merchants"}.issubset(tables): raise ValueError("Backup does not contain a ledger database")
            # A restored snapshot must not revive old browser sessions or stale login throttles.
            if "auth_sessions" in tables: check.execute("DELETE FROM auth_sessions")
            if "auth_login_attempts" in tables: check.execute("DELETE FROM auth_login_attempts")
            if "file_path" in {row[1] for row in check.execute("PRAGMA table_info(statements)")}:
                check.execute("SELECT 1 FROM statements LIMIT 1")
                rows = check.execute("SELECT id,file_path FROM statements").fetchall()
                for statement_id, stored_path in rows:
                    safe_name = Path(stored_path).name
                    if not safe_name or safe_name in (".", ".."): raise ValueError("Unsafe statement path in backup")
                    check.execute("UPDATE statements SET file_path=? WHERE id=?", (str(PDF_DIR / safe_name), statement_id))
        with sqlite3.connect(db_file) as check: check.commit()
        # Preserve the current state as a recoverable encrypted backup before replacing it.
        if DB.is_file(): create_backup(key, reason="before-restore")
        new_statements = extracted / "statements"
        if not new_statements.exists(): new_statements.mkdir()
        restore_db = temp / "ledger.sqlite3.restore"
        shutil.copy2(db_file, restore_db)
        old_statements = DATA / "statements.before-restore"
        if old_statements.exists(): shutil.rmtree(old_statements)
        if PDF_DIR.exists(): os.replace(PDF_DIR, old_statements)
        try:
            os.replace(new_statements, PDF_DIR)
            os.replace(restore_db, DB)
        except Exception:
            if PDF_DIR.exists(): shutil.rmtree(PDF_DIR)
            if old_statements.exists(): os.replace(old_statements, PDF_DIR)
            raise
        if old_statements.exists(): shutil.rmtree(old_statements)
    return True


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Household Ledger encrypted backup utility")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("create", help="Create an encrypted backup")
    restore = commands.add_parser("restore", help="Restore an encrypted backup")
    restore.add_argument("backup_name")
    args = parser.parse_args()
    if args.command == "create":
        print(create_backup(reason="manual"))
        return
    print("This replaces the current ledger database and retained statement PDFs.")
    confirmation = input("Type RESTORE to continue: ").strip()
    if confirmation != "RESTORE":
        print("Restore cancelled")
        return
    restore_backup(args.backup_name, confirm=True)
    print("Restore complete")


if __name__ == "__main__":
    main()
