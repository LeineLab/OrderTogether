import json
import os
from zoneinfo import ZoneInfo

TIMEZONE = os.getenv("TIMEZONE", "Europe/Berlin")
LOCAL_TZ = ZoneInfo(TIMEZONE)

RECEIPT_UPLOAD_ENABLED = os.getenv("RECEIPT_UPLOAD_ENABLED", "true").lower() != "false"

# Predefined shops shown in the shop selector on the create-order form.
# Format: JSON array of {"name": "...", "url": "https://..."} objects.
# Example: PREDEFINED_SHOPS='[{"name":"Pizza Palace","url":"https://pizza.example.com"}]'
_predefined_raw = os.getenv("PREDEFINED_SHOPS", "[]")
try:
    PREDEFINED_SHOPS: list = json.loads(_predefined_raw)
except Exception:
    PREDEFINED_SHOPS = []
