import os

from app import create_app
from extensions import db, bcrypt
from models import User


app = create_app()

with app.app_context():
    email = os.environ.get("DEV_ADMIN_EMAIL", "admin@acadify.test")
    password = os.environ.get("DEV_ADMIN_PASSWORD")

    if not password:
        raise ValueError(
            "DEV_ADMIN_PASSWORD environment variable must be set."
        )

    admin = User(
        email=email,
        password=bcrypt.generate_password_hash(password).decode("utf-8"),
        role="admin",
    )

    db.session.add(admin)
    db.session.commit()

    print("Admin created:", admin.id, admin.email)