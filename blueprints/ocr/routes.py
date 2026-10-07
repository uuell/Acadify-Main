"""
blueprints/ocr/routes.py
========================
Single-page AI Grading — all upload/review functionality lives at /ocr/ai-grading.
The old /ocr/review/<test_id> page route is removed.
API endpoints (upload, confirm, batch, image serve, retry) are unchanged.
"""

import os
import json
import uuid
import time
import re
import unicodedata
import logging
from datetime import datetime

from flask import (
    Blueprint,
    request,
    jsonify,
    url_for,
    send_file
)
from flask_login import current_user
from werkzeug.utils import secure_filename

from extensions import db
from models import Teacher, Class, Enrollment, Student, Test, Grade, TestPaperImage
from config import Config

logger = logging.getLogger(__name__)

ocr_bp = Blueprint('ocr', __name__)

# ── Constants ─────────────────────────────────────────────────────────────────
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
DATALAB_URL        = "https://www.datalab.to/api/v1/convert"
DATALAB_API_KEY    = os.environ.get('DATALAB_API_KEY')
YOLO_MODEL_PATH    = os.environ.get('YOLO_MODEL_PATH')
ULTRALYTICS_API_KEY = os.environ.get('ULTRALYTICS_API_KEY')
ULTRALYTICS_HUB_URL = "https://predict-69c213e2c6ccc1895d3a-dproatj77a-as.a.run.app/predict"
CLASS_NAMES        = ['label', 'name', 'score']
OCR_POLL_INTERVAL  = 2
OCR_MAX_POLLS      = 150

# ── Auth decorator ────────────────────────────────────────────────────────────
def teacher_required(f):
    from functools import wraps

    @wraps(f)
    def decorated(*args, **kwargs):

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

    return decorated


# ── Helpers ───────────────────────────────────────────────────────────────────
def _allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def _paper_upload_folder(test_id):
    folder = os.path.join(Config.UPLOAD_FOLDER, 'test_papers', str(test_id))
    os.makedirs(folder, exist_ok=True)
    return folder

def _clean_text(text, field):
    if text is None:
        return None
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("#", "").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    if field == "name":
        text = re.sub(r"(?i)name\s*:\s*", "", text)
    if field == "score":
        match = re.search(
            r'\d+(?:\.\d+)?\s*/\s*\d+(?:\.\d+)?',
            text
        )
        text = match.group() if match else None
    return text or None

def _run_ocr_on_crop(crop_path, field):
    import requests as req
    if not DATALAB_API_KEY:
        return None
    headers = {"X-API-Key": DATALAB_API_KEY}
    payload = {"mode": "balanced", "output_format": "markdown",
                "token_efficient_markdown": "true"}
    try:
        with open(crop_path, "rb") as f:
            files = {"file": (os.path.basename(crop_path), f, "image/png")}
            resp = req.post(DATALAB_URL, data=payload, files=files,
                            headers=headers, timeout=30)
        resp.raise_for_status()
        check_url = resp.json().get("request_check_url")
        if not check_url:
            return None
    except Exception as exc:
        logger.error("OCR submit error: %s", exc)
        return None
    for _ in range(OCR_MAX_POLLS):
        try:
            poll = req.get(check_url, headers=headers, timeout=15)
            result = poll.json()
            if result.get("status") == "complete":
                return _clean_text(result.get("markdown", "").strip(), field)
            if result.get("status") == "failed":
                return None
        except Exception:
            pass
        time.sleep(OCR_POLL_INTERVAL)
    return None

