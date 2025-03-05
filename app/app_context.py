"""Holds a reference to the Flask app so background tasks can push app context.

The factory sets _APP when it creates the application. This is the standard
workaround for Flask-SocketIO background tasks that need db.session access.
"""

from __future__ import annotations

from flask import Flask

_APP: Flask | None = None


def register_app(app: Flask) -> None:
    global _APP
    _APP = app


def get_app() -> Flask:
    if _APP is None:
        raise RuntimeError("app context not registered; call register_app() in the factory")
    return _APP
