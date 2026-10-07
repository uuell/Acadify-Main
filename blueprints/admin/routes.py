"""
blueprints/admin/routes.py - Admin Blueprint
Backend routes for your gold-themed admin dashboard
"""

from flask import Blueprint, jsonify, request, Response
from flask_login import current_user
from models import User, Student, Teacher
from extensions import db, bcrypt
from config import Config
from sqlalchemy import func
from datetime import datetime
from functools import wraps
import csv
import io

admin_bp = Blueprint('admin', __name__)


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):

        if not current_user.is_authenticated:
            return jsonify({
                'success': False,
                'message': 'Authentication required.'
            }), 401

        if current_user.role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Access denied. Admins only.'
            }), 403

        return f(*args, **kwargs)

    return decorated_function


@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    """Admin Dashboard - Main page"""
    total_students = Student.query.count()
    total_teachers = Teacher.query.count()
    
    # New users today
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    new_today = User.query.filter(User.created_at >= today_start).count()
    
    # Department stats
    students_by_dept = db.session.query(
        Student.department, func.count(Student.id)
    ).group_by(Student.department).all()
    
    departments = []
    for dept_name, student_count in students_by_dept:
        teacher_count = Teacher.query.filter_by(department=dept_name).count()
        departments.append({
            'name': dept_name,
            'student_count': student_count,
            'teacher_count': teacher_count
        })
    
    # Recent users
    recent_users = []
    for student in Student.query.order_by(Student.created_at.desc()).limit(5).all():
        initials = f"{student.first_name[0]}{student.last_name[0]}" if student.last_name else student.first_name[0]
        recent_users.append({
            'name': student.get_full_name(),
            'email': student.user.email,
            'id_number': student.student_number,
            'role': 'Student',
            'initials': initials,
            'date_added': (
                student.created_at.isoformat()
                if student.created_at
                else None
            ),
            'status': 'Active'
        })
    
    for teacher in Teacher.query.order_by(Teacher.created_at.desc()).limit(5).all():
        initials = f"{teacher.first_name[0]}{teacher.last_name[0]}" if teacher.last_name else teacher.first_name[0]
        recent_users.append({
        'name': teacher.get_full_name(),
        'email': teacher.user.email,
        'id_number': teacher.employee_number,
        'role': 'Teacher',
        'initials': initials,
        'date_added': (
            teacher.created_at.isoformat()
            if teacher.created_at
            else None
        ),
        'status': 'Active'
    })
    
    recent_users.sort(key=lambda x: x['date_added'], reverse=True)
    
    
    return jsonify({
        'success': True,

        'statistics': {
            'total_students': total_students,
            'total_teachers': total_teachers,
            'new_users_today': new_today
        },

        'departments': departments,

        'recent_users': recent_users[:10]
    }), 200

@admin_bp.route('/register-student', methods=['POST'])
@admin_required
def register_student():
    """
    Register a single student.
    Expects JSON data.
    """
    try:
        data = request.get_json(silent=True)

        if not data:
            return jsonify({
                'success': False,
                'message': 'Request body must contain JSON data.'
            }), 400

        full_name = data.get('full_name', '').strip()
        student_number = data.get('student_number', '').strip()
        email = data.get('email', '').strip().lower()
        department = data.get('department', '').strip()
        program = data.get('program', '').strip()
        year_level = data.get('year_level', '').strip()
        section = data.get('section', '').strip()

        # Required fields
        if not all([
            full_name,
            student_number,
            email,
            department,
            program
        ]):
            return jsonify({
                'success': False,
                'message': 'Please fill in all required fields.'
            }), 400

        # Parse name
        name_parts = full_name.split()

        first_name = name_parts[0]
        last_name = (
            ' '.join(name_parts[1:])
            if len(name_parts) > 1
            else ''
        )

        # Duplicate email
        if User.query.filter_by(email=email).first():
            return jsonify({
                'success': False,
                'message': 'Email already exists.'
            }), 409

        # Duplicate student number
        if Student.query.filter_by(
            student_number=student_number
        ).first():
            return jsonify({
                'success': False,
                'message': 'Student number already exists.'
            }), 409

        # Default password = student number
        password = student_number

        user = User(
            email=email,
            password=bcrypt.generate_password_hash(
                password
            ).decode('utf-8'),
            role='student'
        )

        db.session.add(user)
        db.session.flush()

        student = Student(
            user_id=user.id,
            student_number=student_number,
            first_name=first_name,
            last_name=last_name,
            department=department,
            program=program,
            year_level=year_level,
            section=section if section else None
        )

        db.session.add(student)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Student registered successfully.',
            'student': {
                'id': student.id,
                'user_id': user.id,
                'student_number': student.student_number,
                'first_name': student.first_name,
                'last_name': student.last_name,
                'email': user.email,
                'department': student.department,
                'program': student.program,
                'year_level': student.year_level,
                'section': student.section
            },
            'default_password': 'Student number'
        }), 201

    except Exception as e:
        db.session.rollback()

        return jsonify({
            'success': False,
            'message': 'An error occurred while registering the student.',
            'error': str(e)
        }), 500

