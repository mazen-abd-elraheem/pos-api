"""
services/inventory_service.py â€” Inventory data service
Routes through HTTP API in API mode, falls back to direct SQLAlchemy.
"""
from datetime import datetime, date
import logging

logger = logging.getLogger(__name__)


def _is_api_mode():
    """Check if we should use API mode."""
    try:
        from controller._base import DATA_SOURCE_MODE
        return DATA_SOURCE_MODE == 'api'
    except Exception:
        return False


def _get_api_client():
    """Get the singleton API client."""
    from network.api_client import get_api_client
    return get_api_client()


# -----------------------
# Daily snapshot creation
# -----------------------

def check_and_create_daily_snapshot():
    """Create automated daily snapshot if one doesn't exist for today."""
    if _is_api_mode():
        try:
            result = _get_api_client()._request('POST', '/api/inventory/snapshot')
            logger.info(f"API snapshot: {result}")
            return
        except Exception as e:
            logger.error(f"API snapshot creation failed: {e}")
            return

    # Direct DB fallback
    from models.models import InventorySnapshot, InventorySnapshotItem, Product
    from controller import get_db

    today_str = datetime.now().strftime("%Y-%m-%d")
    with get_db() as db:
        existing = db.query(InventorySnapshot).filter_by(date=today_str, type='auto_daily').first()
        if existing:
            logger.info(f"Daily snapshot for {today_str} already exists.")
            return

        logger.info(f"Creating automated daily snapshot for {today_str}...")
        snapshot = InventorySnapshot(
            date=today_str, type='auto_daily',
            created_at=datetime.now(), note="Automated daily inventory check."
        )
        db.add(snapshot)
        db.flush()

        products = db.query(Product).all()
        for p in products:
            db.add(InventorySnapshotItem(
                snapshot_id=snapshot.id, product_id=p.id,
                product_name=p.title, quantity=p.stock or 0,
                cost=0, price=p.price or 0,
            ))

        db.commit()
        logger.info(f"Snapshot created with {len(products)} items.")


# -----------------------
# Snapshot retrieval
# -----------------------

def get_snapshot_by_date(date_str):
    """Retrieve snapshot items for a specific date.
    Returns: (snapshot_info, items_list)
    """
    if _is_api_mode():
        try:
            result = _get_api_client().get_inventory_snapshot(date_str)
            if result:
                snapshot = result.get('snapshot')
                items = result.get('items', [])
                return snapshot, items
            return None, []
        except Exception as e:
            logger.error(f"API get_snapshot_by_date failed: {e}")
            return None, []

    # Direct DB fallback
    from models.models import InventorySnapshot, InventorySnapshotItem
    from controller import get_db

    with get_db() as db:
        snapshot = db.query(InventorySnapshot).filter_by(date=date_str).first()
        if not snapshot:
            return None, []

        items = db.query(InventorySnapshotItem).filter_by(snapshot_id=snapshot.id).all()
        items_data = [{
            "product_name": i.product_name,
            "quantity": i.quantity,
            "price": i.price,
            "is_deleted": i.product_id is None,
        } for i in items]
        return snapshot, items_data


def get_available_snapshot_dates():
    """Returns list of dates that have snapshots."""
    # No API endpoint needed â€” not used in the inventory page
    from models.models import InventorySnapshot
    from controller import get_db

    with get_db() as db:
        snapshots = db.query(InventorySnapshot.date).distinct().order_by(InventorySnapshot.date.desc()).all()
        return [s[0] for s in snapshots]


# -----------------------
# Live inventory data
# -----------------------

