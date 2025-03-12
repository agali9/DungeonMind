"""Auth blueprint — register / login / logout.

Kept intentionally small: email + password, bcrypt, Flask-Login session cookies.
No email verification, no OAuth — those are scope-creep for a portfolio demo.
"""

from __future__ import annotations

from email_validator import EmailNotValidError, validate_email
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required, login_user, logout_user

from .extensions import db, limiter, login_manager
from .models import User

bp = Blueprint("auth", __name__, url_prefix="/auth")


@login_manager.user_loader
def _load_user(user_id: str) -> User | None:
    return db.session.get(User, int(user_id))


@bp.route("/register", methods=["GET", "POST"])
@limiter.limit("5/minute", methods=["POST"])
def register():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        display_name = (request.form.get("display_name") or "").strip()
        password = request.form.get("password") or ""

        try:
            validate_email(email, check_deliverability=False)
        except EmailNotValidError as e:
            flash(str(e), "error")
            return render_template("auth/register.html"), 400

        if len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
            return render_template("auth/register.html"), 400

        if not display_name or len(display_name) > 64:
            flash("Display name is required (1–64 characters).", "error")
            return render_template("auth/register.html"), 400

        if User.query.filter_by(email=email).first():
            flash("That email is already registered.", "error")
            return render_template("auth/register.html"), 400

        user = User(email=email, display_name=display_name)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        login_user(user)
        return redirect(url_for("game.index"))

    return render_template("auth/register.html")


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("5/minute", methods=["POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        user = User.query.filter_by(email=email).first()
        if user is None or not user.check_password(password):
            flash("Invalid email or password.", "error")
            return render_template("auth/login.html"), 401

        login_user(user, remember=True)
        return redirect(url_for("game.index"))

    return render_template("auth/login.html")

@bp.route("/logout", methods=["GET", "POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
