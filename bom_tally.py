#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__version__ = "1.0.0"

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple, List

import pandas as pd


# ----------------------------
# Normalization helpers
# ----------------------------



def _clean_str(x) -> str:
    if pd.isna(x):
        return ""
    return str(x).strip()


def normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", _clean_str(s)).strip()


def normalize_decimal(s: str) -> str:
    return _clean_str(s).replace(",", ".")


def _strip_noise(s: str) -> str:
    s = normalize_spaces(s)
    s = s.replace("μ", "u").replace("µ", "u")
    s = s.replace("Ω", "ohm").replace("Ω", "ohm")
    return s


def _fmt_eng(value: float, thresholds: List[Tuple[float, str]]) -> str:
    abs_v = abs(value)
    for factor, suffix in thresholds:
        if abs_v >= factor:
            scaled = value / factor
            return f"{scaled:.6g} {suffix}"
    factor, suffix = thresholds[-1]
    scaled = value / factor
    return f"{scaled:.6g} {suffix}"

# TBD
def normalize_voltage_or_rating(v: str) -> str:
    v0 = _strip_noise(v)
    if not v0:
        return ""
    vv = normalize_decimal(v0)

    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([vV])\b", vv)
    if m:
        num = m.group(1)
        num = str(float(num)).rstrip("0").rstrip(".") if "." in num else num
        return f"{num} V"

    return normalize_spaces(vv)


def normalize_tolerance(t: str) -> str:
    t0 = _strip_noise(t)
    if not t0:
        return ""
    t0 = t0.replace("％", "%")
    t0 = re.sub(r"\s*%\s*", "%", t0)
    t0 = re.sub(r"\s*±\s*", "±", t0)
    return t0


# ----------------------------
# Family detection
# ----------------------------

def detect_family(ref: str, comp_type: str) -> str:
    """Prefer ref prefix, then keywords. Pot/VR checked before resistor keywords."""
    r = _clean_str(ref).upper()
    ct = _clean_str(comp_type).lower()

    # Ref-based (highest priority)
    if r.startswith("VR"):
        return "pot"
    if r.startswith("C"):
        return "cap"
    if r.startswith("L"):
        return "ind"
    if r.startswith("R"):
        return "res"

    # Type-based (order matters)
    pot_kw = ("potentiometer", "trimmer", "variable resistor", "var resistor", "preset")
    ind_kw = ("inductor", "coil", "choke")
    cap_kw = ("capacitor",)
    res_kw = ("resistor",)

    if any(k in ct for k in pot_kw):
        return "pot"
    if any(k in ct for k in ind_kw):
        return "ind"
    if any(k in ct for k in cap_kw):
        return "cap"
    if any(k in ct for k in res_kw):
        return "res"

    return "other"


# ----------------------------
# Value normalization per family
# ----------------------------

def normalize_cap_value(val: str) -> str:
    """
    Accepts missing 'F': '20u'/'20 u' -> '20 uF', '47 n' -> '47 nF'
    No unit conversion.
    """
    v0 = _strip_noise(val)
    if not v0:
        return ""

    v = normalize_decimal(v0).lower().replace(" ", "")
    m = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([munp]?)(f)?", v, flags=re.IGNORECASE)
    if not m:
        return normalize_spaces(v0)

    num_s = m.group(1)
    prefix = (m.group(2) or "").lower()
    has_f = m.group(3) is not None

    if prefix == "" and not has_f:
        return normalize_spaces(v0)

    num = float(num_s)
    unit_map = {"": "F", "m": "mF", "u": "uF", "n": "nF", "p": "pF"}
    return f"{num:.6g} {unit_map.get(prefix, 'F')}"


def normalize_ind_value(val: str) -> str:
    """
    Accepts missing 'H': '10u'/'10 u' -> '10 uH'
    Normalizes to readable engineering unit.
    """
    v0 = _strip_noise(val)
    if not v0:
        return ""

    v = normalize_decimal(v0).lower().replace(" ", "")
    m = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([mun]?)(h)?", v, flags=re.IGNORECASE)
    if not m:
        return normalize_spaces(v0)

    num_s = m.group(1)
    prefix = (m.group(2) or "").lower()
    has_h = m.group(3) is not None

    if prefix == "" and not has_h:
        return normalize_spaces(v0)

    num = float(num_s)
    factor = {"": 1.0, "m": 1e-3, "u": 1e-6, "n": 1e-9}.get(prefix, 1.0)
    henry = num * factor

    return _fmt_eng(henry, thresholds=[(1.0, "H"), (1e-3, "mH"), (1e-6, "uH"), (1e-9, "nH")])