def _run_pipeline_on_image(image_path, crop_folder):
    """
    Calls the ULTRALYTICS HUB API instead of running locally.
    Then crops and sends to Surya OCR.
    """
    import requests as req
    import cv2
    
    result = {"name": None, "score": None, "label": None, "error": None}
    
    # 1. Load image locally for cropping
    image = cv2.imread(image_path)
    if image is None:
        result["error"] = "Could not read image for cropping"
        return result

    # 2. Call Ultralytics Hub API
    try:
        yolo_args = {"conf": 0.6, "iou": 0.45, "imgsz": 640}
        with open(image_path, "rb") as f:
            resp = req.post(
                ULTRALYTICS_HUB_URL,
                headers={"x-api-key": ULTRALYTICS_API_KEY},
                data=yolo_args,
                files={"file": f},
                timeout=30
            )
        resp.raise_for_status()
        yolo_data = resp.json()
        
        # The Hub response structure is: {'images': [{'results': [...]}]}
        detections = yolo_data['images'][0]['results']
        
    except Exception as exc:
        logger.error("Ultralytics Hub API failed: %s", exc)
        result["error"] = f"Cloud YOLO failed: {exc}"
        return result

    if not detections:
        result["error"] = "No sections detected by Hub model"
        return result

    # 3. Process Detections & Run OCR
    for det in detections:
        class_name = det['name'] # 'label', 'name', or 'score'
        if class_name not in CLASS_NAMES:
            continue
            
        box = det['box']
        # Hub returns a dict: {'x1': ..., 'y1': ..., 'x2': ..., 'y2': ...}
        x1, y1 = int(box['x1']), int(box['y1'])
        x2, y2 = int(box['x2']), int(box['y2'])
        
        # Ensure coordinates are within image bounds
        h, w = image.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)

        crop = image[y1:y2, x1:x2]
        crop_path = os.path.join(crop_folder, f"{uuid.uuid4().hex}_{class_name}.png")
        
        try:
            cv2.imwrite(crop_path, crop)
            # Pass the cropped image to your existing Surya OCR helper
            result[class_name] = _run_ocr_on_crop(crop_path, class_name)
        except Exception as exc:
            logger.error("OCR error for %s: %s", class_name, exc)
        finally:
            if os.path.exists(crop_path):
                os.remove(crop_path)
                
    return result

def _write_grade_from_ocr(img_record, student_id, teacher_id):
    """
    Save an OCR-detected score using the Method 2 grading flow.

    OCR score:
        raw_score / max_score
                ↓
        Grade.calculated_percentage
                ↓
        recalculate_term_grade()
                ↓
        _update_enrollment_average()
                ↓
        Enrollment.final_grade
    """

    # ---------------------------------------------------------
    # Validate OCR score
    # ---------------------------------------------------------

    if not img_record.ocr_score:
        return False


    match = re.match(
        r'(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)',
        img_record.ocr_score
    )

    if not match:
        return False

    raw_score = float(match.group(1))
    max_score = float(match.group(2))

    if max_score <= 0:
        return False

    if raw_score < 0 or raw_score > max_score:
        return False

    # ---------------------------------------------------------
    # Get the related test
    # ---------------------------------------------------------

    test = img_record.test

    if not test:
        return False

    # Method 2 requires both tags
    if not test.term_tag or not test.component_tag:
        logger.warning(
            "OCR grade skipped: test %s has no term/component tags",
            test.id
        )
        return False

    # ---------------------------------------------------------
    # Find or create Grade
    # ---------------------------------------------------------

    grade = Grade.query.filter_by(
        test_id=img_record.test_id,
        student_id=student_id
    ).first()

    if not grade:
        grade = Grade(
            test_id=img_record.test_id,
            student_id=student_id,
            graded_by=teacher_id
        )

        db.session.add(grade)

    # ---------------------------------------------------------
    # Save Method 2 score
    # ---------------------------------------------------------

    grade.raw_score = raw_score
    grade.max_score = max_score

    grade.calculated_percentage = round(
        (raw_score / max_score) * 100,
        2
    )

    grade.graded_by = teacher_id
    grade.graded_at = datetime.utcnow()

    # Flush so the Grade exists for term recalculation
    db.session.flush()

    # ---------------------------------------------------------
    # Recalculate term + overall class grade
    # ---------------------------------------------------------

    try:
        from blueprints.teacher.routes import (
            recalculate_term_grade,
            _update_enrollment_average
        )

        recalculate_term_grade(
            student_id=student_id,
            class_id=test.class_id,
            term_tag=test.term_tag,
            teacher_id=teacher_id,
            commit=False
        )

        _update_enrollment_average(
            student_id,
            test.class_id
        )

    except Exception as exc:
        logger.warning(
            "OCR term/final grade recalculation failed: %s",
            exc
        )

    return True

