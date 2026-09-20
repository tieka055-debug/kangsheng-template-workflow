import copy
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('gate', Path(__file__).parents[1] / 'scripts/release_gate.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        artifacts = []
        for role in sorted(gate.ROLES):
            p = self.root / role; p.write_text('synthetic test ' + role)
            artifacts.append(dict(id=role, role=role, path=role, sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
        self.data = dict(schema_version=1, artifacts=artifacts,
            sources=[dict(artifact='source', page_count=1, reviewed_pages=[1])],
            outputs=[dict(artifact='output', page_count=1, reviewed_pages=[1])],
            groups=[dict(id='table1', source='source', source_page=1, kind='table',
                         placements=[dict(output='output', page=1)], source_rows=6,
                         source_columns=3, verified_rows=6, verified_columns=3, cells_verified=True)],
            checks={name:dict(status='pass', reviewer='synthetic-test',
                             reviewed_at='2026-01-01T00:00:00+00:00', evidence=['evidence']) for name in gate.CHECKS})
    def blocked(self): self.assertTrue(gate.validate(self.data, self.root))
    def test_complete_record(self): self.assertEqual(gate.validate(self.data, self.root), [])
    def test_changed_output(self): (self.root/'output').write_text('modified'); self.blocked()
    def test_changed_evidence(self): (self.root/'evidence').write_text('modified'); self.blocked()
    def test_missing_row(self): self.data['groups'][0]['verified_rows']=5; self.blocked()
    def test_unchecked_cells(self): self.data['groups'][0]['cells_verified']=False; self.blocked()
    def test_missing_source_page(self): self.data['sources'][0]['page_count']=2; self.blocked()
    def test_unmapped_reviewed_page(self): self.data['sources'][0].update(page_count=2,reviewed_pages=[1,2]); self.blocked()
    def test_missing_output_page(self): self.data['outputs'][0].update(page_count=2,reviewed_pages=[1,2]); self.blocked()
    def test_review_pending(self): self.data['checks']['tables']['status']='review'; self.blocked()
    def test_missing_check(self): del self.data['checks']['dimensions_symbols']; self.blocked()
    def test_invalid_evidence(self): self.data['checks']['tables']['evidence']=['output']; self.blocked()
    def test_no_reviewer(self): self.data['checks']['tables']['reviewer']=''; self.blocked()
    def test_future_review(self): self.data['checks']['tables']['reviewed_at']='2999-01-01T00:00:00Z'; self.blocked()
    def test_missing_artifact(self): (self.root/'source').unlink(); self.blocked()
    def test_bad_target(self): self.data['groups'][0]['placements'][0]['page']=2; self.blocked()
    def test_boolean_page(self): self.data['groups'][0]['source_page']=True; self.blocked()
    def test_empty(self): self.assertTrue(gate.validate({}, self.root))
    def test_duplicate_group(self): self.data['groups'].append(copy.deepcopy(self.data['groups'][0])); self.blocked()

if __name__ == '__main__': unittest.main()
