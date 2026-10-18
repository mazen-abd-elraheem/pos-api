"""
services/voice/tools.py — POS tool functions + dispatch + permissions.
"""
from __future__ import annotations
import logging
from datetime import datetime
logger = logging.getLogger(__name__)

# Navigation & Cart callbacks (set by UI page)
_nav_callback = None
_add_to_cart_callback = None
_view_cart_callback = None
_clear_cart_callback = None
_checkout_callback = None

# ── Table Tools ──

def _tool_list_tables() -> dict:
    try:
        from controller.tables_mgr import get_all_tables_with_status
        tables = get_all_tables_with_status()
        summary = [{"table_number": t["number"], "status": t["status"],
                     "total_items": t["total_items"], "pending_items": t["pending_items"],
                     "sent_items": t["sent_items"], "total_amount": round(t["total_amount"], 2)}
                    for t in tables]
        return {"success": True, "tables": summary, "count": len(summary)}
    except Exception as e:
        logger.error(f"list_tables error: {e}")
        return {"success": False, "error": str(e)}

def _tool_get_table_order(table_number: int) -> dict:
    try:
        from controller.tables_mgr import get_all_tables_with_status
        tables = get_all_tables_with_status()
        table = next((t for t in tables if t["number"] == table_number), None)
        if not table:
            return {"success": False, "error": f"Table {table_number} not found"}
        items = [{"product_name": i["product_name"], "quantity": i["quantity"],
                  "price": i["price"], "total": round(i["price"] * i["quantity"], 2),
                  "sent_to_kitchen": i["sent_to_kitchen"], "notes": i.get("notes", "")}
                 for i in table["items"]]
        return {"success": True, "table_number": table_number, "status": table["status"],
                "items": items, "total_amount": round(table["total_amount"], 2)}
    except Exception as e:
        logger.error(f"get_table_order error: {e}")
        return {"success": False, "error": str(e)}

def _find_product(product_name: str):
    """Helper: fuzzy-search product by name. Returns product object or None."""
    from controller.products import get_products
    products = get_products()
    search_lower = product_name.lower().strip()
    for p in products:
        p_title = (p.title if hasattr(p, 'title') else p.get('title', '')).lower()
        if search_lower in p_title or p_title in search_lower:
            return p, products
    for p in products:
        p_title = (p.title if hasattr(p, 'title') else p.get('title', '')).lower()
        if any(w in p_title for w in search_lower.split() if len(w) > 2):
            return p, products
    return None, products

def _prod_attr(p, attr, default=''):
    return getattr(p, attr, None) if hasattr(p, attr) else p.get(attr, default)

def _tool_add_item_to_table(table_number: int, product_name: str,
                            quantity: int = 1, notes: str = "") -> dict:
    try:
        from controller.tables_mgr import get_all_tables_with_status, add_item_to_table
        tables = get_all_tables_with_status()
        table = next((t for t in tables if t["number"] == table_number), None)
        if not table:
            return {"success": False, "error": f"Table {table_number} not found"}
        product, products = _find_product(product_name)
        if not product:
            available = [_prod_attr(p, 'title') for p in products[:20]]
            return {"success": False, "error": f"Product '{product_name}' not found",
                    "available_products": available}
        p_id = _prod_attr(product, 'id')
        p_title = _prod_attr(product, 'title')
        p_price = float(_prod_attr(product, 'price', 0))
        ok, msg, item = add_item_to_table(table["id"], p_id, p_title, p_price,
                                          quantity=quantity, notes=notes or None)
        if ok:
            return {"success": True, "message": f"Added {quantity}× {p_title} to table {table_number}",
                    "product": p_title, "quantity": quantity, "price_each": p_price,
                    "total": round(p_price * quantity, 2)}
        return {"success": False, "error": msg}
    except Exception as e:
        logger.error(f"add_item_to_table error: {e}")
        return {"success": False, "error": str(e)}

