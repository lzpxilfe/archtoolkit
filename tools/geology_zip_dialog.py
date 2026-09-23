# -*- coding: utf-8 -*-
"""
KIGAM 1:50,000 geology map ZIP loader + vector->raster conversion (MaxEnt-ready).
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
import zipfile
import csv
import math
from typing import Dict, List, Optional, Tuple

import processing
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QFont, QIcon
from qgis.core import (
    Qgis,
    QgsCategorizedSymbolRenderer,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsFillSymbol,
    QgsLayerTreeGroup,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsProject,
    QgsRasterFillSymbolLayer,
    QgsRasterMarkerSymbolLayer,
    QgsRendererCategory,
    QgsTextFormat,
    QgsRasterLayer,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
    QgsWkbTypes,
)
from .qtcompat import FT_INT, FT_UINT, FT_LONGLONG, FT_ULONGLONG, FT_DOUBLE

from .help_dialog import show_help_dialog
from . import dialog_memory
from .icons import icon as plugin_icon
from .i18n import get_output_group_name, get_plugin_config_value
from .live_log_dialog import ensure_live_log_dialog
from .utils import (
    is_null_value,
    log_swallowed,
    log_message,
    push_message,
    restore_ui_focus,
    set_archtoolkit_layer_metadata,
    new_run_id,
)


def _compact_str_list(value_list, *, include_none=False, lower=False):
    """Normalize a config list by dropping blank values while optionally preserving None."""
    out = []
    for value in value_list or []:
        if value is None:
            if include_none:
                out.append(None)
            continue
        text = str(value).strip()
        if not text:
            continue
        out.append(text.lower() if lower else text)
    return out


def _cfg_int(*keys, default):
    """int() of a config value that NEVER raises at import time — a bad
    config.json entry (e.g. "14d") must not take down tool registration."""
    try:
        return int(get_plugin_config_value(*keys, default=default) or default)
    except Exception:
        return int(default)


def _cfg_float(*keys, default):
    try:
        return float(get_plugin_config_value(*keys, default=default) or default)
    except Exception:
        return float(default)


PARENT_GROUP_NAME = get_output_group_name("geology", "ArchToolkit - Geology")
GEOLOGY_EXTRACT_ROOT_NAME = str(
    get_plugin_config_value("geology_zip", "extract_root_name", default="ArchToolkit_KIGAM_Extract") or ""
).strip() or "ArchToolkit_KIGAM_Extract"
GEOLOGY_EXTRACT_CLEANUP_DAYS = _cfg_int("geology_zip", "extract_cleanup_days", default=90)
GEOLOGY_PROVIDER_ENCODING = str(
    get_plugin_config_value("geology_zip", "provider_encoding", default="cp949") or ""
).strip() or "cp949"
GEOLOGY_CANDIDATE_ENCODINGS = _compact_str_list(
    get_plugin_config_value("geology_zip", "candidate_encodings", default=["CP949", "EUC-KR", None, "UTF-8"]),
    include_none=True,
)
GEOLOGY_ENCODING_PREFERENCE = get_plugin_config_value(
    "geology_zip",
    "encoding_preference",
    default={"CP949": 4, "EUC-KR": 3, "default": 2, "UTF-8": 1},
) or {"CP949": 4, "EUC-KR": 3, "default": 2, "UTF-8": 1}
GEOLOGY_QML_WRITE_ENCODING = str(
    get_plugin_config_value("geology_zip", "qml_write_encoding", default="UTF-8") or ""
).strip() or "UTF-8"
GEOLOGY_POINT_MARKER_SIZE = _cfg_float("geology_zip", "symbology", "point_marker_size", default=6.0)
GEOLOGY_FILL_SYMBOL_WIDTH = _cfg_float("geology_zip", "symbology", "polygon_fill_width", default=10.0)
GEOLOGY_SYMBOL_PRIORITY_FIELDS = _compact_str_list(
    get_plugin_config_value(
        "geology_zip",
        "symbology",
        "symbol_priority_fields",
        default=["LITHOIDX", "TYPE", "ASGN_CODE", "SIGN", "CODE", "AGEIDX"],
    )
)
GEOLOGY_LABEL_FIELD_CANDIDATES = _compact_str_list(
    get_plugin_config_value(
        "geology_zip",
        "symbology",
        "label_field_candidates",
        default=["LITHOIDX", "LITHONAME"],
    )
)
GEOLOGY_FRAME_LAYER_KEYWORDS = _compact_str_list(
    get_plugin_config_value(
        "geology_zip",
        "symbology",
        "frame_layer_keywords",
        default=["frame"],
    ),
    lower=True,
)
GEOLOGY_REFERENCE_HIDE_KEYWORDS = _compact_str_list(
    get_plugin_config_value(
        "geology_zip",
        "symbology",
        "reference_hide_keywords",
        default=["frame", "crosssection"],
    ),
    lower=True,
)
GEOLOGY_LITHO_LAYER_KEYWORD = str(
    get_plugin_config_value("geology_zip", "symbology", "litho_layer_keyword", default="litho") or ""
).strip().lower()
GEOLOGY_RASTER_FIELD_PRIORITY = _compact_str_list(
    get_plugin_config_value(
        "geology_zip",
        "raster",
        "field_priority",
        default=["LITHOIDX", "AGEIDX", "LITHONAME", "TYPE", "ASGN_CODE", "SIGN", "CODE"],
    )
)
GEOLOGY_NAME_FIELD_CANDIDATES = _compact_str_list(
    get_plugin_config_value(
        "geology_zip",
        "raster",
        "name_field_candidates",
        default=["LITHONAME", "AGENAME", "NAME", "KOR_NAME", "ENG_NAME"],
    )
)
GEOLOGY_UI_FONT_SIZE_MIN = _cfg_int("geology_zip", "ui", "font_size_min", default=5)
GEOLOGY_UI_FONT_SIZE_MAX = _cfg_int("geology_zip", "ui", "font_size_max", default=50)
GEOLOGY_UI_FONT_SIZE_DEFAULT = _cfg_int("geology_zip", "ui", "font_size_default", default=10)
GEOLOGY_UI_PIXEL_MIN = _cfg_float("geology_zip", "ui", "pixel_size_min", default=0.1)
GEOLOGY_UI_PIXEL_MAX = _cfg_float("geology_zip", "ui", "pixel_size_max", default=10000.0)
GEOLOGY_UI_PIXEL_DEFAULT = _cfg_float("geology_zip", "ui", "pixel_size_default", default=10.0)
GEOLOGY_UI_NODATA_MIN = _cfg_float("geology_zip", "ui", "nodata_min", default=-9999999.0)
GEOLOGY_UI_NODATA_MAX = _cfg_float("geology_zip", "ui", "nodata_max", default=9999999.0)
GEOLOGY_UI_NODATA_DECIMALS = _cfg_int("geology_zip", "ui", "nodata_decimals", default=2)
GEOLOGY_UI_NODATA_DEFAULT = _cfg_float("geology_zip", "ui", "nodata_default", default=-9999.0)


# Custom property holding the normalised path of the ZIP a layer came from.
ZIP_PATH_PROPERTY = "archtoolkit/kigam_zip_path"


def _safe_name(name: str) -> str:
    base = str(name or "").strip()
    if not base:
        return "layer"
    base = re.sub(r"[\\/:*?\"<>|]+", "_", base)
    base = re.sub(r"\s+", "_", base).strip("_")
    return base or "layer"


def _ensure_output_extension(path: str, fmt: str) -> str:
    p = str(path or "").strip()
    if not p:
        return p
    fmt0 = str(fmt or "").strip().lower()
    desired_ext = ".tif" if fmt0 == "tif" else ".asc" if fmt0 == "asc" else ""
    if not desired_ext:
        return p

    # Strip known raster extensions repeatedly (handles accidental double extensions like ".tif.asc").
    root = p
    while True:
        root2, ext = os.path.splitext(root)
        if ext.lower() in (".tif", ".tiff", ".asc"):
            root = root2
            continue
        break

    return root + desired_ext


def _meters_to_degrees(pixel_m: float, lat_deg: float) -> Tuple[float, float]:
    """Approx convert meters to degrees at latitude (lon_deg, lat_deg)."""
    try:
        lat = float(lat_deg)
    except Exception:
        lat = 0.0
    try:
        m = float(pixel_m)
    except Exception:
        m = 0.0
    if m <= 0:
        return 0.0, 0.0

    r = math.radians(lat)
    # Approx meters per degree (WGS84). Good enough for small extents / UX.
    m_per_deg_lat = sum(
        (
            111132.92,
            -559.82 * math.cos(2 * r),
            1.175 * math.cos(4 * r),
            -0.0023 * math.cos(6 * r),
        )
    )
    m_per_deg_lon = sum(
        (
            111412.84 * math.cos(r),
            -93.5 * math.cos(3 * r),
            0.118 * math.cos(5 * r),
        )
    )
    if m_per_deg_lat <= 0 or m_per_deg_lon <= 0:
        return 0.0, 0.0
    return (m / m_per_deg_lon), (m / m_per_deg_lat)


# Reasons a feature (or a whole layer) never reaches the burn, in report
# order. Keys starting with "layer_" count layers, the rest count features.
DROP_REASON_LABELS = {
    "empty_geometry": "빈 지오메트리",
    "transform_failed": "좌표 변환 실패",
    "null_value": "값 없음(NULL/공백)",
    "non_numeric": "숫자 아님",
    "add_failed": "피처 추가 실패",
    "feature_error": "처리 오류",
    "layer_geometry_mismatch": "지오메트리 타입 불일치",
    "layer_field_missing": "필드 없음",
    "layer_transform_failed": "좌표계 변환 불가",
    "layer_crs_missing": "좌표계 없음",
}


def _format_drops(drops: Optional[Dict[str, int]]) -> str:
    """Human-readable summary of non-zero drop counters, "" when nothing was
    dropped, e.g. '제외된 피처 10개(값 없음(NULL/공백) 8, 숫자 아님 2)'."""
    if not drops:
        return ""
    feat = []
    lyr = []
    n_feat = 0
    n_lyr = 0
    for key, label in DROP_REASON_LABELS.items():
        try:
            n = int(drops.get(key, 0) or 0)
        except Exception as _exc:
            log_swallowed("geology_zip_dialog._format_drops", _exc)
            n = 0
        if n <= 0:
            continue
        if key.startswith("layer_"):
            lyr.append(f"{label} {n}")
            n_lyr += n
        else:
            feat.append(f"{label} {n}")
            n_feat += n
    parts = []
    if n_feat:
        parts.append(f"제외된 피처 {n_feat}개({', '.join(feat)})")
    if n_lyr:
        parts.append(f"제외된 레이어 {n_lyr}개({', '.join(lyr)})")
    return ", ".join(parts)


def _code_key(val) -> str:
    """Text key for a code value. Integral numbers become '12' rather than
    '12.0' so a sheet that stores LITHOIDX as Double and one that stores it as
    text share a key when the field has to be treated as text."""
    if isinstance(val, bool):
        return str(val)
    if isinstance(val, int):
        return str(val)
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    return str(val)


def _is_blank(val) -> bool:
    """True for None, PyQGIS NULL (a QVariant, not None) and blank text.

    str(NULL) is 'NULL', so an `is None` test let every null code through as
    a real class called "NULL" (and a null label printed as "NULL")."""
    if is_null_value(val):
        return True
    try:
        return str(val).strip() == ""
    except Exception as _exc:
        log_swallowed("geology_zip_dialog._is_blank", _exc)
        return True


def _safe_nodata(nodata: float, codes) -> Tuple[int, bool]:
    """Integer NoData for the Int32 class raster that is not a class code.

    gdal:rasterize burns the rounded NoData value, so a NoData equal to a code
    turned that whole class into NoData. Returns (nodata, changed); on a
    collision the value moves below the smallest code (-9999 when free)."""
    nd = int(round(float(nodata)))
    used = set()
    for c in codes or []:
        try:
            used.add(int(c))
        except Exception as _exc:
            log_swallowed("geology_zip_dialog._safe_nodata", _exc)
    if nd not in used:
        return nd, False
    cand = -9999 if -9999 not in used else min(used) - 1
    while cand in used:
        cand -= 1
    return cand, True


def _dbf_text_values(dbf_path: str, max_records: int = 20000) -> List[bytes]:
    """Raw bytes of the non-ASCII character-field values of a DBF (at most
    `max_records` records), used to tell the text encoding apart."""
    out: List[bytes] = []
    try:
        with open(dbf_path, "rb") as fh:
            head = fh.read(32)
            if len(head) < 32:
                return out
            n_rec = int.from_bytes(head[4:8], "little")
            hdr_len = int.from_bytes(head[8:10], "little")
            rec_len = int.from_bytes(head[10:12], "little")
            desc = fh.read(max(0, hdr_len - 32))
            fields = []
            pos = 1  # deletion flag
            for i in range(0, len(desc) - 31, 32):
                d = desc[i:i + 32]
                if d[0] == 0x0D:
                    break
                ftype = chr(d[11])
                flen = d[16]
                if ftype == "C":
                    flen = d[16] + 256 * d[17]
                    fields.append((pos, flen))
                pos += flen
            if not fields or rec_len <= 0:
                return out
            fh.seek(hdr_len)
            for _ in range(min(n_rec, int(max_records))):
                rec = fh.read(rec_len)
                if len(rec) < rec_len:
                    break
                for start, flen in fields:
                    raw = rec[start:start + flen].rstrip(b" \x00")
                    if raw and any(b >= 0x80 for b in raw):
                        out.append(raw)
    except Exception as _exc:
        log_swallowed("geology_zip_dialog._dbf_text_values", _exc)
    return out


def _choose_dbf_encoding(shp_path: str) -> Tuple[Optional[str], str]:
    """(encoding, source) for a shapefile's attribute text.

    A .cpg next to the .shp is honoured: (None, "cpg") means "leave the
    provider encoding alone", QGIS reads the .cpg itself. Without one the
    candidate encodings (config geology_zip.candidate_encodings, ranked by
    encoding_preference) are tried as strict decoders on the DBF's non-ASCII
    text and the one that decodes the most values wins, ties going to the
    preference. Forcing cp949 unconditionally garbled UTF-8 sheets. When the
    DBF holds no non-ASCII text, or no candidate decodes it, the configured
    provider_encoding is used (source "config")."""
    base = os.path.splitext(str(shp_path or ""))[0]
    for ext in (".cpg", ".CPG"):
        try:
            cpg = base + ext
            if os.path.isfile(cpg):
                with open(cpg, "r", encoding="ascii", errors="ignore") as fh:
                    if fh.read().strip():
                        return None, "cpg"
        except Exception as _exc:
            log_swallowed("geology_zip_dialog._choose_dbf_encoding", _exc)
    dbf = ""
    for ext in (".dbf", ".DBF"):
        if os.path.isfile(base + ext):
            dbf = base + ext
            break
    values = _dbf_text_values(dbf) if dbf else []
    if not values:
        return GEOLOGY_PROVIDER_ENCODING, "config"
    pref = GEOLOGY_ENCODING_PREFERENCE if isinstance(GEOLOGY_ENCODING_PREFERENCE, dict) else {}
    ranked = []
    for order, enc in enumerate(GEOLOGY_CANDIDATE_ENCODINGS or []):
        if enc is None:
            continue  # "default" cannot be tested; it is what the config fallback is for
        try:
            rank = float(pref.get(enc, pref.get(str(enc).upper(), 0)) or 0)
        except Exception as _exc:
            log_swallowed("geology_zip_dialog._choose_dbf_encoding (preference)", _exc)
            rank = 0.0
        ok = 0
        for raw in values:
            try:
                raw.decode(str(enc), errors="strict")
                decoded = True
            except (UnicodeDecodeError, LookupError):
                decoded = False  # expected: this candidate is not the encoding
            if decoded:
                ok += 1
        ranked.append((ok, rank, -order, str(enc)))
    ranked = [r for r in ranked if r[0] > 0]
    if not ranked:
        return GEOLOGY_PROVIDER_ENCODING, "config"
    ranked.sort(reverse=True)
    return ranked[0][3], "detected"


def _decode_zip_member_names(infos) -> int:
    """Re-decode ZIP member names written without the UTF-8 flag.

    zipfile decodes such names as cp437, so a Korean folder or file name
    zipped on Korean Windows (cp949) was extracted as mojibake. The raw bytes
    are recovered and decoded as UTF-8 when valid, else with the candidate
    encodings. Returns how many names were changed."""
    changed = 0
    encs = ["utf-8"] + [str(e) for e in (GEOLOGY_CANDIDATE_ENCODINGS or []) if e]
    for info in infos or []:
        try:
            if int(getattr(info, "flag_bits", 0) or 0) & 0x800:
                continue
            name = str(info.filename or "")
            if name.isascii():
                continue
            raw = name.encode("cp437")
        except Exception as _exc:
            log_swallowed("geology_zip_dialog._decode_zip_member_names", _exc)
            raw = None
        if raw is None:
            continue
        for enc in encs:
            try:
                fixed = raw.decode(enc, errors="strict")
            except (UnicodeDecodeError, LookupError):
                fixed = None
            if fixed:
                if fixed != info.filename:
                    info.filename = fixed
                    changed += 1
                break
    return changed


class KigamZipProcessor:
    # Guard rails against malformed/malicious ZIPs (zip bombs).
    MAX_ZIP_ENTRIES = 5000
    MAX_TOTAL_UNCOMPRESSED = 2 * 1024 ** 3  # 2 GiB
    MAX_COMPRESSION_RATIO = 200.0

    @staticmethod
    def default_extract_root() -> str:
        """The managed extraction folder under the QGIS profile, or "" when the
        profile path is unknown (a temp folder is used in that case).

        Side-effect free so the help text can name the folder without
        constructing a processor (whose __init__ runs the cleanup reaper).
        """
        root_name = GEOLOGY_EXTRACT_ROOT_NAME or "ArchToolkit_KIGAM_Extract"
        base = ""
        try:
            from qgis.core import QgsApplication

            base = str(QgsApplication.qgisSettingsDirPath() or "")
        except Exception:
            base = ""
        if base:
            return os.path.join(base, "ArchToolkit", root_name)
        return ""

    def __init__(self, iface=None):
        # The dialog passes its iface so load-time warnings (a sheet without a
        # CRS) reach the message bar; without it they only go to the log.
        self.iface = iface
        root_name = GEOLOGY_EXTRACT_ROOT_NAME or "ArchToolkit_KIGAM_Extract"
        base = self.default_extract_root()
        if base:
            # User-profile directory: private to this user (unlike the shared
            # system temp dir) and survives reboots, so layer sources in saved
            # projects keep working.
            self.extract_root = base
        else:
            self.extract_root = tempfile.mkdtemp(prefix=f"{root_name}_")
        # Folder the most recent process_zip() extracted into; the dialog
        # names it in the load message so the user knows the shapefiles live
        # in a managed folder with a retention window (GEO-13).
        self.last_extract_dir = ""
        # How many layers of an earlier load of the same ZIP organize_layers()
        # replaced in its KIGAM_<sheet> group (0 for a first load).
        self.last_replaced = 0
        try:
            os.makedirs(self.extract_root, exist_ok=True)
        except Exception as _exc:
            log_swallowed("geology_zip_dialog.__init__", _exc)
        self._cleanup_old_extracts()

    def _cleanup_old_extracts(self) -> None:
        """Remove extraction folders older than GEOLOGY_EXTRACT_CLEANUP_DAYS.

        The mtime of a folder is refreshed (touched) every time its layers are
        loaded, so extracts referenced by projects the user still opens never
        expire — cleanup only reaps folders untouched for the full window.
        (Deleting by creation age broke every saved project after 2 weeks.)
        """
        try:
            days = max(1, int(GEOLOGY_EXTRACT_CLEANUP_DAYS))
            cutoff = time.time() - days * 86400
            # Normalize both sides: _extract_dirs_in_use() returns abspath-based
            # paths, so comparing against a raw os.path.join(extract_root, name)
            # missed matches (mixed separators / case on Windows) and reaped
            # project-referenced extracts anyway.
            in_use = {os.path.normcase(os.path.abspath(p)) for p in self._extract_dirs_in_use()}
            for name in os.listdir(self.extract_root):
                path = os.path.join(self.extract_root, name)
                _skip_284 = False
                try:
                    if os.path.normcase(os.path.abspath(path)) in in_use:
                        self._touch_extract_dir(path)
                        continue
                    if os.path.isdir(path) and (not os.path.islink(path)) and os.path.getmtime(path) < cutoff:
                        shutil.rmtree(path, ignore_errors=True)
                except Exception as _exc:
                    log_swallowed("geology_zip_dialog._cleanup_old_extracts", _exc)
                    log_swallowed("tools/geology_zip_dialog.py:290 (_cleanup_old_extracts)", _exc)
                    _skip_284 = True
                if _skip_284:
                    continue
        except Exception as _exc:
            log_swallowed("geology_zip_dialog._cleanup_old_extracts", _exc)

    def _extract_dirs_in_use(self) -> set:
        """Top-level extract folders referenced by any layer in the CURRENT
        project — these must never be reaped, whatever their age."""
        used = set()
        try:
            root = os.path.normcase(os.path.abspath(self.extract_root))
            for lyr in QgsProject.instance().mapLayers().values():
                _skip_303 = False
                try:
                    src = str(lyr.source() or "").split("|", 1)[0]
                    src = os.path.normcase(os.path.abspath(src))
                    if src.startswith(root + os.sep):
                        rel = os.path.relpath(src, root)
                        top = rel.split(os.sep, 1)[0]
                        used.add(os.path.join(root, top))
                except Exception as _exc:
                    log_swallowed("geology_zip_dialog._extract_dirs_in_use", _exc)
                    log_swallowed("tools/geology_zip_dialog.py:310 (_extract_dirs_in_use)", _exc)
                    _skip_303 = True
                if _skip_303:
                    continue
        except Exception as _exc:
            log_swallowed("geology_zip_dialog._extract_dirs_in_use", _exc)
        return used

    @staticmethod
    def _touch_extract_dir(path: str) -> None:
        """Refresh mtime so _cleanup_old_extracts treats the folder as in use."""
        try:
            os.utime(path, None)
        except Exception as _exc:
            log_swallowed("tools/geology_zip_dialog.py:322 (_touch_extract_dir)", _exc)

    @staticmethod
    def _safe_extract_basename(zip_path: str) -> str:
        """Whitelist-sanitized folder name from the ZIP filename.

        A zip named '.. .zip' would otherwise map to '<root>/.. ' which Windows
        normalizes to the PARENT directory — and the pre-extract rmtree would
        then recursively delete everything above the extract root.
        """
        base = os.path.splitext(os.path.basename(str(zip_path or "")))[0]
        safe = re.sub(r"[^A-Za-z0-9가-힣_\-]+", "_", base).strip("._- ")
        return safe or "kigam_zip"

    def _zip_bomb_reason(self, infos) -> str:
        if len(infos) > self.MAX_ZIP_ENTRIES:
            return f"항목이 너무 많습니다({len(infos):,}개 > {self.MAX_ZIP_ENTRIES:,}개)"
        total = 0
        for info in infos:
            size = int(getattr(info, "file_size", 0) or 0)
            total += size
            compressed = int(getattr(info, "compress_size", 0) or 0)
            if size > 10 * 1024 ** 2 and compressed > 0 and (size / compressed) > self.MAX_COMPRESSION_RATIO:
                return f"압축비가 비정상적으로 높습니다({info.filename})"
        if total > self.MAX_TOTAL_UNCOMPRESSED:
            return f"압축 해제 용량이 너무 큽니다({total / 1024 ** 2:,.0f} MB)"
        return ""

    def process_zip(
        self,
        zip_path: str,
        *,
        font_family: str,
        font_size: int,
        apply_style: bool = True,
        apply_labels: bool = True,
        run_id: str,
    ) -> List[QgsVectorLayer]:
        zip_basename = self._safe_extract_basename(zip_path)
        zip_key = self._zip_key(zip_path)
        # Every load extracts into a folder of its own and never deletes an
        # existing one: an earlier folder of the same name may hold the files
        # of a sheet that is still loaded (two ZIPs named alike, or a reload),
        # and rmtree-ing it broke those layers. Unused folders are reaped by
        # _cleanup_old_extracts after the retention window.
        extract_dir = os.path.join(self.extract_root, zip_basename)
        try:
            n = 1
            while os.path.lexists(extract_dir):
                n += 1
                extract_dir = os.path.join(self.extract_root, f"{zip_basename}_{n}")
            os.makedirs(extract_dir)
        except Exception:
            try:
                extract_dir = tempfile.mkdtemp(prefix=f"{zip_basename}_", dir=self.extract_root)
            except Exception as e:
                log_message(f"KIGAM 추출 폴더 생성 실패: {e}", level=Qgis.MessageLevel.Warning)
                return []

        # Extract ZIP (with zip-bomb guard; stdlib extractall already
        # sanitizes absolute paths and '..' components).
        try:
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                infos = zip_ref.infolist()
                reason = self._zip_bomb_reason(infos)
                if reason:
                    log_message(f"KIGAM ZIP 추출 중단: {reason}", level=Qgis.MessageLevel.Warning)
                    return []
                # Names zipped without the UTF-8 flag (Korean Windows: cp949)
                # would otherwise be extracted as cp437 mojibake.
                n_fixed = _decode_zip_member_names(infos)
                if n_fixed:
                    log_message(f"KIGAM ZIP: UTF-8 표시 없는 파일 이름 {n_fixed}개를 한글 인코딩으로 해석했습니다.", level=Qgis.MessageLevel.Info)
                zip_ref.extractall(extract_dir, members=infos)
            self._touch_extract_dir(extract_dir)
        except Exception as e:
            log_message(f"KIGAM ZIP 추출 실패: {e}", level=Qgis.MessageLevel.Warning)
            return []
        self.last_extract_dir = extract_dir
        log_message(
            f"KIGAM 추출 폴더: {extract_dir} (레이어를 {max(1, int(GEOLOGY_EXTRACT_CLEANUP_DAYS))}일 동안 "
            "불러오지 않은 도엽 폴더는 다음 ZIP 로드 시 자동 삭제됩니다)",
            level=Qgis.MessageLevel.Info,
        )

        # Locate 'sym' folder (optional)
        sym_path = None
        for root, dirs, _ in os.walk(extract_dir):
            if "sym" in dirs:
                sym_path = os.path.join(root, "sym")
                break

        if apply_style and not sym_path:
            log_message("KIGAM ZIP에 'sym' 폴더가 없습니다. 심볼 적용은 건너뜁니다.", level=Qgis.MessageLevel.Warning)

        loaded_layers: List[QgsVectorLayer] = []
        for root, _, files in os.walk(extract_dir):
            for fname in files:
                if not fname.lower().endswith(".shp"):
                    continue
                shp_path = os.path.join(root, fname)
                layer_name = os.path.splitext(fname)[0]

                layer = QgsVectorLayer(shp_path, layer_name, "ogr")
                # Honour a .cpg; otherwise pick the encoding the DBF text
                # actually decodes with (was: cp949 forced on every sheet,
                # which garbled UTF-8 sheets even when their .cpg said so).
                encoding, enc_source = _choose_dbf_encoding(shp_path)
                if encoding:
                    try:
                        layer.setProviderEncoding(encoding)
                    except Exception as _exc:
                        log_swallowed("tools/geology_zip_dialog.py:413 (process_zip)", _exc)
                log_message(f"KIGAM: {fname} 속성 인코딩 {encoding or '(.cpg)'} ({enc_source})", level=Qgis.MessageLevel.Info)
                if not layer.isValid():
                    log_message(f"KIGAM 레이어 로드 실패: {shp_path}", level=Qgis.MessageLevel.Warning)
                    continue
                # A sheet whose .prj was lost (re-packed ZIP, decode failure)
                # loads fine and rasterizes fine - to a GeoTIFF with no CRS,
                # reported as success. Say so at load time, where the fix is
                # one click in layer properties.
                try:
                    if not layer.crs().isValid():
                        log_message(f"KIGAM: {fname} 좌표계 없음(.prj 누락/인식 불가). 래스터 변환 전 CRS를 지정하세요.", level=Qgis.MessageLevel.Warning)
                        push_message(self.iface, "지질도 좌표계",
                                     f"{fname}: 좌표계를 읽지 못했습니다. 레이어 속성에서 CRS를 지정한 뒤 래스터로 변환하세요.",
                                     level=1, duration=10)
                except Exception as _exc:
                    log_swallowed("geology_zip_dialog.process_zip (crs check)", _exc)

                QgsProject.instance().addMapLayer(layer, False)
                loaded_layers.append(layer)
                try:
                    # Identifies "the same ZIP" for a reload (organize_layers).
                    layer.setCustomProperty(ZIP_PATH_PROPERTY, zip_key)
                except Exception as _exc:
                    log_swallowed("geology_zip_dialog.process_zip (zip key)", _exc)

                if apply_style and sym_path:
                    try:
                        self.apply_sym_styling(layer, sym_path)
                    except Exception as e:
                        log_message(f"KIGAM 스타일 적용 실패: {layer.name()} ({e})", level=Qgis.MessageLevel.Warning)

                if apply_labels and ("Litho" in layer_name or "LITHO" in layer_name):
                    try:
                        self.apply_labeling(layer, font_family, font_size)
                    except Exception as _exc:
                        log_swallowed("tools/geology_zip_dialog.py:431 (process_zip)", _exc)

                try:
                    set_archtoolkit_layer_metadata(
                        layer,
                        tool_id="kigam_zip",
                        run_id=run_id,
                        kind="vector",
                        params={"zip": os.path.basename(zip_path), "sheet": zip_basename,
                                "encoding": encoding or "", "encoding_source": enc_source},
                    )
                except Exception as _exc:
                    log_swallowed("geology_zip_dialog.process_zip", _exc)

        self.organize_layers(loaded_layers, zip_basename, zip_key=zip_key)
        return loaded_layers

    def apply_sym_styling(self, layer: QgsVectorLayer, sym_path: str) -> None:
        sym_files = {
            os.path.splitext(f)[0]: os.path.join(sym_path, f)
            for f in os.listdir(sym_path)
            if f.lower().endswith(".png")
        }
        if not sym_files:
            return

        # Find best matching field
        best_field = None
        max_matches = 0
        priority_fields = ["LITHOIDX", "TYPE", "ASGN_CODE", "SIGN", "CODE", "AGEIDX"]
        all_fields = [f.name() for f in layer.fields()]
        sorted_fields = [f for f in priority_fields if f in all_fields] + [f for f in all_fields if f not in priority_fields]

        for field_name in sorted_fields:
            idx = layer.fields().indexOf(field_name)
            try:
                unique_values = layer.uniqueValues(idx)
            except Exception:
                unique_values = set()
            matches = 0
            for val in unique_values:
                if str(val) in sym_files:
                    matches += 1
            if matches > max_matches:
                max_matches = matches
                best_field = field_name

        if not best_field:
            return

        categories = []
        unique_values = layer.uniqueValues(layer.fields().indexOf(best_field))
        for val in unique_values:
            val_str = str(val)
            symbol = None

            if val_str in sym_files:
                png_path = sym_files[val_str]
                if layer.geometryType() == Qgis.GeometryType.Point:
                    symbol_layer = QgsRasterMarkerSymbolLayer(png_path)
                    symbol_layer.setSize(6)
                    symbol = QgsMarkerSymbol()
                    symbol.changeSymbolLayer(0, symbol_layer)
                elif layer.geometryType() == Qgis.GeometryType.Polygon:
                    symbol_layer = QgsRasterFillSymbolLayer()
                    symbol_layer.setImageFilePath(png_path)
                    symbol_layer.setWidth(10.0)
                    symbol = QgsFillSymbol()
                    symbol.changeSymbolLayer(0, symbol_layer)

            if symbol:
                categories.append(QgsRendererCategory(val, symbol, val_str))
            else:
                if layer.geometryType() == Qgis.GeometryType.Point:
                    symbol = QgsMarkerSymbol.createSimple({"color": "#ff0000"})
                elif layer.geometryType() == Qgis.GeometryType.Polygon:
                    symbol = QgsFillSymbol.createSimple({"color": "#cccccc", "outline_color": "black"})
                else:
                    continue
                categories.append(QgsRendererCategory(val, symbol, val_str))

        if categories:
            renderer = QgsCategorizedSymbolRenderer(best_field, categories)
            layer.setRenderer(renderer)
            layer.triggerRepaint()

    def apply_labeling(self, layer: QgsVectorLayer, font_family: str, font_size: int) -> None:
        settings = QgsPalLayerSettings()
        fields = [f.name() for f in layer.fields()]
        label_field = "LITHOIDX" if "LITHOIDX" in fields else "LITHONAME" if "LITHONAME" in fields else fields[0]
        settings.fieldName = label_field
        text_format = QgsTextFormat()
        text_format.setFont(QFont(font_family))
        text_format.setSize(int(font_size))
        text_format.setColor(QColor("black"))
        settings.setFormat(text_format)
        settings.placement = Qgis.LabelPlacement.Horizontal
        settings.centroidInside = True
        settings.fitInPolygonOnly = True
        settings.priority = 5
        layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
        layer.setLabelsEnabled(True)

    @staticmethod
    def _zip_key(zip_path: str) -> str:
        """Normalised absolute path of a ZIP: what "the same ZIP" means."""
        try:
            return os.path.normcase(os.path.abspath(str(zip_path or "")))
        except Exception as _exc:
            log_swallowed("geology_zip_dialog._zip_key", _exc)
            return str(zip_path or "")

    def organize_layers(self, layers: List[QgsVectorLayer], group_name: str, zip_key: str = "") -> None:
        if not layers:
            return
        root = QgsProject.instance().layerTreeRoot()
        parent = root.findGroup(PARENT_GROUP_NAME)
        if parent is None:
            parent = root.insertGroup(0, PARENT_GROUP_NAME)
        # Reloading the SAME ZIP (same path) replaces the ZIP layers of its
        # existing KIGAM_<sheet> group instead of adding a second identical
        # group (two "[sheet] Litho" entries in the raster list). Other layers
        # in that group - the rasters made from the sheet - are kept. A
        # different ZIP that merely shares the name gets its own group,
        # KIGAM_<sheet>_2, so neither sheet is lost or confused.
        self.last_replaced = 0
        new_ids = {lyr.id() for lyr in layers}
        base_label = f"KIGAM_{group_name}"
        groups = {c.name(): c for c in parent.children() if isinstance(c, QgsLayerTreeGroup)}
        run_group = None
        old_ids: List[str] = []
        for label, grp in groups.items():
            if label != base_label and not re.fullmatch(re.escape(base_label) + r"_\d+", label):
                continue
            zip_ids = []
            same_zip = False
            for node in grp.findLayers():
                try:
                    lyr0 = node.layer()
                    if lyr0 is None or lyr0.id() in new_ids:
                        continue
                    if str(lyr0.customProperty("archtoolkit/tool_id", "") or "") != "kigam_zip":
                        continue
                    zip_ids.append(lyr0.id())
                    if zip_key and str(lyr0.customProperty(ZIP_PATH_PROPERTY, "") or "") == zip_key:
                        same_zip = True
                except Exception as _exc:
                    log_swallowed("geology_zip_dialog.organize_layers (replace)", _exc)
            if same_zip:
                run_group = grp
                old_ids = zip_ids
                break
        if run_group is None:
            group_label = base_label
            n = 1
            while group_label in groups:
                n += 1
                group_label = f"{base_label}_{n}"
            run_group = parent.insertGroup(0, group_label)
        else:
            if old_ids:
                QgsProject.instance().removeMapLayers(old_ids)
            self.last_replaced = len(old_ids)
            log_message(f"KIGAM: {run_group.name()} 그룹의 기존 도엽 레이어 {len(old_ids)}개를 새로 불러온 레이어로 교체했습니다.",
                        level=Qgis.MessageLevel.Info)

        def _priority(layer: QgsVectorLayer) -> int:
            name = (layer.name() or "").lower()
            geom = layer.geometryType()

            # Reference / sheet helpers
            if "frame" in name:
                return 0

            # Polygons should sit below linework so labels/lines aren't hidden by fills.
            if "litho" in name:
                return 30
            if geom == Qgis.GeometryType.Polygon:
                return 25

            # Linework (top)
            if geom == Qgis.GeometryType.Line:
                if "crosssection" in name:
                    return 55
                if "boundary" in name:
                    return 50
                if "foliation" in name:
                    return 45
                if "schistosity" in name:
                    return 44
                return 40

            # Points (very top)
            if geom == Qgis.GeometryType.Point:
                return 60

            return 10

        def _hide_by_default(layer: QgsVectorLayer) -> bool:
            name = (layer.name() or "").lower()
            return ("frame" in name) or ("crosssection" in name)

        scored: List[Tuple[int, int, QgsVectorLayer]] = []
        for i, layer in enumerate(layers):
            scored.append((_priority(layer), i, layer))
        # Display order (top->bottom): higher priority first, stable by original order.
        scored.sort(key=lambda x: (-x[0], x[1]))

        # Below whatever the group keeps (rasters from a previous load), top->bottom.
        base = len(run_group.children())
        for pos, (_, __, layer) in enumerate(scored):
            node = run_group.insertLayer(base + pos, layer)
            if _hide_by_default(layer):
                try:
                    node.setItemVisibilityChecked(False)
                except Exception as _exc:
                    log_swallowed("tools/geology_zip_dialog.py:591 (organize_layers)", _exc)
        run_group.setExpanded(True)
        parent.setExpanded(True)


class GeologyZipDialog(QtWidgets.QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        # Remember the last-used inputs between sessions (tools/dialog_memory.py).
        dialog_memory.attach(self, "geology_zip")
        try:
            self.setWindowIcon(plugin_icon("geochem.png"))
        except Exception as _exc:
            log_swallowed("geology_zip_dialog.__init__ (icon)", _exc)
        self.iface = iface
        self.setWindowTitle("지질도 도엽 ZIP 불러오기 / MaxEnt 래스터 변환 - ArchToolkit")
        try:
            plugin_dir = os.path.dirname(os.path.dirname(__file__))
            icon_path = os.path.join(plugin_dir, "geochem.png")
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception as _exc:
            log_swallowed("tools/geology_zip_dialog.py:607 (__init__)", _exc)

        layout = QtWidgets.QVBoxLayout(self)

        header = QtWidgets.QLabel(
            "<b>KIGAM 1:50,000 지질도 ZIP 불러오기</b> + <b>벡터→래스터 변환</b><br>"
            "지질도 도엽 ZIP을 바로 로드하고, MaxEnt 같은 예측 모델링용 래스터로 변환합니다."
        )
        header.setWordWrap(True)
        header.setStyleSheet("background:#e3f2fd; padding:10px; border:1px solid #bbdefb; border-radius:4px;")
        layout.addWidget(header)

        # 1) ZIP loader
        grp_zip = QtWidgets.QGroupBox("1. 지질도 ZIP 불러오기 (KIGAM 1:50,000)")
        form_zip = QtWidgets.QFormLayout(grp_zip)

        self.txtZip = QtWidgets.QLineEdit()
        self.txtZip.setPlaceholderText("ZIP 파일을 선택하거나 경로를 입력하세요…")
        btn_browse = QtWidgets.QPushButton("찾기…")
        btn_browse.clicked.connect(self._browse_zip)
        row_zip = QtWidgets.QHBoxLayout()
        row_zip.addWidget(self.txtZip, 1)
        row_zip.addWidget(btn_browse)
        form_zip.addRow("ZIP 파일:", row_zip)

        self.cmbFont = QtWidgets.QFontComboBox()
        form_zip.addRow("라벨 글꼴:", self.cmbFont)

        self.spinFontSize = QtWidgets.QSpinBox()
        self.spinFontSize.setRange(5, 50)
        self.spinFontSize.setValue(10)
        form_zip.addRow("라벨 크기:", self.spinFontSize)

        self.chkApplyStyle = QtWidgets.QCheckBox("표준 심볼(sym 폴더) 적용")
        self.chkApplyStyle.setChecked(True)
        self.chkApplyLabels = QtWidgets.QCheckBox("지층 코드 라벨 적용")
        self.chkApplyLabels.setChecked(True)
        form_zip.addRow("", self.chkApplyStyle)
        form_zip.addRow("", self.chkApplyLabels)

        self.btnLoadZip = QtWidgets.QPushButton("ZIP 불러오기")
        self.btnLoadZip.clicked.connect(self._load_zip)
        form_zip.addRow("", self.btnLoadZip)

        layout.addWidget(grp_zip)

        # 2) Rasterize for MaxEnt
        grp_rst = QtWidgets.QGroupBox("2. 벡터 → 래스터 (MaxEnt/예측모델)")
        vbox = QtWidgets.QVBoxLayout(grp_rst)
        vbox.addWidget(QtWidgets.QLabel("변환할 벡터 레이어를 선택하세요:"))

        row_filter = QtWidgets.QHBoxLayout()
        row_filter.addWidget(QtWidgets.QLabel("필터:"))
        self.chkKigamOnly = QtWidgets.QCheckBox("KIGAM ZIP 레이어만")
        self.chkKigamOnly.setChecked(True)
        self.chkKigamOnly.setToolTip("ArchToolkit의 KIGAM ZIP 로더로 불러온 레이어만 목록에 표시합니다.")
        self.chkLithoOnly = QtWidgets.QCheckBox("Litho(폴리곤)만")
        self.chkLithoOnly.setChecked(True)
        self.chkLithoOnly.setToolTip("보통 예측모델링에는 Litho(암상/지층) 폴리곤만 있으면 충분합니다.")
        self.chkKigamOnly.stateChanged.connect(self.refresh_layer_list)
        self.chkLithoOnly.stateChanged.connect(self.refresh_layer_list)
        row_filter.addWidget(self.chkKigamOnly)
        row_filter.addWidget(self.chkLithoOnly)
        row_filter.addStretch(1)
        vbox.addLayout(row_filter)

        self.lstLayers = QtWidgets.QListWidget()
        self.lstLayers.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.lstLayers.itemChanged.connect(self._refresh_field_choices)
        vbox.addWidget(self.lstLayers)

        row_refresh = QtWidgets.QHBoxLayout()
        btn_refresh = QtWidgets.QPushButton("레이어 목록 새로고침")
        btn_refresh.clicked.connect(self.refresh_layer_list)
        row_refresh.addWidget(btn_refresh)
        row_refresh.addStretch(1)
        vbox.addLayout(row_refresh)

        form_rst = QtWidgets.QFormLayout()
        self.cmbField = QtWidgets.QComboBox()
        self.cmbField.addItem("(자동 선택)")
        form_rst.addRow("값 필드:", self.cmbField)

        self.spinPixel = QtWidgets.QDoubleSpinBox()
        self.spinPixel.setRange(0.1, 10000.0)
        self.spinPixel.setSingleStep(1.0)
        self.spinPixel.setValue(10.0)
        self.spinPixel.setSuffix(" m")
        self.spinPixel.setToolTip(
            "출력 래스터의 셀 크기(미터). 셀 중심이 폴리곤 안에 들어가는 셀에만 코드가 기록되므로, "
            "폭이 한 셀보다 좁은 지질 단위(얇은 암맥 등)는 이 픽셀 크기에서는 래스터에 기록되지 않습니다. "
            "매핑 CSV의 cell_count 열이 0인 코드가 그런 경우이며, 픽셀 크기를 줄이면 포함됩니다."
        )
        form_rst.addRow("해상도(픽셀 크기):", self.spinPixel)

        self.spinNoData = QtWidgets.QDoubleSpinBox()
        self.spinNoData.setRange(-9999999.0, 9999999.0)
        self.spinNoData.setDecimals(2)
        self.spinNoData.setValue(-9999.0)
        form_rst.addRow("NoData 값:", self.spinNoData)

        vbox.addLayout(form_rst)

        self.radMerge = QtWidgets.QRadioButton("선택 레이어 병합 후 단일 래스터")
        self.radPerLayer = QtWidgets.QRadioButton("레이어별 래스터 출력")
        self.radMerge.setChecked(True)
        self.radMerge.toggled.connect(self._toggle_output_mode)
        vbox.addWidget(self.radMerge)
        vbox.addWidget(self.radPerLayer)

        # Output path (single)
        self.txtOutFile = QtWidgets.QLineEdit()
        btn_out_file = QtWidgets.QPushButton("저장 위치…")
        btn_out_file.clicked.connect(self._browse_out_file)
        row_out = QtWidgets.QHBoxLayout()
        row_out.addWidget(self.txtOutFile, 1)
        row_out.addWidget(btn_out_file)
        vbox.addWidget(QtWidgets.QLabel("출력 파일(단일 모드):"))
        vbox.addLayout(row_out)

        # Output dir (per-layer)
        self.txtOutDir = QtWidgets.QLineEdit()
        btn_out_dir = QtWidgets.QPushButton("폴더 선택…")
        btn_out_dir.clicked.connect(self._browse_out_dir)
        row_dir = QtWidgets.QHBoxLayout()
        row_dir.addWidget(self.txtOutDir, 1)
        row_dir.addWidget(btn_out_dir)
        vbox.addWidget(QtWidgets.QLabel("출력 폴더(레이어별 모드):"))
        vbox.addLayout(row_dir)

        self.cmbFormat = QtWidgets.QComboBox()
        self.cmbFormat.addItem("GeoTIFF (*.tif)", "tif")
        self.cmbFormat.addItem("ASCII Grid (*.asc)", "asc")
        vbox.addWidget(QtWidgets.QLabel("출력 형식:"))
        vbox.addWidget(self.cmbFormat)

        self.btnRasterize = QtWidgets.QPushButton("래스터 변환 실행")
        self.btnRasterize.clicked.connect(self._run_rasterize)
        vbox.addWidget(self.btnRasterize)

        layout.addWidget(grp_rst)

        # Bottom buttons
        row_bottom = QtWidgets.QHBoxLayout()
        self.btnHelp = QtWidgets.QPushButton("도움말")
        self.btnHelp.clicked.connect(self._on_help)
        self.btnClose = QtWidgets.QPushButton("닫기")
        self.btnClose.clicked.connect(self.reject)
        row_bottom.addWidget(self.btnHelp)
        row_bottom.addStretch(1)
        row_bottom.addWidget(self.btnClose)
        layout.addLayout(row_bottom)

        self.resize(720, 760)
        self.refresh_layer_list()
        self._toggle_output_mode()

    def _browse_zip(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "KIGAM ZIP 파일 선택", "", "ZIP Files (*.zip *.ZIP)"
        )
        if path:
            self.txtZip.setText(path)

    def _browse_out_file(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "래스터 저장", "", "GeoTIFF (*.tif);;ASCII Grid (*.asc)"
        )
        if path:
            self.txtOutFile.setText(path)

    def _browse_out_dir(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "출력 폴더 선택", "")
        if path:
            self.txtOutDir.setText(path)

    def _toggle_output_mode(self):
        is_merge = self.radMerge.isChecked()
        self.txtOutFile.setEnabled(is_merge)
        # find browse button by sibling layout
        for w in self.findChildren(QtWidgets.QPushButton):
            if w.text() == "저장 위치…":
                w.setEnabled(is_merge)
            if w.text() == "폴더 선택…":
                w.setEnabled(not is_merge)
        self.txtOutDir.setEnabled(not is_merge)

    def _kigam_region_for_layer(self, layer: QgsVectorLayer) -> str:
        try:
            root = QgsProject.instance().layerTreeRoot()
            node = root.findLayer(layer.id())
            while node is not None:
                parent = node.parent()
                if parent is None:
                    break
                if isinstance(parent, QgsLayerTreeGroup):
                    name = str(parent.name() or "").strip()
                    if name.startswith("KIGAM_"):
                        return name[len("KIGAM_") :].strip()
                node = parent
        except Exception as _exc:
            log_swallowed("geology_zip_dialog._kigam_region_for_layer", _exc)
        return ""

    def refresh_layer_list(self):
        checked_ids = set()
        try:
            for i in range(self.lstLayers.count()):
                it = self.lstLayers.item(i)
                if it is not None and it.checkState() == Qt.CheckState.Checked:
                    checked_ids.add(it.data(Qt.ItemDataRole.UserRole))
        except Exception:
            checked_ids = set()

        self.lstLayers.blockSignals(True)
        self.lstLayers.clear()
        layers = list(QgsProject.instance().mapLayers().values())

        kigam_only = True
        litho_only = True
        try:
            kigam_only = bool(self.chkKigamOnly.isChecked())
            litho_only = bool(self.chkLithoOnly.isChecked())
        except Exception as _exc:
            log_swallowed("tools/geology_zip_dialog.py:826 (refresh_layer_list)", _exc)

        scored = []
        for layer in layers:
            if not isinstance(layer, QgsVectorLayer):
                continue
            if kigam_only:
                _skip_834 = False
                try:
                    tool_id = str(layer.customProperty("archtoolkit/tool_id", "") or "").strip()
                    if tool_id != "kigam_zip":
                        continue
                except Exception as _exc:
                    log_swallowed("tools/geology_zip_dialog.py:838 (refresh_layer_list)", _exc)
                    _skip_834 = True
                if _skip_834:
                    continue

            geom = layer.geometryType()
            if litho_only:
                if geom != Qgis.GeometryType.Polygon:
                    continue
                _skip_845 = False
                try:
                    lname = str(layer.name() or "").lower()
                    fields_up = {str(f.name() or "").upper() for f in layer.fields()}
                    candidate_fields_up = {name.upper() for name in GEOLOGY_LABEL_FIELD_CANDIDATES}
                    has_keyword = GEOLOGY_LITHO_LAYER_KEYWORD and GEOLOGY_LITHO_LAYER_KEYWORD in lname
                    has_candidate = any(name in fields_up for name in candidate_fields_up)
                    if GEOLOGY_LITHO_LAYER_KEYWORD and not has_keyword and not has_candidate:
                        continue
                except Exception as _exc:
                    log_swallowed("geology_zip_dialog.refresh_layer_list", _exc)
                    log_swallowed("tools/geology_zip_dialog.py:853 (refresh_layer_list)", _exc)
                    _skip_845 = True
                if _skip_845:
                    continue

            region = self._kigam_region_for_layer(layer)
            scored.append((region, str(layer.name() or ""), layer, geom))

        scored.sort(key=lambda x: (x[0], x[1]))
        for region, layer_name, layer, geom in scored:
            shown_name = layer_name
            if region:
                shown_name = f"[{region}] {layer_name}"
            item = QtWidgets.QListWidgetItem(layer.name())
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if layer.id() in checked_ids else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, layer.id())
            tip = []
            if geom == Qgis.GeometryType.Point:
                tip.append("포인트 레이어")
            elif geom == Qgis.GeometryType.Line:
                tip.append("라인 레이어")
            elif geom == Qgis.GeometryType.Polygon:
                tip.append("폴리곤 레이어")
            if region:
                tip.append(f"지역/도엽: {region}")
            if tip:
                item.setToolTip(" / ".join(tip))
            item.setText(shown_name)
            self.lstLayers.addItem(item)
        self.lstLayers.blockSignals(False)
        self._refresh_field_choices()

    def _selected_vector_layers(self) -> List[QgsVectorLayer]:
        out: List[QgsVectorLayer] = []
        layer_map = QgsProject.instance().mapLayers()
        for i in range(self.lstLayers.count()):
            item = self.lstLayers.item(i)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            lid = item.data(Qt.ItemDataRole.UserRole)
            layer = layer_map.get(lid)
            if isinstance(layer, QgsVectorLayer) and layer.isValid():
                out.append(layer)
        return out

    def _refresh_field_choices(self, *_):
        layers = self._selected_vector_layers()
        fields = set()
        if layers:
            for lyr in layers:
                for f in lyr.fields():
                    fields.add(f.name())
        else:
            layer_map = QgsProject.instance().mapLayers()
            for i in range(self.lstLayers.count()):
                item = self.lstLayers.item(i)
                if item is None:
                    continue
                lid = item.data(Qt.ItemDataRole.UserRole)
                lyr = layer_map.get(lid)
                if isinstance(lyr, QgsVectorLayer):
                    for f in lyr.fields():
                        fields.add(f.name())

        current = self.cmbField.currentText()
        self.cmbField.blockSignals(True)
        self.cmbField.clear()
        self.cmbField.addItem("(자동 선택)")
        for name in sorted(fields):
            self.cmbField.addItem(name)
        if current:
            idx = self.cmbField.findText(current)
            if idx >= 0:
                self.cmbField.setCurrentIndex(idx)
        self.cmbField.blockSignals(False)

    def _choose_common_field(self, layers: List[QgsVectorLayer]) -> Optional[str]:
        if not layers:
            return None
        chosen = self.cmbField.currentText().strip()
        if chosen and chosen != "(자동 선택)":
            if all(lyr.fields().indexOf(chosen) >= 0 for lyr in layers):
                return chosen
        # Auto: prefer common fields
        common = set(f.name() for f in layers[0].fields())
        for lyr in layers[1:]:
            common &= set(f.name() for f in lyr.fields())
        if not common:
            return None
        priority = ["LITHOIDX", "AGEIDX", "LITHONAME", "TYPE", "ASGN_CODE", "SIGN", "CODE"]
        for p in priority:
            if p in common:
                return p
        # Last resort: the alphabetically first common field. It may be an
        # area or id column, so say which field is being burned instead of
        # tagging an arbitrary attribute as a lithology class silently (GEO-09).
        fallback = sorted(common)[0]
        text = (f"우선 필드(LITHOIDX/AGEIDX 등)가 공통으로 없어 공통 필드 중 이름순 첫 번째 '{fallback}'를 "
                "값 필드로 사용합니다. 지질 코드가 아닐 수 있으니 확인하거나 필드를 직접 선택하세요.")
        log_message(f"KIGAM rasterize: {text}", level=Qgis.MessageLevel.Warning)
        push_message(self.iface, "값 필드 자동 선택", text, level=1, duration=10)
        return fallback

    def _suggest_label_field(self, layer: QgsVectorLayer, field_name: str) -> Optional[str]:
        try:
            fields = [f.name() for f in (layer.fields() or [])]
        except Exception:
            fields = []
        if not fields:
            return None

        up = {str(f).upper(): str(f) for f in fields if f}
        base = str(field_name or "").strip()
        base_up = base.upper()
        if not base_up:
            return None

        if base_up.endswith("IDX"):
            cand = base_up[:-3] + "NAME"
            if cand in up:
                return up[cand]

        if base_up.endswith("ID"):
            cand = base_up[:-2] + "NAME"
            if cand in up:
                return up[cand]

        # Common KIGAM pairs / fallbacks
        for cand in ("LITHONAME", "AGENAME", "NAME", "KOR_NAME", "ENG_NAME"):
            if cand in up and up[cand] != base:
                return up[cand]

        return None

    def _is_numeric_field(self, layer: QgsVectorLayer, field_name: str) -> bool:
        try:
            f = layer.fields().field(field_name)
            if f is None:
                return False
            return f.type() in (
                FT_INT,
                FT_UINT,
                FT_LONGLONG,
                FT_ULONGLONG,
                FT_DOUBLE,
            )
        except Exception:
            return False

    def _field_numeric_across(
        self,
        layers: List[QgsVectorLayer],
        field_name: str,
    ) -> Tuple[bool, List[str], List[str], List[str]]:
        """Decide numeric-vs-text for a field over EVERY selected layer that has it.

        Deciding from layers[0] alone made a sheet that stores LITHOIDX as
        text fail int(float('Kgr')) on every feature and contribute nothing
        to the raster. The field is numeric only when it is numeric in all
        layers; on a disagreement the caller warns and the field is treated
        as text, which keeps every sheet (GEO-07). Returns
        (numeric, numeric_layer_names, text_layer_names, double_layer_names).
        """
        num_names: List[str] = []
        text_names: List[str] = []
        double_names: List[str] = []
        for lyr in layers or []:
            try:
                if lyr.fields().indexOf(field_name) < 0:
                    continue
                name = str(lyr.name() or "")
                if self._is_numeric_field(lyr, field_name):
                    num_names.append(name)
                    if lyr.fields().field(field_name).type() == FT_DOUBLE:
                        double_names.append(name)
                else:
                    text_names.append(name)
            except Exception as _exc:
                log_swallowed("geology_zip_dialog._field_numeric_across", _exc)
        numeric = bool(num_names) and not text_names
        return numeric, num_names, text_names, double_names

    def _warn_field_types(self, field_name: str, num_names: List[str], text_names: List[str], double_names: List[str]) -> None:
        """Say in the message bar when the value field is typed differently
        per layer (then burned as text) or is a Double (then truncated)."""
        if num_names and text_names:
            text = (f"'{field_name}' 자료형이 레이어마다 다릅니다(숫자: {', '.join(num_names)} / 문자: {', '.join(text_names)}). "
                    "모든 레이어를 문자 코드로 매핑합니다(정수 코드는 mapping.csv 참고).")
            log_message(f"KIGAM rasterize: {text}", level=Qgis.MessageLevel.Warning)
            push_message(self.iface, "값 필드 자료형 불일치", text, level=1, duration=12)
        elif double_names:
            text = (f"'{field_name}'는 실수(Double) 필드입니다({', '.join(double_names)}). "
                    "소수점 이하를 잘라낸 정수를 클래스 코드로 기록합니다. 실측값(면적 등)이라면 지질 클래스 래스터로 쓰지 마세요.")
            log_message(f"KIGAM rasterize: {text}", level=Qgis.MessageLevel.Warning)
            push_message(self.iface, "실수 필드 정수 변환", text, level=1, duration=12)

    def _build_shared_code_mapping(
        self,
        layers: List[QgsVectorLayer],
        field_name: str,
        numeric: Optional[bool] = None,
    ) -> Tuple[Dict[str, int], Dict[str, str], Dict[str, List[str]], List[Tuple[str, List[str]]]]:
        """One code mapping for every selected sheet, in a content-derived order.

        String codes (Qa, Jbgr, ...) used to be numbered in feature-encounter
        order with the counter restarting per output, so the same lithology
        got a different integer in each sheet and each run, and ticking one
        more sheet renumbered every class. Codes are now assigned over the
        sorted union of values across ALL selected layers, so a lithology
        keeps its integer across sheets and re-runs of the same selection.

        Numeric index codes (LITHOIDX/AGEIDX) are kept as they are, but every
        label seen for a code is collected so a code that means different
        things in different sheets is detected instead of the first sheet's
        name silently winning. Returns (mapping, labels, labels_all, conflicts).
        """
        mapping: Dict[str, int] = {}
        labels: Dict[str, str] = {}
        labels_all: Dict[str, List[str]] = {}
        conflicts: List[Tuple[str, List[str]]] = []
        if not layers:
            return mapping, labels, labels_all, conflicts
        if numeric is None:
            numeric = self._field_numeric_across(layers, field_name)[0]
        label_field = self._suggest_label_field(layers[0], field_name) if numeric else None
        keys: set = set()
        for lyr in layers:
            if lyr.fields().indexOf(field_name) < 0:
                continue
            lf = label_field if (label_field and lyr.fields().indexOf(label_field) >= 0) else None
            for f in lyr.getFeatures():
                try:
                    val = f[field_name]
                except Exception as _exc:
                    log_swallowed("geology_zip_dialog._build_shared_code_mapping", _exc)
                    val = None
                if _is_blank(val):
                    continue
                if numeric:
                    try:
                        code = str(int(float(val)))
                    except Exception as _exc:
                        log_swallowed("geology_zip_dialog._build_shared_code_mapping", _exc)
                        code = None
                    if code is None:
                        continue
                    keys.add(code)
                    if lf:
                        try:
                            lbl = f[lf]
                            if not _is_blank(lbl):
                                seen = labels_all.setdefault(code, [])
                                if str(lbl).strip() not in seen:
                                    seen.append(str(lbl).strip())
                        except Exception as _exc:
                            log_swallowed("geology_zip_dialog._build_shared_code_mapping", _exc)
                else:
                    keys.add(_code_key(val))
        if numeric:
            for code in sorted(keys, key=lambda c: int(c)):
                mapping[code] = int(code)
                seen = labels_all.get(code) or []
                if seen:
                    labels[code] = seen[0]
                if len(seen) > 1:
                    conflicts.append((code, list(seen)))
        else:
            for i, key in enumerate(sorted(keys), start=1):
                mapping[key] = i
                labels[key] = key
        return mapping, labels, labels_all, conflicts

    def _build_numeric_merge_layer(
        self,
        layers: List[QgsVectorLayer],
        field_name: str,
        mapping: Optional[Dict[str, int]] = None,
        labels: Optional[Dict[str, str]] = None,
        numeric: Optional[bool] = None,
    ) -> Tuple[Optional[QgsVectorLayer], Dict[str, int], Dict[str, str], Dict[int, int], Dict[str, int]]:
        """Returns (layer, mapping, labels, counts, drops). ``drops`` counts,
        per DROP_REASON_LABELS key, every feature or layer that did not reach
        the burn, so callers can report it instead of claiming success."""
        if not layers:
            return None, {}, {}, {}, {}

        target_crs = layers[0].crs()
        try:
            wkb = QgsWkbTypes.flatType(layers[0].wkbType())
        except Exception:
            wkb = layers[0].wkbType()
        geom_str = QgsWkbTypes.displayString(wkb) or "Polygon"

        authid = ""
        try:
            if target_crs is not None and target_crs.isValid():
                authid = str(target_crs.authid() or "").strip()
        except Exception:
            authid = ""

        uri = geom_str
        if authid and authid.upper() != "EPSG:0":
            uri = f"{geom_str}?crs={authid}"

        out_layer = QgsVectorLayer(uri, "merged_tmp", "memory")
        if out_layer is None or not out_layer.isValid():
            # Best-effort fallback: omit CRS from URI (some layers may have unknown CRS/authid).
            out_layer = QgsVectorLayer(geom_str, "merged_tmp", "memory")

        if out_layer is None or not out_layer.isValid():
            log_message(f"병합 레이어 생성 실패(메모리 레이어 초기화 실패): geom={geom_str}, crs={authid}", level=Qgis.MessageLevel.Warning)
            return None, {}, {}, {}, {}

        try:
            if target_crs is not None and target_crs.isValid():
                out_layer.setCrs(target_crs)
        except Exception as _exc:
            log_swallowed("tools/geology_zip_dialog.py:1032 (_build_numeric_merge_layer)", _exc)

        pr = out_layer.dataProvider()
        pr.addAttributes([QgsField("ATK_VAL", FT_INT)])
        out_layer.updateFields()

        # A caller may pass the run-wide mapping from _build_shared_code_mapping
        # so every output of the run shares one code table; unseen keys are
        # appended after it rather than restarting at 1.
        mapping = dict(mapping) if mapping else {}
        labels = dict(labels) if labels else {}
        counts: Dict[int, int] = {}
        # Every feature that does not reach the burn is counted by reason so
        # the completion message can say how much of the sheet is missing
        # instead of reporting an unqualified success (GEO-07).
        drops: Dict[str, int] = {k: 0 for k in DROP_REASON_LABELS}
        next_id = (max(int(v) for v in mapping.values()) + 1) if mapping else 1
        if numeric is None:
            numeric, num_names, text_names, _dbl = self._field_numeric_across(layers, field_name)
            if num_names and text_names:
                log_message(
                    f"KIGAM: '{field_name}' 자료형이 레이어마다 다릅니다(숫자: {', '.join(num_names)} / 문자: {', '.join(text_names)}). "
                    "문자 코드로 처리합니다.",
                    level=Qgis.MessageLevel.Warning,
                )
        label_field = self._suggest_label_field(layers[0], field_name) if numeric else None

        for lyr in layers:
            if lyr.geometryType() != layers[0].geometryType():
                log_message(f"지오메트리 타입 불일치: {lyr.name()} (skip)", level=Qgis.MessageLevel.Warning)
                drops["layer_geometry_mismatch"] += 1
                continue
            if lyr.fields().indexOf(field_name) < 0:
                log_message(f"필드 '{field_name}' 없음으로 레이어 제외: {lyr.name()}", level=Qgis.MessageLevel.Warning)
                drops["layer_field_missing"] += 1
                continue
            transform = None
            if lyr.crs() != target_crs and (not lyr.crs().isValid() or not target_crs.isValid()):
                # A transform from (or to) a missing CRS is a silent no-op that
                # reports success, so a sheet without a .prj was merged with
                # its coordinates read as the other sheet's CRS (GEO-14).
                log_message(f"좌표계가 없어 레이어 제외(병합 불가): {lyr.name()}", level=Qgis.MessageLevel.Warning)
                drops["layer_crs_missing"] += 1
                continue
            if lyr.crs() != target_crs:
                _skip_1052 = False
                try:
                    transform = QgsCoordinateTransform(lyr.crs(), target_crs, QgsProject.instance())
                    if not transform.isValid():
                        raise RuntimeError("invalid coordinate transform")
                except Exception as _exc:
                    # Can't reproject this layer — skip it rather than merge its
                    # features untransformed (mixed CRS → misplaced polygons).
                    log_message(f"좌표계 변환 실패로 레이어 제외: {lyr.name()}", level=Qgis.MessageLevel.Warning)
                    log_swallowed("tools/geology_zip_dialog.py:1054 (_build_numeric_merge_layer)", _exc)
                    _skip_1052 = True
                if _skip_1052:
                    drops["layer_transform_failed"] += 1
                    continue

            for f in lyr.getFeatures():
                _skip_1061 = False
                try:
                    geom = f.geometry()
                    if geom is None or geom.isEmpty():
                        drops["empty_geometry"] += 1
                        continue
                    if transform is not None:
                        # transform() returns a status code, not an exception.
                        if geom.transform(transform) != 0:
                            drops["transform_failed"] += 1
                            continue
                    val = f[field_name]
                    if _is_blank(val):
                        # NULL (a QVariant, not None) and blank text alike:
                        # numeric NULLs used to be counted as "숫자 아님" and
                        # text NULLs burned as a class named "NULL".
                        drops["null_value"] += 1
                        continue
                    if numeric:
                        _skip_1073 = False
                        try:
                            out_int = int(float(val))
                        except Exception as _exc:
                            log_swallowed("geology_zip_dialog._build_numeric_merge_layer", _exc)
                            log_swallowed("tools/geology_zip_dialog.py:1075 (_build_numeric_merge_layer)", _exc)
                            _skip_1073 = True
                        if _skip_1073:
                            drops["non_numeric"] += 1
                            continue
                        code = str(out_int)
                        mapping[code] = out_int
                        if label_field and code not in labels:
                            try:
                                lbl = f[label_field]
                                if not _is_blank(lbl):
                                    labels[code] = str(lbl).strip()
                            except Exception as _exc:
                                log_swallowed("tools/geology_zip_dialog.py:1085 (_build_numeric_merge_layer)", _exc)
                        out_val = float(out_int)
                    else:
                        key = _code_key(val)
                        if key not in mapping:
                            mapping[key] = next_id
                            next_id += 1
                        if key not in labels:
                            labels[key] = key
                        out_val = float(mapping[key])

                    nf = QgsFeature(out_layer.fields())
                    nf.setGeometry(geom)
                    nf.setAttributes([out_val])
                    # PyQGIS returns (ok, features); older builds a bare bool.
                    res = pr.addFeatures([nf])
                    ok = bool(res[0]) if isinstance(res, (tuple, list)) else bool(res)
                    if not ok:
                        drops["add_failed"] += 1
                        continue

                    try:
                        out_i = int(out_val)
                        counts[out_i] = counts.get(out_i, 0) + 1
                    except Exception as _exc:
                        log_swallowed("geology_zip_dialog._build_numeric_merge_layer", _exc)
                except Exception as _exc:
                    log_swallowed("geology_zip_dialog._build_numeric_merge_layer", _exc)
                    log_swallowed("tools/geology_zip_dialog.py:1107 (_build_numeric_merge_layer)", _exc)
                    drops["feature_error"] += 1
                    _skip_1061 = True
                if _skip_1061:
                    continue

        out_layer.updateExtents()
        return out_layer, mapping, labels, counts, drops

    def _write_mapping_csv(
        self,
        mapping: Dict[str, int],
        out_path: str,
        *,
        labels: Optional[Dict[str, str]] = None,
        counts: Optional[Dict[int, int]] = None,
        labels_all: Optional[Dict[str, List[str]]] = None,
        cell_counts: Optional[Dict[int, int]] = None,
    ) -> Optional[str]:
        csv_path = ""
        try:
            csv_path = os.path.splitext(str(out_path or ""))[0] + "_mapping.csv"
        except Exception as _exc:
            log_swallowed("geology_zip_dialog._write_mapping_csv", _exc)
        if not mapping and not labels and not counts:
            # Nothing to write: every feature was dropped before the burn
            # (see the drop counters in the completion message).
            log_message(f"코드 매핑 CSV를 만들 코드가 없습니다(피처가 모두 제외되었을 수 있음): {csv_path}", level=Qgis.MessageLevel.Warning)
            return None
        err = ""
        try:
            labels = labels or {}
            counts = counts or {}
            labels_all = labels_all or {}
            # utf-8-sig: Excel on Korean Windows reads BOM-less UTF-8 as cp949
            # and garbles every lithology name; the plugin's other user-facing
            # CSVs already write the BOM (GEO-11).
            with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                # labels_all lists every name seen for a code across the selected
                # sheets, "|"-joined; more than one name means the code is not
                # the same lithology everywhere and the raster must be read with
                # its source sheet in mind.
                # cell_count is the number of cells carrying the code in the
                # WRITTEN raster (cell-centre burn). 0 with feature_count > 0
                # means the unit is narrower than one cell at this pixel size
                # and is absent from the raster; blank means the raster could
                # not be read back to count.
                w.writerow(["code", "int_value", "label", "feature_count", "cell_count", "labels_all"])
                rows = []
                for code, v in (mapping or {}).items():
                    vv = int(v)
                    cc = "" if cell_counts is None else int(cell_counts.get(vv, 0))
                    rows.append((vv, str(code), str(labels.get(str(code), "") or ""), int(counts.get(vv, 0)),
                                 cc, "|".join(labels_all.get(str(code), []) or [])))
                rows.sort(key=lambda x: (x[0], x[1]))
                for vv, code, label, cnt, cc, lall in rows:
                    w.writerow([code, vv, label, cnt, cc, lall])
            if os.path.exists(csv_path) and os.path.getsize(csv_path) > 0:
                return csv_path
            err = "파일이 생성되지 않았거나 비어 있습니다"
        except Exception as _exc:
            log_swallowed("geology_zip_dialog._write_mapping_csv", _exc)
            err = str(_exc) or _exc.__class__.__name__
        # The CSV is the only legend for the raster's integers: a failure to
        # write it must be as visible as the raster's success (GEO-06).
        text = f"코드 매핑 CSV를 쓰지 못했습니다: {csv_path or '(경로 없음)'} ({err})."
        if mapping:
            text += (f" 래스터의 정수 코드 {len(mapping)}개를 해석할 범례 파일이 없습니다. "
                     "이 래스터만으로는 코드가 어떤 지질 단위인지 알 수 없으니 쓰기 가능한 폴더로 다시 실행하세요.")
        log_message(f"KIGAM rasterize: {text}", level=Qgis.MessageLevel.Warning)
        push_message(self.iface, "코드 매핑 CSV 실패", text, level=1, duration=15)
        return None

    def _raster_cell_counts(self, raster_path: str, nodata: float) -> Optional[Dict[int, int]]:
        """Distinct integer values actually present in the written raster and
        their cell counts, read back in row blocks so a whole sheet at a fine
        pixel size is never loaded at once. None when GDAL/numpy are missing
        or the file cannot be read; the CSV then leaves cell_count blank
        rather than claiming a count (GEO-10)."""
        try:
            from osgeo import gdal
            import numpy as np
        except Exception as _exc:
            log_swallowed("geology_zip_dialog._raster_cell_counts", _exc)
            return None
        ds = None
        try:
            ds = gdal.Open(str(raster_path))
            if ds is None:
                return None
            band = ds.GetRasterBand(1)
            xs, ys = int(ds.RasterXSize), int(ds.RasterYSize)
            if xs <= 0 or ys <= 0:
                return None
            nd = band.GetNoDataValue()
            nd = float(nodata) if nd is None else float(nd)
            # About 4M cells (16 MB of Int32) per block.
            rows_per_block = max(1, 4000000 // max(1, xs))
            totals: Dict[int, int] = {}
            y = 0
            while y < ys:
                h = min(rows_per_block, ys - y)
                arr = band.ReadAsArray(0, y, xs, h)
                if arr is None:
                    return None
                vals, cnts = np.unique(np.asarray(arr), return_counts=True)
                for v, c in zip(vals.tolist(), cnts.tolist()):
                    fv = float(v)
                    if math.isnan(fv) or fv == nd:
                        continue
                    iv = int(round(fv))
                    totals[iv] = totals.get(iv, 0) + int(c)
                y += h
            return totals
        except Exception as _exc:
            log_swallowed("geology_zip_dialog._raster_cell_counts", _exc)
            return None
        finally:
            ds = None

    def _report_unburned_codes(
        self,
        mapping: Dict[str, int],
        labels: Dict[str, str],
        cell_counts: Optional[Dict[int, int]],
        raster_path: str,
        feature_counts: Optional[Dict[int, int]] = None,
    ) -> List[str]:
        """Name the codes that have features but no cell in the written raster
        (units narrower than one cell at this pixel size). Returns them.

        `feature_counts` (int code -> features burned into THIS raster) limits
        the check to codes this raster actually received: the shared code
        table also lists codes of the other sheets, and those were reported
        as "narrower than a cell" for a sheet that never contained them."""
        if cell_counts is None:
            log_message(f"래스터 값을 읽지 못해 mapping.csv의 cell_count 열을 비워 둡니다: {raster_path}", level=Qgis.MessageLevel.Warning)
            return []
        missing: List[str] = []
        for code, v in (mapping or {}).items():
            present = True  # unknown counts are never reported as missing
            try:
                if feature_counts is not None and int(feature_counts.get(int(v), 0) or 0) <= 0:
                    continue  # no feature of this code reached this raster
                present = int(cell_counts.get(int(v), 0)) > 0
            except Exception as _exc:
                log_swallowed("geology_zip_dialog._report_unburned_codes", _exc)
            if present:
                continue
            lbl = str((labels or {}).get(str(code), "") or "")
            missing.append(f"{code}={v}" + (f"({lbl})" if lbl and lbl != str(code) else ""))
        if not missing:
            return []
        shown = ", ".join(missing[:10]) + (f" 외 {len(missing) - 10}개" if len(missing) > 10 else "")
        text = (f"코드 {len(missing)}개는 폴리곤 폭이 한 셀보다 좁아 이 픽셀 크기의 래스터에 기록되지 않았습니다"
                f"(cell_count=0): {shown}. 픽셀 크기를 줄이면 포함됩니다.")
        log_message(f"KIGAM rasterize: {text} [{raster_path}]", level=Qgis.MessageLevel.Warning)
        push_message(self.iface, "래스터에 없는 코드", text, level=1, duration=12)
        return missing

    def _rasterize_layer(
        self,
        layer: QgsVectorLayer,
        field_name: str,
        out_path: str,
        pixel_size: float,
        nodata: float,
    ) -> str:
        # The AAIGrid (.asc) driver is CreateCopy-only, but gdal_rasterize needs
        # a Create-capable driver — a direct .asc output has never worked.
        # Rasterize to GTiff first, then translate to .asc (the format MaxEnt
        # actually consumes).
        if str(out_path or "").lower().endswith(".asc"):
            # A geographic CRS gives unequal lon/lat cell sizes, which the
            # AAIGrid driver writes as dx/dy instead of cellsize - a header
            # ArcGIS and MaxEnt do not read. The export is kept (QGIS reads
            # it) but the user is told in the message bar (GEO-08).
            try:
                crs0 = layer.crs()
                if crs0 is not None and crs0.isValid() and crs0.isGeographic():
                    text = (f"{layer.name()}: 지리좌표계({crs0.authid() or '?'}) 레이어를 ASCII Grid로 내보냅니다. "
                            "헤더의 셀 크기가 경도/위도(도) 단위(dx/dy)로 기록되어 ArcGIS·MaxEnt는 이 파일을 읽지 못하거나 "
                            "잘못 배치할 수 있습니다. 투영 CRS(미터, 예: EPSG:5179)로 변환한 뒤 내보내는 것을 권장합니다.")
                    log_message(f"KIGAM rasterize: {text}", level=Qgis.MessageLevel.Warning)
                    push_message(self.iface, "ASCII Grid 좌표계 주의", text, level=1, duration=15)
            except Exception as _exc:
                log_swallowed("geology_zip_dialog._rasterize_layer", _exc)
            tmp_tif = os.path.join(
                tempfile.gettempdir(), f"atk_kigam_asc_{new_run_id('kigam')}.tif"
            )
            tif_path = self._rasterize_layer(layer, field_name, tmp_tif, pixel_size, nodata)
            try:
                processing.run("gdal:translate", {
                    "INPUT": tif_path,
                    "TARGET_CRS": None,
                    "NODATA": float(nodata),
                    "COPY_SUBDATASETS": False,
                    "OPTIONS": "",
                    "EXTRA": "-of AAIGrid",
                    "DATA_TYPE": 0,
                    "OUTPUT": out_path,
                })
            finally:
                try:
                    if os.path.exists(tif_path):
                        os.remove(tif_path)
                except Exception as _exc:
                    log_swallowed("geology_zip_dialog._rasterize_layer", _exc)
            if not os.path.exists(out_path):
                raise RuntimeError("ASCII Grid(.asc) 변환에 실패했습니다. GeoTIFF 형식을 사용해보세요.")
            return out_path

        rect = None
        try:
            rect = layer.extent()
        except Exception:
            rect = None
        try:
            authid = str(layer.crs().authid() or "").strip() if layer.crs().isValid() else ""
        except Exception:
            authid = ""

        cell_w = float(pixel_size)
        cell_h = float(pixel_size)
        try:
            crs = layer.crs()
            units = None
            try:
                units = crs.mapUnits() if crs is not None and crs.isValid() else None
            except Exception:
                units = None

            if crs is None or not crs.isValid():
                # A CRS-less input rasterizes without complaint into a GeoTIFF
                # that carries no projection and reports success. Refuse it.
                raise RuntimeError(
                    f"{layer.name()}: 좌표계가 없어 래스터를 만들 수 없습니다. 레이어 속성에서 CRS를 지정한 뒤 다시 실행하세요."
                )
            if crs is not None and crs.isValid() and (crs.isGeographic() or units == Qgis.DistanceUnit.Degrees):
                lat0 = 0.0
                try:
                    if rect is not None:
                        lat0 = float((rect.yMinimum() + rect.yMaximum()) / 2.0)
                except Exception:
                    lat0 = 0.0
                deg_w, deg_h = _meters_to_degrees(cell_w, lat0)
                if deg_w > 0 and deg_h > 0:
                    log_message(
                        f"KIGAM rasterize: geographic CRS detected ({authid or 'unknown'}). "
                        f"pixel {cell_w}m -> {deg_w:.8f}°(lon) {deg_h:.8f}°(lat) at lat={lat0:.4f}",
                        level=Qgis.MessageLevel.Warning,
                    )
                    # Say it where the user looks, not only in the log (GEO-08).
                    push_message(
                        self.iface, "픽셀 크기 변환",
                        f"{layer.name()}: 지리좌표계({authid or '?'})라서 픽셀 {cell_w:g} m를 위도 {lat0:.2f}° 기준 "
                        f"{deg_w:.8f}°(경도) x {deg_h:.8f}°(위도)로 바꿔 래스터를 만듭니다. "
                        "정확한 미터 격자가 필요하면 투영 CRS로 변환한 뒤 실행하세요.",
                        level=1, duration=12,
                    )
                    cell_w, cell_h = float(deg_w), float(deg_h)
        except Exception as _exc:
            log_swallowed("geology_zip_dialog._rasterize_layer", _exc)

        try:
            if rect is not None:
                w = float(rect.width())
                h = float(rect.height())
                cols = int(math.ceil(w / cell_w)) if cell_w > 0 else 0
                rows = int(math.ceil(h / cell_h)) if cell_h > 0 else 0
                log_message(
                    f"KIGAM rasterize grid: extent_w={w} extent_h={h} cell_w={cell_w} cell_h={cell_h} -> {cols}x{rows}",
                    level=Qgis.MessageLevel.Info,
                )
                if cols <= 0 or rows <= 0:
                    raise RuntimeError(
                        "출력 래스터 크기가 0입니다. (CRS 단위/해상도 불일치) "
                        "투영 CRS(미터 단위)로 변환하거나 픽셀 크기를 조정하세요."
                    )
        except Exception as e:
            log_message(f"KIGAM rasterize preflight 실패: {e}", level=Qgis.MessageLevel.Warning)
            raise

        log_message(
            "KIGAM rasterize: "
            f"layer={layer.name()} field={field_name} out={out_path} "
            f"px={cell_w}x{cell_h} nodata={nodata} crs={authid} extent={rect}",
            level=Qgis.MessageLevel.Info,
        )

        params = {
            "INPUT": layer,
            "FIELD": field_name,
            "UNITS": 1,
            "WIDTH": float(cell_w),
            "HEIGHT": float(cell_h),
            "EXTENT": rect if rect is not None else layer.extent(),
            # NODATA only DECLARES the value on the band. Without INIT the grid
            # starts at 0, so every cell no polygon centre covered was a real
            # class 0 - absent from the mapping CSV and never masked.
            "NODATA": float(int(round(float(nodata)))),
            "INIT": float(int(round(float(nodata)))),
            # Categorical rasters should stay integer-coded for MaxEnt/ML workflows.
            "DATA_TYPE": 4,  # Int32
            "OUTPUT": out_path,
        }
        try:
            result = processing.run("gdal:rasterize", params)
        except Exception as e:
            log_message(f"gdal:rasterize 실패: {e}", level=Qgis.MessageLevel.Warning)
            raise

        raster_path = out_path
        try:
            if isinstance(result, dict) and result.get("OUTPUT"):
                raster_path = str(result.get("OUTPUT"))
        except Exception:
            raster_path = out_path

        # Verify output actually exists (some Processing failures don't raise).
        exists = False
        size = 0
        try:
            exists = os.path.exists(raster_path)
            size = os.path.getsize(raster_path) if exists else 0
        except Exception:
            exists = False
            size = 0

        log_message(
            f"KIGAM rasterize result: OUTPUT={raster_path} exists={exists} size={size}",
            level=Qgis.MessageLevel.Info if exists and size > 0 else Qgis.MessageLevel.Warning,
        )
        if exists and size > 0:
            return raster_path

        # Fallback: export memory layer to disk and retry (helps some GDAL/Processing edge cases).
        try:
            tmp_root = os.path.join(tempfile.gettempdir(), "ArchToolkit_KIGAM_Rasterize")
            os.makedirs(tmp_root, exist_ok=True)
            tmp_vec = os.path.join(tmp_root, f"atk_vec_{new_run_id('kigam')}.gpkg")
            save_res = processing.run("native:savefeatures", {"INPUT": layer, "OUTPUT": tmp_vec})
            vec_path = tmp_vec
            if isinstance(save_res, dict) and save_res.get("OUTPUT"):
                vec_path = str(save_res.get("OUTPUT"))

            params2 = dict(params)
            params2["INPUT"] = vec_path
            result2 = processing.run("gdal:rasterize", params2)
            raster_path2 = out_path
            if isinstance(result2, dict) and result2.get("OUTPUT"):
                raster_path2 = str(result2.get("OUTPUT"))

            exists2 = os.path.exists(raster_path2)
            size2 = os.path.getsize(raster_path2) if exists2 else 0
            log_message(
                f"KIGAM rasterize retry: INPUT={vec_path} OUTPUT={raster_path2} exists={exists2} size={size2}",
                level=Qgis.MessageLevel.Info if exists2 and size2 > 0 else Qgis.MessageLevel.Warning,
            )
            if exists2 and size2 > 0:
                try:
                    if os.path.exists(vec_path):
                        os.remove(vec_path)
                except Exception as _exc:
                    log_swallowed("geology_zip_dialog._rasterize_layer", _exc)
                return raster_path2
        except Exception as e:
            log_message(f"KIGAM rasterize 재시도 실패: {e}", level=Qgis.MessageLevel.Warning)

        # If we get here, we couldn't verify a raster file on disk.
        try:
            log_message(f"KIGAM rasterize raw result={result}", level=Qgis.MessageLevel.Warning)
        except Exception as _exc:
            log_swallowed("tools/geology_zip_dialog.py:1325 (_rasterize_layer)", _exc)
        raise RuntimeError("래스터 파일이 생성되지 않았습니다. 출력 경로/권한/로그를 확인하세요.")

    def _display_name(self, layer: QgsVectorLayer) -> str:
        """'[sheet] layer' as the layer list shows it (layer names repeat across sheets)."""
        region = self._kigam_region_for_layer(layer)
        name = str(layer.name() or "")
        return f"[{region}] {name}" if region else name

    def _warn_nodata_changed(self, requested: float, used: int, field: str) -> None:
        """Say that the requested NoData was a class code and was replaced."""
        text = (f"NoData 값 {requested:g}이(가) '{field}'의 클래스 코드와 같아 그 클래스가 NoData로 지워지므로, "
                f"코드 범위 밖의 값 {used}을(를) NoData로 사용합니다.")
        log_message(f"KIGAM rasterize: {text}", level=Qgis.MessageLevel.Warning)
        push_message(self.iface, "NoData 값 변경", text, level=1, duration=12)

    def _run_rasterize(self):
        layers = self._selected_vector_layers()
        if not layers:
            push_message(self.iface, "오류", "선택된 벡터 레이어가 없습니다.", level=2)
            restore_ui_focus(self)
            return

        chosen = self.cmbField.currentText().strip()
        explicit = bool(chosen) and chosen != "(자동 선택)"

        field = None
        if self.radMerge.isChecked():
            if explicit:
                # The user named a field: a layer that lacks it is left out
                # with a visible warning instead of the choice being replaced
                # by an auto-picked attribute without a word (GEO-09).
                lacking = [l0.name() for l0 in layers if l0.fields().indexOf(chosen) < 0]
                if lacking:
                    layers = [l0 for l0 in layers if l0.fields().indexOf(chosen) >= 0]
                    text = f"선택한 필드 '{chosen}'가 없는 레이어를 제외했습니다: {', '.join(lacking)}"
                    log_message(f"KIGAM rasterize: {text}", level=Qgis.MessageLevel.Warning)
                    push_message(self.iface, "필드 없는 레이어 제외", text, level=1, duration=10)
                if not layers:
                    push_message(self.iface, "오류", f"선택한 레이어 중 필드 '{chosen}'를 가진 레이어가 없습니다.", level=2)
                    restore_ui_focus(self)
                    return
            field = self._choose_common_field(layers)
            if not field:
                push_message(self.iface, "오류", "공통 필드를 찾을 수 없습니다. 필드를 직접 선택하세요.", level=2)
                restore_ui_focus(self)
                return

        fmt = self.cmbFormat.currentData() or "tif"
        pixel = float(self.spinPixel.value())
        nodata = float(self.spinNoData.value())
        run_id = new_run_id("kigam_raster")
        ensure_live_log_dialog(self.iface, owner=self, show=True, clear=True)

        try:
            if self.radMerge.isChecked():
                out_path = (self.txtOutFile.text() or "").strip()
                if not out_path:
                    push_message(self.iface, "오류", "출력 파일을 지정하세요.", level=2)
                    restore_ui_focus(self)
                    return
                out_path = _ensure_output_extension(out_path, fmt)

                # A sheet without a CRS cannot be placed next to the others:
                # transforming from a missing CRS silently keeps its raw
                # coordinates, which merged it far from where it belongs.
                no_crs = [self._display_name(l0) for l0 in layers if not l0.crs().isValid()]
                if no_crs:
                    text = (f"좌표계가 없는 레이어가 있어 병합하지 않습니다: {', '.join(no_crs)}. "
                            "레이어 속성에서 도엽의 CRS를 지정한 뒤 다시 실행하세요.")
                    log_message(f"KIGAM rasterize: {text}", level=Qgis.MessageLevel.Warning)
                    push_message(self.iface, "좌표계 없음", text, level=2, duration=12)
                    restore_ui_focus(self)
                    return

                numeric, num_names, text_names, double_names = self._field_numeric_across(layers, field)
                self._warn_field_types(field, num_names, text_names, double_names)
                shared_map, shared_labels, labels_all, conflicts = self._build_shared_code_mapping(layers, field, numeric=numeric)
                if conflicts:
                    txt = "; ".join(f"{c}: {' / '.join(ls)}" for c, ls in conflicts[:6])
                    log_message(f"KIGAM: 같은 코드가 도엽마다 다른 암상명을 가집니다 — {txt}", level=Qgis.MessageLevel.Warning)
                    push_message(self.iface, "지질도 코드 충돌",
                                 f"코드 {len(conflicts)}개가 도엽별로 다른 이름을 가집니다. mapping.csv의 labels_all 열을 확인하세요.",
                                 level=1, duration=10)
                merged_layer, mapping, labels, counts, drops = self._build_numeric_merge_layer(
                    layers, field, mapping=shared_map, labels=shared_labels, numeric=numeric)
                if merged_layer is None or not merged_layer.isValid():
                    raise RuntimeError("병합 레이어 생성에 실패했습니다.")
                drop_text = _format_drops(drops)
                if drop_text:
                    log_message(f"KIGAM rasterize: {drop_text}", level=Qgis.MessageLevel.Warning)
                if int(merged_layer.featureCount() or 0) <= 0:
                    raise RuntimeError("래스터에 기록할 피처가 없습니다." + (f" {drop_text}" if drop_text else ""))

                nd_used, nd_changed = _safe_nodata(nodata, mapping.values())
                if nd_changed:
                    self._warn_nodata_changed(nodata, nd_used, field)
                raster_path = self._rasterize_layer(merged_layer, "ATK_VAL", out_path, pixel, float(nd_used))
                cell_counts = self._raster_cell_counts(raster_path, float(nd_used))
                unburned = self._report_unburned_codes(mapping, labels, cell_counts, raster_path, feature_counts=counts)
                csv_path = self._write_mapping_csv(mapping, raster_path, labels=labels, counts=counts,
                                                   labels_all=labels_all, cell_counts=cell_counts)

                try:
                    r_name = os.path.splitext(os.path.basename(raster_path))[0].strip() or f"Geology_{run_id}"
                    if field:
                        r_name = f"{r_name} ({field})"
                except Exception:
                    r_name = f"Geology_{run_id}"

                rlayer = QgsRasterLayer(raster_path, r_name)
                if rlayer and rlayer.isValid():
                    QgsProject.instance().addMapLayer(rlayer, False)
                    try:
                        root = QgsProject.instance().layerTreeRoot()
                        parents = []
                        for lyr in layers:
                            node = root.findLayer(lyr.id())
                            if node is not None and node.parent() is not None:
                                parents.append(node.parent())
                        target = parents[0] if parents and all(p is parents[0] for p in parents) else root.findGroup(PARENT_GROUP_NAME) or root
                        target.insertLayer(0, rlayer)
                    except Exception:
                        QgsProject.instance().layerTreeRoot().insertLayer(0, rlayer)
                    set_archtoolkit_layer_metadata(
                        rlayer,
                        tool_id="kigam_raster",
                        run_id=run_id,
                        # Lithology codes are nominal. Saying so here is what
                        # makes align/export resample them with nearest instead
                        # of blending code 5 and code 12 into 8.5, and what
                        # keeps them out of the Pearson/VIF report. "geology_class"
                        # also becomes the exported variable name.
                        kind="geology_class",
                        units="class",
                        params={
                            "field": field,
                            "pixel": pixel,
                            "nodata": int(nd_used),
                            "nodata_requested": float(nodata),
                            "field_numeric": bool(numeric),
                            "double_truncated": bool(double_names),
                            "dropped": {k: int(v) for k, v in drops.items() if v},
                            "unburned_codes": len(unburned),
                            "mapping_csv": csv_path or "",
                        },
                    )
                if csv_path:
                    log_message(f"코드 매핑 저장: {csv_path}", level=Qgis.MessageLevel.Info)
                done = f"래스터 생성: {raster_path} (필드: {field})"
                if drop_text:
                    done += f" / {drop_text}"
                if unburned:
                    done += f" / 래스터에 없는 코드 {len(unburned)}개"
                if mapping and not csv_path:
                    done += " / 코드 매핑 CSV 없음"
                level = 1 if (drop_text or unburned or (mapping and not csv_path)) else 0
                push_message(self.iface, "완료", done, level=level, duration=10 if level else 7)
                return

            # Per-layer mode
            out_dir = (self.txtOutDir.text() or "").strip()
            if not out_dir or not os.path.isdir(out_dir):
                push_message(self.iface, "오류", "출력 폴더를 지정하세요.", level=2)
                restore_ui_focus(self)
                return

            # field -> ((mapping, labels, labels_all, conflicts), numeric, double_truncated)
            shared_by_field: Dict[str, tuple] = {}
            total_drops: Dict[str, int] = {}
            outputs: List[str] = []
            skipped: List[str] = []
            nodata_by_field: Dict[str, int] = {}

            for lyr in layers:
                if not lyr.crs().isValid():
                    # Refused here, per sheet, so the other sheets still run
                    # (the CRS-less raster used to abort the whole batch).
                    text = f"{self._display_name(lyr)}: 좌표계가 없어 건너뜁니다. 레이어 속성에서 CRS를 지정한 뒤 다시 실행하세요."
                    log_message(f"KIGAM rasterize: {text}", level=Qgis.MessageLevel.Warning)
                    push_message(self.iface, "좌표계 없음", text, level=1, duration=10)
                    skipped.append(str(lyr.name() or ""))
                    continue
                if explicit:
                    # The user named a field: a layer that lacks it is skipped
                    # with a visible warning, never silently re-pointed at
                    # another attribute (GEO-09).
                    if lyr.fields().indexOf(chosen) < 0:
                        text = f"{lyr.name()}: 선택한 필드 '{chosen}'가 없어 건너뜁니다."
                        log_message(f"KIGAM rasterize: {text}", level=Qgis.MessageLevel.Warning)
                        push_message(self.iface, "레이어 건너뜀", text, level=1, duration=8)
                        skipped.append(str(lyr.name() or ""))
                        continue
                    field = chosen
                else:
                    # Choose best field for this layer
                    field = None
                    for p in ["LITHOIDX", "AGEIDX", "LITHONAME", "TYPE", "ASGN_CODE", "SIGN", "CODE"]:
                        if lyr.fields().indexOf(p) >= 0:
                            field = p
                            break
                    if field is None:
                        field = lyr.fields()[0].name() if lyr.fields() else None
                        if field:
                            text = (f"{lyr.name()}: 우선 필드(LITHOIDX/AGEIDX 등)가 없어 첫 번째 속성 '{field}'를 "
                                    "값 필드로 사용합니다. 지질 코드가 아닐 수 있으니 확인하세요.")
                            log_message(f"KIGAM rasterize: {text}", level=Qgis.MessageLevel.Warning)
                            push_message(self.iface, "값 필드 자동 선택", text, level=1, duration=10)
                if not field:
                    log_message(f"{lyr.name()}: 필드 없음, 건너뜀", level=Qgis.MessageLevel.Warning)
                    skipped.append(str(lyr.name() or ""))
                    continue

                # Per-layer outputs still share one code table per field, so a
                # lithology carries the same integer in every sheet's raster.
                # The numeric/text decision is made once over every layer that
                # has the field so a sheet storing it as text does not get a
                # different code table from a sheet storing it as integer.
                if field not in shared_by_field:
                    same_field = [l0 for l0 in layers if l0.fields().indexOf(field) >= 0]
                    numeric, num_names, text_names, double_names = self._field_numeric_across(same_field, field)
                    self._warn_field_types(field, num_names, text_names, double_names)
                    shared_by_field[field] = (
                        self._build_shared_code_mapping(same_field, field, numeric=numeric),
                        bool(numeric),
                        bool(double_names),
                    )
                (shared_map, shared_labels, labels_all, _conf), numeric, double_trunc = shared_by_field[field]
                merged_layer, mapping, labels, counts, drops = self._build_numeric_merge_layer(
                    [lyr], field, mapping=shared_map, labels=shared_labels, numeric=numeric)
                for k, v in (drops or {}).items():
                    total_drops[k] = total_drops.get(k, 0) + int(v or 0)
                drop_text = _format_drops(drops)
                if drop_text:
                    log_message(f"KIGAM rasterize: {lyr.name()} - {drop_text}", level=Qgis.MessageLevel.Warning)
                if merged_layer is None or not merged_layer.isValid():
                    skipped.append(str(lyr.name() or ""))
                    continue
                if int(merged_layer.featureCount() or 0) <= 0:
                    text = f"{lyr.name()}: 래스터에 기록할 피처가 없어 건너뜁니다." + (f" {drop_text}" if drop_text else "")
                    log_message(f"KIGAM rasterize: {text}", level=Qgis.MessageLevel.Warning)
                    push_message(self.iface, "레이어 건너뜀", text, level=1, duration=10)
                    skipped.append(str(lyr.name() or ""))
                    continue

                # Layer names repeat across sheets (both ZIPs hold a 'Litho'),
                # so the file is named sheet + layer and never overwrites an
                # existing file (GEO-03).
                region = self._kigam_region_for_layer(lyr)
                base_name = _safe_name(f"{region}_{lyr.name()}" if region else lyr.name())
                out_path = os.path.join(out_dir, f"{base_name}.{fmt}")
                n = 1
                while os.path.exists(out_path):
                    n += 1
                    out_path = os.path.join(out_dir, f"{base_name}_{n}.{fmt}")
                if n > 1:
                    log_message(
                        f"KIGAM rasterize: {base_name}.{fmt}가 이미 있어 {os.path.basename(out_path)}로 저장합니다.",
                        level=Qgis.MessageLevel.Warning,
                    )
                # One NoData per field (so every sheet of the field agrees),
                # moved off the class codes when the requested value is one.
                if field not in nodata_by_field:
                    nd_used, nd_changed = _safe_nodata(nodata, set(shared_map.values()) | set(mapping.values()))
                    if nd_changed:
                        self._warn_nodata_changed(nodata, nd_used, field)
                    nodata_by_field[field] = nd_used
                nd_used = nodata_by_field[field]
                raster_path = self._rasterize_layer(merged_layer, "ATK_VAL", out_path, pixel, float(nd_used))
                cell_counts = self._raster_cell_counts(raster_path, float(nd_used))
                unburned = self._report_unburned_codes(mapping, labels, cell_counts, raster_path, feature_counts=counts)
                csv_path = self._write_mapping_csv(mapping, raster_path, labels=labels, counts=counts,
                                                   labels_all=labels_all, cell_counts=cell_counts)

                try:
                    r_base = os.path.splitext(os.path.basename(raster_path))[0].strip() or base_name
                except Exception as _exc:
                    log_swallowed("geology_zip_dialog._run_rasterize", _exc)
                    r_base = base_name
                rlayer = QgsRasterLayer(raster_path, f"{r_base}_raster ({field})")
                if rlayer and rlayer.isValid():
                    QgsProject.instance().addMapLayer(rlayer, False)
                    try:
                        root = QgsProject.instance().layerTreeRoot()
                        node = root.findLayer(lyr.id())
                        target = node.parent() if node is not None and node.parent() is not None else root.findGroup(PARENT_GROUP_NAME) or root
                        target.insertLayer(0, rlayer)
                    except Exception:
                        QgsProject.instance().layerTreeRoot().insertLayer(0, rlayer)
                    set_archtoolkit_layer_metadata(
                        rlayer,
                        tool_id="kigam_raster",
                        run_id=run_id,
                        # Lithology codes are nominal. Saying so here is what
                        # makes align/export resample them with nearest instead
                        # of blending code 5 and code 12 into 8.5, and what
                        # keeps them out of the Pearson/VIF report. "geology_class"
                        # also becomes the exported variable name.
                        kind="geology_class",
                        units="class",
                        params={
                            "field": field,
                            "pixel": pixel,
                            "nodata": int(nd_used),
                            "nodata_requested": float(nodata),
                            "region": region,
                            "source_layer": str(lyr.name() or ""),
                            "field_numeric": bool(numeric),
                            "double_truncated": bool(double_trunc),
                            "dropped": {k: int(v) for k, v in (drops or {}).items() if v},
                            "unburned_codes": len(unburned),
                            "mapping_csv": csv_path or "",
                        },
                    )
                if csv_path:
                    log_message(f"코드 매핑 저장: {csv_path}", level=Qgis.MessageLevel.Info)
                outputs.append(f"{os.path.basename(raster_path)} [{field}]" + ("" if csv_path or not mapping else " (매핑 CSV 없음)"))

            n_out = len(outputs)
            done = f"레이어별 래스터 {n_out}개 생성"
            if outputs:
                done += ": " + ", ".join(outputs[:6]) + (f" 외 {n_out - 6}개" if n_out > 6 else "")
            if skipped:
                done += f" / 건너뜀 {len(skipped)}개({', '.join(skipped[:6])}" + (f" 외 {len(skipped) - 6}개" if len(skipped) > 6 else "") + ")"
            total_text = _format_drops(total_drops)
            if total_text:
                done += f" / {total_text}"
            if n_out == 0:
                push_message(self.iface, "오류", done + " - 생성된 래스터가 없습니다. 로그를 확인하세요.", level=2, duration=10)
                return
            level = 1 if (skipped or total_text) else 0
            push_message(self.iface, "완료", done, level=level, duration=10 if level else 7)
        except Exception as e:
            log_message(f"래스터 변환 실패: {e}", level=Qgis.MessageLevel.Warning)
            push_message(self.iface, "오류", f"래스터 변환 실패: {e}", level=2)

    def _load_zip(self):
        zip_path = (self.txtZip.text() or "").strip()
        if not zip_path:
            push_message(self.iface, "오류", "ZIP 파일을 선택해주세요.", level=2)
            restore_ui_focus(self)
            return
        if not os.path.exists(zip_path):
            push_message(self.iface, "오류", "선택한 ZIP 파일이 존재하지 않습니다.", level=2)
            restore_ui_focus(self)
            return

        ensure_live_log_dialog(self.iface, owner=self, show=True, clear=True)
        run_id = new_run_id("kigam_zip")
        processor = KigamZipProcessor(iface=self.iface)
        layers = processor.process_zip(
            zip_path,
            font_family=self.cmbFont.currentFont().family(),
            font_size=int(self.spinFontSize.value()),
            apply_style=bool(self.chkApplyStyle.isChecked()),
            apply_labels=bool(self.chkApplyLabels.isChecked()),
            run_id=run_id,
        )
        if layers:
            try:
                frame_layer = next((lyr for lyr in layers if "frame" in lyr.name().lower()), None)
                target = frame_layer or layers[0]
                if target and target.isValid():
                    canvas = self.iface.mapCanvas()
                    canvas.setExtent(target.extent())
                    canvas.refresh()
            except Exception as _exc:
                log_swallowed("geology_zip_dialog._load_zip", _exc)
            # Say where the shapefiles went and how long they are kept: the
            # loaded layers look like ordinary file layers, but they live in a
            # managed folder that the next ZIP load reaps after the retention
            # window if nothing touched it (GEO-13).
            done = f"ZIP에서 {len(layers)}개 레이어를 로드했습니다."
            try:
                n_rep = int(getattr(processor, "last_replaced", 0) or 0)
                if n_rep:
                    done += f" 같은 도엽 그룹의 이전 ZIP 레이어 {n_rep}개는 새로 불러온 레이어로 교체했습니다(그룹의 래스터 결과는 유지)."
            except Exception as _exc:
                log_swallowed("geology_zip_dialog._load_zip (replaced)", _exc)
            try:
                extract_dir = str(getattr(processor, "last_extract_dir", "") or "")
                days = max(1, int(GEOLOGY_EXTRACT_CLEANUP_DAYS))
                if extract_dir:
                    done += (f" SHP는 {extract_dir}에 풀렸습니다. 이 폴더는 {days}일 동안 다시 불러오지 않으면 "
                             "다음 ZIP 로드 때 자동 삭제되며(현재 열린 프로젝트가 쓰는 폴더만 보호), "
                             "그러면 이 도엽을 참조하는 저장된 프로젝트의 레이어가 깨집니다. 오래 쓸 도엽은 다른 폴더로 복사해 두세요.")
            except Exception as _exc:
                log_swallowed("geology_zip_dialog._load_zip", _exc)
            push_message(self.iface, "완료", done, level=0, duration=15)
        else:
            push_message(self.iface, "경고", "로드된 레이어가 없습니다. 로그를 확인하세요.", level=1)

        self.refresh_layer_list()

    def _on_help(self):
        try:
            extract_root = KigamZipProcessor.default_extract_root() or "(QGIS 프로필 폴더를 찾지 못하면 임시 폴더)"
        except Exception as _exc:
            log_swallowed("geology_zip_dialog._on_help", _exc)
            extract_root = "(QGIS 프로필)/ArchToolkit/" + (GEOLOGY_EXTRACT_ROOT_NAME or "ArchToolkit_KIGAM_Extract")
        cleanup_days = max(1, int(GEOLOGY_EXTRACT_CLEANUP_DAYS))
        html = f"""
