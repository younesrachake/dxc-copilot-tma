"""
PDF Service — real formatted PDFs (reportlab) for RG2 guides and KB documents.
Replaces the old fake text-blob "PDF" downloads.
"""
import io
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DXC_PURPLE = "#5F259F"
INK = "#17171F"
MUTED = "#55555F"


def _styles():
    from reportlab.lib.styles import ParagraphStyle
    return {
        "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=19,
                                textColor="white", leading=24),
        "subtitle": ParagraphStyle("subtitle", fontName="Helvetica", fontSize=10,
                                   textColor="white", leading=13),
        "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=13,
                             textColor=DXC_PURPLE, spaceBefore=16, spaceAfter=7),
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=10.5,
                               textColor=INK, leading=15, spaceAfter=5),
        "step": ParagraphStyle("step", fontName="Helvetica", fontSize=10.5,
                               textColor=INK, leading=15, leftIndent=16,
                               spaceAfter=5, bulletIndent=2),
        "meta": ParagraphStyle("meta", fontName="Helvetica", fontSize=9,
                               textColor=MUTED, spaceAfter=2),
        "box": ParagraphStyle("box", fontName="Helvetica-Oblique", fontSize=10,
                              textColor=INK, leading=14),
    }


def _build(title: str, subtitle: str, flowables_body) -> bytes:
    """Common frame: purple header band, body flowables, dated footer."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    )

    styles = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=14 * mm, bottomMargin=16 * mm,
        title=title,
    )

    header = Table(
        [[Paragraph(title, styles["title"])],
         [Paragraph(subtitle, styles["subtitle"])]],
        colWidths=[doc.width],
    )
    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(DXC_PURPLE)),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (0, 0), 12),
        ("BOTTOMPADDING", (0, 1), (0, 1), 12),
    ]))

    stamp = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    footer = Paragraph(
        f"Généré par DXC Copilot — {stamp}", styles["meta"]
    )

    doc.build([header, Spacer(1, 8 * mm)] + flowables_body + [Spacer(1, 10 * mm), footer])
    return buf.getvalue()


def guide_pdf(guide: dict) -> bytes:
    """RG2 incident guide → formatted PDF."""
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Table, TableStyle, Spacer

    styles = _styles()
    incident = str(guide.get("incident_type") or guide.get("incidentType") or "incident")
    occurrences = guide.get("occurrences", "?")
    steps = guide.get("steps") or []
    recommendation = guide.get("recommendation") or ""

    body = [
        Paragraph(f"<b>Type d'incident :</b> {incident}", styles["body"]),
        Paragraph(f"<b>Occurrences détectées :</b> {occurrences}", styles["body"]),
        Paragraph("Étapes de résolution", styles["h2"]),
    ]
    for i, step in enumerate(steps, 1):
        body.append(Paragraph(f"{i}. {step}", styles["step"]))

    if recommendation:
        box = Table([[Paragraph(f"💡 {recommendation}", styles["box"])]],
                    colWidths=[160 * mm])
        box.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F3ECFA")),
            ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor(DXC_PURPLE)),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        body += [Spacer(1, 6 * mm), box]

    title = str(guide.get("title") or f"Guide RG2 — {incident.capitalize()}")
    return _build(title, "Guide de résolution généré automatiquement (règle RG2)", body)


def document_pdf(title: str, meta: dict, sections: list[dict]) -> bytes:
    """Generic KB/library document → formatted PDF.
    sections: [{"heading": str, "content": str}]"""
    from reportlab.platypus import Paragraph

    styles = _styles()
    body = []
    for key, value in (meta or {}).items():
        body.append(Paragraph(f"<b>{key} :</b> {value}", styles["body"]))
    for section in sections or []:
        if section.get("heading"):
            body.append(Paragraph(str(section["heading"]), styles["h2"]))
        if section.get("content"):
            for para in str(section["content"]).split("\n"):
                if para.strip():
                    body.append(Paragraph(para.strip(), styles["body"]))
    return _build(title, "Document — base de connaissances DXC Copilot", body)
