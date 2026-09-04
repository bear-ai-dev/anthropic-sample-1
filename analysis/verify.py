#!/usr/bin/env python3
"""Read-only checks of recovered evidence, adjudication, controls and labels."""
import collections
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def read(path):return json.loads((ROOT/path).read_text())
def sha(path):return hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
rows=read('indexes/trials.json')
review=read('analysis/fable-failure-modes.json')
source={r['canonical_id']:r for r in rows}
assert len(rows)==280 and len(source)==280
assert len(review['trials'])==40
assert collections.Counter(r['category'] for r in review['trials'])==review['counts']
for r in review['trials']:
    assert r['effective_reward']==source[r['canonical_id']]['reward']
    assert (r['category']=='SOLVED')==source[r['canonical_id']]['passed']
    assert (ROOT/r['requirement']).is_file() and (ROOT/r['verifier_detail']).is_file()
    steps={s['step_id'] for s in read(r['trace'])['steps']}
    assert all(a['step_id'] in steps for a in r['trace_anchors'])
recovered=read('analysis/recovered-evidence.json')
assert len(recovered['trials'])==40
for r in recovered['trials']:
    for f in r['files']:assert sha(f['path'])==f['published_sha256']
for task,controls in read('control-results.json')['controls'].items():
    for name,want in [('oracle',1.0),('nop',0.0)]:
        assert controls[name]['reward']==want
        assert all((ROOT/p).is_file() for p in controls[name]['evidence'])
admission=read('analysis/admission-review.json')['reviews']
assert len(admission)==7
assert all(r['status']!='task_side_pending_replay' for r in admission)
for r in admission:
    assert source[r['canonical_id']]['admission_status']==r['status']
    assert all((ROOT/p).is_file() for p in r['evidence'])
    steps={s['step_id'] for s in read(r['trace'])['steps']}
    assert all(s in steps for s in r['trace_step_ids'])
paired=read('analysis/cutover-replay/manifest.json')['controls_and_replays']
assert paired['original']['submission_content_sha256']==paired['corrected']['submission_content_sha256']
for kind,expected in [('oracle',1.0),('nop',0.0),('original',0.0),('corrected',0.0)]:
    assert paired[kind]['reward']['reward']==expected
    assert bool(paired[kind]['reward'].get('harness_failure'))==(kind=='original')
    assert paired[kind]['model_calls']==0
    for f in paired[kind]['files']:assert sha(f['path'])==f['sha256']
for f in read('indexes/artifacts.json'):assert sha(f['path'])==f['sha256']
print('PASS: 280 indexed trials; 40 Fable labels; 7 admission decisions; 10 controls; paired zero-model-call replay; artifact hashes')
