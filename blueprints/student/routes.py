"""
blueprints/student/routes.py - Student Blueprint
Handles student-specific routes: dashboard, grades, classes, profile.
"""
from datetime import datetime as dt
from functools import wraps

from flask import Blueprint, jsonify, request
from flask_login import current_user
from models import Student, Class, Enrollment, Grade, Test, TestPaperImage
from extensions import db, bcrypt
from config import Config
from helpers import student_helpers

# Initialize the blueprint for student-related routes
student_bp = Blueprint('student', __name__)


# Decorator to check if current user is a student
def student_required(f):
    """
    Ensure the request belongs to an authenticated student.
    """
    from functools import wraps

    @wraps(f)
    def decorated_function(*args, **kwargs):

        if not current_user.is_authenticated:
            return jsonify({
                'success': False,
                'message': 'Authentication required.'
            }), 401

        if current_user.role != 'student':
            return jsonify({
                'success': False,
                'message': 'Access denied. Students only.'
            }), 403

        return f(*args, **kwargs)

    return decorated_function


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@student_bp.route('/dashboard')
@student_required
def dashboard():
    """
    Return student dashboard data.
    """
    student = current_user.student_profile

    # get current school year and semester
    (
        selected_year,
        selected_semester,
        current_school_year,
        current_semester
    ) = student_helpers.get_selected_period()


    # list of actual enrolled years plus a buffer for the current year 
    available_years = student_helpers.get_available_years(student)

    # --- Enrolled classes of student for current semester/year ---
    enrollments = Enrollment.query.filter_by(
        student_id=student.id
    ).join(Class).filter(
        Class.school_year == selected_year,
        Class.semester == selected_semester
    ).all()

    enrolled_class_objects = [
        e.class_
        for e in enrollments
    ]

    enrolled_classes = [
        student_helpers.class_to_dict(cls)
        for cls in enrolled_class_objects
    ]

    # Enrollment Data {class_id -> enrollment data}
    enrollment_map = { e.class_id: student_helpers.enrollment_to_dict(e) for e in enrollments }

    # Find the five most recently graded tests belonging to this student.
    # List of SQLAlchemy object<Grades>
    recent_grades = (
        Grade.query
        .filter_by(student_id=student.id)
        .filter(Grade.raw_score.isnot(None))
        .join(Test)
        .join(Class)
        .order_by(Grade.graded_at.desc())
        .limit(5)
        .all()
    )

    # List of grades
    recent_grades_data = []

    for grade in recent_grades:
        recent_grades_data.append({
            'id': grade.id,
            'test_id': grade.test_id,
            'raw_score': grade.raw_score,
            'max_score': grade.max_score,
            'calculated_percentage': grade.calculated_percentage,
            'graded_at': (
                grade.graded_at.isoformat()
                if grade.graded_at
                else None
            )
        })

    # --- Semester GPA (both methods, for selected semester) ---
    semester_gpa_weighted = student.get_semester_gpa(selected_year, selected_semester, 'weighted')

    semester_gpa_simple = student.get_semester_gpa(selected_year, selected_semester, 'simple')

    cumulative_gpa = student.get_cumulative_gpa('weighted')

    # --- Quick Stats ---
    # Units enrolled this semester
    total_units = sum(
        cls.effective_units
        for cls in enrolled_class_objects
    )

    # Graded count: subjects with a final_grade in enrollment vs total enrolled
    graded_count = sum(1 for e in enrollments if e.final_grade is not None)
    total_count = len(enrollments)

    academic_info = student_helpers.get_academic_standing(cumulative_gpa)

    # ---------------------------------------------------------
    # Response
    # ---------------------------------------------------------

    return jsonify({
        'student': student_helpers.student_to_dict(student),

        'period': {
            'selected_year': selected_year,
            'selected_semester': selected_semester,
            'current_school_year': current_school_year,
            'current_semester': current_semester
        },

        'available_years': available_years,

        'enrolled_classes': enrolled_classes,

        'enrollment_map': enrollment_map,

        'recent_grades': recent_grades_data,

        'gpa': {
            'semester_weighted': semester_gpa_weighted,
            'semester_simple': semester_gpa_simple,
            'cumulative_weighted': cumulative_gpa
        },

        'stats': {
            'total_units': total_units,
            'graded_count': graded_count,
            'total_count': total_count
        },

        'academic_standing': academic_info
    }), 200




