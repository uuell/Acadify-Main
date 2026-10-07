"""
blueprints/teacher/routes.py - Teacher Blueprint COMPLETE & FIXED
Handles teacher-specific routes: dashboard, classes, grading, roster management.
This version fixes the routing errors while preserving all existing functionality.
"""

from flask import Blueprint, request, jsonify, current_app
from flask_login import current_user

from models import (
    Class,
    Enrollment,
    Student,
    Grade,
    Test
)

from extensions import db, bcrypt
from config import Config
from sqlalchemy import func, or_
from datetime import datetime, timedelta

# Initialize the blueprint for teacher-related routes
teacher_bp = Blueprint('teacher', __name__)

REQUIRED_TERM_TAGS = (
    'Prelims',
    'Midterms',
    'Finals'
)

PASSING_GRADE = 3.0


# ─────────────────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS — Add these to routes.py (outside any route, at module level)
# ─────────────────────────────────────────────────────────────────────────────


def get_enrollment_grade_display(enrollment, class_obj):
    """
    Return the display value for an enrollment's semester grade.
    """

    # Final grade exists.
    if enrollment.final_grade is not None:
        return f"{enrollment.final_grade:.2f}"

    current_school_year = Config.get_current_school_year()
    current_semester = Config.get_current_semester()

    is_current_semester = (
        class_obj.school_year == current_school_year
        and class_obj.semester == current_semester
    )

    # Semester is still ongoing.
    if is_current_semester:
        return "—"

    # Semester has ended but no final grade exists.
    return "INC"
 
def recalculate_term_grade(student_id, class_id, term_tag):
    """
    Calculate the Philippine grade for one student in one term.

    A term is complete only when:
        - every formula component has at least one test
        - every test in every component has a valid score

    Grading flow:
        raw score / max score
            ↓
        test percentage
            ↓
        component average
            ↓
        weighted term percentage
            ↓
        Philippine term grade
    """

    cls = Class.query.get(class_id)

    if not cls:
        return {
            'grade': None,
            'display': 'INC',
            'percentage': None,
            'missing': []
        }

    formula = cls.get_grading_formula()

    if not formula or 'components' not in formula:
        return {
            'grade': None,
            'display': 'INC',
            'percentage': None,
            'missing': ['No formula']
        }

    missing = []
    comp_averages = {}
    any_scores = False

    # ---------------------------------------------------------
    # Check every component in the grading formula
    # ---------------------------------------------------------

    for comp in formula['components']:

        comp_name = comp['name']

        tests_in_group = Test.query.filter_by(
            class_id=class_id,
            term_tag=term_tag,
            component_tag=comp_name
        ).all()

        # Component has no test at all.
        if not tests_in_group:
            missing.append(comp_name)
            continue

        percentages = []
        component_incomplete = False

        # -----------------------------------------------------
        # Every test in the component must have a valid score
        # -----------------------------------------------------

        for test in tests_in_group:

            grade = Grade.query.filter_by(
                test_id=test.id,
                student_id=student_id
            ).first()

            if grade and grade.raw_score is not None:
                any_scores = True

            if (
                not grade
                or grade.raw_score is None
                or grade.max_score is None
                or grade.max_score <= 0
            ):
                component_incomplete = True
                continue

            percentage = (
                grade.raw_score / grade.max_score
            ) * 100

            percentages.append(percentage)

        # At least one required test is still ungraded.
        if component_incomplete:
            missing.append(comp_name)
            continue

        # Defensive check.
        if not percentages:
            missing.append(comp_name)
            continue

        comp_averages[comp_name] = (
            sum(percentages) / len(percentages)
        )

    # ---------------------------------------------------------
    # Incomplete term
    # ---------------------------------------------------------

    if missing:
        return {
            'grade': None,
            'display': 'INC' if any_scores else '—',
            'percentage': None,
            'missing': missing
        }

    # ---------------------------------------------------------
    # Calculate weighted term percentage
    # ---------------------------------------------------------

    total_weighted = 0.0

    for comp in formula['components']:

        comp_name = comp['name']
        weight = float(comp['weight'])

        total_weighted += (
            comp_averages[comp_name]
            * (weight / 100)
        )

    percentage = round(total_weighted, 2)

    # ---------------------------------------------------------
    # Convert percentage to PH grade
    # ---------------------------------------------------------

    ph_grade = cls.convert_to_ph_grade(percentage)

    return {
        'grade': ph_grade,
        'display': f"{ph_grade:.2f}",
        'percentage': percentage,
        'missing': []
    }
 
def _compute_term_grade_readonly(student_id, class_obj, term_tag):
    """
    Same as recalculate_term_grade but never writes to DB.
    Used when rendering the grading page.
    """
    return recalculate_term_grade(
        student_id=student_id,
        class_id=class_obj.id,
        term_tag=term_tag
    )

def _update_enrollment_average(student_id, class_id):
    """
    Update Enrollment.final_grade only when every required
    semester term is fully complete.

    Required terms:
        - Prelims
        - Midterms
        - Finals
    """

    cls = Class.query.get(class_id)

    if not cls:
        return

    enrollment = Enrollment.query.filter_by(
        student_id=student_id,
        class_id=class_id
    ).first()

    if not enrollment:
        return

    completed_grades = []

    # ---------------------------------------------------------
    # Every required semester term must be complete
    # ---------------------------------------------------------

    for term in REQUIRED_TERM_TAGS:

        result = recalculate_term_grade(
            student_id=student_id,
            class_id=class_id,
            term_tag=term
        )

        if result.get('grade') is None:
            enrollment.final_grade = None
            db.session.commit()
            return

        completed_grades.append(
            result['grade']
        )

    # ---------------------------------------------------------
    # Prelims + Midterms + Finals are all complete
    # ---------------------------------------------------------

    enrollment.final_grade = round(
        sum(completed_grades)
        / len(completed_grades),
        2
    )

    db.session.commit()

def teacher_required(f):
    """
    Ensure the request belongs to an authenticated teacher.
    """

    from functools import wraps

    @wraps(f)
    def decorated_function(*args, **kwargs):

        if not current_user.is_authenticated:
            return jsonify({
                'success': False,
                'message': 'Authentication required.'
            }), 401

        if current_user.role != 'teacher':
            return jsonify({
                'success': False,
                'message': 'Access denied. Teachers only.'
            }), 403

        return f(*args, **kwargs)

    return decorated_function


@teacher_bp.route('/dashboard', methods=['GET'])
@teacher_required
def dashboard():
    """
    API: Return teacher dashboard data.

    Optional query parameters:
        ?year=2026-2027
        ?semester=1st Semester

    If not provided, defaults to the current academic period.
    """

    teacher = current_user.teacher_profile

    current_school_year = Config.get_current_school_year()
    current_semester = Config.get_current_semester()

    # ---------------------------------------------------------
    # Filters
    # ---------------------------------------------------------

    selected_year = request.args.get('year')
    selected_semester = request.args.get('semester')

    if not selected_year or selected_year == 'all':
        selected_year = current_school_year

    if not selected_semester or selected_semester == 'all':
        selected_semester = current_semester

    # ---------------------------------------------------------
    # Get teacher classes
    # ---------------------------------------------------------

    all_classes = Class.query.filter_by(
        teacher_id=teacher.id
    ).all()

    actual_years = {
        cls.school_year
        for cls in all_classes
        if cls.school_year
    }

    current_year_num = datetime.now().year

    buffer_years = {
        f"{year}-{year + 1}"
        for year in range(
            current_year_num - 5,
            current_year_num + 3
        )
    }

    available_years = sorted(
        actual_years | buffer_years,
        reverse=True
    )

    classes = Class.query.filter_by(
        teacher_id=teacher.id,
        school_year=selected_year,
        semester=selected_semester
    ).all()

    # ---------------------------------------------------------
    # Total distinct students
    # ---------------------------------------------------------

    total_students = (
        db.session.query(
            func.count(
                func.distinct(Enrollment.student_id)
            )
        )
        .join(
            Class,
            Enrollment.class_id == Class.id
        )
        .filter(
            Class.teacher_id == teacher.id,
            Class.school_year == selected_year,
            Class.semester == selected_semester,
            Enrollment.status == 'enrolled'
        )
        .scalar()
        or 0
    )

    # ---------------------------------------------------------
    # Weekly schedule summary
    # ---------------------------------------------------------

    weekly_schedule = {
        'Monday': 0,
        'Tuesday': 0,
        'Wednesday': 0,
        'Thursday': 0,
        'Friday': 0,
        'Saturday': 0
    }

    for cls in classes:

        if not cls.schedule:
            continue

        schedule_upper = cls.schedule.upper()

        if 'M' in schedule_upper and 'MONDAY' not in schedule_upper:
            weekly_schedule['Monday'] += 1

        if 'T' in schedule_upper and 'TH' not in schedule_upper:
            weekly_schedule['Tuesday'] += 1

        if 'W' in schedule_upper:
            weekly_schedule['Wednesday'] += 1

        if 'TH' in schedule_upper or 'R' in schedule_upper:
            weekly_schedule['Thursday'] += 1

        if 'F' in schedule_upper:
            weekly_schedule['Friday'] += 1

        if 'SAT' in schedule_upper or 'S' in schedule_upper:
            weekly_schedule['Saturday'] += 1

    # ---------------------------------------------------------
    # Class statistics
    # ---------------------------------------------------------

    classes_data = []

    for cls in classes:

        student_count = Enrollment.query.filter_by(
            class_id=cls.id,
            status='enrolled'
        ).count()

        tests = Test.query.filter_by(
            class_id=cls.id
        ).all()

        ungraded_count = 0

        for test in tests:

            enrolled_students = Enrollment.query.filter_by(
                class_id=cls.id,
                status='enrolled'
            ).count()

            graded_students = (
                Grade.query
                .filter_by(test_id=test.id)
                .filter(
                    Grade.raw_score.isnot(None)
                )
                .count()
            )

            ungraded_count += max(
                enrolled_students - graded_students,
                0
            )

        classes_data.append({
            'id': cls.id,
            'subject_name': cls.effective_subject_name,
            'subject_code': cls.effective_subject_code,
            'units': cls.effective_units,
            'section': cls.section,
            'schedule': cls.schedule,
            'room': cls.room,
            'student_count': student_count,
            'ungraded_count': ungraded_count
        })

    # ---------------------------------------------------------
    # Teacher data
    # ---------------------------------------------------------

    teacher_data = {
        'id': teacher.id,
        'employee_number': teacher.employee_number,
        'first_name': teacher.first_name,
        'last_name': teacher.last_name,
        'department': teacher.department
    }

    # ---------------------------------------------------------
    # JSON response
    # ---------------------------------------------------------

    return jsonify({
        'success': True,

        'teacher': teacher_data,

        'academic_period': {
            'current_school_year': current_school_year,
            'current_semester': current_semester
        },

        'filters': {
            'selected_year': selected_year,
            'selected_semester': selected_semester,
            'available_years': available_years
        },

        'statistics': {
            'total_students': total_students,
            'total_classes': len(classes),
            'weekly_schedule': weekly_schedule
        },

        'classes': classes_data
    }), 200

