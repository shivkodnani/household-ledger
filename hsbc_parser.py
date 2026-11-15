"""Local HSBC India credit-card PDF OCR and transaction extraction."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
NODE_MODULES_MARKERS = ("tesseract.js",)
MONTHS = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
          "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
MONTH_PATTERN = "|".join(MONTHS)
DATE_PREFIX = re.compile(r"^\s*[`'’‘|]*([0-9A-Z|{}@]{1,2})\s*(" + MONTH_PATTERN + r")\b", re.I)
AMOUNT_PATTERN = re.compile(r"(?<![A-Z0-9])(?:\d{1,3}(?:,\d{3})+|\d+)[.,]\d{2}(?!\d)", re.I)
YEAR_PATTERN = re.compile(r"\b20\d{2}\b")
FOREX_PATTERN = re.compile(r"\b(SEK|NOK|DKK|USD|EUR|GBP|CHF|AUD|CAD|JPY|CNY|HKD|THB|SGD|AED)\b", re.I)


def _runtime_paths():
    home = Path.home()
    roots = sorted((home / ".cache" / "codex-runtimes").glob("*/dependencies"))
    node = os.environ.get("LEDGER_NODE") or shutil.which("node")
    local_modules = ROOT / "node_modules"
    modules = os.environ.get("LEDGER_NODE_MODULES") or (str(local_modules) if (local_modules / "tesseract.js").exists() else None)
    pdftoppm = os.environ.get("LEDGER_PDFTOPPM") or shutil.which("pdftoppm")
    for root in roots:
        candidate = root / "node" / "bin" / "node"
        if not node and candidate.exists(): node = str(candidate)
        candidate_modules = root / "node" / "node_modules"
        if not modules and (candidate_modules / "tesseract.js").exists(): modules = str(candidate_modules)
        candidate_pdf = root / "bin" / "override" / "pdftoppm"
        if not pdftoppm and candidate_pdf.exists(): pdftoppm = str(candidate_pdf)
    if not node or not modules or not (Path(modules) / "tesseract.js").exists():
        raise RuntimeError("The local OCR runtime is unavailable. Start this app from the Codex local runtime or set LEDGER_NODE and LEDGER_NODE_MODULES.")
    if not pdftoppm:
        raise RuntimeError("PDF rendering is unavailable. Install Poppler (pdftoppm) locally or set LEDGER_PDFTOPPM.")
    return node, modules, pdftoppm


def _month_and_day(raw, period_bounds=None):
    # OCR commonly turns the O in OCT into a zero and a leading 1 into a brace.
    raw = re.sub(r"0CT", "OCT", raw or "", flags=re.I)
    raw = re.sub(r"MAAY\b", "MAY", raw, flags=re.I)
    match = DATE_PREFIX.match(raw)
    if not match: return None
    day_raw, month_raw = match.group(1).upper().replace("|", "1"), match.group(2).upper()
    month = MONTHS[month_raw]
    if len(day_raw) == 2:
        if day_raw == "OO" and period_bounds:
            start, end = period_bounds
            try:
                if start <= date(end.year - 1 if month > end.month else end.year, month, 9) <= end:
                    day_raw = "09"
            except ValueError:
                pass
        elif day_raw[0] in ("0", "O", "Q", "D") and day_raw[1] in ("A", "O", "B", "@"):
            day_raw = day_raw[0] + "8"
        elif day_raw[0] in ("0", "O", "Q", "D") and day_raw[1] == "@":
            day_raw = day_raw[0] + "8"
        elif day_raw[0] in ("0", "O", "Q", "D") and day_raw[1] == "S" and period_bounds:
            start, end = period_bounds
            try:
                in_period = lambda day: start <= date(end.year - 1 if month > end.month else end.year, month, day) <= end
                if in_period(8) and not in_period(5): day_raw = day_raw[0] + "8"
            except ValueError:
                pass
        elif day_raw == "A0" or day_raw == "AO":
            day_raw = "10"
        elif day_raw == "TE":
            day_raw = "16"
        elif day_raw == "2A":
            day_raw = "23"
        elif day_raw == "S1":
            day_raw = "31"
    # HSBC's narrow date column frequently renders 08 as OS, OA, or OO.
    replacements = {"O": "0", "Q": "0", "D": "0", "{": "1", "S": "5", "G": "9",
                    "I": "1", "L": "1", "T": "1", "Z": "2", "B": "8", "@": "8"}
    digits = "".join(replacements.get(ch, ch) for ch in day_raw)
    try: day = int(digits)
    except ValueError: return None
    if day > 31 and digits[:1] == "4":
        try: day = int("1" + digits[1:])
        except ValueError: return None
    if not 1 <= day <= 31: return None
    return day, month, match.end()


def _hsbc_date_from_crop(page, line, period_bounds=None):
    height = max(1, int(page.get("height", 1)))
    line_center = (float(line.get("y0", 0)) + float(line.get("y1", line.get("y0", 0)))) / 2
    max_distance = max(18, height * 0.012)
    candidates = []
    for word in page.get("date_words", []):
        parsed = _month_and_day(word.get("text", ""), period_bounds)
        if not parsed: continue
        center = (float(word.get("y0", 0)) + float(word.get("y1", word.get("y0", 0)))) / 2
        distance = abs(center - line_center)
        if distance <= max_distance:
            candidates.append((distance, parsed))
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def _detail_without_ocr_date(raw, parsed_from_full_line):
    normalized = re.sub(r"MAAY\b", "MAY", raw, flags=re.I)
    match = DATE_PREFIX.match(normalized)
    if match:
        first, separator, rest = raw.partition(" ")
        return rest.strip(" \t|_-'’‘") if separator else raw[match.end():].strip(" \t|_-'’‘")
    if parsed_from_full_line:
        return raw[parsed_from_full_line[2]:].strip(" \t|_-'’‘")
    first, separator, rest = raw.partition(" ")
    first = re.sub(r"MAAY\b", "MAY", first, flags=re.I)
    if separator and len(first) <= 9 and re.search(r"(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)", first, re.I):
        return rest.strip(" \t|_-'’‘")
    return raw.strip(" \t|_-'’‘")


def _statement_year(ocr, period_hint=""):
    text = (period_hint or "") + " " + " ".join(p.get("text", "") for p in ocr.get("pages", [])[:2])
    years = [int(x) for x in YEAR_PATTERN.findall(text)]
    return years[-1] if years else date.today().year


def _statement_end_month(ocr, period_hint=""):
    # Statement periods normally print the end date last (for example,
    # "08 SEP 2026 TO 08 OCT 2026"). Prefer a user-entered period when present.
    text = (period_hint or "") + " " + " ".join(p.get("text", "") for p in ocr.get("pages", [])[:2])
    month_year = re.findall(r"\b(" + MONTH_PATTERN + r")\s+20\d{2}\b", text, re.I)
    if month_year:
        return MONTHS[month_year[-1].upper()]
    return date.today().month


def _statement_period_bounds(ocr, period_hint=""):
    text = (period_hint or "") + " " + " ".join(p.get("text", "") for p in ocr.get("pages", [])[:2])
    period = re.search(
        r"\b(\d{1,2})\s+(" + MONTH_PATTERN + r")\s+(20\d{2})\s*(?:TO|T0|[-–])\s*"
        r"(\d{1,2})\s+(" + MONTH_PATTERN + r")\s+(20\d{2})\b",
        text,
        re.I,
    )
    if not period:
        return None
    try:
        start = date(int(period.group(3)), MONTHS[period.group(2).upper()], int(period.group(1)))
        end = date(int(period.group(6)), MONTHS[period.group(5).upper()], int(period.group(4)))
        return (start, end) if start <= end else None
    except (KeyError, ValueError):
        return None


def _transaction_date(day, month, end_year, end_month):
    year = end_year - 1 if month > end_month else end_year
    try: return date(year, month, day).isoformat()
    except ValueError: return None


def _money(raw):
    raw = raw.replace(" ", "")
    if "." not in raw and raw.count(",") == 1 and len(raw.rsplit(",", 1)[1]) == 2:
        raw = raw.replace(",", ".")
    clean = raw.replace(",", "")
    try: return round(float(clean), 2)
    except ValueError: return None


def _hsbc_amount_column_center(page):
    """Locate HSBC's rightmost INR Amount column from its printed header."""
    width = max(1, int(page.get("width", 1)))
    height = max(1, int(page.get("height", 1)))
    candidates = []
    for line in page.get("lines", []):
        line_text = (line.get("text", "") or "").upper()
        for word in line.get("words", []):
            label = re.sub(r"[^A-Z]", "", (word.get("text", "") or "").upper())
            if label != "AMOUNT": continue
            y = (float(word.get("y0", line.get("y0", 0))) + float(word.get("y1", line.get("y1", 0)))) / (2 * height)
            if 0.20 <= y <= 0.80:
                priority = 0 if "TRANSACTION" in line_text or "DETAIL" in line_text else 1
                candidates.append((priority, y, (float(word.get("x0", 0)) + float(word.get("x1", 0))) / 2))
    if candidates:
        _, _, center = min(candidates)
        return center
    # The known HSBC India layout places the Amount (₹) column at about 65% of page width.
    return width * 0.65


