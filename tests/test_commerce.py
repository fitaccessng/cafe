from types import SimpleNamespace
import json
import re
from pathlib import Path

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import BusinessSettings, Category, Order, Payment, Product, ProductVariant, User
from app.commands import CATALOGUE
from app.services import ORDER_TRANSITIONS, create_order, process_paystack_event, valid_paystack_signature, verify_paystack


def checkout_form(**overrides):
    data = {
        "customer_name": "Test Customer", "customer_phone": "+27123456789", "customer_email": None,
        "fulfillment": "pickup", "delivery_address": "", "delivery_zone": "", "delivery_instructions": "",
        "pickup_name": "Test Customer", "order_notes": "", "payment_method": "pay_on_pickup",
        "terms_acknowledged": True,
    }
    data.update(overrides)
    return SimpleNamespace(**{key: SimpleNamespace(data=value) for key, value in data.items()})


def test_customer_pages_and_health(client):
    home = client.get("/")
    assert home.status_code == 200
    assert b'href="/menu"' in home.data
    assert b'href="/cart"' in home.data
    assert b'href="/track"' in home.data
    assert b'href="/menu?category=coffee"' in home.data
    assert client.get("/menu").status_code == 200
    assert client.get("/cart").status_code == 200
    assert client.get("/track").status_code == 200
    assert client.get("/health").json == {"status": "ok"}


def test_customer_can_order_and_track_privately(app, client):
    with app.app_context():
        variant = db.session.scalar(select(ProductVariant).where(ProductVariant.name == "Small"))
        variant_id = variant.id
    add = client.post("/cart/add", data={"variant_id": str(variant_id), "quantity": "2"}, follow_redirects=True)
    assert add.status_code == 200
    assert b"Cappuccino" in add.data
    checkout = client.post("/checkout", data={
        "customer_name": "Journey Customer", "customer_phone": "+27111222333", "customer_email": "journey@example.com",
        "fulfillment": "pickup", "pickup_name": "Journey Customer", "delivery_address": "", "delivery_zone": "",
        "delivery_instructions": "", "order_notes": "", "payment_method": "pay_on_pickup", "terms_acknowledged": "y", "submit": "Place order",
    })
    assert checkout.status_code == 302
    tracking_path = checkout.headers["Location"]
    confirmation = client.get(tracking_path)
    assert confirmation.status_code == 200
    assert b"Journey Customer" in confirmation.data
    assert b"Pickup redemption code" in confirmation.data
    assert b"Bank transfer details" in confirmation.data
    assert b"R 57.50" in confirmation.data
    assert client.get("/order/unknown-private-token").status_code == 404


def test_checkout_uses_bank_transfer_and_delivery_details(app, client):
    with app.app_context():
        variant = db.session.scalar(select(ProductVariant).where(ProductVariant.name == "Small"))
        variant_id = variant.id
    client.post("/cart/add", data={"variant_id": str(variant_id), "quantity": "1"})
    checkout_page = client.get("/checkout")
    assert b'name="payment_method"' in checkout_page.data
    assert b'value="bank_transfer"' in checkout_page.data
    assert b"Example Bank" in checkout_page.data
    assert b'id="delivery-field" hidden' in checkout_page.data
    assert re.search(rb'<option(?=[^>]*value="pickup")(?=[^>]*selected)[^>]*>', checkout_page.data)
    assert b'<option value="delivery">Delivery</option>' in checkout_page.data
    assert b'<option value="Central">Central</option>' in checkout_page.data
    assert b'class="bank-transfer-panel"' in checkout_page.data
    response = client.post("/checkout", data={
        "customer_name": "Delivery Customer", "customer_phone": "+27111222333",
        "fulfillment": "delivery", "delivery_zone": "Central", "delivery_address": "10 Main Road",
        "delivery_instructions": "Use side entrance", "order_notes": "Leave at reception",
        "payment_method": "bank_transfer", "terms_acknowledged": "y",
    })
    assert response.status_code == 302
    confirmation = client.get(response.headers["Location"])
    assert b"Delivery in Central to 10 Main Road" in confirmation.data
    assert b"R 5.00" in confirmation.data
    assert b"R 3.75" in confirmation.data
    with app.app_context():
        order = db.session.scalar(select(Order).where(Order.customer_name == "Delivery Customer"))
        assert order.order_notes == "Leave at reception"
        assert order.delivery_instructions == "Use side entrance"
        assert order.delivery_fee_minor == 500
        assert order.tax_minor == 375


