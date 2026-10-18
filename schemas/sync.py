"""
Sync Schemas — Offline-first sync protocol
"""
from pydantic import BaseModel
from typing import Any, Optional
from datetime import datetime
from enum import Enum


class SyncOperationType(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class SyncEntityType(str, Enum):
    SALE = "sale"
    ORDER_ITEM = "order_item"
    TABLE_ORDER = "table_order"
    INVENTORY_MOVEMENT = "inventory_movement"


class SyncOperation(BaseModel):
    """A single queued operation from the client"""
    local_id: str                       # UUID generated on device
    idempotency_key: str                # Same as local_id or custom
    operation: SyncOperationType
    entity: SyncEntityType
    payload: dict[str, Any]
    created_at_local: str               # ISO string from device clock
    device_uuid: Optional[str] = None


class SyncPayload(BaseModel):
    """Batch of operations sent by device during sync"""
    device_uuid: str
    tenant_id: int
    branch_id: Optional[int] = None
    operations: list[SyncOperation]
    last_sync_at: Optional[str] = None  # Last successful sync timestamp


class SyncResult(BaseModel):
    """Result for a single operation"""
    local_id: str
    idempotency_key: str
    success: bool
    server_id: Optional[int] = None     # Server-assigned ID
    error: Optional[str] = None


class SyncAck(BaseModel):
    """Server response after processing sync batch"""
    processed: int
    failed: int
    results: list[SyncResult]
    server_time: str                    # Server timestamp for next sync reference


class SyncPullResponse(BaseModel):
    """Server pushes changes that device missed"""
    since: str
    products_updated: list[dict[str, Any]] = []
    categories_updated: list[dict[str, Any]] = []
    has_more: bool = False
    server_time: str
