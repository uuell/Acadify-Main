
"""
blueprints/contact/routes.py
============================

Public contact form API for Acadify.

Endpoint:
    POST /contact

Uses Resend to deliver inquiries to the
Acadify development team's email address.
"""

import json
import os
import re

import requests
import resend

from extensions import limiter
from flask import (
    Blueprint,
    current_app,
    jsonify,
    request,
)


contact_bp = Blueprint("contact", __name__)


INQUIRY_TYPES = {
    "general": "General Inquiry",
    "technical": "Technical Support",
    "partnership": "School Partnership",
    "feedback": "Feedback & Suggestions",
    "privacy": "Privacy Inquiry",
    "other": "Other Inquiry",
}

VALID_ROLES = {
    "student",
    "teacher",
    "admin",
    "other",
}


def validate_contact_data(data):
    """
    Validate and normalize contact form data.

    Returns:
        (cleaned_data, error_message)
    """

    if not isinstance(data, dict):
        return None, "Invalid request body."

    fields = [
        "first_name",
        "last_name",
        "email",
        "role",
        "inquiry_type",
        "subject",
        "message",
    ]

    cleaned = {}

    for field in fields:
        value = data.get(field, "")

        if not isinstance(value, str):
            return None, f"Invalid value for {field}."

        cleaned[field] = value.strip()

    required_fields = [
        "first_name",
        "last_name",
        "email",
        "inquiry_type",
        "subject",
        "message",
    ]

    for field in required_fields:
        if not cleaned[field]:
            return None, (
                f"{field.replace('_', ' ').title()} "
                "is required."
            )

    limits = {
        "first_name": 100,
        "last_name": 100,
        "email": 254,
        "role": 30,
        "inquiry_type": 30,
        "subject": 150,
        "message": 5000,
    }

    for field, limit in limits.items():
        if len(cleaned[field]) > limit:
            return None, (
                f"{field.replace('_', ' ').title()} "
                f"must not exceed {limit} characters."
            )

    email_pattern = r"^[^\s@]+@[^\s@]+\.[^\s@]+$"

    if not re.fullmatch(email_pattern, cleaned["email"]):
        return None, "Please provide a valid email address."

    if cleaned["inquiry_type"] not in INQUIRY_TYPES:
        return None, "Invalid inquiry type."

    if cleaned["role"] and cleaned["role"] not in VALID_ROLES:
        return None, "Invalid user role."

    # Prevent header injection in email metadata.
    for field in (
        "first_name",
        "last_name",
        "email",
        "subject",
    ):
        if "\r" in cleaned[field] or "\n" in cleaned[field]:
            return None, f"Invalid characters in {field}."

    return cleaned, None


def send_contact_email(data):
    """
    Send a contact inquiry using Resend.

    Credentials and recipient configuration
    are stored in environment variables.
    """

    api_key = os.getenv("RESEND_API_KEY")
    recipient = os.getenv("CONTACT_RECIPIENT_EMAIL")
    sender = os.getenv(
        "CONTACT_SENDER_EMAIL",
        "Acadify <onboarding@resend.dev>",
    )

    if not api_key or not recipient:
        raise RuntimeError(
            "Resend email configuration is incomplete."
        )

    resend.api_key = api_key

    full_name = (
        f"{data['first_name']} {data['last_name']}"
    )

    inquiry_label = INQUIRY_TYPES[
        data["inquiry_type"]
    ]

    email_subject = (
        f"[Acadify] {inquiry_label} — {full_name}"
    )

    email_body = f"""
NEW ACADIFY CONTACT FORM SUBMISSION

----------------------------------------
CONTACT INFORMATION
----------------------------------------

Name: {full_name}
Email: {data['email']}
Role: {data['role'] or 'Not specified'}

----------------------------------------
INQUIRY DETAILS
----------------------------------------

Inquiry Type: {inquiry_label}
Subject: {data['subject']}

Message:

{data['message']}

----------------------------------------

This message was submitted through the
Acadify website contact form.
""".strip()

    params: resend.Emails.SendParams = {
        "from": sender,
        "to": [recipient],
        "subject": email_subject,
        "text": email_body,
        "reply_to": data["email"],
    }

    response = resend.Emails.send(params)

    return response


