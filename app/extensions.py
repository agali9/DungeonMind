"""Singleton extension instances.

Importing this module must not touch the Flask app — the app factory wires
everything up explicitly. This keeps models, services, and routes free of
circular imports.
"""

from flask_login import LoginManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message_category = "warning"

csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")
socketio = SocketIO()
