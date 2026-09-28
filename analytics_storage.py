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
VISITOR_COLLECTION = "usage_visitors"
STATS_COLLECTION = "usage_stats"
STATS_DOCUMENT = "totals"
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

    db = get_db()
    now = datetime.now(timezone.utc)
    batch = db.batch()

    # 詳細ログは従来どおり残す。ただし管理画面では全件走査しない。
    event_ref = db.collection(COLLECTION).document()
    batch.set(event_ref, {
        "visitor_id": visitor_id,
        "event_type": event_type,
        "detail": detail,
        "created_at": now,
    })

    # visit 時だけ匿名訪問者の最終訪問日時を1ドキュメントに集約する。
    # これにより期間別ユニーク数を全ログ読込なしで数えられる。
    if event_type == "visit":
        visitor_ref = db.collection(VISITOR_COLLECTION).document(visitor_id)
        batch.set(visitor_ref, {
            "visitor_id": visitor_id,
            "last_seen": now,
        }, merge=True)

    # 画像生成回数はカウンタを加算し、管理画面では1ドキュメントだけ読む。
    if event_type in ("event_image_generated", "schedule_image_generated"):
        field = (
            "event_generations"
            if event_type == "event_image_generated"
            else "schedule_generations"
        )
        stats_ref = db.collection(STATS_COLLECTION).document(STATS_DOCUMENT)
        batch.set(stats_ref, {field: firestore.Increment(1)}, merge=True)

    batch.commit()


def _count_query(query):
    """Firestoreの集約COUNTを使い、対象ドキュメント本体を読み込まない。"""
    result = query.count().get()
    if not result:
        return 0
    # firebase-admin のAggregationResultは value を持つ。
    return int(result[0][0].value)


def get_usage_summary():
    db = get_db()
    now = datetime.now(JST)
    starts = {
        "today": datetime.combine(now.date(), datetime.min.time(), tzinfo=JST),
        "7days": now - timedelta(days=7),
        "30days": now - timedelta(days=30),
    }

    visitors = db.collection(VISITOR_COLLECTION)
    summary = {
        "today": _count_query(visitors.where("last_seen", ">=", starts["today"])),
        "7days": _count_query(visitors.where("last_seen", ">=", starts["7days"])),
        "30days": _count_query(visitors.where("last_seen", ">=", starts["30days"])),
        "total": _count_query(visitors),
        "event_generations": 0,
        "schedule_generations": 0,
    }

    stats = db.collection(STATS_COLLECTION).document(STATS_DOCUMENT).get()
    if stats.exists:
        data = stats.to_dict() or {}
        summary["event_generations"] = int(data.get("event_generations", 0) or 0)
        summary["schedule_generations"] = int(data.get("schedule_generations", 0) or 0)
    return summary


def list_usage(limit=200):
    """CSV/確認用。全件ではなく最新 limit 件だけ取得する。"""
    db = get_db()
    query = (
        db.collection(COLLECTION)
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
    )
    rows = []
    for doc in query.stream():
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
    return rows


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
