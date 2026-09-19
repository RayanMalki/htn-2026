"""Create or update the HypeCheck Sentry dashboard. Reads secrets from .env, never prints them."""
import os

import httpx
from dotenv import load_dotenv

load_dotenv()
required = ["SENTRY_AUTH_TOKEN", "SENTRY_ORG", "SENTRY_PROJECT_ID"]
missing = [key for key in required if not os.getenv(key)]
if missing:
    raise SystemExit("Configure " + ", ".join(missing) + " in .env")

org = os.environ["SENTRY_ORG"]
base = os.getenv("SENTRY_API_BASE", "https://sentry.io/api/0").rstrip("/")
title = "HypeCheck pipeline"
duration_field = "tags[case.duration_seconds,number]"
duration_filter = f"is_transaction:true transaction:app.tasks.process_case {duration_field}:>=0"
queries = [
    ("Completed cases", "count()", "has:case_id case_status:complete", "transaction-like"),
    ("Incomplete cases", "count()", "has:case_id case_status:incomplete", "transaction-like"),
    ("Case duration p50 (seconds)", f"p50({duration_field})", duration_filter, "spans"),
    ("Case duration p95 (seconds)", f"p95({duration_field})", duration_filter, "spans"),
]
widgets = []
for i, (name, aggregate, condition, widget_type) in enumerate(queries):
    widgets.append({"title": name, "displayType": "big_number", "widgetType": widget_type,
        "interval": "5m", "queries": [{"name": name, "fields": [aggregate], "aggregates": [aggregate],
                                        "columns": [], "conditions": condition, "orderby": f"-{aggregate}"}],
        "layout": {"x": i % 2 * 3, "y": i // 2 * 2, "w": 3, "h": 2, "minH": 2}})
payload = {"title": title, "widgets": widgets, "projects": [int(os.environ["SENTRY_PROJECT_ID"])], "period": "24h"}
with httpx.Client(base_url=base, headers={"Authorization": f"Bearer {os.environ['SENTRY_AUTH_TOKEN']}"}, timeout=20) as client:
    listing = client.get(f"/organizations/{org}/dashboards/")
    listing.raise_for_status()
    existing = next((item for item in listing.json() if item["title"] == title), None)
    if existing:
        response = client.put(f"/organizations/{org}/dashboards/{existing['id']}/", json=payload)
    else:
        response = client.post(f"/organizations/{org}/dashboards/", json=payload)
    if response.is_error:
        raise SystemExit(f"Sentry dashboard request returned {response.status_code}. Check token scopes and widget support in your Sentry workspace.")
    print(f"Dashboard ready: https://sentry.io/organizations/{org}/dashboard/{response.json()['id']}/")
