"""
models.py - Complete Database Models for Acadify
Philippine College Grading System with Customizable Formulas
"""

from extensions import db
from flask_login import UserMixin
from datetime import datetime
from sqlalchemy import func
import json
import os


class User(UserMixin, db.Model):
    """
    Base User Model - Authentication for all users
    """
    __tablename__ = 'user'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'admin', 'teacher', 'student'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    student_profile = db.relationship('Student', backref='user', uselist=False, cascade='all, delete-orphan')
    teacher_profile = db.relationship('Teacher', backref='user', uselist=False, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<User {self.email} ({self.role})>'
    
    def is_admin(self):
        return self.role == 'admin'
    
    def is_teacher(self):
        return self.role == 'teacher'
    
    def is_student(self):
        return self.role == 'student'

class Student(db.Model):
    """
    Student Profile - Extended student information
    """
    __tablename__ = 'student'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True)
    
    # Basic Information
    student_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    
    # Academic Information
    department = db.Column(db.String(100), nullable=False)  # "College of Engineering"
    program = db.Column(db.String(100), nullable=False)  # "BS Computer Science"
    year_level = db.Column(db.String(20), nullable=False)  # "1st Year", "2nd Year", etc.
    section = db.Column(db.String(20), nullable=True)  # "A", "B", "C" (null for irregular)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    enrollments = db.relationship('Enrollment', backref='student', lazy='dynamic', cascade='all, delete-orphan')
    grades = db.relationship('Grade', backref='student', lazy='dynamic', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Student {self.student_number} - {self.get_full_name()}>'
    
    def get_full_name(self):
        """Return full name"""
        return f"{self.first_name} {self.last_name}"
    
    def _get_per_class_ph_grade(self, enrollment):
        """
        Return the Philippine grade for one class enrollment.

        Method 2:
            Enrollment.final_grade is the official class-level
            Philippine grade for the student.

        Returns:
            float | None
        """
        return enrollment.final_grade
 
    def get_semester_gpa(self, school_year, semester, calculation_method):
        """
        Calculate GPA for a specific semester.
 
        Reads one PH grade per enrolled class (via _get_per_class_ph_grade),
        never raw test scores. Handles both old and new grading systems.
        """
        enrollments = (
            Enrollment.query
            .filter_by(student_id=self.id)
            .join(Class)
            .filter(
                Class.school_year == school_year,
                Class.semester    == semester,
            )
            .all()
        )
 
        if not enrollments:
            return None
 
        # Build (ph_grade, units, is_major) for each class that has a grade
        graded = []
        for e in enrollments:
            ph = self._get_per_class_ph_grade(e)
            if ph is not None:
                graded.append((ph, e.class_.effective_units, e.class_.is_major_subject))
 
        if not graded:
            return None
 
        if calculation_method == 'weighted':
            total_points = sum(ph * units for ph, units, _ in graded)
            total_units  = sum(units      for _,  units, _ in graded)
            return round(total_points / total_units, 2) if total_units > 0 else None
 
        elif calculation_method == 'simple':
            return round(sum(ph for ph, _, _ in graded) / len(graded), 2)

        # simple average of major-subject grades
        elif calculation_method == 'major_only':
            major = [(ph, units) for ph, units, is_major in graded if is_major]
            if not major:
                return None
            return round(sum(ph for ph, _ in major) / len(major), 2)
 
        return None
 
    def get_cumulative_gpa(self, calculation_method):
        """
        Calculate cumulative GPA across all semesters.
 
        Reads one PH grade per enrolled class (via _get_per_class_ph_grade),
        never raw test scores. Handles both old and new grading systems.
        """
        enrollments = Enrollment.query.filter_by(student_id=self.id).all()
 
        if not enrollments:
            return None
 
        # Build (ph_grade, units, is_major) for each class that has a grade
        graded = []
        for e in enrollments:
            ph = self._get_per_class_ph_grade(e)
            if ph is not None:
                graded.append((ph, e.class_.effective_units, e.class_.is_major_subject))
 
        if not graded:
            return None
 
        if calculation_method == 'weighted':
            total_points = sum(ph * units for ph, units, _ in graded)
            total_units  = sum(units      for _,  units, _ in graded)
            return round(total_points / total_units, 2) if total_units > 0 else None
 
        elif calculation_method == 'simple':
            return round(sum(ph for ph, _, _ in graded) / len(graded), 2)
 
        elif calculation_method == 'major_only':
            major = [(ph, units) for ph, units, is_major in graded if is_major]
            if not major:
                return None
            return round(sum(ph for ph, _ in major) / len(major), 2)
 
        return None

class Teacher(db.Model):
    """
    Teacher Profile - Extended teacher information
    """
    __tablename__ = 'teacher'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True)
    
    # Basic Information
    employee_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    
    # Professional Information
    department = db.Column(db.String(100), nullable=False)
    specialization = db.Column(db.String(200), nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    classes = db.relationship('Class', backref='teacher', lazy='dynamic')
    
    def __repr__(self):
        return f'<Teacher {self.employee_number} - {self.get_full_name()}>'
    
    def get_full_name(self):
        """Return full name"""
        return f"{self.first_name} {self.last_name}"

class Subject(db.Model):
    """
    Subject/Course Master List
    Defines grading formula per subject (applies to all sections)
    """
    __tablename__ = 'subject'
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)  # "MATH101"
    name = db.Column(db.String(200), nullable=False)  # "Mathematics 101"
    description = db.Column(db.Text, nullable=True)
    units = db.Column(db.Integer, nullable=False, default=3)
    is_major_subject = db.Column(db.Boolean, default=True)  # For GPA calculation filtering
    
    # Grading Formula (JSON format)
    # Example: [
    #   {"component": "Quizzes", "weight": 20, "max_points": 100},
    #   {"component": "Midterm", "weight": 30, "max_points": 100},
    #   {"component": "Final", "weight": 30, "max_points": 100},
    #   {"component": "Projects", "weight": 20, "max_points": 100}
    # ]
    grading_formula = db.Column(db.Text, nullable=True)  # JSON string
    
    # Grade Conversion Table (Percentage to PH Grade)
    # Standard: 97-100=1.0, 94-96=1.25, 91-93=1.5, etc.
    grade_conversion = db.Column(db.Text, nullable=True)  # JSON string
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    classes = db.relationship('Class', backref='subject', lazy='dynamic')
    
    def __repr__(self):
        return f'<Subject {self.code} - {self.name}>'
    
    def get_grading_formula(self):
        """Parse and return grading formula as list"""
        if self.grading_formula:
            return json.loads(self.grading_formula)
        return []
    
    def set_grading_formula(self, formula_list):
        """Set grading formula from list"""
        self.grading_formula = json.dumps(formula_list)
    
    def get_grade_conversion(self):
        """Parse and return grade conversion table"""
        if self.grade_conversion:
            return json.loads(self.grade_conversion)
        # Default PH grading scale
        return {
            "97-100": 1.0, "94-96": 1.25, "91-93": 1.5, "88-90": 1.75,
            "85-87": 2.0, "82-84": 2.25, "79-81": 2.5, "76-78": 2.75,
            "75": 3.0, "65-74": 4.0, "0-64": 5.0
        }
    
    def convert_to_ph_grade(self, percentage):
        """Convert percentage score to Philippine grade."""
        
        if percentage is None:
            return None

        conversion = self.get_grade_conversion()

        for range_str, grade in conversion.items():

            # Example: "88-90"
            if '-' in range_str:
                min_score, max_score = map(float, range_str.split('-'))

                # Treat 88-90 as 88.0 up to, but not including, 91.0
                if min_score <= percentage < max_score + 1:
                    return grade

            # Example: "75"
            else:
                score = float(range_str)

                # Treat 75 as 75.0 up to, but not including, 76.0
                if score <= percentage < score + 1:
                    return grade

        return 5.0

