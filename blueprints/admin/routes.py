"""
blueprints/admin/routes.py - Admin Blueprint
Backend routes for your gold-themed admin dashboard
"""

from flask import Blueprint, jsonify, request, Response, send_file
from flask_login import current_user
from models import User, Student, Teacher, Enrollment, Class
from extensions import db, bcrypt
from config import Config
from sqlalchemy import func
from datetime import datetime
from functools import wraps
from werkzeug.utils import secure_filename
import csv
import io

from helpers.student_helpers import get_student_academic_status
from helpers.progression_helpers import check_student_progression

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment


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



def read_import_rows(file):
    """
    Read CSV or Excel files.

    Returns a list of (row_number, row_data) tuples.
    Headers are preserved as written in the file.
    """
    filename = secure_filename(file.filename or "")
    extension = filename.rsplit(".", 1)[-1].lower()

    if extension == "csv":
        try:
            content = file.stream.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ValueError("CSV file must use UTF-8 encoding.")

        reader = csv.DictReader(io.StringIO(content))

        if not reader.fieldnames:
            raise ValueError("The CSV file is empty or missing headers.")

        return [
            (row_number, row)
            for row_number, row in enumerate(reader, start=2)
        ]

    if extension == "xlsx":
        try:
            workbook = load_workbook(
                file.stream,
                read_only=True,
                data_only=True
            )
        except Exception:
            raise ValueError("Invalid Excel file.")

        try:
            worksheet = workbook.active
            rows = worksheet.iter_rows(values_only=True)

            headers = next(rows, None)

            if not headers:
                raise ValueError("The Excel file is empty.")

            headers = [
                str(header).strip() if header is not None else ""
                for header in headers
            ]

            result = []

            for row_number, values in enumerate(rows, start=2):
                if not any(value is not None for value in values):
                    continue

                row = {
                    header: str(value).strip()
                    if value is not None else ""
                    for header, value in zip(headers, values)
                }

                result.append((row_number, row))

            return result

        finally:
            workbook.close()

    raise ValueError("Only CSV and XLSX files are supported.")



def generate_import_template(headers, example_row, filename):
    """
    Generate a CSV or XLSX registration template.
    CSV is the default format.
    """
    file_format = request.args.get(
        'format', 'csv'
    ).strip().lower()

    if file_format not in ('csv', 'xlsx'):
        return jsonify({
            'success': False,
            'message': 'Unsupported format. Use csv or xlsx.'
        }), 400

    if file_format == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow(headers)
        writer.writerow(example_row)

        return Response(
            '\ufeff' + output.getvalue(),
            mimetype='text/csv; charset=utf-8',
            headers={
                'Content-Disposition':
                    f'attachment; filename={filename}.csv'
            }
        )

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = 'Import Template'

    worksheet.append(headers)
    worksheet.append(example_row)

    header_fill = PatternFill(
        fill_type='solid',
        fgColor='1E3A5F'
    )

    header_font = Font(
        bold=True,
        color='FFFFFF'
    )

    for cell in worksheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(
            horizontal='center'
        )

    # Preserve ID numbers as text.
    for column_number, header in enumerate(headers, start=1):
        if header in ('Student Number', 'Employee Number'):
            for row_number in range(2, 1002):
                worksheet.cell(
                    row=row_number,
                    column=column_number
                ).number_format = '@'

    for column in worksheet.columns:
        letter = column[0].column_letter
        max_length = max(
            len(str(cell.value or ''))
            for cell in column
        )
        worksheet.column_dimensions[letter].width = min(
            max(max_length + 3, 16),
            40
        )

    worksheet.freeze_panes = 'A2'

    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name=f'{filename}.xlsx',
        mimetype=(
            'application/vnd.openxmlformats-officedocument.'
            'spreadsheetml.sheet'
        )
    )





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
            'status':get_student_academic_status(student)
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
    """Register a student using official academic information."""
    try:
        data = request.get_json(silent=True)

        if not isinstance(data, dict):
            return jsonify({
                'success': False,
                'message': 'Request body must contain a JSON object.'
            }), 400

        def clean(value):
            return value.strip() if isinstance(value, str) else ''

        full_name = clean(data.get('full_name'))
        student_number = clean(data.get('student_number'))
        email = clean(data.get('email')).lower()
        department = clean(data.get('department'))
        program = clean(data.get('program'))
        year_level = clean(data.get('year_level'))

        enrollment_classification = clean(
            data.get('enrollment_classification', 'Not Yet Verified')
        )

        valid_classifications = {
            'Regular',
            'Irregular',
            'Not Yet Verified'
        }

        if not all([
            full_name,
            student_number,
            email,
            department,
            program,
            year_level
        ]):
            return jsonify({
                'success': False,
                'message': 'Please fill in all required fields.'
            }), 400

        if enrollment_classification not in valid_classifications:
            return jsonify({
                'success': False,
                'message': 'Invalid enrollment classification.'
            }), 400

        name_parts = full_name.split()
        first_name = name_parts[0]
        last_name = ' '.join(name_parts[1:])

        if User.query.filter_by(email=email).first():
            return jsonify({
                'success': False,
                'message': 'Email already exists.'
            }), 409

        if Student.query.filter_by(
            student_number=student_number
        ).first():
            return jsonify({
                'success': False,
                'message': 'Student number already exists.'
            }), 409

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
            enrollment_classification=enrollment_classification,
            academic_status='Inactive'
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
                'enrollment_classification':
                    student.enrollment_classification,
                'academic_status': get_student_academic_status(student)
            },
            'default_password': 'Student number'
        }), 201

    except Exception:
        db.session.rollback()

        return jsonify({
            'success': False,
            'message': 'An error occurred while registering the student.'
        }), 500