def _hsbc_amount_word(line, column_center, page_width):
    """Select the numeric OCR token aligned with HSBC's Amount (₹) header."""
    candidates = []
    for word in line.get("words", []):
        text = word.get("text", "") or ""
        match = AMOUNT_PATTERN.search(text)
        if not match: continue
        center = (float(word.get("x0", 0)) + float(word.get("x1", 0))) / 2
        distance = abs(center - column_center)
        if distance <= page_width * 0.12:
            candidates.append((distance, word, match.group(0)))
    if not candidates: return None, None
    _, word, token = min(candidates, key=lambda item: item[0])
    return token, float(word.get("confidence", 0))


def _hsbc_amount_from_crop(page, line):
    """Read the INR token from a focused OCR pass over HSBC's Amount column."""
    height = max(1, int(page.get("height", 1)))
    line_center = (float(line.get("y0", 0)) + float(line.get("y1", line.get("y0", 0)))) / 2
    max_distance = max(18, height * 0.012)
    candidates = []
    for word in page.get("amount_words", []):
        match = AMOUNT_PATTERN.search(word.get("text", "") or "")
        if not match: continue
        center = (float(word.get("y0", 0)) + float(word.get("y1", word.get("y0", 0)))) / 2
        distance = abs(center - line_center)
        if distance <= max_distance:
            candidates.append((distance, word, match.group(0)))
    if not candidates: return None, None, None
    _, word, token = min(candidates, key=lambda item: item[0])
    center = (float(word.get("y0", 0)) + float(word.get("y1", word.get("y0", 0)))) / 2
    return token, float(word.get("confidence", 0)), round(center, 1)