class Class(db.Model):
    """
    Class - Specific instance of a subject
    UPDATED: Grading formula no longer requires max_points (for Option B)
    """
    __tablename__ = 'class'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # === SUBJECT INFO ===
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=True)
    subject_name = db.Column(db.String(200), nullable=True)
    subject_code = db.Column(db.String(20), nullable=True)
    units = db.Column(db.Integer, nullable=True)
    
    # === TEACHER & CLASS DETAILS ===
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher.id'), nullable=False)
    section = db.Column(db.String(20), nullable=True)
    schedule = db.Column(db.String(100), nullable=True)
    room = db.Column(db.String(50), nullable=True)
    
    # === ACADEMIC PERIOD ===
    school_year = db.Column(db.String(20), nullable=False)
    semester = db.Column(db.String(20), nullable=False)
    
    # === CLASS LIMITS ===
    max_students = db.Column(db.Integer, default=40)
    
    # === GRADING FORMULA ===
    # NEW FORMAT (Option B - max_points optional):
    # {
    #   "components": [
    #     {"name": "Exams", "weight": 30},
    #     {"name": "Quizzes", "weight": 30},
    #     {"name": "Projects", "weight": 40}
    #   ],
    #   "use_philippine_conversion": true
    # }
    grading_formula = db.Column(db.Text, nullable=True)
    grade_conversion_table = db.Column(db.Text, nullable=True)
    
    # === PROGRAM/YEAR ===
    department = db.Column(db.String(100), nullable=True)
    program = db.Column(db.String(100), nullable=True)
    year_level = db.Column(db.String(20), nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # === RELATIONSHIPS ===
    enrollments = db.relationship('Enrollment', backref='class_', lazy='dynamic', cascade='all, delete-orphan')
    tests = db.relationship('Test', backref='class_', lazy='dynamic', cascade='all, delete-orphan')
    
    # === HELPER PROPERTIES ===
    
    @property
    def effective_subject_name(self):
        """Get subject name from manual input or Subject table"""
        if self.subject_name:
            return self.subject_name
        elif self.subject_id and self.subject:
            return self.subject.name
        return "Unnamed Subject"
    
    @property
    def effective_subject_code(self):
        """Get subject code from manual input or Subject table"""
        if self.subject_code:
            return self.subject_code
        elif self.subject_id and self.subject:
            return self.subject.code
        return "N/A"
    
    @property
    def effective_units(self):
        """Get units from manual input or Subject table"""
        if self.units is not None:
            return self.units
        elif self.subject_id and self.subject:
            return self.subject.units
        return 3  # Default
    
    @property
    def is_major_subject(self):
        """Check if this is a major subject (for GPA calculation)"""
        if self.subject_id and self.subject:
            return self.subject.is_major_subject
        return True
    
    # === GRADING FORMULA METHODS ===
    
    def get_grading_formula(self):
        """
        Parse and return grading formula as dict
        UPDATED: Default formula has no max_points (Option B)
        """
        # Priority 1: Class has its own formula
        if self.grading_formula:
            try:
                return json.loads(self.grading_formula)
            except json.JSONDecodeError:
                pass
        
        # Priority 2: Old class - get from Subject table
        if self.subject_id and self.subject and self.subject.grading_formula:
            try:
                formula = json.loads(self.subject.grading_formula)
                if 'components' in formula:
                    return formula
                return {
                    "components": formula if isinstance(formula, list) else [],
                    "use_philippine_conversion": True
                }
            except (json.JSONDecodeError, AttributeError):
                pass
        
        # Priority 3: Default formula (Option B - no max_points)
        return {
            "components": [
                {"name": "Midterm Exam", "weight": 50},
                {"name": "Final Exam", "weight": 50}
            ],
            "use_philippine_conversion": True
        }
    
    def set_grading_formula(self, formula_dict):
        """
        Set grading formula from dict
        UPDATED: max_points is now optional (for Option B)
        Validates that weights total 100%
        """
        if not isinstance(formula_dict, dict):
            raise ValueError("Formula must be a dictionary")
        
        if 'components' not in formula_dict:
            raise ValueError("Formula must have 'components' key")
        
        # Validate each component
        for component in formula_dict['components']:
            if 'name' not in component:
                raise ValueError("Each component must have a 'name'")
            if 'weight' not in component:
                raise ValueError("Each component must have a 'weight'")
            # Note: max_points is optional with Option B
        
        # Validate weights total 100%
        total_weight = sum(c.get('weight', 0) for c in formula_dict['components'])
        if total_weight != 100:
            raise ValueError(f"Component weights must total 100%, got {total_weight}%")
        
        # remove deprecated fields
        formula_dict.pop('passing_grade', None)
        
        if 'use_philippine_conversion' not in formula_dict:
            formula_dict['use_philippine_conversion'] = True
        
        self.grading_formula = json.dumps(formula_dict)
    
    def validate_formula_weights(self):
        """Check if formula weights total 100%"""
        try:
            formula = self.get_grading_formula()
            if not formula or 'components' not in formula:
                return False
            
            total_weight = sum(c.get('weight', 0) for c in formula['components'])
            return total_weight == 100
        except:
            return False
    
    def has_grading_formula(self):
        """Check if class has a grading formula set"""
        return self.grading_formula is not None or (
            self.subject_id and self.subject and self.subject.grading_formula
        )
    
    def can_edit_formula(self):
        """
        Check if the grading formula can still be edited.

        The formula can only be edited if no Method 2 scores
        have been entered for this class yet.
        """
        from models import Grade, Test

        grades_count = (
            Grade.query
            .join(Test)
            .filter(
                Test.class_id == self.id,
                Grade.raw_score.isnot(None)
            )
            .count()
        )

        return grades_count == 0
    
    def get_grade_conversion_table(self):
        """Get grade conversion table (percentage to PH grade)"""
        if self.grade_conversion_table:
            try:
                return json.loads(self.grade_conversion_table)
            except json.JSONDecodeError:
                pass
        
        # Default Philippine grading scale
        return {
            "97-100": 1.0,
            "94-96": 1.25,
            "91-93": 1.5,
            "88-90": 1.75,
            "85-87": 2.0,
            "82-84": 2.25,
            "79-81": 2.5,
            "76-78": 2.75,
            "75": 3.0,
            "65-74": 4.0,
            "0-64": 5.0
        }
    
    def convert_to_ph_grade(self, percentage):
        """Convert percentage score to Philippine grade."""
        
        if percentage is None:
            return None

        conversion = self.get_grade_conversion_table()

        for range_str, grade in conversion.items():

            # Example: "88-90"
            if '-' in range_str:
                min_score, max_score = map(float, range_str.split('-'))

                # Treat 88-90 as 88.0 up to, but not including, 91.0
                if min_score <= percentage < max_score + 1:
                    return grade

            # Example: "75"
            else:
                score = float(range_str)

                # Treat 75 as 75.0 up to, but not including, 76.0
                if score <= percentage < score + 1:
                    return grade

        return 5.0
    
    def __repr__(self):
        section_str = f" - Section {self.section}" if self.section else ""
        return f'<Class {self.effective_subject_code}{section_str} ({self.school_year} {self.semester})>'
    
    def get_enrolled_count(self):
        """Get number of enrolled students"""
        return self.enrollments.filter_by(status='enrolled').count()
    
    def is_full(self):
        """Check if class is at capacity"""
        return self.get_enrolled_count() >= self.max_students
    
    def get_display_name(self):
        """Get full display name of class"""
        code = self.effective_subject_code
        name = self.effective_subject_name
        section = f" - Section {self.section}" if self.section else ""
        return f"{code}: {name}{section}"

class Enrollment(db.Model):
    """
    Enrollment - Links students to classes (many-to-many relationship)
    """
    __tablename__ = 'enrollment'
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False, index=True)
    class_id = db.Column(db.Integer, db.ForeignKey('class.id'), nullable=False, index=True)
    
    enrollment_date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='enrolled')  # 'enrolled', 'dropped', 'completed'
    
    # Final grade for this class (computed at end of semester)
    final_grade = db.Column(db.Float, nullable=True)
    
    def __repr__(self):
        return f'<Enrollment Student:{self.student_id} Class:{self.class_id} ({self.status})>'