@admin_bp.route('/students/<int:student_id>/academic', methods=['PATCH'])
@admin_required
def update_student_academic(student_id):
    """Update official student academic information."""
    try:
        student = db.session.get(Student, student_id)

        if not student:
            return jsonify({
                'success': False,
                'message': 'Student not found.'
            }), 404

        data = request.get_json(silent=True)

        if not isinstance(data, dict):
            return jsonify({
                'success': False,
                'message': 'A JSON object is required.'
            }), 400

        allowed_fields = {
            'year_level',
            'enrollment_classification',
            'academic_status',
            'confirm_graduation'
        }

        unknown_fields = set(data) - allowed_fields

        if unknown_fields:
            return jsonify({
                'success': False,
                'message': (
                    'Unsupported fields: ' +
                    ', '.join(sorted(unknown_fields))
                )
            }), 400

        if not data:
            return jsonify({
                'success': False,
                'message': 'No changes were provided.'
            }), 400

        if 'year_level' in data:
            year_level = data['year_level']

            if not isinstance(year_level, str) or not year_level.strip():
                return jsonify({
                    'success': False,
                    'message': 'A valid year level is required.'
                }), 400

            student.year_level = year_level.strip()

        if 'enrollment_classification' in data:
            classification = data['enrollment_classification']

            valid_classifications = {
                'Regular',
                'Irregular',
                'Not Yet Verified'
            }

            if classification not in valid_classifications:
                return jsonify({
                    'success': False,
                    'message': 'Invalid enrollment classification.'
                }), 400

            student.enrollment_classification = classification

        if 'academic_status' in data:
            requested_status = data['academic_status']

            if requested_status != 'Graduated':
                return jsonify({
                    'success': False,
                    'message': (
                        'Active and Inactive are determined '
                        'automatically by enrollment.'
                    )
                }), 400

            if data.get('confirm_graduation') is not True:
                return jsonify({
                    'success': False,
                    'message': (
                        'Explicit graduation confirmation is required.'
                    )
                }), 400

            if student.academic_status != 'Graduated':
                student.academic_status = 'Graduated'

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Student academic information updated.',
            'student': {
                'id': student.id,
                'student_number': student.student_number,
                'year_level': student.year_level,
                'enrollment_classification':
                    student.enrollment_classification,
                'academic_status': get_student_academic_status(student)
            }
        }), 200

    except Exception:
        db.session.rollback()

        return jsonify({
            'success': False,
            'message': 'Unable to update student academic information.'
        }), 500



