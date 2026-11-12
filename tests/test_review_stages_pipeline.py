"""`review_pipeline.py --stages` end to end: the real main / run_document / review_stages / FlexBoundary with only
the OpenAI SDK faked. Markdown bill text and fiscal notes are written to a temp "live" tree; every request the
fake SDK sees is recorded as (bill, response-format name). No network, no paid calls.
"""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import review_pipeline as pipeline  # noqa: E402
import flex_boundary  # noqa: E402
import classify_bill as classification  # noqa: E402

REAL_BOUNDARY = flex_boundary.FlexBoundary
CLASSIFY = 'texas_bill_classification_v1'
UPDATE = 'texas_bill_version_update_v1'
FISCAL = 'texas_bill_fiscal_check_v1'

QUOTE_I = 'The agency shall report annually on widgets.'
QUOTE_H = 'The agency shall report quarterly on widgets.'
GADGET = 'A person who sells a gadget commits an offense.'
SUNSET = 'This Act expires in five years.'
GIZMO = 'The state shall fund a gizmo program.'
FISCAL_QUOTE = 'The cost to the state is estimated at one million dollars.'
FISCAL_QUOTE_H = 'The cost to the state is estimated at two million dollars.'


def md_i(bill):
    return f'# {bill} MARKER-{bill} VERSION-I\n\n{QUOTE_I}\n\n{GADGET}\n\n{SUNSET}\n'


def md_h(bill):
    return f'# {bill} MARKER-{bill} VERSION-H\n\nThe agency shall report <ins>quarterly</ins> on widgets.\n\n{GIZMO}\n'


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def body(obj):
    return {'model': classification.MODEL, 'service_tier': 'flex', 'status': 'completed',
            'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(obj)}]}],
            'usage': {'input_tokens': 10, 'output_tokens': 5}}


def ev(quote, span='P002S001'):
    return [{'span_id': span, 'quote': quote}]


def classification_result(bill, quote, uncertainties=()):
    return {'bill_id': bill, 'summary': {'text': 'Summary.', 'evidence': ev(quote)}, 'policy_tags': [],
            'agencies': [], 'all_state_agencies_scope': {'applies': False, 'basis': 'not_applicable',
                                                         'explanation': 'None.', 'evidence': []},
            'locations': [], 'affected_groups': [], 'major_effects': [], 'uncertainties': list(uncertainties)}


GOOD_CHANGES = [
    {'kind': 'altered', 'label': 'Reporting frequency', 'explanation': 'Annual becomes quarterly.',
     'evidence': ev(QUOTE_H)},
    {'kind': 'added', 'label': 'Gizmo program', 'explanation': 'New funding.', 'evidence': ev(GIZMO, 'P003S001')},
    {'kind': 'removed', 'label': 'Gadget offense', 'explanation': 'Dropped.', 'evidence': ev(GADGET, 'P003S001')},
]


class FakeSDK:
    def __init__(self, case):
        self.case, self.requests, self.responses = case, [], self

    def with_options(self, **kw):
        return self

    def create(self, **kw):
        text = json.dumps(kw['input'])
        bill = re.search(r'MARKER-([A-Z]+\d+)', text)[1]
        name = kw['text']['format']['name']
        self.requests.append((bill, name))
        out = self.case.respond(bill, name, text)
        if isinstance(out, BaseException):
            raise out
        return type('Reply', (), {'model_dump': lambda s, mode='json': out})()


class StagesCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.live, self.cache = base / 'live', base / 'cache'
        self.text, self.hist = self.live / 'text', self.live / 'history'
        self.tags = self.live / 'luna' / 'tags.json'
        self.snap = self.live / 'bills.json'
        self.live.mkdir()
        self.ids = ['HB1']
        self.versions, self.docs = {}, {}
        self.overrides = {}  # (name) -> callable(bill, text) -> body | exception, replaces the default reply
        self.changes, self.update_uncertainties, self.first_uncertainties = GOOD_CHANGES, [], []
        p = patch.object(pipeline.detailed, 'load_registry', return_value=[]); p.start(); self.addCleanup(p.stop)
        self.sdk = FakeSDK(self)

    # ---- fixtures ----
    def put(self, bill, code, markdown):
        folder = self.text / bill
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (code + '.md')).write_bytes(markdown.encode('utf-8'))
        versions = self.versions.setdefault(bill, [])
        entry = {'code': code, 'sha256': sha(markdown)}
        for i, v in enumerate(versions):
            if v['code'] == code:
                versions[i] = entry; break
        else:
            versions.append(entry)
        (folder / 'index.json').write_text(json.dumps(
            {'format': 'texas-bill-text-index-v1', 'bill_id': bill, 'versions': versions}), 'utf-8')

    def put_fiscal(self, bill, code, markdown):
        folder = self.hist / bill
        folder.mkdir(parents=True, exist_ok=True)
        name = f'fiscal_note-{code}.md'
        (folder / name).write_bytes(markdown.encode('utf-8'))
        docs = [d for d in self.docs.setdefault(bill, []) if d['code'] != code]
        docs.append({'type': 'fiscal_note', 'code': code, 'name': 'Fiscal note', 'path': name, 'sha256': sha(markdown)})
        self.docs[bill] = docs
        (folder / 'documents.json').write_text(json.dumps(
            {'format': 'texas-bill-documents-v1', 'bill_id': bill, 'documents': docs}), 'utf-8')

    def seed(self, ids=None):
        self.ids = ids or self.ids
        self.snap.write_text(json.dumps({'bills': [{'id': i} for i in self.ids]}), 'utf-8')
        for bill in self.ids:
            self.put(bill, 'I', md_i(bill))

    # ---- fake provider ----
    def respond(self, bill, name, text):
        if name in self.overrides:
            return self.overrides[name](bill, text)
        version = re.search(r'VERSION-(\w)', text)
        if name == CLASSIFY:
            quote = QUOTE_H if version and version[1] == 'H' else QUOTE_I
            return body(classification_result(bill, quote, self.first_uncertainties))
        if name == UPDATE:
            result = classification_result(bill, QUOTE_H, self.update_uncertainties)
            result['changes'] = self.changes
            return body(result)
        if name == FISCAL:
            quote = re.search(r'The cost to the state is estimated at \w+ million dollars\.', text)[0]
            return body({'bill_id': bill, 'fiscal_summary': {'text': 'Costs.', 'evidence': [{'doc_id': 'F1', 'quote': quote}]},
                         'agencies': [], 'disagreements': [], 'no_fiscal_implication': False})
        return RuntimeError('unexpected request kind ' + name)

    def run_main(self, *extra, stages=True, input_markdown=True):
        argv = ['review_pipeline.py', '--cache-dir', str(self.cache), '--snapshot', str(self.snap),
                '--execute', '--transport', 'flex', '--publish-tags', str(self.tags)]
        if input_markdown:
            argv += ['--input', 'markdown']
        if stages:
            argv.append('--stages')
        make = lambda cache_dir, daily, run: REAL_BOUNDARY(cache_dir, daily, run, openai_factory=lambda: self.sdk,
                                                           sleep=lambda s: None, log=lambda t: None)
        out = io.StringIO()
        with patch.object(sys, 'argv', argv + list(extra)), patch.object(flex_boundary, 'FlexBoundary', side_effect=make), \
                contextlib.redirect_stdout(out):
            pipeline.main()
        return out.getvalue()

    def sent_since(self, mark):
        return self.sdk.requests[mark:]

    def review(self, bill='HB1'):
        return json.loads((self.cache / 'reviews' / (bill + '.json')).read_text('utf-8'))

    def luna(self, folder, bill='HB1'):
        path = self.live / 'luna' / folder / (bill + '.json')
        return json.loads(path.read_text('utf-8')) if path.exists() else None

    def ledger_states(self):
        path = self.cache / 'budget.json'
        ledger = json.loads(path.read_text('utf-8')) if path.exists() else {}
        return [row['state'] for day in ledger.values() for row in day.values()]