def test_checkout_shows_prompt_when_fulfillment_is_not_enabled(app, client):
    with app.app_context():
        variant = db.session.scalar(select(ProductVariant).where(ProductVariant.name == "Small"))
        variant_id = variant.id
        settings = db.session.scalar(select(BusinessSettings).limit(1))
        settings.pickup_enabled = False
        settings.delivery_enabled = False
        settings.delivery_zones = ""
        db.session.commit()
    with client.session_transaction() as session:
        session["cart"] = {str(variant_id): {"quantity": 1}}
    response = client.get("/checkout")
    assert response.status_code == 200
    assert b'<option selected value="">Choose pickup or delivery</option>' in response.data
    assert b"Pickup and delivery are currently unavailable" in response.data
    assert b"Ordering unavailable" in response.data


def test_pickup_code_is_visible_to_admin(app, client):
    with app.app_context():
        variant = db.session.scalar(select(ProductVariant).where(ProductVariant.name == "Small"))
        order = create_order(checkout_form(), {str(variant.id): {"quantity": 1}}, "pickup-redemption")
        order_id, pickup_code = order.id, order.reference
    client.post("/admin/login", data={"email": "staff@example.com", "password": "correct-horse-battery-2"})
    response = client.get(f"/admin/orders/{order_id}")
    assert response.status_code == 200
    assert b"Pickup redemption code" in response.data
    assert pickup_code.encode() in response.data


def test_checkout_requires_terms_acknowledgement(app, client):
    with app.app_context():
        variant = db.session.scalar(select(ProductVariant).where(ProductVariant.name == "Small"))
        variant_id = variant.id
    client.post("/cart/add", data={"variant_id": str(variant_id), "quantity": "1"})
    response = client.post("/checkout", data={
        "customer_name": "No Consent", "customer_phone": "+27111222333", "customer_email": "consent@example.com",
        "fulfillment": "pickup", "pickup_name": "No Consent", "payment_method": "pay_on_pickup",
    })
    assert response.status_code == 200
    assert b"Please acknowledge the order terms." in response.data
    with app.app_context():
        assert db.session.scalar(select(db.func.count(Order.id))) == 0


def test_cart_can_change_variant_and_reject_overstock(app, client):
    with app.app_context():
        small = db.session.scalar(select(ProductVariant).where(ProductVariant.name == "Small"))
        medium = db.session.scalar(select(ProductVariant).where(ProductVariant.name == "Medium"))
        small_id, medium_id = small.id, medium.id
        small.product.stock_quantity = 3
        db.session.commit()
    with client.session_transaction() as session:
        session["cart"] = {str(small_id): {"quantity": 2}}
    response = client.post("/cart", data={"action": "change_variant", "variant_id": str(small_id), "new_variant_id": str(medium_id)}, follow_redirects=True)
    assert response.status_code == 200
    assert b"Medium" in response.data
    with client.session_transaction() as session:
        assert session["cart"] == {str(medium_id): {"quantity": 2}}
    overstock = client.post("/cart", data={"action": "update", "variant_id": str(medium_id), "quantity": "4"}, follow_redirects=True)
    assert b"Only 3" in overstock.data
    with client.session_transaction() as session:
        assert session["cart"][str(medium_id)]["quantity"] == 2
    blocked_add = client.post("/cart/add", data={"variant_id": str(small_id), "quantity": "2"}, follow_redirects=True)
    assert b"Only 3" in blocked_add.data
    with client.session_transaction() as session:
        assert session["cart"] == {str(medium_id): {"quantity": 2}}


def test_checkout_redirects_when_cart_stock_has_changed(app, client):
    with app.app_context():
        variant = db.session.scalar(select(ProductVariant).where(ProductVariant.name == "Small"))
        variant.product.stock_quantity = 1
        variant_id = variant.id
        db.session.commit()
    with client.session_transaction() as session:
        session["cart"] = {str(variant_id): {"quantity": 2}}
    response = client.get("/checkout", follow_redirects=True)
    assert response.status_code == 200
    assert b"Review it before checkout" in response.data
    assert b"Remove unavailable items" in response.data