def _build_papers_json(images, class_id):
    """Build JSON list of paper cards for the given test images."""
    enrollments = Enrollment.query.filter_by(
        class_id=class_id, status='enrolled'
    ).join(Student).all()
    student_map = {e.student.id: e.student for e in enrollments}

    items = []
    for img in images:
        suggested = student_map.get(img.suggested_student_id)
        items.append({
            'image_id':          img.id,
            'original_filename': img.original_filename,
            'image_url':         url_for('ocr.paper_image', img_id=img.id),
            'ocr_name':          img.ocr_name,
            'ocr_score':         img.ocr_score,
            'ocr_label':         img.ocr_label,
            'status':            img.status,
            'display_status':    img.display_status,
            'confidence':        img.match_confidence,
            'confidence_tier':   img.confidence_tier,
            'suggested_student_id':   img.suggested_student_id,
            'suggested_student_name': (
                f"{suggested.last_name}, {suggested.first_name}"
                if suggested else None
            ),
            'error_message': img.error_message,
        })
    return items


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE 1  —  Single-page AI Grading  GET /ocr/ai-grading
# ═════════════════════════════════════════════════════════════════════════════

@ocr_bp.route('/ai-grading')
@teacher_required
def ai_grading():
    teacher = current_user.teacher_profile

    teacher_classes = (
        Class.query
        .filter_by(teacher_id=teacher.id)
        .order_by(
            Class.school_year.desc(),
            Class.semester
        )
        .all()
    )

    classes_data = []

    for cls in teacher_classes:
        tests = (
            Test.query
            .filter_by(class_id=cls.id)
            .order_by(Test.created_at.desc())
            .all()
        )

        classes_data.append({
            'id': cls.id,
            'subject_name': cls.effective_subject_name,
            'subject_code': cls.effective_subject_code,
            'section': cls.section,
            'school_year': cls.school_year,
            'semester': cls.semester,
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
            ]
        })

    preselected_test = None
    initial_papers = []
    initial_students = []

    test_id = request.args.get('test_id', type=int)

    if test_id:
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
                'message': 'Test not found.'
            }), 404

        preselected_test = {
            'id': test.id,
            'title': test.title,
            'class_id': test.class_id,
            'term_tag': test.term_tag,
            'component_tag': test.component_tag
        }

        papers = TestPaperImage.query.filter_by(
            test_id=test_id
        ).all()

        initial_papers = _build_papers_json(
            papers,
            test.class_id
        )

        enrollments = (
            Enrollment.query
            .filter_by(
                class_id=test.class_id,
                status='enrolled'
            )
            .join(Student)
            .order_by(
                Student.last_name,
                Student.first_name
            )
            .all()
        )

        initial_students = [
            {
                'id': e.student.id,
                'student_number': e.student.student_number,
                'name': (
                    f'{e.student.last_name}, '
                    f'{e.student.first_name}'
                )
            }
            for e in enrollments
        ]

    return jsonify({
        'success': True,

        'current_period': {
            'school_year': Config.get_current_school_year(),
            'semester': Config.get_current_semester()
        },

        'classes': classes_data,

        'preselected_test': preselected_test,

        'initial_papers': initial_papers,

        'initial_students': initial_students
    }), 200


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE 2  —  API: get papers + students for a test  GET /ocr/test-papers/<id>
# ═════════════════════════════════════════════════════════════════════════════

@ocr_bp.route('/test-papers/<int:test_id>')
@teacher_required
def get_test_papers(test_id):
    """
    Returns existing paper images and enrolled students for a test.
    Called by JS when the professor selects a test from the dropdown.
    """
    teacher = current_user.teacher_profile

    test = Test.query.join(Class).filter(
        Test.id == test_id,
        Class.teacher_id == teacher.id
    ).first()
    if not test:
        return jsonify({'success': False, 'error': 'Test not found'}), 404

    images = TestPaperImage.query.filter_by(test_id=test_id).all()
    papers = _build_papers_json(images, test.class_id)

    enrollments = Enrollment.query.filter_by(
        class_id=test.class_id, status='enrolled'
    ).join(Student).order_by(Student.last_name, Student.first_name).all()

    students = [
        {
            'id':      e.student.id,
            'display': f"{e.student.last_name}, {e.student.first_name} "
                       f"({e.student.student_number})"
        }
        for e in enrollments
    ]

    return jsonify({
        'success':  True,
        'papers':   papers,
        'students': students,
        'test_title': test.title,
        'class_name': test.class_.get_display_name(),
    })


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE 3  —  Upload + pipeline  POST /ocr/upload-papers
# ═════════════════════════════════════════════════════════════════════════════