def format_ohms(ohms: float) -> str:
    a = abs(ohms)
    if a >= 1e6:
        return f"{ohms/1e6:.6g} MΩ"
    if a >= 1e3:
        return f"{ohms/1e3:.6g} kΩ"
    return f"{ohms:.6g} Ω"


def normalize_res_value(val: str) -> str:
    """
    Handles:
    - 4k7, 2R2, 1M0
    - 10k, 4.7k, 470ohm
    """
    v0 = _strip_noise(val)
    if not v0:
        return ""

    v = normalize_decimal(v0).replace(" ", "").lower()
    v = v.replace("ohms", "ohm").replace("ω", "ohm")

    # Remove trailing 'ohm' word only
    v = re.sub(r"ohm(s)?$", "", v)

    # Embedded multiplier: 4k7 / 2r2 / 1m0
    m = re.fullmatch(r"(\d+)([rkm])(\d+)", v, flags=re.IGNORECASE)
    if m:
        a, mid, b = m.group(1), m.group(2).lower(), m.group(3)
        num = float(f"{a}.{b}")
        mult = {"r": 1.0, "k": 1e3, "m": 1e6}[mid]
        return format_ohms(num * mult)

    # Plain number with optional suffix
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([rkm])?$", v, flags=re.IGNORECASE)
    if m:
        num = float(m.group(1))
        suf = (m.group(2) or "").lower()
        mult = {"": 1.0, "r": 1.0, "k": 1e3, "m": 1e6}[suf]
        return format_ohms(num * mult)

    # Fallback: find first number+suffix anywhere
    m = re.search(r"(\d+(?:\.\d+)?)(k|m|r)?\b", v, flags=re.IGNORECASE)
    if m:
        num = float(m.group(1))
        suf = (m.group(2) or "").lower()
        mult = {"": 1.0, "r": 1.0, "k": 1e3, "m": 1e6}.get(suf, 1.0)
        return format_ohms(num * mult)

    return normalize_spaces(v0)


def normalize_value_by_family(family: str, value: str) -> str:
    if family == "cap":
        return normalize_cap_value(value)
    if family == "ind":
        return normalize_ind_value(value)
    if family == "res":
        return normalize_res_value(value)
    return normalize_spaces(_strip_noise(value))


# ----------------------------
# Notes modes
# ----------------------------

NOTES_TOKEN_RULES = [
    ("NP",   r"\b(np|nopop|no\s*pop|not\s*populated|do\s*not\s*fit|dnf)\b"),
    ("ALT",  r"\b(alt|alternate|substitute|equiv)\b"),
    ("FIT",  r"\b(fitted|mount(ed)?|installed)\b"),
    ("NFIT", r"\b(not\s*fitted|not\s*mounted|not\s*installed)\b"),
]

def normalize_notes(notes: str, mode: str) -> str:
    n = normalize_spaces(notes)
    if not n:
        return ""
    if mode == "raw":
        return n
    if mode == "none":
        return ""
    # tokens
    low = n.lower()
    tokens = []
    for tag, rx in NOTES_TOKEN_RULES:
        if re.search(rx, low, flags=re.IGNORECASE):
            tokens.append(tag)
    return ",".join(tokens) if tokens else ""


# ----------------------------
# Column guessing + overrides
# ----------------------------