@admin_bp.route('/register-teacher', methods=['POST'])
@admin_required
def register_teacher():
    """
    Register a single teacher.
    Expects JSON data.
    """
    try:
        data = request.get_json(silent=True)

        if not data:
            return jsonify({
                'success': False,
                'message': 'Request body must contain JSON data.'
            }), 400

        full_name = data.get('full_name', '').strip()
        employee_number = data.get('employee_number', '').strip()
        email = data.get('email', '').strip().lower()
        password = data.get('password', '').strip()
        confirm_password = data.get('confirm_password', '').strip()
        department = data.get('department', '').strip()
        specialization = data.get('specialization', '').strip()

        if not all([
            full_name,
            employee_number,
            email,
            department
        ]):
            return jsonify({
                'success': False,
                'message': 'Please fill in all required fields.'
            }), 400

        name_parts = full_name.split()

        first_name = name_parts[0]
        last_name = (
            ' '.join(name_parts[1:])
            if len(name_parts) > 1
            else ''
        )

        if password:
            if password != confirm_password:
                return jsonify({
                    'success': False,
                    'message': 'Passwords do not match.'
                }), 400

            if len(password) < 6:
                return jsonify({
                    'success': False,
                    'message': 'Password must be at least 6 characters.'
                }), 400
        else:
            password = employee_number

        if User.query.filter_by(email=email).first():
            return jsonify({
                'success': False,
                'message': 'Email already exists.'
            }), 409

        if Teacher.query.filter_by(
            employee_number=employee_number
        ).first():
            return jsonify({
                'success': False,
                'message': 'Employee number already exists.'
            }), 409

        user = User(
            email=email,
            password=bcrypt.generate_password_hash(
                password
            ).decode('utf-8'),
            role='teacher'
        )

        db.session.add(user)
        db.session.flush()

        teacher = Teacher(
            user_id=user.id,
            employee_number=employee_number,
            first_name=first_name,
            last_name=last_name,
            department=department,
            specialization=(
                specialization if specialization else None
            )
        )

        db.session.add(teacher)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Teacher registered successfully.',
            'teacher': {
                'id': teacher.id,
                'user_id': user.id,
                'employee_number': teacher.employee_number,
                'first_name': teacher.first_name,
                'last_name': teacher.last_name,
                'email': user.email,
                'department': teacher.department,
                'specialization': teacher.specialization
            },
            'default_password': (
                'Employee number'
                if not data.get('password')
                else None
            )
        }), 201

    except Exception as e:
        db.session.rollback()

        return jsonify({
            'success': False,
            'message': 'An error occurred while registering the teacher.',
            'error': str(e)
        }), 500

