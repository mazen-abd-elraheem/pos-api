"""
services/api_client.py - HTTP Client for POS Client Mode

Connects to Master server via REST API with JWT authentication.
Provides wrapper functions mirroring controller.py interface.
"""

import logging
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta
import json

logger = logging.getLogger(__name__)

# Lazy import for httpx to avoid import errors if not installed
_httpx = None

def get_httpx():
    global _httpx
    if _httpx is None:
        import httpx
        _httpx = httpx
    return _httpx


class APIError(Exception):
    """Custom exception for API errors."""
    def __init__(self, message: str, status_code: int = 0):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class POSAPIClient:
    """
    HTTP Client for connecting to POS Master Server.
    
    Handles JWT authentication, token refresh, and all API calls.
    Designed to be a drop-in replacement for direct database operations.
    """
    
    def __init__(self, server_url: str = None):
        """
        Initialize API client.
        
        Args:
            server_url: Base URL of Master server (e.g., "https://pos.trycloudflare.com")
        """
        from core.config import get_server_url, get_jwt_token
        
        self.server_url = (server_url or get_server_url()).rstrip('/')
        self._token = get_jwt_token()
        self._token_expiry = None
        self._client = None
        
    def _get_client(self):
        """Get or create persistent HTTP/2 client with keep-alive connection pooling."""
        if self._client is None:
            httpx = get_httpx()
            # HTTP/2 multiplexes all requests over ONE persistent TLS connection
            # Saves ~100-150ms TLS handshake per request after the first one
            try:
                self._client = httpx.Client(
                    base_url=self.server_url,
                    http2=True,  # Enable HTTP/2 (single persistent connection)
                    timeout=httpx.Timeout(
                        connect=10.0,   # Initial connection timeout
                        read=30.0,      # Read timeout for slow queries
                        write=10.0,     # Write timeout
                        pool=5.0,       # Wait for connection from pool
                    ),
                    limits=httpx.Limits(
                        max_keepalive_connections=5,   # Keep 5 connections alive
                        max_connections=10,            # Max concurrent connections
                        keepalive_expiry=120,          # Keep alive for 2 minutes
                    ),
                    headers={
                        "Content-Type": "application/json",
                        "Accept-Encoding": "gzip, deflate",  # Request compressed responses
                        "Connection": "keep-alive",
                    },
                )
            except Exception:
                # Fallback if http2 extra not installed
                self._client = httpx.Client(
                    base_url=self.server_url,
                    timeout=30.0,
                    headers={
                        "Content-Type": "application/json",
                        "Accept-Encoding": "gzip, deflate",
                        "Connection": "keep-alive",
                    },
                )
                logger.warning("HTTP/2 not available â€” install httpx[http2]. Using HTTP/1.1 keep-alive.")
        return self._client
    
    def _get_headers(self) -> Dict[str, str]:
        """Get headers with current JWT token."""
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers
    
    def _handle_response(self, response) -> Dict:
        """Handle API response, raise appropriate errors."""
        try:
            response.raise_for_status()
            return response.json()
        except Exception as e:
            status_code = getattr(response, 'status_code', 0)
            
            if status_code == 401:
                raise APIError("Authentication failed - please login again", 401)
            elif status_code == 403:
                raise APIError("Access denied - insufficient permissions", 403)
            elif status_code == 404:
                raise APIError("Resource not found", 404)
            elif status_code >= 500:
                raise APIError("Server error - Master may be offline", status_code)
            else:
                try:
                    detail = response.json().get("detail", str(e))
                except Exception:
                    detail = str(e)
                raise APIError(f"API Error: {detail}", status_code)
    
    def close(self):
        """Close the HTTP client."""
        if self._client:
            self._client.close()
            self._client = None
    
    # ============ CONNECTION / AUTH ============
    
    def test_connection(self) -> Dict:
        """
        Test connection to Master server.
        
        Returns:
            Dict with status info if successful
            
        Raises:
            APIError: If connection fails
        """
        try:
            httpx = get_httpx()
            response = httpx.get(
                f"{self.server_url}/health",
                timeout=10.0
            )
            return self._handle_response(response)
        except Exception as e:
            if "Connection" in str(e):
                raise APIError(f"Cannot connect to server: {self.server_url}", 0)
            raise APIError(f"Connection test failed: {e}", 0)
    
    def get_users(self) -> List[Dict]:
        """Get active user profiles (for login choice)."""
        response = self._get_client().get(
            "/api/users",
            headers=self._get_headers()
        )
        return self._handle_response(response)
    
    def login(self, username: str, password: str, device_name: str = None, location: str = None) -> Dict:
        """
        Authenticate with Master server.
        
        Args:
            username: User's username
            password: User's password
            device_name: Name of this device
            location: Location of this device
            
        Returns:
            Dict with user info and token
            
        Raises:
            APIError: If authentication fails
        """
        try:
            from core.config import save_jwt_token, get_device_name, get_device_location
            
            httpx = get_httpx()
            
            response = httpx.post(
                f"{self.server_url}/api/auth/login",
                json={
                    "username": username,
                    "password": password,
                    "device_name": device_name or get_device_name(),
                    "location": location or get_device_location()
                },
                timeout=15.0
            )
            
            data = self._handle_response(response)
            
            # Store token
            self._token = data.get("access_token")
            self._token_expiry = data.get("expires_at")
            
            # Save token to config
            save_jwt_token(self._token, self._token_expiry)
            
            return data.get("user", {})
            
        except APIError:
            raise
        except Exception as e:
            raise APIError(f"Login error: {e}", 0)
    
    def refresh_token(self) -> bool:
        """
        Refresh JWT token before expiry.
        
        Returns:
            bool: True if successful
        """
        try:
            from core.config import save_jwt_token
            
            response = self._get_client().post(
                "/api/auth/refresh",
                headers=self._get_headers()
            )
            
            data = self._handle_response(response)
            self._token = data.get("access_token")
            self._token_expiry = data.get("expires_at")
            save_jwt_token(self._token, self._token_expiry)
            
            return True
        except Exception as e:
            logger.error(f"Token refresh failed: {e}")
            return False
    
    def verify_auth(self) -> bool:
        """
        Verify current token is valid.
        
        Returns:
            bool: True if authenticated
        """
        try:
            response = self._get_client().get(
                "/api/auth/verify",
                headers=self._get_headers()
            )
            return response.status_code == 200
        except Exception:
            return False
    
    # ============ PRODUCTS ============
    
    def get_products(self) -> List[Dict]:
        """Get all products from Master."""
        response = self._get_client().get(
            "/api/products",
            headers=self._get_headers()
        )
        return self._handle_response(response)
    
    def get_product(self, product_id: int) -> Dict:
        """Get single product by ID."""
        response = self._get_client().get(
            f"/api/products/{product_id}",
            headers=self._get_headers()
        )
        return self._handle_response(response)
    
    def create_product(self, product_data: Dict) -> Dict:
        """Create new product."""
        response = self._get_client().post(
            "/api/products",
            headers=self._get_headers(),
            json=product_data
        )
        return self._handle_response(response)
    
    # ============ SALES ============
    
    def get_sales(self, date: str = None) -> List[Dict]:
        """Get sales records."""
        params = {}
        if date:
            params["date"] = date
            
        response = self._get_client().get(
            "/api/sales",
            headers=self._get_headers(),
            params=params
        )
        return self._handle_response(response)
    
    def create_sale(self, sale_data: Dict) -> Dict:
        """Record a new sale."""
        response = self._get_client().post(
            "/api/sales",
            headers=self._get_headers(),
            json=sale_data
        )
        return self._handle_response(response)

    def create_sale_complete(self, sale_data: Dict) -> Dict:
        """Single-call sale: report + sale + stock deduction in one round-trip."""
        response = self._get_client().post(
            "/api/sales/complete",
            headers=self._get_headers(),
            json=sale_data
        )
        return self._handle_response(response)
    
    # ============ CATEGORIES ============
    
    def get_categories(self) -> List[str]:
        """Get all categories."""
        response = self._get_client().get(
            "/api/categories",
            headers=self._get_headers()
        )
        data = self._handle_response(response)
        return data.get("categories", [])
    
    # ============ CUSTOMERS ============
    
    def get_customers(self) -> List[Dict]:
        """Get all customers."""
        response = self._get_client().get(
            "/api/customers",
            headers=self._get_headers()
        )
        return self._handle_response(response)

    # ============ REFUNDS ============

    def get_refunds(self, date: str = None) -> List[Dict]:
        """Get all refunds, optionally filtered by date."""
        params = {}
        if date:
            params["date"] = date
        response = self._get_client().get(
            "/api/sales/refunds",
            headers=self._get_headers(),
            params=params
        )
        data = self._handle_response(response)
        return data.get("refunds", [])

    def get_refunds_total(self) -> float:
        """Get total lifetime refund amount."""
        response = self._get_client().get(
            "/api/sales/refunds/total",
            headers=self._get_headers()
        )
        data = self._handle_response(response)
        return float(data.get("total", 0.0))

    # ============ TABLES ============

    def get_tables_status(self) -> List[Dict]:
        """Get tables with computed pending/sent/total fields."""
        response = self._get_client().get(
            "/api/tables/status",
            headers=self._get_headers()
        )
        data = self._handle_response(response)
        return data.get("tables", [])

    # ============ INGREDIENTS ============

    def get_ingredient_movements(self, date: str = None) -> List[Dict]:
        """Get all ingredient stock movements."""
        params = {}
        if date:
            params["date"] = date
        response = self._get_client().get(
            "/api/ingredients/movements",
            headers=self._get_headers(),
            params=params
        )
        data = self._handle_response(response)
        return data.get("movements", [])

    # ============ ROLES ============

    def get_roles(self) -> List[Dict]:
        """Get all roles."""
        response = self._get_client().get(
            "/api/permissions/roles",
            headers=self._get_headers()
        )
        data = self._handle_response(response)
        return data.get("roles", [])

    # ============ EMPLOYEES ============

    def get_employees(self) -> List[Dict]:
        """Get all users/employees."""
        response = self._get_client().get(
            "/api/users",
            headers=self._get_headers()
        )
        data = self._handle_response(response)
        return data.get("users", [])

    # ============ DEVICES ============

    def get_all_devices(self) -> List[Dict]:
        """Get all registered devices."""
        response = self._get_client().get(
            "/api/devices",
            headers=self._get_headers()
        )
        data = self._handle_response(response)
        return data.get("devices", [])

    # ============ SALE LOOKUPS ============

    def get_sale_by_order_number(self, order_number: str) -> Optional[Dict]:
        """Get a sale by order number."""
        try:
            response = self._get_client().get(
                f"/api/sales/by-order/{order_number}",
                headers=self._get_headers()
            )
            data = self._handle_response(response)
            return data.get("sale")
        except Exception:
            return None

    def get_refunds_by_sale(self, sale_id: int) -> List[Dict]:
        """Get refunds for a specific sale."""
        response = self._get_client().get(
            "/api/sales/refunds",
            headers=self._get_headers(),
            params={"sale_id": sale_id}
        )
        data = self._handle_response(response)
        return data.get("refunds", [])

    # ============ TABLE ITEMS ============

    def get_table_items(self, table_id: int) -> List[Dict]:
        """Get order items for a table."""
        response = self._get_client().get(
            f"/api/tables/{table_id}/items",
            headers=self._get_headers()
        )
        data = self._handle_response(response)
        return data.get("items", [])

    def add_table_item(self, table_id: int, item_data: Dict) -> Dict:
        """Add an item to a table order."""
        response = self._get_client().post(
            f"/api/tables/{table_id}/items",
            headers=self._get_headers(),
            json=item_data
        )
        return self._handle_response(response)

    def send_items_to_kitchen(self, table_id: int) -> Dict:
        """Send all pending items to kitchen."""
        response = self._get_client().put(
            f"/api/tables/{table_id}/items/send",
            headers=self._get_headers()
        )
        return self._handle_response(response)

    def remove_table_item(self, item_id: int) -> Dict:
        """Remove a table order item."""
        response = self._get_client().delete(
            f"/api/tables/items/{item_id}",
            headers=self._get_headers()
        )
        return self._handle_response(response)

    # ============ PERMISSIONS ============

    def get_all_permissions(self) -> List[Dict]:
        """Get all permission names."""
        response = self._get_client().get(
            "/api/permissions/all",
            headers=self._get_headers()
        )
        data = self._handle_response(response)
        return data.get("permissions", [])

    def get_roles_with_permissions(self) -> List[Dict]:
        """Get roles with their assigned permissions."""
        response = self._get_client().get(
            "/api/permissions/roles-detail",
            headers=self._get_headers()
        )
        data = self._handle_response(response)
        return data.get("roles", [])

    # ============ CUSTOMER WRITE OPS ============

    def add_customer(self, data: Dict) -> Dict:
        """Create a customer."""
        response = self._get_client().post(
            "/api/customers",
            headers=self._get_headers(),
            json=data
        )
        return self._handle_response(response)

    def update_customer(self, customer_id: int, data: Dict) -> Dict:
        """Update a customer."""
        response = self._get_client().put(
            f"/api/customers/{customer_id}",
            headers=self._get_headers(),
            json=data
        )
        return self._handle_response(response)

    def delete_customer(self, customer_id: int) -> Dict:
        """Delete a customer."""
        response = self._get_client().delete(
            f"/api/customers/{customer_id}",
            headers=self._get_headers()
        )
        return self._handle_response(response)

    def update_customer_purchase(self, customer_id: int, amount: float) -> Dict:
        """Update customer total purchases and loyalty points."""
        response = self._get_client().put(
            f"/api/customers/{customer_id}/purchase",
            headers=self._get_headers(),
            json={"amount": amount}
        )
        return self._handle_response(response)

    # ============ BILL OPS ============

    def create_bill(self, data: Dict) -> Dict:
        """Create a new open bill."""
        response = self._get_client().post(
            "/api/bills",
            headers=self._get_headers(),
            json=data
        )
        return self._handle_response(response)

    def delete_bill(self, bill_id: int) -> Dict:
        """Delete an open bill."""
        response = self._get_client().delete(
            f"/api/bills/{bill_id}",
            headers=self._get_headers()
        )
        return self._handle_response(response)

    def add_item_to_bill(self, bill_id: int, data: Dict) -> Dict:
        """Add item to an open bill."""
        response = self._get_client().post(
            f"/api/bills/{bill_id}/items",
            headers=self._get_headers(),
            json=data
        )
        return self._handle_response(response)

    # ============ SALE WRITE OPS ============

    def delete_sale(self, sale_id: int) -> Dict:
        """Delete a sale."""
        response = self._get_client().delete(
            f"/api/sales/{sale_id}",
            headers=self._get_headers()
        )
        return self._handle_response(response)

    # ============ PERMISSION WRITE OPS ============

    def grant_permission(self, user_id: int, permission_name: str, granted_by: int = None) -> Dict:
        """Grant a permission to a user."""
        response = self._get_client().post(
            "/api/permissions/grant",
            headers=self._get_headers(),
            json={"user_id": user_id, "permission_name": permission_name, "granted_by": granted_by}
        )
        return self._handle_response(response)

    def revoke_permission(self, user_id: int, permission_name: str) -> Dict:
        """Revoke a permission from a user."""
        response = self._get_client().post(
            "/api/permissions/revoke",
            headers=self._get_headers(),
            json={"user_id": user_id, "permission_name": permission_name}
        )
        return self._handle_response(response)

    def batch_update_permissions(self, user_id: int, to_grant: list, to_revoke: list, granted_by: int = None) -> Dict:
        """Grant/revoke multiple permissions at once."""
        response = self._get_client().put(
            "/api/permissions/batch",
            headers=self._get_headers(),
            json={"user_id": user_id, "to_grant": to_grant, "to_revoke": to_revoke, "granted_by": granted_by}
        )
        return self._handle_response(response)
    
    # ============ AI PROCESSING ============
    
    def run_ai_analysis(self, modules: List[str] = None, days_forecast: int = 7) -> str:
        """
        Start AI analysis on Master server.
        
        Args:
            modules: List of modules to run, or None for all
            days_forecast: Number of days to forecast
            
        Returns:
            session_id: ID to poll for results
        """
        response = self._get_client().post(
            "/api/ai/analyze",
            headers=self._get_headers(),
            json={
                "modules": modules,
                "days_forecast": days_forecast
            }
        )
        data = self._handle_response(response)
        return data.get("session_id")
    
    def get_ai_status(self, session_id: str) -> Dict:
        """Get status of AI analysis."""
        response = self._get_client().get(
            f"/api/ai/status/{session_id}",
            headers=self._get_headers()
        )
        return self._handle_response(response)
    
    def get_ai_results(self, session_id: str) -> Dict:
        """Get results of completed AI analysis."""
        response = self._get_client().get(
            f"/api/ai/results/{session_id}",
            headers=self._get_headers()
        )
        return self._handle_response(response)
    
    # ============ DEVICE HEARTBEAT ============
    
    def send_heartbeat(self) -> bool:
        """Send device heartbeat to Master."""
        try:
            from core.config import get_device_name, get_device_location
            
            response = self._get_client().post(
                "/api/devices/heartbeat",
                headers=self._get_headers(),
                json={
                    "device_name": get_device_name(),
                    "location": get_device_location()
                }
            )
            return response.status_code == 200
        except Exception:
            return False


