#!/usr/bin/env python3
"""
update_sd.py - takes the games from "MiniVIC Games/bin", the applications from "MiniVIC Apps/bin" and the songs
from songs/, rebuilds programN.bin and programs.txt and regenerates the SD with make_sd.py.

Three modes:
  --mode games  (default) games and songs: program1..N.bin, programs.txt and sd.img in this folder; sd.img and
                the songs are also copied to ../bo6502-emulator/public/, the emulator's default SD. It runs with
                every BIOS.
  --mode full   games, applications and songs, plus the sample documents of documents.txt: full/program1..N.bin,
                full/programs.txt and sd_full.img (16 MB) in this folder; nothing is copied to the emulator.
                The applications need the BIOS KEYB/SD (sector read/write, "[TYPE] Name" serial line).
  --mode arcade the SD of the Arcade6502 cabinet, from arcade.json of the Arcade Games repository
                (../Arcade Games/arcade.json): its games in alphabetical order (loaded at $0FD0), the MiniVIC
                Jukebox (directory name "Jukebox - APP", loaded at $0FD0), the songs when "songs" is "all", the
                Z-machine stories its games read, and the arcade catalog of the Arcade BIOS from sector 24576
                (arcade.py): arcade/program1..N.bin, arcade/programs.txt and sd_arcade.img (16 MB) in this folder;
                a gzipped copy goes to ../bo6502-emulator/public/sd_arcade.img.gz (--emulator '' to skip it).
                arcade.json is checked first with tools/check_catalog.py of
                that repository; with errors nothing is written.

Menu order: first the games in alphabetical order (plain name, loaded at $0FD0), then (full mode) the applications
in alphabetical order (" - APP" or " - TOOL", names padded so the dashes line up, loaded at $0FD0), then the songs in the order of songs.txt
(plain name, loaded at $1000). Games and songs get their type from a [GAME] / [SOUND] prefix in programs.txt, the
applications from the " - APP" / " - TOOL" suffix that stays in the menu: make_sd.py writes the type in the directory,
the BIOS KEYB/SD sends "[GAME] Name", "[APP] Name", "[TOOL] Name" or "[SOUND] Name" on the serial line when the
program starts, and shows each type in its submenu (GAMES, APPS, SOUNDS).

  minivic.txt    file.bin = Name          known games; new .bin files are appended with a name derived from
                                          the file (e.g. lunar_lander.bin -> "Lunar Lander")
  apps.txt       file.bin = [TYPE] Name   known applications, same rules; [TYPE] is APP (default) or TOOL
  songs.txt      file.bin = Name          songs in songs/
  documents.txt  file = TYPE NAME         documents in documents/ (full mode); TYPE is TEXT, SHEET, CARDS or
                                          MEMORY, NAME at most 12 characters; slot 1, 2, ... in file order
  stories.txt    file = SLOT prog.bin ... Z-machine stories in stories/ (full mode) and the programs that read
                                          them: those programs are only in the full SD
  In minivic.txt and apps.txt the name can start with [GAME], [APP] or [TOOL] to change the type.

Document area (the format of the MiniVIC Apps, lib/docs.asm): sector 16384 ($00800000, after the 255 program
blocks) is the index: +0 "DOCS", +4 version 1, +5 slots (15); entry k (1-15) at k*32: +0 type (1 text, 2 sheet,
3 card file, 4 memory), +1/+2 length, +4..+15 name ($00 padded). Document k is 40 sectors (20 KB) from sector
16384 + k*40.

Story area (the miniVIC Z-Machine of the MiniVIC Games): sector 20480 ($00A00000) is the index: +0 "ZSTO",
+4 version 1, +5 slots (3); entry k (1-3) at k*16: +0/+1 sectors, +2/+3 release, +4..+9 serial (ASCII),
+10/+11 checksum, +12/+13 length / 2 (all little endian). Story k is at most 256 sectors (128 KB) from sector
20480 + 1 + (k-1)*256.

Arcade catalog (version 1, read by the Arcade BIOS front-end): sector 24576 ($00C00000) header "ARCD", version,
entries, title at +16; index from sector 24577, 32 bytes per entry; page of entry i (8 sectors: text, preview
patterns and colours) from sector 24576 + 64 + i*8. Details in arcade.py.

The save area (from sector 32768, $01000000) is never written: every image ends there.

Before overwriting, the old files of the mode (programN.bin, programs.txt and the image) are copied to
.backup/YYYYMMDD-HHMMSS/ (.backup/YYYYMMDD-HHMMSS-full/ or -arcade/ in the other modes).

Examples:
  python3 update_sd.py --dry-run     # only show what would change
  python3 update_sd.py               # update the files and regenerate sd.img (games only)
  python3 update_sd.py --mode full   # SD with games, applications and documents -> sd_full.img
  python3 update_sd.py --mode arcade # cabinet SD from arcade.json -> sd_arcade.img
  python3 update_sd.py -- -o '\\\\.\\PhysicalDrive2'   # arguments after -- go to make_sd.py
"""
import argparse, glob, gzip, hashlib, json, os, re, shutil, subprocess, sys, time
import arcade as arc