class StageTwoTests(StagesCase):
    def setUp(self):
        super().setUp()
        self.seed()

    def update_to_h(self):
        self.run_main()
        self.put('HB1', 'H', md_h('HB1'))
        mark = len(self.sdk.requests)
        self.run_main()
        return mark

    def test_new_version_sends_one_update_and_publishes_verified_changes(self):
        self.changes = GOOD_CHANGES + [{'kind': 'added', 'label': 'Phantom', 'explanation': 'x',
                                        'evidence': ev('This sentence is nowhere in the bill.')}]
        self.run_main()
        self.assertEqual(self.sdk.requests, [('HB1', CLASSIFY)])
        self.assertEqual(self.review()['document']['version'], 'introduced')
        self.put('HB1', 'H', md_h('HB1'))
        mark = len(self.sdk.requests)
        self.run_main()
        self.assertEqual(self.sent_since(mark), [('HB1', UPDATE)])  # exactly one, and not a plain classification
        review = self.review()
        self.assertEqual(review['document']['version'], 'H')
        self.assertEqual(review['version_update']['from_code'], 'I')
        self.assertEqual({c['label'] for c in review['changes']},
                         {'Reporting frequency', 'Gizmo program', 'Gadget offense', 'Phantom'})
        published = self.luna('changes')
        self.assertEqual((published['to_version'], published['from_version']), ('H', 'I'))
        self.assertEqual(published['text_sha256'], sha(md_h('HB1')))
        self.assertEqual({c['label'] for c in published['changes']},
                         {'Reporting frequency', 'Gizmo program', 'Gadget offense'})  # unverified one withheld
        self.assertEqual(self.luna('highlights')['text_version'], 'H')

    def test_revisit_after_update_resends_nothing_and_keeps_version(self):
        self.update_to_h()
        before = self.review()
        mark = len(self.sdk.requests)
        self.run_main()
        self.assertEqual(self.sent_since(mark), [])
        after = self.review()
        self.assertEqual(after['document']['version'], 'H')  # not reverted to I
        self.assertEqual(after['version_update'], before['version_update'])
        self.assertEqual(self.luna('changes')['to_version'], 'H')

    def test_revisit_is_a_cache_hit_even_if_the_old_version_is_reconverted(self):
        self.update_to_h()
        self.assertIn('diff', self.review()['version_update'])
        self.put('HB1', 'I', md_i('HB1') + '\nA paragraph the converter now emits.\n')  # new I bytes and sha
        mark = len(self.sdk.requests)
        self.run_main()
        self.assertEqual(self.sent_since(mark), [])
        self.assertEqual(self.review()['document']['version'], 'H')

    def test_new_version_drops_the_old_versions_pending_questions(self):
        old_span = 'P004S001'  # the sunset paragraph: only in I
        self.first_uncertainties = [{'question': 'Does the sunset apply?', 'affected_claims': ['summary'],
                                     'span_ids': [old_span], 'needed_source': None}]
        self.update_uncertainties = [{'question': 'Is the gizmo funded?', 'affected_claims': ['summary'],
                                      'span_ids': ['P003S001'], 'needed_source': None}]
        self.run_main()
        first = self.review()
        self.assertEqual([q['span_ids'] for q in first['pending_questions']], [[old_span]])
        self.assertIn('HB1', json.loads((self.cache / 'queue.json').read_text('utf-8'))['retry'])
        self.put('HB1', 'H', md_h('HB1'))
        mark = len(self.sdk.requests)
        self.run_main()
        self.assertEqual(self.sent_since(mark), [('HB1', UPDATE)])  # no question request from the I document
        review = self.review()
        h_spans = set(pipeline.load_markdown_document('HB1', self.text, 'H')['spans'])
        self.assertNotIn(old_span, h_spans)
        ids = [s for q in review['pending_questions'] for s in q['span_ids']]
        self.assertTrue(ids and set(ids) <= h_spans, ids)
        self.assertNotIn('Does the sunset apply?', json.dumps(review['pending_questions']))

    def test_unknown_outcome_on_update_keeps_old_review_and_blocks_resend(self):
        self.run_main()
        old_bytes = (self.cache / 'reviews' / 'HB1.json').read_bytes()
        self.put('HB1', 'H', md_h('HB1'))
        self.overrides[UPDATE] = lambda bill, text: TimeoutError('unknown submission outcome')
        mark = len(self.sdk.requests)
        self.run_main()  # only HB1's update is held; the run goes on
        self.assertEqual(self.sent_since(mark), [('HB1', UPDATE)])
        self.assertEqual((self.cache / 'reviews' / 'HB1.json').read_bytes(), old_bytes)
        ledger = json.loads((self.cache / 'budget.json').read_text('utf-8'))
        self.assertEqual(sum(1 for day in ledger.values() for row in day.values() if row.get('held')), 1)
        self.assertNotIn('pending', self.ledger_states())
        self.overrides[UPDATE] = lambda bill, text: body({})  # would be accepted if a resend happened
        mark = len(self.sdk.requests)
        try:
            self.run_main()
        except SystemExit:
            pass
        self.assertEqual(self.sent_since(mark), [])
        self.assertEqual((self.cache / 'reviews' / 'HB1.json').read_bytes(), old_bytes)

    def test_invalid_update_keeps_the_old_review_and_is_not_resent(self):
        self.run_main()
        old_bytes = (self.cache / 'reviews' / 'HB1.json').read_bytes()
        old_tags = json.loads(self.tags.read_text('utf-8'))['bills']['HB1']
        self.put('HB1', 'H', md_h('HB1'))
        self.changes = [{'kind': 'bogus', 'label': 'x', 'explanation': 'y', 'evidence': ev(QUOTE_H)}]
        mark = len(self.sdk.requests)
        self.run_main()
        self.assertEqual(self.sent_since(mark), [('HB1', UPDATE)])
        self.assertEqual((self.cache / 'reviews' / 'HB1.json').read_bytes(), old_bytes)
        self.assertEqual(json.loads(self.tags.read_text('utf-8'))['bills']['HB1'], old_tags)
        self.assertIsNone(self.luna('changes'))
        mark = len(self.sdk.requests)
        self.run_main()
        self.assertEqual(self.sent_since(mark), [])  # the invalid response is cached, not re-billed
        self.assertEqual((self.cache / 'reviews' / 'HB1.json').read_bytes(), old_bytes)

    def test_without_stages_a_new_version_is_not_rereviewed(self):
        self.run_main(stages=False)
        old_bytes = (self.cache / 'reviews' / 'HB1.json').read_bytes()
        self.put('HB1', 'H', md_h('HB1'))
        mark = len(self.sdk.requests)
        self.run_main(stages=False)
        self.assertEqual(self.sent_since(mark), [])
        review = self.review()
        self.assertEqual(review['document']['version'], 'introduced')
        self.assertNotIn('version_update', review)
        self.assertEqual((self.cache / 'reviews' / 'HB1.json').read_bytes(), old_bytes)
        self.assertIsNone(self.luna('changes'))


