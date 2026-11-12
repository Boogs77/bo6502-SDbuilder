# bo6502-SDbuilder

Tools to prepare the SD card of the **BO6502** (homebrew 65C02 computer): the `make_sd.py` script packs up to
255 programs into a RAW image, with no filesystem, that the BIOS **SD PROGRAMS** menu shows in pages of 9 entries
and loads into RAM.

## Contents

| File | Description |
|---|---|
| `make_sd.py` | Builds the `sd.img` image or writes directly to the card |
| `update_sd.py` | Builds the SD in one of two modes: `--mode games` (default) takes the games from `../MiniVIC Games/bin` and the songs from `songs/`, runs `make_sd.py` and copies `sd.img` and the songs to `../bo6502-emulator/public/` (the emulator's default SD); `--mode full` also adds the applications of `../MiniVIC Apps/bin` and the sample documents, and writes `sd_full.img`. `--dry-run` only shows what changes |
| `saves.py` | Save area of the card (game records, saved games, from 16 MB): `export` to Markdown, CSV or JSON, `import` of a JSON export, `clear` (see below) |
| `minivic.txt` / `apps.txt` / `songs.txt` | Menu name of each MiniVIC game, application and song (`file.bin = Name`; `file.bin = [TOOL] Name` for a tool) |
| `documents.txt` / `documents/` | Sample documents of the full SD (`file = TYPE NAME`) |
| `programs.txt` | List of menu names of `sd.img` (one per program, separated by `;`); the full SD keeps its own in `full/` |
| `prog.s` | Example program in ca65 assembly (banner, RAM test with `PROGNUM=4`) |
| `ex.cfg` | ld65 configuration: code at `$1000`, at most `$7000` bytes |
| `bios_jt.inc` | Fixed addresses of the BIOS jump table (`$FD00`–`$FD15`) |
| `build.py` | Assembles `prog.s` into `program1..4.bin` (needs cc65) |
| `songs/` | Backup copy of the songs (Imperial March, The Final Countdown, Super Mario Bros; the MiniVIC Sound songs and MiniVIC Jukebox, built in ../MiniVIC Sound) |

The program binaries (`programN.bin`) and the `.img` images are not in the repository: put them in the folder
before running the script, or generate them with `update_sd.py` or `build.py`. To use a song from `songs/` by
hand, copy it as `programN.bin` into the slot you want.

## Updating the SD with the MiniVIC games

```sh
python3 update_sd.py --dry-run     # list the new SD and mark each entry NEW, UPDATED or REMOVED
python3 update_sd.py               # rewrite program1..N.bin and programs.txt, build sd.img, copy it to the emulator
```

New games found in `../MiniVIC Games/bin` are appended to `minivic.txt` with a name derived from the file
(`lunar_lander.bin` -> "Lunar Lander"): edit the name there and run the script again. The previous files are saved
in `.backup/YYYYMMDD-HHMMSS/`. The emulator's daily workflow runs the same script from this repo (through a
read-only deploy key) with the games published on `github.com/Boogs77/miniVIC_games`, so the default SD online
is rebuilt from what is pushed here. Arguments after `--` are passed to `make_sd.py`, e.g.
`python3 update_sd.py -- -o '\\.\PhysicalDrive2'` (in that case `sd.img` is not copied to the emulator).

## Full SD: games and applications

```sh
python3 update_sd.py --mode full --dry-run   # list the full SD
python3 update_sd.py --mode full             # full/program1..N.bin, full/programs.txt -> sd_full.img (16 MB)
```

