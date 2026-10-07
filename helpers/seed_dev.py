import os

from app import create_app
from extensions import db, bcrypt
from models import User, Teacher, Student

app = create_app()


def get_or_create_user(email, password, role):
    user = User.query.filter_by(email=email).first()

    if user:
        return user

    user = User(
        email=email,
        password=bcrypt.generate_password_hash(
            password
        ).decode("utf-8"),
        role=role
    )

    db.session.add(user)
    db.session.flush()

    return user


with app.app_context():

    print("Starting development seed...")

    teacher_password = os.environ.get("DEV_TEACHER_PASSWORD")
    student1_password = os.environ.get("DEV_STUDENT1_PASSWORD")
    student2_password = os.environ.get("DEV_STUDENT2_PASSWORD")
    student3_password = os.environ.get("DEV_STUDENT3_PASSWORD")

    required_passwords = {
        "DEV_TEACHER_PASSWORD": teacher_password,
        "DEV_STUDENT1_PASSWORD": student1_password,
        "DEV_STUDENT2_PASSWORD": student2_password,
        "DEV_STUDENT3_PASSWORD": student3_password,
    }

    missing = [
        name
        for name, value in required_passwords.items()
        if not value
    ]

    if missing:
        raise ValueError(
            "Missing development seed environment variables: "
            + ", ".join(missing)
        )

    # =========================================================
    # TEACHER
    # =========================================================

    teacher_user = get_or_create_user(
        email="teacher@acadify.test",
        password=teacher_password,
        role="teacher"
    )

    teacher = Teacher.query.filter_by(
        employee_number="T2026001"
    ).first()

    if not teacher:
        teacher = Teacher(
            user_id=teacher_user.id,
            employee_number="T2026001",
            first_name="Maria",
            last_name="Santos",
            department="College of Engineering",
            specialization="Computer Engineering"
        )

        db.session.add(teacher)

    # =========================================================
    # STUDENT 1
    # =========================================================

    student1_user = get_or_create_user(
        email="student1@acadify.test",
        password=student1_password,
        role="student"
    )

    student1 = Student.query.filter_by(
        student_number="20260001"
    ).first()

    if not student1:
        student1 = Student(
            user_id=student1_user.id,
            student_number="20260001",
            first_name="Juan",
            last_name="Dela Cruz",
            department="College of Engineering",
            program="BS Computer Engineering",
            year_level="4th Year",
            section="A"
        )

        db.session.add(student1)

    # =========================================================
    # STUDENT 2
    # =========================================================

    student2_user = get_or_create_user(
        email="student2@acadify.test",
        password=student2_password,
        role="student"
    )

    student2 = Student.query.filter_by(
        student_number="20260002"
    ).first()

    if not student2:
        student2 = Student(
            user_id=student2_user.id,
            student_number="20260002",
            first_name="Ana",
            last_name="Reyes",
            department="College of Engineering",
            program="BS Computer Engineering",
            year_level="4th Year",
            section="A"
        )

        db.session.add(student2)

    # =========================================================
    # STUDENT 3
    # =========================================================

    student3_user = get_or_create_user(
        email="student3@acadify.test",
        password=student3_password,
        role="student"
    )

    student3 = Student.query.filter_by(
        student_number="20260003"
    ).first()

    if not student3:
        student3 = Student(
            user_id=student3_user.id,
            student_number="20260003",
            first_name="Miguel",
            last_name="Garcia",
            department="College of Engineering",
            program="BS Computer Engineering",
            year_level="4th Year",
            section="A"
        )

        db.session.add(student3)

    db.session.commit()

    print()
    print("Development seed completed successfully.")
    print("Teacher: teacher@acadify.test")
    print("Students: 20260001, 20260002, 20260003")