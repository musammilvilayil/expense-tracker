"""Downloadable reports (CSV and PDF) for a month or a year."""
import csv
import io
import re
from datetime import date
from xml.sax.saxutils import escape

from flask import Blueprint, Response, request, session

from .helpers import current_user, err, login_required, run_autopay, user_budgets, user_transactions
from .ml import analysis, subscriptions

bp = Blueprint("reports", __name__)
PERIOD_RE = re.compile(r"^\d{4}(-(0[1-9]|1[0-2]))?$")
PIE_COLORS = ["#2f6b0a", "#b8f06f", "#5bb8d4", "#e0803f", "#f3dc6b", "#a99bf0", "#0d1a08", "#d6e4c4"]


def csv_safe(value):
    """Stop spreadsheet formula injection (cells starting with = + - @)."""
    s = str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def build_report(uid, period):
    run_autopay(uid)
    txs = user_transactions(uid)
    rows = sorted((t for t in txs if t["date"].startswith(period)), key=lambda t: (t["date"], t["id"]))
    summary = analysis.summarize(txs, period)
    monthly = len(period) == 7
    return {
        "period": period, "rows": rows, "summary": summary,
        "budgets": analysis.budget_status(txs, user_budgets(uid), period) if monthly else [],
        "subscriptions": subscriptions.detect(txs),
        "top": sorted((t for t in rows if t["type"] == "expense"), key=lambda t: -t["amount"])[:10],
    }


def make_csv(rep):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["date", "description", "amount", "type", "category", "source"])
    for t in rep["rows"]:
        w.writerow([t["date"], csv_safe(t["description"]), f"{t['amount']:.2f}", t["type"], t["category"] or "", t["source"]])
    return out.getvalue().encode("utf-8-sig")  # BOM so Excel opens UTF-8 correctly


def make_pdf(rep, username):
    from reportlab.graphics.charts.piecharts import Pie
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    green, soft = colors.HexColor("#2f6b0a"), colors.HexColor("#f3f8ec")
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"Finance report {rep['period']}", author="AI Finance Tracker")
    P = lambda t, s="BodyText": Paragraph(escape(str(t)), styles[s])
    s = rep["summary"]
    story = [Paragraph(f"Finance report: {escape(rep['period'])}", styles["Title"]),
             P(f"Prepared for {username} on {date.today().isoformat()}"), Spacer(1, 8)]

    def table(data, widths, header=True):
        t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
        st = [("FONTSIZE", (0, 0), (-1, -1), 9), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d9e3cd")),
              ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, soft])]
        if header:
            st += [("BACKGROUND", (0, 0), (-1, 0), green), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                   ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
        t.setStyle(TableStyle(st))
        return t

    story += [table([["Income", "Expenses", "Savings", "Savings rate"],
                     [f"{s['income']:,.2f}", f"{s['expense']:,.2f}", f"{s['savings']:,.2f}", f"{s['savings_rate']}%"]],
                    [40 * mm] * 4), Spacer(1, 12)]

    if s["by_category"]:
        story.append(P("Spending by category", "Heading2"))
        d = Drawing(70 * mm, 55 * mm)
        pie = Pie()
        pie.x, pie.y, pie.width, pie.height = 5 * mm, 2 * mm, 50 * mm, 50 * mm
        pie.data = list(s["by_category"].values())
        for i in range(len(pie.data)):
            pie.slices[i].fillColor = colors.HexColor(PIE_COLORS[i % len(PIE_COLORS)])
            pie.slices[i].strokeColor = colors.white
        d.add(pie)
        total = s["expense"] or 1
        cat_rows = [["Category", "Amount", "Share"]] + [[c, f"{a:,.2f}", f"{a / total * 100:.1f}%"] for c, a in s["by_category"].items()]
        layout = Table([[d, table(cat_rows, [38 * mm, 28 * mm, 18 * mm])]], colWidths=[75 * mm, 100 * mm])
        layout.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story += [layout, Spacer(1, 10)]

    if rep["budgets"]:
        story += [P("Budgets", "Heading2"), table([["Category", "Limit", "Spent", "Used"]] + [
            [b["category"], f"{b['limit']:,.2f}", f"{b['spent']:,.2f}", f"{b['percent']}%"] for b in rep["budgets"]], [45 * mm, 38 * mm, 38 * mm, 25 * mm]), Spacer(1, 10)]
    if rep["subscriptions"]:
        story += [P("Subscriptions and recurring payments", "Heading2"), table([["Name", "Every", "Amount", "Next renewal"]] + [
            [x["name"][:40], x["frequency"], f"{x['amount']:,.2f}", x["next_renewal"]] for x in rep["subscriptions"][:15]],
            [65 * mm, 25 * mm, 30 * mm, 35 * mm]), Spacer(1, 10)]
    if rep["top"]:
        story += [P("Largest expenses", "Heading2"), table([["Date", "Description", "Category", "Amount"]] + [
            [t["date"], t["description"][:45], t["category"] or "", f"{t['amount']:,.2f}"] for t in rep["top"]],
            [25 * mm, 80 * mm, 32 * mm, 25 * mm]), Spacer(1, 10)]

    limit = 250
    story.append(P(f"All transactions ({len(rep['rows'])})", "Heading2"))
    if rep["rows"]:
        data = [["Date", "Description", "Category", "Type", "Amount"]] + [
            [t["date"], t["description"][:42], t["category"] or "", t["type"], f"{t['amount']:,.2f}"] for t in rep["rows"][:limit]]
        story.append(table(data, [24 * mm, 75 * mm, 30 * mm, 18 * mm, 25 * mm]))
        if len(rep["rows"]) > limit:
            story.append(P(f"Showing the first {limit} of {len(rep['rows'])}. Download the CSV for the full list."))
    else:
        story.append(P("No transactions in this period."))
    story += [Spacer(1, 10), P("Generated automatically. Forecasts and tips are guidance, not financial advice.", "Italic")]

    def footer(canvas, d):
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {d.page}")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


@bp.get("/api/report")
@login_required
def report():
    period = request.args.get("period") or date.today().strftime("%Y-%m")
    fmt = (request.args.get("format") or "csv").lower()
    if not PERIOD_RE.match(period):
        return err("period must look like 2026-11 or 2026")
    if fmt not in ("csv", "pdf"):
        return err("format must be csv or pdf")
    rep = build_report(session["user_id"], period)
    name = f"finance-report-{period}.{fmt}"
    if fmt == "csv":
        return Response(make_csv(rep), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename={name}"})
    try:
        pdf = make_pdf(rep, current_user()["username"])
    except ImportError:
        return err("PDF export needs the 'reportlab' package (pip install reportlab).", 501)
    return Response(pdf, mimetype="application/pdf", headers={"Content-Disposition": f"attachment; filename={name}"})
