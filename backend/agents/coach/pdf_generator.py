"""
PDF export layer for coach reports.

Uses fpdf2 (pure Python, no system dependencies) to generate a
professional A4 report from a CoachReport dict (already JSON-serialised).

Install: pip install fpdf2
"""
from __future__ import annotations

import io
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Colour palette (matches the dark UI theme mapped to print-friendly tones)
# ─────────────────────────────────────────────────────────────────────────────
_C_BLACK       = (10,  10,  15)
_C_DARK        = (30,  30,  45)
_C_MID         = (80,  80, 100)
_C_LIGHT       = (150, 150, 170)
_C_BORDER      = (210, 210, 220)
_C_BG_SOFT     = (245, 245, 250)
_C_ACCENT      = (124, 106, 247)
_C_GREEN       = (52,  170, 120)
_C_AMBER       = (200, 150,  30)
_C_RED         = (220,  80,  80)
_C_WHITE       = (255, 255, 255)


def _score_color(score: float) -> tuple:
    """Map a 1–5 score to a colour."""
    if score >= 4.2:
        return _C_GREEN
    if score >= 3.0:
        return _C_AMBER
    return _C_RED


def _overall_color(score: float) -> tuple:
    """Map a 0–10 overall score to a colour."""
    if score >= 7.5:
        return _C_GREEN
    if score >= 5.5:
        return _C_AMBER
    return _C_RED


# ─────────────────────────────────────────────────────────────────────────────
# Main generator
# ─────────────────────────────────────────────────────────────────────────────

def generate_pdf(report: dict) -> bytes:
    """
    Generate a PDF from a CoachReport dict and return raw bytes.
    Returns an empty bytes object on failure (logs the error).
    """
    try:
        from fpdf import FPDF  # type: ignore[import]
    except ImportError:
        logger.error("[PDF] fpdf2 not installed. Run: pip install fpdf2")
        return b""

    try:
        return _build_pdf(report, FPDF)
    except Exception as e:
        logger.error(f"[PDF] Generation failed: {e}", exc_info=True)
        return b""


