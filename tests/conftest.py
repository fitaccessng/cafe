import pytest

from app import create_app
from app.extensions import db
from app.models import BusinessSettings, Category, Product, ProductVariant, User


@pytest.fixture
def app():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        category = Category(name="Coffee and hot drinks", slug="coffee")
        db.session.add(category)
        db.session.flush()
        product = Product(category_id=category.id, name="Cappuccino", slug="cappuccino", active=True, available=True)
        product.variants.extend([ProductVariant(name="Small", price_minor=2500), ProductVariant(name="Medium", price_minor=3500)])
        db.session.add(product)
        db.session.add(BusinessSettings(pickup_enabled=True, delivery_enabled=True, delivery_zones="Central\nGardens", delivery_fee_minor=500, pay_online_enabled=True, pay_on_pickup_enabled=True, pay_on_delivery_enabled=True, tax_rate_basis_points=1500, bank_name="Example Bank", bank_account_name="Cafe Coffee Day", bank_account_number="1234567890", bank_branch_code="123456"))
        admin = User(full_name="Admin User", email="admin@example.com", role="admin")
        admin.set_password("correct-horse-battery-1")
        staff = User(full_name="Staff User", email="staff@example.com", role="staff")
        staff.set_password("correct-horse-battery-2")
        db.session.add_all([admin, staff])
        db.session.commit()
    yield app
    with app.app_context():
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()