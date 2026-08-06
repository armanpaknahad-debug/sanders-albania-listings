#!/usr/bin/env python3
"""pdfmini — a dependency-free PDF reader, enough for developer plan sheets.

Deliberately brute-force: instead of following the xref table (which these CAD
exports write as an xref *stream*, and which incremental saves make fiddly), we
scan the file for every `N G obj` and expand every object stream. That is robust
against damaged/regenerated xrefs and is fast enough at this file size.

Supports: FlateDecode (+ PNG/TIFF predictors), ASCIIHexDecode, ASCII85Decode,
RunLengthDecode; object streams; page content concatenation; Type0/Type1/TrueType
simple + CID fonts with ToUnicode CMaps or standard encodings.
"""
import re, zlib, sys


# ---------------------------------------------------------------- primitives
class Name(str):
    __slots__ = ()

class Ref:
    __slots__ = ("num", "gen")
    def __init__(self, num, gen): self.num, self.gen = num, gen
    def __repr__(self): return f"{self.num} {self.gen} R"
    def __eq__(self, o): return isinstance(o, Ref) and (o.num, o.gen) == (self.num, self.gen)
    def __hash__(self): return hash((self.num, self.gen))

class Stream:
    __slots__ = ("dict", "raw", "_data")
    def __init__(self, d, raw): self.dict, self.raw, self._data = d, raw, None


WS = b"\x00\t\n\x0c\r "
DELIM = b"()<>[]{}/%"


class Lexer:
    def __init__(self, buf, pos=0):
        self.b, self.i = buf, pos

    def skip(self):
        b, n = self.b, len(self.b)
        while self.i < n:
            c = b[self.i]
            if c in WS:
                self.i += 1
            elif c == 0x25:  # % comment
                while self.i < n and b[self.i] not in b"\r\n":
                    self.i += 1
            else:
                return

    def token(self):
        """Next raw token as bytes, or None at EOF."""
        self.skip()
        b, n = self.b, len(self.b)
        if self.i >= n:
            return None
        c = b[self.i]
        if c == 0x2F:  # /Name
            j = self.i + 1
            while j < n and b[j] not in WS and b[j] not in DELIM:
                j += 1
            t = b[self.i:j]; self.i = j
            return t
        if b[self.i:self.i + 2] in (b"<<", b">>"):
            t = b[self.i:self.i + 2]; self.i += 2
            return t
        if c in b"[]{}":
            self.i += 1
            return bytes([c])
        if c == 0x28:  # ( string
            return self._lit_string()
        if c == 0x3C:  # < hex string
            j = self.b.index(b">", self.i)
            t = b[self.i:j + 1]; self.i = j + 1
            return t
        j = self.i
        while j < n and b[j] not in WS and b[j] not in DELIM:
            j += 1
        if j == self.i:
            j += 1
        t = b[self.i:j]; self.i = j
        return t

    def _lit_string(self):
        b, n = self.b, len(self.b)
        j = self.i + 1
        depth = 1
        out = bytearray()
        while j < n:
            c = b[j]
            if c == 0x5C:  # backslash
                out.append(c)
                if j + 1 < n:
                    out.append(b[j + 1])
                j += 2
                continue
            if c == 0x28:
                depth += 1
            elif c == 0x29:
                depth -= 1
                if depth == 0:
                    j += 1
                    break
            out.append(c)
            j += 1
        self.i = j
        return b"(" + bytes(out) + b")"


NUM_RE = re.compile(rb"^[+-]?(\d+\.?\d*|\.\d+)$")
REF_RE = re.compile(rb"^\d+$")


