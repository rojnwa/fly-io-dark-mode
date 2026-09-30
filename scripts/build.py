#!/usr/bin/env python3
"""Build fly-io-dark-mode.user.css from the Fly.io dashboard's own stylesheet.

The dashboard ships one Tailwind 3 bundle (/phx/assets/app-<hash>.css). This
script downloads it, re-emits every rule that sets a colour-related property
(same selectors, same order, same media queries) with the colour remapped for
a dark UI, layers hand-tuned component patches on top, and appends a few
additions the site never styles. Keeping the cascade order identical is what
makes hover/focus/responsive variants behave exactly like the original.

Usage:
    python scripts/build.py                  # fetch the live CSS from fly.io
    python scripts/build.py --css app.css    # use a local file or another URL

Standard library only; Python 3.9+.
"""
from __future__ import annotations

import argparse
import colorsys
import math
import re
import sys
import urllib.request
from pathlib import Path

VERSION = "1.2.1"
REPO = "rojnwa/fly-io-dark-mode"
OUT_NAME = "fly-io-dark-mode.user.css"
SIGN_IN_URL = "https://fly.io/app/sign-in"
URL_MATCH = r'regexp("https://fly\\.io/(dashboard|apps|app|user|organizations|tokens|oauth)([/?#].*)?")'
USER_AGENT = "Mozilla/5.0 (fly-io-dark-mode build script; +https://github.com/" + REPO + ")"

# --------------------------------------------------------------------------
# Colour math (sRGB <-> OKLCH)
# --------------------------------------------------------------------------

def srgb_to_lin(c: float) -> float:
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def lin_to_srgb(c: float) -> float:
    v = 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055
    return v * 255


def rgb_to_oklch(r, g, b):
    r, g, b = map(srgb_to_lin, (r, g, b))
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l, m, s = [x ** (1 / 3) if x >= 0 else -((-x) ** (1 / 3)) for x in (l, m, s)]
    L = 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s
    a = 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s
    bb = 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s
    return L, math.hypot(a, bb), math.degrees(math.atan2(bb, a)) % 360


def _oklch_to_lin(L, C, h):
    a = C * math.cos(math.radians(h))
    b = C * math.sin(math.radians(h))
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
            -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
            -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)


def _in_gamut(rgb) -> bool:
    return all(-1e-4 <= x <= 1 + 1e-4 for x in rgb)


def oklch_to_rgb(L, C, h):
    """OKLCH -> sRGB ints, reducing chroma until the colour fits the gamut."""
    rgb = _oklch_to_lin(L, C, h)
    if not _in_gamut(rgb):
        lo, hi = 0.0, C
        for _ in range(30):
            mid = (lo + hi) / 2
            if _in_gamut(_oklch_to_lin(L, mid, h)):
                lo = mid
            else:
                hi = mid
        rgb = _oklch_to_lin(L, lo, h)
    return tuple(max(0, min(255, round(lin_to_srgb(max(0, min(1, x)))))) for x in rgb)


def hsl_sat(r, g, b) -> float:
    mx, mn = max(r, g, b) / 255, min(r, g, b) / 255
    if mx == mn:
        return 0.0
    return (mx - mn) / (1 - abs(mx + mn - 1))


def interp(x, pts):
    pts = sorted(pts)
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            return y0 + (x - x0) / (x1 - x0) * (y1 - y0) if x1 != x0 else y0


def mix(c1, c2, a):
    return tuple(round(x * (1 - a) + y * a) for x, y in zip(c1, c2))


def hexs(c) -> str:
    return "#%02x%02x%02x" % tuple(c[:3])


# --------------------------------------------------------------------------
# Palette and colour transforms
# --------------------------------------------------------------------------
NEUTRAL_H = 285                      # Fly's purple-grey hue, used for all neutrals
SURFACE = oklch_to_rgb(.200, .016, NEUTRAL_H)    # white  -> page / cards
CANVAS = oklch_to_rgb(.165, .014, NEUTRAL_H)     # dashboard backdrop
SUNKEN = oklch_to_rgb(.172, .014, NEUTRAL_H)     # inputs, code
OVERLAY = oklch_to_rgb(.270, .020, NEUTRAL_H)    # popovers, tooltips
WHITE_INK = (235, 232, 255)                      # base for translucent borders/overlays

BG_LIGHT = [(1.0, .200), (.982, .222), (.962, .245), (.92, .275), (.86, .31), (.75, .355), (.6, .40)]
BG_DARK = [(0, .12), (.194, .155), (.26, .2), (.35, .30)]
TXT = [(0, .95), (.2, .93), (.27, .905), (.35, .86), (.43, .80), (.54, .72), (.69, .625), (.72, .61)]
BORDER_N = [(.6, .20), (.75, .15), (.86, .115), (.92, .09), (.962, .075), (.982, .06), (1.0, .05)]
BORDER_C = [(.6, .6), (.8, .45), (.87, .36), (.93, .28), (.97, .22), (1.0, .2)]
TINT_A = [(.6, .45), (.8, .34), (.87, .26), (.93, .18), (.962, .13), (.985, .09), (1.0, .08)]

# Every transform takes (r, g, b, alpha) and returns the same shape. alpha is a
# float, or a string such as "var(--tw-bg-opacity)" which is passed through.


