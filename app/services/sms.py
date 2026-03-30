"""
SMS OTP helper for F Drive customer and rider apps.

Production note:
Use Redis or a Supabase table for OTP storage instead of in-memory dict,
especially when running multiple app instances.
"""

import logging
import os
import random
from datetime import datetime, timedelta

try:
    import africastalking
except ImportError:
    africastalking = None

logger = logging.getLogger(__name__)

AFRICASTALKING_USERNAME = os.getenv("AFRICASTALKING_USERNAME", "")
AFRICASTALKING_API_KEY = os.getenv("AFRICASTALKING_API_KEY", "")

# Initialize Africa's Talking SDK from environment variables.
if africastalking:
    africastalking.initialize(AFRICASTALKING_USERNAME, AFRICASTALKING_API_KEY)
    _sms_client = africastalking.SMS
else:
    _sms_client = None

# In-memory OTP store: {phone: {"otp": "123456", "expires_at": datetime}}
_otp_store = {}


def generate_otp():
    """Generate a random 6-digit OTP string."""
    return f"{random.randint(0, 999999):06d}"


def send_otp(phone_number, otp):
    """
    Send OTP SMS via Africa's Talking.
    Returns True on success, False on failure.
    """
    try:
        if _sms_client is None:
            logger.error("Africa's Talking SDK is not installed. OTP SMS not sent.")
            return False

        message = f"Your F Drive code is: {otp}. Valid for 10 minutes."
        response = _sms_client.send(message, [phone_number])

        recipients = response.get("SMSMessageData", {}).get("Recipients", [])
        if not recipients:
            return False

        status = str(recipients[0].get("status", "")).lower()
        return "success" in status or "sent" in status
    except Exception as exc:
        logger.exception("Failed to send OTP SMS: %s", exc)
        return False


def store_otp(phone, otp):
    """Store OTP with a 10-minute expiry window."""
    _otp_store[phone] = {
        "otp": str(otp),
        "expires_at": datetime.utcnow() + timedelta(minutes=10),
    }


def verify_otp(phone, otp):
    """
    Verify OTP match and expiry.
    OTP is deleted after successful verification or expiry.
    """
    entry = _otp_store.get(phone)
    if not entry:
        return False

    if datetime.utcnow() > entry["expires_at"]:
        _otp_store.pop(phone, None)
        return False

    if str(entry["otp"]) != str(otp):
        return False

    _otp_store.pop(phone, None)
    return True
