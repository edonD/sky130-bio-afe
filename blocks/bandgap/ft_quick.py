import subprocess, os, re, sys
import numpy as np
with open('design.cir') as f: base = f.read()
base = re.sub(r'(\.param\s+p_rptat_l\s*=\s*)\S+', r'\g<1>13.0e-6', base)
n = re.sub(r'\.control.*?\.endc', '', base, flags=re.DOTALL)
n = re.sub(r'\.end\s*$', '', n, flags=re.MULTILINE)
n += """
.control
op
let vref_val = v(vref)
print vref_val
dc VDD 1.98 1.62 -0.01
wrdata ft_sup v(vref)
dc temp 125 -40 -1
wrdata ft_temp v(vref)
quit
.endc
.end
"""
with open('ft_test.cir','w') as f: f.write(n)
subprocess.run(['ngspice','-b','ft_test.cir'], capture_output=True, text=True, timeout=120, cwd='sky130_models')
arr = []
with open('ft_sup') as f:
    for line in f:
        parts = line.strip().split()
        if len(parts)>=2:
            try: arr.append([float(p) for p in parts[:2]])
            except: pass
if arr:
    arr = np.array(arr)
    dv = arr[0,1]-arr[-1,1]; dvdd = arr[0,0]-arr[-1,0]
    psrr = 20*np.log10(abs(dvdd/dv)) if abs(dv)>1e-15 else 999
else: psrr=0
arr2 = []
with open('ft_temp') as f:
    for line in f:
        parts = line.strip().split()
        if len(parts)>=2:
            try: arr2.append([float(p) for p in parts[:2]])
            except: pass
if arr2:
    arr2 = np.array(arr2)
    vrefs = arr2[:,1]; temps = arr2[:,0]
    idx27 = np.argmin(np.abs(temps-27))
    vnom = vrefs[idx27]; vref = vnom
    tc = (np.max(vrefs)-np.min(vrefs))/(vnom*165)*1e6
else: tc=9999; vref=0
vm = (0.05-abs(vref-1.20))/0.05*100 if 1.15<=vref<=1.25 else -999
tm = (50-tc)/50*100
pm = (psrr-60)/60*100
mn = min(vm,tm,pm)
print(f'rptat=13.0: vref={vref:.4f} tc={tc:.1f} psrr={psrr:.1f} vm={vm:.0f} tm={tm:.0f} pm={pm:.0f} min={mn:.0f}')