@admin_bp.route('/bulk-import-students', methods=['POST'])
@admin_required
def bulk_import_students():
    try:
        if 'csv_file' not in request.files:
            return jsonify({
                'success': False,
                'message': 'No file uploaded.'
            }), 400

        file = request.files['csv_file']

        if not file or file.filename == '':
            return jsonify({
                'success': False,
                'message': 'No file selected.'
            }), 400

        if not file.filename.lower().endswith('.csv'):
            return jsonify({
                'success': False,
                'message': 'Please upload a CSV file.'
            }), 400

        stream = io.StringIO(
            file.stream.read().decode('utf-8-sig'),
            newline=None
        )

        csv_reader = csv.DictReader(stream)

        success_count = 0
        error_count = 0
        error_details = []

        for row_num, row in enumerate(csv_reader, start=2):
            try:
                with db.session.begin_nested():

                    full_name = row.get(
                        'Full Name',
                        ''
                    ).strip()

                    student_number = row.get(
                        'Student Number',
                        ''
                    ).strip()

                    email = row.get(
                        'Email',
                        ''
                    ).strip().lower()

                    department = row.get(
                        'Department',
                        ''
                    ).strip()

                    program = row.get(
                        'Program',
                        ''
                    ).strip()

                    year_level = row.get(
                        'Year Level',
                        '1st Year'
                    ).strip()

                    section = row.get(
                        'Section',
                        ''
                    ).strip()

                    if not all([
                        full_name,
                        student_number,
                        email,
                        department,
                        program
                    ]):
                        error_count += 1

                        error_details.append({
                            'row': row_num,
                            'message': 'Missing required fields.'
                        })

                        continue

                    if User.query.filter_by(
                        email=email
                    ).first():
                        error_count += 1

                        error_details.append({
                            'row': row_num,
                            'message': (
                                f'Email {email} already exists.'
                            )
                        })

                        continue

                    if Student.query.filter_by(
                        student_number=student_number
                    ).first():
                        error_count += 1

                        error_details.append({
                            'row': row_num,
                            'message': (
                                f'Student number '
                                f'{student_number} already exists.'
                            )
                        })

                        continue

                    name_parts = full_name.split()

                    first_name = name_parts[0]

                    last_name = (
                        ' '.join(name_parts[1:])
                        if len(name_parts) > 1
                        else ''
                    )

                    user = User(
                        email=email,
                        password=bcrypt.generate_password_hash(
                            student_number
                        ).decode('utf-8'),
                        role='student'
                    )

                    db.session.add(user)
                    db.session.flush()

                    student = Student(
                        user_id=user.id,
                        student_number=student_number,
                        first_name=first_name,
                        last_name=last_name,
                        department=department,
                        program=program,
                        year_level=year_level,
                        section=(
                            section
                            if section
                            else None
                        )
                    )

                    db.session.add(student)

                success_count += 1

            except Exception as e:
                error_count += 1

                error_details.append({
                    'row': row_num,
                    'message': str(e)
                })

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Student import completed.',
            'summary': {
                'imported': success_count,
                'errors': error_count
            },
            'errors': error_details
        }), 200

    except UnicodeDecodeError:
        db.session.rollback()

        return jsonify({
            'success': False,
            'message': 'CSV file must use UTF-8 encoding.'
        }), 400

    except Exception as e:
        db.session.rollback()

        return jsonify({
            'success': False,
            'message': 'Student import failed.',
            'error': str(e)
        }), 500

@admin_bp.route('/bulk-import-teachers', methods=['POST'])
@admin_required
def bulk_import_teachers():
    try:
        if 'csv_file' not in request.files:
            return jsonify({
                'success': False,
                'message': 'No file uploaded.'
            }), 400

        file = request.files['csv_file']

        if not file or file.filename == '':
            return jsonify({
                'success': False,
                'message': 'No file selected.'
            }), 400

        if not file.filename.lower().endswith('.csv'):
            return jsonify({
                'success': False,
                'message': 'Please upload a CSV file.'
            }), 400

        stream = io.StringIO(
            file.stream.read().decode('utf-8-sig'),
            newline=None
        )

        csv_reader = csv.DictReader(stream)

        success_count = 0
        error_count = 0
        error_details = []

        for row_num, row in enumerate(csv_reader, start=2):
            try:
                with db.session.begin_nested():

                    full_name = row.get(
                        'Full Name',
                        ''
                    ).strip()

                    employee_number = row.get(
                        'Employee Number',
                        ''
                    ).strip()

                    email = row.get(
                        'Email',
                        ''
                    ).strip().lower()

                    department = row.get(
                        'Department',
                        ''
                    ).strip()

                    specialization = row.get(
                        'Specialization',
                        ''
                    ).strip()

                    if not all([
                        full_name,
                        employee_number,
                        email,
                        department
                    ]):
                        error_count += 1

                        error_details.append({
                            'row': row_num,
                            'message': 'Missing required fields.'
                        })

                        continue

                    if User.query.filter_by(
                        email=email
                    ).first():
                        error_count += 1

                        error_details.append({
                            'row': row_num,
                            'message': (
                                f'Email {email} already exists.'
                            )
                        })

                        continue

                    if Teacher.query.filter_by(
                        employee_number=employee_number
                    ).first():
                        error_count += 1

                        error_details.append({
                            'row': row_num,
                            'message': (
                                f'Employee number '
                                f'{employee_number} already exists.'
                            )
                        })

                        continue

                    name_parts = full_name.split()

                    first_name = name_parts[0]

                    last_name = (
                        ' '.join(name_parts[1:])
                        if len(name_parts) > 1
                        else ''
                    )

                    user = User(
                        email=email,
                        password=bcrypt.generate_password_hash(
                            employee_number
                        ).decode('utf-8'),
                        role='teacher'
                    )

                    db.session.add(user)
                    db.session.flush()

                    teacher = Teacher(
                        user_id=user.id,
                        employee_number=employee_number,
                        first_name=first_name,
                        last_name=last_name,
                        department=department,
                        specialization=(
                            specialization
                            if specialization
                            else None
                        )
                    )

                    db.session.add(teacher)

                success_count += 1

            except Exception as e:
                error_count += 1

                error_details.append({
                    'row': row_num,
                    'message': str(e)
                })

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Teacher import completed.',
            'summary': {
                'imported': success_count,
                'errors': error_count
            },
            'errors': error_details
        }), 200

    except UnicodeDecodeError:
        db.session.rollback()

        return jsonify({
            'success': False,
            'message': 'CSV file must use UTF-8 encoding.'
        }), 400

    except Exception as e:
        db.session.rollback()

        return jsonify({
            'success': False,
            'message': 'Teacher import failed.',
            'error': str(e)
        }), 500