def _alpha(a) -> float:
    return a if isinstance(a, float) else 1.0


def hue_color(h, L=.68, C=.15):
    return oklch_to_rgb(L, C, h)


def is_chromatic(S, C) -> bool:
    return S >= .6 and C > .012


def t_text(r, g, b, a):
    """Dark ink -> light ink; light ink (meant for dark islands) stays."""
    L, C, h = rgb_to_oklch(r, g, b)
    if L > .72:
        return (r, g, b, a)
    Lo = interp(L, TXT)
    if C > .08:                                  # coloured text: keep hue, lift for contrast
        Lo = max(Lo, .74)
        Co = min(C * .75, .17 if Lo < .8 else .08 if Lo < .87 else .035)
        hh = h
    else:
        Co, hh = min(C * .5, .022), NEUTRAL_H
    return (*oklch_to_rgb(Lo, Co, hh), a)


def t_bg(r, g, b, a):
    L, C, h = rgb_to_oklch(r, g, b)
    S, af = hsl_sat(r, g, b), _alpha(a)
    if af == 0:
        return (r, g, b, a)
    if L >= .6:
        chromatic = is_chromatic(S, C)
        if chromatic and C >= .1 and L <= .88:   # vivid 300/400 signal colours: keep
            return (r, g, b, a)
        if not chromatic:
            if af < .4:                          # light glass meant for dark islands
                return (r, g, b, a)
            return (*oklch_to_rgb(interp(L, BG_LIGHT), .016 + min(C, .05) * .3, NEUTRAL_H), a)
        ta, hc = interp(L, TINT_A), hue_color(h)  # pastel tint -> dark glow of the same hue
        if isinstance(a, str) or af >= .999:
            return (*mix(SURFACE, hc, ta), a)
        return (*hc, round(ta * min(1, af * 1.4), 3))
    if af < .4:                                  # dark wash on light -> light wash on dark
        if C < .06:
            return (*WHITE_INK, round(max(.045, min(.16, af * 1.1)), 3))
        return (*hue_color(h, .72, .14), round(max(.05, min(.3, af * .8)), 3))
    if L <= .35:                                 # dark islands stay dark (slightly deeper)
        Lo = interp(L, BG_DARK)
        if C > .06:
            return (*oklch_to_rgb(Lo, C * .45, h), a)
        return (*oklch_to_rgb(Lo, min(C, .03), NEUTRAL_H), a)
    return (r, g, b, a)


def t_border(r, g, b, a):
    L, C, h = rgb_to_oklch(r, g, b)
    S, af = hsl_sat(r, g, b), _alpha(a)
    if af == 0:
        return (r, g, b, a)
    if L >= .6:
        chromatic = is_chromatic(S, C)
        if not chromatic and af < .5:            # translucent white on dark islands
            return (r, g, b, a)
        if L > .995 and C < .005:                # solid white = "cut-out" ring
            return (*SURFACE, a)
        if not chromatic:
            return (*WHITE_INK, round(interp(L, BORDER_N) * af, 3))
        return (*hue_color(h, .7, .14), round(interp(L, BORDER_C) * min(1, af * 1.2), 3))
    if af < .5:
        if C < .06:
            return (*WHITE_INK, round(max(.06, min(.3, af * 1.1)), 3))
        return (*t_text(r, g, b, 1.0)[:3], round(min(.6, af * 1.6 + .04), 3))
    if L < .2 and C < .06:
        return (*t_text(r, g, b, 1.0)[:3], a)
    return (r, g, b, a)


def t_shadow(r, g, b, a):
    L, C, h = rgb_to_oklch(r, g, b)
    af = _alpha(a)
    if af == 0:
        return (r, g, b, a)
    if L >= .6:
        return t_border(r, g, b, a)
    if C > .1 and L > .35 and af >= .15:         # deliberate coloured glow
        return (r, g, b, round(min(.6, af * 1.3), 3) if isinstance(a, float) else a)
    return (0, 0, 0, round(min(.6, af * 2.5 + .12), 3))


# --------------------------------------------------------------------------
# CSS value rewriting
# --------------------------------------------------------------------------
COLOR_TOKEN = re.compile(r"""
    (?P<fn>rgba?|hsla?)\((?P<args>[^()]*(?:\([^()]*\)[^()]*)*)\)
  | \#(?P<hex>[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b
  | (?<![\w-])(?P<named>white|black)(?![\w-])
""", re.X)
NAMED = {"white": (255, 255, 255), "black": (0, 0, 0)}


def _num(x: str) -> float:
    x = x.strip()
    return float(x[:-1]) / 100 if x.endswith("%") else float(x)


