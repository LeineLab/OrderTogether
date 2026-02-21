import os
from zoneinfo import ZoneInfo

TIMEZONE = os.getenv("TIMEZONE", "Europe/Berlin")
LOCAL_TZ = ZoneInfo(TIMEZONE)