def parse_hsbc_ocr(ocr, period_hint=""):
    """Convert line-level OCR into reviewable statement transactions."""
    pages = ocr.get("pages", [])
    year = _statement_year(ocr, period_hint)
    end_month = _statement_end_month(ocr, period_hint)
    period_bounds = _statement_period_bounds(ocr, period_hint)
    # OCR may distort the masked digits and card separators. Detect card
    # headings by their visible last four digits and trailing cardholder name.
    card_pattern = re.compile(r"\b(\d{4})\s+([A-Z][A-Z .'-]{2,})\s*$", re.I)
    primary_last4 = None
    found = []
    for page in pages:
        person = "Me"  # Each statement page begins in the primary-card section.
        height = max(1, int(page.get("height", 1)))
        width = max(1, int(page.get("width", 1)))
        amount_column_center = _hsbc_amount_column_center(page)
        page_num = int(page.get("page", 0))
        used_amount_rows = set()
        for line in page.get("lines", []):
            raw = re.sub(r"\s+", " ", line.get("text", "")).strip()
            if not raw: continue
            header = card_pattern.search(raw.upper()) if re.search(r"X{2,}", raw.upper()) else None
            if header:
                last4 = header.group(1)
                if primary_last4 is None: primary_last4 = last4
                person = "Me" if last4 == primary_last4 else "Wife"
                continue
            y = float(line.get("y0", 0)) / height
            if y < 0.25 or y > 0.80: continue
            if any(marker in raw.upper() for marker in (
                "OPENING BALANCE", "AVAILABLE CREDIT LIMIT", "PURCHASES & INSTALLMENTS",
                "TOTAL PURCHASE", "TOTAL CASH", "TOTAL BALANCE TRANSFER", "TOTAL LOAN",
                "ACCOUNT SUMMARY", "INTEREST RATE",
            )):
                continue
            parsed_from_full_line = _month_and_day(raw, period_bounds)
            parsed_date = _hsbc_date_from_crop(page, line, period_bounds) or parsed_from_full_line
            if not parsed_date: continue
            day, month, date_end = parsed_date
            txn_date = _transaction_date(day, month, year, end_month)
            if not txn_date: continue
            detail = _detail_without_ocr_date(raw, parsed_from_full_line)
            if any(marker in detail.upper() for marker in ("OUTSTANDING BALANCE", "TOTAL PURCHASE", "TOTAL CASH", "BALANCE TRANSFER OUTSTANDING", "LOAN OUTSTANDING", "STATEMENT SUMMARY")):
                continue
            amounts = AMOUNT_PATTERN.findall(detail)
            column_token, column_confidence, amount_row_key = _hsbc_amount_from_crop(page, line)
            full_token, full_confidence = _hsbc_amount_word(line, amount_column_center, width)
            if column_token is not None:
                amount_token, amount_confidence = column_token, column_confidence
                if full_token is not None:
                    same_amount = re.sub(r"\D", "", column_token) == re.sub(r"\D", "", full_token)
                    confidence_values = [value for value in (column_confidence, full_confidence) if value is not None]
                    # Agreement between the full row and focused Amount-column OCR
                    # is stronger evidence than either Tesseract word score alone.
                    amount_confidence = 100.0 if same_amount else min(confidence_values)
            else:
                amount_token, amount_confidence = full_token, full_confidence
                amount_row_key = None
            if not amounts and amount_token is None: continue
            if amount_row_key is not None and amount_row_key in used_amount_rows: continue
            if amount_token is not None:
                amount = _money(amount_token)
            else:
                # Preserve legacy extraction where a scan misses the header/token, but make it a clear review case.
                amount = _money(amounts[-1])
                amount_confidence = 0.0
            if amount is None or amount <= 0: continue
            currency_match = FOREX_PATTERN.search(detail)
            currency = currency_match.group(1).upper() if currency_match else "INR"
            original_tokens = list(amounts)
            if amount_token is not None:
                amount_key = re.sub(r"\D", "", amount_token)
                removed = False
                for index in range(len(original_tokens) - 1, -1, -1):
                    if re.sub(r"\D", "", original_tokens[index]) == amount_key:
                        original_tokens.pop(index)
                        removed = True
                        break
                if not removed and original_tokens and (len(original_tokens) > 1 or not currency_match):
                    original_tokens.pop()
            else:
                original_tokens.pop()
            original = _money(original_tokens[-1]) if currency_match and original_tokens else None
            upper = detail.upper()
            is_payment = any(s in upper for s in ("BBPS PMT", "PAYMENT RECEIVED", "PAYMENT THANK", "CARD PAYMENT"))
            is_refund = not is_payment and any(s in upper for s in ("REFUND", "REVERSAL", "CHARGEBACK"))
            has_credit_marker = bool(re.search(r"\d[\d,]*[.,]\d{2}\s*CR\b\s*$", upper))
            if not is_payment and not is_refund and has_credit_marker:
                is_refund = True
            kind = "Card payment" if is_payment else ("Refund" if is_refund else "Purchase")
            if is_refund: amount = -amount
            # Drop only the trailing numeric columns. Preserve merchant/city/currency as the raw descriptor.
            description = detail
            for token in reversed(amounts):
                pos = description.rfind(token)
                if pos >= 0: description = description[:pos] + description[pos + len(token):]
            description = re.sub(r"\b" + currency + r"\b", "", description, flags=re.I)
            description = re.sub(r"\bCR\b", "", description, flags=re.I)
            description = re.sub(r"\s+", " ", description).strip(" |_-'")
            if len(description) < 2: description = detail
            confidence = float(amount_confidence or 0)
            amount_confidence_text = "{:.1f}%".format(amount_confidence) if amount_confidence is not None else "unavailable"
            found.append({
                "date": txn_date,
                "description": description,
                "amount_inr": amount,
                "original_amount": original,
                "currency": currency,
                "person": person,
                "kind": kind,
                "allocation": "Needs review",
                "share_percent": 0,
                "payment_method": "Credit card",
                "category": "Uncategorised",
                "statement_id": None,
                "notes": "Imported from page {} · INR Amount column OCR confidence {}".format(page_num, amount_confidence_text),
                "source_page": page_num,
                "source_bbox": [int(line.get("x0", 0)), int(line.get("y0", 0)),
                                int(line.get("x1", page.get("width", 0))), int(line.get("y1", 0))],
                "ocr_confidence": confidence,
                "ocr_amount_confidence": amount_confidence,
                "ocr_amount_match": 1 if amount_token is not None else 0,
            })
            if amount_row_key is not None:
                used_amount_rows.add(amount_row_key)
    return found


