"""Session based authentication, role guards, CSRF and safe defaults.

The project intentionally avoids external auth dependencies so it can run on
the lab machines without internet access. Passwords are hashed with Werkzeug
(PBKDF2/scrypt depending on version) and every state-changing request is
protected by a session-bound CSRF token.
"""
from __future__ import annotations

import hmac
import json
import secrets
import time
from collections import defaultdict, deque
from functools import wraps
from typing import Iterable

from flask import (
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    request,
    session,
    url_for,
)

from .extensions import db
from .models import User
from .utils import safe_next_url, utcnow

_FAILED_LOGINS: dict[str, deque] = defaultdict(lambda: deque(maxlen=10))
MAX_LOGIN_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 10 * 60


# ---------------------------------------------------------------------------
# current user / login helpers
# ---------------------------------------------------------------------------
def get_current_user() -> User | None:
    if "user_id" not in session:
        return None
    if getattr(g, "_current_user_loaded", False):
        return g.get("_current_user")
    user = db.session.get(User, session["user_id"])
    if user is None or not user.is_active:
        session.clear()
        user = None
    g._current_user = user
    g._current_user_loaded = True
    return user


def login_user(user: User) -> None:
    session.clear()
    session["user_id"] = user.id
    session["last_activity"] = time.time()
    session["_csrf_token"] = secrets.token_hex(32)
    session.permanent = True
    user.last_login_at = utcnow()
    db.session.commit()


def logout_user() -> None:
    session.clear()


def is_api_request() -> bool:
    return request.path.startswith("/api/")


def _unauthorized(message: str = "Please sign in to continue."):
    if is_api_request():
        return jsonify({"ok": False, "error": message}), 401
    flash(message, "warning")
    target = request.full_path if request.method == "GET" else request.path
    return redirect(url_for("auth.login", next=target))


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if get_current_user() is None:
            return _unauthorized()
        return view(*args, **kwargs)

    return wrapped


def role_required(*roles: Iterable[str]):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = get_current_user()
            if user is None:
                return _unauthorized()
            if user.role not in roles:
                if is_api_request():
                    return jsonify({"ok": False, "error": "Insufficient permissions"}), 403
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------
def csrf_token() -> str:
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_hex(32)
        session["_csrf_token"] = token
    return token


def _csrf_valid() -> bool:
    supplied = request.form.get("csrf_token") or request.headers.get("X-CSRFToken")
    expected = session.get("_csrf_token")
    return bool(supplied and expected and hmac.compare_digest(str(supplied), str(expected)))


# ---------------------------------------------------------------------------
# login throttling (per IP + username, in-memory)
# ---------------------------------------------------------------------------
def _throttle_key(identifier: str) -> str:
    return f"{request.remote_addr or 'unknown'}:{(identifier or '').lower()}"


def is_login_locked(identifier: str) -> bool:
    attempt = _FAILED_LOGINS.get(_throttle_key(identifier))
    if not attempt:
        return False
    cutoff = time.time() - LOGIN_WINDOW_SECONDS
    while attempt and attempt[0] < cutoff:
        attempt.popleft()
    return len(attempt) >= MAX_LOGIN_ATTEMPTS


def record_login_failure(identifier: str) -> None:
    _FAILED_LOGINS[_throttle_key(identifier)].append(time.time())


def clear_login_failures(identifier: str) -> None:
    _FAILED_LOGINS.pop(_throttle_key(identifier), None)


def remaining_login_attempts(identifier: str) -> int:
    attempt = _FAILED_LOGINS.get(_throttle_key(identifier), [])
    return max(0, MAX_LOGIN_ATTEMPTS - len(attempt))


# ---------------------------------------------------------------------------
# app wiring
# ---------------------------------------------------------------------------
def init_auth(app) -> None:
    timeout_seconds = app.config["PERMANENT_SESSION_LIFETIME"].total_seconds()

    @app.before_request
    def _session_and_csrf_guard():
        # 1. inactivity auto-logout -----------------------------------------
        if "user_id" in session:
            last_activity = session.get("last_activity")
            now = time.time()
            if last_activity and now - float(last_activity) > timeout_seconds:
                session.clear()
                if is_api_request():
                    return jsonify({"ok": False, "error": "Session expired. Please sign in again."}), 401
                flash("Your session expired due to inactivity. Please sign in again.", "warning")
                return redirect(url_for("auth.login", next=request.path))
            session["last_activity"] = now
            session.permanent = True

        # 2. CSRF for every state-changing call ----------------------------
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and app.config.get(
            "CSRF_ENABLED", True
        ):
            if not _csrf_valid():
                if is_api_request():
                    return (
                        jsonify({"ok": False, "error": "Invalid or expired security token. Refresh the page."}),
                        400,
                    )
                flash("Your security token expired. Please try again.", "danger")
                return redirect(request.referrer or url_for("main.index"))

        # 3. load the user once per request --------------------------------
        get_current_user()
        return None

    @app.context_processor
    def _inject_globals():
        from .services.cart import cart_count  # local import avoids a cycle

        user = get_current_user()
        unread = 0
        if user is not None:
            unread = user.unread_notifications
        return {
            "current_user": user,
            "app_name": app.config.get("APP_NAME", "MOON Light"),
            "csrf_token": csrf_token,
            "unread_notifications": unread,
            "cart_count": cart_count() if (user and user.is_customer) else 0,
            "session_timeout_minutes": int(timeout_seconds // 60),
            "is_authenticated": user is not None,
        }

    @app.after_request
    def _security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(self), camera=(), microphone=()"
        )
        return response