@student_bp.route('/profile')
@student_required
def profile():
    """
    Return student profile information.
    """
    # student data
    student = current_user.student_profile
    
    # Calculate some profile stats
    current_school_year = Config.get_current_school_year()
    current_semester = Config.get_current_semester()
    
    # Get cumulative GPA
    cumulative_gpa = student.get_cumulative_gpa('weighted')
    
    # Check academic standing based on GPA
    academic_info = student_helpers.get_academic_standing(cumulative_gpa)
    
    # Get total completed units (all enrollments with grades that are passing)
    completed_enrollments = Enrollment.query.filter_by(
        student_id=student.id,
        status='completed'
    ).all()
    total_completed_units = sum(e.class_.effective_units for e in completed_enrollments if e.final_grade and e.final_grade <= 3.0)
    
    # Get current enrollments
    current_enrollments = Enrollment.query.filter_by(
        student_id=student.id,
        status='enrolled'
    ).join(Class).filter(
        Class.school_year == current_school_year,
        Class.semester == current_semester
    ).count()
    
    # Determine student type (Regular vs Irregular)
    classification = student.enrollment_classification

    student_type = {
        'Regular': 'Regular Student',
        'Irregular': 'Irregular Student',
        'Not Yet Verified': 'Not Yet Verified'
    }.get(classification, 'Not Yet Verified')
    
    # Check if Dean's Lister
    is_deans_lister = cumulative_gpa and cumulative_gpa <= 1.75
    
    return jsonify({
        "student": student_helpers.student_to_dict(student),

        'gpa': {
            'cumulative_weighted': cumulative_gpa
        },

        'academic_standing': academic_info,

        'stats': {
            'total_completed_units': total_completed_units,
            'current_enrollments': current_enrollments
        },

        'student_type': student_type,

        'is_deans_lister': is_deans_lister,

        'current_period': {
            'school_year': current_school_year,
            'semester': current_semester
        }
    }), 200


@student_bp.route('/classes')
@student_required
def my_classes():
    """
    Return student's classes for the selected school year and semester.
    """
    # Student Data
    student = current_user.student_profile

    # current school year and semester
    (
        selected_year,
        selected_semester,
        current_school_year,
        current_semester
    ) = student_helpers.get_selected_period()

    # buffer years for the student
    available_years = student_helpers.get_available_years(student)

    # --- Get enrollments for selected semester/year ---
    enrollments = Enrollment.query.filter_by(
        student_id=student.id
    ).join(Class).filter(
        Class.school_year == selected_year,
        Class.semester == selected_semester
    ).all()

    current_classes = [e.class_ for e in enrollments]

    # Build enrollment map: class_id -> enrollment
    enrollment_map = {
        e.class_id: student_helpers.enrollment_to_dict(e)
        for e in enrollments
    }

    # --- Stats ---
    total_subjects = len(current_classes)
    total_units = sum(cls.effective_units for cls in current_classes)

    # Graded count: enrollments with a final_grade set
    graded_count = sum(1 for e in enrollments if e.final_grade is not None)

    # Academic standing from cumulative GPA
    cumulative_gpa = student.get_cumulative_gpa('weighted')

    academic_info = student_helpers.get_academic_standing(cumulative_gpa)

    return jsonify({
        'student': student_helpers.student_to_dict(student),

        'period': {
            'selected_year': selected_year,
            'selected_semester': selected_semester,
            'current_school_year': current_school_year,
            'current_semester': current_semester
        },

        'available_years': available_years,

        'classes': [
            student_helpers.class_to_dict(cls)
            for cls in current_classes
        ],

        'enrollment_map': enrollment_map,

        'stats': {
            'total_subjects': total_subjects,
            'total_units': total_units,
            'graded_count': graded_count
        },

        'academic_standing': academic_info
    }), 200

 
