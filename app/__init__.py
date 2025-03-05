"""Flask application factory.

Keeping the factory small and explicit:
    1. Instantiate app + load config
    2. Initialize extensions
    3. Register blueprints
    4. Register socket handlers (by importing the module for its decorators)
    5. Register CLI commands
    6. Stash app in app_context for background tasks
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

import click
from flask import Flask, g, jsonify, request, send_from_directory
from flask_login import current_user
from flask_limiter.errors import RateLimitExceeded
from pythonjsonlogger import jsonlogger

from . import app_context
from .config import config as app_config
from .extensions import csrf, db, limiter, login_manager, migrate, socketio


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(app_config)
    # Flask expects these names:
    app.config["SECRET_KEY"] = app_config.SECRET_KEY
    app.config["SQLALCHEMY_DATABASE_URI"] = app_config.SQLALCHEMY_DATABASE_URI
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    _configure_logging()

    # Extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    socketio.init_app(
        app,
        cors_allowed_origins=app_config.SOCKETIO_CORS_ALLOWED_ORIGINS,
        async_mode=app_config.SOCKETIO_ASYNC_MODE,
    )

    # Blueprints
    from .auth import bp as auth_bp
    from .routes import bp as game_bp
    csrf.exempt(game_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(game_bp)

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def _react_spa_fallback(path: str):
        if path.startswith(("api/", "auth/", "socket.io/", "static/")) or path == "healthz":
            return jsonify({"error": "not found"}), 404
        react_dir = Path(app.static_folder) / "react"
        index_path = react_dir / "index.html"
        asset_path = react_dir / path if path else None
        if asset_path and asset_path.exists() and asset_path.is_file():
            return send_from_directory(react_dir, path)
        if index_path.exists():
            return send_from_directory(react_dir, "index.html")
        return jsonify({"error": "not found"}), 404

    @app.before_request
    def _protect_json_api():
        g.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.path.startswith("/api/"):
            if request.headers.get("X-Requested-With") != "Embervale":
                return jsonify({"error": "missing required header"}), 400
        return None

    @app.errorhandler(RateLimitExceeded)
    def _rate_limit_exceeded(_: RateLimitExceeded):
        if request.path.startswith("/api/"):
            return jsonify({"error": "rate limit exceeded"}), 429
        return "Too many requests", 429

    # Socket handlers register themselves on import
    from . import sockets  # noqa: F401

    # CLI
    _register_cli(app)

    # Create tables on first run in dev (sqlite default). For Postgres prod
    # use `flask db upgrade`.
    with app.app_context():
        db.create_all()
        from .seed import seed_database
        from .gemini_service import gemini_service
        seed_database()
        socketio.start_background_task(gemini_service.check_connectivity)

    app_context.register_app(app)
    return app


def _register_cli(app: Flask) -> None:
    @app.cli.command("seed")
    def seed_cmd():
        """Create or verify the demo campaign."""
        from .seed import seed_database
        camp = seed_database()
        click.echo(f"Campaign ready: '{camp.name}' (id={camp.id})")

    @app.cli.command("reset-db")
    @click.confirmation_option(prompt="Drop all tables and reseed?")
    def reset_db_cmd():
        """DANGER: drop everything and reseed."""
        db.drop_all()
        db.create_all()
        from .seed import seed_database
        seed_database()
        click.echo("Database reset and seeded.")

    @app.cli.command("metrics")
    def metrics_cmd():
        """Print observability metrics for the most recent turns."""
        from .cache import cache
        from .models import Turn
        click.echo(f"Cache: {cache.stats()}")
        turns = Turn.query.order_by(Turn.id.desc()).limit(20).all()
        if not turns:
            click.echo("No turns yet.")
            return
        avg = sum(t.latency_ms for t in turns) / len(turns)
        click.echo(f"Last {len(turns)} turns: avg {avg:.0f}ms")
        for t in turns[:10]:
            click.echo(f"  turn {t.index}: {t.latency_ms}ms  in={t.tokens_in} out={t.tokens_out}  cache={t.cache_hit}")

    @app.cli.command("seed-user")
    def seed_user_cmd():
        """Create demo@embervale.local / demo-pass if missing."""
        from .models import User

        email = "demo@embervale.local"
        existing = User.query.filter_by(email=email).first()
        if existing:
            click.echo("Seed user already exists.")
            return
        user = User(email=email, display_name="Demo Player")
        user.set_password("demo-pass")
        db.session.add(user)
        db.session.commit()
        click.echo("Created seed user demo@embervale.local / demo-pass")


class _RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = "-"
        record.user_id = "-"
        record.campaign_id = "-"
        try:
            record.request_id = getattr(g, "request_id", "-")
            if current_user.is_authenticated:
                record.user_id = current_user.id
            if request:
                record.campaign_id = request.view_args.get("campaign_id", "-") if request.view_args else "-"
        except Exception:  # noqa: BLE001
            pass
        return True


def _configure_logging() -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler()
    handler.addFilter(_RequestContextFilter())
    if app_config.FLASK_ENV == "development":
        fmt = "%(asctime)s %(levelname)s %(name)s req=%(request_id)s user=%(user_id)s camp=%(campaign_id)s: %(message)s"
        handler.setFormatter(logging.Formatter(fmt))
    else:
        formatter = jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s %(user_id)s %(campaign_id)s"
        )
        handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(logging.INFO)
