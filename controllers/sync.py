"""
Sync Router — /api/sync
Offline-first sync: client pushes queued operations, server processes and ACKs.
Pull endpoint returns server changes since last sync.
"""
import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from core.database import fetch_all, fetch_one, execute, execute_transaction
from auth.security import get_current_user
from schemas.sync import SyncPayload, SyncAck, SyncResult, SyncPullResponse, SyncOperationType, SyncEntityType

router = APIRouter()


@router.post("/push")
async def push_sync(payload: SyncPayload, user: dict = Depends(get_current_user)):
    """
    POST /api/sync/push
    Device sends batch of queued offline operations.
    Server processes each idempotently and returns ACK.
    """
    results: list[SyncResult] = []
    processed = 0
    failed = 0

    for op in payload.operations:
        try:
            server_id = await _process_operation(op, user)
            results.append(SyncResult(
                local_id=op.local_id,
                idempotency_key=op.idempotency_key,
                success=True,
                server_id=server_id,
            ))
            processed += 1
        except Exception as e:
            results.append(SyncResult(
                local_id=op.local_id,
                idempotency_key=op.idempotency_key,
                success=False,
                error=str(e),
            ))
            failed += 1

    return SyncAck(
        processed=processed,
        failed=failed,
        results=results,
        server_time=datetime.now().isoformat(),
    )


async def _process_operation(op, user: dict) -> int | None:
    """Process a single sync operation idempotently."""

    if op.entity == SyncEntityType.SALE:
        return await _sync_sale(op, user)

    if op.entity == SyncEntityType.ORDER_ITEM:
        return await _sync_order_item(op, user)

    if op.entity == SyncEntityType.TABLE_ORDER:
        return await _sync_table_order(op, user)

    if op.entity == SyncEntityType.INVENTORY_MOVEMENT:
        return await _sync_inventory_movement(op, user)

    raise ValueError(f"Unknown entity: {op.entity}")


async def _sync_sale(op, user: dict) -> int | None:
    """Idempotent sale creation: check idempotency_key first."""
    key = op.idempotency_key

    # Check if already synced
    existing = await fetch_one(
        "SELECT id FROM sales WHERE idempotency_key = %s", [key]
    )
    if existing:
        return existing["id"]  # Already processed, return server ID

    if op.operation == SyncOperationType.CREATE:
        p = op.payload
        products_json = json.dumps(p.get("items", []))
        sale_id = await execute(
            "INSERT INTO sales (order_number, date, products, total_items, total_amount, "
            "customer, employee, method, idempotency_key, tenant_id, branch_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                p.get("order_number"),
                p.get("created_at_local", datetime.now().isoformat()),
                products_json,
                p.get("total_items", 0),
                p.get("total_amount", 0.0),
                p.get("customer_name"),
                p.get("employee"),
                p.get("payment_method", "cash"),
                key,
                user.get("tenant_id"),
                user.get("branch_id"),
            ],
        )
        return sale_id

    return None


async def _sync_order_item(op, user: dict) -> int | None:
    """Sync table order item changes."""
    p = op.payload
    if op.operation == SyncOperationType.CREATE:
        item_id = await execute(
            "INSERT INTO table_order_items (table_id, product_id, product_name, quantity, "
            "price, notes, sent_to_kitchen, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())",
            [p.get("table_id"), p.get("product_id"), p.get("product_name"),
             p.get("quantity", 1), p.get("price", 0), p.get("notes"), 0],
        )
        return item_id
    if op.operation == SyncOperationType.UPDATE:
        item_id = p.get("id")
        if item_id:
            await execute(
                "UPDATE table_order_items SET quantity = %s, notes = %s WHERE id = %s",
                [p.get("quantity"), p.get("notes"), item_id],
            )
        return item_id
    return None


async def _sync_table_order(op, user: dict) -> int | None:
    """Sync table status updates (sent to kitchen, done)."""
    p = op.payload
    table_id = p.get("table_id")
    if op.operation == SyncOperationType.UPDATE and table_id:
        await execute(
            "UPDATE tables SET status = %s WHERE id = %s",
            [p.get("status", "occupied"), table_id],
        )
        return table_id
    return None


async def _sync_inventory_movement(op, user: dict) -> int | None:
    """Sync inventory ledger entry."""
    p = op.payload
    if op.operation == SyncOperationType.CREATE:
        mov_id = await execute(
            "INSERT INTO inventory_movements (tenant_id, branch_id, product_id, movement_type, "
            "quantity, reference_type, reference_id, idempotency_key, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                user.get("tenant_id"),
                user.get("branch_id"),
                p.get("product_id"),
                p.get("movement_type", "sale"),
                p.get("quantity", 0),
                p.get("reference_type"),
                p.get("reference_id"),
                op.idempotency_key,
                p.get("created_at_local", datetime.now().isoformat()),
            ],
        )
        return mov_id
    return None


@router.get("/pull")
async def pull_sync(
    since: str,
    user: dict = Depends(get_current_user),
):
    """
    GET /api/sync/pull?since=<ISO_timestamp>
    Returns products and categories updated since last sync.
    Device uses this to refresh its local cache.
    """
    tenant_id = user.get("tenant_id")

    try:
        since_dt = datetime.fromisoformat(since)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid 'since' timestamp format")

    products = await fetch_all(
        "SELECT id, title, price, cost_price, barcode, stock, image, category_id, category "
        "FROM products WHERE tenant_id = %s AND updated_at > %s ORDER BY id",
        [tenant_id, since_dt],
    )
    categories = await fetch_all(
        "SELECT id, name, icon, image FROM categories WHERE tenant_id = %s ORDER BY id",
        [tenant_id],
    )

    return SyncPullResponse(
        since=since,
        products_updated=products,
        categories_updated=categories,
        server_time=datetime.now().isoformat(),
    )