<h3>지질도 ZIP 불러오기 / MaxEnt 래스터 변환</h3>
<p>
KIGAM 1:50,000 지질도 ZIP(도엽)을 바로 로드하고, 지질 코드 기반으로 래스터를 생성합니다.
지구화학도 수치 래스터와 함께 MaxEnt 같은 예측 모델링 입력으로 사용할 수 있습니다.
</p>

<h4>ZIP 불러오기</h4>
<ul>
  <li>KIGAM에서 받은 ZIP을 선택하면 SHP를 자동 로드하고, sym 폴더가 있으면 심볼을 적용합니다.</li>
  <li><b>속성 인코딩</b>: SHP 옆에 <code>.cpg</code>가 있으면 그 인코딩을 따르고, 없으면 DBF 문자열을 CP949/EUC-KR/UTF-8로 풀어 보고
      맞는 인코딩을 씁니다(설정 <code>geology_zip.candidate_encodings</code>). ZIP 안의 한글 파일/폴더 이름(CP949)도 그대로 풀립니다.</li>
  <li><b>좌표계</b>: .prj가 없어 좌표계를 읽지 못한 도엽은 메시지 표시줄에 경고가 뜹니다. 그런 도엽은 CRS를 지정하기 전까지 래스터 변환(병합)에 쓰이지 않습니다.</li>
  <li><b>다시 불러오기</b>: 같은 ZIP 파일(같은 경로)을 다시 불러오면 기존 <code>KIGAM_도엽명</code> 그룹의 도엽 레이어를 새로 불러온 레이어로
      <b>교체</b>합니다(그룹 안의 래스터 결과는 그대로 둡니다). 이름만 같은 다른 ZIP은 <code>KIGAM_도엽명_2</code> 그룹으로 따로 불러옵니다.</li>
  <li>LITHOIDX/LITHONAME 레이어는 라벨을 자동 적용할 수 있습니다.</li>
  <li>레이어는 <code>ArchToolkit - Geology</code> 그룹 아래 <code>KIGAM_도엽명</code>으로 정리되고, 라인/포인트가 폴리곤(Litho) 위로 올라오도록 순서를 맞춥니다.</li>
  <li><b>추출 폴더와 보관 기간</b>: SHP는 <code>{extract_root}</code> 아래 도엽별 폴더에 풀립니다.
      불러올 때마다 새 폴더(이미 있으면 <code>_2</code>, <code>_3</code>…)에 풀며, 이미 불러온 도엽의 파일은 지우지 않습니다.
      이 폴더는 <b>{cleanup_days}일</b> 동안 그 도엽을 다시 불러오지 않으면 다음 ZIP 로드 때 자동 삭제됩니다
      (현재 열려 있는 프로젝트가 쓰는 폴더만 보호되며, 닫혀 있는 다른 프로젝트가 참조하는 폴더는 보호되지 않습니다).
      삭제되면 그 도엽을 참조하는 저장된 프로젝트의 레이어가 깨지므로, 오래 쓸 도엽은 다른 폴더로 복사해 두세요.</li>
