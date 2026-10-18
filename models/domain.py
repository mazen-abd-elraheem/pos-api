from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import (
    Column, String, Integer, Float, DateTime, JSON, ForeignKey, Text,
    UniqueConstraint, Boolean, Index
)
from sqlalchemy.sql import func
from datetime import datetime

Base = declarative_base()


# ===== MULTI-TENANT SAAS MODEL =====

class Tenant(Base):
    """
    Represents a client/organization in the SaaS system.
    Each tenant is a separate business (Restaurant A, Cafe B, etc.)
    Master Admin (developer) can see all tenants.
    """
    __tablename__ = "tenants"
    
    id = Column(Integer, primary_key=True)
    
    # Business Information
    name = Column(String(100), nullable=False)  # "Restaurant El-Masry"
    slug = Column(String(50), unique=True)  # URL-safe identifier: "restaurant-el-masry"
    business_type = Column(String(50))  # 'restaurant', 'cafe', 'supermarket', 'barber', 'pharmacy'
    
    # Contact Information
    owner_name = Column(String(100))
    owner_email = Column(String(100))
    owner_phone = Column(String(20))
    address = Column(String(200))
    city = Column(String(50))
    
    # Subscription & Billing
    plan = Column(String(20), default="basic")  # 'free', 'basic', 'pro', 'enterprise'
    subscription_start = Column(DateTime, server_default=func.now())
    subscription_end = Column(DateTime)
    monthly_fee = Column(Float, default=0)
    is_active = Column(Boolean, default=True)  # True=active, False=suspended
    
    # Branding
    logo_path = Column(String(200))
    primary_color = Column(String(20), default="#1976D2")
    
    # Metadata
    created_at = Column(DateTime, server_default=func.now())
    created_by = Column(Integer)  # Master Admin who created this tenant
    notes = Column(String(500))
    
    # Note: tenant_id FK columns removed — multi-tenant not deployed yet


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    
    # Cascading visibility: Manager can see their subordinates' activities
    manager_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    
    name = Column(String(32))
    role = Column(String(100))  # 'master_admin', 'admin', 'manager', 'cashier', 'user'
    username = Column(String(20), unique=True, index=True)
    password = Column(String(100))
    email = Column(String(100))
    phone = Column(String(20))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    last_login = Column(DateTime)
    device_id = Column(Integer, ForeignKey('devices.id'))  # Which device this user belongs to
    
    # Relationships
    manager = relationship("User", remote_side=[id], backref="subordinates")
    permissions = relationship("UserPermission", back_populates="user", foreign_keys="UserPermission.user_id", cascade="all, delete")
    device = relationship("Device", back_populates="users")

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    
    title = Column(String(100))
    price = Column(Float)
    cost_price = Column(Float, default=0.0)
    regular_price = Column(Float, default=0.0)
    sale_price = Column(Float, default=0.0)
    margin = Column(Float, default=0.0)
    barcode = Column(String(30), index=True)
    stock = Column(Integer)
    image = Column(String(100), default="image.png")
    sale_quantity = Column(Integer, nullable=True)
    category_id = Column(Integer, ForeignKey("categories.id"))
    category = Column(String(50), index=True)  # Indexed for category filter queries

    # Relationships
    stock_entries = relationship("StockEntry", back_populates="product", cascade="all, delete")
    stock_exits = relationship("StockExit", back_populates="product", cascade="all, delete")

class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True)
    
    name = Column(String(30))
    icon = Column(String(50), default="CATEGORY")  # Icon name for category display
    image = Column(String(255), nullable=True)  # Custom image path for category
    
    # Relationships
    products = relationship("Product", backref="products", cascade="all, delete")