def guess_columns(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    cols = list(df.columns)
    norm = {c: re.sub(r"[^a-z0-9]+", "", str(c).strip().lower()) for c in cols}

    def pick(*needles):
        for c, n in norm.items():
            for nd in needles:
                if nd in n:
                    return c
        return None

    return {
        "ref": pick("refdesignator", "ref", "designator"),
        "component_type": pick("componenttype", "type"),
        "value": pick("valuespec", "value"),
        "rating": pick("voltagerating", "voltage", "rating"),
        "tolerance": pick("tolerance", "tol"),
        "notes": pick("notesstatus", "notes", "status"),
        "orig_part": pick("originalpartno", "partno", "partnumber"),
    }


def apply_overrides(colmap: Dict[str, Optional[str]], args: argparse.Namespace) -> Dict[str, Optional[str]]:
    overrides = {
        "ref": args.col_ref,
        "component_type": args.col_type,
        "value": args.col_value,
        "rating": args.col_rating,
        "tolerance": args.col_tol,
        "notes": args.col_notes,
        "orig_part": args.col_partno,
    }
    out = dict(colmap)
    for k, v in overrides.items():
        if v:
            out[k] = v
    return out


# ----------------------------
# Sheet selection
# ----------------------------

def try_sheet(path: Path, sheet_name_or_idx) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    try:
        df = pd.read_excel(path, sheet_name=sheet_name_or_idx, engine="openpyxl")
        return df, str(sheet_name_or_idx)
    except Exception:
        return None, None


def autodetect_sheet(path: Path) -> Tuple[pd.DataFrame, str]:
    xf = pd.ExcelFile(path, engine="openpyxl")
    for sh in xf.sheet_names:
        df = pd.read_excel(path, sheet_name=sh, engine="openpyxl")
        cm = guess_columns(df)
        if cm.get("ref") and cm.get("component_type"):
            # basic signal: at least one non-empty ref
            refs = df[cm["ref"]].map(_clean_str) if cm["ref"] in df.columns else pd.Series([])
            if (refs != "").sum() >= 1:
                return df, sh
    # fallback: first sheet
    df0 = pd.read_excel(path, sheet_name=xf.sheet_names[0], engine="openpyxl")
    return df0, xf.sheet_names[0]


# ----------------------------
# Sanity checks
# ----------------------------

REF_RX = re.compile(r"^[A-Z]{1,4}\d+([A-Z]\d+)?$", re.IGNORECASE)

def sanity_check_refs(ref_series: pd.Series) -> List[str]:
    msgs = []
    s = ref_series.fillna("").map(_clean_str)
    n = len(s)
    if n == 0:
        return ["No rows found."]

    nonempty = (s != "").sum()
    if nonempty == 0:
        msgs.append("All Ref. Designator values are empty.")
        return msgs

    frac_nonempty = nonempty / n
    if frac_nonempty < 0.2:
        msgs.append(f"Low non-empty ref ratio: {frac_nonempty:.1%} (possible wrong column mapping).")

    sample = s[s != ""].head(200)
    ok = sample.map(lambda x: bool(REF_RX.match(x.upper()))).sum()
    frac_ok = ok / max(len(sample), 1)
    if frac_ok < 0.6:
        msgs.append(f"Ref pattern match is low: {frac_ok:.1%} (possible wrong column mapping).")
    return msgs


# ----------------------------
# Main
# ----------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bom_tally.py",
        description="Group and count BOM components with normalization (caps/res/inds/others).",
    )
    p.add_argument("xlsx", type=Path, help="Path to BOM .xlsx")
    p.add_argument("--sheet", default=None, help="Sheet name or index (0-based). If omitted: auto-detect.")
    p.add_argument("--log", default=None, type=Path, help="Log file path. Default: log.txt next to xlsx.")
    p.add_argument("--csv", default=None, type=Path, help="Optional CSV output path.")

    p.add_argument("--notes", choices=["none", "raw", "tokens"], default="tokens",
                   help="How to use Notes/Status for grouping. Default: tokens.")
    p.add_argument("--include-partno", action="store_true", help="Include Original Part No. in grouping key.")

    p.add_argument("--drop-rating", action="store_true", help="Do not include rating/voltage in grouping key.")
    p.add_argument("--drop-tolerance", action="store_true", help="Do not include tolerance in grouping key.")
    p.add_argument("--drop-type", action="store_true", help="Do not include Component Type in grouping key.")

    # Column overrides (exact header names)
    p.add_argument("--col-ref", default=None, help="Override column header for Ref. Designator.")
    p.add_argument("--col-type", default=None, help="Override column header for Component Type.")
    p.add_argument("--col-value", default=None, help="Override column header for Value / Spec.")
    p.add_argument("--col-rating", default=None, help="Override column header for Voltage / Rating.")
    p.add_argument("--col-tol", default=None, help="Override column header for Tolerance.")
    p.add_argument("--col-notes", default=None, help="Override column header for Notes / Status.")
    p.add_argument("--col-partno", default=None, help="Override column header for Original Part No.")

    return p


def parse_sheet_arg(sheet_arg: str):
    # allow numeric index
    if sheet_arg is None:
        return None
    try:
        return int(sheet_arg)
    except ValueError:
        return sheet_arg


