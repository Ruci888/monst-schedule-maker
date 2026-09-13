import io
import json
import unittest
from copy import deepcopy
from service import App, Conflict

KEY = 'x' * 40
MASTER = [{"quest_id":"quest_test", "name":"試験用キャラ", "attribute":"水", "difficulty":"超絶", "category":"通常降臨", "published":True}]
ENTRY = {"quest_id":"quest_test", "date":"2026-09-12", "start_time":"12:00", "end_time":"11:59", "end_next_day":True}
class MemoryStore:
    def __init__(self):
        self.data = {'quest_master.json':deepcopy(MASTER), 'schedule_candidates.json':[], 'schedules.json':[]}
        self.conflicts = 0
    def read(self, name):
        return deepcopy(self.data[name]), 'sha'
    def write_candidates(self, rows, sha):
        if self.conflicts:
            self.conflicts -= 1
            raise Conflict()
        self.data['schedule_candidates.json'] = deepcopy(rows)

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.app = App(self.store, KEY)
    def call(self, path='/v1/candidates', method='POST', entries=None, token=KEY):
        body = json.dumps({'entries': entries if entries is not None else [ENTRY]}).encode()
        status = []
        result = self.app({'PATH_INFO':path,'REQUEST_METHOD':method,'CONTENT_LENGTH':str(len(body)),
            'HTTP_AUTHORIZATION':'Bearer ' + token,'wsgi.input':io.BytesIO(body)}, lambda s,h:status.append(s))
        return int(status[0].split()[0]), json.loads(b''.join(result))
    def test_authentication(self):
        self.assertEqual(self.call(token='bad')[0],401)
        self.assertEqual(self.store.data['schedule_candidates.json'],[])
    def test_master_shape(self):
        code, data = self.call('/v1/master','GET')
        self.assertEqual(code,200)
        self.assertEqual(data[0]['quest_id'],'quest_test')
        self.assertIn('kana_group',data[0])
    def test_pending_and_retry(self):
        self.assertEqual(self.call()[1],{'added':1,'duplicates':0})
        self.assertEqual(self.call()[1],{'added':0,'duplicates':1})
        row = self.store.data['schedule_candidates.json'][0]
        self.assertFalse(row['published'])
        self.assertEqual(row['date'],'9/12')
        self.assertEqual(row['year'],2026)
        self.assertEqual(row['difficulty'],'超絶')
        self.assertEqual(self.store.data['schedules.json'],[])
    def test_client_cannot_spoof_name(self):
        self.call(entries=[dict(ENTRY,name='偽の名前',difficulty='偽',published=True)])
        self.assertEqual(self.store.data['schedule_candidates.json'][0]['name'],'試験用キャラ')
    def test_mixed_invalid_batch_is_atomic(self):
        self.assertEqual(self.call(entries=[ENTRY,dict(ENTRY,quest_id='missing')])[0],422)
        self.assertEqual(self.store.data['schedule_candidates.json'],[])
    def test_time_validation(self):
        for changes in [{'start_time':'25:00'},{'end_next_day':False},{'date':'2026-02-30'}, {'end_next_day':'false'}]:
            self.assertEqual(self.call(entries=[dict(ENTRY,**changes)])[0],422)
    def test_limited_expired(self):
        self.store.data['quest_master.json'][0].update(category='コラボ',period_end_date='2026-09-11')
        self.assertEqual(self.call()[0],422)
    def test_hidden_master(self):
        self.store.data['quest_master.json'][0]['published'] = False
        self.assertEqual(self.call()[0],422)
    def test_conflict_retry_and_existing_preserved(self):
        old = dict(ENTRY,year=2026,date='9/11',name='既存キャラ')
        self.store.data['schedule_candidates.json'] = [old]
        self.store.conflicts = 1
        self.assertEqual(self.call()[0],200)
        self.assertEqual(self.store.data['schedule_candidates.json'][0],old)
    def test_published_duplicate(self):
        self.call()
        self.store.data['schedules.json'] = self.store.data['schedule_candidates.json']
        self.store.data['schedules.json'][0].pop('quest_id', None)
        self.store.data['schedule_candidates.json'] = []
        self.assertEqual(self.call()[1],{'added':0,'duplicates':1})
    def test_same_day_different_start_allowed(self):
        code, result = self.call(entries=[ENTRY,dict(ENTRY,start_time='18:00')])
        self.assertEqual(result['added'],2)
    def test_conflict_exhausted(self):
        self.store.conflicts = 3
        self.assertEqual(self.call()[0],409)
        self.assertEqual(self.store.data['schedule_candidates.json'],[])
    def test_missing_secret_fails_closed(self):
        self.app = App(self.store,'')
        self.assertEqual(self.call()[0],503)

if __name__ == '__main__': unittest.main()