class StockEntry(Base):
    __tablename__ = "stock_entries"
    __table_args__ = (
        Index('idx_stockentry_product_date', 'product_id', 'entry_date'),
    )
    id = Column(Integer, primary_key=True)
    
    name = Column(String(50), nullable=True)
    product_id = Column(Integer, ForeignKey('products.id'), nullable=False)
    quantity = Column(Integer, nullable=False)
    entry_date = Column(DateTime, default=datetime.now)
    # Relationship with back_populates instead of backref
    product = relationship("Product", back_populates="stock_entries")
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=True, index=True)

# Stock Exit Table
class StockExit(Base):
    __tablename__ = "stock_exits"
    __table_args__ = (
        Index('idx_stockexit_product_date', 'product_id', 'exit_date'),
    )
    id = Column(Integer, primary_key=True)
    
    name = Column(String(50))
    product_id = Column(Integer, ForeignKey('products.id'), nullable=False)
    quantity = Column(Integer, nullable=False)
    exit_date = Column(DateTime, default=datetime.now)
    # Relationship with back_populates instead of backref
    product = relationship("Product", back_populates="stock_exits")
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=True, index=True)

class SalesReport(Base):
    __tablename__ = "reports"
    __table_args__ = (
        Index('idx_report_date_name', 'date', 'name'),
    )
    id = Column(Integer, primary_key=True)
    
    name = Column(String(20))
    date = Column(String(22), index=True)  # TODO: migrate to Column(Date) â€” requires ALTER TABLE + data migration
    cashier = Column(String(50))
    employee = Column(String(40))
    
    # Relationships
    sales = relationship("ProductSale", backref="reports", cascade="save-update, merge")  # Preserve sales history
    stock_entry = relationship("StockEntry", backref="report", cascade="save-update, merge")
    stock_exit = relationship("StockExit", backref="report", cascade="save-update, merge")

class ProductSale(Base):
    __tablename__ = "sales"
    id = Column(Integer, primary_key=True)
    
    order_number = Column(String(20), unique=True, nullable=True)  # Format: ORD-YYYYMMDD-XXXX
    date = Column(DateTime, index=True)
    time = Column(String(10), default="08:00")
    products = Column(JSON, nullable=False)
    total_items = Column(Integer)
    total_amount = Column(Float)
    report_id = Column(Integer, ForeignKey("reports.id"), index=True)  # Indexed for report-based lookups
    customer = Column(String(50))
    employee = Column(String(40))
    method = Column(String(40))
    is_refunded = Column(Integer, default=0)  # 0=not refunded, 1=partial, 2=full
    
    # Relationships
    refunds = relationship("Refund", back_populates="sale", cascade="all, delete")

class Refund(Base):
    """Tracks refunds for completed sales"""
    __tablename__ = "refunds"
    
    id = Column(Integer, primary_key=True)
    
    sale_id = Column(Integer, ForeignKey('sales.id'), nullable=False, index=True)
    order_number = Column(String(20))  # Copy from original sale for easy reference
    refund_amount = Column(Float, nullable=False)
    refund_reason = Column(String(200))
    refund_type = Column(String(20))  # 'full', 'partial'
    refund_method = Column(String(40))  # Payment method used for refund
    products_refunded = Column(JSON)  # Which items were refunded (for partial refunds)
    processed_by = Column(String(50))  # Employee who processed the refund
    refund_date = Column(DateTime, server_default=func.now(), index=True)
    status = Column(String(20), default='completed')  # 'completed', 'pending', 'failed'
    gateway_refund_id = Column(String(100))  # Transaction ID from payment gateway
    
    # Relationship
    sale = relationship("ProductSale", back_populates="refunds")

class BillItems(Base):
    __tablename__ = "bill_items"
    
    id = Column(Integer, primary_key=True)
    
    date = Column(DateTime, server_default=func.now())
    items = Column(JSON, nullable=False)  # List of items (JSON)
    bill_id = Column(Integer, ForeignKey('bills.id'), nullable=False)  # Foreign key to OpenBills
    
    # Relationships
    bill = relationship("OpenBills", back_populates="items")

