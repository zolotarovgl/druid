"""The phylocli logo (Grygoriy, 09/10/2026), drawn with half blocks: one text line = two pixel
rows, so the 35 x 19 pixel art fits in 18 lines x 19 columns. ⬜ is transparent (the terminal's
own background), so the logo works on dark and light themes. Source pixels:
docs/superpowers/specs/assets/druid-logo.txt."""
from __future__ import annotations

PIXELS = """\
⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜🟩⬜⬛⬜⬜⬜⬜⬜⬜
⬜⬜🟩⬜⬜🟩⬛⬜⬛⬜⬜⬛⬛⬜⬛⬜⬜⬜⬜
⬜⬜⬜⬛⬜⬛⬛🟩🟧⬛⬛🟩⬛⬛⬛🟩⬜⬜⬜
⬜⬛🟩⬛⬛🟧⬛⬛🟧⬛🟧⬛⬛⬛🟩⬛⬜⬜⬜
⬜⬜⬛🟫⬛🟧⬛🟧⬛🟧⬛⬛⬛🟧⬛⬛⬜⬜⬜
⬜⬜⬛🟧🟧⬛🟧🟧🟫🟧⬛🟧🟫🟫🟧⬛⬜⬜⬜
⬜⬜⬛🟧🟧🟧🟫🟧🟧🟧🟧🟫🟧🟧🟧⬛⬜⬜⬜
⬜⬜⬜⬛🟧🟫🟧🟧🟧🟧🟫🟧🟧🟧⬛⬜⬜⬜⬜
⬜⬜⬜⬛🟧🟧🟧🟧🟧🟧🟧🟧🟧🟧⬛⬜⬜⬜⬜
⬜⬜⬜⬛🟧🟧🟧🟧🟧🟧🟧🟧🟧🟧⬛⬜⬜⬜⬜
⬜⬜⬜⬛🟧⬜⬛🟧🟧🟧🟧⬛⬜🟧⬛⬜⬜⬜⬜
⬜⬜⬜⬛🟧⬛⬛🟧🟧🟧🟧⬛⬛🟧⬛⬜⬜⬜⬜
⬜⬜⬜⬛🟧🟧🟧🟧🟧🟧🟧🟧🟧🟧⬛⬜⬜⬜⬜
⬜⬜⬜⬛🟧⬛🟧🟧🟧🟧🟧🟧⬛🟧⬛⬜🟩⬜⬜
⬜⬜⬜⬛🟧🟧⬛⬛⬛⬛⬛⬛🟧🟧⬛⬜⬛⬜🟩
⬜⬜⬜⬜⬛🟧🟧🟧🟧🟧🟧🟧🟧⬛⬜⬜⬛⬛⬜
⬜⬜⬜⬜⬜⬛⬛⬛⬛⬛⬛⬛⬛⬜⬜⬛🟧⬛⬛
⬜⬜🟩⬜⬜⬜⬜⬛🟧🟧⬛⬜⬜⬜⬛🟧⬛🟩⬜
🟩⬜⬛⬜⬜⬜⬛⬛🟫🟧⬛⬛⬛⬛🟧⬛⬜⬜⬜
⬜⬛⬛⬜🟩⬛🟧⬛⬛🟫🟧⬛🟧🟧⬛⬜⬜⬜⬜
⬛⬛🟧⬛⬛🟧⬛⬜⬛🟧🟫⬛⬛⬛⬜⬜⬜⬜⬜
⬜⬜⬛🟧🟧⬛⬜⬜⬛🟧🟧⬛⬜⬜⬜⬜⬜⬜⬜
⬜⬜⬜⬛⬛🟩⬜⬛🟧🟧⬛⬜⬜⬜⬜⬜⬜⬜⬜
⬜⬜⬜⬜⬜⬜⬜⬛🟧🟫⬛⬜⬜⬜⬜⬜⬜⬜⬜
⬜⬜⬜⬜⬜⬜⬛🟧🟫🟫🟧⬛⬜⬜⬜⬜⬜⬜⬜
⬜⬜⬜⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬜⬜⬜⬜
⬜⬜⬜⬛⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬛⬜⬜⬜⬜
⬜⬜⬜⬛⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬛⬜⬜⬜⬜
⬜⬜⬜⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬜⬜⬜⬜
⬜⬜⬜⬜⬛⬜⬜⬜⬜⬜⬜⬜⬜⬛⬜⬜⬜⬜⬜
⬜⬜⬜⬜⬛⬜⬜⬜⬜⬜⬜⬜⬜⬛⬜⬜⬜⬜⬜
⬜⬜⬜⬜⬜⬛⬜⬜⬜⬜⬜⬜⬛⬜⬜⬜⬜⬜⬜
⬜⬜⬜⬜⬜⬛⬜⬜⬜⬜⬜⬜⬛⬜⬜⬜⬜⬜⬜
⬜⬜⬜⬜⬜⬜⬛⬜⬜⬜⬜⬛⬜⬜⬜⬜⬜⬜⬜
⬜⬜⬜⬜⬜⬜⬛⬛⬛⬛⬛⬛⬜⬜⬜⬜⬜⬜⬜"""

# ⬛ is drawn dark grey, not pure black, so the outline stays visible on a black terminal
COLOURS = {"⬜": None, "⬛": "#303030", "🟩": "#3cb043", "🟧": "#f28c28", "🟫": "#8b5a2b"}


def render_logo(pixels: str = PIXELS) -> list[str]:
    """Rich-markup lines, two pixel rows per line: ▀ = upper pixel in the foreground and lower
    pixel in the background; ▄ when only the lower one is coloured; a space when neither is."""
    rows = [list(r) for r in pixels.splitlines() if r]
    width = max(len(r) for r in rows)
    rows = [r + ["⬜"] * (width - len(r)) for r in rows]
    if len(rows) % 2:
        rows.append(["⬜"] * width)
    lines = []
    for top, bottom in zip(rows[0::2], rows[1::2]):
        cells = []
        for t, b in zip(top, bottom):
            ct, cb = COLOURS[t], COLOURS[b]
            if ct and cb:
                cells.append(f"[{ct} on {cb}]▀[/]")
            elif ct:
                cells.append(f"[{ct}]▀[/]")
            elif cb:
                cells.append(f"[{cb}]▄[/]")
            else:
                cells.append(" ")
        lines.append("".join(cells))
    return lines
