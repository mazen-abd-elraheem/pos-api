"""
services/payment_gateways.py - Payment Gateway Integration Layer

Provides abstraction for various payment gateways:
- Fawry
- Visa/Mastercard
- Talabat
- Tabby (Buy Now Pay Later)
"""

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass
from abc import ABC, abstractmethod
from datetime import datetime
import hashlib
import json

logger = logging.getLogger(__name__)


@dataclass
class PaymentResult:
    """Result of a payment operation"""
    success: bool
    transaction_id: Optional[str] = None
    message: str = ""
    gateway_response: Optional[Dict] = None
    amount: float = 0.0
    timestamp: Optional[datetime] = None


@dataclass
class RefundResult:
    """Result of a refund operation"""
    success: bool
    refund_id: Optional[str] = None
    message: str = ""
    amount: float = 0.0


class PaymentGateway(ABC):
    """Abstract base class for payment gateways"""
    
    def __init__(self, api_key: str = "", api_secret: str = "", merchant_id: str = ""):
        self.api_key = api_key
        self.api_secret = api_secret
        self.merchant_id = merchant_id
    
    @abstractmethod
    def process_payment(self, amount: float, reference: str, **kwargs) -> PaymentResult:
        """Process a payment"""
        pass
    
    @abstractmethod
    def verify_payment(self, transaction_id: str) -> bool:
        """Verify if a payment was successful"""
        pass
    
    @abstractmethod
    def refund(self, transaction_id: str, amount: float) -> RefundResult:
        """Refund a payment"""
        pass
    
    @abstractmethod
    def get_gateway_name(self) -> str:
        """Get the gateway name"""
        pass


class ManualPaymentGateway(PaymentGateway):
    """Manual/Cash payments (no gateway integration needed)"""
    
    def process_payment(self, amount: float, reference: str, **kwargs) -> PaymentResult:
        return PaymentResult(
            success=True,
            transaction_id=f"CASH-{reference}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            message="Cash payment recorded",
            amount=amount,
            timestamp=datetime.now()
        )
    
    def verify_payment(self, transaction_id: str) -> bool:
        return True  # Cash is always verified
    
    def refund(self, transaction_id: str, amount: float) -> RefundResult:
        return RefundResult(
            success=True,
            refund_id=f"REFUND-{transaction_id}",
            message="Cash refund processed",
            amount=amount
        )
    
    def get_gateway_name(self) -> str:
        return "Manual/Cash"


class FawryGateway(PaymentGateway):
    """Fawry payment gateway integration (Egypt)"""
    
    SANDBOX_URL = "https://atfawry.fawrystaging.com"
    PRODUCTION_URL = "https://www.atfawry.com"
    
    def __init__(self, api_key: str = "", api_secret: str = "", merchant_id: str = "", sandbox: bool = True):
        super().__init__(api_key, api_secret, merchant_id)
        self.base_url = self.SANDBOX_URL if sandbox else self.PRODUCTION_URL
    
    def process_payment(self, amount: float, reference: str, **kwargs) -> PaymentResult:
        """Process Fawry payment"""
        try:
            # In production, this would make an API call to Fawry
            # For now, we log the attempt and return a placeholder
            logger.info(f"Fawry payment request: {amount} EGP, ref: {reference}")
            
            # Placeholder for actual API integration
            return PaymentResult(
                success=True,
                transaction_id=f"FAWRY-{reference}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                message="Fawry payment initiated (integration pending)",
                amount=amount,
                timestamp=datetime.now()
            )
        except Exception as e:
            logger.error(f"Fawry payment error: {e}")
            return PaymentResult(success=False, message=str(e))
    
    def verify_payment(self, transaction_id: str) -> bool:
        """Verify Fawry payment status"""
        logger.info(f"Verifying Fawry payment: {transaction_id}")
        return True  # Placeholder
    
    def refund(self, transaction_id: str, amount: float) -> RefundResult:
        """Process Fawry refund"""
        logger.info(f"Fawry refund request: {transaction_id}, amount: {amount}")
        return RefundResult(
            success=True,
            refund_id=f"FAWRY-REFUND-{transaction_id}",
            message="Fawry refund initiated",
            amount=amount
        )
    
    def get_gateway_name(self) -> str:
        return "Fawry"