@admin_bp.route('/download/student-template')
@admin_required
def download_student_template():
    csv_content = (
        "Full Name,Student Number,Email,Department,"
        "Program,Year Level,Section\n"
    )

    csv_content += (
        "Juan Dela Cruz,20260001,"
        "juan@student.acadify.edu,"
        "College of Engineering,"
        "BS Computer Engineering,"
        "4th Year,A\n"
    )

    response = Response(csv_content)

    response.headers["Content-Disposition"] = (
        "attachment; filename=student_template.csv"
    )

    response.headers["Content-Type"] = "text/csv"

    return response


@admin_bp.route('/download/teacher-template')
@admin_required
def download_teacher_template():
    csv_content = (
        "Full Name,Employee Number,Email,"
        "Department,Specialization\n"
    )

    csv_content += (
        "Pedro Reyes,T2026001,"
        "pedro@faculty.acadify.edu,"
        "College of Engineering,"
        "Computer Engineering\n"
    )

    response = Response(csv_content)

    response.headers["Content-Disposition"] = (
        "attachment; filename=teacher_template.csv"
    )

    response.headers["Content-Type"] = "text/csv"

    return response


@admin_bp.route('/user-management')
@admin_required
def user_management():
    """
    Return students and teachers with filtering and pagination.
    """

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    if page < 1:
        page = 1

    if per_page < 1:
        per_page = 20

    if per_page > 100:
        per_page = 100

    role_filter = request.args.get('role', '').strip()
    dept_filter = request.args.get('department', '').strip()
    search_query = request.args.get('search', '').strip()

    students = Student.query.order_by(
        Student.last_name,
        Student.first_name
    ).all()

    teachers = Teacher.query.order_by(
        Teacher.last_name,
        Teacher.first_name
    ).all()

    all_users = []

    for student in students:
        initials = (
            f"{student.first_name[0]}{student.last_name[0]}"
            if student.last_name
            else student.first_name[0]
        )

        all_users.append({
            'user_id': student.user_id,
            'profile_id': student.id,
            'name': student.get_full_name(),
            'email': student.user.email,
            'department': student.department,
            'id_number': student.student_number,
            'role': 'Student',
            'initials': initials,
            'created_at': (
                student.created_at.isoformat()
                if student.created_at
                else None
            ),
            'program': student.program
        })

    for teacher in teachers:
        initials = (
            f"{teacher.first_name[0]}{teacher.last_name[0]}"
            if teacher.last_name
            else teacher.first_name[0]
        )

        all_users.append({
            'user_id': teacher.user_id,
            'profile_id': teacher.id,
            'name': teacher.get_full_name(),
            'email': teacher.user.email,
            'department': teacher.department,
            'id_number': teacher.employee_number,
            'role': 'Teacher',
            'initials': initials,
            'created_at': (
                teacher.created_at.isoformat()
                if teacher.created_at
                else None
            ),
            'program': None
        })

    filtered_users = all_users

    if role_filter:
        filtered_users = [
            user
            for user in filtered_users
            if user['role'].lower() == role_filter.lower()
        ]

    if dept_filter:
        filtered_users = [
            user
            for user in filtered_users
            if user['department'] == dept_filter
        ]

    if search_query:
        search_lower = search_query.lower()

        filtered_users = [
            user
            for user in filtered_users
            if (
                search_lower in user['name'].lower()
                or search_lower in user['email'].lower()
                or search_lower in user['id_number'].lower()
            )
        ]

    total_users = len(filtered_users)

    total_pages = (
        (total_users + per_page - 1) // per_page
        if total_users > 0
        else 0
    )

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page

    paginated_users = filtered_users[start_idx:end_idx]

    departments = sorted({
        user['department']
        for user in all_users
        if user['department']
    })

    return jsonify({
        'success': True,

        'users': paginated_users,

        'pagination': {
            'page': page,
            'per_page': per_page,
            'total_users': total_users,
            'total_pages': total_pages,
            'has_previous': page > 1,
            'has_next': page < total_pages
        },

        'filters': {
            'role': role_filter,
            'department': dept_filter,
            'search': search_query
        },

        'available_departments': departments
    }), 200


