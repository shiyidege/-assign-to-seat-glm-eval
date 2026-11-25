#!/usr/bin/env python3
"""Build a polished, publication-grade Word (.docx) technical report for Assign-to-Seat AI eval."""
from pathlib import Path
from lxml import etree
from docx import Document
from docx.shared import Cm, Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn, nsdecls

BASE_DIR = Path("/Users/xiongzhaoyang/code/assign_to_seat_glm_eval")
OUT_DOCX = BASE_DIR / "AI求解高铁Assign-to-Seat运筹问题技术报告.docx"

# Color palette
HEX_NAVY = "1B365D"
HEX_BLUE = "2E75B6"
HEX_TEAL = "1F7A6E"
HEX_AMBER = "9A5B00"
HEX_TEXT = "1F2937"
HEX_MUTED = "5A6778"
HEX_LIGHT_BLUE = "EEF4FA"
HEX_ZEBRA = "F7FAFD"
HEX_HIGHLIGHT_GREEN = "E8F6F3"
HEX_HIGHLIGHT_GOLD = "FFF8E6"
HEX_CODE_BG = "F4F6F9"
HEX_BORDER = "D5DEE8"

RGB_NAVY = RGBColor(0x1B, 0x36, 0x5D)
RGB_BLUE = RGBColor(0x2E, 0x75, 0xB6)
RGB_TEAL = RGBColor(0x1F, 0x7A, 0x6E)
RGB_AMBER = RGBColor(0x9A, 0x5B, 0x00)
RGB_TEXT = RGBColor(0x1F, 0x29, 0x37)
RGB_MUTED = RGBColor(0x5A, 0x67, 0x78)
RGB_WHITE = RGBColor(0xFF, 0xFF, 0xFF)

FONT_CN = "微软雅黑"
FONT_EN = "Calibri"
FONT_CODE = "Consolas"

M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


# ==============================================================================
# Low-level XML styling helpers
# ==============================================================================
def set_run_font(run, size_pt=10.5, bold=False, italic=False, color=RGB_TEXT, font_en=FONT_EN, font_cn=FONT_CN):
    run.font.size = Pt(size_pt)
    run.bold = bold
    run.italic = italic
    run.font.color.rgb = color
    run.font.name = font_en
    rPr = run._r.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.insert(0, rFonts)
    rFonts.set(qn("w:ascii"), font_en)
    rFonts.set(qn("w:hAnsi"), font_en)
    rFonts.set(qn("w:eastAsia"), font_cn)
    rFonts.set(qn("w:cs"), font_cn)


def set_cell_shading(cell, fill_hex):
    tcPr = cell._tc.get_or_add_tcPr()
    for child in list(tcPr):
        if child.tag == qn("w:shd"):
            tcPr.remove(child)
    tcPr.append(parse_xml(f'<w:shd {nsdecls("w")} w:val="clear" w:color="auto" w:fill="{fill_hex}"/>'))


def set_cell_margins(cell, top=80, bottom=80, left=110, right=110):
    tcPr = cell._tc.get_or_add_tcPr()
    for child in list(tcPr):
        if child.tag == qn("w:tcMar"):
            tcPr.remove(child)
    tcMar = OxmlElement("w:tcMar")
    for side, val in [("top", top), ("bottom", bottom), ("left", left), ("right", right)]:
        node = OxmlElement(f"w:{side}")
        node.set(qn("w:w"), str(val))
        node.set(qn("w:type"), "dxa")
        tcMar.append(node)
    tcPr.append(tcMar)


def set_table_borders(table, color=HEX_BORDER, sz="4", inside_v="none"):
    tblPr = table._tbl.tblPr
    for child in list(tblPr):
        if child.tag == qn("w:tblBorders"):
            tblPr.remove(child)
    borders_xml = f"""
    <w:tblBorders {nsdecls("w")}>
      <w:top w:val="single" w:sz="8" w:space="0" w:color="{HEX_NAVY}"/>
      <w:bottom w:val="single" w:sz="8" w:space="0" w:color="{HEX_NAVY}"/>
      <w:insideH w:val="single" w:sz="{sz}" w:space="0" w:color="{color}"/>
      <w:left w:val="none"/>
      <w:right w:val="none"/>
      <w:insideV w:val="{inside_v}" w:sz="{sz}" w:space="0" w:color="{color}"/>
    </w:tblBorders>
    """
    tblPr.append(parse_xml(borders_xml))


def set_cell_borders(cell, left=None, right=None, top=None, bottom=None):
    tcPr = cell._tc.get_or_add_tcPr()
    for child in list(tcPr):
        if child.tag == qn("w:tcBorders"):
            tcPr.remove(child)
    tcBorders = OxmlElement("w:tcBorders")
    for side, spec in [("top", top), ("left", left), ("bottom", bottom), ("right", right)]:
        node = OxmlElement(f"w:{side}")
        if spec is None:
            node.set(qn("w:val"), "none")
        else:
            val, sz, col = spec
            node.set(qn("w:val"), val)
            node.set(qn("w:sz"), str(sz))
            node.set(qn("w:space"), "0")
            node.set(qn("w:color"), col)
        tcBorders.append(node)
    tcPr.append(tcBorders)


def set_row_cant_split(row):
    trPr = row._tr.get_or_add_trPr()
    trPr.append(OxmlElement("w:cantSplit"))


def set_row_header(row):
    trPr = row._tr.get_or_add_trPr()
    trPr.append(OxmlElement("w:tblHeader"))


def add_para_bottom_border(paragraph, color=HEX_BLUE, sz="12"):
    pPr = paragraph._p.get_or_add_pPr()
    pBdr = parse_xml(
        f'<w:pBdr {nsdecls("w")}><w:bottom w:val="single" w:sz="{sz}" w:space="4" w:color="{color}"/></w:pBdr>'
    )
    pPr.append(pBdr)


def add_page_number_fields(paragraph):
    run1 = paragraph.add_run("第 ")
    set_run_font(run1, size_pt=9, color=RGB_MUTED)

    for fld_name in ["PAGE"]:
        r = paragraph.add_run()
        set_run_font(r, size_pt=9, color=RGB_MUTED)
        fld1 = parse_xml(f'<w:fldChar {nsdecls("w")} w:fldCharType="begin"/>')
        instr = parse_xml(f'<w:instrText {nsdecls("w")} xml:space="preserve"> {fld_name} </w:instrText>')
        fld2 = parse_xml(f'<w:fldChar {nsdecls("w")} w:fldCharType="separate"/>')
        fld3 = parse_xml(f'<w:fldChar {nsdecls("w")} w:fldCharType="end"/>')
        r._r.append(fld1)
        r._r.append(instr)
        r._r.append(fld2)
        r._r.append(fld3)

    run2 = paragraph.add_run(" 页 / 共 ")
    set_run_font(run2, size_pt=9, color=RGB_MUTED)

    for fld_name in ["NUMPAGES"]:
        r = paragraph.add_run()
        set_run_font(r, size_pt=9, color=RGB_MUTED)
        fld1 = parse_xml(f'<w:fldChar {nsdecls("w")} w:fldCharType="begin"/>')
        instr = parse_xml(f'<w:instrText {nsdecls("w")} xml:space="preserve"> {fld_name} </w:instrText>')
        fld2 = parse_xml(f'<w:fldChar {nsdecls("w")} w:fldCharType="separate"/>')
        fld3 = parse_xml(f'<w:fldChar {nsdecls("w")} w:fldCharType="end"/>')
        r._r.append(fld1)
        r._r.append(instr)
        r._r.append(fld2)
        r._r.append(fld3)

    run3 = paragraph.add_run(" 页")
    set_run_font(run3, size_pt=9, color=RGB_MUTED)


# ==============================================================================
# Native Word OMML Math Formula Builder
# ==============================================================================
def m_el(tag, *children):
    el = etree.Element(f"{{{M_NS}}}{tag}")
    for c in children:
        if c is not None:
            el.append(c)
    return el


def m_r(text, normal=False):
    """OMML math run."""
    r = m_el("r")
    rPr_m = m_el("rPr")
    if normal:
        nor = m_el("nor")
        rPr_m.append(nor)
    r.append(rPr_m)
    rPr_w = etree.Element(f"{{{W_NS}}}rPr")
    rFonts = etree.Element(f"{{{W_NS}}}rFonts")
    rFonts.set(f"{{{W_NS}}}ascii", "Cambria Math")
    rFonts.set(f"{{{W_NS}}}hAnsi", "Cambria Math")
    rFonts.set(f"{{{W_NS}}}eastAsia", FONT_CN)
    rPr_w.append(rFonts)
    sz = etree.Element(f"{{{W_NS}}}sz")
    sz.set(f"{{{W_NS}}}val", "22")
    rPr_w.append(sz)
    r.append(rPr_w)
    t = m_el("t")
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    t.text = text
    r.append(t)
    return r


def m_frac(num_nodes, den_nodes):
    return m_el("f", m_el("num", *num_nodes), m_el("den", *den_nodes))


def m_sub(base_nodes, sub_nodes):
    return m_el("sSub", m_el("e", *base_nodes), m_el("sub", *sub_nodes))


def m_sup(base_nodes, sup_nodes):
    return m_el("sSup", m_el("e", *base_nodes), m_el("sup", *sup_nodes))


def m_subsup(base_nodes, sub_nodes, sup_nodes):
    return m_el("sSubSup", m_el("e", *base_nodes), m_el("sub", *sub_nodes), m_el("sup", *sup_nodes))


