#!/usr/bin/env python3
"""Calculate frozen test-100 metrics from saved records; never infer or annotate."""
from pathlib import Path
import argparse,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from choice_trust.test100_metrics import calculate,write_analysis,DEFAULT_OUT,format_rate


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study',type=Path,default=DEFAULT_OUT)
    parser.add_argument('--out',type=Path)
    args=parser.parse_args();result=calculate(args.study);out=write_analysis(result,args.out or args.study/'analysis_v1');m=result['metrics']
    print('Original accuracy:',format_rate(m['original_accuracy']))
    for r in m['prediction_change_by_family']:print(r['family'],format_rate(r['change_rate']),'skipped',r['skipped'])
    print('Linked annotations:',m['annotation_coverage']['linked_total'],'of',m['annotation_coverage']['distinct_responses'])
    print('Outputs:',out)


if __name__=='__main__':main()
