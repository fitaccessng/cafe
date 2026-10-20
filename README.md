# Café Coffee Day Ordering

Flask/Jinja storefront and single-outlet ordering application using Flask-SQLAlchemy, PostgreSQL, Flask-Migrate, Flask-Login, Flask-WTF, and Flask-Limiter. Money is stored as integer minor units in ZAR. Order items retain historical product and price snapshots. Optional product stock is reserved during order placement and restored once on permitted cancellation.

## Local setup

Python 3.12 or later and PostgreSQL 15+ are recommended. A local SQLite database is available for development and tests only.

```sh
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set a local `SECRET_KEY` and `DATABASE_URL` in `.env`. For PostgreSQL, create a database and set, for example, `DATABASE_URL=postgresql+psycopg://cafe:password@localhost:5432/cafe_coffee`. Do not use the example credentials outside a disposable local environment. Set `FLASK_ENV=development` when loading the file in your shell.

## Database and first-run setup

```sh
flask --app wsgi db upgrade
flask --app wsgi seed-menu
flask --app wsgi create-admin
# Optional order-management account:
flask --app wsgi create-staff
flask --app wsgi run
```

The `seed-menu` command is repeatable: it creates missing source rows, adds missing variants, never removes orders, and preserves existing price/image corrections by default. The explicit `--override-managed` option reconciles existing product names, prices, availability and image URLs to the provided catalogue. Only the conflicting R22 Chicken & Mayo Sandwich and “Assorted Giant Coddies” entries remain unpublished for admin review. Do not run the command as an implicit deployment hook.

Product images live in `app/static/images/menu/`. `scripts/fetch_menu_images.py` downloads only the curated Wikimedia Commons sources in `image-sources.json`, checks response type/signature, converts to optimized local JPEGs, and records creator, source and license metadata in `image-manifest.json`. Failed downloads are not marked verified; the seeder uses labeled local category placeholders and lists image gaps. Photo credits are visible at `/image-credits`. Stock photographs are illustrative, not depictions of the café's actual servings.

Current local media review: 13 of 32 catalogue entries have verified locally stored photo files; 19 retain labeled category/neutral placeholders. Photo gaps: Chicken & Mayo Sandwich (R25), Egg Mayo Sandwich, Club Sandwich, Cheese & Tomato Sandwich, Cheese & Tomato Croissants, Chicken Mayo Croissant, Plain Croissants, Mango, Strawberry, Peanut Butter, Oatmeal and Cookies & Cream smoothies, Earl Grey Tea, Chocolate, Banana, Berry and Bubblegum Milkshakes, plus “Assorted Giant Coddies”. The duplicate R22 sandwich entry and Coddies remain unpublished; Coddies has a neutral placeholder. See [image-review-report.md](app/static/images/menu/image-review-report.md).

Business settings default to disabled fulfillment. Sign in at `/admin/login`; configure the outlet, hours, serviceable delivery places (one per line), delivery fee, tax rate, pickup/delivery estimates, bank transfer details and promotions before accepting orders. Checkout currently accepts bank transfer only. An initial admin is created only with the interactive `create-admin` command. No default credentials are shipped. Customers may create accounts at `/account/register` for their own `/orders` history; guest orders remain available only through their private tracking token. Pickup customers receive a unique order reference to present as their redemption code.

## Tests

```sh
pytest -q
```

Tests use an isolated in-memory SQLite database and mock Paystack responses. They do not prove merchant eligibility, gateway onboarding, network behavior, or production PostgreSQL availability.

## Online payments

The gateway adapter currently targets Paystack's hosted transaction initialization, server-side transaction verification, ZAR amount/currency checks, and HMAC-SHA512 signed webhooks. Online payment is not offered unless the merchant secret is configured. Before enabling it, the business must confirm South African merchant eligibility, ZAR transaction and settlement support, account setup, enabled payment methods, and a live or sandbox environment with Paystack. Configure `PAYSTACK_SECRET_KEY`, `PAYSTACK_PUBLIC_KEY`, and the externally reachable `CANONICAL_ORIGIN`; register `/payment/webhook` at the provider. Never treat the return URL as proof of payment. Do not set live credentials until the sandbox tests and webhook configuration have been verified.