| Mode | Contents | Output | BIOS |
|---|---|---|---|
| `games` (default) | games, songs | `sd.img`, copied to the emulator | any |
| `full` | games, applications of [miniVIC Apps](https://github.com/Boogs77/miniVIC_apps), songs, sample documents | `sd_full.img`, not copied | KEYB/SD |

The menu lists the games, then the applications (` - APP` or ` - TOOL`), then the songs; games and songs show their plain name (type GAME / SOUND from a `[TYPE]` prefix in `programs.txt`). New applications found
in `../MiniVIC Apps/bin` are appended to `apps.txt`: fix the name there and mark the tools with `[TOOL]`.
`sd_full.img` is 16 MB: after the 255 program blocks (8 MB) comes the document area that the applications read and
write, where the script puts the documents listed in `documents.txt`:

```
letter.dat = TEXT LETTER       # TYPE: TEXT (WRITE, ASM sources), SHEET (CALC), CARDS (FILE), MEMORY (MON)
```

| Sector | Contents |
|---|---|
| `16384` (`$00800000`) | index: `"DOCS"`, version `1`, 15 slots; entry k (1-15) at `k*32`: type, length (lo,hi), 0, name (12 characters) |
| `16384 + k*40` | document k (at most 40 sectors, 20 KB) |

The applications need the BIOS KEYB/SD, which adds sector read/write to the jump table. In the emulator, load the
BIOS with "Load ROM .bin" and `sd_full.img` with "Insert .img image". For a real card, write the whole
`sd_full.img` with a raw image writer (`dd`, Win32 Disk Imager) so that the documents are on it too:
`update_sd.py --mode full -- -o <device>` writes the programs only.

## Save area: game records

The miniVIC games keep their records (and saved games) on the card from **16 MB** (sector `32768`, byte `$01000000`),
right after the end of `sd_full.img`: writing an image with `dd` / Win32 Disk Imager, or the programs with
`make_sd.py -o`, never erases them. The games write there through the BIOS KEYB/SD (`$FD18` / `$FD1B`).

| Sectors | Contents |
|---|---|
| `32768 + z*16` ... `+15` | zone `z` (0-255): one per game (1-127) or application (128-255), fixed numbers |
| zone sectors 0 and 1 | records, two copies written in turn: `"MVSV"`, version 1, zone, type 1, tables, rows, row size 8, write counter, game name (16 chars) at `+16`, rows at `+32` (BCD score low byte first, 3 initials, extra byte), 16-bit sum at `+510` |
| zone sectors 2-15 | free for the game (saved games) |

```sh
python3 saves.py export sd_card.img                      # records as Markdown on the screen
python3 saves.py export '\\.\PhysicalDrive2' -o records.csv   # from the card (Administrator prompt)
python3 saves.py export sd_card.img -o saves.json        # the whole area, to keep or import elsewhere
python3 saves.py import saves.json sd_full.img           # into an image (extended to 18 MB) or onto a card
python3 saves.py clear sd_full.img --zone 28             # one zone, or the whole area without --zone
```

The `.json` file is the same as **Export records** / **Import records** of the
[web emulator](https://github.com/Boogs77/BO6502-miniVIC-emulator), which keeps the area in the browser.
Writing to a card asks to type the device name, unless `--yes` is given.

## Usage of make_sd.py

```sh
python3 make_sd.py                          # reads programs.txt and program1..N.bin -> sd.img
python3 make_sd.py -n 4 -l names.txt        # only the first 4 programs, names from names.txt
python3 make_sd.py -o /dev/sdX --yes        # writes DIRECTLY to the card (destroys its data!)
python3 make_sd.py -o '\\.\PhysicalDrive2'  # Windows, from an Administrator prompt
```

Main options: `--run-all` (run every program after loading), `--keep-case` (do not upper-case the names),
`--allow-missing` (leave the block of a missing program empty), `--min-load` (lowest load address, default
`0F00`), `--no-verify` (skip the read-back check). `-h` prints the full list.

Use a standard capacity SD (up to 2 GB): the BIOS addresses the card by byte.

### Programs

Each program can be:
- `programN.bin`: raw binary;
- `programN.txt` / `programN.hex`: WozMon-style hex dump (`0FD0: 4C 27 11 ...`), from which the script also takes
  the load address.

### Names (`programs.txt`)

```
[!][[TYPE]]Name[@LOAD[:ENTRY]]
```

- `!`: the program runs right after loading (shown as `N>` in the menu; without `!` it is shown as `N.` and only loaded);
- `[TYPE]`: `GAME`, `APP`, `TOOL` or `SOUND`; without it the type comes from a ` - GAME`, ` - APP`, ` - TOOL`, ` - SOUND` or ` - SONG` suffix of the name;
- `@LOAD`: RAM load address in hex (default `1000`);
- `:ENTRY`: start address (default `1000` if it falls inside the image, otherwise `LOAD`).

Example: `Banner; !Arcade Tank@0FD0; Test RAM@1000`

Before writing, the script checks the size (at most 28 KB), the RAM limits (`$0F00`–`$7FFF`) and the entry point.

## SD format

```
offset        contents
$00000000     block of program 1 (32 KB)
$00008000     block of program 2
...           (N-1) * $8000
```

Each 32 KB block looks like this:

| Offset in the block | Contents |
|---|---|
| `+$0000` (sector 0) | directory page P, in block P (only in the first blocks) |
| `+$0200` (sector 1) | ASCII info line (slot, file, load, len, entry, CRC32) |
| `+$1000` – `+$7FFF` | program bytes (at most `$7000`) |

The reserved area `+$0000..+$0FFF` is never copied to RAM. The BIOS writes exactly `[load, load+len)` and leaves
the rest of the memory untouched.

### Directory sector (version 3)

| Offset | Size | Field |
|---|---|---|
| `0` | 4 | magic `"BOGS"` |
| `4` | 1 | version (`3`) |
| `5` | 1 | programs on this page (1..9) |
| `6` | 9 | flags of each entry (bit0 = run) |
| `15` | 1 | total number of programs |
| `16 + i*8` | 8 | load (lo,hi), length (lo,hi), entry (lo,hi), type, serial name length |
| `96 + i*32` | 32 | ASCII name (at most 31 characters + `$00`) |

Type: 0 none, 1 GAME, 2 APP, 3 TOOL, 4 SOUND. The BIOS KEYB/SD (from 03-11-2026) shows them in the GAMES, APPS (APP and TOOL)
and SOUNDS submenus; type 0 only appears in ALL. When a program starts, the BIOS KEYB/SD sends `[TYPE] Name` on the serial
line, using only the first *serial name length* characters of the name (0 = the whole name), so the ` - GAME`
suffix of the menu is left out. Older BIOS versions ignore both bytes.

In the menu, **A**/**D** change page and **1**..**9** choose the program.

## Writing programs

`bios_jt.inc` exposes the BIOS routines:

| Symbol | Address | Function |
|---|---|---|
| `JT_CHROUT` | `$FD00` | prints the character in A |
| `JT_CHRIN_NOECHO` | `$FD03` | C=1 and A=key, C=0 if no key |
| `JT_RESET_TERM` | `$FD06` | resets the terminal |
| `JT_INIT_CRT` | `$FD09` | initialises the video |
| `JT_LOAD_RUN_SLOT` | `$FD0C` | loads and runs the slot in A (JMP, does not return) |
| `JT_SHOW_MENU` | `$FD0F` | back to the BIOS menu (JMP, does not return) |
| `JT_INIT_SDCARD` | `$FD12` | loads the slot in A and returns (C=1 error) |
| `JT_FLUSH_KB` | `$FD15` | flushes the keyboard (~0.5 s) |

Building the example with [cc65](https://cc65.github.io/):

```sh
ca65 -D PROGNUM=1 prog.s -o p1.o
ld65 -C ex.cfg p1.o -o program1.bin
```

> **Warning:** `build.py` overwrites `program1.bin`..`program4.bin`. If those slots already hold other programs,
> run it in a separate folder.
