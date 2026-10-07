"""
app.py - Application Factory
Entry point for the Acadify Flask API.

Uses the Application Factory pattern for modularity,
testing, and environment-specific configuration.
"""

from flask import Flask, jsonify
from flask_cors import CORS

from config import config
from extensions import db, migrate, login_manager, bcrypt


def create_app(config_name='development'):
    """
    Create and configure the Flask application.

    Args:
        config_name (str):
            development, production, or testing

    Returns:
        Flask: Configured application instance.
    """

    app = Flask(__name__)

    # ---------------------------------------------------------
    # Configuration
    # ---------------------------------------------------------

    app.config.from_object(config[config_name])
    config[config_name].init_app(app)
    # ---------------------------------------------------------
    # CORS
    # ---------------------------------------------------------

    CORS(
        app,
        supports_credentials=True,
        origins=app.config['CORS_ORIGINS']
    )

    # ---------------------------------------------------------
    # Extensions
    # ---------------------------------------------------------

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    bcrypt.init_app(app)

    # ---------------------------------------------------------
    # Flask-Login
    # ---------------------------------------------------------

    @login_manager.user_loader
    def load_user(user_id):
        from models import User

        try:
            return db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None

    @login_manager.unauthorized_handler
    def unauthorized():
        return jsonify({
            'success': False,
            'message': 'Authentication required.'
        }), 401

    # ---------------------------------------------------------
    # Blueprints
    # ---------------------------------------------------------

    register_blueprints(app)

    # ---------------------------------------------------------
    # Error handlers
    # ---------------------------------------------------------

    register_error_handlers(app)

    # ---------------------------------------------------------
    # Load models for Flask-Migrate
    # ---------------------------------------------------------

    with app.app_context():
        import models  # noqa: F401

    return app


def register_blueprints(app):
    """
    Register application blueprints.
    """

    from blueprints.auth.routes import auth_bp
    from blueprints.student.routes import student_bp
    from blueprints.teacher.routes import teacher_bp
    from blueprints.ocr.routes import ocr_bp
    from blueprints.admin.routes import admin_bp

    app.register_blueprint(
        auth_bp,
        url_prefix='/auth'
    )

    app.register_blueprint(
        student_bp,
        url_prefix='/student'
    )

    app.register_blueprint(
        teacher_bp,
        url_prefix='/teacher'
    )

    app.register_blueprint(
        admin_bp,
        url_prefix='/admin'
    )

    app.register_blueprint(
        ocr_bp,
        url_prefix='/ocr'
    )

    # ---------------------------------------------------------
    # Public API health check
    # ---------------------------------------------------------

    @app.route('/api/health', methods=['GET'])
    def api_health():
        return jsonify({
            'success': True,
            'message': 'Acadify API is running'
        }), 200


def register_error_handlers(app):
    """
    Register global JSON API error handlers.
    """

    @app.errorhandler(400)
    def bad_request(error):
        return jsonify({
            'success': False,
            'message': 'Bad request.'
        }), 400

    @app.errorhandler(401)
    def unauthorized(error):
        return jsonify({
            'success': False,
            'message': 'Authentication required.'
        }), 401

    @app.errorhandler(403)
    def forbidden(error):
        return jsonify({
            'success': False,
            'message': 'Access denied.'
        }), 403

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({
            'success': False,
            'message': 'Resource not found.'
        }), 404

    @app.errorhandler(405)
    def method_not_allowed(error):
        return jsonify({
            'success': False,
            'message': 'Method not allowed.'
        }), 405

    @app.errorhandler(413)
    def request_entity_too_large(error):
        return jsonify({
            'success': False,
            'message': 'Uploaded file is too large. Maximum size is 16 MB.'
        }), 413

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()

        app.logger.exception(
            'Unhandled application error: %s',
            error
        )

        return jsonify({
            'success': False,
            'message': 'Internal server error.'
        }), 500


if __name__ == '__main__':
    app = create_app('development')

    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True
    )