def test_availability_filter_keeps_sold_out_products_discoverable(app, client):
    with app.app_context():
        product = db.session.scalar(select(Product).where(Product.slug == "cappuccino"))
        sold_out = Product(category_id=product.category_id, name="Sold Out Mocha", slug="sold-out-mocha", active=True, available=True, stock_quantity=0)
        sold_out.variants.append(ProductVariant(name="Regular", price_minor=3000))
        db.session.add(sold_out)
        db.session.commit()
    available = client.get("/menu?availability=available")
    unavailable = client.get("/menu?availability=unavailable")
    assert available.status_code == unavailable.status_code == 200
    assert b"Sold Out Mocha" not in available.data
    assert b"Sold Out Mocha" in unavailable.data
    assert b"Sold out" in unavailable.data


def test_stock_is_reserved_and_restored_once_on_cancellation(app, client):
    with app.app_context():
        variant = db.session.scalar(select(ProductVariant).where(ProductVariant.name == "Small"))
        variant.product.stock_quantity = 3
        db.session.commit()
        product_id = variant.product_id
        order = create_order(checkout_form(), {str(variant.id): {"quantity": 2}}, "stock-reservation")
        order_id = order.id
        assert db.session.get(Product, product_id).stock_quantity == 1
    client.post("/admin/login", data={"email": "staff@example.com", "password": "correct-horse-battery-2"})
    cancelled = client.post(f"/admin/orders/{order_id}/status", data={"status": "cancelled", "reason": "Customer changed plans", "submit": "Update order"})
    assert cancelled.status_code == 302
    with app.app_context():
        assert db.session.get(Product, product_id).stock_quantity == 3
        assert db.session.get(Order, order_id).stock_released_at is not None


def test_customer_history_only_lists_the_authenticated_users_orders(app, client):
    client.post("/account/register", data={"full_name": "First Customer", "email": "first@example.com", "password": "a-long-customer-pass"})
    with app.app_context():
        first = db.session.scalar(select(User).where(User.email == "first@example.com"))
        other = User(full_name="Other Customer", email="other@example.com", role="customer")
        other.set_password("another-long-customer-pass")
        db.session.add(other)
        db.session.commit()
        variant = db.session.scalar(select(ProductVariant).where(ProductVariant.name == "Small"))
        own_order = create_order(checkout_form(), {str(variant.id): {"quantity": 1}}, "first-customer-order", user_id=first.id)
        other_order = create_order(checkout_form(), {str(variant.id): {"quantity": 1}}, "other-customer-order", user_id=other.id)
        own_reference, other_reference = own_order.reference.encode(), other_order.reference.encode()
    history = client.get("/orders")
    assert history.status_code == 200
    assert own_reference in history.data
    assert other_reference not in history.data


