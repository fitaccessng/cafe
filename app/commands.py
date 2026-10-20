import re
import unicodedata
import json
from pathlib import Path

import click
from flask import current_app
from sqlalchemy import select

from .extensions import db
from .models import BusinessSettings, Category, Product, ProductVariant, User

def item(slug, name, variants, *, review=False, alt=None):
    return {"slug": slug, "name": name, "variants": variants, "review": review,
            "alt": alt or f"Illustrative product image for {name}; not a representation of the served item."}


CATALOGUE = [
    ("Coffee & Hot Drinks", "coffee", [
        item("cappuccino", "Cappuccino", [("Small", 2500), ("Medium", 3500)], alt="Cappuccino with latte art, illustrative stock photograph."),
        item("cafe-latte", "Café Latte", [("Small", 3000), ("Medium", 3800)], alt="Café latte in a cup, illustrative stock photograph."),
        item("americano", "Americano", [("Small", 2800), ("Medium", 3500)], alt="Black Americano coffee, illustrative stock photograph."),
        item("flat-white", "Flat White", [("Small", 2500), ("Medium", 3500)], alt="Flat white with latte art, illustrative stock photograph."),
        item("hot-chocolate", "Hot Chocolate", [("Small", 3000), ("Medium", 4000)], alt="Cup of hot chocolate, illustrative stock photograph."),
        item("green-tea", "Green Tea", [("Small", 2000), ("Medium", 2800)], alt="Green tea in a cup, illustrative stock photograph."),
        item("earl-grey-tea", "Earl Grey Tea", [("Small", 2000), ("Medium", 2800)], alt="Earl Grey tea in a cup, illustrative stock photograph."),
        item("rooibos-tea", "Rooibos Tea", [("Small", 2000), ("Medium", 2800)], alt="Rooibos tea in a cup, illustrative stock photograph."),
        item("matcha-latte", "Matcha Latte", [("Small", 2500), ("Medium", 3500)], alt="Matcha latte, illustrative stock photograph."),
        item("chai-latte", "Chai Latte", [("Small", 3000), ("Medium", 3800)], alt="Chai latte, illustrative stock photograph."),
    ]),
    ("Smoothies", "smoothies", [
        item("mixed-berry", "Mixed Berry", [("Small", 3000), ("Medium", 4000)], alt="Mixed berry smoothie, illustrative stock photograph."),
        item("mango", "Mango", [("Small", 3000), ("Medium", 4000)], alt="Mango smoothie, illustrative stock photograph."),
        item("green-smoothie", "Green Smoothie", [("Small", 3000), ("Medium", 4000)], alt="Green smoothie, illustrative stock photograph."),
        item("blueberry-smoothie", "Blueberry", [("Small", 3000), ("Medium", 4000)], alt="Blueberry smoothie, illustrative stock photograph."),
        item("strawberry-smoothie", "Strawberry", [("Small", 3000), ("Medium", 4000)], alt="Strawberry smoothie, illustrative stock photograph."),
        item("peanut-butter", "Peanut Butter", [("Small", 3000), ("Medium", 4000)], alt="Peanut butter smoothie, illustrative stock photograph."),
        item("oatmeal", "Oatmeal", [("Small", 3000), ("Medium", 4000)], alt="Oatmeal smoothie, illustrative stock photograph."),
        item("cookies-cream", "Cookies & Cream", [("Small", 3000), ("Medium", 4000)], alt="Cookies and cream smoothie, illustrative stock photograph."),
    ]),
    ("Milkshakes", "milkshakes", [
        item("chocolate-milkshake", "Chocolate", [("Small", 3200), ("Medium", 4200)], alt="Chocolate milkshake, illustrative stock photograph."),
        item("strawberry-milkshake", "Strawberry", [("Small", 3200), ("Medium", 4200)], alt="Strawberry milkshake, illustrative stock photograph."),
        item("banana-milkshake", "Banana", [("Small", 3200), ("Medium", 4200)], alt="Banana milkshake, illustrative stock photograph."),
        item("bubblegum-milkshake", "Bubblegum", [("Small", 3200), ("Medium", 4200)], alt="Bubblegum milkshake, illustrative stock photograph."),
        item("berry-milkshake", "Berry", [("Small", 3200), ("Medium", 4200)], alt="Berry milkshake, illustrative stock photograph."),
    ]),
    ("Sandwiches & Bakery", "sandwiches-bakery", [
        item("egg-mayo-sandwich", "Egg Mayo Sandwich", [("Regular", 2500)], alt="Egg mayonnaise sandwich, illustrative stock photograph."),
        item("club-sandwich", "Club Sandwich", [("Regular", 3500)], alt="Club sandwich, illustrative stock photograph."),
        item("chicken-mayo-sandwich", "Chicken & Mayo Sandwich", [("Regular", 2500)], alt="Chicken mayonnaise sandwich, illustrative stock photograph."),
        item("chicken-mayo-sandwich-r22-review", "Chicken & Mayo Sandwich", [("Regular", 2200)], review=True, alt="Chicken mayonnaise sandwich, illustrative stock image; duplicate price requires review."),
        item("cheese-tomato-sandwich", "Cheese & Tomato Sandwich", [("Regular", 2200)], alt="Cheese and tomato sandwich, illustrative stock photograph."),
        item("assorted-giant-coddies", "Assorted Giant Coddies", [("Regular", 1000)], review=True, alt="Neutral bakery placeholder; product name requires review."),
        item("plain-croissants", "Plain Croissants", [("Regular", 1200)], alt="Plain croissant, illustrative stock photograph."),
        item("cheese-tomato-croissants", "Cheese & Tomato Croissants", [("Regular", 2500)], alt="Cheese and tomato croissant, illustrative stock photograph."),
        item("chicken-mayo-croissant", "Chicken Mayo Croissant", [("Regular", 2500)], alt="Chicken mayonnaise croissant, illustrative stock photograph."),
    ]),
]

