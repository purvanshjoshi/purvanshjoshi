"""Render the profile README as a stack of animated SVG cards.

    python scripts/render_cards.py            # animated cards -> cards/, updates README
    STATIC=1 python scripts/render_cards.py   # final frame only -> cards-static/

Cards are shown through <img>, so they only use what survives there: one
inline <style> with CSS keyframes, SMIL <animate>, and fonts subset with
pyftsubset and embedded as base64 WOFF data URIs. Everything turns off under
prefers-reduced-motion. Both modes write preview.html for a local look.
"""
import base64
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
from html import escape
from pathlib import Path

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
STATIC = os.environ.get("STATIC") == "1"
OUT = ROOT / ("cards-static" if STATIC else "cards")
DATA = ROOT / "data" / "profile.json"
README = ROOT / "README.md"

# Brand, taken from portfolio-gray-one-24.vercel.app
BG = "#0a0a0a"
SURFACE = "#111111"
BORDER = "#222222"
FG = "#ededed"
MUTED = "#8a8a8a"
DIM = "#555555"
ACCENT = "#0690d4"
PALE = "#bdd1e3"

W = 840

PROFILE = {
    "kicker": "HI, I AM",
    "name": "Purvansh Joshi",
    "line": "Cloud-native developer and LLM researcher building open-source ML systems.",
    "tags": ["CLOUD NATIVE", "RL", "LLM RESEARCH", "OPEN SOURCE"],
    "portrait": ROOT / "assets" / "portrait.jpg",  # delete the file to drop it
    "url": "https://portfolio-gray-one-24.vercel.app/",
}

TILES = [
    {"slug": "portfolio", "label": "01 / WEBSITE", "title": "Portfolio",
     "sub": "portfolio-gray-one-24.vercel.app", "url": "https://portfolio-gray-one-24.vercel.app/"},
    {"slug": "linkedin", "label": "02 / NETWORK", "title": "LinkedIn",
     "sub": "in/purvansh-joshi", "url": "https://linkedin.com/in/purvansh-joshi"},
    {"slug": "email", "label": "03 / CONTACT", "title": "Email",
     "sub": "Say hello, I reply fast", "url": "mailto:purvanshjoshi7534011576@gmail.com"},
]

# Page order sets each card's start time so the page plays top to bottom.
START = {"hero": 0.0, "tiles": 0.5, "activity": 1.0, "repos": 1.5, "graph": 2.4}


# ---------------------------------------------------------------- fonts

