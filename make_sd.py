#!/usr/bin/env python3
"""
make_sd.py - builds the SD card (or the image) with the programs for the BO6502 "SD PROGRAMS" menu.

Layout (RAW, no filesystem; standard capacity SD <= 2GB, byte addressing):
  PAGED DIRECTORY (version 3): 9 programs per page, up to 255 programs (29 pages).
  Page P (P = 0, 1, ...) is in the FIRST SECTOR of 32KB block number P, i.e. at offset P * $8000:
      +0..3   "BOGS"   +4 version (3)   +5 number of programs ON THIS PAGE (1..9)
      +6..14  flags of entries 0..8 (bit0 = RUN)   +15 TOTAL number of programs
      +16+i*8 parameters of entry i: load address (lo,hi), length (lo,hi), entry (lo,hi), type, serial name length
              type: 0 unknown, 1 GAME, 2 APP, 3 TOOL, 4 SOUND. The BIOS KEYB/SD uses it for the GAMES, APPS
              (APP and TOOL) and SOUNDS submenus, and when a program is run it sends
              "[TYPE] Name" on the serial line, using only the first <serial name length> characters of the
              name (0 = whole name): the " - GAME" suffix shown in the menu is left out. The standard BIOS
              ignores both bytes (they used to be 0).
      +96+i*32 name of entry i (ASCII, max 31 chars + $00)
  The BIOS menu shows one page at a time (keys A/D to change page, 1..9 to choose).
  program N (N = 1..255) -> 32KB block at offset (N-1) * $8000
      +$0000..+$0FFF  reserved (the first sector holds the directory page, if any; the second sector
                      holds an ASCII info line). Never read into RAM.
      +$1000..        the program bytes (max $7000), copied to RAM starting at the load address.
  The BIOS writes EXACTLY [load, load+length) to RAM: the rest of the RAM is left untouched.

Programs: programN.bin = raw binary. Alternatively programN.txt / programN.hex = WozMon-style hex dump
("0FD0: 4C 27 11 ..."), from which the script also takes the load address.

Names: text file (default programs.txt in the programs folder, or -l FILE), names separated by ';'
(also over several lines). The first name is program 1, the second program 2, ...
    [!][[TYPE]]Name[@LOAD[:ENTRY]]
  !      program RUN right after loading ("N>" in the menu); without '!' it is only loaded ("N.")
  [TYPE] GAME, APP, TOOL or SOUND (see the directory above). Without it, the type comes from a " - GAME",
         " - APP", " - TOOL", " - SOUND" or " - SONG" suffix of the name; otherwise it is 0 (no serial
         line, shown only in the ALL list of the BIOS KEYB/SD)
  @LOAD  RAM load address in hex (default 1000; not needed for .txt/.hex dumps)
  :ENTRY start address (default: 1000 if it falls inside the loaded image, otherwise LOAD)
Example programs.txt:   Banner; !Arcade Tank - GAME@0FD0; ![TOOL]Test RAM@1000
With --run-all every program is run after loading.

Examples:
  python3 make_sd.py                               # reads programs.txt and program1..N from the current folder
  python3 make_sd.py -n 4 -l names.txt             # only the first 4 programs
  python3 make_sd.py -o /dev/sdX --yes             # writes DIRECTLY to the card (destroys its data!)
  python3 make_sd.py -o '\\\\.\\PhysicalDrive2'      # Windows, from an Administrator prompt
"""
import argparse, os, re, sys, zlib

BLOCK      = 0x8000          # 32KB per program
RESERVED   = 0x1000          # program data at block + $1000
PAYLOAD    = BLOCK - RESERVED  # 0x7000 = 28KB max per program
SECTOR     = 512
RAM_END    = 0x8000          # first non-writable address
MAX_PROGS  = 255             # the driver addresses slots with 1 byte (0..254)
PER_PAGE   = 9               # programs per menu page (keys '1'..'9')