@admin_bp.route('/delete-user/<int:user_id>', methods=['POST'])
@admin_required
def delete_user(user_id):
    try:
        user = db.session.get(User, user_id)

        if not user:
            return jsonify({
                'success': False,
                'message': 'User not found.'
            }), 404

        if user.id == current_user.id:
            return jsonify({
                'success': False,
                'message': 'You cannot delete your own account.'
            }), 400

        if user.role == 'student':
            student = Student.query.filter_by(
                user_id=user_id
            ).first()

            user_name = (
                student.get_full_name()
                if student
                else 'Student'
            )

        elif user.role == 'teacher':
            teacher = Teacher.query.filter_by(
                user_id=user_id
            ).first()

            user_name = (
                teacher.get_full_name()
                if teacher
                else 'Teacher'
            )

        else:
            return jsonify({
                'success': False,
                'message': 'This user type cannot be deleted here.'
            }), 400

        db.session.delete(user)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'{user_name} has been removed from the system.'
        }), 200

    except Exception as e:
        db.session.rollback()

        return jsonify({
            'success': False,
            'message': 'An error occurred while deleting the user.',
            'error': str(e)
        }), 500


@admin_bp.route('/reset-password/<int:user_id>', methods=['POST'])
@admin_required
def reset_password(user_id):
    try:
        user = db.session.get(User, user_id)

        if not user:
            return jsonify({
                'success': False,
                'message': 'User not found.'
            }), 404

        if user.role == 'student':
            student = Student.query.filter_by(
                user_id=user_id
            ).first()

            if not student:
                return jsonify({
                    'success': False,
                    'message': 'Student profile not found.'
                }), 404

            new_password = student.student_number
            user_name = student.get_full_name()

        elif user.role == 'teacher':
            teacher = Teacher.query.filter_by(
                user_id=user_id
            ).first()

            if not teacher:
                return jsonify({
                    'success': False,
                    'message': 'Teacher profile not found.'
                }), 404

            new_password = teacher.employee_number
            user_name = teacher.get_full_name()

        else:
            return jsonify({
                'success': False,
                'message': (
                    'Password reset is only available '
                    'for students and teachers.'
                )
            }), 400

        user.password = bcrypt.generate_password_hash(
            new_password
        ).decode('utf-8')

        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Password reset successfully for {user_name}.',
            'temporary_password': new_password
        }), 200

    except Exception as e:
        db.session.rollback()

        return jsonify({
            'success': False,
            'message': 'An error occurred while resetting the password.',
            'error': str(e)
        }), 500

@admin_bp.route('/export-users-csv')
@admin_required
def export_users_csv():
    
    # Get all users
    students = Student.query.all()
    teachers = Teacher.query.all()
    
    # Create CSV content
    output = io.StringIO()
    output.write('Name,Email,Role,ID Number,Department,Program,Created Date\n')
    
    for student in students:
        output.write(f'"{student.get_full_name()}",')
        output.write(f'"{student.user.email}",')
        output.write(f'"Student",')
        output.write(f'"{student.student_number}",')
        output.write(f'"{student.department}",')
        output.write(f'"{student.program}",')
        output.write(f'"{student.created_at.strftime("%Y-%m-%d") if student.created_at else "N/A"}"\n')
    
    for teacher in teachers:
        output.write(f'"{teacher.get_full_name()}",')
        output.write(f'"{teacher.user.email}",')
        output.write(f'"Teacher",')
        output.write(f'"{teacher.employee_number}",')
        output.write(f'"{teacher.department}",')
        output.write(f'"N/A",')
        output.write(f'"{teacher.created_at.strftime("%Y-%m-%d") if teacher.created_at else "N/A"}"\n')
    
    # Create response
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={
            'Content-Disposition': 'attachment; filename=acadify_users_export.csv'
        }
    )