def test_catalogue_seed_is_repeatable_and_requires_review(app):
    runner = app.test_cli_runner()
    first = runner.invoke(args=["seed-menu"])
    assert first.exit_code == 0, first.output
    assert "Products created:" in first.output
    assert "assorted-giant-coddies" in first.output
    with app.app_context():
        first_count = db.session.scalar(select(db.func.count(Product.id)))
        assert first_count == 32
        assert db.session.scalar(select(db.func.count(ProductVariant.id))) == 55
        assert db.session.scalar(select(db.func.count(Order.id))) == 0
        categories = db.session.scalars(select(Category).order_by(Category.sort_order)).all()
        assert [(category.name, category.slug, category.active) for category in categories] == [
            ("Coffee & Hot Drinks", "coffee", True), ("Smoothies", "smoothies", True),
            ("Milkshakes", "milkshakes", True), ("Sandwiches & Bakery", "sandwiches-bakery", True),
        ]
        expected_review = {"chicken-mayo-sandwich-r22-review", "assorted-giant-coddies"}
        image_manifest = json.loads((Path(app.static_folder) / "images/menu/image-manifest.json").read_text(encoding="utf-8"))["images"]
        matched_product_ids = set()
        for category_name, category_slug, items in CATALOGUE:
            category = db.session.scalar(select(Category).where(Category.slug == category_slug))
            for entry in items:
                candidates = db.session.scalars(select(Product).where(Product.category_id == category.id, Product.name == entry["name"])).all()
                product = next((candidate for candidate in candidates if all(
                    any(variant.name == variant_name and variant.price_minor == price and variant.active for variant in candidate.variants)
                    for variant_name, price in entry["variants"]
                ) and candidate.review_required is entry["review"]), None)
                assert product is not None, entry["slug"]
                assert product.id not in matched_product_ids, f"duplicate source mapping for {entry['slug']}"
                matched_product_ids.add(product.id)
                prices = {variant.name: variant.price_minor for variant in product.variants if variant.active}
                assert prices == dict(entry["variants"]), (entry["slug"], prices)
                assert product.review_required is (entry["slug"] in expected_review)
                if entry["review"]:
                    assert product.active is False
                else:
                    assert product.active is True
                assert product.image_url.startswith("/static/images/menu/")
                image_file = app.static_folder + product.image_url.removeprefix("/static")
                assert Path(image_file).is_file()
                assert product.image_alt
                assert product.image_review_required is (entry["slug"] not in image_manifest)
                if entry["slug"] in image_manifest:
                    image = image_manifest[entry["slug"]]
                    image_bytes = Path(image_file).read_bytes()
                    assert image_bytes.startswith(b"\xff\xd8\xff")
                    assert image["source_page"].startswith("https://commons.wikimedia.org/wiki/File:")
                    assert image["creator"] and image["license"]
                else:
                    assert "placeholder" in product.image_alt.lower() or entry["slug"] == "assorted-giant-coddies"
        assert len(matched_product_ids) == 32
    second = runner.invoke(args=["seed-catalogue"])
    assert second.exit_code == 0, second.output
    with app.app_context():
        assert db.session.scalar(select(db.func.count(Product.id))) == first_count
        assert db.session.scalar(select(db.func.count(ProductVariant.id))) == 55


def test_catalogue_seed_preserves_manual_price_and_image_changes(app):
    runner = app.test_cli_runner()
    initial = runner.invoke(args=["seed-menu"])
    assert initial.exit_code == 0, initial.output
    with app.app_context():
        product = db.session.scalar(select(Product).where(Product.name == "Cappuccino"))
        product.variants[0].price_minor = 2599
        product.image_url = "/media/business-cappuccino.jpg"
        db.session.commit()
    rerun = runner.invoke(args=["seed-menu"])
    assert rerun.exit_code == 0, rerun.output
    assert "cappuccino/Small" in rerun.output
    with app.app_context():
        product = db.session.scalar(select(Product).where(Product.name == "Cappuccino"))
        assert next(variant for variant in product.variants if variant.name == "Small").price_minor == 2599
        assert product.image_url == "/media/business-cappuccino.jpg"


def test_catalogue_seed_upgrades_placeholder_when_verified_photo_is_available(app):
    with app.app_context():
        product = db.session.scalar(select(Product).where(Product.slug == "cappuccino"))
        product.image_url = "/static/images/menu/fallback-coffee.svg"
        product.image_alt = "Cappuccino: illustrative category placeholder; product photo pending."
        product.image_review_required = True
        db.session.commit()
    result = app.test_cli_runner().invoke(args=["seed-menu"])
    assert result.exit_code == 0, result.output
    with app.app_context():
        product = db.session.scalar(select(Product).where(Product.slug == "cappuccino"))
        assert product.image_url == "/static/images/menu/cappuccino.jpg"
        assert product.image_review_required is False


def test_catalogue_seed_never_changes_existing_order_snapshots(app):
    runner = app.test_cli_runner()
    assert runner.invoke(args=["seed-menu"]).exit_code == 0
    with app.app_context():
        product = db.session.scalar(select(Product).where(Product.name == "Cappuccino"))
        variant = next(variant for variant in product.variants if variant.name == "Small")
        order = Order(customer_name="History", customer_phone="+27123456789", fulfillment="pickup", subtotal_minor=5000,
                      total_minor=5000, payment_method="pay_on_pickup")
        from app.models import OrderItem
        order.items.append(OrderItem(product_id=product.id, variant_id=variant.id, product_name=product.name,
                                     variant_name=variant.name, unit_price_minor=2500, quantity=2, line_total_minor=5000))
        db.session.add(order)
        db.session.commit()
        order_id = order.id
    rerun = runner.invoke(args=["seed-menu"])
    assert rerun.exit_code == 0, rerun.output
    with app.app_context():
        order = db.session.get(Order, order_id)
        assert order.items[0].product_name == "Cappuccino"
        assert order.items[0].unit_price_minor == 2500
        assert order.items[0].line_total_minor == 5000