DIR_MAGIC  = b"BOGS"
DIR_VER    = 3
DIR_TOTAL  = 15              # byte with the total number of programs
DIR_PARAMS = 16              # parameter table: 8 bytes per program
DIR_PSIZE  = 8
DIR_NAMES  = 96              # names: 32 bytes per program
DIR_ESIZE  = 32              # 31 characters + $00
NAME_MAX   = DIR_ESIZE - 1
DEFAULT_LOAD = 0x1000
TYPES      = {"GAME": 1, "APP": 2, "TOOL": 3, "SOUND": 4}   # directory byte +6 of the entry parameters
TYPE_NAMES = {v: k for k, v in TYPES.items()}
SUFFIXES   = dict(TYPES, SONG=4)   # name suffixes that give the type (" - SONG" is a SOUND)

def parse_hex(s, what):
    try:
        v = int(s, 16)
    except ValueError:
        sys.exit(f"ERROR: invalid hex address in {what}: {s!r}")
    if not 0 <= v <= 0xFFFF:
        sys.exit(f"ERROR: address outside $0000-$FFFF in {what}: {s!r}")
    return v

def read_names(path, keep_case):
    """Reads [!][[TYPE]]Name[@LOAD[:ENTRY]] separated by ';' (and/or newlines)."""
    raw = open(path, "r", encoding="utf-8-sig", errors="replace").read()
    items = []
    for part in raw.replace("\r", "\n").replace("\n", ";").split(";"):
        p = part.strip()
        if not p:
            continue
        run = p.startswith("!")
        if run:
            p = p[1:].strip()
        ptype = None
        m = re.match(r"\[\s*([A-Za-z]+)\s*\]", p)
        if m:
            ptype = TYPES.get(m.group(1).upper())
            if ptype is None:
                sys.exit(f"ERROR: unknown type [{m.group(1)}] in '{p}' (use {', '.join(TYPES)})")
            p = p[m.end():].strip()
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
            print(f"WARNING: name too long, truncated to {NAME_MAX} characters: {p!r}")
            p = p[:NAME_MAX]
        ptype, serlen = serial_name(p, ptype)
        items.append({"name": p, "run": run, "load": load, "entry": entry, "type": ptype, "serlen": serlen})
    return items

def serial_name(name, ptype):
    """(type, serial name length): a " - GAME"/" - APP"/" - TOOL"/" - SOUND"/" - SONG" suffix gives the type when it is not
    given, and is left out of the serial line when it matches the type."""
    m = re.search(r"\s+-\s+([A-Za-z]+)$", name)
    if m and m.group(1).upper() in SUFFIXES:
        t = SUFFIXES[m.group(1).upper()]
        if ptype is None:
            ptype = t
        if ptype == t:
            return ptype, m.start()
    return ptype or 0, 0

def read_hexdump(path):
    """WozMon-style dump 'ADDR: HH HH ...' -> (start_address, bytes). Error if not contiguous."""
    mem = {}
    for line in open(path, "r", errors="replace"):
        m = re.match(r"\s*([0-9A-Fa-f]{4}):\s*((?:[0-9A-Fa-f]{2}\s*)+)$", line)
        if not m:
            continue
        a = int(m.group(1), 16)
        for i, b in enumerate(m.group(2).split()):
            mem[a + i] = int(b, 16)
    if not mem:
        sys.exit(f"ERROR: no 'ADDR: bytes...' line found in {path}")
    lo, hi = min(mem), max(mem)
    if len(mem) != hi - lo + 1:
        sys.exit(f"ERROR: {path}: the dump is not contiguous (gaps between ${lo:04X} and ${hi:04X})")
    return lo, bytes(mem[a] for a in range(lo, hi + 1))