@teacher_bp.route('/classes', methods=['GET'])
@teacher_required
def classes():
    """
    API: Get classes belonging to the logged-in teacher.

    Optional query parameters:
        ?year=2026-2027
        ?semester=1st Semester

    Use "all" to disable a filter:
        ?year=all&semester=all
    """
    teacher = current_user.teacher_profile

    current_school_year = Config.get_current_school_year()
    current_semester = Config.get_current_semester()

    # Default to the current academic period if parameters
    # are not provided.
    selected_year = request.args.get('year')
    selected_semester = request.args.get('semester')

    if selected_year is None:
        selected_year = current_school_year

    if selected_semester is None:
        selected_semester = current_semester

    # ---------------------------------------------------------
    # Build class query
    # ---------------------------------------------------------

    query = Class.query.filter_by(
        teacher_id=teacher.id
    )

    if selected_year != 'all':
        query = query.filter_by(
            school_year=selected_year
        )

    if selected_semester != 'all':
        query = query.filter_by(
            semester=selected_semester
        )

    teacher_classes = query.order_by(
        Class.school_year.desc(),
        Class.semester
    ).all()

    # ---------------------------------------------------------
    # Available school years
    # ---------------------------------------------------------

    all_teacher_classes = Class.query.filter_by(
        teacher_id=teacher.id
    ).all()

    available_years = sorted(
        {
            cls.school_year
            for cls in all_teacher_classes
        },
        reverse=True
    )

    # ---------------------------------------------------------
    # Build class data
    # ---------------------------------------------------------

    classes_data = []

    for cls in teacher_classes:

        enrollment_count = Enrollment.query.filter_by(
            class_id=cls.id,
            status='enrolled'
        ).count()

        tests = Test.query.filter_by(
            class_id=cls.id
        ).all()

        total_possible_grades = (
            enrollment_count * len(tests)
            if tests
            else 0
        )

        graded_count = 0

        if total_possible_grades > 0:
            for test in tests:
                graded_count += (
                    Grade.query
                    .filter_by(test_id=test.id)
                    .filter(Grade.raw_score.isnot(None))
                    .count()
                )

            grading_percentage = (
                graded_count / total_possible_grades
            ) * 100
        else:
            grading_percentage = 0

        capacity_percentage = (
            (enrollment_count / cls.max_students) * 100
            if cls.max_students
            else 0
        )

        classes_data.append({
            'id': cls.id,
            'name': cls.effective_subject_name,
            'code': cls.effective_subject_code,
            'units': cls.effective_units,
            'section': cls.section,
            'schedule': cls.schedule,
            'room': cls.room,

            'academic_period': {
                'school_year': cls.school_year,
                'semester': cls.semester
            },

            'enrollment': {
                'count': enrollment_count,
                'max_students': cls.max_students,
                'capacity_percentage': round(
                    capacity_percentage,
                    2
                )
            },

            'grading': {
                'test_count': len(tests),
                'graded_count': graded_count,
                'total_possible_grades': total_possible_grades,
                'completion_percentage': round(
                    grading_percentage,
                    2
                ),
                'has_formula': cls.has_grading_formula(),
                'can_edit_formula': cls.can_edit_formula()
            }
        })

    # ---------------------------------------------------------
    # JSON API response
    # ---------------------------------------------------------

    return jsonify({
        'success': True,

        'current_academic_period': {
            'school_year': current_school_year,
            'semester': current_semester
        },

        'filters': {
            'selected_year': selected_year,
            'selected_semester': selected_semester,
            'available_years': available_years
        },

        'classes': classes_data,
        'count': len(classes_data)
    }), 200


@teacher_bp.route('/students', methods=['GET'])
@teacher_required
def get_students():
    """
    API: Get students available to the teacher.

    Optional query parameters:
        ?search=juan
        ?department=COE
        ?program=BSCpE
        ?class_id=1

    If class_id is provided, the response also indicates
    whether each student is already enrolled in that class.
    """
    teacher = current_user.teacher_profile

    search = request.args.get('search', '').strip()
    department = request.args.get('department', '').strip()
    program = request.args.get('program', '').strip()
    class_id = request.args.get('class_id', type=int)

    # ---------------------------------------------------------
    # If class_id is provided, verify teacher owns the class
    # ---------------------------------------------------------

    cls = None
    enrolled_student_ids = set()

    if class_id is not None:
        cls = Class.query.filter_by(
            id=class_id,
            teacher_id=teacher.id
        ).first()

        if not cls:
            return jsonify({
                'success': False,
                'message': 'Class not found or you do not have access to it.'
            }), 404

        enrolled_student_ids = {
            enrollment.student_id
            for enrollment in Enrollment.query.filter_by(
                class_id=class_id,
                status='enrolled'
            ).all()
        }

    # ---------------------------------------------------------
    # Build student query
    # ---------------------------------------------------------

    query = Student.query

    if department:
        query = query.filter(
            Student.department == department
        )

    if program:
        query = query.filter(
            Student.program == program
        )

    if search:
        search_pattern = f'%{search}%'

        query = query.filter(
            or_(
                Student.first_name.ilike(search_pattern),
                Student.last_name.ilike(search_pattern),
                Student.student_number.ilike(search_pattern)
            )
        )

    students = query.order_by(
        Student.last_name,
        Student.first_name
    ).all()

    # ---------------------------------------------------------
    # Serialize
    # ---------------------------------------------------------

    students_data = []

    for student in students:
        student_data = {
            'id': student.id,
            'student_number': student.student_number,
            'first_name': student.first_name,
            'last_name': student.last_name,
            'department': student.department,
            'program': student.program,
            'year_level': student.year_level,
            'section': student.section
        }

        if class_id is not None:
            student_data['is_enrolled'] = (
                student.id in enrolled_student_ids
            )

        students_data.append(student_data)

    return jsonify({
        'success': True,
        'students': students_data,
        'count': len(students_data),

        'filters': {
            'search': search or None,
            'department': department or None,
            'program': program or None,
            'class_id': class_id
        }
    }), 200



@teacher_bp.route('/classes/create', methods=['POST'])
@teacher_required
def create_class():
    """
    API: Create a new class with a grading formula
    and optionally enroll selected students.

    Expected JSON:
    {
        "subject_name": "Software Engineering",
        "subject_code": "CPE401",
        "units": 3,
        "section": "4A",
        "room": "201",
        "schedule": "MWF 10:00-11:00",
        "school_year": "2026-2027",
        "semester": "1st Semester",
        "max_students": 40,
        "grading_formula": {
            "components": [
                {"name": "Quizzes", "weight": 30},
                {"name": "Activities", "weight": 40},
                {"name": "Exams", "weight": 30}
            ]
        },
        "student_ids": [1, 2, 3]
    }
    """

    teacher = current_user.teacher_profile

    # ---------------------------------------------------------
    # Get JSON request
    # ---------------------------------------------------------

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            'success': False,
            'message': 'Request body must be valid JSON.'
        }), 400

    # ---------------------------------------------------------
    # Get subject/class fields
    # ---------------------------------------------------------

    subject_name = str(
        data.get('subject_name') or ''
    ).strip()

    subject_code = str(
        data.get('subject_code') or ''
    ).strip()

    section = str(
        data.get('section') or ''
    ).strip()

    room = str(
        data.get('room') or ''
    ).strip()

    schedule = str(
        data.get('schedule') or ''
    ).strip()

    school_year = str(
        data.get('school_year') or ''
    ).strip()

    semester = str(
        data.get('semester') or ''
    ).strip()

    # ---------------------------------------------------------
    # Validate numeric fields
    # ---------------------------------------------------------

    try:
        units = int(data.get('units'))
    except (TypeError, ValueError):
        return jsonify({
            'success': False,
            'message': 'Units must be a valid integer.'
        }), 400

    try:
        max_students = int(
            data.get('max_students', 40)
        )
    except (TypeError, ValueError):
        return jsonify({
            'success': False,
            'message': 'Maximum students must be a valid integer.'
        }), 400

    # ---------------------------------------------------------
    # Validate required fields
    # ---------------------------------------------------------

    if not subject_name:
        return jsonify({
            'success': False,
            'message': 'Subject name is required.'
        }), 400

    if units < 1:
        return jsonify({
            'success': False,
            'message': 'Units must be at least 1.'
        }), 400

    if not section:
        return jsonify({
            'success': False,
            'message': 'Section is required.'
        }), 400

    if not school_year:
        return jsonify({
            'success': False,
            'message': 'School year is required.'
        }), 400

    if not semester:
        return jsonify({
            'success': False,
            'message': 'Semester is required.'
        }), 400

    if max_students < 1:
        return jsonify({
            'success': False,
            'message': 'Maximum students must be at least 1.'
        }), 400

    # ---------------------------------------------------------
    # Validate grading formula
    # ---------------------------------------------------------

    formula = data.get('grading_formula')

    if not isinstance(formula, dict):
        return jsonify({
            'success': False,
            'message': 'Grading formula is required.'
        }), 400

    components = formula.get('components')

    if not isinstance(components, list) or not components:
        return jsonify({
            'success': False,
            'message': 'Grading formula must contain at least one component.'
        }), 400

    total_weight = 0

    for component in components:

        if not isinstance(component, dict):
            return jsonify({
                'success': False,
                'message': 'Each grading component must be an object.'
            }), 400

        name = str(
            component.get('name') or ''
        ).strip()

        if not name:
            return jsonify({
                'success': False,
                'message': 'All grading components must have a name.'
            }), 400

        try:
            weight = float(component.get('weight'))
        except (TypeError, ValueError):
            return jsonify({
                'success': False,
                'message': f'Weight for "{name}" must be a valid number.'
            }), 400

        if weight < 0 or weight > 100:
            return jsonify({
                'success': False,
                'message': (
                    f'Weight for "{name}" must be '
                    'between 0 and 100.'
                )
            }), 400

        # Normalize values before saving.
        component['name'] = name
        component['weight'] = weight

        total_weight += weight

    if abs(total_weight - 100) > 0.001:
        return jsonify({
            'success': False,
            'message': (
                f'Component weights must total 100%. '
                f'Current total: {total_weight}%.'
            )
        }), 400

    formula['use_philippine_conversion'] = True

    # ---------------------------------------------------------
    # Validate student IDs
    # ---------------------------------------------------------

    student_ids = data.get('student_ids', [])

    if student_ids is None:
        student_ids = []

    if not isinstance(student_ids, list):
        return jsonify({
            'success': False,
            'message': 'student_ids must be an array.'
        }), 400

    try:
        student_ids = list({
            int(student_id)
            for student_id in student_ids
        })
    except (TypeError, ValueError):
        return jsonify({
            'success': False,
            'message': 'All student IDs must be valid integers.'
        }), 400

    if len(student_ids) > max_students:
        return jsonify({
            'success': False,
            'message': (
                f'Cannot enroll {len(student_ids)} students. '
                f'Class capacity is {max_students}.'
            )
        }), 400

    # Verify students actually exist.
    students = []

    if student_ids:
        students = Student.query.filter(
            Student.id.in_(student_ids)
        ).all()

        found_ids = {
            student.id
            for student in students
        }

        missing_ids = [
            student_id
            for student_id in student_ids
            if student_id not in found_ids
        ]

        if missing_ids:
            return jsonify({
                'success': False,
                'message': 'One or more students were not found.',
                'invalid_student_ids': missing_ids
            }), 400

    # ---------------------------------------------------------
    # Create class + enrollments
    # ---------------------------------------------------------

    try:
        new_class = Class(
            teacher_id=teacher.id,

            subject_name=subject_name,
            subject_code=subject_code or None,
            units=units,

            section=section,
            room=room or None,
            schedule=schedule or None,

            school_year=school_year,
            semester=semester,
            max_students=max_students
        )

        # Let the Class model validate and serialize the formula.
        new_class.set_grading_formula(formula)

        db.session.add(new_class)
        db.session.flush()

        for student in students:
            enrollment = Enrollment(
                student_id=student.id,
                class_id=new_class.id,
                status='enrolled'
            )

            db.session.add(enrollment)

        db.session.commit()

    except ValueError as e:
        db.session.rollback()

        return jsonify({
            'success': False,
            'message': str(e)
        }), 400

    except Exception:
        db.session.rollback()

        current_app.logger.exception(
            'Unexpected error while creating class'
        )

        return jsonify({
            'success': False,
            'message': 'An unexpected error occurred while creating the class.'
        }), 500

    # ---------------------------------------------------------
    # Success
    # ---------------------------------------------------------

    return jsonify({
        'success': True,
        'message': 'Class created successfully.',

        'class': {
            'id': new_class.id,
            'subject_name': new_class.effective_subject_name,
            'subject_code': new_class.effective_subject_code,
            'units': new_class.effective_units,
            'section': new_class.section,
            'room': new_class.room,
            'schedule': new_class.schedule,
            'school_year': new_class.school_year,
            'semester': new_class.semester,
            'max_students': new_class.max_students,
            'enrollment_count': len(students),
            'grading_formula': new_class.get_grading_formula()
        }
    }), 201

