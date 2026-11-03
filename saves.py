#!/usr/bin/env python3
"""
saves.py - reads, exports, imports and clears the SAVE AREA of a miniVIC SD card (game records, saved games).

Layout: the area starts at 16 MB (sector 32768, byte $01000000), right after the end of sd_full.img, so
writing an SD image (dd, Win32 Disk Imager, make_sd.py -o) never erases it. 256 zones of 16 sectors (2 MB):
zone z = sectors 32768 + z*16 ... +15, one zone per game or application (fixed numbers: 1-127 games,
128-255 applications). Sectors 0 and 1 of a zone hold the records, two copies written in turn:
    +0 "MVSV"  +4 version 1  +5 zone  +6 type 1 (records)  +7 tables  +8 rows per table  +9 row size (8)
    +10 write counter (lo,hi): the valid copy with the higher counter wins   +16 game name (16 chars)
    +32 rows: score (4 bytes BCD, low byte first), initials (3 ASCII), extra byte (level reached...)
    +510 16-bit sum of bytes 0-509 (lo,hi)
Sectors 2-15 of a zone are free for the game (saved games). A sector of zeros is an empty sector.

The .json file is the same as the "Export records" of the web emulator (bo6502-emulator):
    {"format": "minivic-saves", "version": 1, "first": 32768, "sectors": {"<sector>": "<base64>"}, "records": [...]}
only the written sectors; "records" is the readable view and is ignored on import.

Commands (SOURCE / TARGET = an image file, a card device, or for export also a .json):
  python3 saves.py export sd_card.img                    # records as Markdown on the screen
  python3 saves.py export '\\\\.\\PhysicalDrive2' -o records.csv   # from the card (Administrator prompt)
  python3 saves.py export records.json -o records.md     # an export of the web emulator, as Markdown
  python3 saves.py export sd_card.img -o saves.json      # whole area, to import elsewhere
  python3 saves.py import saves.json sd_full.img         # puts the area into an image (extends it to 18 MB)
  python3 saves.py import saves.json /dev/sdX            # ... or onto a card (asks for confirmation)
  python3 saves.py clear sd_full.img [--zone 28]         # erases the whole area or one zone
The output format comes from the -o extension (.md, .csv, .json); without -o, Markdown on the screen.
Spec shared by the miniVIC projects: SD_SALVATAGGI.md (in the folder that contains them).
"""
import argparse, base64, csv, io, json, os, sys

SECTOR     = 512
SAVE_FIRST = 32768           # first sector of the area (16 MB)
SAVE_COUNT = 4096            # 256 zones x 16 sectors
ZONE       = 16
MAGIC      = b"MVSV"


def is_device(p):
    return p.startswith("\\\\.\\") or p.startswith("/dev/")


