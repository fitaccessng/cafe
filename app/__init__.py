import os
from pathlib import Path

from flask import Flask, jsonify

from .config import get_config
from .extensions import csrf, db, limiter, login_manager, migrate


def create_app(config_name=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(get_config(config_name))
    if app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:"):
        os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    app.config["RATELIMIT_STORAGE_URI"] = app.config.get("REDIS_URL") or "memory://"
    limiter.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "error"

    from . import models
    from .routes import admin, auth, shop
    from .commands import register_commands

    app.register_blueprint(shop.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(admin.bp)
    register_commands(app)

    @app.get("/health")
    def health():
        try:
            db.session.execute(db.text("SELECT 1"))
        except Exception:
            app.logger.exception("Health check database failure")
            return jsonify(status="unhealthy"), 503
        return jsonify(status="ok"), 200

    @app.get("/media/<path:filename>")
    def uploaded_media(filename):
        from flask import send_from_directory

        response = send_from_directory(app.config["UPLOAD_FOLDER"], filename)
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.template_filter("zar")
    def zar(minor_units):
        return f"R {int(minor_units) / 100:,.2f}"

    @app.context_processor
    def cart_context():
        from flask import session

        cart = session.get("cart", {})
        return {"cart_count": sum(max(0, int(item.get("quantity", 0))) for item in cart.values())}

    return app