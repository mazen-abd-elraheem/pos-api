"""
pos-api-fastapi/services/pdf_service.py — PDF Generation Service
Ported from core/PDF_Generation.py with dual-format support:
1. 80mm Thermal Receipt (POS Roll Printer)
2. Standard A4 Formal Invoice
Includes Arabic Bidi/reshaper support & QR Code generation.
"""

import io
import os
import json
import logging
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

logger = logging.getLogger("pdf_service")

# Try to register Arabic font if available on host system
DEFAULT_FONT = "Helvetica"
try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    HAS_ARABIC_SUPPORT = True
except ImportError:
    HAS_ARABIC_SUPPORT = False

# Register Arial or common TTF for Arabic support if available
for font_name, font_path in [
    ("Arial", "arial.ttf"),
    ("Arial", "C:\\Windows\\Fonts\\arial.ttf"),
    ("SegoeUI", "C:\\Windows\\Fonts\\segoeui.ttf"),
    ("DejaVuSans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
]:
    try:
        if os.path.exists(font_path) or not font_path.startswith(("/", "C:")):
            pdfmetrics.registerFont(TTFont(font_name, font_path))
            DEFAULT_FONT = font_name
            break
    except Exception:
        continue


def reshape_text(text: Any) -> str:
    """Format Arabic text for ReportLab rendering."""
    if text is None:
        return ""
    text_str = str(text)
    if not HAS_ARABIC_SUPPORT:
        return text_str
    try:
        reshaped = arabic_reshaper.reshape(text_str)
        return get_display(reshaped)
    except Exception:
        return text_str


def generate_qr_image(data: str) -> Optional[Image]:
    """Generate in-memory QR code image for receipt / invoice verification."""
    try:
        import qrcode
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=4,
            border=1,
        )
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return Image(buf, width=28 * mm, height=28 * mm)
    except Exception as e:
        logger.warning(f"QR generation skipped: {e}")
        return None