def _tool_remove_item(table_number: int, product_name: str) -> dict:
    try:
        from controller.tables_mgr import get_all_tables_with_status, remove_order_item
        tables = get_all_tables_with_status()
        table = next((t for t in tables if t["number"] == table_number), None)
        if not table:
            return {"success": False, "error": f"Table {table_number} not found"}
        search_lower = product_name.lower().strip()
        target = next((i for i in table["items"] if search_lower in i["product_name"].lower()), None)
        if not target:
            return {"success": False, "error": f"'{product_name}' not found on table {table_number}",
                    "current_items": [i["product_name"] for i in table["items"]]}
        ok, msg = remove_order_item(target["id"], "admin")
        if ok:
            return {"success": True, "message": f"Removed {target['product_name']} from table {table_number}"}
        return {"success": False, "error": msg}
    except Exception as e:
        logger.error(f"remove_item error: {e}")
        return {"success": False, "error": str(e)}

def _tool_send_to_kitchen(table_number: int) -> dict:
    try:
        from controller.tables_mgr import get_all_tables_with_status, send_items_to_kitchen
        tables = get_all_tables_with_status()
        table = next((t for t in tables if t["number"] == table_number), None)
        if not table:
            return {"success": False, "error": f"Table {table_number} not found"}
        ok, msg, tickets = send_items_to_kitchen(table["id"])
        if ok:
            return {"success": True, "message": msg, "items_sent": len(tickets),
                    "ticket_items": [{"name": t["name"], "qty": t["quantity"]} for t in tickets]}
        return {"success": False, "error": msg}
    except Exception as e:
        logger.error(f"send_to_kitchen error: {e}")
        return {"success": False, "error": str(e)}

def _tool_close_table(table_number: int, payment_method: str = "Cash") -> dict:
    try:
        from controller.tables_mgr import get_all_tables_with_status, close_table_bill
        tables = get_all_tables_with_status()
        table = next((t for t in tables if t["number"] == table_number), None)
        if not table:
            return {"success": False, "error": f"Table {table_number} not found"}
        if table["total_items"] == 0:
            return {"success": False, "error": f"Table {table_number} has no items"}
        ok, msg, receipt = close_table_bill(table["id"], payment_method)
        if ok:
            return {"success": True, "message": f"Table {table_number} closed successfully",
                    "total": receipt.get("total", 0), "method": payment_method, "receipt": receipt}
        return {"success": False, "error": msg}
    except Exception as e:
        logger.error(f"close_table error: {e}")
        return {"success": False, "error": str(e)}

# ── Product & Category Tools ──

def _tool_search_products(query: str) -> dict:
    try:
        from controller.products import get_products
        products = get_products()
        q = query.lower().strip()
        results = []
        for p in products:
            title = _prod_attr(p, 'title')
            if q in title.lower():
                results.append({"name": title, "price": float(_prod_attr(p, 'price', 0)),
                                "category": _prod_attr(p, 'category'), "stock": int(_prod_attr(p, 'stock', 0))})
        if not results:
            for p in products[:15]:
                title = _prod_attr(p, 'title')
                results.append({"name": title, "price": float(_prod_attr(p, 'price', 0)),
                                "category": _prod_attr(p, 'category')})
        return {"success": True, "results": results[:15], "count": len(results)}
    except Exception as e:
        logger.error(f"search_products error: {e}")
        return {"success": False, "error": str(e)}

def _tool_list_categories() -> dict:
    try:
        from controller.categories import get_categories
        cats = get_categories()
        names = []
        for c in cats:
            if isinstance(c, str): name = c
            elif hasattr(c, 'name'): name = c.name
            elif isinstance(c, dict): name = c.get('name', '')
            else: name = str(c)
            if name: names.append(name)
        return {"success": True, "categories": names, "count": len(names)}
    except Exception as e:
        logger.error(f"list_categories error: {e}")
        return {"success": False, "error": str(e)}

