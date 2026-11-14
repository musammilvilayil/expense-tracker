"""Bank statement PDF reader (text-based PDFs, with optional password).

Bank layouts differ a lot, so this is a heuristic parser: it finds lines that
start with a date and contain money amounts, works out debit/credit from the
running balance when available (most reliable), then from Dr/Cr markers or
minus signs, then from the Debit/Credit column position, then keywords.
The import screen always shows a preview so the user can fix mistakes.
Scanned (image-only) PDFs are not supported.
"""
import io
import re
from datetime import date, datetime

MAX_PAGES = 200


class StatementError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


# ---------------- PDF text ----------------
def extract_pages(data: bytes, password: str | None = None):
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError as e:  # pragma: no cover
        raise StatementError("unsupported", "PDF support is not installed (pip install pypdf cryptography).") from e
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                ok = reader.decrypt(password or "")
            except Exception as e:  # missing crypto library or unsupported scheme
                raise StatementError("unsupported", "This PDF's encryption could not be handled. "
                                     "Install 'cryptography' or export an unprotected copy.") from e
            if not ok:
                raise StatementError("wrong_password" if password else "password_required",
                                     "That password is incorrect." if password else
                                     "This PDF is password protected. Enter its password to continue.")
        pages = []
        for page in reader.pages[:MAX_PAGES]:
            try:
                text = page.extract_text(extraction_mode="layout")
            except TypeError:  # older pypdf
                text = page.extract_text()
            pages.append(text or "")
    except StatementError:
        raise
    except PdfReadError as e:
        raise StatementError("invalid", "This file could not be read as a PDF.") from e
    except Exception as e:
        raise StatementError("invalid", "This file could not be read as a PDF.") from e
    if not "".join(pages).strip():
        raise StatementError("scanned", "No text found. This looks like a scanned image PDF, which is not supported. "
                             "Download the statement as CSV/Excel or a text PDF from net banking instead.")
    return pages


# ---------------- tokens ----------------
DATE_RE = re.compile(
    r"^\s*(?:\d{1,3}\s+)?("
    r"\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}[-/ .][A-Za-z]{3,9}[-/ .,]*\d{2,4}"
    r"|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}"
    r")(?!\d)")
ANY_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}[-/ .][A-Za-z]{3,9}[-/ .,]*\d{2,4}|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})(?!\d)")
AMOUNT_RE = re.compile(r"(?<![\w.,])(-|\()?(?:₹|Rs\.?|INR)?\s?((?:\d{1,3}(?:,\d{2,3})+|\d+)\.\d{2})(?![\d])\)?\s*(Cr|CR|cr|Dr|DR|dr)?(?![A-Za-z])")
NOISE_LINE = re.compile(
    r"(page\s+\d+|statement\s+of\s+account|account\s+(no|number|statement)|customer\s+(id|name)|ifsc|micr|branch|"
    r"date\s+(narration|description|particulars|details)|particulars|brought\s+forward|carried\s+forward|"
    r"closing\s+balance|total\s+(debit|credit|withdraw)|generated\s+on|this\s+is\s+a\s+computer|registered\s+office|"
    r"opening\s+balance)", re.I)
OPENING_RE = re.compile(r"opening\s+balance|balance\s+(brought\s+forward|b/f)", re.I)
CREDIT_WORDS = re.compile(r"\b(salary|credit(ed)?|deposit(ed)?|refund|reversal|interest|cashback|received|dividend|"
                          r"by\s+transfer|inward|neft\s*cr|upi\s*cr)\b", re.I)
HEADER_DEBIT = re.compile(r"(withdraw\w*|debit\w*|\bdr\b)", re.I)
HEADER_CREDIT = re.compile(r"(deposit\w*|credit\w*|\bcr\b)", re.I)


def _amount(s):
    return round(float(s.replace(",", "")), 2)


def _parse_date(raw, dayfirst):
    raw = raw.strip().replace(",", " ")
    raw = re.sub(r"\s+", " ", raw)
    cands = ["%Y-%m-%d"]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        pass
    elif re.fullmatch(r"\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}", raw):
        sep = re.search(r"[/.-]", raw).group()
        parts = ["%d", "%m"] if dayfirst else ["%m", "%d"]
        yr = "%Y" if len(raw.split(sep)[-1]) == 4 else "%y"
        cands = [sep.join(parts + [yr]), sep.join(parts[::-1] + [yr])]
    else:
        norm = re.sub(r"[-/.]", " ", raw)
        raw = norm
        cands = ["%d %b %Y", "%d %b %y", "%d %B %Y", "%d %B %y"]
    for fmt in cands:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _detect_dayfirst(date_strings):
    for s in date_strings:
        m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-]\d{2,4}", s.strip())
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a > 12:
                return True
            if b > 12:
                return False
    return True


# ---------------- parsing ----------------
def _blank_spans(line, spans):
    chars = list(line)
    for a, b in spans:
        for i in range(a, min(b, len(chars))):
            chars[i] = " "
    return "".join(chars)


def _find_columns(lines):
    """Positions (centres) of Debit/Withdrawal and Credit/Deposit headers, if a header line exists."""
    for ln in lines:
        d = HEADER_DEBIT.search(ln)
        c = HEADER_CREDIT.search(ln)
        if d and c and d.start() != c.start():
            return ((d.start() + d.end()) / 2, (c.start() + c.end()) / 2)
    return None


