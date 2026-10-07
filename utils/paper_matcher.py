"""
utils/paper_matcher.py — Fuzzy Name Matching for Test Paper Assignment
=======================================================================

Place this file at:   your_project/utils/paper_matcher.py

Install dependency:
    pip install rapidfuzz

Usage example (in your Flask route):
    from utils.paper_matcher import match_ocr_name_to_student

    result = match_ocr_name_to_student(
        ocr_name   = paper_result["name"],      # from your pipeline JSON
        class_id   = selected_class.id,
        db_session = db.session
    )

    image_record.suggested_student_id = result["student_id"]
    image_record.match_confidence      = result["confidence"]
    image_record.mark_processed(
        ocr_name             = paper_result["name"],
        ocr_score            = paper_result["score"],
        ocr_label            = paper_result["label"],
        raw_json             = json.dumps(paper_result),
        suggested_student_id = result["student_id"],
        match_confidence     = result["confidence"],
    )
"""

import re
import unicodedata
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Confidence Thresholds ─────────────────────────────────────────────────────
CONFIDENCE_HIGH   = 85   # Auto-suggest; teacher just confirms
CONFIDENCE_MEDIUM = 50   # Uncertain; teacher must actively pick
# Below CONFIDENCE_MEDIUM → 'low' tier → treated as unassigned (no suggestion)


# ── Name Normalisation ────────────────────────────────────────────────────────

def _normalise(text: str) -> str:
    """
    Aggressively clean a name string so fuzzy matching is
    not thrown off by:
      • accents / diacritics        (Réyes → Reyes)
      • extra whitespace / newlines
      • common OCR noise chars      (# _ | \ /)
      • "Name:" prefixes the OCR sometimes picks up
      • inconsistent comma/period placement
    """
    if not text:
        return ""

    # Unicode normalise + strip combining chars (accents)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))

    # Lower-case for comparison
    text = text.lower()

    # Remove "name:" prefix that OCR sometimes includes
    text = re.sub(r"^name\s*[:\-]\s*", "", text)

    # Strip common OCR noise characters
    text = re.sub(r"[#_|\\\/\[\]{}]", " ", text)

    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()

    return text


def _is_usable(text: Optional[str]) -> bool:
    """
    Return False if the OCR name is null, empty, or clearly garbage.
    'Clearly garbage' = fewer than 3 alphabetic characters after cleaning.
    Examples that fail:
        None, "", "??", "____", "###", "N/A", "  ", "1234"
    """
    if not text:
        return False

    cleaned = _normalise(text)
    alpha_chars = [c for c in cleaned if c.isalpha()]
    return len(alpha_chars) >= 3


# ── Main Matching Function ────────────────────────────────────────────────────

