#!/usr/bin/env python3
"""
Scan a folder of images for ICC / color-profile issues relevant to bulk AVIF conversion.

- Most JPEGs embed a **small sRGB ICC** — that is normal and **not** a problem.
- **Wide-gamut** profiles (Rec.2020, P3, Adobe RGB, …) or **ICC with no readable
  description** are the ones that usually need per-file encoder flags or baking.

**Default mode** (``--mode risky``): print only paths that look **wide gamut** or
**ambiguous** (embedded ICC but ExifTool cannot classify as sRGB).

Other modes::

    --mode stats      Counts only (stderr): srgb / wide / unknown / no_icc_meta
    --mode all-icc    Every file ExifTool reports ICC metadata for (legacy-style list)
    --mode copy-wide  Copy only wide-gamut files into a subfolder (for manual Affinity / etc.)

Uses **exiftool** (recommended) for profile names; optional **ffprobe** only when
you pass ``--require-ffprobe-icc`` to also require an ICC side-data block.

Usage::

    uv run python scripts/scan_images_icc.py /path/to/avif
    uv run python scripts/scan_images_icc.py /path/to/avif -r --mode stats
    uv run python scripts/scan_images_icc.py /path/to/avif -r --mode copy-wide

Requires **exiftool** on PATH. Optional: **ffprobe** for ``--require-ffprobe-icc``.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_WIDE_COPY_DIR = "_wide_gamut_copy"

DEFAULT_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
    ".bmp",
    ".heic",
    ".heif",
)

# Heuristic classifiers — ExifTool strings vary a lot (Skia, Photoshop, vendor ICC).
_SRGB_DESC_RES = (
    re.compile(r"\bsrgb\b", re.I),
    re.compile(r"iec\s*61966", re.I),
    re.compile(r"61966[- ]*2[- .]*1", re.I),
    re.compile(r"\bskia\b", re.I),
    re.compile(r"\bchrome\b", re.I),
    re.compile(r"photoshop", re.I),
    re.compile(r"standard rgb color space", re.I),
    re.compile(r"formulation of the srgb", re.I),
    re.compile(r"hp\s*srgb|hewlett.{0,20}srgb", re.I),
    re.compile(r"color match rgb", re.I),
    re.compile(r"srgb.{0,40}built|built.{0,40}srgb", re.I | re.DOTALL),
    re.compile(r"web.{0,20}srgb|srgb.{0,20}web", re.I),
    re.compile(r"image\s*state\s*adjustment", re.I),  # common Photoshop sRGB path
    re.compile(r"gimp", re.I),  # often ships sRGB built-in
)

# Avoid bare "p3" / "aces" substrings (false positives). Prefer explicit phrases / word bounds.
_WIDE_DESC_RES = (
    re.compile(r"rec\.?\s*2020|rec2020", re.I),
    re.compile(r"bt\.?\s*2020|bt2020", re.I),
    re.compile(r"bt\.?\s*2100|bt2100", re.I),
    re.compile(r"rgb\s+rec", re.I),
    re.compile(r"display\s*p3|p3[- ]d65", re.I),
    re.compile(r"dci[-\s]?p3", re.I),
    re.compile(r"adobe\s*rgb", re.I),
    re.compile(r"adobe\s*\(?\s*1998\s*\)?", re.I),
    re.compile(r"prophoto|romm(\s|$|[,.)])", re.I),
    re.compile(r"wide[-\s]?gamut", re.I),
    re.compile(r"\baces(cg|cct)?\b", re.I),
    re.compile(r"linear\s+rec", re.I),
    re.compile(r"\bscrgb\b", re.I),
    re.compile(r"eci\s*rgb|best\s*rgb|don\s*rgb", re.I),
    re.compile(r"pointer\s+gamut|romm\s+rgb", re.I),
    re.compile(r"apple.{0,50}display|display.{0,30}p3", re.I),  # Apple Display P3
)


def _json_has_icc_side_data(node) -> bool:
    if isinstance(node, dict):
        st = node.get("side_data_type")
        if isinstance(st, str) and "icc" in st.lower():
            return True
        return any(_json_has_icc_side_data(v) for v in node.values())
    if isinstance(node, list):
        return any(_json_has_icc_side_data(x) for x in node)
    return False


def file_has_embedded_icc_ffprobe(path: Path, timeout: float) -> bool | None:
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_streams",
        "-show_frames",
        "-read_intervals",
        "%+#1",
        "-select_streams",
        "v:0",
        str(path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return None

    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return None
    if not (data.get("streams") or []):
        return None
    if _json_has_icc_side_data(data):
        return True
    return False


def _exiftool_icc_value(rec: dict, short_name: str):
    """
    Read an ICC field from ExifTool JSON. ``-j`` emits short keys (e.g. ColorSpaceData)
    even when the CLI used ``-ICC_Profile:ColorSpaceData``.
    """
    for key in (f"ICC_Profile:{short_name}", short_name):
        v = rec.get(key)
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        return v
    return None


def _gather_profile_text(rec: dict) -> str:
    parts: list[str] = []
    for key in (
        "ProfileDescription",
        "ICC_Profile:ProfileDescription",
        "ICCProfileDescription",
        "ColorSpace",
        "ColorSpaceData",
        "ICC_Profile:ColorSpaceData",
    ):
        v = rec.get(key)
        if v is not None and str(v).strip():
            parts.append(str(v).strip())
    return " ".join(parts).lower()


def _exiftool_colorspace_says_srgb(rec: dict) -> bool:
    """Exif ColorSpace tag: sRGB string or EXIF value 1 = sRGB."""
    cs = rec.get("ColorSpace")
    if isinstance(cs, (int, float)):
        return int(cs) == 1
    if isinstance(cs, str):
        c = cs.strip().lower()
        if c == "1" or c == "0x1":
            return True
        return c == "srgb" or c.startswith("srgb ")
    return False


def _has_icc_tag(rec: dict) -> bool:
    """ExifTool exposes ICC-related tags when a profile is embedded."""
    return bool(
        _exiftool_icc_value(rec, "ProfileVersion")
        or _exiftool_icc_value(rec, "ProfileClass")
        or _exiftool_icc_value(rec, "ProfileDescription")
    )


def _text_matches_wide(t: str) -> bool:
    return bool(t and any(rx.search(t) for rx in _WIDE_DESC_RES))


def _fallback_compact_rgb_matrix_profile(rec: dict, t: str) -> bool:
    """
    Stock sites often embed a small matrix-shaper RGB ICC with ColorSpace=Uncalibrated
    and a generic/empty ProfileDescription. If it is RGB data, not huge (LUT), and no
    wide-gamut hints in any text, treat as sRGB-class for bulk AVIF purposes.
    """
    if _text_matches_wide(t):
        return False
    csraw = _exiftool_icc_value(rec, "ColorSpaceData")
    csdata = (str(csraw).strip().upper() if csraw is not None else "").replace(" ", "")
    if csdata != "RGB":
        return False

    psz = _exiftool_icc_value(rec, "ProfileSize")
    try:
        n = int(str(psz).strip()) if psz is not None and str(psz).strip() != "" else 0
    except (TypeError, ValueError):
        n = 0

    # Embedded sRGB clones are usually hundreds–a few KB; skip huge LUT profiles.
    if 260 <= n <= 4800:
        return True

    if n > 4800:
        return False

    # ExifTool often omits ProfileSize; require a typical matrix/profile class string.
    pcl = (str(_exiftool_icc_value(rec, "ProfileClass") or "").lower())
    if any(
        k in pcl
        for k in (
            "colorspace",
            "abstract",
            "matrix",
            "three color",
            "input device",
            "output device",
            "display device",
        )
    ):
        return True
    return False


def classify_profile(rec: dict) -> str:
    """
    Return 'srgb', 'wide', 'unknown', or 'none' (no ICC description text to inspect).

    Order: Exif ColorSpace=sRGB → wide regex → sRGB regex → compact RGB ICC fallback.
    """
    if _exiftool_colorspace_says_srgb(rec):
        return "srgb"

    text = _gather_profile_text(rec)
    t = (text or "").strip().lower()

    if t:
        if _text_matches_wide(t):
            return "wide"
        for rx in _SRGB_DESC_RES:
            if rx.search(t):
                return "srgb"

    if _fallback_compact_rgb_matrix_profile(rec, t):
        return "srgb"

    return "none" if not t else "unknown"


def exiftool_batch_json(paths: list[Path], timeout: float) -> dict[str, dict]:
    """Map absolute path string -> first exiftool record for that file."""
    if not paths:
        return {}
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".txt",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            for p in paths:
                tmp.write(str(p.resolve()) + "\n")
            argfile = tmp.name
    except OSError as e:
        print(f"error: could not write temp argfile: {e}", file=sys.stderr)
        sys.exit(2)

    cmd = [
        "exiftool",
        "-q",
        "-q",
        "-json",
        "-charset",
        "filename=UTF8",
        "-@",
        argfile,
        "-ICC_Profile:ProfileVersion",
        "-ICC_Profile:ProfileClass",
        "-ICC_Profile:ProfileDescription",
        "-ICC_Profile:ColorSpaceData",
        "-ICC_Profile:ProfileSize",
        "-ProfileDescription",
        "-ColorSpace",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        Path(argfile).unlink(missing_ok=True)
        print("error: exiftool not found on PATH", file=sys.stderr)
        sys.exit(2)
    except subprocess.TimeoutExpired:
        Path(argfile).unlink(missing_ok=True)
        print("error: exiftool timed out", file=sys.stderr)
        sys.exit(2)

    Path(argfile).unlink(missing_ok=True)

    if proc.returncode != 0:
        print(proc.stderr or proc.stdout or "exiftool failed", file=sys.stderr)
        sys.exit(2)

    try:
        rows = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        print("error: could not parse exiftool JSON", file=sys.stderr)
        sys.exit(2)

    out: dict[str, dict] = {}
    for row in rows:
        sf = row.get("SourceFile")
        if sf:
            out[str(Path(sf).resolve())] = row
    return out


def _is_under(path: Path, ancestor: Path) -> bool:
    try:
        path.resolve().relative_to(ancestor.resolve())
    except ValueError:
        return False
    return True


def collect_paths(
    root: Path,
    recursive: bool,
    exts: set[str],
    *,
    skip_under: Path | None = None,
) -> list[Path]:
    root_r = root.resolve()
    skip_r = skip_under.resolve() if skip_under else None

    def excluded(f: Path) -> bool:
        if skip_r is None:
            return False
        return _is_under(f, skip_r)

    if recursive:
        return sorted(
            f
            for f in root_r.rglob("*")
            if f.is_file()
            and f.suffix.lower() in exts
            and not excluded(f)
        )
    return sorted(
        f
        for f in root_r.iterdir()
        if f.is_file()
        and f.suffix.lower() in exts
        and not excluded(f)
    )


def main() -> None:
    p = argparse.ArgumentParser(
        description="Classify image ICC profiles (ExifTool) for AVIF bulk-convert risk."
    )
    p.add_argument("directory", type=Path, help="Folder to scan.")
    p.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="Scan subfolders.",
    )
    p.add_argument(
        "--ext",
        default=",".join(DEFAULT_EXTENSIONS),
        help="Comma-separated extensions (default: common raster types).",
    )
    p.add_argument(
        "--mode",
        choices=("risky", "stats", "all-icc", "copy-wide"),
        default="risky",
        help=(
            "risky: wide or unknown ICC (default). stats: counts. all-icc: any ICC metadata. "
            "copy-wide: copy wide-gamut files to --copy-dest (see there)."
        ),
    )
    p.add_argument(
        "--copy-dest",
        type=Path,
        default=None,
        help=(
            f"With --mode copy-wide: output directory (default: <directory>/{DEFAULT_WIDE_COPY_DIR}). "
            "Files keep paths relative to the scan folder."
        ),
    )
    p.add_argument(
        "--chunk",
        type=int,
        default=200,
        help="ExifTool batch size (default: 200).",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Seconds per exiftool batch (default: 120).",
    )
    p.add_argument(
        "--require-ffprobe-icc",
        action="store_true",
        help="In risky/all-icc/copy-wide modes, also require ffprobe ICC side data (slower).",
    )
    p.add_argument(
        "--ffprobe-timeout",
        type=float,
        default=30.0,
        help="Seconds per ffprobe (with --require-ffprobe-icc).",
    )
    args = p.parse_args()

    if args.require_ffprobe_icc:
        try:
            subprocess.run(
                ["ffprobe", "-version"],
                capture_output=True,
                timeout=5,
                check=True,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
            print("error: --require-ffprobe-icc needs ffprobe on PATH", file=sys.stderr)
            sys.exit(2)

    root: Path = args.directory
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        sys.exit(1)
    root = root.resolve()

    copy_dest: Path | None = None
    skip_under: Path | None = None
    if args.mode == "copy-wide":
        copy_dest = (args.copy_dest or root / DEFAULT_WIDE_COPY_DIR).resolve()
        if copy_dest == root:
            print(
                "error: --copy-dest must not be the scan directory itself "
                f"(try default {DEFAULT_WIDE_COPY_DIR}/ under it)",
                file=sys.stderr,
            )
            sys.exit(2)
        if copy_dest.exists() and not copy_dest.is_dir():
            print("error: --copy-dest exists and is not a directory", file=sys.stderr)
            sys.exit(2)
        if _is_under(copy_dest, root):
            skip_under = copy_dest

    exts = {e.strip().lower() for e in args.ext.split(",") if e.strip()}
    for e in list(exts):
        if not e.startswith("."):
            exts.discard(e)
            exts.add("." + e)

    paths = collect_paths(root, args.recursive, exts, skip_under=skip_under)
    total = len(paths)
    if total == 0:
        print("# no matching files", file=sys.stderr)
        return

    counts = {
        "no_exif_row": 0,
        "no_icc": 0,
        "icc_srgb": 0,
        "icc_wide": 0,
        "icc_unknown_text": 0,
        "icc_no_text": 0,
    }
    risky_paths: list[tuple[Path, str, str]] = []
    all_icc_paths: list[Path] = []

    for i in range(0, total, args.chunk):
        chunk = paths[i : i + args.chunk]
        meta = exiftool_batch_json(chunk, args.timeout)
        for path in chunk:
            key = str(path.resolve())
            rec = meta.get(key)
            if not rec:
                counts["no_exif_row"] += 1
                continue

            text = _gather_profile_text(rec)
            has_icc = _has_icc_tag(rec)
            bucket = classify_profile(rec)

            if not has_icc:
                counts["no_icc"] += 1
                continue

            all_icc_paths.append(path)

            if bucket == "srgb":
                counts["icc_srgb"] += 1
                continue

            if bucket == "wide":
                counts["icc_wide"] += 1
                snippet = (text[:80] + "…") if len(text) > 80 else text
                risky_paths.append((path, "wide_gamut_hint", snippet))
                continue

            if bucket == "unknown":
                counts["icc_unknown_text"] += 1
                snippet = (text[:80] + "…") if len(text) > 80 else (text or "(empty)")
                risky_paths.append((path, "icc_unclassified_description", snippet))
                continue

            # ICC present but ExifTool gave no usable description string
            counts["icc_no_text"] += 1
            risky_paths.append((path, "icc_embedded_no_description", "(no profile text)"))

    if args.require_ffprobe_icc:
        filtered: list[tuple[Path, str, str]] = []
        for path, reason, snip in risky_paths:
            if file_has_embedded_icc_ffprobe(path, args.ffprobe_timeout) is True:
                filtered.append((path, reason, snip))
        risky_paths = filtered
        all_icc_paths = [
            path
            for path in all_icc_paths
            if file_has_embedded_icc_ffprobe(path, args.ffprobe_timeout) is True
        ]

    if args.mode == "stats":
        print(
            f"# stats: scanned={total}  "
            f"icc_srgb_like={counts['icc_srgb']}  "
            f"icc_wide_gamut={counts['icc_wide']}  "
            f"icc_unknown_description={counts['icc_unknown_text']}  "
            f"icc_no_description={counts['icc_no_text']}  "
            f"no_icc_embedded={counts['no_icc']}  "
            f"exiftool_missing_row={counts['no_exif_row']}",
            file=sys.stderr,
        )
        print(
            f"# risky_for_bulk_avif={len(risky_paths)}  "
            f"(wide + unclassified + icc_without_text; use default --mode risky to list)",
            file=sys.stderr,
        )
        return

    if args.mode == "all-icc":
        for path in all_icc_paths:
            print(path)
        print(
            f"\n# summary: {len(all_icc_paths)} file(s) with ICC metadata (ExifTool), "
            f"of {total} scanned",
            file=sys.stderr,
        )
        return

    if args.mode == "copy-wide":
        assert copy_dest is not None
        wide_files = [p for p, reason, _ in risky_paths if reason == "wide_gamut_hint"]
        if not wide_files:
            print("# copy-wide: no wide-gamut files found; nothing to copy", file=sys.stderr)
            return
        copy_dest.mkdir(parents=True, exist_ok=True)
        copied = 0
        for src in wide_files:
            src_r = src.resolve()
            try:
                rel = src_r.relative_to(root)
            except ValueError:
                rel = Path(src.name)
            out = copy_dest / rel
            if out.resolve() == src_r:
                print(f"error: destination would overwrite source: {src}", file=sys.stderr)
                sys.exit(2)
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_r, out)
            copied += 1
            print(out)
        print(
            f"\n# copy-wide: copied {copied} file(s) to {copy_dest}",
            file=sys.stderr,
        )
        return

    # risky (default)
    for path, reason, _snippet in risky_paths:
        print(f"{path}\t{reason}")
    print(
        f"\n# summary: {len(risky_paths)} risky (of {total} scanned); "
        f"icc_srgb_ok={counts['icc_srgb']}  "
        f"no_icc={counts['no_icc']}  "
        f"exiftool_missing={counts['no_exif_row']}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