def _build_pdf(report: dict, FPDF) -> bytes:
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(18, 18, 18)
    pdf.add_page()

    W = pdf.w - 36  # usable width (page - left - right margins)

    # ── Cover / Header block ──────────────────────────────────────────────
    _section_header_box(pdf, W, report)
    pdf.ln(6)

    # ── Overall score hero ────────────────────────────────────────────────
    overall = float(report.get("overall_score") or 0)
    _score_hero(pdf, W, overall, report)
    pdf.ln(4)

    # ── Overall summary ───────────────────────────────────────────────────
    _card_heading(pdf, "Overall Assessment")
    _body_text(pdf, W, report.get("overall_summary") or "")
    _trajectory_tag(pdf, report.get("score_summary", {}).get("trajectory") or "")
    pdf.ln(6)

    # ── Performance scores ────────────────────────────────────────────────
    _card_heading(pdf, "Performance Scores")
    scores = report.get("score_summary", {}).get("scores") or {}
    dim_labels = report.get("dimension_labels") or {}
    for key, val in scores.items():
        label = dim_labels.get(key) or key.replace("_", " ").title()
        _score_bar(pdf, W, label, float(val or 0))
    pdf.ln(4)

    # ── Strongest / Weakest mini-cards ────────────────────────────────────
    ss = report.get("score_summary") or {}
    strongest = ss.get("strongest_dimension") or ""
    weakest   = ss.get("weakest_dimension") or ""
    if strongest or weakest:
        _extremes_row(pdf, W, strongest, weakest)
        pdf.ln(4)

    # ── Strengths ─────────────────────────────────────────────────────────
    strengths = report.get("strengths") or []
    if strengths:
        _card_heading(pdf, "Strengths")
        for fp in strengths:
            _feedback_item(pdf, W, fp, color=_C_GREEN)
        pdf.ln(2)

    # ── Growth Areas ──────────────────────────────────────────────────────
    improvements = report.get("improvement_areas") or []
    if improvements:
        _card_heading(pdf, "Growth Areas")
        for fp in improvements:
            _feedback_item(pdf, W, fp, color=_C_AMBER)
        pdf.ln(2)

    # ── Role Fit Assessment ───────────────────────────────────────────────
    role_fit_assessment = report.get("role_fit_assessment") or ""
    role_fit_rating     = report.get("role_fit_rating") or ""
    if role_fit_assessment or role_fit_rating:
        _card_heading(pdf, "Role Fit Assessment")
        _role_fit_block(pdf, W, role_fit_rating, role_fit_assessment)
        pdf.ln(4)

    # ── Ideal Direction Analysis ──────────────────────────────────────────
    turn_insights = report.get("turn_insights") or []
    key_missing   = report.get("key_missing_concepts") or []
    if turn_insights:
        _card_heading(pdf, "Ideal Direction Analysis")
        _ideal_direction_section(pdf, W, turn_insights)
        pdf.ln(2)
    if key_missing:
        _card_heading(pdf, "Key Concept Gaps (Cross-Turn)")
        _missing_concepts_block(pdf, W, key_missing)
        pdf.ln(4)

    # ── Detailed Feedback ─────────────────────────────────────────────────
    tech_fb   = report.get("technical_feedback")
    comm_fb   = report.get("communication_feedback")
    if tech_fb or comm_fb:
        _card_heading(pdf, "Detailed Feedback")
        if tech_fb:
            _feedback_item(pdf, W, tech_fb, color=_C_MID)
        if comm_fb:
            _feedback_item(pdf, W, comm_fb, color=_C_MID)
        pdf.ln(2)

    # ── Practice Recommendations ──────────────────────────────────────────
    recs = report.get("practice_recommendations") or []
    if recs:
        _card_heading(pdf, "Practice Recommendations")
        for i, rec in enumerate(recs, 1):
            _numbered_item(pdf, W, i, rec)
        pdf.ln(2)

    # ── Topic Coverage ────────────────────────────────────────────────────
    coverage = report.get("topic_coverage") or []
    if coverage:
        _card_heading(pdf, "Topic Coverage")
        _coverage_table(pdf, W, coverage)
        pdf.ln(2)

    # ── Transcript ────────────────────────────────────────────────────────
    turns = report.get("_turns") or []
    if turns:
        _card_heading(pdf, "Full Transcript")
        for t in turns:
            _transcript_turn(pdf, W, t)
        pdf.ln(2)

    # ── Footer ────────────────────────────────────────────────────────────
    _footer(pdf, report)

    return bytes(pdf.output())


# ─────────────────────────────────────────────────────────────────────────────
# Drawing primitives
# ─────────────────────────────────────────────────────────────────────────────

def _set_font(pdf, style: str, size: int):
    """helvetica covers the full Latin range without embedding extra fonts."""
    pdf.set_font("Helvetica", style=style, size=size)


def _section_header_box(pdf, W: float, report: dict):
    pdf.set_fill_color(*_C_DARK)
    pdf.rect(pdf.l_margin, pdf.get_y(), W, 24, "F")

    pdf.set_y(pdf.get_y() + 5)
    _set_font(pdf, "B", 14)
    pdf.set_text_color(*_C_WHITE)
    pdf.cell(W, 7, "Interview Performance Report", align="L", ln=True)

    _set_font(pdf, "", 9)
    pdf.set_text_color(*_C_BORDER)
    role      = report.get("role") or ""
    focus     = report.get("focus_area") or ""
    turns     = report.get("total_turns") or 0
    duration  = report.get("interview_duration_approx") or ""
    meta = f"{role}  |  {focus}  |  {turns} turns  |  {duration}"
    pdf.cell(W, 6, meta, align="L", ln=True)

    pdf.set_text_color(*_C_BLACK)
    pdf.ln(3)