@admin_bp.route(
    '/students/<int:student_id>/reverse-graduation',
    methods=['POST']
)
@admin_required
def reverse_student_graduation(student_id):
    """
    Reverse a student's Graduated status.

    Only administrators can perform this action.
    The student's status is recalculated from
    enrollment in the current academic period.
    """
    try:
        student = db.session.get(Student, student_id)

        if not student:
            return jsonify({
                'success': False,
                'message': 'Student not found.'
            }), 404

        data = request.get_json(silent=True)

        if not isinstance(data, dict):
            return jsonify({
                'success': False,
                'message': 'A JSON object is required.'
            }), 400

        if data.get('confirm_reversal') is not True:
            return jsonify({
                'success': False,
                'message': 'Explicit reversal confirmation is required.'
            }), 400

        reason = data.get('reason')

        if not isinstance(reason, str) or not reason.strip():
            return jsonify({
                'success': False,
                'message': 'A reason for graduation reversal is required.'
            }), 400

        if student.academic_status != 'Graduated':
            return jsonify({
                'success': False,
                'message': 'Student is not currently marked as Graduated.'
            }), 400

        current_year = Config.get_current_school_year()
        current_semester = Config.get_current_semester()

        has_current_enrollment = (
            db.session.query(Enrollment.id)
            .join(Class, Enrollment.class_id == Class.id)
            .filter(
                Enrollment.student_id == student.id,
                Enrollment.status == 'enrolled',
                Class.school_year == current_year,
                Class.semester == current_semester
            )
            .first()
            is not None
        )

        student.academic_status = (
            'Active' if has_current_enrollment else 'Inactive'
        )

        # Temporary application audit logging.
        # A persistent database audit table will be added later.
        import logging

        logging.getLogger(__name__).info(
            'Graduation reversed: student_id=%s, '
            'admin_id=%s, reason=%s, new_status=%s',
            student.id,
            current_user.id,
            reason.strip(),
            student.academic_status
        )

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Graduation status reversed successfully.',
            'student': {
                'id': student.id,
                'student_number': student.student_number,
                'academic_status':  get_student_academic_status(student)
            }
        }), 200

    except Exception:
        db.session.rollback()

        return jsonify({
            'success': False,
            'message': 'Unable to reverse graduation status.'
        }), 500



@admin_bp.route('/students/academic/bulk-preview', methods=['POST'])
@admin_required
def preview_bulk_academic_updates():
    """Validate a CSV/XLSX academic update file without modifying records."""
    try:
        file = request.files.get('csv_file') or request.files.get('file')

        if not file or not file.filename:
            return jsonify({
                'success': False,
                'message': 'Please upload a CSV or Excel file.'
            }), 400

        try:
            rows = read_import_rows(file)
        except ValueError as e:
            return jsonify({
                'success': False,
                'message': str(e)
            }), 400

        if not rows:
            return jsonify({
                'success': False,
                'message': 'The uploaded file contains no records.'
            }), 400

        required_headers = {
            'Student Number',
            'Year Level',
            'Enrollment Classification'
        }

        missing_headers = required_headers - set(rows[0][1].keys())

        if missing_headers:
            return jsonify({
                'success': False,
                'message': (
                    'Missing columns: ' +
                    ', '.join(sorted(missing_headers))
                )
            }), 400

        valid_classifications = {
            'Regular',
            'Irregular',
            'Not Yet Verified'
        }

        preview = []
        errors = []
        seen_numbers = set()

        for row_number, row in rows:
            student_number = row.get('Student Number', '').strip()
            year_level = row.get('Year Level', '').strip()
            classification = row.get(
                'Enrollment Classification', ''
            ).strip()

            if not student_number:
                errors.append({
                    'row': row_number,
                    'message': 'Student Number is required.'
                })
                continue

            if student_number in seen_numbers:
                errors.append({
                    'row': row_number,
                    'message': 'Duplicate student number in upload.'
                })
                continue

            seen_numbers.add(student_number)

            if not year_level and not classification:
                errors.append({
                    'row': row_number,
                    'message': 'No academic changes specified.'
                })
                continue

            if classification and classification not in valid_classifications:
                errors.append({
                    'row': row_number,
                    'message': 'Invalid enrollment classification.'
                })
                continue

            student = Student.query.filter_by(
                student_number=student_number
            ).first()

            if not student:
                errors.append({
                    'row': row_number,
                    'message': f'Student {student_number} not found.'
                })
                continue

            new_year_level = year_level or student.year_level
            new_classification = (
                classification or student.enrollment_classification
            )

            preview.append({
                'row': row_number,
                'student_id': student.id,
                'student_number': student.student_number,
                'student_name': student.get_full_name(),
                'current': {
                    'year_level': student.year_level,
                    'enrollment_classification':
                        student.enrollment_classification
                },
                'proposed': {
                    'year_level': new_year_level,
                    'enrollment_classification': new_classification
                }
            })

        return jsonify({
            'success': True,
            'message': 'Academic update preview generated.',
            'summary': {
                'valid': len(preview),
                'errors': len(errors)
            },
            'preview': preview,
            'errors': errors
        }), 200

    except Exception:
        return jsonify({
            'success': False,
            'message': 'Unable to preview academic updates.'
        }), 500



