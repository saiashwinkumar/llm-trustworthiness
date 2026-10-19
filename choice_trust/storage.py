"""Content-linked append-only records, atomic manifests and single-writer locks."""
import json
import hashlib
import os
from contextlib import contextmanager
from pathlib import Path
from experiment import digest, read_jsonl, append_jsonl
from . import PROTOCOL_VERSION


def output_snapshot(out, data):
    """Bind display-only completion information to recorded outputs and audit."""
    audit = Path(out) / 'manual_audit.csv'
    return {**{name: digest([row['record_hash'] for row in data[name]])
               for name in ('predictions', 'explanations', 'interventions')},
            'manual_audit_sha256': hashlib.sha256(audit.read_bytes()).hexdigest() if audit.exists() else None}


def atomic_json(path, value):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    with temp.open('w',encoding='utf-8') as f:
        f.write(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
        f.flush(); os.fsync(f.fileno())
    os.replace(temp,path)


def write_jsonl(path,rows):
    with Path(path).open('x',encoding='utf-8') as f:
        for r in rows: f.write(json.dumps(r,ensure_ascii=False,allow_nan=False)+'\n')


def seal(row):
    row=dict(row)
    row['record_hash']=digest({k:v for k,v in row.items() if k!='record_hash'})
    return row


def records(path, repair=False):
    rows=read_jsonl(Path(path),repair)
    seen=set()
    for r in rows:
        if seal(r)['record_hash']!=r.get('record_hash'): raise ValueError(f'Record content changed in {path}')
        key=r['record_id']
        if key in seen: raise ValueError(f'Duplicate record ID in {path}')
        seen.add(key)
    return rows


def append(path,row):
    row=seal(row)
    append_jsonl(Path(path),row)
    return row


@contextmanager
def writer_lock(out):
    out.mkdir(parents=True,exist_ok=True)
    path=out/'.writer.lock'
    try: fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError: raise ValueError('Run locked by another writer. After a crash, verify the recorded PID is stopped before removing .writer.lock.')
    try:
        os.write(fd,str(os.getpid()).encode()); os.close(fd)
        yield
    finally: path.unlink(missing_ok=True)


def code_hash():
    root=Path(__file__).parent
    return digest({p.name:p.read_text() for p in sorted(root.glob('*')) if p.suffix in ('.py','.html')})


def init_run(out,cases,dataset_manifest,backend,settings,study_plan=None):
    from .model import PROMPT_VERSION, CITATION_POLICY_VERSION
    identity=dict(schema_version=2,protocol_version=PROTOCOL_VERSION,code_hash=code_hash(),
                  cases_hash=digest(cases),dataset_manifest=dataset_manifest,backend=backend.metadata,
                  settings=settings,prompt_version=PROMPT_VERSION,citation_policy_version=CITATION_POLICY_VERSION,
                  decoding={'do_sample':False,'enable_thinking':False},
                  splits={c['case_id']:c['split'] for c in cases},
                  study_plan=study_plan,
                  warnings=[study_plan['interpretation']] if study_plan and study_plan.get('interpretation') else [])
    path=out/'run_manifest.json'
    if path.exists():
        if json.loads(path.read_text())!=identity: raise ValueError('Incompatible dataset/model/code/protocol/settings; choose a NEW --out directory')
        if digest(read_jsonl(out/'cases.jsonl'))!=identity['cases_hash']: raise ValueError('Run case snapshot changed')
    else:
        if any(out.iterdir()) and set(p.name for p in out.iterdir())!={'.writer.lock'}:
            raise ValueError('Refusing to adopt a nonempty unversioned output directory')
        write_jsonl(out/'cases.jsonl',cases)
        atomic_json(path,identity)
    return digest(identity)


def load_run(out,repair=False):
    out=Path(out)
    manifest=json.loads((out/'run_manifest.json').read_text())
    cases=read_jsonl(out/'cases.jsonl')
    if digest(cases)!=manifest['cases_hash']: raise ValueError('Dataset snapshot changed')
    run_id=digest(manifest)
    data={name:records(out/(name+'.jsonl'),repair) for name in ('predictions','explanations','interventions')}
    predictions={r['record_id']:r for r in data['predictions']}
    explanations={r['record_id']:r for r in data['explanations']}
    for rows in data.values():
        for r in rows:
            if r['run_id']!=run_id: raise ValueError('Record joined across incompatible runs')
            if 'prediction_hash' in r:
                p=predictions.get(r['prediction_id'])
                if not p or p['record_hash']!=r['prediction_hash']: raise ValueError('Source prediction changed or is missing')
            if 'explanation_hash' in r and r['explanation_hash'] is not None:
                e=explanations.get(r['explanation_id'])
                if not e or e['record_hash']!=r['explanation_hash']: raise ValueError('Source explanation changed or is missing')
    return manifest,cases,data