def decode_lit(tok):
    """(...) literal string bytes → bytes, resolving escapes."""
    s = tok[1:-1]
    out = bytearray()
    i = 0
    while i < len(s):
        c = s[i]
        if c == 0x5C and i + 1 < len(s):
            d = s[i + 1]
            m = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12}
            if d in m:
                out.append(m[d]); i += 2
            elif 0x30 <= d <= 0x37:
                j = i + 1; oct_ = b""
                while j < len(s) and len(oct_) < 3 and 0x30 <= s[j] <= 0x37:
                    oct_ += bytes([s[j]]); j += 1
                out.append(int(oct_, 8) & 0xFF); i = j
            elif d in (10, 13):
                i += 2
                if d == 13 and i < len(s) and s[i] == 10:
                    i += 1
            else:
                out.append(d); i += 2
        else:
            out.append(c); i += 1
    return bytes(out)


def decode_hex(tok):
    h = re.sub(rb"[^0-9A-Fa-f]", b"", tok[1:-1])
    if len(h) % 2:
        h += b"0"
    return bytes.fromhex(h.decode())


class Parser(Lexer):
    """Object parser layered on the lexer."""

    def obj(self):
        t = self.token()
        return self._from(t)

    def _from(self, t):
        if t is None:
            return None
        if t == b"<<":
            d = {}
            while True:
                k = self.token()
                if k is None or k == b">>":
                    break
                if not k.startswith(b"/"):
                    continue
                d[k[1:].decode("latin-1")] = self.obj()
            # stream?
            save = self.i
            self.skip()
            if self.b[self.i:self.i + 6] == b"stream":
                self.i += 6
                if self.b[self.i:self.i + 2] == b"\r\n":
                    self.i += 2
                elif self.b[self.i:self.i + 1] in (b"\n", b"\r"):
                    self.i += 1
                start = self.i
                ln = d.get("Length")
                end = None
                if isinstance(ln, int):
                    end = start + ln
                    tail = self.b[end:end + 20]
                    if b"endstream" not in tail:
                        end = None
                if end is None:
                    e = self.b.find(b"endstream", start)
                    end = e if e >= 0 else len(self.b)
                raw = self.b[start:end]
                self.i = self.b.find(b"endstream", end)
                self.i = len(self.b) if self.i < 0 else self.i + 9
                return Stream(d, raw)
            self.i = save
            return d
        if t == b"[":
            a = []
            while True:
                x = self.token()
                if x is None or x == b"]":
                    break
                a.append(self._from(x))
            return a
        if t.startswith(b"/"):
            return Name(t[1:].decode("latin-1"))
        if t.startswith(b"("):
            return decode_lit(t)
        if t.startswith(b"<"):
            return decode_hex(t)
        if t == b"true":
            return True
        if t == b"false":
            return False
        if t == b"null":
            return None
        if REF_RE.match(t):
            # lookahead for "gen R"
            save = self.i
            t2 = self.token()
            if t2 is not None and REF_RE.match(t2):
                t3 = self.token()
                if t3 == b"R":
                    return Ref(int(t), int(t2))
            self.i = save
            return int(t)
        if NUM_RE.match(t):
            s = t.decode()
            return float(s) if ("." in s) else int(s)
        return Name(t.decode("latin-1", "replace"))  # operator / junk


