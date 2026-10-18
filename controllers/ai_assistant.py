import json
import logging
import os
from datetime import datetime
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
import google.generativeai as genai

from core.database import fetch_all, execute
from auth.security import get_current_user
from core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

CACHE_FILE = "data/ai_insights_cache.json"

# Ensure data directory exists
os.makedirs("data", exist_ok=True)

# System prompt template for Chat
SYSTEM_PROMPT = """You are an ultra-professional, friendly AI Cashier Assistant for a modern POS system.
You help the cashier manage tables, find products, and process sales.
You have access to the current state of the store.
Current Tables: {tables}
Current Products: {products}

If the user asks a question, answer it politely.
If the user asks you to perform an action (e.g., reserve a table, create a sale, free a table), you must output a JSON block at the END of your response with the exact action to execute.

Available Actions in JSON:
1. Reserve a table:
```json
{{"action": "reserve_table", "table_id": 1, "customer_name": "John"}}
```
2. Create a quick sale:
```json
{{"action": "create_sale", "product_ids": [1, 2], "method": "Cash"}}
```
3. Free/checkout a table:
```json
{{"action": "free_table", "table_id": 1}}
```
4. No action needed:
```json
{{"action": "none"}}
```

Always respond with friendly text, followed by the JSON block in exactly the format above.
"""

@router.post("/chat")
async def chat(request: Request, user_data: dict = Depends(get_current_user)):
    try:
        body = await request.json()
        message = body.get("message", "")
        
        if not message:
            return JSONResponse({"error": True, "message": "Message is required"}, status_code=400)
            
        tables = await fetch_all("SELECT id, number, capacity, status FROM tables")
        products = await fetch_all("SELECT id, title, price, stock FROM products LIMIT 50")
        
        api_key = await fetch_all("SELECT config_value FROM app_config WHERE config_key = 'gemini_api_key'")
        key = api_key[0]["config_value"] if api_key else settings.GEMINI_API_KEY
        
        if not key:
            return JSONResponse({"error": True, "message": "Gemini API Key not configured in settings"}, status_code=400)
            
        genai.configure(api_key=key)
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        prompt = SYSTEM_PROMPT.format(
            tables=json.dumps(tables, default=str),
            products=json.dumps(products, default=str)
        )
        
        chat = model.start_chat(history=[
            {"role": "user", "parts": [prompt]},
            {"role": "model", "parts": ["Understood. I am ready to help."]}
        ])
        
        response = chat.send_message(message)
        response_text = response.text
        
        action_result = "No action performed."
        action_data = None
        
        try:
            if "```json" in response_text:
                json_str = response_text.split("```json")[1].split("```")[0].strip()
                action_data = json.loads(json_str)
            elif "```" in response_text:
                 json_str = response_text.split("```")[1].split("```")[0].strip()
                 action_data = json.loads(json_str)
        except Exception as e:
            logger.error(f"Failed to parse AI action JSON: {e}")
            
        if action_data:
            action = action_data.get("action")
            if action == "reserve_table":
                t_id = action_data.get("table_id")
                c_name = action_data.get("customer_name", "AI Reservation")
                await execute("UPDATE tables SET status = 'occupied' WHERE id = %s", [t_id])
                action_result = f"Table {t_id} reserved for {c_name}."
            elif action == "free_table":
                t_id = action_data.get("table_id")
                await execute("UPDATE tables SET status = 'free' WHERE id = %s", [t_id])
                await execute("DELETE FROM table_order_items WHERE table_id = %s", [t_id])
                action_result = f"Table {t_id} is now free."
            elif action == "create_sale":
                p_ids = action_data.get("product_ids", [])
                if p_ids:
                    placeholders = ",".join(["%s"] * len(p_ids))
                    prods = await fetch_all(f"SELECT id, title, price FROM products WHERE id IN ({placeholders})", p_ids)
                    total = sum(p["price"] for p in prods)
                    import random
                    from datetime import datetime
                    order_num = f"AI-ORD-{random.randint(1000, 9999)}"
                    await execute(
                        "INSERT INTO sales (order_number, date, time, products, total_items, total_amount, employee, method) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                        [order_num, datetime.now().strftime("%Y-%m-%d"), datetime.now().strftime("%H:%M:%S"), json.dumps(prods, default=str), len(prods), total, "AI Assistant", action_data.get("method", "Cash")]
                    )
                    action_result = f"Sale created! Order {order_num} for {total} EGP."
        
        if "```json" in response_text:
            clean_text = response_text.split("```json")[0].strip()
        elif "```" in response_text:
            clean_text = response_text.split("```")[0].strip()
        else:
            clean_text = response_text
            
        return JSONResponse({
            "response": clean_text,
            "action_result": action_result if action_data and action_data.get("action") != "none" else None
        })
        
    except Exception as e:
        logger.error(f"AI Assistant error: {str(e)}")
        return JSONResponse({"error": True, "message": str(e)}, status_code=500)