</ul>

<h4>벡터 → 래스터</h4>
<ul>
  <li><b>기본 목록</b>: 보통 Litho(암상/지층) 폴리곤만 있으면 충분하므로, 기본은 <b>KIGAM ZIP 레이어 + Litho(폴리곤)</b>만 표시합니다.</li>
  <li>레이어 이름 앞에 <code>[GF13_청주]</code>처럼 <b>도엽/지역</b> 정보가 함께 표시됩니다(여러 도엽을 불러온 경우 구분용).</li>
  <li>값 필드는 보통 <code>LITHOIDX</code>/<code>AGEIDX</code>를 사용합니다.</li>
  <li>문자 코드(예: Qa, Jbgr)일 경우 자동으로 정수 코드로 매핑하며, <code>*_mapping.csv</code>를 함께 저장합니다.</li>
  <li>숫자 코드(예: <code>LITHOIDX</code>)를 선택해도 가능한 경우 <code>LITHONAME</code>/<code>AGENAME</code>을 함께 매핑 CSV에 기록합니다.</li>
  <li>단일 래스터(병합) 또는 레이어별 출력 중 선택할 수 있습니다. 레이어별 출력의 파일 이름은
      <code>도엽_레이어</code>(예: <code>GF13_청주_Litho.tif</code>)이며, 같은 이름의 파일이 있으면 덮어쓰지 않고
      <code>_2</code>, <code>_3</code>을 붙입니다.</li>
  <li>래스터는 <b>셀 중심이 폴리곤 안에 들어가는 셀</b>에만 코드를 기록합니다. 폭이 한 셀보다 좁은 지질 단위(얇은 암맥 등)는
      그 픽셀 크기에서는 래스터에 기록되지 않으며, 매핑 CSV의 <code>cell_count</code> 열이 0인 코드가 그런 경우입니다.
      픽셀 크기를 줄이면 포함됩니다.</li>
  <li>값이 비어 있거나(NULL) 숫자 필드에 숫자가 아닌 값이 든 피처, 좌표 변환에 실패한 피처는 래스터에서 빠지며, 완료 메시지와 로그에 제외된 피처 수가 이유별로 표시됩니다.
      NULL/공백은 코드로 매핑되지 않고(“NULL”이라는 클래스를 만들지 않음) '값 없음'으로 셉니다.</li>
  <li>레이어별 출력의 <code>cell_count</code> 경고(셀보다 좁은 단위)는 그 도엽에 실제로 있는 코드만 대상으로 합니다. 공용 코드표의 다른 도엽 코드는 feature_count 0으로만 기록됩니다.</li>
  <li>NoData 값이 클래스 코드와 같으면 그 클래스가 통째로 NoData가 되므로, 코드 범위 밖의 값(보통 -9999, 겹치면 가장 작은 코드보다 작은 값)으로 바꾸고 메시지와 메타데이터(<code>nodata</code>)에 남깁니다.</li>
  <li>좌표계가 없는 도엽이 섞여 있으면 병합하지 않고 중단합니다(레이어별 출력에서는 그 도엽만 건너뜀).</li>
  <li>ASCII Grid(.asc)는 지리좌표계(도) 레이어에서는 셀 크기가 도 단위(dx/dy)로 기록되어 ArcGIS·MaxEnt가 읽지 못할 수 있습니다. 투영 CRS(미터)로 변환한 뒤 내보내세요.</li>
  <li>실행 후에는 <b>출력 파일이 실제로 생성되었는지</b> 확인하고, 문제가 있으면 로그에 원인을 남깁니다. 매핑 CSV를 쓰지 못하면 메시지 표시줄에 경고가 뜹니다(CSV 없이는 래스터의 정수 코드를 해석할 수 없습니다).</li>