def parse_color(m):
    if m.group("named"):
        return (*NAMED[m.group("named")], 1.0)
    if m.group("hex"):
        hx = m.group("hex")
        if len(hx) in (3, 4):
            hx = "".join(c * 2 for c in hx)
        a = int(hx[6:8], 16) / 255 if len(hx) == 8 else 1.0
        return (int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16), round(a, 3))
    fn, args = m.group("fn"), m.group("args").strip()
    if "/" in args:
        main, alpha = args.split("/", 1)
        alpha = alpha.strip()
        parts = main.replace(",", " ").split()
    else:
        parts = [p for p in re.split(r"[\s,]+", args) if p]
        alpha = parts[3] if len(parts) > 3 else "1"
        parts = parts[:3]
    if len(parts) != 3 or any("var(" in p for p in parts):
        return None
    try:
        a = alpha if ("var(" in alpha or "calc" in alpha) else _num(alpha)
    except ValueError:
        return None
    if fn.startswith("rgb"):
        r, g, b = [_num(p) * 255 if p.endswith("%") else float(p) for p in parts]
    else:
        rr, gg, bb = colorsys.hls_to_rgb(float(parts[0].replace("deg", "")) / 360, _num(parts[2]), _num(parts[1]))
        r, g, b = rr * 255, gg * 255, bb * 255
    return (round(r), round(g), round(b), a)


def fmt(r, g, b, a) -> str:
    if isinstance(a, str):
        return f"rgb({r} {g} {b} / {a})"
    if a >= .999:
        return f"rgb({r} {g} {b})"
    return f"rgb({r} {g} {b} / {round(a, 3):g})"


def rewrite_value(val: str, fn):
    changed = False

    def rep(m):
        nonlocal changed
        c = parse_color(m)
        if c is None:
            return m.group(0)
        out = fn(*c)
        if tuple(out) == tuple(c):
            return m.group(0)
        changed = True
        return fmt(*out)

    parts = re.split(r"(url\([^)]*\))", val)       # never touch url(...) contents
    return "".join(p if p.startswith("url(") else COLOR_TOKEN.sub(rep, p) for p in parts), changed


def split_top(v: str, sep=","):
    out, depth, start = [], 0, 0
    for i, ch in enumerate(v):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == sep and depth == 0:
            out.append(v[start:i])
            start = i + 1
    out.append(v[start:])
    return out


RING_SEGMENT = re.compile(r"^\s*(inset\s+)?0(px)?\s+0(px)?\s+0(px)?\s+[\d.]+(px|rem)?\s")


def rewrite_shadow(val: str):
    """box-shadow lists: `0 0 0 Npx` rings are borders, the rest are shadows."""
    changed, out = False, []
    for seg in split_top(val):
        new, ch = rewrite_value(seg, t_border if RING_SEGMENT.match(seg) else t_shadow)
        changed |= ch
        out.append(new)
    return ",".join(out), changed


PROPS_BG = {"background-color", "background", "background-image", "--tw-gradient-from", "--tw-gradient-to",
            "--tw-gradient-via", "--tw-gradient-stops", "--tw-ring-offset-color"}
PROPS_TEXT = {"color", "fill", "stroke", "caret-color", "text-decoration-color", "-webkit-text-fill-color",
              "column-rule-color"}
PROPS_BORDER = {"border-color", "border", "border-top", "border-right", "border-bottom", "border-left",
                "border-top-color", "border-right-color", "border-bottom-color", "border-left-color",
                "outline-color", "outline", "--tw-ring-color"}
PROPS_SHADOW_LIST = {"box-shadow", "--tw-shadow", "--tw-shadow-colored", "--tw-ring-shadow", "--tw-ring-offset-shadow"}
PROPS_SHADOW = {"--tw-shadow-color", "filter", "--tw-drop-shadow", "text-shadow"}


def transform_for(prop: str):
    p = prop.lower()
    if p in PROPS_BG:
        return lambda v: rewrite_value(v, t_bg)
    if p in PROPS_TEXT:
        return lambda v: rewrite_value(v, t_text)
    if p in PROPS_BORDER:
        return lambda v: rewrite_value(v, t_border)
    if p in PROPS_SHADOW_LIST:
        return rewrite_shadow
    if p in PROPS_SHADOW:
        return lambda v: rewrite_value(v, t_shadow)
    return None


# --------------------------------------------------------------------------
# CSS parsing
# --------------------------------------------------------------------------
GROUPING_AT_RULES = ("@media", "@supports", "@layer", "@container")
SKIPPED_AT_RULES = ("@keyframes", "@-webkit-keyframes", "@font-face", "@page")


def parse_rules(css: str):
    """Flat list of (media_stack, selector, body) in source order."""
    out, stack, i, n, start = [], [], 0, len(css), 0
    while i < n:
        if css.startswith("/*", i):
            i = css.find("*/", i + 2) + 2
            start = i
            continue
        ch = css[i]
        if ch == "{":
            prelude = css[start:i].strip()
            if prelude.startswith(GROUPING_AT_RULES):
                stack.append(prelude)
                i += 1
                start = i
                continue
            if prelude.startswith(SKIPPED_AT_RULES):
                depth, j = 1, i + 1
                while depth:
                    depth += {"{": 1, "}": -1}.get(css[j], 0)
                    j += 1
                i = start = j
                continue
            j = css.find("}", i)
            out.append((tuple(stack), prelude, css[i + 1:j]))
            i = start = j + 1
            continue
        if ch == "}":
            if stack:
                stack.pop()
            i += 1
            start = i
            continue
        i += 1
    return out


