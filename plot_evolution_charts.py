#!/usr/bin/env python3
"""
Generate publication-quality evolution curve charts from experiment logs:
1. figures/pop100_evolution_curve.png  (100-round Top-6 population evolution vs paper LP baselines)
2. figures/model_compare_20rounds.png  (20-round from-scratch comparison: glm-5.3 vs glm-5.3-flash)

Pure Python + Pillow (2x supersampled anti-aliasing + proper RGBA alpha compositing).
"""

import json
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = Path(__file__).resolve().parent
RES_DIR = BASE_DIR / "results"
FIG_DIR = BASE_DIR / "figures"
FIG_DIR.mkdir(exist_ok=True)

FONT_PATH = "/System/Library/Fonts/Hiragino Sans GB.ttc"


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    idx = 2 if bold else 0
    return ImageFont.truetype(FONT_PATH, size, index=idx)


def draw_dashed_line(
    draw: ImageDraw.ImageDraw,
    p0: tuple,
    p1: tuple,
    color,
    width: int = 2,
    dash: int = 12,
    gap: int = 8,
):
    x0, y0 = p0
    x1, y1 = p1
    dist = math.hypot(x1 - x0, y1 - y0)
    if dist < 1e-6:
        return
    dx = (x1 - x0) / dist
    dy = (y1 - y0) / dist
    pos = 0.0
    while pos < dist:
        end = min(pos + dash, dist)
        sx, sy = x0 + dx * pos, y0 + dy * pos
        ex, ey = x0 + dx * end, y0 + dy * end
        draw.line([(sx, sy), (ex, ey)], fill=color, width=width)
        pos += dash + gap


def draw_dashed_polyline(
    draw: ImageDraw.ImageDraw,
    pts: list,
    color,
    width: int = 3,
    dash: int = 14,
    gap: int = 8,
):
    for i in range(len(pts) - 1):
        draw_dashed_line(draw, pts[i], pts[i + 1], color, width=width, dash=dash, gap=gap)


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont):
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def composite_layer(base_img: Image.Image, draw_fn):
    """Draw semi-transparent shapes on a clean RGBA layer and alpha-composite onto base_img."""
    layer = Image.new("RGBA", base_img.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer, "RGBA")
    draw_fn(ld)
    base_img.alpha_composite(layer)


def draw_rounded_badge(
    base_img: Image.Image,
    x: float,
    y: float,
    lines: list,
    font_main: ImageFont.FreeTypeFont,
    font_sub: ImageFont.FreeTypeFont,
    bg=(255, 255, 255, 245),
    border=(37, 99, 235, 255),
    text_color=(15, 23, 42, 255),
    sub_color=(71, 85, 105, 255),
    pad_x: int = 18,
    pad_y: int = 12,
    radius: int = 14,
    anchor: str = "tl",
):
    tmp = ImageDraw.Draw(base_img)
    widths, heights = [], []
    for idx, line in enumerate(lines):
        f = font_main if idx == 0 else font_sub
        w, h = text_size(tmp, line, f)
        widths.append(w)
        heights.append(h)
    line_gap = 8
    box_w = max(widths) + pad_x * 2
    box_h = sum(heights) + line_gap * (len(lines) - 1) + pad_y * 2

    if anchor == "tl":
        bx, by = x, y
    elif anchor == "tr":
        bx, by = x - box_w, y
    elif anchor == "bl":
        bx, by = x, y - box_h
    elif anchor == "br":
        bx, by = x - box_w, y - box_h
    elif anchor == "bc":
        bx, by = x - box_w / 2, y - box_h
    elif anchor == "tc":
        bx, by = x - box_w / 2, y
    else:
        bx, by = x, y

    # Soft shadow via alpha_composite
    composite_layer(
        base_img,
        lambda d: d.rounded_rectangle(
            [bx + 4, by + 6, bx + box_w + 4, by + box_h + 6],
            radius=radius,
            fill=(15, 23, 42, 24),
        ),
    )
    composite_layer(
        base_img,
        lambda d: d.rounded_rectangle(
            [bx, by, bx + box_w, by + box_h],
            radius=radius,
            fill=bg,
            outline=border,
            width=3,
        ),
    )
    draw = ImageDraw.Draw(base_img)
    cy = by + pad_y
    for idx, line in enumerate(lines):
        f = font_main if idx == 0 else font_sub
        col = text_color if idx == 0 else sub_color
        draw.text((bx + pad_x, cy), line, font=f, fill=col)
        cy += heights[idx] + line_gap
    return (bx, by, bx + box_w, by + box_h)


