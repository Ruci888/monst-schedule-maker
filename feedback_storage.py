from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import csv
from io import StringIO

import streamlit as st

try:
    import firebase_admin
    from firebase_admin import credentials, firestore
except ImportError:
    firebase_admin = None
    credentials = None
    firestore = None

COLLECTION = "feedback"
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

def add_feedback(message):
    db = get_db()
    doc = {
        "message": message,
        "category": "未分類",
        "hidden": False,
        "created_at": datetime.now(timezone.utc),
    }
    db.collection(COLLECTION).add(doc)

def list_feedback():
    db = get_db()
    docs = db.collection(COLLECTION).stream()
    rows = []
    for doc in docs:
        data = doc.to_dict()
        created = data.get("created_at")
        if hasattr(created, "astimezone"):
            created = created.astimezone(JST).strftime("%Y/%m/%d %H:%M:%S")
        rows.append({
            "id": doc.id,
            "created_at": created or "",
            "category": data.get("category", "未分類"),
            "message": data.get("message", ""),
            "hidden": bool(data.get("hidden", False)),
        })
    rows.sort(key=lambda x: x["created_at"], reverse=True)
    return rows

def update_feedback(doc_id, *, category=None, hidden=None):
    values = {}
    if category is not None:
        values["category"] = category
    if hidden is not None:
        values["hidden"] = bool(hidden)
    if values:
        get_db().collection(COLLECTION).document(doc_id).update(values)

def feedback_csv(rows):
    output = StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["投稿日時", "カテゴリ", "意見・要望", "表示状態"])
    for row in rows:
        writer.writerow([
            row.get("created_at", ""),
            row.get("category", "未分類"),
            row.get("message", ""),
            "非表示" if row.get("hidden") else "表示",
        ])
    return output.getvalue().encode("utf-8-sig")