def split_decls(body: str):
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    out, depth, quote, start = [], 0, None, 0
    for i, ch in enumerate(body):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == ";" and depth == 0:
            out.append(body[start:i])
            start = i + 1
    out.append(body[start:])
    decls = []
    for d in out:
        if ":" in d:
            p, v = d.split(":", 1)
            if p.strip() and v.strip():
                decls.append((p.strip(), v.strip()))
    return decls


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def key(s: str) -> str:
    return re.sub(r"\s*,\s*", ",", norm(s))


# Marketing / docs-only selectors: never on dashboard URLs, skip them.
EXCLUDED = re.compile(r"^\s*(\.docs|\.post|\.sp-|\.sprite-preview|\.DocSearch|\.prose|\.phoenix-|\.auth-art|\.youtube"
                      r"|:is\(\.docs-nav|\.docs-nav|\.page-nav|\.api-|\.json-table|\.checklist|\[toggle|\.index-page)")
VENDOR_PSEUDO = re.compile(r"::?-(moz|webkit|ms)-")
RELATIVE_URL = re.compile(r"""url\(\s*["']?(?!data:|https?:|/)""", re.I)


def keep_selector(sel: str) -> str:
    parts = [s.strip() for s in re.split(r",(?![^()]*\))", sel)]
    return ", ".join(s for s in parts if s and not EXCLUDED.match(s))


