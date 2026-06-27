from __future__ import annotations

import os

from flask import Flask

from .routes import bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv(
        "FLASK_SECRET_KEY",
        "troque-esta-chave-em-producao",
    )
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.register_blueprint(bp)
    return app
