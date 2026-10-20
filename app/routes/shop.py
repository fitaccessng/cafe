import secrets
import json
from datetime import timedelta
from pathlib import Path

import requests
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user
from sqlalchemy import or_, select

from ..extensions import csrf, db, limiter
from ..forms import CheckoutForm
from ..models import BusinessSettings, Category, Order, OrderItem, Payment, Product, ProductVariant
from ..services import cart_lines, create_order, initialize_paystack, process_paystack_event, valid_paystack_signature, verify_paystack

bp = Blueprint("shop", __name__)


def cart_product_quantity(cart_data, product_id, excluding_variant_id=None):
    total = 0
    for key, entry in cart_data.items():
        if key == str(excluding_variant_id):
            continue
        try:
            variant = db.session.get(ProductVariant, int(key))
            quantity = int(entry.get("quantity", 0))
        except (TypeError, ValueError):
            continue
        if variant and variant.product_id == product_id and quantity > 0:
            total += quantity
    return total


@bp.get("/")
def home():
    categories = db.session.scalars(select(Category).where(Category.active.is_(True)).order_by(Category.sort_order, Category.name)).all()
    featured = db.session.scalars(select(Product).where(Product.active.is_(True), Product.available.is_(True), Product.featured.is_(True), Product.review_required.is_(False), or_(Product.stock_quantity.is_(None), Product.stock_quantity > 0)).limit(4)).all()
    best_seller_ids = db.session.scalars(select(OrderItem.product_id).join(Order).where(OrderItem.product_id.is_not(None), Order.status != "cancelled").group_by(OrderItem.product_id).order_by(db.func.sum(OrderItem.quantity).desc()).limit(4)).all()
    best_sellers = db.session.scalars(select(Product).where(Product.id.in_(best_seller_ids), Product.active.is_(True), Product.available.is_(True), Product.review_required.is_(False), or_(Product.stock_quantity.is_(None), Product.stock_quantity > 0))).all() if best_seller_ids else []
    settings = db.session.scalar(select(BusinessSettings).order_by(BusinessSettings.id).limit(1))
    return render_template("home.html", categories=categories, featured=featured, best_sellers=best_sellers, settings=settings)


@bp.get("/menu")
def menu():
    query = request.args.get("q", "").strip()[:100]
    category_slug = request.args.get("category", "").strip()
    availability = request.args.get("availability", "all")
    if availability not in {"all", "available", "unavailable"}:
        availability = "all"
    statement = select(Product).join(Category).where(Product.active.is_(True), Product.review_required.is_(False), Category.active.is_(True))
    if category_slug:
        statement = statement.where(Category.slug == category_slug)
    if query:
        statement = statement.where(or_(Product.name.ilike(f"%{query}%"), Product.description.ilike(f"%{query}%")))
    if availability == "available":
        statement = statement.where(Product.available.is_(True), or_(Product.stock_quantity.is_(None), Product.stock_quantity > 0))
    elif availability == "unavailable":
        statement = statement.where(or_(Product.available.is_(False), Product.stock_quantity == 0))
    products = db.session.scalars(statement.order_by(Category.sort_order, Product.name)).all()
    categories = db.session.scalars(select(Category).where(Category.active.is_(True)).order_by(Category.sort_order, Category.name)).all()
    review_pending = db.session.scalar(select(Product.id).where(Product.review_required.is_(True)).limit(1)) is not None
    return render_template("menu.html", products=products, categories=categories, query=query, selected_category=category_slug, availability=availability, review_pending=review_pending)


@bp.get("/product/<slug>")
def product(slug):
    item = db.session.scalar(select(Product).where(Product.slug == slug, Product.active.is_(True), Product.review_required.is_(False)))
    if not item:
        abort(404)
    variants = db.session.scalars(select(ProductVariant).where(ProductVariant.product_id == item.id, ProductVariant.active.is_(True))).all()
    in_stock = item.available and (item.stock_quantity is None or item.stock_quantity > 0)
    return render_template("product.html", product=item, variants=variants, in_stock=in_stock)


