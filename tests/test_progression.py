
from app import create_app
from extensions import db
from models import User, Student, Teacher, Class, Enrollment
from config import Config

from flask_login import login_user

def test_promotion_requires_authentication():
    app = create_app("testing")

    with app.app_context():
        db.create_all()

        try:
            client = app.test_client()

            response = client.post(
                "/admin/progression/promote/1",
                json={"confirm_promotion": True}
            )

            assert response.status_code == 401
            assert response.json["success"] is False

            print("PASS: Promotion requires authentication.")

        finally:
            db.session.remove()
            db.drop_all()

def test_promotion_requires_admin():
    app = create_app("testing")

    with app.app_context():
        db.create_all()

        try:
            client = app.test_client()

            # Simulate a logged-in user whose role is not admin.
            with client.session_transaction() as session:
                session["_user_id"] = "1"
                session["_fresh"] = True

            # No user with ID 1 exists, so this should
            # still be treated as unauthenticated.
            response = client.post(
                "/admin/progression/promote/1",
                json={"confirm_promotion": True}
            )

            assert response.status_code == 401

            print("PASS: Invalid login session is rejected.")

        finally:
            db.session.remove()
            db.drop_all()


def test_promotion_rejects_non_admin():
    app = create_app("testing")

    with app.app_context():
        db.create_all()

        try:
            teacher = User(
                email="teacher@test.com",
                password="test-password",
                role="teacher"
            )

            db.session.add(teacher)
            db.session.commit()

            client = app.test_client()

            # Simulate an authenticated teacher session.
            with client.session_transaction() as session:
                session["_user_id"] = str(teacher.id)
                session["_fresh"] = True

            response = client.post(
                "/admin/progression/promote/1",
                json={"confirm_promotion": True}
            )

            assert response.status_code == 403
            assert response.json["success"] is False
            assert response.json["message"] == "Access denied. Admins only."

            print("PASS: Non-admin promotion request rejected.")

        finally:
            db.session.remove()
            db.drop_all()


def test_successful_promotion_and_duplicate_prevention():
    app = create_app("testing")

    with app.app_context():
        db.create_all()

        try:
            admin = User(
                email="admin-promotion@test.com",
                password="test-password",
                role="admin"
            )
            teacher_user = User(
                email="teacher-promotion@test.com",
                password="test-password",
                role="teacher"
            )
            student_user = User(
                email="student-promotion@test.com",
                password="test-password",
                role="student"
            )

            db.session.add_all([admin, teacher_user, student_user])
            db.session.flush()

            teacher = Teacher(
                user_id=teacher_user.id,
                employee_number="TEST-T001",
                first_name="Test",
                last_name="Teacher",
                department="Engineering"
            )

            student = Student(
                user_id=student_user.id,
                student_number="TEST-S001",
                first_name="Test",
                last_name="Student",
                department="Engineering",
                program="BS Computer Engineering",
                year_level="1st Year",
                enrollment_classification="Regular"
            )

            db.session.add_all([teacher, student])
            db.session.flush()

            test_class = Class(
                teacher_id=teacher.id,
                subject_name="Introduction to Engineering",
                subject_code="CPE101",
                units=3,
                school_year=Config.get_current_school_year(),
                semester=Config.get_current_semester(),
                department="Engineering",
                program="BS Computer Engineering",
                year_level="1st Year"
            )

            db.session.add(test_class)
            db.session.flush()

            enrollment = Enrollment(
                student_id=student.id,
                class_id=test_class.id,
                status="completed",
                final_grade=2.0
            )

            db.session.add(enrollment)
            db.session.commit()

            student_id = student.id

            client = app.test_client()

            with client.session_transaction() as session:
                session["_user_id"] = str(admin.id)
                session["_fresh"] = True

            endpoint = f"/admin/progression/promote/{student_id}"

            # 1. Confirmation is required.
            response = client.post(
                endpoint,
                json={"confirm_promotion": False}
            )

            assert response.status_code == 400, response.json
            assert db.session.get(Student, student_id).year_level == "1st Year"

            print("PASS: Explicit confirmation required.")

            # 2. Eligible student is promoted.
            response = client.post(
                endpoint,
                json={"confirm_promotion": True}
            )

            assert response.status_code == 200, response.json
            assert response.json["success"] is True

            db.session.expire_all()
            promoted = db.session.get(Student, student_id)

            assert promoted.year_level == "2nd Year"

            print("PASS: Student promoted from 1st Year to 2nd Year.")

            # 3. Same records cannot be reused for promotion.
            response = client.post(
                endpoint,
                json={"confirm_promotion": True}
            )

            assert response.status_code == 400, response.json

            db.session.expire_all()
            assert db.session.get(Student, student_id).year_level == "2nd Year"

            print("PASS: Duplicate promotion rejected.")

        finally:
            db.session.remove()
            db.drop_all()