@router.post("/insights/run")
async def run_insights(request: Request, user_data: dict = Depends(get_current_user)):
    try:
        body = await request.json()
        force_refresh = body.get("force_refresh", False)
        
        # Return cached results if available and not forced
        if not force_refresh and os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                    return JSONResponse({"success": True, "data": cached_data})
            except Exception as e:
                logger.error(f"Cache read error: {e}")

        # Gather real data for analysis
        products = await fetch_all("SELECT title, stock, price, cost_price FROM products WHERE stock < 20 LIMIT 30")
        sales = await fetch_all("SELECT date, products, total_amount, employee, is_refunded FROM sales ORDER BY id DESC LIMIT 100")
        customers = await fetch_all("SELECT name, loyalty_points, total_purchases FROM customers ORDER BY total_purchases DESC LIMIT 20")
        
        # Prepare context for AI
        context_data = {
            "low_stock_products": products,
            "recent_sales": sales,
            "top_customers": customers,
            "current_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        # Initialize Gemini
        api_key_query = await fetch_all("SELECT config_value FROM app_config WHERE config_key = 'gemini_api_key'")
        key = api_key_query[0]["config_value"] if api_key_query else settings.GEMINI_API_KEY
        
        if not key:
            return JSONResponse({"error": True, "message": "Gemini API Key not configured in settings. Please add it to Database."}, status_code=400)
            
        genai.configure(api_key=key)
        model = genai.GenerativeModel('gemini-2.5-flash', generation_config={"response_mime_type": "application/json"})
        
        prompt = f"""
You are an expert POS Data Scientist. Analyze the following store data and output a strictly formatted JSON response containing business insights.

DATA CONTEXT:
{json.dumps(context_data, default=str)}

OUTPUT REQUIREMENTS (MUST BE EXACT JSON FORMAT):
{{
  "health_score": <integer 0-100 based on overall store health>,
  "executive_summary": "<A professional 3-4 sentence summary of the business state>",
  "waste": {{
    "total_waste_cost": <calculate total lost revenue from low stock using price * (20 - stock) for critical items>,
    "waste_items": [
      {{
        "name": "<product name>",
        "stock_qty": <current stock>,
        "expiry_days": <random estimate 2-15>,
        "waste_percentage": <float percentage of stock lost>,
        "status": "<'critical' if stock < 5 else 'stable'>"
      }}
    ]
  }},
  "sellers": {{
    "top_by_units": [
      {{
        "name": "<product name>",
        "units_sold": <calculate from sales data products list>,
        "trend_pct": <float between -10 and 25>
      }}
    ]
  }},
  "forecast": {{
    "forecast": [
      {{ "day": "<Mon>", "predicted": <float predicted sales amount> }},
      {{ "day": "<Tue>", "predicted": <float> }},
      {{ "day": "<Wed>", "predicted": <float> }},
      {{ "day": "<Thu>", "predicted": <float> }},
      {{ "day": "<Fri>", "predicted": <float> }},
      {{ "day": "<Sat>", "predicted": <float> }},
      {{ "day": "<Sun>", "predicted": <float> }}
    ]
  }},
  "fraud": {{
    "alerts": [
      {{
        "user_name": "<employee name from sales with is_refunded=1 or 2>",
        "risk_score": <integer 50-100>,
        "voids": <integer>,
        "last_incident": "<date string>"
      }}
    ]
  }},
  "retention": {{
    "churn_risks": [
      {{
        "name": "<customer name from top_customers>",
        "days_inactive": <integer 30-90>,
        "churn_probability": <float 0.5-0.9>,
        "total_spent": <float from total_purchases>
      }}
    ]
  }},
  "recommendations": [
    {{ "name": "<short action title>", "reason": "<why and how to execute>" }},
    {{ "name": "<short action title>", "reason": "<why and how to execute>" }}
  ]
}}
"""
        response = model.generate_content(prompt)
        ai_response = json.loads(response.text)
        
        # Add timestamp
        ai_response["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Save to cache
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(ai_response, f, ensure_ascii=False, indent=2)

        return JSONResponse({"success": True, "data": ai_response})

    except Exception as e:
        logger.error(f"Insights Generation Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": True, "message": str(e)}, status_code=500)

@router.get("/insights")
async def get_insights_legacy():
    # Legacy endpoint redirects to run to ensure compatibility if accessed
    return JSONResponse({"error": True, "message": "Use POST /insights/run"})