def _build_thermal_receipt_sync(sale: Dict[str, Any], store: Dict[str, Any]) -> bytes:
    """Build 80mm thermal receipt PDF in memory."""
    buf = io.BytesIO()

    # 80mm width standard = ~226.77 points
    page_width = 80 * mm
    # Estimate height based on items
    products = sale.get("products") or []
    if isinstance(products, str):
        try:
            products = json.loads(products)
        except Exception:
            products = []

    estimated_height = max(140 * mm, (110 + len(products) * 12) * mm)

    doc = SimpleDocTemplate(
        buf,
        pagesize=(page_width, estimated_height),
        leftMargin=4 * mm,
        rightMargin=4 * mm,
        topMargin=5 * mm,
        bottomMargin=5 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReceiptTitle",
        fontName=DEFAULT_FONT,
        fontSize=13,
        leading=16,
        alignment=1,  # Center
        textColor=colors.HexColor("#111827"),
    )
    center_style = ParagraphStyle(
        "ReceiptCenter",
        fontName=DEFAULT_FONT,
        fontSize=8,
        leading=11,
        alignment=1,
        textColor=colors.HexColor("#4B5563"),
    )
    bold_style = ParagraphStyle(
        "ReceiptBold",
        fontName=DEFAULT_FONT,
        fontSize=9,
        leading=12,
        alignment=0,
        textColor=colors.HexColor("#111827"),
    )
    item_style = ParagraphStyle(
        "ReceiptItem",
        fontName=DEFAULT_FONT,
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#111827"),
    )

    elements = []

    # Store Name & Contact
    store_name = store.get("store_name") or store.get("name") or "POS Store"
    store_address = store.get("store_address") or store.get("address") or ""
    store_phone = store.get("store_phone") or store.get("phone") or ""

    elements.append(Paragraph(f"<b>{reshape_text(store_name)}</b>", title_style))
    if store_address:
        elements.append(Paragraph(reshape_text(store_address), center_style))
    if store_phone:
        elements.append(Paragraph(f"Tel: {store_phone}", center_style))
    elements.append(Spacer(1, 3 * mm))

    # Divider line
    line_data = [["-" * 42]]
    t_line = Table(line_data, colWidths=[72 * mm])
    t_line.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"), ("FONTSIZE", (0, 0), (-1, -1), 7)]))
    elements.append(t_line)

    # Order Meta
    order_num = sale.get("order_number") or f"ORD-{sale.get('id', 0)}"
    date_str = str(sale.get("date") or sale.get("created_at") or datetime.now().strftime("%Y-%m-%d"))
    time_str = str(sale.get("time") or datetime.now().strftime("%H:%M:%S"))
    cashier = sale.get("employee") or "Cashier"

    meta_table = [
        [Paragraph(f"Order: <b>{order_num}</b>", bold_style), Paragraph(f"Date: {date_str[:10]}", item_style)],
        [Paragraph(f"Cashier: {cashier}", item_style), Paragraph(f"Time: {time_str[:8]}", item_style)],
    ]
    t_meta = Table(meta_table, colWidths=[36 * mm, 36 * mm])
    t_meta.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    elements.append(t_meta)
    elements.append(t_line)

    # Items Table Header
    items_table_data = [[
        Paragraph("<b>Item</b>", item_style),
        Paragraph("<b>Qty</b>", item_style),
        Paragraph("<b>Price</b>", item_style),
        Paragraph("<b>Total</b>", item_style),
    ]]

    for p in products:
        name = p.get("title") or p.get("name") or "Item"
        qty = p.get("quantity") or p.get("qty") or 1
        price = float(p.get("price") or 0.0)
        item_total = qty * price
        items_table_data.append([
            Paragraph(reshape_text(name), item_style),
            Paragraph(str(qty), item_style),
            Paragraph(f"{price:.2f}", item_style),
            Paragraph(f"{item_total:.2f}", item_style),
        ])

    t_items = Table(items_table_data, colWidths=[33 * mm, 11 * mm, 14 * mm, 14 * mm])
    t_items.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
    ]))
    elements.append(t_items)
    elements.append(t_line)

    # Totals
    total_amount = float(sale.get("total_amount") or 0.0)
    method = sale.get("method") or "Cash"

    totals_data = [
        [Paragraph("<b>Grand Total:</b>", bold_style), Paragraph(f"<b>{total_amount:.2f} EGP</b>", bold_style)],
        [Paragraph("Payment Method:", item_style), Paragraph(method, item_style)],
    ]
    t_totals = Table(totals_data, colWidths=[40 * mm, 32 * mm])
    t_totals.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    elements.append(t_totals)
    elements.append(Spacer(1, 3 * mm))

    # QR Code
    qr_payload = f"Order:{order_num}|Total:{total_amount}|Date:{date_str}"
    qr_img = generate_qr_image(qr_payload)
    if qr_img:
        elements.append(qr_img)
        elements.append(Spacer(1, 2 * mm))

    # Footer
    elements.append(Paragraph(reshape_text("شكراً لزيارتكم!"), center_style))
    elements.append(Paragraph("Thank you for your visit!", center_style))

    doc.build(elements)
    buf.seek(0)
    return buf.getvalue()