def parse_pages(pages):
    """Return (rows, warnings). rows: dicts with date, description, amount, type, confidence."""
    lines = [ln for p in pages for ln in p.splitlines()]
    cols = _find_columns(lines)

    raw_rows, cur, opening = [], None, None

    def finish():
        nonlocal cur, opening
        if cur is None:
            return
        text = re.sub(r"\s+", " ", " ".join(cur["text"])).strip(" -|/")
        text = re.sub(r"(\s+\d{7,})+$", "", text)  # trailing reference / cheque numbers
        if cur["amounts"] and OPENING_RE.search(text):
            opening = cur["amounts"][-1]["value"]
        elif cur["amounts"] and not NOISE_LINE.search(text):
            cur["desc"] = text[:120] or "Statement transaction"
            raw_rows.append(cur)
        cur = None

    for line in lines:
        if not line.strip():
            continue
        m = DATE_RE.match(line)
        if m:
            finish()
            spans = [(m.start(1), m.end(1))]
            rest_start = m.end()
            m2 = DATE_RE.match(" " * rest_start + line[rest_start:])  # value date right after the first
            if m2 and m2.start(1) - rest_start <= 4:
                spans.append((m2.start(1), m2.end(1)))
            cur = {"date_raw": m.group(1), "text": [], "amounts": []}
            body = _blank_spans(line, spans)
        elif cur is not None:
            if NOISE_LINE.search(line) and not OPENING_RE.search(line):
                finish()
                continue
            body = _blank_spans(line, [m_.span() for m_ in ANY_DATE_RE.finditer(line)])
        else:
            continue
        pos = 0
        pieces = []
        for am in AMOUNT_RE.finditer(body):
            pieces.append(body[pos:am.start()])
            pos = am.end()
            cur["amounts"].append({
                "value": _amount(am.group(2)), "neg": bool(am.group(1)),
                "mark": (am.group(3) or "").lower(), "center": (am.start(2) + am.end(2)) / 2})
        pieces.append(body[pos:])
        txt = " ".join(p.strip() for p in pieces if p.strip())
        if txt:
            cur["text"].append(txt)
    finish()

    if not raw_rows:
        raise StatementError("no_transactions", "No transactions were found in this PDF. If it is a bank statement, "
                             "try exporting it as CSV (date, description, amount).")

    dayfirst = _detect_dayfirst([r["date_raw"] for r in raw_rows])
    with_balance = sum(1 for r in raw_rows if len(r["amounts"]) >= 2) > len(raw_rows) / 2

    parsed = []
    for r in raw_rows:
        d = _parse_date(r["date_raw"], dayfirst)
        if d is None:
            continue
        ams = r["amounts"]
        bal = None
        if with_balance and len(ams) >= 2:
            bal, ams = ams[-1]["value"], ams[:-1]
        nz = [a for a in ams if a["value"] > 0]
        if not nz:
            continue
        a = nz[0]
        hint, conf = None, None
        if a["mark"] in ("dr", "cr"):
            hint, conf = ("expense" if a["mark"] == "dr" else "income"), "marker"
        elif a["neg"]:
            hint, conf = "expense", "marker"
        elif cols and len(ams) >= 1:
            dist_d, dist_c = abs(a["center"] - cols[0]), abs(a["center"] - cols[1])
            hint, conf = ("expense" if dist_d <= dist_c else "income"), "column"
        parsed.append({"date": d, "description": r["desc"], "amount": a["value"], "balance": bal,
                       "type": hint, "confidence": conf})

    _apply_balance_deltas(parsed, opening)

    guesses = 0
    for p in parsed:
        if p["type"] is None:
            p["type"] = "income" if CREDIT_WORDS.search(p["description"]) else "expense"
            p["confidence"] = "keyword" if p["type"] == "income" else "guess"
            guesses += p["type"] == "expense" and p["confidence"] == "guess"
    warnings = []
    if guesses:
        warnings.append(f"{guesses} row(s) had no clear debit/credit marker and were assumed to be expenses. Check the Type column in the preview.")
    rows = [{"date": p["date"].isoformat(), "description": p["description"], "amount": p["amount"],
             "type": p["type"], "confidence": p["confidence"]} for p in parsed]
    return rows, warnings


def _apply_balance_deltas(parsed, opening):
    """Use the running balance to decide debit vs credit (most reliable signal)."""
    n = len(parsed)
    if n < 2 and opening is None:
        return
    bals = [p["balance"] for p in parsed]
    if sum(b is not None for b in bals) < max(2, n // 2):
        return

    def close(x, y):
        return abs(x - y) < 0.02

    def prev_asc(i):
        return bals[i - 1] if i > 0 else opening

    def next_desc(i):
        return bals[i + 1] if i + 1 < n else opening

    asc = sum(1 for i in range(n) if bals[i] is not None and prev_asc(i) is not None
              and (close(abs(bals[i] - prev_asc(i)), parsed[i]["amount"])))
    desc = sum(1 for i in range(n) if bals[i] is not None and next_desc(i) is not None
               and (close(abs(bals[i] - next_desc(i)), parsed[i]["amount"])))
    if max(asc, desc) < max(1, n // 3):
        return
    ascending = asc >= desc
    for i, p in enumerate(parsed):
        before = prev_asc(i) if ascending else next_desc(i)
        if p["balance"] is None or before is None:
            continue
        delta = p["balance"] - before
        if close(delta, p["amount"]):
            p["type"], p["confidence"] = "income", "balance"
        elif close(delta, -p["amount"]):
            p["type"], p["confidence"] = "expense", "balance"