def test_menu_page_reads_published_database_catalogue(app, client):
    with app.app_context():
        category = db.session.scalar(select(Category).where(Category.slug == "coffee"))
        product = Product(category_id=category.id, name="Published Flat White", slug="published-flat-white", active=True, available=True, image_url="/static/images/menu/fallback-coffee.svg", image_alt="Coffee placeholder")
        product.variants.extend([ProductVariant(name="Small", price_minor=2500), ProductVariant(name="Medium", price_minor=3500)])
        db.session.add(product)
        db.session.commit()
    response = client.get("/menu?category=coffee")
    assert response.status_code == 200
    assert b"Published Flat White" in response.data
    assert b"R 25.00" in response.data
    assert b"R 35.00" in response.data


def test_checkout_uses_database_price_and_snapshots(app):
    with app.app_context():
        variant = db.session.scalar(select(ProductVariant).where(ProductVariant.name == "Small"))
        order = create_order(checkout_form(), {str(variant.id): {"quantity": 2, "price": 1}}, "checkout-1")
        assert order.subtotal_minor == 5000
        assert order.tax_minor == 750
        assert order.total_minor == 5750
        assert order.items[0].unit_price_minor == 2500
        assert order.terms_acknowledged_at is not None
        assert order.tracking_token != str(order.id)
        assert db.session.get(Order, order.id).idempotency_key == "checkout-1"


def test_duplicate_submission_returns_existing_order(app):
    with app.app_context():
        variant = db.session.scalar(select(ProductVariant).where(ProductVariant.name == "Small"))
        cart = {str(variant.id): {"quantity": 1}}
        first = create_order(checkout_form(), cart, "same-token")
        again = create_order(checkout_form(), cart, "same-token")
        assert first.id == again.id
        assert db.session.scalar(select(db.func.count(Order.id))) == 1


def test_delivery_needs_configured_zone(app):
    with app.app_context():
        variant = db.session.scalar(select(ProductVariant).where(ProductVariant.name == "Small"))
        cart = {str(variant.id): {"quantity": 1}}
        with pytest.raises(ValueError, match="configured delivery area"):
            create_order(checkout_form(fulfillment="delivery", payment_method="pay_on_delivery", delivery_address="10 Main Road", delivery_zone="Elsewhere"), cart, "delivery-invalid")
        order = create_order(checkout_form(fulfillment="delivery", payment_method="pay_on_delivery", delivery_address="10 Main Road", delivery_zone="Central"), cart, "delivery-valid")
        assert order.delivery_fee_minor == 500
        assert order.delivery_zone == "Central"


def test_disabled_fulfillment_is_rejected(app):
    with app.app_context():
        settings = db.session.scalar(select(BusinessSettings))
        settings.pickup_enabled = False
        db.session.commit()
        variant = db.session.scalar(select(ProductVariant).where(ProductVariant.name == "Small"))
        with pytest.raises(ValueError, match="Pickup is not currently available"):
            create_order(checkout_form(), {str(variant.id): {"quantity": 1}}, "disabled-pickup")


def test_order_transition_graph_rejects_invalid_next_state():
    assert "preparing" in ORDER_TRANSITIONS["accepted"]
    assert "completed" not in ORDER_TRANSITIONS["pending_confirmation"]
    assert not ORDER_TRANSITIONS["cancelled"]


def test_admin_is_protected_and_role_gated(client):
    assert client.get("/admin").status_code in (302, 401)
    login = client.post("/admin/login", data={"email": "staff@example.com", "password": "correct-horse-battery-2"}, follow_redirects=True)
    assert login.status_code == 200
    assert client.get("/admin/products").status_code == 403
    assert client.get("/admin/orders").status_code == 200