def read_area(src):
    """{sector: 512 bytes} of the written (non-zero) sectors, from an image/device or a .json export"""
    if src.lower().endswith(".json"):
        j = json.load(open(src, encoding="utf-8"))
        if j.get("format") != "minivic-saves":
            sys.exit(f"{src}: not a miniVIC saves file")
        out = {}
        for k, v in j.get("sectors", {}).items():
            n, d = int(k), base64.b64decode(v)
            if not (SAVE_FIRST <= n < SAVE_FIRST + SAVE_COUNT) or len(d) != SECTOR:
                sys.exit(f"{src}: bad sector {k}")
            out[n] = d
        return out
    out = {}
    with open(src, "rb") as f:
        f.seek(SAVE_FIRST * SECTOR)
        data = f.read(SAVE_COUNT * SECTOR)
    for i in range(len(data) // SECTOR):
        d = data[i * SECTOR:(i + 1) * SECTOR]
        if any(d):
            out[SAVE_FIRST + i] = d
    return out


def parse_records(d, zone):
    """the records table of a sector, or None if it is not a valid records sector of that zone"""
    if d[:4] != MAGIC or d[4] != 1 or d[5] != zone or d[6] != 1:
        return None
    if sum(d[:510]) & 0xFFFF != d[510] | (d[511] << 8):
        return None
    tables, per, size = d[7], d[8], d[9]
    if size != 8 or 32 + tables * per * size > 510:
        return None
    rows = []
    for i in range(tables * per):
        r = d[32 + i * 8:40 + i * 8]
        score = "".join(f"{b:02x}" for b in reversed(r[:4])).lstrip("0") or "0"
        rows.append({"score": score, "name": r[4:7].decode("ascii", "replace"), "extra": r[7]})
    return {"zone": zone, "game": d[16:32].decode("ascii", "replace").strip(),
            "counter": d[10] | (d[11] << 8), "tables": tables, "rows": rows}


def records(area):
    out = []
    for z in range(SAVE_COUNT // ZONE):
        base = SAVE_FIRST + z * ZONE
        copies = [parse_records(area[s], z) for s in (base, base + 1) if s in area]
        copies = [c for c in copies if c]
        if copies:
            out.append(max(copies, key=lambda c: c["counter"]))
    return out


def as_markdown(recs, area):
    lines = ["# miniVIC records", ""]
    if not recs:
        lines.append("No records in the save area.")
    for r in recs:
        lines += [f"## {r['game'] or 'zone ' + str(r['zone'])} (zone {r['zone']})", "",
                  "| # | Initials | Score | Extra |", "| ---: | :--- | ---: | ---: |"]
        for i, row in enumerate(r["rows"], 1):
            if row["name"] != "---":
                lines.append(f"| {i} | {row['name']} | {row['score']} | {row['extra']} |")
        lines.append("")
    saved = sorted({(s - SAVE_FIRST) // ZONE for s in area if (s - SAVE_FIRST) % ZONE >= 2})
    if saved:
        lines.append("Zones with saved games: " + ", ".join(map(str, saved)))
    return "\n".join(lines) + "\n"


def as_csv(recs):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["zone", "game", "rank", "initials", "score", "extra"])
    for r in recs:
        for i, row in enumerate(r["rows"], 1):
            if row["name"] != "---":
                w.writerow([r["zone"], r["game"], i, row["name"], row["score"], row["extra"]])
    return buf.getvalue()


def as_json(area, recs):
    sectors = {str(n): base64.b64encode(area[n]).decode() for n in sorted(area)}
    return json.dumps({"format": "minivic-saves", "version": 1, "first": SAVE_FIRST,
                       "sectors": sectors, "records": recs}, indent=1) + "\n"


def confirm(target, what, yes):
    if is_device(target) and not yes:
        print(f"WARNING: about to {what} on {target} (save area only, from 16 MB).")
        if input(f"Type the device name ({target}) to confirm: ").strip() != target:
            sys.exit("Cancelled.")


def write_sectors(target, sectors):
    """writes {sector: 512 bytes} into an image (extended if shorter) or a device"""
    if not is_device(target) and not os.path.exists(target):
        sys.exit(f"{target}: not found")
    with open(target, "r+b") as f:
        for n in sorted(sectors):
            f.seek(n * SECTOR)
            f.write(sectors[n])
        f.flush()
        try: os.fsync(f.fileno())
        except OSError: pass


def main():
    ap = argparse.ArgumentParser(description="Save area of a miniVIC SD card: export, import, clear.",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export", help="records (.md, .csv) or the whole area (.json)")
    e.add_argument("source", help="image, device or .json export")
    e.add_argument("-o", "--output", help="output file: .md, .csv or .json (default: Markdown on the screen)")
    i = sub.add_parser("import", help="writes a .json export into an image or onto a card (replaces the area)")
    i.add_argument("json")
    i.add_argument("target")
    i.add_argument("--yes", action="store_true", help="no confirmation for a device")
    c = sub.add_parser("clear", help="erases the save area (or one zone)")
    c.add_argument("target")
    c.add_argument("--zone", type=int, help="only this zone (0-255)")
    c.add_argument("--yes", action="store_true", help="no confirmation for a device")
    a = ap.parse_args()

    if a.cmd == "export":
        area = read_area(a.source)
        recs = records(area)
        ext = os.path.splitext(a.output or "")[1].lower()
        text = as_json(area, recs) if ext == ".json" else as_csv(recs) if ext == ".csv" else as_markdown(recs, area)
        if a.output:
            open(a.output, "w", encoding="utf-8", newline="").write(text)
            print(f"{len(recs)} games with records, {len(area)} sectors written -> {a.output}")
        else:
            sys.stdout.write(text)
    elif a.cmd == "import":
        area = read_area(a.json)
        confirm(a.target, f"replace the save area with {len(area)} sectors of {a.json}", a.yes)
        zero = bytes(SECTOR)
        write_sectors(a.target, {n: area.get(n, zero) for n in range(SAVE_FIRST, SAVE_FIRST + SAVE_COUNT)})
        print(f"{len(area)} sectors imported into {a.target} ({len(records(area))} games with records)")
    else:
        if a.zone is not None and not 0 <= a.zone < SAVE_COUNT // ZONE:
            sys.exit("zone: 0-255")
        first = SAVE_FIRST + (a.zone * ZONE if a.zone is not None else 0)
        count = ZONE if a.zone is not None else SAVE_COUNT
        what = f"erase zone {a.zone}" if a.zone is not None else "erase the whole save area"
        confirm(a.target, what, a.yes)
        write_sectors(a.target, {n: bytes(SECTOR) for n in range(first, first + count)})
        print(f"{what}: {count} sectors cleared on {a.target}")


if __name__ == "__main__":
    main()