@ocr_bp.route('/upload-papers', methods=['POST'])
@teacher_required
def upload_papers():
    teacher = current_user.teacher_profile
    test_id = request.form.get('test_id', type=int)
    if not test_id:
        return jsonify({'success': False, 'error': 'test_id required'}), 400

    test = Test.query.join(Class).filter(
        Test.id == test_id, Class.teacher_id == teacher.id
    ).first()
    if not test:
        return jsonify({'success': False, 'error': 'Test not found'}), 404

    files = request.files.getlist('files[]')
    if not files or all(f.filename == '' for f in files):
        return jsonify({'success': False, 'error': 'No files selected'}), 400

    upload_folder = _paper_upload_folder(test_id)
    crop_folder   = os.path.join(upload_folder, '_crops')
    os.makedirs(crop_folder, exist_ok=True)

    batch_results = []
    image_records = []
    skipped_duplicates = []

    # Phase 1: save files + create DB records
    for f in files:
        if f.filename == '' or not _allowed_file(f.filename):
            continue
        original_name = secure_filename(f.filename)

        # ── Duplicate check ───────────────────────────────────────────────────
        existing = TestPaperImage.query.filter_by(
            test_id=test_id,
            original_filename=original_name
        ).first()
        if existing:
            skipped_duplicates.append(original_name)
            logger.info("Skipping duplicate file: %s (already exists as image ID %s)",
                        original_name, existing.id)
            continue
        # ─────────────────────────────────────────────────────────────────────

        stored_name   = f"{uuid.uuid4().hex}_{original_name}"
        full_path     = os.path.join(upload_folder, stored_name)
        rel_path      = os.path.join('test_papers', str(test_id), stored_name)
        try:
            f.save(full_path)
        except Exception as exc:
            logger.error("Save failed %s: %s", original_name, exc)
            continue
        img = TestPaperImage(
            test_id=test_id, uploaded_by=teacher.id,
            image_path=rel_path, original_filename=original_name,
            status='pending', uploaded_at=datetime.utcnow()
        )
        db.session.add(img)
        image_records.append((img, full_path, original_name))

    if not image_records:
        return jsonify({'success': False, 'error': 'No valid images'}), 400

    db.session.commit()

    # Phase 2: run pipeline
    for img, full_path, original_name in image_records:
        try:
            out = _run_pipeline_on_image(full_path, crop_folder)
            batch_results.append({
                'paper':   original_name,
                'name':    out.get('name'),
                'score':   out.get('score'),
                'label':   out.get('label'),
                '_img_id': img.id,
                '_error':  out.get('error')
            })
            if out.get('error'):
                img.mark_error(out['error'])
        except Exception as exc:
            img.mark_error(str(exc))
            batch_results.append({
                'paper': original_name, 'name': None,
                'score': None, 'label': None,
                '_img_id': img.id, '_error': str(exc)
            })

    # Phase 3: fuzzy match
    try:
        from utils.paper_matcher import match_batch
        matched = match_batch(batch_results, test.class_id, db.session)
    except Exception as exc:
        logger.error("match_batch failed: %s", exc)
        matched = [{**r, 'match_result': {
            'student_id': None, 'confidence': None,
            'tier': 'none', 'matched_name': None,
            'reason': str(exc)
        }} for r in batch_results]

    # Phase 4: apply match results
    record_map = {img.id: img for img, _, _ in image_records}
    for item in matched:
        img_id = item.get('_img_id')
        match  = item.get('match_result', {})
        img    = record_map.get(img_id)
        if img is None or img.status == 'error':
            continue
        img.mark_processed(
            ocr_name=item.get('name'), ocr_score=item.get('score'),
            ocr_label=item.get('label'), raw_json=json.dumps(item),
            suggested_student_id=match.get('student_id'),
            match_confidence=match.get('confidence')
        )

    db.session.commit()

    try:
        import shutil
        shutil.rmtree(crop_folder, ignore_errors=True)
    except Exception:
        pass

    all_images = TestPaperImage.query.filter_by(test_id=test_id).all()
    return jsonify({
        'success':      True,
        'test_id':      test_id,
        'total':        len(image_records),
        'skipped_duplicates': skipped_duplicates,
        'review_items': _build_papers_json(all_images, test.class_id)
    })


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE 4  —  Confirm single  POST /ocr/confirm-assignment
# ═════════════════════════════════════════════════════════════════════════════