CATEGORY_LABELS = {
    "coffee": "Coffee & Hot Drinks",
    "smoothies": "Smoothies",
    "milkshakes": "Milkshakes",
    "sandwiches-bakery": "Sandwiches & Bakery",
}
LEGACY_IMAGE_URLS = {
    "https://images.unsplash.com/photo-1509042239860-f550ce710b93?auto=format&fit=crop&w=900&q=85",
    "https://images.unsplash.com/photo-1505252585461-04db1eb84625?auto=format&fit=crop&w=900&q=85",
    "https://images.unsplash.com/photo-1572490122747-3968b75cc699?auto=format&fit=crop&w=900&q=85",
    "https://images.unsplash.com/photo-1528735602780-2552fd46c7af?auto=format&fit=crop&w=900&q=85",
}
IMAGE_DIRECTORY = Path(__file__).resolve().parent / "static" / "images" / "menu"


def slugify(value):
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")


def register_commands(app):
    @app.cli.command("seed-menu")
    @click.option("--override-managed", is_flag=True, help="Explicitly replace existing product names, prices, availability, and image URLs with this menu manifest.")
    def seed_menu(override_managed):
        """Safely import the Cafe Coffee Day menu and report reconciliation details."""
        manifest_path = IMAGE_DIRECTORY / "image-manifest.json"
        try:
              manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
              image_manifest = manifest.get("images", manifest)
        except (OSError, json.JSONDecodeError) as error:
            raise click.ClickException(f"Cannot read menu image manifest: {error}") from error

        report = {
            "categories_created": [], "categories_updated": [], "products_created": [],
            "products_updated": [], "products_unchanged": [], "variants_created": 0,
            "ambiguous": [], "missing_images": [], "price_differences": [],
        }
        def is_image_file(path):
            try:
                header = path.read_bytes()[:16]
            except OSError:
                return False
            return (header.startswith(b"\xff\xd8\xff") or header.startswith(b"\x89PNG\r\n\x1a\n")
                    or (header[:4] == b"RIFF" and header[8:12] == b"WEBP"))

        for category_order, (category_name, category_slug, entries) in enumerate(CATALOGUE):
            category = db.session.scalar(select(Category).where(Category.slug == category_slug))
            if category is None:
                category = Category(name=category_name, slug=category_slug, sort_order=category_order, active=True)
                db.session.add(category)
                db.session.flush()
                report["categories_created"].append(category_slug)
            elif (category.name != category_name or category.sort_order != category_order or not category.active):
                category.name = category_name
                category.sort_order = category_order
                category.active = True
                report["categories_updated"].append(category_slug)

            for entry in entries:
                expected_variants = dict(entry["variants"])
                product = db.session.scalar(select(Product).where(Product.slug == entry["slug"]))
                if product is None:
                    candidates = db.session.scalars(select(Product).where(
                        Product.category_id == category.id, Product.name == entry["name"],
                    )).all()
                    product = next((candidate for candidate in candidates if any(
                        variant.name in expected_variants and variant.price_minor == expected_variants[variant.name]
                        for variant in candidate.variants
                    )), None)
                    duplicate_source_name = sum(source_entry["name"] == entry["name"] for source_entry in entries) > 1
                    if product is None and len(candidates) == 1 and not duplicate_source_name:
                        product = candidates[0]

                is_new = product is None
                if is_new:
                    product = Product(category_id=category.id, name=entry["name"], slug=entry["slug"])
                    db.session.add(product)
                    db.session.flush()
                    report["products_created"].append(entry["slug"])

                legacy_seed = bool(product.image_url in LEGACY_IMAGE_URLS and product.review_required and not product.active)
                changed = is_new or legacy_seed
                if is_new or override_managed:
                    product.name = entry["name"]
                    product.category_id = category.id
                    if not is_new and product.slug != entry["slug"] and not db.session.scalar(select(Product.id).where(Product.slug == entry["slug"])):
                        product.slug = entry["slug"]
                    product.active = not entry["review"]
                    product.available = True
                    product.review_required = entry["review"]
                    changed = True
                elif legacy_seed:
                    product.category_id = category.id
                    product.review_required = entry["review"]
                    product.active = not entry["review"]
                    product.available = True

                image_record = image_manifest.get(entry["slug"], {})
                relative_image = image_record.get("file", f"{entry['slug']}.jpg")
                image_path = IMAGE_DIRECTORY / Path(relative_image).name
                attribution_present = all(image_record.get(field) for field in ("source_page", "creator", "license"))
                image_verified = bool(attribution_present and is_image_file(image_path))
                if image_verified:
                    desired_image_url = f"/static/images/menu/{image_path.name}"
                    if is_new or override_managed or legacy_seed or product.image_review_required or not product.image_url:
                        if product.image_url != desired_image_url or product.image_review_required:
                            product.image_url = desired_image_url
                            product.image_alt = (image_record.get("alt") or entry["alt"])[:180]
                            product.image_review_required = False
                            changed = True
                else:
                    fallback_name = "fallback-neutral.svg" if entry["slug"] == "assorted-giant-coddies" else f"fallback-{category_slug}.svg"
                    fallback_path = IMAGE_DIRECTORY / fallback_name
                    if not fallback_path.exists():
                        fallback_name = "fallback-neutral.svg"
                        fallback_path = IMAGE_DIRECTORY / fallback_name
                    managed_image_url = f"/static/images/menu/{entry['slug']}.jpg"
                    if (is_new or override_managed or legacy_seed or not product.image_url
                            or product.image_url in LEGACY_IMAGE_URLS or product.image_url == managed_image_url):
                        if fallback_path.exists():
                            fallback_url = f"/static/images/menu/{fallback_name}"
                            if product.image_url != fallback_url or not product.image_review_required:
                                product.image_url = fallback_url
                                product.image_alt = (
                                    f"{entry['name']}: identity and product photo require review."
                                    if entry["slug"] == "assorted-giant-coddies"
                                    else f"{entry['name']}: illustrative category placeholder; product photo pending."
                                )
                                product.image_review_required = True
                                changed = True
                    report["missing_images"].append(entry["slug"])

                existing_variants = {variant.name: variant for variant in product.variants}
                for variant_name, expected_price in entry["variants"]:
                    variant = existing_variants.get(variant_name)
                    if variant is None:
                        product.variants.append(ProductVariant(name=variant_name, price_minor=expected_price, active=True))
                        report["variants_created"] += 1
                        changed = True
                    elif variant.price_minor != expected_price:
                        report["price_differences"].append(
                            f"{product.slug}/{variant_name}: stored {variant.price_minor} cents, source {expected_price} cents"
                        )
                        if override_managed:
                            variant.price_minor = expected_price
                            variant.active = True
                            changed = True

                if entry["review"]:
                    product.review_required = True
                    product.active = False
                    report["ambiguous"].append(entry["slug"])
                if changed:
                    if not is_new:
                        report["products_updated"].append(product.slug)
                else:
                    report["products_unchanged"].append(product.slug)

        if not db.session.scalar(select(BusinessSettings.id).limit(1)):
            db.session.add(BusinessSettings())
        db.session.commit()
        report["products_updated"] = sorted(set(report["products_updated"]))
        report["products_unchanged"] = sorted(set(report["products_unchanged"]))
        report["missing_images"] = sorted(set(report["missing_images"]))
        click.echo("Menu import report")
        click.echo(f"Categories created: {len(report['categories_created'])}; updated: {len(report['categories_updated'])}")
        click.echo(f"Products created: {len(report['products_created'])}; updated: {len(report['products_updated'])}; unchanged: {len(report['products_unchanged'])}")
        click.echo(f"Variants created: {report['variants_created']}")
        click.echo(f"Ambiguous records requiring admin review: {', '.join(report['ambiguous']) or 'none'}")
        click.echo(f"Products missing verified local photos: {', '.join(report['missing_images']) or 'none'}")
        click.echo(f"Price differences preserved: {', '.join(report['price_differences']) or 'none'}")
        if override_managed:
            click.echo("Explicit override enabled: existing menu-managed product values were reconciled to the source catalogue.")

    app.cli.add_command(seed_menu, "seed-catalogue")

    @app.cli.command("create-admin")
    @click.option("--email", prompt=True)
    @click.option("--name", prompt="Full name")
    def create_admin(email, name):
        """Create or promote an administrator with an interactively entered password."""
        normalized_email = email.strip().lower()
        user = db.session.scalar(select(User).where(User.email == normalized_email))
        if user:
            click.echo("An account with that email already exists.", err=True)
            raise click.Abort()
        password = click.prompt("Password (at least 12 characters)", hide_input=True, confirmation_prompt=True)
        if len(password) < 12:
            raise click.ClickException("Password must contain at least 12 characters.")
        user = User(email=normalized_email, full_name=name.strip(), role="admin")
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo("Administrator created.")

    @app.cli.command("create-staff")
    @click.option("--email", prompt=True)
    @click.option("--name", prompt="Full name")
    def create_staff(email, name):
        """Create an order-management staff account with an interactively entered password."""
        normalized_email = email.strip().lower()
        if db.session.scalar(select(User).where(User.email == normalized_email)):
            raise click.ClickException("An account with that email already exists.")
        password = click.prompt("Password (at least 12 characters)", hide_input=True, confirmation_prompt=True)
        if len(password) < 12:
            raise click.ClickException("Password must contain at least 12 characters.")
        user = User(email=normalized_email, full_name=name.strip(), role="staff")
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo("Order-management staff account created.")