def _score_hero(pdf, W: float, overall: float, report: dict):
    color = _overall_color(overall)
    pdf.set_fill_color(*_C_BG_SOFT)
    pdf.rect(pdf.l_margin, pdf.get_y(), W, 22, "F")

    y = pdf.get_y() + 4
    pdf.set_y(y)
    _set_font(pdf, "", 8)
    pdf.set_text_color(*_C_MID)
    pdf.cell(W, 4, "OVERALL SCORE", align="C", ln=True)

    _set_font(pdf, "B", 28)
    pdf.set_text_color(*color)
    pdf.cell(W, 12, f"{overall:.1f} / 10", align="C", ln=True)
    pdf.set_text_color(*_C_BLACK)


def _card_heading(pdf, title: str):
    pdf.set_draw_color(*_C_BORDER)
    pdf.set_fill_color(*_C_BG_SOFT)

    _set_font(pdf, "B", 9)
    pdf.set_text_color(*_C_ACCENT)
    pdf.cell(0, 6, title.upper(), ln=True)
    pdf.set_draw_color(*_C_ACCENT)
    pdf.set_line_width(0.4)
    x0 = pdf.l_margin
    y0 = pdf.get_y()
    pdf.line(x0, y0, x0 + 40, y0)
    pdf.set_line_width(0.2)
    pdf.set_text_color(*_C_BLACK)
    pdf.ln(3)


def _body_text(pdf, W: float, text: str):
    _set_font(pdf, "", 10)
    pdf.set_text_color(*_C_DARK)
    pdf.multi_cell(W, 5.5, _safe(text))
    pdf.set_text_color(*_C_BLACK)


def _trajectory_tag(pdf, traj: str):
    tags = {
        "improving": ("improving", _C_GREEN),
        "declining": ("declining", _C_RED),
        "stable":    ("stable",   _C_AMBER),
    }
    label, color = tags.get(traj, ("insufficient data", _C_LIGHT))
    pdf.ln(2)
    _set_font(pdf, "I", 8)
    pdf.set_text_color(*color)
    pdf.cell(0, 5, _safe(f"Trajectory: {label}"), ln=True)
    pdf.set_text_color(*_C_BLACK)


def _score_bar(pdf, W: float, label: str, score: float):
    bar_h = 4
    bar_w = W * 0.55
    label_w = W * 0.38
    val_w = W - label_w - bar_w - 2

    _set_font(pdf, "", 9)
    pdf.set_text_color(*_C_DARK)
    x = pdf.l_margin
    y = pdf.get_y()

    pdf.set_xy(x, y)
    pdf.cell(label_w, bar_h + 2, _safe(label), align="L")

    pdf.set_xy(x + label_w + 2, y + 1)
    pdf.set_fill_color(*_C_BORDER)
    pdf.rect(x + label_w + 2, y + 1, bar_w, bar_h, "F")
    fill = min(1.0, score / 5.0) * bar_w
    pdf.set_fill_color(*_score_color(score))
    pdf.rect(x + label_w + 2, y + 1, fill, bar_h, "F")

    pdf.set_xy(x + label_w + bar_w + 4, y)
    _set_font(pdf, "B", 9)
    pdf.set_text_color(*_score_color(score))
    pdf.cell(val_w, bar_h + 2, _safe(f"{score:.1f}"), align="L")

    pdf.set_text_color(*_C_BLACK)
    pdf.ln(7)


