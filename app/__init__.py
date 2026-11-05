"""Application factory for the Food Delivery Optimization System."""
from __future__ import annotations

import logging
import os

import click
from flask import Flask, jsonify, render_template, request, url_for
from werkzeug.exceptions import HTTPException

from config import Config
from .auth import init_auth
from .extensions import db
from .utils import format_datetime, format_money, format_time, time_ago, utcnow


def create_app(config_object=None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object or Config)
    app.config.setdefault("APP_NAME", "MOON Light")
    os.makedirs(app.instance_path, exist_ok=True)

    if app.config.get("DATABASE_PATH"):
        database_path = os.path.abspath(app.config["DATABASE_PATH"])
        os.makedirs(os.path.dirname(database_path), exist_ok=True)

    db.init_app(app)
    init_auth(app)

    # ------------------------------------------------------------- filters
    app.jinja_env.filters["money"] = format_money
    app.jinja_env.filters["dt"] = format_datetime
    app.jinja_env.filters["time"] = format_time
    app.jinja_env.filters["ago"] = time_ago
    app.jinja_env.globals["now"] = utcnow

    def page_url(page: int) -> str:
        args = request.args.to_dict(flat=True)
        args["page"] = page
        return url_for(request.endpoint, **args)

    app.jinja_env.globals["page_url"] = page_url

    # ----------------------------------------------------------- blueprints
    from .blueprints.auth import bp as auth_bp
    from .blueprints.main import bp as main_bp
    from .blueprints.customer import bp as customer_bp
    from .blueprints.delivery import bp as delivery_bp
    from .blueprints.admin import bp as admin_bp
    from .blueprints.api import bp as api_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(customer_bp, url_prefix="/customer")
    app.register_blueprint(delivery_bp, url_prefix="/delivery")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(api_bp, url_prefix="/api")

    # -------------------------------------------------------- error pages
    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": error.description}), error.code
        titles = {
            400: "Bad request",
            401: "Sign in required",
            403: "Access denied",
            404: "Page not found",
            405: "Method not allowed",
            413: "File too large",
            500: "Something went wrong",
        }
        return (
            render_template(
                "errors/error.html",
                code=error.code,
                title=titles.get(error.code, error.name),
                message=error.description,
            ),
            error.code,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(error):  # pragma: no cover - safety net
        app.logger.exception("Unhandled error: %s", error)
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "Unexpected server error"}), 500
        return (
            render_template(
                "errors/error.html",
                code=500,
                title="Something went wrong",
                message="The request could not be completed. Please try again.",
            ),
            500,
        )

    # ------------------------------------------------------------- startup
    app.logger.setLevel(logging.INFO)

    with app.app_context():
        if app.config.get("AUTO_CREATE_DB", True):
            db.create_all()
            from .services.settings import ensure_defaults

            ensure_defaults()

    # ----------------------------------------------------------- CLI tools
    @app.cli.command("init-db")
    def init_db_command():
        """Create all tables and default settings."""
        db.create_all()
        from .services.settings import ensure_defaults

        ensure_defaults()
        click.echo("Database initialised.")

    @app.cli.command("seed-demo")
    @click.option("--with-orders", is_flag=True, help="Also create sample orders for analytics.")
    def seed_demo_command(with_orders):
        """Insert demo accounts, restaurants and menu items."""
        from .seed import seed_demo

        result = seed_demo(with_orders=with_orders)
        click.echo(result)

    @app.cli.command("create-admin")
    @click.option("--name", prompt=True)
    @click.option("--username", prompt=True)
    @click.option("--email", prompt=True)
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def create_admin_command(name, username, email, password):
        """Create an administrator account."""
        from .models import ROLE_ADMIN, User

        if User.query.filter((User.username == username) | (User.email == email)).first():
            click.echo("A user with that username or email already exists.")
            return
        user = User(name=name, username=username, email=email, role=ROLE_ADMIN)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Admin '{username}' created.")

    return app
