from datetime import datetime as dt

from flask import Blueprint, jsonify, request
from models import Student, Class, Enrollment, Grade, Test, TestPaperImage
from config import Config


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def student_to_dict(student):
    """
    Convert a Student model into JSON-safe data.
    """

    return {
        'id': student.id,
        'student_number': student.student_number,
        'first_name': student.first_name,
        'last_name': student.last_name,
        'department': student.department,
        'program': student.program,
        'year_level': student.year_level,
        'section': student.section
    }


def class_to_dict(cls):
    """
    Convert a Class model into JSON-safe data.
    """

    return {
        'id': cls.id,
        'subject_name': cls.effective_subject_name,
        'subject_code': cls.effective_subject_code,
        'units': cls.effective_units,
        'school_year': cls.school_year,
        'semester': cls.semester
    }


def enrollment_to_dict(enrollment):
    """
    Convert an Enrollment model into JSON-safe data.
    """

    return {
        'id': enrollment.id,
        'class_id': enrollment.class_id,
        'student_id': enrollment.student_id,
        'enrollment_date': enrollment.enrollment_date,
        'status': enrollment.status,
        'final_grade': enrollment.final_grade
    }


def get_academic_standing(cumulative_gpa):
    """
    Determine academic standing from cumulative GPA.

    Returns both the standing and the frontend color variable
    currently used by the Flask application.
    """

    if cumulative_gpa:

        if cumulative_gpa <= 1.75:
            return {
                'standing': "Dean's Lister",
                'color': 'var(--success-green)'
            }

        elif cumulative_gpa <= 2.5:
            return {
                'standing': 'Good Standing',
                'color': 'var(--success-green)'
            }

        elif cumulative_gpa <= 3.0:
            return {
                'standing': 'Satisfactory',
                'color': 'var(--text-main)'
            }

        else:
            return {
                'standing': 'Probation',
                'color': 'var(--danger-red)'
            }

    return {
        'standing': 'Good Standing',
        'color': 'var(--text-main)'
    }


def get_available_years(student):
    """
    Build the list of school years available to the student.

    Includes:
    - actual years from enrollment history
    - a small buffer around the current year
    """

    all_enrollments = (
        Enrollment.query
        .filter_by(student_id=student.id)
        .join(Class)
        .with_entities(Class.school_year)
        .distinct()
        .all()
    )

    # generates a set of school years based on school year database
    actual_years = { row.school_year for row in all_enrollments }

    current_year_num = dt.now().year
    # generates a set of years 
    buffer_years = { f"{year}-{year + 1}" for year in range(current_year_num - 3, current_year_num + 2)}

    #returns a list of sorted school school years in descending order 
    return sorted(
        list(actual_years | buffer_years),
        reverse=True
    )

def get_selected_period():
    """
    Get the school year and semester requested by the frontend.

    If omitted or set to 'all', use the current school year/semester.
    """

    current_school_year = Config.get_current_school_year()
    current_semester = Config.get_current_semester()

    selected_year = request.args.get('year')
    selected_semester = request.args.get('semester')

    if not selected_year or selected_year == 'all':
        selected_year = current_school_year

    if not selected_semester or selected_semester == 'all':
        selected_semester = current_semester

    return (
        selected_year,
        selected_semester,
        current_school_year,
        current_semester
    )