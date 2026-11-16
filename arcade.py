#!/usr/bin/env python3
"""
arcade.py - the arcade catalog of the Arcade6502 cabinet SD (used by "update_sd.py --mode arcade").

The catalog is read by the front-end of the Arcade BIOS (ARCADE.md of arcade_bios). Version 2:

  sector 24576 ($00C00000)  header: "ARCD", version 2, number of entries N (1-255); title at +16 (31 chars + $00)
  sector 24577 ...          index, 32 bytes per entry: +0 SD slot, +1 kind (1 game, 2 music), +2 flags
                            (bit 0 preview, bit 1 text), +3 credits (bit 0 COIN by default, bit 1 the game
                            handles the credits, bit 2 uses START, bit 3 uses button 3), +4 save zone
                            (0 = none), +8 name (23 chars + $00); +5..+7 are 0
                            (version 1 had +3..+7 = 0: every entry in free play, no zone)
  24576 + 64 + i*8          page of entry i: sector 0 = 16 text lines of 32 bytes, sectors 1-3 = preview patterns
                            (192 tiles of 8 bytes, 16 x 12 by rows), sectors 4-6 = preview colours (fg << 4 | bg)

The texts come from arcade.json (format of the Arcade Games repository); the page lines are built by
header_lines / wrap / page_lines of its tools/check_catalog.py, loaded from there so the two never differ.
The preview is the 512x384 or 256x192 PNG of the entry reduced to the 15 TMS9918A colours, 128 x 96 pixels
with 2 colours per 8-pixel row (same rules as tools/arcade_sd.ts of arcade_bios).
"""
import importlib.util, os, struct, zlib

CAT_LBA    = 24576           # sector of the catalog header
CAT_VER    = 2
PAGE_OFS   = 64              # pages start 64 sectors after the header
PAGE_SECTS = 8
SAVE_LBA   = 32768           # save area: never written
SECTOR     = 512
KINDS      = {"game": 1, "music": 2}

# TMS9918A palette (bo6502-emulator, src/devices/TMS9918A.ts)
TMS_PALETTE = [
    (0, 0, 0), (0, 0, 0), (33, 200, 66), (94, 220, 120), (84, 85, 237), (125, 118, 252), (212, 82, 77),
    (66, 235, 245), (252, 85, 84), (255, 121, 120), (212, 193, 84), (230, 206, 128), (33, 176, 59),
    (201, 91, 186), (204, 204, 204), (255, 255, 255),
]
BRIGHT = [sum(c) for c in TMS_PALETTE]


