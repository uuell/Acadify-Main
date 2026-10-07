"""
config.py - Configuration Classes
Manages development, production, and testing environments.
"""

import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Store protected uploads outside /static
    UPLOAD_FOLDER = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'uploads'
    )

    MAX_CONTENT_LENGTH = 16 * 1024 * 1024

    ALLOWED_EXTENSIONS = {
        'png', 'jpg', 'jpeg',
        'gif', 'pdf',
        'csv', 'xlsx', 'xls'
    }

    # ---------------------------------------------------------
    # Sessions
    # ---------------------------------------------------------

    PERMANENT_SESSION_LIFETIME = timedelta(days=7)

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = False

    # ---------------------------------------------------------
    # CORS
    # ---------------------------------------------------------

    CORS_ORIGINS = []

    # ---------------------------------------------------------
    # Pagination
    # ---------------------------------------------------------

    ITEMS_PER_PAGE = 50
    STUDENTS_PER_PAGE = 50
    CLASSES_PER_PAGE = 20

    # ---------------------------------------------------------
    # Academic period
    # ---------------------------------------------------------

    @staticmethod
    def _auto_calculate_school_year():
        from datetime import datetime

        now = datetime.now()
        year = now.year
        month = now.month

        if month >= 8:
            return f"{year}-{year + 1}"

        return f"{year - 1}-{year}"

    @staticmethod
    def _auto_calculate_semester():
        from datetime import datetime

        month = datetime.now().month

        if 8 <= month <= 12:
            return "1st Semester"

        if 1 <= month <= 5:
            return "2nd Semester"

        return "Summer"

    @staticmethod
    def get_current_school_year():
        try:
            from models import SystemSettings

            db_value = SystemSettings.get_setting(
                'current_school_year'
            )

            if db_value:
                return db_value

        except Exception:
            pass

        return Config._auto_calculate_school_year()

    @staticmethod
    def get_current_semester():
        try:
            from models import SystemSettings

            db_value = SystemSettings.get_setting(
                'current_semester'
            )

            if db_value:
                return db_value

        except Exception:
            pass

        return Config._auto_calculate_semester()

    # ---------------------------------------------------------
    # Grade settings
    # ---------------------------------------------------------

    PASSING_GRADE = 3.0
    FAILED_GRADE = 5.0
    INCOMPLETE_GRADE = 'INC'
    DROPPED_GRADE = 'DRP'

    DEFAULT_GRADE_CONVERSION = {
        "97-100": 1.0,
        "94-96": 1.25,
        "91-93": 1.5,
        "88-90": 1.75,
        "85-87": 2.0,
        "82-84": 2.25,
        "79-81": 2.5,
        "76-78": 2.75,
        "75": 3.0,
        "65-74": 4.0,
        "0-64": 5.0
    }

    # ---------------------------------------------------------
    # CSV imports
    # ---------------------------------------------------------

    CSV_ALLOWED_EXTENSIONS = {
        'csv',
        'xlsx',
        'xls'
    }

    CSV_MAX_ROWS = 10000

    # ---------------------------------------------------------
    # Email
    # ---------------------------------------------------------

    MAIL_SERVER = os.environ.get(
        'MAIL_SERVER',
        'smtp.gmail.com'
    )

    MAIL_PORT = int(
        os.environ.get(
            'MAIL_PORT',
            587
        )
    )

    MAIL_USE_TLS = (
        os.environ.get(
            'MAIL_USE_TLS',
            'true'
        ).lower()
        in ['true', 'on', '1']
    )

    MAIL_USERNAME = os.environ.get(
        'MAIL_USERNAME'
    )

    MAIL_PASSWORD = os.environ.get(
        'MAIL_PASSWORD'
    )

    MAIL_DEFAULT_SENDER = os.environ.get(
        'MAIL_DEFAULT_SENDER',
        'noreply@acadify.edu'
    )

    @classmethod
    def init_app(cls, app):
        pass


class DevelopmentConfig(Config):
    DEBUG = True
    TESTING = False

    SECRET_KEY = os.environ.get(
        'SECRET_KEY',
        'acadify-development-secret-key'
    )

    SQLALCHEMY_DATABASE_URI = (
        os.environ.get('DEV_DATABASE_URL')
        or 'sqlite:///' + os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'acadify_dev.db'
        )
    )

    SQLALCHEMY_ECHO = True

    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'

    CORS_ORIGINS = [
        'http://localhost:5173',
        'http://127.0.0.1:5173'
    ]


class ProductionConfig(Config):
    DEBUG = False
    TESTING = False

    @staticmethod
    def _get_database_url():
        url = os.environ.get('DATABASE_URL')

        if not url:
            return None

        if url.startswith('postgres://'):
            url = url.replace(
                'postgres://',
                'postgresql://',
                1
            )

        return url

    SQLALCHEMY_DATABASE_URI = (
        _get_database_url.__func__()
    )

    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'None'

    CORS_ORIGINS = [
        origin.strip()
        for origin in os.environ.get(
            'CORS_ORIGINS',
            ''
        ).split(',')
        if origin.strip()
    ]

    SQLALCHEMY_POOL_SIZE = 10
    SQLALCHEMY_POOL_RECYCLE = 3600
    SQLALCHEMY_POOL_PRE_PING = True
    SQLALCHEMY_ECHO = False

    @classmethod
    def init_app(cls, app):
        Config.init_app(app)

        if not os.environ.get('SECRET_KEY'):
            raise ValueError(
                'SECRET_KEY environment variable '
                'must be set in production!'
            )

        if not os.environ.get('DATABASE_URL'):
            raise ValueError(
                'DATABASE_URL environment variable '
                'must be set in production!'
            )

        if not cls.CORS_ORIGINS:
            raise ValueError(
                'CORS_ORIGINS environment variable '
                'must be set in production!'
            )


class TestingConfig(Config):
    DEBUG = False
    TESTING = True

    SECRET_KEY = 'testing-secret-key'

    SQLALCHEMY_DATABASE_URI = (
        'sqlite:///:memory:'
    )

    WTF_CSRF_ENABLED = False
    BCRYPT_LOG_ROUNDS = 4
    SQLALCHEMY_ECHO = False

    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'

    CORS_ORIGINS = [
        'http://localhost:5173'
    ]


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}