class FiscalTests(StagesCase):
    def setUp(self):
        super().setUp()
        self.seed()
        self.put_fiscal('HB1', 'I', f'# Fiscal Note MARKER-HB1\n\n{FISCAL_QUOTE}\n')

    def test_one_check_per_binding_and_stale_after_a_version_change(self):
        self.run_main()
        self.assertEqual(self.sdk.requests, [('HB1', CLASSIFY)])  # a first pass does no fiscal check
        mark = len(self.sdk.requests)
        out = self.run_main()
        self.assertEqual(self.sent_since(mark), [('HB1', FISCAL)])
        record = json.loads((self.cache / 'fiscal' / 'HB1.json').read_text('utf-8'))
        self.assertEqual(record['binding']['review_key'], self.review()['first_pass_request_key'])
        published = self.luna('fiscal')
        self.assertEqual(published['text_version'], 'I')
        self.assertIn(FISCAL_QUOTE, json.dumps(published))
        mark = len(self.sdk.requests)
        self.run_main()
        self.assertEqual(self.sent_since(mark), [])
        self.assertIsNotNone(self.luna('fiscal'))
        # A new version replaces the review: the stored fiscal record's binding no longer matches.
        self.put('HB1', 'H', md_h('HB1'))
        mark = len(self.sdk.requests)
        self.run_main()
        self.assertEqual(self.sent_since(mark), [('HB1', UPDATE)])
        self.assertIsNone(self.luna('fiscal'))
        # A fiscal note for H, checked on the next visit, publishes again.
        self.put_fiscal('HB1', 'H', f'# Fiscal Note MARKER-HB1\n\n{FISCAL_QUOTE_H}\n')
        mark = len(self.sdk.requests)
        self.run_main()
        self.assertEqual(self.sent_since(mark), [('HB1', FISCAL)])
        published = self.luna('fiscal')
        self.assertEqual(published['text_version'], 'H')
        self.assertIn(FISCAL_QUOTE_H, json.dumps(published))


    def test_unknown_outcome_on_a_fiscal_check_is_held_not_resent(self):
        self.run_main()
        self.overrides[FISCAL] = lambda bill, text: TimeoutError('unknown submission outcome')
        mark = len(self.sdk.requests)
        self.run_main()  # the review is recorded and the run goes on
        self.assertEqual(self.sent_since(mark), [('HB1', FISCAL)])
        self.assertFalse((self.cache / 'fiscal' / 'HB1.json').exists())
        self.overrides[FISCAL] = lambda bill, text: self.fail('Must not resend a held fiscal check')
        mark = len(self.sdk.requests)
        self.run_main()
        self.assertEqual(self.sent_since(mark), [])


