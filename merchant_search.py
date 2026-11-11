"""Server-side merchant alias lookup using the Parallel Search API."""
from __future__ import annotations

import json
import re
from urllib.request import Request, urlopen

LOCATION_WORDS = {
    "IND", "INDIA", "MAH", "MAHARASHTRA", "DEL", "DELHI", "KAR", "KARNATAKA",
    "TN", "TAMIL", "NADU", "UP", "UTT", "HARYANA", "MUMBAI", "BOMBAY",
    "GURGAON", "GURUGRAM", "NOIDA", "BANGALORE", "BENGALURU", "PUNE", "CHENNAI",
    "HYDERABAD", "KOLKATA", "JAIPUR", "AHMEDABAD", "THANE", "NLD", "SWE", "NOR",
    "DNK", "DEU", "USA", "GBR", "AUS", "SGP", "ARE", "NLD", "STOCKHOLM", "OSLO",
    "COPENHAGEN", "BERLIN", "LONDON", "SINGAPORE", "DUBAI",
}
GENERIC_WORDS = {"PAYMENT", "CARD", "PURCHASE", "TRANSACTION", "POS", "ECOM", "ECOMM"}
LEGAL_SUFFIX = re.compile(
    r"\b([A-Z][A-Z0-9&.'(),/-]*(?:\s+[A-Z][A-Z0-9&.'(),/-]*){0,7}\s+"
    r"(?:PRIVATE\s+LIMITED|PVT\.?\s+LTD\.?|LIMITED|LTD\.?|LLP|INC\.?|CORPORATION|CORP\.?))\b",
    re.I,
)


def merchant_alias_core(description: str) -> str:
    """Keep likely merchant words while dropping amounts and trailing locations."""
    text = re.sub(r"\b\d{2,}\b", " ", (description or "").upper())
    words = re.findall(r"[A-Z][A-Z0-9&.'/-]*", text)
    kept = []
    for word in words:
        token = re.sub(r"[^A-Z0-9]", "", word)
        if token in LOCATION_WORDS and kept:
            break
        if token in GENERIC_WORDS:
            continue
        kept.append(word.strip(".'-/"))
        if len(kept) == 4:
            break
    core = " ".join(w for w in kept if w)
    return core if len(re.sub(r"[^A-Z0-9]", "", core)) >= 4 else ""


def merchant_alias_key(alias: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (alias or "").upper())


def _brand_name(title: str) -> str:
    title = re.split(r"\s+[|–—-]\s+|\s*:\s*", title or "", maxsplit=1)[0]
    title = re.sub(r"\b(official site|official website|home page|homepage)\b", "", title, flags=re.I)
    return re.sub(r"\s+", " ", title).strip(" -|:")[:120]


def _legal_name(text: str) -> str:
    match = LEGAL_SUFFIX.search(text or "")
    return re.sub(r"\s+", " ", match.group(1)).strip(" ,.;") if match else ""


def _normalize_result(result: dict) -> dict:
    title = (result.get("title") or "").strip()
    description = (result.get("description") or "").strip()
    url = (result.get("url") or "").strip()
    if not url.startswith("https://"):
        url = ""
    return {
        "title": title[:240],
        "url": url[:1200],
        "description": description[:1200],
        "suggested_brand_name": _brand_name(title),
        "suggested_legal_name": _legal_name(title + " " + description),
    }


def search_parallel(alias: str, api_key: str) -> dict:
    """Return ranked Parallel results; the caller decides whether to approve."""
    clean_alias = re.sub(r"\s+", " ", alias or "").strip()[:100]
    query = "{} merchant brand legal company name".format(clean_alias)
    payload = {
        "objective": (
            "Identify the merchant brand and, when reliable sources show it, the legal business name "
            "represented by this statement descriptor. The merchant may be based in any country. "
            "Return sources that support the identification. Descriptor: {}"
        ).format(clean_alias),
        "search_queries": [
            "{} merchant brand".format(clean_alias[:70]),
            "{} company legal name".format(clean_alias[:70]),
        ],
        "mode": "fast",
        "advanced_settings": {"max_results": 5},
        "max_chars_total": 6000,
    }
    request = Request(
        "https://api.parallel.ai/v1/search",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "User-Agent": "HouseholdLedger/1.0 merchant-alias-review",
        },
        method="POST",
    )
    with urlopen(request, timeout=15) as response:
        result_payload = json.loads(response.read().decode("utf-8"))
    results = [_normalize_result({
        "title": item.get("title"),
        "url": item.get("url"),
        "description": "\n".join(item.get("excerpts") or []),
    }) for item in result_payload.get("results", [])]
    return {"query": query, "results": results}