# --------------------------------------------------------------------------
# Hand-tuned component patches. Keyed by the original selector (whitespace
# after commas removed). Declarations replace the auto-mapped ones for that
# rule at its original cascade position; an empty body keeps the original.
# --------------------------------------------------------------------------
PATCH_SRC = r"""
@@ [type='text'],input:where(:not([type])),[type='email'],[type='url'],[type='password'],[type='number'],[type='date'],[type='datetime-local'],[type='month'],[type='search'],[type='tel'],[type='time'],[type='week'],[multiple],textarea,select
background-color: {sunken}; border-color: rgb(235 232 255 / .17);
@@ [type='text']:focus,input:where(:not([type])):focus,[type='email']:focus,[type='url']:focus,[type='password']:focus,[type='number']:focus,[type='date']:focus,[type='datetime-local']:focus,[type='month']:focus,[type='search']:focus,[type='tel']:focus,[type='time']:focus,[type='week']:focus,[multiple]:focus,textarea:focus,select:focus
--tw-ring-offset-color: {surface}; --tw-ring-color: rgb(139 92 246 / .45); border-color: #8b5cf6;
@@ input::placeholder,textarea::placeholder
color: #7a7a8c;
@@ [type='checkbox'],[type='radio']
color: #8b5cf6; background-color: {sunken}; border-color: rgb(235 232 255 / .26);
@@ [type='checkbox']:focus,[type='radio']:focus
--tw-ring-offset-color: {surface}; --tw-ring-color: rgb(139 92 246 / .5);
@@ .badge-danger,.badge-warning,.badge-success,.badge-inactive
--tw-shadow-color: rgb(0 0 0 / .25);
@@ .badge-danger[badge-count]::before,.badge-warning[badge-count]::before,.badge-success[badge-count]::before,.badge-inactive[badge-count]::before
color: {surface};
@@ .badge-danger
--text-color: #fb7185; --tw-ring-color: rgb(251 113 133 / .3); --tw-gradient-from: rgb(244 63 94 / .16); --tw-gradient-to: rgb(244 63 94 / .07);
@@ .badge-warning
--text-color: #fbbf24; --tw-ring-color: rgb(251 191 36 / .3); --tw-gradient-from: rgb(245 158 11 / .16); --tw-gradient-to: rgb(245 158 11 / .06);
@@ .badge-success
--text-color: #34d399; --tw-ring-color: rgb(52 211 153 / .28); --tw-gradient-from: rgb(16 185 129 / .16); --tw-gradient-to: rgb(16 185 129 / .06);
@@ .badge-inactive
--text-color: #9d9db2; --tw-ring-color: rgb(235 232 255 / .14); --tw-gradient-from: rgb(235 232 255 / .07); --tw-gradient-to: rgb(235 232 255 / .025);
@@ :where(.bubble,.bubble-tl,.bubble-t,.bubble-tr,.bubble-lt,.bubble-rt,.bubble-l,.bubble-r,.bubble-lb,.bubble-rb,.bubble-bl,.bubble-b,.bubble-br)
background-color: {overlay}; color: {text}; filter: drop-shadow(0 6px 14px rgb(0 0 0 / .45)) drop-shadow(0 0 1px rgb(235 232 255 / .35));
@@ :where(.tail,[class*=tail-])::after
color: {overlay}; background-image: {arrow};
@@ .btn-xs,.btn-sm,.btn,.btn-lg,.btn-xl,.btn-2xl
--btn-inner-shadow: inset 0 1px 0 rgb(255 255 255 / .04); --btn-inner-shadow-active: inset 0 1px 0 rgb(255 255 255 / .06); --btn-text-color: {text}; --btn-text-color-active: #c4b5fd; --btn-bg-color: {raised2}; --btn-bg-color-active: {overlay}; --btn-border-color: rgb(235 232 255 / .12); --btn-border-color-active: rgb(167 139 250 / .45); --btn-ring-color: rgb(139 92 246 / .28);
@@ .btn-shadow
--btn-shadow: 0 4px 10px -4px rgb(0 0 0 / .55), 0 2px 4px -2px rgb(0 0 0 / .4); --btn-shadow-active: 0 8px 16px -6px rgb(0 0 0 / .6), 0 2px 4px -2px rgb(0 0 0 / .45);
@@ .btn-danger
--btn-bg-color: rgb(244 63 94 / .12); --btn-bg-color-active: rgb(244 63 94 / .2); --btn-border-color: rgb(251 113 133 / .35); --btn-border-color-active: rgb(251 113 133 / .6); --btn-inner-shadow: inset 0 1px 0 rgb(255 255 255 / .03); --btn-inner-shadow-active: inset 0 0 8px rgb(244 63 94 / .2); --btn-ring-color: rgb(244 63 94 / .3); --btn-text-color: #fda4af; --btn-text-color-active: #ffe4e6;
@@ .btn-warning
--btn-bg-color: rgb(245 158 11 / .12); --btn-bg-color-active: rgb(245 158 11 / .2); --btn-border-color: rgb(251 191 36 / .35); --btn-border-color-active: rgb(251 191 36 / .6); --btn-inner-shadow: inset 0 1px 0 rgb(255 255 255 / .03); --btn-inner-shadow-active: inset 0 0 8px rgb(245 158 11 / .2); --btn-ring-color: rgb(245 158 11 / .3); --btn-text-color: #fcd34d; --btn-text-color-active: #fef3c7;
@@ .btn-primary
--btn-bg-color: #7c3aed; --btn-bg-color-active: #8b5cf6; --btn-border-color: rgb(167 139 250 / .35); --btn-border-color-active: rgb(196 181 253 / .55); --btn-inner-shadow: inset 0 1px 0 rgb(255 255 255 / .14), inset 0 -2px 6px rgb(91 33 182 / .7); --btn-inner-shadow-active: inset 0 1px 0 rgb(255 255 255 / .18), inset 0 0 8px rgb(91 33 182 / .5); --btn-ring-color: rgb(139 92 246 / .45); --btn-text-color: white; --btn-text-color-active: white;
@@ .btn-success
--btn-bg-color: #16a34a; --btn-bg-color-active: #22c55e; --btn-border-color: rgb(74 222 128 / .3); --btn-border-color-active: rgb(134 239 172 / .5); --btn-inner-shadow: inset 0 1px 0 rgb(255 255 255 / .12), inset 0 -2px 6px rgb(21 128 61 / .7); --btn-inner-shadow-active: inset 0 1px 0 rgb(255 255 255 / .16); --btn-ring-color: rgb(34 197 94 / .35); --btn-text-color: white; --btn-text-color-active: white;
@@ .btn-secondary
--btn-bg-color: rgb(139 92 246 / .14); --btn-bg-color-active: rgb(139 92 246 / .24); --btn-border-color: rgb(167 139 250 / .3); --btn-border-color-active: rgb(167 139 250 / .55); --btn-inner-shadow: inset 0 1px 0 rgb(255 255 255 / .04); --btn-inner-shadow-active: inset 0 0 8px rgb(139 92 246 / .25); --btn-ring-color: rgb(139 92 246 / .3); --btn-text-color: #c4b5fd; --btn-text-color-active: #ede9fe;
@@ .btn-translucent
@@ .btn-purple
@@ .btn-border-light
@@ .btn-border-dark
--btn-inner-shadow: inset 0 0 0 1px rgb(167 139 250 / .25); --btn-inner-shadow-active: inset 0 0 0 1px rgb(167 139 250 / .35);
@@ .btn-disabled
--btn-bg-color: {raised}; --btn-bg-color-active: {raised}; --btn-border-color: rgb(235 232 255 / .08); --btn-border-color-active: rgb(235 232 255 / .08); --btn-inner-shadow: 0 0 transparent; --btn-inner-shadow-active: 0 0 transparent; --btn-text-color: #6e6e80; --btn-text-color-active: #6e6e80;
@@ .btn-link
color: {accent}; text-decoration-color: rgb(175 151 255 / .35);
@@ .btn-link:not(:disabled):hover,.btn-link:not(:disabled):focus,.btn-link:not(:disabled):focus-within
color: #d4c8ff; text-decoration-color: rgb(212 200 255 / .75);
@@ .card,.card-info,.card-error,.card-warning,.card-success
--tw-shadow-color: rgb(0 0 0 / .35);
@@ .card
--card-border-color: rgb(235 232 255 / .085); background-color: rgb({surface_rgb} / .88);
@@ .card-title
color: {text};
@@ .card-info
--card-border-color: rgb(96 165 250 / .25); background-image: linear-gradient(to bottom right, rgb(56 189 248 / .10), rgb(129 140 248 / .13)); color: rgb(191 219 254 / .78);
@@ .card-info .card-title,.card-info strong,.card-info code,.card-info a
color: #c7dcfe;
@@ .card-info .btn-inline
text-decoration-color: rgb(191 219 254 / .35);
@@ .card-info .btn-inline:hover,.card-info .btn-inline:focus
text-decoration-color: rgb(191 219 254 / .9);
@@ .card-info code
background-color: rgb(96 165 250 / .15);
@@ .card-error
--card-border-color: rgb(251 113 133 / .28); background-image: linear-gradient(to bottom right, rgb(244 63 94 / .13), rgb(251 113 133 / .07)); color: rgb(254 205 211 / .78);
@@ .card-error .card-title,.card-error strong,.card-error code,.card-error a
color: #fecdd3;
@@ .card-error .btn-inline
text-decoration-color: rgb(254 205 211 / .35);
@@ .card-error .btn-inline:hover,.card-error .btn-inline:focus
text-decoration-color: #fecdd3;
@@ .card-error code
background-color: rgb(244 63 94 / .16);
@@ .card-warning
--card-border-color: rgb(251 191 36 / .28); background-image: linear-gradient(to bottom right, rgb(245 158 11 / .13), rgb(251 146 60 / .07)); color: rgb(253 230 138 / .78);
@@ .card-warning .card-title,.card-warning strong,.card-warning code,.card-warning a
color: #fde68a;
@@ .card-warning .btn-inline
text-decoration-color: rgb(253 230 138 / .35);
@@ .card-warning .btn-inline:hover,.card-warning .btn-inline:focus
text-decoration-color: #fde68a;
@@ .card-warning code
background-color: rgb(245 158 11 / .16);
@@ .card-success
--card-border-color: rgb(52 211 153 / .28); background-image: linear-gradient(to bottom right, rgb(16 185 129 / .13), rgb(52 211 153 / .06)); color: rgb(167 243 208 / .78);
@@ .card-success .card-title,.card-success strong,.card-success code,.card-success a
color: #a7f3d0;
@@ .card-success .btn-inline
text-decoration-color: rgb(167 243 208 / .35);
@@ .card-success .btn-inline:hover,.card-success .btn-inline:focus
text-decoration-color: #a7f3d0;
@@ .card-success code
background-color: rgb(16 185 129 / .16);
@@ .input-text,.input-select
background-color: rgb({sunken_rgb} / var(--tw-bg-opacity));
@@ .input-text,.input-select,.input-checkbox,.input-radio
border-color: rgb(235 232 255 / .17); --tw-shadow: 0 1px 2px 0 rgb(0 0 0 / .3); --tw-shadow-color: rgb(0 0 0 / .3);
@@ .input-text:focus,.input-select:focus,.input-checkbox:focus,.input-radio:focus
border-color: rgb(167 139 250 / .75); --tw-ring-color: rgb(139 92 246 / .25);
@@ .input-checkbox,.input-radio
color: #8b5cf6;
@@ .input-text::-moz-placeholder
color: rgb(235 232 255 / .4);
@@ .input-text::placeholder
color: rgb(235 232 255 / .4);
@@ .input-radio:checked
border-color: #8b5cf6;
@@ .input-radio:hover
border-color: rgb(196 181 253 / .6);
@@ .loader.overlay
background: rgb({surface_rgb} / .82);
@@ [data-tooltip] code
background-color: rgb(0 0 0 / .3);
@@ [data-tooltip-content]
background-color: {overlay}; color: {text}; box-shadow: 0 0 0 1px rgb(235 232 255 / .1), 0 10px 24px -6px rgb(0 0 0 / .6);
@@ [data-tooltip-content]:before
background: {arrow} 0 0/100% auto no-repeat;
@@ .phx-modal-content
background-color: {raised}; border: 1px solid rgb(235 232 255 / .12);
@@ .phx-modal-close
color: {faint};
@@ .phx-modal-close:hover,.phx-modal-close:focus
color: {text};
@@ .hljs
color: #c9d1d9; background: {sunken};
@@ .hljs-doctag,.hljs-keyword,.hljs-meta .hljs-keyword,.hljs-template-tag,.hljs-template-variable,.hljs-type,.hljs-variable.language_
color: #ff7b72;
@@ .hljs-title,.hljs-title.class_,.hljs-title.class_.inherited__,.hljs-title.function_
color: #d2a8ff;
@@ .hljs-regexp,.hljs-string,.hljs-meta .hljs-string
color: #a5d6ff;
@@ .hljs-built_in,.hljs-symbol
color: #ffa657;
@@ .hljs-comment,.hljs-code,.hljs-formula
color: #8b949e;
@@ .hljs-name,.hljs-quote,.hljs-selector-tag,.hljs-selector-pseudo
color: #7ee787;
@@ .hljs-subst
color: #c9d1d9;
@@ .hljs-section
color: #79c0ff;
@@ .hljs-bullet
color: #f2cc60;
@@ .hljs-emphasis
color: #c9d1d9;
@@ .hljs-strong
color: #c9d1d9;
@@ .hljs-addition
color: #aff5b4; background-color: rgb(46 160 67 / .15);
@@ .hljs-deletion
color: #ffdcd7; background-color: rgb(248 81 73 / .15);
@@ pre code.hljs
background-color: {sunken} !important; border: 1px solid rgb(235 232 255 / .1) !important;
@@ pre code,.prose pre code
background-color: {sunken} !important; border: 1px solid rgb(235 232 255 / .1) !important;
@@ .sql-editor-autocomplete
background: {overlay}; border: 1px solid rgb(235 232 255 / .1); box-shadow: 0 12px 28px -6px rgb(0 0 0 / .6), 0 4px 8px -4px rgb(0 0 0 / .5);
@@ .sql-editor-autocomplete .sql-ac-item.active
background: rgb(139 92 246 / .22);
@@ .sql-history-item:hover,.sql-history-item:focus-visible
background: rgb(139 92 246 / .12);
"""