def test_admin_can_update_status_and_collect_pay_later(app, client):
    with app.app_context():
        variant = db.session.scalar(select(ProductVariant).where(ProductVariant.name == "Small"))
        order = create_order(checkout_form(), {str(variant.id): {"quantity": 1}}, "staff-order")
        order_id = order.id
    client.post("/admin/login", data={"email": "staff@example.com", "password": "correct-horse-battery-2"})
    changed = client.post(f"/admin/orders/{order_id}/status", data={"status": "accepted", "reason": "In service", "submit": "Update order"})
    assert changed.status_code == 302
    collected = client.post(f"/admin/orders/{order_id}/collect", data={"amount": "28.75", "method": "cash", "submit": "Record payment"})
    assert collected.status_code == 302
    with app.app_context():
        order = db.session.get(Order, order_id)
        assert order.status == "accepted"
        assert order.payment_status == "paid"
        payment = db.session.scalar(select(Payment).where(Payment.order_id == order_id))
        assert payment.collection_method == "cash"
        assert payment.collected_by_id is not None


def test_admin_report_screens_render(client):
    client.post("/admin/login", data={"email": "admin@example.com", "password": "correct-horse-battery-1"})
    assert client.get("/admin/reports").status_code == 200
    assert client.get("/admin/reports.csv").status_code == 200
    assert client.get("/admin/products?category=milkshakes&availability=review").status_code == 200


def test_public_image_credits_list_only_verified_local_photos(client):
    response = client.get("/image-credits")
    assert response.status_code == 200
    assert b"Cappuccino" in response.data
    assert b"CC BY 3.0" in response.data
    assert b"Bubblegum" not in response.data


def test_admin_can_set_product_stock(app, client):
    client.post("/admin/login", data={"email": "admin@example.com", "password": "correct-horse-battery-1"})
    with app.app_context():
        product = db.session.scalar(select(Product).where(Product.slug == "cappuccino"))
        product_id, category_id = product.id, product.category_id
    editor = client.get(f"/admin/products/{product_id}/edit")
    assert editor.status_code == 200
    assert b"Stock quantity" in editor.data
    response = client.post(f"/admin/products/{product_id}/edit", data={
        "name": "Cappuccino", "category_id": str(category_id), "description": "Espresso with steamed milk.",
        "image_url": "", "small_price": "25.00", "medium_price": "35.00", "regular_price": "",
        "stock_quantity": "0", "active": "y", "available": "y", "featured": "",
    })
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Product, product_id).stock_quantity == 0


def test_unknown_tracking_token_does_not_reveal_order(client):
    assert client.get("/order/not-a-valid-token").status_code == 404


def test_webhook_signature_and_duplicate_success_are_safe(app):
    with app.app_context():
        app.config["PAYSTACK_SECRET_KEY"] = "test-secret"
        variant = db.session.scalar(select(ProductVariant).where(ProductVariant.name == "Small"))
        order = create_order(checkout_form(payment_method="online", customer_email="customer@example.com"), {str(variant.id): {"quantity": 1}}, "online-order")
        payment = order.payments[0]
        body = b"verified payload"
        import hashlib
        import hmac
        signature = hmac.new(b"test-secret", body, hashlib.sha512).hexdigest()
        assert valid_paystack_signature(body, signature)
        assert not valid_paystack_signature(body, "bad")
        event = {"event": "charge.success", "data": {"id": 101, "reference": payment.transaction_reference, "amount": payment.amount_minor, "currency": "ZAR", "status": "success"}}
        assert process_paystack_event(event)
        assert process_paystack_event(event)
        assert db.session.get(Payment, payment.id).status == "paid"


def test_payment_verify_checks_reference_amount_and_currency(app, monkeypatch):
    with app.app_context():
        app.config["PAYSTACK_SECRET_KEY"] = "test-secret"
        variant = db.session.scalar(select(ProductVariant).where(ProductVariant.name == "Small"))
        order = create_order(checkout_form(payment_method="online", customer_email="customer@example.com"), {str(variant.id): {"quantity": 1}}, "verify-order")
        payment = order.payments[0]

        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return {"data": {"status": "success", "reference": payment.transaction_reference, "amount": payment.amount_minor, "currency": "ZAR", "id": 202}}

        monkeypatch.setattr("app.services.requests.get", lambda *args, **kwargs: Response())
        assert verify_paystack(payment.transaction_reference)
        assert db.session.get(Payment, payment.id).status == "paid"