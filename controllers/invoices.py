"""
Invoices & Receipts Router — /api/invoices
Serves downloadable/printable 80mm thermal receipts and A4 invoices.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
import io

from core.database import fetch_one
from auth.security import get_current_user
from services.pdf_service import generate_thermal_receipt_pdf, generate_a4_invoice_pdf

router = APIRouter()


async def _get_store_settings() -> dict:
    """Fetch store metadata for receipt/invoice header."""
    store = await fetch_one("SELECT * FROM store_settings LIMIT 1")
    if not store:
        # Fallback to defaults
        return {
            "store_name": "SkyPOS Store",
            "store_address": "Main Street",
            "store_phone": "+20 100 000 0000",
            "tax_number": "EG-123456789",
        }
    return store


@router.get("/sales/{sale_id}/receipt")
async def get_sale_receipt_pdf(
    sale_id: int,
    user_data: dict = Depends(get_current_user),
):
    """GET /api/invoices/sales/{sale_id}/receipt — 80mm thermal receipt stream."""
    sale = await fetch_one("SELECT * FROM sales WHERE id = %s", [sale_id])
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    store = await _get_store_settings()
    pdf_bytes = await generate_thermal_receipt_pdf(sale, store)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename=receipt-{sale.get('order_number', sale_id)}.pdf"
        },
    )


@router.get("/sales/{sale_id}/invoice")
async def get_sale_invoice_pdf(
    sale_id: int,
    user_data: dict = Depends(get_current_user),
):
    """GET /api/invoices/sales/{sale_id}/invoice — A4 formal invoice PDF stream."""
    sale = await fetch_one("SELECT * FROM sales WHERE id = %s", [sale_id])
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    store = await _get_store_settings()
    pdf_bytes = await generate_a4_invoice_pdf(sale, store)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename=invoice-{sale.get('order_number', sale_id)}.pdf"
        },
    )


@router.get("/bills/{bill_id}/receipt")
async def get_bill_receipt_pdf(
    bill_id: int,
    user_data: dict = Depends(get_current_user),
):
    """GET /api/invoices/bills/{bill_id}/receipt — 80mm thermal receipt for table bill."""
    bill = await fetch_one("SELECT * FROM bills WHERE id = %s", [bill_id])
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")

    # Map bill fields to sale format for receipt rendering
    sale_repr = {
        "id": bill.get("id"),
        "order_number": f"BILL-{bill.get('id')}",
        "date": bill.get("created_at"),
        "products": bill.get("items") or [],
        "total_amount": bill.get("total_amount") or bill.get("total") or 0.0,
        "method": bill.get("payment_method") or "Cash",
        "employee": bill.get("cashier") or user_data.get("username", "Staff"),
        "customer": f"Table #{bill.get('table_id', '')}",
    }

    store = await _get_store_settings()
    pdf_bytes = await generate_thermal_receipt_pdf(sale_repr, store)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename=bill-receipt-{bill_id}.pdf"
        },
    )