@teacher_bp.route('/classes/delete', methods=['POST'])
@teacher_required
def delete_class():
    """
    API: Delete a teacher-owned class.

    Expected JSON:
    {
        "class_id": 1
    }
    """

    teacher = current_user.teacher_profile

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            'success': False,
            'message': 'Request body must be valid JSON.'
        }), 400

    class_id = data.get('class_id')

    try:
        class_id = int(class_id)
    except (TypeError, ValueError):
        return jsonify({
            'success': False,
            'message': 'class_id must be a valid integer.'
        }), 400

    cls = Class.query.filter_by(
        id=class_id,
        teacher_id=teacher.id
    ).first()

    if not cls:
        return jsonify({
            'success': False,
            'message': 'Class not found or you do not have access to it.'
        }), 404

    class_name = (
        f"{cls.effective_subject_name} "
        f"- Section {cls.section}"
    )

    try:
        db.session.delete(cls)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Class "{class_name}" deleted successfully.',
            'deleted_class_id': class_id
        }), 200

    except Exception:
        db.session.rollback()

        current_app.logger.exception(
            'Unexpected error while deleting class %s',
            class_id
        )

        return jsonify({
            'success': False,
            'message': 'An unexpected error occurred while deleting the class.'
        }), 500

@teacher_bp.route('/classes/<int:class_id>', methods=['GET'])
@teacher_required
def class_detail(class_id):
    """
    API: Get detailed information for one teacher-owned class,
    including its enrolled students and grading status.
    """
    teacher = current_user.teacher_profile

    # Get class and verify ownership
    cls = Class.query.filter_by(
        id=class_id,
        teacher_id=teacher.id
    ).first()

    if not cls:
        return jsonify({
            'success': False,
            'message': 'Class not found or you do not have access to it.'
        }), 404

    # Get active enrollments
    enrollments = (
        Enrollment.query
        .filter_by(
            class_id=class_id,
            status='enrolled'
        )
        .join(Student)
        .order_by(Student.last_name, Student.first_name)
        .all()
    )

    students = []

    for enrollment in enrollments:
        student = enrollment.student

        # Count graded activities
        grade_count = (
            Grade.query
            .join(Test)
            .filter(
                Test.class_id == class_id,
                Grade.student_id == student.id,
                Grade.raw_score.isnot(None)
            )
            .count()
        )

        students.append({
            'id': student.id,
            'student_number': student.student_number,
            'first_name': student.first_name,
            'last_name': student.last_name,

            'enrollment': {
                'id': enrollment.id,
                'status': enrollment.status,
                'final_grade': enrollment.final_grade,
                'grade_display': get_enrollment_grade_display(
                    enrollment,
                    cls
                )
            },

            'graded_activities': grade_count
        })

    return jsonify({
        'success': True,

        'class': {
            'id': cls.id,
            'subject_name': cls.effective_subject_name,
            'subject_code': cls.effective_subject_code,
            'units': cls.effective_units,
            'section': cls.section,
            'schedule': cls.schedule,
            'room': cls.room,
            'school_year': cls.school_year,
            'semester': cls.semester
        },

        'students': students,
        'student_count': len(students)
    }), 200

@teacher_bp.route('/classes/<int:class_id>/formula', methods=['GET'])
@teacher_required
def view_formula(class_id):
    """
    API: Get grading formula for a teacher-owned class.
    """

    teacher = current_user.teacher_profile

    cls = Class.query.filter_by(
        id=class_id,
        teacher_id=teacher.id
    ).first()

    if not cls:
        return jsonify({
            'success': False,
            'message': 'Class not found or you do not have access to it.'
        }), 404

    return jsonify({
        'success': True,
        'formula': cls.get_grading_formula(),
        'can_edit': cls.can_edit_formula()
    }), 200


@teacher_bp.route('/classes/<int:class_id>/formula', methods=['POST'])
@teacher_required
def update_formula(class_id):
    """
    API: Update a class grading formula.

    Expected JSON:
    {
        "formula": {
            "components": [
                {"name": "Quizzes", "weight": 30},
                {"name": "Activities", "weight": 40},
                {"name": "Exams", "weight": 30}
            ]
        }
    }
    """

    teacher = current_user.teacher_profile

    cls = Class.query.filter_by(
        id=class_id,
        teacher_id=teacher.id
    ).first()

    if not cls:
        return jsonify({
            'success': False,
            'message': 'Class not found or you do not have access to it.'
        }), 404

    if not cls.can_edit_formula():
        return jsonify({
            'success': False,
            'message': (
                'Cannot edit the grading formula after '
                'grades have been entered.'
            )
        }), 403

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            'success': False,
            'message': 'Request body must be valid JSON.'
        }), 400

    formula = data.get('formula')

    if not isinstance(formula, dict):
        return jsonify({
            'success': False,
            'message': 'formula must be a JSON object.'
        }), 400

    try:
        cls.set_grading_formula(formula)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Grading formula updated successfully.',
            'formula': cls.get_grading_formula(),
            'can_edit': cls.can_edit_formula()
        }), 200

    except ValueError as e:
        db.session.rollback()

        return jsonify({
            'success': False,
            'message': str(e)
        }), 400

    except Exception:
        db.session.rollback()

        current_app.logger.exception(
            'Unexpected error while updating formula for class %s',
            class_id
        )

        return jsonify({
            'success': False,
            'message': (
                'An unexpected error occurred while '
                'updating the grading formula.'
            )
        }), 500


@teacher_bp.route('/classes/<int:class_id>/enrolled-students', methods=['GET'])
@teacher_required
def get_enrolled_students(class_id):
    """
    API: Return currently enrolled students for a class.
    """

    teacher = current_user.teacher_profile

    cls = Class.query.filter_by(
        id=class_id,
        teacher_id=teacher.id
    ).first()

    if not cls:
        return jsonify({
            'success': False,
            'message': 'Class not found or you do not have access to it.'
        }), 404

    enrollments = (
        Enrollment.query
        .filter_by(
            class_id=class_id,
            status='enrolled'
        )
        .join(Student)
        .order_by(
            Student.last_name,
            Student.first_name
        )
        .all()
    )

    students = []

    for enrollment in enrollments:
        student = enrollment.student

        students.append({
            'id': student.id,
            'student_number': student.student_number,
            'first_name': student.first_name,
            'last_name': student.last_name,
            'department': student.department,
            'program': student.program,
            'year_level': student.year_level,
            'section': student.section
        })

    return jsonify({
        'success': True,
        'class_id': class_id,
        'students': students,
        'count': len(students)
    }), 200


@teacher_bp.route('/classes/<int:class_id>/edit-data', methods=['GET'])
@teacher_required
def get_class_edit_data(class_id):
    """
    API: Return class information needed by the React edit form.
    """

    teacher = current_user.teacher_profile

    cls = Class.query.filter_by(
        id=class_id,
        teacher_id=teacher.id
    ).first()

    if not cls:
        return jsonify({
            'success': False,
            'message': 'Class not found or you do not have access to it.'
        }), 404

    enrollment_count = Enrollment.query.filter_by(
        class_id=class_id,
        status='enrolled'
    ).count()

    has_grades = (
        Grade.query
        .join(Test)
        .filter(
            Test.class_id == class_id,
            Grade.raw_score.isnot(None)
        )
        .count() > 0
    )

    return jsonify({
        'success': True,

        'class': {
            'id': cls.id,

            'subject_name': cls.effective_subject_name,
            'subject_code': cls.effective_subject_code,
            'units': cls.effective_units,

            'section': cls.section,
            'school_year': cls.school_year,
            'semester': cls.semester,

            'schedule': cls.schedule,
            'room': cls.room,
            'max_students': cls.max_students,

            'grading_formula': (
                cls.get_grading_formula()
            ),

            'enrollment_count': enrollment_count,
            'has_grades': has_grades,
            'can_edit_formula': (
                cls.can_edit_formula()
            )
        }
    }), 200


