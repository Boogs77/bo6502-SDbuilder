#!/usr/bin/env python3
"""
aggiorna_sd.py - prende i giochi da "MiniVIC Games/bin" e le canzoni da songs/, rifa' program1..N.bin e
programs.txt e rigenera l'SD con make_sd.py.

Ordine nel menu: prima i giochi in ordine alfabetico (" - GAME", caricati a $0FD0), poi le canzoni
nell'ordine di songs.txt (" - SONG", caricate a $1000).

  minivic.txt  file.bin = Nome   giochi conosciuti; i .bin nuovi vengono aggiunti in fondo con un nome
                                 ricavato dal file (es. lunar_lander.bin -> "Lunar Lander")
  songs.txt    file.bin = Nome   canzoni in songs/

Prima di sovrascrivere, i vecchi programN.bin e programs.txt vengono copiati in .backup/AAAAMMGG-HHMMSS/.

Esempi:
  python3 aggiorna_sd.py --dry-run     # mostra solo cosa cambierebbe
  python3 aggiorna_sd.py               # aggiorna i file e rigenera sd.img
  python3 aggiorna_sd.py -o '\\\\.\\PhysicalDrive2'   # passa -o (e gli altri argomenti dopo --) a make_sd.py
"""
import argparse, glob, hashlib, os, re, shutil, subprocess, sys, time

HERE       = os.path.dirname(os.path.abspath(__file__))
MINIVIC    = os.path.join(HERE, "..", "MiniVIC Games", "bin")
GAME_LOAD  = "0FD0"          # trampolino NMI dei giochi MiniVIC
MAX_PROGS  = 255

def read_map(path):
    """Righe 'file.bin = Nome' -> lista di (file, nome) nell'ordine del file."""
    items = []
    if not os.path.isfile(path):
        return items
    for n, line in enumerate(open(path, encoding="utf-8-sig"), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            sys.exit(f"ERRORE: {os.path.basename(path)} riga {n}: manca '=' in {line!r}")
        f, name = (s.strip() for s in line.split("=", 1))
        if not f or not name:
            sys.exit(f"ERRORE: {os.path.basename(path)} riga {n}: file o nome vuoto")
        if re.search(r"[;!@]", name):
            sys.exit(f"ERRORE: {os.path.basename(path)} riga {n}: il nome non puo' contenere ; ! @")
        items.append((f, name))
    return items

def name_from_file(f):
    return " ".join(w.capitalize() for w in os.path.splitext(f)[0].replace("-", "_").split("_") if w)

def digest(data):
    return hashlib.sha1(data).hexdigest()

def current_sd():
    """Nome nel menu -> hash del programN.bin attuale, letto da programs.txt."""
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
    ap = argparse.ArgumentParser(description="Aggiorna l'SD BO6502 con i giochi di MiniVIC Games",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--minivic", default=MINIVIC, help="cartella con i .bin dei giochi (default ../MiniVIC Games/bin)")
    ap.add_argument("--dry-run", action="store_true", help="mostra le differenze senza scrivere niente")
    ap.add_argument("make_sd_args", nargs=argparse.REMAINDER, help="argomenti passati a make_sd.py (dopo --)")
    a = ap.parse_args()
    if not os.path.isdir(a.minivic):
        sys.exit(f"ERRORE: cartella dei giochi non trovata: {a.minivic}")

    map_path = os.path.join(HERE, "minivic.txt")
    known = read_map(map_path)
    known_files = {f for f, _ in known}
    found = sorted(os.path.basename(p) for p in glob.glob(os.path.join(a.minivic, "*.bin")))
    added = [(f, name_from_file(f)) for f in found if f not in known_files]
    missing = [f for f, _ in known if f not in found]

    games = [(f, nm) for f, nm in known + added if f in found]
    games.sort(key=lambda g: g[1].upper())
    songs = read_map(os.path.join(HERE, "songs.txt"))
    for f, _ in songs:
        if not os.path.isfile(os.path.join(HERE, "songs", f)):
            sys.exit(f"ERRORE: canzone non trovata: songs/{f}")
    if len(games) + len(songs) > MAX_PROGS:
        sys.exit(f"ERRORE: {len(games) + len(songs)} programmi, massimo {MAX_PROGS}")

    # nuova SD: (nome nel menu, voce di programs.txt, dati)
    sd = [(f"{nm} - GAME", f"!{nm} - GAME@{GAME_LOAD}", open(os.path.join(a.minivic, f), "rb").read())
          for f, nm in games]
    sd += [(f"{nm} - SONG", f"!{nm} - SONG", open(os.path.join(HERE, "songs", f), "rb").read())
           for f, nm in songs]

    cur = current_sd()
    print(f"Giochi da {os.path.normpath(a.minivic)}: {len(games)}   canzoni: {len(songs)}\n")
    changes = 0
    for n, (label, _, data) in enumerate(sd, 1):
        old = cur.pop(label.upper(), None)
        state = "NUOVO" if old is None else ("AGGIORNATO" if old != digest(data) else "")
        changes += bool(state)
        print(f"{n:>3}  {label:<34}{len(data):>6} byte  {state}")
    for label in cur:
        changes += 1
        print(f"  -  {label:<34}         TOLTO")
    for f in missing:
        print(f"ATTENZIONE: {f} e' in minivic.txt ma non in {a.minivic}: lasciato fuori")
    for f, nm in added:
        print(f"NUOVO GIOCO: {f} -> \"{nm}\" ({'verra' if a.dry_run else 'e'}' aggiunto a minivic.txt, "
              f"correggi il nome li' se serve)")
    print(f"\n{changes} differenze rispetto all'SD attuale")
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
    sys.exit(subprocess.call([sys.executable, os.path.join(HERE, "make_sd.py"), "-d", HERE,
                              "-l", os.path.join(HERE, "programs.txt")] + extra, cwd=HERE))

if __name__ == "__main__":
    main()
