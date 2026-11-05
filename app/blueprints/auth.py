"""Login, registration, logout and password change."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..auth import (
    clear_login_failures,
    get_current_user,
    is_login_locked,
    login_user,
    login_required,
    logout_user,
    record_login_failure,
)
from ..extensions import db
from ..models import ROLE_CUSTOMER, CustomerProfile, User
from ..utils import safe_next_url, validate_email, validate_phone

bp = Blueprint("auth", __name__)


def _dashboard_for(user: User) -> str:
    return url_for(user.dashboard_endpoint)


@bp.route("/login", methods=["GET", "POST"])
def login():
    user = get_current_user()
    if user is not None:
        return redirect(_dashboard_for(user))

    next_url = safe_next_url(request.args.get("next") or request.form.get("next"))
    if request.method == "POST":
        identifier = (request.form.get("identifier") or "").strip()
        password = request.form.get("password") or ""

        if not identifier or not password:
            flash("Enter your username/email and password.", "danger")
        elif is_login_locked(identifier):
            flash("Too many failed attempts. Please wait 10 minutes and try again.", "danger")
        else:
            account = User.query.filter(
                db.or_(User.username == identifier, User.email == identifier.lower())
            ).first()
            if account is None or not account.check_password(password):
                record_login_failure(identifier)
                flash("Invalid username/email or password.", "danger")
            elif not account.is_active:
                flash("This account has been deactivated. Contact the administrator.", "danger")
            else:
                clear_login_failures(identifier)
                login_user(account)
                flash(f"Welcome back, {account.name.split(' ')[0]}!", "success")
                return redirect(next_url or _dashboard_for(account))

    return render_template("auth/login.html", next_url=next_url or "")


@bp.route("/register", methods=["GET", "POST"])
def register():
    user = get_current_user()
    if user is not None:
        return redirect(_dashboard_for(user))

    form = {key: request.form.get(key, "").strip() for key in (
        "name", "username", "email", "phone", "address", "city", "password", "confirm_password"
    )}
    if request.method == "POST":
        errors = []
        if len(form["name"]) < 3:
            errors.append("Please enter your full name.")
        if len(form["username"]) < 3 or " " in form["username"]:
            errors.append("Username must be at least 3 characters and contain no spaces.")
        if not validate_email(form["email"]):
            errors.append("Please enter a valid email address.")
        if form["phone"] and not validate_phone(form["phone"]):
            errors.append("Please enter a valid phone number.")
        if len(form["password"]) < 8:
            errors.append("Password must be at least 8 characters long.")
        if form["password"] != form["confirm_password"]:
            errors.append("Passwords do not match.")
        if User.query.filter(
            db.or_(
                db.func.lower(User.username) == form["username"].lower(),
                db.func.lower(User.email) == form["email"].lower(),
            )
        ).first():
            errors.append("An account with that username or email already exists.")

        if errors:
            for error in errors:
                flash(error, "danger")
        else:
            account = User(
                name=form["name"],
                username=form["username"],
                email=form["email"].lower(),
                phone=form["phone"],
                role=ROLE_CUSTOMER,
            )
            account.set_password(form["password"])
            account.customer_profile = CustomerProfile(
                address=form["address"], city=form["city"]
            )
            db.session.add(account)
            db.session.commit()
            login_user(account)
            flash("Your account is ready. Start exploring restaurants!", "success")
            return redirect(url_for("customer.dashboard"))

    return render_template("auth/register.html", form=form)


@bp.post("/logout")
def logout():
    if get_current_user() is not None:
        logout_user()
        flash("You have been signed out.", "info")
    return redirect(url_for("main.index"))


@bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    user = get_current_user()
    if request.method == "POST":
        current = request.form.get("current_password") or ""
        new = request.form.get("new_password") or ""
        confirm = request.form.get("confirm_password") or ""
        errors = []
        if not user.check_password(current):
            errors.append("Your current password is incorrect.")
        if len(new) < 8:
            errors.append("The new password must be at least 8 characters long.")
        if new != confirm:
            errors.append("New passwords do not match.")
        if errors:
            for error in errors:
                flash(error, "danger")
        else:
            user.set_password(new)
            db.session.commit()
            flash("Password updated successfully.", "success")
            return redirect(url_for(user.dashboard_endpoint))
    return render_template("auth/change_password.html")