# Things the site never styles, appended after the re-mapped rules.
ADDITIONS = """
/* ---- Base ------------------------------------------------------------ */
:root {{
  color-scheme: dark;
  scrollbar-color: rgb(235 232 255 / .18) transparent;
}}
html, body {{
  background-color: {surface};
}}
body {{
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}}
::selection {{
  background-color: rgb(139 92 246 / .45);
  color: #fff;
}}

/* ---- Dashboard backdrop ------------------------------------------------
 * <body class="bg-custom" style="--bg: url(app-shapes.webp)"> paints a pastel
 * photo over the whole page once it loads. Swap it for dark glows in the
 * same spots. */
body.bg-custom {{
  background-color: {canvas};
  background-image:
    radial-gradient(38% 34% at 14% 18%, rgb(96 165 250 / .07), transparent 72%),
    radial-gradient(30% 22% at 55% 8%, rgb(244 114 182 / .045), transparent 72%),
    radial-gradient(34% 40% at 86% 28%, rgb(167 139 250 / .085), transparent 72%),
    radial-gradient(32% 34% at 12% 64%, rgb(192 132 252 / .06), transparent 72%),
    radial-gradient(40% 34% at 80% 88%, rgb(96 165 250 / .065), transparent 72%);
}}
html:has(> body.bg-custom) {{
  background-color: {canvas};
}}

/* ---- Browser autofill (kills the yellow/blue fill) --------------------- */
input:-webkit-autofill,
input:-webkit-autofill:hover,
input:-webkit-autofill:focus,
textarea:-webkit-autofill,
select:-webkit-autofill {{
  -webkit-text-fill-color: {text};
  -webkit-box-shadow: 0 0 0 1000px {sunken} inset;
  caret-color: {text};
  transition: background-color 99999s ease-out 0s;
}}
input:autofill {{
  filter: none;
}}

/* ---- Hard-coded black text ---------------------------------------------
 * The fly.toml viewer renders <code style="color: #000000 !important">. No
 * stylesheet can beat an inline !important colour, but
 * -webkit-text-fill-color (Chrome, Edge, Safari, Firefox) paints over it. */
:is([style*="color: #000"], [style*="color:#000"], [style*="color: black"], [style*="color:black"]):not([style*="background"]) {{
  -webkit-text-fill-color: {text};
}}

/* ---- Charts (uPlot draws axes/labels on canvas with dark ink) ---------- */
.uplot canvas {{
  filter: invert(1) hue-rotate(180deg);
}}

/* ---- Region maps (Leaflet) --------------------------------------------- */
.leaflet-container {{
  background: {surface};
}}
.leaflet-tile-pane {{
  filter: invert(1) hue-rotate(180deg) brightness(.95) contrast(.9);
}}

/* ---- Fly logo ------------------------------------------------------------
 * The balloon/mountain linework is `fill-current` (navy on light). Colour it
 * like the background instead, the way docs.fly.io's dark logo does; the
 * "Fly.io" wordmark (last path, sign-in page) stays light. */
svg:has(> g > path[fill*="Radial1"]) > g > path.fill-current:nth-of-type(2) {{
  fill: #121219;
}}

/* ---- Sign-in page: haiku sits on a light illustration, keep it dark --- */
.sign-in-art blockquote {{ color: rgb(93 25 133); }}
.sign-in-art blockquote a {{ text-decoration-color: rgb(93 25 133 / .4); }}
.sign-in-art blockquote a:hover {{ color: rgb(137 25 201); text-decoration-color: rgb(137 25 201); }}
"""