class OpenBills(Base):
    __tablename__ = "bills"
    
    id = Column(Integer, primary_key=True)
    
    customer = Column(String(100), nullable=False)
    table_id = Column(Integer, ForeignKey('tables.id'), nullable=True)  # Foreign key to Table
    
    # Relationships
    items = relationship("BillItems", back_populates="bill", cascade="all, delete")
    table = relationship("Table", back_populates="bills")

class StockReport(Base):
    __tablename__ = 'stock_reports'

    id = Column(Integer, primary_key=True, autoincrement=True)
    # report_id removed: was redundant with id
    history = Column(JSON, nullable=False)  # Column to store the complete list as JSON
    
class Table(Base):
    __tablename__ = "tables"
    
    id = Column(Integer, primary_key=True)
    
    number = Column(Integer, nullable=False)  # Table number (unique per tenant)
    capacity = Column(Integer, nullable=False)  # Table capacity
    status = Column(String(20), default="free")  # Table status: free, reserved, occupied
    current_order_id = Column(Integer, default=0)  # Current order ID for this table session
    customer_id = Column(Integer, ForeignKey('customers.id'), nullable=True)  # Assigned customer
    waiter_name = Column(String(100), nullable=True)  # Assigned waiter name
    
    # Relationships
    bills = relationship("OpenBills", back_populates="table", cascade="all, delete")
    order_items = relationship("TableOrderItem", back_populates="table", cascade="all, delete")

class TableOrderItem(Base):
    """Tracks individual order items for a table with kitchen status"""
    __tablename__ = "table_order_items"
    __table_args__ = (
        Index('idx_tableorder_table_kitchen', 'table_id', 'sent_to_kitchen'),
    )
    
    id = Column(Integer, primary_key=True)
    table_id = Column(Integer, ForeignKey('tables.id'), nullable=False)
    product_id = Column(Integer, ForeignKey('products.id'), nullable=False)
    product_name = Column(String(100))
    quantity = Column(Integer, default=1)
    price = Column(Float)
    notes = Column(String(200), nullable=True)  # Special instructions
    sent_to_kitchen = Column(Integer, default=0)  # 0=pending, 1=sent
    sent_at = Column(DateTime, nullable=True)
    kitchen_done = Column(Integer, default=0)  # 0=in-progress, 1=done
    order_number = Column(String(20), nullable=True)  # Kitchen order batch number
    created_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    table = relationship("Table", back_populates="order_items")
    product = relationship("Product")

class PaymentMethod(Base):
    __tablename__ = "payment_methods"
    
    id = Column(Integer, primary_key=True)
    
    name = Column(String(50), nullable=False)  # Method name (e.g., Cash, Fawry, Visa)
    description = Column(String(200))  # Optional description of the method
    active = Column(Integer, default=1)  # Method status (1=active, 0=inactive)
    creation_date = Column(DateTime, server_default=func.now())
    
    # Payment Gateway Integration Fields
    gateway_type = Column(String(50), default="manual")  # 'manual', 'fawry', 'visa', 'talabat', 'tabby'
    api_key = Column(String(200))  # Encrypted API key for gateway
    api_secret = Column(String(200))  # Encrypted API secret
    merchant_id = Column(String(100))  # Merchant ID for gateway
    is_online = Column(Integer, default=0)  # 1=online gateway, 0=manual/offline
    
    # Relationships

# Recipe/Ingredient Management System
class Ingredient(Base):
    """Raw materials/ingredients table"""
    __tablename__ = "ingredients"
    __table_args__ = (
    )
    
    id = Column(Integer, primary_key=True)
    
    name = Column(String(100), nullable=False)  # Unique per tenant (enforced by UniqueConstraint)
    unit = Column(String(20), nullable=False)  # kg, g, L, ml, pieces, etc.
    current_stock = Column(Float, default=0)
    min_stock_level = Column(Float, default=0)  # Alert when stock falls below this
    cost_per_unit = Column(Float, default=0)  # Cost price per unit
    supplier = Column(String(100))
    notes = Column(String(500))
    image = Column(String(100), default="ingredient.png")  # Ingredient image
    
    # Relationships
    recipe_items = relationship("RecipeItem", back_populates="ingredient", cascade="save-update, merge")
    stock_movements = relationship("IngredientStockMovement", back_populates="ingredient", cascade="save-update, merge")