@student_bp.route('/grades')
@student_required
def my_grades():
    """
    Return detailed grades for the student's classes.
    """
    # student data
    student = current_user.student_profile

    # get current school year and semester
    (
        selected_year,
        selected_semester,
        current_school_year,
        current_semester
    ) = student_helpers.get_selected_period()

    # buffer years for the student
    available_years = student_helpers.get_available_years(student)

    # Enrollments data of student for the current semester and year
    enrollments = (
        Enrollment.query.filter_by(student_id=student.id)
        .join(Class)
        .filter(Class.school_year == selected_year,
                Class.semester    == selected_semester)
        .all()
    )
 
    classes_data = []
    for enrollment in enrollments:
        cls = enrollment.class_
 
        tests = (
            Test.query.filter_by(class_id=cls.id)
            .order_by(Test.term_tag, Test.component_tag,
                      Test.test_date, Test.created_at)
            .all()
        )
 
        formula            = cls.get_grading_formula()
        formula_components = formula.get('components', []) if formula else []
        component_weights  = {c['name']: c['weight'] for c in formula_components}
 
        test_grades = {}
        for test in tests:
            grade = Grade.query.filter_by(
                test_id=test.id, student_id=student.id
            ).first()
 
            # Check if this student has an assigned paper image for this test
            paper_img = TestPaperImage.query.filter_by(
                test_id    = test.id,
                student_id = student.id,
                status     = 'assigned'
            ).first()
 
            if grade:
                test_grades[str(test.id)] = {
                    'grade_id':              grade.id,
                    'raw_score':             grade.raw_score,
                    'max_score':             grade.max_score,
                    'calculated_percentage': grade.calculated_percentage,
                    'paper_image_id':        paper_img.id if paper_img else None,
                }
            else:
                test_grades[str(test.id)] = {
                    'grade_id':             None,
                    'raw_score':             None,
                    'max_score':             None,
                    'calculated_percentage': None,
                    'paper_image_id':        paper_img.id if paper_img else None,
                }
 
        classes_data.append({
            'class': student_helpers.class_to_dict(cls),

            'enrollment': student_helpers.enrollment_to_dict(
                enrollment
            ),

            'tests': [
                {
                    'id': test.id,
                    'title': test.title,
                    'term_tag': test.term_tag,
                    'component_tag': test.component_tag,
                    'test_date': (
                        test.test_date.isoformat()
                        if test.test_date
                        else None
                    )
                }
                for test in tests
            ],

            'test_grades': test_grades,

            'component_weights': component_weights,

            'formula_components': formula_components,

            'final_grade': enrollment.final_grade
        })
 
    return jsonify({
        'student': student_helpers.student_to_dict(student),

        'period': {
            'selected_year': selected_year,
            'selected_semester': selected_semester,
            'current_school_year': current_school_year,
            'current_semester': current_semester
        },

        'available_years': available_years,

        'classes': classes_data
    }), 200

