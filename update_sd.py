#!/usr/bin/env python3
"""
update_sd.py - takes the games from "MiniVIC Games/bin" and the songs from songs/, rebuilds program1..N.bin and
programs.txt and regenerates the SD with make_sd.py.

Menu order: first the pinned games in the order of minivic.txt, then the other games in alphabetical order
(" - GAME", loaded at $0FD0), then the songs in the order of songs.txt (" - SONG", loaded at $1000).

  minivic.txt  file.bin = Name   known games; new .bin files are appended with a name derived from the file
                                 (e.g. lunar_lander.bin -> "Lunar Lander"); '+file.bin = Name' pins the game
                                 at the top of the menu
  songs.txt    file.bin = Name   songs in songs/

Before overwriting, the old programN.bin, programs.txt and sd.img are copied to .backup/YYYYMMDD-HHMMSS/.
Afterwards sd.img is also copied to ../bo6502-emulator/public/sd.img, which the emulator loads at startup, and
the songs to ../bo6502-emulator/public/songs/.

Examples:
  python3 update_sd.py --dry-run     # only show what would change
  python3 update_sd.py               # update the files and regenerate sd.img
  python3 update_sd.py -- -o '\\\\.\\PhysicalDrive2'   # arguments after -- go to make_sd.py
"""
import argparse, glob, hashlib, os, re, shutil, subprocess, sys, time

HERE       = os.path.dirname(os.path.abspath(__file__))
MINIVIC    = os.path.join(HERE, "..", "MiniVIC Games", "bin")
EMULATOR   = os.path.join(HERE, "..", "bo6502-emulator")
GAME_LOAD  = "0FD0"          # NMI trampoline of the MiniVIC games
MAX_PROGS  = 255

def read_map(path):
    """Lines 'file.bin = Name' -> list of (file, name) in file order."""
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
        if re.search(r"[;!@]", name):
            sys.exit(f"ERROR: {os.path.basename(path)} line {n}: the name cannot contain ; ! @")
        items.append((f, name))
    return items

def name_from_file(f):
    return " ".join(w.capitalize() for w in os.path.splitext(f)[0].replace("-", "_").split("_") if w)

def digest(data):
    return hashlib.sha1(data).hexdigest()

def current_sd():
    """Menu name -> hash of the current programN.bin, read from programs.txt."""
    path = os.path.join(HERE, "programs.txt")
    cur = {}
    if not os.path.isfile(path):
        return cur
    raw = open(path, encoding="utf-8-sig").read().replace("\r", "\n").replace("\n", ";")
    names = [p.strip() for p in raw.split(";") if p.strip()]
    for n, p in enumerate(names, 1):
        p = re.sub(r"@.*$", "", p.lstrip("!")).strip()
        b = os.path.join(HERE, f"program{n}.bin")
        if os.path.isfile(b):
            cur[p.upper()] = digest(open(b, "rb").read())
    return cur

