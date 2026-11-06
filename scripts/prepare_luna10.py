#!/usr/bin/env python3
"""Prepare/inspect the10 original-only Luna jobs. This CLI cannot make API calls."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from choice_trust.luna_annotations import LunaInspection,DEFAULT_OUT

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',choices=['prepare','status','preview']);p.add_argument('--out',type=Path,default=DEFAULT_OUT);a=p.parse_args()
 i=LunaInspection.prepare(a.out) if a.stage=='prepare' else LunaInspection(a.out)
 print(json.dumps(i.preview() if a.stage=='preview' else i.status(),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
