#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
import sys
BASE=Path(__file__).resolve().parent; sys.path.insert(0,str(BASE/"lib"))
from auditing import audit

def main(argv=None):
 p=argparse.ArgumentParser(); p.add_argument("--manifest",type=Path,default=BASE/"manifest.json"); p.add_argument("--report",type=Path,required=True); p.add_argument("--require-independent-signoff",action="store_true"); p.add_argument("--signoff",type=Path); a=p.parse_args(argv)
 result=audit(a.manifest,a.report,a.require_independent_signoff,a.signoff); print(json.dumps(result,sort_keys=True,indent=2)); return 0 if result["ok"] else 1
if __name__=="__main__": raise SystemExit(main())