class BreakerTests(StagesCase):
    def setUp(self):
        super().setUp()
        self.seed([f'HB{n}' for n in range(1, 9)])
        self.run_main()
        self.assertEqual(len(self.sdk.requests), 8)

    def revise(self, bill):
        self.put(bill, 'I', md_i(bill) + '\nAn extra paragraph from a new converter.\n')

    def test_mass_text_change_under_one_version_code_is_not_rereviewed(self):
        for bill in self.ids:
            self.revise(bill)
        mark = len(self.sdk.requests)
        out = self.run_main()
        self.assertIn('changed text under the same version', out)
        self.assertEqual(self.sent_since(mark), [])
        for bill in self.ids:
            self.assertEqual(self.review(bill)['document']['text_sha256'], sha(md_i(bill)))  # old review kept

    def test_a_single_text_change_is_reviewed_afresh_not_as_a_version_update(self):
        self.revise('HB3')
        mark = len(self.sdk.requests)
        out = self.run_main()
        self.assertNotIn('changed text under the same version', out)
        self.assertEqual(self.sent_since(mark), [('HB3', CLASSIFY)])
        review = self.review('HB3')
        self.assertEqual(review['document']['text_sha256'], self.versions['HB3'][0]['sha256'])
        self.assertNotIn('version_update', review)
        self.assertNotIn('changes', review)


class ParserTests(unittest.TestCase):
    def test_stages_without_markdown_input_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ['review_pipeline.py', '--cache-dir', str(Path(tmp) / 'cache'), '--stages']
            err = io.StringIO()
            with patch.object(sys, 'argv', argv), contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as caught:
                pipeline.main()
            self.assertEqual(caught.exception.code, 2)
            self.assertIn('--stages needs --input markdown', err.getvalue())


if __name__ == '__main__':
    unittest.main()
