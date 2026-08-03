from __future__ import annotations

from datetime import datetime
from html import escape
from io import BytesIO
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

ORANGE = colors.HexColor("#FF5A00")
INK = colors.HexColor("#111111")
MUTED = colors.HexColor("#676767")


def render_application_letter_pdf(
    *,
    company: str,
    subject: str,
    body: str,
    generated_at: datetime | None = None,
) -> bytes:
    """Render every JobFlow application letter through one consistent A4 template."""
    now = generated_at or datetime.now(ZoneInfo("Europe/Vienna"))
    output = BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=24 * mm,
        rightMargin=24 * mm,
        topMargin=28 * mm,
        bottomMargin=24 * mm,
        title=subject,
        author="Antonio Beslic",
    )

    sender = ParagraphStyle(
        "Sender",
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=18,
        textColor=INK,
        spaceAfter=2,
    )
    sender_meta = ParagraphStyle(
        "SenderMeta",
        fontName="Helvetica",
        fontSize=9.5,
        leading=13,
        textColor=MUTED,
    )
    recipient = ParagraphStyle(
        "Recipient",
        fontName="Helvetica",
        fontSize=10.5,
        leading=15,
        textColor=INK,
    )
    date_style = ParagraphStyle(
        "Date",
        parent=recipient,
        alignment=TA_RIGHT,
        textColor=MUTED,
    )
    subject_style = ParagraphStyle(
        "Subject",
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=INK,
        spaceAfter=8 * mm,
    )
    body_style = ParagraphStyle(
        "Body",
        fontName="Helvetica",
        fontSize=10.5,
        leading=15.5,
        textColor=INK,
        spaceAfter=4.2 * mm,
        allowWidows=0,
        allowOrphans=0,
    )

    story = [
        Paragraph("ANTONIO BESLIC", sender),
        Paragraph("antoniobeslic.com · Wien, Österreich", sender_meta),
        Spacer(1, 17 * mm),
        Paragraph(escape(company), recipient),
        Paragraph("Personalabteilung", recipient),
        Spacer(1, 6 * mm),
        Paragraph(f"Wien, {now.strftime('%d.%m.%Y')}", date_style),
        Spacer(1, 8 * mm),
        Paragraph(escape(subject), subject_style),
    ]

    for block in (part.strip() for part in body.split("\n\n")):
        if not block:
            continue
        story.append(Paragraph("<br/>".join(escape(line) for line in block.splitlines()), body_style))

    def decorate(canvas, document) -> None:  # type: ignore[no-untyped-def]
        width, height = A4
        canvas.saveState()
        canvas.setFillColor(ORANGE)
        canvas.rect(0, height - 7 * mm, width, 7 * mm, stroke=0, fill=1)
        canvas.setStrokeColor(colors.HexColor("#D8D4CE"))
        canvas.setLineWidth(0.6)
        canvas.line(24 * mm, 18 * mm, width - 24 * mm, 18 * mm)
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 8)
        footer = "Antonio Beslic · antoniobeslic.com"
        canvas.drawString(24 * mm, 12 * mm, footer)
        page = str(document.page)
        canvas.drawString(width - 24 * mm - stringWidth(page, "Helvetica", 8), 12 * mm, page)
        canvas.restoreState()

    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return output.getvalue()
