"""
blueprints/auth/routes.py - Authentication Blueprint
Handles user login, logout, and password management.
"""

from flask import Blueprint, request, jsonify
from flask_login import login_user, logout_user, current_user
from extensions import bcrypt
from models import User, Student

# Create blueprint
auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/student-login', methods=['POST'])
def student_login():
    """
    Authenticate a student using their student number and password.

    Expected JSON:
    {
        "student_number": "2024-00001",
        "password": "student123"
    }

    Success response:
    {
        "success": true,
        "message": "Login successful.",
        "user": {
            "id": 3,
            "role": "student",
            "student_number": "2024-00001",
            "first_name": "Juan",
            "last_name": "Dela Cruz"
        }
    }
    """

    # If already authenticated, return the current session user
    if current_user.is_authenticated:
        return jsonify({
            "success": True,
            "message": "User is already logged in.",
            "user": {
                "id": current_user.id,
                "role": current_user.role
            }
        }), 200

    # Read JSON request
    data = request.get_json(silent=True) or {}

    student_number = data.get("student_number", "").strip()
    password = data.get("password", "")

    # Validate input 
    if not student_number or not password:
        return jsonify({
            "success": False,
            "message": "Student ID and password are required"
        }), 400

    # Find student
    student = Student.query.filter_by(
        student_number=student_number
    ).first()

    if student is None:
        return jsonify({
            "success": False,
            "message": "Invalid student number or password." 
        }), 401

    # Check associated user account
    user = student.user
    if user.role != "student":
        return jsonify({
            "success": False,
            "message": "This login is for students only"
        }), 403

    #verify password
    if not bcrypt.check_password_hash(user.password, password):
        return jsonify({
            "success": False,
            "message": "Invalid student number or password."
        }), 401

    # Login user with flask-login
    login_user(user, remember=True)

    # return user data
    return jsonify({
        "success": True,
        "message": f'Welcome back, {student.first_name}!',
        "user": {
            "id": user.id,
            'role': user.role,
            'student_number': student.student_number,
            'first_name': student.first_name,
            'last_name': student.last_name
        }
    }), 200
    


@auth_bp.route('/teacher-login', methods=['POST'])
@auth_bp.route('/admin-login', methods=['POST'])
def teacher_admin_login():

    if current_user.is_authenticated:
        return jsonify({
            'success': True,
            'message': 'User is already logged in.',
            'user': {
                'id': current_user.id,
                'role': current_user.role,
                'email': current_user.email
            }
        }), 200

    data = request.get_json(silent=True) or {}

    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    if not email or not password:
        return jsonify({
            'success': False,
            'message': 'Email and password are required.'
        }), 400

    user = User.query.filter_by(email=email).first()

    if user is None:
        return jsonify({
            'success': False,
            'message': 'Invalid email or password.'
        }), 401

    # Determine which login endpoint was used
    requested_path = request.path

    if requested_path.endswith('/teacher-login') and user.role != 'teacher':
        return jsonify({
            'success': False,
            'message': 'This login is for teachers only.'
        }), 403

    if requested_path.endswith('/admin-login') and user.role != 'admin':
        return jsonify({
            'success': False,
            'message': 'This login is for administrators only.'
        }), 403

    if not bcrypt.check_password_hash(user.password, password):
        return jsonify({
            'success': False,
            'message': 'Invalid email or password.'
        }), 401

    login_user(user, remember=True)

    user_data = {
        'id': user.id,
        'role': user.role,
        'email': user.email
    }

    if user.role == 'teacher':
        teacher = user.teacher_profile

        if teacher:
            user_data.update({
                'employee_number': teacher.employee_number,
                'first_name': teacher.first_name,
                'last_name': teacher.last_name,
                'department': teacher.department,
                'specialization': teacher.specialization
            })

        message = (
            f'Welcome back, '
            f'{teacher.first_name if teacher else "Teacher"}!'
        )

    else:
        message = 'Welcome back, Admin!'

    return jsonify({
        'success': True,
        'message': message,
        'user': user_data
    }), 200

@auth_bp.route('/logout', methods=['POST'])
def logout():

    if not current_user.is_authenticated:
        return jsonify({
            'success': False,
            'message': 'Authentication required.'
        }), 401

    logout_user()

    return jsonify({
        'success': True,
        'message': 'You have been logged out successfully.'
    }), 200


@auth_bp.route('/forgot-password', methods=['POST'])
def forgot_password():
    """
    Request a password reset.

    Password reset functionality has not been implemented yet.

    Expected JSON:
    {
        "email": "student@acadify.edu"
    }
    """

    data = request.get_json(silent=True) or {}

    email = data.get('email', '').strip().lower()

    if not email:
        return jsonify({
            'success': False,
            'message': 'Email is required.'
        }), 400

    return jsonify({
        'success': False,
        'message': (
            'Password reset functionality is not available yet. '
            'Please contact your administrator.'
        )
    }), 501

@auth_bp.route('/me', methods=['GET'])
def get_current_user():
    """
    Return information about the currently authenticated user.

    This endpoint is useful when React loads the application and needs
    to determine whether a Flask-Login session already exists.

    Logged in:
    {
        "success": true,
        "authenticated": true,
        "user": {...}
    }

    Not logged in:
    {
        "success": true,
        "authenticated": false,
        "user": null
    }
    """

    if not current_user.is_authenticated:
        return jsonify({
            'success': True,
            'authenticated': False,
            'user': None
        }), 200

    user = current_user

    user_data = {
        'id': user.id,
        'role': user.role,
        'email': user.email
    }

    # Student information
    if user.role == 'student':
        student = user.student_profile

        if student:
            user_data.update({
                'student_number': student.student_number,
                'first_name': student.first_name,
                'last_name': student.last_name,
                'department': student.department,
                'program': student.program,
                'year_level': student.year_level,
                'section': student.section
            })

    # Teacher information
    elif user.role == 'teacher':
        teacher = user.teacher_profile

        if teacher:
            user_data.update({
                'employee_number': teacher.employee_number,
                'first_name': teacher.first_name,
                'last_name': teacher.last_name,
                'department': teacher.department,
                'specialization': teacher.specialization
            })

    return jsonify({
        'success': True,
        'authenticated': True,
        'user': user_data
    }), 200