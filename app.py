#!/usr/bin/env python3
"""Local-first household spend ledger. Uses only Python's standard library."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import json, sqlite3, uuid, datetime, mimetypes, os, re, shutil, tempfile
import subprocess, hashlib, hmac, secrets, base64, ipaddress, threading, time
from difflib import SequenceMatcher
from http.cookies import SimpleCookie
from concurrent.futures import ThreadPoolExecutor
from hsbc_parser import extract_hsbc_pdf, _runtime_paths
from merchant_search import merchant_alias_core, merchant_alias_key, search_parallel
from database import connect as connect_database, hosted_database_enabled, schema_for_backend, table_column_names
from file_store import (hosted_storage_enabled, local_statement_path, require_hosted_storage,
                        statement_bytes, store_statement_pdf)

ROOT = Path(__file__).parent
DATA = (Path(tempfile.gettempdir()) / "household-ledger-runtime") if os.environ.get("VERCEL") == "1" else ROOT / "data"
PDF_DIR = DATA / "statements"
DB = DATA / "ledger.sqlite3"
SEARCH_WORKERS = ThreadPoolExecutor(max_workers=3, thread_name_prefix="merchant-search")

def load_local_env():
    """Load simple KEY=value entries without overriding shell-provided settings."""
    for env_file in (ROOT / ".env", ROOT / ".env.local"):
        if not env_file.exists(): continue
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line: continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"": value = value[1:-1]
            if key and key not in os.environ: os.environ[key] = value

load_local_env()
AUTH_REQUIRED = os.environ.get("LEDGER_AUTH_REQUIRED", "0").strip() == "1"
SECURE_COOKIES = os.environ.get("LEDGER_SECURE_COOKIES", "0").strip() == "1"
SESSION_COOKIE = "household_ledger_session"
LOGIN_CSRF_COOKIE = "household_ledger_login_csrf"
SESSION_DAYS = 14
CACHE_TEMP = tempfile.TemporaryDirectory(prefix="household-ledger-preview-")
PAGE_CACHE = Path(CACHE_TEMP.name) / "pages"
SNAPSHOT_CACHE = Path(CACHE_TEMP.name) / "snapshots"
PDF_DIR.mkdir(parents=True, exist_ok=True)

def connect():
    return connect_database(DB)

def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)

def password_hash(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600_000, dklen=32)
    return "pbkdf2-sha256$600000${}${}".format(base64.urlsafe_b64encode(salt).decode(), base64.urlsafe_b64encode(digest).decode())

def password_matches(password, encoded):
    try:
        parts = encoded.split("$")
        algorithm = parts[0]
        if algorithm == "pbkdf2-sha256" and len(parts) == 4:
            iterations, salt_text, digest_text = parts[1:]
            if iterations != "600000": return False
            salt = base64.urlsafe_b64decode(salt_text.encode())
            expected = base64.urlsafe_b64decode(digest_text.encode())
            actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600_000, dklen=len(expected))
        elif algorithm == "scrypt" and len(parts) == 6 and hasattr(hashlib, "scrypt"):
            _, n, r, p, salt_text, digest_text = parts
            if (n, r, p) != ("16384", "8", "1"): return False
            salt = base64.urlsafe_b64decode(salt_text.encode())
            expected = base64.urlsafe_b64decode(digest_text.encode())
            actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=len(expected))
        else:
            return False
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False

def valid_email(value):
    value = (value or "").strip().lower()
    return value if len(value) <= 254 and re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value) else ""

def valid_password(value):
    return isinstance(value, str) and 12 <= len(value) <= 1024

def b64url_encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

def b64url_decode(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Invalid encoded passkey data")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

DUMMY_PASSWORD_HASH = password_hash(secrets.token_urlsafe(32))

def init_db(seed_merchants=True, bootstrap_admin=True):
    with connect() as c:
        if hosted_database_enabled():
            c.execute("SELECT pg_advisory_xact_lock(hashtext('household-ledger-schema-v1'))")
        schema = """
        CREATE TABLE IF NOT EXISTS merchants(
          id TEXT PRIMARY KEY, display_name TEXT NOT NULL, aliases TEXT NOT NULL DEFAULT '[]',
          category TEXT NOT NULL DEFAULT 'Uncategorised', created_at TEXT NOT NULL,
          allocation_suggestion TEXT NOT NULL DEFAULT '', suggestion_person TEXT NOT NULL DEFAULT 'Any');
        CREATE TABLE IF NOT EXISTS merchant_discoveries(
          id TEXT PRIMARY KEY, alias_key TEXT NOT NULL UNIQUE, raw_alias TEXT NOT NULL,
          query_alias TEXT NOT NULL, transaction_count INTEGER NOT NULL DEFAULT 0,
          statement_ids TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'pending',
          results TEXT NOT NULL DEFAULT '[]', search_query TEXT NOT NULL DEFAULT '',
          search_error TEXT NOT NULL DEFAULT '', approved_merchant_id TEXT,
          created_at TEXT NOT NULL, searched_at TEXT, decision_at TEXT);
        CREATE TABLE IF NOT EXISTS statements(
          id TEXT PRIMARY KEY, filename TEXT NOT NULL, bank TEXT NOT NULL, card_name TEXT NOT NULL DEFAULT '',
          period TEXT NOT NULL DEFAULT '', file_path TEXT NOT NULL, uploaded_at TEXT NOT NULL,
          extraction_status TEXT NOT NULL DEFAULT 'manual', transaction_count INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS transactions(
          id TEXT PRIMARY KEY, date TEXT NOT NULL, description TEXT NOT NULL, merchant_id TEXT,
          amount_inr REAL NOT NULL, original_amount REAL, currency TEXT NOT NULL DEFAULT 'INR',
          person TEXT NOT NULL DEFAULT 'Unknown', kind TEXT NOT NULL DEFAULT 'Purchase',
          allocation TEXT NOT NULL DEFAULT 'Needs review', share_percent REAL NOT NULL DEFAULT 0,
          payment_method TEXT NOT NULL DEFAULT 'Credit card', category TEXT NOT NULL DEFAULT 'Uncategorised',
          statement_id TEXT, notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
          source_page INTEGER, source_bbox TEXT, ocr_confidence REAL,
          ocr_amount_confidence REAL, ocr_amount_match INTEGER,
          FOREIGN KEY(merchant_id) REFERENCES merchants(id) ON DELETE SET NULL,
          FOREIGN KEY(statement_id) REFERENCES statements(id) ON DELETE SET NULL);
        CREATE TABLE IF NOT EXISTS audit(
          id INTEGER PRIMARY KEY AUTOINCREMENT, transaction_id TEXT, action TEXT NOT NULL,
          detail TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS users(
          id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE, display_name TEXT NOT NULL,
          password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','user')),
          active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, last_login_at TEXT);
        CREATE TABLE IF NOT EXISTS auth_sessions(
          token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, csrf_token TEXT NOT NULL,
          created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
          FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
        CREATE INDEX IF NOT EXISTS auth_sessions_user_id ON auth_sessions(user_id);
        CREATE TABLE IF NOT EXISTS auth_login_attempts(
          id INTEGER PRIMARY KEY AUTOINCREMENT, remote_ip TEXT NOT NULL,
          email TEXT NOT NULL, attempted_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS auth_login_attempts_time ON auth_login_attempts(attempted_at);
        CREATE TABLE IF NOT EXISTS passkeys(
          id TEXT PRIMARY KEY, credential_id TEXT NOT NULL UNIQUE, user_id TEXT NOT NULL,
          public_key TEXT NOT NULL, sign_count BIGINT NOT NULL DEFAULT 0,
          transports TEXT NOT NULL DEFAULT '[]', nickname TEXT NOT NULL DEFAULT 'Passkey',
          device_type TEXT NOT NULL DEFAULT '', backed_up INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL, last_used_at TEXT,
          FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
        CREATE INDEX IF NOT EXISTS passkeys_user_id ON passkeys(user_id);
        CREATE TABLE IF NOT EXISTS webauthn_challenges(
          id TEXT PRIMARY KEY, user_id TEXT, purpose TEXT NOT NULL, challenge TEXT NOT NULL,
          nickname TEXT NOT NULL DEFAULT 'Passkey', remote_ip TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
          expires_at TEXT NOT NULL, consumed_at TEXT,
          FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
        CREATE INDEX IF NOT EXISTS webauthn_challenges_expiry ON webauthn_challenges(expires_at);
        CREATE TABLE IF NOT EXISTS auth_passkey_login_attempts(
          id INTEGER PRIMARY KEY AUTOINCREMENT, remote_ip TEXT NOT NULL, attempted_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS auth_passkey_login_attempts_time ON auth_passkey_login_attempts(attempted_at);
        CREATE TABLE IF NOT EXISTS ledger_backups(
          name TEXT PRIMARY KEY, created_at TEXT NOT NULL, size_bytes INTEGER NOT NULL);
        """
        schema = schema_for_backend(schema)
        c.executescript(schema)
        if hosted_database_enabled():
            # The application connects server-side; keep the new credential tables
            # inaccessible to Supabase's user-facing APIs unless policies are added.
            c.execute("ALTER TABLE passkeys ENABLE ROW LEVEL SECURITY")
            c.execute("ALTER TABLE webauthn_challenges ENABLE ROW LEVEL SECURITY")
            c.execute("ALTER TABLE auth_passkey_login_attempts ENABLE ROW LEVEL SECURITY")
        challenge_columns = table_column_names(c, "webauthn_challenges")
        if "remote_ip" not in challenge_columns:
            c.execute("ALTER TABLE webauthn_challenges ADD COLUMN remote_ip TEXT NOT NULL DEFAULT ''")
        statement_columns = table_column_names(c, "statements")
        if "extraction_status" not in statement_columns:
            c.execute("ALTER TABLE statements ADD COLUMN extraction_status TEXT NOT NULL DEFAULT 'manual'")
        if "transaction_count" not in statement_columns:
            c.execute("ALTER TABLE statements ADD COLUMN transaction_count INTEGER NOT NULL DEFAULT 0")
        for name, declaration in (("statement_month", "TEXT"), ("expected_charges_inr", "REAL"),
                                  ("extracted_charges_inr", "REAL"), ("reconciliation_difference_inr", "REAL"),
                                  ("reconciliation_status", "TEXT NOT NULL DEFAULT 'unavailable'")):
            if name not in statement_columns:
                c.execute(f"ALTER TABLE statements ADD COLUMN {name} {schema_for_backend(declaration)}")
        for row in c.execute("SELECT id,period FROM statements WHERE statement_month IS NULL"):
            match = re.findall(r"\b(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\w*\s+(20\d{2})", (row["period"] or "").upper())
            if match:
                months = {"JAN":1,"FEB":2,"MAR":3,"APR":4,"MAY":5,"JUN":6,"JUL":7,"AUG":8,"SEP":9,"OCT":10,"NOV":11,"DEC":12}
                c.execute("UPDATE statements SET statement_month=? WHERE id=?", (f"{match[-1][1]}-{months[match[-1][0]]:02d}", row["id"]))
        merchant_columns = table_column_names(c, "merchants")
        for name, declaration in (("allocation_suggestion", "TEXT NOT NULL DEFAULT ''"),
                                  ("suggestion_person", "TEXT NOT NULL DEFAULT 'Any'"),
                                  ("legal_name", "TEXT NOT NULL DEFAULT ''"),
                                  ("discovery_url", "TEXT NOT NULL DEFAULT ''"),
                                  ("discovery_title", "TEXT NOT NULL DEFAULT ''")):
            if name not in merchant_columns:
                c.execute(f"ALTER TABLE merchants ADD COLUMN {name} {declaration}")
        transaction_columns = table_column_names(c, "transactions")
        for name, declaration in (("source_page", "INTEGER"), ("source_bbox", "TEXT"),
                                  ("ocr_confidence", "REAL"), ("ocr_amount_confidence", "REAL"),
                                  ("ocr_amount_match", "INTEGER")):
            if name not in transaction_columns:
                c.execute(f"ALTER TABLE transactions ADD COLUMN {name} {schema_for_backend(declaration)}")
        if seed_merchants and c.execute("SELECT COUNT(*) FROM merchants").fetchone()[0] == 0:
            now = datetime.datetime.now().isoformat(timespec="seconds")
            c.execute("INSERT INTO merchants(id,display_name,aliases,category,created_at) VALUES(?,?,?,?,?)", (str(uuid.uuid4()), "Swiggy", json.dumps(["BUNDL", "SWIGGY", "SWIGGY.COM"]), "Dining", now))
            c.execute("INSERT INTO merchants(id,display_name,aliases,category,created_at) VALUES(?,?,?,?,?)", (str(uuid.uuid4()), "Uber", json.dumps(["UBER INDIA", "UBER TRIP"]), "Transport", now))
        if bootstrap_admin and AUTH_REQUIRED and c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            email = valid_email(os.environ.get("LEDGER_BOOTSTRAP_ADMIN_EMAIL", ""))
            password = os.environ.get("LEDGER_BOOTSTRAP_ADMIN_PASSWORD", "")
            if not email or len(password) < 16:
                raise RuntimeError("Hosted authentication is enabled, but no users exist. Set LEDGER_BOOTSTRAP_ADMIN_EMAIL and a 16+ character LEDGER_BOOTSTRAP_ADMIN_PASSWORD before starting.")
            user_id = str(uuid.uuid4())
            c.execute("INSERT INTO users(id,email,display_name,password_hash,role,active,created_at) VALUES(?,?,?,?,?,?,?)",
                      (user_id,email,os.environ.get("LEDGER_BOOTSTRAP_ADMIN_NAME", "Household admin")[:80],password_hash(password),"admin",1,utc_now().isoformat(timespec="seconds")))

def _merchant_names(merchant):
    try: aliases = json.loads(merchant["aliases"] or "[]")
    except (TypeError, ValueError): aliases = []
    return [name for name in [merchant["display_name"], merchant["legal_name"] or "", *aliases] if name]

MATCH_GENERIC_WORDS = {"COM","WWW","HTTP","HTTPS","THE","AND","INDIA","PRIVATE","PVT","LTD","LIMITED","ONLINE","OFFICIAL","WEB","APP","SERVICE","SERVICES","COMPANY","GROUP"}

def _merchant_match_score(alias, known_name):
    """Conservative similarity score used to suggest, never silently apply, near matches."""
    alias_key, known_key = merchant_alias_key(alias), merchant_alias_key(known_name)
    if not alias_key or not known_key: return 0.0
    if alias_key == known_key: return 1.0
    score = SequenceMatcher(None, alias_key, known_key).ratio()
    shorter, longer = sorted((alias_key, known_key), key=len)
    if len(shorter) >= 4 and shorter in longer:
        score = max(score, .72 + .18 * (len(shorter) / len(longer)))
    alias_tokens = {merchant_alias_key(word) for word in re.findall(r"[A-Z0-9]+", alias.upper()) if len(word) >= 3 and word not in MATCH_GENERIC_WORDS}
    known_tokens = {merchant_alias_key(word) for word in re.findall(r"[A-Z0-9]+", known_name.upper()) if len(word) >= 3 and word not in MATCH_GENERIC_WORDS}
    if alias_tokens and known_tokens:
        overlap = len(alias_tokens & known_tokens) / min(len(alias_tokens), len(known_tokens))
        if overlap:
            score = max(score, .72 + .23 * overlap)
    return min(score, .99)

def _classify_merchant_alias(alias, merchants):
    """Return an exact merchant or close candidates; only unmatched names are web searched."""
    key = merchant_alias_key(alias)
    if not key: return None, []
    for merchant in merchants:
        if any(merchant_alias_key(name) == key for name in _merchant_names(merchant)):
            return merchant, []
    candidates = []
    for merchant in merchants:
        score = max((_merchant_match_score(alias, name) for name in _merchant_names(merchant)), default=0.0)
        if score >= .78:
            candidates.append({"type":"existing_merchant", "merchant_id":merchant["id"],
                               "title":merchant["display_name"], "description":"Possible existing merchant",
                               "url":"", "match_score":round(score, 3),
                               "suggested_brand_name":merchant["display_name"],
                               "suggested_legal_name":merchant["legal_name"] or ""})
    candidates.sort(key=lambda item: item["match_score"], reverse=True)
    return None, candidates[:3]

def queue_unknown_merchants(statement_id=None, auto_search=False):
    """Classify statement aliases after extraction, keeping every uncertain result reviewable."""
    now = datetime.datetime.now().isoformat(timespec="seconds")
    search_ids = []
    with connect() as c:
        merchants = c.execute("SELECT id,display_name,legal_name,aliases FROM merchants ORDER BY display_name").fetchall()
        rows = c.execute("""SELECT t.id,t.description,t.statement_id FROM transactions t
                            WHERE t.merchant_id IS NULL AND t.kind IN ('Purchase','Refund')""" +
                         (" AND t.statement_id=?" if statement_id else ""),
                         (statement_id,) if statement_id else ()).fetchall()
        statement_alias_keys = set()
        for row in rows:
            alias = merchant_alias_core(row["description"])
            key = merchant_alias_key(alias)
            if key: statement_alias_keys.add(key)
        if not statement_alias_keys: return []

        # Keep occurrence counts and statement references current across the household history.
        all_rows = c.execute("""SELECT t.id,t.description,t.statement_id FROM transactions t
                                WHERE t.merchant_id IS NULL AND t.kind IN ('Purchase','Refund')""").fetchall()
        grouped = {}
        for row in all_rows:
            alias = merchant_alias_core(row["description"])
            key = merchant_alias_key(alias)
            if key not in statement_alias_keys: continue
            item = grouped.setdefault(key, {"alias":alias, "count":0, "statements":set(), "transaction_ids":[]})
            item["count"] += 1
            item["transaction_ids"].append(row["id"])
            if row["statement_id"]: item["statements"].add(row["statement_id"])

        for key, item in grouped.items():
            exact, close = _classify_merchant_alias(item["alias"], merchants)
            prior = c.execute("SELECT id,status FROM merchant_discoveries WHERE alias_key=?", (key,)).fetchone()
            statement_ids = json.dumps(sorted(item["statements"]))
            if exact:
                c.executemany("UPDATE transactions SET merchant_id=? WHERE id=? AND merchant_id IS NULL",
                              [(exact["id"],txid) for txid in item["transaction_ids"]])
                c.execute("""UPDATE merchant_discoveries SET status='approved',approved_merchant_id=?,
                    transaction_count=?,statement_ids=?,results='[]',search_error='',decision_at=? WHERE alias_key=?""",
                    (exact["id"],item["count"],statement_ids,now,key))
                continue
            if prior and prior["status"] in ("approved", "rejected", "review", "searching"):
                c.execute("UPDATE merchant_discoveries SET transaction_count=?,statement_ids=? WHERE alias_key=?",
                          (item["count"],statement_ids,key))
                continue
            status = "close_match" if close else "pending"
            results = json.dumps(close, ensure_ascii=False) if close else "[]"
            if prior:
                c.execute("""UPDATE merchant_discoveries SET raw_alias=?,query_alias=?,transaction_count=?,
                    statement_ids=?,status=?,results=?,search_error='',approved_merchant_id=NULL WHERE alias_key=?""",
                    (item["alias"],item["alias"],item["count"],statement_ids,status,results,key))
                discovery_id = prior["id"]
            else:
                discovery_id = str(uuid.uuid4())
                c.execute("""INSERT INTO merchant_discoveries
                    (id,alias_key,raw_alias,query_alias,transaction_count,statement_ids,status,results,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?)""",
                    (discovery_id,key,item["alias"],item["alias"],item["count"],statement_ids,status,results,now))
            if auto_search and not close and os.environ.get("PARALLEL_API_KEY", "").strip():
                c.execute("UPDATE merchant_discoveries SET status='searching',search_error='' WHERE id=?", (discovery_id,))
                search_ids.append(discovery_id)
            elif auto_search and not close:
                c.execute("UPDATE merchant_discoveries SET search_error='Parallel search is not connected for automatic app lookups.' WHERE id=?", (discovery_id,))
    for discovery_id in search_ids:
        SEARCH_WORKERS.submit(search_discovery, discovery_id)
    return search_ids

def process_statement_discoveries(statement_id):
    """Run merchant classification/search independently from the statement upload response."""
    try:
        queue_unknown_merchants(statement_id, auto_search=True)
    except Exception as exc:
        # Discovery is an optional follow-up; ingestion has already completed and remains successful.
        print("Merchant follow-up failed for statement {}: {}".format(statement_id, str(exc)[:240]))

def search_discovery(discovery_id):
    """Search one merchant alias in the background and leave the result for approval."""
    key = os.environ.get("PARALLEL_API_KEY", "").strip()
    if not key:
        with connect() as c:
            c.execute("UPDATE merchant_discoveries SET status='pending',search_error='Add PARALLEL_API_KEY to the server environment to search.' WHERE id=?", (discovery_id,))
        return
    try:
        with connect() as c:
            row = c.execute("SELECT query_alias,status FROM merchant_discoveries WHERE id=?", (discovery_id,)).fetchone()
        if not row or row["status"] != "searching": return
        result = search_parallel(row["query_alias"], key)
        status = "review" if result["results"] else "no_results"
        with connect() as c:
            c.execute("UPDATE merchant_discoveries SET status=?,results=?,search_query=?,search_error='',searched_at=? WHERE id=?",
                      (status, json.dumps(result["results"], ensure_ascii=False), result["query"], datetime.datetime.now().isoformat(timespec="seconds"), discovery_id))
    except Exception as exc:
        with connect() as c:
            c.execute("UPDATE merchant_discoveries SET status='failed',search_error=?,searched_at=? WHERE id=?",
                      (str(exc)[:500], datetime.datetime.now().isoformat(timespec="seconds"), discovery_id))

def encrypted_backup_status():
    if hosted_database_enabled():
        from hosted_backup import list_hosted_backups
        files = list_hosted_backups()
        configured = bool(os.environ.get("LEDGER_BACKUP_FERNET_KEY", "").strip())
        return {"configured":configured,"interval_hours":24,"retention_count":30,"backups":files,
                "latest":files[0] if files else None}
    from backup import list_backups
    files = list_backups()
    configured = bool(os.environ.get("LEDGER_BACKUP_FERNET_KEY", "").strip())
    return {"configured":configured,"interval_hours":24,"retention_count":30,"backups":files,
            "latest":files[0] if files else None}

def create_encrypted_backup(reason="manual"):
    if hosted_database_enabled():
        from hosted_backup import create_hosted_backup
        return create_hosted_backup(reason=reason)
    from backup import create_backup
    return create_backup(reason=reason)

def scheduled_backup_loop():
    while True:
        try:
            if os.environ.get("LEDGER_BACKUP_FERNET_KEY", "").strip():
                from backup import list_backups
                files = list_backups()
                due = not files
                if files:
                    latest = datetime.datetime.fromisoformat(files[0]["created_at"])
                    due = utc_now() - latest >= datetime.timedelta(hours=24)
                if due: create_encrypted_backup(reason="scheduled")
        except Exception as exc:
            print("Scheduled encrypted backup failed: {}".format(str(exc)[:240]))
        time.sleep(3600)

def transaction_dict(row):
    d = dict(row)
    d["owed_inr"] = round(d["amount_inr"] * d["share_percent"] / 100, 2)
    if d.get("source_bbox"):
        try: d["source_bbox"] = json.loads(d["source_bbox"])
        except (TypeError, ValueError): d["source_bbox"] = None
    return d

def allocation_suggestions(rows, merchant_rules):
    """Return conservative recurring allocation suggestions; never assign automatically."""
    groups = {}
    for row in rows:
        if row["kind"] != "Purchase" or row["allocation"] not in ("Shared", "Wife personal", "Your personal"):
            continue
        merchant_key = row["merchant_id"] or re.sub(r"[^A-Z0-9]", "", row["description"].upper())
        key = (merchant_key, row["person"])
        groups.setdefault(key, []).append(row["allocation"])
    result = {}
    for row in rows:
        if row["kind"] == "Card payment": continue
        rule = merchant_rules.get(row["merchant_id"])
        if rule and rule["allocation_suggestion"] and rule["suggestion_person"] in ("Any", row["person"]):
            result[row["id"]] = (rule["allocation_suggestion"], "Merchant rule")
            continue
        merchant_key = row["merchant_id"] or re.sub(r"[^A-Z0-9]", "", row["description"].upper())
        history = groups.get((merchant_key, row["person"]), [])
        if row["person"] == "Unknown":
            history = [a for (k, _), values in groups.items() if k == merchant_key for a in values]
        if len(history) < 2: continue
        counts = {}
        for allocation in history: counts[allocation] = counts.get(allocation, 0) + 1
        candidate, count = max(counts.items(), key=lambda item: item[1])
        if count / len(history) >= 0.8:
            result[row["id"]] = (candidate, "{} of {} reviewed".format(count, len(history)))
    return result

def recalculate_statement(c, statement_id):
    statement = c.execute("SELECT expected_charges_inr FROM statements WHERE id=?", (statement_id,)).fetchone()
    if not statement: return
    totals = c.execute("SELECT COUNT(*) n,COALESCE(SUM(CASE WHEN kind!='Card payment' THEN amount_inr ELSE 0 END),0) amount FROM transactions WHERE statement_id=?", (statement_id,)).fetchone()
    expected = statement["expected_charges_inr"]
    extracted = round(float(totals["amount"]), 2)
    difference = round(extracted-float(expected), 2) if expected is not None else None
    status = "matched" if difference is not None and abs(difference) <= 1 else ("needs attention" if difference is not None else "unavailable")
    c.execute("UPDATE statements SET transaction_count=?,extracted_charges_inr=?,reconciliation_difference_inr=?,reconciliation_status=? WHERE id=?", (totals["n"],extracted,difference,status,statement_id))

def json_bytes(obj): return json.dumps(obj, ensure_ascii=False).encode()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'")
        if SECURE_COOKIES: self.send_header("Strict-Transport-Security", "max-age=31536000")
        super().end_headers()
    def send_json(self, obj, code=200, extra_headers=()):
        body = json_bytes(obj); self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store")
        for name, value in extra_headers: self.send_header(name, value)
        self.end_headers(); self.wfile.write(body)
    def body(self):
        n = int(self.headers.get("Content-Length", 0)); return self.rfile.read(n)
    def cookie_value(self, name):
        try:
            cookie = SimpleCookie(); cookie.load(self.headers.get("Cookie", ""))
            return cookie[name].value if name in cookie else ""
        except Exception: return ""
    def cookie_header(self, name, value, max_age=None, httponly=True, samesite="Lax"):
        bits = [f"{name}={value}", "Path=/", f"SameSite={samesite}"]
        if httponly: bits.append("HttpOnly")
        if SECURE_COOKIES: bits.append("Secure")
        if max_age is not None: bits.append(f"Max-Age={int(max_age)}")
        return "; ".join(bits)
    def current_user(self):
        if not AUTH_REQUIRED:
            return {"id":"local-owner","email":"","display_name":"Local owner","role":"admin","active":1}
        token = self.cookie_value(SESSION_COOKIE)
        if not token: return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        with connect() as c:
            row = c.execute("""SELECT u.id,u.email,u.display_name,u.role,u.active,s.csrf_token,s.expires_at
                FROM auth_sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?""",(digest,)).fetchone()
            if not row: return None
            if not row["active"] or row["expires_at"] <= utc_now().isoformat(timespec="seconds"):
                c.execute("DELETE FROM auth_sessions WHERE token_hash=?",(digest,)); return None
        self.session_token_hash = digest
        self.session_csrf_token = row["csrf_token"]
        return {k:row[k] for k in ("id","email","display_name","role","active")}
    def origin_is_same_site(self):
        origin = self.headers.get("Origin", "")
        host = self.headers.get("Host", "")
        if not origin or not host: return False
        from urllib.parse import urlsplit
        try:
            parsed = urlsplit(origin)
            request_host = urlsplit("//" + host)
            expected_scheme = "https" if SECURE_COOKIES else "http"
            if (parsed.scheme != expected_scheme or not parsed.hostname or not request_host.hostname
                    or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
                return False
            origin_port = parsed.port or (443 if parsed.scheme == "https" else 80)
            request_port = request_host.port or (443 if expected_scheme == "https" else 80)
            return parsed.hostname.rstrip(".").lower() == request_host.hostname.rstrip(".").lower() and origin_port == request_port
        except ValueError:
            return False
    def secure_proxy_request(self):
        if not SECURE_COOKIES: return True
        # The TLS ingress must replace this header; direct HTTP requests must never serve the sign-in form.
        forwarded = self.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip().lower()
        return forwarded == "https"
    def authorize(self, mutate=False, admin=False):
        user = self.current_user()
        if not user:
            self.send_json({"error":"Sign in required"},401); return False
        self.user = user
        if admin and user["role"] != "admin":
            self.send_json({"error":"Administrator access required"},403); return False
        if mutate and AUTH_REQUIRED:
            supplied = self.headers.get("X-CSRF-Token", "")
            if not self.origin_is_same_site() or not hmac.compare_digest(supplied, getattr(self,"session_csrf_token","")):
                self.send_json({"error":"Request verification failed. Reload the page and try again."},403); return False
        return True
    def send_static(self, filename, content_type=None):
        file_path = ROOT / filename
        if not file_path.is_file(): return self.send_json({"error":"Not found"},404)
        body = file_path.read_bytes(); self.send_response(200)
        self.send_header("Content-Type",content_type or (mimetypes.guess_type(filename)[0] or "application/octet-stream")+"; charset=utf-8")
        self.send_header("Content-Length",str(len(body))); self.send_header("Cache-Control","no-cache")
        self.end_headers(); self.wfile.write(body)
    def send_login_page(self):
        return self.send_static("login.html","text/html; charset=utf-8")
    def auth_status(self):
        if not AUTH_REQUIRED:
            return self.send_json({"auth_required":False,"authenticated":True,"user":self.current_user(),"csrf_token":""})
        user = self.current_user()
        if user:
            return self.send_json({"auth_required":True,"authenticated":True,"user":user,"csrf_token":self.session_csrf_token})
        csrf = self.cookie_value(LOGIN_CSRF_COOKIE) or secrets.token_urlsafe(32)
        return self.send_json({"auth_required":True,"authenticated":False,"csrf_token":csrf},extra_headers=[("Set-Cookie",self.cookie_header(LOGIN_CSRF_COOKIE,csrf,httponly=True,samesite="Strict"))])
    def logout(self):
        if AUTH_REQUIRED:
            supplied = self.headers.get("X-CSRF-Token", "")
            if not self.origin_is_same_site() or not supplied:
                return self.send_json({"error":"Request verification failed. Reload the page and try again."},403)
            token = self.cookie_value(SESSION_COOKIE)
            digest = hashlib.sha256(token.encode()).hexdigest() if token else ""
            now = utc_now().isoformat(timespec="seconds")
            with connect() as c:
                removed = c.execute("""DELETE FROM auth_sessions
                    WHERE token_hash=? AND csrf_token=? AND expires_at>?
                    AND user_id IN (SELECT id FROM users WHERE active=1)""",
                    (digest,supplied,now))
            if removed.rowcount != 1:
                return self.send_json({"error":"Your session has ended. Sign in again."},401)
        return self.send_json({"ok":True},extra_headers=[("Set-Cookie",self.cookie_header(SESSION_COOKIE,"",max_age=0)),("Set-Cookie",self.cookie_header(LOGIN_CSRF_COOKIE,"",max_age=0,samesite="Strict"))])
    def login(self):
        if not AUTH_REQUIRED: return self.send_json({"error":"Sign-in is not enabled in local mode"},404)
        if not self.origin_is_same_site() or not hmac.compare_digest(self.headers.get("X-CSRF-Token",""),self.cookie_value(LOGIN_CSRF_COOKIE)):
            return self.send_json({"error":"Request verification failed. Reload the page and try again."},403)
        try:
            d=json.loads(self.body()); email=valid_email(d.get("email")); password=d.get("password","")
            remote_ip=self.client_address[0]
            if not email or not isinstance(password,str): return self.send_json({"error":"Email or password is incorrect"},401)
            cutoff=(utc_now()-datetime.timedelta(minutes=15)).isoformat(timespec="seconds")
            with connect() as c:
                failures=c.execute("SELECT COUNT(*) FROM auth_login_attempts WHERE attempted_at>? AND (remote_ip=? OR email=?)",(cutoff,remote_ip,email)).fetchone()[0]
                if failures >= 8: return self.send_json({"error":"Too many sign-in attempts. Try again in 15 minutes."},429)
                row=c.execute("SELECT * FROM users WHERE email=? AND active=1",(email,)).fetchone()
                encoded=row["password_hash"] if row else DUMMY_PASSWORD_HASH
                valid=password_matches(password,encoded)
                if not row or not valid:
                    c.execute("INSERT INTO auth_login_attempts(remote_ip,email,attempted_at) VALUES(?,?,?)",(remote_ip,email,utc_now().isoformat(timespec="seconds")))
                    return self.send_json({"error":"Email or password is incorrect"},401)
                token=secrets.token_urlsafe(48); token_hash=hashlib.sha256(token.encode()).hexdigest(); csrf=secrets.token_urlsafe(32)
                created=utc_now(); expires=created+datetime.timedelta(days=SESSION_DAYS)
                c.execute("INSERT INTO auth_sessions(token_hash,user_id,csrf_token,created_at,expires_at) VALUES(?,?,?,?,?)",(token_hash,row["id"],csrf,created.isoformat(timespec="seconds"),expires.isoformat(timespec="seconds")))
                c.execute("UPDATE users SET last_login_at=? WHERE id=?",(created.isoformat(timespec="seconds"),row["id"]))
                c.execute("DELETE FROM auth_login_attempts WHERE attempted_at<?",(cutoff,))
            cookie=self.cookie_header(SESSION_COOKIE,token,max_age=SESSION_DAYS*86400,httponly=True,samesite="Lax")
            return self.send_json({"ok":True},extra_headers=[("Set-Cookie",cookie),("Set-Cookie",self.cookie_header(LOGIN_CSRF_COOKIE,"",max_age=0,httponly=True,samesite="Strict"))])
        except Exception as exc: return self.send_json({"error":str(exc)},400)
    def _passkey_request_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > 128 * 1024:
            raise ValueError("Invalid passkey request")
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict): raise ValueError("Invalid passkey request")
        return data
    def _passkey_origin_config(self):
        if not self.origin_is_same_site():
            raise ValueError("Passkey request origin is not allowed")
        origin = self.headers.get("Origin", "")
        configured_origin = os.environ.get("WEBAUTHN_ORIGIN", "").strip().rstrip("/")
        configured_rp_id = os.environ.get("WEBAUTHN_RP_ID", "").strip().lower().rstrip(".")
        if AUTH_REQUIRED and (not configured_origin or not configured_rp_id):
            raise RuntimeError("Passkeys are not configured for this sign-in address")
        expected_origin = configured_origin or origin
        if origin != expected_origin:
            raise ValueError("Passkey request origin is not allowed")
        from urllib.parse import urlsplit
        parsed = urlsplit(expected_origin)
        if (parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment):
            raise ValueError("Passkey origin configuration is invalid")
        if AUTH_REQUIRED and parsed.scheme != "https":
            raise ValueError("Passkeys require a secure sign-in address")
        rp_id = configured_rp_id or parsed.hostname.lower().rstrip(".")
        if not re.fullmatch(r"[a-z0-9.-]+", rp_id) or "." not in rp_id and rp_id != "localhost":
            raise ValueError("Passkey relying-party configuration is invalid")
        if parsed.hostname.lower().rstrip(".") != rp_id and not parsed.hostname.lower().rstrip(".").endswith("." + rp_id):
            raise ValueError("Passkey origin does not match its relying-party ID")
        return expected_origin, rp_id
    def _login_csrf_is_valid(self):
        supplied = self.headers.get("X-CSRF-Token", "")
        return (self.origin_is_same_site() and bool(supplied)
                and hmac.compare_digest(supplied, self.cookie_value(LOGIN_CSRF_COOKIE)))
    def _consume_webauthn_challenge(self, challenge_id, purpose, user_id=None, connection=None):
        if not isinstance(challenge_id, str) or not re.fullmatch(r"[0-9a-f-]{36}", challenge_id):
            return None
        now = utc_now().isoformat(timespec="seconds")
        def consume(c):
            if user_id is None:
                row = c.execute("""SELECT * FROM webauthn_challenges WHERE id=? AND purpose=?
                    AND user_id IS NULL AND consumed_at IS NULL AND expires_at>?""", (challenge_id,purpose,now)).fetchone()
            else:
                row = c.execute("""SELECT * FROM webauthn_challenges WHERE id=? AND purpose=?
                    AND user_id=? AND consumed_at IS NULL AND expires_at>?""", (challenge_id,purpose,user_id,now)).fetchone()
            if not row: return None
            changed = c.execute("UPDATE webauthn_challenges SET consumed_at=? WHERE id=? AND consumed_at IS NULL",(now,challenge_id))
            if changed.rowcount != 1: return None
            return dict(row)
        if connection is not None:
            return consume(connection)
        with connect() as c:
            return consume(c)
    def _save_webauthn_challenge(self, purpose, challenge, user_id=None, nickname="Passkey", connection=None):
        now = utc_now()
        expires = now + datetime.timedelta(minutes=5)
        challenge_id = str(uuid.uuid4())
        def save(c):
            c.execute("DELETE FROM webauthn_challenges WHERE expires_at<? OR (consumed_at IS NOT NULL AND consumed_at<?)",
                      (now.isoformat(timespec="seconds"),(now-datetime.timedelta(days=1)).isoformat(timespec="seconds")))
            c.execute("""INSERT INTO webauthn_challenges(id,user_id,purpose,challenge,nickname,remote_ip,created_at,expires_at)
                VALUES(?,?,?,?,?,?,?,?)""",(challenge_id,user_id,purpose,b64url_encode(challenge),nickname,
                self.client_address[0],now.isoformat(timespec="seconds"),expires.isoformat(timespec="seconds")))
        if connection is not None:
            save(connection)
        else:
            with connect() as c:
                save(c)
        return challenge_id
    def _create_passkey_session(self, user_id, credential_id, sign_count, device_type, backed_up, connection=None):
        token = secrets.token_urlsafe(48)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        csrf = secrets.token_urlsafe(32)
        created = utc_now(); expires = created + datetime.timedelta(days=SESSION_DAYS)
        stamp = created.isoformat(timespec="seconds")
        def create(c):
            user = c.execute("SELECT id FROM users WHERE id=? AND active=1",(user_id,)).fetchone()
            if not user: return False
            changed = c.execute("""UPDATE passkeys SET last_used_at=?,sign_count=?,device_type=?,backed_up=?
                WHERE user_id=? AND credential_id=?""",(stamp,sign_count,device_type,backed_up,user_id,credential_id))
            if changed.rowcount != 1: return False
            c.execute("INSERT INTO auth_sessions(token_hash,user_id,csrf_token,created_at,expires_at) VALUES(?,?,?,?,?)",
                      (token_hash,user_id,csrf,stamp,expires.isoformat(timespec="seconds")))
            c.execute("UPDATE users SET last_login_at=? WHERE id=?",(stamp,user_id))
            c.execute("DELETE FROM auth_passkey_login_attempts WHERE remote_ip=?",(self.client_address[0],))
            return True
        if connection is not None:
            created_ok = create(connection)
            if created_ok:
                connection.commit()
        else:
            with connect() as c:
                created_ok = create(c)
        if not created_ok:
            return self.send_json({"error":"Passkey sign-in failed. Use your password or try again."},401)
        return self.send_json({"ok":True},extra_headers=[("Set-Cookie",self.cookie_header(SESSION_COOKIE,token,max_age=SESSION_DAYS*86400,httponly=True,samesite="Lax")),
                                                          ("Set-Cookie",self.cookie_header(LOGIN_CSRF_COOKIE,"",max_age=0,httponly=True,samesite="Strict"))])
    def list_passkeys(self):
        if not self.authorize(): return
        if not AUTH_REQUIRED: return self.send_json([])
        with connect() as c:
            rows = c.execute("""SELECT id,nickname,device_type,backed_up,created_at,last_used_at,transports
                FROM passkeys WHERE user_id=? ORDER BY created_at DESC""",(self.user["id"],)).fetchall()
        return self.send_json([dict(r,transports=json.loads(r["transports"] or "[]")) for r in rows])
    def passkey_registration_options(self):
        if not self.authorize(mutate=True): return
        if not AUTH_REQUIRED: return self.send_json({"error":"Passkeys require hosted sign-in"},404)
        try:
            from webauthn import generate_registration_options, options_to_json
            from webauthn.helpers.structs import (AuthenticatorAttachment, AuthenticatorSelectionCriteria,
                PublicKeyCredentialDescriptor, ResidentKeyRequirement, UserVerificationRequirement)
        except ImportError:
            return self.send_json({"error":"Passkey support is unavailable on this server"},503)
        try:
            origin, rp_id = self._passkey_origin_config()
            data = self._passkey_request_json()
            nickname = (data.get("nickname") or "Passkey").strip()
            if not nickname or len(nickname) > 60: raise ValueError("Name the passkey in 1 to 60 characters")
            with connect() as c:
                saved = c.execute("SELECT credential_id FROM passkeys WHERE user_id=? ORDER BY created_at",(self.user["id"],)).fetchall()
                if len(saved) >= 10: return self.send_json({"error":"Remove a passkey before adding another (maximum 10 per account)."},409)
            challenge = secrets.token_bytes(32)
            options = generate_registration_options(
                rp_id=rp_id, rp_name="Household Ledger", user_id=uuid.UUID(self.user["id"]).bytes,
                user_name=self.user["email"], user_display_name=self.user["display_name"], challenge=challenge,
                authenticator_selection=AuthenticatorSelectionCriteria(
                    authenticator_attachment=AuthenticatorAttachment.PLATFORM,
                    resident_key=ResidentKeyRequirement.REQUIRED,
                    user_verification=UserVerificationRequirement.REQUIRED),
                exclude_credentials=[PublicKeyCredentialDescriptor(id=b64url_decode(row["credential_id"])) for row in saved])
            challenge_id = self._save_webauthn_challenge("register",challenge,self.user["id"],nickname)
            return self.send_json({"challenge_id":challenge_id,"public_key":json.loads(options_to_json(options))})
        except ValueError as exc: return self.send_json({"error":str(exc)},400)
        except Exception: return self.send_json({"error":"Could not prepare passkey setup. Reload and try again."},400)
    def verify_passkey_registration(self):
        if not self.authorize(mutate=True): return
        if not AUTH_REQUIRED: return self.send_json({"error":"Passkeys require hosted sign-in"},404)
        data = None
        try:
            from webauthn import verify_registration_response
            data = self._passkey_request_json()
            if not isinstance(data.get("credential"),dict): raise ValueError("Missing passkey response")
            challenge = self._consume_webauthn_challenge(data.get("challenge_id"),"register",self.user["id"])
            if not challenge: return self.send_json({"error":"That passkey setup expired. Start again."},400)
            origin, rp_id = self._passkey_origin_config()
            result = verify_registration_response(credential=data.get("credential"),
                expected_challenge=b64url_decode(challenge["challenge"]), expected_origin=origin,
                expected_rp_id=rp_id, require_user_verification=True)
            credential_id = b64url_encode(result.credential_id)
            public_key = b64url_encode(result.credential_public_key)
            if not credential_id or not public_key: raise ValueError("Credential data was incomplete")
            transports = data.get("credential",{}).get("response",{}).get("transports",[])
            allowed_transports = {"usb","nfc","ble","internal","hybrid"}
            transports = sorted({x for x in transports if isinstance(x,str) and x in allowed_transports}) if isinstance(transports,list) else []
            device_type = getattr(result.credential_device_type,"value",str(result.credential_device_type))
            with connect() as c:
                c.execute("""INSERT INTO passkeys(id,credential_id,user_id,public_key,sign_count,transports,nickname,device_type,backed_up,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?)""",(str(uuid.uuid4()),credential_id,self.user["id"],public_key,
                    int(result.sign_count),json.dumps(transports),challenge["nickname"],str(device_type),
                    1 if result.credential_backed_up else 0,utc_now().isoformat(timespec="seconds")))
            return self.send_json({"ok":True})
        except Exception as exc:
            if getattr(exc,"sqlstate","") == "23505" or isinstance(exc,sqlite3.IntegrityError):
                return self.send_json({"error":"This passkey is already registered to a household account."},409)
            return self.send_json({"error":"Could not verify the passkey. Start setup again."},400)
    def rename_passkey(self, passkey_id):
        if not self.authorize(mutate=True): return
        try:
            data = self._passkey_request_json(); nickname = (data.get("nickname") or "").strip()
            if not nickname or len(nickname)>60: raise ValueError("Use a name between 1 and 60 characters")
            with connect() as c:
                changed = c.execute("UPDATE passkeys SET nickname=? WHERE id=? AND user_id=?",(nickname,passkey_id,self.user["id"]))
            if changed.rowcount != 1: return self.send_json({"error":"Passkey not found"},404)
            return self.send_json({"ok":True})
        except Exception as exc: return self.send_json({"error":str(exc)},400)
    def remove_passkey(self, passkey_id):
        if not self.authorize(mutate=True): return
        with connect() as c:
            changed = c.execute("DELETE FROM passkeys WHERE id=? AND user_id=?",(passkey_id,self.user["id"]))
        if changed.rowcount != 1: return self.send_json({"error":"Passkey not found"},404)
        return self.send_json({"ok":True})
    def passkey_login_options(self):
        if not AUTH_REQUIRED: return self.send_json({"error":"Sign-in is not enabled in local mode"},404)
        if not self._login_csrf_is_valid(): return self.send_json({"error":"Request verification failed. Reload and try again."},403)
        try:
            from webauthn import generate_authentication_options, options_to_json
            from webauthn.helpers.structs import UserVerificationRequirement
            origin, rp_id = self._passkey_origin_config()
            cutoff = (utc_now()-datetime.timedelta(minutes=15)).isoformat(timespec="seconds")
            with connect() as c:
                failures = c.execute("SELECT COUNT(*) FROM auth_passkey_login_attempts WHERE remote_ip=? AND attempted_at>?",(self.client_address[0],cutoff)).fetchone()[0]
                if failures >= 8: return self.send_json({"error":"Too many passkey attempts. Try again in 15 minutes or use your password."},429)
                starts = c.execute("SELECT COUNT(*) FROM webauthn_challenges WHERE purpose='login' AND remote_ip=? AND created_at>?",(self.client_address[0],cutoff)).fetchone()[0]
                if starts >= 20: return self.send_json({"error":"Too many passkey requests. Try again in 15 minutes or use your password."},429)
                challenge = secrets.token_bytes(32)
                options = generate_authentication_options(rp_id=rp_id,challenge=challenge,allow_credentials=[],
                    user_verification=UserVerificationRequirement.REQUIRED)
                challenge_id = self._save_webauthn_challenge("login",challenge,connection=c)
            return self.send_json({"challenge_id":challenge_id,"public_key":json.loads(options_to_json(options))})
        except RuntimeError as exc: return self.send_json({"error":str(exc)},503)
        except ImportError: return self.send_json({"error":"Passkey support is unavailable on this server"},503)
        except Exception: return self.send_json({"error":"Could not start passkey sign-in. Use your password or try again."},400)
    def verify_passkey_login(self):
        if not AUTH_REQUIRED: return self.send_json({"error":"Sign-in is not enabled in local mode"},404)
        if not self._login_csrf_is_valid(): return self.send_json({"error":"Request verification failed. Reload and try again."},403)
        try:
            from webauthn import verify_authentication_response
            data = self._passkey_request_json()
            with connect() as c:
                challenge = self._consume_webauthn_challenge(data.get("challenge_id"),"login",connection=c)
                if not challenge: raise ValueError("Expired passkey challenge")
                # Persist one-time use before validating the assertion, including failed assertions.
                c.commit()
                credential = data.get("credential")
                if not isinstance(credential,dict) or not isinstance(credential.get("id"),str): raise ValueError("Missing passkey response")
                credential_id = credential["id"]
                row = c.execute("""SELECT p.credential_id,p.user_id,p.public_key,p.sign_count,u.active
                    FROM passkeys p JOIN users u ON u.id=p.user_id WHERE p.credential_id=?""",(credential_id,)).fetchone()
                if not row or not row["active"]: raise ValueError("Unknown passkey")
                origin, rp_id = self._passkey_origin_config()
                verified = verify_authentication_response(credential=credential,
                    expected_challenge=b64url_decode(challenge["challenge"]),expected_origin=origin,expected_rp_id=rp_id,
                    credential_public_key=b64url_decode(row["public_key"]),credential_current_sign_count=int(row["sign_count"]),
                    require_user_verification=True)
                if b64url_encode(verified.credential_id) != row["credential_id"]: raise ValueError("Passkey identifier mismatch")
                user_handle = credential.get("response",{}).get("userHandle")
                if user_handle and b64url_decode(user_handle) != uuid.UUID(row["user_id"]).bytes:
                    raise ValueError("Passkey account mismatch")
                device_type = str(getattr(verified.credential_device_type,"value",verified.credential_device_type))
                return self._create_passkey_session(row["user_id"],row["credential_id"],int(verified.new_sign_count),
                    device_type,1 if verified.credential_backed_up else 0,connection=c)
        except ImportError: return self.send_json({"error":"Passkey support is unavailable on this server"},503)
        except Exception:
            cutoff = (utc_now()-datetime.timedelta(minutes=15)).isoformat(timespec="seconds")
            with connect() as c:
                c.execute("INSERT INTO auth_passkey_login_attempts(remote_ip,attempted_at) VALUES(?,?)",(self.client_address[0],utc_now().isoformat(timespec="seconds")))
                c.execute("DELETE FROM auth_passkey_login_attempts WHERE attempted_at<?",(cutoff,))
            return self.send_json({"error":"Passkey sign-in failed. Try again or use your password."},401)
    def admin_users(self):
        if not self.authorize(admin=True): return
        with connect() as c:
            rows=c.execute("SELECT id,email,display_name,role,active,created_at,last_login_at FROM users ORDER BY created_at").fetchall()
        return self.send_json([dict(row) for row in rows])
    def create_user(self):
        if not self.authorize(mutate=True,admin=True): return
        try:
            d=json.loads(self.body()); email=valid_email(d.get("email")); name=(d.get("display_name") or "").strip(); password=d.get("password",""); role=d.get("role","user")
            if not email: raise ValueError("Enter a valid email address")
            if not name or len(name)>80: raise ValueError("Enter a name up to 80 characters")
            if not valid_password(password): raise ValueError("Use a password between 12 and 1024 characters")
            if role not in ("admin","user"): raise ValueError("Choose Admin or Member")
            with connect() as c:
                c.execute("INSERT INTO users(id,email,display_name,password_hash,role,active,created_at) VALUES(?,?,?,?,?,?,?)",
                          (str(uuid.uuid4()),email,name,password_hash(password),role,1,utc_now().isoformat(timespec="seconds")))
            return self.send_json({"ok":True},201)
        except Exception as exc:
            if isinstance(exc, sqlite3.IntegrityError) or getattr(exc, "sqlstate", "") == "23505":
                return self.send_json({"error":"That email already has an account"},409)
            return self.send_json({"error":str(exc)},400)
        except Exception as exc: return self.send_json({"error":str(exc)},400)
    def update_user(self, user_id):
        if not self.authorize(mutate=True,admin=True): return
        try:
            d=json.loads(self.body()); name=(d.get("display_name") or "").strip(); role=d.get("role"); active=1 if d.get("active") else 0
            if not name or len(name)>80: raise ValueError("Enter a name up to 80 characters")
            if role not in ("admin","user"): raise ValueError("Choose Admin or Member")
            with connect() as c:
                target=c.execute("SELECT id,role,active FROM users WHERE id=?",(user_id,)).fetchone()
                if not target: return self.send_json({"error":"User not found"},404)
                if user_id==self.user["id"] and (not active or role!="admin"):
                    raise ValueError("You cannot deactivate or demote your own admin account")
                if target["role"]=="admin" and (role!="admin" or not active):
                    admins=c.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1 AND id!=?",(user_id,)).fetchone()[0]
                    if admins==0: raise ValueError("Keep at least one active administrator")
                c.execute("UPDATE users SET display_name=?,role=?,active=? WHERE id=?",(name,role,active,user_id))
                if not active or role!=target["role"]: c.execute("DELETE FROM auth_sessions WHERE user_id=?",(user_id,))
            return self.send_json({"ok":True})
        except Exception as exc: return self.send_json({"error":str(exc)},400)
    def reset_user_password(self, user_id):
        if not self.authorize(mutate=True,admin=True): return
        try:
            d=json.loads(self.body()); password=d.get("password","")
            if not valid_password(password): raise ValueError("Use a password between 12 and 1024 characters")
            with connect() as c:
                if not c.execute("SELECT 1 FROM users WHERE id=?",(user_id,)).fetchone(): return self.send_json({"error":"User not found"},404)
                c.execute("UPDATE users SET password_hash=? WHERE id=?",(password_hash(password),user_id))
                c.execute("DELETE FROM auth_sessions WHERE user_id=?",(user_id,))
            return self.send_json({"ok":True})
        except Exception as exc: return self.send_json({"error":str(exc)},400)
    def change_password(self):
        if not self.authorize(mutate=True): return
        if not AUTH_REQUIRED: return self.send_json({"error":"Sign-in is not enabled in local mode"},404)
        try:
            d=json.loads(self.body()); old=d.get("current_password",""); new=d.get("new_password","")
            if not valid_password(new): raise ValueError("Use a password between 12 and 1024 characters")
            with connect() as c:
                row=c.execute("SELECT password_hash FROM users WHERE id=?",(self.user["id"],)).fetchone()
                if not row or not password_matches(old,row["password_hash"]): return self.send_json({"error":"Current password is incorrect"},400)
                c.execute("UPDATE users SET password_hash=? WHERE id=?",(password_hash(new),self.user["id"]))
                c.execute("DELETE FROM auth_sessions WHERE user_id=?",(self.user["id"],))
            return self.send_json({"ok":True},extra_headers=[("Set-Cookie",self.cookie_header(SESSION_COOKIE,"",max_age=0))])
        except Exception as exc: return self.send_json({"error":str(exc)},400)
    def send_snapshot(self, tid):
        with connect() as c:
            row = c.execute("""SELECT t.id,t.source_page,t.source_bbox,t.statement_id,s.file_path
                              FROM transactions t LEFT JOIN statements s ON s.id=t.statement_id WHERE t.id=?""", (tid,)).fetchone()
        if not row or not row["statement_id"] or not row["source_page"] or not row["source_bbox"]:
            raise FileNotFoundError("No OCR line snapshot is available for this transaction")
        SNAPSHOT_CACHE.mkdir(parents=True, exist_ok=True); PAGE_CACHE.mkdir(parents=True, exist_ok=True)
        cached = SNAPSHOT_CACHE / (tid + ".png")
        if not cached.exists():
            statement_id, page = row["statement_id"], int(row["source_page"])
            prefix = PAGE_CACHE / (statement_id + "-render-{:02d}".format(page))
            page_image = PAGE_CACHE / (statement_id + "-page-{:02d}.png".format(page))
            if not page_image.exists():
                _, _, pdftoppm = _runtime_paths()
                subprocess.run([pdftoppm, "-f", str(page), "-l", str(page), "-png", "-scale-to", "2400",
                                str(local_statement_path(row["file_path"])), str(prefix)], check=True, stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE, timeout=120)
                candidates = sorted(PAGE_CACHE.glob(prefix.name + "-*.png"))
                if candidates:
                    rendered = candidates[-1]
                    if rendered != page_image: rendered.replace(page_image)
            if not page_image.exists(): raise FileNotFoundError("Could not render the statement page")
            bbox = json.loads(row["source_bbox"])
            try:
                from PIL import Image
                with Image.open(page_image) as image:
                    width, page_height = image.size
                    y0, y1 = max(0, int(bbox[1]) - 10), min(page_height, int(bbox[3]) + 10)
                    height = max(36, min(110, y1 - y0))
                    y0 = min(y0, max(0, page_height-height))
                    image.crop((0, y0, width, min(page_height, y0 + height))).save(cached, format="PNG", optimize=True)
            except ImportError:
                # Keep the existing local macOS workflow working without a fresh pip install.
                sips = shutil.which("sips")
                if not sips: raise RuntimeError("OCR snapshot cropping is unavailable. Install dependencies from requirements.txt.")
                dimensions = subprocess.run([sips, "-g", "pixelWidth", "-g", "pixelHeight", str(page_image)],
                                            check=True, capture_output=True, text=True, timeout=20).stdout
                dim = re.findall(r"pixel(?:Width|Height):\s*(\d+)", dimensions)
                if len(dim) != 2: raise RuntimeError("Could not read the rendered page dimensions")
                width, page_height = int(dim[0]), int(dim[1])
                y0, y1 = max(0, int(bbox[1]) - 10), min(page_height, int(bbox[3]) + 10)
                height = max(36, min(110, y1 - y0))
                y0 = min(y0, max(0, page_height-height))
                subprocess.run([sips, "-c", str(height), str(width), "--cropOffset", str(y0), "0",
                                str(page_image), "--out", str(cached)], check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30)
        data = cached.read_bytes(); self.send_response(200); self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(data))); self.send_header("Cache-Control", "private, no-store")
        self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        u = urlparse(self.path); path = u.path
        if path == "/healthz": return self.send_json({"ok":True})
        if not self.secure_proxy_request(): return self.send_json({"error":"HTTPS through the trusted proxy is required"},400)
        if path == "/api/cron/backup":
            expected=os.environ.get("CRON_SECRET", "") or os.environ.get("LEDGER_BACKUP_CRON_SECRET", "")
            supplied=self.headers.get("Authorization", "")
            if not expected or not hmac.compare_digest(supplied, "Bearer " + expected):
                return self.send_json({"error":"Not found"},404)
            try: return self.send_json({"ok":True,"backup":create_encrypted_backup(reason="scheduled")})
            except Exception as exc: return self.send_json({"error":str(exc)},500)
        if path == "/api/auth/status": return self.auth_status()
        if path == "/api/auth/passkeys": return self.list_passkeys()
        if path == "/api/admin/users": return self.admin_users()
        if path == "/api/admin/backups":
            if not self.authorize(admin=True): return
            try: return self.send_json(encrypted_backup_status())
            except Exception as exc: return self.send_json({"error":str(exc)},500)
        if path.startswith("/api/admin/backups/"):
            if not self.authorize(admin=True): return
            name=path.rsplit("/",1)[-1]
            if Path(name).name!=name or not name.startswith("ledger-") or not name.endswith(".hlb"):
                return self.send_json({"error":"Invalid backup name"},400)
            if hosted_database_enabled():
                try: body=__import__("hosted_backup").download_hosted_backup(name)
                except FileNotFoundError: return self.send_json({"error":"Backup not found"},404)
                except Exception as exc: return self.send_json({"error":str(exc)},500)
                self.send_response(200); self.send_header("Content-Type","application/octet-stream")
                self.send_header("Content-Disposition",'attachment; filename="'+name+'"'); self.send_header("Content-Length",str(len(body)))
                self.send_header("Cache-Control","private, no-store"); self.end_headers(); return self.wfile.write(body)
            backup_path=DATA/"backups"/name
            if not backup_path.is_file(): return self.send_json({"error":"Backup not found"},404)
            body=backup_path.read_bytes(); self.send_response(200); self.send_header("Content-Type","application/octet-stream")
            self.send_header("Content-Disposition",'attachment; filename="'+name+'"'); self.send_header("Content-Length",str(len(body)))
            self.send_header("Cache-Control","private, no-store"); self.end_headers(); return self.wfile.write(body)
        if path in ("/login.html","/login.js","/login.css","/theme.js","/icons.svg"):
            return self.send_static(path[1:])
        if path == "/" or path == "/index.html":
            if AUTH_REQUIRED and not self.current_user(): return self.send_login_page()
            return self.send_static("index.html","text/html; charset=utf-8")
        if path in ("/style.css","/app.js"):
            return self.send_static(path[1:])
        if not self.authorize(): return
        if path == "/api/transactions":
            with connect() as c:
                rows = c.execute("""SELECT t.*,m.display_name merchant,s.bank,s.card_name,s.statement_month FROM transactions t LEFT JOIN merchants m ON m.id=t.merchant_id LEFT JOIN statements s ON s.id=t.statement_id ORDER BY t.date DESC,t.created_at DESC""").fetchall()
                rules = {r["id"]: r for r in c.execute("SELECT id,allocation_suggestion,suggestion_person FROM merchants")}
                total = c.execute("SELECT COALESCE(SUM(amount_inr*share_percent/100),0) FROM transactions").fetchone()[0]
            suggestions = allocation_suggestions(rows, rules)
            items = []
            for row in rows:
                item = transaction_dict(row)
                if row["id"] in suggestions:
                    item["suggested_allocation"], item["suggestion_reason"] = suggestions[row["id"]]
                items.append(item)
            return self.send_json({"items":items,"owed_inr":round(total,2)})
        if path == "/api/merchants":
            with connect() as c: rows=c.execute("SELECT * FROM merchants ORDER BY display_name").fetchall()
            return self.send_json([dict(r, aliases=json.loads(r["aliases"])) for r in rows])
        if path == "/api/merchant-discoveries":
            with connect() as c:
                rows = c.execute("""SELECT * FROM merchant_discoveries
                    WHERE status NOT IN ('approved','rejected') ORDER BY
                    CASE status WHEN 'review' THEN 0 WHEN 'close_match' THEN 1 WHEN 'failed' THEN 2 WHEN 'no_results' THEN 3 ELSE 4 END,
                    transaction_count DESC,lower(raw_alias)""").fetchall()
                counts = {r["status"]: r["n"] for r in c.execute("SELECT status,COUNT(*) n FROM merchant_discoveries GROUP BY status")}
            items = []
            for row in rows:
                item = dict(row)
                item["results"] = json.loads(item["results"])
                item["statement_ids"] = json.loads(item["statement_ids"])
                items.append(item)
            return self.send_json({"items":items,"counts":counts,"search_available":bool(os.environ.get("PARALLEL_API_KEY", "").strip())})
        if path == "/api/statements":
            with connect() as c: rows=c.execute("SELECT id,filename,bank,card_name,period,statement_month,uploaded_at,extraction_status,transaction_count,expected_charges_inr,extracted_charges_inr,reconciliation_difference_inr,reconciliation_status FROM statements ORDER BY uploaded_at DESC").fetchall()
            return self.send_json([dict(r) for r in rows])
        if path == "/api/export":
            with connect() as c:
                tx=[transaction_dict(r) for r in c.execute("SELECT t.*,m.display_name merchant FROM transactions t LEFT JOIN merchants m ON m.id=t.merchant_id ORDER BY date DESC")]
                merchants=[dict(r,aliases=json.loads(r["aliases"])) for r in c.execute("SELECT * FROM merchants")]
            return self.send_json({"transactions":tx,"merchants":merchants,"exported_at":datetime.datetime.now().isoformat(timespec="seconds")})
        if path.startswith("/files/"):
            sid=path.split("/")[-1]
            with connect() as c: row=c.execute("SELECT filename,file_path FROM statements WHERE id=?",(sid,)).fetchone()
            if not row: return self.send_json({"error":"Not found"},404)
            try: b=statement_bytes(row["file_path"])
            except FileNotFoundError: return self.send_json({"error":"File missing"},404)
            self.send_response(200); self.send_header("Content-Type","application/pdf"); self.send_header("Content-Disposition", "inline; filename*=UTF-8''"+__import__('urllib.parse').parse.quote(row["filename"])); self.send_header("Content-Length",str(len(b))); self.send_header("Cache-Control","private, no-store"); self.end_headers(); return self.wfile.write(b)
        if path.startswith("/api/transactions/") and path.endswith("/snapshot"):
            tid = path.split("/")[-2]
            try: return self.send_snapshot(tid)
            except Exception as e: return self.send_json({"error":str(e)},404)
        if path == "/" or path == "/index.html":
            b=(ROOT/"index.html").read_bytes(); self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(b))); self.send_header("Cache-Control","no-cache"); self.end_headers(); return self.wfile.write(b)
        if path in ("/style.css","/app.js"):
            b=(ROOT/path[1:]).read_bytes(); self.send_response(200); self.send_header("Content-Type",mimetypes.guess_type(path)[0]+"; charset=utf-8"); self.send_header("Content-Length",str(len(b))); self.send_header("Cache-Control","no-cache"); self.end_headers(); return self.wfile.write(b)
        self.send_json({"error":"Not found"},404)
    def do_POST(self):
        path=urlparse(self.path).path
        if not self.secure_proxy_request(): return self.send_json({"error":"HTTPS through the trusted proxy is required"},400)
        if path == "/api/auth/login": return self.login()
        if path == "/api/auth/passkey/login/options": return self.passkey_login_options()
        if path == "/api/auth/passkey/login/verify": return self.verify_passkey_login()
        if path == "/api/auth/passkeys/options": return self.passkey_registration_options()
        if path == "/api/auth/passkeys/verify": return self.verify_passkey_registration()
        if path == "/api/auth/logout":
            return self.logout()
        if path == "/api/auth/password": return self.change_password()
        if not self.authorize(mutate=True): return
        if path == "/api/admin/backups":
            if not self.authorize(mutate=True,admin=True): return
            try:
                backup_path=create_encrypted_backup(reason="manual")
                name=backup_path["name"] if isinstance(backup_path,dict) else backup_path.name
                return self.send_json({"ok":True,"name":name})
            except Exception as exc: return self.send_json({"error":str(exc)},409)
        if path == "/api/admin/users": return self.create_user()
        if path.startswith("/api/admin/users/") and path.endswith("/password"):
            return self.reset_user_password(path.split("/")[-2])
        if path == "/api/merchant-discoveries/search":
            if not os.environ.get("PARALLEL_API_KEY", "").strip():
                return self.send_json({"error":"Parallel search needs a PARALLEL_API_KEY in the server environment."},400)
            with connect() as c:
                rows = c.execute("SELECT id FROM merchant_discoveries WHERE status='pending'").fetchall()
                ids = [row["id"] for row in rows]
                c.executemany("UPDATE merchant_discoveries SET status='searching',search_error='' WHERE id=?", [(i,) for i in ids])
            for discovery_id in ids: SEARCH_WORKERS.submit(search_discovery, discovery_id)
            return self.send_json({"ok":True,"queued":len(ids)})
        if path.startswith("/api/merchant-discoveries/") and path.endswith("/search-as-new"):
            if not os.environ.get("PARALLEL_API_KEY", "").strip():
                return self.send_json({"error":"Automatic Parallel lookups need a server-side API key."},400)
            discovery_id=path.split("/")[-2]
            with connect() as c:
                row=c.execute("SELECT status FROM merchant_discoveries WHERE id=?",(discovery_id,)).fetchone()
                if not row: return self.send_json({"error":"Suggestion not found"},404)
                if row["status"]!="close_match": return self.send_json({"error":"Only a close match can be searched as a new merchant"},409)
                c.execute("UPDATE merchant_discoveries SET status='searching',search_error='',results='[]' WHERE id=?",(discovery_id,))
            SEARCH_WORKERS.submit(search_discovery,discovery_id)
            return self.send_json({"ok":True,"queued":1})
        if path.startswith("/api/merchant-discoveries/") and path.endswith("/retry"):
            if not os.environ.get("PARALLEL_API_KEY", "").strip():
                return self.send_json({"error":"Parallel search needs a PARALLEL_API_KEY in the server environment."},400)
            discovery_id = path.split("/")[-2]
            with connect() as c:
                row = c.execute("SELECT status FROM merchant_discoveries WHERE id=?", (discovery_id,)).fetchone()
                if not row: return self.send_json({"error":"Suggestion not found"},404)
                if row["status"] not in ("failed","no_results"): return self.send_json({"error":"Only failed or empty searches can be retried"},409)
                c.execute("UPDATE merchant_discoveries SET status='searching',search_error='',results='[]' WHERE id=?", (discovery_id,))
            SEARCH_WORKERS.submit(search_discovery, discovery_id)
            return self.send_json({"ok":True,"queued":1})
        if path.startswith("/api/merchant-discoveries/") and path.endswith("/approve"):
            try:
                d=json.loads(self.body()); discovery_id=path.split("/")[-2]
                brand=(d.get("brand_name") or "").strip(); legal=(d.get("legal_name") or "").strip()
                with connect() as c:
                    discovery=c.execute("SELECT * FROM merchant_discoveries WHERE id=?",(discovery_id,)).fetchone()
                    if not discovery: return self.send_json({"error":"Suggestion not found"},404)
                    results=json.loads(discovery["results"])
                    merchants=c.execute("SELECT id,display_name,legal_name,aliases FROM merchants").fetchall()
                    if discovery["status"]=="close_match":
                        mid=(d.get("merchant_id") or "").strip()
                        candidate=next((item for item in results if item.get("merchant_id")==mid),None)
                        if not candidate: raise ValueError("Choose one of the possible existing merchants")
                        merchant=next((item for item in merchants if item["id"]==mid),None)
                        if not merchant: raise ValueError("That merchant is no longer in the directory")
                        aliases=list(dict.fromkeys(json.loads(merchant["aliases"])+[discovery["raw_alias"],discovery["query_alias"]]))
                        c.execute("UPDATE merchants SET aliases=? WHERE id=?",(json.dumps(aliases,ensure_ascii=False),mid))
                        c.execute("UPDATE merchant_discoveries SET status='approved',approved_merchant_id=?,decision_at=? WHERE id=?",
                                  (mid,datetime.datetime.now().isoformat(timespec="seconds"),discovery_id))
                    else:
                        if discovery["status"]!="review": raise ValueError("Only a search result waiting for review can be approved")
                        if not brand: raise ValueError("Enter the merchant's familiar brand name before approving")
                        result_index=int(d.get("result_index",0))
                        if result_index<0 or result_index>=len(results): raise ValueError("Choose a valid search result")
                        selected=results[result_index]
                        aliases=list(dict.fromkeys(x for x in [discovery["raw_alias"],discovery["query_alias"],brand,legal] if x))
                        existing=None
                        wanted=merchant_alias_key(brand)
                        for merchant in merchants:
                            if any(merchant_alias_key(name)==wanted for name in _merchant_names(merchant)):
                                existing=merchant; break
                        if existing:
                            mid=existing["id"]
                            merged=list(dict.fromkeys(json.loads(existing["aliases"])+aliases))
                            c.execute("UPDATE merchants SET aliases=?,legal_name=CASE WHEN ?!='' THEN ? ELSE legal_name END,discovery_url=?,discovery_title=? WHERE id=?",
                                      (json.dumps(merged,ensure_ascii=False),legal,legal,selected.get("url",""),selected.get("title",""),mid))
                        else:
                            mid=str(uuid.uuid4()); now=datetime.datetime.now().isoformat(timespec="seconds")
                            c.execute("""INSERT INTO merchants(id,display_name,aliases,category,created_at,legal_name,discovery_url,discovery_title)
                                         VALUES(?,?,?,?,?,?,?,?)""",
                                      (mid,brand,json.dumps(aliases,ensure_ascii=False),"Uncategorised",now,legal,selected.get("url",""),selected.get("title","")))
                        c.execute("UPDATE merchant_discoveries SET status='approved',approved_merchant_id=?,decision_at=? WHERE id=?",
                                  (mid,datetime.datetime.now().isoformat(timespec="seconds"),discovery_id))
                self.rematch_merchant(mid)
                queue_unknown_merchants()
                return self.send_json({"ok":True,"merchant_id":mid})
            except Exception as e: return self.send_json({"error":str(e)},400)
        if path.startswith("/api/merchant-discoveries/") and path.endswith("/reject"):
            discovery_id=path.split("/")[-2]
            with connect() as c:
                row=c.execute("SELECT status FROM merchant_discoveries WHERE id=?",(discovery_id,)).fetchone()
                if not row: return self.send_json({"error":"Suggestion not found"},404)
                if row["status"] not in ("review","close_match","no_results","failed","pending"):
                    return self.send_json({"error":"This suggestion cannot be rejected in its current state"},409)
                c.execute("UPDATE merchant_discoveries SET status='rejected',decision_at=? WHERE id=?",
                          (datetime.datetime.now().isoformat(timespec="seconds"),discovery_id))
            return self.send_json({"ok":True})
        if path == "/api/transactions":
            try: d=json.loads(self.body()); self.save_transaction(d,False); return self.send_json({"ok":True})
            except Exception as e: return self.send_json({"error":str(e)},400)
        if path == "/api/transactions/bulk":
            try:
                d=json.loads(self.body()); items=d.get("items",[])
                if not items or len(items)>500: raise ValueError("Choose between 1 and 500 transactions")
                allowed={"Needs review":0,"Shared":50,"Wife personal":100,"Your personal":0,"Card payment":0,"Custom":None}
                now=datetime.datetime.now().isoformat(timespec="seconds")
                with connect() as c:
                    rows={r["id"]:r for r in c.execute("SELECT id,kind,allocation,share_percent,amount_inr FROM transactions WHERE id IN ({})".format(",".join("?" for _ in items)),[x.get("id") for x in items]).fetchall()}
                    if len(rows)!=len(items): raise ValueError("One or more selected transactions no longer exist")
                    updated_items=[]
                    for item in items:
                        tid=item.get("id"); row=rows[tid]
                        allocation=item.get("allocation")
                        if allocation not in allowed: raise ValueError("Choose a supported allocation")
                        if row["kind"]=="Card payment" and allocation!="Card payment": raise ValueError("Card payment lines cannot be assigned as expenses")
                        if row["kind"]!="Card payment" and allocation=="Card payment": raise ValueError("Only card payment lines can be marked as payments")
                        pct=float(item.get("share_percent",0)) if allocation=="Custom" else allowed[allocation]
                        c.execute("UPDATE transactions SET allocation=?,share_percent=? WHERE id=?",(allocation,pct,tid))
                        c.execute("INSERT INTO audit(transaction_id,action,detail,created_at) VALUES(?,?,?,?)",(tid,"allocation updated",json.dumps({"from":row["allocation"],"to":allocation,"share_percent":pct}),now))
                        updated_items.append({"id":tid,"allocation":allocation,"share_percent":pct,"owed_inr":round(float(row["amount_inr"])*pct/100,2)})
                return self.send_json({"ok":True,"updated":len(items),"items":updated_items})
            except Exception as e: return self.send_json({"error":str(e)},400)
        if path == "/api/merchants":
            try:
                d=json.loads(self.body()); name=d["display_name"].strip()
                if not name: raise ValueError("Merchant name is required")
                aliases=[x.strip() for x in d.get("aliases",[]) if x.strip()]
                mid=str(uuid.uuid4())
                with connect() as c: c.execute("INSERT INTO merchants(id,display_name,aliases,category,created_at,allocation_suggestion,suggestion_person,legal_name) VALUES(?,?,?,?,?,?,?,?)",(mid,name,json.dumps(aliases),d.get("category","Uncategorised"),datetime.datetime.now().isoformat(timespec="seconds"),d.get("allocation_suggestion", ""),d.get("suggestion_person", "Any"),d.get("legal_name","")))
                self.rematch_merchant(mid)
                return self.send_json({"ok":True})
            except Exception as e: return self.send_json({"error":str(e)},400)
        if path == "/api/statements":
            try:
                d=json.loads(self.body()); filename=Path(d["filename"]).name
                if not filename.lower().endswith(".pdf"): raise ValueError("Please upload a PDF statement")
                raw=__import__('base64').b64decode(d["data"]); sid=str(uuid.uuid4())
                if os.environ.get("VERCEL") == "1" and len(raw) > 3 * 1024 * 1024:
                    raise ValueError("For Vercel uploads, choose a statement PDF under 3 MB")
                file_reference, local_pdf = store_statement_pdf(sid, filename, raw, PDF_DIR)
                extraction_pdf = local_pdf or local_statement_path(file_reference)
                bank=d.get("bank","HSBC"); period=d.get("period",""); status="manual"; count=0; pages=0; message=""; summary={}; extracted=None
                month_match=re.findall(r"\b(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\w*\s+(20\d{2})",period.upper())
                month_map={"JAN":1,"FEB":2,"MAR":3,"APR":4,"MAY":5,"JUN":6,"JUL":7,"AUG":8,"SEP":9,"OCT":10,"NOV":11,"DEC":12}
                statement_month=f"{month_match[-1][1]}-{month_map[month_match[-1][0]]:02d}" if month_match else ""
                with connect() as c: c.execute("INSERT INTO statements(id,filename,bank,card_name,period,file_path,uploaded_at,extraction_status,transaction_count,statement_month) VALUES(?,?,?,?,?,?,?,?,?,?)",(sid,filename,bank,d.get("card_name",""),period,file_reference,datetime.datetime.now().isoformat(timespec="seconds"),"processing" if bank.upper()=="HSBC" else "manual",0,statement_month))
                if bank.upper()=="HSBC":
                    try:
                        items,pages,summary=extract_hsbc_pdf(extraction_pdf,period_hint=period)
                        for item in items:
                            item["statement_id"]=sid
                            item["merchant_id"]=self.match_merchant(item.get("description", ""))
                            self.save_transaction(item,False)
                        count=len(items); status="ready" if count else "empty"
                        extracted=round(sum(float(i["amount_inr"]) for i in items if i.get("kind")!="Card payment"),2)
                        if summary.get("statement_month"):
                            statement_month=summary["statement_month"]
                        if not period and summary.get("statement_period"):
                            period=summary["statement_period"]
                        if not count: message="No transactions were recognized; the PDF is retained for manual entry."
                    except Exception as e:
                        with connect() as c: c.execute("DELETE FROM transactions WHERE statement_id=?",(sid,))
                        status="error"; message=str(e)
                expected=summary.get("expected_charges_inr")
                difference=round(extracted-expected,2) if extracted is not None and expected is not None else None
                recon="matched" if difference is not None and abs(difference)<=1 else ("needs attention" if difference is not None else "unavailable")
                with connect() as c: c.execute("UPDATE statements SET period=?,statement_month=?,extraction_status=?,transaction_count=?,expected_charges_inr=?,extracted_charges_inr=?,reconciliation_difference_inr=?,reconciliation_status=? WHERE id=?",(period,statement_month,status,count,expected,extracted,difference,recon,sid))
                if count:
                    try: SEARCH_WORKERS.submit(process_statement_discoveries,sid)
                    except RuntimeError: pass
                return self.send_json({"ok":True,"id":sid,"extraction_status":status,"transaction_count":count,"pages":pages,"message":message,"reconciliation_status":recon,"reconciliation_difference_inr":difference})
            except Exception as e: return self.send_json({"error":str(e)},400)
        self.send_json({"error":"Not found"},404)
    def do_PUT(self):
        path=urlparse(self.path).path
        if not self.secure_proxy_request(): return self.send_json({"error":"HTTPS through the trusted proxy is required"},400)
        if path.startswith("/api/auth/passkeys/"):
            passkey_id=path.rsplit("/",1)[-1]
            return self.rename_passkey(passkey_id)
        if not self.authorize(mutate=True): return
        if path.startswith("/api/admin/users/"):
            return self.update_user(path.rsplit("/",1)[-1])
        if path.startswith("/api/merchants/"):
            try:
                d=json.loads(self.body()); mid=path.rsplit("/",1)[-1]; name=d["display_name"].strip()
                if not name: raise ValueError("Merchant name is required")
                aliases=[x.strip() for x in d.get("aliases",[]) if x.strip()]
                with connect() as c: c.execute("UPDATE merchants SET display_name=?,aliases=?,category=?,allocation_suggestion=?,suggestion_person=?,legal_name=? WHERE id=?",(name,json.dumps(aliases),d.get("category","Uncategorised"),d.get("allocation_suggestion", ""),d.get("suggestion_person", "Any"),d.get("legal_name",""),mid))
                self.rematch_merchant(mid)
                return self.send_json({"ok":True})
            except Exception as e: return self.send_json({"error":str(e)},400)
        if path.startswith("/api/transactions/"):
            try: d=json.loads(self.body()); d["id"]=path.rsplit("/",1)[-1]; self.save_transaction(d,True); return self.send_json({"ok":True})
            except Exception as e: return self.send_json({"error":str(e)},400)
        self.send_json({"error":"Not found"},404)
    def save_transaction(self,d,update):
        date=d.get("date"); amount=float(d.get("amount_inr",0)); kind=d.get("kind","Purchase")
        if not date or not d.get("description","").strip(): raise ValueError("Date and description are required")
        if kind=="Refund" and amount>0: amount=-amount
        if kind!="Refund" and amount<0: amount=abs(amount)
        allocation=d.get("allocation","Needs review"); presets={"Needs review":0,"Shared":50,"Wife personal":100,"Your personal":0,"Custom":float(d.get("share_percent",0)),"Card payment":0}
        pct=float(d.get("share_percent",presets.get(allocation,0)))
        if allocation in presets and allocation!="Custom": pct=presets[allocation]
        merchant_id=d.get("merchant_id") or None
        with connect() as c:
            old_statement_id = None
            old_source = (None, None, None, None)
            if update:
                previous = c.execute("SELECT statement_id,source_page,source_bbox,ocr_confidence,ocr_amount_confidence,ocr_amount_match FROM transactions WHERE id=?", (d["id"],)).fetchone()
                if not previous: raise ValueError("Transaction not found")
                old_statement_id = previous["statement_id"]
                old_source = (previous["source_page"], previous["source_bbox"], previous["ocr_confidence"], previous["ocr_amount_confidence"], previous["ocr_amount_match"])
            source_page = d.get("source_page") or old_source[0]
            source_bbox = d.get("source_bbox") or old_source[1]
            if isinstance(source_bbox, (list, tuple)): source_bbox = json.dumps(source_bbox)
            ocr_confidence = d.get("ocr_confidence") or old_source[2]
            ocr_amount_confidence = d.get("ocr_amount_confidence")
            if ocr_amount_confidence is None: ocr_amount_confidence = old_source[3]
            ocr_amount_match = d.get("ocr_amount_match", old_source[4])
            if update and old_source[4] is not None: ocr_amount_match = 1
            vals=(date,d["description"].strip(),merchant_id,amount,float(d["original_amount"]) if d.get("original_amount") not in (None,"") else None,d.get("currency","INR"),d.get("person","Unknown"),kind,allocation,pct,d.get("payment_method","Credit card"),d.get("category","Uncategorised"),d.get("statement_id") or None,d.get("notes","").strip())
            if update:
                c.execute("UPDATE transactions SET date=?,description=?,merchant_id=?,amount_inr=?,original_amount=?,currency=?,person=?,kind=?,allocation=?,share_percent=?,payment_method=?,category=?,statement_id=?,notes=?,source_page=?,source_bbox=?,ocr_confidence=?,ocr_amount_confidence=?,ocr_amount_match=? WHERE id=?",vals+(source_page,source_bbox,ocr_confidence,ocr_amount_confidence,ocr_amount_match,d["id"]))
                action="updated"; tid=d["id"]
            else:
                tid=str(uuid.uuid4()); c.execute("INSERT INTO transactions(id,date,description,merchant_id,amount_inr,original_amount,currency,person,kind,allocation,share_percent,payment_method,category,statement_id,notes,created_at,source_page,source_bbox,ocr_confidence,ocr_amount_confidence,ocr_amount_match) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(tid,*vals,datetime.datetime.now().isoformat(timespec="seconds"),source_page,source_bbox,ocr_confidence,ocr_amount_confidence,d.get("ocr_amount_match"))); action="created"
            c.execute("INSERT INTO audit(transaction_id,action,detail,created_at) VALUES(?,?,?,?)",(tid,action,json.dumps({"allocation":allocation,"amount_inr":amount,"share_percent":pct}),datetime.datetime.now().isoformat(timespec="seconds")))
            for statement_id in {old_statement_id, d.get("statement_id") or None} - {None}:
                recalculate_statement(c, statement_id)
    def match_merchant(self,description):
        raw=re.sub(r"[^A-Z0-9]", "", (description or "").upper())
        with connect() as c: rows=c.execute("SELECT id,display_name,legal_name,aliases FROM merchants").fetchall()
        core_key=merchant_alias_key(merchant_alias_core(description))
        for row in rows:
            if core_key and any(merchant_alias_key(name)==core_key for name in _merchant_names(row)): return row["id"]
        # `contains` matching is reserved for statement aliases already approved into the master.
        for row in rows:
            try: aliases=json.loads(row["aliases"] or "[]")
            except (TypeError,ValueError): aliases=[]
            if any(len(merchant_alias_key(alias))>=4 and merchant_alias_key(alias) in raw for alias in aliases): return row["id"]
        return None
    def rematch_merchant(self,merchant_id):
        with connect() as c:
            merchant=c.execute("SELECT display_name,legal_name,aliases FROM merchants WHERE id=?",(merchant_id,)).fetchone()
            if not merchant:return
            aliases=_merchant_names(merchant)
            try: statement_aliases=json.loads(merchant["aliases"] or "[]")
            except (TypeError,ValueError): statement_aliases=[]
            exact_keys={merchant_alias_key(name) for name in aliases if name}
            rows=c.execute("SELECT id,description,merchant_id FROM transactions WHERE merchant_id IS NULL OR merchant_id=?",(merchant_id,)).fetchall()
            for row in rows:
                raw=re.sub(r"[^A-Z0-9]", "", (row["description"] or "").upper())
                core_key=merchant_alias_key(merchant_alias_core(row["description"]))
                matched=core_key in exact_keys or any(len(merchant_alias_key(a))>=4 and merchant_alias_key(a) in raw for a in statement_aliases)
                if matched and row["merchant_id"] is None:c.execute("UPDATE transactions SET merchant_id=? WHERE id=?",(merchant_id,row["id"]))
                elif not matched and row["merchant_id"]==merchant_id:c.execute("UPDATE transactions SET merchant_id=NULL WHERE id=?",(row["id"],))
    def do_DELETE(self):
        path=urlparse(self.path).path
        if not self.secure_proxy_request(): return self.send_json({"error":"HTTPS through the trusted proxy is required"},400)
        if path.startswith("/api/auth/passkeys/"):
            passkey_id=path.rsplit("/",1)[-1]
            return self.remove_passkey(passkey_id)
        if not self.authorize(mutate=True): return
        if path.startswith("/api/transactions/"):
            tid=path.rsplit("/",1)[-1]
            with connect() as c:
                row=c.execute("SELECT statement_id FROM transactions WHERE id=?",(tid,)).fetchone()
                c.execute("DELETE FROM transactions WHERE id=?",(tid,))
                if row and row["statement_id"]: recalculate_statement(c,row["statement_id"])
            return self.send_json({"ok":True})
        self.send_json({"error":"Not found"},404)

if __name__ == "__main__":
    if os.environ.get("VERCEL") == "1":
        if not hosted_database_enabled():
            raise RuntimeError("Vercel deployment requires a persistent PostgreSQL connection")
        require_hosted_storage()
        if not AUTH_REQUIRED or not SECURE_COOKIES or os.environ.get("LEDGER_TRUST_PROXY", "0") != "1":
            raise RuntimeError("Vercel deployment requires hosted sign-in, secure cookies, and trusted proxy mode")
    init_db()
    with connect() as c: c.execute("UPDATE merchant_discoveries SET status='pending' WHERE status='searching'")
    # Hosted data is durable and already has its discovery rows; rescanning all
    # unmatched transactions here adds hundreds of remote DB round trips on every
    # container cold start. New statements still queue suggestions after upload.
    if os.environ.get("VERCEL") != "1":
        queue_unknown_merchants()
    host=os.environ.get("LEDGER_HOST","127.0.0.1"); port=int(os.environ.get("PORT","8000"))
    try: loopback=ipaddress.ip_address(host).is_loopback
    except ValueError: loopback=host.lower()=="localhost"
    if not loopback and (not AUTH_REQUIRED or not SECURE_COOKIES or os.environ.get("LEDGER_TRUST_PROXY","0")!="1"):
        raise RuntimeError("Refusing a public bind. Require LEDGER_AUTH_REQUIRED=1, LEDGER_SECURE_COOKIES=1, and a trusted TLS proxy (LEDGER_TRUST_PROXY=1).")
    if os.environ.get("VERCEL") != "1":
        threading.Thread(target=scheduled_backup_loop,name="ledger-backups",daemon=True).start()
    print(f"Household Ledger running at http://{host}:{port}")
    ThreadingHTTPServer((host,port),Handler).serve_forever()
