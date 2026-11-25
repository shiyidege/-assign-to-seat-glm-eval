#!/usr/bin/env python3
"""Generate a clean high-resolution two-phase architecture diagram for the Word report."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path("/Users/xiongzhaoyang/code/assign_to_seat_glm_eval/figures/two_phase_architecture.png")

FONT_BOLD = "/Library/Fonts/STHeiti Medium.ttc"
FONT_REG = "/Library/Fonts/STHeiti Light.ttc"


def font(size: int, bold: bool = False):
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)


def draw_rounded_box(draw, xy, radius, fill, outline, width=3):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def draw_centered_lines(draw, box, lines, fonts, colors, line_gap=8):
    x1, y1, x2, y2 = box
    metrics = []
    total_h = 0
    for txt, fnt in zip(lines, fonts):
        bbox = draw.textbbox((0, 0), txt, font=fnt)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        metrics.append((w, h, bbox[1]))
        total_h += h
    total_h += line_gap * (len(lines) - 1)
    cur_y = y1 + (y2 - y1 - total_h) / 2
    for (txt, fnt, col), (w, h, top_off) in zip(zip(lines, fonts, colors), metrics):
        cur_x = x1 + (x2 - x1 - w) / 2
        draw.text((cur_x, cur_y - top_off), txt, font=fnt, fill=col)
        cur_y += h + line_gap


def draw_arrow(draw, start, end, color="#3A5A80", width=4, head=14):
    import math
    x1, y1 = start
    x2, y2 = end
    draw.line([start, end], fill=color, width=width)
    ang = math.atan2(y2 - y1, x2 - x1)
    p1 = (x2 - head * math.cos(ang - 0.42), y2 - head * math.sin(ang - 0.42))
    p2 = (x2 - head * math.cos(ang + 0.42), y2 - head * math.sin(ang + 0.42))
    draw.polygon([end, p1, p2], fill=color)


def main():
    W, H = 1800, 1020
    img = Image.new("RGB", (W, H), "#FFFFFF")
    draw = ImageDraw.Draw(img)

    # Colors
    NAVY = "#1B365D"
    BLUE = "#2E75B6"
    LIGHT_BLUE = "#EDF4FB"
    PALE_BLUE = "#F7FAFD"
    TEAL = "#1F7A6E"
    LIGHT_TEAL = "#EBF7F5"
    AMBER = "#B86B00"
    LIGHT_AMBER = "#FFF6E6"
    BORDER_GRAY = "#C8D6E5"
    TEXT_DARK = "#1E293B"
    TEXT_MUTED = "#475569"

    # Header band
    draw.rectangle([0, 0, W, 118], fill=NAVY)
    draw.text((54, 24), "高铁 Assign-to-Seat 运筹求解：两阶段实验技术架构全景", font=font(36, True), fill="#FFFFFF")
    draw.text(
        (54, 74),
        "Phase 1：纯 AI 零求解器 Top-K 策略代码进化（Policy as Code）   vs   Phase 2：开源求解器可选组件（solver_toolkit）",
        font=font(21, False),
        fill="#CBD5E1",
    )

    # ================= PHASE 1 CONTAINER =================
    p1_box = (42, 148, 1758, 540)
    draw_rounded_box(draw, p1_box, 18, PALE_BLUE, BLUE, width=3)
    draw.rounded_rectangle([62, 166, 668, 212], radius=8, fill=BLUE)
    draw.text(
        (80, 176),
        "第一阶段：无求解器 Top-K 种群进化（严禁外部优化器）",
        font=font(22, True),
        fill="#FFFFFF",
    )
    draw.text(
        (692, 178),
        "目标：检验大模型仅靠纯 Python 能否离线进化出高水平动态控票策略",
        font=font(19, False),
        fill=TEXT_MUTED,
    )

    # Phase 1 boxes
    b1 = (72, 244, 342, 396)
    b2 = (402, 244, 682, 396)
    b3 = (742, 244, 1022, 396)
    b4 = (1082, 244, 1362, 396)
    b5 = (1422, 244, 1726, 396)

    draw_rounded_box(draw, b1, 14, "#FFFFFF", BLUE, 2)
    draw_centered_lines(
        draw, b1,
        ["Top-6 精英策略池", "4 类算子轮换采样", "探索 / 交叉 / 精修 / 微调"],
        [font(22, True), font(18), font(17)],
        [NAVY, TEXT_DARK, TEXT_MUTED],
    )

    draw_rounded_box(draw, b2, 14, LIGHT_BLUE, BLUE, 2)
    draw_centered_lines(
        draw, b2,
        ["GLM-5 并发代码生成", "5 路并发（glm-5.3）", "输出纯 Python decide()"],
        [font(22, True), font(18), font(17)],
        [NAVY, TEXT_DARK, BLUE],
    )

    draw_rounded_box(draw, b3, 14, "#FFFFFF", BLUE, 2)
    draw_centered_lines(
        draw, b3,
        ["AST 静态审计门禁", "仅允许 Python 标准库", "禁用全部求解器 + 3.5s 超时"],
        [font(22, True), font(18), font(17)],
        [NAVY, TEXT_DARK, TEXT_MUTED],
    )

    draw_rounded_box(draw, b4, 14, "#FFFFFF", BLUE, 2)
    draw_centered_lines(
        draw, b4,
        ["40 条训练路径仿真", "Case1(20) + Case2(20)", "输出得分 + 剩座/流失体检"],
        [font(22, True), font(18), font(17)],
        [NAVY, TEXT_DARK, TEXT_MUTED],
    )

    draw_rounded_box(draw, b5, 14, LIGHT_AMBER, AMBER, 3)
    draw_centered_lines(
        draw, b5,
        ["60 条留出集防过拟合", "冠军 E097：94.22% HO", "耗时 ~0.32s · 线上零成本"],
        [font(22, True), font(20, True), font(17)],
        [AMBER, "#8A4F00", TEXT_DARK],
    )

    for left, right in [(b1, b2), (b2, b3), (b3, b4), (b4, b5)]:
        draw_arrow(draw, (left[2] + 4, 320), (right[0] - 6, 320), color=BLUE, width=4, head=14)

    # Feedback loop arrow under Phase 1
    loop_y = 468
    draw.line([(1222, 396), (1222, loop_y), (207, loop_y)], fill=BLUE, width=3)
    draw_arrow(draw, (207, loop_y), (207, 400), color=BLUE, width=3, head=13)
    draw.rounded_rectangle([475, 444, 1155, 492], radius=10, fill="#FFFFFF", outline=BLUE, width=2)
    draw_centered_lines(
        draw, (475, 444, 1155, 492),
        ["失分诊断反馈（按长度接单/拒单/流失 + 剩座分布）写回下一代 Prompt"],
        [font(17, True)],
        [NAVY],
    )

    # ================= PHASE 2 CONTAINER =================
    p2_box = (42, 576, 1758, 978)
    draw_rounded_box(draw, p2_box, 18, LIGHT_TEAL, TEAL, width=3)
    draw.rounded_rectangle([62, 594, 758, 640], radius=8, fill=TEAL)
    draw.text(
        (80, 604),
        "第二阶段（新增）：开源求解器可选组件（AI 可调用也可不调用）",
        font=font(22, True),
        fill="#FFFFFF",
    )
    draw.text(
        (782, 606),
        "目标：零商业授权费引入 5 大开源后端，量化对比「开源求解器组件 vs 纯 AI」",
        font=font(19, False),
        fill=TEXT_MUTED,
    )

    # Left: AI / Paper Policy
    c1 = (72, 672, 420, 862)
    draw_rounded_box(draw, c1, 14, "#FFFFFF", TEAL, 2)
    draw_centered_lines(
        draw, c1,
        ["决策策略入口（自由裁量）", "① GLM-5 进化策略（可用/可不用）", "② 论文完整方法基准对照", "MP / BPC-S / BPC-M / RDP"],
        [font(22, True), font(18), font(18), font(18, True)],
        [TEAL, TEXT_DARK, TEXT_DARK, NAVY],
        line_gap=10,
    )

    # Middle: AST + solver_toolkit
    c2 = (490, 672, 940, 862)
    draw_rounded_box(draw, c2, 14, "#FFFFFF", TEAL, 3)
    draw_centered_lines(
        draw, c2,
        ["统一可选组件 solver_toolkit.py", "AST 白名单：仅放行标准库 + solver_toolkit", "统一接口 solve_lp(c, A_ub, b_ub, solver=...)", "自动记录 used_toolkit + 超时安全护栏"],
        [font(22, True), font(17), font(17, True), font(17)],
        [NAVY, TEXT_DARK, TEAL, TEXT_MUTED],
        line_gap=10,
    )

    # Middle-right: 5 open-source backends
    c3 = (998, 666, 1358, 870)
    draw_rounded_box(draw, c3, 14, "#FFFFFF", TEAL, 2)
    draw.rounded_rectangle([1014, 678, 1342, 714], radius=8, fill="#D8F1EC")
    draw_centered_lines(draw, (1014, 678, 1342, 714), ["5 大本机开源后端（全部通过）"], [font(18, True)], [TEAL])
    backends = [
        ("GLOP", "OR-Tools LP · 1.5s · 95.43%"),
        ("CLP", "COIN-OR LP · 1.6s · 95.41%"),
        ("HiGHS", "SciPy LP · 1.1s · 95.34%"),
        ("CBC", "COIN-OR MIP · 2.7s · 95.28%"),
        ("SCIP", "ZIB MIP · 7.5s · 95.33%"),
    ]
    y0 = 724
    for name, desc in backends:
        draw.text((1024, y0), f"• {name:<5}", font=font(17, True), fill=NAVY)
        draw.text((1106, y0), desc, font=font(16), fill=TEXT_DARK)
        y0 += 28

    # Right: Result summary
    c4 = (1410, 672, 1726, 862)
    draw_rounded_box(draw, c4, 14, LIGHT_AMBER, AMBER, 3)
    draw_centered_lines(
        draw, c4,
        ["同 60 条留出集公平对决", "最优：BPC-M via GLOP", "95.43% HO（+1.21% vs E097）", "全套开源方案零商业授权费"],
        [font(21, True), font(20, True), font(19, True), font(17)],
        [NAVY, TEAL, "#8A4F00", TEXT_DARK],
        line_gap=10,
    )

    draw_arrow(draw, (c1[2] + 4, 767), (c2[0] - 6, 767), color=TEAL, width=4, head=14)
    draw_arrow(draw, (c2[2] + 4, 767), (c3[0] - 6, 767), color=TEAL, width=4, head=14)
    draw_arrow(draw, (c3[2] + 4, 767), (c4[0] - 6, 767), color=TEAL, width=4, head=14)

    # Bottom note in Phase 2
    draw.rounded_rectangle([72, 898, 1726, 952], radius=10, fill="#FFFFFF", outline=BORDER_GRAY, width=2)
    draw_centered_lines(
        draw, (72, 898, 1726, 952),
        ["核心洞察：纯 AI (E097, 94.22%) 已反超 4/5 版本的论文 BPC-S 且快 3~23 倍；加上开源求解器组件运行 BPC-M/RDP 可再稳步提升 +1.0% ~ +1.2%"],
        [font(18, True)],
        [NAVY],
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, dpi=(220, 220))
    print("Saved:", OUT)


if __name__ == "__main__":
    main()
