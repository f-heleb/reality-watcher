from __future__ import annotations

import os, csv, math
from datetime import datetime
from statistics import median
from typing import List, Dict, Tuple, Optional

LOG_DIR = "logs"

def _log_path_for_channel(channel_id: str) -> str:
    os.makedirs(LOG_DIR, exist_ok=True)
    return os.path.join(LOG_DIR, f"sreality_{channel_id}.tsv")

def log_append(channel_id: str, items: List[Dict]) -> None:
    """
    Append do per-channel TSV logu:
    dt, id, title, url, dispo, locality, area_m2, price_czk, price_per_m2
    """
    path = _log_path_for_channel(channel_id)
    new_file = not os.path.exists(path)
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        if new_file:
            w.writerow(["dt","id","title","url","dispo","locality","area_m2","price_czk","price_per_m2"])
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for it in items:
            w.writerow([
                now,
                it.get("id",""),
                (it.get("title","") or "").replace("\t"," ").strip(),
                it.get("url",""),
                (it.get("dispo") or "") or "",
                (it.get("locality") or "") or "",
                _to_str_num(it.get("area_m2")),
                _to_str_num(it.get("price_czk")),
                _to_str_num(it.get("price_per_m2")),
            ])

def _to_str_num(v) -> str:
    if v is None: return ""
    try:
        if isinstance(v, float):
            # u m2 chceme klidně desetinné
            return f"{v}"
        return str(int(v))
    except Exception:
        try:
            return str(float(v))
        except Exception:
            return ""

def _parse_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None

def read_log(channel_id: str) -> List[Dict]:
    path = _log_path_for_channel(channel_id)
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        r = csv.DictReader(f, delimiter="\t")
        for row in r:
            row["area_m2"] = _parse_float(row.get("area_m2",""))
            row["price_czk"] = _parse_float(row.get("price_czk",""))
            row["price_per_m2"] = _parse_float(row.get("price_per_m2",""))
            out.append(row)
    return out

def _slice_last(items: List[Dict], n: int) -> List[Dict]:
    return items[-n:] if n > 0 else []

def _slice_window(items: List[Dict], dt_from: str, dt_to: Optional[str]) -> List[Dict]:
    def _to_dt(s):
        try: return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        except Exception: return None
    df = _to_dt(dt_from)
    dt = _to_dt(dt_to) if dt_to else None
    out = []
    for it in items:
        dti = _to_dt(it.get("dt",""))
        if not dti: 
            continue
        if df and dti < df: 
            continue
        if dt and dti > dt:
            continue
        out.append(it)
    return out

def _rm_outliers_by_factor(items: List[Dict], factor: float = 10.0) -> List[Dict]:
    """Vyřadí z cenových statistik extrémy (<= med/factor nebo >= med*factor).
       Vstup nefiltrujeme na výstupu (jen pro výpočet metrik).
    """
    prices = [it["price_czk"] for it in items if isinstance(it.get("price_czk"), (int,float))]
    if len(prices) < 3:
        return items[:]  # málo dat -> nenecháme seříznout
    med = median(prices)
    if med <= 0:
        return items[:]
    lo, hi = med / factor, med * factor
    keep = []
    for it in items:
        p = it.get("price_czk")
        if isinstance(p, (int,float)) and (p < lo or p > hi):
            # outlier -> přeskočit ve statistikách
            continue
        keep.append(it)
    return keep

def _basic_stats(nums: List[float]) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    nums = [x for x in nums if isinstance(x,(int,float)) and not math.isnan(x)]
    if not nums:
        return None, None, None, None
    return (min(nums), median(nums), sum(nums)/len(nums), max(nums))

def summarize(items: List[Dict]) -> Dict:
    areas = [it["area_m2"] for it in items if isinstance(it.get("area_m2"), (int,float))]
    prices = [it["price_czk"] for it in items if isinstance(it.get("price_czk"), (int,float))]
    ppm2   = [it["price_per_m2"] for it in items if isinstance(it.get("price_per_m2"), (int,float))]

    a_min, a_med, a_avg, a_max = _basic_stats(areas)
    p_min, p_med, p_avg, p_max = _basic_stats(prices)
    m_min, m_med, m_avg, m_max = _basic_stats(ppm2)

    return {
        "count": len(items),
        "area": {"min":a_min, "med":a_med, "avg":a_avg, "max":a_max},
        "price":{"min":p_min, "med":p_med, "avg":p_avg, "max":p_max},
        "ppm2": {"min":m_min, "med":m_med, "avg":m_avg, "max":m_max},
    }

def format_summary_block(title: str, raw_stats: Dict, clean_stats: Dict) -> list:
    def f(v, unit=""):
        return "-" if v is None else (f"{int(v):,}{unit}".replace(",", " ") if isinstance(v,(int,float)) else str(v))

    def lines(label, s, unit=""):
        return (
            f"*{label}*: count {f(s['count'])}\n"
            f"• min/med/avg/max: {f(s[label]['min'], unit)} / {f(s[label]['med'], unit)} / {f(s[label]['avg'], unit)} / {f(s[label]['max'], unit)}"
        )

    blocks = [
        {"type":"header","text":{"type":"plain_text","text":title}},
        {"type":"divider"},
        {"type":"section","text":{"type":"mrkdwn","text": "*Raw data* (bez filtru outlierů)"}},
        {"type":"section","text":{"type":"mrkdwn","text": lines("price", {"count":raw_stats["count"], **raw_stats}, " Kč") }},
        {"type":"section","text":{"type":"mrkdwn","text": lines("area",  {"count":raw_stats["count"], **raw_stats}, " m²") }},
        {"type":"section","text":{"type":"mrkdwn","text": lines("ppm2",  {"count":raw_stats["count"], **raw_stats}, " Kč/m²") }},
        {"type":"divider"},
        {"type":"section","text":{"type":"mrkdwn","text": "*Cleaned* (bez extrémů ±10× mediánu ceny)"}},
        {"type":"section","text":{"type":"mrkdwn","text": lines("price", {"count":clean_stats["count"], **clean_stats}, " Kč") }},
        {"type":"section","text":{"type":"mrkdwn","text": lines("area",  {"count":clean_stats["count"], **clean_stats}, " m²") }},
        {"type":"section","text":{"type":"mrkdwn","text": lines("ppm2",  {"count":clean_stats["count"], **clean_stats}, " Kč/m²") }},
    ]
    return blocks

def stats_last(channel_id: str, n: int) -> Tuple[list, int, int]:
    rows = read_log(channel_id)
    sample = _slice_last(rows, n)
    raw = summarize(sample)
    clean = summarize(_rm_outliers_by_factor(sample, 10.0))
    blocks = format_summary_block(f"Summary – last {n} items", raw, clean)
    return blocks, len(sample), len(rows)

def stats_window(channel_id: str, dt_from: str, dt_to: Optional[str]) -> Tuple[list, int, int]:
    rows = read_log(channel_id)
    sample = _slice_window(rows, dt_from, dt_to)
    raw = summarize(sample)
    clean = summarize(_rm_outliers_by_factor(sample, 10.0))
    title = f"Summary – window {dt_from} → {dt_to or 'now'}"
    blocks = format_summary_block(title, raw, clean)
    return blocks, len(sample), len(rows)