The current checkout does not offer hosted online payment; customers receive configured bank details and use their unique order reference as the transfer reference. Bank transfers remain unpaid until an authenticated staff member verifies and records the EFT in admin. Existing Paystack verification and webhook handlers remain available for historical transactions, but are not selectable at checkout. Card credentials are never handled or stored by this application.

## Production deployment

Use a supported Linux host, PostgreSQL, HTTPS, a private upload volume or object storage, and a shared Redis/Valkey-compatible limiter store for multi-worker rate limiting. Configure:

- `FLASK_ENV=production`
- `SECRET_KEY` with a high-entropy secret from a secret manager
- `DATABASE_URL` using `postgresql+psycopg://`
- `REDIS_URL` for shared rate-limit state
- `CANONICAL_ORIGIN` as the public HTTPS origin
- `PAYSTACK_SECRET_KEY` and `PAYSTACK_PUBLIC_KEY` only after merchant verification
- `UPLOAD_FOLDER` as durable, non-executable media storage

Production refuses to start without required secrets/database settings and forces secure session cookies. Run migrations as a reviewed release step, not on every application boot:

```sh
flask --app wsgi db upgrade
gunicorn --workers 3 --bind 0.0.0.0:8000 wsgi:app
```

Health check: `GET /health` verifies database connectivity. Put TLS termination and request-size limits at the reverse proxy. Restrict admin access operationally, rotate secrets, retain logs only as long as needed, and never log gateway secrets or full payment credentials.

## Migrations

Create a reviewed migration after model changes:

```sh
flask --app wsgi db migrate -m "describe schema change"
flask --app wsgi db upgrade
```

Review generated SQL and test both upgrade and rollback strategy against a disposable copy before production. Do not use `db create_all()` in production.

## Backup and restore

Use managed PostgreSQL backups where available. For a manual logical backup, use credentials provided via protected environment/PG service files, not command-line password arguments:

```sh
pg_dump --format=custom --no-owner --file=cafe-$(date -u +%Y%m%dT%H%M%SZ).dump "$DATABASE_URL"
pg_restore --list cafe-backup.dump
```

Restore into a new, empty recovery database first, validate the restored application and order history, then follow the hosting provider's controlled recovery procedure. Do not restore over production without an approved incident/recovery plan. Database backups do not include product uploads; back up the configured media volume separately and test restoring both together. Encrypt backups, restrict access, and apply retention/deletion policies.

## Operational checklist

- Confirm the single outlet's contact details, hours, pickup prep estimate, delivery zones and fees.
- Confirm every menu name, image, price, size, tax and minimum order before publishing.
- Verify merchant country/account eligibility, ZAR settlement, enabled payment methods, hosted checkout, webhook signature and refunds in the provider sandbox.
- Confirm PostgreSQL migrations and restore procedure against staging.
- Configure shared limiter storage, HTTPS, durable media, monitoring, structured log shipping and retention.
- Exercise pickup/delivery, pay-later collection, cancellation, unavailable products, gateway failure/retry, customer tracking and staff authorization on staging.

## Current limitations

- A real Paystack merchant account, eligibility, payment methods, settlement configuration and live credentials cannot be established from this repository. Refund initiation/reconciliation is not implemented; refunded records must not be represented as supported until an approved provider flow and staff permissions are built.
- Email/SMS notifications are not implemented. Guest tracking uses a high-entropy private token; signed-in customer order history is restricted to orders linked to that account.
- Uploaded product images are restricted to PNG/JPEG/WebP signatures and 5 MB, but malware scanning/object-storage lifecycle controls must be supplied by deployment operations.
- Browser automation, PostgreSQL integration tests, tax/legal configuration, delivery-zone policy and operational details require business-provided values and staging infrastructure.
- The supplied brief did not include an actual logo or menu image; the storefront uses the business name as text and photographic image URLs, not a fabricated logo or poster.