@admin_bp.route('/students/academic/bulk-confirm', methods=['POST'])
@admin_required
def confirm_bulk_academic_updates():
    """Atomically apply administrator-confirmed academic updates."""
    try:
        data = request.get_json(silent=True)

        if not isinstance(data, dict):
            return jsonify({
                'success': False,
                'message': 'A JSON object is required.'
            }), 400

        if data.get('confirm') is not True:
            return jsonify({
                'success': False,
                'message': 'Explicit confirmation is required.'
            }), 400

        updates = data.get('updates')

        if not isinstance(updates, list) or not updates:
            return jsonify({
                'success': False,
                'message': 'No academic updates provided.'
            }), 400

        if len(updates) > 1000:
            return jsonify({
                'success': False,
                'message': 'Maximum of 1000 updates per request.'
            }), 400

        valid_classifications = {
            'Regular',
            'Irregular',
            'Not Yet Verified'
        }

        prepared = []
        errors = []
        seen_numbers = set()

        # Validate every update before modifying any student.
        for index, item in enumerate(updates, start=1):
            if not isinstance(item, dict):
                errors.append({
                    'row': index,
                    'message': 'Invalid update object.'
                })
                continue

            student_number = item.get('student_number')
            current = item.get('current')
            proposed = item.get('proposed')

            if not isinstance(student_number, str) or not student_number.strip():
                errors.append({
                    'row': index,
                    'message': 'Student number is required.'
                })
                continue

            student_number = student_number.strip()

            if student_number in seen_numbers:
                errors.append({
                    'row': index,
                    'message': 'Duplicate student number.'
                })
                continue

            seen_numbers.add(student_number)

            if not isinstance(current, dict) or not isinstance(proposed, dict):
                errors.append({
                    'row': index,
                    'message': 'Current and proposed values are required.'
                })
                continue

            year_level = proposed.get('year_level')
            classification = proposed.get('enrollment_classification')

            if not isinstance(year_level, str) or not year_level.strip():
                errors.append({
                    'row': index,
                    'message': 'Invalid proposed year level.'
                })
                continue

            if classification not in valid_classifications:
                errors.append({
                    'row': index,
                    'message': 'Invalid proposed enrollment classification.'
                })
                continue

            student = Student.query.filter_by(
                student_number=student_number
            ).first()

            if not student:
                errors.append({
                    'row': index,
                    'message': f'Student {student_number} not found.'
                })
                continue

            # Reject stale previews rather than overwriting newer changes.
            if (
                student.year_level != current.get('year_level')
                or student.enrollment_classification
                != current.get('enrollment_classification')
            ):
                errors.append({
                    'row': index,
                    'message': (
                        f'Academic information for {student_number} '
                        'has changed since preview. Preview again.'
                    )
                })
                continue

            prepared.append({
                'student': student,
                'year_level': year_level.strip(),
                'enrollment_classification': classification
            })

        if errors:
            return jsonify({
                'success': False,
                'message': 'Validation failed. No changes were applied.',
                'errors': errors
            }), 400

        # Changes are committed together, not individually.
        for update in prepared:
            student = update['student']
            student.year_level = update['year_level']
            student.enrollment_classification = (
                update['enrollment_classification']
            )

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Academic information updated successfully.',
            'summary': {
                'updated': len(prepared),
                'errors': 0
            }
        }), 200

    except Exception:
        db.session.rollback()

        return jsonify({
            'success': False,
            'message': 'Unable to confirm academic updates.'
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
    """Register students from a CSV or XLSX file."""
    try:
        file = request.files.get('csv_file') or request.files.get('file')

        if not file or not file.filename:
            return jsonify({
                'success': False,
                'message': 'Please upload a CSV or Excel file.'
            }), 400

        try:
            rows = read_import_rows(file)
        except ValueError as e:
            return jsonify({
                'success': False,
                'message': str(e)
            }), 400

        required_headers = {
            'Full Name',
            'Student Number',
            'Email',
            'Department',
            'Program',
            'Year Level'
        }

        # Headers are checked separately from row values.
        # This also supports an empty template with valid headers.
        if rows:
            actual_headers = set(rows[0][1].keys())
        else:
            return jsonify({
                'success': False,
                'message': 'The uploaded file contains no student records.'
            }), 400

        missing_headers = required_headers - actual_headers

        if missing_headers:
            return jsonify({
                'success': False,
                'message': (
                    'Missing required columns: ' +
                    ', '.join(sorted(missing_headers))
                )
            }), 400

        valid_classifications = {
            'Regular',
            'Irregular',
            'Not Yet Verified'
        }

        success_count = 0
        error_count = 0
        error_details = []

        for row_number, row in rows:
            try:
                full_name = row.get('Full Name', '').strip()
                student_number = row.get('Student Number', '').strip()
                email = row.get('Email', '').strip().lower()
                department = row.get('Department', '').strip()
                program = row.get('Program', '').strip()
                year_level = row.get('Year Level', '').strip()

                enrollment_classification = (
                    row.get('Enrollment Classification', '').strip()
                    or 'Not Yet Verified'
                )

                if not all([
                    full_name,
                    student_number,
                    email,
                    department,
                    program,
                    year_level
                ]):
                    raise ValueError('Missing required fields.')

                if enrollment_classification not in valid_classifications:
                    raise ValueError(
                        'Invalid enrollment classification: ' +
                        enrollment_classification
                    )

                if User.query.filter_by(email=email).first():
                    raise ValueError(
                        f'Email {email} already exists.'
                    )

                if Student.query.filter_by(
                    student_number=student_number
                ).first():
                    raise ValueError(
                        f'Student number {student_number} already exists.'
                    )

                name_parts = full_name.split()
                first_name = name_parts[0]
                last_name = ' '.join(name_parts[1:])

                with db.session.begin_nested():
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
                        enrollment_classification=enrollment_classification,
                        academic_status='Inactive'
                    )

                    db.session.add(student)
                    db.session.flush()

                success_count += 1

            except Exception as e:
                error_count += 1
                error_details.append({
                    'row': row_number,
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

    except Exception:
        db.session.rollback()

        return jsonify({
            'success': False,
            'message': 'Student import failed.'
        }), 500


@admin_bp.route('/bulk-import-teachers', methods=['POST'])
@admin_required
def bulk_import_teachers():
    """Register teachers from a CSV or XLSX file."""
    try:
        file = request.files.get('csv_file') or request.files.get('file')

        if not file or not file.filename:
            return jsonify({
                'success': False,
                'message': 'Please upload a CSV or Excel file.'
            }), 400

        try:
            rows = read_import_rows(file)
        except ValueError as e:
            return jsonify({
                'success': False,
                'message': str(e)
            }), 400

        if not rows:
            return jsonify({
                'success': False,
                'message': 'The uploaded file contains no teacher records.'
            }), 400

        required_headers = {
            'Full Name',
            'Employee Number',
            'Email',
            'Department'
        }

        actual_headers = set(rows[0][1].keys())
        missing_headers = required_headers - actual_headers

        if missing_headers:
            return jsonify({
                'success': False,
                'message': (
                    'Missing required columns: ' +
                    ', '.join(sorted(missing_headers))
                )
            }), 400

        success_count = 0
        error_count = 0
        error_details = []

        for row_number, row in rows:
            try:
                full_name = row.get('Full Name', '').strip()
                employee_number = row.get('Employee Number', '').strip()
                email = row.get('Email', '').strip().lower()
                department = row.get('Department', '').strip()
                specialization = row.get('Specialization', '').strip()

                if not all([
                    full_name,
                    employee_number,
                    email,
                    department
                ]):
                    raise ValueError('Missing required fields.')

                if User.query.filter_by(email=email).first():
                    raise ValueError(
                        f'Email {email} already exists.'
                    )

                if Teacher.query.filter_by(
                    employee_number=employee_number
                ).first():
                    raise ValueError(
                        f'Employee number {employee_number} already exists.'
                    )

                name_parts = full_name.split()
                first_name = name_parts[0]
                last_name = ' '.join(name_parts[1:])

                with db.session.begin_nested():
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
                        specialization=specialization or None
                    )

                    db.session.add(teacher)
                    db.session.flush()

                success_count += 1

            except Exception as e:
                error_count += 1
                error_details.append({
                    'row': row_number,
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

    except Exception:
        db.session.rollback()

        return jsonify({
            'success': False,
            'message': 'Teacher import failed.'
        }), 500


@admin_bp.route('/download/student-template')
@admin_required
def download_student_template():
    headers = [
        'Full Name',
        'Student Number',
        'Email',
        'Department',
        'Program',
        'Year Level',
        'Enrollment Classification'
    ]

    example_row = [
        'Juan Dela Cruz',
        '20260001',
        'juan@student.acadify.edu',
        'College of Engineering',
        'BS Computer Engineering',
        '1st Year',
        'Not Yet Verified'
    ]

    return generate_import_template(
        headers,
        example_row,
        'acadify_student_registration_template'
    )



@admin_bp.route('/download/teacher-template')
@admin_required
def download_teacher_template():
    headers = [
        'Full Name',
        'Employee Number',
        'Email',
        'Department',
        'Specialization'
    ]

    example_row = [
        'Pedro Reyes',
        'T2026001',
        'pedro@faculty.acadify.edu',
        'College of Engineering',
        'Computer Engineering'
    ]

    return generate_import_template(
        headers,
        example_row,
        'acadify_teacher_registration_template'
    )



@admin_bp.route('/download/academic-update-template')
@admin_required
def download_academic_update_template():
    """
    Download a CSV or XLSX template for bulk
    student academic information updates.
    """
    headers = [
        'Student Number',
        'Year Level',
        'Enrollment Classification'
    ]

    example_row = [
        '20260001',
        '2nd Year',
        'Regular'
    ]

    return generate_import_template(
        headers,
        example_row,
        'acadify_student_academic_update_template'
    )


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
            'program': student.program,
            'year_level': student.year_level,
            'enrollment_classification': student.enrollment_classification,
            'academic_status': get_student_academic_status(student)
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
            'program': None,
            'year_level': None,
            'enrollment_classification': None,
            'academic_status': None
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




# ---------------------------------------------------------
# ADMIN — MANUAL ACADEMIC PROGRESSION CHECKER
# ---------------------------------------------------------

@admin_bp.route('/progression/check', methods=['GET'])
@admin_required
def check_academic_progression():
    """
    Evaluate student progression eligibility.

    Optional query parameters:
        student_id: Evaluate one student
        school_year: Academic year to evaluate

    Without student_id, evaluates all students.

    Read-only: does not update student records.
    """

    school_year = request.args.get('school_year') or Config.get_current_school_year()
    student_id = request.args.get('student_id', type=int)

    if student_id is not None:
        student = db.session.get(Student, student_id)

        if student is None:
            return jsonify({
                'success': False,
                'message': 'Student not found.'
            }), 404

        result = check_student_progression(
            student,
            school_year=school_year
        )

        return jsonify({
            'success': True,
            'data': result
        }), 200

    students = Student.query.order_by(
        Student.last_name,
        Student.first_name
    ).all()

    results = [
        check_student_progression(
            student,
            school_year=school_year
        )
        for student in students
    ]

    eligible_count = sum(
        1 for result in results if result['eligible']
    )

    return jsonify({
        'success': True,
        'school_year': school_year,
        'summary': {
            'total_students': len(results),
            'eligible': eligible_count,
            'ineligible': len(results) - eligible_count
        },
        'data': results
    }), 200



@admin_bp.route('/progression/promote/<int:student_id>', methods=['POST'])
@admin_required
def promote_student(student_id):
    """
    Promote one eligible student by one year level.
    Requires explicit administrator confirmation.
    """

    data = request.get_json(silent=True) or {}

    if data.get('confirm_promotion') is not True:
        return jsonify({
            'success': False,
            'message': 'Explicit promotion confirmation is required.'
        }), 400

    student = db.session.get(Student, student_id)

    if student is None:
        return jsonify({
            'success': False,
            'message': 'Student not found.'
        }), 404

    # Always recheck eligibility before changing the record.
    result = check_student_progression(student)

    if not result['eligible']:
        return jsonify({
            'success': False,
            'message': 'Student is not eligible for promotion.',
            'reasons': result['reasons']
        }), 400

    year_levels = [
        '1st Year',
        '2nd Year',
        '3rd Year',
        '4th Year',
        '5th Year',
        '6th Year'
    ]

    if student.year_level not in year_levels:
        return jsonify({
            'success': False,
            'message': 'Invalid student year level.'
        }), 400

    current_index = year_levels.index(student.year_level)

    if current_index + 1 >= len(year_levels):
        return jsonify({
            'success': False,
            'message': 'No higher year level is available.'
        }), 400

    previous_year_level = student.year_level
    next_year_level = year_levels[current_index + 1]

    try:
        student.year_level = next_year_level
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Student promoted successfully.',
            'data': {
                'student_id': student.id,
                'student_number': student.student_number,
                'previous_year_level': previous_year_level,
                'new_year_level': next_year_level
            }
        }), 200

    except Exception:
        db.session.rollback()

        return jsonify({
            'success': False,
            'message': 'Failed to promote student.'
        }), 500



# ---------------------------------------------------------
# ADMIN — BATCH STUDENT PROMOTION
# ---------------------------------------------------------

@admin_bp.route('/progression/promote/batch', methods=['POST'])
@admin_required
def promote_students_batch():
    """
    Promote eligible students by one year level.

    Ineligible students are skipped.
    Each student's eligibility is rechecked.
    """

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            'success': False,
            'message': 'A JSON object is required.'
        }), 400

    if data.get('confirm_promotion') is not True:
        return jsonify({
            'success': False,
            'message': 'Explicit promotion confirmation is required.'
        }), 400

    student_ids = data.get('student_ids')

    if (
        not isinstance(student_ids, list)
        or not student_ids
        or any(type(sid) is not int or sid <= 0 for sid in student_ids)
    ):
        return jsonify({
            'success': False,
            'message': 'student_ids must be a non-empty list of positive integers.'
        }), 400

    if len(student_ids) != len(set(student_ids)):
        return jsonify({
            'success': False,
            'message': 'Duplicate student IDs are not allowed.'
        }), 400

    if len(student_ids) > 100:
        return jsonify({
            'success': False,
            'message': 'Maximum of 100 students per batch.'
        }), 400

    year_levels = [
        '1st Year',
        '2nd Year',
        '3rd Year',
        '4th Year',
        '5th Year',
        '6th Year'
    ]

    promoted = []
    rejected = []

    try:
        for student_id in student_ids:
            student = db.session.get(Student, student_id)

            if student is None:
                rejected.append({
                    'student_id': student_id,
                    'reasons': ['Student not found.']
                })
                continue

            result = check_student_progression(student)

            if not result['eligible']:
                rejected.append({
                    'student_id': student_id,
                    'student_number': student.student_number,
                    'reasons': result['reasons']
                })
                continue

            if student.year_level not in year_levels:
                rejected.append({
                    'student_id': student_id,
                    'student_number': student.student_number,
                    'reasons': ['Invalid student year level.']
                })
                continue

            current_index = year_levels.index(student.year_level)

            if current_index + 1 >= len(year_levels):
                rejected.append({
                    'student_id': student_id,
                    'student_number': student.student_number,
                    'reasons': ['No higher year level is available.']
                })
                continue

            previous_year_level = student.year_level
            next_year_level = year_levels[current_index + 1]

            student.year_level = next_year_level

            promoted.append({
                'student_id': student.id,
                'student_number': student.student_number,
                'previous_year_level': previous_year_level,
                'new_year_level': next_year_level
            })

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Batch promotion processed.',
            'summary': {
                'requested': len(student_ids),
                'promoted': len(promoted),
                'rejected': len(rejected)
            },
            'promoted': promoted,
            'rejected': rejected
        }), 200

    except Exception:
        db.session.rollback()

        return jsonify({
            'success': False,
            'message': 'Batch promotion failed. No changes were saved.'
        }), 500