class RecipeItem(Base):
    """Defines what ingredients/products are needed for each product"""
    __tablename__ = "recipe_items"
    
    id = Column(Integer, primary_key=True)
    
    product_id = Column(Integer, ForeignKey('products.id', ondelete='CASCADE'), nullable=False)
    ingredient_id = Column(Integer, ForeignKey('ingredients.id'), nullable=True)  # Can be null if using component product
    component_product_id = Column(Integer, ForeignKey('products.id'), nullable=True)  # Product used as ingredient
    quantity_needed = Column(Float, nullable=False)  # Amount needed per product unit
    recipe_unit = Column(String(20), nullable=True)  # Unit for quantity_needed: 'g', 'ml', 'kg', 'L', 'pieces'
    
    # Relationships
    product = relationship("Product", backref="recipe_items", foreign_keys=[product_id])
    ingredient = relationship("Ingredient", back_populates="recipe_items")
    component_product = relationship("Product", foreign_keys=[component_product_id])

class IngredientStockMovement(Base):
    """Track ingredient stock movements (purchase, usage, wastage)"""
    __tablename__ = "ingredient_stock_movements"
    __table_args__ = (
        Index('idx_ingredient_movement_date', 'ingredient_id', 'movement_date'),
    )
    
    id = Column(Integer, primary_key=True)
    
    ingredient_id = Column(Integer, ForeignKey('ingredients.id'), nullable=False)
    movement_type = Column(String(20), nullable=False)  # 'purchase', 'usage', 'wastage', 'adjustment'
    quantity = Column(Float, nullable=False)  # Positive for additions, negative for deductions
    cost = Column(Float, default=0)
    movement_date = Column(DateTime, default=datetime.now)
    reference_id = Column(Integer)  # Reference to sale_id if movement is from a sale
    notes = Column(String(500))
    user = Column(String(100))
    
    # Relationships
    ingredient = relationship("Ingredient", back_populates="stock_movements")

# Customer Management for Loyalty System
class Customer(Base):
    """Customer database for loyalty program"""
    __tablename__ = "customers"
    
    id = Column(Integer, primary_key=True)
    
    name = Column(String(100), nullable=False)
    phone = Column(String(20), index=True)  # Unique per tenant
    email = Column(String(100))
    loyalty_points = Column(Integer, default=0)
    total_purchases = Column(Float, default=0)
    discount_percentage = Column(Float, default=0)
    registration_date = Column(DateTime, server_default=func.now())
    notes = Column(String(500))
    
    # Relationships

# Discount Management
class Discount(Base):
    """Discount/Promotion management"""
    __tablename__ = "discounts"
    
    id = Column(Integer, primary_key=True)
    
    name = Column(String(100), nullable=False)
    discount_type = Column(String(20), nullable=False)  # 'percentage', 'fixed_amount'
    value = Column(Float, nullable=False)
    start_date = Column(DateTime, server_default=func.now())
    end_date = Column(DateTime)
    active = Column(Boolean, default=True)
    applicable_to = Column(String(20))  # 'all', 'category', 'product'
    product_id = Column(Integer, ForeignKey('products.id', ondelete='SET NULL'))
    category = Column(String(50))
    
    # Relationships

# Language Translations
class Translation(Base):
    """Multi-language support"""
    __tablename__ = "translations"
    
    id = Column(Integer, primary_key=True)
    key = Column(String(100), nullable=False, unique=True)  # Translation key
    english = Column(String(500))
    arabic = Column(String(500))

# ===== ADVANCED ROLE & PERMISSION SYSTEM =====

