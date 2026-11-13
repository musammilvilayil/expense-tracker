import os
import secrets

from flask import Flask

from . import db


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)
    app.config.update(
        DATABASE=os.path.join(app.instance_path, "tracker.sqlite"),
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    )
    if config:
        app.config.update(config)

    app.teardown_appcontext(db.close_db)
    with app.app_context():
        db.init_db()

    from .routes import bp
    app.register_blueprint(bp)

    @app.errorhandler(404)
    def not_found(_):
        from flask import jsonify, render_template, request
        if request.path.startswith("/api/"):
            return jsonify(error="not found"), 404
        return render_template("notfound.html"), 404
    return app