@teacher_bp.route('/classes/<int:class_id>/update', methods=['POST'])
@teacher_required
def update_class(class_id):
    """
    API: Update safe class fields, grading formula,
    and optionally the student roster.

    Expected JSON example:
    {
        "schedule": "MWF 10:00-11:00",
        "room": "201",
        "max_students": 40,

        "grading_formula": {
            "components": [
                {"name": "Quizzes", "weight": 30},
                {"name": "Activities", "weight": 40},
                {"name": "Exams", "weight": 30}
            ],
            "use_philippine_conversion": true
        },

        "student_ids": [1, 2, 3]
    }

    Notes:
        - grading_formula is optional
        - student_ids is optional
        - if student_ids is omitted, roster is not changed
        - if student_ids = [], all current students are removed/dropped
    """

    teacher = current_user.teacher_profile

    # ---------------------------------------------------------
    # Verify teacher owns the class
    # ---------------------------------------------------------

    cls = Class.query.filter_by(
        id=class_id,
        teacher_id=teacher.id
    ).first()

    if not cls:
        return jsonify({
            'success': False,
            'message': 'Class not found or you do not have access to it.'
        }), 404

    # ---------------------------------------------------------
    # Get JSON request
    # ---------------------------------------------------------

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            'success': False,
            'message': 'Request body must be valid JSON.'
        }), 400

    try:
        # -----------------------------------------------------
        # Schedule
        # -----------------------------------------------------

        if 'schedule' in data:
            schedule = str(
                data.get('schedule') or ''
            ).strip()

            cls.schedule = schedule or None

        # -----------------------------------------------------
        # Room
        # -----------------------------------------------------

        if 'room' in data:
            room = str(
                data.get('room') or ''
            ).strip()

            cls.room = room or None

        # -----------------------------------------------------
        # Maximum students
        # -----------------------------------------------------

        if 'max_students' in data:

            try:
                max_students = int(
                    data.get('max_students')
                )

            except (TypeError, ValueError):
                return jsonify({
                    'success': False,
                    'message': 'max_students must be a valid integer.'
                }), 400

            if max_students < 1:
                return jsonify({
                    'success': False,
                    'message': 'Maximum students must be at least 1.'
                }), 400

            current_enrollment_count = (
                Enrollment.query.filter_by(
                    class_id=class_id,
                    status='enrolled'
                ).count()
            )

            if max_students < current_enrollment_count:
                return jsonify({
                    'success': False,
                    'message': (
                        'Cannot reduce class capacity below the '
                        f'current enrollment of '
                        f'{current_enrollment_count} students.'
                    )
                }), 400

            cls.max_students = max_students

        # -----------------------------------------------------
        # Grading formula
        # -----------------------------------------------------

        if 'grading_formula' in data:

            formula = data.get('grading_formula')

            if formula is not None:

                if not isinstance(formula, dict):
                    return jsonify({
                        'success': False,
                        'message': (
                            'grading_formula must be a JSON object.'
                        )
                    }), 400

                if not cls.can_edit_formula():
                    return jsonify({
                        'success': False,
                        'message': (
                            'Cannot edit the grading formula after '
                            'grades have been entered.'
                        )
                    }), 403

                # Let the model perform the real formula validation.
                cls.set_grading_formula(formula)

        # -----------------------------------------------------
        # Student roster
        #
        # Important:
        # Only modify roster when student_ids is actually
        # included in the JSON request.
        # -----------------------------------------------------

        added_student_ids = []
        removed_student_ids = []
        dropped_student_ids = []

        if 'student_ids' in data:

            student_ids = data.get('student_ids')

            if student_ids is None:
                student_ids = []

            if not isinstance(student_ids, list):
                return jsonify({
                    'success': False,
                    'message': 'student_ids must be an array.'
                }), 400

            try:
                new_student_ids = {
                    int(student_id)
                    for student_id in student_ids
                }

            except (TypeError, ValueError):
                return jsonify({
                    'success': False,
                    'message': (
                        'All student IDs must be valid integers.'
                    )
                }), 400

            # -------------------------------------------------
            # Verify requested students exist
            # -------------------------------------------------

            requested_students = []

            if new_student_ids:

                requested_students = Student.query.filter(
                    Student.id.in_(new_student_ids)
                ).all()

                found_ids = {
                    student.id
                    for student in requested_students
                }

                missing_ids = sorted(
                    new_student_ids - found_ids
                )

                if missing_ids:
                    return jsonify({
                        'success': False,
                        'message': (
                            'One or more students were not found.'
                        ),
                        'invalid_student_ids': missing_ids
                    }), 400

            # -------------------------------------------------
            # Check capacity using requested final roster
            # -------------------------------------------------

            if len(new_student_ids) > cls.max_students:
                return jsonify({
                    'success': False,
                    'message': (
                        f'Cannot enroll {len(new_student_ids)} '
                        f'students. Class capacity is '
                        f'{cls.max_students}.'
                    )
                }), 400

            # -------------------------------------------------
            # Current active roster
            # -------------------------------------------------

            current_enrollments = (
                Enrollment.query.filter_by(
                    class_id=class_id,
                    status='enrolled'
                ).all()
            )

            current_student_ids = {
                enrollment.student_id
                for enrollment in current_enrollments
            }

            students_to_add = (
                new_student_ids - current_student_ids
            )

            students_to_remove = (
                current_student_ids - new_student_ids
            )

            # -------------------------------------------------
            # Add / reactivate students
            # -------------------------------------------------

            for student_id in students_to_add:

                # Check if this student was previously dropped.
                existing_enrollment = (
                    Enrollment.query.filter_by(
                        class_id=class_id,
                        student_id=student_id
                    ).first()
                )

                if existing_enrollment:
                    existing_enrollment.status = 'enrolled'

                else:
                    enrollment = Enrollment(
                        student_id=student_id,
                        class_id=class_id,
                        status='enrolled'
                    )

                    db.session.add(enrollment)

                added_student_ids.append(student_id)

            # -------------------------------------------------
            # Remove students
            # -------------------------------------------------

            for student_id in students_to_remove:

                enrollment = Enrollment.query.filter_by(
                    class_id=class_id,
                    student_id=student_id,
                    status='enrolled'
                ).first()

                if not enrollment:
                    continue

                # Determine whether historical grade data exists.
                has_grades = (
                    Grade.query
                    .join(Test)
                    .filter(
                        Test.class_id == class_id,
                        Grade.student_id == student_id,
                        Grade.raw_score.isnot(None)
                    )
                    .count() > 0
                )

                if has_grades:
                    # Keep enrollment history.
                    enrollment.status = 'dropped'
                    dropped_student_ids.append(student_id)

                else:
                    # No grade history, safe to delete.
                    db.session.delete(enrollment)
                    removed_student_ids.append(student_id)

        # -----------------------------------------------------
        # Commit everything
        # -----------------------------------------------------

        db.session.commit()

        # -----------------------------------------------------
        # Build response
        # -----------------------------------------------------

        enrollment_count = Enrollment.query.filter_by(
            class_id=class_id,
            status='enrolled'
        ).count()

        return jsonify({
            'success': True,
            'message': 'Class updated successfully.',

            'class': {
                'id': cls.id,
                'subject_name': cls.effective_subject_name,
                'subject_code': cls.effective_subject_code,
                'units': cls.effective_units,
                'section': cls.section,
                'schedule': cls.schedule,
                'room': cls.room,
                'school_year': cls.school_year,
                'semester': cls.semester,
                'max_students': cls.max_students,
                'enrollment_count': enrollment_count,
                'grading_formula': cls.get_grading_formula(),
                'can_edit_formula': cls.can_edit_formula()
            },

            'roster_changes': {
                'added_student_ids': sorted(
                    added_student_ids
                ),
                'removed_student_ids': sorted(
                    removed_student_ids
                ),
                'dropped_student_ids': sorted(
                    dropped_student_ids
                )
            }
        }), 200

    except ValueError as e:
        db.session.rollback()

        return jsonify({
            'success': False,
            'message': str(e)
        }), 400

    except Exception:
        db.session.rollback()

        current_app.logger.exception(
            'Unexpected error while updating class %s',
            class_id
        )

        return jsonify({
            'success': False,
            'message': (
                'An unexpected error occurred while '
                'updating the class.'
            )
        }), 500


@teacher_bp.route('/grading', methods=['GET'])
@teacher_required
def grading():
    """
    API: Return grading data for a teacher-owned class.

    Optional query parameters:
        ?year=2026-2027
        ?semester=1st Semester
        ?class_id=1

    Response includes:
        - available teacher classes
        - selected class
        - tests
        - grading terms
        - grading components
        - enrolled students
        - raw activity scores
        - computed term grades
        - enrollment final grade
    """

    teacher = current_user.teacher_profile

    current_school_year = Config.get_current_school_year()
    current_semester = Config.get_current_semester()

    # ---------------------------------------------------------
    # Filters
    # ---------------------------------------------------------

    selected_year = request.args.get('year')
    selected_semester = request.args.get('semester')

    if selected_year is None:
        selected_year = current_school_year

    if selected_semester is None:
        selected_semester = current_semester

    # ---------------------------------------------------------
    # Get teacher classes
    # ---------------------------------------------------------

    query = Class.query.filter_by(
        teacher_id=teacher.id
    )

    if selected_year != 'all':
        query = query.filter_by(
            school_year=selected_year
        )

    if selected_semester != 'all':
        query = query.filter_by(
            semester=selected_semester
        )

    classes = query.order_by(
        Class.school_year.desc(),
        Class.semester
    ).all()

    # ---------------------------------------------------------
    # Available school years
    # ---------------------------------------------------------

    all_teacher_classes = Class.query.filter_by(
        teacher_id=teacher.id
    ).all()

    available_years = sorted(
        {
            cls.school_year
            for cls in all_teacher_classes
            if cls.school_year
        },
        reverse=True
    )

    # ---------------------------------------------------------
    # Selected class
    # ---------------------------------------------------------

    selected_class_id = request.args.get(
        'class_id',
        type=int
    )

    selected_class = None

    if selected_class_id is not None:

        selected_class = next(
            (
                cls
                for cls in classes
                if cls.id == selected_class_id
            ),
            None
        )

        if not selected_class:
            return jsonify({
                'success': False,
                'message': (
                    'Class not found in the selected academic '
                    'period or you do not have access to it.'
                )
            }), 404

    elif classes:
        selected_class = classes[0]

    # ---------------------------------------------------------
    # Serialize class list
    # ---------------------------------------------------------

    classes_data = []

    for cls in classes:
        classes_data.append({
            'id': cls.id,
            'subject_name': cls.effective_subject_name,
            'subject_code': cls.effective_subject_code,
            'units': cls.effective_units,
            'section': cls.section,
            'school_year': cls.school_year,
            'semester': cls.semester
        })

    # ---------------------------------------------------------
    # No available class
    # ---------------------------------------------------------

    if not selected_class:
        return jsonify({
            'success': True,

            'current_academic_period': {
                'school_year': current_school_year,
                'semester': current_semester
            },

            'filters': {
                'selected_year': selected_year,
                'selected_semester': selected_semester,
                'available_years': available_years
            },

            'classes': classes_data,
            'selected_class': None,

            'grading': {
                'tests': [],
                'terms': [],
                'components': [],
                'students': []
            }
        }), 200

    # ---------------------------------------------------------
    # Enrolled students
    # ---------------------------------------------------------

    enrollments = (
        Enrollment.query
        .filter_by(
            class_id=selected_class.id,
            status='enrolled'
        )
        .join(Student)
        .order_by(
            Student.last_name,
            Student.first_name
        )
        .all()
    )

    # ---------------------------------------------------------
    # Tests
    # ---------------------------------------------------------

    tests = (
        Test.query
        .filter_by(
            class_id=selected_class.id
        )
        .order_by(
            Test.term_tag,
            Test.component_tag,
            Test.test_date,
            Test.created_at
        )
        .all()
    )

    tests_data = []

    for test in tests:

        tests_data.append({
            'id': test.id,
            'title': test.title,
            'term_tag': test.term_tag,
            'component_tag': test.component_tag,

            'test_date': (
                test.test_date.isoformat()
                if test.test_date
                else None
            ),

            'created_at': (
                test.created_at.isoformat()
                if test.created_at
                else None
            )
        })

    # ---------------------------------------------------------
    # Ordered grading terms
    # ---------------------------------------------------------

    seen_terms = set()
    term_tags = []

    for test in tests:

        if (
            test.term_tag
            and test.term_tag not in seen_terms
        ):
            seen_terms.add(test.term_tag)
            term_tags.append(test.term_tag)

    # ---------------------------------------------------------
    # Formula components
    # ---------------------------------------------------------

    formula = selected_class.get_grading_formula()

    formula_components = []

    if formula:
        formula_components = [
            component['name']
            for component in formula.get(
                'components',
                []
            )
        ]

    # ---------------------------------------------------------
    # Tests grouped by term
    # ---------------------------------------------------------

    tests_by_term = {}

    for term in term_tags:

        tests_by_term[term] = [
            test.id
            for test in tests
            if test.term_tag == term
        ]

    # ---------------------------------------------------------
    # Student grading data
    # ---------------------------------------------------------

    students_data = []

    for enrollment in enrollments:

        student = enrollment.student

        # -----------------------------------------------------
        # Activity scores
        # -----------------------------------------------------

        test_grades = {}

        for test in tests:

            grade = Grade.query.filter_by(
                test_id=test.id,
                student_id=student.id
            ).first()

            if grade:
                test_grades[str(test.id)] = {
                    'grade_id': grade.id,
                    'raw_score': grade.raw_score,
                    'max_score': grade.max_score,
                    'calculated_percentage': (
                        grade.calculated_percentage
                    ),
                    'graded_at': (
                        grade.graded_at.isoformat()
                        if grade.graded_at
                        else None
                    )
                }

            else:
                test_grades[str(test.id)] = None

        # -----------------------------------------------------
        # Computed term grades
        # -----------------------------------------------------

        term_grades = {}

        for term in term_tags:

            result = recalculate_term_grade(
                student_id=student.id,
                class_id=selected_class.id,
                term_tag=term
            )

            term_grades[term] = {
                'grade': result.get('grade'),
                'display': result.get('display'),
                'percentage': result.get(
                    'percentage'
                ),
                'missing_components': result.get(
                    'missing',
                    []
                )
            }

        # -----------------------------------------------------
        # Student serialization
        # -----------------------------------------------------

        students_data.append({
            'student': {
                'id': student.id,
                'student_number': student.student_number,
                'first_name': student.first_name,
                'last_name': student.last_name,
                'department': student.department,
                'program': student.program,
                'year_level': student.year_level,
                'section': student.section
            },

            'enrollment': {
                'id': enrollment.id,
                'status': enrollment.status,
                'final_grade': enrollment.final_grade,
                'final_grade_display': (
                    get_enrollment_grade_display(
                        enrollment,
                        selected_class
                    )
                )
            },

            'test_grades': test_grades,
            'term_grades': term_grades
        })

    # ---------------------------------------------------------
    # Selected class serialization
    # ---------------------------------------------------------

    selected_class_data = {
        'id': selected_class.id,
        'subject_name': (
            selected_class.effective_subject_name
        ),
        'subject_code': (
            selected_class.effective_subject_code
        ),
        'units': selected_class.effective_units,
        'section': selected_class.section,
        'schedule': selected_class.schedule,
        'room': selected_class.room,
        'school_year': selected_class.school_year,
        'semester': selected_class.semester,
        'grading_formula': formula
    }

    # ---------------------------------------------------------
    # Final JSON response
    # ---------------------------------------------------------

    return jsonify({
        'success': True,

        'current_academic_period': {
            'school_year': current_school_year,
            'semester': current_semester
        },

        'filters': {
            'selected_year': selected_year,
            'selected_semester': selected_semester,
            'available_years': available_years
        },

        'classes': classes_data,

        'selected_class': selected_class_data,

        'grading': {
            'tests': tests_data,
            'terms': term_tags,
            'components': formula_components,
            'tests_by_term': tests_by_term,
            'students': students_data
        }
    }), 200


