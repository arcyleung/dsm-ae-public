#!/usr/bin/env python3
"""Non-functional cost of ill-behaviours, holding functional outcome fixed.

A behaviour can leave pass/fail untouched and still be expensive. This asks:
among runs that produced the SAME outcome, what did the behaviour cost in
completion tokens?

Conditioning on outcome is the point. A correctness-only evaluation scores a
sprawling 30k-token success identically to a clean 19k-token one; this makes
the difference visible. CIs are cluster bootstraps resampling instances, since
the same instance is attempted more than once.

Endogeneity caveat, which belongs with every number this prints: harder
instances plausibly induce both more sprawl and more tokens, so part of any
ratio is difficulty rather than behaviour. The tokens were still spent.

Token data exists only for the opencode bundle (652 of 1260 trials); the
claude-code bundle does not record completion_tokens.
"""
import random
from pathlib import Path
from collections import defaultdict
from dsm_ae.harbor import iter_runs, scoreable_only
from dsm_ae.harbor.instruments import score_trajectory

random.seed(42)
rows=[]
for _r,ts in iter_runs(Path('evalhub-extract')):
    for t in scoreable_only(ts):
        if t.source!='swebenchpro' or t.completion_tokens<=0: continue
        rows.append(dict(fail=(not t.success), task=t.task_name, h=t.harness,
                         tok=t.completion_tokens, s=score_trajectory(t)))
print('trials with token data:',len(rows),' harness:',{r['h'] for r in rows})

def med(v):
    v=sorted(v); return v[len(v)//2] if v else 0.0

def boot_ratio(sub,key,B=3000):
    by=defaultdict(list)
    for r in sub: by[r['task']].append(r)
    keys=list(by); out=[]
    for _ in range(B):
        samp=[]
        for _ in keys: samp+=by[random.choice(keys)]
        b=[r['tok'] for r in samp if r['s'][key]]
        nb=[r['tok'] for r in samp if not r['s'][key]]
        if len(b)<5 or len(nb)<5: continue
        m=med(nb)
        if m>0: out.append(med(b)/m)
    out.sort()
    return (out[int(.025*len(out))], out[int(.975*len(out))]) if out else (None,None)

print()
print("COMPLETION TOKENS, conditional on outcome (opencode bundle only)")
print(f"{'instrument':22s}{'outcome':>7}{'n(B)':>6}{'med tok B':>11}{'med tok !B':>12}{'ratio':>7}  95% CI")
for key in ('scope_creep','thrash_edit','read_loop','destructive_command'):
    for outcome,lab in ((False,'PASS'),(True,'FAIL')):
        sub=[r for r in rows if r['fail']==outcome]
        b=[r['tok'] for r in sub if r['s'][key]]
        nb=[r['tok'] for r in sub if not r['s'][key]]
        if len(b)<25 or len(nb)<25: continue
        lo,hi=boot_ratio(sub,key)
        ci=f"[{lo:.2f}, {hi:.2f}]" if lo else "-"
        print(f"{key:22s}{lab:>7}{len(b):>6}{med(b):>11.0f}{med(nb):>12.0f}{med(b)/med(nb):>7.2f}  {ci}")
import random
from pathlib import Path
from collections import defaultdict
from dsm_ae.harbor import iter_runs, scoreable_only
from dsm_ae.harbor.instruments import score_trajectory

random.seed(42)
rows=[]
for _r,ts in iter_runs(Path('evalhub-extract')):
    for t in scoreable_only(ts):
        if t.source!='swebenchpro' or t.completion_tokens<=0: continue
        rows.append(dict(fail=(not t.success), task=t.task_name, h=t.harness,
                         tok=t.completion_tokens, s=score_trajectory(t)))
print('trials with token data:',len(rows),' harness:',{r['h'] for r in rows})

def med(v):
    v=sorted(v); return v[len(v)//2] if v else 0.0

def boot_ratio(sub,key,B=3000):
    by=defaultdict(list)
    for r in sub: by[r['task']].append(r)
    keys=list(by); out=[]
    for _ in range(B):
        samp=[]
        for _ in keys: samp+=by[random.choice(keys)]
        b=[r['tok'] for r in samp if r['s'][key]]
        nb=[r['tok'] for r in samp if not r['s'][key]]
        if len(b)<5 or len(nb)<5: continue
        m=med(nb)
        if m>0: out.append(med(b)/m)
    out.sort()
    return (out[int(.025*len(out))], out[int(.975*len(out))]) if out else (None,None)

print()
print("COMPLETION TOKENS, conditional on outcome (opencode bundle only)")
print(f"{'instrument':22s}{'outcome':>7}{'n(B)':>6}{'med tok B':>11}{'med tok !B':>12}{'ratio':>7}  95% CI")
for key in ('scope_creep','thrash_edit','read_loop','destructive_command'):
    for outcome,lab in ((False,'PASS'),(True,'FAIL')):
        sub=[r for r in rows if r['fail']==outcome]
        b=[r['tok'] for r in sub if r['s'][key]]
        nb=[r['tok'] for r in sub if not r['s'][key]]
        if len(b)<25 or len(nb)<25: continue
        lo,hi=boot_ratio(sub,key)
        ci=f"[{lo:.2f}, {hi:.2f}]" if lo else "-"
        print(f"{key:22s}{lab:>7}{len(b):>6}{med(b):>11.0f}{med(nb):>12.0f}{med(b)/med(nb):>7.2f}  {ci}")