def parse_hsbc_summary(ocr):
    """Read the statement's printed account-summary totals as reconciliation data."""
    all_text = " ".join(p.get("text", "") for p in ocr.get("pages", [])[:2])
    month_year = re.findall(r"\b(" + MONTH_PATTERN + r")\s+(20\d{2})\b", all_text, re.I)
    statement_month = ("{}-{:02d}".format(month_year[-1][1], MONTHS[month_year[-1][0].upper()])
                       if month_year else None)
    period = re.search(r"\b(\d{1,2}\s+(?:" + MONTH_PATTERN + r")\s+20\d{2})\s*(?:TO|T0|[-–])\s*(\d{1,2}\s+(?:" + MONTH_PATTERN + r")\s+20\d{2})\b", all_text, re.I)
    metadata = {"statement_month": statement_month,
                "statement_period": "{} to {}".format(period.group(1), period.group(2)) if period else None}
    for page in ocr.get("pages", [])[:2]:
        lines = page.get("lines", [])
        for i, line in enumerate(lines):
            if "ACCOUNT SUMMARY" not in line.get("text", "").upper():
                continue
            block = " ".join(x.get("text", "") for x in lines[i:i + 5])
            match = re.search(r"([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})", block)
            if match:
                return {**metadata, "opening_balance_inr": _money(match.group(1)),
                        "expected_charges_inr": _money(match.group(2)),
                        "payment_credits_inr": _money(match.group(3))}
    return metadata


