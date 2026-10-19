"""Standalone, offline HTML; data is embedded inertly and rendered as text."""
import json
import os
import re
from pathlib import Path
from .storage import load_run, output_snapshot
from experiment import digest


def scrub(value,secrets=()):
    if isinstance(value,dict):
        return {k:scrub(v,secrets) for k,v in value.items() if not re.search(r'(?i)(api.?key|authorization|password|secret|credential|access_token)',k)}
    if isinstance(value,list): return [scrub(v,secrets) for v in value]
    if isinstance(value,str):
        for secret in secrets:
            if len(secret)>=12: value=value.replace(secret,'[REDACTED]')
        return value
    return value


def safe_json(value):
    return json.dumps(value,ensure_ascii=True,allow_nan=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')


def build(out):
    manifest,cases,data=load_run(out)
    metrics=json.loads((out/'metrics.json').read_text())
    secrets=[os.environ.get('MODEL_API_KEY','')]
    env=Path(__file__).resolve().parent.parent/'.env'
    if env.exists():
        for line in env.read_text().splitlines():
            if '=' in line and re.search(r'(?i)(key|secret|password|token)',line.split('=',1)[0]): secrets.append(line.split('=',1)[1].strip().strip('\"\''))
    completion=None
    completion_note='No execution-completeness snapshot is available. Saved results alone do not establish that the planned study finished.'
    summary_path=out/'execution_summary.json'
    if summary_path.exists():
        saved=json.loads(summary_path.read_text())
        if saved.get('record_snapshot')==output_snapshot(out,data) and saved.get('study_plan_hash')==digest(manifest.get('study_plan')):
            completion=saved
            completion_note='Completion counts include responses with recorded issues and explicit skips; they do not mean the explanations passed their tests.'
        else:
            completion_note='The completion snapshot is outdated. Run the study report phase to refresh progress after changing outputs or reviews.'
    bundle=scrub(dict(manifest=manifest,cases=cases,metrics=metrics,completion=completion,completion_note=completion_note,**data),secrets)
    template=Path(__file__).with_name('dashboard.html').read_text()
    html=template.replace('__RUN_DATA__',safe_json(bundle))
    (out/'dashboard.html').write_text(html,encoding='utf-8')
    print(f'Open {out}/dashboard.html in a browser (no server required).')