def main():
    ap = argparse.ArgumentParser(description="Update the BO6502 SD with the MiniVIC games",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--minivic", default=MINIVIC, help="folder with the game .bin files (default ../MiniVIC Games/bin)")
    ap.add_argument("--emulator", default=EMULATOR, help="emulator project to copy sd.img into "
                    "(default ../bo6502-emulator; '' to skip the copy)")
    ap.add_argument("--dry-run", action="store_true", help="show the differences without writing anything")
    ap.add_argument("make_sd_args", nargs=argparse.REMAINDER, help="arguments passed to make_sd.py (after --)")
    a = ap.parse_args()
    if not os.path.isdir(a.minivic):
        sys.exit(f"ERROR: games folder not found: {a.minivic}")

    map_path = os.path.join(HERE, "minivic.txt")
    known = read_map(map_path)
    pinned = [f[1:].strip() for f, _ in known if f.startswith("+")]
    known = [(f.lstrip("+").strip(), nm) for f, nm in known]
    known_files = {f for f, _ in known}
    found = sorted(os.path.basename(p) for p in glob.glob(os.path.join(a.minivic, "*.bin")))
    added = [(f, name_from_file(f)) for f in found if f not in known_files]
    missing = [f for f, _ in known if f not in found]

    games = [(f, nm) for f, nm in known + added if f in found]
    games.sort(key=lambda g: (pinned.index(g[0]) if g[0] in pinned else len(pinned), g[1].upper()))
    songs = read_map(os.path.join(HERE, "songs.txt"))
    for f, _ in songs:
        if not os.path.isfile(os.path.join(HERE, "songs", f)):
            sys.exit(f"ERROR: song not found: songs/{f}")
    if len(games) + len(songs) > MAX_PROGS:
        sys.exit(f"ERROR: {len(games) + len(songs)} programs, at most {MAX_PROGS}")

    # new SD: (menu name, programs.txt entry, data)
    sd = [(f"{nm} - GAME", f"!{nm} - GAME@{GAME_LOAD}", open(os.path.join(a.minivic, f), "rb").read())
          for f, nm in games]
    sd += [(f"{nm} - SONG", f"!{nm} - SONG", open(os.path.join(HERE, "songs", f), "rb").read())
           for f, nm in songs]

    cur = current_sd()
    print(f"Games from {os.path.normpath(a.minivic)}: {len(games)}   songs: {len(songs)}\n")
    changes = 0
    for n, (label, _, data) in enumerate(sd, 1):
        old = cur.pop(label.upper(), None)
        state = "NEW" if old is None else ("UPDATED" if old != digest(data) else "")
        changes += bool(state)
        print(f"{n:>3}  {label:<34}{len(data):>6} bytes  {state}")
    for label in cur:
        changes += 1
        print(f"  -  {label:<34}          REMOVED")
    for f in missing:
        print(f"WARNING: {f} is in minivic.txt but not in {a.minivic}: left out")
    for f, nm in added:
        print(f"NEW GAME: {f} -> \"{nm}\" ({'will be' if a.dry_run else 'was'} added to minivic.txt, "
              f"fix the name there if needed)")
    print(f"\n{changes} differences from the current SD")
    if a.dry_run:
        return

    if added:
        with open(map_path, "a", encoding="utf-8") as fp:
            for f, nm in added:
                fp.write(f"{f} = {nm}\n")

    old_bins = glob.glob(os.path.join(HERE, "program*.bin"))
    old_bins = [p for p in old_bins if re.fullmatch(r"program\d+\.bin", os.path.basename(p))]
    bak = os.path.join(HERE, ".backup", time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(bak)
    for p in old_bins + [os.path.join(HERE, "programs.txt"), os.path.join(HERE, "sd.img")]:
        if os.path.isfile(p):
            shutil.copy2(p, bak)
    for p in old_bins:
        os.remove(p)
    for n, (_, _, data) in enumerate(sd, 1):
        open(os.path.join(HERE, f"program{n}.bin"), "wb").write(data)
    open(os.path.join(HERE, "programs.txt"), "w", encoding="utf-8").write("".join(e + ";\n" for _, e, _ in sd))
    print(f"Backup in {bak}\n", flush=True)

    extra = [x for x in a.make_sd_args if x != "--"]
    rc = subprocess.call([sys.executable, os.path.join(HERE, "make_sd.py"), "-d", HERE,
                          "-l", os.path.join(HERE, "programs.txt")] + extra, cwd=HERE)
    if rc:
        sys.exit(rc)

    # same SD in the emulator (public/sd.img, loaded at startup) plus the songs it contains (public/songs),
    # only when make_sd.py wrote sd.img
    img = os.path.join(HERE, "sd.img")
    pub = os.path.join(a.emulator, "public")
    if a.emulator and "-o" not in extra and "--output" not in extra:
        if os.path.isdir(pub):
            shutil.copyfile(img, os.path.join(pub, "sd.img"))
            print(f"Also copied to {os.path.normpath(os.path.join(pub, 'sd.img'))}")
            os.makedirs(os.path.join(pub, "songs"), exist_ok=True)
            for f, _ in songs:
                shutil.copyfile(os.path.join(HERE, "songs", f), os.path.join(pub, "songs", f))
            print(f"Songs copied to {os.path.normpath(os.path.join(pub, 'songs'))}: {', '.join(f for f, _ in songs)}")
        else:
            print(f"WARNING: emulator not found ({os.path.normpath(pub)}): sd.img not copied")

if __name__ == "__main__":
    main()