# ---------------------------------------------------------------- filters
def png_predict(data, colors, bpc, columns):
    bpp = max(1, (colors * bpc + 7) // 8)
    rowlen = (columns * colors * bpc + 7) // 8
    out = bytearray()
    prev = bytearray(rowlen)
    i = 0
    while i + 1 <= len(data) - 1:
        ft = data[i]; i += 1
        row = bytearray(data[i:i + rowlen]); i += rowlen
        if len(row) < rowlen:
            row += bytearray(rowlen - len(row))
        if ft == 1:
            for j in range(bpp, rowlen):
                row[j] = (row[j] + row[j - bpp]) & 0xFF
        elif ft == 2:
            for j in range(rowlen):
                row[j] = (row[j] + prev[j]) & 0xFF
        elif ft == 3:
            for j in range(rowlen):
                left = row[j - bpp] if j >= bpp else 0
                row[j] = (row[j] + ((left + prev[j]) >> 1)) & 0xFF
        elif ft == 4:
            for j in range(rowlen):
                a = row[j - bpp] if j >= bpp else 0
                b = prev[j]
                c = prev[j - bpp] if j >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                row[j] = (row[j] + pr) & 0xFF
        out += row
        prev = row
    return bytes(out)


def a85(data):
    data = re.sub(rb"\s", b"", data)
    if data.endswith(b"~>"):
        data = data[:-2]
    out = bytearray(); grp = []
    for ch in data:
        if ch == 0x7A and not grp:
            out += b"\0\0\0\0"; continue
        grp.append(ch - 33)
        if len(grp) == 5:
            v = 0
            for g in grp: v = v * 85 + g
            out += v.to_bytes(4, "big"); grp = []
    if grp:
        n = len(grp)
        grp += [84] * (5 - n)
        v = 0
        for g in grp: v = v * 85 + g
        out += v.to_bytes(4, "big")[:n - 1]
    return bytes(out)


def rle(data):
    out = bytearray(); i = 0
    while i < len(data):
        l = data[i]; i += 1
        if l == 128: break
        if l < 128:
            out += data[i:i + l + 1]; i += l + 1
        else:
            out += bytes([data[i]]) * (257 - l); i += 1
    return bytes(out)


IMAGE_FILTERS = {"DCTDecode", "JPXDecode", "JBIG2Decode", "CCITTFaxDecode"}


# ---------------------------------------------------------------- document
class PDF:
    def __init__(self, path):
        self.buf = open(path, "rb").read() if isinstance(path, str) else path
        self.objs = {}          # num -> byte offset
        self.cache = {}
        self._scan()
        self._expand_objstms()

    def _scan(self):
        for m in re.finditer(rb"(?:^|[\s>\]])(\d+)\s+(\d+)\s+obj\b", self.buf):
            self.objs[int(m.group(1))] = m.end()   # later definitions win

    def _expand_objstms(self):
        self.instm = {}
        for num in list(self.objs):
            o = self.get(num)
            if isinstance(o, Stream) and o.dict.get("Type") == "ObjStm":
                try:
                    data = self.data(o)
                    n = self.res(o.dict.get("N", 0))
                    first = self.res(o.dict.get("First", 0))
                    head = data[:first].split()
                    for k in range(n):
                        onum, off = int(head[2 * k]), int(head[2 * k + 1])
                        if onum not in self.objs:
                            self.instm[onum] = (data, first + off)
                except Exception:
                    pass

    def get(self, num):
        if num in self.cache:
            return self.cache[num]
        self.cache[num] = None
        if num in self.objs:
            v = Parser(self.buf, self.objs[num]).obj()
        elif num in getattr(self, "instm", {}):
            data, off = self.instm[num]
            v = Parser(data, off).obj()
        else:
            v = None
        self.cache[num] = v
        return v

    def res(self, o):
        seen = 0
        while isinstance(o, Ref) and seen < 32:
            o = self.get(o.num); seen += 1
        return o

    def data(self, st):
        if st._data is not None:
            return st._data
        d = st.raw
        f = self.res(st.dict.get("Filter"))
        if f is None:
            f = []
        if isinstance(f, (str, Name)):
            f = [f]
        parms = self.res(st.dict.get("DecodeParms")) or self.res(st.dict.get("DP"))
        if not isinstance(parms, list):
            parms = [parms] * len(f)
        for k, fl in enumerate(f):
            fl = str(fl)
            if fl in IMAGE_FILTERS:
                break                                # leave encoded (JPEG etc.)
            if fl in ("FlateDecode", "Fl"):
                try:
                    d = zlib.decompress(d)
                except Exception:
                    d = zlib.decompressobj().decompress(d)
            elif fl in ("ASCIIHexDecode", "AHx"):
                d = bytes.fromhex(re.sub(rb"[^0-9A-Fa-f]", b"", d.split(b">")[0]).decode())
            elif fl in ("ASCII85Decode", "A85"):
                d = a85(d)
            elif fl in ("RunLengthDecode", "RL"):
                d = rle(d)
            p = self.res(parms[k]) if k < len(parms) else None
            if isinstance(p, dict) and self.res(p.get("Predictor", 1)) and self.res(p.get("Predictor", 1)) >= 10:
                d = png_predict(d, self.res(p.get("Colors", 1)), self.res(p.get("BitsPerComponent", 8)),
                                self.res(p.get("Columns", 1)))
        st._data = d
        return d

    # -- pages ------------------------------------------------------------
    def pages(self):
        out = []
        for num in sorted(self.objs) + sorted(getattr(self, "instm", {})):
            o = self.get(num)
            if isinstance(o, dict) and not isinstance(o, Stream) and o.get("Type") == "Page":
                out.append(o)
        return out

    def content(self, page):
        c = self.res(page.get("Contents"))
        if isinstance(c, Stream):
            return self.data(c)
        if isinstance(c, list):
            return b"\n".join(self.data(self.res(x)) for x in c if isinstance(self.res(x), Stream))
        return b""


# ---------------------------------------------------------------- fonts
STD_DIFF_FALLBACK = {}


def cmap_from_tounicode(data):
    m = {}
    for blk in re.findall(rb"beginbfchar(.*?)endbfchar", data, re.S):
        for src, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            m[int(src, 16)] = _utf16(dst)
    for blk in re.findall(rb"beginbfrange(.*?)endbfrange", data, re.S):
        for lo, hi, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            lo_, hi_ = int(lo, 16), int(hi, 16)
            base = int(dst, 16)
            for k in range(lo_, min(hi_, lo_ + 65535) + 1):
                m[k] = chr(base + (k - lo_)) if len(dst) <= 4 else _utf16(dst)
        for lo, hi, arr in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[(.*?)\]", blk, re.S):
            lo_ = int(lo, 16)
            for off, dst in enumerate(re.findall(rb"<([0-9A-Fa-f]+)>", arr)):
                m[lo_ + off] = _utf16(dst)
    return m


def _utf16(h):
    b = bytes.fromhex(h.decode() if isinstance(h, bytes) else h)
    try:
        return b.decode("utf-16-be")
    except Exception:
        return b.decode("latin-1", "replace")


class Font:
    def __init__(self, pdf, fd):
        self.pdf, self.d = pdf, fd
        self.two_byte = False
        self.map = {}
        sub = str(pdf.res(fd.get("Subtype")) or "")
        tu = pdf.res(fd.get("ToUnicode"))
        if isinstance(tu, Stream):
            self.map = cmap_from_tounicode(pdf.data(tu))
        if sub == "Type0":
            enc = pdf.res(fd.get("Encoding"))
            self.two_byte = True
            if isinstance(enc, Stream):
                pass
        # simple-font Differences
        enc = pdf.res(fd.get("Encoding"))
        if isinstance(enc, dict):
            diffs = pdf.res(enc.get("Differences"))
            if isinstance(diffs, list):
                code = 0
                for it in diffs:
                    it = pdf.res(it)
                    if isinstance(it, (int, float)):
                        code = int(it)
                    else:
                        ch = glyph_to_char(str(it))
                        if ch and code not in self.map:
                            self.map[code] = ch
                        code += 1

    def decode(self, b):
        out = []
        if self.two_byte:
            for i in range(0, len(b) - 1, 2):
                c = (b[i] << 8) | b[i + 1]
                out.append(self.map.get(c, ""))
        else:
            for c in b:
                out.append(self.map.get(c, chr(c) if 32 <= c < 127 or c > 160 else ""))
        return "".join(out)


GLYPH_RE = re.compile(r"^uni([0-9A-Fa-f]{4})$")
AGL = {"space": " ", "period": ".", "comma": ",", "slash": "/", "hyphen": "-", "colon": ":",
       "semicolon": ";", "parenleft": "(", "parenright": ")", "plus": "+", "equal": "=",
       "percent": "%", "numbersign": "#", "asterisk": "*", "quotesingle": "'", "quotedbl": '"',
       "underscore": "_", "degree": "°", "twosuperior": "²", "threesuperior": "³",
       "Euro": "€", "euro": "%s" % "€", "ampersand": "&", "exclam": "!", "question": "?",
       "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
       "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9"}


def glyph_to_char(g):
    if g in AGL:
        return AGL[g]
    m = GLYPH_RE.match(g)
    if m:
        return chr(int(m.group(1), 16))
    if len(g) == 1:
        return g
    return ""


# ---------------------------------------------------------------- text
class TextItem:
    __slots__ = ("text", "x", "y", "size", "font", "dx", "dy")
    def __init__(self, text, x, y, size, font, dx=1.0, dy=0.0):
        self.text, self.x, self.y, self.size, self.font = text, x, y, size, font
        self.dx, self.dy = dx, dy          # unit vector of the writing direction
    def __repr__(self):
        return f"({self.x:.0f},{self.y:.0f},{self.size:.1f}) {self.text!r}"


def mul(a, b):
    return (a[0]*b[0]+a[1]*b[2], a[0]*b[1]+a[1]*b[3],
            a[2]*b[0]+a[3]*b[2], a[2]*b[1]+a[3]*b[3],
            a[4]*b[0]+a[5]*b[2]+b[4], a[4]*b[1]+a[5]*b[3]+b[5])


def page_text_items(pdf, page):
    """Text runs with page-space positions. Follows Form XObjects one level deep."""
    res = pdf.res(page.get("Resources")) or {}
    items = []
    _run(pdf, pdf.content(page), res, (1, 0, 0, 1, 0, 0), items, 0)
    return items


def _fonts(pdf, res):
    fr = pdf.res(res.get("Font")) or {}
    out = {}
    for k, v in fr.items():
        fd = pdf.res(v)
        if isinstance(fd, dict):
            try:
                out[k] = Font(pdf, fd)
            except Exception:
                pass
    return out


def _run(pdf, content, res, base_ctm, items, depth):
    if depth > 6:
        return
    fonts = _fonts(pdf, res)
    xobjs = pdf.res(res.get("XObject")) or {}
    p = Parser(content)
    stack = []
    ctm = base_ctm
    tm = tlm = (1, 0, 0, 1, 0, 0)
    font = None; size = 0; leading = 0; charsp = 0; wordsp = 0; hscale = 1.0
    operands = []
    while True:
        t = p.token()
        if t is None:
            break
        if t[:1].isdigit() or t[:1] in b"+-." or t[:1] in b"(</[":
            p.i -= len(t)
            operands.append(p.obj())
            continue
        op = t.decode("latin-1", "replace")
        try:
            if op == "q":
                stack.append(ctm)
            elif op == "Q":
                ctm = stack.pop() if stack else ctm
            elif op == "cm" and len(operands) >= 6:
                ctm = mul(tuple(float(x) for x in operands[-6:]), ctm)
            elif op == "BT":
                tm = tlm = (1, 0, 0, 1, 0, 0)
            elif op == "Tf" and len(operands) >= 2:
                font = fonts.get(str(operands[-2])); size = float(operands[-1])
            elif op == "TL":
                leading = float(operands[-1])
            elif op == "Tc":
                charsp = float(operands[-1])
            elif op == "Tw":
                wordsp = float(operands[-1])
            elif op == "Tz":
                hscale = float(operands[-1]) / 100.0
            elif op == "Td" and len(operands) >= 2:
                tlm = mul((1, 0, 0, 1, float(operands[-2]), float(operands[-1])), tlm); tm = tlm
            elif op == "TD" and len(operands) >= 2:
                leading = -float(operands[-1])
                tlm = mul((1, 0, 0, 1, float(operands[-2]), float(operands[-1])), tlm); tm = tlm
            elif op == "Tm" and len(operands) >= 6:
                tm = tlm = tuple(float(x) for x in operands[-6:])
            elif op == "T*":
                tlm = mul((1, 0, 0, 1, 0, -leading), tlm); tm = tlm
            elif op in ("Tj", "'", '"', "TJ"):
                if op in ("'", '"'):
                    tlm = mul((1, 0, 0, 1, 0, -leading), tlm); tm = tlm
                arr = operands[-1] if operands else b""
                parts = arr if isinstance(arr, list) else [arr]
                buf = ""
                for el in parts:
                    if isinstance(el, bytes):
                        buf += font.decode(el) if font else el.decode("latin-1", "replace")
                    elif isinstance(el, (int, float)):
                        if el < -180:
                            buf += " "
                m = mul(tm, ctm)
                if buf.strip():
                    scale = (m[0] ** 2 + m[1] ** 2) ** 0.5
                    u = scale or 1
                    items.append(TextItem(buf, m[4], m[5], size * u, font,
                                          m[0] / u, m[1] / u))
                # advance (approximate: assume 0.5 em average width)
                adv = sum(len(e) for e in parts if isinstance(e, bytes)) * 0.5 * size * hscale
                tm = mul((1, 0, 0, 1, adv, 0), tm)
            elif op == "Do" and operands:
                xo = pdf.res(xobjs.get(str(operands[-1])))
                if isinstance(xo, Stream) and str(pdf.res(xo.dict.get("Subtype"))) == "Form":
                    mtx = pdf.res(xo.dict.get("Matrix")) or [1, 0, 0, 1, 0, 0]
                    sub = pdf.res(xo.dict.get("Resources")) or res
                    _run(pdf, pdf.data(xo), sub, mul(tuple(float(x) for x in mtx), ctm), items, depth + 1)
        except Exception:
            pass
        operands = []


def page_lines(pdf, page, tol=2.5):
    """Text runs merged back into lines, honouring the run's writing direction.

    CAD sheets rotate their title blocks and set a label and its value as two
    separate runs on one baseline, sometimes hundreds of points apart. Grouping
    by y (what a naive extractor does) tears those apart on a rotated sheet and
    glues unrelated columns together. Grouping by the coordinate PERPENDICULAR to
    each run's own direction reconstructs the line either way.

    Returns [(text, x, y, size)] in reading order.
    """
    items = [i for i in page_text_items(pdf, page) if i.text.strip()]
    groups = {}
    for it in items:
        vertical = abs(it.dy) > abs(it.dx)
        perp = it.x if vertical else it.y
        groups.setdefault(("V" if vertical else "H", round(perp / tol)), []).append(it)
    # merge buckets that are within tol of each other (a baseline can straddle two)
    merged = {}
    for (orient, bucket), lst in sorted(groups.items()):
        key = (orient, bucket)
        prev = (orient, bucket - 1)
        merged.setdefault(prev if prev in merged else key, []).extend(lst)
    out = []
    for (orient, _), lst in merged.items():
        if orient == "V":
            lst.sort(key=lambda i: i.y * (1 if i.dy > 0 else -1))
        else:
            lst.sort(key=lambda i: i.x * (1 if i.dx >= 0 else -1))
        text = " ".join(i.text.strip() for i in lst)
        text = re.sub(r"\s{2,}", " ", text).strip()
        first = lst[0]
        out.append((text, first.x, first.y, max(i.size for i in lst)))
    out.sort(key=lambda r: (-round(r[2], 1), r[1]))
    return out


def page_text(pdf, page, sep="\n"):
    return sep.join(t for t, _, _, _ in page_lines(pdf, page))


if __name__ == "__main__":
    doc = PDF(sys.argv[1])
    for pi, pg in enumerate(doc.pages()):
        print(f"----- page {pi} media={doc.res(pg.get('MediaBox'))}")
        for it in sorted(page_text_items(doc, pg), key=lambda t: (-round(t.y, 1), t.x)):
            print(it)