def load_checker(catalog_path):
    """tools/check_catalog.py next to arcade.json, as a module (check, page_lines, wrap)."""
    path = os.path.join(os.path.dirname(os.path.abspath(catalog_path)), "tools", "check_catalog.py")
    if not os.path.isfile(path):
        raise SystemExit(f"ERROR: catalog checker not found: {path}")
    spec = importlib.util.spec_from_file_location("check_catalog", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def screen_from_png(path):
    """8-bit RGB/RGBA PNG (not interlaced) -> 256x192 palette indices (nearest colour, 1-15)."""
    d = open(path, "rb").read()
    if d[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit(f"ERROR: {path}: not a PNG file")
    w = h = ctype = 0
    idat = []
    o = 8
    while o < len(d):
        ln, t = struct.unpack(">I4s", d[o:o + 8])
        c = d[o + 8:o + 8 + ln]
        if t == b"IHDR":
            w, h, depth, ctype, _, _, inter = struct.unpack(">IIBBBBB", c)
            if depth != 8 or ctype not in (2, 6) or inter:
                raise SystemExit(f"ERROR: {path}: only 8-bit RGB/RGBA PNG, not interlaced")
        elif t == b"IDAT":
            idat.append(c)
        o += 12 + ln
    bpp = 4 if ctype == 6 else 3
    stride = w * bpp
    raw = zlib.decompress(b"".join(idat))
    px = bytearray(stride * h)
    for y in range(h):
        f = raw[y * (stride + 1)]
        line = raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)]
        row, up = y * stride, (y - 1) * stride
        for x in range(stride):
            a = px[row + x - bpp] if x >= bpp else 0
            b = px[up + x] if y else 0
            cc = px[up + x - bpp] if x >= bpp and y else 0
            v = line[x]
            if f == 1:
                v += a
            elif f == 2:
                v += b
            elif f == 3:
                v += (a + b) >> 1
            elif f == 4:
                p = a + b - cc
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - cc)
                v += a if pa <= pb and pa <= pc else (b if pb <= pc else cc)
            px[row + x] = v & 0xFF
    near = {}
    out = bytearray(256 * 192)
    for y in range(192):
        sy = y * h // 192
        for x in range(256):
            o = (sy * w + x * w // 256) * bpp
            rgb = (px[o], px[o + 1], px[o + 2])
            best = near.get(rgb)
            if best is None:
                best, bd = 1, None
                for i in range(1, 16):
                    q = TMS_PALETTE[i]
                    dd = (rgb[0] - q[0]) ** 2 + (rgb[1] - q[1]) ** 2 + (rgb[2] - q[2]) ** 2
                    if bd is None or dd < bd:
                        bd, best = dd, i
                near[rgb] = best
            out[y * 256 + x] = best
    return out


def _dist(a, b):
    p, q = TMS_PALETTE[a], TMS_PALETTE[b]
    return (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2


def _counts(colours):
    """colour -> count, in order of first appearance"""
    n = {}
    for c in colours:
        n[c] = n.get(c, 0) + 1
    return n


def make_preview(scr):
    """256x192 screen -> 128x96 preview: (patterns, colours) of 192 tiles (16 x 12), 8 bytes each."""
    px = bytearray(128 * 96)
    for y in range(96):
        for x in range(128):
            o = y * 2 * 256 + x * 2
            n = _counts((scr[o], scr[o + 1], scr[o + 256], scr[o + 257]))
            # the most frequent colour; with a tie the brightest one (thin lines survive)
            px[y * 128 + x] = sorted(n.items(), key=lambda e: (-e[1], -BRIGHT[e[0]]))[0][0]
    pat, col = bytearray(192 * 8), bytearray(192 * 8)
    for t in range(192):
        tx, ty = (t % 16) * 8, (t // 16) * 8
        for r in range(8):
            row = px[(ty + r) * 128 + tx:(ty + r) * 128 + tx + 8]
            order = [c for c, _ in sorted(_counts(row).items(), key=lambda e: -e[1])]
            fg = order[0]
            bg = order[1] if len(order) > 1 else fg
            bits = 0
            for i, c in enumerate(row):
                if c == fg or (c != bg and _dist(c, fg) <= _dist(c, bg)):
                    bits |= 0x80 >> i
            pat[t * 8 + r] = bits
            col[t * 8 + r] = (fg << 4) | bg
    return bytes(pat), bytes(col)


def text_sector(lines):
    """16 lines of 32 bytes (31 characters + $00)"""
    s = bytearray(SECTOR)
    for i, l in enumerate(lines[:16]):
        b = l.encode("ascii")[:31]
        s[i * 32:i * 32 + len(b)] = b
    return bytes(s)


def sort_entries(entries):
    """front-end order: games in alphabetical order of name, then the music entry"""
    return sorted(entries, key=lambda e: (e["kind"] == "music", e["name"].casefold()))


def credit_flags(e):
    """index byte +3 from the credits and controls of an arcade.json entry"""
    cr, ct = e.get("credits") or {}, e.get("controls") or {}
    return ((1 if cr.get("default") == "coin" else 0) | (2 if cr.get("mode") == "game" else 0)
            | (4 if ct.get("start") else 0) | (8 if (ct.get("buttons") or 0) >= 3 else 0))


def write_catalog(img, title, entries):
    """Writes the catalog into the image (bytearray). entries: dicts with slot, kind, name, lines, preview
    ((patterns, colours) or None), zone (or None), credits and controls (arcade.json), in front-end order."""
    if not 1 <= len(entries) <= 255:
        raise SystemExit(f"ERROR: {len(entries)} catalog entries, 1-255")
    end = CAT_LBA + PAGE_OFS + len(entries) * PAGE_SECTS
    if end > SAVE_LBA or len(img) < end * SECTOR:
        raise SystemExit("ERROR: the catalog does not fit before the save area")
    base = CAT_LBA * SECTOR
    img[base:base + PAGE_OFS * SECTOR] = bytes(PAGE_OFS * SECTOR)
    img[base:base + 6] = b"ARCD" + bytes([CAT_VER, len(entries)])
    t = title.encode("ascii")[:31]
    img[base + 16:base + 16 + len(t)] = t
    for i, e in enumerate(entries):
        o = base + SECTOR + i * 32
        img[o] = e["slot"]
        img[o + 1] = KINDS[e["kind"]]
        img[o + 2] = (1 if e["preview"] else 0) | (2 if e["lines"] else 0)
        img[o + 3] = credit_flags(e)
        img[o + 4] = e.get("zone") or 0
        n = e["name"].encode("ascii")[:23]
        img[o + 8:o + 8 + len(n)] = n
        p = (CAT_LBA + PAGE_OFS + i * PAGE_SECTS) * SECTOR
        img[p:p + PAGE_SECTS * SECTOR] = bytes(PAGE_SECTS * SECTOR)
        img[p:p + SECTOR] = text_sector(e["lines"])
        if e["preview"]:
            pat, col = e["preview"]
            img[p + SECTOR:p + SECTOR + len(pat)] = pat
            img[p + 4 * SECTOR:p + 4 * SECTOR + len(col)] = col
    return end
