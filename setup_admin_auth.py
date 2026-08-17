import getpass

import pyotp
from argon2 import PasswordHasher


def main():
    print("管理者認証の初回設定を作成します。")
    password = getpass.getpass("管理者パスワード: ")
    confirmation = getpass.getpass("管理者パスワード（確認）: ")
    if password != confirmation:
        raise SystemExit("パスワードが一致しません。")
    if len(password) < 12:
        raise SystemExit("パスワードは12文字以上にしてください。")

    password_hash = PasswordHasher().hash(password)
    totp_secret = pyotp.random_base32()
    provisioning_uri = pyotp.TOTP(totp_secret).provisioning_uri(
        name="Monst Schedule Admin",
        issuer_name="Monst Schedule Maker",
    )

    print("\n以下をStreamlit Secretsへ登録してください。")
    print("この出力をGitHubやチャットへ貼らないでください。\n")
    print("[admin_auth]")
    print(f'password_hash = "{password_hash}"')
    print(f'totp_secret = "{totp_secret}"')
    print("\n認証アプリへ次のセットアップキーを手動登録してください。")
    print(totp_secret)
    print("\n対応アプリでURIを読み込める場合はこちらを使用できます。")
    print(provisioning_uri)


if __name__ == "__main__":
    main()