@ocr_bp.route('/confirm-assignment', methods=['POST'])
@teacher_required
def confirm_assignment():
    teacher = current_user.teacher_profile

    data = request.get_json(silent=True)

    if not data:
        return jsonify({
            'success': False,
            'error': 'Request body must contain JSON data.'
        }), 400

    image_id = data.get('image_id')
    student_id = data.get('student_id')

    if not image_id or not student_id:
        return jsonify({
            'success': False,
            'error': 'image_id and student_id required'
        }), 400

    img = (
        TestPaperImage.query
        .join(Test)
        .join(Class)
        .filter(
            TestPaperImage.id == image_id,
            Class.teacher_id == teacher.id
        )
        .first()
    )

    if not img:
        return jsonify({
            'success': False,
            'error': 'Image not found'
        }), 404

    enrolled = Enrollment.query.filter_by(
        student_id=student_id,
        class_id=img.test.class_id,
        status='enrolled'
    ).first()

    if not enrolled:
        return jsonify({
            'success': False,
            'error': 'Student not enrolled in this class'
        }), 400

    try:
        img.assign_to_student(student_id)
    except ValueError as exc:
        return jsonify({
            'success': False,
            'error': str(exc)
        }), 409

    grade_written = _write_grade_from_ocr(
        img,
        student_id,
        teacher.id
    )

    db.session.commit()

    student = db.session.get(Student, student_id)

    return jsonify({
        'success': True,
        'image_id': image_id,
        'student_id': student_id,
        'student_name': (
            f'{student.last_name}, {student.first_name}'
        ),
        'grade_written': grade_written
    }), 200


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE 5  —  Confirm batch  POST /ocr/confirm-batch
# ═════════════════════════════════════════════════════════════════════════════
@ocr_bp.route('/confirm-batch', methods=['POST'])
@teacher_required
def confirm_batch():
    teacher = current_user.teacher_profile

    data = request.get_json(silent=True)

    if not data:
        return jsonify({
            'success': False,
            'error': 'Request body must contain JSON data.'
        }), 400

    test_id = data.get('test_id')
    assignments = data.get('assignments', [])

    if not test_id:
        return jsonify({
            'success': False,
            'error': 'test_id required'
        }), 400

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
            'error': 'Test not found'
        }), 404

    confirmed = 0
    skipped = 0
    errors = []
    seen = set()

    for item in assignments:
        image_id = item.get('image_id')
        student_id = item.get('student_id')

        if not image_id or not student_id:
            skipped += 1
            continue

        if student_id in seen:
            errors.append(
                f'Image {image_id}: duplicate student - skipped'
            )
            skipped += 1
            continue

        img = TestPaperImage.query.filter_by(
            id=image_id,
            test_id=test_id
        ).first()

        if not img:
            errors.append(
                f'Image {image_id}: image not found'
            )
            skipped += 1
            continue

        enrolled = Enrollment.query.filter_by(
            student_id=student_id,
            class_id=test.class_id,
            status='enrolled'
        ).first()

        if not enrolled:
            errors.append(
                f'Image {image_id}: student not enrolled'
            )
            skipped += 1
            continue

        try:
            img.assign_to_student(student_id)

            _write_grade_from_ocr(
                img,
                student_id,
                teacher.id
            )

            seen.add(student_id)
            confirmed += 1

        except ValueError as exc:
            errors.append(
                f'Image {image_id}: {exc}'
            )
            skipped += 1

    db.session.commit()

    return jsonify({
        'success': True,
        'confirmed': confirmed,
        'skipped': skipped,
        'errors': errors
    }), 200
    
# ═════════════════════════════════════════════════════════════════════════════
# ROUTE 6  —  Serve image  GET /ocr/paper-image/<img_id>
# ═════════════════════════════════════════════════════════════════════════════