def build_pop100_chart():
    rows = [
        json.loads(line)
        for line in (RES_DIR / "pop_100_log.jsonl").read_text().splitlines()
        if line.strip()
    ]
    rows.sort(key=lambda r: r["eval_num"])

    vp = json.loads((RES_DIR / "vs_paper_methods.json").read_text())["bench1_N20_heldout"]

    def paper_mean(key: str) -> float:
        return (vp["Case1_平稳到达"][key]["ratio_pct"] + vp["Case2_短途先来"][key]["ratio_pct"]) / 2.0

    ref_bpcm = paper_mean("BPC-M (论文 Eq.12 LP)")     # 95.335
    ref_rdp = paper_mean("RDP (论文 Eq.14+15 LP)")      # 95.005
    ref_bpcs = paper_mean("BPC-S (论文 Eq.6 LP)")       # 94.365
    ref_mp = paper_mean("MP (Myopic)")                  # 88.230

    best_train = 0.0
    best_test = 0.0
    best_train_curve = []
    best_test_curve = []
    scatter_pts = []
    milestones = {}

    for r in rows:
        ev = r["eval_num"]
        if r["status"] == "ok" and r["train_score"] is not None:
            ts = r["train_score"]
            scatter_pts.append((ev, ts, r["op"]))
            if ts > best_train:
                best_train = ts
                if r.get("test_score") is not None:
                    best_test = r["test_score"]
                milestones[ev] = (r["id"], r["op"], best_train, best_test, r.get("test_c1"), r.get("test_c2"))
        if best_train > 0:
            best_train_curve.append((ev, best_train))
            best_test_curve.append((ev, best_test))

    # 2x supersampled canvas (final output 1500x880)
    W, H = 3000, 1760
    img = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img, "RGBA")

    f_title = load_font(54, bold=True)
    f_subtitle = load_font(30, bold=False)
    f_axis_title = load_font(30, bold=True)
    f_tick = load_font(26, bold=False)
    f_legend = load_font(25, bold=False)
    f_ref = load_font(24, bold=True)
    f_badge_main = load_font(24, bold=True)
    f_badge_sub = load_font(20, bold=False)
    f_note = load_font(22, bold=False)

    ml, mr, mt, mb = 210, 470, 290, 200
    pw, ph = W - ml - mr, H - mt - mb

    x_min, x_max = 0.0, 102.0
    y_min, y_max = 83.0, 96.5

    def sx(x: float) -> float:
        return ml + (x - x_min) / (x_max - x_min) * pw

    def sy(y: float) -> float:
        return mt + (y_max - y) / (y_max - y_min) * ph

    # Title & subtitle
    draw.text((ml, 54), "无求解器 AI 种群进化曲线：循环次数 vs 最终求解结果", font=f_title, fill=(15, 23, 42, 255))
    draw.text(
        (ml, 126),
        "Assign-to-Seat 动态控票（M=6 站, N=20 座, T=100 步）| GLM-5 Top-6 进化 100 轮 · 60 条留出测试集 vs 论文精确 LP 基准",
        font=f_subtitle,
        fill=(71, 85, 105, 255),
    )

    # Plot panel background
    draw.rounded_rectangle(
        [ml, mt, ml + pw, mt + ph],
        radius=16,
        fill=(248, 250, 252, 255),
        outline=(226, 232, 240, 255),
        width=2,
    )

    # Subtle vertical highlight band for Round 34 paradigm jump
    composite_layer(
        img,
        lambda d: d.rectangle([sx(32.8), mt + 2, sx(35.2), mt + ph - 2], fill=(37, 99, 235, 20)),
    )

    # Grid lines & ticks
    draw = ImageDraw.Draw(img, "RGBA")
    for yt in [84, 86, 88, 90, 92, 94, 96]:
        yy = sy(yt)
        draw.line([(ml + 2, yy), (ml + pw - 2, yy)], fill=(226, 232, 240, 255), width=2)
        lbl = f"{yt}%"
        tw, th = text_size(draw, lbl, f_tick)
        draw.text((ml - tw - 22, yy - th / 2 - 2), lbl, font=f_tick, fill=(71, 85, 105, 255))

    for xt in range(0, 101, 10):
        xx = sx(xt)
        if 0 < xt <= 100:
            draw.line([(xx, mt + 2), (xx, mt + ph - 2)], fill=(226, 232, 240, 210), width=2)
        lbl = str(xt)
        tw, th = text_size(draw, lbl, f_tick)
        draw.text((xx - tw / 2, mt + ph + 22), lbl, font=f_tick, fill=(71, 85, 105, 255))

    # Area fill under Best-so-far Test curve (properly alpha-composited!)
    poly_pts = [(sx(ev), sy(val)) for ev, val in best_test_curve]
    area_pts = [(poly_pts[0][0], sy(y_min))] + poly_pts + [(poly_pts[-1][0], sy(y_min))]
    composite_layer(img, lambda d: d.polygon(area_pts, fill=(37, 99, 235, 26)))

    # Scatter points of individual evaluations (alpha-composited!)
    below_count = 0
    vis_scatter = []
    for ev, score, op in scatter_pts:
        if score < y_min:
            below_count += 1
        else:
            vis_scatter.append((sx(ev), sy(score)))

    def draw_scatters(d):
        r = 8
        for cx, cy in vis_scatter:
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(100, 116, 139, 85), outline=(71, 85, 105, 135), width=2)

    composite_layer(img, draw_scatters)

    # Paper reference lines + right-side neatly spaced labels
    draw = ImageDraw.Draw(img, "RGBA")
    refs = [
        (ref_bpcm, "BPC-M (论文 Eq.12 LP)", f"{ref_bpcm:.2f}%", (5, 150, 105, 255), -10),
        (ref_rdp,  "RDP (论文 Eq.14+15 LP)", f"{ref_rdp:.2f}%", (8, 145, 178, 255), 8),
        (ref_bpcs, "BPC-S (论文 Eq.6 LP)",   f"{ref_bpcs:.2f}%", (180, 83, 9, 255), 24),
        (ref_mp,   "MP (Myopic 贪心基线)",    f"{ref_mp:.2f}%",  (71, 85, 105, 255), 0),
    ]
    for val, name, pct, col, y_nudge in refs:
        yy = sy(val)
        draw_dashed_line(draw, (ml + 4, yy), (ml + pw - 4, yy), col, width=3, dash=16, gap=10)
        ly = yy + y_nudge
        draw.line([(ml + pw, yy), (ml + pw + 18, ly)], fill=col, width=2)
        draw.text((ml + pw + 26, ly - 15), f"{pct}  {name}", font=f_ref, fill=col)

    # Best-so-far Train curve (purple dashed)
    train_pts = [(sx(ev), sy(val)) for ev, val in best_train_curve]
    draw_dashed_polyline(draw, train_pts, (124, 58, 237, 255), width=4, dash=14, gap=10)

    # Best-so-far Held-out Test curve (royal blue solid)
    draw.line(poly_pts, fill=(37, 99, 235, 255), width=7, joint="curve")

    # Axis borders on top
    draw.line([(ml, mt), (ml, mt + ph)], fill=(148, 163, 184, 255), width=3)
    draw.line([(ml, mt + ph), (ml + pw, mt + ph)], fill=(148, 163, 184, 255), width=3)

    # Axis titles
    x_title = "AI 进化循环次数（Iteration / Evaluation Round）"
    tw, _ = text_size(draw, x_title, f_axis_title)
    draw.text((ml + (pw - tw) / 2, mt + ph + 86), x_title, font=f_axis_title, fill=(30, 41, 59, 255))

    y_title = "收益达成率（% of Hindsight Optimum）"
    ytw, yth = text_size(draw, y_title, f_axis_title)
    y_img = Image.new("RGBA", (ytw + 20, yth + 20), (0, 0, 0, 0))
    yd = ImageDraw.Draw(y_img)
    yd.text((10, 8), y_title, font=f_axis_title, fill=(30, 41, 59, 255))
    y_rot = y_img.rotate(90, expand=True)
    img.alpha_composite(y_rot, (54, int(mt + (ph - y_rot.height) / 2)))

    # Milestone markers on Best-so-far Test curve
    draw = ImageDraw.Draw(img, "RGBA")
    key_evs = [1, 11, 28, 34, 67, 97]
    for ev in key_evs:
        if ev in milestones:
            _, _, _, btest, _, _ = milestones[ev]
            cx, cy = sx(ev), sy(btest)
            rad = 13 if ev in (34, 97) else 10
            draw.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=(255, 255, 255, 255), outline=(37, 99, 235, 255), width=5)

    # Annotations (widely separated, zero overlap!)
    # 1) Round 1 (E001) -> bottom-left
    p1 = (sx(1), sy(milestones[1][3]))
    draw.line([p1, (sx(5), sy(86.6))], fill=(100, 116, 139, 255), width=2)
    draw_rounded_badge(
        img, sx(4), sy(86.5),
        ["Round 1 · E001：88.36%", "初始范式探索，略超 Myopic"],
        f_badge_main, f_badge_sub,
        border=(148, 163, 184, 255), anchor="tl",
    )

    # 2) Round 11 (E011) -> upper-left
    draw = ImageDraw.Draw(img, "RGBA")
    p11 = (sx(11), sy(milestones[11][3]))
    draw.line([p11, (sx(13), sy(92.4))], fill=(59, 130, 246, 255), width=2)
    draw_rounded_badge(
        img, sx(9), sy(92.5),
        ["Round 11 · E011：90.82%", "跨范式交叉，首次突破 90%"],
        f_badge_main, f_badge_sub,
        border=(59, 130, 246, 255), anchor="bl",
    )

    # 3) Round 34 (E034) -> mid-center lower band (y=89.6), clearly separated from Round 97
    draw = ImageDraw.Draw(img, "RGBA")
    p34 = (sx(34), sy(milestones[34][3]))
    draw.line([p34, (sx(40), sy(89.8))], fill=(37, 99, 235, 255), width=3)
    draw_rounded_badge(
        img, sx(37), sy(89.7),
        ["Round 34 · E034：93.65%（关键跃迁 +2.78%）", "诊断精修发现「严格分裂流体前向推演」机制"],
        f_badge_main, f_badge_sub,
        bg=(239, 246, 255, 250), border=(37, 99, 235, 255), text_color=(29, 78, 216, 255), anchor="tl",
    )

    # 4) Round 97 (E097) -> right side (y=92.2), well above & right of Round 34
    draw = ImageDraw.Draw(img, "RGBA")
    p97 = (sx(97), sy(milestones[97][3]))
    draw.line([p97, (sx(92), sy(92.4))], fill=(29, 78, 216, 255), width=3)
    draw_rounded_badge(
        img, sx(98.5), sy(92.3),
        ["Round 97 · E097 冠军：94.23%（零求解器）", "Case 1: 94.88% | Case 2: 93.57%（反超 BPC-S）"],
        f_badge_main, f_badge_sub,
        bg=(239, 246, 255, 250), border=(29, 78, 216, 255), text_color=(30, 58, 138, 255), anchor="tr",
    )

    # Legend bar
    draw = ImageDraw.Draw(img, "RGBA")
    ly = 210
    lx = ml
    draw.line([(lx, ly + 16), (lx + 54, ly + 16)], fill=(37, 99, 235, 255), width=7)
    draw.ellipse([lx + 19, ly + 8, lx + 35, ly + 24], fill=(255, 255, 255, 255), outline=(37, 99, 235, 255), width=4)
    lbl1 = "累计最优 · 留出测试集均分（60条）"
    draw.text((lx + 68, ly), lbl1, font=f_legend, fill=(15, 23, 42, 255))
    lx += 68 + text_size(draw, lbl1, f_legend)[0] + 54

    draw_dashed_line(draw, (lx, ly + 16), (lx + 54, ly + 16), (124, 58, 237, 255), width=4, dash=12, gap=8)
    lbl2 = "累计最优 · 训练集均分（40条，重合=无过拟合）"
    draw.text((lx + 68, ly), lbl2, font=f_legend, fill=(15, 23, 42, 255))
    lx += 68 + text_size(draw, lbl2, f_legend)[0] + 54

    composite_layer(
        img,
        lambda d: d.ellipse([lx + 16, ly + 7, lx + 34, ly + 25], fill=(100, 116, 139, 110), outline=(71, 85, 105, 180), width=2),
    )
    draw = ImageDraw.Draw(img, "RGBA")
    lbl3 = "单轮有效候选策略得分（共 90/100 有效）"
    draw.text((lx + 48, ly), lbl3, font=f_legend, fill=(71, 85, 105, 255))

    # Footer note
    note = f"注：总耗时 925.7s（5 并发），消耗 631,631 tokens；纵轴聚焦 83%~96.5%，另有 {below_count} 个早期低分探索点（<83%）未在视野内显示。Case 2 上 E097 (93.57%) 已反超带 LP 的 BPC-S (93.31%)。"
    draw.text((ml, H - 56), note, font=f_note, fill=(100, 116, 139, 255))

    out = img.resize((W // 2, H // 2), Image.Resampling.LANCZOS)
    out_path = FIG_DIR / "pop100_evolution_curve.png"
    out.convert("RGB").save(out_path, optimize=True)
    print(f"Saved {out_path} ({out.size[0]}x{out.size[1]})")


def build_model_compare_chart():
    mc = json.loads((RES_DIR / "model_comparison_glm53_vs_flash.json").read_text())
    evo = mc["evolution_20rounds_from_scratch"]

    vp = json.loads((RES_DIR / "vs_paper_methods.json").read_text())["bench1_N20_heldout"]
    ref_bpcm = (vp["Case1_平稳到达"]["BPC-M (论文 Eq.12 LP)"]["ratio_pct"] + vp["Case2_短途先来"]["BPC-M (论文 Eq.12 LP)"]["ratio_pct"]) / 2.0
    ref_e097 = 94.23  # (94.88 + 93.57) / 2 = 94.225 -> 94.23%
    ref_mp = (vp["Case1_平稳到达"]["MP (Myopic)"]["ratio_pct"] + vp["Case2_短途先来"]["MP (Myopic)"]["ratio_pct"]) / 2.0

    def extract_series(key: str):
        hist = evo[key]["history"]
        best_tr = 0.0
        best_te = 0.0
        curve = []
        pts = []
        for idx, r in enumerate(hist, 1):
            if r.get("status") == "ok" and r.get("train_score") is not None:
                ts = r["train_score"]
                te = r["test_score"]
                pts.append((idx, te))
                if ts > best_tr:
                    best_tr = ts
                    best_te = te
            if best_te > 0:
                curve.append((idx, best_te))
        return curve, pts

    c_pro, p_pro = extract_series("glm-5.3 (req=glm-5)")
    c_flash, p_flash = extract_series("glm-5.3-flash (req=glm-4.7)")

    W, H = 2800, 1520
    img = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img, "RGBA")

    f_title = load_font(52, bold=True)
    f_subtitle = load_font(29, bold=False)
    f_axis_title = load_font(29, bold=True)
    f_tick = load_font(25, bold=False)
    f_legend = load_font(25, bold=False)
    f_ref = load_font(23, bold=True)
    f_badge_main = load_font(24, bold=True)
    f_badge_sub = load_font(20, bold=False)
    f_note = load_font(21, bold=False)

    ml, mr, mt, mb = 200, 440, 280, 190
    pw, ph = W - ml - mr, H - mt - mb

    x_min, x_max = 0.5, 20.6
    y_min, y_max = 78.0, 96.5

    def sx(x: float) -> float:
        return ml + (x - x_min) / (x_max - x_min) * pw

    def sy(y: float) -> float:
        return mt + (y_max - y) / (y_max - y_min) * ph

    draw.text((ml, 54), "同起跑线 20 轮从零进化曲线：glm-5.3 vs glm-5.3-flash", font=f_title, fill=(15, 23, 42, 255))
    draw.text(
        (ml, 124),
        "无种子冷启动 · 相同 Prompt 与评测集 | 60 条留出测试集收益达成率（% HO）随进化轮次变化",
        font=f_subtitle,
        fill=(71, 85, 105, 255),
    )

    draw.rounded_rectangle(
        [ml, mt, ml + pw, mt + ph],
        radius=16,
        fill=(248, 250, 252, 255),
        outline=(226, 232, 240, 255),
        width=2,
    )

    for yt in [78, 80, 82, 84, 86, 88, 90, 92, 94, 96]:
        yy = sy(yt)
        draw.line([(ml + 2, yy), (ml + pw - 2, yy)], fill=(226, 232, 240, 255), width=2)
        lbl = f"{yt}%"
        tw, th = text_size(draw, lbl, f_tick)
        draw.text((ml - tw - 22, yy - th / 2 - 2), lbl, font=f_tick, fill=(71, 85, 105, 255))

    for xt in range(1, 21):
        xx = sx(xt)
        if xt % 2 == 0 or xt == 1:
            draw.line([(xx, mt + 2), (xx, mt + ph - 2)], fill=(226, 232, 240, 200), width=2)
        lbl = str(xt)
        tw, th = text_size(draw, lbl, f_tick)
        draw.text((xx - tw / 2, mt + ph + 20), lbl, font=f_tick, fill=(71, 85, 105, 255))

    # Shaded gap between glm-5.3 and glm-5.3-flash from round 6..20 (properly alpha-composited!)
    pro_map = dict(c_pro)
    fl_map = dict(c_flash)
    gap_top = [(sx(x), sy(pro_map[x])) for x in range(6, 21) if x in pro_map and x in fl_map]
    gap_bot = [(sx(x), sy(fl_map[x])) for x in range(20, 5, -1) if x in pro_map and x in fl_map]
    if gap_top and gap_bot:
        composite_layer(img, lambda d: d.polygon(gap_top + gap_bot, fill=(37, 99, 235, 32)))

    # Scatter valid single-round points (alpha-composited)
    def draw_pts(d):
        for idx, te in p_pro:
            if te >= y_min:
                cx, cy = sx(idx), sy(te)
                d.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], fill=(59, 130, 246, 120), outline=(37, 99, 235, 200), width=2)
        for idx, te in p_flash:
            if te >= y_min:
                cx, cy = sx(idx), sy(te)
                d.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], fill=(248, 113, 113, 120), outline=(220, 38, 38, 200), width=2)

    composite_layer(img, draw_pts)

    # Reference lines
    draw = ImageDraw.Draw(img, "RGBA")
    refs = [
        (ref_bpcm, "BPC-M (论文 Eq.12 LP)", f"{ref_bpcm:.2f}%", (5, 150, 105, 255)),
        (ref_e097, "E097 (glm-5.3 100轮)",  f"{ref_e097:.2f}%", (79, 70, 229, 255)),
        (ref_mp,   "MP (Myopic 贪心基线)",   f"{ref_mp:.2f}%",   (71, 85, 105, 255)),
    ]
    for val, name, pct, col in refs:
        yy = sy(val)
        draw_dashed_line(draw, (ml + 4, yy), (ml + pw - 4, yy), col, width=3, dash=16, gap=10)
        draw.line([(ml + pw, yy), (ml + pw + 16, yy)], fill=col, width=2)
        draw.text((ml + pw + 24, yy - 15), f"{pct}  {name}", font=f_ref, fill=col)

    # Best-so-far curves
    flash_vis = [(sx(x), sy(max(y, y_min))) for x, y in c_flash if x >= 3]
    pro_vis = [(sx(x), sy(max(y, y_min))) for x, y in c_pro]

    draw_dashed_line(draw, (sx(2.4), sy(y_min)), (sx(3), sy(fl_map[3])), (220, 38, 38, 220), width=4, dash=10, gap=8)
    draw.line(flash_vis, fill=(220, 38, 38, 255), width=7, joint="curve")
    draw.line(pro_vis, fill=(37, 99, 235, 255), width=7, joint="curve")

    # Axis borders on top
    draw.line([(ml, mt), (ml, mt + ph)], fill=(148, 163, 184, 255), width=3)
    draw.line([(ml, mt + ph), (ml + pw, mt + ph)], fill=(148, 163, 184, 255), width=3)

    x_title = "从零进化循环次数（Round 1 ~ 20）"
    tw, _ = text_size(draw, x_title, f_axis_title)
    draw.text((ml + (pw - tw) / 2, mt + ph + 82), x_title, font=f_axis_title, fill=(30, 41, 59, 255))

    y_title = "留出测试集收益达成率（% HO）"
    ytw, yth = text_size(draw, y_title, f_axis_title)
    y_img = Image.new("RGBA", (ytw + 20, yth + 20), (0, 0, 0, 0))
    yd = ImageDraw.Draw(y_img)
    yd.text((10, 8), y_title, font=f_axis_title, fill=(30, 41, 59, 255))
    y_rot = y_img.rotate(90, expand=True)
    img.alpha_composite(y_rot, (50, int(mt + (ph - y_rot.height) / 2)))

    draw = ImageDraw.Draw(img, "RGBA")
    for x, y in c_pro:
        if x in (1, 5, 6, 20):
            cx, cy = sx(x), sy(y)
            draw.ellipse([cx - 11, cy - 11, cx + 11, cy + 11], fill=(255, 255, 255, 255), outline=(37, 99, 235, 255), width=5)
    for x, y in c_flash:
        if x in (3, 20):
            cx, cy = sx(x), sy(y)
            draw.ellipse([cx - 11, cy - 11, cx + 11, cy + 11], fill=(255, 255, 255, 255), outline=(220, 38, 38, 255), width=5)

    # Gap bracket at round 14
    gx = sx(14)
    gy1, gy2 = sy(pro_map[14]), sy(fl_map[14])
    draw.line([(gx, gy1 + 12), (gx, gy2 - 12)], fill=(29, 78, 216, 255), width=3)
    draw.line([(gx - 10, gy1 + 12), (gx + 10, gy1 + 12)], fill=(29, 78, 216, 255), width=3)
    draw.line([(gx - 10, gy2 - 12), (gx + 10, gy2 - 12)], fill=(29, 78, 216, 255), width=3)
    draw_rounded_badge(
        img, gx + 20, (gy1 + gy2) / 2 - 48,
        ["代差 +3.21%（92.12% vs 88.91%）", "高配 glm-5.3 更快且有效率更高（90% vs 75%）"],
        f_badge_main, f_badge_sub,
        bg=(255, 255, 255, 248), border=(37, 99, 235, 255), text_color=(29, 78, 216, 255), anchor="tl",
    )

    # Badges for round 6 (pro) and round 3 (flash)
    draw = ImageDraw.Draw(img, "RGBA")
    draw.line([(sx(6), sy(pro_map[6])), (sx(6.6), sy(92.8))], fill=(37, 99, 235, 255), width=2)
    draw_rounded_badge(
        img, sx(6), sy(92.75),
        ["glm-5.3 · Round 6 跃升至 92.12%", "自发构建流体影子价机制（耗时仅 197.8s）"],
        f_badge_main, f_badge_sub,
        bg=(239, 246, 255, 250), border=(37, 99, 235, 255), text_color=(29, 78, 216, 255), anchor="bl",
    )

    draw = ImageDraw.Draw(img, "RGBA")
    draw.line([(sx(3), sy(fl_map[3])), (sx(4.8), sy(83.8))], fill=(220, 38, 38, 255), width=2)
    draw_rounded_badge(
        img, sx(4.2), sy(83.8),
        ["glm-5.3-flash · 卡在 88.91%", "第 3 轮后 17 轮零突破（仅比 Myopic 高 0.68%）"],
        f_badge_main, f_badge_sub,
        bg=(254, 242, 242, 250), border=(220, 38, 38, 255), text_color=(185, 28, 28, 255), anchor="tl",
    )

    # Legend
    draw = ImageDraw.Draw(img, "RGBA")
    ly = 205
    lx = ml
    draw.line([(lx, ly + 15), (lx + 52, ly + 15)], fill=(37, 99, 235, 255), width=7)
    lbl1 = "glm-5.3（高配，有效 18/20，197.8s）"
    draw.text((lx + 66, ly), lbl1, font=f_legend, fill=(15, 23, 42, 255))
    lx += 66 + text_size(draw, lbl1, f_legend)[0] + 60

    draw.line([(lx, ly + 15), (lx + 52, ly + 15)], fill=(220, 38, 38, 255), width=7)
    lbl2 = "glm-5.3-flash（轻量，有效 15/20，357.2s）"
    draw.text((lx + 66, ly), lbl2, font=f_legend, fill=(15, 23, 42, 255))
    lx += 66 + text_size(draw, lbl2, f_legend)[0] + 60

    composite_layer(
        img,
        lambda d: d.ellipse([lx + 12, ly + 7, lx + 30, ly + 25], fill=(100, 116, 139, 120), outline=(71, 85, 105, 190), width=2),
    )
    draw = ImageDraw.Draw(img, "RGBA")
    draw.text((lx + 42, ly), "单轮有效评估得分", font=f_legend, fill=(71, 85, 105, 255))

    note = "注：纵轴聚焦 78%~96.5% 核心区间；两个模型早期均有少数 <78% 的冷启动试错点（如 flash Round 2 为 10.16%，Round 6/11 因拒客过多为 0%）。"
    draw.text((ml, H - 52), note, font=f_note, fill=(100, 116, 139, 255))

    out = img.resize((W // 2, H // 2), Image.Resampling.LANCZOS)
    out_path = FIG_DIR / "model_compare_20rounds.png"
    out.convert("RGB").save(out_path, optimize=True)
    print(f"Saved {out_path} ({out.size[0]}x{out.size[1]})")


if __name__ == "__main__":
    build_pop100_chart()
    build_model_compare_chart()