HEADER = """/* ==UserStyle==
@name           Fly.io Dark Mode
@namespace      github.com/{repo}
@version        {version}
@description    Smooth, purple-tinted dark theme for the Fly.io dashboard: apps, Machines, Managed Postgres, billing, tokens and sign-in.
@author         Roman Wagner (https://github.com/rojnwa)
@homepageURL    https://github.com/{repo}
@supportURL     https://github.com/{repo}/issues
@updateURL      https://raw.githubusercontent.com/{repo}/main/{out_name}
@license        MIT
@preprocessor   default
==/UserStyle== */

/*
 * Generated by scripts/build.py from {css_name} - do not edit by hand.
 *
 * How it works
 *   Section 1 re-maps every colour rule that Fly's stylesheet (Tailwind 3 +
 *   custom components) ships, keeping the original selectors and cascade
 *   order: light surfaces -> dark surfaces, dark ink -> light ink, pastel
 *   tints -> translucent glows, hairlines -> soft white borders. Section 2
 *   adds things the site never styles (color-scheme, scrollbars, autofill,
 *   backdrop, charts, maps, logo).
 *
 * Palette
 *   canvas {canvas}   cards {surface}   raised {raised} / {raised2}   popovers {overlay}
 *   inputs, code  {sunken}  text    {text}   muted {muted}   faint {faint}
 *   accent        {accent}  (Fly violet, lifted for dark backgrounds)
 */
"""


