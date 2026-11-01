import csv,statistics as s,collections,sys
d=collections.defaultdict(list); L=collections.defaultdict(list)
for r,sc,cfg,q,ms,l in csv.reader(open(sys.argv[1]),delimiter='\t'):
    d[(sc,q,cfg)].append(float(ms)); L[(sc,q,cfg)].append(float(l))
cfgs=[c for c in ["V0","L_arr","C_gin_arr","C_gin_slots","C_gpo_arr","C_gpo_slots","C_none_slots"] if any(k[2]==c for k in d)]
print("scope query | "+" | ".join(cfgs)+"   (median ms [min-max]; *=spread>1.5x; ratio vs V0 in parens; 90000=timeout)")
for sc in sorted({k[0] for k in d}):
  for q in sorted({k[1] for k in d}):
    base=s.median(d[(sc,q,"V0")]); cells=[]
    for c in cfgs:
      x=d[(sc,q,c)]; m=s.median(x); sp=max(x)/min(x)
      cells.append(f"{m:.0f} [{min(x):.0f}-{max(x):.0f}]{'*' if sp>1.5 else ''} ({m/base:.1f}x)")
    print(f"{sc} {q} | "+" | ".join(cells))
ls=[float(l) for v in L.values() for l in v]; print(f"load range {min(ls):.1f}-{max(ls):.1f}")
