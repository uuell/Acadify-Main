"""
extensions.py - Flask Extensions
Initialize Flask extensions here to avoid circular imports.
Extensions are created here but initialized in app.py with init_app().
"""

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_bcrypt import Bcrypt

# Database ORM (Object-Relational Mapping)
# Allows us to work with database tables as Python objects
db = SQLAlchemy()

# Database Migration Tool
# Manages database schema changes (like version control for your database)
# Usage: flask db init, flask db migrate, flask db upgrade
migrate = Migrate()

# User Session Management
# Handles user login/logout, session persistence, and authentication
login_manager = LoginManager()

# Password Hashing
# Securely hash and verify passwords (never store plain text passwords!)
bcrypt = Bcrypt()