"""Private Supabase Storage for hosted statement PDFs; local disk for development."""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


def _config():
    url = (os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or "").strip().rstrip("/")
    # Supabase's newer secret API keys belong in the apikey header; the
    # Authorization bearer header must remain a JWT. Prefer the legacy
    # server-only service-role JWT when both are provisioned by the integration.
    key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SECRET_KEY") or "").strip()
    bucket = os.environ.get("LEDGER_STORAGE_BUCKET", "ledger-statements").strip()
    return url, key, bucket


def hosted_storage_enabled() -> bool:
    url, key, bucket = _config()
    return bool(url and key and bucket)


def require_hosted_storage():
    url, key, bucket = _config()
    if not (url and key and bucket):
        raise RuntimeError("Set SUPABASE_URL, SUPABASE_SECRET_KEY, and LEDGER_STORAGE_BUCKET for hosted statement storage")


def _request(method: str, endpoint: str, data: bytes | None = None, content_type: str | None = None) -> bytes:
    url, key, _ = _config()
    headers = {"apikey": key, "Authorization": "Bearer " + key}
    if content_type:
        headers["Content-Type"] = content_type
    request = Request(url + endpoint, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=90) as response:
            return response.read()
    except HTTPError as exc:
        raise RuntimeError("Supabase Storage request failed (HTTP {})".format(exc.code)) from None
    except (URLError, TimeoutError) as exc:
        raise RuntimeError("Could not reach Supabase Storage: {}".format(type(exc).__name__)) from None


def _object_path(path: str) -> str:
    _, _, bucket = _config()
    return "/storage/v1/object/{}/{}".format(quote(bucket, safe=""), quote(path, safe="/"))


def upload_object(path: str, data: bytes, content_type="application/octet-stream", upsert=False):
    endpoint = _object_path(path)
    url, key, _ = _config()
    request = Request(url + endpoint, data=data, headers={
        "apikey": key,
        "Authorization": "Bearer " + key,
        "Content-Type": content_type,
        "x-upsert": "true" if upsert else "false",
    }, method="POST")
    try:
        with urlopen(request, timeout=90) as response:
            response.read()
    except HTTPError as exc:
        raise RuntimeError("Supabase Storage upload failed (HTTP {})".format(exc.code)) from None
    except (URLError, TimeoutError) as exc:
        raise RuntimeError("Could not reach Supabase Storage: {}".format(type(exc).__name__)) from None
    return "supabase://" + path


def download_object(path: str) -> bytes:
    url, key, bucket = _config()
    endpoint = "/storage/v1/object/authenticated/{}/{}".format(
        quote(bucket, safe=""), quote(path, safe="/"))
    request = Request(url + endpoint, headers={"apikey": key, "Authorization": "Bearer " + key})
    try:
        with urlopen(request, timeout=90) as response:
            return response.read()
    except HTTPError as exc:
        raise FileNotFoundError("Statement object is unavailable in private storage (HTTP {})".format(exc.code)) from None
    except (URLError, TimeoutError) as exc:
        raise RuntimeError("Could not reach Supabase Storage: {}".format(type(exc).__name__)) from None


def delete_object(path: str):
    url, key, bucket = _config()
    endpoint = "/storage/v1/object/{}".format(quote(bucket, safe=""))
    request = Request(url + endpoint, data=__import__("json").dumps({"prefixes": [path]}).encode("utf-8"),
                      headers={"apikey": key, "Authorization": "Bearer " + key,
                               "Content-Type": "application/json"}, method="DELETE")
    try:
        with urlopen(request, timeout=30) as response:
            response.read()
    except HTTPError as exc:
        raise RuntimeError("Supabase Storage delete failed (HTTP {})".format(exc.code)) from None
    except (URLError, TimeoutError) as exc:
        raise RuntimeError("Could not reach Supabase Storage: {}".format(type(exc).__name__)) from None


def store_statement_pdf(statement_id: str, filename: str, raw: bytes, pdf_dir: Path) -> tuple[str, Path | None]:
    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", Path(filename).name)
    if hosted_storage_enabled():
        reference = upload_object("statements/{}_{}".format(statement_id, safe), raw, "application/pdf")
        return reference, None
    destination = pdf_dir / (statement_id + "_" + safe)
    destination.write_bytes(raw)
    return str(destination), destination


def statement_bytes(reference: str) -> bytes:
    if reference.startswith("supabase://"):
        return download_object(reference[len("supabase://"):])
    return Path(reference).read_bytes()


def local_statement_path(reference: str) -> Path:
    if not reference.startswith("supabase://"):
        return Path(reference)
    cache_dir = Path(tempfile.gettempdir()) / "household-ledger-runtime" / "statements"
    cache_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(reference.encode("utf-8")).hexdigest()
    cached = cache_dir / (digest + ".pdf")
    if not cached.is_file():
        cached.write_bytes(statement_bytes(reference))
    return cached
