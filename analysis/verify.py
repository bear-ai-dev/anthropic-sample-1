#!/usr/bin/env python3
"""Read-only checks of recovered evidence, adjudication, controls and labels."""
import collections
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def read(path):return json.loads((ROOT/path).read_text())
def sha(path):return hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
rows=read('indexes/trials.json')
for folder in ('results', 'verification', 'trajectories', 'controls', 'analysis', 'indexes', 'docs', 'tasks', 'shared'):
    for path in (ROOT/folder).rglob('*'):
        if path.is_dir():
            assert not re.search(r'bedrock|open.?router', path.name, re.I), path
review=read('analysis/fable-failure-modes.json')
source={r['canonical_id']:r for r in rows}
assert len(rows)==200 and len(source)==200
assert {r['harness'] for r in rows if r['model_label']=='Fable 5.1'}=={'Claude Code'}
assert {r['harness'] for r in rows if r['model_label']=='Grok 4.6'}=={'Grok Build'}
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
for task,controls in read('controls/control-results.json')['controls'].items():
    for name,want in [('oracle',1.0),('nop',0.0)]:
        assert controls[name]['reward']==want
        assert all((ROOT/p).is_file() for p in controls[name]['evidence'])
admission=read('analysis/admission-review.json')['reviews']
assert len(admission)==5
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
opus=read('analysis/opus-task-provenance.json')
opus_rows=[r for r in rows if r['model_label']=='Opus 5']
assert len(opus_rows)==40 and sum(r['passed'] for r in opus_rows)==6
native=reconstructed=0;seen=set()
assert len(opus['runs'])==4
for version in opus['task_versions']:
    checksum=version['checksum'];assert re.fullmatch('[a-f0-9]{64}',checksum)
    assert re.fullmatch('sha256:[a-f0-9]{64}',version['image_digest'])
    assert version['run_id'] in {r['run_id'] for r in opus['runs']}
    assert {a['filename'] for a in version['inputs']}=={'task.toml','instruction.md','environment.tar.gz','tests.tar.gz','solution.tar.gz'}
    for item in version['inputs']:
        assert re.fullmatch('[a-f0-9]{64}',item['sha256'])
        assert all(datetime.fromisoformat(item['last_modified'])<datetime.fromisoformat(t['first_event']) for t in version['trials'])
    for trial in version['trials']:
        cid=trial['canonical_id'];assert cid not in seen;seen.add(cid);row=source[cid]
        assert row['task']==version['task'] and row['task_checksum']==checksum
        assert row['task_checksum_source']==trial['checksum_source']
        assert row['task_provenance']=='analysis/opus-task-provenance.json'
        assert sha(trial['original_result'])==trial['original_result_sha256']
        assert read(trial['original_result'])['task_checksum']==trial['recorded_checksum']
        assert sha(row['trajectory'])==trial['published_trajectory_sha256']
        trace=read(row['trajectory'])
        assert trace['session_id']==trial['trajectory_session_id'] and len(trace['steps'])==trial['trajectory_steps']
        assert trial['ddb_trial_binding_verified'] and trial['aws_result_fields_verified'] and trial['trajectory_step_identity_verified']
        assert row['reward']==trial['reward']
        if trial['checksum_source']=='native':
            native+=1;assert trial['recorded_checksum']==checksum and trial['native_checksum_match']
        else:
            reconstructed+=1;assert trial['recorded_checksum']=='recovered-from-original-sandbox' and not trial['native_checksum_match']
assert (native,reconstructed)==(10,30) and seen=={r['canonical_id'] for r in opus_rows}
for f in read('indexes/artifacts.json'):assert sha(f['path'])==f['sha256']
print('PASS: 200 indexed trials for the five reported configurations; 40 Fable labels; 40 Opus identities (10 native/30 reconstructed); 5 admission decisions; 10 controls; paired zero-model-call replay; artifact hashes')
