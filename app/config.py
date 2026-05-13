import os
from zoneinfo import ZoneInfo

TIMEZONE = os.getenv("TIMEZONE", "Europe/Berlin")
LOCAL_TZ = ZoneInfo(TIMEZONE)

RECEIPT_UPLOAD_ENABLED = os.getenv("RECEIPT_UPLOAD_ENABLED", "true").lower() != "false"
