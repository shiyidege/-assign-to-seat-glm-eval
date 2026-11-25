#!/usr/bin/env python3
"""Render crisp 300-DPI publication-style math equation PNGs for universal Word/WPS/QuickLook/Feishu compatibility."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path("/Users/xiongzhaoyang/code/assign_to_seat_glm_eval/figures/formulas")
OUT_DIR.mkdir(parents=True, exist_ok=True)

FONT_CN_MED = "/Library/Fonts/STHeiti Medium.ttc"
FONT_CN_REG = "/Library/Fonts/STHeiti Light.ttc"
FONT_MATH_IT = "/System/Library/Fonts/Supplemental/Times New Roman Italic.ttf"
FONT_MATH_REG = "/System/Library/Fonts/Supplemental/Times New Roman.ttf"
FONT_MATH_BOLD = "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf"
FONT_SYM = "/Library/Fonts/Arial Unicode.ttf"


def f_cn(sz, bold=False):
    return ImageFont.truetype(FONT_CN_MED if bold else FONT_CN_REG, sz)


def f_it(sz):
    return ImageFont.truetype(FONT_MATH_IT, sz)


def f_rg(sz):
    return ImageFont.truetype(FONT_MATH_REG, sz)


def f_bd(sz):
    return ImageFont.truetype(FONT_MATH_BOLD, sz)


def f_sym(sz):
    return ImageFont.truetype(FONT_SYM, sz)


def text_size(draw, text, font):
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[2] - bb[0], bb[3] - bb[1], bb[0], bb[1]


def new_card(w=1560, h=170, eq_num="(1)"):
    img = Image.new("RGB", (w, h), "#EEF4FA")
    draw = ImageDraw.Draw(img)
    # Left blue accent bar
    draw.rectangle([0, 0, 14, h], fill="#2E75B6")
    # Subtle outer border
    draw.rectangle([14, 0, w - 1, h - 1], outline="#D5E2F0", width=2)
    # Right-aligned equation number
    fn = f_rg(34)
    nw, nh, _, top = text_size(draw, eq_num, fn)
    draw.text((w - nw - 34, (h - nh) // 2 - top), eq_num, font=fn, fill="#475569")
    return img, draw


def draw_run_seq(draw, x, y_mid, items, color="#1B365D"):
    """items: list of (text, font, dy_offset) or (text, font, dy_offset, dx_advance_override)."""
    cur_x = x
    for it in items:
        txt, font, dy = it[0], it[1], it[2]
        w, h, left, top = text_size(draw, txt, font)
        draw.text((cur_x - left, y_mid - h / 2 - top + dy), txt, font=font, fill=color)
        cur_x += it[3] if len(it) > 3 else w
    return cur_x


def seq_width(draw, items):
    total = 0
    for it in items:
        txt, font = it[0], it[1]
        w, _, _, _ = text_size(draw, txt, font)
        total += it[3] if len(it) > 3 else w
    return total


def build_eq1():
    """收益达成率 = 策略实际收益 / HO（事后全知最优收益） × 100%,  Gap = 100% − 收益达成率"""
    W, H = 1560, 184
    img, draw = new_card(W, H, "(1)")
    NAVY = "#1B365D"
    cy = H // 2

    # Measure fraction parts
    num_txt, den_txt = "策略实际收益", "HO（事后全知最优收益）"
    fn_cn = f_cn(32, True)
    nw, nh, nl, nt = text_size(draw, num_txt, fn_cn)
    dw, dh, dl, dt = text_size(draw, den_txt, fn_cn)
    frac_w = max(nw, dw) + 32

    left_seq = [("收益达成率", f_cn(34, True), 0), ("  =  ", f_rg(36), 0)]
    right_seq = [
        ("  × 100% ,     ", f_rg(34), 0),
        ("Gap", f_it(38), 0),
        ("  =  100% − ", f_rg(34), 0),
        ("收益达成率", f_cn(34, True), 0),
    ]
    total_w = seq_width(draw, left_seq) + frac_w + seq_width(draw, right_seq)
    x0 = (W - 110 - total_w) // 2 + 24

    x = draw_run_seq(draw, x0, cy, left_seq, NAVY)
    # Fraction bar
    draw.line([(x, cy), (x + frac_w, cy)], fill=NAVY, width=3)
    draw.text((x + (frac_w - nw) / 2 - nl, cy - nh - 14 - nt), num_txt, font=fn_cn, fill=NAVY)
    draw.text((x + (frac_w - dw) / 2 - dl, cy + 14 - dt), den_txt, font=fn_cn, fill=NAVY)
    x += frac_w
    draw_run_seq(draw, x, cy, right_seq, NAVY)

    out = OUT_DIR / "eq1_metric.png"
    img.save(out, dpi=(300, 300))
    return out


def build_eq2():
    """p_{ij} = ⌊ 10 · (j - i + 1)^{4/5} ⌋ ,   1 ≤ i ≤ j ≤ M"""
    W, H = 1560, 152
    img, draw = new_card(W, H, "(2)")
    NAVY = "#1B365D"
    cy = H // 2 + 4

    seq = [
        ("p", f_it(44), 0),
        ("ij", f_it(28), 16),
        ("  =  ", f_rg(40), 2),
        ("⌊", f_sym(46), 0),
        (" 10 · (", f_rg(40), 0),
        ("j", f_it(42), 2),
        (" − ", f_rg(40), 3),
        ("i", f_it(42), 0),
        (" + 1)", f_rg(40), 0),
        ("4/5", f_rg(27), -20),
        (" ", f_rg(30), 0),
        ("⌋", f_sym(46), 0),
        (" ,", f_rg(40), 12),
        ("      1 ≤ ", f_rg(38), 0),
        ("i", f_it(40), 0),
        (" ≤ ", f_rg(38), 0),
        ("j", f_it(40), 2),
        (" ≤ ", f_rg(38), 0),
        ("M", f_it(40), 0),
    ]
    tw = seq_width(draw, seq)
    x0 = (W - 110 - tw) // 2 + 24
    draw_run_seq(draw, x0, cy, seq, NAVY)

    out = OUT_DIR / "eq2_fare.png"
    img.save(out, dpi=(300, 300))
    return out


def build_eq3():
    """[u, v]  --分配(i→j)-->  [u, i-1]  ∪  [j+1, v]"""
    W, H = 1560, 160
    img, draw = new_card(W, H, "(3)")
    NAVY = "#1B365D"
    BLUE = "#2E75B6"
    cy = H // 2 + 8

    left_seq = [("[", f_rg(42), 0), ("u", f_it(42), 0), (",", f_rg(40), 14), (" ", f_rg(28), 0), ("v", f_it(42), 0), ("]", f_rg(42), 0)]
    arrow_w = 220
    right_seq = [
        ("[", f_rg(42), 0), ("u", f_it(42), 0), (",", f_rg(40), 14), (" ", f_rg(28), 0), ("i", f_it(42), 0), (" − 1]", f_rg(40), 1),
        ("   ∪   ", f_sym(40), 0),
        ("[", f_rg(42), 0), ("j", f_it(42), 2), (" + 1", f_rg(40), 0), (",", f_rg(40), 14), (" ", f_rg(28), 0), ("v", f_it(42), 0), ("]", f_rg(42), 0),
    ]
    tw = seq_width(draw, left_seq) + arrow_w + seq_width(draw, right_seq)
    x0 = (W - 110 - tw) // 2 + 24

    x = draw_run_seq(draw, x0, cy, left_seq, NAVY)
    # Arrow with label above
    ax1, ax2 = x + 28, x + arrow_w - 28
    draw.line([(ax1, cy), (ax2, cy)], fill=BLUE, width=4)
    draw.polygon([(ax2 + 2, cy), (ax2 - 16, cy - 9), (ax2 - 16, cy + 9)], fill=BLUE)
    lbl_seq = [("分配 ", f_cn(24, True), 0), ("i", f_it(28), 0), (" → ", f_sym(26), 0), ("j", f_it(28), 0)]
    lw = seq_width(draw, lbl_seq)
    draw_run_seq(draw, (ax1 + ax2 - lw) / 2, cy - 28, lbl_seq, BLUE)

    draw_run_seq(draw, x + arrow_w, cy, right_seq, NAVY)

    out = OUT_DIR / "eq3_split.png"
    img.save(out, dpi=(300, 300))
    return out


def build_eq4():
    """max_{(u,v): u<=i<=j<=v} ( p_{ij} - β†_{uv} + β†_{u,i-1} + β†_{j+1,v} ) >= 0"""
    W, H = 1560, 176
    img, draw = new_card(W, H, "(4)")
    NAVY = "#1B365D"
    cy = H // 2 - 6

    max_block_w = 240
    rhs_seq = [
        ("( ", f_rg(44), 0),
        ("p", f_it(44), 0), ("ij", f_it(26), 16),
        ("  −  ", f_rg(40), 3),
        ("β", f_sym(44), 0), ("†", f_rg(24), -18, 2), ("uv", f_it(26), 17),
        ("  +  ", f_rg(40), 2),
        ("β", f_sym(44), 0), ("†", f_rg(24), -18, 2), ("u, i−1", f_it(26), 17),
        ("  +  ", f_rg(40), 2),
        ("β", f_sym(44), 0), ("†", f_rg(24), -18, 2), ("j+1, v", f_it(26), 17),
        (" )  ≥  0", f_rg(44), 1),
    ]
    tw = max_block_w + seq_width(draw, rhs_seq)
    x0 = (W - 110 - tw) // 2 + 20

    # Draw "max" + condition underneath
    mw, mh, ml, mt = text_size(draw, "max", f_bd(42))
    draw.text((x0 + (max_block_w - mw) / 2 - ml, cy - mh / 2 - mt), "max", font=f_bd(42), fill=NAVY)
    sub_seq = [
        ("(", f_rg(23), 0), ("u", f_it(24), 0), (",", f_rg(23), 7), ("v", f_it(24), 0), ("): ", f_rg(23), 0),
        ("u", f_it(24), 0), ("≤", f_sym(22), 0), ("i", f_it(24), 0), ("≤", f_sym(22), 0),
        ("j", f_it(24), 1), ("≤", f_sym(22), 0), ("v", f_it(24), 0),
    ]
    sw = seq_width(draw, sub_seq)
    draw_run_seq(draw, x0 + (max_block_w - sw) / 2, cy + 38, sub_seq, "#334155")

    draw_run_seq(draw, x0 + max_block_w + 6, cy, rhs_seq, NAVY)

    out = OUT_DIR / "eq4_bpcm.png"
    img.save(out, dpi=(300, 300))
    return out


def build_eq5():
    """BPC-M (95.28%–95.43%) ≳ RDP (94.73%–95.22%) > BPC-S (93.40%–94.37%) ≈ 纯AI E097 (94.22%) ≫ MP (88.23%)"""
    W, H = 1560, 146
    img, draw = new_card(W, H, "(5)")
    cy = H // 2

    parts = [
        ("BPC-M ", f_bd(31), "#1F7A6E"),
        ("(95.28–95.43%)", f_rg(26), "#1F7A6E"),
        ("  ≳  ", f_sym(34), "#475569"),
        ("RDP ", f_bd(31), "#1B365D"),
        ("(94.73–95.22%)", f_rg(26), "#1B365D"),
        ("  >  ", f_sym(34), "#475569"),
        ("BPC-S ", f_bd(31), "#334155"),
        ("(93.40–94.37%)", f_rg(26), "#334155"),
        ("  ≈  ", f_sym(34), "#475569"),
        ("纯AI E097 ", f_cn(28, True), "#9A5B00"),
        ("(94.22%)", f_bd(26), "#9A5B00"),
        ("  ≫  ", f_sym(34), "#475569"),
        ("MP ", f_bd(31), "#64748B"),
        ("(88.23%)", f_rg(26), "#64748B"),
    ]
    tw = sum(text_size(draw, t, f)[0] for t, f, _ in parts)
    x = (W - 105 - tw) // 2 + 22
    for t, f, col in parts:
        w, h, l, top = text_size(draw, t, f)
        draw.text((x - l, cy - h / 2 - top), t, font=f, fill=col)
        x += w

    out = OUT_DIR / "eq5_hierarchy.png"
    img.save(out, dpi=(300, 300))
    return out


def main():
    paths = [build_eq1(), build_eq2(), build_eq3(), build_eq4(), build_eq5()]
    for p in paths:
        print("Rendered formula:", p)


if __name__ == "__main__":
    main()
