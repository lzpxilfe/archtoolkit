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
import unicodedata
from typing import Dict, List, Optional, Tuple

import processing
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtGui import QColor, QFont, QIcon
from qgis.PyQt.QtXml import QDomDocument
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
    QgsUnitTypes,
    QgsRasterLayer,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
    QgsWkbTypes,
)

from .config import get_output_group_name, get_plugin_config_value
from .help_dialog import show_help_dialog
from .i18n import apply_language, is_english_ui
from .live_log_dialog import ensure_live_log_dialog
from .utils import (
    log_message,
    push_message,
    restore_ui_focus,
    set_archtoolkit_layer_metadata,
    new_run_id,
)


PARENT_GROUP_NAME = get_output_group_name("geology", "ArchToolkit - Geology")
GEOLOGY_EXTRACT_ROOT_NAME = str(
    get_plugin_config_value("geology_zip", "extract_root_name", default="ArchToolkit_KIGAM_Extract") or ""
).strip() or "ArchToolkit_KIGAM_Extract"
GEOLOGY_EXTRACT_CLEANUP_DAYS = int(
    get_plugin_config_value("geology_zip", "extract_cleanup_days", default=14) or 14
)
GEOLOGY_PROVIDER_ENCODING = str(
    get_plugin_config_value("geology_zip", "provider_encoding", default="cp949") or ""
).strip() or "cp949"
GEOLOGY_CANDIDATE_ENCODINGS = [
    (None if value is None else str(value).strip())
    for value in (get_plugin_config_value("geology_zip", "candidate_encodings", default=["CP949", "EUC-KR", None, "UTF-8"]) or [])
    if value is None or str(value).strip()
]
GEOLOGY_ENCODING_PREFERENCE = get_plugin_config_value(
    "geology_zip",
    "encoding_preference",
    default={"CP949": 4, "EUC-KR": 3, "default": 2, "UTF-8": 1},
) or {"CP949": 4, "EUC-KR": 3, "default": 2, "UTF-8": 1}
GEOLOGY_QML_WRITE_ENCODING = str(
    get_plugin_config_value("geology_zip", "qml_write_encoding", default="UTF-8") or ""
).strip() or "UTF-8"
GEOLOGY_POINT_MARKER_SIZE = float(
    get_plugin_config_value("geology_zip", "symbology", "point_marker_size", default=6.0) or 6.0
)
GEOLOGY_FILL_SYMBOL_WIDTH = float(
    get_plugin_config_value("geology_zip", "symbology", "polygon_fill_width", default=10.0) or 10.0
)
GEOLOGY_SYMBOL_PRIORITY_FIELDS = [
    str(v).strip()
    for v in (
        get_plugin_config_value(
            "geology_zip",
            "symbology",
            "symbol_priority_fields",
            default=["LITHOIDX", "TYPE", "ASGN_CODE", "SIGN", "CODE", "AGEIDX"],
        )
        or []
    )
    if str(v or "").strip()
]
GEOLOGY_LABEL_FIELD_CANDIDATES = [
    str(v).strip()
    for v in (
        get_plugin_config_value(
            "geology_zip",
            "symbology",
            "label_field_candidates",
            default=["LITHOIDX", "LITHONAME"],
        )
        or []
    )
    if str(v or "").strip()
]
GEOLOGY_FRAME_LAYER_KEYWORDS = [
    str(v).strip().lower()
    for v in (
        get_plugin_config_value(
            "geology_zip",
            "symbology",
            "frame_layer_keywords",
            default=["frame"],
        )
        or []
    )
    if str(v or "").strip()
]
GEOLOGY_REFERENCE_HIDE_KEYWORDS = [
    str(v).strip().lower()
    for v in (
        get_plugin_config_value(
            "geology_zip",
            "symbology",
            "reference_hide_keywords",
            default=["frame", "crosssection"],
        )
        or []
    )
    if str(v or "").strip()
]
GEOLOGY_LITHO_LAYER_KEYWORD = str(
    get_plugin_config_value("geology_zip", "symbology", "litho_layer_keyword", default="litho") or ""
).strip().lower()
GEOLOGY_RASTER_FIELD_PRIORITY = [
    str(v).strip()
    for v in (
        get_plugin_config_value(
            "geology_zip",
            "raster",
            "field_priority",
            default=["LITHOIDX", "AGEIDX", "LITHONAME", "TYPE", "ASGN_CODE", "SIGN", "CODE"],
        )
        or []
    )
    if str(v or "").strip()
]
GEOLOGY_NAME_FIELD_CANDIDATES = [
    str(v).strip()
    for v in (
        get_plugin_config_value(
            "geology_zip",
            "raster",
            "name_field_candidates",
            default=["LITHONAME", "AGENAME", "NAME", "KOR_NAME", "ENG_NAME"],
        )
        or []
    )
    if str(v or "").strip()
]
GEOLOGY_UI_FONT_SIZE_MIN = int(get_plugin_config_value("geology_zip", "ui", "font_size_min", default=5) or 5)
GEOLOGY_UI_FONT_SIZE_MAX = int(get_plugin_config_value("geology_zip", "ui", "font_size_max", default=50) or 50)
GEOLOGY_UI_FONT_SIZE_DEFAULT = int(
    get_plugin_config_value("geology_zip", "ui", "font_size_default", default=10) or 10
)
GEOLOGY_UI_PIXEL_MIN = float(get_plugin_config_value("geology_zip", "ui", "pixel_size_min", default=0.1) or 0.1)
GEOLOGY_UI_PIXEL_MAX = float(
    get_plugin_config_value("geology_zip", "ui", "pixel_size_max", default=10000.0) or 10000.0
)
GEOLOGY_UI_PIXEL_DEFAULT = float(
    get_plugin_config_value("geology_zip", "ui", "pixel_size_default", default=10.0) or 10.0
)
GEOLOGY_UI_NODATA_MIN = float(
    get_plugin_config_value("geology_zip", "ui", "nodata_min", default=-9999999.0) or -9999999.0
)
GEOLOGY_UI_NODATA_MAX = float(
    get_plugin_config_value("geology_zip", "ui", "nodata_max", default=9999999.0) or 9999999.0
)
GEOLOGY_UI_NODATA_DECIMALS = int(
    get_plugin_config_value("geology_zip", "ui", "nodata_decimals", default=2) or 2
)
GEOLOGY_UI_NODATA_DEFAULT = float(
    get_plugin_config_value("geology_zip", "ui", "nodata_default", default=-9999.0) or -9999.0
)


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
    m_per_deg_lat = (
        111132.92
        - 559.82 * math.cos(2 * r)
        + 1.175 * math.cos(4 * r)
        - 0.0023 * math.cos(6 * r)
    )
    m_per_deg_lon = (
        111412.84 * math.cos(r)
        - 93.5 * math.cos(3 * r)
        + 0.118 * math.cos(5 * r)
    )
    if m_per_deg_lat <= 0 or m_per_deg_lon <= 0:
        return 0.0, 0.0
    return (m / m_per_deg_lon), (m / m_per_deg_lat)