class Test(db.Model):
    """
    Test — A single gradable activity in a class.
 
    METHOD 2 (Activity-Based):
        Every quiz, exam, and project is its own Test row.
        term_tag      → which grading period  ("Prelims", "Midterms", "Finals")
        component_tag → which formula bucket  ("Quizzes", "Exams", "Projects")
 
        Example rows:
            title="Prelim Quiz 1",  term_tag="Prelims",  component_tag="Quizzes"
            title="Prelim Exam",    term_tag="Prelims",  component_tag="Exams"
            title="Midterm Quiz 1", term_tag="Midterms", component_tag="Quizzes"
 
        The grade formula engine groups tests by (term_tag, component_tag),
        averages the scores within each group, applies weights, and produces
        a Philippine grade per term. If any component in the formula has NO
        tagged tests with scores yet, the term grade shows as INC.
 
    BACKWARD COMPATIBLE:
        Old tests with term_tag=None are simply ignored by the new engine.
        They still appear as columns in the grading spreadsheet and can be
        graded manually via final_grade (the old direct-entry path).
    """
 
    __tablename__ = 'test'
 
    id         = db.Column(db.Integer, primary_key=True)
    class_id   = db.Column(db.Integer, db.ForeignKey('class.id'), nullable=False)
    title      = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    test_date  = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
 
    # ── Method 2 tags ──────────────────────────────────────────────────────
    # Nullable so old (untagged) tests keep working without changes.
    term_tag      = db.Column(db.String(50),  nullable=True, index=True)
    component_tag = db.Column(db.String(100), nullable=True)
 
    # Relationships
    grades = db.relationship(
        'Grade', backref='test', lazy='dynamic', cascade='all, delete-orphan'
    )
 
    # ── Helpers ────────────────────────────────────────────────────────────
 
    @property
    def is_tagged(self):
        """True if this test participates in the Method 2 formula engine."""
        return bool(self.term_tag and self.component_tag)
 
    @property
    def display_label(self):
        """
        Short label used in the column header tooltip and student grade view.
        e.g.  "Prelims · Quizzes"
        """
        if self.is_tagged:
            return f"{self.term_tag} · {self.component_tag}"
        return self.title
 
    def __repr__(self):
        tag = f" [{self.term_tag}/{self.component_tag}]" if self.is_tagged else ""
        return f'<Test {self.title}{tag} Class:{self.class_id}>'

