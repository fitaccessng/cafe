from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user, login_user, logout_user
from sqlalchemy import select

from ..extensions import db, limiter
from ..forms import CustomerRegistrationForm, LoginForm
from ..models import User

bp = Blueprint("auth", __name__)


@bp.route("/admin/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("admin.dashboard"))
    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.scalar(select(User).where(User.email == form.email.data.lower().strip(), User.active.is_(True)))
        if user and user.check_password(form.password.data) and user.role in {"admin", "staff"}:
            login_user(user, remember=False, fresh=True)
            return redirect(url_for("admin.dashboard"))
        flash("Email or password is incorrect.", "error")
    return render_template("login.html", form=form, customer_portal=False)


@bp.post("/admin/logout")
def logout():
    logout_user()
    return redirect(url_for("shop.home"))


@bp.route("/account/register", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def customer_register():
    if current_user.is_authenticated:
        return redirect(url_for("shop.customer_orders")) if current_user.role == "customer" else redirect(url_for("admin.dashboard"))
    form = CustomerRegistrationForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if db.session.scalar(select(User.id).where(User.email == email)):
            form.email.errors.append("An account with that email already exists.")
        else:
            user = User(full_name=form.full_name.data.strip(), email=email, role="customer")
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()
            login_user(user, fresh=True)
            flash("Your account is ready.", "success")
            return redirect(url_for("shop.customer_orders"))
    return render_template("account_register.html", form=form)


@bp.route("/account/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def customer_login():
    if current_user.is_authenticated:
        return redirect(url_for("shop.customer_orders")) if current_user.role == "customer" else redirect(url_for("admin.dashboard"))
    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.scalar(select(User).where(User.email == form.email.data.strip().lower(), User.active.is_(True), User.role == "customer"))
        if user and user.check_password(form.password.data):
            login_user(user, remember=False, fresh=True)
            return redirect(url_for("shop.customer_orders"))
        flash("Email or password is incorrect.", "error")
    return render_template("login.html", form=form, customer_portal=True)


@bp.post("/account/logout")
def customer_logout():
    logout_user()
    return redirect(url_for("shop.home"))