@admin_bp.route('/settings', methods=['GET', 'POST'])
@admin_required
def settings():
    """
    GET:
        Return current academic settings.

    POST:
        Update academic settings or reset to automatic mode.
    """
    from models import SystemSettings
    import re

    # ---------------------------------------------------------
    # POST
    # ---------------------------------------------------------

    if request.method == 'POST':
        try:
            data = request.get_json(silent=True)

            if not data:
                return jsonify({
                    'success': False,
                    'message': 'Request body must contain JSON data.'
                }), 400

            action = data.get('action', '').strip()

            # -------------------------------------------------
            # Manual academic period
            # -------------------------------------------------

            if action == 'update_academic':

                school_year = data.get(
                    'school_year',
                    ''
                ).strip()

                semester = data.get(
                    'semester',
                    ''
                ).strip()

                if not school_year or not semester:
                    return jsonify({
                        'success': False,
                        'message': (
                            'School year and semester are required.'
                        )
                    }), 400

                if not re.match(
                    r'^\d{4}-\d{4}$',
                    school_year
                ):
                    return jsonify({
                        'success': False,
                        'message': (
                            'Invalid school year format. '
                            'Use YYYY-YYYY.'
                        )
                    }), 400

                start_year, end_year = map(
                    int,
                    school_year.split('-')
                )

                if end_year != start_year + 1:
                    return jsonify({
                        'success': False,
                        'message': (
                            'School year must contain '
                            'consecutive years.'
                        )
                    }), 400

                valid_semesters = [
                    '1st Semester',
                    '2nd Semester',
                    'Summer'
                ]

                if semester not in valid_semesters:
                    return jsonify({
                        'success': False,
                        'message': 'Invalid semester.'
                    }), 400

                SystemSettings.set_setting(
                    'current_school_year',
                    school_year,
                    current_user.email
                )

                SystemSettings.set_setting(
                    'current_semester',
                    semester,
                    current_user.email
                )

                return jsonify({
                    'success': True,
                    'message': 'Academic settings updated.',
                    'school_year': school_year,
                    'semester': semester,
                    'mode': 'manual'
                }), 200

            # -------------------------------------------------
            # Reset to automatic
            # -------------------------------------------------

            elif action == 'reset_to_auto':

                SystemSettings.delete_setting(
                    'current_school_year'
                )

                SystemSettings.delete_setting(
                    'current_semester'
                )

                return jsonify({
                    'success': True,
                    'message': (
                        'Academic period reverted to '
                        'automatic calculation.'
                    ),
                    'school_year': (
                        Config._auto_calculate_school_year()
                    ),
                    'semester': (
                        Config._auto_calculate_semester()
                    ),
                    'mode': 'automatic'
                }), 200

            return jsonify({
                'success': False,
                'message': 'Invalid action.'
            }), 400

        except Exception as e:
            db.session.rollback()

            return jsonify({
                'success': False,
                'message': (
                    'An error occurred while updating settings.'
                ),
                'error': str(e)
            }), 500

    # ---------------------------------------------------------
    # GET
    # ---------------------------------------------------------

    current_year = Config.get_current_school_year()
    current_semester = Config.get_current_semester()

    db_year = SystemSettings.get_setting(
        'current_school_year'
    )

    db_semester = SystemSettings.get_setting(
        'current_semester'
    )

    is_manual = (
        db_year is not None
        and db_semester is not None
    )

    auto_year = Config._auto_calculate_school_year()
    auto_semester = Config._auto_calculate_semester()

    last_updated = None
    updated_by = None

    if is_manual:
        year_setting = SystemSettings.query.filter_by(
            setting_key='current_school_year'
        ).first()

        if year_setting:
            last_updated = (
                year_setting.updated_at.isoformat()
                if year_setting.updated_at
                else None
            )

            updated_by = year_setting.updated_by

    return jsonify({
        'success': True,

        'current': {
            'school_year': current_year,
            'semester': current_semester
        },

        'mode': (
            'manual'
            if is_manual
            else 'automatic'
        ),

        'automatic_values': {
            'school_year': auto_year,
            'semester': auto_semester
        },

        'manual_values': {
            'school_year': db_year,
            'semester': db_semester
        },

        'last_updated': last_updated,
        'updated_by': updated_by
    }), 200