</ul>

<h4>예측모델링 팁</h4>
<ul>
  <li>지질 단위(지층/암상)는 보통 <b>범주형(categorical)</b> 변수입니다. 래스터는 숫자로 저장되며, 매핑 CSV로 해석합니다.</li>
  <li>MaxEnt를 쓴다면 해당 변수를 범주형으로 지정하는 방식을 권장합니다(연속형 숫자로 해석되면 왜곡될 수 있음).</li>
  <li>다중 변수(예: 지질+지구화학+지형)로 모델을 만들 때는 모든 래스터의 <b>좌표계/해상도/Extent</b>를 맞추는 것이 중요합니다.</li>
</ul>

<h4>문제 해결</h4>
<ul>
  <li>CSV는 나오는데 래스터가 없으면: 출력 폴더 권한/경로(특수문자/보안 설정)를 확인하고, 다른 폴더(예: Downloads)로 다시 저장해보세요.</li>
  <li>원인 파악: ArchToolkit 실시간 로그/로그 파일에서 <code>KIGAM rasterize result</code> 줄을 확인하세요.</li>
</ul>
"""
        try:
            plugin_dir = os.path.dirname(os.path.dirname(__file__))
            show_help_dialog(parent=self, title="지질도 ZIP/MaxEnt 도움말", html=html, plugin_dir=plugin_dir, tool_id="geology_zip")
        except Exception as _exc:
            log_swallowed("tools/geology_zip_dialog.py:1544 (_on_help)", _exc)