def _extremes_row(pdf, W: float, strongest: str, weakest: str):
    half = (W - 4) / 2
    y = pdf.get_y()
    x = pdf.l_margin

    # Strongest card
    pdf.set_fill_color(220, 245, 235)
    pdf.rect(x, y, half, 16, "F")
    _set_font(pdf, "", 7)
    pdf.set_text_color(*_C_MID)
    pdf.set_xy(x + 3, y + 3)
    pdf.cell(half - 6, 4, "STRONGEST", ln=False)
    _set_font(pdf, "B", 9)
    pdf.set_text_color(*_C_GREEN)
    pdf.set_xy(x + 3, y + 8)
    pdf.cell(half - 6, 5, _safe(strongest or "Balanced"), ln=False)

    # Weakest card
    pdf.set_fill_color(250, 235, 235)
    pdf.rect(x + half + 4, y, half, 16, "F")
    _set_font(pdf, "", 7)
    pdf.set_text_color(*_C_MID)
    pdf.set_xy(x + half + 7, y + 3)
    pdf.cell(half - 6, 4, _safe("NEEDS WORK"), ln=False)
    _set_font(pdf, "B", 9)
    pdf.set_text_color(*_C_RED)
    pdf.set_xy(x + half + 7, y + 8)
    pdf.cell(half - 6, 5, _safe(weakest or "Balanced"), ln=False)

    pdf.set_text_color(*_C_BLACK)
    pdf.ln(20)


def _feedback_item(pdf, W: float, fp: dict, color: tuple = _C_MID):
    if not fp or not isinstance(fp, dict):
        return

    # Left accent bar
    x = pdf.l_margin
    y = pdf.get_y()
    pdf.set_fill_color(*color)
    pdf.rect(x, y, 2, 1, "F")  # will extend after content is written

    obs = fp.get("observation") or ""
    sug = fp.get("suggestion") or ""
    evidence = fp.get("evidence") or []

    # Observation
    _set_font(pdf, "B", 9)
    pdf.set_text_color(*_C_DARK)
    pdf.set_x(x + 5)
    pdf.multi_cell(W - 5, 5, _safe(obs))

    # Evidence chips (turn references)
    if evidence:
        _set_font(pdf, "I", 7.5)
        pdf.set_text_color(*_C_LIGHT)
        ev_parts = []
        for ev in evidence[:3]:
            if isinstance(ev, dict):
                ti = ev.get("turn_index", "?")
                exc = (ev.get("excerpt") or "")[:50]
                ev_parts.append(f"[Turn {ti}] {exc}")
        if ev_parts:
            pdf.set_x(x + 5)
            pdf.multi_cell(W - 5, 4.5, "  ".join(ev_parts))

    # Suggestion
    if sug:
        _set_font(pdf, "", 8.5)
        pdf.set_text_color(*_C_MID)
        pdf.set_x(x + 5)
        pdf.multi_cell(W - 5, 5, _safe(f"Practice: {sug}"))

    # Draw the accent bar retroactively over actual height (simpler: just draw a small line)
    y_end = pdf.get_y()
    bar_h = y_end - y
    pdf.set_fill_color(*color)
    pdf.rect(x, y, 2, max(bar_h, 1), "F")

    pdf.set_text_color(*_C_BLACK)
    pdf.ln(4)


def _numbered_item(pdf, W: float, num: int, text: str):
    x = pdf.l_margin
    # Number circle (approximated as bold prefix)
    _set_font(pdf, "B", 9)
    pdf.set_text_color(*_C_ACCENT)
    pdf.set_x(x)
    pdf.cell(7, 6, f"{num}.", align="L")
    _set_font(pdf, "", 9)
    pdf.set_text_color(*_C_DARK)
    pdf.multi_cell(W - 7, 6, _safe(text))
    pdf.set_text_color(*_C_BLACK)
    pdf.ln(1)


