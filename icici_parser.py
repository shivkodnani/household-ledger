"""Local OCR extraction for ICICI Amazon Pay Credit Card PDF statements."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from hsbc_parser import _runtime_paths

ROOT = Path(__file__).parent
MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
MONTH_NAME_PATTERN = r"(?:JAN(?:UARY)?|FEB(?:RUARY)?|MAR(?:CH)?|APR(?:IL)?|MAY|JUN(?:E)?|JUL(?:Y)?|AUG(?:UST)?|SEP(?:TEMBER)?|OCT(?:OBER)?|NOV(?:EMBER)?|DEC(?:EMBER)?)"
DATE_PATTERN = re.compile(r"(?<!\d)(\d{1,2})[/.\-](\d{1,2})[/.\-](20\d{2})(?!\d)")
MONTH_DATE_PATTERN = re.compile(
    r"\b(" + MONTH_NAME_PATTERN + r")\s+(\d{1,2}),?\s+(20\d{2})\b",
    re.I,
)
AMOUNT_PATTERN = re.compile(r"(?<![A-Z0-9])(?:\d{1,3}(?:,\d{3})+|\d+)[.,]\d{2}(?!\d)", re.I)
CURRENCY_PATTERN = re.compile(r"\b(AED|AUD|CAD|CHF|CNY|DKK|EUR|GBP|HKD|INR|JPY|NOK|NZD|SEK|SGD|THB|USD|ZAR)\b", re.I)


def get_icici_statement_password() -> str:
    """Return the ICICI-specific secret, configured outside the repository.

    For this account, ICICI's PDF rule is lowercase(first four name characters)
    followed by the birth day and month in DDMM order. The derived value is held
    only in ICICI_STATEMENT_PASSWORD, never in source code or the database.
    """
    password = os.environ.get("ICICI_STATEMENT_PASSWORD", "").strip()
    if not password:
        raise RuntimeError("ICICI PDF password is not configured on this server.")
    return password


def _decimal(raw: str | None) -> Decimal | None:
    if not raw:
        return None
    value = re.sub(r"[^\d,.]", "", raw.strip())
    if not value:
        return None
    if "." in value:
        value = value.replace(",", "")
    elif "," in value and len(value.rsplit(",", 1)[-1]) == 2:
        value = value.replace(",", ".")
    else:
        value = value.replace(",", "")
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _word_label(word: dict) -> str:
    return re.sub(r"[^A-Z]", "", str(word.get("text", "")).upper())


def _word_center(word: dict, width: int) -> float:
    return (float(word.get("x0", 0)) + float(word.get("x1", 0))) / (2 * max(width, 1))


def _clean_description(value: str) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    return re.sub(r"^[\W_]+|[\W_]+$", "", value, flags=re.UNICODE).strip()


def _columns(page: dict) -> dict[str, float]:
    width = max(1, int(page.get("width", 1)))
    for line in page.get("lines", []):
        words = line.get("words", [])
        labels = [_word_label(word) for word in words]
        if not ("DATE" in labels and "TRANSACTION" in labels and "AMOUNT" in labels and any(label.startswith("INTL") for label in labels)):
            continue
        word_by_label = {label: word for label, word in zip(labels, words)}
        amount_words = [word for label, word in zip(labels, words) if label == "AMOUNT"]
        inr_header = max(amount_words, key=lambda word: _word_center(word, width))
        intl_header = next(word for label, word in zip(labels, words) if label.startswith("INTL"))
        date_header = word_by_label["DATE"]
        serial_header = next((word for label, word in zip(labels, words) if label.startswith("SER")), None)
        detail_header = word_by_label["TRANSACTION"]
        reward_header = next((word for label, word in zip(labels, words) if label.startswith("REWARD")), None)
        date_left = max(0.0, float(date_header.get("x0", 0)) / width - 0.035)
        date_right = float(serial_header.get("x0", width * 0.4)) / width if serial_header else 0.42
        serial_left = float(serial_header.get("x0", width * 0.4)) / width - 0.01 if serial_header else 0.40
        detail_left = float(detail_header.get("x0", width * 0.5)) / width - 0.015
        detail_right = float(reward_header.get("x0", intl_header.get("x0", width * 0.74))) / width - 0.012 if reward_header else float(intl_header.get("x0", width * 0.78)) / width - 0.015
        intl_left = float(intl_header.get("x0", width * 0.80)) / width - 0.015
        inr_left = float(inr_header.get("x0", width * 0.88)) / width - 0.04
        return {
            "date_left": date_left,
            "date_right": date_right,
            "serial_left": serial_left,
            "detail_left": detail_left,
            "detail_right": detail_right,
            "intl_left": intl_left,
            "inr_left": max(intl_left + 0.02, inr_left),
            "inr_center": _word_center(inr_header, width),
        }
    # ICICI Amazon Pay statement layout fallback, used only if OCR misses a header word.
    return {
        "date_left": 0.28,
        "date_right": 0.41,
        "serial_left": 0.40,
        "detail_left": 0.49,
        "detail_right": 0.74,
        "intl_left": 0.79,
        "inr_left": 0.84,
        "inr_center": 0.90,
    }


def _date_from_text(text: str) -> date | None:
    normalized = text.strip().replace("O", "0").replace("o", "0")
    match = DATE_PATTERN.search(normalized)
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _statement_meta(pages: list[dict], period_hint: str = "") -> dict:
    statement_date = None
    statement_period = None
    for page in pages[:2]:
        lines = page.get("lines", [])
        for index, line in enumerate(lines):
            if "STATEMENT DATE" in str(line.get("text", "")).upper():
                nearby = " ".join(str(item.get("text", "")) for item in lines[index:index + 5])
                match = MONTH_DATE_PATTERN.search(nearby)
                if match:
                    month = MONTHS.get(match.group(1)[:3].upper())
                    if month:
                        try:
                            statement_date = date(int(match.group(3)), month, int(match.group(2)))
                        except ValueError:
                            pass
                        break
        for index, line in enumerate(lines):
            if "STATEMENT PERIOD" not in str(line.get("text", "")).upper():
                continue
            nearby = " ".join(str(item.get("text", "")) for item in lines[index:index + 5])
            dates = list(MONTH_DATE_PATTERN.finditer(nearby))
            if len(dates) >= 2:
                first, second = dates[:2]
                statement_period = "{} {}, {} to {} {}, {}".format(
                    first.group(1).title(), first.group(2), first.group(3),
                    second.group(1).title(), second.group(2), second.group(3),
                )
            break

    if not statement_date:
        for page in pages[:2]:
            lines = page.get("lines", [])
            for index, line in enumerate(lines):
                if "STATEMENT DATE" not in str(line.get("text", "")).upper():
                    continue
                for near in lines[index:index + 6]:
                    date_match = MONTH_DATE_PATTERN.search(str(near.get("text", "")))
                    if date_match:
                        month = MONTHS.get(date_match.group(1)[:3].upper())
                        if month:
                            try:
                                statement_date = date(int(date_match.group(3)), month, int(date_match.group(2)))
                            except ValueError:
                                pass
                        break
                if statement_date:
                    break

    if not statement_date:
        hint_match = re.search(r"\b(" + MONTH_NAME_PATTERN + r")\s+(20\d{2})\b|\b(20\d{2})-(\d{2})\b", period_hint.upper())
        if hint_match:
            if hint_match.group(1):
                month, year = MONTHS.get(hint_match.group(1)[:3], 0), int(hint_match.group(2))
            else:
                year, month = int(hint_match.group(3)), int(hint_match.group(4))
            if month:
                statement_date = date(year, month, 1)

    return {
        "statement_month": "{:04d}-{:02d}".format(statement_date.year, statement_date.month) if statement_date else None,
        "statement_period": statement_period,
    }


def _summary_expected(pages: list[dict]) -> float | None:
    for page in pages[:2]:
        width = max(1, int(page.get("width", 1)))
        lines = page.get("lines", [])
        for index, line in enumerate(lines):
            labels = [_word_label(word) for word in line.get("words", [])]
            if "PURCHASES" not in labels or "CHARGES" not in labels:
                continue
            purchase_words = [word for label, word in zip(labels, line.get("words", [])) if label in ("PURCHASES", "CHARGES")]
            purchase_center = sum(_word_center(word, width) for word in purchase_words) / len(purchase_words)
            header_y = float(line.get("y0", 0))
            for candidate in lines[index + 1:index + 4]:
                delta = float(candidate.get("y0", 0)) - header_y
                if delta <= 0 or delta > int(page.get("height", 1)) * 0.04:
                    continue
                values = []
                for word in candidate.get("words", []):
                    match = AMOUNT_PATTERN.search(str(word.get("text", "")))
                    center = _word_center(word, width)
                    if match and abs(center - purchase_center) <= 0.08:
                        amount = _decimal(match.group(0))
                        if amount is not None:
                            values.append((abs(center - purchase_center), amount))
                if values:
                    return float(min(values, key=lambda item: item[0])[1])
    return None


def parse_icici_ocr(ocr: dict, period_hint: str = "") -> tuple[list[dict], dict]:
    """Convert ICICI line OCR into reviewable transaction records."""
    pages = ocr.get("pages", [])
    summary = _statement_meta(pages, period_hint)
    summary["expected_charges_inr"] = _summary_expected(pages)
    found: list[dict] = []

    for page in pages:
        width = max(1, int(page.get("width", 1)))
        height = max(1, int(page.get("height", 1)))
        page_num = int(page.get("page", 0))
        columns = _columns(page)
        page_rows: list[dict] = []

        for line in page.get("lines", []):
            words = line.get("words", [])
            positioned = [(_word_center(word, width), word) for word in words]
            date_word = next((word for center, word in positioned
                              if columns["date_left"] <= center <= columns["date_right"]
                              and _date_from_text(str(word.get("text", "")))), None)
            if not date_word:
                continue
            transaction_date = _date_from_text(str(date_word.get("text", "")))
            if not transaction_date:
                continue

            serial_word = next((word for center, word in positioned
                                if columns["serial_left"] <= center < columns["detail_left"]
                                and 8 <= len(re.sub(r"\D", "", str(word.get("text", "")))) <= 14), None)
            if not serial_word:
                continue

            description_words = [word for center, word in positioned
                                 if columns["detail_left"] <= center < columns["detail_right"]]
            description = _clean_description(" ".join(str(word.get("text", "")) for word in description_words))

            amount_candidates = []
            for center, word in positioned:
                if center < columns["inr_left"]:
                    continue
                match = AMOUNT_PATTERN.search(str(word.get("text", "")))
                amount = _decimal(match.group(0)) if match else None
                if amount is not None:
                    amount_candidates.append((abs(center - columns["inr_center"]), word, amount))
            selected_amount = min(amount_candidates, key=lambda item: item[0]) if amount_candidates else None
            amount = selected_amount[2] if selected_amount else Decimal("0")
            amount_word = selected_amount[1] if selected_amount else None
            amount_confidence = float(amount_word.get("confidence", 0)) if amount_word else 0.0

            intl_words = [word for center, word in positioned if columns["intl_left"] <= center < columns["inr_left"]]
            intl_text = " ".join(str(word.get("text", "")) for word in intl_words)
            original_match = next((AMOUNT_PATTERN.search(str(word.get("text", ""))) for word in intl_words
                                   if AMOUNT_PATTERN.search(str(word.get("text", "")))), None)
            original_amount = _decimal(original_match.group(0)) if original_match else None
            upper_description = description.upper()
            currency_match = CURRENCY_PATTERN.search(intl_text + " " + description) if original_amount is not None else None
            currency = currency_match.group(1).upper() if currency_match else ("FX" if original_amount is not None else "INR")

            upper_row = " ".join(str(word.get("text", "")) for word in words).upper()
            payment = any(marker in upper_description for marker in (
                "BBPS", "PAYMENT RECEIVED", "PAYMENT THANK", "CARD PAYMENT", "AUTOPAY",
            ))
            credited = bool(re.search(r"\bCR\b", upper_row))
            refund = not payment and (credited or any(marker in upper_description for marker in (
                "REFUND", "REVERSAL", "CHARGEBACK", "CASHBACK",
            )))
            if payment:
                kind = "Card payment"
            elif refund:
                kind = "Refund"
                amount = -abs(amount)
            elif "INTEREST" in upper_description:
                kind = "Interest"
            elif any(marker in upper_description for marker in ("FEE", "CHARGE", "GST", "TAX")):
                kind = "Fee"
            else:
                kind = "Purchase"

            detail_confidences = [float(word.get("confidence", 0)) for word in description_words]
            line_confidence = float(line.get("confidence", 0))
            bbox = [int(float(date_word.get("x0", 0))), int(float(line.get("y0", 0))),
                    int(float(amount_word.get("x1", line.get("x1", width))) if amount_word else float(line.get("x1", width))),
                    int(float(line.get("y1", 0)))]
            page_rows.append({
                "date": transaction_date.isoformat(),
                "description": description or "ICICI transaction details need review",
                "amount_inr": float(amount),
                "original_amount": float(original_amount) if original_amount is not None else None,
                "currency": currency,
                "person": "Me",
                "kind": kind,
                "allocation": "Needs review",
                "share_percent": 0,
                "payment_method": "Credit card",
                "category": "Interest" if kind == "Interest" else ("Fees & charges" if kind == "Fee" else "Uncategorised"),
                "statement_id": None,
                "notes": "Imported from page {} · line OCR confidence {:.1f}% · INR amount confidence {:.1f}%".format(
                    page_num, line_confidence, amount_confidence,
                ),
                "source_page": page_num,
                "source_bbox": bbox,
                "ocr_confidence": sum(detail_confidences) / len(detail_confidences) if detail_confidences else line_confidence,
                "ocr_amount_confidence": amount_confidence,
                "ocr_amount_match": 1 if amount_word else 0,
                "_row_y": float(line.get("y0", 0)),
                "_row_y1": float(line.get("y1", 0)),
            })

        # ICICI descriptions sometimes wrap the final city/country to one short next line.
        for line in page.get("lines", []):
            y = float(line.get("y0", 0))
            previous = next((row for row in reversed(page_rows) if row["_row_y"] < y), None)
            if not previous:
                continue
            if y - previous["_row_y"] > height * 0.014:
                continue
            if any(_date_from_text(str(word.get("text", ""))) for word in line.get("words", [])):
                continue
            continuation = [word for word in line.get("words", [])
                            if columns["detail_left"] <= _word_center(word, width) < columns["detail_right"]]
            if not continuation or any(AMOUNT_PATTERN.search(str(word.get("text", ""))) for word in line.get("words", [])):
                continue
            suffix = " ".join(str(word.get("text", "")) for word in continuation).strip()
            if suffix:
                previous["description"] = _clean_description(previous["description"] + " " + suffix)
                previous["source_bbox"][3] = max(previous["source_bbox"][3], int(float(line.get("y1", 0))))

        for row in page_rows:
            row.pop("_row_y", None)
            row.pop("_row_y1", None)
            found.append(row)

    return found, summary


def extract_icici_pdf(pdf_path: str | Path, period_hint: str = "", job_dir: str | Path | None = None):
    """Render the encrypted source locally, OCR all pages, then clean temporary images."""
    password = get_icici_statement_password()
    node, modules, pdftoppm = _runtime_paths()
    temporary = tempfile.TemporaryDirectory(prefix="household-ledger-icici-") if job_dir is None else None
    workdir = Path(job_dir or temporary.name)
    try:
        workdir.mkdir(parents=True, exist_ok=True)
        prefix = workdir / "page"
        try:
            subprocess.run(
                [pdftoppm, "-upw", password, "-png", "-scale-to", "2400", str(pdf_path), str(prefix)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=180,
            )
        except subprocess.CalledProcessError:
            raise RuntimeError("The ICICI PDF could not be unlocked or rendered. Check the ICICI statement password.") from None
        except subprocess.TimeoutExpired:
            raise RuntimeError("The ICICI PDF took too long to render.") from None
        images = sorted(workdir.glob("page-*.png"), key=lambda path: int(re.search(r"page-(\d+)\.png$", path.name).group(1)))
        if not images:
            raise RuntimeError("The ICICI PDF could not be rendered into pages.")
        env = os.environ.copy()
        env["NODE_PATH"] = modules
        env["LEDGER_OCR_CACHE"] = str(workdir / "cache")
        env["LEDGER_OCR_MAX_X_RATIO"] = "1.0"
        proc = subprocess.run(
            [node, str(ROOT / "vendor" / "ocr.js")],
            input=json.dumps([str(image) for image in images]),
            text=True,
            capture_output=True,
            env=env,
            cwd=str(ROOT),
            timeout=1200,
        )
        if proc.returncode:
            raise RuntimeError("Local ICICI OCR failed: " + (proc.stderr.strip() or "unknown OCR error"))
        items, summary = parse_icici_ocr(json.loads(proc.stdout), period_hint)
        return items, len(images), summary
    finally:
        if temporary is not None:
            temporary.cleanup()