# ============ SINGLETON CLIENT ============

_api_client: Optional[POSAPIClient] = None

def get_api_client() -> POSAPIClient:
    """Get singleton API client instance."""
    global _api_client
    if _api_client is None:
        _api_client = POSAPIClient()
    return _api_client


# ============ CONVENIENCE FUNCTIONS ============
# These mirror controller.py function signatures for easy drop-in replacement

def api_login(username: str, password: str) -> Optional[Dict]:
    """Login via API (mirrors controller.start_login)."""
    try:
        return get_api_client().login(username, password)
    except APIError as e:
        logger.error(f"API Login failed: {e}")
        return None


def api_get_products() -> List:
    """Get products via API (mirrors controller.get_products)."""
    try:
        products = get_api_client().get_products()
        if products is None:
            return None
        
        # Convert to objects matching controller.py format
        result = []
        for p in products:
            class ProductData:
                pass
            obj = ProductData()
            obj.id = p.get("id")
            obj.title = p.get("title")
            obj.barcode = p.get("barcode")
            obj.category = p.get("category")
            obj.price = p.get("price", 0)
            obj.cost_price = p.get("cost_price", 0)
            obj.stock = p.get("stock", 0)
            obj.image = p.get("image")
            result.append(obj)
        return result
    except APIError as e:
        logger.error(f"API Get Products failed: {e}")
        return None


def api_get_categories() -> List[str]:
    """Get categories via API (mirrors controller.get_categories)."""
    try:
        cats = get_api_client().get_categories()
        return cats if cats is not None else None
    except APIError:
        return None
