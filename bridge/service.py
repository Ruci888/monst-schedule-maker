"""Standalone authenticated WSGI bridge. No writes to schedules.json."""
import base64
import hashlib
import hmac
import json
import os
import re
from datetime import date, datetime
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
from quest_master import normalize_quest_master, schedule_from_master, master_expired, quest_master_kana_group, normalize_master_name

class Conflict(Exception):
    pass

class GitHubStore:
    def __init__(self):
        self.repo = os.environ['GITHUB_REPOSITORY']
        self.branch = os.environ.get('GITHUB_BRANCH', 'main')
        self.token = os.environ['GITHUB_TOKEN']
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', self.repo):
            raise ValueError('Invalid repository')

    def request(self, name, payload=None):
        url = f'https://api.github.com/repos/{self.repo}/contents/{name}'
        if payload is None:
            url += '?ref=' + quote(self.branch, safe='')
        request = Request(url, data=None if payload is None else json.dumps(payload).encode(),
            headers={'Authorization': f'Bearer {self.token}', 'Accept': 'application/vnd.github+json',
                     'User-Agent': 'RaidRegister-bridge', 'Content-Type': 'application/json'},
            method='GET' if payload is None else 'PUT')
        try:
            with urlopen(request, timeout=20) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code == 409:
                raise Conflict() from None
            raise

    def read(self, name):
        try:
            item = self.request(name)
        except HTTPError as error:
            if error.code == 404 and name == 'schedule_candidates.json':
                return [], None
            raise
        records = json.loads(base64.b64decode(item['content']))
        if not isinstance(records, list):
            raise ValueError('Expected JSON array')
        return records, item['sha']

    def write_candidates(self, records, sha):
        payload = {'message': 'Add pending schedules from iPhone registrar', 'branch': self.branch,
            'content': base64.b64encode(json.dumps(records, ensure_ascii=False, indent=2).encode()).decode()}
        if sha:
            payload['sha'] = sha
        self.request('schedule_candidates.json', payload)

def identity(row):
    return (str(row.get('year')), str(row.get('date')), row.get('start_time'),
            (normalize_master_name(row.get('name')), row.get('difficulty')))

def prepare(payload, master):
    if not isinstance(payload, dict) or not isinstance(payload.get('entries'), list):
        raise ValueError('entries配列が必要です。')
    entries = payload['entries']
    if not 1 <= len(entries) <= 200:
        raise ValueError('一度に1〜200件を送信してください。')
    lookup = {r['quest_id']: r for r in normalize_quest_master(master)}
    result = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('日程の形式が不正です。')
        record = lookup.get(entry.get('quest_id'))
        game_date = date.fromisoformat(entry.get('date', ''))
        if record is None or not record.get('published', True) or master_expired(record, game_date):
            raise ValueError('未登録・非公開・対象日で期限切れのマスターがあります。再取得してください。')
        start, end = entry.get('start_time', ''), entry.get('end_time', '')
        for value in [start, end]:
            if not isinstance(value, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value):
                raise ValueError('時刻はHH:mmで指定してください。')
        next_day = entry.get('end_next_day')
        if not isinstance(next_day, bool) or (not next_day and end <= start):
            raise ValueError('終了日時は開始日時より後にしてください。')
        row = schedule_from_master(record, game_date, start)
        row.update(end_time=end, end_next_day=next_day, published=False, confirmed_at='',
                   source_type='master', review_reason='iPhoneで画像を参照して手動選択',
                   source_capture_type='manual_reference', fetched_at=datetime.now().astimezone().isoformat())
        key = json.dumps(identity(row), ensure_ascii=False)
        row['candidate_id'] = 'iphone_' + hashlib.sha256(key.encode()).hexdigest()[:24]
        result.append(row)
    return result

class App:
    def __init__(self, store=None, token=None, allowed_origin=None):
        self.store = store
        self.allowed_origin = allowed_origin if allowed_origin is not None else os.environ.get("REGISTRAR_ALLOWED_ORIGIN", "")
        self.token = token if token is not None else os.environ.get('REGISTRAR_API_KEY', '')

    def __call__(self, env, start_response):
        origin = env.get('HTTP_ORIGIN', '')
        cors = [('Vary', 'Origin')]
        if origin and origin == self.allowed_origin:
            cors += [('Access-Control-Allow-Origin', origin),
                     ('Access-Control-Allow-Methods', 'GET, POST, OPTIONS'),
                     ('Access-Control-Allow-Headers', 'Authorization, Content-Type')]
        def reply(status, data):
            body = json.dumps(data, ensure_ascii=False).encode()
            start_response(status, [('Content-Type','application/json; charset=utf-8'),
                                    ('Cache-Control','no-store'), ('Content-Length',str(len(body)))] + cors)
            return [body]
        if origin and origin != self.allowed_origin:
            return reply('403 Forbidden', {'detail': 'この接続元は許可されていません。'})
        if env.get('REQUEST_METHOD') == 'OPTIONS':
            if not origin or env.get('HTTP_ACCESS_CONTROL_REQUEST_METHOD') not in ('GET', 'POST'):
                return reply('403 Forbidden', {'detail': '接続元を確認してください。'})
            return reply('200 OK', {})
        if len(self.token) < 32:
            return reply('503 Service Unavailable', {'detail':'接続キーが未設定です。'})
        if not hmac.compare_digest(env.get('HTTP_AUTHORIZATION',''), 'Bearer ' + self.token):
            return reply('401 Unauthorized', {'detail':'認証に失敗しました。'})
        try:
            store = self.store or GitHubStore()
            path, method = env.get('PATH_INFO'), env.get('REQUEST_METHOD')
            if path == '/v1/master' and method == 'GET':
                master, _ = store.read('quest_master.json')
                records = normalize_quest_master(master)
                for record in records:
                    record['kana_group'] = quest_master_kana_group(record)
                    record.pop('image_references', None)
                return reply('200 OK', records)
            if path != '/v1/candidates' or method != 'POST':
                return reply('404 Not Found', {'detail':'存在しないAPIです。'})
            size = int(env.get('CONTENT_LENGTH') or 0)
            if not 0 < size <= 200000:
                return reply('413 Payload Too Large', {'detail':'送信サイズが不正です。'})
            payload = json.loads(env['wsgi.input'].read(size))
            master, _ = store.read('quest_master.json')
            additions = prepare(payload, master)
            for attempt in range(3):
                pending, sha = store.read('schedule_candidates.json')
                schedules, _ = store.read('schedules.json')
                known = {identity(x) for x in pending + schedules}
                appended = []
                for row in additions:
                    if identity(row) not in known:
                        appended.append(row)
                        known.add(identity(row))
                try:
                    if appended:
                        store.write_candidates(pending + appended, sha)
                    return reply('200 OK', {'added':len(appended), 'duplicates':len(additions)-len(appended)})
                except Conflict:
                    if attempt == 2:
                        return reply('409 Conflict', {'detail':'他の更新と重なりました。再送してください。'})
        except (ValueError, TypeError, KeyError) as error:
            return reply('422 Unprocessable Entity', {'detail':'入力またはマスターデータが不正です。日付・時刻・マスターを確認してください。'})
        except Exception:
            # Do not expose credentials, upstream URLs, or repository bodies.
            return reply('502 Bad Gateway', {'detail':'保存先へ接続できません。下書きは残っています。再送してください。'})

application = App()
if __name__ == '__main__':
    from wsgiref.simple_server import make_server
    with make_server('127.0.0.1', 8765, application) as server:
        server.serve_forever()