def extract_hsbc_pdf(pdf_path, job_dir=None, period_hint=""):
    """Render and OCR locally; returns structured line items, never calls a remote API."""
    temporary = tempfile.TemporaryDirectory(prefix="household-ledger-ocr-") if job_dir is None else None
    try:
        return _extract_hsbc_pdf(pdf_path, job_dir or temporary.name, period_hint)
    finally:
        if temporary is not None: temporary.cleanup()


def _extract_hsbc_pdf(pdf_path, job_dir, period_hint=""):
    node, modules, pdftoppm = _runtime_paths()
    job_dir = Path(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)
    prefix = job_dir / "page"
    subprocess.run([pdftoppm, "-png", "-scale-to", "2400", str(pdf_path), str(prefix)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=180)
    images = sorted(job_dir.glob("page-*.png"))
    if not images: raise RuntimeError("The PDF could not be rendered into pages.")
    env = os.environ.copy()
    env["NODE_PATH"] = modules
    env["LEDGER_OCR_CACHE"] = str(job_dir / "cache")
    env["LEDGER_OCR_HSBC_COLUMNS"] = "1"
    proc = subprocess.run([node, str(ROOT / "vendor" / "ocr.js")], input=json.dumps([str(p) for p in images]),
                          text=True, capture_output=True, env=env, cwd=str(ROOT), timeout=1200)
    if proc.returncode:
        raise RuntimeError("Local OCR failed: " + (proc.stderr.strip() or "unknown OCR error"))
    ocr = json.loads(proc.stdout)
    items = parse_hsbc_ocr(ocr, period_hint)
    summary = parse_hsbc_summary(ocr)
    return items, len(images), summary