HERE       = os.path.dirname(os.path.abspath(__file__))
MINIVIC    = os.path.join(HERE, "..", "MiniVIC Games", "bin")
APPS       = os.path.join(HERE, "..", "MiniVIC Apps", "bin")
EMULATOR   = os.path.join(HERE, "..", "bo6502-emulator")
CATALOG    = os.path.join(HERE, "..", "Arcade Games", "arcade.json")
GAME_LOAD  = "0FD0"          # NMI trampoline of the MiniVIC games (and applications)
TYPES      = ("GAME", "APP", "TOOL")   # menu suffix = type in the SD directory
MAX_PROGS  = 255
FULL_SIZE  = 16 * 1024 * 1024          # sd_full.img: programs + document area
DOC_BASE   = 16384           # sector of the document index
DOC_SLOTS  = 15
DOC_SECTS  = 40              # sectors per document (20 KB)
DOC_NAMELEN = 12
DOC_TYPES  = {"TEXT": 1, "SHEET": 2, "CARDS": 3, "MEMORY": 4}
STORY_BASE = 20480           # sector of the story index
STORY_SLOTS = 3
STORY_SECTS = 256            # sectors per story (128 KB)

def read_map(path, default_type=None):
    """Lines 'file.bin = [TYPE] Name' -> list of (file, name, type) in file order."""
    items = []
    if not os.path.isfile(path):
        return items
    for n, line in enumerate(open(path, encoding="utf-8-sig"), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            sys.exit(f"ERROR: {os.path.basename(path)} line {n}: missing '=' in {line!r}")
        f, name = (s.strip() for s in line.split("=", 1))
        if not f or not name:
            sys.exit(f"ERROR: {os.path.basename(path)} line {n}: empty file or name")
        ptype = default_type
        m = re.match(r"\[\s*([A-Za-z]+)\s*\]\s*", name)
        if m:
            ptype = m.group(1).upper()
            if default_type is None or ptype not in TYPES:
                sys.exit(f"ERROR: {os.path.basename(path)} line {n}: unknown type [{m.group(1)}]")
            name = name[m.end():]
        if not name:
            sys.exit(f"ERROR: {os.path.basename(path)} line {n}: empty name")
        if re.search(r"[;!@\[\]]", name):
            sys.exit(f"ERROR: {os.path.basename(path)} line {n}: the name cannot contain ; ! @ [ ]")
        items.append((f, name, ptype))
    return items

def read_documents(path):
    """documents.txt -> list of (file, type number, name); checks files, types, names and sizes."""
    docs = []
    for f, rest, _ in read_map(path):
        t, _, name = rest.partition(" ")
        name = name.strip()
        if t.upper() not in DOC_TYPES:
            sys.exit(f"ERROR: documents.txt: {f}: unknown type {t!r} (use {', '.join(DOC_TYPES)})")
        if not name or len(name) > DOC_NAMELEN or not name.isascii():
            sys.exit(f"ERROR: documents.txt: {f}: the name must be 1-{DOC_NAMELEN} ASCII characters")
        p = os.path.join(HERE, "documents", f)
        if not os.path.isfile(p):
            sys.exit(f"ERROR: document not found: documents/{f}")
        if os.path.getsize(p) > min(DOC_SECTS * 512, 0xFFFF):
            sys.exit(f"ERROR: documents/{f}: larger than {DOC_SECTS * 512} bytes")
        docs.append((f, DOC_TYPES[t.upper()], name))
    if len(docs) > DOC_SLOTS:
        sys.exit(f"ERROR: {len(docs)} documents, at most {DOC_SLOTS}")
    return docs

def write_documents(img_path, docs):
    """Extends the image to FULL_SIZE and writes the document index and the documents."""
    img = bytearray(open(img_path, "rb").read())
    if len(img) > DOC_BASE * 512:
        sys.exit(f"ERROR: {img_path}: the programs reach the document area")
    img += bytes(FULL_SIZE - len(img))
    ix = DOC_BASE * 512
    img[ix:ix + 6] = b"DOCS" + bytes([1, DOC_SLOTS])
    for k, (f, t, name) in enumerate(docs, 1):
        data = open(os.path.join(HERE, "documents", f), "rb").read()
        e = ix + k * 32
        img[e] = t
        img[e + 1:e + 3] = len(data).to_bytes(2, "little")
        img[e + 4:e + 4 + len(name)] = name.encode("ascii")
        p = (DOC_BASE + k * DOC_SECTS) * 512
        img[p:p + len(data)] = data
    open(img_path, "wb").write(img)

def read_stories(path):
    """stories.txt -> list of (file, slot, [programs]); checks the files (Z-machine version 3, checksum)."""
    items = []
    if not os.path.isfile(path):
        return items
    for n, line in enumerate(open(path, encoding="utf-8-sig"), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        f, _, rest = (s.strip() for s in line.partition("="))
        words = rest.split()
        if not f or not words or not words[0].isdigit() or not 1 <= int(words[0]) <= STORY_SLOTS:
            sys.exit(f"ERROR: stories.txt line {n}: use 'file = slot (1-{STORY_SLOTS}) program.bin ...'")
        p = os.path.join(HERE, "stories", f)
        if not os.path.isfile(p):
            sys.exit(f"ERROR: story not found: stories/{f}")
        b = open(p, "rb").read()
        if b[0] != 3 or len(b) > STORY_SECTS * 512:
            sys.exit(f"ERROR: stories/{f}: not a version 3 story of at most {STORY_SECTS * 512} bytes")
        ln = ((b[0x1A] << 8) | b[0x1B]) * 2
        if sum(b[0x40:ln]) & 0xFFFF != (b[0x1C] << 8) | b[0x1D]:
            sys.exit(f"ERROR: stories/{f}: wrong checksum")
        items.append((f, int(words[0]), words[1:]))
    if len({s for _, s, _ in items}) != len(items):
        sys.exit("ERROR: stories.txt: two stories in the same slot")
    return items

def write_stories(img_path, stories):
    """Writes the story index and the stories into the (16 MB) image."""
    img = bytearray(open(img_path, "rb").read())
    ix = STORY_BASE * 512
    img[ix:ix + 512] = bytes(512)
    img[ix:ix + 6] = b"ZSTO" + bytes([1, STORY_SLOTS])
    for f, k, _ in stories:
        b = open(os.path.join(HERE, "stories", f), "rb").read()
        e = ix + 16 * k
        img[e:e + 2] = ((len(b) + 511) // 512).to_bytes(2, "little")
        img[e + 2:e + 4] = b[2:4][::-1]                          # release
        img[e + 4:e + 10] = b[0x12:0x18]                         # serial
        img[e + 10:e + 12] = b[0x1C:0x1E][::-1]                  # checksum
        img[e + 12:e + 14] = b[0x1A:0x1C][::-1]                  # length / 2
        p = (STORY_BASE + 1 + (k - 1) * STORY_SECTS) * 512
        img[p:p + STORY_SECTS * 512] = b + bytes(STORY_SECTS * 512 - len(b))
    open(img_path, "wb").write(img)

def extend_image(img_path):
    """Pads the image made by make_sd.py to FULL_SIZE (it must end before the document area)."""
    img = bytearray(open(img_path, "rb").read())
    if len(img) > DOC_BASE * 512:
        sys.exit(f"ERROR: {img_path}: the programs reach the document area")
    img += bytes(FULL_SIZE - len(img))
    open(img_path, "wb").write(img)

def read_arcade(path, dirs):
    """arcade.json, checked with tools/check_catalog.py of its repository -> (catalog, checker module)."""
    if not os.path.isfile(path):
        sys.exit(f"ERROR: arcade catalog not found: {path}")
    cat = json.load(open(path, encoding="utf-8"))
    checker = arc.load_checker(path)
    from pathlib import Path
    errors, warnings = checker.check(cat, {k: Path(v) for k, v in dirs.items()})
    for w in warnings:
        print("arcade.json warning:", w)
    for x in errors:
        print("arcade.json error:", x)
    if errors:
        sys.exit(f"ERROR: {len(errors)} errors in {path}: nothing written")
    for e in cat["entries"]:
        if re.search(r"[;!@\[\]]", e["name"]):
            sys.exit(f"ERROR: arcade.json: {e['id']}: the name cannot contain ; ! @ [ ]")
    return cat, checker

def arcade_pages(cat, checker, catalog_path, slots, songs):
    """Catalog entries in front-end order: slot, kind, name, page lines and preview."""
    out = []
    for e in arc.sort_entries(cat["entries"]):
        e = dict(e)
        if e["kind"] == "music" and songs:
            # the songs on the card, only when they fit in the description lines
            text = f"{e.get('description', '')} Songs on this card: {', '.join(nm for _, nm, _ in songs)}."
            if len(checker.wrap(text)) <= checker.DESC_LINES:
                e["description"] = text
        pv = None
        if e.get("preview"):
            png = os.path.join(os.path.dirname(os.path.abspath(catalog_path)), e["preview"])
            pv = arc.make_preview(arc.screen_from_png(png))
        out.append({"slot": slots[e["id"]], "kind": e["kind"], "name": e["name"],
                    "lines": checker.page_lines(e), "preview": pv, "zone": e.get("zone"),
                    "credits": e.get("credits"), "controls": e.get("controls")})
    return out

def name_from_file(f):
    return " ".join(w.capitalize() for w in os.path.splitext(f)[0].replace("-", "_").split("_") if w)

def digest(data):
    return hashlib.sha1(data).hexdigest()

def current_sd(folder):
    """Menu name -> hash of the current programN.bin, read from programs.txt."""
    path = os.path.join(folder, "programs.txt")
    cur = {}
    if not os.path.isfile(path):
        return cur
    raw = open(path, encoding="utf-8-sig").read().replace("\r", "\n").replace("\n", ";")
    names = [p.strip() for p in raw.split(";") if p.strip()]
    for n, p in enumerate(names, 1):
        p = re.sub(r"^\[[A-Za-z]+\]", "", re.sub(r"@.*$", "", p.lstrip("!")).strip()).strip()   # no [TYPE] prefix
        b = os.path.join(folder, f"program{n}.bin")
        if os.path.isfile(b):
            cur[p.upper()] = digest(open(b, "rb").read())
    return cur

def collect(folder, map_path, default_type):
    """Programs of one folder: (sorted list of (file, name, type), files added to the map, files missing)."""
    known = read_map(map_path, default_type)
    known_files = {f for f, _, _ in known}
    found = sorted(os.path.basename(p) for p in glob.glob(os.path.join(folder, "*.bin")))
    added = [(f, name_from_file(f), default_type) for f in found if f not in known_files]
    missing = [f for f, _, _ in known if f not in found]
    progs = [(f, nm, t) for f, nm, t in known + added if f in found]
    progs.sort(key=lambda g: g[1].upper())
    return progs, added, missing

def main():
    ap = argparse.ArgumentParser(description="Update the BO6502 SD with the MiniVIC games (and applications)",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--mode", choices=("games", "full", "arcade"), default="games",
                    help="games: games and songs -> sd.img, copied to the emulator (default); "
                    "full: games, applications, songs and documents -> sd_full.img; "
                    "arcade: the cabinet SD of arcade.json, with the arcade catalog -> sd_arcade.img")
    ap.add_argument("--catalog", default=CATALOG, help="arcade.json, arcade mode (default ../Arcade Games/arcade.json)")
    ap.add_argument("--arcade", default=None, help="folder with the arcade .bin files, arcade mode "
                    "(default bin/ next to arcade.json)")
    ap.add_argument("--minivic", default=MINIVIC, help="folder with the game .bin files (default ../MiniVIC Games/bin)")
    ap.add_argument("--apps", default=APPS, help="folder with the application .bin files, full mode "
                    "(default ../MiniVIC Apps/bin)")
    ap.add_argument("--emulator", default=EMULATOR, help="emulator project to copy sd.img (games mode) or "
                    "sd_arcade.img.gz (arcade mode) into "
                    "(default ../bo6502-emulator; '' to skip the copy)")
    ap.add_argument("--dry-run", action="store_true", help="show the differences without writing anything")
    ap.add_argument("make_sd_args", nargs=argparse.REMAINDER, help="arguments passed to make_sd.py (after --)")
    a = ap.parse_args()
    full = a.mode == "full"
    arcade = a.mode == "arcade"
    if not os.path.isdir(a.minivic):
        sys.exit(f"ERROR: games folder not found: {a.minivic}")
    if full and not os.path.isdir(a.apps):
        sys.exit(f"ERROR: applications folder not found: {a.apps}")
    out = os.path.join(HERE, a.mode) if full or arcade else HERE           # programN.bin and programs.txt
    img = os.path.join(HERE, {"games": "sd.img", "full": "sd_full.img", "arcade": "sd_arcade.img"}[a.mode])

    map_path = os.path.join(HERE, "minivic.txt")
    apps_map = os.path.join(HERE, "apps.txt")
    stories = read_stories(os.path.join(HERE, "stories.txt"))
    songs = read_map(os.path.join(HERE, "songs.txt"))
    games, added, missing, full_only = [], [], [], []
    apps, apps_added, apps_missing = [], [], []
    if arcade:
        # the programs of arcade.json: games in alphabetical order, then the Jukebox (an application,
        # its directory name starts with JUKEBOX: the Arcade BIOS finds it so when there is no catalog)
        a.arcade = a.arcade or os.path.join(os.path.dirname(os.path.abspath(a.catalog)), "bin")
        dirs = {"minivic": a.minivic, "apps": a.apps, "arcade": a.arcade}
        cat, checker = read_arcade(a.catalog, dirs)
        for e in arc.sort_entries(cat["entries"]):
            path = os.path.join(dirs[e["bin"]["source"]], e["bin"]["file"])
            if e["kind"] == "game":
                games.append((path, e["name"], "GAME", e["id"]))
            else:
                apps.append((path, "Jukebox", "APP", e["id"]))
        if cat.get("songs") != "all":
            songs = []
        files = {os.path.basename(p) for p, _, _, _ in games + apps}
        stories = [s for s in stories if files & set(s[2])]
    else:
        games, added, missing = collect(a.minivic, map_path, "GAME")
        full_only = [g for g in games if not full and any(g[0] in progs for _, _, progs in stories)]
        games = [g for g in games if g not in full_only]
        if full:
            apps, apps_added, apps_missing = collect(a.apps, apps_map, "APP")
        games = [(os.path.join(a.minivic, f), nm, t, None) for f, nm, t in games]
        apps = [(os.path.join(a.apps, f), nm, t, None) for f, nm, t in apps]
    for f, _, _ in songs:
        if not os.path.isfile(os.path.join(HERE, "songs", f)):
            sys.exit(f"ERROR: song not found: songs/{f}")
    docs = read_documents(os.path.join(HERE, "documents.txt")) if full else []
    total = len(games) + len(apps) + len(songs)
    if total > MAX_PROGS:
        sys.exit(f"ERROR: {total} programs, at most {MAX_PROGS}")

    # new SD: (menu name, programs.txt entry, data)
    # the menu shows " - APP" / " - TOOL" only: games and songs take their type from a [TYPE] prefix
    # the application names are padded with spaces, so that the dash starts in the same column for all of them
    width = max((len(nm) for _, nm, _, _ in apps), default=0)
    def entry(nm, t, load):
        if t in ("APP", "TOOL"):
            name = f"{nm:<{width}} - {t}"
            spec = "!" + name
        else:
            name, spec = nm, f"![{t}]{nm}"
        return name, spec + (f"@{load}" if load else "")
    sd = [(*entry(nm, t, GAME_LOAD), open(p, "rb").read()) for p, nm, t, _ in games]
    sd += [(*entry(nm, t, GAME_LOAD), open(p, "rb").read()) for p, nm, t, _ in apps]
    sd += [(*entry(nm, "SOUND", None), open(os.path.join(HERE, "songs", f), "rb").read()) for f, nm, _ in songs]

    cur = current_sd(out)
    if arcade:
        print(f"Mode arcade -> sd_arcade.img   catalog {os.path.normpath(a.catalog)}: {len(games)} games, "
              f"{len(apps)} music   songs: {len(songs)}   stories: {len(stories)}\n")
    else:
        print(f"Mode {a.mode} -> {os.path.basename(img)}   games from {os.path.normpath(a.minivic)}: {len(games)}   "
              + (f"applications from {os.path.normpath(a.apps)}: {len(apps)}   " if full else "")
              + f"songs: {len(songs)}" + (f"   documents: {len(docs)}   stories: {len(stories)}" if full else "") + "\n")
    changes = 0
    for n, (label, _, data) in enumerate(sd, 1):
        old = cur.pop(label.upper(), None)
        state = "NEW" if old is None else ("UPDATED" if old != digest(data) else "")
        changes += bool(state)
        print(f"{n:>3}  {label:<34}{len(data):>6} bytes  {state}")
    for label in cur:
        changes += 1
        print(f"  -  {label:<34}          REMOVED")
    for k, (f, t, name) in enumerate(docs, 1):
        print(f"doc {k:>2}  {name:<12} {next(x for x, v in DOC_TYPES.items() if v == t):<7}"
              f"{os.path.getsize(os.path.join(HERE, 'documents', f)):>6} bytes  documents/{f}")
    for f, k, _ in stories if full or arcade else []:
        print(f"story {k}  {os.path.getsize(os.path.join(HERE, 'stories', f)):>6} bytes  stories/{f}")
    for f, nm, _ in full_only:
        print(f"{nm} ({f}) reads a story: only in the full SD")
    for f in missing:
        print(f"WARNING: {f} is in minivic.txt but not in {a.minivic}: left out")
    for f in apps_missing:
        print(f"WARNING: {f} is in apps.txt but not in {a.apps}: left out")
    for f, nm, _ in added:
        print(f"NEW GAME: {f} -> \"{nm}\" ({'will be' if a.dry_run else 'was'} added to minivic.txt, "
              f"fix the name there if needed)")
    for f, nm, _ in apps_added:
        print(f"NEW APPLICATION: {f} -> \"{nm}\" ({'will be' if a.dry_run else 'was'} added to apps.txt, "
              f"fix the name or the type there if needed)")
    print(f"\n{changes} differences from the current SD")
    if a.dry_run:
        return

    extra = [x for x in a.make_sd_args if x != "--"]
    to_img = "-o" not in extra and "--output" not in extra       # (otherwise make_sd.py writes elsewhere)
    if arcade:
        if not to_img:
            sys.exit("ERROR: output given with -o: the arcade catalog is written only into sd_arcade.img")
        print("Building the arcade catalog (previews from the PNG files)...", flush=True)
        slots = {i: n for n, (_, _, _, i) in enumerate(games + apps)}
        pages = arcade_pages(cat, checker, a.catalog, slots, songs)

    if added:
        with open(map_path, "a", encoding="utf-8") as fp:
            for f, nm, _ in added:
                fp.write(f"{f} = {nm}\n")
    if apps_added:
        new_map = not os.path.isfile(apps_map)
        with open(apps_map, "a", encoding="utf-8") as fp:
            if new_map:
                fp.write('# Applications taken from "MiniVIC Apps/bin": file = [TYPE] menu name (without " - APP",\n'
                         '# added by update_sd.py). TYPE is APP (default, can be left out) or TOOL.\n')
            for f, nm, _ in apps_added:
                fp.write(f"{f} = {nm}\n")

    os.makedirs(out, exist_ok=True)
    old_bins = glob.glob(os.path.join(out, "program*.bin"))
    old_bins = [p for p in old_bins if re.fullmatch(r"program\d+\.bin", os.path.basename(p))]
    bak = os.path.join(HERE, ".backup", time.strftime("%Y%m%d-%H%M%S") + ("" if a.mode == "games" else "-" + a.mode))
    os.makedirs(bak)
    for p in old_bins + [os.path.join(out, "programs.txt"), img]:
        if os.path.isfile(p):
            shutil.copy2(p, bak)
    for p in old_bins:
        os.remove(p)
    for n, (_, _, data) in enumerate(sd, 1):
        open(os.path.join(out, f"program{n}.bin"), "wb").write(data)
    open(os.path.join(out, "programs.txt"), "w", encoding="utf-8").write("".join(e + ";\n" for _, e, _ in sd))
    print(f"Backup in {bak}\n", flush=True)

    rc = subprocess.call([sys.executable, os.path.join(HERE, "make_sd.py"), "-d", out,
                          "-l", os.path.join(out, "programs.txt"), "-o", img] + extra, cwd=HERE)
    if rc:
        sys.exit(rc)

    if arcade:
        extend_image(img)
        write_stories(img, stories)
        data = bytearray(open(img, "rb").read())
        end = arc.write_catalog(data, cat["title"], pages)
        if len(data) != FULL_SIZE:
            sys.exit("ERROR: the image grew past the save area")
        open(img, "wb").write(data)
        print(f"{len(stories)} stories written from sector {STORY_BASE}")
        print(f"Arcade catalog \"{cat['title']}\": {len(pages)} entries, sectors {arc.CAT_LBA}-{end - 1}; "
              f"{os.path.basename(img)} is {FULL_SIZE // 1024 // 1024} MB (use it with the Arcade BIOS)")
        # gzipped copy in the emulator (public/sd_arcade.img.gz, like sd_full.img.gz); mtime 0: same image, same file
        pub = os.path.join(a.emulator, "public")
        if a.emulator and os.path.isdir(pub):
            open(os.path.join(pub, "sd_arcade.img.gz"), "wb").write(gzip.compress(bytes(data), 9, mtime=0))
            print(f"Also copied to {os.path.normpath(os.path.join(pub, 'sd_arcade.img.gz'))}")
        elif a.emulator:
            print(f"WARNING: emulator not found ({os.path.normpath(pub)}): sd_arcade.img not copied")
        return

    if full:
        if to_img:
            write_documents(img, docs)
            write_stories(img, stories)
            print(f"{len(stories)} stories written from sector {STORY_BASE}")
            print(f"{len(docs)} documents written, {os.path.basename(img)} extended to {FULL_SIZE // 1024 // 1024} MB "
                  f"(use it with the BIOS KEYB/SD)")
        else:
            print("WARNING: output given with -o: the documents were not written")
        return

    # same SD in the emulator (public/sd.img, loaded at startup) plus the songs it contains (public/songs),
    # only when make_sd.py wrote sd.img
    pub = os.path.join(a.emulator, "public")
    if a.emulator and to_img:
        if os.path.isdir(pub):
            shutil.copyfile(img, os.path.join(pub, "sd.img"))
            print(f"Also copied to {os.path.normpath(os.path.join(pub, 'sd.img'))}")
            os.makedirs(os.path.join(pub, "songs"), exist_ok=True)
            for f, _, _ in songs:
                shutil.copyfile(os.path.join(HERE, "songs", f), os.path.join(pub, "songs", f))
            print(f"Songs copied to {os.path.normpath(os.path.join(pub, 'songs'))}: {', '.join(f for f, _, _ in songs)}")
        else:
            print(f"WARNING: emulator not found ({os.path.normpath(pub)}): sd.img not copied")

if __name__ == "__main__":
    main()
