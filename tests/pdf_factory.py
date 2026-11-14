"""Generate fake bank-statement PDFs (several layouts) for tests."""
import io
from datetime import date

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

W, H = A4


def fmt(x):
    return f"{x:,.2f}"


def build(txns, layout="columns", start_balance=50000.0, password=None, newest_first=False, per_page=28, wrap=False):
    """txns: list of (date, narration, debit, credit). Returns PDF bytes."""
    bal, rows = start_balance, []
    for d, narr, debit, credit in txns:
        bal = bal - (debit or 0) + (credit or 0)
        rows.append((d, narr, debit or 0, credit or 0, bal))
    if newest_first:
        rows = rows[::-1]

    def dstr(d):
        return {"columns": d.strftime("%d/%m/%y"), "drcr": d.strftime("%d %b %Y"), "signed": d.isoformat(),
                "columns_us": d.strftime("%m/%d/%Y")}[layout]

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    pages = [rows[i:i + per_page] for i in range(0, len(rows), per_page)] or [[]]
    for pn, chunk in enumerate(pages, 1):
        c.setFont("Helvetica-Bold", 12)
        c.drawString(40, H - 40, "ACME BANK - Statement of Account")
        c.setFont("Helvetica", 9)
        c.drawString(40, H - 56, "Account No: 123456789012   IFSC: ACME0001234")
        y = H - 90
        c.setFont("Helvetica-Bold", 9)
        if layout in ("columns", "columns_us"):
            c.drawString(40, y, "Date"); c.drawString(100, y, "Narration"); c.drawString(270, y, "Chq/Ref No")
            c.drawRightString(440, y, "Withdrawal Amt."); c.drawRightString(510, y, "Deposit Amt."); c.drawRightString(580, y, "Closing Balance")
        elif layout == "drcr":
            for x, t in [(40, "Date"), (130, "Description")]:
                c.drawString(x, y, t)
            c.drawRightString(440, y, "Amount"); c.drawRightString(540, y, "Balance")
        else:
            c.drawString(40, y, "Date"); c.drawString(130, y, "Details"); c.drawRightString(540, y, "Amount")
        c.setFont("Helvetica", 9)
        y -= 18
        if pn == 1 and layout != "signed":
            c.drawString(40, y, dstr(date(2026, 1, 1)) if not newest_first else "")
            if not newest_first:
                c.drawString(100, y, "Opening Balance")
                c.drawRightString(540, y, fmt(start_balance))
                y -= 14
        for d, narr, debit, credit, b in chunk:
            c.drawString(40, y, dstr(d))
            lines = [narr]
            if wrap and len(narr) > 18:
                lines = [narr[:18], narr[18:]]
            c.drawString(100 if layout.startswith("columns") else 130, y, lines[0])
            if layout.startswith("columns"):
                c.drawString(270, y, str(abs(hash(narr)) % 10**10))
                if debit:
                    c.drawRightString(440, y, fmt(debit))
                if credit:
                    c.drawRightString(510, y, fmt(credit))
                c.drawRightString(580, y, fmt(b))
            elif layout == "drcr":
                c.drawRightString(440, y, fmt(debit or credit) + (" Dr" if debit else " Cr"))
                c.drawRightString(540, y, fmt(b))
            else:
                c.drawRightString(540, y, ("-" if debit else "") + fmt(debit or credit))
            for extra in lines[1:]:
                y -= 11
                c.drawString(100 if layout.startswith("columns") else 130, y, extra)
            y -= 14
        c.setFont("Helvetica", 8)
        c.drawString(40, 30, f"Page {pn} of {len(pages)}   This is a computer generated statement")
        c.showPage()
    c.save()
    data = buf.getvalue()
    if password:
        from pypdf import PdfReader, PdfWriter
        w = PdfWriter(clone_from=PdfReader(io.BytesIO(data)))
        w.encrypt(password, algorithm="AES-256")
        out = io.BytesIO()
        w.write(out)
        data = out.getvalue()
    return data


SAMPLE = [
    (date(2026, 1, 2), "UPI/SWIGGY/9876543210", 450.00, None),
    (date(2026, 1, 3), "SALARY ACME CORP", None, 52000.00),
    (date(2026, 1, 5), "POS 4321 STARBUCKS MUMBAI", 380.50, None),
    (date(2026, 1, 8), "NEFT-ELECTRICITY BILL", 1840.00, None),
    (date(2026, 1, 9), "UPI/UBER INDIA/12345", 212.75, None),
    (date(2026, 1, 12), "INTEREST CREDIT", None, 118.25),
    (date(2026, 1, 15), "AMAZON PAY INDIA", 2499.00, None),
    (date(2026, 1, 15), "UPI/SWIGGY/9876543211", 450.00, None),   # same day/amount as above on purpose? different day
]