def find_program(dirpath, n):
    """Returns (path, data, load_from_dump_or_None)."""
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
    """Directory sector of page `page`: holds the programs progs[page*9 : page*9+9]."""
    d = bytearray(SECTOR)
    d[0:4] = DIR_MAGIC
    d[4] = DIR_VER
    chunk = progs[page * PER_PAGE:(page + 1) * PER_PAGE]
    d[5] = len(chunk)
    d[DIR_TOTAL] = total
    for i, p in enumerate(chunk):
        d[6 + i] = 1 if p["run"] else 0               # flag: bit0 = run after loading
        o = DIR_PARAMS + i * DIR_PSIZE
        d[o:o + 2] = p["load"].to_bytes(2, "little")
        d[o + 2:o + 4] = p["len"].to_bytes(2, "little")
        d[o + 4:o + 6] = p["entry"].to_bytes(2, "little")
        d[o + 6] = p["type"]
        d[o + 7] = p["serlen"]
        o = DIR_NAMES + i * DIR_ESIZE
        d[o:o + len(p["name"])] = p["name"].encode("ascii")    # the rest stays $00
    return bytes(d)

def build_block(n, p):
    info = (f"BO6502 SD PROGRAM {n} slot={n-1} file={os.path.basename(p['path'])} load={p['load']:04X} "
            f"len={p['len']} entry={p['entry']:04X} crc32={zlib.crc32(p['data']):08X}\n").encode("ascii")
    block = bytearray(BLOCK)
    block[SECTOR:SECTOR + len(info)] = info               # 2nd sector of the reserved area
    block[RESERVED:RESERVED + p["len"]] = p["data"]
    return bytes(block)

def is_device(path):
    return path.startswith("/dev/") or path.startswith("\\\\.\\")

