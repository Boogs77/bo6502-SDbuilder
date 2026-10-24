# bo6502-SDbuilder

Tools to prepare the SD card of the **BO6502** (homebrew 65C02 computer): the `make_sd.py` script packs up to
255 programs into a RAW image, with no filesystem, that the BIOS **SD PROGRAMS** menu shows in pages of 9 entries
and loads into RAM.

## Contents

| File | Description |
|---|---|
| `make_sd.py` | Builds the `sd.img` image or writes directly to the card |
| `update_sd.py` | Takes the games from `../MiniVIC Games/bin` and the songs from `songs/`, sorts them (games in alphabetical order, then songs), runs `make_sd.py` and copies `sd.img` and the songs to `../bo6502-emulator/public/` (the emulator's default SD); `--dry-run` only shows what changes |
| `minivic.txt` / `songs.txt` | Menu name of each MiniVIC game and of each song (`file.bin = Name`) |
| `programs.txt` | List of menu names (one per program, separated by `;`) |
| `prog.s` | Example program in ca65 assembly (banner, RAM test with `PROGNUM=4`) |
| `ex.cfg` | ld65 configuration: code at `$1000`, at most `$7000` bytes |
| `bios_jt.inc` | Fixed addresses of the BIOS jump table (`$FD00`–`$FD15`) |
| `build.py` | Assembles `prog.s` into `program1..4.bin` (needs cc65) |
| `songs/` | Backup copy of the songs (Imperial March, The Final Countdown, Super Mario Bros) |

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
[!]Name[@LOAD[:ENTRY]]
```

- `!`: the program runs right after loading (shown as `N>` in the menu; without `!` it is shown as `N.` and only loaded);
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
| `16 + i*8` | 8 | load (lo,hi), length (lo,hi), entry (lo,hi), 0, 0 |
| `96 + i*32` | 32 | ASCII name (at most 31 characters + `$00`) |

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
