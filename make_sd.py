#!/usr/bin/env python3
"""
make_sd.py - crea la SD (o l'immagine) con i programmi per il menu "SD PROGRAMS" del BO6502.

Layout (RAW, senza filesystem; SD standard capacity <= 2GB, indirizzamento a byte):
  DIRECTORY A PAGINE (versione 3): 9 programmi per pagina, fino a 255 programmi (29 pagine).
  La pagina P (P = 0, 1, ...) sta nel PRIMO SETTORE del blocco da 32KB numero P, cioe' all'offset P * $8000:
      +0..3   "BOGS"   +4 versione (3)   +5 numero di programmi DI QUESTA PAGINA (1..9)
      +6..14  flag della voce 0..8 (bit0 = ESEGUI)   +15 numero TOTALE di programmi
      +16+i*8 parametri della voce i: indirizzo di caricamento (lo,hi), lunghezza (lo,hi), entry (lo,hi), 0, 0
      +96+i*32 nome della voce i (ASCII, max 31 car. + $00)
  Il menu del BIOS mostra una pagina alla volta (tasti A/D per cambiare pagina, 1..9 per scegliere).
  programma N (N = 1..255) -> blocco da 32KB all'offset (N-1) * $8000
      +$0000..+$0FFF  riservato (nel primo settore sta la pagina di directory, se esiste; il secondo settore
                      contiene una riga di info ASCII). Non viene mai letto in RAM.
      +$1000..        i byte del programma (max $7000), copiati in RAM a partire dall'indirizzo di caricamento.
  Il BIOS scrive in RAM ESATTAMENTE [load, load+lunghezza): il resto della RAM non viene toccato.

Programmi: programN.bin = binario grezzo. In alternativa programN.txt / programN.hex = dump esadecimale stile
WozMon ("0FD0: 4C 27 11 ..."), da cui lo script ricava anche l'indirizzo di caricamento.

Nomi: file di testo (default programs.txt nella cartella dei programmi, o -l FILE), nomi separati da ';'
(anche su piu' righe). Il primo nome e' il programma 1, il secondo il 2, ...
    [!]Nome[@LOAD[:ENTRY]]
  !      programma ESEGUITO subito dopo il caricamento (nel menu "N>"); senza '!' viene solo caricato ("N.")
  @LOAD  indirizzo RAM di caricamento in esadecimale (default 1000; non serve per i dump .txt/.hex)
  :ENTRY indirizzo di esecuzione (default: 1000 se cade nell'immagine caricata, altrimenti LOAD)
Esempio programs.txt:   Banner; !Arcade Tank@0FD0; Test RAM@1000
Con --run-all tutti i programmi vengono eseguiti dopo il caricamento.

Esempi:
  python3 make_sd.py                               # legge programs.txt e program1..N dalla cartella corrente
  python3 make_sd.py -n 4 -l nomi.txt              # solo i primi 4 programmi
  python3 make_sd.py -o /dev/sdX --yes             # scrive DIRETTAMENTE sulla scheda (distrugge i dati!)
  python3 make_sd.py -o '\\\\.\\PhysicalDrive2'      # Windows, da prompt Amministratore
"""
import argparse, os, re, sys, zlib

BLOCK      = 0x8000          # 32KB per programma
RESERVED   = 0x1000          # dati del programma a blocco + $1000
PAYLOAD    = BLOCK - RESERVED  # 0x7000 = 28KB max per programma
SECTOR     = 512
RAM_END    = 0x8000          # primo indirizzo non scrivibile
MAX_PROGS  = 255             # il driver indirizza gli slot con 1 byte (0..254)
PER_PAGE   = 9               # programmi per pagina di menu (tasti '1'..'9')

DIR_MAGIC  = b"BOGS"
DIR_VER    = 3
DIR_TOTAL  = 15              # byte con il numero totale di programmi
DIR_PARAMS = 16              # tabella parametri: 8 byte per programma
DIR_PSIZE  = 8
DIR_NAMES  = 96              # nomi: 32 byte per programma
DIR_ESIZE  = 32              # 31 caratteri + $00
NAME_MAX   = DIR_ESIZE - 1
DEFAULT_LOAD = 0x1000