def _build_a4_invoice_sync(sale: Dict[str, Any], store: Dict[str, Any]) -> bytes:
    """Build standard A4 formal tax invoice PDF in memory."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    styles = getSampleStyleSheet()
    header_title = ParagraphStyle(
        "A4Title",
        fontName=DEFAULT_FONT,
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#5A55D6"),
        fontBold=True,
    )
    company_style = ParagraphStyle(
        "A4Company",
        fontName=DEFAULT_FONT,
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#374151"),
    )
    th_style = ParagraphStyle(
        "A4TH",
        fontName=DEFAULT_FONT,
        fontSize=10,
        leading=12,
        textColor=colors.white,
        alignment=1,
    )
    td_style = ParagraphStyle(
        "A4TD",
        fontName=DEFAULT_FONT,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#1F2937"),
    )

    elements = []

    store_name = store.get("store_name") or store.get("name") or "POS System"
    store_addr = store.get("store_address") or store.get("address") or ""
    store_phone = store.get("store_phone") or store.get("phone") or ""
    store_tax_id = store.get("tax_number") or store.get("vat_number") or ""

    order_num = sale.get("order_number") or f"INV-{sale.get('id', 0)}"
    date_str = str(sale.get("date") or sale.get("created_at") or datetime.now().strftime("%Y-%m-%d"))

    # Top Header Row: Store info on left, Invoice title & order on right
    header_table_data = [
        [
            Paragraph(f"<b>{reshape_text(store_name)}</b><br/>{reshape_text(store_addr)}<br/>Tel: {store_phone}<br/>Tax ID: {store_tax_id}", company_style),
            Paragraph(f"<b>TAX INVOICE</b><br/><font size=11 color='#6B7280'>#{order_num}</font><br/><font size=9>Date: {date_str[:10]}</font>", header_title),
        ]
    ]
    t_top = Table(header_table_data, colWidths=[95 * mm, 85 * mm])
    t_top.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ]))
    elements.append(t_top)
    elements.append(Spacer(1, 8 * mm))

    # Customer & Bill-to Box
    customer = sale.get("customer") or "Walk-in Customer"
    employee = sale.get("employee") or "Staff"
    elements.append(Paragraph(f"<b>Bill To:</b> {reshape_text(customer)} &nbsp;&nbsp;|&nbsp;&nbsp; <b>Cashier:</b> {employee}", company_style))
    elements.append(Spacer(1, 4 * mm))

    # Items Table
    products = sale.get("products") or []
    if isinstance(products, str):
        try:
            products = json.loads(products)
        except Exception:
            products = []

    table_data = [[
        Paragraph("<b>#</b>", th_style),
        Paragraph("<b>Item Description</b>", th_style),
        Paragraph("<b>Quantity</b>", th_style),
        Paragraph("<b>Unit Price</b>", th_style),
        Paragraph("<b>Total (EGP)</b>", th_style),
    ]]

    subtotal = 0.0
    for idx, p in enumerate(products, 1):
        name = p.get("title") or p.get("name") or "Product"
        qty = p.get("quantity") or p.get("qty") or 1
        price = float(p.get("price") or 0.0)
        item_total = qty * price
        subtotal += item_total

        table_data.append([
            Paragraph(str(idx), td_style),
            Paragraph(reshape_text(name), td_style),
            Paragraph(str(qty), td_style),
            Paragraph(f"{price:.2f}", td_style),
            Paragraph(f"{item_total:.2f}", td_style),
        ])

    t_items = Table(table_data, colWidths=[12 * mm, 85 * mm, 25 * mm, 28 * mm, 30 * mm])
    t_items.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#5A55D6")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("ALIGN", (1, 1), (1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F9FAFB")]),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(t_items)
    elements.append(Spacer(1, 6 * mm))

    # Totals Row
    grand_total = float(sale.get("total_amount") or subtotal)
    method = sale.get("method") or "Cash"

    totals_table = [
        ["Subtotal:", f"{subtotal:.2f} EGP"],
        ["Payment Method:", method],
        ["Grand Total:", f"{grand_total:.2f} EGP"],
    ]
    t_totals = Table(totals_table, colWidths=[140 * mm, 40 * mm])
    t_totals.setStyle(TableStyle([
        ("ALIGN", (0, 0), (0, -1), "RIGHT"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (0, 0), (-1, -1), DEFAULT_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTNAME", (0, 2), (-1, 2), DEFAULT_FONT),
        ("FONTSIZE", (0, 2), (-1, 2), 12),
        ("TEXTCOLOR", (0, 2), (-1, 2), colors.HexColor("#5A55D6")),
        ("LINEABOVE", (0, 2), (-1, 2), 1, colors.HexColor("#5A55D6")),
    ]))
    elements.append(t_totals)
    elements.append(Spacer(1, 10 * mm))

    # QR Code & Footer
    qr_payload = f"Seller:{store_name}|TaxID:{store_tax_id}|Date:{date_str}|Total:{grand_total}"
    qr_img = generate_qr_image(qr_payload)
    if qr_img:
        elements.append(qr_img)

    doc.build(elements)
    buf.seek(0)
    return buf.getvalue()


async def generate_thermal_receipt_pdf(sale: Dict[str, Any], store: Dict[str, Any]) -> bytes:
    """Async wrapper to generate 80mm thermal receipt in threadpool."""
    return await asyncio.to_thread(_build_thermal_receipt_sync, sale, store)


async def generate_a4_invoice_pdf(sale: Dict[str, Any], store: Dict[str, Any]) -> bytes:
    """Async wrapper to generate A4 invoice in threadpool."""
    return await asyncio.to_thread(_build_a4_invoice_sync, sale, store)
