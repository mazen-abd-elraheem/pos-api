"""
services/ai_engine.py - Advanced AI Data Scientist Engine for POS System
Dual-model support: Local (Ollama) + Cloud (Google Gemini)
Bilingual: Arabic/English based on current language setting
"""

import gc
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Callable
from collections import defaultdict
from core.translations import t, get_current_language

logger = logging.getLogger(__name__)

# Lazy imports
def get_pandas():
    import pandas as pd
    return pd

def get_prophet():
    from prophet import Prophet
    return Prophet

def get_ollama():
    import ollama
    return ollama

def get_gemini():
    import google.generativeai as genai
    return genai


class AIModelManager:
    """Manages AI model connections (Ollama + Gemini)"""
    
    def __init__(self, gemini_api_key: str = None):
        self.gemini_api_key = gemini_api_key
        self.active_model = "local"  # "local", "gemini", "auto"
        self._ollama_available = None
        self._gemini_available = None
        self._gemini_configured = False
        
    def check_ollama(self) -> bool:
        """Check if Ollama is available"""
        if self._ollama_available is not None:
            return self._ollama_available
        try:
            ollama = get_ollama()
            ollama.list()
            self._ollama_available = True
        except Exception:
            self._ollama_available = False
        return self._ollama_available
    
    def check_gemini(self) -> bool:
        """Check if Gemini API is available"""
        if self._gemini_available is not None:
            return self._gemini_available
        if not self.gemini_api_key:
            self._gemini_available = False
            return False
        try:
            genai = get_gemini()
            genai.configure(api_key=self.gemini_api_key)
            self._gemini_configured = True
            self._gemini_available = True
        except Exception:
            self._gemini_available = False
        return self._gemini_available
    
    def get_language_instruction(self) -> str:
        """Get language instruction for AI prompts"""
        lang = get_current_language()
        if lang == "arabic":
            return "IMPORTANT: Respond entirely in Arabic (Ø§Ù„Ø¹Ø±Ø¨ - ). All analysis, recommendations, and insights must be in Arabic."
        return "Respond in English."
    
    def query_local(self, prompt: str, model: str = None) -> str:
        """Query local Ollama model"""
        try:
            ollama = get_ollama()
            lang_instruction = self.get_language_instruction()
            full_prompt = f"{lang_instruction}\n\n{prompt}"
            
            # Auto-detect available model if not specified
            if model is None:
                try:
                    models = ollama.list()
                    if models and models.get('models'):
                        model = models['models'][0]['name']
                        logger.info(f"Using Ollama model: {model}")
                    else:
                        logger.warning("No Ollama models available")
                        return None
                except Exception:
                    model = "mistral"  # Default to mistral since it is installed
            
            response = ollama.chat(model=model, messages=[
                {"role": "system", "content": "You are an expert business data scientist and consultant. Provide actionable insights based on data analysis."},
                {"role": "user", "content": full_prompt}
            ])
            return response['message']['content']
        except Exception as e:
            logger.error(f"Ollama error: {e}")
            return None
    
    def query_gemini(self, prompt: str) -> str:
        """Query Google Gemini API with rate limit handling"""
        import time
        
        max_retries = 3
        base_delay = 5  # Start with 5 seconds delay
        
        for attempt in range(max_retries):
            try:
                genai = get_gemini()
                if not self._gemini_configured:
                    genai.configure(api_key=self.gemini_api_key)
                    self._gemini_configured = True
                
                model = genai.GenerativeModel('gemini-2.5-flash')
                
                lang_instruction = self.get_language_instruction()
                
                # Determine business type context from prompt content or defaults
                business_context = "This is a general retail business."
                if "menu" in prompt.lower() or "ingredient" in prompt.lower() or "recipe" in prompt.lower():
                    business_context = "This is a Restaurant/Cafe. Focus on menu engineering, food cost, and table turnover."
                
                full_prompt = f"""{lang_instruction}
                
                ROLE & CONTEXT:
                You are an expert business consultant. {business_context}
                
                YOUR TASK:
                Analyze the data providing actionable insights specific to this business type.
                
                {prompt}
                
                SPECIAL REQUIREMENTS:
                1. TRENDY PRODUCTS: Suggest 3 specific, trending products/menu items they should ADD right now based on current market trends.
                2. RISK MITIGATION: For every risk identified, provide a concrete 'Best Solution' to mitigate it.
                """
                
                # Add delay before request to respecting rate limits
                if attempt > 0:
                    time.sleep(base_delay * attempt)
                
                response = model.generate_content(full_prompt)
                return response.text
                
            except Exception as e:
                error_str = str(e).lower()
                if "429" in error_str or "quota" in error_str:
                    logger.warning(f"Gemini quota exceeded (Attempt {attempt+1}/{max_retries}). Retrying in {base_delay * (attempt + 1)}s...")
                    time.sleep(base_delay * (attempt + 1))
                else:
                    logger.error(f"Gemini error: {e}")
                    return None
        
        return None
    
    def query(self, prompt: str) -> str:
        """Query the active model - tries Gemini first if API key available, then Ollama"""
        import time
        
        # Add small delay between queries to avoid hitting rate limits immediately
        time.sleep(2)
        
        # Try Gemini first if configured (faster than local)
        if self.gemini_api_key and (self.active_model == "gemini" or self.active_model == "auto"):
            try:
                result = self.query_gemini(prompt)
                if result:
                    return result
            except Exception as e:
                logger.warning(f"Gemini failed, trying local: {e}")
        
        # Try local Ollama
        if self.active_model != "gemini":
            try:
                if self.check_ollama():
                    # Fallback for rate limits
                    logger.info("Falling back to local Ollama model due to API limit/error")
                    result = self.query_local(prompt)
                    if result:
                        return result
            except Exception as e:
                logger.warning(f"Ollama failed: {e}")
        
        # Final attempt with Gemini (with longer delay)
        if self.gemini_api_key and self.active_model == "local":
            try:
                time.sleep(5)
                result = self.query_gemini(prompt)
                if result:
                    return result
            except Exception:
                pass
        
        return None