def _coverage_table(pdf, W: float, coverage: list[dict]):
    col_topic = W * 0.45
    col_status = W * 0.22
    col_turns = W * 0.13
    col_peak = W * 0.20

    # Header
    _set_font(pdf, "B", 8)
    pdf.set_text_color(*_C_MID)
    pdf.set_fill_color(*_C_BG_SOFT)
    x = pdf.l_margin
    pdf.set_x(x)
    pdf.cell(col_topic,  6, "Topic",   border=0, fill=True)
    pdf.cell(col_status, 6, "Status",  border=0, fill=True)
    pdf.cell(col_turns,  6, "Turns",   border=0, fill=True, align="C")
    pdf.cell(col_peak,   6, "Peak Depth", border=0, fill=True, align="C", ln=True)

    # Rows
    _set_font(pdf, "", 8.5)
    for i, tc in enumerate(coverage):
        if not isinstance(tc, dict):
            continue
        pdf.set_fill_color(*(_C_BG_SOFT if i % 2 == 0 else _C_WHITE))
        pdf.set_text_color(*_C_DARK)
        pdf.set_x(pdf.l_margin)

        status = tc.get("status") or ""
        status_color = (
            _C_GREEN if status == "visited"
            else _C_AMBER if status == "depth_ceiling"
            else _C_LIGHT
        )

        pdf.cell(col_topic,  6, _safe(tc.get("topic") or ""), fill=True)
        pdf.set_text_color(*status_color)
        pdf.cell(col_status, 6, _safe(status), fill=True)
        pdf.set_text_color(*_C_DARK)
        pdf.cell(col_turns,  6, str(tc.get("turns_spent") or 0), fill=True, align="C")
        peak = tc.get("peak_depth_score")
        pdf.cell(col_peak,   6,
                 f"{peak}/5" if peak is not None else "-",
                 fill=True, align="C", ln=True)

    pdf.set_text_color(*_C_BLACK)


def _transcript_turn(pdf, W: float, turn: dict):
    idx = turn.get("turn_index", "?")
    topic = turn.get("topic") or ""
    question = turn.get("question") or ""
    answer = turn.get("answer") or ""

    # Q header
    pdf.set_fill_color(*_C_BG_SOFT)
    pdf.set_x(pdf.l_margin)
    _set_font(pdf, "B", 8)
    pdf.set_text_color(*_C_MID)
    q_short = question[:120] + ("..." if len(question) > 120 else "")
    pdf.multi_cell(W, 5, _safe(f"Q{idx}  {topic}  {q_short}"),
                   fill=True)

    # Answer
    _set_font(pdf, "", 9)
    pdf.set_text_color(*_C_DARK)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(W, 5.5, _safe(answer[:800] + ("..." if len(answer) > 800 else "")))

    pdf.set_text_color(*_C_BLACK)
    pdf.ln(3)


def _footer(pdf, report: dict):
    generated_at = report.get("generated_at") or ""
    if generated_at:
        try:
            dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
            generated_at = dt.strftime("%d %b %Y %H:%M UTC")
        except Exception:
            pass

    pdf.set_y(-15)
    _set_font(pdf, "I", 7)
    pdf.set_text_color(*_C_LIGHT)
    pdf.cell(0, 5, f"AI Interview Coach  |  Generated {generated_at}", align="C", ln=True)
    pdf.set_text_color(*_C_BLACK)


# ─────────────────────────────────────────────────────────────────────────────
# Coach Intelligence sections
# ─────────────────────────────────────────────────────────────────────────────

_FIT_COLORS = {
    "strong_fit":  (_C_GREEN,  "STRONG FIT",  (220, 245, 235)),
    "partial_fit": (_C_AMBER,  "PARTIAL FIT", (252, 243, 220)),
    "weak_fit":    (_C_RED,    "WEAK FIT",    (250, 235, 235)),
}


def _role_fit_block(pdf, W: float, rating: str, assessment: str):
    """Render the role-fit badge + assessment paragraph."""
    color, label, bg = _FIT_COLORS.get(rating, (_C_MID, rating.upper().replace("_", " "), _C_BG_SOFT))

    # Badge box
    badge_w = 32
    x = pdf.l_margin
    y = pdf.get_y()
    pdf.set_fill_color(*bg)
    pdf.rect(x, y, badge_w, 8, "F")
    _set_font(pdf, "B", 8)
    pdf.set_text_color(*color)
    pdf.set_xy(x + 1, y + 2)
    pdf.cell(badge_w - 2, 5, _safe(label), align="C")
    pdf.set_text_color(*_C_BLACK)
    pdf.ln(10)

    # Assessment text
    if assessment:
        _set_font(pdf, "I", 9)
        pdf.set_text_color(*_C_DARK)
        pdf.set_x(x)
        pdf.multi_cell(W, 5.5, _safe(assessment))
        pdf.set_text_color(*_C_BLACK)