class Grade(db.Model):
    """
    Grade - Stores one student's score for one test/activity.

    METHOD 2 GRADING:

        Test
            ↓
        Grade.raw_score / Grade.max_score
            ↓
        Grade.calculated_percentage
            ↓
        recalculate_term_grade()
            ↓
        Philippine term grade
            ↓
        _update_enrollment_average()
            ↓
        Enrollment.final_grade

    IMPORTANT:
        Grade does NOT represent the student's overall class grade.

        Enrollment.final_grade is the official overall grade
        for the student's class enrollment.

    LEGACY:
        component_scores
        calculated_grade
        final_grade

        These columns are temporarily kept for database compatibility
        and can be removed later through a migration.

    OVERRIDE:
        Override fields are also temporarily kept until the override
        system is redesigned for Method 2.
    """

    __tablename__ = 'grade'

    # =========================================================
    # PRIMARY / FOREIGN KEYS
    # =========================================================

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    test_id = db.Column(
        db.Integer,
        db.ForeignKey('test.id'),
        nullable=False
    )

    student_id = db.Column(
        db.Integer,
        db.ForeignKey('student.id'),
        nullable=False,
        index=True
    )

    # =========================================================
    # METHOD 2 SCORE DATA
    # =========================================================

    # Student's actual score for this test/activity.
    raw_score = db.Column(
        db.Float,
        nullable=True
    )

    # Maximum possible score for this test/activity.
    max_score = db.Column(
        db.Float,
        nullable=True
    )

    # Individual test percentage:
    #
    #     raw_score / max_score * 100
    #
    # Example:
    #     18 / 20 = 90.00
    calculated_percentage = db.Column(
        db.Float,
        nullable=True
    )


    # =========================================================
    # OVERRIDE FIELDS
    # =========================================================
    #
    # Temporarily kept.
    #
    # We still need to decide whether overrides should apply to:
    #
    #   - individual test scores
    #   - term grades
    #   - Enrollment.final_grade
    #
    # Do not build new Method 2 logic around these yet.
    # =========================================================

    is_overridden = db.Column(
        db.Boolean,
        default=False
    )

    override_grade = db.Column(
        db.Float,
        nullable=True
    )

    override_reason = db.Column(
        db.Text,
        nullable=True
    )

    # =========================================================
    # GRADING METADATA
    # =========================================================

    graded_by = db.Column(
        db.Integer,
        db.ForeignKey('teacher.id'),
        nullable=True
    )

    graded_at = db.Column(
        db.DateTime,
        nullable=True
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    # =========================================================
    # DISPLAY
    # =========================================================

    def __repr__(self):
        return (
            f'<Grade '
            f'Student:{self.student_id} '
            f'Test:{self.test_id} '
            f'Score:{self.raw_score}/{self.max_score}>'
        )

    # =========================================================
    # TEMPORARY OVERRIDE METHODS
    # =========================================================
    #
    # These are retained temporarily for compatibility.
    #
    # They still use Grade.final_grade, which is a legacy field.
    # We will redesign this after the core Method 2 grading
    # architecture is fully cleaned up.
    # =========================================================

    def set_override(self, grade, reason, teacher_id):
        """
        Temporarily store an override value.

        NOTE:
        Override handling will be redesigned later for Method 2.
        This method no longer writes to Grade.final_grade.
        """

        self.is_overridden = True
        self.override_grade = grade
        self.override_reason = reason
        self.graded_by = teacher_id
        self.graded_at = datetime.utcnow()


    def remove_override(self):
        """
        Remove the temporary override metadata.

        Does not modify Grade.final_grade because that field
        is no longer part of the Method 2 grading flow.
        """

        self.is_overridden = False
        self.override_grade = None
        self.override_reason = None

class TestPaperImage(db.Model):
    """
    TestPaperImage — Stores uploaded test paper images from the AI pipeline.
 
    Lifecycle of a record:
        1. 'pending'   → Image uploaded, pipeline running or just finished,
                         not yet assigned to a student.
        2. 'uncertain' → Pipeline ran but OCR name confidence is LOW (<85%).
                         Teacher must manually confirm the suggested student.
        3. 'assigned'  → Teacher has confirmed which student owns this paper.
        4. 'error'     → Pipeline crashed on this specific image. The image
                         file is still saved; teacher can retry or reassign.
 
    Assignment confidence levels (stored in match_confidence):
        >= 85  → HIGH   — auto-suggested, teacher just clicks confirm
        50–84  → MEDIUM — flagged as uncertain, teacher must actively pick
        <  50  → LOW    — treated as unassigned, no suggestion shown
        None   → OCR returned null/garbage, skip fuzzy match entirely
    """
 
    __tablename__ = 'test_paper_image'
 
    id = db.Column(db.Integer, primary_key=True)
 
    # ── Foreign Keys ──────────────────────────────────────────────────────────
    test_id = db.Column(
        db.Integer,
        db.ForeignKey('test.id'),
        nullable=False,
        index=True
    )
    # Null until the professor confirms which student owns this paper
    student_id = db.Column(
        db.Integer,
        db.ForeignKey('student.id'),
        nullable=True,
        index=True
    )
    # Teacher who uploaded the batch
    uploaded_by = db.Column(
        db.Integer,
        db.ForeignKey('teacher.id'),
        nullable=False
    )
 
    # ── File Storage ──────────────────────────────────────────────────────────
    # Relative path from your app's UPLOAD_FOLDER, e.g.:
    #   "test_papers/2025/class_3/test_7/hazel.png"
    image_path = db.Column(db.String(500), nullable=False)
 
    # Original filename as uploaded by the professor
    original_filename = db.Column(db.String(255), nullable=False)
 
    # ── Pipeline / OCR Output (raw from your JSON) ────────────────────────────
    ocr_name  = db.Column(db.String(300), nullable=True)   # raw OCR name field
    ocr_score = db.Column(db.String(50),  nullable=True)   # e.g. "23/100"
    ocr_label = db.Column(db.String(500), nullable=True)   # exam label/title
    ocr_raw_json = db.Column(db.Text,     nullable=True)   # full JSON blob from pipeline
 
    # ── Matching / Assignment ─────────────────────────────────────────────────
    # 0–100 fuzzy match score. None = OCR returned null/garbage.
    match_confidence = db.Column(db.Float, nullable=True)
 
    # Best-guess student_id from fuzzy matching (before teacher confirms).
    # This is the SUGGESTION. student_id above is the CONFIRMED assignment.
    suggested_student_id = db.Column(
        db.Integer,
        db.ForeignKey('student.id'),
        nullable=True
    )
 
    # ── Status ────────────────────────────────────────────────────────────────
    # 'pending' | 'uncertain' | 'assigned' | 'error'
    status = db.Column(db.String(20), nullable=False, default='pending', index=True)
 
    # Human-readable error message if status == 'error'
    error_message = db.Column(db.Text, nullable=True)
 
    # ── Timestamps ────────────────────────────────────────────────────────────
    uploaded_at  = db.Column(db.DateTime, default=datetime.utcnow)
    assigned_at  = db.Column(db.DateTime, nullable=True)   # when teacher confirmed
    processed_at = db.Column(db.DateTime, nullable=True)   # when pipeline finished
 
    # ── Relationships ─────────────────────────────────────────────────────────
    test              = db.relationship('Test',    backref='paper_images',    foreign_keys=[test_id])
    student           = db.relationship('Student', backref='paper_images',    foreign_keys=[student_id])
    suggested_student = db.relationship('Student', foreign_keys=[suggested_student_id])
    uploader          = db.relationship('Teacher', backref='uploaded_papers', foreign_keys=[uploaded_by])
 
    # ── Helpers ───────────────────────────────────────────────────────────────
 
    @property
    def confidence_tier(self):
        """
        Returns a human-readable tier based on match_confidence.
        Used by the template to decide which UI badge/colour to show.
        """
        if self.match_confidence is None:
            return 'none'          # OCR returned null/garbage
        if self.match_confidence >= 85:
            return 'high'          # green  — auto-suggest, professor confirms
        if self.match_confidence >= 50:
            return 'medium'        # yellow — uncertain, professor must pick
        return 'low'               # red    — no useful guess, treat as unassigned
 
    @property
    def display_status(self):
        """Friendly label for the UI."""
        return {
            'pending':   '⏳ Pending Review',
            'uncertain': '⚠️ Uncertain — Verify',
            'assigned':  '✅ Assigned',
            'error':     '❌ Pipeline Error',
        }.get(self.status, self.status)
 
    def assign_to_student(self, student_id):
        """
        Confirm assignment to a student.
        Call this when the teacher clicks 'Confirm' or picks from the dropdown.
        Raises ValueError if student_id is already assigned to another image
        in the same test (duplicate-assignment guard).
        """
        # Duplicate guard — one paper per student per test
        existing = TestPaperImage.query.filter(
            TestPaperImage.test_id    == self.test_id,
            TestPaperImage.student_id == student_id,
            TestPaperImage.id         != self.id,         # not this record itself
            TestPaperImage.status     == 'assigned'
        ).first()
 
        if existing:
            raise ValueError(
                f"Student ID {student_id} already has an assigned paper "
                f"for this test (image ID {existing.id}: {existing.original_filename})."
            )
 
        self.student_id  = student_id
        self.status      = 'assigned'
        self.assigned_at = datetime.utcnow()
 
    def mark_error(self, message):
        """Mark this image as failed during pipeline processing."""
        self.status        = 'error'
        self.error_message = message
        self.processed_at  = datetime.utcnow()
 
    def mark_processed(self, ocr_name, ocr_score, ocr_label, raw_json,
                       suggested_student_id=None, match_confidence=None):
        """
        Call this after the pipeline finishes for this image.
        Sets OCR fields and determines initial status automatically.
        """
        self.ocr_name             = ocr_name
        self.ocr_score            = ocr_score
        self.ocr_label            = ocr_label
        self.ocr_raw_json         = raw_json
        self.suggested_student_id = suggested_student_id
        self.match_confidence     = match_confidence
        self.processed_at         = datetime.utcnow()
 
        # Auto-set status from confidence tier
        tier = self.confidence_tier
        if tier == 'high':
            self.status = 'pending'     # still needs teacher confirm, but pre-filled
        elif tier in ('medium', 'low', 'none'):
            self.status = 'uncertain'   # explicitly flag for manual review
 
    def get_image_url(self):
        """
        Returns the URL path for serving the image.
        Assumes Flask serves uploaded files under /uploads/<image_path>.
        Adjust the prefix to match your app.config['UPLOAD_FOLDER'] setup.
        """
        return f"/uploads/{self.image_path}"
 
    def __repr__(self):
        return (
            f"<TestPaperImage id={self.id} file='{self.original_filename}' "
            f"status='{self.status}' confidence={self.match_confidence}>"
        )

class SystemSettings(db.Model):
    """
    System-wide settings stored in database
    Allows admin to override auto-calculated values
    """
    __tablename__ = 'system_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    setting_key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    setting_value = db.Column(db.String(200), nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.String(100), nullable=True)  # Email of admin who updated
    
    def __repr__(self):
        return f'<SystemSettings {self.setting_key}={self.setting_value}>'
    
    @staticmethod
    def get_setting(key, default=None):
        """
        Get a setting value from database
        Returns None if not found
        """
        setting = SystemSettings.query.filter_by(setting_key=key).first()
        return setting.setting_value if setting else default
    
    @staticmethod
    def set_setting(key, value, updated_by=None):
        """
        Set a setting value in database
        Creates new setting if doesn't exist
        """
        setting = SystemSettings.query.filter_by(setting_key=key).first()
        if setting:
            setting.setting_value = value
            setting.updated_at = datetime.utcnow()
            setting.updated_by = updated_by
        else:
            setting = SystemSettings(
                setting_key=key,
                setting_value=value,
                updated_by=updated_by
            )
            db.session.add(setting)
        db.session.commit()
        return setting
    
    @staticmethod
    def delete_setting(key):
        """Delete a setting (revert to auto-calculation)"""
        setting = SystemSettings.query.filter_by(setting_key=key).first()
        if setting:
            db.session.delete(setting)
            db.session.commit()
            return True
        return False