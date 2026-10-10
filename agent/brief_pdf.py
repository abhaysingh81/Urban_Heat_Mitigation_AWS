"""One-page A4 PDF of a ward brief (English + Hindi). Uses fpdf2 with HarfBuzz
shaping so Devanagari conjuncts and vowel signs render correctly."""

from __future__ import annotations

from pathlib import Path

FONT_DIR = Path(__file__).parent / "fonts"
LATIN = FONT_DIR / "NotoSans-Regular.ttf"
DEVANAGARI = FONT_DIR / "NotoSansDevanagari-Regular.ttf"


def build_pdf(brief: dict) -> bytes:
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    fonts_ok = LATIN.exists() and DEVANAGARI.exists()
    if fonts_ok:
        pdf.add_font("latin", "", str(LATIN))
        pdf.add_font("deva", "", str(DEVANAGARI))
        pdf.set_text_shaping(True)
        pdf.set_fallback_fonts(["latin"], exact_match=False)  # Latin names/units inside Hindi text
    pdf.add_page()

    def font(name, size):
        pdf.set_font(name if fonts_ok else "Helvetica", size=size)

    def clean(t: str, latin_only: bool = False) -> str:
        if fonts_ok and not latin_only:
            return t
        return t.replace("₹", "Rs.").encode("latin-1", "replace").decode("latin-1")

    w = brief["facts"]["ward"]
    font("latin", 16)
    pdf.multi_cell(0, 9, clean(f"Heat action brief — {w['ward_name']}, {brief['facts']['city']}"),
                   new_x="LMARGIN", new_y="NEXT")
    font("latin", 9)
    src = "AI-drafted, numbers verified against model output" if brief["source"] == "bedrock" \
        else "Template brief (numbers taken directly from model output)"
    pdf.multi_cell(0, 5, clean(f"{src}. Cooling effects are estimates. Risk is a relative ranking."),
                   new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    font("latin", 11)
    pdf.multi_cell(0, 6, clean(brief["brief_en"]), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    font("deva", 11)
    pdf.multi_cell(0, 7, clean(brief["brief_hi"], latin_only=False), new_x="LMARGIN", new_y="NEXT")
    if not fonts_ok:
        pdf.ln(3)
        font("latin", 8)
        pdf.multi_cell(0, 5, "Hindi text requires fonts in agent/fonts; see README.")
    return bytes(pdf.output())