@bp.post("/cart/add")
@limiter.limit("30 per minute")
def cart_add():
    try:
        variant_id = int(request.form.get("variant_id", ""))
        quantity = int(request.form.get("quantity", "1"))
    except ValueError:
        abort(400)
    variant = db.session.get(ProductVariant, variant_id)
    if not variant or not variant.active or not variant.product.active or not variant.product.available or variant.product.review_required:
        flash("That item is unavailable.", "error")
        return redirect(url_for("shop.menu"))
    if not 1 <= quantity <= 20:
        flash("Choose a quantity from 1 to 20.", "error")
        return redirect(url_for("shop.product", slug=variant.product.slug))
    cart = session.setdefault("cart", {})
    key = str(variant.id)
    new_quantity = int(cart.get(key, {}).get("quantity", 0)) + quantity
    total_product_quantity = cart_product_quantity(cart, variant.product_id) + quantity
    if variant.product.stock_quantity is not None and total_product_quantity > variant.product.stock_quantity:
        flash(f"Only {variant.product.stock_quantity} of {variant.product.name} remain in stock.", "error")
        return redirect(request.referrer or url_for("shop.menu"))
    cart[key] = {"quantity": min(20, new_quantity)}
    session.modified = True
    flash(f"{variant.product.name} added to your cart.", "success")
    return redirect(request.referrer or url_for("shop.menu"))


@bp.route("/cart", methods=["GET", "POST"])
def cart():
    cart_data = session.get("cart", {})
    if request.method == "POST":
        action = request.form.get("action")
        key = request.form.get("variant_id", "")
        if action == "clear_stale":
            valid_keys = {str(variant.id) for variant, _ in cart_lines(cart_data)}
            session["cart"] = {cart_key: value for cart_key, value in cart_data.items() if cart_key in valid_keys}
        elif key in cart_data:
            if action == "remove":
                cart_data.pop(key)
            elif action == "change_variant":
                try:
                    new_variant_id = int(request.form.get("new_variant_id", ""))
                except ValueError:
                    new_variant_id = 0
                old_variant = db.session.get(ProductVariant, int(key)) if key.isdigit() else None
                new_variant = db.session.get(ProductVariant, new_variant_id)
                quantity = int(cart_data[key].get("quantity", 0))
                if (old_variant and new_variant and new_variant.product_id == old_variant.product_id and new_variant.active
                        and new_variant.product.active and new_variant.product.available):
                    cart_data.pop(key)
                    new_key = str(new_variant.id)
                    combined = quantity + int(cart_data.get(new_key, {}).get("quantity", 0))
                    total_product_quantity = cart_product_quantity(cart_data, new_variant.product_id) + quantity
                    if combined <= 20 and (new_variant.product.stock_quantity is None or total_product_quantity <= new_variant.product.stock_quantity):
                        cart_data[new_key] = {"quantity": combined}
                    else:
                        cart_data[key] = {"quantity": quantity}
                        flash("That size cannot be combined with the current quantity.", "error")
                else:
                    flash("That size is no longer available.", "error")
            elif action == "update":
                try:
                    quantity = int(request.form.get("quantity", ""))
                except ValueError:
                    quantity = 0
                if 1 <= quantity <= 20:
                    variant = db.session.get(ProductVariant, int(key)) if key.isdigit() else None
                    total_product_quantity = cart_product_quantity(cart_data, variant.product_id, excluding_variant_id=variant.id) + quantity if variant else quantity
                    if variant and variant.product.stock_quantity is not None and total_product_quantity > variant.product.stock_quantity:
                        flash(f"Only {variant.product.stock_quantity} of {variant.product.name} remain in stock.", "error")
                    else:
                        cart_data[key]["quantity"] = quantity
                else:
                    flash("Choose a quantity from 1 to 20.", "error")
            session["cart"] = cart_data
        return redirect(url_for("shop.cart"))
    lines = cart_lines(cart_data)
    stale_cart = len(lines) != len(cart_data)
    subtotal = sum(variant.price_minor * quantity for variant, quantity in lines)
    return render_template("cart.html", lines=lines, subtotal=subtotal, stale_cart=stale_cart)