def m_delim(inner_nodes, beg="(", end=")"):
    dPr = m_el("dPr")
    begChr = m_el("begChr")
    begChr.set(f"{{{M_NS}}}val", beg)
    endChr = m_el("endChr")
    endChr.set(f"{{{M_NS}}}val", end)
    dPr.append(begChr)
    dPr.append(endChr)
    return m_el("d", dPr, m_el("e", *inner_nodes))


def m_limlow(base_nodes, lim_nodes):
    return m_el("limLow", m_el("e", *base_nodes), m_el("lim", *lim_nodes))


def add_formula_img(doc, formula_png: Path, caption: str = None):
    """Embed a 300-DPI publication-style formula card PNG (100% consistent across Word/WPS/Pages/Feishu/WeChat/QuickLook)."""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(3)
    p.paragraph_format.space_after = Pt(2 if caption else 7)
    p.paragraph_format.keep_with_next = bool(caption)
    p.add_run().add_picture(str(formula_png), width=Cm(16.5))

    if caption:
        pc = doc.add_paragraph()
        pc.paragraph_format.space_before = Pt(1)
        pc.paragraph_format.space_after = Pt(8)
        pc.paragraph_format.left_indent = Cm(0.25)
        pc.paragraph_format.line_spacing = 1.22
        rc = pc.add_run(caption)
        set_run_font(rc, size_pt=9, italic=False, color=RGB_MUTED)


