"""Esporta l'ultima risposta in memoria, senza scrivere file sul server."""

import re
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
from text_format import readable_text


def answer_pdf(result, document_name):
    import reportlab
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    fonts = Path(reportlab.__file__).parent / 'fonts'
    for name, filename in [('BLText', 'Vera.ttf'), ('BLBold', 'VeraBd.ttf')]:
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(fonts / filename)))
    pdfmetrics.registerFontFamily('BLText', normal='BLText', bold='BLBold', italic='BLText', boldItalic='BLBold')
    body = ParagraphStyle('body', fontName='BLText', fontSize=10.5, leading=15,
                          textColor=colors.HexColor('#202238'), spaceAfter=6, splitLongWords=True)
    title = ParagraphStyle('title', parent=body, fontName='BLBold', fontSize=24, leading=30, spaceAfter=14)
    heading = ParagraphStyle('heading', parent=body, fontName='BLBold', fontSize=13, leading=18,
                             spaceBefore=10, spaceAfter=7, keepWithNext=True)
    small = ParagraphStyle('small', parent=body, fontSize=8.5, leading=12, textColor=colors.HexColor('#60687B'))
    story = [Paragraph('BoostLearn', title), Paragraph(escape(document_name), small),
             Paragraph('La tua richiesta', heading), Paragraph(escape(result['question']), body)]
    if result.get('request') and result['request'] != result['question']:
        story.append(Paragraph('Richiesta completa: ' + escape(result['request']), small))
    story.append(Paragraph('Risposta', heading))
    in_code = False
    for line in readable_text(result['text']).splitlines():
        if line.strip().startswith('```'):
            in_code = not in_code
            continue
        if not line.strip():
            story.append(Spacer(1, 4))
            continue
        is_heading = not in_code and bool(re.match(r'^#{1,6}\s+', line))
        text = re.sub(r'^#{1,6}\s+', '', line) if is_heading else line
        text = escape(text)
        if not in_code:
            text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
            text = re.sub(r'(?<!\S)\*([^*\n]+)\*(?=$|[\s.,;:!?])', r'<i>\1</i>', text)
            text = re.sub(r'`([^`]+)`', r'\1', text)
        story.append(Paragraph(text, heading if is_heading else body))
    pages = result.get('pages', [])
    if pages:
        story.extend([Paragraph('Pagine di riferimento', heading),
                      Paragraph(', '.join(map(str, pages)) + ' (numerazione del PDF originale)', body)])
    if result.get('summarized'):
        story.append(Paragraph('Analisi basata su sintesi intermedie: alcuni dettagli possono andare persi.', small))
    story.append(Paragraph('Risposta generata con AI. Verifica le informazioni nelle fonti originali.', small))

    def footer(canvas, doc):
        canvas.setFont('BLText', 8)
        canvas.setFillColor(colors.HexColor('#60687B'))
        canvas.drawString(2 * cm, 1.1 * cm, 'BoostLearn | Risposta esportata')
        canvas.drawRightString(A4[0] - 2 * cm, 1.1 * cm, str(doc.page))

    buffer = BytesIO()
    SimpleDocTemplate(buffer, pagesize=A4, leftMargin=2*cm, rightMargin=2*cm,
                      topMargin=1.8*cm, bottomMargin=1.8*cm, title='BoostLearn - Risposta').build(
                          story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