@teacher_bp.route('/grading/update', methods=['POST'])
@teacher_required
def update_grade():
    """
    API: Create or update one student's score for one test.

    Expected JSON:
    {
        "student_id": 1,
        "test_id": 10,
        "raw_score": 18,
        "max_score": 20
    }
    """

    teacher = current_user.teacher_profile

    # ---------------------------------------------------------
    # Get JSON
    # ---------------------------------------------------------

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            'success': False,
            'message': 'Request body must be valid JSON.'
        }), 400

    student_id = data.get('student_id')
    test_id = data.get('test_id')
    raw_score = data.get('raw_score')
    max_score = data.get('max_score')

    # ---------------------------------------------------------
    # Validate IDs
    # ---------------------------------------------------------

    try:
        student_id = int(student_id)
        test_id = int(test_id)
    except (TypeError, ValueError):
        return jsonify({
            'success': False,
            'message': 'student_id and test_id must be valid integers.'
        }), 400

    # ---------------------------------------------------------
    # Validate score values
    # ---------------------------------------------------------

    try:
        raw_score = float(raw_score)
        max_score = float(max_score)
    except (TypeError, ValueError):
        return jsonify({
            'success': False,
            'message': 'raw_score and max_score must be valid numbers.'
        }), 400

    if max_score <= 0:
        return jsonify({
            'success': False,
            'message': 'max_score must be greater than 0.'
        }), 400

    if raw_score < 0 or raw_score > max_score:
        return jsonify({
            'success': False,
            'message': (
                f'raw_score must be between 0 and {max_score}.'
            )
        }), 400

    # ---------------------------------------------------------
    # Verify test belongs to this teacher
    # ---------------------------------------------------------

    test = (
        Test.query
        .join(Class)
        .filter(
            Test.id == test_id,
            Class.teacher_id == teacher.id
        )
        .first()
    )

    if not test:
        return jsonify({
            'success': False,
            'message': 'Test not found or you do not have access to it.'
        }), 404

    # ---------------------------------------------------------
    # Method 2 requires term + component
    # ---------------------------------------------------------

    if not test.term_tag or not test.component_tag:
        return jsonify({
            'success': False,
            'message': (
                'This test must have a term and component assigned.'
            )
        }), 400

    # ---------------------------------------------------------
    # Verify student exists
    # ---------------------------------------------------------

    student = Student.query.get(student_id)

    if not student:
        return jsonify({
            'success': False,
            'message': 'Student not found.'
        }), 404

    # ---------------------------------------------------------
    # Verify student is actively enrolled in this class
    # ---------------------------------------------------------

    enrollment = Enrollment.query.filter_by(
        student_id=student_id,
        class_id=test.class_id,
        status='enrolled'
    ).first()

    if not enrollment:
        return jsonify({
            'success': False,
            'message': (
                'Student is not currently enrolled in this class.'
            )
        }), 400

    # ---------------------------------------------------------
    # Create or update Grade
    # ---------------------------------------------------------

    try:
        grade = Grade.query.filter_by(
            test_id=test_id,
            student_id=student_id
        ).first()

        if not grade:
            grade = Grade(
                test_id=test_id,
                student_id=student_id,
                graded_by=teacher.id
            )

            db.session.add(grade)

        grade.raw_score = raw_score
        grade.max_score = max_score

        grade.calculated_percentage = round(
            (raw_score / max_score) * 100,
            2
        )

        grade.graded_by = teacher.id
        grade.graded_at = datetime.utcnow()

        db.session.commit()

        # -----------------------------------------------------
        # Recalculate term
        # -----------------------------------------------------

        term_result = recalculate_term_grade(
            student_id=student_id,
            class_id=test.class_id,
            term_tag=test.term_tag
        )

        # -----------------------------------------------------
        # Recalculate official final grade when complete
        # -----------------------------------------------------

        _update_enrollment_average(
            student_id,
            test.class_id
        )

        # Refresh enrollment after recalculation
        db.session.refresh(enrollment)

        # -----------------------------------------------------
        # Success
        # -----------------------------------------------------

        return jsonify({
            'success': True,
            'message': 'Grade updated successfully.',

            'score': {
                'grade_id': grade.id,
                'student_id': student_id,
                'test_id': test_id,
                'raw_score': grade.raw_score,
                'max_score': grade.max_score,
                'calculated_percentage': (
                    grade.calculated_percentage
                )
            },

            'term': {
                'term_tag': test.term_tag,
                'component_tag': test.component_tag,
                'grade': term_result.get('grade'),
                'display': term_result.get('display'),
                'percentage': term_result.get('percentage'),
                'missing_components': term_result.get(
                    'missing',
                    []
                )
            },

            'enrollment': {
                'id': enrollment.id,
                'final_grade': enrollment.final_grade,
                'final_grade_display': (
                    get_enrollment_grade_display(
                        enrollment,
                        test.class_
                    )
                )
            }
        }), 200

    except Exception:
        db.session.rollback()

        current_app.logger.exception(
            'Unexpected error while updating grade. '
            'student_id=%s test_id=%s',
            student_id,
            test_id
        )

        return jsonify({
            'success': False,
            'message': (
                'An unexpected error occurred while updating the grade.'
            )
        }), 500

@teacher_bp.route('/grading/create-test', methods=['POST'])
@teacher_required
def create_test():
    """
    API: Create a new Method 2 test/activity.

    Expected JSON:
    {
        "class_id": 1,
        "title": "Quiz 1",
        "term_tag": "Prelims",
        "component_tag": "Quizzes"
    }
    """

    teacher = current_user.teacher_profile

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            'success': False,
            'message': 'Request body must be valid JSON.'
        }), 400

    # ---------------------------------------------------------
    # Get and validate request data
    # ---------------------------------------------------------

    class_id = data.get('class_id')
    title = str(
        data.get('title') or ''
    ).strip()

    term_tag = str(
        data.get('term_tag') or ''
    ).strip()

    component_tag = str(
        data.get('component_tag') or ''
    ).strip()

    try:
        class_id = int(class_id)
    except (TypeError, ValueError):
        return jsonify({
            'success': False,
            'message': 'class_id must be a valid integer.'
        }), 400

    if not title:
        return jsonify({
            'success': False,
            'message': 'Test title is required.'
        }), 400

    if not term_tag:
        return jsonify({
            'success': False,
            'message': 'term_tag is required.'
        }), 400

    if term_tag not in REQUIRED_TERM_TAGS:
        return jsonify({
            'success': False,
            'message': (
                f'Invalid term_tag "{term_tag}". '
                f'Allowed terms are: {", ".join(REQUIRED_TERM_TAGS)}.'
            ),
            'allowed_terms': list(REQUIRED_TERM_TAGS)
        }), 400

    if not component_tag:
        return jsonify({
            'success': False,
            'message': 'component_tag is required.'
        }), 400

    # ---------------------------------------------------------
    # Verify class belongs to teacher
    # ---------------------------------------------------------

    cls = Class.query.filter_by(
        id=class_id,
        teacher_id=teacher.id
    ).first()

    if not cls:
        return jsonify({
            'success': False,
            'message': (
                'Class not found or you do not have access to it.'
            )
        }), 404

    # ---------------------------------------------------------
    # Validate grading formula
    # ---------------------------------------------------------

    formula = cls.get_grading_formula()

    if not formula:
        return jsonify({
            'success': False,
            'message': (
                'This class does not have a grading formula.'
            )
        }), 400

    formula_components = [
        component['name']
        for component in formula.get(
            'components',
            []
        )
    ]

    if component_tag not in formula_components:
        return jsonify({
            'success': False,
            'message': (
                f'Component "{component_tag}" is not part of '
                'this class grading formula.'
            ),
            'available_components': formula_components
        }), 400

    # ---------------------------------------------------------
    # Create test
    # ---------------------------------------------------------

    try:
        new_test = Test(
            class_id=class_id,
            title=title,
            term_tag=term_tag,
            component_tag=component_tag,
            test_date=datetime.utcnow().date()
        )

        db.session.add(new_test)
        db.session.commit()

        enrollments = Enrollment.query.filter_by(
            class_id=class_id,
            status='enrolled'
        ).all()

        for enrollment in enrollments:
            _update_enrollment_average(
                student_id=enrollment.student_id,
                class_id=class_id
            )

        return jsonify({
            'success': True,
            'message': 'Test created successfully.',

            'test': {
                'id': new_test.id,
                'title': new_test.title,
                'class_id': new_test.class_id,
                'term_tag': new_test.term_tag,
                'component_tag': new_test.component_tag,

                'test_date': (
                    new_test.test_date.isoformat()
                    if new_test.test_date
                    else None
                ),

                'created_at': (
                    new_test.created_at.isoformat()
                    if new_test.created_at
                    else None
                )
            }
        }), 201

    except Exception:
        db.session.rollback()

        current_app.logger.exception(
            'Unexpected error while creating test for class %s',
            class_id
        )

        return jsonify({
            'success': False,
            'message': (
                'An unexpected error occurred while creating the test.'
            )
        }), 500


