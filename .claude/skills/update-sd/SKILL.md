---
name: update-sd
description: Checks "MiniVIC Games/bin" for new or updated games and regenerates the BO6502 SD (program*.bin, programs.txt, sd.img), then copies it into the emulator project; also rebuilds the Arcade6502 cabinet SD (sd_arcade.img, --mode arcade) from arcade.json of Arcade Games. Use it when the user asks to update or rebuild the SD ("aggiorna la SD", "rifai l'SD", "SD arcade", "SD del cabinato"), to add the new MiniVIC games, when arcade.json, its previews or the cabinet games change, or to check what changed compared with the current SD.
---

# Updating the SD with the MiniVIC games

All the work is done by `update_sd.py`, in the project folder. Never renumber the files by hand.

## Steps

1. **Preview.** Run `python update_sd.py --dry-run` from the project folder. The script lists the programs of the
   new SD in menu order: first the games in alphabetical order, then the songs. Next to each entry it prints NEW,
   UPDATED or REMOVED compared with the current SD.
2. **If there are 0 differences**, tell the user and stop: the SD is already up to date.
3. **If there are new games**, the script derives the name from the file (e.g. `lunar_lander.bin` -> "Lunar Lander").
   Show the name to the user. If they want a different one, fix it in `minivic.txt` after step 4 and run the script again.
4. **Generation.** Run `python update_sd.py`. The script:
   - appends the new games to `minivic.txt`;
   - saves the old `program*.bin`, `programs.txt` and `sd.img` in `.backup/<date-time>/`;
   - rewrites `program1..N.bin` and `programs.txt`;
   - runs `make_sd.py`, which builds `sd.img` and reads it back to verify it;
   - copies `sd.img` to `../bo6502-emulator/public/sd.img`, which the emulator loads at startup, and the songs to
     `../bo6502-emulator/public/songs/`. With `--emulator ''` it skips the copy.
5. **Check.** The output must contain `Verify OK`, `Also copied to ...\bo6502-emulator\public\sd.img` and
   `Songs copied to ...`.
   If `make_sd.py` fails (program too large, address outside RAM, ...), report the message as it is, without
   changing the MiniVIC binaries.

## Rules

- Write `sd.img` only. Writing directly to a card (`-- -o '\\.\PhysicalDrive2'` or `-- -o /dev/sdX`) needs an
  explicit request from the user naming the device: it erases everything on the card.
- No commit or push unless the user asks. When they do, the files to commit here are `programs.txt` and
  `minivic.txt` (the `.bin` and `.img` files are excluded by `.gitignore`).
- The SD generated here must be identical to the one the online emulator loads by default. The user has approved
  publishing it: after a new SD, commit and push here (`programs.txt`, `minivic.txt`, any new song) and in the
  `bo6502-emulator` repo (public repo, the push redeploys GitHub Pages) commit only `public/sd.img` and
  `public/songs/`, because that repo may contain changes from other sessions. Then wait for the Pages deploy,
  download `https://boogs77.github.io/BO6502-miniVIC-emulator/sd.img` and compare it with `sd.img` (`cmp`).
- The emulator's daily workflow `sync-games.yml` also runs `update_sd.py` from this repo (read-only deploy key,
  secret `SDBUILDER_DEPLOY_KEY`) with the games of `github.com/Boogs77/miniVIC_games`, and publishes the SD if it
  changed. So: push `minivic.txt`, `songs.txt` and `songs/` here, otherwise the next daily run rebuilds the online
  SD from the old ones. Games that exist only in the local `MiniVIC Games` folder and are not pushed to
  miniVIC_games will be missing online.
- Everything written to files and commit messages is in English; talk to the user in Italian. In the final summary
  list: games added, updated or removed, total number of programs and menu pages, verify result.
- Update the session diary with the `session-log` skill.

## Cabinet SD (`--mode arcade`)

Rebuild it whenever `../Arcade Games/arcade.json`, its `previews/`, a game it lists or `songs.txt` changes:

1. `python update_sd.py --mode arcade --dry-run`: checks `arcade.json` with `tools/check_catalog.py` of Arcade
   Games (with errors nothing is written; fix them there, not from here) and lists the programs.
2. `python update_sd.py --mode arcade`: writes `arcade/program*.bin`, `arcade/programs.txt` and `sd_arcade.img`
   (16 MB, catalog from sector 24576) and **always** copies it gzipped to
   `../bo6502-emulator/public/sd_arcade.img.gz`. The output must end with `Verify OK`, `Arcade catalog ...` and
   `Also copied to ...sd_arcade.img.gz`. Never skip the copy (`--emulator ''`) unless the user asks.
3. Optional check: `node test/run.mjs` in `../Arcade BIOS` reads `tmp/sd_arcade.img`; copy the new image there
   only for the test and put the old one back.

The `games` and `full` modes do not change with it. Commit `public/sd_arcade.img.gz` in the emulator repo only
when the user asks (it is published by GitHub Pages).

## Files

- `minivic.txt`: `file.bin = Name` for each MiniVIC game. The menu name becomes `NAME - GAME` and the game is loaded at `$0FD0`.
- `songs.txt`: `file.bin = Name` for the songs in `songs/`, in menu order. The name becomes `NAME - SONG` and the song is loaded at `$1000`.
- Different games folder: `--minivic PATH`.
