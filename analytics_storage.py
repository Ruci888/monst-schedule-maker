from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import csv
from io import StringIO
import uuid

import streamlit as st

try:
    import firebase_admin
    from firebase_admin import credentials, firestore
except ImportError:
    firebase_admin = None
    credentials = None
    firestore = None

COLLECTION = "usage_events"
JST = ZoneInfo("Asia/Tokyo")


def _firebase_config():
    try:
        return dict(st.secrets["firebase"]["service_account"])
    except Exception:
        return None


def is_configured():
    return firebase_admin is not None and _firebase_config() is not None


def get_db():
    if not is_configured():
        raise RuntimeError("Firebaseが未設定です。")
    if not firebase_admin._apps:
        firebase_admin.initialize_app(credentials.Certificate(_firebase_config()))
    return firestore.client()


def get_or_create_visitor_id():
    # Streamlit exposes browser cookies read-only, so use an anonymous URL query
    # parameter as the persistent browser-side identifier when possible.
    try:
        visitor_id = st.query_params.get("vid")
    except Exception:
        visitor_id = None
    if isinstance(visitor_id, list):
        visitor_id = visitor_id[0] if visitor_id else None
    if visitor_id and len(str(visitor_id)) >= 16:
        return str(visitor_id), False

    key = "_anonymous_visitor_id"
    if key not in st.session_state:
        st.session_state[key] = uuid.uuid4().hex
        is_new = True
    else:
        is_new = False
    visitor_id = st.session_state[key]
    try:
        st.query_params["vid"] = visitor_id
    except Exception:
        pass
    return visitor_id, is_new


def log_usage(event_type, visitor_id, *, detail=""):
    if not is_configured() or not visitor_id:
        return
    get_db().collection(COLLECTION).add({
        "visitor_id": visitor_id,
        "event_type": event_type,
        "detail": detail,
        "created_at": datetime.now(timezone.utc),
    })


def list_usage():
    db = get_db()
    rows = []
    for doc in db.collection(COLLECTION).stream():
        data = doc.to_dict()
        created = data.get("created_at")
        created_jst = created.astimezone(JST) if hasattr(created, "astimezone") else None
        rows.append({
            "id": doc.id,
            "created_at": created_jst.strftime("%Y/%m/%d %H:%M:%S") if created_jst else "",
            "_created_at": created_jst,
            "visitor_id": data.get("visitor_id", ""),
            "event_type": data.get("event_type", ""),
            "detail": data.get("detail", ""),
        })
    rows.sort(key=lambda x: x["created_at"], reverse=True)
    return rows


def usage_summary(rows):
    now = datetime.now(JST)
    starts = {
        "today": datetime.combine(now.date(), datetime.min.time(), tzinfo=JST),
        "7days": now - timedelta(days=7),
        "30days": now - timedelta(days=30),
    }

    def unique_since(start=None):
        return len({
            r["visitor_id"] for r in rows
            if r.get("visitor_id")
            and r.get("event_type") == "visit"
            and (start is None or (r.get("_created_at") and r["_created_at"] >= start))
        })

    return {
        "today": unique_since(starts["today"]),
        "7days": unique_since(starts["7days"]),
        "30days": unique_since(starts["30days"]),
        "total": unique_since(),
        "event_generations": sum(r.get("event_type") == "event_image_generated" for r in rows),
        "schedule_generations": sum(r.get("event_type") == "schedule_image_generated" for r in rows),
    }


def usage_csv(rows):
    output = StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["日時(JST)", "匿名訪問者ID", "イベント種別", "詳細"])
    for row in rows:
        writer.writerow([
            row.get("created_at", ""),
            row.get("visitor_id", ""),
            row.get("event_type", ""),
            row.get("detail", ""),
        ])
    return output.getvalue().encode("utf-8-sig")