def match_ocr_name_to_student(
    ocr_name: Optional[str],
    class_id: int,
    db_session,
    already_assigned_student_ids: Optional[set] = None
) -> dict:
    """
    Match an OCR-extracted name to an enrolled student in the given class.

    Parameters
    ----------
    ocr_name : str | None
        The raw name string from your pipeline JSON.
        Can be None, empty, or garbage — all handled gracefully.

    class_id : int
        The Class.id to scope the search to enrolled students only.

    db_session :
        Pass db.session from your Flask app.

    already_assigned_student_ids : set | None
        Optional set of student IDs already confirmed in this batch upload.
        Prevents the same student being suggested twice in one batch.

    Returns
    -------
    dict with keys:
        student_id  : int | None   — best-match student ID, or None
        confidence  : float | None — 0–100 score, or None if OCR unusable
        tier        : str          — 'high' | 'medium' | 'low' | 'none'
        matched_name: str | None   — the student's full name that was matched
        reason      : str          — human-readable explanation (for logs/UI)

    This function NEVER raises — all errors are caught and returned
    as tier='none' with a reason string.
    """

    already_assigned = already_assigned_student_ids or set()

    # ── Step 1: Check if OCR name is usable at all ────────────────────────────
    if not _is_usable(ocr_name):
        logger.info(
            "paper_matcher: OCR name unusable (null/garbage): %r — skipping fuzzy match",
            ocr_name
        )
        return {
            "student_id":   None,
            "confidence":   None,
            "tier":         "none",
            "matched_name": None,
            "reason":       f"OCR name is null or unreadable ({ocr_name!r}). "
                            "Teacher must assign manually."
        }

    # ── Step 2: Load enrolled students for this class ─────────────────────────
    try:
        # Import here to avoid circular imports at module level
        from models import Enrollment, Student

        enrollments = (
            db_session.query(Enrollment)
            .filter_by(class_id=class_id, status='enrolled')
            .join(Student)
            .all()
        )

        if not enrollments:
            logger.warning(
                "paper_matcher: No enrolled students found for class_id=%s", class_id
            )
            return {
                "student_id":   None,
                "confidence":   None,
                "tier":         "none",
                "matched_name": None,
                "reason":       "No enrolled students found for this class."
            }

    except Exception as exc:
        logger.error("paper_matcher: DB error loading enrollments: %s", exc, exc_info=True)
        return {
            "student_id":   None,
            "confidence":   None,
            "tier":         "none",
            "matched_name": None,
            "reason":       f"Database error while loading students: {exc}"
        }

    # ── Step 3: Build candidate list ─────────────────────────────────────────
    # Each candidate is (student_id, normalised_full_name, display_name)
    candidates = []
    for enr in enrollments:
        s = enr.student
        # Skip already-confirmed students in this upload batch
        if s.id in already_assigned:
            continue

        # Build multiple name formats to maximise match chance:
        #   "Juan dela Cruz"  →  "juan dela cruz"
        #   "dela Cruz, Juan" →  "dela cruz, juan"
        #   "JDC"            →  not added (too short, already filtered above)
        full_name_firstlast = f"{s.first_name} {s.last_name}"
        full_name_lastfirst = f"{s.last_name}, {s.first_name}"

        candidates.append((s.id, _normalise(full_name_firstlast), full_name_firstlast))
        candidates.append((s.id, _normalise(full_name_lastfirst), full_name_firstlast))

    if not candidates:
        return {
            "student_id":   None,
            "confidence":   None,
            "tier":         "none",
            "matched_name": None,
            "reason":       "All enrolled students are already assigned in this batch."
        }

    # ── Step 4: Fuzzy match ───────────────────────────────────────────────────
    try:
        from rapidfuzz import fuzz, process as fuzz_process

        query = _normalise(ocr_name)

        # extract_one returns (match_string, score, index)
        # We use token_sort_ratio because name order (last,first vs first last)
        # should not heavily penalise the score.
        best = fuzz_process.extractOne(
            query,
            [c[1] for c in candidates],    # list of normalised names
            scorer=fuzz.token_sort_ratio,
            score_cutoff=0                  # 0 = always return something
        )

        if best is None:
            # Should not happen with score_cutoff=0, but guard anyway
            raise ValueError("rapidfuzz returned None unexpectedly")

        best_name_normalised, score, idx = best
        matched_student_id, _, matched_display_name = candidates[idx]

    except ImportError:
        logger.error(
            "paper_matcher: 'rapidfuzz' is not installed. "
            "Run: pip install rapidfuzz"
        )
        return {
            "student_id":   None,
            "confidence":   None,
            "tier":         "none",
            "matched_name": None,
            "reason":       "rapidfuzz library not installed. Run: pip install rapidfuzz"
        }
    except Exception as exc:
        logger.error("paper_matcher: Fuzzy match error: %s", exc, exc_info=True)
        return {
            "student_id":   None,
            "confidence":   None,
            "tier":         "none",
            "matched_name": None,
            "reason":       f"Fuzzy matching error: {exc}"
        }

    # ── Step 5: Apply confidence thresholds ───────────────────────────────────
    score = float(score)

    if score >= CONFIDENCE_HIGH:
        tier = "high"
        reason = (
            f"High confidence ({score:.1f}%): OCR '{ocr_name}' → '{matched_display_name}'. "
            "Auto-suggested; professor should confirm."
        )
    elif score >= CONFIDENCE_MEDIUM:
        tier = "medium"
        reason = (
            f"Uncertain ({score:.1f}%): OCR '{ocr_name}' loosely matches "
            f"'{matched_display_name}'. Teacher must verify."
        )
    else:
        # Score too low — don't suggest anyone, avoid misleading the teacher
        tier = "low"
        reason = (
            f"Low confidence ({score:.1f}%): best guess was '{matched_display_name}' "
            f"but score is below threshold. Treated as unassigned."
        )
        matched_student_id = None

    logger.info(
        "paper_matcher: '%s' → '%s' | score=%.1f | tier=%s",
        ocr_name, matched_display_name, score, tier
    )

    return {
        "student_id":   matched_student_id,
        "confidence":   score,
        "tier":         tier,
        "matched_name": matched_display_name,
        "reason":       reason
    }


# ── Batch Helper ──────────────────────────────────────────────────────────────

def match_batch(pipeline_results: list, class_id: int, db_session) -> list:
    """
    Run match_ocr_name_to_student for an entire pipeline output list.
    Tracks already-suggested students across the batch so the same student
    is never suggested twice (prevents accidental double-assignment).

    Parameters
    ----------
    pipeline_results : list of dicts
        Your pipeline's JSON output, e.g.:
        [
            {"paper": "hazel.png", "name": "Hazel Ann O. Reyes",
             "score": "23/100", "label": "Final Exam Set D ..."},
            ...
        ]

    Returns
    -------
    list of dicts — one per paper, same order as input, with added keys:
        "match_result": the dict returned by match_ocr_name_to_student
    """
    results = []
    confirmed_ids: set = set()   # grows as high-confidence matches are found

    for paper in pipeline_results:
        match = match_ocr_name_to_student(
            ocr_name                    = paper.get("name"),
            class_id                    = class_id,
            db_session                  = db_session,
            already_assigned_student_ids = confirmed_ids
        )

        # Reserve high-confidence matches so they won't be suggested again
        if match["tier"] == "high" and match["student_id"] is not None:
            confirmed_ids.add(match["student_id"])

        results.append({**paper, "match_result": match})

    return results