def parse_hex(s, what):
    try:
        v = int(s, 16)
    except ValueError:
        sys.exit(f"ERRORE: indirizzo esadecimale non valido in {what}: {s!r}")
    if not 0 <= v <= 0xFFFF:
        sys.exit(f"ERRORE: indirizzo fuori da $0000-$FFFF in {what}: {s!r}")
    return v

def read_names(path, keep_case):
    """Legge [!]Nome[@LOAD[:ENTRY]] separati da ';' (e/o a capo)."""
    raw = open(path, "r", encoding="utf-8-sig", errors="replace").read()
    items = []
    for part in raw.replace("\r", "\n").replace("\n", ";").split(";"):
        p = part.strip()
        if not p:
            continue
        run = p.startswith("!")
        if run:
            p = p[1:].strip()
        load = entry = None
        m = re.search(r"@\s*([0-9A-Fa-f]+)\s*(?::\s*([0-9A-Fa-f]+))?\s*$", p)
        if m:
            load = parse_hex(m.group(1), f"'{p}'")
            if m.group(2):
                entry = parse_hex(m.group(2), f"'{p}'")
            p = p[:m.start()].strip()
        if not p:
            continue
        if not keep_case:
            p = p.upper()
        p = "".join(ch if 0x20 <= ord(ch) <= 0x7E else "?" for ch in p)
        if len(p) > NAME_MAX:
            print(f"ATTENZIONE: nome troppo lungo, troncato a {NAME_MAX} caratteri: {p!r}")
            p = p[:NAME_MAX]
        items.append({"name": p, "run": run, "load": load, "entry": entry})
    return items

def read_hexdump(path):
    """Dump stile WozMon 'ADDR: HH HH ...' -> (indirizzo_iniziale, bytes). Errore se non contiguo."""
    mem = {}
    for line in open(path, "r", errors="replace"):
        m = re.match(r"\s*([0-9A-Fa-f]{4}):\s*((?:[0-9A-Fa-f]{2}\s*)+)$", line)
        if not m:
            continue
        a = int(m.group(1), 16)
        for i, b in enumerate(m.group(2).split()):
            mem[a + i] = int(b, 16)
    if not mem:
        sys.exit(f"ERRORE: nessuna riga 'ADDR: byte...' trovata in {path}")
    lo, hi = min(mem), max(mem)
    if len(mem) != hi - lo + 1:
        sys.exit(f"ERRORE: {path}: il dump non e' contiguo (buchi tra ${lo:04X} e ${hi:04X})")
    return lo, bytes(mem[a] for a in range(lo, hi + 1))

def find_program(dirpath, n):
    """Restituisce (path, dati, load_dal_dump_o_None)."""
    b = os.path.join(dirpath, f"program{n}.bin")
    if os.path.isfile(b):
        return b, open(b, "rb").read(), None
    for ext in ("txt", "hex"):
        t = os.path.join(dirpath, f"program{n}.{ext}")
        if os.path.isfile(t):
            load, data = read_hexdump(t)
            return t, data, load
    return None, None, None

def build_directory(progs, page, total):
    """Settore di directory della pagina `page`: contiene i programmi progs[page*9 : page*9+9]."""
    d = bytearray(SECTOR)
    d[0:4] = DIR_MAGIC
    d[4] = DIR_VER
    chunk = progs[page * PER_PAGE:(page + 1) * PER_PAGE]
    d[5] = len(chunk)
    d[DIR_TOTAL] = total
    for i, p in enumerate(chunk):
        d[6 + i] = 1 if p["run"] else 0               # flag: bit0 = esegui dopo il caricamento
        o = DIR_PARAMS + i * DIR_PSIZE
        d[o:o + 2] = p["load"].to_bytes(2, "little")
        d[o + 2:o + 4] = p["len"].to_bytes(2, "little")
        d[o + 4:o + 6] = p["entry"].to_bytes(2, "little")
        o = DIR_NAMES + i * DIR_ESIZE
        d[o:o + len(p["name"])] = p["name"].encode("ascii")    # il resto resta $00
    return bytes(d)