class KigamZipProcessor:
    def __init__(self):
        self.extract_root = os.path.join(tempfile.gettempdir(), GEOLOGY_EXTRACT_ROOT_NAME)
        try:
            os.makedirs(self.extract_root, exist_ok=True)
        except Exception:
            pass
        self._cleanup_stale_extract_dirs()

    def _cleanup_stale_extract_dirs(self) -> None:
        if GEOLOGY_EXTRACT_CLEANUP_DAYS <= 0:
            return
        try:
            cutoff_ts = time.time() - (float(GEOLOGY_EXTRACT_CLEANUP_DAYS) * 86400.0)
            with os.scandir(self.extract_root) as entries:
                for entry in entries:
                    if not entry.is_dir():
                        continue
                    try:
                        if entry.stat().st_mtime >= cutoff_ts:
                            continue
                    except Exception:
                        continue
                    try:
                        shutil.rmtree(entry.path)
                    except Exception:
                        continue
        except Exception:
            pass

    def _build_extract_dir(self, zip_path: str, run_id: str) -> str:
        zip_basename = _safe_name(os.path.splitext(os.path.basename(zip_path))[0])
        run_token = _safe_name(run_id) or new_run_id("kigam")
        return os.path.join(self.extract_root, f"{zip_basename}_{run_token}")

    def _normalize_token(self, text: str) -> str:
        value = str(text or "").strip()
        if not value:
            return ""
        value = unicodedata.normalize("NFKC", value).upper()
        return re.sub(r"[\s_\-]+", "", value)

    def _redecode_variants(self, text: str) -> List[str]:
        value = str(text or "")
        variants: List[str] = []
        seen = set()

        def _append(candidate: str) -> None:
            item = str(candidate or "")
            if item in seen:
                return
            seen.add(item)
            variants.append(item)

        _append(value)
        for src_enc in ("latin1", "cp1252"):
            for dst_enc in ("cp949", "euc-kr"):
                try:
                    _append(value.encode(src_enc).decode(dst_enc))
                except Exception:
                    continue
        return variants

    def _value_candidates(self, value) -> List[str]:
        out: List[str] = []
        seen = set()
        for variant in self._redecode_variants(str(value or "")):
            text = str(variant or "").strip()
            if text and text not in seen:
                seen.add(text)
                out.append(text)
            normalized = self._normalize_token(text)
            if normalized and normalized not in seen:
                seen.add(normalized)
                out.append(normalized)
        return out

    def _build_symbol_index(self, sym_path: Optional[str]) -> Tuple[Dict[str, str], Dict[str, str]]:
        raw_sym_files: Dict[str, str] = {}
        lookup_sym_files: Dict[str, str] = {}
        if not sym_path or not os.path.isdir(sym_path):
            return raw_sym_files, lookup_sym_files

        for fname in os.listdir(sym_path):
            if not fname.lower().endswith(".png"):
                continue
            key = os.path.splitext(fname)[0]
            path = os.path.join(sym_path, fname)
            raw_sym_files.setdefault(key, path)
            for candidate in self._value_candidates(key):
                lookup_sym_files.setdefault(candidate, path)
        return raw_sym_files, lookup_sym_files

    def _resolve_symbol_path(
        self,
        value,
        raw_sym_files: Dict[str, str],
        lookup_sym_files: Dict[str, str],
    ) -> Optional[str]:
        for candidate in self._value_candidates(value):
            path = lookup_sym_files.get(candidate)
            if path:
                return path
        return None

    def _find_sidecar_qml(self, folder_path: str, layer_name: str) -> Optional[str]:
        direct = os.path.join(folder_path, f"{layer_name}.qml")
        if os.path.exists(direct):
            return direct
        try:
            wanted = layer_name.lower()
            for fname in os.listdir(folder_path):
                if not fname.lower().endswith(".qml"):
                    continue
                if os.path.splitext(fname)[0].lower() == wanted:
                    return os.path.join(folder_path, fname)
        except Exception:
            return None
        return None

    def _load_qml_dom(self, qml_path: Optional[str]) -> Optional[QDomDocument]:
        if not qml_path or not os.path.exists(qml_path):
            return None
        try:
            with open(qml_path, "rb") as fh:
                raw = fh.read()
        except Exception:
            return None

        doc = QDomDocument()
        try:
            result = doc.setContent(raw)
        except Exception:
            return None

        ok = bool(result[0]) if isinstance(result, tuple) else bool(result)
        if not ok:
            return None
        return doc

    def _iter_dom_children(self, node, tag_name: Optional[str] = None):
        if node is None:
            return
        try:
            child = node.firstChildElement()
        except Exception:
            return
        while not child.isNull():
            try:
                if tag_name is None or child.tagName() == tag_name:
                    yield child
            except Exception:
                pass
            try:
                child = child.nextSiblingElement()
            except Exception:
                break

    def _iter_dom_descendants(self, node, tag_name: Optional[str] = None):
        for child in self._iter_dom_children(node):
            try:
                if tag_name is None or child.tagName() == tag_name:
                    yield child
            except Exception:
                pass
            for grandchild in self._iter_dom_descendants(child, tag_name):
                yield grandchild

    def _parse_qml_mapping(
        self,
        qml_path: Optional[str],
    ) -> Tuple[Optional[str], Dict[str, str], Dict[str, str]]:
        if not qml_path or not os.path.exists(qml_path):
            return None, {}, {}

        qml_field = None
        qml_value_to_image: Dict[str, str] = {}
        qml_lookup_map: Dict[str, str] = {}
        doc = self._load_qml_dom(qml_path)
        if doc is None:
            return None, {}, {}
        try:
            root = doc.documentElement()
        except Exception:
            return None, {}, {}
        if root is None or root.isNull():
            return None, {}, {}

        renderer = next(self._iter_dom_descendants(root, "renderer-v2"), None)
        if renderer is not None:
            try:
                qml_field = (renderer.attribute("attr") or renderer.attribute("classAttribute") or "").strip() or None
            except Exception:
                qml_field = None

        symbol_images: Dict[str, str] = {}
        if renderer is not None:
            for symbols_node in self._iter_dom_children(renderer, "symbols"):
                for symbol_node in self._iter_dom_children(symbols_node, "symbol"):
                    try:
                        symbol_name = str(symbol_node.attribute("name") or "").strip()
                    except Exception:
                        symbol_name = ""
                    image_ref = ""
                    for prop in self._iter_dom_descendants(symbol_node, "prop"):
                        try:
                            value = str(prop.attribute("v") or "").strip()
                        except Exception:
                            value = ""
                        if value.lower().endswith(".png"):
                            image_ref = value
                            break
                    if symbol_name and image_ref:
                        symbol_images[symbol_name] = image_ref

            for categories_node in self._iter_dom_children(renderer, "categories"):
                for category_node in self._iter_dom_children(categories_node, "category"):
                    try:
                        value = str(category_node.attribute("value") or "").strip()
                    except Exception:
                        value = ""
                    try:
                        symbol_ref = str(category_node.attribute("symbol") or "").strip()
                    except Exception:
                        symbol_ref = ""
                    image_ref = symbol_images.get(symbol_ref) or symbol_images.get(value)
                    if not value or not image_ref:
                        continue
                    qml_value_to_image[value] = image_ref
                    for candidate in self._value_candidates(value):
                        qml_lookup_map.setdefault(candidate, image_ref)

        return qml_field, qml_value_to_image, qml_lookup_map

    def _resolve_symbol_with_qml_map(
        self,
        value,
        raw_sym_files: Dict[str, str],
        lookup_sym_files: Dict[str, str],
        qml_lookup_map: Dict[str, str],
    ) -> Optional[str]:
        for candidate in self._value_candidates(value):
            image_ref = qml_lookup_map.get(candidate)
            if not image_ref:
                continue
            qml_symbol_name = os.path.splitext(os.path.basename(image_ref))[0]
            path = self._resolve_symbol_path(qml_symbol_name, raw_sym_files, lookup_sym_files)
            if path:
                return path
            if os.path.exists(image_ref):
                return image_ref
        return self._resolve_symbol_path(value, raw_sym_files, lookup_sym_files)

    def _find_best_matching_field(
        self,
        layer: QgsVectorLayer,
        raw_sym_files: Dict[str, str],
        lookup_sym_files: Dict[str, str],
        qml_field: Optional[str],
        qml_lookup_map: Dict[str, str],
    ) -> Tuple[Optional[str], int, int]:
        best_field = None
        best_matches = -1
        best_total_values = -1
        all_fields = [f.name() for f in layer.fields()]

        ordered_fields: List[str] = []
        for field_name in ([qml_field] if qml_field else []) + GEOLOGY_SYMBOL_PRIORITY_FIELDS + all_fields:
            if field_name and field_name in all_fields and field_name not in ordered_fields:
                ordered_fields.append(field_name)

        for field_name in ordered_fields:
            idx = layer.fields().indexOf(field_name)
            if idx < 0:
                continue
            try:
                unique_values = list(layer.uniqueValues(idx))
            except Exception:
                unique_values = []

            matches = 0
            total_values = len(unique_values)
            for value in unique_values:
                if self._resolve_symbol_with_qml_map(value, raw_sym_files, lookup_sym_files, qml_lookup_map):
                    matches += 1

            score = (matches, total_values)
            if score > (best_matches, best_total_values):
                best_field = field_name
                best_matches = matches
                best_total_values = total_values

        return best_field, max(best_matches, 0), max(best_total_values, 0)

    def _encoding_preference_rank(self, encoding: Optional[str]) -> int:
        pref_map = {}
        if isinstance(GEOLOGY_ENCODING_PREFERENCE, dict):
            for key, value in GEOLOGY_ENCODING_PREFERENCE.items():
                try:
                    pref_map[str(key or "").strip().upper()] = int(value)
                except Exception:
                    continue
        key = str(encoding or "").strip().upper() or "DEFAULT"
        return pref_map.get(key, pref_map.get("DEFAULT", 0))

    def _load_layer_with_best_encoding(
        self,
        shp_path: str,
        layer_name: str,
        *,
        sym_path: Optional[str],
        qml_path: Optional[str],
    ) -> Tuple[Optional[QgsVectorLayer], Optional[str], Optional[str], int]:
        raw_sym_files, lookup_sym_files = self._build_symbol_index(sym_path)
        qml_field, _, qml_lookup_map = self._parse_qml_mapping(qml_path)

        encodings = GEOLOGY_CANDIDATE_ENCODINGS or [GEOLOGY_PROVIDER_ENCODING]
        seen = set()
        best_layer = None
        best_encoding = None
        best_field = None
        best_matches = -1
        best_total_values = -1
        best_pref = -1

        for encoding in encodings:
            enc_key = str(encoding or "__default__").upper()
            if enc_key in seen:
                continue
            seen.add(enc_key)

            uri = shp_path if not encoding else f"{shp_path}|encoding={encoding}"
            layer = QgsVectorLayer(uri, layer_name, "ogr")
            if not layer.isValid():
                continue
            if encoding:
                try:
                    layer.setProviderEncoding(str(encoding))
                except Exception:
                    pass

            field_name, matches, total_values = self._find_best_matching_field(
                layer,
                raw_sym_files,
                lookup_sym_files,
                qml_field,
                qml_lookup_map,
            )
            pref_rank = self._encoding_preference_rank(encoding)
            score = (matches, pref_rank, total_values)
            if score > (best_matches, best_pref, best_total_values):
                best_layer = layer
                best_encoding = str(encoding).strip() if encoding else None
                best_field = field_name
                best_matches = matches
                best_total_values = total_values
                best_pref = pref_rank

        return best_layer, best_encoding, best_field, max(best_matches, 0)

    def _build_relinked_qml(
        self,
        qml_path: Optional[str],
        raw_sym_files: Dict[str, str],
        lookup_sym_files: Dict[str, str],
    ) -> Tuple[Optional[str], int, int]:
        if not qml_path or not os.path.exists(qml_path):
            return None, 0, 0

        doc = self._load_qml_dom(qml_path)
        if doc is None:
            return None, 0, 0
        try:
            root = doc.documentElement()
        except Exception:
            return None, 0, 0
        if root is None or root.isNull():
            return None, 0, 0

        relinked = 0
        total_images = 0
        for prop in self._iter_dom_descendants(root, "prop"):
            try:
                value = str(prop.attribute("v") or "").strip()
            except Exception:
                value = ""
            if not value.lower().endswith(".png"):
                continue
            total_images += 1
            symbol_name = os.path.splitext(os.path.basename(value))[0]
            resolved = self._resolve_symbol_path(symbol_name, raw_sym_files, lookup_sym_files)
            if not resolved:
                continue
            try:
                prop.setAttribute("v", resolved)
            except Exception:
                continue
            relinked += 1

        if relinked <= 0:
            return None, 0, total_images

        out_path = os.path.join(
            os.path.dirname(qml_path),
            f"{os.path.splitext(os.path.basename(qml_path))[0]}_archtoolkit.qml",
        )
        try:
            xml_text = doc.toString(2)
            if not str(xml_text or "").lstrip().startswith("<?xml"):
                xml_text = f'<?xml version="1.0" encoding="{GEOLOGY_QML_WRITE_ENCODING}"?>\n{xml_text}'
            with open(out_path, "w", encoding=GEOLOGY_QML_WRITE_ENCODING, newline="\n") as fh:
                fh.write(xml_text)
        except Exception:
            return None, 0, total_images
        return out_path, relinked, total_images

    def _load_named_style(self, layer: QgsVectorLayer, style_path: str) -> bool:
        try:
            result = layer.loadNamedStyle(style_path)
        except Exception:
            return False

        ok = False
        if isinstance(result, tuple):
            ok = bool(result[1]) if len(result) > 1 else bool(result[0])
        else:
            ok = bool(result)
        if ok:
            layer.triggerRepaint()
        return ok

    def apply_qml_style(self, layer: QgsVectorLayer, qml_path: Optional[str], sym_path: Optional[str]) -> bool:
        if not qml_path or not os.path.exists(qml_path):
            return False

        raw_sym_files, lookup_sym_files = self._build_symbol_index(sym_path)
        style_path, relinked_count, total_images = self._build_relinked_qml(
            qml_path,
            raw_sym_files,
            lookup_sym_files,
        )
        target_style = style_path or qml_path
        ok = self._load_named_style(layer, target_style)
        if not ok:
            return False

        if style_path:
            log_message(
                f"KIGAM QML 스타일 적용: {layer.name()} ({relinked_count}/{total_images} symbols relinked)",
                level=Qgis.Info,
            )
        else:
            log_message(f"KIGAM QML 스타일 적용: {layer.name()}", level=Qgis.Info)
        return True

    def _build_unique_group_name(self, parent: QgsLayerTreeGroup, base_name: str) -> str:
        existing = set()
        try:
            for child in parent.children():
                try:
                    existing.add(str(child.name() or "").strip())
                except Exception:
                    continue
        except Exception:
            existing = set()

        if base_name not in existing:
            return base_name

        index = 2
        while f"{base_name}_{index}" in existing:
            index += 1
        return f"{base_name}_{index}"

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
        zip_basename = os.path.splitext(os.path.basename(zip_path))[0]
        extract_dir = self._build_extract_dir(zip_path, run_id)

        try:
            os.makedirs(extract_dir, exist_ok=False)
        except Exception:
            log_message(f"KIGAM ZIP 임시 폴더 생성 실패: {extract_dir}", level=Qgis.Warning)
            return []

        # Extract ZIP
        try:
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(extract_dir)
        except Exception as e:
            log_message(f"KIGAM ZIP 추출 실패: {e}", level=Qgis.Warning)
            return []

        # Locate 'sym' folder (optional)
        sym_path = None
        for root, dirs, _ in os.walk(extract_dir):
            if "sym" in dirs:
                sym_path = os.path.join(root, "sym")
                break

        if apply_style and not sym_path:
            log_message("KIGAM ZIP에 'sym' 폴더가 없습니다. 심볼 적용은 건너뜁니다.", level=Qgis.Warning)

        loaded_layers: List[QgsVectorLayer] = []
        for root, _, files in os.walk(extract_dir):
            for fname in files:
                if not fname.lower().endswith(".shp"):
                    continue
                shp_path = os.path.join(root, fname)
                layer_name = os.path.splitext(fname)[0]

                qml_path = self._find_sidecar_qml(root, layer_name)
                layer, chosen_encoding, best_field, match_count = self._load_layer_with_best_encoding(
                    shp_path,
                    layer_name,
                    sym_path=sym_path,
                    qml_path=qml_path,
                )
                if layer is None or not layer.isValid():
                    log_message(f"KIGAM 레이어 로드 실패: {shp_path}", level=Qgis.Warning)
                    continue

                if chosen_encoding:
                    try:
                        layer.setProviderEncoding(chosen_encoding)
                    except Exception:
                        pass

                QgsProject.instance().addMapLayer(layer, False)
                loaded_layers.append(layer)

                if chosen_encoding or best_field:
                    log_message(
                        f"KIGAM layer load: {layer.name()} encoding={chosen_encoding or 'provider-default'} "
                        f"style_field={best_field or '-'} matches={match_count}",
                        level=Qgis.Info,
                    )

                style_loaded = False
                if apply_style and qml_path:
                    try:
                        style_loaded = self.apply_qml_style(layer, qml_path, sym_path)
                    except Exception as e:
                        log_message(f"KIGAM QML ?곸슜 ?ㅽ뙣: {layer.name()} ({e})", level=Qgis.Warning)

                if apply_style and sym_path and not style_loaded:
                    try:
                        self.apply_sym_styling(layer, sym_path, qml_path=qml_path)
                    except Exception as e:
                        log_message(f"KIGAM 스타일 적용 실패: {layer.name()} ({e})", level=Qgis.Warning)

                if apply_labels and GEOLOGY_LITHO_LAYER_KEYWORD and GEOLOGY_LITHO_LAYER_KEYWORD in layer_name.lower():
                    try:
                        self.apply_labeling(layer, font_family, font_size)
                    except Exception:
                        pass

                try:
                    set_archtoolkit_layer_metadata(
                        layer,
                        tool_id="kigam_zip",
                        run_id=run_id,
                        kind="vector",
                        params={"zip": os.path.basename(zip_path)},
                    )
                except Exception:
                    pass

        self.organize_layers(loaded_layers, zip_basename)
        return loaded_layers

    def apply_sym_styling(self, layer: QgsVectorLayer, sym_path: str, *, qml_path: Optional[str] = None) -> None:
        raw_sym_files, lookup_sym_files = self._build_symbol_index(sym_path)
        if not raw_sym_files:
            return

        qml_field, _, qml_lookup_map = self._parse_qml_mapping(qml_path)
        best_field, max_matches, _ = self._find_best_matching_field(
            layer,
            raw_sym_files,
            lookup_sym_files,
            qml_field,
            qml_lookup_map,
        )
        if not best_field or max_matches <= 0:
            return

        categories = []
        unique_values = layer.uniqueValues(layer.fields().indexOf(best_field))
        for val in unique_values:
            val_str = str(val)
            symbol = None

            png_path = self._resolve_symbol_with_qml_map(
                val,
                raw_sym_files,
                lookup_sym_files,
                qml_lookup_map,
            )
            if png_path:
                if layer.geometryType() == QgsWkbTypes.PointGeometry:
                    symbol_layer = QgsRasterMarkerSymbolLayer(png_path)
                    symbol_layer.setSize(GEOLOGY_POINT_MARKER_SIZE)
                    symbol = QgsMarkerSymbol()
                    symbol.changeSymbolLayer(0, symbol_layer)
                elif layer.geometryType() == QgsWkbTypes.PolygonGeometry:
                    symbol_layer = QgsRasterFillSymbolLayer()
                    symbol_layer.setImageFilePath(png_path)
                    symbol_layer.setWidth(GEOLOGY_FILL_SYMBOL_WIDTH)
                    symbol = QgsFillSymbol()
                    symbol.changeSymbolLayer(0, symbol_layer)

            if symbol:
                categories.append(QgsRendererCategory(val, symbol, val_str))
            else:
                if layer.geometryType() == QgsWkbTypes.PointGeometry:
                    symbol = QgsMarkerSymbol.createSimple({"color": "#ff0000"})
                elif layer.geometryType() == QgsWkbTypes.PolygonGeometry:
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
        label_field = next((name for name in GEOLOGY_LABEL_FIELD_CANDIDATES if name in fields), fields[0])
        settings.fieldName = label_field
        text_format = QgsTextFormat()
        text_format.setFont(QFont(font_family))
        text_format.setSize(int(font_size))
        text_format.setColor(QColor("black"))
        settings.setFormat(text_format)
        settings.placement = QgsPalLayerSettings.Horizontal
        settings.centroidInside = True
        settings.fitInPolygonOnly = True
        settings.priority = 5
        layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
        layer.setLabelsEnabled(True)

    def organize_layers(self, layers: List[QgsVectorLayer], group_name: str) -> None:
        if not layers:
            return
        root = QgsProject.instance().layerTreeRoot()
        parent = root.findGroup(PARENT_GROUP_NAME)
        if parent is None:
            parent = root.insertGroup(0, PARENT_GROUP_NAME)
        run_group = parent.insertGroup(0, self._build_unique_group_name(parent, f"KIGAM_{group_name}"))

        def _priority(layer: QgsVectorLayer) -> int:
            name = (layer.name() or "").lower()
            geom = layer.geometryType()

            # Reference / sheet helpers
            if any(keyword in name for keyword in GEOLOGY_FRAME_LAYER_KEYWORDS):
                return 0

            # Polygons should sit below linework so labels/lines aren't hidden by fills.
            if GEOLOGY_LITHO_LAYER_KEYWORD and GEOLOGY_LITHO_LAYER_KEYWORD in name:
                return 30
            if geom == QgsWkbTypes.PolygonGeometry:
                return 25

            # Linework (top)
            if geom == QgsWkbTypes.LineGeometry:
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
            if geom == QgsWkbTypes.PointGeometry:
                return 60

            return 10

        def _hide_by_default(layer: QgsVectorLayer) -> bool:
            name = (layer.name() or "").lower()
            return any(keyword in name for keyword in GEOLOGY_REFERENCE_HIDE_KEYWORDS)

        scored: List[Tuple[int, int, QgsVectorLayer]] = []
        for i, layer in enumerate(layers):
            scored.append((_priority(layer), i, layer))
        # Display order (top->bottom): higher priority first, stable by original order.
        scored.sort(key=lambda x: (-x[0], x[1]))

        # insertLayer(0, ...) builds the list from bottom->top, so iterate reversed.
        for _, __, layer in reversed(scored):
            node = run_group.insertLayer(0, layer)
            if _hide_by_default(layer):
                try:
                    node.setItemVisibilityChecked(False)
                except Exception:
                    pass
        run_group.setExpanded(True)
        parent.setExpanded(True)