def test_batch_promotion():
    app = create_app("testing")

    with app.app_context():
        db.create_all()

        try:
            admin = User(
                email="batch-admin@test.com",
                password="test-password",
                role="admin"
            )
            teacher_user = User(
                email="batch-teacher@test.com",
                password="test-password",
                role="teacher"
            )
            student_users = [
                User(
                    email=f"batch-student-{i}@test.com",
                    password="test-password",
                    role="student"
                )
                for i in range(1, 4)
            ]

            db.session.add_all(
                [admin, teacher_user, *student_users]
            )
            db.session.flush()

            teacher = Teacher(
                user_id=teacher_user.id,
                employee_number="BATCH-T001",
                first_name="Batch",
                last_name="Teacher",
                department="Engineering"
            )

            db.session.add(teacher)
            db.session.flush()

            students = []

            for i, user in enumerate(student_users, start=1):
                student = Student(
                    user_id=user.id,
                    student_number=f"BATCH-S00{i}",
                    first_name=f"Student{i}",
                    last_name="Test",
                    department="Engineering",
                    program="BS Computer Engineering",
                    year_level="1st Year",
                    enrollment_classification=(
                        "Regular" if i != 3 else "Irregular"
                    )
                )
                students.append(student)

            db.session.add_all(students)
            db.session.flush()

            test_class = Class(
                teacher_id=teacher.id,
                subject_name="Engineering Fundamentals",
                subject_code="CPE101",
                units=3,
                school_year=Config.get_current_school_year(),
                semester=Config.get_current_semester(),
                department="Engineering",
                program="BS Computer Engineering",
                year_level="1st Year"
            )

            db.session.add(test_class)
            db.session.flush()

            for student in students:
                db.session.add(
                    Enrollment(
                        student_id=student.id,
                        class_id=test_class.id,
                        status="completed",
                        final_grade=2.0
                    )
                )

            db.session.commit()

            student_ids = [student.id for student in students]
            endpoint = "/admin/progression/promote/batch"

            client = app.test_client()

            with client.session_transaction() as session:
                session["_user_id"] = str(admin.id)
                session["_fresh"] = True

            # 1. Explicit confirmation is required.
            response = client.post(
                endpoint,
                json={
                    "student_ids": student_ids,
                    "confirm_promotion": False
                }
            )

            assert response.status_code == 400, response.json
            print("PASS: Batch promotion requires confirmation.")

            # 2. Promote eligible students; reject irregular student.
            response = client.post(
                endpoint,
                json={
                    "student_ids": student_ids,
                    "confirm_promotion": True
                }
            )

            assert response.status_code == 200, response.json

            summary = response.json["summary"]

            assert summary["requested"] == 3
            assert summary["promoted"] == 2
            assert summary["rejected"] == 1

            db.session.expire_all()

            assert db.session.get(Student, student_ids[0]).year_level == "2nd Year"
            assert db.session.get(Student, student_ids[1]).year_level == "2nd Year"
            assert db.session.get(Student, student_ids[2]).year_level == "1st Year"

            print("PASS: Batch promotes eligible students only.")
            print("PASS: Batch summary is correct.")

            # 3. Reusing the same records cannot promote again.
            response = client.post(
                endpoint,
                json={
                    "student_ids": student_ids,
                    "confirm_promotion": True
                }
            )

            assert response.status_code == 200, response.json
            assert response.json["summary"]["promoted"] == 0
            assert response.json["summary"]["rejected"] == 3

            db.session.expire_all()

            assert db.session.get(Student, student_ids[0]).year_level == "2nd Year"
            assert db.session.get(Student, student_ids[1]).year_level == "2nd Year"

            print("PASS: Duplicate batch promotion rejected.")

        finally:
            db.session.remove()
            db.drop_all()