def main():
    ap = argparse.ArgumentParser(description="Build a multi-program SD/image for the BO6502",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("-n", "--num", type=int, help=f"number of programs (1..{MAX_PROGS}, 9 per menu page); default = number of names")
    ap.add_argument("-l", "--list", help="file with names separated by ';' (default: programs.txt in the -d folder)")
    ap.add_argument("--run-all", action="store_true", help="every program is run after loading")
    ap.add_argument("--keep-case", action="store_true", help="do not convert names to upper case")
    ap.add_argument("-d", "--dir", default=".", help="folder with the programs (default .)")
    ap.add_argument("-o", "--output", default="sd.img", help="image file or device (default sd.img)")
    ap.add_argument("--min-load", default="0F00", help="lowest allowed load address, hex (default 0F00, "
                    "the same as sd_min_load in the BIOS)")
    ap.add_argument("--allow-missing", action="store_true", help="if programN is missing, leave its block empty")
    ap.add_argument("--no-verify", action="store_true", help="do not read back and compare after writing")
    ap.add_argument("--yes", action="store_true", help="do not ask for confirmation before writing to a device")
    a = ap.parse_args()
    min_load = parse_hex(a.min_load, "--min-load")

    listfile = a.list or os.path.join(a.dir, "programs.txt")
    items = []
    if os.path.isfile(listfile):
        items = read_names(listfile, a.keep_case)
        print(f"Names read from {listfile}: {len(items)}")
    elif a.list:
        sys.exit(f"ERROR: names file not found: {listfile}")
    else:
        print(f"WARNING: {listfile} not found: the programs will be called PROGRAM 1, PROGRAM 2, ...")
    num = a.num if a.num is not None else len(items)
    if a.num is None and not items:
        sys.exit("ERROR: give -n or provide a names file")
    if not 1 <= num <= MAX_PROGS:
        sys.exit(f"ERROR: programs must be between 1 and {MAX_PROGS}, found {num}")
    if len(items) > num:
        print(f"WARNING: {len(items)} names but only {num} programs: ignoring the extra names")
        items = items[:num]
    while len(items) < num:
        items.append({"name": f"PROGRAM {len(items)+1}", "run": False, "load": None, "entry": None,
                      "type": 0, "serlen": 0})

    progs, blocks = [], []
    print(f"{'Page.Key':<10}{'File':<14}{'Bytes':>6}  {'SD offset':<10}{'RAM':<12}{'Entry':<7}{'Mode':<5}{'Type':<5} Menu name")
    for n in range(1, num + 1):
        it = items[n - 1]
        key = f"{(n - 1) // PER_PAGE + 1}.{(n - 1) % PER_PAGE + 1}"   # page.key in the menu
        run = it["run"] or a.run_all
        path, data, dump_load = find_program(a.dir, n)
        if path is None:
            if a.allow_missing:
                progs.append({"name": it["name"], "run": run, "load": DEFAULT_LOAD, "len": 1, "entry": DEFAULT_LOAD,
                              "type": 0, "serlen": 0, "data": b"\0", "path": "(missing)"})
                blocks.append(bytes(BLOCK))
                print(f"{key:<10}{'(missing)':<14}{'-':>6}  ${(n-1)*BLOCK:08X} -           -      {'RUN' if run else 'LOAD':<5} {it['name']}  [empty]")
                continue
            sys.exit(f"ERROR: program{n}.bin (or .txt/.hex) is missing; use --allow-missing to leave the block empty")
        if dump_load is not None:
            if it["load"] is not None and it["load"] != dump_load:
                sys.exit(f"ERROR: {path}: the dump starts at ${dump_load:04X} but the name says @{it['load']:04X}")
            load = dump_load
        else:
            load = it["load"] if it["load"] is not None else DEFAULT_LOAD
        size = len(data)
        if size == 0:
            sys.exit(f"ERROR: {path} is empty")
        if size > PAYLOAD:
            sys.exit(f"ERROR: {path} is {size} bytes: at most {PAYLOAD} ($7000) per program")
        if load < min_load:
            sys.exit(f"ERROR: {path}: load address ${load:04X} below the allowed minimum ${min_load:04X} "
                     f"(protects zero page, stack and BIOS variables; see --min-load and sd_min_load in the BIOS)")
        if load + size > RAM_END:
            sys.exit(f"ERROR: {path}: ${load:04X} + {size} bytes goes past the RAM (end ${RAM_END-1:04X})")
        if it["entry"] is not None:
            entry = it["entry"]
        else:
            entry = 0x1000 if load <= 0x1000 < load + size else load
        if not load <= entry < load + size:
            sys.exit(f"ERROR: {path}: entry ${entry:04X} outside the image ${load:04X}-${load+size-1:04X}")
        p = {"name": it["name"], "run": run, "load": load, "len": size, "entry": entry, "type": it["type"],
             "serlen": it["serlen"], "data": data, "path": path}
        progs.append(p)
        blocks.append(build_block(n, p))
        print(f"{key:<10}{os.path.basename(path):<14}{size:>6}  ${(n-1)*BLOCK:08X} ${load:04X}-${load+size-1:04X} ${entry:04X}  "
              f"{'RUN' if run else 'LOAD':<5}{TYPE_NAMES.get(it['type'], '-'):<5} {it['name']}")

    # directory pages: page P in the first sector of block P (reserved area: never loaded into RAM)
    pages = (num + PER_PAGE - 1) // PER_PAGE
    for pg in range(pages):
        blocks[pg] = build_directory(progs, pg, num) + blocks[pg][SECTOR:]
    print(f"\nDirectory: {num} programs in {pages} pages of {PER_PAGE}")
    image = b"".join(blocks)
    assert len(image) % SECTOR == 0

    if is_device(a.output) and not a.yes:
        print(f"\nWARNING: about to write {len(image)} bytes at the START of {a.output}.")
        print("The contents/filesystem of the card will be DESTROYED.")
        if input(f"Type the device name ({a.output}) to confirm: ").strip() != a.output:
            sys.exit("Cancelled.")

    mode = "r+b" if is_device(a.output) else "wb"
    with open(a.output, mode) as f:
        f.write(image)
        f.flush()
        try: os.fsync(f.fileno())
        except OSError: pass
    print(f"\nWrote {len(image)} bytes ({len(image)//SECTOR} sectors) to {a.output}")

    if not a.no_verify:
        with open(a.output, "rb") as f:
            back = f.read(len(image))
        if back != image:
            sys.exit("VERIFY FAILED: the data read back does not match")
        print("Verify OK")

if __name__ == "__main__":
    main()