def arrow_svg(fill_hex: str) -> str:
    return ("url(\"data:image/svg+xml,%3Csvg viewBox='0 0 36 12' xmlns='http://www.w3.org/2000/svg' "
            "fill-rule='evenodd' clip-rule='evenodd'%3E%3Cpath d='M2.658 0h32.004c-6 0-11.627 12.002-16.002 "
            "12.002-4.375 0-10.066-12.002-16.002-12.002z' fill='%23" + fill_hex.lstrip("#") + "'/%3E%3C/svg%3E\")")


def palette() -> dict:
    return {
        "surface": hexs(SURFACE), "canvas": hexs(CANVAS), "sunken": hexs(SUNKEN), "overlay": hexs(OVERLAY),
        "raised": hexs(t_bg(248, 249, 252, 1.0)), "raised2": hexs(t_bg(241, 242, 249, 1.0)),
        "text": hexs(t_text(18, 18, 38, 1.0)), "muted": hexs(t_text(103, 107, 137, 1.0)),
        "faint": hexs(t_text(150, 152, 182, 1.0)), "accent": hexs(t_text(124, 58, 237, 1.0)),
        "surface_rgb": "%d %d %d" % SURFACE, "sunken_rgb": "%d %d %d" % SUNKEN,
        "arrow": arrow_svg(hexs(OVERLAY)),
    }


def load_patches(pal: dict) -> dict:
    patches = {}
    for chunk in PATCH_SRC.split("@@")[1:]:
        head, _, body = chunk.partition("\n")
        body = body.strip()
        for k, v in pal.items():
            body = body.replace("{" + k + "}", v)
        patches[key(head)] = split_decls(body)
    return patches


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------

def generate(rules, patches):
    out, used = [], set()
    for media, sel, body in rules:
        if not sel or sel.startswith("@"):
            continue
        k = key(sel)
        patched = not media and k in patches
        selector = norm(sel) if patched else keep_selector(sel)
        if not selector:
            continue
        decls = []
        for prop, value in split_decls(body):
            fn = transform_for(prop)
            if not fn:
                continue
            important = value.endswith("!important")
            raw = value[:-10].strip() if important else value
            if patched and not patches[k]:
                new, changed = raw, False
            else:
                new, changed = fn(raw)
            if not changed and RELATIVE_URL.search(raw):
                continue    # url() would resolve against the page, not the stylesheet
            decls.append((prop, new + (" !important" if important else "")))
        if patched:
            used.add(k)
            override = dict(patches[k])
            decls = [(p, override.pop(p)) if p in override else (p, v) for p, v in decls] + list(override.items())
        if decls:
            out.append((media, norm(selector), decls))
    return out, set(patches) - used


def emit(rules) -> str:
    merged = []
    for media, sel, decls in rules:
        prev = merged[-1] if merged else None
        # Merge neighbours with identical output, but never into a list that
        # holds a vendor pseudo: one unknown selector invalidates the whole rule.
        if (prev and prev[0] == media and prev[2] == decls
                and not VENDOR_PSEUDO.search(sel) and not any(VENDOR_PSEUDO.search(s) for s in prev[1])):
            prev[1].append(sel)
        else:
            merged.append([media, [sel], decls])
    lines = []
    for media, sels, decls in merged:
        rule = f'{", ".join(sels)} {{ {" ".join(f"{p}: {v};" for p, v in decls)} }}'
        for mq in reversed(media):
            rule = f"{mq} {{ {rule} }}"
        lines.append(rule)
    return "\n".join(lines)


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def resolve_css(source: str | None) -> tuple[str, str]:
    if source and not source.startswith(("http://", "https://")):
        return Path(source).read_text(encoding="utf-8"), Path(source).name
    url = source
    if not url:
        m = re.search(r"/phx/assets/app-[0-9a-f]+\.css(?:\?vsn=d)?", fetch(SIGN_IN_URL))
        if not m:
            sys.exit(f"error: no app-*.css link found on {SIGN_IN_URL}")
        url = "https://fly.io" + m.group(0)
    return fetch(url), url.rsplit("/", 1)[-1].split("?", 1)[0]


def build(css: str, css_name: str) -> str:
    pal = palette()
    patches = load_patches(pal)
    rules, unused = generate(parse_rules(css), patches)
    for k in sorted(unused):
        print(f"warning: patch no longer matches a rule in {css_name}: {k[:100]}", file=sys.stderr)
    header = HEADER.format(repo=REPO, version=VERSION, out_name=OUT_NAME, css_name=css_name, **pal)
    return (header
            + f"\n@-moz-document {URL_MATCH} {{\n\n"
            + "/* ==== 1. Re-mapped site colours ======================================= */\n"
            + emit(rules)
            + "\n\n/* ==== 2. Additions ===================================================== */"
            + ADDITIONS.format(**pal)
            + "\n}\n")


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--css", help="path or URL of Fly's app-*.css (default: discover it on fly.io)")
    ap.add_argument("--out", default=str(root / OUT_NAME), help=f"output file (default: {OUT_NAME})")
    args = ap.parse_args()
    css, css_name = resolve_css(args.css)
    result = build(css, css_name)
    Path(args.out).write_text(result, encoding="utf-8", newline="\n")
    print(f"wrote {args.out} ({len(result):,} bytes) from {css_name}")


if __name__ == "__main__":
    main()