class Permission(Base):
    """Permission definitions"""
    __tablename__ = "permissions"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)  # e.g., 'view_sales', 'edit_products'
    description = Column(String(200))
    category = Column(String(50))  # 'sales', 'products', 'inventory', 'reports', 'settings'
    
    # Relationships
    user_permissions = relationship("UserPermission", back_populates="permission", cascade="all, delete")
    role_permissions = relationship("RolePermission", back_populates="permission", cascade="all, delete")

class Role(Base):
    """Role definitions with default permissions"""
    __tablename__ = "roles"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False, unique=True)  # 'user', 'manager', 'admin', 'master_admin'
    display_name = Column(String(100))  # 'User', 'Manager', 'Administrator', 'Master Admin'
    description = Column(String(200))
    level = Column(Integer, default=0)  # Hierarchy: user=1, manager=2, admin=3, master_admin=4
    
    # Relationships
    role_permissions = relationship("RolePermission", back_populates="role", cascade="all, delete")

class UserPermission(Base):
    """User-specific permissions (override role defaults)"""
    __tablename__ = "user_permissions"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    permission_id = Column(Integer, ForeignKey('permissions.id'), nullable=False)
    granted = Column(Integer, default=1)  # 1=granted, 0=revoked
    granted_by = Column(Integer, ForeignKey('users.id'))  # Who granted this permission
    granted_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    user = relationship("User", back_populates="permissions", foreign_keys=[user_id])
    permission = relationship("Permission", back_populates="user_permissions")

class RolePermission(Base):
    """Default permissions for each role"""
    __tablename__ = "role_permissions"
    
    id = Column(Integer, primary_key=True)
    role_id = Column(Integer, ForeignKey('roles.id'), nullable=False)
    permission_id = Column(Integer, ForeignKey('permissions.id'), nullable=False)
    
    # Relationships
    role = relationship("Role", back_populates="role_permissions")
    permission = relationship("Permission", back_populates="role_permissions")

# ===== MULTI-DEVICE MANAGEMENT SYSTEM =====

class Device(Base):
    """Device/Installation registration for multi-device management"""
    __tablename__ = "devices"
    
    id = Column(Integer, primary_key=True)
    
    device_name = Column(String(100), nullable=False)  # e.g., "Main Counter", "Kitchen Terminal"
    device_uuid = Column(String(100), unique=True, nullable=False)  # Unique device identifier
    location = Column(String(200))  # Physical location
    ip_address = Column(String(50))
    mac_address = Column(String(50))
    is_active = Column(Boolean, default=True)
    registered_at = Column(DateTime, server_default=func.now())
    last_seen = Column(DateTime, server_default=func.now())
    sync_enabled = Column(Boolean, default=True)  # Can sync with master
    api_key = Column(String(100))  # For API authentication
    
    # Relationships
    users = relationship("User", back_populates="device")
    sales = relationship("DeviceSale", back_populates="device", cascade="all, delete")

class DeviceSale(Base):
    """Track which device made which sale (for master admin reporting)"""
    __tablename__ = "device_sales"
    
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey('devices.id'), nullable=False)
    sale_id = Column(Integer, ForeignKey('sales.id'), nullable=False)
    synced_to_master = Column(Integer, default=0)  # Has this been synced to master?
    sync_date = Column(DateTime)
    
    # Relationships
    device = relationship("Device", back_populates="sales")

class AuditLog(Base):
    """Audit trail for master admin monitoring"""
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True)
    
    user_id = Column(Integer, ForeignKey('users.id'))
    device_id = Column(Integer, ForeignKey('devices.id'))
    action = Column(String(100), nullable=False)  # 'login', 'sale', 'product_edit', etc.
    resource_type = Column(String(50))  # 'product', 'sale', 'user', etc.
    resource_id = Column(Integer)
    details = Column(JSON)  # Additional details as JSON
    ip_address = Column(String(50))
    timestamp = Column(DateTime, server_default=func.now(), index=True)
    success = Column(Boolean, default=True)  # Was action successful?
    
    # Relationships