@teacher_bp.route('/grading/delete-test', methods=['POST'])
@teacher_required
def delete_test():
    """
    API: Delete a teacher-owned test only if no grades
    have been entered for it.

    Expected JSON:
    {
        "test_id": 10
    }
    """

    teacher = current_user.teacher_profile

    # ---------------------------------------------------------
    # Get JSON
    # ---------------------------------------------------------

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            'success': False,
            'message': 'Request body must be valid JSON.'
        }), 400

    test_id = data.get('test_id')

    try:
        test_id = int(test_id)
    except (TypeError, ValueError):
        return jsonify({
            'success': False,
            'message': 'test_id must be a valid integer.'
        }), 400

    # ---------------------------------------------------------
    # Verify teacher owns the test
    # ---------------------------------------------------------

    test = (
        Test.query
        .join(Class)
        .filter(
            Test.id == test_id,
            Class.teacher_id == teacher.id
        )
        .first()
    )

    if not test:
        return jsonify({
            'success': False,
            'message': (
                'Test not found or you do not have access to it.'
            )
        }), 404

    # ---------------------------------------------------------
    # Prevent deletion if any grade has been entered
    # ---------------------------------------------------------

    has_grades = (
        Grade.query
        .filter(
            Grade.test_id == test_id,
            Grade.raw_score.isnot(None)
        )
        .first()
        is not None
    )

    if has_grades:
        return jsonify({
            'success': False,
            'message': (
                'This test cannot be deleted because grades '
                'have already been entered for it.'
            )
        }), 409

    # ---------------------------------------------------------
    # Delete test
    # ---------------------------------------------------------

    test_title = test.title
    class_id = test.class_id

    try:
        db.session.delete(test)
        db.session.commit()

        enrollments = Enrollment.query.filter_by(
            class_id=class_id,
            status='enrolled'
        ).all()

        for enrollment in enrollments:
            _update_enrollment_average(
                student_id=enrollment.student_id,
                class_id=class_id
            )

        return jsonify({
            'success': True,
            'message': f'Test "{test_title}" deleted successfully.',
            'deleted_test': {
                'id': test_id,
                'class_id': class_id,
                'title': test_title
            }
        }), 200

    except Exception:
        db.session.rollback()

        current_app.logger.exception(
            'Unexpected error while deleting test %s',
            test_id
        )

        return jsonify({
            'success': False,
            'message': (
                'An unexpected error occurred while deleting the test.'
            )
        }), 500


@teacher_bp.route('/analytics', methods=['GET'])
@teacher_required
def analytics():
    """
    API: Return teacher analytics for an academic period.

    Optional query parameters:
        ?year=2026-2027
        ?semester=1st Semester

    Defaults to the current academic period.
    """

    teacher = current_user.teacher_profile

    current_school_year = Config.get_current_school_year()
    current_semester = Config.get_current_semester()

    selected_year = request.args.get(
        'year',
        current_school_year
    )

    selected_semester = request.args.get(
        'semester',
        current_semester
    )

    # ---------------------------------------------------------
    # Teacher classes in selected period
    # ---------------------------------------------------------

    classes = Class.query.filter_by(
        teacher_id=teacher.id,
        school_year=selected_year,
        semester=selected_semester
    ).all()

    # ---------------------------------------------------------
    # Total distinct enrolled students
    # ---------------------------------------------------------

    total_students = (
        db.session.query(
            func.count(
                func.distinct(Enrollment.student_id)
            )
        )
        .join(
            Class,
            Enrollment.class_id == Class.id
        )
        .filter(
            Class.teacher_id == teacher.id,
            Class.school_year == selected_year,
            Class.semester == selected_semester,
            Enrollment.status == 'enrolled'
        )
        .scalar()
        or 0
    )

    # ---------------------------------------------------------
    # Enrollments with completed final grades
    # ---------------------------------------------------------

    graded_enrollments = (
        Enrollment.query
        .join(
            Class,
            Enrollment.class_id == Class.id
        )
        .filter(
            Class.teacher_id == teacher.id,
            Class.school_year == selected_year,
            Class.semester == selected_semester,
            Enrollment.status == 'enrolled',
            Enrollment.final_grade.isnot(None)
        )
        .all()
    )

    graded_students = len(
        graded_enrollments
    )

    # ---------------------------------------------------------
    # Average final grade
    # ---------------------------------------------------------

    if graded_enrollments:

        average_final_grade = round(
            sum(
                enrollment.final_grade
                for enrollment in graded_enrollments
            )
            / graded_students,
            2
        )

    else:
        average_final_grade = None

    # ---------------------------------------------------------
    # Passing rate
    #
    # Based on completed Enrollment.final_grade only.
    # Existing system uses <= 3.0 as passing.
    # ---------------------------------------------------------

    passed_students = sum(
        1
        for enrollment in graded_enrollments
        if enrollment.final_grade <= PASSING_GRADE
    )

    passing_rate = (
        round(
            (
                passed_students
                / graded_students
            ) * 100,
            2
        )
        if graded_students > 0
        else 0
    )

    # ---------------------------------------------------------
    # Grade distribution
    # ---------------------------------------------------------

    grade_distribution = {
        '1.00-1.74': 0,
        '1.75-2.24': 0,
        '2.25-2.74': 0,
        '2.75-3.00': 0,
        'Above 3.00': 0
    }

    for enrollment in graded_enrollments:

        grade = enrollment.final_grade

        if 1.00 <= grade < 1.75:
            grade_distribution[
                '1.00-1.74'
            ] += 1

        elif 1.75 <= grade < 2.25:
            grade_distribution[
                '1.75-2.24'
            ] += 1

        elif 2.25 <= grade < 2.75:
            grade_distribution[
                '2.25-2.74'
            ] += 1

        elif 2.75 <= grade <= 3.00:
            grade_distribution[
                '2.75-3.00'
            ] += 1

        elif grade > 3.00:
            grade_distribution[
                'Above 3.00'
            ] += 1

    # ---------------------------------------------------------
    # Class performance
    # ---------------------------------------------------------

    class_performance = []

    for cls in classes:

        enrollments = (
            Enrollment.query
            .filter_by(
                class_id=cls.id,
                status='enrolled'
            )
            .all()
        )

        completed_class_grades = [
            enrollment.final_grade
            for enrollment in enrollments
            if enrollment.final_grade is not None
        ]

        if completed_class_grades:

            class_average = round(
                sum(completed_class_grades)
                / len(completed_class_grades),
                2
            )

        else:
            class_average = None

        class_performance.append({
            'class_id': cls.id,
            'subject_name': cls.effective_subject_name,
            'subject_code': cls.effective_subject_code,
            'section': cls.section,
            'student_count': len(enrollments),
            'graded_students': len(
                completed_class_grades
            ),
            'average_final_grade': class_average
        })

    # ---------------------------------------------------------
    # Test / grading completion statistics
    # ---------------------------------------------------------

    total_tests = (
        Test.query
        .join(
            Class,
            Test.class_id == Class.id
        )
        .filter(
            Class.teacher_id == teacher.id,
            Class.school_year == selected_year,
            Class.semester == selected_semester
        )
        .count()
    )

    total_gradable = 0
    graded_count = 0

    for cls in classes:

        enrollment_count = (
            Enrollment.query
            .filter_by(
                class_id=cls.id,
                status='enrolled'
            )
            .count()
        )

        test_count = Test.query.filter_by(
            class_id=cls.id
        ).count()

        total_gradable += (
            enrollment_count
            * test_count
        )

        graded_count += (
            Grade.query
            .join(Test)
            .filter(
                Test.class_id == cls.id,
                Grade.raw_score.isnot(None)
            )
            .count()
        )

    completion_rate = (
        round(
            (
                graded_count
                / total_gradable
            ) * 100,
            2
        )
        if total_gradable > 0
        else 0
    )

    ungraded_count = max(
        total_gradable - graded_count,
        0
    )

    # ---------------------------------------------------------
    # Units
    # ---------------------------------------------------------

    total_units = sum(
        cls.effective_units
        for cls in classes
    )

    # ---------------------------------------------------------
    # Response
    # ---------------------------------------------------------

    return jsonify({
        'success': True,

        'academic_period': {
            'school_year': selected_year,
            'semester': selected_semester
        },

        'summary': {
            'total_classes': len(classes),
            'total_students': total_students,
            'total_tests': total_tests,
            'total_units': total_units,

            'graded_students': graded_students,
            'passed_students': passed_students,

            'average_final_grade': (
                average_final_grade
            ),

            'passing_rate': passing_rate,

            'average_tests_per_class': (
                round(
                    total_tests / len(classes),
                    1
                )
                if classes
                else 0
            )
        },

        'grading_progress': {
            'graded_scores': graded_count,
            'total_gradable_scores': total_gradable,
            'ungraded_scores': ungraded_count,
            'completion_rate': completion_rate
        },

        'grade_distribution': (
            grade_distribution
        ),

        'class_performance': (
            class_performance
        )
    }), 200


@teacher_bp.route('/profile', methods=['GET'])
@teacher_required
def profile():
    """
    API: Return the logged-in teacher's profile,
    teaching statistics, and recent grading activity.
    """

    teacher = current_user.teacher_profile

    current_school_year = Config.get_current_school_year()
    current_semester = Config.get_current_semester()

    # ---------------------------------------------------------
    # Teaching statistics
    # ---------------------------------------------------------

    total_classes = Class.query.filter_by(
        teacher_id=teacher.id
    ).count()

    current_students = (
        db.session.query(
            func.count(
                func.distinct(Enrollment.student_id)
            )
        )
        .join(
            Class,
            Enrollment.class_id == Class.id
        )
        .filter(
            Class.teacher_id == teacher.id,
            Class.school_year == current_school_year,
            Class.semester == current_semester,
            Enrollment.status == 'enrolled'
        )
        .scalar()
        or 0
    )

    total_grades_given = (
        Grade.query
        .join(Test)
        .join(
            Class,
            Test.class_id == Class.id
        )
        .filter(
            Class.teacher_id == teacher.id,
            Grade.raw_score.isnot(None)
        )
        .count()
    )

    # ---------------------------------------------------------
    # Years teaching
    #
    # Existing logic estimates this from account creation date.
    # ---------------------------------------------------------

    if teacher.created_at:
        years_teaching = max(
            1,
            (
                datetime.utcnow()
                - teacher.created_at
            ).days // 365
        )
    else:
        years_teaching = 1

    # ---------------------------------------------------------
    # Recent grading activity
    # ---------------------------------------------------------

    recent_grades = (
        Grade.query
        .join(Test)
        .join(
            Class,
            Test.class_id == Class.id
        )
        .filter(
            Class.teacher_id == teacher.id,
            Grade.graded_at.isnot(None)
        )
        .order_by(
            Grade.graded_at.desc()
        )
        .limit(10)
        .all()
    )

    recent_activities = []

    for grade in recent_grades:

        test = grade.test
        class_obj = test.class_
        student = grade.student

        time_diff = (
            datetime.utcnow()
            - grade.graded_at
        )

        if time_diff < timedelta(minutes=60):

            minutes = max(
                0,
                int(
                    time_diff.total_seconds()
                    // 60
                )
            )

            time_ago = f"{minutes} minutes ago"

        elif time_diff < timedelta(hours=24):

            hours = max(
                0,
                int(
                    time_diff.total_seconds()
                    // 3600
                )
            )

            time_ago = f"{hours} hours ago"

        else:

            time_ago = (
                f"{time_diff.days} days ago"
            )

        recent_activities.append({
            'grade_id': grade.id,

            'student': {
                'id': student.id,
                'student_number': (
                    student.student_number
                ),
                'first_name': (
                    student.first_name
                ),
                'last_name': (
                    student.last_name
                )
            },

            'test': {
                'id': test.id,
                'title': test.title,
                'term_tag': test.term_tag,
                'component_tag': (
                    test.component_tag
                )
            },

            'class': {
                'id': class_obj.id,
                'subject_name': (
                    class_obj.effective_subject_name
                ),
                'subject_code': (
                    class_obj.effective_subject_code
                ),
                'section': class_obj.section
            },

            'graded_at': (
                grade.graded_at.isoformat()
            ),

            'time_ago': time_ago
        })

    # ---------------------------------------------------------
    # Response
    # ---------------------------------------------------------

    return jsonify({
        'success': True,

        'teacher': {
            'id': teacher.id,
            'employee_number': (
                teacher.employee_number
            ),
            'first_name': teacher.first_name,
            'last_name': teacher.last_name,
            'department': teacher.department,

            'specialization': (
                teacher.specialization
                if hasattr(
                    teacher,
                    'specialization'
                )
                else None
            ),

            'created_at': (
                teacher.created_at.isoformat()
                if teacher.created_at
                else None
            )
        },

        'academic_period': {
            'school_year': (
                current_school_year
            ),
            'semester': (
                current_semester
            )
        },

        'statistics': {
            'total_classes': total_classes,
            'current_students': (
                current_students
            ),
            'total_grades_given': (
                total_grades_given
            ),
            'years_teaching': (
                years_teaching
            )
        },

        'recent_activities': (
            recent_activities
        )
    }), 200


