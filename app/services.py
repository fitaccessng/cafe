import hashlib
import hmac
import json
import secrets
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import requests
from flask import current_app
from sqlalchemy import select

from .extensions import db
from .models import AuditLog, BusinessSettings, Order, OrderItem, OrderStatusHistory, Payment, Product, ProductVariant, utcnow

ORDER_TRANSITIONS = {
    "pending_confirmation": {"accepted", "cancelled"},
    "accepted": {"preparing", "cancelled"},
    "preparing": {"ready_for_pickup", "out_for_delivery", "cancelled"},
    "ready_for_pickup": {"completed", "cancelled"},
    "out_for_delivery": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


def money_to_minor(value, optional=False):
    if optional and (value is None or not str(value).strip()):
        return None
    try:
        amount = Decimal(str(value).strip()).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if not amount.is_finite() or amount < 0:
            raise ValueError("Amount must be a finite non-negative number.")
    except (InvalidOperation, ValueError):
        raise ValueError("Enter a valid amount in rand.")
    return int(amount * 100)


def cart_lines(cart):
    lines = []
    for key, entry in cart.items():
        try:
            variant_id = int(key)
            quantity = int(entry.get("quantity", 0))
        except (TypeError, ValueError):
            continue
        variant = db.session.get(ProductVariant, variant_id)
        if not variant or not variant.active or not variant.product.active or not variant.product.available:
            continue
        if not 1 <= quantity <= 20:
            continue
        if variant.product.stock_quantity is not None and quantity > variant.product.stock_quantity:
            continue
        lines.append((variant, quantity))
    return lines


def create_order(form, cart, customer_session_key, user_id=None):
    if not getattr(form.terms_acknowledged, "data", False):
        raise ValueError("Please acknowledge the order terms before placing your order.")
    existing = db.session.scalar(select(Order).where(Order.idempotency_key == customer_session_key))
    if existing:
        return existing
    settings = db.session.scalar(select(BusinessSettings).order_by(BusinessSettings.id).limit(1))
    lines = cart_lines(cart)
    if not lines:
        raise ValueError("Your cart is empty or contains unavailable items.")
    product_ids = {variant.product_id for variant, _ in lines}
    locked_products = {
        product.id: product
        for product in db.session.scalars(select(Product).where(Product.id.in_(product_ids)).order_by(Product.id).with_for_update())
    }
    requested_by_product = {}
    for variant, quantity in lines:
        requested_by_product[variant.product_id] = requested_by_product.get(variant.product_id, 0) + quantity
    for product_id, requested in requested_by_product.items():
        product = locked_products[product_id]
        if not product.active or not product.available or product.review_required:
            raise ValueError(f"{product.name} is no longer available.")
        if product.stock_quantity is not None and requested > product.stock_quantity:
            raise ValueError(f"Only {product.stock_quantity} of {product.name} remain in stock.")
    fulfillment = form.fulfillment.data
    if not settings or settings.maintenance_mode:
        raise ValueError("Ordering is temporarily unavailable.")
    if fulfillment == "delivery":
        if not settings.delivery_enabled:
            raise ValueError("Delivery is not currently available.")
        if not form.delivery_address.data or len(form.delivery_address.data.strip()) < 5:
            raise ValueError("Enter a complete delivery address.")
        zones = [zone.strip() for zone in settings.delivery_zones.splitlines() if zone.strip()]
        if not zones or form.delivery_zone.data not in zones:
            raise ValueError("Choose a configured delivery area.")
        fee = settings.delivery_fee_minor
        order_notes = (form.order_notes.data or "").strip() or None
    elif fulfillment == "pickup":
        if not settings.pickup_enabled:
            raise ValueError("Pickup is not currently available.")
        if not (form.pickup_name.data or "").strip():
            raise ValueError("Enter the name the order will be collected under.")
        fee = 0
        order_notes = None
    else:
        raise ValueError("Choose a valid fulfillment method.")
    method = form.payment_method.data
    allowed = {
        "bank_transfer": True,
        "online": settings.pay_online_enabled and bool(current_app.config["PAYSTACK_SECRET_KEY"]),
        "pay_on_pickup": fulfillment == "pickup" and settings.pay_on_pickup_enabled,
        "pay_on_delivery": fulfillment == "delivery" and settings.pay_on_delivery_enabled,
    }
    if method not in allowed or not allowed[method]:
        raise ValueError("That payment method is not currently available.")
    subtotal = sum(variant.price_minor * quantity for variant, quantity in lines)
    if settings.minimum_order_minor is not None and subtotal < settings.minimum_order_minor:
        raise ValueError("Your cart does not meet the configured minimum order value.")
    tax = (subtotal * settings.tax_rate_basis_points + 5000) // 10000
    order = Order(
        customer_name=form.customer_name.data.strip(), customer_phone=form.customer_phone.data.strip(),
        customer_email=(form.customer_email.data or "").strip() or None, fulfillment=fulfillment,
        delivery_address=form.delivery_address.data.strip() if fulfillment == "delivery" else None,
        delivery_zone=form.delivery_zone.data if fulfillment == "delivery" else None,
        delivery_instructions=(form.delivery_instructions.data or "").strip() if fulfillment == "delivery" else None,
        pickup_name=(form.pickup_name.data or form.customer_name.data).strip() if fulfillment == "pickup" else None,
        order_notes=order_notes, subtotal_minor=subtotal,
        terms_acknowledged_at=utcnow(),
        delivery_fee_minor=fee, tax_minor=tax, total_minor=subtotal + fee + tax,
        payment_method=method, payment_status="pending" if method == "online" else "unpaid",
        user_id=user_id, idempotency_key=customer_session_key,
    )
    for variant, quantity in lines:
        order.items.append(OrderItem(
            product_id=variant.product_id, variant_id=variant.id, product_name=variant.product.name,
            variant_name=variant.name, unit_price_minor=variant.price_minor, quantity=quantity,
            line_total_minor=variant.price_minor * quantity,
        ))
    db.session.add(order)
    db.session.flush()
    for product_id, requested in requested_by_product.items():
        product = locked_products[product_id]
        if product.stock_quantity is not None:
            product.stock_quantity -= requested
    db.session.add(OrderStatusHistory(order_id=order.id, to_status="pending_confirmation", reason="Customer placed order"))
    db.session.add(AuditLog(action="order.created", entity_type="order", entity_id=str(order.id)))
    payment = None
    if method == "online":
        payment = Payment(order_id=order.id, provider="paystack", transaction_reference=secrets.token_urlsafe(24), amount_minor=order.total_minor)
        db.session.add(payment)
    db.session.commit()
    return order


def initialize_paystack(payment):
    secret = current_app.config["PAYSTACK_SECRET_KEY"]
    order = payment.order
    response = requests.post(
        "https://api.paystack.co/transaction/initialize",
        headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
        json={"email": order.customer_email, "amount": payment.amount_minor, "currency": "ZAR", "reference": payment.transaction_reference,
              "callback_url": f"{current_app.config['CANONICAL_ORIGIN'].rstrip('/')}/payment/return"},
        timeout=12,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("status") or not payload.get("data", {}).get("authorization_url"):
        raise RuntimeError("Payment provider did not return a checkout URL")
    payment.provider_reference = payload["data"].get("reference")
    db.session.commit()
    return payload["data"]["authorization_url"]


def verify_paystack(reference):
    payment = db.session.scalar(select(Payment).where(Payment.transaction_reference == reference).with_for_update())
    if not payment or payment.provider != "paystack":
        return False
    if payment.status == "paid":
        return True
    response = requests.get(
        f"https://api.paystack.co/transaction/verify/{reference}",
        headers={"Authorization": f"Bearer {current_app.config['PAYSTACK_SECRET_KEY']}"}, timeout=12,
    )
    response.raise_for_status()
    data = response.json().get("data", {})
    if data.get("status") != "success" or data.get("reference") != reference or data.get("amount") != payment.amount_minor or data.get("currency") != "ZAR":
        if data.get("status") in {"failed", "abandoned"}:
            payment.status = data["status"]
            payment.order.payment_status = data["status"]
            db.session.commit()
        return False
    payment.status = "paid"
    payment.provider_reference = str(data.get("id", "")) or payment.provider_reference
    payment.order.payment_status = "paid"
    db.session.add(AuditLog(action="payment.verified", entity_type="payment", entity_id=str(payment.id)))
    db.session.commit()
    return True


def valid_paystack_signature(raw_body, signature):
    secret = current_app.config["PAYSTACK_SECRET_KEY"].encode()
    expected = hmac.new(secret, raw_body, hashlib.sha512).hexdigest()
    return bool(signature) and hmac.compare_digest(expected, signature)


def process_paystack_event(payload):
    provider_event_id = str(payload.get("data", {}).get("id", ""))
    event_id = f"{payload.get('event', '')}:{provider_event_id}"
    reference = payload.get("data", {}).get("reference")
    if not reference or not provider_event_id or event_id == ":":
        return False
    payment = db.session.scalar(select(Payment).where(Payment.transaction_reference == reference).with_for_update())
    if not payment or payment.event_id == event_id:
        return bool(payment and payment.status == "paid")
    data = payload["data"]
    if payload.get("event") == "charge.success" and data.get("status") == "success" and data.get("amount") == payment.amount_minor and data.get("currency") == "ZAR":
        payment.event_id = event_id
        payment.status = "paid"
        payment.provider_reference = str(data["id"])
        payment.order.payment_status = "paid"
        db.session.add(AuditLog(action="payment.webhook_paid", entity_type="payment", entity_id=str(payment.id)))
    elif payload.get("event") == "charge.failed" and payment.status != "paid":
        payment.event_id = event_id
        payment.status = "failed"
        payment.order.payment_status = "failed"
    db.session.commit()
    return payment.status == "paid"