@student_bp.route('/gpa-calculator')
@student_required
def gpa_calculator():
    """
    Return GPA calculator data for the current semester.
    """
    student = current_user.student_profile
    
    current_school_year = Config.get_current_school_year()
    current_semester = Config.get_current_semester()
    
    # Get enrolled classes with current grades
    enrolled_classes_data = []
    
    enrollments = Enrollment.query.filter_by(
        student_id=student.id
    ).join(Class).filter(
        Class.school_year == current_school_year,
        Class.semester == current_semester,
        Enrollment.status == 'enrolled'
    ).all()
    
    for enrollment in enrollments:
        cls = enrollment.class_

        ph_grade = student._get_per_class_ph_grade(enrollment)

        enrolled_classes_data.append({
            'subject_name': cls.effective_subject_name,
            'subject_code': cls.effective_subject_code,
            'units': cls.effective_units,
            'current_grade': ph_grade,
            'is_major_subject': cls.is_major_subject
        })
    
    # Calculate GPA with all three methods
    semester_gpa_weighted = student.get_semester_gpa(
        current_school_year, current_semester, 'weighted'
    )
    semester_gpa_simple = student.get_semester_gpa(
        current_school_year, current_semester, 'simple'
    )
    semester_gpa_major = student.get_semester_gpa(
        current_school_year, current_semester, 'major_only'
    )
    
    cumulative_gpa_weighted = student.get_cumulative_gpa('weighted')
    cumulative_gpa_simple = student.get_cumulative_gpa('simple')
    cumulative_gpa_major = student.get_cumulative_gpa('major_only')
    
    # Get all grades for reference
    all_grades = (
        Grade.query
        .filter_by(student_id=student.id)
        .filter(Grade.raw_score.isnot(None))
        .all()
    )

    all_grades_data = [
        {
            'id': grade.id,
            'test_id': grade.test_id,
            'raw_score': grade.raw_score,
            'max_score': grade.max_score,
            'calculated_percentage': grade.calculated_percentage
        }
        for grade in all_grades
    ]
    
    return jsonify({
        'student': student_helpers.student_to_dict(student),

        'current_period': {
            'school_year': current_school_year,
            'semester': current_semester
        },

        'enrolled_classes': enrolled_classes_data,

        'semester_gpa': {
            'weighted': semester_gpa_weighted,
            'simple': semester_gpa_simple,
            'major_only': semester_gpa_major
        },

        'cumulative_gpa': {
            'weighted': cumulative_gpa_weighted,
            'simple': cumulative_gpa_simple,
            'major_only': cumulative_gpa_major
        },

        'all_grades': all_grades_data
    }), 200

@student_bp.route('/change-password', methods=['POST'])
@student_required
def change_password():
    """
    Change the authenticated student's password.

    Expected JSON:

    {
        "current_password": "...",
        "new_password": "...",
        "confirm_password": "..."
    }
    """
    
    try:

        data = request.get_json(silent=True)

        if not data:
            return jsonify({
                'error': 'Request body must contain JSON data.'
            }), 400

        current_password = (
            data.get('current_password', '').strip()
        )

        new_password = (
            data.get('new_password', '').strip()
        )

        confirm_password = (
            data.get('confirm_password', '').strip()
        )

        # -----------------------------------------------------
        # Required fields
        # -----------------------------------------------------

        if not all([
            current_password,
            new_password,
            confirm_password
        ]):
            return jsonify({
                'error': 'All fields are required.'
            }), 400

        # -----------------------------------------------------
        # Password confirmation
        # -----------------------------------------------------

        if new_password != confirm_password:
            return jsonify({
                'error': 'New passwords do not match.'
            }), 400

        # -----------------------------------------------------
        # Password length
        # -----------------------------------------------------

        if len(new_password) < 6:
            return jsonify({
                'error': 'Password must be at least 6 characters long.'
            }), 400

        # -----------------------------------------------------
        # Verify current password
        # -----------------------------------------------------

        if not bcrypt.check_password_hash(
            current_user.password,
            current_password
        ):
            return jsonify({
                'error': 'Current password is incorrect.'
            }), 400

        # -----------------------------------------------------
        # Update password
        # -----------------------------------------------------

        current_user.password = (
            bcrypt
            .generate_password_hash(new_password)
            .decode('utf-8')
        )

        db.session.commit()

        return jsonify({
            'message': 'Password updated successfully.'
        }), 200

    except Exception:
        db.session.rollback()

        return jsonify({
            'error': 'An error occurred while updating the password.'
        }), 500