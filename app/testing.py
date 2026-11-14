"""Test client that automatically supplies the CSRF token."""
from flask.testing import FlaskClient


class CsrfClient(FlaskClient):
    def open(self, *args, **kwargs):
        if kwargs.get("method", "GET").upper() not in ("GET", "HEAD", "OPTIONS") and not kwargs.pop("no_csrf", False):
            with self.session_transaction() as s:
                token = s.setdefault("csrf", "test-csrf-token")
            headers = dict(kwargs.get("headers") or {})
            headers.setdefault("X-CSRF-Token", token)
            kwargs["headers"] = headers
        kwargs.pop("no_csrf", None)
        return super().open(*args, **kwargs)
