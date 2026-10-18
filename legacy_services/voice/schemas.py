"""
services/voice/schemas.py — Gemini function-calling tool declarations (JSON schemas).

These schemas tell the LLM what tools are available and what parameters they accept.
"""
from __future__ import annotations


def build_tool_declarations() -> list[dict]:
    """Build the Gemini function-calling tool schema."""
    return [
        {
            "name": "list_tables",
            "description": "Get all restaurant tables with their current status (free/occupied), item counts, and totals.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "get_table_order",
            "description": "Get the current order items on a specific table including prices, quantities, and kitchen status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_number": {"type": "integer", "description": "The table number to check"},
                },
                "required": ["table_number"],
            },
        },
        {
            "name": "add_item_to_table",
            "description": "Add a product/menu item to a table's order. If the table is free it will automatically become occupied.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_number": {"type": "integer", "description": "The table number to add the item to"},
                    "product_name": {"type": "string", "description": "Name of the product/menu item to add"},
                    "quantity": {"type": "integer", "description": "How many units to add (default 1)"},
                    "notes": {"type": "string", "description": "Special notes (e.g. 'no sugar', 'extra cheese')"},
                },
                "required": ["table_number", "product_name"],
            },
        },
        {
            "name": "remove_item_from_table",
            "description": "Remove a product from a table's order.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_number": {"type": "integer", "description": "The table number"},
                    "product_name": {"type": "string", "description": "Name of the product to remove"},
                },
                "required": ["table_number", "product_name"],
            },
        },
        {
            "name": "send_to_kitchen",
            "description": "Send all pending (unsent) items on a table to the kitchen for preparation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_number": {"type": "integer", "description": "The table number"},
                },
                "required": ["table_number"],
            },
        },
        {
            "name": "close_table",
            "description": "Close a table by processing payment and generating a receipt.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_number": {"type": "integer", "description": "The table number to close"},
                    "payment_method": {"type": "string", "description": "Payment method: Cash, Visa, etc. Default is Cash."},
                },
                "required": ["table_number"],
            },
        },
        {
            "name": "search_products",
            "description": "Search the menu/product catalog by name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query for product name"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "list_categories",
            "description": "List all product/menu categories.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "get_products_by_category",
            "description": "Get all products/items in a specific category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category_name": {"type": "string", "description": "Category name to filter by"},
                },
                "required": ["category_name"],
            },
        },
        {
            "name": "navigate_to_page",
            "description": "Navigate to a specific page in the POS application.",
            "parameters": {
                "type": "object",
                "properties": {
                    "page_name": {
                        "type": "string",
                        "description": "Page to navigate to. Options: home, checkout, cart, products, inventory, tables, reports, categories, customers, kitchen, recipes, ingredients, shelves, scanner",
                    },
                },
                "required": ["page_name"],
            },
        },
        {
            "name": "add_to_cart",
            "description": "Add a product to the main checkout cart on the home/sales page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name": {"type": "string", "description": "Name of the product to add to cart"},
                    "quantity": {"type": "integer", "description": "How many units to add (default 1)"},
                },
                "required": ["product_name"],
            },
        },
        {
            "name": "view_cart",
            "description": "View the current checkout cart contents.",
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "name": "clear_cart",
            "description": "Clear all items from the checkout cart.",
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "name": "start_checkout",
            "description": "Start the checkout/payment process. Opens the POS home page with the payment dialog.",
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "name": "check_availability",
            "description": "Check if a product is currently available in stock.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name": {"type": "string", "description": "Name of the product to check"},
                },
                "required": ["product_name"],
            },
        },
        {
            "name": "get_product_ingredients",
            "description": "Get the recipe and ingredients of a product.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name": {"type": "string", "description": "Name of the product"},
                },
                "required": ["product_name"],
            },
        },
        {
            "name": "get_active_discounts",
            "description": "Get all currently active discounts, offers, and promotions.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "get_today_sales",
            "description": "Get today's sales summary including total count, revenue, and top-selling products.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "get_store_info",
            "description": "Get store information like name, address, phone number, business type, and VAT.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    ]
