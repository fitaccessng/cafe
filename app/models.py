import secrets
from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, login_manager


def utcnow():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(254), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="staff")
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    @property
    def is_active(self):
        return self.active

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False, unique=True)
    slug = db.Column(db.String(90), nullable=False, unique=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    active = db.Column(db.Boolean, nullable=False, default=True)
    products = db.relationship("Product", back_populates="category")


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False, index=True)
    name = db.Column(db.String(140), nullable=False, index=True)
    slug = db.Column(db.String(160), nullable=False, unique=True)
    description = db.Column(db.Text, nullable=False, default="")
    image_url = db.Column(db.String(500), nullable=False, default="")
    image_alt = db.Column(db.String(180), nullable=False, default="")
    image_review_required = db.Column(db.Boolean, nullable=False, default=False)
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    available = db.Column(db.Boolean, nullable=False, default=True)
    stock_quantity = db.Column(db.Integer)
    featured = db.Column(db.Boolean, nullable=False, default=False)
    review_required = db.Column(db.Boolean, nullable=False, default=False)
    archived_at = db.Column(db.DateTime(timezone=True))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    category = db.relationship("Category", back_populates="products")
    variants = db.relationship("ProductVariant", back_populates="product", cascade="all, delete-orphan")
    __table_args__ = (db.CheckConstraint("stock_quantity IS NULL OR stock_quantity >= 0"),)


class ProductVariant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False, index=True)
    name = db.Column(db.String(60), nullable=False)
    price_minor = db.Column(db.Integer, nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    product = db.relationship("Product", back_populates="variants")
    __table_args__ = (db.UniqueConstraint("product_id", "name"), db.CheckConstraint("price_minor >= 0"))


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(16), nullable=False, unique=True, index=True, default=lambda: secrets.token_hex(6).upper())
    tracking_token = db.Column(db.String(64), nullable=False, unique=True, index=True, default=lambda: secrets.token_urlsafe(32))
    customer_name = db.Column(db.String(120), nullable=False)
    customer_phone = db.Column(db.String(30), nullable=False)
    customer_email = db.Column(db.String(254))
    fulfillment = db.Column(db.String(12), nullable=False)
    delivery_address = db.Column(db.String(500))
    delivery_zone = db.Column(db.String(100))
    delivery_instructions = db.Column(db.String(500))
    pickup_name = db.Column(db.String(120))
    order_notes = db.Column(db.String(1000))
    requested_at = db.Column(db.DateTime(timezone=True))
    terms_acknowledged_at = db.Column(db.DateTime(timezone=True))
    subtotal_minor = db.Column(db.Integer, nullable=False)
    delivery_fee_minor = db.Column(db.Integer, nullable=False, default=0)
    discount_minor = db.Column(db.Integer, nullable=False, default=0)
    tax_minor = db.Column(db.Integer, nullable=False, default=0)
    total_minor = db.Column(db.Integer, nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="ZAR")
    status = db.Column(db.String(30), nullable=False, default="pending_confirmation", index=True)
    payment_method = db.Column(db.String(20), nullable=False)
    payment_status = db.Column(db.String(24), nullable=False, default="unpaid", index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True)
    idempotency_key = db.Column(db.String(64), unique=True)
    stock_released_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    items = db.relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    payments = db.relationship("Payment", back_populates="order")
    status_history = db.relationship("OrderStatusHistory", back_populates="order", order_by="OrderStatusHistory.created_at")


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=True)
    variant_id = db.Column(db.Integer, db.ForeignKey("product_variant.id"), nullable=True)
    product_name = db.Column(db.String(140), nullable=False)
    variant_name = db.Column(db.String(60), nullable=False, default="")
    unit_price_minor = db.Column(db.Integer, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    line_total_minor = db.Column(db.Integer, nullable=False)
    order = db.relationship("Order", back_populates="items")
    __table_args__ = (db.CheckConstraint("quantity > 0"), db.CheckConstraint("unit_price_minor >= 0"))


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False, index=True)
    provider = db.Column(db.String(30), nullable=False)
    transaction_reference = db.Column(db.String(100), nullable=False, unique=True, index=True)
    provider_reference = db.Column(db.String(120), unique=True)
    amount_minor = db.Column(db.Integer, nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="ZAR")
    status = db.Column(db.String(24), nullable=False, default="pending", index=True)
    event_id = db.Column(db.String(160), unique=True)
    collected_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    collected_at = db.Column(db.DateTime(timezone=True))
    collection_method = db.Column(db.String(20))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    order = db.relationship("Order", back_populates="payments")


class OrderStatusHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False, index=True)
    from_status = db.Column(db.String(30))
    to_status = db.Column(db.String(30), nullable=False)
    actor_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    reason = db.Column(db.String(500))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    order = db.relationship("Order", back_populates="status_history")


class BusinessSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    business_name = db.Column(db.String(120), nullable=False, default="Café Coffee Day")
    outlet_address = db.Column(db.String(500), nullable=False, default="")
    contact_phone = db.Column(db.String(30), nullable=False, default="")
    contact_email = db.Column(db.String(254), nullable=False, default="")
    bank_name = db.Column(db.String(120), nullable=False, default="")
    bank_account_name = db.Column(db.String(120), nullable=False, default="")
    bank_account_number = db.Column(db.String(40), nullable=False, default="")
    bank_branch_code = db.Column(db.String(20), nullable=False, default="")
    bank_account_type = db.Column(db.String(40), nullable=False, default="")
    opening_hours = db.Column(db.String(500), nullable=False, default="")
    pickup_enabled = db.Column(db.Boolean, nullable=False, default=False)
    delivery_enabled = db.Column(db.Boolean, nullable=False, default=False)
    delivery_zones = db.Column(db.String(1000), nullable=False, default="")
    delivery_fee_minor = db.Column(db.Integer, nullable=False, default=0)
    pickup_prep_minutes = db.Column(db.Integer)
    delivery_estimate_minutes = db.Column(db.Integer)
    promo_banner = db.Column(db.String(300), nullable=False, default="")
    minimum_order_minor = db.Column(db.Integer)
    pay_online_enabled = db.Column(db.Boolean, nullable=False, default=False)
    pay_on_pickup_enabled = db.Column(db.Boolean, nullable=False, default=False)
    pay_on_delivery_enabled = db.Column(db.Boolean, nullable=False, default=False)
    tax_rate_basis_points = db.Column(db.Integer, nullable=False, default=0)
    maintenance_mode = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True)
    action = db.Column(db.String(100), nullable=False)
    entity_type = db.Column(db.String(60), nullable=False)
    entity_id = db.Column(db.String(80), nullable=False)
    details = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)