@ocr_bp.route('/paper-image/<int:img_id>')
def paper_image(img_id):

    if not current_user.is_authenticated:
        return jsonify({
            'success': False,
            'message': 'Authentication required.'
        }), 401

    img = db.session.get(TestPaperImage, img_id)

    if not img:
        return jsonify({
            'success': False,
            'message': 'Image not found.'
        }), 404

    if current_user.role == 'teacher':

        test = (
            Test.query
            .join(Class)
            .filter(
                Test.id == img.test_id,
                Class.teacher_id ==
                    current_user.teacher_profile.id
            )
            .first()
        )

        if not test:
            return jsonify({
                'success': False,
                'message': 'Access denied.'
            }), 403

    elif current_user.role == 'student':

        if (
            img.student_id != current_user.student_profile.id
            or img.status != 'assigned'
        ):
            return jsonify({
                'success': False,
                'message': 'Access denied.'
            }), 403

    elif current_user.role != 'admin':

        return jsonify({
            'success': False,
            'message': 'Access denied.'
        }), 403

    full_path = os.path.join(
        Config.UPLOAD_FOLDER,
        img.image_path
    )

    if not os.path.exists(full_path):
        return jsonify({
            'success': False,
            'message': 'Image file not found.'
        }), 404

    return send_file(full_path)


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE 7  —  Retry  POST /ocr/retry/<img_id>
# ═════════════════════════════════════════════════════════════════════════════

@ocr_bp.route('/retry/<int:img_id>', methods=['POST'])
@teacher_required
def retry_pipeline(img_id):
    teacher = current_user.teacher_profile
    img = (
        TestPaperImage.query
        .join(Test)
        .join(Class)
        .filter(
            TestPaperImage.id == img_id,
            Class.teacher_id == teacher.id
        )
        .first()
    )

    if not img:
        return jsonify({
            'success': False,
            'error': 'Image not found.'
        }), 404

    full_path = os.path.join(Config.UPLOAD_FOLDER, img.image_path)
    if not os.path.exists(full_path):
        return jsonify({'success': False, 'error': 'File not found on disk'}), 404

    crop_folder = os.path.join(os.path.dirname(full_path), '_crops')
    os.makedirs(crop_folder, exist_ok=True)

    try:
        out = _run_pipeline_on_image(full_path, crop_folder)
        if out.get('error'):
            img.mark_error(out['error'])
            db.session.commit()
            return jsonify({
                'success': False,
                'error': out['error']
            }), 422

        try:
            from utils.paper_matcher import match_ocr_name_to_student
            match = match_ocr_name_to_student(
                out.get('name'), img.test.class_id, db.session)
        except Exception:
            match = {'student_id': None, 'confidence': None,
                     'tier': 'none', 'matched_name': None, 'reason': ''}

        img.status        = 'pending'
        img.error_message = None
        img.mark_processed(
            ocr_name=out.get('name'), ocr_score=out.get('score'),
            ocr_label=out.get('label'), raw_json=json.dumps(out),
            suggested_student_id=match.get('student_id'),
            match_confidence=match.get('confidence')
        )
        db.session.commit()
        return jsonify({'success': True, 'status': img.status,
                        'ocr_name': img.ocr_name, 'ocr_score': img.ocr_score})
    except Exception as exc:
        img.mark_error(str(exc))
        db.session.commit()
        return jsonify({'success': False, 'error': str(exc)}), 500


# ═══════════════════════════════════════════════════════════════════
# ROUTE 9  —  Delete paper image  DELETE /ocr/paper-image/<img_id>
# ═══════════════════════════════════════════════════════════════════

@ocr_bp.route('/paper-image/<int:img_id>/delete', methods=['POST'])
@teacher_required
def delete_paper_image(img_id):
    """
    Delete a TestPaperImage record and its file from disk.
    Only the teacher who uploaded it can delete it.
    Cannot delete an already-assigned image (grade would be orphaned).
    """
    teacher = current_user.teacher_profile

    img = TestPaperImage.query.join(Test).join(Class).filter(
        TestPaperImage.id == img_id,
        Class.teacher_id  == teacher.id
    ).first()

    if not img:
        return jsonify({'success': False, 'error': 'Image not found'}), 404

    if img.status == 'assigned':
        return jsonify({
            'success': False,
            'error':   'Cannot delete an assigned paper. '
                       'The student\'s grade is linked to this image. '
                       'Reassign it to a different student first, or '
                       'delete the grade manually.'
        }), 409

    # Delete file from disk
    full_path = os.path.join(Config.UPLOAD_FOLDER, img.image_path)
    if os.path.exists(full_path):
        try:
            os.remove(full_path)
        except OSError as exc:
            logger.warning("Could not delete file %s: %s", full_path, exc)

    # Delete DB record
    db.session.delete(img)
    db.session.commit()

    return jsonify({'success': True, 'image_id': img_id})