@teacher_bp.route('/change-password', methods=['POST'])
@teacher_required
def change_password():
    """
    API: Change the logged-in teacher's password.

    Expected JSON:
    {
        "current_password": "oldPassword",
        "new_password": "newPassword123",
        "confirm_password": "newPassword123"
    }
    """

    data = request.get_json(
        silent=True
    )

    if not isinstance(data, dict):
        return jsonify({
            'success': False,
            'message': (
                'Request body must be valid JSON.'
            )
        }), 400

    current_password = str(
        data.get('current_password')
        or ''
    ).strip()

    new_password = str(
        data.get('new_password')
        or ''
    ).strip()

    confirm_password = str(
        data.get('confirm_password')
        or ''
    ).strip()

    # ---------------------------------------------------------
    # Required fields
    # ---------------------------------------------------------

    if not all([
        current_password,
        new_password,
        confirm_password
    ]):
        return jsonify({
            'success': False,
            'message': (
                'All password fields are required.'
            )
        }), 400

    # ---------------------------------------------------------
    # Confirm passwords match
    # ---------------------------------------------------------

    if new_password != confirm_password:
        return jsonify({
            'success': False,
            'message': (
                'New passwords do not match.'
            )
        }), 400

    # ---------------------------------------------------------
    # Minimum password length
    # ---------------------------------------------------------

    if len(new_password) < 6:
        return jsonify({
            'success': False,
            'message': (
                'Password must be at least '
                '6 characters long.'
            )
        }), 400

    # ---------------------------------------------------------
    # Verify current password
    # ---------------------------------------------------------

    if not bcrypt.check_password_hash(
        current_user.password,
        current_password
    ):
        return jsonify({
            'success': False,
            'message': (
                'Current password is incorrect.'
            )
        }), 400

    # ---------------------------------------------------------
    # Prevent reusing current password
    # ---------------------------------------------------------

    if bcrypt.check_password_hash(
        current_user.password,
        new_password
    ):
        return jsonify({
            'success': False,
            'message': (
                'New password must be different '
                'from the current password.'
            )
        }), 400

    # ---------------------------------------------------------
    # Update password
    # ---------------------------------------------------------

    try:

        current_user.password = (
            bcrypt.generate_password_hash(
                new_password
            ).decode('utf-8')
        )

        db.session.commit()

        return jsonify({
            'success': True,
            'message': (
                'Password updated successfully.'
            )
        }), 200

    except Exception:

        db.session.rollback()

        current_app.logger.exception(
            'Unexpected error while changing '
            'password for teacher user %s',
            current_user.id
        )

        return jsonify({
            'success': False,
            'message': (
                'An unexpected error occurred '
                'while updating the password.'
            )
        }), 500


@teacher_bp.route('/grading/components', methods=['GET'])
@teacher_required
def get_components():
    """
    API: Return the current score for one student/test.

    Query parameters:
        ?student_id=1
        ?test_id=10
    """

    teacher = current_user.teacher_profile

    student_id = request.args.get(
        'student_id',
        type=int
    )

    test_id = request.args.get(
        'test_id',
        type=int
    )

    if student_id is None or test_id is None:
        return jsonify({
            'success': False,
            'message': (
                'student_id and test_id are required.'
            )
        }), 400

    # ---------------------------------------------------------
    # Verify teacher owns the test
    # ---------------------------------------------------------

    test = (
        Test.query
        .join(Class)
        .filter(
            Test.id == test_id,
            Class.teacher_id == teacher.id
        )
        .first()
    )

    if not test:
        return jsonify({
            'success': False,
            'message': (
                'Test not found or you do not have access to it.'
            )
        }), 404

    # ---------------------------------------------------------
    # Verify student exists
    # ---------------------------------------------------------

    student = Student.query.get(student_id)

    if not student:
        return jsonify({
            'success': False,
            'message': 'Student not found.'
        }), 404

    # ---------------------------------------------------------
    # Verify student is enrolled
    # ---------------------------------------------------------

    enrollment = Enrollment.query.filter_by(
        student_id=student_id,
        class_id=test.class_id,
        status='enrolled'
    ).first()

    if not enrollment:
        return jsonify({
            'success': False,
            'message': (
                'Student is not currently enrolled in this class.'
            )
        }), 400

    # ---------------------------------------------------------
    # Get score
    # ---------------------------------------------------------

    grade = Grade.query.filter_by(
        test_id=test_id,
        student_id=student_id
    ).first()

    return jsonify({
        'success': True,

        'score': {
            'raw_score': (
                grade.raw_score
                if grade
                else None
            ),
            'max_score': (
                grade.max_score
                if grade
                else None
            ),
            'calculated_percentage': (
                grade.calculated_percentage
                if grade
                else None
            )
        },

        'test': {
            'id': test.id,
            'title': test.title,
            'term_tag': test.term_tag,
            'component_tag': test.component_tag
        },

        'student': {
            'id': student.id,
            'student_number': student.student_number,
            'first_name': student.first_name,
            'last_name': student.last_name
        }
    }), 200

@teacher_bp.route('/grading/update-components', methods=['POST'])
@teacher_required
def update_components():
    """
    Compatibility endpoint.

    This route temporarily forwards requests to the canonical
    /grading/update handler while the frontend is being migrated.

    New React code should use:
        POST /teacher/grading/update
    """

    return update_grade()


@teacher_bp.route('/grading/student-average', methods=['GET'])
@teacher_required
def get_student_average():
    """
    API: Return the student's running average based only on
    completed grading terms.

    Query parameters:
        ?student_id=1
        ?class_id=10

    This is NOT the same as Enrollment.final_grade.

    Running average:
        average of completed term PH grades only

    Enrollment.final_grade:
        official semester grade once all required terms are complete
    """

    teacher = current_user.teacher_profile

    student_id = request.args.get(
        'student_id',
        type=int
    )

    class_id = request.args.get(
        'class_id',
        type=int
    )

    # ---------------------------------------------------------
    # Validate parameters
    # ---------------------------------------------------------

    if student_id is None or class_id is None:
        return jsonify({
            'success': False,
            'message': (
                'student_id and class_id are required.'
            )
        }), 400

    # ---------------------------------------------------------
    # Verify teacher owns the class
    # ---------------------------------------------------------

    cls = Class.query.filter_by(
        id=class_id,
        teacher_id=teacher.id
    ).first()

    if not cls:
        return jsonify({
            'success': False,
            'message': (
                'Class not found or you do not have access to it.'
            )
        }), 404

    # ---------------------------------------------------------
    # Verify student exists
    # ---------------------------------------------------------

    student = Student.query.get(student_id)

    if not student:
        return jsonify({
            'success': False,
            'message': 'Student not found.'
        }), 404

    # ---------------------------------------------------------
    # Verify active enrollment
    # ---------------------------------------------------------

    enrollment = Enrollment.query.filter_by(
        student_id=student_id,
        class_id=class_id,
        status='enrolled'
    ).first()

    if not enrollment:
        return jsonify({
            'success': False,
            'message': (
                'Student is not currently enrolled in this class.'
            )
        }), 400

    # ---------------------------------------------------------
    # Get grading terms
    # ---------------------------------------------------------

    term_tags = (
        db.session.query(Test.term_tag)
        .filter(
            Test.class_id == class_id,
            Test.term_tag.isnot(None)
        )
        .distinct()
        .all()
    )

    term_tags = [
        row[0]
        for row in term_tags
        if row[0]
    ]

    # ---------------------------------------------------------
    # Calculate each term
    # ---------------------------------------------------------

    term_grades = {}
    completed_ph_grades = []

    for term in term_tags:

        result = recalculate_term_grade(
            student_id=student_id,
            class_id=class_id,
            term_tag=term
        )

        term_grades[term] = {
            'grade': result.get('grade'),
            'display': result.get('display'),
            'percentage': result.get('percentage'),
            'missing_components': result.get(
                'missing',
                []
            )
        }

        if result.get('grade') is not None:
            completed_ph_grades.append(
                result['grade']
            )

    # ---------------------------------------------------------
    # Running average
    # ---------------------------------------------------------

    if completed_ph_grades:

        running_average = round(
            sum(completed_ph_grades)
            / len(completed_ph_grades),
            2
        )

        running_average_display = (
            f"{running_average:.2f}"
        )

    else:
        running_average = None

        any_started_term = any(
            term_data.get('display') == 'INC'
            for term_data in term_grades.values()
        )

        running_average_display = (
            'INC'
            if any_started_term
            else '—'
        )

    # ---------------------------------------------------------
    # Response
    # ---------------------------------------------------------

    return jsonify({
        'success': True,

        'student': {
            'id': student.id,
            'student_number': student.student_number,
            'first_name': student.first_name,
            'last_name': student.last_name
        },

        'class': {
            'id': cls.id,
            'subject_name': cls.effective_subject_name,
            'subject_code': cls.effective_subject_code,
            'section': cls.section
        },

        'running_average': running_average,
        'running_average_display': (
            running_average_display
        ),

        'official_final_grade': (
            enrollment.final_grade
        ),

        'official_final_grade_display': (
            get_enrollment_grade_display(
                enrollment,
                cls
            )
        ),

        'term_grades': term_grades
    }), 200


