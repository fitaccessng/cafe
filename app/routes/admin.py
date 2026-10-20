import csv
import io
import os
import re
import secrets
import unicodedata
from pathlib import Path
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import Blueprint, abort, current_app, flash, make_response, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, select
from werkzeug.utils import secure_filename

from ..extensions import db
from ..forms import CollectPaymentForm, ProductForm, SettingsForm, StatusForm
from ..models import AuditLog, BusinessSettings, Category, Order, OrderItem, OrderStatusHistory, Payment, Product, ProductVariant
from ..services import ORDER_TRANSITIONS, money_to_minor

bp = Blueprint("admin", __name__, url_prefix="/admin")


def roles_required(*roles):
    def decorate(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorate


def slugify(text):
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")[:150]


@bp.get("")
@roles_required("admin", "staff")
def dashboard():
    today = datetime.now(timezone.utc).date()
    start = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
    orders_today = db.session.scalar(select(func.count(Order.id)).where(Order.created_at >= start)) or 0
    counts = {status: db.session.scalar(select(func.count(Order.id)).where(Order.status == status)) or 0 for status in ("pending_confirmation", "preparing", "ready_for_pickup", "out_for_delivery", "completed", "cancelled")}
    successful = db.session.scalar(select(func.coalesce(func.sum(Payment.amount_minor), 0)).where(Payment.status == "paid")) or 0
    unpaid = db.session.scalar(select(func.coalesce(func.sum(Order.total_minor), 0)).where(Order.payment_status.in_(("unpaid", "pending", "failed", "partially_paid")))) or 0
    best_sellers = db.session.execute(select(func.sum(OrderItem.quantity), OrderItem.product_name).group_by(OrderItem.product_name).order_by(func.sum(OrderItem.quantity).desc()).limit(5)).all()
    return render_template("admin/dashboard.html", orders_today=orders_today, counts=counts, successful=successful, unpaid=unpaid, best_sellers=best_sellers)


@bp.get("/orders")
@roles_required("admin", "staff")
def orders():
    statement = select(Order)
    if request.args.get("reference"):
        statement = statement.where(Order.reference.ilike(f"%{request.args['reference'][:16]}%"))
    for field, model_field in (("status", Order.status), ("payment", Order.payment_status), ("fulfillment", Order.fulfillment)):
        value = request.args.get(field, "")
        if value:
            statement = statement.where(model_field == value)
    if request.args.get("date"):
        try:
            date = datetime.strptime(request.args["date"], "%Y-%m-%d").date()
            start = datetime.combine(date, datetime.min.time(), tzinfo=timezone.utc)
            statement = statement.where(Order.created_at >= start, Order.created_at < start + timedelta(days=1))
        except ValueError:
            flash("Invalid date filter.", "error")
    result = db.session.scalars(statement.order_by(Order.created_at.desc()).limit(250)).all()
    return render_template("admin/orders.html", orders=result)


@bp.get("/reports")
@roles_required("admin")
def reports():
    now = datetime.now(timezone.utc)
    start_arg = request.args.get("start", now.date().replace(day=1).isoformat())
    end_arg = request.args.get("end", now.date().isoformat())
    try:
        start_date = datetime.strptime(start_arg, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_arg, "%Y-%m-%d").date()
    except ValueError:
        abort(400)
    if end_date < start_date or (end_date - start_date).days > 366:
        abort(400)
    start = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
    end = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    gross_orders = db.session.scalar(select(func.coalesce(func.sum(Order.total_minor), 0)).where(Order.created_at >= start, Order.created_at < end, Order.status != "cancelled")) or 0
    received = db.session.scalar(select(func.coalesce(func.sum(Payment.amount_minor), 0)).where(Payment.created_at >= start, Payment.created_at < end, Payment.status == "paid")) or 0
    refunds = db.session.scalar(select(func.coalesce(func.sum(Payment.amount_minor), 0)).where(Payment.created_at >= start, Payment.created_at < end, Payment.status == "refunded")) or 0
    unpaid = db.session.scalar(select(func.coalesce(func.sum(Order.total_minor), 0)).where(Order.created_at >= start, Order.created_at < end, Order.payment_status.in_(("unpaid", "pending", "failed", "partially_paid")))) or 0
    daily = db.session.execute(select(func.date(Order.created_at), func.sum(Order.total_minor)).where(Order.created_at >= start, Order.created_at < end, Order.status != "cancelled").group_by(func.date(Order.created_at)).order_by(func.date(Order.created_at))).all()
    return render_template("admin/reports.html", start=start_arg, end=end_arg, gross=gross_orders, received=received, refunds=refunds, net=received-refunds, unpaid=unpaid, daily=daily)


@bp.get("/orders/<int:order_id>")
@roles_required("admin", "staff")
def order_detail(order_id):
    order = db.get_or_404(Order, order_id)
    form = StatusForm()
    form.status.choices = [(value, value.replace("_", " ").title()) for value in ORDER_TRANSITIONS.get(order.status, set())]
    payment_form = CollectPaymentForm()
    payment_form.method.data = "eft"
    return render_template("admin/order_detail.html", order=order, form=form, payment_form=payment_form)


@bp.post("/orders/<int:order_id>/status")
@roles_required("admin", "staff")
def update_order_status(order_id):
    order = db.session.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if not order:
        abort(404)
    form = StatusForm()
    allowed = ORDER_TRANSITIONS.get(order.status, set())
    form.status.choices = [(value, value.replace("_", " ").title()) for value in allowed]
    if not form.validate_on_submit() or form.status.data not in allowed:
        abort(400)
    if order.fulfillment == "pickup" and form.status.data == "out_for_delivery":
        abort(400)
    if order.fulfillment == "delivery" and form.status.data == "ready_for_pickup":
        abort(400)
    previous = order.status
    if form.status.data == "cancelled" and order.payment_status == "paid":
        flash("Paid orders require a refund review before cancellation.", "error")
        return redirect(url_for("admin.order_detail", order_id=order.id))
    order.status = form.status.data
    if order.status == "cancelled" and order.stock_released_at is None:
        for item in order.items:
            product = db.session.scalar(select(Product).where(Product.id == item.product_id).with_for_update()) if item.product_id else None
            if product and product.stock_quantity is not None:
                product.stock_quantity += item.quantity
        order.stock_released_at = datetime.now(timezone.utc)
    db.session.add(OrderStatusHistory(order_id=order.id, from_status=previous, to_status=order.status, actor_id=current_user.id, reason=form.reason.data or None))
    db.session.add(AuditLog(actor_id=current_user.id, action="order.status_changed", entity_type="order", entity_id=str(order.id), details=f"{previous} -> {order.status}"))
    db.session.commit()
    flash("Order status updated.", "success")
    return redirect(url_for("admin.order_detail", order_id=order.id))


@bp.post("/orders/<int:order_id>/collect")
@roles_required("admin", "staff")
def collect_payment(order_id):
    order = db.session.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if not order:
        abort(404)
    form = CollectPaymentForm()
    if not form.validate_on_submit() or order.payment_method == "online" or order.payment_status == "paid":
        abort(400)
    try:
        amount = money_to_minor(form.amount.data)
    except ValueError:
        form.amount.errors.append("Enter a valid amount.")
        return redirect(url_for("admin.order_detail", order_id=order.id))
    collected = db.session.scalar(select(func.coalesce(func.sum(Payment.amount_minor), 0)).where(Payment.order_id == order.id, Payment.provider == "manual", Payment.status == "paid")) or 0
    remaining = order.total_minor - collected
    if not 0 < amount <= remaining:
        abort(400)
    payment = Payment(order_id=order.id, provider="manual", transaction_reference=f"manual-{order.reference}-{secrets.token_hex(5)}", amount_minor=amount, status="paid", collected_by_id=current_user.id, collected_at=datetime.now(timezone.utc), collection_method=form.method.data)
    order.payment_status = "paid" if collected + amount == order.total_minor else "partially_paid"
    db.session.add(payment)
    db.session.add(AuditLog(actor_id=current_user.id, action="payment.collected", entity_type="order", entity_id=str(order.id), details=f"{amount} minor units via {form.method.data}"))
    db.session.commit()
    flash("Payment collection recorded.", "success")
    return redirect(url_for("admin.order_detail", order_id=order.id))


@bp.get("/products")
@roles_required("admin")
def products():
    categories = db.session.scalars(select(Category).order_by(Category.name)).all()
    statement = select(Product)
    category_slug = request.args.get("category", "").strip()
    availability = request.args.get("availability", "all")
    if category_slug:
        statement = statement.join(Category).where(Category.slug == category_slug)
    if availability == "published":
        statement = statement.where(Product.active.is_(True), Product.review_required.is_(False))
    elif availability == "draft":
        statement = statement.where(Product.active.is_(False))
    elif availability == "available":
        statement = statement.where(Product.available.is_(True), (Product.stock_quantity.is_(None)) | (Product.stock_quantity > 0))
    elif availability == "unavailable":
        statement = statement.where((Product.available.is_(False)) | (Product.stock_quantity == 0))
    elif availability == "review":
        statement = statement.where((Product.review_required.is_(True)) | (Product.image_review_required.is_(True)))
    items = db.session.scalars(statement.order_by(Product.active.desc(), Product.name)).all()
    return render_template("admin/products.html", products=items, categories=categories, selected_category=category_slug, selected_availability=availability)


@bp.route("/products/new", methods=["GET", "POST"])
@roles_required("admin")
def product_new():
    return product_form(None)


@bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@roles_required("admin")
def product_edit(product_id):
    return product_form(db.get_or_404(Product, product_id))


def product_form(item):
    form = ProductForm(obj=item)
    categories = db.session.scalars(select(Category).order_by(Category.name)).all()
    form.category_id.choices = [(category.id, category.name) for category in categories]
    if item and request.method == "GET":
        form.stock_quantity.data = item.stock_quantity
        form.small_price.data = next((f"{v.price_minor / 100:.2f}" for v in item.variants if v.name.lower() == "small"), "")
        form.medium_price.data = next((f"{v.price_minor / 100:.2f}" for v in item.variants if v.name.lower() == "medium"), "")
        form.regular_price.data = next((f"{v.price_minor / 100:.2f}" for v in item.variants if v.name.lower() == "regular"), "")
        form.image_alt.data = item.image_alt
    if form.validate_on_submit():
        name = form.name.data.strip()
        slug = slugify(name)
        collision = db.session.scalar(select(Product).where(Product.slug == slug, Product.id != (item.id if item else 0)))
        if collision:
            slug = f"{slug}-{item.id if item else 'new'}"
        prices = []
        for variant_name, value in (("Small", form.small_price.data), ("Medium", form.medium_price.data), ("Regular", form.regular_price.data)):
            if value:
                try:
                    prices.append((variant_name, money_to_minor(value)))
                except ValueError as error:
                    form.errors["small_price"] = [str(error)]
                    return render_template("admin/product_form.html", form=form, item=item), 400
        if not prices:
            form.errors["regular_price"] = ["Enter at least one variant price."]
            return render_template("admin/product_form.html", form=form, item=item), 400
        uploaded = form.image_file.data
        image_url = (form.image_url.data or "").strip()
        if image_url and not image_url.startswith(("https://", "http://", "/media/")):
            form.image_url.errors.append("Use an http(s) image URL or upload an image.")
            return render_template("admin/product_form.html", form=form, item=item), 400
        if uploaded and uploaded.filename:
            extension = Path(secure_filename(uploaded.filename)).suffix.lower()
            raw = uploaded.stream.read(5 * 1024 * 1024 + 1)
            signatures = {".png": b"\x89PNG\r\n\x1a\n", ".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff", ".webp": b"RIFF"}
            if len(raw) > 5 * 1024 * 1024 or extension not in signatures or not raw.startswith(signatures.get(extension, b"!")) or (extension == ".webp" and raw[8:12] != b"WEBP"):
                form.image_file.errors.append("Upload a valid PNG, JPEG, or WebP image no larger than 5 MB.")
                return render_template("admin/product_form.html", form=form, item=item), 400
            filename = f"{secrets.token_hex(16)}{extension}"
            os.makedirs(current_app.config["UPLOAD_FOLDER"], exist_ok=True)
            with open(os.path.join(current_app.config["UPLOAD_FOLDER"], filename), "wb") as image_file:
                image_file.write(raw)
            image_url = f"/media/{filename}"
        if not item:
            item = Product()
            db.session.add(item)
        item.name, item.slug = name, slug
        item.category_id = form.category_id.data
        item.description = (form.description.data or "").strip()
        item.image_url = image_url or item.image_url
        item.image_alt = (form.image_alt.data or "").strip() or item.image_alt or f"Illustrative product image for {item.name}."
        if image_url:
            item.image_review_required = False
        item.active, item.available, item.featured = bool(form.active.data), bool(form.available.data), bool(form.featured.data)
        item.stock_quantity = form.stock_quantity.data
        if item.review_required:
            item.review_required = not bool(form.confirm_review.data)
            if item.review_required:
                item.active = False
        db.session.flush()
        existing = {variant.name: variant for variant in item.variants}
        keep = set()
        for variant_name, price in prices:
            keep.add(variant_name)
            variant = existing.get(variant_name)
            if variant:
                variant.price_minor, variant.active = price, True
            else:
                item.variants.append(ProductVariant(name=variant_name, price_minor=price))
        for variant_name, variant in existing.items():
            if variant_name not in keep:
                variant.active = False
        db.session.add(AuditLog(actor_id=current_user.id, action="product.saved", entity_type="product", entity_id=str(item.id)))
        db.session.commit()
        flash("Product saved.", "success")
        return redirect(url_for("admin.products"))
    return render_template("admin/product_form.html", form=form, item=item)


@bp.post("/products/<int:product_id>/archive")
@roles_required("admin")
def archive_product(product_id):
    item = db.get_or_404(Product, product_id)
    item.active = False
    item.available = False
    item.archived_at = datetime.now(timezone.utc)
    db.session.add(AuditLog(actor_id=current_user.id, action="product.archived", entity_type="product", entity_id=str(item.id)))
    db.session.commit()
    flash("Product archived. Historical order items remain unchanged.", "success")
    return redirect(url_for("admin.products"))


@bp.post("/categories")
@roles_required("admin")
def category_create():
    name = request.form.get("name", "").strip()[:80]
    if not name:
        abort(400)
    slug = slugify(name)[:90]
    if db.session.scalar(select(Category).where(Category.slug == slug)):
        flash("That category already exists.", "error")
    else:
        db.session.add(Category(name=name, slug=slug))
        db.session.commit()
        flash("Category added.", "success")
    return redirect(url_for("admin.products"))


@bp.get("/settings")
@roles_required("admin")
def settings():
    item = db.session.scalar(select(BusinessSettings).order_by(BusinessSettings.id).limit(1))
    form = SettingsForm(obj=item)
    if item:
        form.bank_name.data = item.bank_name
        form.bank_account_name.data = item.bank_account_name
        form.bank_account_number.data = item.bank_account_number
        form.bank_branch_code.data = item.bank_branch_code
        form.bank_account_type.data = item.bank_account_type
        form.delivery_fee.data = f"{item.delivery_fee_minor / 100:.2f}"
        form.minimum_order.data = f"{item.minimum_order_minor / 100:.2f}" if item.minimum_order_minor is not None else ""
        form.tax_rate.data = f"{item.tax_rate_basis_points / 100:.2f}"
        form.delivery_estimate_minutes.data = str(item.delivery_estimate_minutes or "")
    return render_template("admin/settings.html", form=form)


@bp.post("/settings")
@roles_required("admin")
def settings_save():
    form = SettingsForm()
    if not form.validate_on_submit():
        return render_template("admin/settings.html", form=form), 400
    item = db.session.scalar(select(BusinessSettings).order_by(BusinessSettings.id).limit(1)) or BusinessSettings()
    try:
        delivery_fee = money_to_minor(form.delivery_fee.data)
        minimum = money_to_minor(form.minimum_order.data, optional=True)
        tax_rate = Decimal(form.tax_rate.data or "0")
        if tax_rate < 0 or tax_rate > 100:
            raise ValueError("Tax rate must be between 0 and 100 percent.")
        prep_minutes = int(form.pickup_prep_minutes.data) if form.pickup_prep_minutes.data else None
        if prep_minutes is not None and not 0 <= prep_minutes <= 1440:
            raise ValueError("Pickup preparation estimate must be between 0 and 1440 minutes.")
        delivery_minutes = int(form.delivery_estimate_minutes.data) if form.delivery_estimate_minutes.data else None
        if delivery_minutes is not None and not 0 <= delivery_minutes <= 1440:
            raise ValueError("Delivery estimate must be between 0 and 1440 minutes.")
    except (ValueError, InvalidOperation):
        form.delivery_fee.errors.append("Enter valid delivery, minimum and tax values.")
        return render_template("admin/settings.html", form=form), 400
    for field in ("business_name", "outlet_address", "contact_phone", "contact_email", "bank_name", "bank_account_name", "bank_account_number", "bank_branch_code", "bank_account_type", "opening_hours", "delivery_zones", "promo_banner", "pickup_enabled", "delivery_enabled", "maintenance_mode"):
        setattr(item, field, getattr(form, field).data)
    item.delivery_fee_minor = delivery_fee
    item.minimum_order_minor = minimum
    item.tax_rate_basis_points = int(tax_rate * 100)
    item.pickup_prep_minutes = prep_minutes
    item.delivery_estimate_minutes = delivery_minutes
    if item.delivery_enabled and not any(zone.strip() for zone in item.delivery_zones.splitlines()):
        form.delivery_zones.errors.append("Add at least one delivery zone before enabling delivery.")
        return render_template("admin/settings.html", form=form), 400
    db.session.add(item)
    db.session.add(AuditLog(actor_id=current_user.id, action="settings.updated", entity_type="settings", entity_id=str(item.id)))
    db.session.commit()
    flash("Business settings saved.", "success")
    return redirect(url_for("admin.settings"))


@bp.get("/payments")
@roles_required("admin")
def payments():
    rows = db.session.scalars(select(Payment).order_by(Payment.created_at.desc()).limit(300)).all()
    return render_template("admin/payments.html", payments=rows)


@bp.get("/reports.csv")
@roles_required("admin")
def report_csv():
    start_arg, end_arg = request.args.get("start"), request.args.get("end")
    statement = select(Order).order_by(Order.created_at)
    try:
        if start_arg:
            statement = statement.where(Order.created_at >= datetime.fromisoformat(start_arg).replace(tzinfo=timezone.utc))
        if end_arg:
            statement = statement.where(Order.created_at < datetime.fromisoformat(end_arg).replace(tzinfo=timezone.utc) + timedelta(days=1))
    except ValueError:
        abort(400)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["reference", "created_at", "fulfillment", "status", "payment_status", "payment_method", "subtotal_zar", "delivery_fee_zar", "tax_zar", "total_zar"])
    for order in db.session.scalars(statement):
        writer.writerow([order.reference, order.created_at.isoformat(), order.fulfillment, order.status, order.payment_status, order.payment_method, f"{order.subtotal_minor/100:.2f}", f"{order.delivery_fee_minor/100:.2f}", f"{order.tax_minor/100:.2f}", f"{order.total_minor/100:.2f}"])
    response = make_response(output.getvalue())
    response.headers["Content-Type"] = "text/csv"
    response.headers["Content-Disposition"] = "attachment; filename=cafe-orders.csv"
    return response