def get_live_inventory_data():
    """Retrieve current live inventory items as snapshot format."""
    if _is_api_mode():
        try:
            result = _get_api_client().get_live_inventory()
            if result:
                snapshot = result.get('snapshot')
                items = result.get('items', [])
                return snapshot, items
            return None, []
        except Exception as e:
            logger.error(f"API get_live_inventory failed: {e}")
            return None, []

    # Direct DB fallback
    from controller import get_products, get_db
    from models.models import InventorySnapshot, InventorySnapshotItem

    products = get_products()
    items_data = [{
        "product_name": p.title,
        "quantity": p.stock if p.stock else 0,
        "price": p.price if p.price else 0,
        "is_deleted": False,
    } for p in products]

    with get_db() as db:
        today_str = datetime.now().strftime("%Y-%m-%d")
        snapshot = db.query(InventorySnapshot).filter_by(date=today_str).first()
        if snapshot:
            deleted_items = db.query(InventorySnapshotItem).filter_by(
                snapshot_id=snapshot.id, product_id=None
            ).all()
            for d in deleted_items:
                if not any(item['product_name'] == d.product_name for item in items_data):
                    items_data.append({
                        "product_name": d.product_name,
                        "quantity": 0,
                        "price": d.price,
                        "is_deleted": True,
                    })

        snapshot_info = type('MockSnapshot', (), {
            'date': today_str, 'type': 'live', 'note': 'Live inventory data'
        })
        return snapshot_info, items_data


# -----------------------
# Stock movements (entries + exits)
# -----------------------

def get_stock_movements_by_range(start_date, end_date):
    """Retrieve all stock entries and exits between two dates."""
    if _is_api_mode():
        try:
            result = _get_api_client().get_stock_movements(start_date, end_date)
            if result:
                entries = result.get('entries', [])
                exits = result.get('exits', [])
                # Ensure date fields are strings
                for e in entries:
                    if not isinstance(e.get('date'), str):
                        e['date'] = str(e.get('date', ''))
                for ex in exits:
                    if not isinstance(ex.get('date'), str):
                        ex['date'] = str(ex.get('date', ''))
                return entries, exits
            return [], []
        except Exception as e:
            logger.error(f"API get_stock_movements failed: {e}")
            return [], []

    # Direct DB fallback
    from models.models import StockEntry, StockExit
    from controller import get_db

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)

    with get_db() as db:
        entries = db.query(StockEntry).filter(
            StockEntry.entry_date >= start_dt, StockEntry.entry_date <= end_dt
        ).all()
        exits = db.query(StockExit).filter(
            StockExit.exit_date >= start_dt, StockExit.exit_date <= end_dt
        ).all()

        entry_list = [{
            "product_name": e.name,
            "quantity": e.quantity,
            "date": e.entry_date.strftime("%Y-%m-%d %H:%M"),
        } for e in entries]

        exit_list = [{
            "product_name": ex.name,
            "quantity": ex.quantity,
            "date": ex.exit_date.strftime("%Y-%m-%d %H:%M"),
        } for ex in exits]

        return entry_list, exit_list


# -----------------------
# Deleted products from snapshots
# -----------------------

def get_deleted_from_snapshots(start_date, end_date):
    """Get products that appear as deleted in any snapshot within range."""
    if _is_api_mode():
        try:
            result = _get_api_client().get_deleted_products(start_date, end_date)
            if result:
                return result.get('deleted', [])
            return []
        except Exception as e:
            logger.error(f"API get_deleted_from_snapshots failed: {e}")
            return []

    # Direct DB fallback
    from models.models import InventorySnapshot, InventorySnapshotItem
    from controller import get_db

    with get_db() as db:
        snapshots = db.query(InventorySnapshot).filter(
            InventorySnapshot.date >= start_date,
            InventorySnapshot.date <= end_date,
        ).all()

        if not snapshots:
            return []

        snapshot_ids = [s.id for s in snapshots]
        deleted_items = db.query(InventorySnapshotItem).filter(
            InventorySnapshotItem.snapshot_id.in_(snapshot_ids),
            InventorySnapshotItem.product_id == None,
        ).all()

        seen = set()
        result = []
        for item in deleted_items:
            if item.product_name not in seen:
                result.append({
                    "product_name": item.product_name,
                    "last_quantity": item.quantity,
                    "price": item.price,
                    "snapshot_item_id": item.id,
                })
                seen.add(item.product_name)

        return result
