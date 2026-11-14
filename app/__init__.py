import os
import secrets

from flask import Flask

from . import db, security


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)
    app.config.update(
        DATABASE=os.path.join(app.instance_path, "tracker.sqlite"),
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE") == "1",
        PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 7,
        MAX_CONTENT_LENGTH=12 * 1024 * 1024,
    )
    if config:
        app.config.update(config)

    app.teardown_appcontext(db.close_db)
    with app.app_context():
        db.init_db()

    if app.config.get("TESTING") and not app.config.get("CSRF_STRICT"):
        from .testing import CsrfClient
        app.test_client_class = CsrfClient

    app.before_request(security.check_csrf)
    app.after_request(security.add_headers)
    app.context_processor(lambda: {"csrf_token": security.csrf_token})

    from .account import bp as account_bp
    from .admin import bp as admin_bp
    from .goals import bp as goals_bp
    from .imports import bp as imports_bp
    from .notifications import bp as notifications_bp
    from .reports import bp as reports_bp
    from .routes import bp
    app.register_blueprint(account_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(imports_bp)
    app.register_blueprint(goals_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(bp)

    @app.errorhandler(404)
    def not_found(_):
        from flask import jsonify, render_template, request
        if request.path.startswith("/api/"):
            return jsonify(error="not found"), 404
        return render_template("notfound.html"), 404
    return app
