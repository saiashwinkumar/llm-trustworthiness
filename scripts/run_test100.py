#!/usr/bin/env python3
"""Prepare/status/run only the frozen test/with-history 100-case joint study."""
import argparse,json,os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from choice_trust.test100_plan import prepare,DEFAULT_OUT
from choice_trust.test100_execution import Study,HTTPClient,original_candidates,write_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=['plan','status','run','reuse-inventory'])
    parser.add_argument('--out',type=Path,default=DEFAULT_OUT)
    parser.add_argument('--base-url',default='http://127.0.0.1:8000')
    args=parser.parse_args()
    if args.stage=='plan':prepare(args.out)
    study=Study(args.out)
    if args.stage=='run':
        study.run(HTTPClient(args.base_url,timeout=900));return
    if args.stage=='reuse-inventory':
        index={e['case_id']:e for e in study.manifest['entries'] if e['family']=='ORIGINAL'}
        candidates=[]
        for p,o,r in original_candidates(Path(__file__).resolve().parents[1]):
            e=index.get(o.get('case_id'))
            if e and r.get('messages')==e['messages']:
                candidates.append({'case_id':e['case_id'],'source_path':str(p),'runtime_match':'not yet verified'})
        inventory={'matching_input_candidates':candidates,'verified_reused':0,
          'originals_without_matching_input_candidate':100-len({c['case_id'] for c in candidates}),
          'note':'Full runtime/tokenizer/rendered-prompt/settings match is checked before reuse on the execution host.'}
        write_json(args.out/'reuse_inventory.json',inventory);print(json.dumps(inventory,indent=2));return
    study.initialize()
    print(json.dumps(study.status(),indent=2))


if __name__=='__main__':main()
