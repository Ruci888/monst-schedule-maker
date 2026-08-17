from datetime import datetime, timedelta, timezone

import pyotp
import streamlit as st
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError


MAX_FAILURES = 5
LOCK_MINUTES = 15
SESSION_MINUTES = 30
PASSWORD_HASHER = PasswordHasher()


def utc_now():
    return datetime.now(timezone.utc)


def clear_authentication():
    for key in (
        "admin_authenticated",
        "admin_last_activity",
        "admin_failures",
        "admin_locked_until",
    ):
        st.session_state.pop(key, None)


def get_auth_settings():
    try:
        settings = st.secrets["admin_auth"]
        return {
            "password_hash": settings["password_hash"],
            "totp_secret": settings["totp_secret"],
        }
    except (KeyError, FileNotFoundError):
        return None


def session_is_valid():
    if not st.session_state.get("admin_authenticated", False):
        return False

    last_activity = st.session_state.get("admin_last_activity")
    if not last_activity or utc_now() - last_activity > timedelta(minutes=SESSION_MINUTES):
        clear_authentication()
        return False

    st.session_state.admin_last_activity = utc_now()
    return True


def verify_password(password, password_hash):
    try:
        return PASSWORD_HASHER.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def verify_totp(code, secret):
    if not code.isdigit() or len(code) != 6:
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def register_failure():
    failures = st.session_state.get("admin_failures", 0) + 1
    st.session_state.admin_failures = failures
    if failures >= MAX_FAILURES:
        st.session_state.admin_locked_until = utc_now() + timedelta(minutes=LOCK_MINUTES)
        st.session_state.admin_failures = 0


def require_admin_authentication():
    settings = get_auth_settings()
    if not settings:
        st.error(
            "管理者認証が未設定です。Streamlit Secretsのadmin_authを設定してください。"
        )
        st.stop()

    if session_is_valid():
        with st.sidebar:
            st.success("管理者としてログイン中")
            st.caption(f"無操作{SESSION_MINUTES}分で再認証します。")
            if st.button("ログアウト"):
                clear_authentication()
                st.rerun()
        return

    locked_until = st.session_state.get("admin_locked_until")
    if locked_until and utc_now() < locked_until:
        remaining = max(1, int((locked_until - utc_now()).total_seconds() // 60) + 1)
        st.error(f"認証失敗が続いたため、約{remaining}分後に再試行してください。")
        st.stop()

    st.title("管理者ログイン")
    st.caption("パスワードと認証アプリの6桁コードを入力してください。")
    with st.form("admin_login_form", clear_on_submit=True):
        password = st.text_input("管理者パスワード", type="password")
        otp_code = st.text_input(
            "認証番号",
            type="password",
            max_chars=6,
            help="Google Authenticator等に表示される6桁コード",
        )
        submitted = st.form_submit_button("ログイン", type="primary")

    if submitted:
        password_ok = verify_password(password, settings["password_hash"])
        totp_ok = verify_totp(otp_code.strip(), settings["totp_secret"])
        if password_ok and totp_ok:
            st.session_state.admin_authenticated = True
            st.session_state.admin_last_activity = utc_now()
            st.session_state.admin_failures = 0
            st.rerun()
        else:
            register_failure()
            st.error("パスワードまたは認証番号が一致しません。")

    st.stop()
