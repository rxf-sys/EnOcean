"""Generate the relay front-panel diagrams for the dashboard tab "Anlernen".

Writes ha-config/www/enocean/{sr4,mf2,jrg2}.svg (served by Home Assistant as
/local/enocean/*.svg). Run: python tools/make_relay_svgs.py
"""

from __future__ import annotations

import math
import pathlib
from html import escape

OUT = pathlib.Path(__file__).resolve().parents[1] / "ha-config" / "www" / "enocean"

RUN = "#2e9d5b"     # operating position
TEACH = "#e8890c"   # teach-in position
DANGER = "#d23c3c"  # careful
LABEL = "#e8eefc"

W, H = 900, 560


def dial(cx: float, cy: float, r: float, labels: list[tuple[str, float, str | None]]) -> str:
    """Draw a rotary switch with labels at angles (0° = up, clockwise)."""
    parts = [
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="#20263a" stroke="#9fb3e6" stroke-width="2"/>',
        f'<circle cx="{cx}" cy="{cy}" r="{r * 0.35}" fill="#c9d3ea"/>',
        f'<line x1="{cx - r * 0.25}" y1="{cy}" x2="{cx + r * 0.25}" y2="{cy}" stroke="#20263a" stroke-width="3"/>',
        f'<line x1="{cx}" y1="{cy - r * 0.25}" x2="{cx}" y2="{cy + r * 0.25}" stroke="#20263a" stroke-width="3"/>',
    ]
    for text, angle, color in labels:
        a = math.radians(angle)
        tx = cx + (r + 22) * math.sin(a)
        ty = cy - (r + 22) * math.cos(a) + 4
        ix, iy = cx + r * math.sin(a), cy - r * math.cos(a)
        ox, oy = cx + (r + 8) * math.sin(a), cy - (r + 8) * math.cos(a)
        tick = color or "#9fb3e6"
        parts.append(f'<line x1="{ix:.1f}" y1="{iy:.1f}" x2="{ox:.1f}" y2="{oy:.1f}" stroke="{tick}" stroke-width="2"/>')
        if color:
            width = 7.2 * len(text) + 10
            parts.append(
                f'<rect x="{tx - width / 2:.1f}" y="{ty - 13:.1f}" width="{width:.1f}" height="18" rx="5" fill="{color}"/>'
            )
        parts.append(
            f'<text x="{tx:.1f}" y="{ty:.1f}" font-size="12" font-weight="{700 if color else 400}" '
            f'text-anchor="middle" fill="{"#ffffff" if color else LABEL}">{escape(text)}</text>'
        )
    return "\n".join(parts)


def panel(title: str, article: str, dials: list[str], notes: list[tuple[str, list[tuple[str, str]]]]) -> str:
    """Module front on the left, explanation on the right."""
    body = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="Helvetica, Arial, sans-serif">',
        f'<rect width="{W}" height="{H}" rx="18" fill="#f4f6fb"/>',
        '<rect x="30" y="24" width="250" height="512" rx="10" fill="#1f4fa3"/>',
        f'<text x="155" y="58" font-size="15" font-weight="700" text-anchor="middle" fill="#ffffff">OPUS {escape(title)}</text>',
        f'<text x="155" y="78" font-size="12" text-anchor="middle" fill="#cfe0ff">{escape(article)}</text>',
        *dials,
    ]
    y = 46
    for heading, lines in notes:
        body.append(f'<text x="310" y="{y}" font-size="17" font-weight="700" fill="#1b2340">{escape(heading)}</text>')
        y += 24
        for color, text in lines:
            if color:
                body.append(f'<rect x="312" y="{y - 12}" width="12" height="12" rx="3" fill="{color}"/>')
            body.append(f'<text x="332" y="{y}" font-size="14" fill="#1b2340">{escape(text)}</text>')
            y += 21
        y += 10
    legend = [(RUN, "Betrieb"), (TEACH, "Anlernen"), (DANGER, "Vorsicht")]
    x = 310
    for color, text in legend:
        body.append(f'<rect x="{x}" y="{H - 34}" width="14" height="14" rx="3" fill="{color}"/>')
        body.append(f'<text x="{x + 20}" y="{H - 22}" font-size="13" fill="#1b2340">{text}</text>')
        x += 120
    body.append("</svg>")
    return "\n".join(body)


def sr4() -> str:
    top = dial(155, 160, 34, [
        ("ES-UT", 235, DANGER), ("RT", 265, RUN), ("0", 295, TEACH), ("2", 325, TEACH),
        ("5", 0, None), ("10", 30, None), ("20", 60, None), ("ER", 95, None),
    ])
    mid = dial(155, 295, 28, [("AUTO", 300, RUN), ("LRN", 240, TEACH), ("CLR", 90, DANGER)])
    low = dial(155, 440, 40, [
        ("AUTO", 315, RUN), ("ZE", 260, None), ("ZA", 235, None),
        ("1", 140, TEACH), ("2", 165, TEACH), ("3", 190, TEACH), ("4", 215, TEACH),
    ])
    notes = [
        ("Oberer Schalter – Funktion aller 4 Kanäle", [
            (RUN, "Betrieb: RT = Richtungstaster (Seite EIN / Seite AUS)"),
            (DANGER, "UT: jeder Tastendruck schaltet um – nicht verwenden"),
            (TEACH, "Lernen: 0 = EIN lernen (Anschlag links neben 2)"),
            (TEACH, "Lernen: 2 = AUS lernen"),
            (None, "EW 2–25 s: Ein, automatisch aus · ER: Relais"),
        ]),
        ("Mittlerer Schalter", [
            (RUN, "AUTO = Betrieb"),
            (TEACH, "LRN = Lernen (LED blinkt, aus = gelernt)"),
            (DANGER, "CLR = Löschen – dabei oberen Schalter NICHT drehen"),
        ]),
        ("Unterer Schalter", [
            (RUN, "AUTO = Betrieb"),
            (TEACH, "1–4 = Kanal, der gelernt wird"),
            (None, "ZE / ZA = Zentral-EIN / -AUS"),
        ]),
        ("Ablauf pro Kanal (2 Schritte)", [
            (None, "1. Unten Kanal, oben 0, Mitte LRN → „EIN / Lernen“"),
            (None, "2. Oben 2, Mitte kurz AUTO → LRN → „AUS“"),
            (None, "3. Unten + Mitte AUTO, oben zurück auf RT"),
        ]),
    ]
    return panel("GN-A-R12V-SR-4", "561.152 · 4 Kanäle à 4 A", [top, mid, low], notes)


