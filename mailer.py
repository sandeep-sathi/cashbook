import json
import os
import urllib.error
import urllib.request

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"
TIMEOUT_SECONDS = 10


def send_password_reset_email(to_email, reset_url):
    api_key = os.environ.get("BREVO_API_KEY")
    from_email = os.environ.get("MAIL_FROM_ADDRESS")
    if not api_key or not from_email:
        raise RuntimeError("BREVO_API_KEY / MAIL_FROM_ADDRESS is not configured.")

    payload = {
        "sender": {"email": from_email, "name": "Cashbook"},
        "to": [{"email": to_email}],
        "subject": "Reset your Cashbook password",
        "htmlContent": (
            "<p>Click the link below to reset your Cashbook password. "
            "This link expires in 1 hour.</p>"
            f'<p><a href="{reset_url}">{reset_url}</a></p>'
            "<p>If you didn't request this, you can ignore this email.</p>"
        ),
        "textContent": (
            f"Reset your Cashbook password: {reset_url}\n\n"
            "This link expires in 1 hour. If you didn't request this, ignore this email."
        ),
    }
    req = urllib.request.Request(
        BREVO_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"Brevo API error {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not reach Brevo API: {e.reason}") from e