class VisaGateway(PaymentGateway):
    """Visa/Mastercard payment gateway (generic card processing)"""
    
    def process_payment(self, amount: float, reference: str, **kwargs) -> PaymentResult:
        """Process card payment"""
        try:
            logger.info(f"Card payment request: {amount}, ref: {reference}")
            
            return PaymentResult(
                success=True,
                transaction_id=f"CARD-{reference}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                message="Card payment initiated (integration pending)",
                amount=amount,
                timestamp=datetime.now()
            )
        except Exception as e:
            logger.error(f"Card payment error: {e}")
            return PaymentResult(success=False, message=str(e))
    
    def verify_payment(self, transaction_id: str) -> bool:
        logger.info(f"Verifying card payment: {transaction_id}")
        return True
    
    def refund(self, transaction_id: str, amount: float) -> RefundResult:
        logger.info(f"Card refund request: {transaction_id}, amount: {amount}")
        return RefundResult(
            success=True,
            refund_id=f"CARD-REFUND-{transaction_id}",
            message="Card refund initiated",
            amount=amount
        )
    
    def get_gateway_name(self) -> str:
        return "Visa/Mastercard"


class TalabatGateway(PaymentGateway):
    """Talabat payment integration"""
    
    def process_payment(self, amount: float, reference: str, **kwargs) -> PaymentResult:
        """Process Talabat payment"""
        try:
            logger.info(f"Talabat payment request: {amount}, ref: {reference}")
            
            return PaymentResult(
                success=True,
                transaction_id=f"TALABAT-{reference}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                message="Talabat payment recorded",
                amount=amount,
                timestamp=datetime.now()
            )
        except Exception as e:
            logger.error(f"Talabat payment error: {e}")
            return PaymentResult(success=False, message=str(e))
    
    def verify_payment(self, transaction_id: str) -> bool:
        return True
    
    def refund(self, transaction_id: str, amount: float) -> RefundResult:
        return RefundResult(
            success=True,
            refund_id=f"TALABAT-REFUND-{transaction_id}",
            message="Talabat refund processed",
            amount=amount
        )
    
    def get_gateway_name(self) -> str:
        return "Talabat"


class TabbyGateway(PaymentGateway):
    """Tabby Buy Now Pay Later integration"""
    
    def process_payment(self, amount: float, reference: str, **kwargs) -> PaymentResult:
        """Process Tabby payment"""
        try:
            logger.info(f"Tabby payment request: {amount}, ref: {reference}")
            
            return PaymentResult(
                success=True,
                transaction_id=f"TABBY-{reference}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                message="Tabby payment initiated",
                amount=amount,
                timestamp=datetime.now()
            )
        except Exception as e:
            logger.error(f"Tabby payment error: {e}")
            return PaymentResult(success=False, message=str(e))
    
    def verify_payment(self, transaction_id: str) -> bool:
        return True
    
    def refund(self, transaction_id: str, amount: float) -> RefundResult:
        return RefundResult(
            success=True,
            refund_id=f"TABBY-REFUND-{transaction_id}",
            message="Tabby refund processed",
            amount=amount
        )
    
    def get_gateway_name(self) -> str:
        return "Tabby"


# ===== GATEWAY FACTORY =====

def get_payment_gateway(gateway_type: str, **config) -> PaymentGateway:
    """
    Factory function to get the appropriate payment gateway.
    
    Args:
        gateway_type: 'manual', 'fawry', 'visa', 'talabat', 'tabby'
        **config: Gateway configuration (api_key, api_secret, merchant_id)
        
    Returns:
        PaymentGateway instance
    """
    gateways = {
        "manual": ManualPaymentGateway,
        "fawry": FawryGateway,
        "visa": VisaGateway,
        "talabat": TalabatGateway,
        "tabby": TabbyGateway,
    }
    
    gateway_class = gateways.get(gateway_type.lower(), ManualPaymentGateway)
    return gateway_class(**config)


# ===== CONVENIENCE FUNCTIONS =====