@teacher_bp.route('/grading/export')
@teacher_required
def export_grades():
    """
    Export grades for a class as Excel (.xlsx) or CSV (.csv).
 
    Query params:
        class_id  — required
        format    — 'xlsx' or 'csv' (default: xlsx)
    """
    import io
    import csv
    from flask import send_file, Response
 
    teacher = current_user.teacher_profile

    class_id = request.args.get(
        'class_id',
        type=int
    )

    fmt = request.args.get(
        'format',
        'xlsx'
    ).lower()

    if class_id is None:
        return jsonify({
            'success': False,
            'message': 'class_id is required.'
        }), 400

    if fmt not in {'xlsx', 'csv'}:
        return jsonify({
            'success': False,
            'message': (
                'format must be either "xlsx" or "csv".'
            )
        }), 400

    cls = Class.query.filter_by(
        id=class_id,
        teacher_id=teacher.id
    ).first()

    if not cls:
        return jsonify({
            'success': False,
            'message': (
                'Class not found or you do not have access to it.'
            )
        }), 404
 
    # ── Gather data ──────────────────────────────────────────────────────────
 
    enrollments = (
        Enrollment.query
        .filter_by(class_id=class_id, status='enrolled')
        .join(Student)
        .order_by(Student.last_name, Student.first_name)
        .all()
    )
 
    tests = (
        Test.query
        .filter_by(class_id=class_id)
        .order_by(Test.term_tag, Test.component_tag, Test.test_date, Test.created_at)
        .all()
    )
 
    # Ordered distinct term tags
    seen_terms = {}
    for t in tests:
        if t.term_tag and t.term_tag not in seen_terms:
            seen_terms[t.term_tag] = True
    term_tags = list(seen_terms.keys())
 
    tests_by_term = {term: [t for t in tests if t.term_tag == term] for term in term_tags}
 
    # Class info
    subject_name = cls.effective_subject_name
    subject_code = cls.effective_subject_code
    section      = cls.section or ''
    school_year  = cls.school_year
    semester     = cls.semester
 
    safe_name = f"{subject_code}_{section}_{school_year}_{semester}".replace(' ', '_').replace('/', '-')
 
    # ── Build rows ───────────────────────────────────────────────────────────
 
    # Header row 1: info labels
    # Header row 2: column names
    # Data rows: one per student
 
    col_headers = ['Student Name', 'Student ID']
 
    if term_tags:
        for term in term_tags:
            for t in tests_by_term[term]:
                col_headers.append(f'{term} | {t.title}')
            col_headers.append(f'{term} Grade')
    else:
        for t in tests:
            col_headers.append(t.title)
 
    col_headers.append('Overall Grade')
 
    data_rows = []
    for enrollment in enrollments:
        student = enrollment.student
 
        row = [student.get_full_name(), student.student_number]
 
        if term_tags:
            for term in term_tags:
                for t in tests_by_term[term]:
                    g = Grade.query.filter_by(
                        test_id=t.id,
                        student_id=student.id
                    ).first()

                    if g and g.raw_score is not None:
                        max_s = (
                            g.max_score
                            if g.max_score is not None
                            else '?'
                        )
                        row.append(
                            f"{g.raw_score}/{max_s}"
                        )
                    else:
                        row.append('')

                result = recalculate_term_grade(
                    student_id=student.id,
                    class_id=class_id,
                    term_tag=term
                )

                row.append(
                    result.get('display', '—')
                )
 
        # Overall
        if enrollment.final_grade is not None:
            row.append(f"{enrollment.final_grade:.2f}")
        else:
            row.append('INC' if any(
                recalculate_term_grade(student.id, class_id, term).get('display') == 'INC'
                for term in term_tags
            ) else '—')
 
        data_rows.append(row)
 
    # ── CSV export ───────────────────────────────────────────────────────────
 
    if fmt == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
 
        # Class info header block
        writer.writerow(['Subject', subject_name])
        writer.writerow(['Code', subject_code])
        writer.writerow(['Section', section])
        writer.writerow(['School Year', school_year])
        writer.writerow(['Semester', semester])
        writer.writerow([])  # blank separator
 
        writer.writerow(col_headers)
        for row in data_rows:
            writer.writerow(row)
 
        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={
                'Content-Disposition': f'attachment; filename=grades_{safe_name}.csv'
            }
        )
 
    # ── Excel export ─────────────────────────────────────────────────────────
 
    from openpyxl import Workbook
    from openpyxl.styles import (
        Font, PatternFill, Alignment, Border, Side
    )
    from openpyxl.utils import get_column_letter
 
    wb = Workbook()
    ws = wb.active
    ws.title = 'Grades'
 
    # Styles
    header_font      = Font(name='Arial', bold=True, color='FFFFFF', size=11)
    info_font        = Font(name='Arial', bold=True, size=10)
    label_font       = Font(name='Arial', bold=True, size=9)
    data_font        = Font(name='Arial', size=9)
    header_fill      = PatternFill('solid', start_color='1F3864')   # dark navy
    term_fill        = PatternFill('solid', start_color='2E4D7B')   # medium navy
    term_grade_fill  = PatternFill('solid', start_color='3A5A8C')   # lighter navy
    col_header_fill  = PatternFill('solid', start_color='4472C4')   # blue
    overall_fill     = PatternFill('solid', start_color='375623')   # dark green
    alt_row_fill     = PatternFill('solid', start_color='EBF3FF')   # light blue tint
    center           = Alignment(horizontal='center', vertical='center')
    left             = Alignment(horizontal='left',   vertical='center')
    thin             = Side(style='thin', color='BFBFBF')
    border           = Border(left=thin, right=thin, top=thin, bottom=thin)
 
    # ── Row 1–5: Class info block ─────────────────────────────────────────
    info_pairs = [
        ('Subject',     subject_name),
        ('Code',        subject_code),
        ('Section',     section),
        ('School Year', school_year),
        ('Semester',    semester),
    ]
    for i, (label, value) in enumerate(info_pairs, start=1):
        ws.cell(row=i, column=1, value=label).font = info_font
        cell = ws.cell(row=i, column=2, value=value)
        cell.font = Font(name='Arial', size=10)
    
    info_rows = len(info_pairs)
    blank_row  = info_rows + 1
    ws.append([])  # blank separator
 
    # ── Term group header row (only if tagged tests exist) ────────────────
    current_row = blank_row + 1
    col_cursor  = 3  # columns 1=Name, 2=ID, then activities
 
    if term_tags:
        # Row: merged term label spanning activity cols + 1 grade col
        for r in range(1, current_row):
            ws.cell(row=r, column=1).fill = PatternFill('solid', start_color='F2F2F2')
 
        # Name + ID headers (merged across group header row)
        name_cell = ws.cell(row=current_row, column=1, value='Student Name')
        name_cell.font  = header_font
        name_cell.fill  = header_fill
        name_cell.alignment = center
        name_cell.border = border
 
        id_cell = ws.cell(row=current_row, column=2, value='Student ID')
        id_cell.font  = header_font
        id_cell.fill  = header_fill
        id_cell.alignment = center
        id_cell.border = border
 
        for term in term_tags:
            term_tests    = tests_by_term[term]
            span          = len(term_tests) + 1   # activities + 1 grade col
            start_col     = col_cursor
            end_col       = col_cursor + span - 1
 
            # Merge term label
            if span > 1:
                ws.merge_cells(
                    start_row=current_row, start_column=start_col,
                    end_row=current_row,   end_column=end_col
                )
            cell = ws.cell(row=current_row, column=start_col, value=term)
            cell.font      = Font(name='Arial', bold=True, color='FFFFFF', size=10)
            cell.fill      = term_fill
            cell.alignment = center
            cell.border    = border
 
            col_cursor += span
 
        # Overall column header (group row)
        ov_cell = ws.cell(row=current_row, column=col_cursor, value='Overall')
        ov_cell.font      = Font(name='Arial', bold=True, color='FFFFFF', size=10)
        ov_cell.fill      = overall_fill
        ov_cell.alignment = center
        ov_cell.border    = border
 
        current_row += 1
 
    # ── Activity-level column headers ────────────────────────────────────
    ws.cell(row=current_row, column=1, value='Student Name').font  = label_font
    ws.cell(row=current_row, column=1).fill      = col_header_fill
    ws.cell(row=current_row, column=1).alignment = left
    ws.cell(row=current_row, column=1).font      = Font(name='Arial', bold=True, color='FFFFFF', size=9)
    ws.cell(row=current_row, column=1).border    = border
 
    ws.cell(row=current_row, column=2, value='Student ID').fill      = col_header_fill
    ws.cell(row=current_row, column=2).alignment = center
    ws.cell(row=current_row, column=2).font      = Font(name='Arial', bold=True, color='FFFFFF', size=9)
    ws.cell(row=current_row, column=2).border    = border
 
    col_cursor = 3
    if term_tags:
        for term in term_tags:
            for t in tests_by_term[term]:
                cell = ws.cell(row=current_row, column=col_cursor, value=t.title)
                cell.font      = Font(name='Arial', bold=True, color='FFFFFF', size=8)
                cell.fill      = col_header_fill
                cell.alignment = center
                cell.border    = border
                col_cursor += 1
            # Term grade column header
            cell = ws.cell(row=current_row, column=col_cursor, value='Grade')
            cell.font      = Font(name='Arial', bold=True, color='FFFFFF', size=9)
            cell.fill      = term_grade_fill
            cell.alignment = center
            cell.border    = border
            col_cursor += 1
    else:
        for t in tests:
            cell = ws.cell(row=current_row, column=col_cursor, value=t.title)
            cell.font      = Font(name='Arial', bold=True, color='FFFFFF', size=9)
            cell.fill      = col_header_fill
            cell.alignment = center
            cell.border    = border
            col_cursor += 1
 
    # Overall
    cell = ws.cell(row=current_row, column=col_cursor, value='Overall Grade')
    cell.font      = Font(name='Arial', bold=True, color='FFFFFF', size=9)
    cell.fill      = overall_fill
    cell.alignment = center
    cell.border    = border
 
    current_row += 1
    total_cols = col_cursor
 
    # ── Data rows ─────────────────────────────────────────────────────────
    for idx, row_values in enumerate(data_rows):
        is_alt = (idx % 2 == 1)
        for col_i, value in enumerate(row_values, start=1):
            cell = ws.cell(row=current_row, column=col_i, value=value)
            cell.font   = data_font
            cell.border = border
            if col_i == 1:
                cell.alignment = left
            else:
                cell.alignment = center
            if is_alt:
                cell.fill = alt_row_fill
            # Highlight INC in orange
            if value == 'INC':
                cell.font = Font(name='Arial', size=9, bold=True, color='D29922')
        current_row += 1
 
    # ── Column widths ─────────────────────────────────────────────────────
    ws.column_dimensions['A'].width = 28   # Student Name
    ws.column_dimensions['B'].width = 16   # Student ID
    for col_i in range(3, total_cols + 1):
        ws.column_dimensions[get_column_letter(col_i)].width = 14
 
    # ── Row heights ───────────────────────────────────────────────────────
    for r in range(1, current_row):
        ws.row_dimensions[r].height = 18
 
    # ── Freeze panes: freeze after name + ID columns ──────────────────────
    freeze_row = blank_row + 2 if term_tags else blank_row + 1
    ws.freeze_panes = ws.cell(row=freeze_row + 1, column=3)
 
    # ── Stream to client ──────────────────────────────────────────────────
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
 
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'grades_{safe_name}.xlsx'
    )