def test_progression_api_validation():
    app = create_app("testing")
    batch_endpoint = "/admin/progression/promote/batch"

    # Create the test database and users.
    with app.app_context():
        db.create_all()

        admin = User(
            email="validation-admin@test.com",
            password="test-password",
            role="admin"
        )

        teacher = User(
            email="validation-teacher@test.com",
            password="test-password",
            role="teacher"
        )

        db.session.add_all([admin, teacher])
        db.session.commit()

        admin_id = admin.id
        teacher_id = teacher.id

    try:
        # 1. Unauthenticated request
        guest_client = app.test_client()

        response = guest_client.post(
            batch_endpoint,
            json={
                "student_ids": [1],
                "confirm_promotion": True
            }
        )

        assert response.status_code == 401, response.json
        print("PASS: Unauthenticated batch request rejected.")

        # 2. Authenticated non-admin request
        teacher_client = app.test_client()

        with teacher_client.session_transaction() as session:
            session["_user_id"] = str(teacher_id)
            session["_fresh"] = True

        response = teacher_client.post(
            batch_endpoint,
            json={
                "student_ids": [1],
                "confirm_promotion": True
            }
        )

        assert response.status_code == 403, response.json
        print("PASS: Non-admin batch request rejected.")

        # 3. Authenticated administrator
        admin_client = app.test_client()

        with admin_client.session_transaction() as session:
            session["_user_id"] = str(admin_id)
            session["_fresh"] = True

        # 4. Nonexistent student
        response = admin_client.post(
            "/admin/progression/promote/99999",
            json={"confirm_promotion": True}
        )

        assert response.status_code == 404, response.json
        print("PASS: Nonexistent student promotion rejected.")

        # 5. Missing confirmation
        response = admin_client.post(
            batch_endpoint,
            json={"student_ids": [1]}
        )

        assert response.status_code == 400, response.json
        print("PASS: Missing batch confirmation rejected.")

        # 6. Empty student list
        response = admin_client.post(
            batch_endpoint,
            json={
                "student_ids": [],
                "confirm_promotion": True
            }
        )

        assert response.status_code == 400, response.json
        print("PASS: Empty student list rejected.")

        # 7. Duplicate student IDs
        response = admin_client.post(
            batch_endpoint,
            json={
                "student_ids": [1, 1],
                "confirm_promotion": True
            }
        )

        assert response.status_code == 400, response.json
        print("PASS: Duplicate student IDs rejected.")

        # 8. Invalid student ID types
        response = admin_client.post(
            batch_endpoint,
            json={
                "student_ids": ["abc", 2],
                "confirm_promotion": True
            }
        )

        assert response.status_code == 400, response.json
        print("PASS: Invalid student ID types rejected.")

        # 9. Oversized batch
        response = admin_client.post(
            batch_endpoint,
            json={
                "student_ids": list(range(1, 102)),
                "confirm_promotion": True
            }
        )

        assert response.status_code == 400, response.json
        print("PASS: Oversized batch rejected.")

        # 10. Invalid JSON
        response = admin_client.post(
            batch_endpoint,
            data="not valid json",
            content_type="application/json"
        )

        assert response.status_code == 400, response.json
        print("PASS: Invalid JSON body rejected.")

        # 11. Missing student records
        response = admin_client.post(
            batch_endpoint,
            json={
                "student_ids": [99998, 99999],
                "confirm_promotion": True
            }
        )

        assert response.status_code == 200, response.json
        assert response.json["summary"] == {
            "requested": 2,
            "promoted": 0,
            "rejected": 2
        }

        print("PASS: Missing students reported as rejected.")
        print("\nPASS: All academic progression API validation tests passed.")

    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()

if __name__ == "__main__":
    test_promotion_requires_authentication()
    test_promotion_requires_admin()
    test_promotion_rejects_non_admin()
    test_successful_promotion_and_duplicate_prevention()
    test_batch_promotion()
    test_progression_api_validation()