class StoreSettings(Base):
    """Store configuration for receipts and branding - one per tenant"""
    __tablename__ = "store_settings"
    
    id = Column(Integer, primary_key=True)
    
    store_name = Column(String(100), default="My POS Store")
    address = Column(String(200))
    phone = Column(String(50))
    logo_path = Column(String(200))  # Path to logo image
    header_text = Column(String(200))  # Text to appear at top of receipt
    footer_text = Column(String(200))  # Text to appear at bottom of receipt
    
    # Business type configuration
    business_type = Column(String(50), default="restaurant")  # 'restaurant', 'cafe', 'barber_shop', 'supermarket'
    
    # Tax configuration
    vat_percentage = Column(Float, default=16.0)  # VAT rate as percentage (e.g., 16.0 = 16%)
    vat_number = Column(String(50))  # VAT registration number for receipts
    
    # Hardware configuration
    printer_name = Column(String(100), default="XP-80C")  # Thermal printer name
    scanner_port = Column(String(50))  # COM port for barcode scanner (e.g., COM3)
    drawer_command = Column(String(100), default="\\x1b\\x70\\x00\\x19\\xfa")  # ESC/POS drawer open command
    
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Relationships

class InventorySnapshot(Base):
    """Tracks automated or manual inventory snapshots"""
    __tablename__ = "inventory_snapshots"

    id = Column(Integer, primary_key=True)
    date = Column(String(20), nullable=False)  # YYYY-MM-DD
    created_at = Column(DateTime, server_default=func.now())
    type = Column(String(20), default='auto_daily')  # 'auto_daily', 'manual', 'opening', 'closing'
    note = Column(String(200))
    
    # Relationships
    items = relationship("InventorySnapshotItem", back_populates="snapshot", cascade="all, delete")

class InventorySnapshotItem(Base):
    """Individual product stock in a snapshot"""
    __tablename__ = "inventory_snapshot_items"

    id = Column(Integer, primary_key=True)
    snapshot_id = Column(Integer, ForeignKey('inventory_snapshots.id'), nullable=False)
    product_id = Column(Integer, ForeignKey('products.id', ondelete='CASCADE'), nullable=True)  # Cascade: if product deleted, snapshot item also deleted
    product_name = Column(String(100)) # Backup name
    quantity = Column(Float, nullable=False)
    cost = Column(Float, default=0)
    price = Column(Float, default=0)
    
    # Relationships
    snapshot = relationship("InventorySnapshot", back_populates="items")
    product = relationship("Product")

class Shelf(Base):
    """Shelf Management System"""
    __tablename__ = "shelves"

    id = Column(Integer, primary_key=True)
    
    shelf_code = Column(String(50), nullable=False)  # e.g. "A1-05" - unique per tenant
    description = Column(String(200))
    max_capacity = Column(Integer, default=100)
    current_quantity = Column(Integer, default=0)
    
    # Linked Product
    product_id = Column(Integer, ForeignKey('products.id'), nullable=True, index=True)  # Indexed for product lookups
    
    # Relationships
    product = relationship("Product")


# ===== APPLICATION CONFIGURATION TABLE =====

class AppConfig(Base):
    """
    Application configuration stored in database.
    Replaces JSON config files (ai_config.json, security_config.json, language_state.json).
    Supports per-tenant configuration overrides.
    """
    __tablename__ = "app_config"
    __table_args__ = (
    )
    
    id = Column(Integer, primary_key=True)
    
    config_key = Column(String(100), nullable=False, index=True)    # e.g. 'gemini_api_key'
    config_value = Column(Text, nullable=True)                       # The value (stored as string)
    config_type = Column(String(20), default="string")               # 'string', 'int', 'float', 'bool', 'json'
    category = Column(String(50), default="general")                 # 'general', 'ai', 'security', 'display', 'hardware'
    description = Column(String(200), nullable=True)                 # Human-readable description
    
    # Relationships