def build_block(n, p):
    info = (f"BO6502 SD PROGRAM {n} slot={n-1} file={os.path.basename(p['path'])} load={p['load']:04X} "
            f"len={p['len']} entry={p['entry']:04X} crc32={zlib.crc32(p['data']):08X}\n").encode("ascii")
    block = bytearray(BLOCK)
    block[SECTOR:SECTOR + len(info)] = info               # 2o settore della zona riservata
    block[RESERVED:RESERVED + p["len"]] = p["data"]
    return bytes(block)

def is_device(path):
    return path.startswith("/dev/") or path.startswith("\\\\.\\")

def main():
    ap = argparse.ArgumentParser(description="Crea SD/immagine multi-programma per BO6502",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("-n", "--num", type=int, help=f"numero di programmi (1..{MAX_PROGS}, 9 per pagina di menu); default = numero di nomi")
    ap.add_argument("-l", "--list", help="file con i nomi separati da ';' (default: programs.txt nella cartella -d)")
    ap.add_argument("--run-all", action="store_true", help="tutti i programmi vengono eseguiti dopo il caricamento")
    ap.add_argument("--keep-case", action="store_true", help="non convertire i nomi in maiuscolo")
    ap.add_argument("-d", "--dir", default=".", help="cartella con i programmi (default .)")
    ap.add_argument("-o", "--output", default="sd.img", help="file immagine o device (default sd.img)")
    ap.add_argument("--min-load", default="0F00", help="indirizzo minimo di caricamento consentito, hex (default 0F00, "
                    "lo stesso sd_min_load del BIOS)")
    ap.add_argument("--allow-missing", action="store_true", help="se programN manca, lascia il blocco vuoto")
    ap.add_argument("--no-verify", action="store_true", help="non rileggere e confrontare dopo la scrittura")
    ap.add_argument("--yes", action="store_true", help="non chiedere conferma per la scrittura su device")
    a = ap.parse_args()
    min_load = parse_hex(a.min_load, "--min-load")

    listfile = a.list or os.path.join(a.dir, "programs.txt")
    items = []
    if os.path.isfile(listfile):
        items = read_names(listfile, a.keep_case)
        print(f"Nomi letti da {listfile}: {len(items)}")
    elif a.list:
        sys.exit(f"ERRORE: file nomi non trovato: {listfile}")
    else:
        print(f"ATTENZIONE: {listfile} non trovato: i programmi si chiameranno PROGRAM 1, PROGRAM 2, ...")
    num = a.num if a.num is not None else len(items)
    if a.num is None and not items:
        sys.exit("ERRORE: indica -n oppure fornisci un file nomi")
    if not 1 <= num <= MAX_PROGS:
        sys.exit(f"ERRORE: i programmi devono essere tra 1 e {MAX_PROGS}, trovati {num}")
    if len(items) > num:
        print(f"ATTENZIONE: {len(items)} nomi ma solo {num} programmi: ignoro i nomi in piu'")
        items = items[:num]
    while len(items) < num:
        items.append({"name": f"PROGRAM {len(items)+1}", "run": False, "load": None, "entry": None})

    progs, blocks = [], []
    print(f"{'Pag.Tasto':<10}{'File':<14}{'Byte':>6}  {'Offset SD':<10}{'RAM':<12}{'Entry':<7}{'Modo':<5} Nome nel menu")
    for n in range(1, num + 1):
        it = items[n - 1]
        key = f"{(n - 1) // PER_PAGE + 1}.{(n - 1) % PER_PAGE + 1}"   # pagina.tasto nel menu
        run = it["run"] or a.run_all
        path, data, dump_load = find_program(a.dir, n)
        if path is None:
            if a.allow_missing:
                progs.append({"name": it["name"], "run": run, "load": DEFAULT_LOAD, "len": 1, "entry": DEFAULT_LOAD,
                              "data": b"\0", "path": "(manca)"})
                blocks.append(bytes(BLOCK))
                print(f"{key:<10}{'(manca)':<14}{'-':>6}  ${(n-1)*BLOCK:08X} -           -      {'RUN' if run else 'LOAD':<5} {it['name']}  [vuoto]")
                continue
            sys.exit(f"ERRORE: manca program{n}.bin (o .txt/.hex); usa --allow-missing per lasciare il blocco vuoto")
        if dump_load is not None:
            if it["load"] is not None and it["load"] != dump_load:
                sys.exit(f"ERRORE: {path}: il dump parte da ${dump_load:04X} ma il nome dice @{it['load']:04X}")
            load = dump_load
        else:
            load = it["load"] if it["load"] is not None else DEFAULT_LOAD
        size = len(data)
        if size == 0:
            sys.exit(f"ERRORE: {path} e' vuoto")
        if size > PAYLOAD:
            sys.exit(f"ERRORE: {path} e' {size} byte: massimo {PAYLOAD} ($7000) per programma")
        if load < min_load:
            sys.exit(f"ERRORE: {path}: indirizzo di caricamento ${load:04X} sotto il minimo consentito ${min_load:04X} "
                     f"(protegge zero page, stack e variabili BIOS; vedi --min-load e sd_min_load nel BIOS)")
        if load + size > RAM_END:
            sys.exit(f"ERRORE: {path}: ${load:04X} + {size} byte supera la RAM (fine ${RAM_END-1:04X})")
        if it["entry"] is not None:
            entry = it["entry"]
        else:
            entry = 0x1000 if load <= 0x1000 < load + size else load
        if not load <= entry < load + size:
            sys.exit(f"ERRORE: {path}: entry ${entry:04X} fuori dall'immagine ${load:04X}-${load+size-1:04X}")
        p = {"name": it["name"], "run": run, "load": load, "len": size, "entry": entry, "data": data, "path": path}
        progs.append(p)
        blocks.append(build_block(n, p))
        print(f"{key:<10}{os.path.basename(path):<14}{size:>6}  ${(n-1)*BLOCK:08X} ${load:04X}-${load+size-1:04X} ${entry:04X}  "
              f"{'RUN' if run else 'LOAD':<5} {it['name']}")

    # pagine di directory: la pagina P nel primo settore del blocco P (zona riservata: mai caricata in RAM)
    pages = (num + PER_PAGE - 1) // PER_PAGE
    for pg in range(pages):
        blocks[pg] = build_directory(progs, pg, num) + blocks[pg][SECTOR:]
    print(f"\nDirectory: {num} programmi in {pages} pagine da {PER_PAGE}")
    image = b"".join(blocks)
    assert len(image) % SECTOR == 0

    if is_device(a.output) and not a.yes:
        print(f"\nATTENZIONE: sto per scrivere {len(image)} byte all'INIZIO di {a.output}.")
        print("Il contenuto/filesystem della scheda verra' DISTRUTTO.")
        if input(f"Digita il nome del device ({a.output}) per confermare: ").strip() != a.output:
            sys.exit("Annullato.")

    mode = "r+b" if is_device(a.output) else "wb"
    with open(a.output, mode) as f:
        f.write(image)
        f.flush()
        try: os.fsync(f.fileno())
        except OSError: pass
    print(f"\nScritti {len(image)} byte ({len(image)//SECTOR} settori) su {a.output}")

    if not a.no_verify:
        with open(a.output, "rb") as f:
            back = f.read(len(image))
        if back != image:
            sys.exit("VERIFICA FALLITA: i dati riletti non coincidono")
        print("Verifica OK")

if __name__ == "__main__":
    main()