class Font:
    # Characters a font lacks are swapped for these before falling back to dropping them.
    SUBSTITUTES = {"—": "-", "–": "-", "’": "'", "·": "-"}

    def __init__(self, family, path, css_class):
        self.family = family
        self.path = path
        self.css_class = css_class
        tt = TTFont(str(path))
        self.cmap = tt.getBestCmap()
        self.hmtx = tt["hmtx"]
        self.upem = tt["head"].unitsPerEm

    def supports(self, text):
        return all(ord(c) in self.cmap for c in text)

    def clean(self, text):
        out = []
        for c in text:
            if ord(c) not in self.cmap:
                c = self.SUBSTITUTES.get(c, "")
                if c and ord(c) not in self.cmap:
                    c = ""
            out.append(c)
        return "".join(out)

    def width(self, text, size, spacing=0.0):
        units = sum(self.hmtx[self.cmap[ord(c)]][0] for c in text if ord(c) in self.cmap)
        return units * size / self.upem + spacing * len(text)

    def fit(self, text, size, max_width, spacing=0.0):
        """Largest size <= size at which text fits max_width."""
        while size > 8 and self.width(text, size, spacing) > max_width:
            size -= 0.5
        return size

    def wrap(self, text, size, max_width, max_lines):
        words, lines, line = self.clean(text).split(), [], ""
        for word in words:
            trial = (line + " " + word).strip()
            if self.width(trial, size) <= max_width or not line:
                line = trial
            else:
                lines.append(line)
                line = word
        if line:
            lines.append(line)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            last = lines[-1]
            while last and self.width(last + "...", size) > max_width:
                last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
            lines[-1] = last.rstrip(",.;: ") + "..."
        return lines

    def woff_data_uri(self, chars):
        """Subset to chars with pyftsubset and return a base64 WOFF data URI."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "subset.woff"
            unicodes = ",".join("%04X" % ord(c) for c in sorted(chars | {" "}))
            subprocess.run(
                [sys.executable, "-m", "fontTools.subset", str(self.path),
                 "--unicodes=" + unicodes, "--flavor=woff", "--no-hinting",
                 "--desubroutinize", "--output-file=" + str(out)],
                check=True,
            )
            return "data:font/woff;base64," + base64.b64encode(out.read_bytes()).decode()


SERIF = Font("Soria", ROOT / "assets" / "fonts" / "Soria.ttf", "serif")
SANS = Font("Vercetti", ROOT / "assets" / "fonts" / "Vercetti-Regular.woff", "sans")


def display_font(text):
    """Soria where it has every glyph, otherwise Vercetti (Soria lacks - _ , etc.)."""
    return SERIF if SERIF.supports(text) else SANS


# ---------------------------------------------------------------- cards

ANIM_CSS = """
@keyframes fu{from{opacity:0;transform:translateY(10px)}}
@keyframes fi{from{opacity:0}}
@keyframes grow{from{transform:scaleY(0)}}
@keyframes wipe{from{transform:scaleX(0)}}
@keyframes pop{from{opacity:0;transform:scale(.4)}}
.fu{animation:fu .7s cubic-bezier(.2,.7,.2,1) both}
.fi{animation:fi .9s ease-out both}
.grow{animation:grow .8s cubic-bezier(.2,.7,.2,1) both;transform-box:fill-box;transform-origin:50% 100%}
.wipe{animation:wipe .9s cubic-bezier(.6,0,.2,1) both;transform-box:fill-box;transform-origin:0 50%}
.pop{animation:pop .5s cubic-bezier(.2,.9,.3,1.3) both;transform-box:fill-box;transform-origin:50% 50%}
.still{display:none}
@media (prefers-reduced-motion:reduce){*{animation:none!important}.move{display:none}.still{display:inline}}
"""


class Card:
    def __init__(self, name, width, height, start, title):
        self.name = name
        self.width = width
        self.height = height
        self.start = start
        self.title = title
        self.parts = []
        self.defs = []
        self.chars = {SERIF: set(), SANS: set()}

    def add(self, markup):
        self.parts.append(markup)

    def anim(self, cls, delay):
        """class/style attributes for a CSS animation `delay` seconds into this card."""
        if STATIC:
            return ""
        return ' class="%s" style="animation-delay:%.2fs"' % (cls, self.start + delay)

    def text(self, x, y, s, font, size, fill, anim=None, delay=0.0, anchor="start",
             spacing=0.0, weight=None):
        s = font.clean(s)
        self.chars[font].update(s)
        attrs = ' x="%.1f" y="%.1f" font-size="%.1f" fill="%s"' % (x, y, size, fill)
        if anchor != "start":
            attrs += ' text-anchor="%s"' % anchor
        if spacing:
            attrs += ' letter-spacing="%.1f"' % spacing
        body = '<text class="%s"%s>%s</text>' % (font.css_class, attrs, escape(s))
        return self.wrap(body, anim, delay)

    def wrap(self, markup, anim, delay):
        if not anim or STATIC:
            return markup
        return "<g%s>%s</g>" % (self.anim(anim, delay), markup)

    def smil(self, attr, frm, to, delay, dur):
        """One-shot SMIL animate that holds `frm` until its delay, then eases to `to`."""
        begin = self.start + delay
        total = begin + dur
        return ('<animate attributeName="%s" values="%s;%s;%s" keyTimes="0;%.3f;1" '
                'dur="%.2fs" calcMode="spline" keySplines="0 0 1 1;.2 .7 .2 1" fill="freeze"/>'
                % (attr, frm, frm, to, begin / total, total))

    def motion(self, moving, still):
        """SMIL ignores CSS media queries, so animated markup ships with a still twin
        that reduced-motion swaps in. STATIC=1 emits only the still one."""
        if STATIC:
            return still
        return '<g class="move">%s</g><g class="still">%s</g>' % (moving, still)

    def frame(self):
        return ('<rect x="0.5" y="0.5" width="%d" height="%d" rx="16" fill="%s" stroke="%s"/>'
                % (self.width - 1, self.height - 1, BG, BORDER))

    def render(self):
        faces = []
        for font, chars in self.chars.items():
            if chars:
                faces.append("@font-face{font-family:%s;src:url(%s) format('woff')}"
                             % (font.family, font.woff_data_uri(chars)))
        css = "".join(faces)
        css += ".serif{font-family:Soria,Georgia,serif}.sans{font-family:Vercetti,Helvetica,Arial,sans-serif}"
        if not STATIC:
            css += ANIM_CSS.replace("\n", "")
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" '
            'role="img" aria-label="%s">\n'
            "<!-- Generated by scripts/render_cards.py. Fonts: Soria by Bydani (CC BY-ND 4.0), "
            "Vercetti by Filippos Fragkogiannis and Richard Mandona. -->\n"
            "<title>%s</title>\n<style>%s</style>\n<defs>%s</defs>\n%s\n%s\n</svg>\n"
            % (self.width, self.height, self.width, self.height, escape(self.title),
               escape(self.title), css, "".join(self.defs), self.frame(), "\n".join(self.parts))
        )

    def save(self):
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / (self.name + ".svg")
        path.write_text(self.render())
        return path


# ---------------------------------------------------------------- data

def load_data():
    data = json.loads(DATA.read_text())
    days = [(dt.date.fromisoformat(d["date"]), d["count"]) for d in data["days"]]
    days.sort()
    return data, days


def streaks(days):
    """Current streak (today may still be empty) and longest streak in the window."""
    longest = run = 0
    for _, count in days:
        run = run + 1 if count else 0
        longest = max(longest, run)
    counts = [c for _, c in days]
    if counts and counts[-1] == 0:
        counts = counts[:-1]
    current = 0
    for count in reversed(counts):
        if not count:
            break
        current += 1
    return current, longest


def monthly(days):
    """Contribution totals for the last 12 calendar months, oldest first."""
    last = days[-1][0]
    months = []
    y, m = last.year, last.month
    for _ in range(12):
        months.append((y, m))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    months.reverse()
    totals = {key: 0 for key in months}
    for day, count in days:
        if (day.year, day.month) in totals:
            totals[(day.year, day.month)] += count
    return [(dt.date(y, m, 1), totals[(y, m)]) for y, m in months]


def mix(a, b, t):
    a = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join("%02x" % round(x + (y - x) * t) for x, y in zip(a, b))


def fmt_date(day):
    return "%s %d, %d" % (day.strftime("%b"), day.day, day.year)


# ---------------------------------------------------------------- hero

def hero_card():
    c = Card("hero", W, 260, START["hero"], "%s. %s" % (PROFILE["name"], PROFILE["line"]))
    portrait = PROFILE["portrait"]
    has_portrait = portrait.exists()
    text_w = 580 if has_portrait else W - 96

    c.defs.append('<radialGradient id="glow" cx="80%%" cy="30%%" r="60%%">'
                  '<stop offset="0" stop-color="%s" stop-opacity=".22"/>'
                  '<stop offset="1" stop-color="%s" stop-opacity="0"/></radialGradient>' % (ACCENT, ACCENT))
    c.add('<rect x="1" y="1" width="%d" height="%d" rx="15" fill="url(#glow)"%s/>'
          % (W - 2, c.height - 2, c.anim("fi", 0.0)))

    c.add(c.text(48, 70, PROFILE["kicker"], SANS, 12, ACCENT, "fu", 0.1, spacing=3))
    name_size = SERIF.fit(PROFILE["name"], 68, text_w)
    c.add(c.text(46, 138, PROFILE["name"], SERIF, name_size, FG, "fu", 0.2))

    # Underline draws itself from left to right.
    line_w = SERIF.width(PROFILE["name"], name_size)
    path = 'd="M48 158 H%.1f" stroke="%s" stroke-width="2" stroke-linecap="round" fill="none"' % (48 + line_w, ACCENT)
    c.add(c.motion(
        '<path %s stroke-dasharray="%.1f" stroke-dashoffset="%.1f">%s</path>'
        % (path, line_w, line_w, c.smil("stroke-dashoffset", "%.1f" % line_w, "0", 0.6, 0.9)),
        "<path %s/>" % path))

    for i, line in enumerate(SANS.wrap(PROFILE["line"], 16, text_w, 2)):
        c.add(c.text(48, 194 + i * 22, line, SANS, 16, MUTED, "fu", 0.45 + i * 0.08))

    x = 48
    tag_y = 228 if len(SANS.wrap(PROFILE["line"], 16, text_w, 2)) == 1 else 246
    for i, tag in enumerate(PROFILE["tags"]):
        if i:
            c.add('<circle cx="%.1f" cy="%.1f" r="1.6" fill="%s"%s/>' % (x + 9, tag_y - 4, DIM, c.anim("fi", 0.7 + i * 0.08)))
            x += 18
        c.add(c.text(x, tag_y, tag, SANS, 10.5, DIM, "fi", 0.7 + i * 0.08, spacing=2))
        x += SANS.width(tag, 10.5, 2)

    if has_portrait:
        cx, cy, r = 718, 130, 76
        mime = "image/png" if portrait.suffix == ".png" else "image/jpeg"
        img = base64.b64encode(portrait.read_bytes()).decode()
        c.defs.append('<clipPath id="pc"><circle cx="%d" cy="%d" r="%d"/></clipPath>' % (cx, cy, r))
        c.add('<g%s><image href="data:%s;base64,%s" x="%d" y="%d" width="%d" height="%d" '
              'clip-path="url(#pc)" preserveAspectRatio="xMidYMid slice"/></g>'
              % (c.anim("pop", 0.3), mime, img, cx - r, cy - r, 2 * r, 2 * r))
        ring = 'cx="%d" cy="%d" fill="none" stroke="%s"' % (cx, cy, ACCENT)
        c.add('<circle %s r="%d" stroke-width="1.5" stroke-opacity=".7"%s/>' % (ring, r + 7, c.anim("fi", 0.5)))
        # A slow sonar ping around the portrait, forever.
        begin = c.start + 1.4
        c.add(c.motion(
            '<circle %s r="%d" stroke-width="1" stroke-opacity="0">'
            '<animate attributeName="r" values="%d;%d" dur="3s" begin="%.1fs" repeatCount="indefinite"/>'
            '<animate attributeName="stroke-opacity" values=".6;0" dur="3s" begin="%.1fs" repeatCount="indefinite"/>'
            "</circle>" % (ring, r + 7, r + 7, r + 26, begin, begin),
            ""))
    return c


# ---------------------------------------------------------------- tiles

def tile_cards():
    cards = []
    for i, tile in enumerate(TILES):
        start = START["tiles"] + i * 0.15
        c = Card("tile-" + tile["slug"], 270, 124, start, "%s: %s" % (tile["title"], tile["sub"]))
        c.add('<rect x="22" y="1" width="226" height="2" fill="%s"%s/>' % (ACCENT, c.anim("wipe", 0.0)))
        c.add(c.text(22, 36, tile["label"], SANS, 10, DIM, "fu", 0.1, spacing=2))
        title_font = display_font(tile["title"])
        c.add(c.text(21, 78, tile["title"], title_font, title_font.fit(tile["title"], 32, 190), FG, "fu", 0.2))
        c.add(c.text(22, 104, tile["sub"], SANS, SANS.fit(tile["sub"], 12, 226), MUTED, "fu", 0.3))

        # Arrow in a ring, top right; it slides in along its own diagonal.
        arrow = '<path d="M-4 4 L4 -4 M-2.5 -4 H4 V2.5" stroke="%s" stroke-width="1.6" fill="none" stroke-linecap="round"/>' % ACCENT
        c.add('<circle cx="238" cy="34" r="14" fill="none" stroke="%s"%s/>' % (BORDER, c.anim("pop", 0.15)))
        c.add(c.motion(
            '<g transform="translate(238 34)"><g opacity="0">%s%s'
            '<animateTransform attributeName="transform" type="translate" values="-6 6;-6 6;0 0" '
            'keyTimes="0;%.3f;1" dur="%.2fs" calcMode="spline" keySplines="0 0 1 1;.2 .7 .2 1" fill="freeze"/>'
            "</g></g>" % (arrow, c.smil("opacity", "0", "1", 0.35, 0.6),
                          (start + 0.35) / (start + 0.95), start + 0.95),
            '<g transform="translate(238 34)">%s</g>' % arrow))
        cards.append((c, tile["url"], tile["title"]))
    return cards


# ---------------------------------------------------------------- activity

def activity_card(data, days):
    months = monthly(days)
    current, longest = streaks(days)
    active = sum(1 for _, n in days if n)
    busiest_day, busiest_n = max(days, key=lambda d: (d[1], d[0]))
    total = sum(n for _, n in months)

    c = Card("activity", W, 340, START["activity"],
             "Contributions per month: %d in the last 12 months, current streak %d days" % (total, current))
    c.add(c.text(40, 54, "Contributions", SERIF, 28, FG, "fu", 0.0))
    span = "%s - %s  /  %s in 12 months" % (months[0][0].strftime("%b %Y"), months[-1][0].strftime("%b %Y"), "{:,}".format(total))
    c.add(c.text(40, 78, span.replace(" - ", " – ").replace("  /  ", "  ·  "), SANS, 12.5, MUTED, "fu", 0.08))

    # Bars
    left, right, top, base = 40, 560, 112, 286
    peak = max(n for _, n in months) or 1
    slot = (right - left) / len(months)
    bar_w = slot * 0.56
    for i, (month, n) in enumerate(months):
        h = max(2, (base - top) * n / peak)
        x = left + i * slot + (slot - bar_w) / 2
        delay = 0.25 + i * 0.05
        fill = PALE if n == peak else ACCENT
        c.add('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="3" fill="%s"%s/>'
              % (x, base - h, bar_w, h, fill, c.anim("grow", delay)))
        c.add(c.text(x + bar_w / 2, base - h - 7, "{:,}".format(n), SANS, 10, FG if n == peak else MUTED,
                     "fi", delay + 0.5, anchor="middle"))
        c.add(c.text(x + bar_w / 2, base + 20, month.strftime("%b"), SANS, 10.5, DIM, "fi", delay, anchor="middle"))
    c.add('<rect x="%d" y="%d" width="%d" height="1" fill="%s"%s/>' % (left, base, right - left, BORDER, c.anim("wipe", 0.2)))

    # Dashed monthly-average line draws in after the bars.
    avg = total / len(months)
    ay = base - (base - top) * avg / peak
    line = 'd="M%d %.1f H%d" stroke="%s" stroke-width="1" fill="none"' % (left, ay, right, FG)
    if not STATIC:
        c.defs.append('<clipPath id="avg"><rect x="%d" y="%.1f" width="0" height="6">%s</rect></clipPath>'
                      % (left, ay - 3, c.smil("width", "0", str(right - left), 1.0, 1.0)))
    c.add(c.motion(
        '<path %s stroke-dasharray="3 4" stroke-opacity=".45" clip-path="url(#avg)"/>' % line,
        '<path %s stroke-dasharray="3 4" stroke-opacity=".45"/>' % line))
    c.add(c.text(left, ay - 6, "avg %s / mo" % "{:,}".format(round(avg)), SANS, 9.5, MUTED, "fi", 1.6))

    # Stats column
    c.add('<rect x="600" y="40" width="1" height="260" fill="%s"%s/>' % (BORDER, c.anim("fi", 0.2)))
    stats = [
        ("CURRENT STREAK", "%d days" % current),
        ("LONGEST STREAK", "%d days" % longest),
        ("ACTIVE DAYS", "%d / %d" % (active, len(days))),
        ("BUSIEST DAY", "%s on %s" % ("{:,}".format(busiest_n), fmt_date(busiest_day))),
    ]
    for i, (label, value) in enumerate(stats):
        y = 66 + i * 66
        delay = 0.5 + i * 0.12
        c.add(c.text(632, y, label, SANS, 9.5, DIM, "fu", delay, spacing=2))
        font = display_font(value)
        c.add(c.text(631, y + 30, value, font, font.fit(value, 26, 180), ACCENT if i == 0 else FG, "fu", delay + 0.06))
    return c


# ---------------------------------------------------------------- repos

STAR = "M8 .8l2.2 4.5 5 .7-3.6 3.5.9 5L8 12.1l-4.5 2.4.9-5L.8 6l5-.7z"
FORK = ("M5 3.25a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0zm0 2.12a2.25 2.25 0 1 0-1.5 0v.88c0 .97.78 1.75 "
        "1.75 1.75h5.5a.25.25 0 0 1 .25.25v.88a2.25 2.25 0 1 0 1.5 0v-.88A1.75 1.75 0 0 0 10.75 6.5h-5.5"
        "a.25.25 0 0 1-.25-.25zm6.75.88a.75.75 0 1 1 0-1.5.75.75 0 0 1 0 1.5zM8 12.75a.75.75 0 1 1 0 1.5"
        ".75.75 0 0 1 0-1.5zm-.75-1.63V9.75h1.5v1.37a2.25 2.25 0 1 1-1.5 0z")


def repo_cards(data):
    cards = []
    for i, repo in enumerate(data["repos"]):
        c = Card("repo-%d" % (i + 1), W, 156, START["repos"] + i * 0.2,
                 "%s/%s: %s" % (repo["owner"], repo["name"], repo["description"]))
        # Accent rail on the left edge grows down.
        rail = 'x="0" y="20" width="3" rx="1.5" fill="%s"' % ACCENT
        c.add(c.motion('<rect %s height="0">%s</rect>' % (rail, c.smil("height", "0", "116", 0.0, 0.8)),
                       '<rect %s height="116"/>' % rail))
        c.add(c.text(796, 118, "%02d" % (i + 1), SERIF, 96, "#1a1a1a", "fi", 0.1, anchor="end"))

        c.add(c.text(40, 40, repo["owner"] + " /", SANS, 12, MUTED, "fu", 0.05))
        c.add(c.text(39, 72, repo["name"], SANS, SANS.fit(repo["name"], 26, 640), FG, "fu", 0.12))
        for j, line in enumerate(SANS.wrap(repo["description"], 13.5, 640, 2)):
            c.add(c.text(40, 98 + j * 19, line, SANS, 13.5, MUTED, "fu", 0.2 + j * 0.05))

        x, y = 40, 140
        if repo["language"]:
            c.add('<circle cx="%d" cy="%d" r="5" fill="%s"%s/>' % (x + 5, y - 4, repo["language_color"] or DIM, c.anim("pop", 0.35)))
            c.add(c.text(x + 16, y, repo["language"], SANS, 12, MUTED, "fi", 0.4))
            x += 16 + SANS.width(repo["language"], 12) + 24
        for icon, n, k in ((STAR, repo["stars"], 0), (FORK, repo["forks"], 1)):
            c.add('<g transform="translate(%.1f %d) scale(.8)"><path d="%s" fill="%s"%s/></g>'
                  % (x, y - 11, icon, MUTED, c.anim("pop", 0.45 + k * 0.08)))
            c.add(c.text(x + 18, y, str(n), SANS, 12, MUTED, "fi", 0.5 + k * 0.08))
            x += 18 + SANS.width(str(n), 12) + 24
        cards.append((c, repo["url"], repo["name"]))
    return cards


# ---------------------------------------------------------------- graph

def graph_card(data, days):
    c = Card("graph", W, 220, START["graph"],
             "Contribution graph: %d contributions in the past year" % data["total_contributions"])
    c.add(c.text(40, 46, "Every day, the past year", SERIF, 22, FG, "fu", 0.0))
    total = "{:,} contributions".format(data["total_contributions"])
    c.add(c.text(800, 46, total, SANS, 12.5, MUTED, "fu", 0.05, anchor="end"))

    nonzero = sorted(n for _, n in days if n)
    cuts = [nonzero[int(len(nonzero) * q)] for q in (0.25, 0.5, 0.75)] if nonzero else [1, 2, 3]
    ramp = [SURFACE, mix(SURFACE, ACCENT, 0.3), mix(SURFACE, ACCENT, 0.55), mix(SURFACE, ACCENT, 0.8), ACCENT]

    def level(n):
        return 0 if not n else 1 + sum(n > cut for cut in cuts)

    step, size, gx, gy = 14, 11, 61, 82
    first = days[0][0]
    offset = (first.weekday() + 1) % 7  # Sunday-first rows, like GitHub
    columns, last_month = {}, None
    for idx, (day, n) in enumerate(days):
        col, row = divmod(idx + offset, 7)
        columns.setdefault(col, []).append(
            '<rect x="%d" y="%d" width="%d" height="%d" rx="2.5" fill="%s"/>'
            % (gx + col * step, gy + row * step, size, size, ramp[level(n)]))
        if day.day <= 7 and row == 0 or idx == 0:
            if day.month != last_month and col < 52:
                c.add(c.text(gx + col * step, gy - 10, day.strftime("%b"), SANS, 10, DIM, "fi", 0.1 + col * 0.012))
                last_month = day.month
    for col, cells in sorted(columns.items()):
        c.add("<g%s>%s</g>" % (c.anim("pop", 0.15 + col * 0.012), "".join(cells)))
    for row, label in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        c.add(c.text(gx - 12, gy + row * step + 9, label, SANS, 9.5, DIM, "fi", 0.1, anchor="end"))

    # Ping on today's cell.
    col, row = divmod(len(days) - 1 + offset, 7)
    tx, ty = gx + col * step + size / 2, gy + row * step + size / 2
    begin = c.start + 1.2
    c.add(c.motion(
        '<circle cx="%.1f" cy="%.1f" r="6" fill="none" stroke="%s" stroke-width="1.2" stroke-opacity="0">'
        '<animate attributeName="r" values="6;13" dur="2.4s" begin="%.1fs" repeatCount="indefinite"/>'
        '<animate attributeName="stroke-opacity" values="0;.9;0" keyTimes="0;.1;1" dur="2.4s" begin="%.1fs" repeatCount="indefinite"/>'
        "</circle>" % (tx, ty, PALE, begin, begin),
        ""))

    lx = 800 - 5 * step - SANS.width("More", 10) - 6
    c.add(c.text(lx - 6, 200, "Less", SANS, 10, DIM, "fi", 0.9, anchor="end"))
    for k, colour in enumerate(ramp):
        c.add('<rect x="%d" y="191" width="%d" height="%d" rx="2.5" fill="%s"%s/>'
              % (lx + k * step, size, size, colour, c.anim("pop", 0.9 + k * 0.05)))
    c.add(c.text(lx + 5 * step + 3, 200, "More", SANS, 10, DIM, "fi", 0.9))
    c.add(c.text(40, 200, "Updated %s" % data["fetched_at"][:10], SANS, 10, DIM, "fi", 0.9))
    return c


# ---------------------------------------------------------------- page

def page_html(src_dir, hero, tiles, activity, repos, graph):
    """The README block: one <img> per card, tiles three to a row."""
    def img(card, width, alt):
        return '<img src="%s/%s.svg" width="%s" alt="%s">' % (src_dir, card.name, width, escape(alt))

    lines = ['<a href="%s">%s</a>' % (PROFILE["url"], img(hero, "100%", hero.title)), ""]
    lines += ['<a href="%s">%s</a>' % (url, img(card, "32.5%", title)) for card, url, title in tiles]
    lines += ["", img(activity, "100%", activity.title), ""]
    lines += ['<a href="%s">%s</a>' % (url, img(card, "100%", card.title)) for card, url, _ in repos]
    lines += ["", img(graph, "100%", graph.title)]
    return '<div align="center">\n\n' + "\n".join(lines) + "\n\n</div>"


def update_readme(block):
    start, end = "<!-- cards:start -->", "<!-- cards:end -->"
    text = README.read_text()
    if start not in text or end not in text:
        sys.exit("README.md needs %s and %s markers" % (start, end))
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    README.write_text(head + start + "\n" + block + "\n" + end + tail)


def main():
    data, days = load_data()
    hero = hero_card()
    tiles = tile_cards()
    activity = activity_card(data, days)
    repos = repo_cards(data)
    graph = graph_card(data, days)
    for card in [hero, activity, graph] + [t[0] for t in tiles] + [r[0] for r in repos]:
        path = card.save()
        print("%-28s %6.1f KB" % (path.relative_to(ROOT), path.stat().st_size / 1024))

    block = page_html(OUT.name, hero, tiles, activity, repos, graph)
    if not STATIC:
        update_readme(block)
    (ROOT / "preview.html").write_text(
        "<!doctype html><meta charset=utf-8><title>Profile preview</title>"
        "<style>body{background:#0d1117;margin:0;padding:32px 16px}"
        "main{max-width:830px;margin:auto}img{max-width:100%%}</style><main>%s</main>" % block)


if __name__ == "__main__":
    main()