class GeologyZipDialog(QtWidgets.QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        use_en = is_english_ui()
        self.setWindowTitle(
            "KIGAM Geology ZIP Loader / MaxEnt Raster Conversion - ArchToolkit"
            if use_en
            else "지질도 도엽 ZIP 불러오기 / MaxEnt 래스터 변환 - ArchToolkit"
        )
        try:
            plugin_dir = os.path.dirname(os.path.dirname(__file__))
            icon_path = os.path.join(plugin_dir, "geochem.png")
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception:
            pass

        layout = QtWidgets.QVBoxLayout(self)

        header = QtWidgets.QLabel(
            (
                "<b>Load KIGAM 1:50,000 Geology ZIP</b> + <b>Vector to Raster Conversion</b><br>"
                "Load a geology map ZIP sheet directly and convert it into rasters for predictive modeling tools such as MaxEnt."
            )
            if use_en
            else
            (
                "<b>KIGAM 1:50,000 지질도 ZIP 불러오기</b> + <b>벡터→래스터 변환</b><br>"
                "지질도 도엽 ZIP을 바로 로드하고, MaxEnt 같은 예측 모델링용 래스터로 변환합니다."
            )
        )
        header.setWordWrap(True)
        header.setStyleSheet("background:#e3f2fd; padding:10px; border:1px solid #bbdefb; border-radius:4px;")
        layout.addWidget(header)

        # 1) ZIP loader
        grp_zip = QtWidgets.QGroupBox("1. 지질도 ZIP 불러오기 (KIGAM 1:50,000)")
        form_zip = QtWidgets.QFormLayout(grp_zip)

        self.txtZip = QtWidgets.QLineEdit()
        self.txtZip.setPlaceholderText("ZIP 파일을 선택하거나 경로를 입력하세요…")
        self.btnBrowseZip = QtWidgets.QPushButton("찾기…")
        self.btnBrowseZip.clicked.connect(self._browse_zip)
        row_zip = QtWidgets.QHBoxLayout()
        row_zip.addWidget(self.txtZip, 1)
        row_zip.addWidget(self.btnBrowseZip)
        form_zip.addRow("ZIP 파일:", row_zip)

        self.cmbFont = QtWidgets.QFontComboBox()
        form_zip.addRow("라벨 글꼴:", self.cmbFont)

        self.spinFontSize = QtWidgets.QSpinBox()
        self.spinFontSize.setRange(GEOLOGY_UI_FONT_SIZE_MIN, GEOLOGY_UI_FONT_SIZE_MAX)
        self.spinFontSize.setValue(GEOLOGY_UI_FONT_SIZE_DEFAULT)
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
        self.lstLayers.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.lstLayers.itemChanged.connect(self._refresh_field_choices)
        vbox.addWidget(self.lstLayers)

        row_refresh = QtWidgets.QHBoxLayout()
        self.btnRefreshLayers = QtWidgets.QPushButton("레이어 목록 새로고침")
        self.btnRefreshLayers.clicked.connect(self.refresh_layer_list)
        row_refresh.addWidget(self.btnRefreshLayers)
        row_refresh.addStretch(1)
        vbox.addLayout(row_refresh)

        form_rst = QtWidgets.QFormLayout()
        self.cmbField = QtWidgets.QComboBox()
        self.cmbField.addItem("(자동 선택)", "")
        form_rst.addRow("값 필드:", self.cmbField)

        self.spinPixel = QtWidgets.QDoubleSpinBox()
        self.spinPixel.setRange(GEOLOGY_UI_PIXEL_MIN, GEOLOGY_UI_PIXEL_MAX)
        self.spinPixel.setSingleStep(1.0)
        self.spinPixel.setValue(GEOLOGY_UI_PIXEL_DEFAULT)
        self.spinPixel.setSuffix(" m")
        form_rst.addRow("해상도(픽셀 크기):", self.spinPixel)

        self.spinNoData = QtWidgets.QDoubleSpinBox()
        self.spinNoData.setRange(GEOLOGY_UI_NODATA_MIN, GEOLOGY_UI_NODATA_MAX)
        self.spinNoData.setDecimals(GEOLOGY_UI_NODATA_DECIMALS)
        self.spinNoData.setValue(GEOLOGY_UI_NODATA_DEFAULT)
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
        self.btnBrowseOutFile = QtWidgets.QPushButton("저장 위치…")
        self.btnBrowseOutFile.clicked.connect(self._browse_out_file)
        row_out = QtWidgets.QHBoxLayout()
        row_out.addWidget(self.txtOutFile, 1)
        row_out.addWidget(self.btnBrowseOutFile)
        vbox.addWidget(QtWidgets.QLabel("출력 파일(단일 모드):"))
        vbox.addLayout(row_out)

        # Output dir (per-layer)
        self.txtOutDir = QtWidgets.QLineEdit()
        self.btnBrowseOutDir = QtWidgets.QPushButton("폴더 선택…")
        self.btnBrowseOutDir.clicked.connect(self._browse_out_dir)
        row_dir = QtWidgets.QHBoxLayout()
        row_dir.addWidget(self.txtOutDir, 1)
        row_dir.addWidget(self.btnBrowseOutDir)
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
        apply_language(self)

    def _browse_zip(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select KIGAM ZIP File" if is_english_ui() else "KIGAM ZIP 파일 선택",
            "",
            "ZIP Files (*.zip *.ZIP)",
        )
        if path:
            self.txtZip.setText(path)

    def _browse_out_file(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save Raster" if is_english_ui() else "래스터 저장",
            "",
            "GeoTIFF (*.tif);;ASCII Grid (*.asc)",
        )
        if path:
            self.txtOutFile.setText(path)

    def _browse_out_dir(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Select Output Folder" if is_english_ui() else "출력 폴더 선택",
            "",
        )
        if path:
            self.txtOutDir.setText(path)

    def _toggle_output_mode(self):
        is_merge = self.radMerge.isChecked()
        self.txtOutFile.setEnabled(is_merge)
        try:
            self.btnBrowseOutFile.setEnabled(is_merge)
        except Exception:
            pass
        try:
            self.btnBrowseOutDir.setEnabled(not is_merge)
        except Exception:
            pass
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
                        return name[len("KIGAM_"):].strip()
                node = parent
        except Exception:
            pass
        return ""

    def refresh_layer_list(self):
        checked_ids = set()
        try:
            for i in range(self.lstLayers.count()):
                it = self.lstLayers.item(i)
                if it is not None and it.checkState() == Qt.Checked:
                    checked_ids.add(it.data(Qt.UserRole))
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
        except Exception:
            pass

        scored = []
        for layer in layers:
            if not isinstance(layer, QgsVectorLayer):
                continue
            if kigam_only:
                try:
                    tool_id = str(layer.customProperty("archtoolkit/tool_id", "") or "").strip()
                    if tool_id != "kigam_zip":
                        continue
                except Exception:
                    continue

            geom = layer.geometryType()
            if litho_only:
                if geom != QgsWkbTypes.PolygonGeometry:
                    continue
                try:
                    lname = str(layer.name() or "").lower()
                    fields_up = {str(f.name() or "").upper() for f in layer.fields()}
                    candidate_fields_up = {name.upper() for name in GEOLOGY_LABEL_FIELD_CANDIDATES}
                    if (
                        GEOLOGY_LITHO_LAYER_KEYWORD
                        and GEOLOGY_LITHO_LAYER_KEYWORD not in lname
                        and not any(name in fields_up for name in candidate_fields_up)
                    ):
                        continue
                except Exception:
                    continue

            region = self._kigam_region_for_layer(layer)
            scored.append((region, str(layer.name() or ""), layer, geom))

        scored.sort(key=lambda x: (x[0], x[1]))
        for region, layer_name, layer, geom in scored:
            shown_name = layer_name
            if region:
                shown_name = f"[{region}] {layer_name}"
            item = QtWidgets.QListWidgetItem(layer.name())
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if layer.id() in checked_ids else Qt.Unchecked)
            item.setData(Qt.UserRole, layer.id())
            tip = []
            if geom == QgsWkbTypes.PointGeometry:
                tip.append("Point Layer" if is_english_ui() else "포인트 레이어")
            elif geom == QgsWkbTypes.LineGeometry:
                tip.append("Line Layer" if is_english_ui() else "라인 레이어")
            elif geom == QgsWkbTypes.PolygonGeometry:
                tip.append("Polygon Layer" if is_english_ui() else "폴리곤 레이어")
            if region:
                tip.append(f"Area / Sheet: {region}" if is_english_ui() else f"지역/도엽: {region}")
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
            if item.checkState() != Qt.Checked:
                continue
            lid = item.data(Qt.UserRole)
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
                lid = item.data(Qt.UserRole)
                lyr = layer_map.get(lid)
                if isinstance(lyr, QgsVectorLayer):
                    for f in lyr.fields():
                        fields.add(f.name())

        current = str(self.cmbField.currentData() or self.cmbField.currentText() or "").strip()
        self.cmbField.blockSignals(True)
        self.cmbField.clear()
        self.cmbField.addItem("(자동 선택)", "")
        for name in sorted(fields):
            self.cmbField.addItem(name, name)
        if current:
            idx = self.cmbField.findData(current)
            if idx >= 0:
                self.cmbField.setCurrentIndex(idx)
        self.cmbField.blockSignals(False)

    def _choose_common_field(self, layers: List[QgsVectorLayer]) -> Optional[str]:
        if not layers:
            return None
        chosen = str(self.cmbField.currentData() or self.cmbField.currentText() or "").strip()
        if chosen:
            if all(lyr.fields().indexOf(chosen) >= 0 for lyr in layers):
                return chosen
        # Auto: prefer common fields
        common = set(f.name() for f in layers[0].fields())
        for lyr in layers[1:]:
            common &= set(f.name() for f in lyr.fields())
        if not common:
            return None
        for p in GEOLOGY_RASTER_FIELD_PRIORITY:
            if p in common:
                return p
        return sorted(common)[0]

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
        for cand in GEOLOGY_NAME_FIELD_CANDIDATES:
            if cand in up and up[cand] != base:
                return up[cand]

        return None

    def _is_numeric_field(self, layer: QgsVectorLayer, field_name: str) -> bool:
        try:
            f = layer.fields().field(field_name)
            if f is None:
                return False
            return f.type() in (
                QVariant.Int,
                QVariant.UInt,
                QVariant.LongLong,
                QVariant.ULongLong,
                QVariant.Double,
            )
        except Exception:
            return False

    def _build_numeric_merge_layer(
        self,
        layers: List[QgsVectorLayer],
        field_name: str,
    ) -> Tuple[Optional[QgsVectorLayer], Dict[str, int], Dict[str, str], Dict[int, int]]:
        if not layers:
            return None, {}, {}, {}

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
            log_message(f"병합 레이어 생성 실패(메모리 레이어 초기화 실패): geom={geom_str}, crs={authid}", level=Qgis.Warning)
            return None, {}, {}, {}

        try:
            if target_crs is not None and target_crs.isValid():
                out_layer.setCrs(target_crs)
        except Exception:
            pass

        pr = out_layer.dataProvider()
        pr.addAttributes([QgsField("ATK_VAL", QVariant.Int)])
        out_layer.updateFields()

        mapping: Dict[str, int] = {}
        labels: Dict[str, str] = {}
        counts: Dict[int, int] = {}
        next_id = 1
        numeric = self._is_numeric_field(layers[0], field_name)
        label_field = self._suggest_label_field(layers[0], field_name) if numeric else None

        for lyr in layers:
            if lyr.geometryType() != layers[0].geometryType():
                log_message(f"지오메트리 타입 불일치: {lyr.name()} (skip)", level=Qgis.Warning)
                continue
            transform = None
            if lyr.crs() != target_crs:
                try:
                    transform = QgsCoordinateTransform(lyr.crs(), target_crs, QgsProject.instance())
                except Exception:
                    transform = None

            for f in lyr.getFeatures():
                try:
                    geom = f.geometry()
                    if geom is None or geom.isEmpty():
                        continue
                    if transform is not None:
                        geom.transform(transform)
                    val = f[field_name]
                    if val is None or str(val).strip() == "":
                        continue
                    if numeric:
                        try:
                            out_int = int(float(val))
                        except Exception:
                            continue
                        code = str(out_int)
                        mapping[code] = out_int
                        if label_field and code not in labels:
                            try:
                                lbl = f[label_field]
                                if lbl is not None and str(lbl).strip():
                                    labels[code] = str(lbl).strip()
                            except Exception:
                                pass
                        out_val = float(out_int)
                    else:
                        key = str(val)
                        if key not in mapping:
                            mapping[key] = next_id
                            next_id += 1
                        if key not in labels:
                            labels[key] = key
                        out_val = float(mapping[key])

                    try:
                        out_i = int(out_val)
                        counts[out_i] = counts.get(out_i, 0) + 1
                    except Exception:
                        pass

                    nf = QgsFeature(out_layer.fields())
                    nf.setGeometry(geom)
                    nf.setAttributes([out_val])
                    pr.addFeatures([nf])
                except Exception:
                    continue

        out_layer.updateExtents()
        return out_layer, mapping, labels, counts

    def _write_mapping_csv(
        self,
        mapping: Dict[str, int],
        out_path: str,
        *,
        labels: Optional[Dict[str, str]] = None,
        counts: Optional[Dict[int, int]] = None,
    ) -> Optional[str]:
        if not mapping and not labels and not counts:
            return None
        try:
            base = os.path.splitext(out_path)[0]
            csv_path = base + "_mapping.csv"
            labels = labels or {}
            counts = counts or {}
            with open(csv_path, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["code", "int_value", "label", "feature_count"])
                rows = []
                for code, v in (mapping or {}).items():
                    vv = int(v)
                    rows.append((vv, str(code), str(labels.get(str(code), "") or ""), int(counts.get(vv, 0))))
                rows.sort(key=lambda x: (x[0], x[1]))
                for vv, code, label, cnt in rows:
                    w.writerow([code, vv, label, cnt])
            if os.path.exists(csv_path) and os.path.getsize(csv_path) > 0:
                return csv_path
            return None
        except Exception:
            return None

    def _rasterize_layer(
        self,
        layer: QgsVectorLayer,
        field_name: str,
        out_path: str,
        pixel_size: float,
        nodata: float,
    ) -> str:
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

            if crs is not None and crs.isValid() and (crs.isGeographic() or units == QgsUnitTypes.DistanceDegrees):
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
                        level=Qgis.Warning,
                    )
                    cell_w, cell_h = float(deg_w), float(deg_h)
        except Exception:
            pass

        try:
            if rect is not None:
                w = float(rect.width())
                h = float(rect.height())
                cols = int(math.ceil(w / cell_w)) if cell_w > 0 else 0
                rows = int(math.ceil(h / cell_h)) if cell_h > 0 else 0
                log_message(
                    f"KIGAM rasterize grid: extent_w={w} extent_h={h} cell_w={cell_w} cell_h={cell_h} -> {cols}x{rows}",
                    level=Qgis.Info,
                )
                if cols <= 0 or rows <= 0:
                    raise RuntimeError(
                        "출력 래스터 크기가 0입니다. (CRS 단위/해상도 불일치) "
                        "투영 CRS(미터 단위)로 변환하거나 픽셀 크기를 조정하세요."
                    )
        except Exception as e:
            log_message(f"KIGAM rasterize preflight 실패: {e}", level=Qgis.Warning)
            raise

        log_message(
            "KIGAM rasterize: "
            f"layer={layer.name()} field={field_name} out={out_path} "
            f"px={cell_w}x{cell_h} nodata={nodata} crs={authid} extent={rect}",
            level=Qgis.Info,
        )

        params = {
            "INPUT": layer,
            "FIELD": field_name,
            "UNITS": 1,
            "WIDTH": float(cell_w),
            "HEIGHT": float(cell_h),
            "EXTENT": rect if rect is not None else layer.extent(),
            "NODATA": float(nodata),
            # Categorical rasters should stay integer-coded for MaxEnt/ML workflows.
            "DATA_TYPE": 4,  # Int32
            "OUTPUT": out_path,
        }
        try:
            result = processing.run("gdal:rasterize", params)
        except Exception as e:
            log_message(f"gdal:rasterize 실패: {e}", level=Qgis.Warning)
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
            level=Qgis.Info if exists and size > 0 else Qgis.Warning,
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
                level=Qgis.Info if exists2 and size2 > 0 else Qgis.Warning,
            )
            if exists2 and size2 > 0:
                try:
                    if os.path.exists(vec_path):
                        os.remove(vec_path)
                except Exception:
                    pass
                return raster_path2
        except Exception as e:
            log_message(f"KIGAM rasterize 재시도 실패: {e}", level=Qgis.Warning)

        # If we get here, we couldn't verify a raster file on disk.
        try:
            log_message(f"KIGAM rasterize raw result={result}", level=Qgis.Warning)
        except Exception:
            pass
        raise RuntimeError("래스터 파일이 생성되지 않았습니다. 출력 경로/권한/로그를 확인하세요.")

    def _run_rasterize(self):
        layers = self._selected_vector_layers()
        if not layers:
            push_message(self.iface, "오류", "선택된 벡터 레이어가 없습니다.", level=2)
            restore_ui_focus(self)
            return

        field = self._choose_common_field(layers) if self.radMerge.isChecked() else None
        if self.radMerge.isChecked() and not field:
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

                merged_layer, mapping, labels, counts = self._build_numeric_merge_layer(layers, field)
                if merged_layer is None or not merged_layer.isValid():
                    raise RuntimeError("병합 레이어 생성에 실패했습니다.")

                raster_path = self._rasterize_layer(merged_layer, "ATK_VAL", out_path, pixel, nodata)
                csv_path = self._write_mapping_csv(mapping, raster_path, labels=labels, counts=counts)

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
                        kind="raster",
                        params={"field": field, "pixel": pixel},
                    )
                if csv_path:
                    log_message(f"코드 매핑 저장: {csv_path}", level=Qgis.Info)
                push_message(self.iface, "완료", f"래스터 생성: {raster_path}", level=0, duration=7)
                return

            # Per-layer mode
            out_dir = (self.txtOutDir.text() or "").strip()
            if not out_dir or not os.path.isdir(out_dir):
                push_message(self.iface, "오류", "출력 폴더를 지정하세요.", level=2)
                restore_ui_focus(self)
                return

            for lyr in layers:
                field = str(self.cmbField.currentData() or self.cmbField.currentText() or "").strip()
                if not field or lyr.fields().indexOf(field) < 0:
                    # Choose best field for this layer
                    field = None
                    for p in GEOLOGY_RASTER_FIELD_PRIORITY:
                        if lyr.fields().indexOf(p) >= 0:
                            field = p
                            break
                    if field is None:
                        field = lyr.fields()[0].name() if lyr.fields() else None
                if not field:
                    log_message(f"{lyr.name()}: 필드 없음, 건너뜀", level=Qgis.Warning)
                    continue

                merged_layer, mapping, labels, counts = self._build_numeric_merge_layer([lyr], field)
                if merged_layer is None or not merged_layer.isValid():
                    continue

                out_path = os.path.join(out_dir, f"{_safe_name(lyr.name())}.{fmt}")
                raster_path = self._rasterize_layer(merged_layer, "ATK_VAL", out_path, pixel, nodata)
                csv_path = self._write_mapping_csv(mapping, raster_path, labels=labels, counts=counts)

                rlayer = QgsRasterLayer(raster_path, f"{lyr.name()}_raster")
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
                        kind="raster",
                        params={"field": field, "pixel": pixel},
                    )
                if csv_path:
                    log_message(f"코드 매핑 저장: {csv_path}", level=Qgis.Info)

            push_message(self.iface, "완료", "레이어별 래스터 변환이 완료되었습니다.", level=0, duration=7)
        except Exception as e:
            log_message(f"래스터 변환 실패: {e}", level=Qgis.Warning)
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
        processor = KigamZipProcessor()
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
                frame_layer = next(
                    (
                        layer_obj
                        for layer_obj in layers
                        if any(keyword in layer_obj.name().lower() for keyword in GEOLOGY_FRAME_LAYER_KEYWORDS)
                    ),
                    None,
                )
                target = frame_layer or layers[0]
                if target and target.isValid():
                    canvas = self.iface.mapCanvas()
                    canvas.setExtent(target.extent())
                    canvas.refresh()
            except Exception:
                pass
            push_message(self.iface, "완료", f"ZIP에서 {len(layers)}개 레이어를 로드했습니다.", level=0, duration=7)
        else:
            push_message(self.iface, "경고", "로드된 레이어가 없습니다. 로그를 확인하세요.", level=1)

        self.refresh_layer_list()

    def _on_help(self):
        if is_english_ui():
            html = """
<h3>Geology ZIP Loader / MaxEnt Raster Conversion</h3>
<p>
Loads KIGAM 1:50,000 geology ZIP sheets directly and creates geology-code rasters
that can be used with predictive modeling workflows such as MaxEnt.
</p>

<h4>Load ZIP</h4>
<ul>
  <li>Select a ZIP downloaded from KIGAM to load SHP layers automatically. If a <code>sym</code> folder is present, symbol styling is applied.</li>
  <li>LITHOIDX / LITHONAME layers can receive labels automatically.</li>
  <li>Layers are organized under <code>ArchToolkit - Geology</code> as <code>KIGAM_sheet_name</code>,
  with lines and points placed above polygon geology layers.</li>
</ul>

<h4>Vector to Raster</h4>
<ul>
  <li><b>Default list</b>: for most predictive-modeling cases, Litho (rock / formation) polygons are enough,
  so the default filter shows only <b>KIGAM ZIP layers + Litho polygons</b>.</li>
  <li>Layer names include sheet / area tags such as <code>[GF13_Cheongju]</code> when multiple sheets are loaded.</li>
  <li>Typical value fields are <code>LITHOIDX</code> and <code>AGEIDX</code>.</li>
  <li>String codes (for example Qa, Jbgr) are mapped automatically to integer values, and an accompanying <code>*_mapping.csv</code> file is written.</li>
  <li>When numeric codes are used, related labels such as <code>LITHONAME</code> / <code>AGENAME</code> are written to the mapping CSV when available.</li>
  <li>You can create one merged raster or export a separate raster per layer.</li>
  <li>After processing, the tool checks whether output files were actually created and logs the cause when something goes wrong.</li>
</ul>

<h4>Predictive Modeling Tips</h4>
<ul>
  <li>Geology units are usually <b>categorical</b> variables. The raster stores integer codes, and the mapping CSV explains them.</li>
  <li>When using MaxEnt, treat the geology raster as a categorical input to avoid interpreting the codes as continuous values.</li>
  <li>When combining geology with other variables such as geochemistry or terrain, align CRS, resolution, and extent across all rasters.</li>
</ul>

<h4>Troubleshooting</h4>
<ul>
  <li>If the CSV is created but the raster is missing, check output-folder permissions / path issues and try another folder such as Downloads.</li>
  <li>For diagnosis, inspect the <code>KIGAM rasterize result</code> lines in the ArchToolkit live log.</li>
</ul>
"""
            title = "Geology ZIP / MaxEnt Help"
        else:
            html = """
<h3>지질도 ZIP 불러오기 / MaxEnt 래스터 변환</h3>
<p>
KIGAM 1:50,000 지질도 ZIP(도엽)을 바로 로드하고, 지질 코드 기반으로 래스터를 생성합니다.
지구화학도 수치 래스터와 함께 MaxEnt 같은 예측 모델링 입력으로 사용할 수 있습니다.
</p>

<h4>ZIP 불러오기</h4>
<ul>
  <li>KIGAM에서 받은 ZIP을 선택하면 SHP를 자동 로드하고, sym 폴더가 있으면 심볼을 적용합니다.</li>
  <li>LITHOIDX/LITHONAME 레이어는 라벨을 자동 적용할 수 있습니다.</li>
  <li>레이어는 <code>ArchToolkit - Geology</code> 그룹 아래 <code>KIGAM_도엽명</code>으로 정리되고, 라인/포인트가 폴리곤(Litho) 위로 올라오도록 순서를 맞춥니다.</li>
</ul>

<h4>벡터 → 래스터</h4>
<ul>
  <li><b>기본 목록</b>: 보통 Litho(암상/지층) 폴리곤만 있으면 충분하므로, 기본은 <b>KIGAM ZIP 레이어 + Litho(폴리곤)</b>만 표시합니다.</li>
  <li>레이어 이름 앞에 <code>[GF13_청주]</code>처럼 <b>도엽/지역</b> 정보가 함께 표시됩니다(여러 도엽을 불러온 경우 구분용).</li>
  <li>값 필드는 보통 <code>LITHOIDX</code>/<code>AGEIDX</code>를 사용합니다.</li>
  <li>문자 코드(예: Qa, Jbgr)일 경우 자동으로 정수 코드로 매핑하며, <code>*_mapping.csv</code>를 함께 저장합니다.</li>
  <li>숫자 코드(예: <code>LITHOIDX</code>)를 선택해도 가능한 경우 <code>LITHONAME</code>/<code>AGENAME</code>을 함께 매핑 CSV에 기록합니다.</li>
  <li>단일 래스터(병합) 또는 레이어별 출력 중 선택할 수 있습니다.</li>
  <li>실행 후에는 <b>출력 파일이 실제로 생성되었는지</b> 확인하고, 문제가 있으면 로그에 원인을 남깁니다.</li>
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
            title = "지질도 ZIP/MaxEnt 도움말"
        try:
            plugin_dir = os.path.dirname(os.path.dirname(__file__))
            show_help_dialog(parent=self, title=title, html=html, plugin_dir=plugin_dir)
        except Exception:
            pass
