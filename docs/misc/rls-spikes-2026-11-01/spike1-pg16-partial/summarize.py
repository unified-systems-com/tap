import csv,statistics as s,collections,sys
d=collections.defaultdict(list); L=collections.defaultdict(list)
for r,v,q,ms,l in csv.reader(open(sys.argv[1]),delimiter='\t'):
    d[(q,v)].append(float(ms)); L[(q,v)].append(float(l))
vs=sorted({v for _,v in d}); 
print("query | "+" | ".join(f"{v} med (min-max, spread)" for v in vs)+" | ratios vs V0 | load range")
for q in sorted({q for q,_ in d}):
    row=[];med={}
    for v in vs:
        x=d[(q,v)]; med[v]=s.median(x); sp=max(x)/min(x)
        row.append(f"{med[v]:.0f} ms ({min(x):.0f}-{max(x):.0f}, {sp:.1f}x{' UNRELIABLE' if sp>1.5 else ''})")
    rat=", ".join(f"{v}/V0={med[v]/med['V0']:.2f}" for v in vs if v!='V0')
    ls=[l for v in vs for l in L[(q,v)]]
    print(f"{q} | "+" | ".join(row)+f" | {rat} | {min(ls):.1f}-{max(ls):.1f}")
