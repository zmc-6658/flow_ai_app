from __future__ import annotations

import re


CM_TO_PT = 28.346
MM_TO_PT = 2.835

CN_SIZE_TO_PT: dict[str, float] = {
    "初号": 42.0,
    "小初": 36.0,
    "一号": 26.0,
    "小一": 24.0,
    "二号": 22.0,
    "小二": 18.0,
    "三号": 16.0,
    "小三": 15.0,
    "四号": 14.0,
    "小四": 12.0,
    "五号": 10.5,
    "小五": 9.0,
    "六号": 7.5,
    "小六": 6.5,
    "七号": 5.5,
    "八号": 5.0,
}


def pt_to_cn_size(pt: float, *, tolerance: float = 0.05) -> str:

    value = _round_pt(pt)
    for label, mapped_pt in CN_SIZE_TO_PT.items():
        if abs(value - mapped_pt) <= tolerance:
            return f"{label} ({value:.1f} 磅)"
    return f"{value:.1f} 磅"


def pt_to_cn_chars(pt: float, *, base_font_size_pt: float = 12.0) -> str:

    value = _round_pt(pt)
    if base_font_size_pt <= 0:
        raise ValueError("base_font_size_pt 必须大于 0")

    chars = value / base_font_size_pt
    chars_text = _format_number(chars)
    return f"{chars_text} 字符 ({value:.1f} 磅)"


def line_spacing_to_cn(
    *,
    multiple: float | None = None,
    fixed_pt: float | None = None,
) -> str:

    if multiple is not None:
        return f"{_format_number(multiple)} 倍行距"
    if fixed_pt is not None:
        return f"固定值 {_round_pt(fixed_pt):.1f} 磅"
    raise ValueError("line_spacing_to_cn 需要传入 multiple 或 fixed_pt")


def parse_length_to_pt(text: str, *, base_font_size_pt: float = 12.0) -> float:
    """将人类可读的排版长度解析为磅值。

    支持格式："12pt"、"12 磅"、"1.2cm"、"8毫米"、"小四"、"小四号"、"2字符"、"2字"。
    """

    if base_font_size_pt <= 0:
        raise ValueError("base_font_size_pt 必须大于 0")

    normalized = re.sub(r"\s+", "", text.strip().lower())
    if not normalized:
        raise ValueError("无法解析空的排版长度")

    cn_size_key = normalized.removesuffix("号")
    if cn_size_key in CN_SIZE_TO_PT:
        return CN_SIZE_TO_PT[cn_size_key]

    if match := re.fullmatch(r"([+-]?\d+(?:\.\d+)?)(?:pt|pts|磅|点)", normalized):
        return _round_pt(float(match.group(1)))

    if match := re.fullmatch(r"([+-]?\d+(?:\.\d+)?)(?:cm|厘米|公分)", normalized):
        return _round_pt(float(match.group(1)) * CM_TO_PT)

    if match := re.fullmatch(r"([+-]?\d+(?:\.\d+)?)(?:mm|毫米)", normalized):
        return _round_pt(float(match.group(1)) * MM_TO_PT)

    if match := re.fullmatch(r"([+-]?\d+(?:\.\d+)?)(?:字符|字)", normalized):
        return _round_pt(float(match.group(1)) * base_font_size_pt)

    raise ValueError(
        f"无法解析排版长度 '{text}'，支持单位：pt/磅、cm/厘米、mm/毫米、中文字号、字符/字"
    )


def _round_pt(value: float) -> float:
    return round(float(value), 2)


def _format_number(value: float) -> str:
    rounded = round(float(value), 2)
    if rounded.is_integer():
        return str(int(rounded))
    return f"{rounded:g}"
