"""python -m choice_trust --help"""
import argparse
import json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description='Versioned adapter-based choice/explanation experiments; no GPU required.')
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare')
    p.add_argument('--source',type=Path,required=True); p.add_argument('--out',type=Path,required=True)
    p.add_argument('--adapter',choices=['generic','yogurt'],default='generic'); p.add_argument('--config',type=Path)
    for name in ('predict','explain','counterfactuals'):
        p=sub.add_parser(name)
        p.add_argument('--cases',type=Path,required=True); p.add_argument('--out',type=Path,required=True)
        p.add_argument('--split',choices=['all','development','validation','test'],default='test')
        p.add_argument('--limit',type=int,default=0); p.add_argument('--mock',action='store_true')
        p.add_argument('--conditions',nargs='+',choices=['full','no_history','with_history'],default=['full'])
        p.add_argument('--seed',type=int,default=42); p.add_argument('--random-controls',type=int,default=5)
        p.add_argument('--permutations',type=int,default=2)
        p.add_argument('--suite',choices=['all','explanation','systematic'],default='all',help='Intervention subset; presentation tests are included in explanation checks.')
        p.add_argument('--only-conditions',nargs='+',choices=['full','no_history','with_history'],help='Execute a subset of the fixed --conditions protocol without changing its identity.')
        p.add_argument('--plan',type=Path,help='Frozen study-plan JSON; use the same file for all stages.')
    for name in ('analyze','dashboard'):
        p=sub.add_parser(name); p.add_argument('--out',type=Path,required=True)
        p.add_argument('--bootstrap',type=int,default=500)
    p=sub.add_parser('import-legacy')
    p.add_argument('--source',type=Path,required=True); p.add_argument('--cases',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    sub.add_parser('health')
    args=parser.parse_args()
    if getattr(args,'limit',0)<0 or getattr(args,'random_controls',1)<1 or getattr(args,'permutations',1)<1 or getattr(args,'bootstrap',1)<1:
        parser.error('Limits must be nonnegative; controls, permutations and bootstrap must be positive')
    if args.command=='prepare':
        from .adapters import prepare
        if args.adapter=='generic' and not args.config: parser.error('Generic adapter requires --config')
        cases=prepare(args.source,args.out,json.loads(args.config.read_text()) if args.config else None,args.adapter)
        print(f'Prepared {len(cases)} cases in {args.out}')
    elif args.command=='health':
        from .model import RemoteBackend
        print(json.dumps(RemoteBackend().metadata,indent=2))
    elif args.command=='import-legacy':
        from .legacy import import_legacy
        import_legacy(args.source,args.cases,args.out)
    elif args.command in ('analyze','dashboard'):
        from .evaluation import analyze
        analyze(args.out,args.bootstrap)
        if args.command=='dashboard':
            from .dashboard import build
            build(args.out)
    else:
        from .runner import run
        run(args)


if __name__=='__main__':
    try: main()
    except (ValueError,OSError,RuntimeError,KeyError) as e: raise SystemExit(str(e))