@bp.route("/checkout", methods=["GET", "POST"])
@limiter.limit("8 per minute")
def checkout():
    cart_data = session.get("cart", {})
    lines = cart_lines(cart_data)
    if len(lines) != len(cart_data):
        flash("Your bag has items or quantities that changed. Review it before checkout.", "error")
        return redirect(url_for("shop.cart"))
    if not lines:
        flash("Add an available item before checking out.", "error")
        return redirect(url_for("shop.cart"))
    settings = db.session.scalar(select(BusinessSettings).order_by(BusinessSettings.id).limit(1))
    if not settings:
        flash("Ordering is not configured yet. Please contact the café.", "error")
        return redirect(url_for("shop.cart"))
    form = CheckoutForm()
    delivery_zones = [zone.strip() for zone in settings.delivery_zones.splitlines() if zone.strip()]
    form.fulfillment.choices = [("", "Choose pickup or delivery")]
    if settings.pickup_enabled:
        form.fulfillment.choices.append(("pickup", "Pickup"))
    if settings.delivery_enabled and delivery_zones:
        form.fulfillment.choices.append(("delivery", "Delivery"))
    if request.method == "GET":
        form.fulfillment.data = form.fulfillment.choices[1][0] if len(form.fulfillment.choices) > 1 else ""
    form.delivery_zone.choices = [("", "Choose delivery area")] + [(zone, zone) for zone in delivery_zones]
    form.payment_method.data = "bank_transfer"
    subtotal = sum(variant.price_minor * quantity for variant, quantity in lines)
    delivery_fee = settings.delivery_fee_minor if form.fulfillment.data == "delivery" and settings.delivery_enabled else 0
    tax = (subtotal * settings.tax_rate_basis_points + 5000) // 10000
    checkout_context = {"form": form, "settings": settings, "lines": lines, "subtotal": subtotal, "delivery_fee": delivery_fee, "tax": tax, "total": subtotal + delivery_fee + tax, "delivery_zones": delivery_zones}
    if form.validate_on_submit():
        if not settings.bank_name or not settings.bank_account_number:
            flash("Bank transfer details are not configured yet. Please contact the café.", "error")
            return render_template("checkout.html", **checkout_context), 400
        checkout_key = session.setdefault("checkout_key", secrets.token_urlsafe(32))
        try:
            order = create_order(form, session.get("cart", {}), checkout_key, current_user.id if current_user.is_authenticated else None)
        except ValueError as error:
            flash(str(error), "error")
            return render_template("checkout.html", **checkout_context), 400
        session.pop("checkout_key", None)
        session.pop("cart", None)
        return redirect(url_for("shop.order_confirmation", token=order.tracking_token))
    return render_template("checkout.html", **checkout_context)


@bp.get("/order/<token>")
def order_confirmation(token):
    order = db.session.scalar(select(Order).where(Order.tracking_token == token))
    if not order:
        abort(404)
    settings = db.session.scalar(select(BusinessSettings).order_by(BusinessSettings.id).limit(1))
    estimate_minutes = (settings.pickup_prep_minutes if order.fulfillment == "pickup" else settings.delivery_estimate_minutes) if settings else None
    estimated_ready_at = order.created_at + timedelta(minutes=estimate_minutes) if estimate_minutes is not None else None
    return render_template("order.html", order=order, settings=settings, estimated_ready_at=estimated_ready_at)


@bp.get("/track")
def track():
    token = request.args.get("token", "").strip()
    if token:
        return redirect(url_for("shop.order_confirmation", token=token))
    return render_template("track.html")


@bp.get("/image-credits")
def image_credits():
    manifest_path = Path(current_app.static_folder) / "images" / "menu" / "image-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"images": {}}
    entries = sorted(manifest.get("images", {}).items())
    return render_template("image_credits.html", image_credits=entries)


@bp.get("/orders")
def customer_orders():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.customer_login"))
    if current_user.role != "customer":
        abort(403)
    orders = db.session.scalars(select(Order).where(Order.user_id == current_user.id).order_by(Order.created_at.desc()).limit(100)).all()
    return render_template("customer_orders.html", orders=orders)


@bp.get("/payment/return")
@limiter.limit("20 per minute")
def payment_return():
    reference = request.args.get("reference", "")
    payment = db.session.scalar(select(Payment).where(Payment.transaction_reference == reference))
    if not payment:
        abort(404)
    try:
        verify_paystack(reference)
    except requests.RequestException:
        current_app.logger.warning("Payment verification unavailable for transaction %s", reference)
        flash("Payment is being verified. Refresh this page shortly.", "error")
    return redirect(url_for("shop.order_confirmation", token=payment.order.tracking_token))


@bp.post("/payment/webhook")
@csrf.exempt
@limiter.limit("120 per minute")
def payment_webhook():
    raw_body = request.get_data()
    if not valid_paystack_signature(raw_body, request.headers.get("x-paystack-signature", "")):
        abort(401)
    try:
        process_paystack_event(request.get_json(force=True))
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Payment webhook processing failed")
        return "retry", 500
    return "ok", 200