def main():

    args = build_parser().parse_args()

    xlsx_path: Path = args.xlsx.expanduser()
    if not xlsx_path.exists():
        print(f"Error: file not found: {xlsx_path}")
        sys.exit(1)

    # Sheet selection
    chosen_sheet = None
    if args.sheet is not None:
        sh = parse_sheet_arg(args.sheet)
        df, sh_name = try_sheet(xlsx_path, sh)
        if df is None:
            print(f"Error: unable to read sheet '{args.sheet}'")
            sys.exit(1)
        chosen_sheet = sh_name
    else:
        df, sh_name = autodetect_sheet(xlsx_path)
        chosen_sheet = sh_name

    # Column mapping
    guessed = guess_columns(df)
    col = apply_overrides(guessed, args)

    required = ["ref", "component_type"]
    missing = [k for k in required if not col.get(k) or col.get(k) not in df.columns]
    if missing:
        print("Error: missing required columns after mapping/overrides.")
        print("Columns in sheet:", list(df.columns))
        print("Chosen mapping:", col)
        sys.exit(1)

    # Build log sink
    log_path = args.log.expanduser() if args.log else xlsx_path.with_name("log.txt")
    lines: List[str] = []

    def emit(s=""):
        lines.append(str(s))

    emit("=== BOM TALLY ===")
    emit(f"Version: {__version__}")
    emit(f"Input: {xlsx_path}")
    emit(f"Sheet: {chosen_sheet}")
    emit(f"Notes mode: {args.notes}")
    emit(f"Include partno in key: {bool(args.include_partno)}")
    emit(f"Key drops: type={bool(args.drop_type)}, rating={bool(args.drop_rating)}, tol={bool(args.drop_tolerance)}")
    emit("")
    emit("Chosen column mapping:")
    for k in ["ref", "component_type", "value", "rating", "tolerance", "notes", "orig_part"]:
        emit(f"  {k:14s} -> {col.get(k)}")
    emit("")

    # Sanity checks
    ref_series = df[col["ref"]].map(_clean_str)
    sanity_msgs = sanity_check_refs(ref_series)
    if sanity_msgs:
        emit("Sanity check warnings:")
        for m in sanity_msgs:
            emit(f"  - {m}")
        emit("")
        # Fail hard if refs look totally wrong
        if any("All Ref" in m for m in sanity_msgs):
            log_path.write_text("\n".join(lines), encoding="utf-8")
            print(f"Wrote log to: {log_path}")
            sys.exit(2)

    # Build working dataframe
    work = pd.DataFrame()
    work["ref"] = df[col["ref"]].map(_clean_str)
    work["component_type"] = df[col["component_type"]].map(_clean_str)

    work["orig_part"] = df[col["orig_part"]].map(_clean_str) if col.get("orig_part") in df.columns else ""
    work["value_raw"] = df[col["value"]].map(_clean_str) if col.get("value") in df.columns else ""
    work["rating_raw"] = df[col["rating"]].map(_clean_str) if col.get("rating") in df.columns else ""
    work["tolerance_raw"] = df[col["tolerance"]].map(_clean_str) if col.get("tolerance") in df.columns else ""
    work["notes_raw"] = df[col["notes"]].map(_clean_str) if col.get("notes") in df.columns else ""

    work["family"] = [detect_family(r, ct) for r, ct in zip(work["ref"], work["component_type"])]
    work["type_norm"] = work["component_type"].map(lambda s: normalize_spaces(s).lower())
    work["value_norm"] = [normalize_value_by_family(f, v) for f, v in zip(work["family"], work["value_raw"])]

    #TBD
    work["rating_norm"] = work["rating_raw"].map(normalize_voltage_or_rating)

    work["tolerance_norm"] = work["tolerance_raw"].map(normalize_tolerance)
    work["notes_norm"] = work["notes_raw"].map(lambda s: normalize_notes(s, args.notes))
    work["orig_part_norm"] = work["orig_part"].map(normalize_spaces)

    # Build grouping key
    key_parts = [work["family"]]
    if not args.drop_type:
        key_parts.append(work["type_norm"])
    key_parts.append(work["value_norm"])
    if not args.drop_rating:
        key_parts.append(work["rating_norm"])
    if not args.drop_tolerance:
        key_parts.append(work["tolerance_norm"])
    if args.include_partno:
        key_parts.append(work["orig_part_norm"])
    if args.notes != "none":
        key_parts.append(work["notes_norm"])

    work["group_key"] = list(zip(*key_parts))

    groups = (
        work.groupby("group_key", dropna=False)
        .agg(
            count=("ref", "count"),
            refs=("ref", lambda s: ", ".join(sorted([x for x in s if x]))),
        )
        .reset_index()
        .sort_values(["count"], ascending=[False])
    )

    # Print grouped results to log
    emit("=== GROUPS ===")
    emit(f"Total rows: {len(work)}")
    emit(f"Total groups: {len(groups)}")
    emit("")

    for _, r in groups.iterrows():
        cnt = int(r["count"])
        refs = r["refs"]
        # Reconstruct readable key
        key = r["group_key"]
        emit(f"- {cnt}x | key={key}")
        emit(f"  Refs: {refs}")
        emit("")

    # Save log + optional CSV
    log_path.write_text("\n".join(lines), encoding="utf-8")

    if args.csv:
        out_csv = args.csv.expanduser()
        groups_out = groups.copy()
        groups_out["group_key"] = groups_out["group_key"].map(str)
        groups_out.to_csv(out_csv, index=False)

    print(f"Wrote log to: {log_path}")
    if args.csv:
        print(f"Saved CSV to: {args.csv.expanduser()}")


if __name__ == "__main__":
    main()