def verify_turnstile_token(token):
    """
    Verify a Cloudflare Turnstile token server-side.

    Returns True only when Cloudflare confirms that
    the token is valid.
    """

    secret_key = os.getenv("TURNSTILE_SECRET_KEY")

    if not secret_key:
        raise RuntimeError(
            "Cloudflare Turnstile secret key is not configured."
        )

    if not isinstance(token, str) or not token.strip():
        return False

    try:
        response = requests.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={
                "secret": secret_key,
                "response": token,
            },
            timeout=10,
        )

        response.raise_for_status()

        result = response.json()

        if not isinstance(result, dict):
            return False

        if result.get("success") is not True:
            current_app.logger.warning(
                "Cloudflare Turnstile verification failed: %s",
                result.get("error-codes", []),
            )
            return False

        # Optional hostname restriction. Set this to a comma-separated
        # list of trusted frontend hostnames in your backend .env.
        allowed_hostnames = {
            host.strip().lower()
            for host in os.getenv(
                "TURNSTILE_ALLOWED_HOSTNAMES", ""
            ).split(",")
            if host.strip()
        }

        verified_hostname = str(
            result.get("hostname", "")
        ).lower()

        if allowed_hostnames and verified_hostname not in allowed_hostnames:
            current_app.logger.warning(
                "Turnstile verification returned an unexpected hostname."
            )
            return False

        return True

    except (requests.RequestException, ValueError):
        current_app.logger.exception(
            "Unable to verify Cloudflare Turnstile token."
        )
        raise



@contact_bp.route("", methods=["POST"])
@contact_bp.route("/", methods=["POST"])
@limiter.limit("2 per minute; 5 per hour")
def submit_contact():
    """
    Public contact form endpoint.

    Security:
    - Rate limiting
    - 16 KB request-size limit
    - JSON validation
    - Cloudflare Turnstile verification
    - Resend email delivery
    """

    MAX_CONTACT_BYTES = 16 * 1024

    if not request.is_json:
        return jsonify({
            "success": False,
            "message": "Content-Type must be application/json.",
        }), 415

    if (
        request.content_length is not None
        and request.content_length > MAX_CONTACT_BYTES
    ):
        return jsonify({
            "success": False,
            "message": "Contact form submission is too large.",
        }), 413

    raw_body = request.stream.read(MAX_CONTACT_BYTES + 1)

    if len(raw_body) > MAX_CONTACT_BYTES:
        return jsonify({
            "success": False,
            "message": "Contact form submission is too large.",
        }), 413

    try:
        data = json.loads(raw_body)
    except (ValueError, UnicodeDecodeError):
        return jsonify({
            "success": False,
            "message": "Invalid JSON request body.",
        }), 400

    cleaned, error = validate_contact_data(data)

    if error:
        return jsonify({
            "success": False,
            "message": error,
        }), 400

    # The Turnstile token is separate from the validated
    # contact form fields.
    turnstile_token = data.get("turnstile_token")

    if not isinstance(turnstile_token, str) or not turnstile_token:
        return jsonify({
            "success": False,
            "message": "Please complete the security verification.",
        }), 400

    if len(turnstile_token) > 2048:
        return jsonify({
            "success": False,
            "message": "Invalid security verification token.",
        }), 400

    try:
        verified = verify_turnstile_token(turnstile_token)
    except (requests.RequestException, ValueError, RuntimeError):
        return jsonify({
            "success": False,
            "message": (
                "Security verification is temporarily unavailable. "
                "Please try again later."
            ),
        }), 503

    if not verified:
        return jsonify({
            "success": False,
            "message": (
                "Security verification failed or expired. "
                "Please try again."
            ),
        }), 400

    try:
        response = send_contact_email(cleaned)

        current_app.logger.info(
            "Acadify contact email accepted by Resend: %s",
            response.get("id"),
        )

    except Exception:
        current_app.logger.exception(
            "Failed to send Acadify contact email."
        )

        return jsonify({
            "success": False,
            "message": (
                "Unable to send your message right now. "
                "Please try again later."
            ),
        }), 503

    return jsonify({
        "success": True,
        "message": (
            "Your message has been submitted successfully. "
            "Thank you for contacting Acadify!"
        ),
    }), 200
