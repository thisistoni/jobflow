from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from jobflow.letter_pdf import render_application_letter_pdf


def test_application_letter_template_is_a_single_page_pdf() -> None:
    pdf = render_application_letter_pdf(
        company="PMC International GmbH",
        subject="Bewerbung als Junior Software Developer (all genders)",
        body=(
            "Sehr geehrte Damen und Herren,\n\n"
            "die Position interessiert mich, weil sie praktische Softwareentwicklung mit digitalen Produkten verbindet.\n\n"
            "In meiner aktuellen Tätigkeit entwickle ich neben dem operativen Support Automatisierungen und interne Anwendungen. "
            "Dabei arbeite ich unter anderem mit Python sowie mit Prozess- und Systemintegrationen.\n\n"
            "Gerne erläutere ich persönlich, wie ich diese Erfahrung in die ausgeschriebene Position einbringen kann.\n\n"
            "Mit freundlichen Grüßen\nAntonio Beslic"
        ),
        generated_at=datetime(2026, 8, 3, 12, 0, tzinfo=ZoneInfo("Europe/Vienna")),
    )

    assert pdf.startswith(b"%PDF-")
    assert b"/Count 1" in pdf
    assert len(pdf) > 1_000