def _ideal_direction_section(pdf, W: float, turn_insights: list):
    """Render one card per TurnInsight entry."""
    for insight in turn_insights:
        if not isinstance(insight, dict):
            continue

        turn_idx = insight.get("turn_index", "?")
        topic = insight.get("topic") or ""
        ideal_signals = insight.get("ideal_signals") or []
        missing = insight.get("missing_concepts") or []
        outline = insight.get("ideal_answer_outline") or ""
        severity = insight.get("gap_severity", "minor")

        sev_color = _C_RED if severity == "major" else _C_AMBER

        # Turn header
        x = pdf.l_margin
        pdf.set_fill_color(*_C_BG_SOFT)
        _set_font(pdf, "B", 8.5)
        pdf.set_text_color(*_C_DARK)
        pdf.set_x(x)
        pdf.cell(W, 6, _safe(f"Turn {turn_idx}  |  {topic}"), fill=True, ln=True)

        # "What strong answers would include" subsection
        if ideal_signals:
            _set_font(pdf, "B", 8)
            pdf.set_text_color(*_C_GREEN)
            pdf.set_x(x + 3)
            pdf.cell(W - 3, 5, "What strong answers would include:", ln=True)
            _set_font(pdf, "", 8.5)
            pdf.set_text_color(*_C_DARK)
            for sig in ideal_signals[:4]:
                pdf.set_x(x + 6)
                pdf.multi_cell(W - 6, 5, _safe(f"+ {sig}"))

        # "What was missing" subsection
        if missing:
            _set_font(pdf, "B", 8)
            pdf.set_text_color(*sev_color)
            pdf.set_x(x + 3)
            pdf.cell(W - 3, 5, "Reasoning gaps identified:", ln=True)
            _set_font(pdf, "", 8.5)
            pdf.set_text_color(*_C_DARK)
            for m in missing[:4]:
                pdf.set_x(x + 6)
                pdf.multi_cell(W - 6, 5, _safe(f"- {m}"))

        # Ideal direction
        if outline:
            _set_font(pdf, "I", 8.5)
            pdf.set_text_color(*_C_MID)
            pdf.set_x(x + 3)
            pdf.multi_cell(W - 3, 5, _safe(outline))
            pdf.set_text_color(*_C_BLACK)

        pdf.ln(4)


def _missing_concepts_block(pdf, W: float, concepts: list):
    """Render a compact list of cross-turn missing concepts."""
    _set_font(pdf, "", 9)
    pdf.set_text_color(*_C_DARK)
    for concept in concepts[:3]:
        pdf.set_x(pdf.l_margin + 3)
        pdf.multi_cell(W - 3, 5.5, _safe(f"- {concept}"))
    pdf.set_text_color(*_C_BLACK)


# ─────────────────────────────────────────────────────────────────────────────
# Utility
# ─────────────────────────────────────────────────────────────────────────────

def _safe(text: str) -> str:
    """Strip characters that fpdf2 cannot encode in latin-1."""
    if not text:
        return ""
    # Replace common unicode punctuation with ASCII equivalents
    replacements = {
        "’": "'",  # right single quote
        "‘": "'",  # left single quote
        "“": '"',  # left double quote
        "”": '"',  # right double quote
        "–": "-",  # en dash
        "—": "--", # em dash
        "…": "...", # ellipsis
        "→": "->",  # right arrow
        "←": "<-",  # left arrow
        "·": "·",   # middle dot (latin-1 ok)
        "•": "*",   # bullet
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    # Strip anything still outside latin-1
    return text.encode("latin-1", errors="replace").decode("latin-1")