class AdvancedBusinessAI:
    """
    Advanced AI Data Scientist for POS System
    Provides comprehensive business analysis and recommendations
    """
    
    def __init__(self, db_session_factory, gemini_api_key: str = None):
        self.get_db = db_session_factory
        self.model_manager = AIModelManager(gemini_api_key)
        self.results = {}
        self.progress_callback: Optional[Callable] = None
        self._business_type = None
        
    def set_progress_callback(self, callback: Callable):
        self.progress_callback = callback
        
    def _update_progress(self, stage: str, percent: int):
        if self.progress_callback:
            self.progress_callback(stage, percent)
            
    def _clear_memory(self):
        gc.collect()
    
    def set_model(self, model: str):
        """Set active model: 'local', 'gemini', or 'auto'"""
        self.model_manager.active_model = model
    
    def get_business_type(self) -> str:
        """Fetch business type from store settings"""
        if self._business_type:
            return self._business_type
        try:
            from models.models import StoreSettings
            with self.get_db() as db:
                settings = db.query(StoreSettings).first()
                if settings and settings.business_type:
                    self._business_type = settings.business_type
                    return self._business_type
        except Exception as e:
            logger.warning(f"Could not fetch business type: {e}")
        return "general retail business"

    # ============ MODULE 1: WASTE DETECTION ============
    def analyze_waste_detection(self) -> Dict[str, Any]:
        """Detect ingredient waste patterns"""
        self._update_progress(t("waste_detection"), 0)
        logger.info("Starting Waste Detection analysis...")
        
        try:
            from models.models import Ingredient, IngredientStockMovement, RecipeItem, ProductSale, Product
            
            with self.get_db() as db:
                ingredients = db.query(Ingredient).all()
                
                waste_data = []
                total_waste_cost = 0
                
                for ing in ingredients:
                    # Get wastage movements
                    wastage = db.query(IngredientStockMovement).filter_by(
                        ingredient_id=ing.id,
                        movement_type='wastage'
                    ).all()
                    
                    waste_qty = sum(abs(w.quantity) for w in wastage)
                    waste_cost = waste_qty * (ing.cost_per_unit or 0)
                    total_waste_cost += waste_cost
                    
                    # Get total usage
                    usage = db.query(IngredientStockMovement).filter_by(
                        ingredient_id=ing.id,
                        movement_type='usage'
                    ).all()
                    total_usage = sum(abs(u.quantity) for u in usage)
                    
                    # Calculate waste percentage
                    waste_pct = (waste_qty / (total_usage + waste_qty) * 100) if (total_usage + waste_qty) > 0 else 0
                    
                    if waste_qty > 0:
                        waste_data.append({
                            'id': ing.id,
                            'name': ing.name,
                            'unit': ing.unit,
                            'waste_quantity': round(waste_qty, 2),
                            'waste_cost': round(waste_cost, 2),
                            'waste_percentage': round(waste_pct, 1),
                            'total_usage': round(total_usage, 2),
                            'status': 'critical' if waste_pct > 15 else 'warning' if waste_pct > 8 else 'normal'
                        })
            
            self._update_progress(t("waste_detection"), 70)
            
            # Sort by waste cost (highest first)
            waste_data = sorted(waste_data, key=lambda x: x['waste_cost'], reverse=True)
            
            # Generate AI recommendations if significant waste
            recommendations = []
            if total_waste_cost > 100:
                prompt = f"""Analyze this ingredient waste data and provide 3-5 specific actionable recommendations:
                
Total Waste Cost: {total_waste_cost:.2f} EGP
Top Waste Items:
{json.dumps(waste_data[:5], indent=2)}

Provide brief, actionable recommendations to reduce waste."""

                ai_response = self.model_manager.query(prompt)
                if ai_response:
                    recommendations = [ai_response]
            
            result = {
                'waste_items': waste_data[:10],
                'total_waste_cost': round(total_waste_cost, 2),
                'critical_count': len([w for w in waste_data if w['status'] == 'critical']),
                'recommendations': recommendations,
                'summary': f"{t('analyzed')} {len(waste_data)} {t('ingredients')}. {t('total_waste')}: {total_waste_cost:.2f} EGP"
            }
            
            self._update_progress(t("waste_detection"), 100)
            self.results['waste_detection'] = result
            return result
            
        except Exception as e:
            logger.error(f"Waste Detection error: {e}")
            return {'waste_items': [], 'error': str(e)}

    # ============ MODULE 2: BEST SELLERS ============
    def analyze_best_sellers(self) -> Dict[str, Any]:
        """Identify best selling products and trends"""
        self._update_progress(t("best_sellers"), 0)
        logger.info("Starting Best Sellers analysis...")
        
        try:
            from models.models import Product, ProductSale
            
            with self.get_db() as db:
                products = db.query(Product).all()
                sales = db.query(ProductSale).all()
                
                # Aggregate sales per product
                product_sales = defaultdict(lambda: {'qty': 0, 'revenue': 0, 'orders': 0})
                
                for sale in sales:
                    if sale.products:
                        prods = sale.products
                        if isinstance(prods, str):
                            try:
                                prods = json.loads(prods)
                            except Exception:
                                continue
                        if not isinstance(prods, list):
                            continue
                        for item in prods:
                            if not isinstance(item, dict):
                                continue
                            pid = item.get('id') or item.get('product_id')
                            qty = item.get('quantity', 1)
                            price = item.get('price', 0)
                            
                            product_sales[pid]['qty'] += qty
                            product_sales[pid]['revenue'] += qty * price
                            product_sales[pid]['orders'] += 1
                
                # Build product data
                product_data = []
                for product in products:
                    sales_data = product_sales.get(product.id, {'qty': 0, 'revenue': 0, 'orders': 0})
                    product_data.append({
                        'id': product.id,
                        'name': product.title,
                        'category': product.category,
                        'price': product.price or 0,
                        'units_sold': sales_data['qty'],
                        'revenue': round(sales_data['revenue'], 2),
                        'order_count': sales_data['orders'],
                        'avg_per_order': round(sales_data['qty'] / sales_data['orders'], 1) if sales_data['orders'] > 0 else 0
                    })
            
            self._update_progress(t("best_sellers"), 60)
            
            # Sort by units sold
            by_units = sorted(product_data, key=lambda x: x['units_sold'], reverse=True)
            # Sort by revenue
            by_revenue = sorted(product_data, key=lambda x: x['revenue'], reverse=True)
            
            # Category breakdown
            category_sales = defaultdict(lambda: {'qty': 0, 'revenue': 0})
            for p in product_data:
                cat = p['category'] or 'Uncategorized'
                category_sales[cat]['qty'] += p['units_sold']
                category_sales[cat]['revenue'] += p['revenue']
            
            categories = [{'name': k, 'units': v['qty'], 'revenue': round(v['revenue'], 2)} 
                         for k, v in category_sales.items()]
            categories = sorted(categories, key=lambda x: x['revenue'], reverse=True)
            
            total_revenue = sum(p['revenue'] for p in product_data)
            total_units = sum(p['units_sold'] for p in product_data)
            
            result = {
                'top_by_units': by_units[:10],
                'top_by_revenue': by_revenue[:10],
                'categories': categories[:5],
                'total_revenue': round(total_revenue, 2),
                'total_units': total_units,
                'summary': f"{t('top_seller')}: {by_units[0]['name'] if by_units else 'N/A'} ({by_units[0]['units_sold'] if by_units else 0} {t('units')})"
            }
            
            self._update_progress(t("best_sellers"), 100)
            self.results['best_sellers'] = result
            return result
            
        except Exception as e:
            logger.error(f"Best Sellers error: {e}")
            return {'top_by_units': [], 'error': str(e)}

    # ============ MODULE 3: IMPROVEMENT RECOMMENDATIONS ============
    def generate_recommendations(self) -> Dict[str, Any]:
        """Generate AI-powered improvement recommendations"""
        self._update_progress(t("recommendations"), 0)
        logger.info("Generating Improvement Recommendations...")
        
        try:
            # Gather context from other analyses
            context_parts = []
            
            if 'waste_detection' in self.results:
                wd = self.results['waste_detection']
                context_parts.append(f"Waste Analysis: Total waste cost {wd.get('total_waste_cost', 0):.2f} EGP")
            
            if 'best_sellers' in self.results:
                bs = self.results['best_sellers']
                context_parts.append(f"Sales: Total revenue {bs.get('total_revenue', 0):.2f} EGP, {bs.get('total_units', 0)} units sold")
            
            if 'menu_engineering' in self.results:
                me = self.results['menu_engineering']
                context_parts.append(f"Menu: {len(me.get('stars', []))} stars, {len(me.get('dogs', []))} dogs")
            
            self._update_progress(t("recommendations"), 30)
            
            prompt = f"""As a business consultant, analyze this POS business data and provide 5-7 specific, actionable improvement recommendations:

Business Context:
{chr(10).join(context_parts)}

Provide recommendations in these categories:
1. Revenue Growth
2. Cost Reduction  
3. Customer Experience
4. Operational Efficiency
5. Menu/Product Optimization

Format each recommendation with a clear action and expected impact."""

            recommendations = []
            ai_response = self.model_manager.query(prompt)
            
            if ai_response:
                recommendations.append({
                    'source': 'ai',
                    'content': ai_response
                })
            else:
                # Fallback recommendations based on data
                if 'waste_detection' in self.results:
                    wd = self.results['waste_detection']
                    if wd.get('total_waste_cost', 0) > 100:
                        recommendations.append({
                            'source': 'system',
                            'category': t('cost_reduction'),
                            'title': t('reduce_ingredient_waste'),
                            'content': f"{t('waste_costing')} {wd['total_waste_cost']:.2f} EGP. {t('review_portions')}"
                        })
            
            self._update_progress(t("recommendations"), 100)
            
            result = {
                'recommendations': recommendations,
                'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
                'model_used': self.model_manager.active_model,
                'summary': f"{t('generated')} {len(recommendations)} {t('recommendations')}"
            }
            
            self.results['recommendations'] = result
            return result
            
        except Exception as e:
            logger.error(f"Recommendations error: {e}")
            return {'recommendations': [], 'error': str(e)}

    # ============ MODULE 4: SALES FORECAST ============
    def analyze_sales_forecast(self, days_ahead: int = 7) -> Dict[str, Any]:
        """Enhanced 7-day sales forecasting with Prophet"""
        self._update_progress(t("sales_forecast"), 0)
        logger.info("Starting Sales Forecast analysis...")
        
        try:
            from models.models import ProductSale
            pd = get_pandas()
            
            with self.get_db() as db:
                sales = db.query(ProductSale).order_by(ProductSale.date).all()
                logger.info(f"Found {len(sales)} sales records for forecasting")
                
                if len(sales) < 3:
                    result = {'forecast': [], 'summary': t('insufficient_data'), 'total_predicted': 0}
                    self.results['sales_forecast'] = result
                    self._update_progress(t("sales_forecast"), 100)
                    return result
                
                daily_sales = defaultdict(float)
                for sale in sales:
                    if sale.date:
                        date_key = sale.date.strftime('%Y-%m-%d')
                        daily_sales[date_key] += sale.total_amount or 0
            
            logger.info(f"Aggregated to {len(daily_sales)} unique days")
            self._update_progress(t("sales_forecast"), 30)
            
            # Try Prophet forecasting
            try:
                Prophet = get_prophet()
                
                df = pd.DataFrame([
                    {'ds': pd.to_datetime(date), 'y': total}
                    for date, total in daily_sales.items()
                ])
                df = df.sort_values('ds')
                
                if len(df) < 3:
                    # Use simple average instead
                    avg_daily = df['y'].mean()
                    forecast_list = []
                    for i in range(days_ahead):
                        future_date = datetime.now() + timedelta(days=i+1)
                        forecast_list.append({
                            'date': future_date.strftime('%Y-%m-%d'),
                            'day': future_date.strftime('%A'),
                            'predicted': round(avg_daily, 2),
                            'low': round(avg_daily * 0.7, 2),
                            'high': round(avg_daily * 1.3, 2)
                        })
                    total_predicted = avg_daily * days_ahead
                else:
                    model = Prophet(
                        yearly_seasonality=False,
                        weekly_seasonality=True if len(df) >= 7 else False,
                        daily_seasonality=False,
                        uncertainty_samples=50,
                        changepoint_prior_scale=0.05
                    )
                    
                    self._update_progress(t("sales_forecast"), 50)
                    model.fit(df)
                    
                    self._update_progress(t("sales_forecast"), 70)
                    
                    future = model.make_future_dataframe(periods=days_ahead)
                    forecast = model.predict(future)
                    
                    last_date = df['ds'].max()
                    future_forecast = forecast[forecast['ds'] > last_date][['ds', 'yhat', 'yhat_lower', 'yhat_upper']]
                    
                    forecast_list = []
                    for _, row in future_forecast.iterrows():
                        forecast_list.append({
                            'date': row['ds'].strftime('%Y-%m-%d'),
                            'day': row['ds'].strftime('%A'),
                            'predicted': round(max(0, row['yhat']), 2),
                            'low': round(max(0, row['yhat_lower']), 2),
                            'high': round(row['yhat_upper'], 2)
                        })
                    
                    total_predicted = sum(f['predicted'] for f in forecast_list)
            
            except ImportError:
                logger.warning("Prophet not installed, using day-of-week average forecast")
                # Group historical sales by weekday (0=Mon..6=Sun)
                from datetime import date as _date
                weekday_totals = defaultdict(list)
                for date_str, total in daily_sales.items():
                    try:
                        d = datetime.strptime(date_str, '%Y-%m-%d')
                        weekday_totals[d.weekday()].append(total)
                    except Exception:
                        pass
                weekday_avg = {}
                for wd, vals in weekday_totals.items():
                    weekday_avg[wd] = sum(vals) / len(vals) if vals else 0
                overall_avg = sum(daily_sales.values()) / len(daily_sales) if daily_sales else 0
                forecast_list = []
                for i in range(days_ahead):
                    future_date = datetime.now() + timedelta(days=i+1)
                    wd = future_date.weekday()
                    day_avg = weekday_avg.get(wd, overall_avg) or overall_avg
                    forecast_list.append({
                        'date': future_date.strftime('%Y-%m-%d'),
                        'day': future_date.strftime('%A'),
                        'predicted': round(day_avg, 2),
                        'low': round(day_avg * 0.7, 2),
                        'high': round(day_avg * 1.3, 2)
                    })
                total_predicted = sum(f['predicted'] for f in forecast_list)
            
            avg_daily = total_predicted / days_ahead if days_ahead > 0 else 0
            
            # Find trends
            best_day = max(forecast_list, key=lambda x: x['predicted']) if forecast_list else None
            worst_day = min(forecast_list, key=lambda x: x['predicted']) if forecast_list else None
            
            result = {
                'forecast': forecast_list,
                'total_predicted': round(total_predicted, 2),
                'avg_daily': round(avg_daily, 2),
                'best_day': best_day,
                'worst_day': worst_day,
                'summary': f"{t('predicted')} {total_predicted:.2f} EGP ({days_ahead} {t('days')})"
            }
            
            logger.info(f"Forecast complete: {total_predicted:.2f} EGP predicted")
            self._update_progress(t("sales_forecast"), 100)
            self._clear_memory()
            self.results['sales_forecast'] = result
            return result
            
        except Exception as e:
            logger.error(f"Sales Forecast error: {e}")
            import traceback
            traceback.print_exc()
            result = {'forecast': [], 'error': str(e), 'total_predicted': 0, 'summary': f"Error: {str(e)}"}
            self.results['sales_forecast'] = result
            return result

    # ============ MODULE 5: FRAUD DETECTION ============
    def analyze_fraud_detection(self) -> Dict[str, Any]:
        """Enhanced fraud pattern detection"""
        self._update_progress(t("fraud_watch"), 0)
        logger.info("Starting Fraud Detection analysis...")
        
        try:
            from models.models import AuditLog, User, ProductSale, Refund
            
            with self.get_db() as db:
                cutoff = datetime.now() - timedelta(days=30)
                
                # Suspicious audit actions
                suspicious_actions = db.query(AuditLog).filter(
                    AuditLog.timestamp >= cutoff,
                    AuditLog.action.in_(['void', 'discount', 'refund', 'price_override', 'delete_sale'])
                ).all()
                
                # Refund analysis
                refunds = db.query(Refund).filter(Refund.refund_date >= cutoff).all()
                
                # Analyze per user
                user_stats = defaultdict(lambda: {
                    'voids': 0, 'discounts': 0, 'refunds': 0, 
                    'overrides': 0, 'total_refund_amount': 0
                })
                
                for action in suspicious_actions:
                    uid = action.user_id or 0
                    if action.action == 'void':
                        user_stats[uid]['voids'] += 1
                    elif action.action == 'discount':
                        user_stats[uid]['discounts'] += 1
                    elif action.action == 'refund':
                        user_stats[uid]['refunds'] += 1
                    elif action.action == 'price_override':
                        user_stats[uid]['overrides'] += 1
                
                for refund in refunds:
                    # Find user who processed
                    user = db.query(User).filter_by(name=refund.processed_by).first()
                    uid = user.id if user else 0
                    user_stats[uid]['total_refund_amount'] += refund.refund_amount or 0
                
                # Get user names and calculate risk scores
                alerts = []
                for uid, stats in user_stats.items():
                    user = db.query(User).filter_by(id=uid).first() if uid else None
                    user_name = user.name if user else t('unknown')
                    
                    # Calculate risk score
                    total_actions = stats['voids'] + stats['discounts'] + stats['refunds'] + stats['overrides']
                    risk_score = (
                        stats['voids'] * 3 +
                        stats['discounts'] * 1 +
                        stats['refunds'] * 2 +
                        stats['overrides'] * 4 +
                        (stats['total_refund_amount'] / 100)
                    )
                    
                    if total_actions > 3 or risk_score > 10:
                        alerts.append({
                            'user_id': uid,
                            'user_name': user_name,
                            'voids': stats['voids'],
                            'discounts': stats['discounts'],
                            'refunds': stats['refunds'],
                            'overrides': stats['overrides'],
                            'refund_amount': round(stats['total_refund_amount'], 2),
                            'risk_score': round(risk_score, 1),
                            'risk_level': 'high' if risk_score > 20 else 'medium' if risk_score > 10 else 'low'
                        })
            
            self._update_progress(t("fraud_watch"), 70)
            
            alerts = sorted(alerts, key=lambda x: x['risk_score'], reverse=True)
            high_risk = [a for a in alerts if a['risk_level'] == 'high']
            
            result = {
                'alerts': alerts[:10],
                'high_risk_count': len(high_risk),
                'total_suspicious_actions': len(suspicious_actions),
                'status': 'critical' if len(high_risk) > 0 else 'warning' if len(alerts) > 0 else 'clear',
                'summary': f"{len(high_risk)} {t('high_risk')}, {len(alerts)} {t('total_alerts')}"
            }
            
            self._update_progress(t("fraud_watch"), 100)
            self.results['fraud_watch'] = result
            return result
            
        except Exception as e:
            logger.error(f"Fraud Detection error: {e}")
            return {'alerts': [], 'error': str(e)}

    # ============ MODULE 6: CUSTOMER RETENTION ============
    def analyze_customer_retention(self, churn_days: int = 14) -> Dict[str, Any]:
        """Enhanced customer retention analysis"""
        self._update_progress(t("customer_retention"), 0)
        logger.info("Starting Customer Retention analysis...")
        
        try:
            from models.models import ProductSale, Customer
            
            with self.get_db() as db:
                sales = db.query(ProductSale).filter(ProductSale.customer.isnot(None)).all()
                
                # Build customer lookup dict with just the data we need (not ORM objects)
                customers_db = {}
                for c in db.query(Customer).all():
                    customers_db[c.name] = {
                        'phone': c.phone,
                        'loyalty_points': c.loyalty_points if hasattr(c, 'loyalty_points') else 0
                    }
                
                customer_data = defaultdict(lambda: {
                    'visits': 0, 'last_visit': None, 'first_visit': None,
                    'total_spent': 0, 'items_purchased': 0
                })
                
                for sale in sales:
                    if sale.customer and sale.customer.strip():
                        name = sale.customer.strip()
                        customer_data[name]['visits'] += 1
                        customer_data[name]['total_spent'] += sale.total_amount or 0
                        customer_data[name]['items_purchased'] += sale.total_items or 0
                        
                        if sale.date:
                            if not customer_data[name]['last_visit'] or sale.date > customer_data[name]['last_visit']:
                                customer_data[name]['last_visit'] = sale.date
                            if not customer_data[name]['first_visit'] or sale.date < customer_data[name]['first_visit']:
                                customer_data[name]['first_visit'] = sale.date
            
            self._update_progress(t("customer_retention"), 50)
            
            cutoff_date = datetime.now() - timedelta(days=churn_days)
            
            churn_risks = []
            loyal_customers = []
            new_customers = []
            
            for name, data in customer_data.items():
                customer_record = customers_db.get(name, {})
                
                customer_info = {
                    'name': name,
                    'visits': data['visits'],
                    'total_spent': round(data['total_spent'], 2),
                    'avg_ticket': round(data['total_spent'] / data['visits'], 2) if data['visits'] > 0 else 0,
                    'last_visit': data['last_visit'].strftime('%Y-%m-%d') if data['last_visit'] else None,
                    'days_inactive': (datetime.now() - data['last_visit']).days if data['last_visit'] else 999,
                    'phone': customer_record.get('phone'),
                    'loyalty_points': customer_record.get('loyalty_points', 0)
                }
                
                # Classify customer
                if data['visits'] >= 3:  # Regular customer
                    if data['last_visit'] and data['last_visit'] < cutoff_date:
                        churn_risks.append(customer_info)
                    else:
                        loyal_customers.append(customer_info)
                elif data['first_visit'] and (datetime.now() - data['first_visit']).days <= 30:
                    new_customers.append(customer_info)
            
            churn_risks = sorted(churn_risks, key=lambda x: x['total_spent'], reverse=True)[:20]
            loyal_customers = sorted(loyal_customers, key=lambda x: x['total_spent'], reverse=True)[:10]
            
            total_at_risk_value = sum(c['total_spent'] for c in churn_risks)
            
            result = {
                'churn_risks': churn_risks,
                'loyal_customers': loyal_customers,
                'new_customers': new_customers[:10],
                'total_at_risk': len(churn_risks),
                'total_at_risk_value': round(total_at_risk_value, 2),
                'churn_threshold_days': churn_days,
                'summary': f"{len(churn_risks)} {t('at_risk')}, {total_at_risk_value:.2f} EGP {t('revenue_at_risk')}"
            }
            
            self._update_progress(t("customer_retention"), 100)
            self.results['customer_retention'] = result
            return result
            
        except Exception as e:
            logger.error(f"Customer Retention error: {e}")
            return {'churn_risks': [], 'error': str(e)}

    # ============ MODULE 7: ADVANCED MENU ENGINEERING ============
    def analyze_menu_engineering(self) -> Dict[str, Any]:
        """Advanced menu engineering with profitability analysis"""
        self._update_progress(t("menu_engineering"), 0)
        logger.info("Starting Advanced Menu Engineering analysis...")
        
        try:
            from models.models import Product, ProductSale, RecipeItem, Ingredient
            pd = get_pandas()
            
            with self.get_db() as db:
                products = db.query(Product).all()
                
                product_data = []
                for product in products:
                    # Calculate food cost from recipe
                    cost = 0
                    recipe_items = db.query(RecipeItem).filter_by(product_id=product.id).all()
                    for ri in recipe_items:
                        ingredient = db.query(Ingredient).filter_by(id=ri.ingredient_id).first()
                        if ingredient:
                            cost += ri.quantity_needed * (ingredient.cost_per_unit or 0)
                    
                    # Get sales data
                    sales = db.query(ProductSale).all()
                    total_sold = 0
                    for sale in sales:
                        if sale.products:
                            prods = sale.products
                            if isinstance(prods, str):
                                try:
                                    prods = json.loads(prods)
                                except Exception:
                                    continue
                            if not isinstance(prods, list):
                                continue
                            for item in prods:
                                if not isinstance(item, dict):
                                    continue
                                if item.get('id') == product.id or item.get('name') == product.title:
                                    total_sold += item.get('quantity', 0)
                    
                    price = product.price or 0
                    margin = price - cost
                    margin_pct = (margin / price * 100) if price > 0 else 0
                    food_cost_pct = (cost / price * 100) if price > 0 else 0
                    
                    product_data.append({
                        'id': product.id,
                        'name': product.title,
                        'category': product.category,
                        'price': price,
                        'cost': round(cost, 2),
                        'margin': round(margin, 2),
                        'margin_pct': round(margin_pct, 1),
                        'food_cost_pct': round(food_cost_pct, 1),
                        'popularity': total_sold,
                        'revenue': round(total_sold * price, 2),
                        'profit': round(total_sold * margin, 2)
                    })
            
            self._update_progress(t("menu_engineering"), 50)
            
            if not product_data:
                return {'stars': [], 'dogs': [], 'summary': t('no_product_data')}
            
            df = pd.DataFrame(product_data)
            avg_margin = df['margin'].median()
            avg_popularity = df['popularity'].median()
            
            # Classify items
            stars = []       # High margin, high popularity
            dogs = []        # Low margin, low popularity
            plowhorses = []  # Low margin, high popularity
            puzzles = []     # High margin, low popularity
            
            for _, row in df.iterrows():
                item = row.to_dict()
                if row['margin'] >= avg_margin and row['popularity'] >= avg_popularity:
                    item['classification'] = 'star'
                    stars.append(item)
                elif row['margin'] < avg_margin and row['popularity'] < avg_popularity:
                    item['classification'] = 'dog'
                    dogs.append(item)
                elif row['margin'] < avg_margin and row['popularity'] >= avg_popularity:
                    item['classification'] = 'plowhorse'
                    plowhorses.append(item)
                else:
                    item['classification'] = 'puzzle'
                    puzzles.append(item)
            
            # Calculate totals
            total_revenue = sum(p['revenue'] for p in product_data)
            total_profit = sum(p['profit'] for p in product_data)
            avg_food_cost = sum(p['food_cost_pct'] for p in product_data) / len(product_data) if product_data else 0
            
            result = {
                'stars': sorted(stars, key=lambda x: x['profit'], reverse=True)[:10],
                'dogs': sorted(dogs, key=lambda x: x['profit'])[:10],
                'plowhorses': sorted(plowhorses, key=lambda x: x['popularity'], reverse=True)[:10],
                'puzzles': sorted(puzzles, key=lambda x: x['margin'], reverse=True)[:10],
                'total_products': len(product_data),
                'total_revenue': round(total_revenue, 2),
                'total_profit': round(total_profit, 2),
                'avg_food_cost_pct': round(avg_food_cost, 1),
                'summary': f"{len(stars)} {t('stars')}, {len(dogs)} {t('dogs')}, {len(plowhorses)} {t('plowhorses')}, {len(puzzles)} {t('puzzles')}"
            }
            
            self._update_progress(t("menu_engineering"), 100)
            self._clear_memory()
            self.results['menu_engineering'] = result
            return result
            
        except Exception as e:
            logger.error(f"Menu Engineering error: {e}")
            return {'stars': [], 'dogs': [], 'error': str(e)}

    # ============ EXECUTIVE SUMMARY ============
    def generate_executive_summary(self) -> str:
        """Generate AI-powered executive summary"""
        self._update_progress(t("ai_summary"), 0)
        logger.info("Generating Executive Summary...")
        
        try:
            # Build context from all analyses
            context = []
            
            if 'waste_detection' in self.results:
                wd = self.results['waste_detection']
                context.append(f"Waste: {wd.get('total_waste_cost', 0):.2f} EGP total waste cost")
            
            if 'best_sellers' in self.results:
                bs = self.results['best_sellers']
                top = bs.get('top_by_units', [{}])[0]
                context.append(f"Top Seller: {top.get('name', 'N/A')} with {top.get('units_sold', 0)} units")
            
            if 'sales_forecast' in self.results:
                sf = self.results['sales_forecast']
                context.append(f"7-Day Forecast: {sf.get('total_predicted', 0):.2f} EGP projected")
            
            if 'fraud_watch' in self.results:
                fw = self.results['fraud_watch']
                context.append(f"Security: {fw.get('high_risk_count', 0)} high-risk alerts")
            
            if 'customer_retention' in self.results:
                cr = self.results['customer_retention']
                context.append(f"Retention: {cr.get('total_at_risk', 0)} customers at risk ({cr.get('total_at_risk_value', 0):.2f} EGP)")
            
            if 'menu_engineering' in self.results:
                me = self.results['menu_engineering']
                context.append(f"Menu: {len(me.get('stars', []))} stars, {len(me.get('dogs', []))} dogs, Avg food cost: {me.get('avg_food_cost_pct', 0):.1f}%")
            
            self._update_progress(t("ai_summary"), 30)
            
            # Generate AI summary
            # Get business type for context
            business_type = self.get_business_type()
            lang = get_current_language()
            lang_name = "Arabic" if lang == "arabic" else "English"
            
            prompt = f"""You are an expert combining TWO roles for a business owner:

ROLE 1 - DATA ANALYST: Analyze patterns, trends, and anomalies in the data. Provide statistical insights.
ROLE 2 - BUSINESS DEVELOPER: Recommend growth strategies, market opportunities, and competitive advantages.

BUSINESS TYPE: {business_type}
LANGUAGE: Respond entirely in {lang_name}. {"All text must be in Arabic ." if lang == "arabic" else ""}

DATA SUMMARY:
{chr(10).join(context)}

Provide your analysis in this structure. DO NOT use asterisks (*) or markdown formatting. Use CAPITAL LETTERS for headers.

=======================================================
BUSINESS OVERVIEW
=======================================================
Write 2-3 sentences about the overall health of this {business_type}. Be honest but encouraging.

=======================================================
DATA ANALYSIS INSIGHTS
=======================================================
As a data analyst, explain:
- Key patterns you see in the sales and customer data
- Any concerning trends that need attention
- Comparison insights (top vs bottom performers)

=======================================================
BUSINESS DEVELOPMENT OPPORTUNITIES  
=======================================================
As a business developer, recommend:
- 2-3 growth strategies specific to a {business_type}
- Market positioning improvements
- Revenue diversification ideas

=======================================================
TRENDING PRODUCTS TO ADD
=======================================================
Based on current market trends for {business_type}, suggest 3 specific products/items they should consider adding to their menu/inventory RIGHT NOW. Be specific with names.

=======================================================
RISK MITIGATION SOLUTIONS
=======================================================
For each problem identified, provide a concrete solution:
- Problem  ->  Solution format
- Practical steps the owner can take

=======================================================
QUICK WINS (DO THIS TODAY)
=======================================================
3 specific actions they can complete in under 30 minutes today.

Keep the total response under 600 words. Be practical and actionable. Speak like a trusted advisor, not a corporate consultant."""

            ai_summary = self.model_manager.query(prompt)
            
            if not ai_summary:
                # Fallback summary
                ai_summary = self._generate_fallback_summary()
            
            self._update_progress(t("ai_summary"), 100)
            return ai_summary
            
        except Exception as e:
            logger.error(f"Executive Summary error: {e}")
            return f"{t('error_generating_summary')}: {str(e)}"
    
    def _generate_fallback_summary(self) -> str:
        """Generate comprehensive rule-based summary when AI unavailable"""
        lines = []
        lang = get_current_language()
        
        lines.append("=" * 55)
        lines.append(t("ai_executive_report"))
        lines.append("=" * 55)
        lines.append(f"{t('generated')}: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append("")
        
        # Health score
        score = self._calculate_health_score()
        health_label = "Excellent" if score >= 85 else "Good" if score >= 70 else "Needs Attention" if score >= 50 else "Critical"
        if lang == "arabic":
            health_label = "Excellent" if score >= 85 else "Good" if score >= 70 else "Needs Attention" if score >= 50 else "Critical"
        lines.append(f"{t('business_health')}: {score}/100 ({health_label})")
        lines.append("")
        
        # ------ KEY METRICS ------
        lines.append("=" * 55)
        header_metrics = "KEY METRICS" if lang != "arabic" else t("key_metrics")

        lines.append(header_metrics)
        lines.append("=" * 55)
        
        if 'waste_detection' in self.results:
            wd = self.results['waste_detection']
            waste_cost = wd.get('total_waste_cost', 0)
            lines.append(f"  {t('total_waste')}: {waste_cost:.2f} EGP")
            if waste_cost > 500:
                warn = "ACTION REQUIRED: High waste detected!" if lang != "arabic" else t("action_required:_high_waste_detected!")

                lines.append(f"  ! {warn}")
        
        if 'best_sellers' in self.results:
            bs = self.results['best_sellers']
            lines.append(f"  {t('total_revenue')}: {bs.get('total_revenue', 0):,.2f} EGP")
            lines.append(f"  Total Units Sold: {bs.get('total_units', 0):,}")
        
        if 'sales_forecast' in self.results:
            sf = self.results['sales_forecast']
            lines.append(f"  {t('forecast_7day')}: {sf.get('total_predicted', 0):,.2f} EGP")
            if sf.get('avg_daily', 0) > 0:
                lines.append(f"  Avg Daily Forecast: {sf['avg_daily']:,.2f} EGP")
        
        if 'fraud_watch' in self.results:
            fw = self.results['fraud_watch']
            lines.append(f"  {t('security_alerts')}: {fw.get('high_risk_count', 0)} {t('high_risk')}")
        
        lines.append("")
        
        # ------ TOP SELLERS ------
        if 'best_sellers' in self.results:
            bs = self.results['best_sellers']
            top_items = bs.get('top_by_units', [])[:5]
            if top_items:
                lines.append("=" * 55)
                header_top = "TOP 5 BEST SELLERS" if lang != "arabic" else t("top_5_best_sellers")

                lines.append(header_top)
                lines.append("=" * 55)
                for i, item in enumerate(top_items, 1):
                    lines.append(f"  #{i}  {item['name']}   -   {item.get('units_sold', 0)} units  |  {item.get('revenue', 0):,.0f} EGP")
                lines.append("")
            
            # Category breakdown
            cats = bs.get('categories', [])[:5]
            if cats:
                header_cat = "CATEGORY PERFORMANCE" if lang != "arabic" else t("category_performance")

                lines.append(header_cat)
                lines.append("=" * 55)
                for cat in cats:
                    lines.append(f"  {cat['name']}:  {cat.get('units', 0)} units  |  {cat.get('revenue', 0):,.0f} EGP")
                lines.append("")
        
        # ------ MENU ENGINEERING ------
        if 'menu_engineering' in self.results:
            me = self.results['menu_engineering']
            lines.append("=" * 55)
            header_menu = "MENU ENGINEERING ANALYSIS" if lang != "arabic" else t("menu_engineering_analysis")

            lines.append(header_menu)
            lines.append("=" * 55)
            
            stars = me.get('stars', [])
            dogs = me.get('dogs', [])
            plowhorses = me.get('plowhorses', [])
            puzzles = me.get('puzzles', [])
            
            lines.append(f"  Stars (High Profit + Popular): {len(stars)}")
            for s in stars[:3]:
                lines.append(f"    + {s['name']}  margin: {s.get('margin_pct', 0):.0f}%  sold: {s.get('popularity', 0)}")
            
            lines.append(f"  Dogs (Low Profit + Unpopular): {len(dogs)}")
            for d in dogs[:3]:
                lines.append(f"    - {d['name']}  margin: {d.get('margin_pct', 0):.0f}%  sold: {d.get('popularity', 0)}")
            
            if plowhorses:
                lines.append(f"  Plowhorses (Popular but Low Margin): {len(plowhorses)}")
                for p in plowhorses[:2]:
                    lines.append(f"    ~ {p['name']}  margin: {p.get('margin_pct', 0):.0f}%   -   Consider raising price")
            
            if puzzles:
                lines.append(f"  Puzzles (High Margin but Unpopular): {len(puzzles)}")
                for p in puzzles[:2]:
                    lines.append(f"    ? {p['name']}  margin: {p.get('margin_pct', 0):.0f}%   -   Needs more marketing")
            
            if me.get('avg_food_cost_pct', 0) > 0:
                lines.append(f"\n  Avg Food Cost: {me['avg_food_cost_pct']:.1f}%")
                if me['avg_food_cost_pct'] > 35:
                    lines.append("  ! Food cost is above industry average (30-35%). Review supplier pricing.")
            lines.append("")
        
        # ------ SALES FORECAST ------
        if 'sales_forecast' in self.results:
            sf = self.results['sales_forecast']
            forecast = sf.get('forecast', [])
            if forecast:
                lines.append("=" * 55)
                header_fc = "7-DAY SALES FORECAST" if lang != "arabic" else t("sales_forecast_7day")

                lines.append(header_fc)
                lines.append("=" * 55)
                for f in forecast[:7]:
                    bar_len = min(20, int(f['predicted'] / max(1, sf.get('avg_daily', 1)) * 10))
                    bar = "#" * bar_len
                    lines.append(f"  {f['day'][:3]}  {bar}  {f['predicted']:,.0f} EGP")
                
                best = sf.get('best_day')
                worst = sf.get('worst_day')
                if best:
                    lines.append(f"\n  Best Day: {best.get('day', 'N/A')} ({best.get('predicted', 0):,.0f} EGP)")
                if worst:
                    lines.append(f"  Slowest Day: {worst.get('day', 'N/A')} ({worst.get('predicted', 0):,.0f} EGP)")
                lines.append("")
        
        # ------ CUSTOMER RETENTION ------
        if 'customer_retention' in self.results:
            cr = self.results['customer_retention']
            at_risk = cr.get('total_at_risk', 0)
            if at_risk > 0:
                lines.append("=" * 55)
                header_cr = "CUSTOMER RETENTION ALERTS" if lang != "arabic" else t("customer_retention_alerts")

                lines.append(header_cr)
                lines.append("=" * 55)
                lines.append(f"  {at_risk} customers at risk ({cr.get('total_at_risk_value', 0):,.2f} EGP at stake)")
                for c in cr.get('churn_risks', [])[:3]:
                    lines.append(f"    {c['name']}   -   {c.get('days_inactive', 0)} days inactive  |  {c.get('total_spent', 0):,.0f} EGP lifetime")
                lines.append("")
        
        # ------ RECOMMENDATIONS ------
        lines.append("=" * 55)
        header_rec = "RECOMMENDATIONS & QUICK WINS" if lang != "arabic" else t("recommendations_quick_wins")

        lines.append(header_rec)
        lines.append("=" * 55)
        
        rec_num = 1
        
        # Data-driven recommendations
        if 'waste_detection' in self.results:
            wd = self.results['waste_detection']
            if wd.get('total_waste_cost', 0) > 100:
                lines.append(f"  {rec_num}. Reduce waste  -  costing you {wd['total_waste_cost']:.0f} EGP. Review portion sizes and stock rotation.")
                rec_num += 1
        
        if 'menu_engineering' in self.results:
            me = self.results['menu_engineering']
            dogs = me.get('dogs', [])
            plowhorses = me.get('plowhorses', [])
            if dogs:
                lines.append(f"  {rec_num}. Remove or rebrand {len(dogs)} underperforming items: {', '.join(d['name'] for d in dogs[:3])}")
                rec_num += 1
            if plowhorses:
                lines.append(f"  {rec_num}. Increase prices on popular low-margin items: {', '.join(p['name'] for p in plowhorses[:3])}")
                rec_num += 1
        
        if 'customer_retention' in self.results:
            cr = self.results['customer_retention']
            if cr.get('total_at_risk', 0) > 0:
                lines.append(f"  {rec_num}. Re-engage {cr['total_at_risk']} at-risk customers with loyalty offers or SMS campaigns.")
                rec_num += 1
        
        if 'fraud_watch' in self.results:
            fw = self.results['fraud_watch']
            if fw.get('high_risk_count', 0) > 0:
                lines.append(f"  {rec_num}. Review {fw['high_risk_count']} high-risk employee activity  -  implement manager approval for voids/refunds.")
                rec_num += 1
        
        # General recommendations if nothing else flagged
        if rec_num <= 2:
            lines.append(f"  {rec_num}. Your business is performing well! Focus on expanding your product range and marketing.")
            rec_num += 1
            lines.append(f"  {rec_num}. Consider implementing a loyalty program to increase repeat visits.")
            rec_num += 1
        
        # ------ TRENDING PRODUCTS ------
        business_type = self.get_business_type()
        lines.append("")
        lines.append("=" * 55)
        header_trend = "TRENDING PRODUCTS TO CONSIDER" if lang != "arabic" else t("trending_products")

        lines.append(header_trend)
        lines.append("=" * 55)
        
        bt = business_type.lower()
        if any(kw in bt for kw in ['restaurant', 'grill', 'food', 'kitchen']):
            lines.append("  1. Loaded fries / Truffle fries  -  high margin, trending on social media")
            lines.append("  2. Smash burgers  -  lower food cost, extremely popular")
            lines.append("  3. Fresh lemonades / Mojitos  -  high margin drinks, low cost")
        if any(kw in bt for kw in ['coffee', 'cafe']):
            lines.append("  1. Cold brew / Iced coffee variations  -  trending year-round")
            lines.append("  2. Matcha lattes  -  premium pricing, growing demand")
            lines.append("  3. Protein-infused drinks  -  health-conscious trend")
        if any(kw in bt for kw in ['pharmacy']):
            lines.append("  1. Vitamin D + Zinc combos  -  high demand supplements")
            lines.append("  2. Collagen supplements  -  growing beauty/health trend")
            lines.append("  3. First-aid travel kits  -  impulse buy, good margins")
        if any(kw in bt for kw in ['grocery', 'market']):
            lines.append("  1. Ready-to-eat meal kits  -  convenience trend")
            lines.append("  2. Organic/health food section  -  premium margins")
            lines.append("  3. Local artisan products  -  unique competitive advantage")
        else:
            lines.append("  1. Bundle deals / loyalty combos based on your top sellers")
            lines.append("  2. Seasonal limited-edition products for urgency")
            lines.append("  3. Complementary products to your best sellers")
        
        lines.append("")
        lines.append("=" * 55)
        note = "NOTE: Connect Gemini AI or Ollama for deeper, personalized insights." if lang != "arabic" else t("note:_connect_gemini_ai_or_ollama_for_deeper,_personalized_insights.")

        lines.append(note)
        lines.append("=" * 55)
        
        return "\n".join(lines)
    
    def _calculate_health_score(self) -> int:
        """Calculate business health score (0-100)"""
        score = 100
        
        if 'fraud_watch' in self.results:
            high_risk = self.results['fraud_watch'].get('high_risk_count', 0)
            score -= min(20, high_risk * 10)
        
        if 'waste_detection' in self.results:
            critical = self.results['waste_detection'].get('critical_count', 0)
            score -= min(15, critical * 5)
        
        if 'customer_retention' in self.results:
            at_risk = self.results['customer_retention'].get('total_at_risk', 0)
            score -= min(15, at_risk * 2)
        
        if 'menu_engineering' in self.results:
            dogs = len(self.results['menu_engineering'].get('dogs', []))
            if dogs > 5:
                score -= min(10, (dogs - 5) * 2)
        
        return max(0, score)

    # ============ FULL ANALYSIS ============
    def run_full_analysis(self) -> Dict[str, Any]:
        """Run all analysis modules sequentially"""
        logger.info("=" * 50)
        logger.info("STARTING FULL AI ANALYSIS")
        logger.info("=" * 50)
        
        self.results = {}
        
        # Module 1: Waste Detection
        self.analyze_waste_detection()
        gc.collect()
        
        # Module 2: Best Sellers
        self.analyze_best_sellers()
        gc.collect()
        
        # Module 3: Menu Engineering
        self.analyze_menu_engineering()
        gc.collect()
        
        # Module 4: Sales Forecast
        self.analyze_sales_forecast()
        gc.collect()
        
        # Module 5: Fraud Detection
        self.analyze_fraud_detection()
        gc.collect()
        
        # Module 6: Customer Retention
        self.analyze_customer_retention()
        gc.collect()
        
        # Module 7: Recommendations (uses other results)
        self.generate_recommendations()
        gc.collect()
        
        # Generate Executive Summary
        self.results['executive_summary'] = self.generate_executive_summary()
        self.results['analysis_timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.results['health_score'] = self._calculate_health_score()
        
        logger.info("=" * 50)
        logger.info("FULL AI ANALYSIS COMPLETE")
        logger.info("=" * 50)
        
        return self.results


# Factory functions
def create_advanced_ai(gemini_api_key: str = None):
    """Create AdvancedBusinessAI instance"""
    from controller import get_db
    return AdvancedBusinessAI(get_db, gemini_api_key)

def create_business_ai(gemini_api_key: str = None):
    """Alias for create_advanced_ai"""
    return create_advanced_ai(gemini_api_key)