def _tool_get_products_by_category(category_name: str) -> dict:
    try:
        from controller.products import get_products
        products = get_products()
        cat_lower = category_name.lower().strip()
        results = []
        for p in products:
            cat = str(_prod_attr(p, 'category', '')).lower()
            if cat_lower in cat or cat in cat_lower:
                results.append({"name": _prod_attr(p, 'title', _prod_attr(p, 'name', '')),
                                "price": float(_prod_attr(p, 'price', 0) or 0)})
        return {"success": True, "products": results, "count": len(results), "category": category_name}
    except Exception as e:
        logger.error(f"get_products_by_category error: {e}")
        return {"success": False, "error": str(e)}

# ── Navigation & Cart Tools ──

def _tool_navigate(page_name: str) -> dict:
    valid_pages = {
        "home": "home", "checkout": "home", "cart": "home", "main": "home",
        "products": "products", "inventory": "inventory", "tables": "tables",
        "reports": "reports", "categories": "categories", "customers": "customers",
        "kitchen": "kitchen_display", "recipes": "recipes", "ingredients": "ingredients",
        "shelves": "shelves_dashboard", "scanner": "scanner",
    }
    target = valid_pages.get(page_name.lower().strip())
    if not target:
        return {"success": False, "error": f"Unknown page '{page_name}'",
                "available_pages": list(valid_pages.keys())}
    if _nav_callback:
        try:
            _nav_callback(target)
            return {"success": True, "message": f"Navigated to {target}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    return {"success": False, "error": "Navigation not available"}

def _tool_add_to_cart(product_name: str, quantity: int = 1) -> dict:
    try:
        product, products = _find_product(product_name)
        if not product:
            available = [_prod_attr(p, 'title') for p in products[:20]]
            return {"success": False, "error": f"Product '{product_name}' not found",
                    "available_products": available}
        p_title = _prod_attr(product, 'title')
        p_price = float(_prod_attr(product, 'price', 0))
        p_id = _prod_attr(product, 'id')
        if _add_to_cart_callback:
            return _add_to_cart_callback(p_id, p_title, p_price, quantity)
        return {"success": True, "message": f"Added {quantity}× {p_title} to cart",
                "product": p_title, "quantity": quantity,
                "price_each": p_price, "total": round(p_price * quantity, 2)}
    except Exception as e:
        logger.error(f"add_to_cart error: {e}")
        return {"success": False, "error": str(e)}

def _tool_view_cart() -> dict:
    if _view_cart_callback:
        try: return _view_cart_callback()
        except Exception as e:
            logger.error(f"view_cart error: {e}")
            return {"success": False, "error": str(e)}
    return {"success": False, "error": "Cart not available"}

def _tool_clear_cart() -> dict:
    if _clear_cart_callback:
        try: return _clear_cart_callback()
        except Exception as e:
            logger.error(f"clear_cart error: {e}")
            return {"success": False, "error": str(e)}
    return {"success": False, "error": "Cart not available"}

def _tool_start_checkout() -> dict:
    if _checkout_callback:
        try: return _checkout_callback()
        except Exception as e:
            logger.error(f"start_checkout error: {e}")
            return {"success": False, "error": str(e)}
    return {"success": False, "error": "Checkout not available"}

# ── Info & Availability Tools ──

def _tool_check_availability(product_name: str) -> dict:
    try:
        from controller.products import get_products
        products = get_products()
        search_lower = product_name.lower().strip()
        for p in products:
            title = _prod_attr(p, 'title', '').lower()
            if search_lower in title or title in search_lower:
                stock = int(_prod_attr(p, 'stock', 0))
                return {"success": True, "product": _prod_attr(p, 'title'),
                        "available": stock > 0, "price": float(_prod_attr(p, 'price', 0)),
                        "status": "Available" if stock > 0 else "Not Available"}
        return {"success": False, "error": f"Product '{product_name}' not found"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _tool_get_product_ingredients(product_name: str) -> dict:
    try:
        from controller.products import get_products
        from controller.ingredients import get_product_recipe
        product, _ = _find_product(product_name)
        if not product:
            return {"success": False, "error": f"Product '{product_name}' not found"}
        p_id = _prod_attr(product, 'id')
        p_title = _prod_attr(product, 'title')
        recipe = get_product_recipe(p_id)
        if not recipe:
            return {"success": True, "product": p_title, "ingredients": [], "message": "No recipe defined"}
        ingredients = [{"name": item.get("ingredient_name", ""), "quantity": item.get("quantity_needed", 0),
                        "unit": item.get("unit", "")} for item in recipe]
        return {"success": True, "product": p_title, "ingredients": ingredients, "count": len(ingredients)}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _tool_get_active_discounts() -> dict:
    try:
        from controller._base import get_db
        from models.models import Discount
        with get_db() as db:
            now = datetime.now()
            discounts = db.query(Discount).filter(Discount.active == True).all()
            active = [{"name": d.name, "type": d.discount_type, "value": d.value,
                        "applies_to": d.applicable_to or "all", "category": d.category or ""}
                       for d in discounts if not (d.end_date and d.end_date < now)]
            if not active:
                return {"success": True, "discounts": [], "message": "No active discounts"}
            return {"success": True, "discounts": active, "count": len(active)}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _tool_get_today_sales() -> dict:
    try:
        from controller.sales import get_sales
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        sales = get_sales(limit=500, date_from=today_start)
        if not sales:
            return {"success": True, "total_sales": 0, "total_revenue": 0, "message": "No sales today yet"}
        total_revenue = sum(float(s.total_amount or 0) for s in sales)
        product_counts = {}
        for s in sales:
            if s.products:
                for item in (s.products if isinstance(s.products, list) else []):
                    if isinstance(item, dict):
                        name = item.get('name', 'Unknown')
                        product_counts[name] = product_counts.get(name, 0) + int(item.get('quantity', 1))
        top = sorted(product_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        return {"success": True, "total_sales": len(sales), "total_revenue": round(total_revenue, 2),
                "top_products": [{"name": n, "qty": q} for n, q in top]}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _tool_get_store_info() -> dict:
    try:
        from controller.settings import get_store_settings
        s = get_store_settings()
        if not s:
            return {"success": False, "error": "Store settings not configured"}
        return {"success": True, "store_name": getattr(s, 'store_name', '') or '',
                "address": getattr(s, 'address', '') or '', "phone": getattr(s, 'phone', '') or '',
                "business_type": getattr(s, 'business_type', '') or '',
                "vat_percentage": getattr(s, 'vat_percentage', 0) or 0}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ── Dispatch & Permissions ──

TOOL_DISPATCH = {
    "list_tables": _tool_list_tables, "get_table_order": _tool_get_table_order,
    "add_item_to_table": _tool_add_item_to_table, "remove_item_from_table": _tool_remove_item,
    "send_to_kitchen": _tool_send_to_kitchen, "close_table": _tool_close_table,
    "search_products": _tool_search_products, "list_categories": _tool_list_categories,
    "get_products_by_category": _tool_get_products_by_category,
    "navigate_to_page": _tool_navigate, "add_to_cart": _tool_add_to_cart,
    "view_cart": _tool_view_cart, "clear_cart": _tool_clear_cart,
    "start_checkout": _tool_start_checkout, "check_availability": _tool_check_availability,
    "get_product_ingredients": _tool_get_product_ingredients,
    "get_active_discounts": _tool_get_active_discounts,
    "get_today_sales": _tool_get_today_sales, "get_store_info": _tool_get_store_info,
}

TOOL_PERMISSIONS = {
    "list_tables": "view_tables", "get_table_order": "view_tables",
    "add_item_to_table": "view_tables", "remove_item_from_table": "view_tables",
    "send_to_kitchen": "view_tables", "close_table": "view_tables",
    "search_products": "view_sales", "list_categories": "view_sales",
    "get_products_by_category": "view_sales", "navigate_to_page": "view_sales",
    "add_to_cart": "view_sales", "view_cart": "view_sales",
    "clear_cart": "view_sales", "start_checkout": "view_sales",
    "check_availability": "view_sales", "get_product_ingredients": "view_sales",
    "get_active_discounts": "view_sales", "get_today_sales": "view_sales",
    "get_store_info": "view_sales",
}