def mf2() -> str:
    top = dial(155, 160, 34, [
        ("1", 210, None), ("3", 245, None), ("5", 285, TEACH), ("7", 330, None),
        ("8", 10, None), ("9", 50, TEACH), ("10", 90, TEACH),
    ])
    mid = dial(155, 295, 28, [("AUTO", 0, RUN), ("CLR", 270, DANGER), ("LRN", 90, TEACH)])
    low = dial(155, 440, 40, [
        ("SS1", 300, None), ("SS2", 275, None), ("GS", 245, None), ("2R", 215, None),
        ("WR", 185, None), ("GR", 145, None), ("WS", 35, None), ("2S(2xS)", 65, RUN),
    ])
    notes = [
        ("Oberer Schalter – Lernfunktion", [
            (TEACH, "5 = Wippe für BEIDE Kontakte gemeinsam"),
            (TEACH, "9 = Wippe nur für Kontakt 1"),
            (TEACH, "10 = Wippe nur für Kontakt 2"),
            (None, "2/4 Zentral AUS/EIN · 3/7/8 Universaltaster"),
            (None, "Nach dem Lernen: zurück auf die notierte Stellung"),
        ]),
        ("Mittlerer Schalter", [
            (RUN, "AUTO = Betrieb"),
            (TEACH, "LRN = Lernen (LED blinkt, aus = gelernt)"),
            (DANGER, "CLR = Löschen – dabei oberen Schalter NICHT drehen"),
        ]),
        ("Unterer Schalter – Betriebsart (nicht verstellen)", [
            (RUN, "2S (2xS): Anlage-Einstellung; mit 9/10 Kontakte einzeln"),
            (None, "WS, SS1–3, GS, 2R, WR, RR, GR: andere Betriebsarten"),
        ]),
        ("Ablauf (1 Schritt pro Kontakt)", [
            (None, "1. Oben 9 bzw. 10, Mitte LRN → „EIN / Lernen“"),
            (None, "2. Mitte AUTO, oben zurück · EIN und AUS sind gelernt"),
            (DANGER, "Einmal mit 5 gelernt? Erst löschen, dann 9/10"),
        ]),
    ]
    return panel("GN-A-R12V-MF-2", "561.177 · 2 Kontakte à 16 A", [top, mid, low], notes)


def jrg2() -> str:
    top = dial(155, 160, 34, [
        ("10", 225, TEACH), ("20", 255, None), ("30", 285, TEACH), ("40", 315, None),
        ("60", 345, None), ("90", 15, None), ("120", 45, None), ("200", 120, None),
    ])
    mid = dial(155, 295, 28, [
        ("CLR", 225, DANGER), ("0", 255, None), ("0,5", 320, None), ("2", 20, None),
        ("5", 70, None), ("LRN", 120, TEACH),
    ])
    low = dial(155, 440, 40, [
        ("AUTO 1", 315, RUN), ("2", 260, None), ("3", 210, None), ("4", 165, None),
        ("▲", 45, None), ("▼", 110, None),
    ])
    notes = [
        ("Oberer Schalter RV – Laufzeit in Sekunden", [
            (RUN, "Betrieb: Laufzeit, etwas länger als die ganze Fahrt"),
            (TEACH, "Lernen: 10 = Motor 1 · 30 = Motor 2"),
            (DANGER, "Wert vorher notieren und exakt zurückstellen"),
        ]),
        ("Mittlerer Schalter WA – Wendezeit Lamellen", [
            (RUN, "Betrieb: Wendezeit 0–5 s"),
            (TEACH, "LRN (ganz rechts) = Lernen"),
            (DANGER, "CLR (ganz links) = Löschen – oben NICHT drehen"),
        ]),
        ("Unterer Schalter – Betriebsart (nicht verstellen)", [
            (None, "AUTO 1–4, ▲ ▼"),
        ]),
        ("Ablauf (1 Schritt pro Motor)", [
            (None, "1. RV und WA notieren"),
            (None, "2. Oben 10 / 30, Mitte LRN → „EIN / Lernen“ (hoch)"),
            (None, "3. RV und WA exakt zurück · Test hoch / stopp / runter"),
        ]),
    ]
    return panel("GN-A-R12V-JRG-2", "561.153 · 2 Motoren (Jalousie)", [top, mid, low], notes)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, make in (("sr4", sr4), ("mf2", mf2), ("jrg2", jrg2)):
        (OUT / f"{name}.svg").write_text(make(), encoding="utf-8")
        print(f"wrote {OUT / f'{name}.svg'}")


if __name__ == "__main__":
    main()