# ==============================================================================
# High-level document component builders
# ==============================================================================
def add_h1(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(16)
    p.paragraph_format.space_after = Pt(8)
    p.paragraph_format.keep_with_next = True
    r = p.add_run(text)
    set_run_font(r, size_pt=15.5, bold=True, color=RGB_NAVY)
    add_para_bottom_border(p, color=HEX_BLUE, sz="12")
    return p


def add_h2(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(12)
    p.paragraph_format.space_after = Pt(5)
    p.paragraph_format.keep_with_next = True
    r_bar = p.add_run("▎ ")
    set_run_font(r_bar, size_pt=12.5, bold=True, color=RGB_BLUE)
    r = p.add_run(text)
    set_run_font(r, size_pt=12.5, bold=True, color=RGB_NAVY)
    return p


def add_h3(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.keep_with_next = True
    r = p.add_run(text)
    set_run_font(r, size_pt=11, bold=True, color=RGB_TEAL)
    return p


def add_body(doc, segments, space_after=6, left_indent=0):
    """segments: list of str or (str, bold, color, code)."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = 1.32
    if left_indent:
        p.paragraph_format.left_indent = Cm(left_indent)
    if isinstance(segments, str):
        segments = [(segments, False, RGB_TEXT, False)]
    for item in segments:
        if isinstance(item, str):
            txt, bold, col, is_code = item, False, RGB_TEXT, False
        else:
            txt = item[0]
            bold = item[1] if len(item) > 1 else False
            col = item[2] if len(item) > 2 else RGB_TEXT
            is_code = item[3] if len(item) > 3 else False
        r = p.add_run(txt)
        if is_code:
            set_run_font(r, size_pt=9.5, bold=bold, color=RGB_NAVY, font_en=FONT_CODE, font_cn=FONT_CN)
        else:
            set_run_font(r, size_pt=10.5, bold=bold, color=col)
    return p


def add_bullet(doc, lead_bold, rest_segments, space_after=4):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.65)
    p.paragraph_format.first_line_indent = Cm(-0.38)
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = 1.28

    rb = p.add_run("●  ")
    set_run_font(rb, size_pt=8.5, bold=True, color=RGB_BLUE)

    if lead_bold:
        rl = p.add_run(lead_bold)
        set_run_font(rl, size_pt=10.2, bold=True, color=RGB_NAVY)

    if isinstance(rest_segments, str):
        rest_segments = [(rest_segments, False, RGB_TEXT, False)]
    for item in rest_segments:
        if isinstance(item, str):
            txt, bold, col, is_code = item, False, RGB_TEXT, False
        else:
            txt = item[0]
            bold = item[1] if len(item) > 1 else False
            col = item[2] if len(item) > 2 else RGB_TEXT
            is_code = item[3] if len(item) > 3 else False
        r = p.add_run(txt)
        if is_code:
            set_run_font(r, size_pt=9.3, bold=bold, color=RGB_NAVY, font_en=FONT_CODE, font_cn=FONT_CN)
        else:
            set_run_font(r, size_pt=10.2, bold=bold, color=col)
    return p


def add_callout(doc, title, paragraphs_list, accent_hex=HEX_BLUE, bg_hex=HEX_LIGHT_BLUE):
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False
    tbl.columns[0].width = Cm(16.6)
    cell = tbl.cell(0, 0)
    cell.width = Cm(16.6)
    set_row_cant_split(tbl.rows[0])
    set_cell_shading(cell, bg_hex)
    set_cell_margins(cell, top=110, bottom=110, left=170, right=150)
    set_cell_borders(cell, left=("single", 24, accent_hex))

    p0 = cell.paragraphs[0]
    p0.paragraph_format.space_before = Pt(0)
    p0.paragraph_format.space_after = Pt(4)
    rt = p0.add_run(title)
    accent_rgb = RGB_TEAL if accent_hex == HEX_TEAL else (RGB_AMBER if accent_hex == HEX_AMBER else RGB_NAVY)
    set_run_font(rt, size_pt=10.5, bold=True, color=accent_rgb)

    for idx, segs in enumerate(paragraphs_list):
        p = cell.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(3 if idx < len(paragraphs_list) - 1 else 0)
        p.paragraph_format.line_spacing = 1.28
        if isinstance(segs, str):
            segs = [(segs, False, RGB_TEXT, False)]
        for item in segs:
            if isinstance(item, str):
                txt, bold, col, is_code = item, False, RGB_TEXT, False
            else:
                txt = item[0]
                bold = item[1] if len(item) > 1 else False
                col = item[2] if len(item) > 2 else RGB_TEXT
                is_code = item[3] if len(item) > 3 else False
            r = p.add_run(txt)
            if is_code:
                set_run_font(r, size_pt=9.2, bold=bold, color=RGB_NAVY, font_en=FONT_CODE, font_cn=FONT_CN)
            else:
                set_run_font(r, size_pt=9.8, bold=bold, color=col)

    sp = doc.add_paragraph()
    sp.paragraph_format.space_before = Pt(0)
    sp.paragraph_format.space_after = Pt(4)


def add_code_block(doc, code_text, title=None):
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False
    tbl.columns[0].width = Cm(16.6)
    cell = tbl.cell(0, 0)
    cell.width = Cm(16.6)
    set_row_cant_split(tbl.rows[0])
    set_cell_shading(cell, HEX_CODE_BG)
    set_cell_margins(cell, top=100, bottom=100, left=150, right=140)
    set_cell_borders(
        cell,
        left=("single", 14, HEX_NAVY),
        top=("single", 4, HEX_BORDER),
        bottom=("single", 4, HEX_BORDER),
        right=("single", 4, HEX_BORDER),
    )

    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.15
    if title:
        rt = p.add_run(title + "\n")
        set_run_font(rt, size_pt=9.0, bold=True, color=RGB_BLUE, font_en=FONT_EN, font_cn=FONT_CN)
    rc = p.add_run(code_text.strip())
    set_run_font(rc, size_pt=8.7, color=RGB_NAVY, font_en=FONT_CODE, font_cn=FONT_CN)

    sp = doc.add_paragraph()
    sp.paragraph_format.space_before = Pt(0)
    sp.paragraph_format.space_after = Pt(5)


def add_styled_table(
    doc,
    headers,
    rows,
    col_widths_cm,
    alignments=None,
    highlight_rows=None,
    font_size=9.2,
    header_bg=HEX_NAVY,
):
    """highlight_rows: dict {row_idx_0based: (bg_hex, bold_bool)}"""
    highlight_rows = highlight_rows or {}
    tbl = doc.add_table(rows=1 + len(rows), cols=len(headers))
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False
    set_table_borders(tbl, color=HEX_BORDER, sz="4", inside_v="none")

    # Header row
    hdr_row = tbl.rows[0]
    set_row_header(hdr_row)
    set_row_cant_split(hdr_row)
    for c_idx, h_text in enumerate(headers):
        cell = hdr_row.cells[c_idx]
        cell.width = Cm(col_widths_cm[c_idx])
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        set_cell_shading(cell, header_bg)
        set_cell_margins(cell, top=85, bottom=85, left=85, right=85)
        p = cell.paragraphs[0]
        p.alignment = alignments[c_idx] if alignments else WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(h_text)
        set_run_font(r, size_pt=font_size, bold=True, color=RGB_WHITE)

    # Data rows
    for r_idx, row_vals in enumerate(rows):
        row = tbl.rows[r_idx + 1]
        set_row_cant_split(row)
        hl = highlight_rows.get(r_idx)
        bg = hl[0] if hl else (HEX_ZEBRA if r_idx % 2 == 1 else "FFFFFF")
        is_hl_bold = hl[1] if hl else False
        for c_idx, val in enumerate(row_vals):
            cell = row.cells[c_idx]
            cell.width = Cm(col_widths_cm[c_idx])
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            set_cell_shading(cell, bg)
            set_cell_margins(cell, top=65, bottom=65, left=85, right=85)
            p = cell.paragraphs[0]
            p.alignment = alignments[c_idx] if alignments else WD_ALIGN_PARAGRAPH.LEFT
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.18
            txt = str(val)
            bold_flag = is_hl_bold or (c_idx == 0 and txt.startswith("**"))
            if txt.startswith("**") and txt.endswith("**"):
                txt = txt[2:-2]
                bold_flag = True
            col_rgb = RGB_NAVY if (bold_flag and hl) else RGB_TEXT
            r = p.add_run(txt)
            set_run_font(r, size_pt=font_size, bold=bold_flag, color=col_rgb)

    sp = doc.add_paragraph()
    sp.paragraph_format.space_before = Pt(0)
    sp.paragraph_format.space_after = Pt(5)
    return tbl


def add_figure(doc, img_path: Path, caption: str, width_cm=16.2):
    p_img = doc.add_paragraph()
    p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_img.paragraph_format.space_before = Pt(4)
    p_img.paragraph_format.space_after = Pt(4)
    p_img.paragraph_format.keep_with_next = True
    run = p_img.add_run()
    run.add_picture(str(img_path), width=Cm(width_cm))

    p_cap = doc.add_paragraph()
    p_cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_cap.paragraph_format.space_before = Pt(0)
    p_cap.paragraph_format.space_after = Pt(9)
    r = p_cap.add_run(caption)
    set_run_font(r, size_pt=9.2, bold=False, color=RGB_MUTED)


def add_kpi_strip(doc, items):
    """items: list of (label, big_value, subtext, accent_hex, bg_hex)."""
    tbl = doc.add_table(rows=1, cols=len(items))
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False
    w = 16.6 / len(items)
    set_row_cant_split(tbl.rows[0])
    for i, (label, big_val, sub, accent_hex, bg_hex) in enumerate(items):
        cell = tbl.cell(0, i)
        cell.width = Cm(w)
        set_cell_shading(cell, bg_hex)
        set_cell_margins(cell, top=110, bottom=110, left=100, right=100)
        set_cell_borders(
            cell,
            top=("single", 18, accent_hex),
            left=("single", 6, "FFFFFF"),
            right=("single", 6, "FFFFFF"),
            bottom=("single", 6, HEX_BORDER),
        )
        p1 = cell.paragraphs[0]
        p1.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p1.paragraph_format.space_before = Pt(0)
        p1.paragraph_format.space_after = Pt(3)
        r1 = p1.add_run(label)
        set_run_font(r1, size_pt=8.8, bold=True, color=RGB_MUTED)

        p2 = cell.add_paragraph()
        p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p2.paragraph_format.space_before = Pt(0)
        p2.paragraph_format.space_after = Pt(3)
        r2 = p2.add_run(big_val)
        col = RGB_TEAL if accent_hex == HEX_TEAL else (RGB_AMBER if accent_hex == HEX_AMBER else RGB_NAVY)
        set_run_font(r2, size_pt=14.5, bold=True, color=col)

        p3 = cell.add_paragraph()
        p3.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p3.paragraph_format.space_before = Pt(0)
        p3.paragraph_format.space_after = Pt(0)
        r3 = p3.add_run(sub)
        set_run_font(r3, size_pt=8.3, color=RGB_TEXT)

    sp = doc.add_paragraph()
    sp.paragraph_format.space_before = Pt(0)
    sp.paragraph_format.space_after = Pt(6)


# ==============================================================================
# Build Full Document
# ==============================================================================
def build():
    doc = Document()

    # Page setup: A4, comfortable margins
    sec = doc.sections[0]
    sec.page_width = Cm(21.0)
    sec.page_height = Cm(29.7)
    sec.top_margin = Cm(2.1)
    sec.bottom_margin = Cm(2.1)
    sec.left_margin = Cm(2.2)
    sec.right_margin = Cm(2.2)
    sec.different_first_page_header_footer = True

    # Running Header & Footer (from page 2 onwards)
    hdr = sec.header
    hp = hdr.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    hr = hp.add_run("AI 求解高铁 Assign-to-Seat 收益管理运筹问题 · 技术实证报告")
    set_run_font(hr, size_pt=8.8, color=RGB_MUTED)
    add_para_bottom_border(hp, color=HEX_BORDER, sz="4")

    ftr = sec.footer
    fp = ftr.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_page_number_fields(fp)

    # Set Normal style baseline
    normal_style = doc.styles["Normal"]
    normal_style.font.name = FONT_EN
    normal_style.font.size = Pt(10.5)
    normal_style.font.color.rgb = RGB_TEXT

    # ==========================================================================
    # COVER PAGE
    # ==========================================================================
    banner = doc.add_table(rows=1, cols=1)
    banner.alignment = WD_TABLE_ALIGNMENT.CENTER
    banner.autofit = False
    banner.columns[0].width = Cm(16.6)
    bc = banner.cell(0, 0)
    bc.width = Cm(16.6)
    set_cell_shading(bc, HEX_NAVY)
    set_cell_margins(bc, top=220, bottom=220, left=240, right=240)
    set_cell_borders(bc, bottom=("single", 30, HEX_BLUE))

    bp0 = bc.paragraphs[0]
    bp0.paragraph_format.space_before = Pt(0)
    bp0.paragraph_format.space_after = Pt(6)
    br0 = bp0.add_run("TECHNICAL EVALUATION REPORT  ·  OPERATIONS RESEARCH × LLM")
    set_run_font(br0, size_pt=9.5, bold=True, color=RGBColor(0x93, 0xC5, 0xFD))

    bp1 = bc.add_paragraph()
    bp1.paragraph_format.space_before = Pt(2)
    bp1.paragraph_format.space_after = Pt(8)
    br1 = bp1.add_run("AI 求解高铁 Assign-to-Seat 收益管理问题\n全量技术实证报告")
    set_run_font(br1, size_pt=22, bold=True, color=RGB_WHITE)

    bp2 = bc.add_paragraph()
    bp2.paragraph_format.space_before = Pt(0)
    bp2.paragraph_format.space_after = Pt(0)
    br2 = bp2.add_run("从「纯大模型零求解器进化」到「开源求解器可选组件」的两阶段深度对比研究")
    set_run_font(br2, size_pt=12, bold=False, color=RGBColor(0xE2, 0xE8, 0xF0))

    sp = doc.add_paragraph()
    sp.paragraph_format.space_before = Pt(14)
    sp.paragraph_format.space_after = Pt(6)

    # Executive summary card on cover
    add_callout(
        doc,
        "报告核心定位与阅读导览",
        [
            [
                ("本报告围绕高铁动态控票与排座经典运筹论文 ", False),
                ("Assign-to-Seat: Dynamic Capacity Control for Selling High-Speed Train Tickets", True, RGB_NAVY),
                ("（Feng Zhu, Shaoxuan Liu, Rowan Wang, Zizhuo Wang），系统回答两个工程界最关心的问题：", False),
            ],
            [
                ("问题一（第一阶段）：", True, RGB_BLUE),
                ("完全不依赖任何商业或开源运筹求解器，只靠大模型（智谱 GLM-5）+ 仿真/校验反馈闭环，究竟能把这类高难度运筹问题解到什么水平？", False),
            ],
            [
                ("问题二（第二阶段新增）：", True, RGB_TEAL),
                ("如果为 AI 配上一个免费、轻量的「开源求解器可选组件」（封装 OR-Tools GLOP/CLP/CBC/SCIP 与 SciPy HiGHS），允许 AI 自由决定用或不用，效果相对纯 AI 能提升多少？AI 自主调用工具时会踩哪些真实工程坑？", False),
            ],
        ],
        accent_hex=HEX_BLUE,
        bg_hex=HEX_LIGHT_BLUE,
    )

    sp2 = doc.add_paragraph()
    sp2.paragraph_format.space_before = Pt(8)
    sp2.paragraph_format.space_after = Pt(4)

    # Cover Metadata Table
    meta_rows = [
        ["目标复现论文", "Assign-to-Seat: Dynamic Capacity Control for Selling High-Speed Train Tickets"],
        ["第一阶段技术路线", "纯 AI 零求解器：静态排座校验闭环 + 动态控票 100 轮 Top-6 种群代码进化（Policy as Code）"],
        ["第二阶段新增路线", "开源求解器可选组件 solver_toolkit（OR-Tools GLOP / CLP / CBC / SCIP + SciPy HiGHS）"],
        ["评测模型档位", "智谱 GLM Coding Plan：glm-5.3（主力高配版）vs glm-5.3-flash（同系列轻量版）"],
        ["核心量化成果", "纯 AI 零求解器 E097 达 94.22% HO（+5.99% vs 贪心）；开源组件 BPC-M via GLOP 达 95.43% HO（+1.21% vs 纯 AI）"],
        ["代码与原始数据仓库", "https://github.com/shiyidege/-assign-to-seat-glm-eval"],
        ["报告版本与日期", "v2.0（含 Phase 1 全量 + Phase 2 开源求解器组件新增实测）  ·  2026 年 11 月"],
    ]
    add_styled_table(
        doc,
        ["项目要素", "说明"],
        meta_rows,
        [4.5, 12.1],
        alignments=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.LEFT],
        font_size=9.5,
        header_bg=HEX_NAVY,
    )

    # ==========================================================================
    # CHAPTER 1: EXECUTIVE SUMMARY
    # ==========================================================================
    p_ch1 = add_h1(doc, "一、执行摘要与核心实证结论")
    p_ch1.paragraph_format.page_break_before = True

    add_kpi_strip(
        doc,
        [
            ("静态非 NSE 排座", "98.9%–100%", "GLM-5 校验闭环\n3 算例全面反超贪心", HEX_BLUE, HEX_LIGHT_BLUE),
            ("纯 AI 零求解器冠军", "94.22% HO", "100 轮进化 E097\n比 Myopic +5.99% · 0.32s", HEX_AMBER, HEX_HIGHLIGHT_GOLD),
            ("开源求解器可选组件", "95.43% HO", "BPC-M via GLOP\n比纯 AI 再 +1.21% · 零授权费", HEX_TEAL, HEX_HIGHLIGHT_GREEN),
            ("10 倍大列车泛化", "96.98% / 99.0%", "中等稀缺纯 AI / BPC-M\n天然抗 ±15% 预测误差", HEX_NAVY, HEX_ZEBRA),
        ],
    )

    add_h2(doc, "1.1 读懂本文所有百分比：评测口径定义")
    add_body(
        doc,
        [
            ("在动态售票控票问题中，每一条随机到达的乘客请求序列都存在一个「上帝视角」的离线理论天花板——", False),
            ("事后全知最优收益 HO（Hindsight Optimum）", True, RGB_NAVY),
            ("（假设提前知道全部乘客何时来、买哪段票，通过论文 Theorem 2 精确最小费用网络流求得的 100% 理论上限）。任何在线策略都无法超过 HO，因此本文所有动态实验均采用如下统一指标：", False),
        ],
    )

    # Formula (1): % of HO & Gap
    add_formula_img(
        doc,
        BASE_DIR / "figures/formulas/eq1_metric.png",
        "注：每个实验均在完全独立的 60 条全新留出路径（Case 1 平稳到达 30 条 + Case 2 短途先来 30 条）上评测，综合均分 = (Case 1 均分 + Case 2 均分) / 2。例如 95.43% 即代表在线策略平均拿到事后理论上限的 95.43%（Gap 仅 4.57%）。",
    )

    add_h2(doc, "1.2 六条核心实证结论")

    add_bullet(
        doc,
        "结论 1（纯 AI 零求解器可行，但范式决定生死）：",
        [
            ("静态非 NSE 碎片排座（NP-hard，小中规模）上，GLM-5 配合校验反馈闭环可稳定拿到 ", False),
            ("98.88% ~ 100.00%", True, RGB_NAVY),
            (" 精确最优；动态控票上，", False),
            ("逐单在线直接问大模型完全不可行", True, RGB_AMBER),
            ("（仅 73.66%，不如贪心 81.70%，单步延迟 3.39 秒），而「离线进化纯 Python 策略代码（Policy as Code）」表现惊艳——100 轮 Top-6 种群进化冠军 ", False),
            ("E097", True, RGB_NAVY),
            (" 在 60 条全新留出集上拿到 ", False),
            ("94.22%", True, RGB_NAVY),
            ("（Case 1 94.88% / Case 2 93.57%），比 Myopic 贪心高 +5.99%，线上仅需 0.32 秒/30 路径且零 API 成本。", False),
        ],
    )
    add_bullet(
        doc,
        "结论 2（【新增】接入免费开源求解器可选组件后，效果稳定超越纯 AI +1.0% ~ +1.2%）：",
        [
            ("本机无需任何商业求解器授权，仅凭免费开源的 ", False),
            ("OR-Tools（GLOP / CLP / CBC / SCIP）+ SciPy（HiGHS）", True, RGB_TEAL),
            (" 即可完整跑通论文全部 LP 方法。在同 60 条留出集 17 组方法正面对决中，", False),
            ("BPC-M via GLOP 以 95.43% 夺冠", True, RGB_TEAL),
            ("（Case 1 95.82% / Case 2 95.04%），高出纯 AI E097（94.22%）", False),
            ("+1.21%", True, RGB_TEAL),
            ("。与此同时，纯 AI E097 已经打赢了 5 个后端中 4 个版本的论文 BPC-S（SCIP/CLP/CBC/GLOP），说明纯 AI 进化已越过一阶线性影子价格门槛，但在二阶非线性块定价（BPC-M）和重求解（RDP）面前仍有约 1 个百分点的结构性差距。", False),
        ],
    )
    add_bullet(
        doc,
        "结论 3（【新增】5 大开源求解器后端精度极近，但速度相差 6 倍）：",
        [
            ("求解同一套 BPC-M 模型，5 个开源后端综合均分全部落在 ", False),
            ("95.28% ~ 95.43%", True, RGB_NAVY),
            (" 极窄区间内（极差仅 0.15%），完全可以平替昂贵的商业求解器；但 30 路径耗时差异显著：", False),
            ("HiGHS（~1.1s）≈ GLOP（~1.5s）≈ CLP（~1.6s）< CBC（~2.7s）≪ SCIP（~7.5s）", True, RGB_NAVY),
            ("。纯 LP 场景首选 GLOP 或 HiGHS；而纯 AI E097（~0.32s）仍比最快的开源 LP 快 3.4 倍、比 SCIP 快 23 倍。", False),
        ],
    )
    add_bullet(
        doc,
        "结论 4（【新增】AI 面对可选求解器组件会主动调用，但极易踩“静默回退”工程坑）：",
        [
            ("Prompt 明确告知“solver_toolkit 可调用也可不调用”后，GLM-5 所有有效输出均 ", False),
            ("100% 主动导入并调用组件", True, RGB_TEAL),
            ("。但 4 轮实测暴露出两类高发代码 Bug：R01 因把稀疏索引列表误传给稠密矩阵参数且裸 ", False),
            ("except Exception", True, RGB_NAVY, True),
            (" 吞掉报错，退化到苛刻启发式掉至 32.74%；R03 虽成功解通 GLOP，但末尾把负增益本该 ", False),
            ("return None", True, RGB_NAVY, True),
            (" 拒单护留的分支错写成调用启发式强行接单，直接把 BPC-M 短路成了 Myopic（88.38%）。因此给 AI 开放求解器工具必须配强类型入参契约、禁用静默吞错并在进化反馈中暴露「LP 实际命中率」。", False),
        ],
    )
    add_bullet(
        doc,
        "结论 5（10 倍大列车零样本外推边界明确）：",
        [
            ("将 N=20 进化出的纯 AI E097 不改代码直接迁移到 10 倍大列车（T=1000），在中等稀缺（N=220）上零样本飙升至 ", False),
            ("96.98%", True, RGB_NAVY),
            ("（甩开 Myopic +10.86%）；但在训练未覆盖的极端稀缺（N=140）上退化至 90.04%，而基于 LP 求解器的 BPC-M / RDP 在三档稀缺度与 ±15% 预测误差下全线稳守 ", False),
            ("98.6% ~ 99.0%", True, RGB_TEAL),
            ("。", False),
        ],
    )
    add_bullet(
        doc,
        "结论 6（同系列模型档位存在明显推理断层）：",
        [
            ("同起跑线 20 轮从零进化中，主力高配版 ", False),
            ("glm-5.3", True, RGB_NAVY),
            (" 留出集均分达 ", False),
            ("92.12%", True, RGB_NAVY),
            ("（代码有效率 90%，耗时 197.8s），轻量版 ", False),
            ("glm-5.3-flash", True, RGB_MUTED),
            (" 仅 88.91%（有效率 75%，耗时 357.2s，且在静态 S3 连续 4 轮全冲突）。高阶运筹策略发现必须使用旗舰推理档位。", False),
        ],
    )

    # ==========================================================================
    # CHAPTER 2: PROBLEM BACKGROUND & PAPER METHODS
    # ==========================================================================
    add_h1(doc, "二、业务背景与论文运筹体系速览")

    add_h2(doc, "2.1 为什么高铁售票比普通航空控票更难？（Assign-to-Seat 约束）")
    add_body(
        doc,
        [
            ("设想一列共有 ", False),
            ("N 个座位、M 个相邻区间（M+1 个车站）", True, RGB_NAVY),
            (" 的高铁列车。在常规航空或酒店收益管理中，只要每一段还有空余座位数就能卖票；但高铁具有两条独特的现实约束：", False),
        ],
    )
    add_bullet(
        doc,
        "政府指导的次加性定价（不可动态涨价）：",
        "短途单公里更贵、长途单公里更便宜但总价更高。论文合成实验采用标准次加性票价公式（式 2），当 M=6 时，跨度 1~6 个区间的票价依次为 [10, 17, 24, 30, 36, 41]：",
    )

    # Formula (2): Subadditive fare
    add_formula_img(
        doc,
        BASE_DIR / "figures/formulas/eq2_fare.png",
        "例：售出 1 张全程票 [1, 6] 收益 41 元；若被 2 张中间短途票 [2, 3]（17 元）和 [4, 5]（17 元）把同一张空座切碎，总收益仅 34 元，且头尾残留的 [1, 1] 与 [6, 6] 极难再匹配售出。",
    )

    add_bullet(
        doc,
        "购票即定座、全程不可换座（Assign-to-Seat）：",
        "乘客下单瞬间必须分配一个具体座位号且中途不得更换。如果前期来的短途客把完整空座 [1, 6] 切得支离破碎，后期高总价长途客到来时，即使每一段总余座都大于 0，也会因为找不到「同一座位在全程连续空闲」而被迫拒单流失。",
    )

    add_h2(doc, "2.2 论文的核心建模巧思：Maximal Sequence 无损压缩与 4 大基准方法")
    add_body(
        doc,
        [
            ("论文作者证明：无需追踪每个具体座位编号，只需统计列车上各类", False),
            ("最大连续空闲区间（Maximal Sequence）[u, v] 的数量", True, RGB_NAVY),
            ("即可完成无损状态压缩，使状态维度完全独立于座位数 N。当我们将一张请求 i → j 的车票装入空闲块 [u, v]（满足 u ≤ i ≤ j ≤ v）时，状态转移严格遵循如下区间分裂规则：", False),
        ],
    )

    # Formula (3): Maximal Sequence split
    add_formula_img(
        doc,
        BASE_DIR / "figures/formulas/eq3_split.png",
        "每次售票消耗 1 个 [u, v] 块，并释放最多 2 个残余连续空闲子块（若左/右端为空则不生成），整个售票过程本质上是“用一块大料切出订单与边角料”的动态套裁问题。",
    )

    add_body(
        doc,
        [
            ("基于该状态压缩框架，论文提出了从弱到强 4 种在线策略；其中最推荐的 ", False),
            ("BPC-M（Algorithm 2，式 12）", True, RGB_NAVY),
            (" 通过求解 Maximal Sequence 对偶 LP 直接估计每类连续空块 [u, v] 的非线性影子价格 ", False),
            ("β†_uv", True, RGB_NAVY),
            ("，并在订单 (i, j) 到来时按如下边际净收益准则做接单/拒单与选块决策：", False),
        ],
    )

    # Formula (4): BPC-M decision rule
    add_formula_img(
        doc,
        BASE_DIR / "figures/formulas/eq4_bpcm.png",
        "决策含义：只有当票价 p_ij 加上切分后残留左右子块的影子价值，不低于所消耗整块 [u, v] 的影子价值时，才接单并选择使净增益最大的空闲块；否则主动拒单、保留整座等待未来长途高价需求。",
    )

    add_styled_table(
        doc,
        ["方法名称", "论文对应算法", "核心决策机制", "是否需 LP 求解器", "实战定位"],
        [
            ["MP（Myopic）", "贪心基线", "先到先得，有连续空座即卖，按 Tie-Breaking 选块", "否", "不控票保底基线"],
            ["BPC-S", "Algorithm 1（式 6）", "静态松弛对偶 LP，按单段线性影子价格累加定价", "是", "忽略连续空座的非线性溢价"],
            ["**BPC-M**", "Algorithm 2（式 12）", "Maximal Sequence 对偶 LP，直接学整块非线性影子价格", "是", "论文最推荐：稳健且抗预测误差"],
            ["RDP", "Algorithm 3（式 14+15）", "每步重解动态原问题 LP，按最优流比例决策", "是", "理论最优（NEE 下 O(1) 遗憾界）"],
            ["HO（裁判上界）", "Theorem 2（式 3）", "上帝视角已知全部订单，纯 Python 最小费用流精确求解", "否（精确图论）", "100% 事后理论天花板"],
        ],
        [2.7, 3.0, 5.2, 2.3, 3.4],
        alignments=[
            WD_ALIGN_PARAGRAPH.LEFT,
            WD_ALIGN_PARAGRAPH.LEFT,
            WD_ALIGN_PARAGRAPH.LEFT,
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.LEFT,
        ],
        highlight_rows={2: (HEX_HIGHLIGHT_GREEN, True)},
        font_size=8.9,
    )

    # ==========================================================================
    # CHAPTER 3: TWO-PHASE ARCHITECTURE
    # ==========================================================================
    add_h1(doc, "三、两阶段技术方案与工程架构设计")

    add_body(
        doc,
        "为全面评估大模型在运筹决策中的能力边界与工具协同效应，我们搭建了一套高度自动化、严格防过拟合、支持毫秒级仿真与 AST 安全审计的两阶段实验平台，整体技术架构如图 1 所示。",
    )

    add_figure(
        doc,
        BASE_DIR / "figures/two_phase_architecture.png",
        "图 1  高铁 Assign-to-Seat 两阶段实验技术架构全景（Phase 1 纯 AI 零求解器进化 vs Phase 2 开源求解器可选组件）",
        width_cm=16.5,
    )

    add_h2(doc, "3.1 第一阶段：无求解器 Top-K 策略代码进化（Policy as Code）")
    add_body(
        doc,
        "第一阶段的核心思想不是让大模型在线“拍脑袋”逐单回复买还是不买，而是让大模型在离线阶段扮演「运筹算法科学家」——不断编写、诊断、迭代独立的纯 Python 决策函数 decide(...)，并经由仿真环境淘汰进化：",
    )
    add_bullet(
        doc,
        "严格 AST 零求解器门禁：",
        "每一段模型生成的代码在执行前都必须通过 Python AST 静态语法树审计，严禁导入 scipy / ortools / pulp / cvxpy / gurobipy / coptpy 等任何第三方优化库，仅允许 Python 标准库，且单批 40 条训练路径设 3.5 秒硬超时，保证线上具备毫秒级吞吐。",
    )
    add_bullet(
        doc,
        "训练 / 留出集严格隔离（防过拟合）：",
        "训练集包含 40 条路径（Case 1 平稳到达 20 条 + Case 2 短途先来 20 条）；留出测试集使用全新随机种子生成 60 条路径（Case 1 30 条 + Case 2 30 条），留出集详情全程对大模型不可见，仅用于检验策略是否真正学到泛化规律。",
    )
    add_bullet(
        doc,
        "4 类进化算子轮换驱动（Top-6 精英池 + 5 路并发）：",
        "每轮从 Top-6 精英策略池按比例调度 4 种不同温度与提示词模板的算子，兼顾全局范式跳出与局部精细收敛：",
    )

    add_styled_table(
        doc,
        ["进化算子", "调度占比", "采样温度", "Prompt 注入内容与设计意图"],
        [
            ["explore_paradigm（新范式探索）", "20%", "0.35", "强制跳出当前局部框架，从纯 Python 最小费用流 / 次梯度对偶 / 动态流体 / 多阶段护留等 6 条路线从头发明新算法"],
            ["crossover（双精英交叉融合）", "20%", "0.25", "同时输入精英池中两个高分策略的完整源码与各自体检报告，取长补短融合出更强后代"],
            ["refine_diagnostics（诊断定向精修）", "40%", "0.15", "输入当前精英代码 + 按行程长度统计的接单/拒单/无座流失体检表 + 剩座分布，精准定位失分点"],
            ["hyper_tune（冠军局部微调）", "20%", "0.15", "保持冠军骨架不变，围绕需求方差校准、端部让利与碎片惩罚系数做小步长精细调优"],
        ],
        [4.2, 1.8, 1.8, 8.8],
        alignments=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.LEFT],
        font_size=8.9,
    )

    add_h2(doc, "3.2 第二阶段（新增）：开源求解器可选组件架构（solver_toolkit）")
    add_body(
        doc,
        [
            ("在完成纯 AI 零求解器极限探索后，我们进一步思考：在真实工业落地中，既然 ", False),
            ("OR-Tools、SciPy HiGHS、CBC、SCIP", True, RGB_TEAL),
            (" 都是完全免费开源、pip 一键可装的轻量库，那么", False),
            ("给 AI 增加一个“可调用也可不调用”的开源求解器组件", True, RGB_NAVY),
            ("，能否进一步突破纯 AI 的天花板？为此我们在 ", False),
            ("open_solver_component/", True, RGB_NAVY, True),
            (" 目录构建了如下标准化组件架构：", False),
        ],
    )

    add_code_block(
        doc,
        """from solver_toolkit import available_solvers, preferred_lp_solver, solve_lp

# 1. 自动探测本机可用的免费开源后端（全部零商业授权）
# {'scip': True, 'cbc': True, 'glop': True, 'clp': True, 'highs': True}
avail = available_solvers()

# 2. 统一标准形式 LP 求解接口（minimize c·x  s.t. A_ub x <= b_ub, bounds）
res = solve_lp(
    c, A_ub=A, b_ub=b,
    bounds=[(0.0, None)] * len(c),
    solver="glop",         # 支持 "auto" | "glop" | "clp" | "cbc" | "scip" | "highs"
    time_limit_s=0.5,      # 强制超时安全护栏
)
if res["ok"]:
    x = res["x"]           # 最优解向量""",
        title="核心组件统一调用接口（open_solver_component/solver_toolkit.py）",
    )

    add_bullet(
        doc,
        "AST 白名单精细放行与行为观测：",
        "新版审计器放行标准库 + solver_toolkit，依然禁止直接引入商业求解器或绕过封装底层调用，同时自动标记每轮生成代码是否真正使用了求解器组件（used_toolkit: True/False），便于观测大模型在自由裁量下的真实偏好。",
    )

    # ==========================================================================
    # CHAPTER 4: PHASE 1 EXPERIMENTS (EXP 1 - EXP 5)
    # ==========================================================================
    add_h1(doc, "四、第一阶段实验：纯 AI 零求解器求解全量实测（实验 1 ~ 5）")

    add_h2(doc, "4.1 实验 1：静态非 NSE 排座（Section 3，4 轮校验反馈闭环）")
    add_body(
        doc,
        "论文 Section 3 指出，当列车初始座位已被提前占用而呈现碎片化（不满足 NSE 条件）时，静态排座最大化收益问题本身就是 NP-hard。我们构造了 S1/S2/S3 三组不同规模的非 NSE 碎片算例，用纯 Python 分支定界算出精确最优作为裁判（不向模型泄露），让 GLM-5 通过「生成方案 → 校验器报冲突/收益 → 修正重排」闭环迭代 4 轮：",
    )

    add_styled_table(
        doc,
        ["算例规模", "精确最优", "贪心(总价)", "贪心(单价)", "GLM-5 第 1 轮", "GLM-5 闭环最佳", "最优达成率 / Gap"],
        [
            ["S1 小规模（3 座×6 段，6 单）", "20", "19", "17", "合法 20", "**20**（R1）", "**100.00%**（Gap 0.00%）"],
            ["S2 中规模（5 座×6 段，14 单）", "179", "165", "166", "思考截断失败", "**177–179**（R3）", "**98.88%–100%**（Gap ≤ 1.12%）"],
            ["S3 较大规模（8 座×6 段，24 单）", "275", "259", "242", "1 处冲突", "**274**（R2）", "**99.64%**（Gap 0.36%）"],
        ],
        [4.1, 1.6, 1.7, 1.7, 2.3, 2.3, 2.9],
        alignments=[
            WD_ALIGN_PARAGRAPH.LEFT,
            WD_ALIGN_PARAGRAPH.RIGHT,
            WD_ALIGN_PARAGRAPH.RIGHT,
            WD_ALIGN_PARAGRAPH.RIGHT,
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.RIGHT,
        ],
        highlight_rows={2: (HEX_HIGHLIGHT_GOLD, False)},
        font_size=8.8,
    )
    add_body(
        doc,
        "核心洞察：校验反馈闭环能将 S3 从第 1 轮存在座位冲突一举修复至 274/275（99.64%，大幅领先贪心 259），同时实测也表明大模型在后续轮次做激进重排时仍可能重新引入冲突，因此工程上必须配「硬校验器 + 历史最优保留（Elitism）」。",
        space_after=8,
    )

    add_h2(doc, "4.2 实验 2：为什么不能「逐单实时问大模型」？（Online LLM vs 进化代码）")
    add_body(
        doc,
        "在一条完整的 Case 2 动态路径（M=6, N=5, T=25，21 条有效请求，事后最优 HO = 224）上，我们将「每来一张订单就实时调用一次 GLM-5 决策」与「离线进化出的纯 Python 策略」直接对比：",
    )

    add_styled_table(
        doc,
        ["方案", "总收益", "占 HO 比率", "总耗时（单步延迟）", "线上 API 成本"],
        [
            ["事后全知上界 HO", "224", "100.00%", "< 1 ms", "0"],
            ["Myopic 贪心基线（MP）", "183", "81.70%", "< 1 ms", "0"],
            ["GLM-5 逐单在线实时决策", "165", "73.66%", "50.85 s（3.39 s/单）", "15 次调用 / 6,835 tokens"],
            ["**GLM-5 进化纯 Python 策略**", "**194**", "**86.61%**", "**1.08 ms（0.05 ms/单）**", "**0（线上零成本）**"],
        ],
        [4.5, 1.8, 2.2, 3.9, 4.2],
        alignments=[
            WD_ALIGN_PARAGRAPH.LEFT,
            WD_ALIGN_PARAGRAPH.RIGHT,
            WD_ALIGN_PARAGRAPH.RIGHT,
            WD_ALIGN_PARAGRAPH.RIGHT,
            WD_ALIGN_PARAGRAPH.LEFT,
        ],
        highlight_rows={3: (HEX_HIGHLIGHT_GOLD, True)},
        font_size=9.0,
    )
    add_body(
        doc,
        "结论非常明确：逐单在线问大模型不仅延迟高出近 5 万倍、持续消耗 Token，还出现了严重的数值尺度失真（例如误拒了票价高达 36 元的 [1, 5] 优质长途订单），收益甚至低于不控票的 Myopic 贪心。因此「离线进化算法代码 → 线上毫秒执行」才是大模型做运筹控票的正确范式。",
        space_after=8,
    )

    add_h2(doc, "4.3 实验 3：100 轮 Top-6 无求解器种群进化全景（冠军策略 E097）")
    add_body(
        doc,
        "在基础规模（M=6, N=20, T=100）上，我们启动 5 并发共 20 代 = 100 轮进化，总耗时 925.7 秒（约 15.4 分钟），有效可执行代码 90/100，总消耗 631,631 tokens。全程进化曲线如图 2 所示：",
    )

    add_figure(
        doc,
        BASE_DIR / "figures/pop100_evolution_curve.png",
        "图 2  100 轮无求解器 Top-6 种群进化曲线（实线为 40 路径训练集，星标为 60 路径全新留出集，可见零过拟合）",
        width_cm=16.2,
    )

    add_styled_table(
        doc,
        ["进化里程碑", "算子 / 编号", "训练集 40 路径（C1 / C2 / 均分）", "留出集 60 路径（C1 / C2 / 均分）", "相对 MP 提升"],
        [
            ["基线", "Myopic (MP)", "89.52% / 84.88% / 87.20%", "90.54% / 85.92% / 88.23%", "—"],
            ["单线 7 轮种子", "Seed_R7", "89.99% / 87.84% / 88.92%", "90.58% / 88.66% / 89.62%", "+1.39%"],
            ["第 6 轮", "E006 [Tune]", "91.18% / 88.66% / 89.92%", "91.70% / 89.45% / 90.58%", "+2.35%"],
            ["第 11 轮", "E011 [Cross]", "91.09% / 89.52% / 90.31%", "91.41% / 90.22% / 90.82%", "+2.59%"],
            ["**第 34 轮（关键质变）**", "E034 [Refine]", "93.88% / 92.70% / 93.29%", "94.32% / 92.98% / 93.65%", "**+5.42%**"],
            ["第 61 轮", "E061 [Tune]", "94.67% / 93.02% / 93.85%", "94.52% / 93.51% / 94.02%", "+5.79%"],
            ["第 72 轮", "E072 [Cross]", "94.86% / 93.47% / 94.17%", "94.87% / 93.77% / 94.32%", "+6.09%"],
            ["**第 97 轮（最终冠军）**", "**E097 [Cross]**", "**94.88% / 93.56% / 94.22%**", "**94.88% / 93.57% / 94.22%**", "**+5.99%**"],
        ],
        [3.2, 2.7, 4.3, 4.3, 2.1],
        alignments=[
            WD_ALIGN_PARAGRAPH.LEFT,
            WD_ALIGN_PARAGRAPH.LEFT,
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.RIGHT,
        ],
        highlight_rows={4: (HEX_LIGHT_BLUE, True), 7: (HEX_HIGHLIGHT_GOLD, True)},
        font_size=8.6,
    )

    add_callout(
        doc,
        "代码级解剖：纯 AI 冠军策略 E097（best_pop100_policy.py）自发进化出的 4 大运筹机制",
        [
            [("1. 严格 Maximal Sequence 分裂前向流体模拟（_alloc_demand）：", True, RGB_NAVY), (" 在无求解器条件下，模型自发在纯 Python 里模拟未来需求分配，并严格将分裂出的残余子块 [u, a-1] 和 [b+1, v] 放回块池继续参与竞争，正是第 34 轮质变跃迁（+2.78%）的关键。", False)],
            [("2. 双情景鲁棒随机估值（_robust_V）：", True, RGB_NAVY), (" 不再盲信单一期望值，而是在 0.85× 与 1.15× 两种需求扰动情景下各算一次剩余价值取均值，自发逼近随机规划中的样本平均近似（SAA）。", False)],
            [("3. 泊松尾概率满载率 + 调和供需压力（_pois_ge / rho_harm）：", True, RGB_NAVY), (" 精准校准有限座位数（N=20）下确定性流体近似偏乐观的经典偏差。", False)],
            [("4. 端部让利 + 左贴合 Tie-Breaking + 末端倾销：", True, RGB_NAVY), (" 优先消耗贴合边界或已被切分的残块，尽量保护完整的长跨度空座 [1, M]，并在尾盘自动降低门槛清空余座。", False)],
        ],
        accent_hex=HEX_AMBER,
        bg_hex=HEX_HIGHLIGHT_GOLD,
    )

    add_h2(doc, "4.4 实验 4：10 倍大列车三档稀缺度与 ±15% 预测误差零样本外推（仿论文 Table 1）")
    add_body(
        doc,
        "为了检验纯 AI 进化策略的泛化边界，我们将 N=20, T=100 下进化出的 E097 不修改任何参数，直接零样本迁移到 10 倍规模大列车（M=6, T=1000, Case 2, 10 路径）的三种资源紧张度下，并引入 ±15% 系统需求预测误差，与 SciPy HiGHS 精确复现的论文 BPC-M / RDP 正面对照：",
    )

    add_styled_table(
        doc,
        ["方法", "N=320 资源较宽\n（准确 / ±15% 误差）", "N=220 中等紧张\n（准确 / ±15% 误差）", "N=140 极度紧张\n（准确 / ±15% 误差）", "10 路径总耗时"],
        [
            ["MP（Myopic 贪心）", "85.01% / 85.01%", "86.12% / 86.12%", "89.53% / 89.53%", "~18 ms"],
            ["**GLM-5 E097（纯 AI 无求解器）**", "**94.12% / 94.94%**", "**96.98% / 96.64%**", "**90.04% / 89.59%**", "**~1.1 s**"],
            ["RDP（论文式 14+15 LP）", "99.00% / 98.71%", "98.96% / 98.60%", "98.67% / 98.66%", "~5.9 s"],
            ["**BPC-M（论文式 12 LP）**", "**99.02% / 98.97%**", "**99.00% / 98.91%**", "**98.82% / 98.72%**", "**~3.6 s**"],
        ],
        [4.4, 3.3, 3.3, 3.3, 2.3],
        alignments=[
            WD_ALIGN_PARAGRAPH.LEFT,
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.RIGHT,
        ],
        highlight_rows={1: (HEX_HIGHLIGHT_GOLD, False), 3: (HEX_HIGHLIGHT_GREEN, True)},
        font_size=8.8,
    )
    add_body(
        doc,
        "边界结论：在供需比与训练集匹配的中等稀缺大列车（N=220）上，纯 AI E097 零样本即达到 96.98%（领先贪心 +10.86%）；但面对训练未曾覆盖的极端稀缺场景（N=140），经验性阈值会明显失准（回落至 90.04%），而求解器驱动的 BPC-M 依靠全局数学规划对偶价格，在全稀缺度与 ±15% 噪声下稳守 98.7%~99.0%。",
        space_after=8,
    )

    add_h2(doc, "4.5 实验 5：同系列不同档位 GLM 模型对比（glm-5.3 vs glm-5.3-flash）")
    add_body(
        doc,
        "经 API 实测探测，智谱 Coding Plan 实际路由为两档同系列模型：主力高配版 glm-5.3（请求 glm-5 等）与同系列轻量版 glm-5.3-flash（请求 glm-4.7 等）。我们在完全一致的起跑线、相同 Prompt 模板下对比两档模型的静态排座与 20 轮从零动态进化表现：",
    )

    add_styled_table(
        doc,
        ["评测维度", "glm-5.3-flash（轻量档）", "glm-5.3（旗舰高配档）", "代差对比"],
        [
            ["静态排座 S1（最优 20）", "20 / 20（100%） · 90.4s", "20 / 20（100%） · 39.1s", "简单题持平，高配快 2.3×"],
            ["静态排座 S2（最优 179）", "179 / 179（100%，R3 修通）", "179 / 179（100%，R2 修通）", "均拿满分，高配少 1 轮"],
            ["静态排座 S3（最优 275）", "0 / 275（0%，4 轮全冲突）", "259 / 275（94.18%，历史最高 274）", "复杂约束断层差距"],
            ["20 轮进化 · 留出集 Case 1", "91.22%", "**93.81%**", "+2.59%"],
            ["20 轮进化 · 留出集 Case 2", "86.60%", "**90.42%**", "+3.82%"],
            ["**20 轮进化 · 留出集综合均分**", "88.91%（仅比 MP +0.68%）", "**92.12%（比 MP +3.89%）**", "**+3.21%**"],
            ["代码有效可执行率 / 总耗时", "15/20（75%） · 357.2 s", "**18/20（90%） · 197.8 s**", "质量更高且耗时省 45%"],
        ],
        [4.5, 4.1, 4.3, 3.7],
        alignments=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.LEFT],
        highlight_rows={5: (HEX_LIGHT_BLUE, True)},
        font_size=8.8,
    )

    add_figure(
        doc,
        BASE_DIR / "figures/model_compare_20rounds.png",
        "图 3  同起跑线 20 轮从零进化曲线对比：glm-5.3（蓝）vs glm-5.3-flash（红），旗舰档从第 5 轮起持续拉开差距",
        width_cm=15.8,
    )

    # ==========================================================================
    # CHAPTER 5: PHASE 2 NEW EXPERIMENTS (EXP 6)
    # ==========================================================================
    add_h1(doc, "五、第二阶段新增实验：开源求解器可选组件全量评测（实验 6）")

    add_h2(doc, "5.1 零商业授权：5 大本机开源求解器后端一键就绪")
    add_body(
        doc,
        "传统运筹论文常使用 Gurobi、COPT、CPLEX 等商业求解器，部署门槛与授权费用高昂。本阶段我们在普通开发机上通过 pip 安装 ortools、pulp、scipy，封装了统一组件 solver_toolkit.py 并完成冒烟自检，确认以下 5 大主流开源求解器全部 100% 可用：",
    )

    add_styled_table(
        doc,
        ["组件后端标识", "开源项目来源", "实测版本", "求解器定位", "自检状态"],
        [
            ["**glop**", "Google OR-Tools", "v9.15.6755", "纯线性规划（LP）单纯形求解器，速度快精度稳", "通过"],
            ["clp", "OR-Tools / COIN-OR", "v1.17.10", "工业界经典开源纯 LP 求解器", "通过"],
            ["**highs**", "SciPy 内置", "1.13.1（HiGHS）", "新一代高性能开源 LP / MIP 求解器，调用零转换开销", "通过"],
            ["cbc", "OR-Tools / COIN-OR", "v2.10.12", "经典开源混合整数规划（MIP）求解器", "通过"],
            ["scip", "OR-Tools / ZIB", "v10.0.0（SoPlex 8.0）", "学术界最强非商业开源 MIP / MINLP 求解器", "通过"],
        ],
        [2.4, 3.2, 3.0, 6.2, 1.8],
        alignments=[
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.LEFT,
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.LEFT,
            WD_ALIGN_PARAGRAPH.CENTER,
        ],
        highlight_rows={0: (HEX_HIGHLIGHT_GREEN, False), 2: (HEX_HIGHLIGHT_GREEN, False)},
        font_size=8.9,
    )

    add_h2(doc, "5.2 全量 17 组方法正面对决：论文 4 方法 × 5 开源后端 vs 纯 AI 冠军 E097")
    add_body(
        doc,
        "在完全相同的 60 条留出测试路径（M=6, N=20, T=100；Case 1 平均 HO = 932.17，Case 2 平均 HO = 922.57）上，我们将论文的 BPC-M、RDP、BPC-S 分别接入全部 5 个开源求解器后端（共 15 组），与纯 AI 冠军 E097、Myopic 贪心基线（合计 17 组）进行同台排位赛，可视化排名见图 4，全量明细见下表：",
    )

    add_figure(
        doc,
        BASE_DIR / "open_solver_component/figures/ranking_vs_pure_ai.png",
        "图 4  留出集 17 组方法综合均分横向排名（紫色虚线标注纯 AI 100 轮零求解器冠军 E097 = 94.22%）",
        width_cm=16.2,
    )

    # Full 17-row table
    rows_17 = [
        ["#01", "**BPC-M via GLOP**", "95.82%（893.27 / 1,416.5 ms）", "95.04%（876.70 / 1,577.0 ms）", "**95.43%**", "**+1.21%**"],
        ["#02", "BPC-M via CLP", "95.82%（893.27 / 1,547.5 ms）", "95.01%（876.37 / 1,635.5 ms）", "95.41%", "+1.19%"],
        ["#03", "BPC-M via HiGHS", "95.63%（891.47 / 1,022.0 ms）", "95.04%（876.67 / 1,183.6 ms）", "95.34%", "+1.12%"],
        ["#04", "BPC-M via SCIP", "95.65%（891.67 / 7,223.1 ms）", "95.01%（876.43 / 7,706.4 ms）", "95.33%", "+1.11%"],
        ["#05", "BPC-M via CBC", "95.63%（891.57 / 2,530.4 ms）", "94.92%（875.60 / 2,822.0 ms）", "95.28%", "+1.06%"],
        ["#06", "RDP via GLOP", "95.48%（890.13 / 1,774.6 ms）", "94.97%（876.10 / 1,854.2 ms）", "95.22%", "+1.00%"],
        ["#07", "RDP via CBC", "95.31%（888.53 / 3,478.7 ms）", "94.92%（875.63 / 3,987.8 ms）", "95.12%", "+0.90%"],
        ["#08", "RDP via HiGHS", "95.06%（886.17 / 1,733.6 ms）", "94.95%（875.87 / 1,804.2 ms）", "95.00%", "+0.78%"],
        ["#09", "RDP via SCIP", "94.58%（881.73 / 7,539.2 ms）", "95.01%（876.37 / 7,688.6 ms）", "94.80%", "+0.58%"],
        ["#10", "RDP via CLP", "94.92%（884.83 / 2,503.2 ms）", "94.55%（872.13 / 2,485.8 ms）", "94.73%", "+0.51%"],
        ["#11", "BPC-S via HiGHS", "95.42%（889.57 / 1,167.9 ms）", "93.31%（860.77 / 1,253.8 ms）", "94.37%", "+0.15%"],
        ["#12", "**GLM-5 E097（纯 AI 无求解器）**", "**94.88%（884.43 / 314.3 ms）**", "**93.57%（863.07 / 326.5 ms）**", "**94.22%**", "**基线 (0.00%)**"],
        ["#13", "BPC-S via SCIP", "95.40%（889.40 / 5,691.7 ms）", "92.86%（856.57 / 5,432.2 ms）", "94.13%", "-0.09%"],
        ["#14", "BPC-S via CLP", "95.54%（890.73 / 1,040.6 ms）", "92.43%（852.60 / 976.7 ms）", "93.99%", "-0.23%"],
        ["#15", "BPC-S via CBC", "95.11%（886.73 / 2,145.2 ms）", "92.58%（854.07 / 2,056.9 ms）", "93.84%", "-0.38%"],
        ["#16", "BPC-S via GLOP", "95.23%（887.93 / 1,018.5 ms）", "91.56%（844.60 / 1,083.0 ms）", "93.40%", "-0.82%"],
        ["#17", "MP（Myopic 贪心）", "90.54%（844.37 / 4.6 ms）", "85.92%（792.67 / 4.9 ms）", "88.23%", "-5.99%"],
    ]
    add_styled_table(
        doc,
        ["排名", "方法 × 求解器后端", "Case 1（占比 / 均收益 / 耗时）", "Case 2（占比 / 均收益 / 耗时）", "综合均分", "相对 E097"],
        rows_17,
        [1.1, 3.8, 4.1, 4.1, 1.7, 1.8],
        alignments=[
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.LEFT,
            WD_ALIGN_PARAGRAPH.RIGHT,
            WD_ALIGN_PARAGRAPH.RIGHT,
            WD_ALIGN_PARAGRAPH.RIGHT,
            WD_ALIGN_PARAGRAPH.RIGHT,
        ],
        highlight_rows={0: (HEX_HIGHLIGHT_GREEN, True), 11: (HEX_HIGHLIGHT_GOLD, True)},
        font_size=8.2,
    )

    # Formula (5): Empirical hierarchy
    add_formula_img(
        doc,
        BASE_DIR / "figures/formulas/eq5_hierarchy.png",
        "实证方法强度梯度：开源求解器驱动的 BPC-M 与 RDP 占据前 10 席，纯 AI E097 强势杀入 BPC-S 阵营并反超其中 4 个版本。",
    )

    add_h2(doc, "5.3 深度机理分析：速度差 6 倍的根源与“同 LP 微小波动”之谜")
    add_bullet(
        doc,
        "为什么 HiGHS / GLOP 比 SCIP / CBC 快 2~7 倍？",
        "Assign-to-Seat 的 BPC-M / RDP 每步求解的是小型连续线性规划（LP），不含整数变量。HiGHS、GLOP、CLP 是原生纯 LP 求解器，单纯形建模与热启动极其轻量（30 路径仅 1.0~1.6 秒）；而 SCIP、CBC 是完整的混合整数规划（MIP）引擎，每步创建模型都要走预处理、割平面与分支框架初始化，导致在纯 LP 场景下速度慢 2~7 倍且精度毫无优势。因此纯 LP 控票场景应首选 GLOP 或 HiGHS。",
    )
    add_bullet(
        doc,
        "为什么 5 个求解器解同一套精确 LP，最终收益会有 0.1% ~ 0.9% 的细微差异？",
        "这是因为动态控票 LP 存在高度退化（Degeneracy）与多重最优解——最优目标值唯一，但对应的对偶影子价格 β 顶点解不止一个。不同求解器的枢轴规则选出不同最优基后，在边际净收益恰好接近 0 的临界订单上会触发不同的接/拒或选块分支，进而在后续几十步随机到达中产生路径分叉。值得注意的是，BPC-M 在 5 个求解器之间的极差仅有 0.15%（95.28%~95.43%），而 BPC-S 的极差高达 0.97%（93.40%~94.37%），再次从数值稳定性角度印证了论文结论——Maximal Sequence 非线性块对偶（BPC-M）远比线性段对偶（BPC-S）稳健。",
    )
    add_bullet(
        doc,
        "纯 AI E097 的真实站位：",
        "尽管综合均分（94.22%）落后 BPC-M 最优组（95.43%）1.21%，但 E097 在 Case 2（93.57%）上全面击败了全部 5 个版本的 BPC-S（最高 93.31%），并且 30 路径耗时仅 0.31~0.33 秒，比最快的 LP 重求解（HiGHS）还快 3.4 倍、比 GLOP 快 4.7 倍、比 SCIP 快 23 倍。",
    )

    add_h2(doc, "5.4 AI 自主选用求解器组件实测（4 轮 GLM-5 短跑）与代码级踩坑复盘")
    add_body(
        doc,
        "除了评测论文既有方法外，我们还实跑了「把 solver_toolkit 作为可选组件交给 GLM-5（glm-5.3）自主进化」的 4 轮短跑实验（奇数轮建议优先尝试组件，偶数轮完全自由选择，提供 seed_bpcm_via_toolkit.py 留出集 95.34% 作为参考种子）。逐轮实测结果与源码级复盘如下：",
    )

    add_styled_table(
        doc,
        ["轮次", "Prompt 倾向", "调用组件?", "训练集均分", "留出集（C1 / C2 / 均分）", "耗时 / Tokens", "代码级根因诊断"],
        [
            ["种子", "参考示范", "是", "—", "95.67% / 95.01% / 95.34%", "—", "标准 BPC-M via toolkit(scip)"],
            ["R01", "鼓励用组件", "**是**", "30.21%", "18.91% / 46.57% / 32.74%", "73.4s / 4,352", "误把稀疏索引传给稠密 A_ub + 裸 except 吞错走苛刻回退"],
            ["R02", "自由选择", "—", "—", "空回复失败", "—", "智谱平台午后高峰拥堵（HTTP 429 / code 1305）"],
            ["R03", "鼓励用组件", "**是**", "87.97%", "90.67% / 86.09% / 88.38%", "47.9s / 3,694", "GLOP 成功解出 β，但负增益拒单错写回退强行接单"],
            ["R04", "自由选择", "—", "—", "空回复失败", "—", "同 R02，平台高峰空响应"],
        ],
        [1.1, 2.0, 1.5, 1.7, 3.6, 2.2, 4.5],
        alignments=[
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.RIGHT,
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.RIGHT,
            WD_ALIGN_PARAGRAPH.LEFT,
        ],
        highlight_rows={0: (HEX_HIGHLIGHT_GREEN, False)},
        font_size=8.2,
    )

    add_callout(
        doc,
        "极具工程价值的真实教训：为什么 R01、R03 都调了求解器却掉分？下一步怎么修？",
        [
            [("1. AI 的意愿很明确：", True, RGB_TEAL), (" 2/2 有效轮次中，模型 100% 主动选择 import solver_toolkit，说明大模型能够准确识别线性规划对偶在 Assign-to-Seat 中的结构优势。", False)],
            [("2. 坑一（R01 接口契约误用 + 静默吞错）：", True, RGB_AMBER), (" 模型为避免引入 numpy，自行将 A_ub 构造为稀疏二元组列表 [[col, val], ...] 而非 solve_lp 要求的二维稠密矩阵；每次调用抛异常又被模型自己写的 except Exception: continue 静默吞掉，直接降级到过度严苛的兜底启发式，导致大量拒单（32.74%）。", False)],
            [("3. 坑二（R03 兜底逻辑短路拒单机制）：", True, RGB_AMBER), (" R03 模型已修正矩阵格式、成功跑通 GLOP 拿到准确对偶价格 β，但最后一行写成了「若 best_gain < 0，则 return _heuristic(...)」——把本来最值钱的“拒绝低价短途单、保护长途空座”的 return None 决策给强行接回来了，导致策略瞬间退化成 Myopic 贪心（88.38% vs 88.23%）。", False)],
            [("4. 三条可直接落地的改进规范：", True, RGB_NAVY), (" ① Prompt 中给出 solve_lp 精确入参形状示例；② AST 规则禁止在 decide 内用裸 try/except 吞掉工具异常（报错即刻暴露给下一轮修复）；③ 在进化体检表中新增「LP 成功调用率 / 回退触发率 / 拒单率」三项关键诊断指标。", False)],
        ],
        accent_hex=HEX_TEAL,
        bg_hex=HEX_HIGHLIGHT_GREEN,
    )

    # ==========================================================================
    # CHAPTER 6: SELECTION GUIDE & REPRODUCIBILITY
    # ==========================================================================
    add_h1(doc, "六、业务落地选型决策指南与复现说明")

    add_h2(doc, "6.1 不同业务场景下的最佳实践选型表")
    add_styled_table(
        doc,
        ["业务场景特征", "推荐技术路线", "预期收益达成率", "单步延迟 / 成本", "关键工程注意点"],
        [
            [
                "标准 Assign-to-Seat / 可写为中小型 LP，且允许引入开源库",
                "**BPC-M + OR-Tools GLOP 或 SciPy HiGHS**",
                "小列车 95.3%–95.4%\n大列车 98.8%–99.0%",
                "~0.5–1.0 ms/步\n零商业授权费",
                "综合性价比之王：精度媲美商业求解器，且抗 ±15% 需求预测误差最稳",
            ],
            [
                "极致低延迟 / 严禁引入任何求解器 / 含复杂非凸业务规则",
                "**旗舰大模型离线 Top-K 进化纯代码策略（如 E097）**",
                "同分布 ~94.2%\n匹配大列车 ~97.0%",
                "~0.1 ms/步\n线上零 API 成本",
                "训练集必须覆盖宽/中/紧多档稀缺度，避免极端稀缺外推失准",
            ],
            [
                "复杂混合问题（LP 松弛 + 有限样本方差/非凸业务修正）",
                "**AI + 可选求解器组件（solver_toolkit）联合进化**",
                "潜力 ≥ 95.5%\n（LP 定价 + AI 校准）",
                "~1 ms/步\n线上零 API 成本",
                "必须配强类型契约、禁用静默吞错、反馈 LP 命中率，并使用高配推理档位",
            ],
            [
                "线上每来一单直接调 LLM 做数值控票决策",
                "不推荐（反面教材）",
                "~73.7%（低于贪心）",
                "> 3,000 ms/步\n高额 Token 费用",
                "数值尺度失真严重且延迟不可接受",
            ],
        ],
        [3.5, 3.6, 2.8, 2.6, 4.1],
        alignments=[
            WD_ALIGN_PARAGRAPH.LEFT,
            WD_ALIGN_PARAGRAPH.LEFT,
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.LEFT,
        ],
        highlight_rows={0: (HEX_HIGHLIGHT_GREEN, False), 1: (HEX_HIGHLIGHT_GOLD, False)},
        font_size=8.6,
    )

    add_h2(doc, "6.2 代码仓库与一键复现指引")
    add_body(
        doc,
        [
            ("全部实验源码、原始 JSON/JSONL 结果数据与高清图表均已开源托管至 GitHub：", False),
            ("https://github.com/shiyidege/-assign-to-seat-glm-eval", True, RGB_BLUE),
            ("（全仓库零硬编码密钥，按需通过环境变量 ", False),
            ("GLM_API_KEY", True, RGB_NAVY, True),
            (" 鉴权；所有本地评测与开源求解器对决实验均无需任何 API 费用）。", False),
        ],
    )

    add_code_block(
        doc,
        """# 1. 安装可选开源求解器依赖（仅实验 4、6 需要；实验 1~3、5 零第三方依赖）
pip install --user scipy ortools pulp

# 2. 零 API 成本：复现实验 4（E097 vs 论文 HiGHS LP + 大列车三档稀缺度泛化）
python3 compare_vs_paper_methods.py

# 3. 零 API 成本：复现实验 6（开源求解器组件自检 + 全量 17 组留出集排位赛）
cd open_solver_component
python3 solver_toolkit.py
python3 compare_all_via_toolkit.py

# 4. 如需复现大模型进化过程（实验 3 / 5 / 6.4），设置环境变量后运行：
export GLM_API_KEY="你的智谱Coding_Plan_Key"
python3 evolve_population.py --rounds 100 --workers 5 --topk 6 --seed-existing
python3 open_solver_component/evolve_with_solver_option.py --rounds 10 --model glm-5""",
        title="核心复现命令清单",
    )

    doc.save(OUT_DOCX)
    print(f"Successfully generated: {OUT_DOCX} ({OUT_DOCX.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    build()
