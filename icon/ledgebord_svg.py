# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
ledgebord_svg.py — Ledgebords ikon och logotyp som VEKTOR-SVG (ren text, inga paket behövs).

Bygger SVG-strängar för:
  * ikon()            appikonen (1024 × 1024, rundad ruta, gul kantlist, vitt uppgiftskort med bockad lista)
  * logo_liggande()   ikonen + ordet "Ledgebord"
  * logo_stapel()     ikonen över ordet
Varje finns i fyra färgvarianter (``variant``): "farg" (standard), "vit" (på mörk botten), "svart" (enfärgat tryck),
"enfarg" (en spotfärg, t.ex. för stämpel/gravyr — samma som svart men i valfri färg via ``spot``).

Anpassat för tryck: bara rena former, kurvor och linjära toningar — INGA filter, ingen inbäddad bild och ingen
typsnittsfil. Ordet "Ledgebord" är OMRITAT till banor (Inter ExtraBold, SIL Open Font License 1.1, © The Inter Project
Authors), så SVG:n ser likadan ut överallt och kan skickas till tryckeri utan att typsnittet följer med.
Färger: indigo #4F46E5, violett #7C3AED, mörk indigo #2A2370, gul #FBBF24 / #F59E0B, kort #FFFFFF.
För CMYK-tryck: öppna SVG/PDF i Inkscape/Illustrator och konvertera till tryckeriets färgprofil.
"""
from __future__ import annotations

from typing import Dict

# "Ledgebord" i Inter ExtraBold, omritat; enheter = typsnittets 2048/em, y nedåt, baslinje y=0, bredd ADV.
WORD_ADV = 10847
WORD_PATH = "M116 0V-1490H469V-288H1092V0ZM1780 21Q1605 21 1478 -48Q1351 -118 1284 -247Q1216 -376 1216 -555Q1216 -727 1284 -857Q1351 -987 1475 -1060Q1599 -1132 1767 -1132Q1885 -1132 1984 -1095Q2082 -1058 2154 -986Q2227 -913 2266 -807Q2306 -701 2306 -562V-474H1559Q1562 -399 1588 -347Q1616 -289 1667 -260Q1718 -232 1786 -232Q1833 -232 1872 -245Q1910 -258 1938 -284Q1965 -310 1979 -347L2290 -296Q2262 -200 2194 -128Q2125 -57 2020 -18Q1916 21 1780 21ZM1561 -677H1975Q1969 -725 1954 -763Q1930 -819 1884 -849Q1838 -879 1770 -879Q1702 -879 1655 -848Q1608 -818 1584 -764Q1566 -725 1561 -677ZM2880 16Q2756 16 2654 -48Q2552 -113 2492 -240Q2432 -368 2432 -558Q2432 -754 2494 -882Q2557 -1009 2658 -1070Q2760 -1132 2877 -1132Q2966 -1132 3029 -1102Q3092 -1071 3132 -1024Q3173 -977 3194 -926H3202V-1490H3550V0H3206V-181H3194Q3172 -131 3130 -86Q3089 -41 3028 -12Q2966 16 2880 16ZM2999 -256Q3065 -256 3112 -294Q3160 -331 3185 -399Q3210 -467 3210 -558Q3210 -651 3185 -718Q3160 -786 3112 -822Q3065 -859 2999 -859Q2932 -859 2886 -822Q2839 -784 2815 -716Q2791 -649 2791 -558Q2791 -468 2815 -400Q2839 -331 2886 -294Q2932 -256 2999 -256ZM4282 442Q4136 442 4027 405Q3918 368 3850 302Q3783 236 3763 149L4066 87Q4076 117 4103 142Q4130 168 4174 184Q4218 199 4280 199Q4387 199 4444 151Q4502 103 4502 3V-195H4475Q4455 -145 4416 -104Q4376 -63 4316 -39Q4255 -15 4172 -15Q4049 -15 3948 -72Q3846 -130 3785 -250Q3724 -371 3724 -559Q3724 -755 3787 -882Q3850 -1009 3952 -1070Q4053 -1132 4171 -1132Q4260 -1132 4324 -1102Q4387 -1072 4428 -1024Q4470 -977 4491 -926H4501V-1118H4846V-25Q4846 129 4774 233Q4703 337 4576 390Q4449 442 4282 442ZM4291 -271Q4358 -271 4405 -305Q4452 -339 4477 -404Q4502 -470 4502 -560Q4502 -652 4477 -719Q4452 -786 4406 -822Q4359 -859 4291 -859Q4224 -859 4178 -822Q4131 -784 4107 -717Q4083 -650 4083 -560Q4083 -470 4107 -405Q4131 -340 4178 -306Q4224 -271 4291 -271ZM5583 21Q5408 21 5281 -48Q5154 -118 5086 -247Q5019 -376 5019 -555Q5019 -727 5086 -857Q5154 -987 5278 -1060Q5402 -1132 5570 -1132Q5688 -1132 5786 -1095Q5885 -1058 5958 -986Q6030 -913 6070 -807Q6109 -701 6109 -562V-474H5362Q5365 -399 5391 -347Q5419 -289 5470 -260Q5521 -232 5589 -232Q5636 -232 5674 -245Q5713 -258 5740 -284Q5768 -310 5782 -347L6093 -296Q6065 -200 5996 -128Q5928 -57 5824 -18Q5719 21 5583 21ZM5364 -677H5778Q5772 -725 5757 -763Q5733 -819 5687 -849Q5641 -879 5573 -879Q5505 -879 5458 -848Q5411 -818 5387 -764Q5369 -725 5364 -677ZM6949 16Q6864 16 6802 -12Q6739 -41 6698 -86Q6657 -131 6635 -181H6623V0H6278V-1490H6627V-926H6635Q6656 -977 6696 -1024Q6737 -1071 6800 -1102Q6862 -1132 6951 -1132Q7069 -1132 7170 -1070Q7272 -1009 7334 -882Q7397 -754 7397 -558Q7397 -368 7337 -240Q7277 -113 7175 -48Q7073 16 6949 16ZM6830 -256Q6897 -256 6944 -294Q6990 -331 7014 -400Q7038 -468 7038 -558Q7038 -649 7014 -716Q6990 -784 6944 -822Q6898 -859 6830 -859Q6763 -859 6716 -822Q6669 -786 6644 -718Q6619 -651 6619 -558Q6619 -467 6644 -399Q6669 -331 6716 -294Q6764 -256 6830 -256ZM8089 21Q7914 21 7788 -52Q7662 -124 7594 -254Q7527 -383 7527 -555Q7527 -728 7594 -858Q7662 -987 7788 -1060Q7914 -1132 8089 -1132Q8264 -1132 8390 -1060Q8516 -987 8583 -858Q8650 -728 8650 -555Q8650 -383 8583 -254Q8516 -124 8390 -52Q8264 21 8089 21ZM8089 -246Q8156 -246 8202 -285Q8248 -324 8272 -394Q8295 -464 8295 -557Q8295 -650 8272 -720Q8248 -789 8202 -827Q8156 -865 8089 -865Q8022 -865 7976 -827Q7930 -789 7906 -720Q7883 -650 7883 -557Q7883 -464 7906 -394Q7930 -324 7976 -285Q8022 -246 8089 -246ZM8824 0V-1118H9163V-914H9175Q9205 -1025 9274 -1078Q9344 -1132 9436 -1132Q9460 -1132 9486 -1129Q9513 -1126 9535 -1120V-816Q9510 -825 9470 -830Q9429 -834 9397 -834Q9333 -834 9282 -806Q9231 -777 9202 -727Q9173 -677 9173 -610V0ZM10075 16Q9951 16 9849 -48Q9747 -113 9687 -240Q9627 -368 9627 -558Q9627 -754 9690 -882Q9752 -1009 9854 -1070Q9955 -1132 10072 -1132Q10161 -1132 10224 -1102Q10287 -1071 10328 -1024Q10368 -977 10389 -926H10397V-1490H10745V0H10401V-181H10389Q10367 -131 10326 -86Q10284 -41 10222 -12Q10161 16 10075 16ZM10194 -256Q10260 -256 10308 -294Q10355 -331 10380 -399Q10405 -467 10405 -558Q10405 -651 10380 -718Q10355 -786 10308 -822Q10260 -859 10194 -859Q10127 -859 10080 -822Q10034 -784 10010 -716Q9986 -649 9986 -558Q9986 -468 10010 -400Q10034 -331 10080 -294Q10127 -256 10194 -256Z"

PALETT: Dict[str, Dict[str, str]] = {
    "farg": dict(bg0="#3B2FD0", bg1="#7C3AED", ledge0="#FDE047", ledge1="#F59E0B", edge="#1E1B4B", card="#FFFFFF",
                 on="#4F46E5", on_mark="#FFFFFF", off="#B4B1D8", bar_on="#8B87C9", bar="#D6D4EC", word="#2A2370",
                 shadow="#1E1B4B"),
    "vit": dict(bg0="#FFFFFF", bg1="#FFFFFF", ledge0="#FBBF24", ledge1="#FBBF24", edge="#1E1B4B", card="#2A2370",
                on="#FFFFFF", on_mark="#2A2370", off="#8B87C9", bar_on="#FFFFFF", bar="#8B87C9", word="#FFFFFF",
                shadow=""),
    "svart": dict(bg0="#000000", bg1="#000000", ledge0="#FFFFFF", ledge1="#FFFFFF", edge="", card="#FFFFFF",
                  on="#000000", on_mark="#FFFFFF", off="#000000", bar_on="#000000", bar="#000000", word="#000000",
                  shadow=""),
}


def _pal(variant: str, spot: str = "#000000") -> Dict[str, str]:
    if variant == "enfarg":
        p = dict(PALETT["svart"])
        for k in ("bg0", "bg1", "on", "off", "bar_on", "bar", "word"):
            p[k] = spot
        return p
    return PALETT[variant]


def _defs(p: Dict[str, str], uid: str) -> str:
    return (
        f'<linearGradient id="{uid}bg" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="1024" y2="1024">'
        f'<stop offset="0" stop-color="{p["bg0"]}"/><stop offset="1" stop-color="{p["bg1"]}"/></linearGradient>'
        f'<linearGradient id="{uid}ld" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="1024">'
        f'<stop offset="0" stop-color="{p["ledge0"]}"/><stop offset="1" stop-color="{p["ledge1"]}"/></linearGradient>'
        f'<clipPath id="{uid}cl"><rect width="1024" height="1024" rx="232"/></clipPath>'
    )


def _icon_body(p: Dict[str, str], uid: str, liten: bool = False) -> str:
    """Själva ikonen i ett 1024 × 1024-koordinatsystem (utan <svg>-ram). ``liten``: förenklad, grövre variant för ≤48 px."""
    o = [f'<g clip-path="url(#{uid}cl)">',
         f'<rect width="1024" height="1024" fill="url(#{uid}bg)"/>']
    if p["edge"]:   # kantlistens skugga mot bakgrunden
        o.append(f'<rect x="150" width="46" height="1024" fill="{p["edge"]}" fill-opacity="0.22"/>')
    if p["edge"]:
        o.append(f'<rect width="156" height="1024" fill="url(#{uid}ld)"/>')
    else:   # enfärgat: ramen till vänster ligger kvar, listen blir en vit rand innanför den (annars "äts" hörnet upp av papperet)
        o.append(f'<rect x="44" width="96" height="1024" fill="{p["ledge0"]}"/>')
    if p["edge"]:
        o.append('<rect x="34" width="14" height="1024" fill="#FFFFFF" fill-opacity="0.35"/>')
    o.append('</g>')
    if p["shadow"]:   # mjuk skugga under kortet utan filter: tre staplade, allt svagare former
        for dy, grow, op in ((34, 14, 0.10), (24, 6, 0.14), (14, 0, 0.18)):
            o.append(f'<rect x="{236 - grow}" y="{176 - grow + dy}" width="{624 + 2 * grow}" height="{672 + 2 * grow}" '
                     f'rx="{72 + grow}" fill="{p["shadow"]}" fill-opacity="{op}"/>')
    cx0, cy0, cw, ch = (212, 150, 676, 724) if liten else (236, 176, 624, 672)
    o.append(f'<rect x="{cx0}" y="{cy0}" width="{cw}" height="{ch}" rx="{80 if liten else 72}" fill="{p["card"]}"/>')
    rows = (336, 512, 688) if liten else (344, 512, 680)
    bs, bw, bh = (132, 22, 64) if liten else (104, 12, 40)
    bx = 266 if liten else 308
    barx = 438 if liten else 458
    for i, cy in enumerate(rows):
        by = cy - bs // 2
        if i == 0:
            o.append(f'<rect x="{bx}" y="{by}" width="{bs}" height="{bs}" rx="{34 if liten else 28}" fill="{p["on"]}"/>')
            k = bs / 104.0
            o.append(f'<path d="M{bx + 26 * k:.0f} {cy + 2 * k:.0f} L{bx + 46 * k:.0f} {cy + 24 * k:.0f} L{bx + 82 * k:.0f} {cy - 22 * k:.0f}" fill="none" '
                     f'stroke="{p["on_mark"]}" stroke-width="{18 * k:.0f}" stroke-linecap="round" stroke-linejoin="round"/>')
        else:
            h = bw // 2
            o.append(f'<rect x="{bx + h}" y="{by + h}" width="{bs - bw}" height="{bs - bw}" rx="{28 if liten else 24}" fill="none" '
                     f'stroke="{p["off"]}" stroke-width="{bw}"/>')
        x1 = (846, 846, 740)[i] if liten else (790, 790, 700)[i]
        o.append(f'<rect x="{barx}" y="{cy - bh // 2}" width="{x1 - barx}" height="{bh}" rx="{bh // 2}" '
                 f'fill="{p["bar_on"] if i == 0 else p["bar"]}"/>')
    return "".join(o)


def ikon(variant: str = "farg", spot: str = "#000000", liten: bool = False) -> str:
    p = _pal(variant, spot)
    if liten and variant == "farg":   # grövre linjer och mörkare toner så att raderna syns på 16–48 px
        p = dict(p, off="#8F8BC4", bar_on="#6D68C4", bar="#A9A6DA")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="1024" height="1024">'
            '<title>Ledgebord</title>'
            f'<defs>{_defs(p, "i")}</defs>{_icon_body(p, "i", liten)}</svg>\n')


def _word(p: Dict[str, str], scale: float, x: float, base: float) -> str:
    return (f'<path transform="translate({x:.1f} {base:.1f}) scale({scale})" fill="{p["word"]}" '
            f'd="{WORD_PATH}"/>')


def logo_liggande(variant: str = "farg", spot: str = "#000000") -> str:
    p = _pal(variant, spot)
    s = 0.38
    w = int(WORD_ADV * s)
    gap = 130
    W, H = 1024 + gap + w + 10, 1060
    base = 512 + 1490 * s / 2
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">'
            '<title>Ledgebord</title>'
            f'<defs>{_defs(p, "l")}</defs>{_icon_body(p, "l")}{_word(p, s, 1024 + gap, base)}</svg>\n')


def logo_stapel(variant: str = "farg", spot: str = "#000000") -> str:
    p = _pal(variant, spot)
    s = 0.30
    w = int(WORD_ADV * s)
    W = max(w, 1024) + 40
    H = 1024 + 130 + int(1490 * s) + 190
    ix = (W - 1024) / 2
    base = 1024 + 130 + 1490 * s
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">'
            '<title>Ledgebord</title>'
            f'<defs>{_defs(p, "s")}</defs><g transform="translate({ix:.1f} 0)">{_icon_body(p, "s")}</g>'
            f'{_word(p, s, (W - w) / 2, base)}</svg>\n')
