"""Send a correctly signed test webhook.  Usage:
  python scripts/send_webhook.py OMX-TEE-001 NorthLoop 999
"""
import json
import sys
import time
import urllib.request

sys.path.insert(0, ".")
from app.core.config import settings  # noqa: E402
from app.core.security import sign  # noqa: E402

sku, competitor, price = sys.argv[1], sys.argv[2], float(sys.argv[3])
body = json.dumps({"event_type": "competitor.price_changed",
                   "data": {"sku": sku, "competitor": competitor, "price": price, "note": "Flash sale detected."}}).encode()
ts = str(time.time())
req = urllib.request.Request("http://localhost:8000/api/v1/webhooks/competitor-scraper", data=body, method="POST",
                             headers={"Content-Type": "application/json", "X-Timestamp": ts,
                                      "X-Signature": sign(settings.webhook_secret, ts, body)})
print(urllib.request.urlopen(req).read().decode())
