"""Data preprocessing and cleaning for raw transactions."""
import csv
import io
import re
from datetime import datetime

DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d %b %Y")


def clean_description(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    return text[:120]


# Words banks add to narrations that say nothing about the merchant.
BANK_NOISE = {
    "upi", "neft", "imps", "rtgs", "pos", "ach", "ecs", "nach", "atm", "dr", "cr", "debit", "credit",
    "payment", "pay", "paid", "to", "from", "by", "via", "txn", "transaction", "transfer", "trf", "ref",
    "no", "bank", "card", "ltd", "pvt", "limited", "india", "the", "and", "of", "for", "online", "purchase",
}


def normalize_merchant(text: str) -> str:
    """Key used to group repeated charges: lowercase, no digits/punctuation/bank noise words."""
    cleaned = re.sub(r"[^a-z\s]", " ", (text or "").lower())
    words = cleaned.split()
    kept = [w for w in words if w not in BANK_NOISE]
    return " ".join(kept or words)


def parse_date(value: str) -> str:
    value = (value or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"Unrecognised date: {value!r}")


def parse_csv(content: str):
    """Parse CSV with columns date, description, amount[, type].

    Negative amounts are treated as expenses when no type column is given.
    Returns (rows, errors). Repeated identical rows are kept (they can be real purchases);
    duplicates against existing data are detected separately in ml/dedupe.py.
    """
    reader = csv.DictReader(io.StringIO(content))
    rows, errors = [], []
    for i, raw in enumerate(reader, start=2):
        rec = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        try:
            date = parse_date(rec.get("date", ""))
            desc = clean_description(rec.get("description", ""))
            if not desc:
                raise ValueError("missing description")
            amount = float(rec.get("amount", "").replace(",", ""))
            ttype = rec.get("type", "").lower()
            if not ttype:  # no type column: sign decides
                ttype = "expense" if amount < 0 else "income"
            elif ttype not in ("income", "expense"):
                raise ValueError("type must be income or expense")
            amount = abs(amount)
            if amount == 0:
                raise ValueError("amount is zero")
        except ValueError as e:
            errors.append(f"line {i}: {e}")
            continue
        rows.append({"date": date, "description": desc, "amount": amount,
                     "type": ttype, "category": rec.get("category") or None})
    return rows, errors
