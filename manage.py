"""Command-line tasks.

  python manage.py make-admin <username>      give a user admin rights
  python manage.py remove-admin <username>    remove admin rights
  python manage.py send-reminders             email reminder digests (run daily)
  python manage.py list-users
"""
import argparse
import sys

from app import create_app
from app.db import get_db


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("make-admin", "remove-admin"):
        sub.add_parser(name).add_argument("username")
    sub.add_parser("send-reminders")
    sub.add_parser("list-users")
    args = ap.parse_args(argv)
    app = create_app()

    if args.cmd == "send-reminders":
        from app.notifications import send_all
        n = send_all(app)
        print(f"Sent {n} reminder email(s).")
        return 0

    with app.app_context():
        db = get_db()
        if args.cmd == "list-users":
            for r in db.execute("SELECT username, role, is_active, email FROM users ORDER BY id"):
                print(f"{r['username']:<24} {r['role']:<6} {'active' if r['is_active'] else 'disabled':<9} {r['email'] or ''}")
            return 0
        role = "admin" if args.cmd == "make-admin" else "user"
        cur = db.execute("UPDATE users SET role=? WHERE lower(username)=?", (role, args.username.lower()))
        db.commit()
        if not cur.rowcount:
            print(f"No such user: {args.username}", file=sys.stderr)
            return 1
        print(f"{args.username} is now {'an admin' if role == 'admin' else 'a regular user'}.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
