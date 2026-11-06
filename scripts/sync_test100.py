#!/usr/bin/env python3
"""Download saved EC2 results only. Never infer, start a runner, or annotate."""
import argparse,json,os,shlex,subprocess,tarfile,tempfile
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host',default='ubuntu@54.252.237.68')
    p.add_argument('--key',type=Path,default=Path.home()/'Downloads/llm-experiment.pem')
    p.add_argument('--remote-out',default='/home/ubuntu/customer-choice-trust/continuations/test_with_history_100_v1/choice_study/test_with_history_100_v1')
    p.add_argument('--out',type=Path,default=ROOT/'choice_study/test_with_history_100_v1')
    a=p.parse_args();local=json.loads((a.out/'manifest.json').read_text())
    command=['ssh','-i',str(a.key),'-o','BatchMode=yes','-o','ConnectTimeout=15',a.host]
    code="from pathlib import Path;import json;print(json.loads((Path("+repr(a.remote_out)+")/'manifest.json').read_text())['plan_id'])"
    result=subprocess.run(command+['python3 -c '+shlex.quote(code)],check=True,capture_output=True,text=True)
    if result.stdout.strip()!=local['plan_id']:raise ValueError('Remote selection/manifest differs; refusing mixed snapshot')
    code='''from pathlib import Path
import sys,tarfile
root=Path(REMOTE_OUT)
with tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz') as tf:
 for f in sorted(root.rglob('*')):
  rel=f.relative_to(root)
  if not f.is_file() or any(x.startswith('.') for x in rel.parts):continue
  if rel.parts[0] in ('manifest.json','deployment_files.json','selected_cases.json','remaining_test_case_ids.json','evaluation_targets.json','registry.json','protocol.json'):continue
  if f.suffix not in ('.json','.jsonl','.log','.md'):continue
  try:tf.add(f,arcname=str(rel),recursive=False)
  except FileNotFoundError:pass
'''.replace('REMOTE_OUT',repr(a.remote_out))
    copied=0
    with tempfile.TemporaryDirectory() as temp:
        archive=Path(temp)/'snapshot.tar.gz'
        with archive.open('wb') as stream:
            subprocess.run(command+['python3 -c '+shlex.quote(code)],check=True,stdout=stream)
        with tarfile.open(archive,'r:gz') as tf:
            for member in tf:
                rel=Path(member.name)
                if rel.is_absolute() or '..' in rel.parts or not member.isfile():raise ValueError('Unexpected snapshot path/type')
                data=tf.extractfile(member).read();dest=a.out/rel
                immutable=rel.parts[0] in ('responses','server_responses','received') or rel.name in ('execution_config.json','rendered_prompts.json')
                if immutable and dest.exists():
                    if dest.read_bytes()!=data:raise ValueError('Completed immutable local record differs: '+str(rel))
                    continue
                dest.parent.mkdir(parents=True,exist_ok=True)
                tmp=dest.with_name('.'+dest.name+'.sync');tmp.write_bytes(data);os.replace(tmp,dest);copied+=1
    (a.out/'snapshot_sync.json').write_text(json.dumps({'snapshot_utc':datetime.now(timezone.utc).isoformat(),'host':a.host,'remote_out':a.remote_out,'plan_id':local['plan_id'],'files_copied':copied,'read_only_remote':True,'inference_calls':0},indent=2)+'\n')
    print(json.dumps({'files_copied':copied,'local_snapshot':str(a.out),'plan_id':local['plan_id'],'inference_calls':0},indent=2))

if __name__=='__main__':main()
