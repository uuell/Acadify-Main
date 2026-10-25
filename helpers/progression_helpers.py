
from models import Student, Enrollment, Class
from config import Config
from helpers.student_helpers import get_student_academic_status

# Configure the maximum year level for each program.
# Add actual program names and durations here.
PROGRAM_MAX_YEAR_LEVELS = {
    # Engineering
    "BS Computer Engineering": 4,
    "BS Civil Engineering": 4,
    "BS Electrical Engineering": 4,
    "BS Electronics Engineering": 4,
    "BS Mechanical Engineering": 4,
    "BS Industrial Engineering": 4,

    # Computing
    "BS Information Technology": 4,
    "BS Computer Science": 4,
    "BS Information Systems": 4,

    # Business
    "BS Business Administration": 4,
    "BS Accountancy": 4,
    "BS Management Accounting": 4,
    "BS Entrepreneurship": 4,

    # Education
    "Bachelor of Elementary Education": 4,
    "Bachelor of Secondary Education": 4,

    # Health Sciences
    "BS Nursing": 4,
    "BS Medical Technology": 4,
    "BS Pharmacy": 4,
    "BS Physical Therapy": 5,
    "BS Occupational Therapy": 5,

    # Other Programs
    "BS Psychology": 4,
    "BS Biology": 4,
    "BS Criminology": 4,
    "BS Hospitality Management": 4,
    "BS Tourism Management": 4,
    "BS Architecture": 5,
}

def check_student_progression(student, school_year=None):
    """
    Evaluate a student's eligibility for academic progression.

    This function is read-only. It does not promote students
    or modify database records.
    """

    if school_year is None:
        school_year = Config.get_current_school_year()

    reasons = []

    year_level_numbers = {
        "1st Year": 1,
        "2nd Year": 2,
        "3rd Year": 3,
        "4th Year": 4,
        "5th Year": 5,
        "6th Year": 6,
    }

    current_year = year_level_numbers.get(student.year_level)
    max_year = PROGRAM_MAX_YEAR_LEVELS.get(student.program)

    if current_year is None:
        reasons.append("Student has an unrecognized year level.")

    if max_year is None:
        reasons.append(
            f"Maximum year level is not configured for program: {student.program}."
        )
    elif current_year is not None and current_year >= max_year:
        reasons.append(
            "Student is already at the final year level of their program."
        )

    academic_status = get_student_academic_status(student)


    if student.academic_status == "Graduated":
        reasons.append(
            "Graduated students cannot be promoted."
        )

    if student.enrollment_classification != "Regular":
        reasons.append(
            "Student must have Regular enrollment classification."
        )

    enrollments = (
        Enrollment.query
        .join(Class, Enrollment.class_id == Class.id)
        .filter(
            Enrollment.student_id == student.id,
            Class.school_year == school_year,
            Enrollment.status.in_(["enrolled", "completed"])
        )
        .all()
    )

    if not enrollments:
        reasons.append(
            f"No enrollment records found for school year {school_year}."
        )

    subjects = []

    for enrollment in enrollments:
        cls = enrollment.class_
        grade = enrollment.final_grade

        # Prevent reusing previous year-level records for another promotion.
        if cls.year_level != student.year_level:
            reasons.append(
                f"{cls.effective_subject_code} belongs to "
                f"{cls.year_level or 'an unspecified year level'}, "
                f"not the student's current {student.year_level}."
            )

        if enrollment.status != "completed":
            reasons.append(
                f"{cls.effective_subject_code} enrollment is not completed."
            )

        if grade is None:
            result = "Missing Grade"
            reasons.append(
                f"{cls.effective_subject_code} has no final grade."
            )
        elif grade > 3.0:
            result = "Failed"
            reasons.append(
                f"{cls.effective_subject_code} has a failing grade."
            )
        else:
            result = "Passed"

        subjects.append({
            "class_id": cls.id,
            "subject_code": cls.effective_subject_code,
            "subject_name": cls.effective_subject_name,
            "semester": cls.semester,
            "enrollment_status": enrollment.status,
            "final_grade": grade,
            "result": result
        })

    return {
        "student_id": student.id,
        "student_number": student.student_number,
        "student_name": student.get_full_name(),
        "school_year": school_year,
        "current_year_level": student.year_level,
        "academic_status": academic_status,
        "enrollment_classification": student.enrollment_classification,
        "eligible": len(reasons) == 0,
        "reasons": reasons,
        "subjects": subjects
    }
