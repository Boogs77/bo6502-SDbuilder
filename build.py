#!/usr/bin/env python3
# Ricostruisce program1..4.bin (richiede cc65: ca65/ld65)
import subprocess
for n in range(1,5):
    subprocess.check_call(["ca65","-D",f"PROGNUM={n}","prog.s","-o",f"p{n}.o"])
    subprocess.check_call(["ld65","-C","ex.cfg",f"p{n}.o","-o",f"program{n}.bin"])
d = bytearray(open("program4.bin","rb").read())
assert len(d) <= 0x200, len(d)
d += bytes(0x200 - len(d))                      # fino a $1200
for a in range(0x1200, 0x8000):                 # pattern di test fino a $7FFF
    d.append((a & 0xFF) ^ (a >> 8))
open("program4.bin","wb").write(d)
for n in range(1,5):
    print(n, len(open(f"program{n}.bin","rb").read()))
