# -*- coding: utf-8 -*-

# ArchToolkit - Archaeology Toolkit for QGIS
# Copyright (C) 2026 balguljang2
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""
Terrain Profile Dialog for ArchToolkit
Draw a line on DEM and display elevation profile with graphical chart
"""
import os
import csv
import datetime
import math
from typing import List, Optional, Sequence, Tuple
from qgis.PyQt import uic
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import Qt, QPointF, QRectF
from qgis.PyQt.QtWidgets import QMessageBox, QFileDialog, QWidget
from qgis.PyQt.QtGui import QColor, QPainter, QPen, QBrush, QPalette, QPainterPath, QImage
from qgis.core import (
    QgsProject,
    QgsPointXY,
    QgsVectorLayer,
    QgsField,
    QgsFeature,
    QgsFeatureRequest,
    QgsGeometry,
    QgsLineSymbol,
    QgsSingleSymbolRenderer,
    QgsProperty,
    Qgis,
    QgsDistanceArea,
    QgsCoordinateTransform,
)
from .qtcompat import FT_INT, FT_DOUBLE, FT_STRING, SYMBOL_PROPERTY_STROKE_COLOR, RUBBER_BAND_CIRCLE
from qgis.gui import QgsMapLayerComboBox, QgsMapToolEmitPoint, QgsRubberBand
from .utils import (
    is_null_value,
    log_swallowed,
    log_message,
    move_group_to_top,
    new_run_id,
    push_message,
    restore_ui_focus,
    set_archtoolkit_layer_metadata,
    transform_point,
)
from .live_log_dialog import ensure_live_log_dialog
from .help_dialog import show_help_dialog
from . import dialog_memory
from .icons import icon as plugin_icon

PROFILE_LAYER_NAME = "Terrain Profile Lines"
PROFILE_GROUP_NAME = "ArchToolkit - Terrain Profile"
PROFILE_SINGLE_SUBGROUP_NAME = "단면선 (개별 레이어)"
PROFILE_KIND_PROP = "ArchToolkit/profile_kind"
PROFILE_KIND_SINGLE = "terrain_profile_single"

# Optional chart smoothing: +/- this many samples (moving average). Off by
# default - the chart draws the raw samples so a narrow ditch or bank keeps its
# real depth/height on screen and in the exported image.
CHART_SMOOTH_HALF_WINDOW = 3


def _profile_runs(series):
    """Split profile samples into runs separated by NoData gaps.

    A sample carries ``gap_before=True`` when one or more samples between it
    and the previous valid sample were NoData / outside the DEM. The chart
    breaks its line there and the statistics skip that segment instead of
    bridging the hole with a straight line.
    """
    runs = []
    cur = []
    for p in series or []:
        if cur and p.get("gap_before"):
            runs.append(cur)
            cur = []
        cur.append(p)
    if cur:
        runs.append(cur)
    return runs


def _line_fraction(start: QgsPointXY, end: QgsPointXY, x: float, y: float) -> float:
    """Planar position (0-1) of (x, y) projected onto start->end, clamped."""
    vx = float(end.x() - start.x())
    vy = float(end.y() - start.y())
    vv = vx * vx + vy * vy
    if vv <= 0:
        return 0.0
    t = ((float(x) - float(start.x())) * vx + (float(y) - float(start.y())) * vy) / vv
    return min(1.0, max(0.0, float(t)))


def _intersection_ranges_m(inter, start: QgsPointXY, end: QgsPointXY, total_m: float) -> List[Tuple[float, float]]:
    """Distance ranges (m) covered by the line parts of an intersection geometry."""
    ranges: List[Tuple[float, float]] = []
    if inter is None or inter.isEmpty():
        return ranges
    parts = []
    try:
        if inter.type() == Qgis.GeometryType.Line:
            parts = inter.asMultiPolyline() if inter.isMultipart() else [inter.asPolyline()]
        elif inter.isMultipart():
            # Geometry collection (e.g. a line part plus a touching point).
            for g in inter.asGeometryCollection():
                if g.type() == Qgis.GeometryType.Line:
                    parts.extend(g.asMultiPolyline() if g.isMultipart() else [g.asPolyline()])
    except Exception as _exc:
        log_swallowed("terrain_profile_dialog._intersection_ranges_m", _exc)
        parts = []
    for seg in parts:
        if not seg or len(seg) < 2:
            continue
        ts = [_line_fraction(start, end, p.x(), p.y()) for p in seg]
        a = min(ts) * float(total_m)
        b = max(ts) * float(total_m)
        if math.isfinite(a) and math.isfinite(b) and b > a:
            ranges.append((a, b))
    ranges.sort(key=lambda t: t[0])
    merged: List[Tuple[float, float]] = []
    for a, b in ranges:
        if merged and a <= merged[-1][1] + 1e-9:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def _gap_aware_profile_stats(data):
    """Ascent/descent/slope statistics that skip NoData gap segments.

    Returns a dict with per-sample ``slopes`` (None on a gap segment),
    cumulative ``cum_up``/``cum_dn``, totals, the measured (non-gap) length and
    the number/length of gaps.
    """
    dists = [float(p["distance"]) for p in data]
    elevs = [float(p["elevation"]) for p in data]
    slopes = [0.0] if data else []
    cum_up = [0.0] if data else []
    cum_dn = [0.0] if data else []
    max_abs_slope = 0.0
    measured = 0.0
    gap_len = 0.0
    n_gaps = 0
    for i in range(1, len(dists)):
        dd = dists[i] - dists[i - 1]
        dz = elevs[i] - elevs[i - 1]
        if data[i].get("gap_before"):
            n_gaps += 1
            gap_len += max(0.0, dd)
            slopes.append(None)
            cum_up.append(cum_up[-1])
            cum_dn.append(cum_dn[-1])
        else:
            measured += max(0.0, dd)
            s = (dz / dd * 100.0) if dd > 1e-9 else 0.0
            slopes.append(s)
            max_abs_slope = max(max_abs_slope, abs(s))
            cum_up.append(cum_up[-1] + (dz if dz > 0 else 0.0))
            cum_dn.append(cum_dn[-1] + ((-dz) if dz < 0 else 0.0))
    ascent = cum_up[-1] if cum_up else 0.0
    descent = cum_dn[-1] if cum_dn else 0.0
    return {
        "dists": dists,
        "elevs": elevs,
        "slopes": slopes,
        "cum_up": cum_up,
        "cum_dn": cum_dn,
        "ascent": ascent,
        "descent": descent,
        "max_abs_slope": max_abs_slope,
        "mean_abs_slope": ((ascent + descent) / measured * 100.0) if measured > 1e-9 else 0.0,
        "measured_m": measured,
        "n_gaps": n_gaps,
        "gap_len_m": gap_len,
    }


def _segment_slope_parts(data, s0: float, s1: float):
    """(net_dz, abs_dz, up, down, measured_run) of the non-gap segments inside [s0, s1]."""
    net_dz = abs_dz = up = dn = run = 0.0
    for i in range(1, len(data)):
        if data[i].get("gap_before"):
            continue
        a = float(data[i - 1]["distance"])
        b = float(data[i]["distance"])
        if b <= s0 or a >= s1:
            continue
        overlap = min(s1, b) - max(s0, a)
        dd = b - a
        if overlap <= 0 or dd <= 1e-9:
            continue
        dz_seg = (float(data[i]["elevation"]) - float(data[i - 1]["elevation"])) * (overlap / dd)
        net_dz += dz_seg
        abs_dz += abs(dz_seg)
        if dz_seg > 0:
            up += dz_seg
        else:
            dn += -dz_seg
        run += overlap
    return net_dz, abs_dz, up, dn, run


def _profile_color_palette() -> List[QColor]:
    # A small set of distinct, print-friendly colors (rotates when exceeded).
    return [
        QColor("#1f77b4"),  # blue
        QColor("#ff7f0e"),  # orange
        QColor("#2ca02c"),  # green
        QColor("#d62728"),  # red
        QColor("#9467bd"),  # purple
        QColor("#8c564b"),  # brown
        QColor("#e377c2"),  # pink
        QColor("#7f7f7f"),  # gray
        QColor("#bcbd22"),  # olive
        QColor("#17becf"),  # cyan
    ]


FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'terrain_profile_dialog_base.ui'))


class ProfileChartWidget(QWidget):
    """Custom widget to draw elevation profile using QPainter
    
    Features:
    - Scroll wheel to zoom in/out
    - Mouse tracking to show position info
    - Drag to pan when zoomed
    - Smooth line rendering
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = []      # List of {'distance': d, 'elevation': e, 'x': x, 'y': y}
        self.smooth_data = []
        self.min_e = 0
        self.max_e = 100
        self.total_d = 0
        self.setMinimumHeight(250)
        self.setBackgroundRole(QPalette.ColorRole.Base)
        self.setAutoFillBackground(True)
        
        # Zoom and pan
        self.zoom_level = 1.0
        self.pan_offset = 0  # Horizontal offset in data units (distance)
        
        # Mouse tracking
        self.setMouseTracking(True)
        self.mouse_x = -1
        self.mouse_y = -1
        self.hover_distance = None
        self.hover_elevation = None
        self.hover_x = None  # Map X coordinate
        self.hover_y = None  # Map Y coordinate
        
        # Drag panning
        self.is_dragging = False
        self.drag_start_x = 0
        self.drag_start_offset = 0
        
        # Callback for map synchronization
        self.on_hover_callback = None  # Function(x, y) to show position on map

        # Profile line color (can be varied per saved profile)
        self.profile_color = QColor(0, 100, 255)

        # Curve smoothing: 0 = raw samples (default); N = +/-N-sample moving
        # average, stated on the chart. Vertical exaggeration of the last draw.
        self.smooth_window = 0
        self.vertical_exaggeration: Optional[float] = None
        self.annotation_lines: List[str] = []
        self.export_vertical_exaggeration: Optional[float] = None
        self.export_annotation_lines: List[str] = []
        self.axis_label_color = QColor(60, 60, 60)

        # Highlight ranges on distance axis (e.g., AOI intersection)
        self.highlight_ranges: List[Tuple[float, float]] = []
        self.highlight_label: str = ""
        self.highlight_color = QColor(255, 193, 7, 40)  # amber with alpha

        # Overlay (optional): show another layer along the profile.
        # - Polygon layers: ranges (background shading)
        # - Point/line layers: markers (vertical lines + points on the profile)
        self.overlay_ranges: List[Tuple[float, float]] = []
        self.overlay_label: str = ""
        self.overlay_color = QColor(76, 175, 80, 40)  # green with alpha
        self.overlay_markers: List[Tuple[float, str]] = []  # (distance_m, label)
        self.overlay_marker_color = QColor(76, 175, 80, 180)
        
        # Margins
        self.margin_left = 60
        self.margin_top = 30
        self.margin_right = 30
        self.margin_bottom = 40

    def set_data(self, data):
        self.data = data
        self.zoom_level = 1.0
        self.pan_offset = 0
        self.highlight_ranges = []
        self.highlight_label = ""
        self.overlay_ranges = []
        self.overlay_label = ""
        self.overlay_markers = []
        
        if not data:
            self.smooth_data = []
            self.update()
            return

        # The drawn curve: raw samples unless smoothing was switched on.
        self._recompute_curve()
        elevations = [p['elevation'] for p in data]

        self.min_e = min(elevations)
        self.max_e = max(elevations)
        self.total_d = data[-1]['distance']
        
        # Add some margin to elevation range
        margin = (self.max_e - self.min_e) * 0.1
        if margin == 0: margin = 1
        self.min_e -= margin
        self.max_e += margin
        
        self.update()

    def _recompute_curve(self):
        """Build the drawn curve (``smooth_data``) from the raw samples.

        With ``smooth_window == 0`` it is the raw samples. Otherwise a
        +/-N-sample moving average computed inside each NoData-free run, so a
        gap never averages values from its two far sides together.
        """
        k = max(0, int(self.smooth_window or 0))
        curve = []
        for run in _profile_runs(self.data):
            elevs = [float(p['elevation']) for p in run]
            for i, p in enumerate(run):
                if k > 0:
                    a = max(0, i - k)
                    b = min(len(run), i + k + 1)
                    e = sum(elevs[a:b]) / (b - a)
                else:
                    e = elevs[i]
                curve.append({
                    'distance': p['distance'],
                    'elevation': e,
                    'gap_before': bool(p.get('gap_before')),
                })
        self.smooth_data = curve

    def set_smoothing(self, half_window: int):
        """0 draws raw samples; N draws a +/-N-sample moving average (stated on the chart)."""
        try:
            self.smooth_window = max(0, int(half_window or 0))
        except (TypeError, ValueError):
            self.smooth_window = 0
        if self.data:
            self._recompute_curve()
        self.update()

    def _sample_spacing_m(self) -> Optional[float]:
        ds = [float(p['distance']) for p in self.data or []]
        steps = sorted(b - a for a, b in zip(ds, ds[1:]) if b - a > 1e-9)
        if not steps:
            return None
        return steps[len(steps) // 2]

    def _clamp_pan(self):
        visible = self.total_d / self.zoom_level if self.zoom_level else self.total_d
        max_offset = max(0.0, float(self.total_d) - float(visible))
        self.pan_offset = max(0.0, min(max_offset, float(self.pan_offset)))

    def wheelEvent(self, event):
        """Zoom in/out with scroll wheel, keeping the distance under the cursor fixed."""
        if not self.data or not self.total_d or self.total_d <= 0:
            return

        old_visible = self.total_d / self.zoom_level
        w = self.width() - self.margin_left - self.margin_right
        try:
            mx = float(event.position().x())
        except AttributeError:
            mx = float(event.pos().x())
        rel = ((mx - self.margin_left) / w) if w > 0 else 0.5
        rel = min(1.0, max(0.0, rel))
        anchor = self.pan_offset + rel * old_visible

        # Get zoom direction
        delta = event.angleDelta().y()
        if delta > 0:
            self.zoom_level = min(10.0, self.zoom_level * 1.2)
        else:
            self.zoom_level = max(1.0, self.zoom_level / 1.2)

        # Keep the distance under the cursor where it was, then clamp so the
        # view never runs past either end of the data.
        new_visible = self.total_d / self.zoom_level
        self.pan_offset = anchor - rel * new_visible
        self._clamp_pan()

        self.update()
    
    def mousePressEvent(self, event):
        """Start dragging for pan"""
        if event.button() == Qt.MouseButton.LeftButton and self.zoom_level > 1.0:
            self.is_dragging = True
            self.drag_start_x = event.pos().x()
            self.drag_start_offset = self.pan_offset
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
    
    def mouseReleaseEvent(self, event):
        """End dragging"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
    
    def mouseMoveEvent(self, event):
        """Track mouse position, handle drag panning, and sync with map"""
        if not self.data or not self.smooth_data:
            return
        
        self.mouse_x = event.pos().x()
        self.mouse_y = event.pos().y()
        
        # Calculate chart area
        w = self.width() - self.margin_left - self.margin_right
        h = self.height() - self.margin_top - self.margin_bottom
        visible_range = self.total_d / self.zoom_level
        
        # Handle drag panning
        if self.is_dragging and self.zoom_level > 1.0:
            delta_x = self.drag_start_x - self.mouse_x
            delta_distance = (delta_x / w) * visible_range
            new_offset = self.drag_start_offset + delta_distance
            
            # Clamp to valid range
            max_offset = self.total_d - visible_range
            self.pan_offset = max(0, min(max_offset, new_offset))
            self.update()
            return
        
        # Check if mouse is in chart area
        if (
            self.margin_left <= self.mouse_x <= self.margin_left + w and self.margin_top <= self.mouse_y <= self.margin_top + h
        ):

            # Calculate distance at mouse position
            rel_x = (self.mouse_x - self.margin_left) / w
            distance = self.pan_offset + rel_x * visible_range
            
            # Find closest data point (with map coordinates)
            if 0 <= distance <= self.total_d:
                # Find from original data which has x, y coordinates
                closest = min(self.data, key=lambda p: abs(p['distance'] - distance))
                self.hover_distance = closest['distance']
                self.hover_elevation = closest['elevation']
                self.hover_x = closest.get('x')
                self.hover_y = closest.get('y')
                
                # Show tooltip
                tooltip_text = f"거리: {self.hover_distance:.1f}m\n고도: {self.hover_elevation:.1f}m"
                self.setToolTip(tooltip_text)
                
                # Notify map to show position
                if self.on_hover_callback and self.hover_x is not None and self.hover_y is not None:
                    self.on_hover_callback(self.hover_x, self.hover_y)
            else:
                self.hover_distance = None
                self.hover_elevation = None
                self.hover_x = None
                self.hover_y = None
                self.setToolTip("")
        else:
            self.hover_distance = None
            self.hover_elevation = None
            self.hover_x = None
            self.hover_y = None
            self.setToolTip("")
        
        self.update()
    
    def leaveEvent(self, event):
        """Clear hover state when mouse leaves widget"""
        self.hover_distance = None
        self.hover_elevation = None
        self.hover_x = None
        self.hover_y = None
        self.setToolTip("")
        # Clear map marker
        if self.on_hover_callback:
            self.on_hover_callback(None, None)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        self.draw_chart(painter, self.width(), self.height())

    def set_profile_color(self, color: QColor):
        try:
            self.profile_color = QColor(color)
        except Exception:
            self.profile_color = QColor(0, 100, 255)
        self.update()

    def set_highlight_ranges(self, ranges: Sequence[Tuple[float, float]], *, label: str = ""):
        cleaned: List[Tuple[float, float]] = []
        try:
            for a, b in ranges or []:
                _skip_310 = False
                try:
                    a = float(a)
                    b = float(b)
                except Exception as _exc:
                    log_swallowed("terrain_profile_dialog.set_highlight_ranges", _exc)
                    log_swallowed("tools/terrain_profile_dialog.py:313 (set_highlight_ranges)", _exc)
                    _skip_310 = True
                if _skip_310:
                    continue
                if not math.isfinite(a) or not math.isfinite(b):
                    continue
                if b < a:
                    a, b = b, a
                if b <= a:
                    continue
                cleaned.append((a, b))
        except Exception:
            cleaned = []
        cleaned.sort(key=lambda t: t[0])
        self.highlight_ranges = cleaned
        self.highlight_label = str(label or "")
        self.update()

    def set_overlay_ranges(
        self,
        ranges: Sequence[Tuple[float, float]],
        *,
        label: str = "",
        color: Optional[QColor] = None,
    ):
        cleaned: List[Tuple[float, float]] = []
        try:
            for a, b in ranges or []:
                _skip_340 = False
                try:
                    a = float(a)
                    b = float(b)
                except Exception as _exc:
                    log_swallowed("terrain_profile_dialog.set_overlay_ranges", _exc)
                    log_swallowed("tools/terrain_profile_dialog.py:343 (set_overlay_ranges)", _exc)
                    _skip_340 = True
                if _skip_340:
                    continue
                if not math.isfinite(a) or not math.isfinite(b):
                    continue
                if b < a:
                    a, b = b, a
                if b <= a:
                    continue
                cleaned.append((a, b))
        except Exception:
            cleaned = []
        cleaned.sort(key=lambda t: t[0])
        self.overlay_ranges = cleaned
        self.overlay_label = str(label or "")
        if color is not None:
            try:
                self.overlay_color = QColor(color)
            except Exception as _exc:
                log_swallowed("tools/terrain_profile_dialog.py:361 (set_overlay_ranges)", _exc)
        self.update()

    def set_overlay_markers(self, markers: Sequence[Tuple[float, str]], *, color: Optional[QColor] = None):
        cleaned: List[Tuple[float, str]] = []
        try:
            for d, lbl in markers or []:
                _skip_369 = False
                try:
                    d = float(d)
                except Exception as _exc:
                    log_swallowed("terrain_profile_dialog.set_overlay_markers", _exc)
                    log_swallowed("tools/terrain_profile_dialog.py:371 (set_overlay_markers)", _exc)
                    _skip_369 = True
                if _skip_369:
                    continue
                if not math.isfinite(d):
                    continue
                cleaned.append((d, str(lbl or "")))
        except Exception:
            cleaned = []
        cleaned.sort(key=lambda t: t[0])
        self.overlay_markers = cleaned
        if color is not None:
            try:
                self.overlay_marker_color = QColor(color)
            except Exception as _exc:
                log_swallowed("tools/terrain_profile_dialog.py:384 (set_overlay_markers)", _exc)
        self.update()

    def draw_chart(self, painter, width, height):
        if not self.data:
            painter.drawText(QRectF(0, 0, width, height), Qt.AlignmentFlag.AlignCenter, "데이터가 없습니다.")
            return
        # Guard against a zero-length profile line (identical start/end): total_d==0
        # would make visible_range 0 and divide-by-zero in the sample loop below.
        if not self.total_d or self.total_d <= 0:
            painter.drawText(QRectF(0, 0, width, height), Qt.AlignmentFlag.AlignCenter, "단면 길이가 0입니다.")
            return

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Margins
        left, top, right, bottom = self.margin_left, self.margin_top, self.margin_right, self.margin_bottom
        w = width - left - right
        h = height - top - bottom
        
        # Calculate visible range based on zoom
        visible_range = self.total_d / self.zoom_level
        view_start = self.pan_offset
        view_end = view_start + visible_range
        
        # Fill background
        painter.fillRect(0, 0, width, height, QColor(255, 255, 255))

        # Draw background/grid. Tick labels get their own dark pen: drawn with
        # the light grid pen they were near-invisible in the exported image.
        grid_pen = QPen(QColor(220, 220, 220), 1, Qt.PenStyle.DashLine)
        label_pen = QPen(self.axis_label_color)
        num_grids_y = 5
        for i in range(num_grids_y + 1):
            y = top + h - (i / num_grids_y) * h
            painter.setPen(grid_pen)
            painter.drawLine(left, int(y), left + w, int(y))
            val = self.min_e + (i / num_grids_y) * (self.max_e - self.min_e)
            painter.setPen(label_pen)
            painter.drawText(5, int(y + 5), f"{val:.1f}m")

        num_grids_x = 5
        for i in range(num_grids_x + 1):
            x = left + (i / num_grids_x) * w
            painter.setPen(grid_pen)
            painter.drawLine(int(x), top, int(x), top + h)
            dist = view_start + (i / num_grids_x) * visible_range
            painter.setPen(label_pen)
            painter.drawText(int(x - 15), top + h + 20, f"{dist:.0f}m")

        # Vertical exaggeration of THIS drawing (pixels per metre vertically
        # over pixels per metre horizontally) and the curve method, stated on
        # the chart itself so an exported image carries them.
        self.vertical_exaggeration = None
        try:
            x_px_per_m = float(w) / float(visible_range)
            y_px_per_m = float(h) / float(self.max_e - self.min_e)
            if x_px_per_m > 0 and y_px_per_m > 0:
                self.vertical_exaggeration = y_px_per_m / x_px_per_m
        except (ZeroDivisionError, TypeError, ValueError):
            self.vertical_exaggeration = None
        notes = []
        if self.vertical_exaggeration is not None:
            notes.append(f"수직 과장 {self.vertical_exaggeration:.1f}배")
        if self.smooth_window > 0:
            spacing = self._sample_spacing_m()
            win_txt = f" (약 {2 * self.smooth_window * spacing:.0f}m 창)" if spacing else ""
            notes.append(f"곡선: ±{self.smooth_window}점 이동평균{win_txt}")
        else:
            notes.append("곡선: 원시 샘플")
        if any(p.get('gap_before') for p in self.data):
            notes.append("끊긴 구간: NoData")
        if self.zoom_level > 1.0:
            notes.append(f"확대: {self.zoom_level:.1f}x")
        self.annotation_lines = notes
        painter.setPen(label_pen)
        painter.drawText(left, max(12, top - 10), " | ".join(notes))

        # Draw axis
        painter.setPen(QPen(Qt.GlobalColor.black, 2))
        painter.drawLine(left, top, left, top + h)            # Y axis
        painter.drawLine(left, top + h, left + w, top + h)    # X axis
        
        # Highlight ranges (behind the profile line)
        if self.highlight_ranges:
            try:
                painter.save()
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(self.highlight_color))
                for d0, d1 in self.highlight_ranges:
                    if d1 <= view_start or d0 >= view_end:
                        continue
                    a = max(float(d0), float(view_start))
                    b = min(float(d1), float(view_end))
                    if b <= a:
                        continue
                    x0 = left + ((a - view_start) / visible_range) * w
                    x1 = left + ((b - view_start) / visible_range) * w
                    painter.drawRect(QRectF(x0, top, max(0.0, x1 - x0), h))
                if self.highlight_label:
                    painter.setPen(QPen(QColor(80, 80, 80)))
                    painter.drawText(left + 6, top + 18, self.highlight_label)
                painter.restore()
            except Exception:
                try:
                    painter.restore()
                except Exception as _exc:
                    log_swallowed("tools/terrain_profile_dialog.py:457 (draw_chart)", _exc)

        # Overlay ranges (behind the profile line, below hover/markers)
        if self.overlay_ranges:
            try:
                painter.save()
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(self.overlay_color))
                for d0, d1 in self.overlay_ranges:
                    if d1 <= view_start or d0 >= view_end:
                        continue
                    a = max(float(d0), float(view_start))
                    b = min(float(d1), float(view_end))
                    if b <= a:
                        continue
                    x0 = left + ((a - view_start) / visible_range) * w
                    x1 = left + ((b - view_start) / visible_range) * w
                    painter.drawRect(QRectF(x0, top, max(0.0, x1 - x0), h))
                if self.overlay_label:
                    painter.setPen(QPen(QColor(60, 120, 60)))
                    # Avoid overlapping with AOI label (which is drawn at top+18)
                    painter.drawText(left + 6, top + 34, self.overlay_label)
                painter.restore()
            except Exception:
                try:
                    painter.restore()
                except Exception as _exc:
                    log_swallowed("tools/terrain_profile_dialog.py:484 (draw_chart)", _exc)

        # Draw the profile line, broken at NoData gaps (a gap is never bridged
        # by a straight line that would look like measured terrain).
        runs_px = []
        cur = []
        for p in self.smooth_data:
            if p.get('gap_before') and cur:
                runs_px.append(cur)
                cur = []
            dist = p['distance']
            if dist < view_start or dist > view_end:
                continue
            px = left + ((dist - view_start) / visible_range) * w
            py = top + h - ((p['elevation'] - self.min_e) / (self.max_e - self.min_e)) * h
            cur.append((px, py))
        if cur:
            runs_px.append(cur)

        path = QPainterPath()
        for run in runs_px:
            path.moveTo(run[0][0], run[0][1])
            for px, py in run[1:]:
                path.lineTo(px, py)

        painter.setPen(QPen(self.profile_color, 2))
        painter.drawPath(path)
        # An isolated single valid sample between two gaps: a dot, not nothing.
        painter.setBrush(QBrush(self.profile_color))
        for run in runs_px:
            if len(run) == 1:
                painter.drawEllipse(QPointF(run[0][0], run[0][1]), 2, 2)

        # Draw Fill (area below profile), one polygon per run
        painter.setOpacity(0.15)
        painter.setBrush(QBrush(self.profile_color))
        painter.setPen(Qt.PenStyle.NoPen)
        for run in runs_px:
            if len(run) < 2:
                continue
            fill_path = QPainterPath()
            fill_path.moveTo(run[0][0], top + h)
            for px, py in run:
                fill_path.lineTo(px, py)
            fill_path.lineTo(run[-1][0], top + h)
            fill_path.closeSubpath()
            painter.drawPath(fill_path)

        painter.setOpacity(1.0)

        # Overlay markers (on top of profile line)
        if self.overlay_markers:
            try:
                show_labels = len(self.overlay_markers) <= 12
                painter.save()
                if self.overlay_label and not self.overlay_ranges:
                    try:
                        painter.setPen(QPen(QColor(60, 120, 60)))
                        painter.drawText(left + 6, top + 34, self.overlay_label)
                    except Exception as _exc:
                        log_swallowed("tools/terrain_profile_dialog.py:539 (draw_chart)", _exc)
                painter.setPen(QPen(self.overlay_marker_color, 1, Qt.PenStyle.DashLine))
                for dist, lbl in self.overlay_markers:
                    if dist < view_start or dist > view_end:
                        continue
                    x = left + ((dist - view_start) / visible_range) * w

                    # Vertical reference line
                    painter.drawLine(int(x), top, int(x), top + h)

                    # Marker on profile (nearest smoothed point)
                    try:
                        closest = min(self.smooth_data, key=lambda p: abs(float(p["distance"]) - float(dist)))
                        elev = float(closest.get("elevation"))
                        if math.isfinite(elev):
                            y = top + h - ((elev - self.min_e) / (self.max_e - self.min_e)) * h
                            painter.setPen(QPen(self.overlay_marker_color, 2))
                            painter.setBrush(QBrush(QColor(255, 255, 255)))
                            painter.drawEllipse(QPointF(x, y), 4, 4)
                    except Exception as _exc:
                        log_swallowed("terrain_profile_dialog.draw_chart", _exc)

                    if show_labels and lbl:
                        painter.setPen(QPen(QColor(30, 30, 30)))
                        painter.drawText(int(x) + 4, top + 14, lbl)
                painter.restore()
            except Exception:
                try:
                    painter.restore()
                except Exception as _exc:
                    log_swallowed("tools/terrain_profile_dialog.py:569 (draw_chart)", _exc)
         
        # Draw hover indicator
        if self.hover_distance is not None and view_start <= self.hover_distance <= view_end:
            hover_x = left + ((self.hover_distance - view_start) / visible_range) * w
            hover_y = top + h - ((self.hover_elevation - self.min_e) / (self.max_e - self.min_e)) * h
            
            # Vertical line
            painter.setPen(QPen(QColor(255, 0, 0, 150), 1, Qt.PenStyle.DashLine))
            painter.drawLine(int(hover_x), top, int(hover_x), top + h)
            
            # Point marker
            painter.setPen(QPen(QColor(255, 0, 0), 2))
            painter.setBrush(QBrush(QColor(255, 255, 255)))
            painter.drawEllipse(QPointF(hover_x, hover_y), 5, 5)
            
            # Info label
            painter.setPen(QPen(Qt.GlobalColor.black))
            info_text = f"{self.hover_distance:.1f}m / {self.hover_elevation:.1f}m"
            painter.drawText(int(hover_x) + 8, int(hover_y) - 5, info_text)

    def save_to_image(self, path):
        # Create image with higher resolution for better quality
        img_w, img_h = 1200, 800
        image = QImage(img_w, img_h, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.white)
        
        # Temporarily reset zoom for saving
        old_zoom = self.zoom_level
        old_pan = self.pan_offset
        self.zoom_level = 1.0
        self.pan_offset = 0
        
        painter = QPainter(image)
        self.draw_chart(painter, img_w, img_h)
        painter.end()
        # What the exported figure states (the on-screen values are redrawn below).
        self.export_vertical_exaggeration = self.vertical_exaggeration
        self.export_annotation_lines = list(self.annotation_lines)

        # Restore zoom
        self.zoom_level = old_zoom
        self.pan_offset = old_pan
        self.update()

        ext = os.path.splitext(str(path or ""))[1].lower()
        if ext == ".png":
            return image.save(path, "PNG")
        return image.save(path, "JPG", 95)


class TerrainProfileDialog(QtWidgets.QDialog, FORM_CLASS):
     
    def __init__(self, iface, parent=None):
        super(TerrainProfileDialog, self).__init__(parent)
        # Remember the last-used inputs between sessions (tools/dialog_memory.py).
        dialog_memory.attach(self, "terrain_profile")
        try:
            self.setWindowIcon(plugin_icon("profile.png"))
        except Exception as _exc:
            log_swallowed("terrain_profile_dialog.__init__ (icon)", _exc)
        self.setupUi(self)
        self.iface = iface
        self.canvas = iface.mapCanvas()
        
        # Custom Chart Widget
        self.chart = ProfileChartWidget()
        # Insert chart into layout (replace placeholder or add to vertical layout)
        # We named the layout chartLayout in UI
        self.chartLayout.insertWidget(0, self.chart)
        
        # Profile data
        self.points = []
        self.profile_data = []

        # Persistent profile layer (multi-profile support)
        self._profile_layer = None
        self._profile_layer_id = None
        self._ignore_selection_changed = False
        self._last_selected_fid = None
        self._ignore_current_layer_changed = False
        self._layer_tree_view = None
        self._single_layers_enabled = True

        # Optional: overlay another vector layer on the profile chart.
        self._overlay_layer = None
        self._overlay_selection_handler = None

        # Setup
        self.cmbDemLayer.setFilters(Qgis.LayerFilter.RasterLayer)

        # Extra options: fixed-length profile line + AOI highlight on chart
        self._last_profile_length_m: Optional[float] = None
        self._last_aoi_inside_m: Optional[float] = None
        self._last_num_samples: Optional[int] = None
        try:
            self.grpExtra = QtWidgets.QGroupBox("추가 옵션 (길이/AOI)", self)
            grid_extra = QtWidgets.QGridLayout(self.grpExtra)

            self.chkFixedLength = QtWidgets.QCheckBox("같은 길이로 단면선(고정 길이)", self.grpExtra)
            self.chkFixedLength.setChecked(False)
            self.chkFixedLength.setToolTip(
                "첫 점 이후 두 번째 클릭은 '방향'만 결정하고, 길이는 고정 길이(m)로 맞춥니다.\n"
                "비교 단면(같은 길이/같은 샘플 수)을 여러 개 만들 때 유용합니다."
            )

            self.spinFixedLength = QtWidgets.QDoubleSpinBox(self.grpExtra)
            self.spinFixedLength.setDecimals(1)
            self.spinFixedLength.setMinimum(0.0)
            self.spinFixedLength.setMaximum(10_000_000.0)
            self.spinFixedLength.setSingleStep(100.0)
            self.spinFixedLength.setValue(0.0)
            self.spinFixedLength.setSuffix(" m")
            self.spinFixedLength.setEnabled(False)
            self.spinFixedLength.setToolTip("고정 길이(m). 0이면 적용되지 않습니다.")

            self.btnUseLastLength = QtWidgets.QPushButton("최근 길이", self.grpExtra)
            self.btnUseLastLength.setEnabled(False)
            self.btnUseLastLength.setToolTip("가장 최근에 만든 단면선 길이를 고정 길이에 적용합니다.")

            self.cmbAoiLayer = QgsMapLayerComboBox(self.grpExtra)
            self.cmbAoiLayer.setFilters(Qgis.LayerFilter.VectorLayer)
            self.cmbAoiLayer.setToolTip(
                "조사대상지(AOI) 폴리곤 레이어를 선택하세요.\n"
                "- 선택 피처가 있으면 선택 피처만 사용합니다.\n"
                "- 단면 그래프에 AOI 내부 구간을 음영으로 표시할 수 있습니다."
            )

            self.chkShowAoiOnProfile = QtWidgets.QCheckBox("단면 그래프에 조사대상지(AOI) 구간 표시", self.grpExtra)
            self.chkShowAoiOnProfile.setChecked(True)
            self.chkShowAoiOnProfile.setToolTip(
                "단면선이 AOI 내부를 지나는 구간을 그래프 배경(음영)으로 표시합니다.\n"
                "구간과 'AOI 구간' 길이는 단면선과 AOI 폴리곤의 실제 기하 교차로 계산합니다\n"
                "(샘플 간격과 무관)."
            )

            grid_extra.addWidget(self.chkFixedLength, 0, 0, 1, 3)
            grid_extra.addWidget(QtWidgets.QLabel("고정 길이"), 1, 0)
            grid_extra.addWidget(self.spinFixedLength, 1, 1)
            grid_extra.addWidget(self.btnUseLastLength, 1, 2)
            grid_extra.addWidget(QtWidgets.QLabel("조사대상지(AOI)"), 2, 0)
            grid_extra.addWidget(self.cmbAoiLayer, 2, 1, 1, 2)
            grid_extra.addWidget(self.chkShowAoiOnProfile, 3, 0, 1, 3)

            self.chkSegmentStats = QtWidgets.QCheckBox("구간 통계(경사/누적상승) 계산", self.grpExtra)
            self.chkSegmentStats.setChecked(True)
            self.chkSegmentStats.setToolTip(
                "단면 프로파일에서 다음 통계를 계산합니다.\n"
                "- 구간별 평균 경사(예: 0–200m)\n"
                "- 누적 상승/하강\n"
                "CSV 저장 시 구간 요약표도 함께 저장됩니다."
            )

            self.spinSegmentLength = QtWidgets.QDoubleSpinBox(self.grpExtra)
            self.spinSegmentLength.setDecimals(0)
            self.spinSegmentLength.setMinimum(0.0)
            self.spinSegmentLength.setMaximum(1_000_000.0)
            self.spinSegmentLength.setSingleStep(50.0)
            self.spinSegmentLength.setValue(200.0)
            self.spinSegmentLength.setSuffix(" m")
            self.spinSegmentLength.setToolTip(
                "구간 통계에 사용할 거리 간격(m).\n"
                "예: 200m -> 0–200m, 200–400m ... 구간별 평균 경사.\n"
                "0이면 구간 통계를 계산하지 않습니다."
            )

            grid_extra.addWidget(QtWidgets.QLabel("구간 길이"), 4, 0)
            grid_extra.addWidget(self.spinSegmentLength, 4, 1)
            grid_extra.addWidget(self.chkSegmentStats, 4, 2)

            help_lbl = QtWidgets.QLabel(
                "TIP: value 비교용으로 같은 길이 단면을 만들거나,\n"
                "AOI 단면이라면 그래프에서 AOI 구간(배경 음영)을 확인할 수 있습니다.",
                self.grpExtra,
            )
            help_lbl.setWordWrap(True)
            help_lbl.setStyleSheet("color:#555;")
            grid_extra.addWidget(help_lbl, 5, 0, 1, 3)

            self.chkSmoothChart = QtWidgets.QCheckBox(
                f"그래프 곡선 평활화 (±{CHART_SMOOTH_HALF_WINDOW}점 이동평균)", self.grpExtra
            )
            self.chkSmoothChart.setChecked(False)
            self.chkSmoothChart.setToolTip(
                "끄면(기본) 그래프는 추출한 원시 샘플을 그대로 그립니다.\n"
                f"켜면 곡선만 앞뒤 {CHART_SMOOTH_HALF_WINDOW}개 샘플의 이동평균으로 그리며, 창 크기(m)가 그래프에 표시됩니다.\n"
                "이동평균은 좁은 도랑/둔덕의 깊이와 높이를 줄여 보이게 합니다.\n"
                "통계와 CSV는 항상 원시 샘플 값입니다."
            )
            grid_extra.addWidget(self.chkSmoothChart, 6, 0, 1, 3)

            try:
                idx = int(self.verticalLayout.indexOf(self.groupProfile))
                if idx >= 0:
                    self.verticalLayout.insertWidget(idx, self.grpExtra)
                else:
                    self.verticalLayout.insertWidget(3, self.grpExtra)
            except Exception:
                self.verticalLayout.insertWidget(3, self.grpExtra)

            self.chkFixedLength.toggled.connect(self._update_fixed_length_ui)
            self.btnUseLastLength.clicked.connect(self._use_last_length)
            self.chkShowAoiOnProfile.toggled.connect(self._refresh_aoi_highlight)
            self.cmbAoiLayer.layerChanged.connect(self._refresh_aoi_highlight)
            try:
                self.chkSegmentStats.toggled.connect(self.update_stats)
                self.spinSegmentLength.valueChanged.connect(self.update_stats)
                self.chkSmoothChart.toggled.connect(self._on_smoothing_toggled)
            except Exception as _exc:
                log_swallowed("tools/terrain_profile_dialog.py:758 (__init__)", _exc)
        except Exception:
            self.grpExtra = None
            self.chkSmoothChart = None
            self.chkFixedLength = None
            self.spinFixedLength = None
            self.btnUseLastLength = None
            self.cmbAoiLayer = None
            self.chkShowAoiOnProfile = None
            self.chkSegmentStats = None
            self.spinSegmentLength = None

        # Optional: show a selected vector layer on the profile chart (intersection/inside).
        try:
            self.grpOverlay = QtWidgets.QGroupBox("단면 오버레이 (레이어 표시)", self)
            grid_ov = QtWidgets.QGridLayout(self.grpOverlay)

            self.chkShowOverlayOnProfile = QtWidgets.QCheckBox("단면 그래프에 레이어 표시", self.grpOverlay)
            self.chkShowOverlayOnProfile.setChecked(False)
            self.chkShowOverlayOnProfile.setToolTip(
                "선택한 벡터 레이어를 단면 그래프에 표시합니다.\n"
                "- 면(폴리곤): 단면선이 내부를 지나는 구간을 배경(음영)으로 표시\n"
                "- 점/선: 단면선과 교차(또는 근접)하는 지점을 마커로 표시"
            )

            self.cmbOverlayLayer = QgsMapLayerComboBox(self.grpOverlay)
            self.cmbOverlayLayer.setFilters(Qgis.LayerFilter.VectorLayer)
            self.cmbOverlayLayer.setToolTip("단면에 표시할 벡터 레이어를 선택하세요.")

            self.chkOverlaySelectedOnly = QtWidgets.QCheckBox("선택 피처만 사용", self.grpOverlay)
            self.chkOverlaySelectedOnly.setChecked(False)
            self.chkOverlaySelectedOnly.setToolTip("레이어에서 선택한 피처만 단면 표시 대상으로 사용합니다.")

            help_lbl_ov = QtWidgets.QLabel(
                "TIP: 점/선 레이어는 교차지점 마커로, 폴리곤 레이어는 내부 구간 음영으로 표시됩니다.",
                self.grpOverlay,
            )
            help_lbl_ov.setWordWrap(True)
            help_lbl_ov.setStyleSheet("color:#555;")

            grid_ov.addWidget(self.chkShowOverlayOnProfile, 0, 0, 1, 3)
            grid_ov.addWidget(QtWidgets.QLabel("레이어"), 1, 0)
            grid_ov.addWidget(self.cmbOverlayLayer, 1, 1, 1, 2)
            grid_ov.addWidget(self.chkOverlaySelectedOnly, 2, 0, 1, 3)
            grid_ov.addWidget(help_lbl_ov, 3, 0, 1, 3)

            try:
                idx = int(self.verticalLayout.indexOf(self.groupProfile))
                if idx >= 0:
                    self.verticalLayout.insertWidget(idx, self.grpOverlay)
                else:
                    self.verticalLayout.insertWidget(3, self.grpOverlay)
            except Exception:
                self.verticalLayout.insertWidget(3, self.grpOverlay)

            self.chkShowOverlayOnProfile.toggled.connect(self._refresh_overlay)
            self.chkOverlaySelectedOnly.toggled.connect(self._refresh_overlay)
            self.cmbOverlayLayer.layerChanged.connect(self._on_overlay_layer_changed)
        except Exception:
            self.grpOverlay = None
            self.chkShowOverlayOnProfile = None
            self.cmbOverlayLayer = None
            self.chkOverlaySelectedOnly = None
        
        # Connect signals
        self.btnDrawLine.clicked.connect(self.start_drawing)
        self.btnClear.clicked.connect(self.clear_profile)
        self.btnExportCsv.clicked.connect(self.export_csv)
        self.btnExportImage.clicked.connect(self.export_image)
        self.btnClose.clicked.connect(self.cleanup_and_close)
        self._setup_help_button()

        try:
            self.btnClear.setText("현재 초기화")
            self.btnClear.setToolTip("현재 그래프/임시 표시만 초기화합니다. 저장된 단면선 레이어는 유지됩니다.")
        except Exception as _exc:
            log_swallowed("tools/terrain_profile_dialog.py:833 (__init__)", _exc)
        try:
            self.label_Header.setToolTip(
                "팁: 저장된 단면선 레이어에서 선을 '선택'하면 해당 단면이 자동으로 열립니다.\n"
                f"- 레이어 이름: {PROFILE_LAYER_NAME}"
            )
        except Exception as _exc:
            log_swallowed("tools/terrain_profile_dialog.py:840 (__init__)", _exc)

        # Optional: create a per-profile layer as well (so users can click a layer to reopen).
        try:
            self.chkSingleLayers = QtWidgets.QCheckBox("개별 레이어도 생성", self)
            self.chkSingleLayers.setObjectName("chkSingleLayers")
            self.chkSingleLayers.setChecked(True)
            self.chkSingleLayers.setToolTip(
                "단면선을 '1개=1개 레이어'로도 추가합니다.\n"
                "레이어 패널에서 해당 레이어를 클릭(현재 레이어)하면 단면 그래프가 자동으로 열립니다.\n"
                "많이 생성하면 레이어가 많아질 수 있어 필요할 때만 켜세요."
            )
            try:
                idx = int(self.horizontalLayout.indexOf(self.btnDrawLine))
                if idx >= 0:
                    self.horizontalLayout.insertWidget(idx, self.chkSingleLayers)
                else:
                    self.horizontalLayout.addWidget(self.chkSingleLayers)
            except Exception:
                self.horizontalLayout.addWidget(self.chkSingleLayers)
 
            def _sync_single_layers(on: bool):
                self._single_layers_enabled = bool(on)

            self.chkSingleLayers.toggled.connect(_sync_single_layers)
            self._single_layers_enabled = bool(self.chkSingleLayers.isChecked())
        except Exception:
            self.chkSingleLayers = None
            self._single_layers_enabled = True

        # Layer panel click → open profile (for per-profile layers).
        try:
            view = self.iface.layerTreeView()
            view.currentLayerChanged.connect(self._on_current_layer_changed)
            self._layer_tree_view = view
        except Exception:
            self._layer_tree_view = None
        
        # Rubber band for drawing line
        self.rubber_band = QgsRubberBand(self.canvas, Qgis.GeometryType.Line)
        self.rubber_band.setColor(QColor(255, 0, 0))
        self.rubber_band.setWidth(2)
        
        # Hover marker for showing position on map
        self.hover_marker = QgsRubberBand(self.canvas, Qgis.GeometryType.Point)
        self.hover_marker.setColor(QColor(255, 0, 0))
        self.hover_marker.setWidth(10)
        self.hover_marker.setIcon(RUBBER_BAND_CIRCLE)
        
        # Connect chart hover callback
        self.chart.on_hover_callback = self.show_position_on_map
        
        # Map tool
        self.map_tool = None
        self.original_tool = None

        # If the profile layer already exists in the project, hook selection to open profiles.
        try:
            layers = QgsProject.instance().mapLayersByName(PROFILE_LAYER_NAME)
            if layers:
                self._ensure_profile_layer_schema(layers[0])
                self._connect_profile_layer(layers[0])
        except Exception as _exc:
            log_swallowed("tools/terrain_profile_dialog.py:903 (__init__)", _exc)

    def _setup_help_button(self):
        try:
            self.btnHelp = QtWidgets.QPushButton("도움말", self)
            self.btnHelp.clicked.connect(self._on_help)

            layout = self.layout()
            if layout is None:
                return

            idx = -1
            try:
                idx = int(layout.indexOf(self.btnClose))
            except Exception:
                idx = -1

            if idx >= 0:
                layout.insertWidget(idx, self.btnHelp)
            else:
                layout.addWidget(self.btnHelp)
        except Exception as _exc:
            log_swallowed("terrain_profile_dialog._setup_help_button", _exc)

    def _on_help(self):
        try:
            plugin_dir = os.path.dirname(os.path.dirname(__file__))
            html = (
                "<h2>지형 단면 (Terrain Profile)</h2>"
                "<p>DEM 위에 단면선을 그려 고도 프로파일을 그래프로 표시하고, 통계/CSV/이미지로 내보냅니다.</p>"
                "<h3>기본 흐름</h3>"
                "<ol>"
                "<li>DEM 선택</li>"
                "<li>단면선 그리기(시작→끝)</li>"
                "<li>(옵션) AOI/오버레이 레이어 표시</li>"
                "<li>CSV/이미지 내보내기</li>"
                "</ol>"
                "<h3>팁</h3>"
                "<ul>"
                "<li>저장된 단면선 레이어에서 선을 선택하면 해당 단면이 자동으로 열립니다.</li>"
                "<li>고정 길이 옵션은 여러 단면을 같은 길이로 비교할 때 유용합니다.</li>"
                "<li><b>샘플링 방식:</b> 고도는 샘플 지점이 속한 DEM 셀의 값을 그대로 읽습니다"
                "(보간 없음 - QGIS 기본 단면 도구와 동일). 따라서 <b>샘플 간격(단면 길이 / 샘플 수)이"
                " DEM 셀 크기와 비슷해지도록</b> 샘플 수를 정하세요. 셀 크기보다 훨씬 촘촘하게 잡으면"
                " 같은 셀 값이 반복되는 계단만 늘어날 뿐 실제 정보가 늘지 않고, 훨씬 성기게 잡으면"
                " 좁은 능선이나 구곡을 통째로 건너뛸 수 있습니다."
                " (예: 5m DEM, 1,000m 단면 → 샘플 200개 내외)."
                " 샘플 수 N은 구간 수이며, 양 끝을 포함해 N+1개 지점에서 고도를 읽습니다.</li>"
                "<li><b>그래프 곡선:</b> 기본은 원시 샘플을 그대로 그립니다. '그래프 곡선 평활화'를 켜면"
                f" ±{CHART_SMOOTH_HALF_WINDOW}점 이동평균 곡선을 그리고 창 크기(m)를 그래프에 적습니다."
                " 통계와 CSV는 항상 원시 샘플 값입니다.</li>"
                "<li><b>수직 과장:</b> 그래프는 고도 범위에 맞춰 세로축을 늘리므로 수직 과장 배율이"
                " 화면과 내보낸 이미지 위쪽에 표시됩니다(이미지는 1200x800 기준 배율). 보고서에 그대로 옮겨 적으세요.</li>"
                "<li><b>NoData 구간:</b> DEM 밖이거나 NoData인 샘플은 버리고, 그 구간에서 그래프 선을 끊습니다."
                " 끊긴 구간은 누적 상승/하강, 경사 통계에서 제외되며 CSV의 GapBefore 열에 1로 표시됩니다.</li>"
                "<li><b>AOI 구간:</b> 단면선과 AOI 폴리곤의 실제 기하 교차로 계산합니다(샘플 간격과 무관).</li>"
                "<li>저장된 단면을 다시 열 때 그 단면을 만든 DEM이 프로젝트에 없으면, 현재 선택한 DEM으로"
                " 다시 계산할지 묻습니다(아니오를 고르면 열지 않습니다).</li>"
                "</ul>"
            )
            show_help_dialog(parent=self, title="지형 단면 도움말", html=html, plugin_dir=plugin_dir, tool_id="terrain_profile")
        except Exception:
            try:
                QMessageBox.information(self, "도움말", "README.md를 참고하세요.")
            except Exception as _exc:
                log_swallowed("tools/terrain_profile_dialog.py:951 (_on_help)", _exc)
    
    def show_position_on_map(self, x, y):
        """Show hover position on map"""
        if x is None or y is None:
            self.hover_marker.reset(Qgis.GeometryType.Point)
            try:
                self.hover_marker.hide()
            except Exception as _exc:
                log_swallowed("tools/terrain_profile_dialog.py:960 (show_position_on_map)", _exc)
        else:
            self.hover_marker.reset(Qgis.GeometryType.Point)
            self.hover_marker.addPoint(QgsPointXY(x, y))
            try:
                self.hover_marker.show()
            except Exception as _exc:
                log_swallowed("tools/terrain_profile_dialog.py:967 (show_position_on_map)", _exc)

    def _show_profile_line_on_map(self, *, start: QgsPointXY, end: QgsPointXY, color: Optional[QColor] = None):
        """Show the current profile line as a rubber band so users can see where it was drawn."""
        if start is None or end is None:
            return
        try:
            self.rubber_band.reset(Qgis.GeometryType.Line)
        except Exception:
            self.rubber_band.reset()
        try:
            self.rubber_band.addPoint(QgsPointXY(start))
            self.rubber_band.addPoint(QgsPointXY(end))
        except Exception:
            return
        try:
            self.rubber_band.setColor(QColor(color) if color is not None else QColor(255, 0, 0))
        except Exception as _exc:
            log_swallowed("tools/terrain_profile_dialog.py:985 (_show_profile_line_on_map)", _exc)
        try:
            self.rubber_band.setWidth(3)
        except Exception as _exc:
            log_swallowed("tools/terrain_profile_dialog.py:989 (_show_profile_line_on_map)", _exc)
        try:
            self.rubber_band.show()
        except Exception as _exc:
            log_swallowed("tools/terrain_profile_dialog.py:993 (_show_profile_line_on_map)", _exc)

    def _smoothing_half_window(self) -> int:
        chk = getattr(self, "chkSmoothChart", None)
        try:
            return CHART_SMOOTH_HALF_WINDOW if (chk is not None and chk.isChecked()) else 0
        except Exception as _exc:
            log_swallowed("terrain_profile_dialog._smoothing_half_window", _exc)
            return 0

    def _on_smoothing_toggled(self, *_args):
        try:
            self.chart.set_smoothing(self._smoothing_half_window())
        except Exception as _exc:
            log_swallowed("terrain_profile_dialog._on_smoothing_toggled", _exc)
        self.update_stats()

    def _update_fixed_length_ui(self):
        enabled = False
        try:
            enabled = bool(self.chkFixedLength is not None and self.chkFixedLength.isChecked())
        except Exception:
            enabled = False

        try:
            if self.spinFixedLength is not None:
                self.spinFixedLength.setEnabled(enabled)
        except Exception as _exc:
            log_swallowed("tools/terrain_profile_dialog.py:1006 (_update_fixed_length_ui)", _exc)

        try:
            if enabled and self.spinFixedLength is not None:
                cur = float(self.spinFixedLength.value())
                if cur <= 0 and self._last_profile_length_m is not None and math.isfinite(self._last_profile_length_m):
                    self.spinFixedLength.setValue(float(self._last_profile_length_m))
        except Exception as _exc:
            log_swallowed("terrain_profile_dialog._update_fixed_length_ui", _exc)

        try:
            if self.btnUseLastLength is not None:
                last_len = self._last_profile_length_m
                can_use = enabled and all(
                    (
                        last_len is not None,
                        math.isfinite(last_len),
                        last_len > 0,
                    )
                )
                self.btnUseLastLength.setEnabled(bool(can_use))
        except Exception as _exc:
            log_swallowed("terrain_profile_dialog._update_fixed_length_ui", _exc)

    def _use_last_length(self):
        try:
            if self._last_profile_length_m is None or not math.isfinite(self._last_profile_length_m):
                return
            if self.spinFixedLength is not None:
                self.spinFixedLength.setValue(float(self._last_profile_length_m))
            if self.chkFixedLength is not None:
                self.chkFixedLength.setChecked(True)
        except Exception as _exc:
            log_swallowed("terrain_profile_dialog._use_last_length", _exc)

    def _fixed_length_m(self) -> Optional[float]:
        try:
            if self.chkFixedLength is None or not self.chkFixedLength.isChecked():
                return None
            if self.spinFixedLength is None:
                return None
            v = float(self.spinFixedLength.value())
            if math.isfinite(v) and v > 0:
                return v
        except Exception as _exc:
            log_swallowed("terrain_profile_dialog._fixed_length_m", _exc)
        return None

    @staticmethod
    def _metric_ellipsoid() -> str:
        """Return an ellipsoid acronym that makes QgsDistanceArea report meters.

        QgsProject.ellipsoid() returns the literal string "NONE" when the
        project has ellipsoidal measurement switched off, and "NONE" is truthy
        - so the familiar ``ellipsoid() or "WGS84"`` fallback never fires and
        measureLine() quietly hands back source-CRS units (degrees on a
        geographic canvas). Everything downstream here is labelled in meters
        (chart x-axis, CSV export, the layer's distance_m metadata, the
        sample-spacing check), so normalise empty/"NONE" to WGS84 instead.
        """
        try:
            ellipsoid = (QgsProject.instance().ellipsoid() or "").strip()
        except Exception as _exc:
            log_swallowed("terrain_profile_dialog._metric_ellipsoid", _exc)
            ellipsoid = ""
        if not ellipsoid or ellipsoid.upper() == "NONE":
            return "WGS84"
        return ellipsoid

    @staticmethod
    def _measures_in_meters(distance_area: QgsDistanceArea) -> bool:
        """True when this QgsDistanceArea's lengths really are meters.

        QgsDistanceArea only converts to meters while an ellipsoid is in use;
        otherwise measureLine() returns raw source-CRS units. Callers that mix
        a measured distance with a meter-converted DEM cell size must check
        this first - without an ellipsoid the two numbers are ~1e5 apart and
        anything derived from comparing them is noise.
        """
        try:
            return bool(distance_area.willUseEllipsoid())
        except Exception as _exc:
            log_swallowed("terrain_profile_dialog._measures_in_meters", _exc)
            return False

    def _distance_area_canvas(self) -> QgsDistanceArea:
        """Build the QgsDistanceArea every length measurement in this dialog uses.

        Centralised on purpose: the ellipsoid normalisation above is the only
        thing standing between a geographic project and degree-valued
        "meters", and it used to be copy-pasted (and wrong) in three places.
        """
        canvas_crs = self.canvas.mapSettings().destinationCrs()
        distance_area = QgsDistanceArea()
        distance_area.setSourceCrs(canvas_crs, QgsProject.instance().transformContext())
        distance_area.setEllipsoid(self._metric_ellipsoid())
        try:
            distance_area.setEllipsoidalMode(True)
        except AttributeError as _exc:
            log_swallowed("tools/terrain_profile_dialog.py:1062 (_distance_area_canvas)", _exc)
        return distance_area

    def _end_point_fixed_length(self, *, start: QgsPointXY, direction_point: QgsPointXY, length_m: float) -> QgsPointXY:
        dx = float(direction_point.x() - start.x())
        dy = float(direction_point.y() - start.y())
        if dx == 0.0 and dy == 0.0:
            return QgsPointXY(direction_point)

        try:
            distance_area = self._distance_area_canvas()
            cur = float(distance_area.measureLine(start, direction_point))
        except Exception:
            cur = 0.0

        if not math.isfinite(cur) or cur <= 0:
            # Fallback to planar scaling (best effort)
            norm = math.sqrt(dx * dx + dy * dy)
            if norm <= 0:
                return QgsPointXY(direction_point)
            scale = float(length_m) / norm
            return QgsPointXY(start.x() + dx * scale, start.y() + dy * scale)

        scale_total = float(length_m) / cur
        end = QgsPointXY(start.x() + dx * scale_total, start.y() + dy * scale_total)
        # Refine a couple of times (useful in geographic CRS where degrees->meters is nonlinear)
        for _ in range(2):
            try:
                cur2 = float(distance_area.measureLine(start, end))
            except Exception:
                break
            if not math.isfinite(cur2) or cur2 <= 0:
                break
            scale_total *= float(length_m) / cur2
            end = QgsPointXY(start.x() + dx * scale_total, start.y() + dy * scale_total)
        return end

    def update_preview(self, point: QgsPointXY):
        """Update temporary rubber band preview while drawing the profile line."""
        try:
            if len(self.points) != 1:
                return
            start = self.points[0]
            end = QgsPointXY(point)
            fixed = self._fixed_length_m()
            if fixed is not None:
                end = self._end_point_fixed_length(start=start, direction_point=end, length_m=fixed)
            self.rubber_band.reset(Qgis.GeometryType.Line)
            self.rubber_band.addPoint(start)
            self.rubber_band.addPoint(end)
            self.rubber_band.show()
        except Exception as _exc:
            log_swallowed("terrain_profile_dialog.update_preview", _exc)

    def _compute_aoi_highlight_ranges(self) -> List[Tuple[float, float]]:
        """Return AOI intersection ranges (m along the profile) from the exact line/AOI intersection."""
        self._last_aoi_inside_m = None
        if not self.profile_data:
            return []
        try:
            if self.chkShowAoiOnProfile is None or not self.chkShowAoiOnProfile.isChecked():
                return []
        except Exception:
            return []

        aoi_layer = None
        try:
            aoi_layer = self.cmbAoiLayer.currentLayer() if self.cmbAoiLayer is not None else None
        except Exception:
            aoi_layer = None
        if aoi_layer is None or not isinstance(aoi_layer, QgsVectorLayer):
            return []
        try:
            if aoi_layer.geometryType() != Qgis.GeometryType.Polygon:
                return []
        except Exception:
            return []

        feats = []
        try:
            feats = aoi_layer.selectedFeatures()
        except Exception:
            feats = []
        if not feats:
            try:
                feats = list(aoi_layer.getFeatures())
            except Exception:
                feats = []
        if not feats:
            return []

        geoms = []
        for ft in feats:
            _skip_1156 = False
            try:
                g = ft.geometry()
                if g is None or g.isEmpty():
                    continue
                geoms.append(g)
            except Exception as _exc:
                log_swallowed("terrain_profile_dialog._compute_aoi_highlight_ranges", _exc)
                log_swallowed("tools/terrain_profile_dialog.py:1161 (_compute_aoi_highlight_ranges)", _exc)
                _skip_1156 = True
            if _skip_1156:
                continue
        if not geoms:
            return []

        aoi_geom = None
        try:
            aoi_geom = QgsGeometry.unaryUnion(geoms)
        except Exception:
            aoi_geom = None
        if aoi_geom is None or aoi_geom.isEmpty():
            try:
                g0 = None
                for g in geoms:
                    g0 = g if g0 is None else g0.combine(g)
                aoi_geom = g0
            except Exception:
                aoi_geom = None
        if aoi_geom is None or aoi_geom.isEmpty():
            return []

        # Transform AOI geometry to canvas CRS once.
        try:
            canvas_crs = self.canvas.mapSettings().destinationCrs()
            aoi_crs = aoi_layer.crs()
            if aoi_crs != canvas_crs:
                ct = QgsCoordinateTransform(aoi_crs, canvas_crs, QgsProject.instance())
                aoi_geom = QgsGeometry(aoi_geom)  # copy
                aoi_geom.transform(ct)
        except Exception:
            return []

        # Exact geometric intersection of the profile line with the AOI (the
        # same fraction-along-the-line mapping the overlay uses), not the
        # first/last inside SAMPLE - that under-read every crossing by up to
        # one sample spacing at each boundary (80 m reported for a true 90 m).
        start_canvas, end_canvas, total_m = self._profile_line_canvas_and_length()
        if start_canvas is None or total_m is None:
            return []
        try:
            inter = aoi_geom.intersection(QgsGeometry.fromPolylineXY([start_canvas, end_canvas]))
        except Exception as _exc:
            log_swallowed("terrain_profile_dialog._compute_aoi_highlight_ranges", _exc)
            return []
        ranges = _intersection_ranges_m(inter, start_canvas, end_canvas, total_m)

        inside_len = 0.0
        try:
            inside_len = float(sum((b - a) for a, b in ranges if b > a))
        except Exception:
            inside_len = 0.0
        if math.isfinite(inside_len) and inside_len > 0:
            self._last_aoi_inside_m = inside_len

        return ranges

    def _profile_line_canvas_and_length(self):
        """(start, end, total_m) of the current profile line in canvas CRS, or (None, None, None)."""
        start_canvas = end_canvas = None
        try:
            if len(self.points) >= 2:
                start_canvas = QgsPointXY(self.points[0])
                end_canvas = QgsPointXY(self.points[1])
            elif self.profile_data:
                start_canvas = QgsPointXY(float(self.profile_data[0]["x"]), float(self.profile_data[0]["y"]))
                end_canvas = QgsPointXY(float(self.profile_data[-1]["x"]), float(self.profile_data[-1]["y"]))
        except Exception as _exc:
            log_swallowed("terrain_profile_dialog._profile_line_canvas_and_length", _exc)
            start_canvas = end_canvas = None
        if start_canvas is None or end_canvas is None:
            return None, None, None
        total_m = self._last_profile_length_m
        if total_m is None or not math.isfinite(float(total_m)) or float(total_m) <= 0:
            try:
                total_m = float(self._distance_area_canvas().measureLine(start_canvas, end_canvas))
            except Exception as _exc:
                log_swallowed("terrain_profile_dialog._profile_line_canvas_and_length", _exc)
                total_m = None
        if total_m is None or not math.isfinite(float(total_m)) or float(total_m) <= 0:
            return None, None, None
        return start_canvas, end_canvas, float(total_m)

    def _refresh_aoi_highlight(self, *_args):
        """Recompute AOI highlight ranges for the current profile (if any)."""
        try:
            if not self.profile_data:
                self._last_aoi_inside_m = None
                try:
                    self.chart.set_highlight_ranges([], label="")
                except Exception as _exc:
                    log_swallowed("tools/terrain_profile_dialog.py:1246 (_refresh_aoi_highlight)", _exc)
                return

            ranges = self._compute_aoi_highlight_ranges()
            label = ""
            if ranges:
                try:
                    lyr = self.cmbAoiLayer.currentLayer() if self.cmbAoiLayer is not None else None
                    label = f"AOI: {lyr.name()}" if lyr is not None else "AOI"
                except Exception:
                    label = "AOI"
            try:
                self.chart.set_highlight_ranges(ranges, label=label)
            except Exception as _exc:
                log_swallowed("tools/terrain_profile_dialog.py:1260 (_refresh_aoi_highlight)", _exc)
            try:
                self.update_stats()
            except Exception as _exc:
                log_swallowed("tools/terrain_profile_dialog.py:1264 (_refresh_aoi_highlight)", _exc)
        except Exception as _exc:
            log_swallowed("terrain_profile_dialog._refresh_aoi_highlight", _exc)

    def _on_overlay_layer_changed(self, layer):
        """Reconnect selectionChanged handler for the overlay layer and refresh overlay."""
        # Disconnect previous handler
        try:
            if self._overlay_layer is not None and self._overlay_selection_handler is not None:
                self._overlay_layer.selectionChanged.disconnect(self._overlay_selection_handler)
        except Exception as _exc:
            log_swallowed("tools/terrain_profile_dialog.py:1275 (_on_overlay_layer_changed)", _exc)

        self._overlay_layer = layer if isinstance(layer, QgsVectorLayer) else None
        self._overlay_selection_handler = None

        if self._overlay_layer is not None:
            try:
                handler = lambda *_args: self._refresh_overlay()
                self._overlay_selection_handler = handler
                self._overlay_layer.selectionChanged.connect(handler)
            except Exception:
                self._overlay_selection_handler = None

        self._refresh_overlay()

    def _refresh_overlay(self, *_args):
        """Recompute overlay (ranges/markers) for the current profile and update the chart."""
        try:
            if not hasattr(self, "chart") or self.chart is None:
                return

            # Clear overlay if disabled or no profile
            try:
                enabled = bool(self.chkShowOverlayOnProfile is not None and self.chkShowOverlayOnProfile.isChecked())
            except Exception:
                enabled = False

            if (not enabled) or (not self.profile_data):
                try:
                    self.chart.set_overlay_ranges([], label="")
                except Exception as _exc:
                    log_swallowed("tools/terrain_profile_dialog.py:1306 (_refresh_overlay)", _exc)
                try:
                    self.chart.set_overlay_markers([])
                except Exception as _exc:
                    log_swallowed("tools/terrain_profile_dialog.py:1310 (_refresh_overlay)", _exc)
                return

            layer = None
            try:
                layer = self.cmbOverlayLayer.currentLayer() if self.cmbOverlayLayer is not None else None
            except Exception:
                layer = None
            if layer is None or not isinstance(layer, QgsVectorLayer) or not layer.isValid():
                try:
                    self.chart.set_overlay_ranges([], label="")
                except Exception as _exc:
                    log_swallowed("tools/terrain_profile_dialog.py:1322 (_refresh_overlay)", _exc)
                try:
                    self.chart.set_overlay_markers([])
                except Exception as _exc:
                    log_swallowed("tools/terrain_profile_dialog.py:1326 (_refresh_overlay)", _exc)
                return

            # Profile endpoints (canvas CRS)
            start_canvas = None
            end_canvas = None
            try:
                if len(self.points) >= 2:
                    start_canvas = QgsPointXY(self.points[0])
                    end_canvas = QgsPointXY(self.points[1])
            except Exception:
                start_canvas = None
                end_canvas = None

            if start_canvas is None or end_canvas is None:
                try:
                    start_canvas = QgsPointXY(float(self.profile_data[0]["x"]), float(self.profile_data[0]["y"]))
                    end_canvas = QgsPointXY(float(self.profile_data[-1]["x"]), float(self.profile_data[-1]["y"]))
                except Exception:
                    start_canvas = None
                    end_canvas = None

            if start_canvas is None or end_canvas is None:
                try:
                    self.chart.set_overlay_ranges([], label="")
                except Exception as _exc:
                    log_swallowed("tools/terrain_profile_dialog.py:1352 (_refresh_overlay)", _exc)
                try:
                    self.chart.set_overlay_markers([])
                except Exception as _exc:
                    log_swallowed("tools/terrain_profile_dialog.py:1356 (_refresh_overlay)", _exc)
                return

            # Total distance (meters) consistent with profile chart.
            total_distance_m = None
            try:
                if self._last_profile_length_m is not None and math.isfinite(self._last_profile_length_m):
                    total_distance_m = float(self._last_profile_length_m)
            except Exception:
                total_distance_m = None
            if total_distance_m is None or not math.isfinite(total_distance_m) or total_distance_m <= 0:
                try:
                    total_distance_m = float(self._distance_area_canvas().measureLine(start_canvas, end_canvas))
                except Exception:
                    total_distance_m = None
            if total_distance_m is None or not math.isfinite(total_distance_m) or total_distance_m <= 0:
                return

            vx = float(end_canvas.x() - start_canvas.x())
            vy = float(end_canvas.y() - start_canvas.y())
            vv = float(vx * vx + vy * vy)
            if vv <= 0:
                return

            def _fraction_for_xy(x: float, y: float) -> float:
                try:
                    t = ((float(x) - float(start_canvas.x())) * vx + (float(y) - float(start_canvas.y())) * vy) / vv
                except Exception:
                    t = 0.0
                if t < 0.0:
                    return 0.0
                if t > 1.0:
                    return 1.0
                return float(t)

            canvas_crs = self.canvas.mapSettings().destinationCrs()
            layer_crs = None
            try:
                layer_crs = layer.crs()
            except Exception:
                layer_crs = canvas_crs

            ct = None
            ct_inv = None
            try:
                if layer_crs != canvas_crs:
                    ct = QgsCoordinateTransform(layer_crs, canvas_crs, QgsProject.instance())
                    ct_inv = QgsCoordinateTransform(canvas_crs, layer_crs, QgsProject.instance())
            except Exception:
                ct = None
                ct_inv = None

            line_geom = QgsGeometry.fromPolylineXY([start_canvas, end_canvas])

            # Pixel-based tolerance (map units) for near-misses (mostly for point layers).
            tol_mu = 0.0
            try:
                tol_mu = float(self.canvas.mapUnitsPerPixel()) * 8.0
            except Exception:
                tol_mu = 0.0
            if not math.isfinite(tol_mu) or tol_mu < 0:
                tol_mu = 0.0

            selected_only = False
            try:
                selected_only = bool(self.chkOverlaySelectedOnly is not None and self.chkOverlaySelectedOnly.isChecked())
            except Exception:
                selected_only = False

            # Iterate candidate features (best-effort bbox filter when not using selected features).
            feats_iter = None
            if selected_only:
                try:
                    feats_iter = layer.selectedFeatures()
                except Exception:
                    feats_iter = []
            else:
                try:
                    rect = line_geom.boundingBox()
                    if tol_mu > 0:
                        rect.grow(tol_mu * 2.0)
                    if ct_inv is not None:
                        rect = ct_inv.transformBoundingBox(rect)
                    feats_iter = layer.getFeatures(QgsFeatureRequest().setFilterRect(rect))
                except Exception:
                    feats_iter = layer.getFeatures()

            # Best-effort feature label
            def _feature_label(ft: QgsFeature) -> str:
                try:
                    for name in ("name", "label", "title", "id"):
                        idx = layer.fields().indexFromName(name)
                        if idx >= 0:
                            v = ft.attribute(name)
                            if v is not None and str(v).strip():
                                return str(v).strip()
                except Exception as _exc:
                    log_swallowed("terrain_profile_dialog._feature_label", _exc)
                try:
                    for fld in layer.fields():
                        if fld.type() == FT_STRING:
                            v = ft.attribute(fld.name())
                            if v is not None and str(v).strip():
                                return str(v).strip()
                except Exception as _exc:
                    log_swallowed("tools/terrain_profile_dialog.py:1461 (_feature_label)", _exc)
                try:
                    return str(int(ft.id()))
                except Exception:
                    return ""

            markers: List[Tuple[float, str]] = []
            ranges: List[Tuple[float, float]] = []

            geom_type = None
            try:
                geom_type = int(layer.geometryType())
            except Exception:
                geom_type = None

            for ft in feats_iter:
                try:
                    g = ft.geometry()
                except Exception:
                    g = None
                if g is None or g.isEmpty():
                    continue

                _skip_1485 = False
                try:
                    g2 = QgsGeometry(g)
                    if ct is not None:
                        g2.transform(ct)
                except Exception as _exc:
                    log_swallowed("terrain_profile_dialog._refresh_overlay", _exc)
                    log_swallowed("tools/terrain_profile_dialog.py:1489 (_refresh_overlay)", _exc)
                    _skip_1485 = True
                if _skip_1485:
                    continue

                # Polygon: inside-segments on the profile line
                if geom_type == Qgis.GeometryType.Polygon:
                    try:
                        inter = g2.intersection(line_geom)
                    except Exception:
                        inter = None
                    if inter is None or inter.isEmpty():
                        continue

                    # Segment ranges (line geometry)
                    _skip_1503 = False
                    try:
                        if inter.type() == Qgis.GeometryType.Line:
                            segs = []
                            if inter.isMultipart():
                                segs = inter.asMultiPolyline() or []
                            else:
                                seg = inter.asPolyline() or []
                                if seg:
                                    segs = [seg]
                            for seg in segs:
                                if not seg or len(seg) < 2:
                                    continue
                                t_vals = []
                                for p in (seg[0], seg[-1]):
                                    _skip_1517 = False
                                    try:
                                        t_vals.append(_fraction_for_xy(float(p.x()), float(p.y())))
                                    except Exception as _exc:
                                        log_swallowed("terrain_profile_dialog._refresh_overlay", _exc)
                                        log_swallowed("tools/terrain_profile_dialog.py:1519 (_refresh_overlay)", _exc)
                                        _skip_1517 = True
                                    if _skip_1517:
                                        continue
                                if len(t_vals) < 2:
                                    continue
                                a = min(t_vals) * total_distance_m
                                b = max(t_vals) * total_distance_m
                                if math.isfinite(a) and math.isfinite(b) and b > a:
                                    ranges.append((a, b))
                        elif inter.type() == Qgis.GeometryType.Point:
                            pts = []
                            if inter.isMultipart():
                                pts = inter.asMultiPoint() or []
                            else:
                                pts = [inter.asPoint()]
                            for p in pts:
                                _skip_1535 = False
                                try:
                                    t = _fraction_for_xy(float(p.x()), float(p.y()))
                                    d = t * total_distance_m
                                    if math.isfinite(d):
                                        markers.append((d, _feature_label(ft)))
                                except Exception as _exc:
                                    log_swallowed("terrain_profile_dialog._refresh_overlay", _exc)
                                    log_swallowed("tools/terrain_profile_dialog.py:1540 (_refresh_overlay)", _exc)
                                    _skip_1535 = True
                                if _skip_1535:
                                    continue
                    except Exception as _exc:
                        log_swallowed("terrain_profile_dialog._refresh_overlay", _exc)
                        log_swallowed("tools/terrain_profile_dialog.py:1543 (_refresh_overlay)", _exc)
                        _skip_1503 = True
                    if _skip_1503:
                        continue
                    continue

                # Lines: intersection points (or overlap segments)
                if geom_type == Qgis.GeometryType.Line:
                    try:
                        inter = g2.intersection(line_geom)
                    except Exception:
                        inter = None
                    if inter is None or inter.isEmpty():
                        continue
                    lbl = _feature_label(ft)
                    _skip_1557 = False
                    try:
                        if inter.type() == Qgis.GeometryType.Point:
                            pts = []
                            if inter.isMultipart():
                                pts = inter.asMultiPoint() or []
                            else:
                                pts = [inter.asPoint()]
                            for p in pts:
                                _skip_1565 = False
                                try:
                                    t = _fraction_for_xy(float(p.x()), float(p.y()))
                                    d = t * total_distance_m
                                    if math.isfinite(d):
                                        markers.append((d, lbl))
                                except Exception as _exc:
                                    log_swallowed("terrain_profile_dialog._refresh_overlay", _exc)
                                    log_swallowed("tools/terrain_profile_dialog.py:1570 (_refresh_overlay)", _exc)
                                    _skip_1565 = True
                                if _skip_1565:
                                    continue
                        elif inter.type() == Qgis.GeometryType.Line:
                            segs = []
                            if inter.isMultipart():
                                segs = inter.asMultiPolyline() or []
                            else:
                                seg = inter.asPolyline() or []
                                if seg:
                                    segs = [seg]
                            for seg in segs:
                                if not seg or len(seg) < 2:
                                    continue
                                _skip_1584 = False
                                try:
                                    t0 = _fraction_for_xy(float(seg[0].x()), float(seg[0].y()))
                                    t1 = _fraction_for_xy(float(seg[-1].x()), float(seg[-1].y()))
                                    d0 = min(t0, t1) * total_distance_m
                                    d1 = max(t0, t1) * total_distance_m
                                    if math.isfinite(d0) and math.isfinite(d1) and d1 > d0:
                                        markers.append((d0, lbl))
                                        markers.append((d1, lbl))
                                except Exception as _exc:
                                    log_swallowed("terrain_profile_dialog._refresh_overlay", _exc)
                                    log_swallowed("tools/terrain_profile_dialog.py:1592 (_refresh_overlay)", _exc)
                                    _skip_1584 = True
                                if _skip_1584:
                                    continue
                    except Exception as _exc:
                        log_swallowed("terrain_profile_dialog._refresh_overlay", _exc)
                        log_swallowed("tools/terrain_profile_dialog.py:1595 (_refresh_overlay)", _exc)
                        _skip_1557 = True
                    if _skip_1557:
                        continue
                    continue

                # Points: near the profile line (tolerance)
                if geom_type == Qgis.GeometryType.Point:
                    lbl = _feature_label(ft)
                    _skip_1603 = False
                    try:
                        pts = []
                        if g2.isMultipart():
                            pts = g2.asMultiPoint() or []
                        else:
                            pts = [g2.asPoint()]
                        for p in pts:
                            _skip_1610 = False
                            try:
                                pg = QgsGeometry.fromPointXY(QgsPointXY(p))
                                if tol_mu > 0:
                                    if float(line_geom.distance(pg)) > float(tol_mu):
                                        continue
                                else:
                                    if float(line_geom.distance(pg)) > 0.0:
                                        continue
                                t = _fraction_for_xy(float(p.x()), float(p.y()))
                                d = t * total_distance_m
                                if math.isfinite(d):
                                    markers.append((d, lbl))
                            except Exception as _exc:
                                log_swallowed("terrain_profile_dialog._refresh_overlay", _exc)
                                log_swallowed("tools/terrain_profile_dialog.py:1622 (_refresh_overlay)", _exc)
                                _skip_1610 = True
                            if _skip_1610:
                                continue
                    except Exception as _exc:
                        log_swallowed("terrain_profile_dialog._refresh_overlay", _exc)
                        log_swallowed("tools/terrain_profile_dialog.py:1625 (_refresh_overlay)", _exc)
                        _skip_1603 = True
                    if _skip_1603:
                        continue

            # Merge overlapping ranges
            merged_ranges: List[Tuple[float, float]] = []
            try:
                ranges.sort(key=lambda t: t[0])
                for a, b in ranges:
                    if not merged_ranges:
                        merged_ranges.append((a, b))
                        continue
                    pa, pb = merged_ranges[-1]
                    if a <= pb + 0.5:
                        merged_ranges[-1] = (pa, max(pb, b))
                    else:
                        merged_ranges.append((a, b))
            except Exception:
                merged_ranges = ranges

            # Merge close markers
            merged_markers: List[Tuple[float, str]] = []
            try:
                markers.sort(key=lambda t: t[0])
                for d, lbl in markers:
                    if not merged_markers:
                        merged_markers.append((d, lbl))
                        continue
                    pd, pl = merged_markers[-1]
                    if abs(float(d) - float(pd)) <= 0.5:
                        # Keep the first label; avoid exploding labels.
                        continue
                    merged_markers.append((d, lbl))
            except Exception:
                merged_markers = markers

            layer_label = ""
            try:
                layer_label = f"레이어: {layer.name()}"
            except Exception:
                layer_label = "레이어"

            try:
                self.chart.set_overlay_ranges(merged_ranges, label=layer_label)
            except Exception as _exc:
                log_swallowed("tools/terrain_profile_dialog.py:1669 (_refresh_overlay)", _exc)
            try:
                self.chart.set_overlay_markers(merged_markers)
            except Exception as _exc:
                log_swallowed("tools/terrain_profile_dialog.py:1673 (_refresh_overlay)", _exc)
        except Exception as _exc:
            log_swallowed("terrain_profile_dialog._refresh_overlay", _exc)
    
    def start_drawing(self):
        """Start drawing profile line on map"""
        dem_layer = self.cmbDemLayer.currentLayer()
        if not dem_layer:
            push_message(self.iface, "오류", "DEM 래스터를 선택해주세요", level=2)
            restore_ui_focus(self)
            return
        self.points = []
        self.rubber_band.reset()
        try:
            # Always start drawing with a clear, visible preview style.
            self.rubber_band.setColor(QColor(255, 0, 0))
            self.rubber_band.setWidth(2)
        except Exception as _exc:
            log_swallowed("tools/terrain_profile_dialog.py:1691 (start_drawing)", _exc)
        
        # Save original tool and set our tool
        self.original_tool = self.canvas.mapTool()
        self.map_tool = ProfileLineTool(self.canvas, self)
        self.canvas.setMapTool(self.map_tool)

        fixed = self._fixed_length_m()
        if fixed is not None:
            push_message(
                self.iface,
                "지형 단면",
                f"고정 길이 {fixed:.0f}m: 시작점을 클릭한 뒤, 방향만 클릭하세요 (2번)",
                level=0,
            )
        else:
            push_message(self.iface, "지형 단면", "지도에서 시작점과 끝점을 클릭하세요 (2번)", level=0)
        self.hide()
    
    def add_point(self, point):
        """Add point to profile line"""
        if point is None:
            return
        if len(self.points) >= 2:
            return

        if len(self.points) == 0:
            self.points.append(QgsPointXY(point))
            try:
                self.rubber_band.reset(Qgis.GeometryType.Line)
            except Exception:
                self.rubber_band.reset()
            self.rubber_band.addPoint(self.points[0])
            self.rubber_band.show()
            return

        # Second click: apply fixed length (direction-only click) if enabled.
        start = self.points[0]
        end = QgsPointXY(point)
        fixed = self._fixed_length_m()
        if fixed is not None:
            end = self._end_point_fixed_length(start=start, direction_point=end, length_m=fixed)

        self.points = [start, end]
        self.rubber_band.reset(Qgis.GeometryType.Line)
        self.rubber_band.addPoint(start)
        self.rubber_band.addPoint(end)
        self.rubber_band.show()
        self.calculate_profile()
    
    def _dem_cell_size_m(self, dem_layer) -> Optional[float]:
        """Return the DEM cell size in meters, or None when it cannot be determined.

        A geographic DEM reports its pixel size in degrees, so comparing it
        straight against a meter-based sample spacing would be off by ~1e5 and
        every profile would look "far too dense". Convert with the same
        111320 m/deg approximation the other tools use - this only feeds an
        order-of-magnitude warning, so a geodesic is not needed.
        """
        if dem_layer is None:
            return None
        try:
            px = abs(float(dem_layer.rasterUnitsPerPixelX() or 0.0))
            py = abs(float(dem_layer.rasterUnitsPerPixelY() or 0.0))
        except Exception as _exc:
            log_swallowed("terrain_profile_dialog._dem_cell_size_m", _exc)
            return None
        sizes = [v for v in (px, py) if v > 0]
        if not sizes:
            return None
        # Narrowest axis: that is the resolution a ridge/gully has to survive.
        cell_m = min(sizes)
        try:
            crs = dem_layer.crs()
            if crs is not None and crs.isValid() and crs.isGeographic():
                cell_m *= 111320.0
        except Exception as _exc:
            log_swallowed("terrain_profile_dialog._dem_cell_size_m", _exc)
        return float(cell_m)

    def _check_sample_spacing(
        self,
        *,
        dem_layer,
        total_distance_m: float,
        num_samples: int,
        distance_area: Optional[QgsDistanceArea] = None,
    ) -> Optional[float]:
        """Return meters-per-sample, warning when it is badly matched to the DEM grid.

        Sampling is nearest-cell (see the sampling loops), so the DEM cell size
        is the real resolution limit: a spacing much finer than a cell only
        repeats the same cell value (a staircase, not extra detail), and a
        spacing much coarser can step straight over a narrow ridge or gully.
        A misconfigured sample count should announce itself in the log rather
        than quietly producing a plausible-looking but wrong profile.
        """
        try:
            num_samples = int(num_samples)
            spacing_m = float(total_distance_m) / num_samples if num_samples > 0 else 0.0
        except (TypeError, ValueError, ZeroDivisionError) as _exc:
            log_swallowed("terrain_profile_dialog._check_sample_spacing", _exc)
            return None
        if spacing_m <= 0:
            return None

        cell_m = self._dem_cell_size_m(dem_layer)
        if cell_m is None or cell_m <= 0:
            return spacing_m

        # The cell size above is in meters. If the distance that produced
        # spacing_m is not, the two are ~1e5 apart and the comparison below
        # would fire on every run - so stay quiet instead of crying wolf.
        if distance_area is not None and not self._measures_in_meters(distance_area):
            log_message(
                "TerrainProfile: 프로젝트에 타원체가 설정되지 않아 거리 단위가 미터인지 확인할 수 없어 "
                "샘플 간격 점검을 건너뜁니다.",
                level=Qgis.MessageLevel.Info,
            )
            return spacing_m

        # Thresholds are deliberately loose: within 4x finer / 2x coarser of the
        # cell size is normal practice and must not cry wolf on every run.
        if spacing_m * 4.0 < cell_m:
            log_message(
                f"TerrainProfile: 샘플 간격 {spacing_m:.2f}m가 DEM 셀 크기 {cell_m:.2f}m보다 훨씬 촘촘합니다. "
                "최근접 셀 추출이라 같은 값이 반복되는 계단만 늘어납니다. 샘플 수를 줄이세요.",
                level=Qgis.MessageLevel.Warning,
            )
        elif spacing_m > cell_m * 2.0:
            log_message(
                f"TerrainProfile: 샘플 간격 {spacing_m:.2f}m가 DEM 셀 크기 {cell_m:.2f}m보다 훨씬 성깁니다. "
                "좁은 능선이나 구곡이 통째로 누락될 수 있습니다. 샘플 수를 늘리세요.",
                level=Qgis.MessageLevel.Warning,
            )
        return spacing_m

    @staticmethod
    def _samples_done_text(valid_samples: int, num_samples: int) -> str:
        """N intervals sample N+1 points; say so, and how many were NoData/outside."""
        points = int(num_samples) + 1
        skipped = points - int(valid_samples)
        text = f"{int(valid_samples)}/{points}개 지점 유효 샘플 추출 완료!"
        if skipped > 0:
            text += f" (NoData/DEM 범위 밖 {skipped}개 제외)"
        return text

    def calculate_profile(self):
        """Sample the DEM along the drawn line and draw/store the elevation profile.

        Elevation comes from ``identify(..., IdentifyFormatValue)``, i.e. the
        value of the cell each sample point falls in - nearest-cell, no
        bilinear interpolation. That is deliberate: it matches QGIS's own
        elevation-profile tool, so ArchToolkit's numbers agree with the
        built-in tool instead of quietly differing by a smoothed half-cell.
        The cost is that the DEM cell size, not the sample count, sets the real
        resolution - hence the spacing check below.
        """
        dem_layer = self.cmbDemLayer.currentLayer()
        if not dem_layer or len(self.points) < 2:
            push_message(self.iface, "오류", "DEM 레이어가 선택되지 않았거나 점이 부족합니다.", level=2)
            restore_ui_focus(self)
            return

        # Live log window (non-modal) so users can see progress in real time.
        ensure_live_log_dialog(self.iface, owner=self, show=True, clear=True)
        try:
            start_canvas = self.points[0]
            end_canvas = self.points[1]
            num_samples = int(self.spinSamples.value())
            if num_samples <= 0:
                push_message(self.iface, "오류", "샘플 수는 1 이상이어야 합니다.", level=2)
                restore_ui_focus(self)
                return

            canvas_crs = self.canvas.mapSettings().destinationCrs()
            dem_crs = dem_layer.crs()
            
            self.profile_data = []

            # Measure in meters (ellipsoidal) so geographic CRS projects don't break stats/exports.
            # _distance_area_canvas() is what makes that true: it normalises a
            # missing or "NONE" project ellipsoid to WGS84, without which
            # measureLine() would return degrees here.
            distance_area = self._distance_area_canvas()
            total_distance_m = float(distance_area.measureLine(start_canvas, end_canvas))
            try:
                self._last_profile_length_m = float(total_distance_m)
                self._update_fixed_length_ui()
            except Exception as _exc:
                log_swallowed("terrain_profile_dialog.calculate_profile", _exc)
            
            sample_spacing_m = self._check_sample_spacing(
                dem_layer=dem_layer,
                total_distance_m=total_distance_m,
                num_samples=num_samples,
                distance_area=distance_area,
            )

            push_message(
                self.iface,
                "단면 분석",
                f"시작점에서 끝점까지 {total_distance_m:.1f}m, {num_samples}개 구간({num_samples + 1}개 지점) 샘플 추출 중...",
                level=0,
            )

            valid_samples = 0
            last_valid_i = None
            for i in range(num_samples + 1):
                fraction = i / num_samples
                x_canvas = start_canvas.x() + fraction * (end_canvas.x() - start_canvas.x())
                y_canvas = start_canvas.y() + fraction * (end_canvas.y() - start_canvas.y())
                sample_canvas = QgsPointXY(x_canvas, y_canvas)

                # Identify expects coordinates in DEM CRS.
                sample_dem = transform_point(sample_canvas, canvas_crs, dem_crs)
                
                # Nearest-cell: identify() returns the value of the cell the
                # point lands in, with no bilinear interpolation. See the
                # method docstring - this mirrors QGIS's own profile tool.
                result = dem_layer.dataProvider().identify(
                    sample_dem,
                    Qgis.RasterIdentifyFormat.Value
                )
                
                if result.isValid():
                    # Try band 1 first, then any available band
                    results_dict = result.results()
                    value = results_dict.get(1, None)
                    if value is None and results_dict:
                        # Fallback: get first available band value
                        value = list(results_dict.values())[0]

                    # NoData handling: exact float equality misses the float32
                    # round-trip of sentinels like -3.4e38 (leaked into charts
                    # as elevation), and NaN passed entirely (NaN != x is
                    # always True) — blanking the min/max scale. Use a finite
                    # check plus a relative-tolerance NoData comparison.
                    ok_val = False
                    if value is not None:
                        try:
                            fv = float(value)
                            if math.isfinite(fv):
                                nd = dem_layer.dataProvider().sourceNoDataValue(1)
                                if nd is None or not math.isfinite(float(nd)):
                                    ok_val = True
                                else:
                                    ndf = float(nd)
                                    ok_val = not math.isclose(fv, ndf, rel_tol=1e-6, abs_tol=1e-6)
                        except (TypeError, ValueError):
                            ok_val = False
                    if ok_val:
                        dist = fraction * total_distance_m
                        self.profile_data.append({
                            'distance': dist,
                            'elevation': float(value),
                            'x': x_canvas,
                            'y': y_canvas,
                            # NoData/outside samples since the previous valid one:
                            # the chart breaks here and the stats skip the segment.
                            'gap_before': last_valid_i is not None and i - last_valid_i > 1,
                        })
                        valid_samples += 1
                        last_valid_i = i
            self._last_num_samples = int(num_samples)

            if self.profile_data:
                # Save line to persistent layer first (assigns a per-profile color).
                profile_color = None
                try:
                    profile_color = self.save_line_to_layer(
                        total_distance_m,
                        dem_layer=dem_layer,
                        num_samples=num_samples,
                        sample_spacing_m=sample_spacing_m,
                    )
                except Exception as _exc:
                    log_swallowed("terrain_profile_dialog.calculate_profile (save_line_to_layer)", _exc)
                    profile_color = None

                if profile_color is not None:
                    try:
                        self.chart.set_profile_color(profile_color)
                    except Exception as _exc:
                        log_swallowed("tools/terrain_profile_dialog.py:1849 (calculate_profile)", _exc)

                self.chart.set_data(self.profile_data)
                self._refresh_aoi_highlight()
                self._refresh_overlay()
                self.btnExportCsv.setEnabled(True)
                self.btnExportImage.setEnabled(True)
                try:
                    self._show_profile_line_on_map(start=start_canvas, end=end_canvas, color=profile_color)
                except Exception as _exc:
                    log_swallowed("tools/terrain_profile_dialog.py:1859 (calculate_profile)", _exc)
                
                push_message(self.iface, "단면 완료", self._samples_done_text(valid_samples, num_samples), level=0)
            else:
                push_message(self.iface, "경고", "유효한 고도 데이터를 추출하지 못했습니다. DEM 범위를 확인하세요.", level=1)

        except Exception as e:
            push_message(self.iface, "오류", f"계산 실패: {str(e)}", level=2)
        finally:
            if self.original_tool:
                self.canvas.setMapTool(self.original_tool)
            restore_ui_focus(self)

    def _connect_profile_layer(self, layer: QgsVectorLayer):
        if layer is None or not isinstance(layer, QgsVectorLayer):
            return

        try:
            if self._profile_layer_id == layer.id():
                return
        except Exception as _exc:
            log_swallowed("tools/terrain_profile_dialog.py:1880 (_connect_profile_layer)", _exc)

        # Best-effort disconnect previous.
        try:
            if self._profile_layer is not None:
                self._profile_layer.selectionChanged.disconnect(self._on_profile_layer_selection_changed)
        except Exception as _exc:
            log_swallowed("tools/terrain_profile_dialog.py:1887 (_connect_profile_layer)", _exc)

        self._profile_layer = layer
        try:
            self._profile_layer_id = layer.id()
        except Exception:
            self._profile_layer_id = None

        try:
            layer.selectionChanged.connect(self._on_profile_layer_selection_changed)
        except Exception as _exc:
            log_swallowed("tools/terrain_profile_dialog.py:1898 (_connect_profile_layer)", _exc)

    def _on_current_layer_changed(self, layer):
        if self._ignore_current_layer_changed:
            return
        if layer is None:
            return
        if not isinstance(layer, QgsVectorLayer):
            return
        try:
            kind = str(layer.customProperty(PROFILE_KIND_PROP, "") or "")
        except Exception:
            kind = ""
        if kind != PROFILE_KIND_SINGLE:
            return

        try:
            ft = None
            for f in layer.getFeatures(QgsFeatureRequest().setLimit(1)):
                ft = f
                break
            if ft is None:
                return
            self._open_profile_from_feature(layer, ft)
        except Exception as e:
            log_message(f"TerrainProfile: open from layer click failed: {e}", level=Qgis.MessageLevel.Warning)

    def _on_profile_layer_selection_changed(self, *_args):
        if self._ignore_selection_changed:
            return
        layer = self._profile_layer
        if layer is None:
            return
        try:
            feats = layer.selectedFeatures()
        except Exception:
            feats = []
        if not feats:
            return

        ft = feats[0]
        try:
            fid = int(ft.id())
        except Exception:
            fid = None
        if fid is not None and fid == self._last_selected_fid:
            return
        self._last_selected_fid = fid

        try:
            self._open_profile_from_feature(layer, ft)
        except Exception as e:
            log_message(f"TerrainProfile: open from selection failed: {e}", level=Qgis.MessageLevel.Warning)

    def _open_profile_from_feature(self, layer: QgsVectorLayer, ft: QgsFeature):
        """Recompute and show profile when a saved profile line is selected."""
        dem_layer = None
        stored_dem_id = ""
        try:
            dem_id = ft.attribute("dem_id")
            if not is_null_value(dem_id) and str(dem_id).strip():
                stored_dem_id = str(dem_id).strip()
                dem_layer = QgsProject.instance().mapLayer(stored_dem_id)
        except Exception as _exc:
            log_swallowed("terrain_profile_dialog._open_profile_from_feature (dem_id)", _exc)
            dem_layer = None

        if dem_layer is None:
            # The DEM this line was sampled on is gone (removed, or re-added
            # under a new layer id). Silently sampling whatever DEM is selected
            # would show a different surface under the saved line's name, so
            # ask first and refuse unless the user explicitly agrees.
            current = self.cmbDemLayer.currentLayer()
            if current is None:
                push_message(self.iface, "오류", "프로파일을 열 DEM을 선택해주세요.", level=2)
                restore_ui_focus(self)
                return
            reply = QMessageBox.question(
                self,
                "지형 단면",
                f"이 단면선을 만든 DEM(레이어 id: {stored_dem_id or '기록 없음'})이 현재 프로젝트에 없습니다.\n"
                f"현재 선택한 DEM '{current.name()}'으로 다시 계산할까요?\n"
                "DEM이 다르면 고도 값이 원래 단면과 달라집니다.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                push_message(
                    self.iface,
                    "지형 단면",
                    "원래 DEM을 찾을 수 없어 저장된 단면을 열지 않았습니다. 원래 DEM을 프로젝트에 추가한 뒤 다시 선택하세요.",
                    level=1,
                )
                restore_ui_focus(self)
                return
            dem_layer = current
            push_message(
                self.iface,
                "지형 단면",
                f"원래 DEM이 없어 현재 DEM '{current.name()}'으로 다시 계산합니다(원래 단면과 값이 다를 수 있음).",
                level=1,
            )

        try:
            num_samples = int(ft.attribute("samples") or 0)
        except Exception:
            num_samples = 0
        if num_samples <= 0:
            num_samples = int(self.spinSamples.value())

        # Color (optional)
        try:
            r = int(ft.attribute("r"))
            g = int(ft.attribute("g"))
            b = int(ft.attribute("b"))
            self.chart.set_profile_color(QColor(r, g, b))
        except Exception as _exc:
            log_swallowed("terrain_profile_dialog._open_profile_from_feature", _exc)

        geom = ft.geometry()
        if geom is None or geom.isEmpty():
            return

        try:
            line_crs = layer.crs()
        except Exception:
            line_crs = self.canvas.mapSettings().destinationCrs()
        canvas_crs = self.canvas.mapSettings().destinationCrs()

        # Extract endpoints
        pts = None
        try:
            if geom.isMultipart():
                mp = geom.asMultiPolyline()
                if mp and mp[0]:
                    pts = mp[0]
            else:
                pts = geom.asPolyline()
        except Exception:
            pts = None
        if not pts or len(pts) < 2:
            return

        start_line = QgsPointXY(pts[0])
        end_line = QgsPointXY(pts[-1])
        start_canvas = transform_point(start_line, line_crs, canvas_crs)
        end_canvas = transform_point(end_line, line_crs, canvas_crs)

        self.points = [start_canvas, end_canvas]
        try:
            # Keep an on-top visual cue even when the line already exists in a layer.
            self._show_profile_line_on_map(start=start_canvas, end=end_canvas)
        except Exception as _exc:
            log_swallowed("tools/terrain_profile_dialog.py:2019 (_open_profile_from_feature)", _exc)
        self._compute_profile_for_points(dem_layer=dem_layer, start_canvas=start_canvas, end_canvas=end_canvas, num_samples=num_samples)
        restore_ui_focus(self)

    def _compute_profile_for_points(self, *, dem_layer, start_canvas: QgsPointXY, end_canvas: QgsPointXY, num_samples: int):
        """Recompute a stored profile line's chart from its endpoints.

        Same nearest-cell sampling as ``calculate_profile``: ``identify`` with
        ``IdentifyFormatValue`` reads the cell the sample point falls in, with
        no interpolation, so reopening a saved line reproduces QGIS's own
        profile numbers rather than a smoothed variant of them.
        """
        if dem_layer is None:
            return
        if num_samples <= 0:
            num_samples = 200

        ensure_live_log_dialog(self.iface, owner=self, show=True, clear=True)

        canvas_crs = self.canvas.mapSettings().destinationCrs()
        dem_crs = dem_layer.crs()

        self.profile_data = []

        # Meters guaranteed via the shared helper's ellipsoid normalisation
        # (see _metric_ellipsoid) - the reopen path must agree with the run path.
        distance_area = self._distance_area_canvas()
        total_distance_m = float(distance_area.measureLine(start_canvas, end_canvas))
        try:
            self._last_profile_length_m = float(total_distance_m)
            self._update_fixed_length_ui()
        except Exception as _exc:
            log_swallowed("terrain_profile_dialog._compute_profile_for_points", _exc)

        self._check_sample_spacing(
            dem_layer=dem_layer,
            total_distance_m=total_distance_m,
            num_samples=num_samples,
            distance_area=distance_area,
        )

        push_message(
            self.iface,
            "단면 분석",
            f"선택한 단면선 {total_distance_m:.1f}m, {num_samples}개 구간({num_samples + 1}개 지점) 샘플 추출 중...",
            level=0,
        )

        valid_samples = 0
        last_valid_i = None
        for i in range(num_samples + 1):
            fraction = i / num_samples
            x_canvas = start_canvas.x() + fraction * (end_canvas.x() - start_canvas.x())
            y_canvas = start_canvas.y() + fraction * (end_canvas.y() - start_canvas.y())
            sample_canvas = QgsPointXY(x_canvas, y_canvas)

            sample_dem = transform_point(sample_canvas, canvas_crs, dem_crs)
            # Nearest-cell, no interpolation (see the method docstring).
            result = dem_layer.dataProvider().identify(sample_dem, Qgis.RasterIdentifyFormat.Value)
            if not result.isValid():
                continue
            results_dict = result.results()
            value = results_dict.get(1, None)
            if value is None and results_dict:
                value = list(results_dict.values())[0]
            if value is None:
                continue
            # Same NoData handling as calculate_profile: exact == misses float32
            # sentinel round-trips and lets NaN through (NaN != x is always True).
            _skip_2078 = False
            try:
                elev = float(value)
            except (TypeError, ValueError) as _exc:
                log_swallowed("tools/terrain_profile_dialog.py:2080 (_compute_profile_for_points)", _exc)
                _skip_2078 = True
            if _skip_2078:
                continue
            if not math.isfinite(elev):
                continue
            try:
                nd = dem_layer.dataProvider().sourceNoDataValue(1)
                if nd is not None and math.isfinite(float(nd)) and math.isclose(
                    elev, float(nd), rel_tol=1e-6, abs_tol=1e-6
                ):
                    continue
            except Exception as _exc:
                log_swallowed("terrain_profile_dialog._compute_profile_for_points", _exc)
            dist = fraction * total_distance_m
            self.profile_data.append({
                "distance": dist,
                "elevation": elev,
                "x": x_canvas,
                "y": y_canvas,
                "gap_before": last_valid_i is not None and i - last_valid_i > 1,
            })
            valid_samples += 1
            last_valid_i = i
        self._last_num_samples = int(num_samples)

        if self.profile_data:
            self.chart.set_data(self.profile_data)
            self._refresh_aoi_highlight()
            self._refresh_overlay()
            self.btnExportCsv.setEnabled(True)
            self.btnExportImage.setEnabled(True)
            try:
                self._show_profile_line_on_map(start=start_canvas, end=end_canvas)
            except Exception as _exc:
                log_swallowed("tools/terrain_profile_dialog.py:2104 (_compute_profile_for_points)", _exc)
            push_message(self.iface, "단면 완료", self._samples_done_text(valid_samples, num_samples), level=0)
        else:
            push_message(self.iface, "경고", "유효한 고도 데이터를 추출하지 못했습니다. DEM 범위를 확인하세요.", level=1)

    def _ensure_profile_layer_schema(self, layer: QgsVectorLayer):
        """Ensure older projects' profile layers have the fields/style needed for multi-profile viewing."""
        if layer is None or not isinstance(layer, QgsVectorLayer):
            return

        pr = layer.dataProvider()
        required = [
            QgsField("no", FT_INT),
            QgsField("distance", FT_DOUBLE, "m", 10, 2),
            QgsField("min_elev", FT_DOUBLE, "m", 10, 2),
            QgsField("max_elev", FT_DOUBLE, "m", 10, 2),
            QgsField("date", FT_STRING),
            QgsField("dem_id", FT_STRING),
            QgsField("samples", FT_INT),
            QgsField("r", FT_INT),
            QgsField("g", FT_INT),
            QgsField("b", FT_INT),
        ]

        missing = []
        for f in required:
            try:
                if layer.fields().indexFromName(f.name()) < 0:
                    missing.append(f)
            except Exception:
                missing.append(f)

        if missing:
            try:
                pr.addAttributes(missing)
                layer.updateFields()
            except Exception as _exc:
                log_swallowed("tools/terrain_profile_dialog.py:2141 (_ensure_profile_layer_schema)", _exc)

        # If the layer was created before we had per-feature colors, populate r/g/b for existing features.
        try:
            idx_r = layer.fields().indexFromName("r")
            idx_g = layer.fields().indexFromName("g")
            idx_b = layer.fields().indexFromName("b")
            if idx_r >= 0 and idx_g >= 0 and idx_b >= 0:
                palette = _profile_color_palette()
                if palette:
                    changes = {}
                    for ft in layer.getFeatures():
                        try:
                            r0 = ft.attribute("r")
                            g0 = ft.attribute("g")
                            b0 = ft.attribute("b")
                        except Exception:
                            r0 = g0 = b0 = None
                        has_color = False
                        try:
                            has_color = (r0 is not None) and (g0 is not None) and (b0 is not None)
                        except Exception:
                            has_color = False
                        if has_color:
                            continue
                        try:
                            no = int(ft.attribute("no") or 0)
                        except Exception:
                            no = 0
                        if no <= 0:
                            try:
                                no = int(ft.id()) + 1
                            except Exception:
                                no = 1
                        c = palette[(no - 1) % len(palette)]
                        changes[int(ft.id())] = {
                            idx_r: int(c.red()),
                            idx_g: int(c.green()),
                            idx_b: int(c.blue()),
                        }
                    if changes:
                        pr.changeAttributeValues(changes)
                        layer.triggerRepaint()
        except Exception as _exc:
            log_swallowed("terrain_profile_dialog._ensure_profile_layer_schema", _exc)

        # Ensure renderer uses per-feature colors when possible.
        try:
            if layer.fields().indexFromName("r") >= 0:
                symbol = QgsLineSymbol.createSimple({'color': '0,0,0,200', 'width': '1.4'})
                sl = symbol.symbolLayer(0)
                if sl is not None:
                    sl.setDataDefinedProperty(
                        SYMBOL_PROPERTY_STROKE_COLOR,
                        QgsProperty.fromExpression('color_rgba("r","g","b",220)'),
                    )
                layer.setRenderer(QgsSingleSymbolRenderer(symbol))
                layer.triggerRepaint()
        except Exception as _exc:
            log_swallowed("terrain_profile_dialog._ensure_profile_layer_schema", _exc)

    def _ensure_single_group(self):
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        group = root.findGroup(PROFILE_GROUP_NAME)
        if group is None:
            group = root.insertGroup(0, PROFILE_GROUP_NAME)
        sub = group.findGroup(PROFILE_SINGLE_SUBGROUP_NAME)
        if sub is None:
            try:
                sub = group.insertGroup(0, PROFILE_SINGLE_SUBGROUP_NAME)
            except Exception:
                sub = group.addGroup(PROFILE_SINGLE_SUBGROUP_NAME)
            try:
                sub.setExpanded(False)
            except Exception as _exc:
                log_swallowed("tools/terrain_profile_dialog.py:2217 (_ensure_single_group)", _exc)
        return sub

    def _create_single_profile_layer(
        self,
        *,
        no: int,
        total_distance: float,
        min_elev: float,
        max_elev: float,
        start: QgsPointXY,
        end: QgsPointXY,
        dem_layer,
        num_samples: int,
        color: QColor,
        sample_spacing_m: Optional[float] = None,
    ):
        """Create a '1 profile = 1 layer' line layer so users can click the layer to reopen the chart."""
        if not self._single_layers_enabled:
            return None

        name = f"단면선_{int(no):03d} ({float(total_distance):.0f}m)"
        # setCrs, not "?crs=<authid>": a custom canvas CRS has no authid and the
        # URI form would silently leave the layer without a CRS.
        layer = QgsVectorLayer("LineString", name, "memory")
        layer.setCrs(self.canvas.mapSettings().destinationCrs())
        pr = layer.dataProvider()
        pr.addAttributes(
            [
                QgsField("no", FT_INT),
                QgsField("distance", FT_DOUBLE, "m", 10, 2),
                QgsField("min_elev", FT_DOUBLE, "m", 10, 2),
                QgsField("max_elev", FT_DOUBLE, "m", 10, 2),
                QgsField("date", FT_STRING),
                QgsField("dem_id", FT_STRING),
                QgsField("samples", FT_INT),
                QgsField("r", FT_INT),
                QgsField("g", FT_INT),
                QgsField("b", FT_INT),
            ]
        )
        layer.updateFields()

        f = QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry.fromPolylineXY([start, end]))
        f.setAttributes(
            [
                int(no),
                float(total_distance),
                float(min_elev),
                float(max_elev),
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                (dem_layer.id() if dem_layer is not None else ""),
                int(num_samples or 0),
                int(color.red()),
                int(color.green()),
                int(color.blue()),
            ]
        )
        pr.addFeatures([f])
        layer.updateExtents()

        # Fixed color for this layer.
        try:
            symbol = QgsLineSymbol.createSimple(
                {
                    "color": f"{int(color.red())},{int(color.green())},{int(color.blue())},220",
                    "width": "1.6",
                }
            )
            layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        except Exception as _exc:
            log_swallowed("terrain_profile_dialog._create_single_profile_layer", _exc)

        try:
            layer.setCustomProperty(PROFILE_KIND_PROP, PROFILE_KIND_SINGLE)
        except Exception as _exc:
            log_swallowed("tools/terrain_profile_dialog.py:2291 (_create_single_profile_layer)", _exc)
        try:
            # Record HOW the elevations were sampled, not just how many: the
            # numbers are only reproducible/comparable if a later reader knows
            # they are nearest-cell reads at this spacing (see calculate_profile).
            params = {
                "no": int(no),
                "distance_m": float(total_distance),
                "samples": int(num_samples or 0),
                "sampling": "nearest_cell_identify",
            }
            spacing = sample_spacing_m
            if spacing is None and num_samples:
                spacing = float(total_distance) / float(num_samples)
            if spacing is not None and float(spacing) > 0:
                params["sample_spacing_m"] = round(float(spacing), 4)
            set_archtoolkit_layer_metadata(
                layer,
                tool_id="terrain_profile",
                run_id=new_run_id("terrain_profile"),
                kind="profile_single",
                units="m",
                params=params,
            )
        except Exception as _exc:
            log_swallowed("terrain_profile_dialog._create_single_profile_layer", _exc)

        project = QgsProject.instance()
        sub = self._ensure_single_group()

        try:
            self._ignore_current_layer_changed = True
            project.addMapLayer(layer, False)
            sub.insertLayer(0, layer)
        finally:
            self._ignore_current_layer_changed = False

        return layer

    def get_or_create_profile_layer(self):
        """Get or create a memory layer to store profile lines"""
        layers = QgsProject.instance().mapLayersByName(PROFILE_LAYER_NAME)
        
        if layers:
            layer = layers[0]
            try:
                self._ensure_profile_layer_schema(layer)
                self._connect_profile_layer(layer)
            except Exception as _exc:
                log_swallowed("tools/terrain_profile_dialog.py:2330 (get_or_create_profile_layer)", _exc)
            try:
                if not str(layer.customProperty("archtoolkit/tool_id", "") or "").strip():
                    set_archtoolkit_layer_metadata(
                        layer,
                        tool_id="terrain_profile",
                        run_id=new_run_id("terrain_profile"),
                        kind="profile_lines",
                        units="m",
                    )
            except Exception as _exc:
                log_swallowed("terrain_profile_dialog.get_or_create_profile_layer", _exc)
            return layer
        
        # Create new memory layer (in the canvas CRS of NOW; lines drawn after a
        # later canvas CRS change are transformed into it by save_line_to_layer).
        layer = QgsVectorLayer("LineString", PROFILE_LAYER_NAME, "memory")
        layer.setCrs(self.canvas.mapSettings().destinationCrs())
        
        # Add fields
        pr = layer.dataProvider()
        pr.addAttributes([
            QgsField("no", FT_INT),
            QgsField("distance", FT_DOUBLE, "m", 10, 2),
            QgsField("min_elev", FT_DOUBLE, "m", 10, 2),
            QgsField("max_elev", FT_DOUBLE, "m", 10, 2),
            QgsField("date", FT_STRING),
            QgsField("dem_id", FT_STRING),
            QgsField("samples", FT_INT),
            QgsField("r", FT_INT),
            QgsField("g", FT_INT),
            QgsField("b", FT_INT),
        ])
        layer.updateFields()

        symbol = QgsLineSymbol.createSimple({'color': '0,0,0,200', 'width': '1.4'})
        try:
            sl = symbol.symbolLayer(0)
            if sl is not None:
                sl.setDataDefinedProperty(
                    SYMBOL_PROPERTY_STROKE_COLOR,
                    QgsProperty.fromExpression('color_rgba("r","g","b",220)'),
                )
        except Exception as _exc:
            log_swallowed("terrain_profile_dialog.get_or_create_profile_layer", _exc)
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))

        project = QgsProject.instance()
        root = project.layerTreeRoot()
        group = root.findGroup(PROFILE_GROUP_NAME)
        if group is None:
            group = root.insertGroup(0, PROFILE_GROUP_NAME)
        try:
            set_archtoolkit_layer_metadata(
                layer,
                tool_id="terrain_profile",
                run_id=new_run_id("terrain_profile"),
                kind="profile_lines",
                units="m",
            )
        except Exception as _exc:
            log_swallowed("terrain_profile_dialog.get_or_create_profile_layer", _exc)
        project.addMapLayer(layer, False)
        group.insertLayer(0, layer)

        try:
            # Keep group near top. removeChildNode() deletes the group (and the
            # layer node just inserted into it); move_group_to_top clones first.
            group = move_group_to_top(root, group)
        except Exception as _exc:
            log_swallowed("terrain_profile_dialog.get_or_create_profile_layer", _exc)

        try:
            self._ensure_profile_layer_schema(layer)
            self._connect_profile_layer(layer)
        except Exception as _exc:
            log_swallowed("tools/terrain_profile_dialog.py:2408 (get_or_create_profile_layer)", _exc)
        return layer

    def save_line_to_layer(
        self,
        total_distance,
        *,
        dem_layer=None,
        num_samples: int = 0,
        sample_spacing_m: Optional[float] = None,
    ) -> Optional[QColor]:
        """Save the profile line to the memory layer"""
        layer = self.get_or_create_profile_layer()
        if not layer: return

        try:
            self._connect_profile_layer(layer)
        except Exception as _exc:
            log_swallowed("tools/terrain_profile_dialog.py:2419 (save_line_to_layer)", _exc)

        elevs = [p['elevation'] for p in self.profile_data]

        next_no = int(layer.featureCount()) + 1
        palette = _profile_color_palette()
        color = palette[(next_no - 1) % len(palette)] if palette else QColor(0, 100, 255)
        
        # self.points are in the CURRENT canvas CRS; the library layer keeps the
        # CRS it was created with. Store in the layer's CRS, or a canvas CRS
        # change puts every later line in the wrong place (and reopening it
        # finds no DEM data). _open_profile_from_feature transforms back.
        canvas_crs = self.canvas.mapSettings().destinationCrs()
        line_pts = [
            QgsPointXY(transform_point(QgsPointXY(p), canvas_crs, layer.crs())) for p in self.points[:2]
        ]
        feat = QgsFeature(layer.fields())
        feat.setGeometry(QgsGeometry.fromPolylineXY(line_pts))
        feat.setAttributes([
            next_no,
            total_distance,
            min(elevs),
            max(elevs),
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            (dem_layer.id() if dem_layer is not None else ""),
            int(num_samples or 0),
            int(color.red()),
            int(color.green()),
            int(color.blue()),
        ])
        
        layer.dataProvider().addFeatures([feat])
        layer.updateExtents()
        layer.triggerRepaint()

        # Highlight the newly added line so users can immediately see which line matches the current chart.
        try:
            self._ignore_selection_changed = True
            try:
                layer.removeSelection()
            except Exception as _exc:
                log_swallowed("tools/terrain_profile_dialog.py:2452 (save_line_to_layer)", _exc)
            try:
                layer.selectByExpression(f"\"no\" = {int(next_no)}")
            except Exception as _exc:
                log_swallowed("terrain_profile_dialog.save_line_to_layer", _exc)
        finally:
            self._ignore_selection_changed = False

        # Optional: also create a dedicated layer for this profile (so users can click the layer to reopen).
        try:
            self._create_single_profile_layer(
                no=int(next_no),
                total_distance=float(total_distance),
                min_elev=float(min(elevs)),
                max_elev=float(max(elevs)),
                start=self.points[0],
                end=self.points[1],
                dem_layer=dem_layer,
                num_samples=int(num_samples or 0),
                color=color,
                sample_spacing_m=sample_spacing_m,
            )
        except Exception as _exc:
            log_swallowed("terrain_profile_dialog.save_line_to_layer", _exc)

        return color
    
    def update_stats(self):
        if not self.profile_data: return

        # NoData gap segments (samples dropped between two valid ones) are
        # excluded from ascent/descent/slope - bridging them with a straight
        # line would invent terrain the DEM does not have.
        st = _gap_aware_profile_stats(self.profile_data)
        elevs = st["elevs"]
        dists = st["dists"]
        total_d = float(dists[-1]) if dists else 0.0
        min_e = min(elevs)
        max_e = max(elevs)
        ascent = st["ascent"]
        descent = st["descent"]
        max_abs_slope = st["max_abs_slope"]
        mean_abs_slope = st["mean_abs_slope"]

        stats = (
            f"총 거리: {total_d:.1f}m | 고도 범위: {min_e:.1f}m - {max_e:.1f}m (차: {max_e - min_e:.1f}m)"
            f" | 누적상승: {ascent:.1f}m | 누적하강: {descent:.1f}m"
            f" | 평균경사(|%|): {mean_abs_slope:.1f}% | 최대경사(|%|): {max_abs_slope:.1f}%"
        )
        if st["n_gaps"] > 0:
            stats += (
                f" | NoData 구간: {st['n_gaps']}곳 {st['gap_len_m']:.1f}m"
                " (그래프에서 끊고 상승/경사 계산에서 제외)"
            )

        # Segment stats (example: 0–200m 평균경사)
        try:
            seg_len = float(self.spinSegmentLength.value()) if getattr(self, "spinSegmentLength", None) is not None else 0.0
            seg_enabled = bool(self.chkSegmentStats is not None and self.chkSegmentStats.isChecked())
        except Exception:
            seg_len = 0.0
            seg_enabled = False

        if seg_enabled and seg_len > 0 and total_d > 0 and len(dists) >= 2:
            try:
                seg0_end = min(total_d, seg_len)
                # Distance-weighted mean absolute slope for the first segment (gap segments excluded)
                _net, abs_dz_sum, _up, _dn, run_sum = _segment_slope_parts(self.profile_data, 0.0, seg0_end)
                seg0_mean_abs_slope = (abs_dz_sum / run_sum * 100.0) if run_sum > 1e-9 else 0.0
                stats += f" | 0–{seg0_end:.0f}m 평균경사: {seg0_mean_abs_slope:.1f}%"
            except Exception as _exc:
                log_swallowed("terrain_profile_dialog.update_stats", _exc)

        try:
            inside = float(self._last_aoi_inside_m) if self._last_aoi_inside_m is not None else None
            if inside is not None and math.isfinite(inside) and inside > 0:
                stats += f" | AOI 구간: {inside:.1f}m"
        except Exception as _exc:
            log_swallowed("terrain_profile_dialog.update_stats", _exc)
        # Say what the drawn curve is: the stats/CSV always use raw samples.
        k = self._smoothing_half_window()
        if k > 0:
            stats += f" | 차트 곡선: ±{k}점 이동평균(통계/CSV는 원시값)"
        else:
            stats += " | 차트 곡선: 원시 샘플"
        self.lblStats.setText(stats)

    def export_csv(self):
        if not self.profile_data: return

        path, _ = QFileDialog.getSaveFileName(
            self, "CSV 저장", os.path.expanduser("~"), "CSV Files (*.csv)"
        )
        if not path: return

        try:
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                # Gap-aware: a segment spanning dropped NoData samples gets no
                # slope and adds nothing to the cumulative ascent/descent.
                st = _gap_aware_profile_stats(self.profile_data)
                elevs = st["elevs"]
                dists = st["dists"]
                slopes = st["slopes"]
                cum_up = st["cum_up"]
                cum_dn = st["cum_dn"]

                total_d = float(dists[-1]) if dists else 0.0
                min_e = float(min(elevs)) if elevs else 0.0
                max_e = float(max(elevs)) if elevs else 0.0
                ascent = float(st["ascent"])
                descent = float(st["descent"])

                # Segment settings
                try:
                    seg_len = float(self.spinSegmentLength.value()) if getattr(self, "spinSegmentLength", None) is not None else 0.0
                    seg_enabled = bool(self.chkSegmentStats is not None and self.chkSegmentStats.isChecked())
                except Exception:
                    seg_len = 0.0
                    seg_enabled = False
                seg_len = seg_len if seg_enabled else 0.0

                seg_idx = []
                if seg_len > 0:
                    for d in dists:
                        try:
                            seg_idx.append(int(float(d) // float(seg_len)))
                        except Exception:
                            seg_idx.append(0)
                else:
                    seg_idx = [0 for _ in dists]

                # Summary block (key/value rows)
                writer.writerow(["metric", "value"])
                writer.writerow(["total_distance_m", round(total_d, 3)])
                writer.writerow(["min_elev_m", round(min_e, 3)])
                writer.writerow(["max_elev_m", round(max_e, 3)])
                writer.writerow(["elev_range_m", round(max_e - min_e, 3)])
                writer.writerow(["total_ascent_m", round(ascent, 3)])
                writer.writerow(["total_descent_m", round(descent, 3)])
                if self._last_num_samples:
                    writer.writerow(["sample_points", int(self._last_num_samples) + 1])
                writer.writerow(["valid_samples", len(self.profile_data)])
                writer.writerow(["nodata_gaps", int(st["n_gaps"])])
                writer.writerow(["nodata_gap_length_m", round(float(st["gap_len_m"]), 3)])
                writer.writerow(["sampling", "nearest_cell_identify"])
                if seg_len > 0:
                    writer.writerow(["segment_length_m", round(seg_len, 3)])
                try:
                    inside = float(self._last_aoi_inside_m) if self._last_aoi_inside_m is not None else None
                    if inside is not None and math.isfinite(inside) and inside > 0:
                        writer.writerow(["aoi_inside_m", round(float(inside), 3)])
                        writer.writerow(["aoi_method", "exact_line_polygon_intersection"])
                except Exception as _exc:
                    log_swallowed("terrain_profile_dialog.export_csv", _exc)

                writer.writerow([])

                # Per-sample table
                writer.writerow(
                    [
                        "Distance(m)",
                        "Elevation(m)",
                        "Slope(%)",
                        "CumAscent(m)",
                        "CumDescent(m)",
                        "Segment",
                        "X",
                        "Y",
                        "GapBefore",
                    ]
                )
                for i, p in enumerate(self.profile_data):
                    writer.writerow(
                        [
                            round(dists[i], 3),
                            round(elevs[i], 3),
                            ("" if slopes[i] is None else round(slopes[i], 3)),
                            round(cum_up[i], 3),
                            round(cum_dn[i], 3),
                            int(seg_idx[i]),
                            round(float(p["x"]), 6),
                            round(float(p["y"]), 6),
                            1 if p.get("gap_before") else 0,
                        ]
                    )

                # Segment summary table
                if seg_len > 0 and len(dists) >= 2 and total_d > 0:
                    writer.writerow([])
                    writer.writerow(
                        [
                            "SegStart(m)",
                            "SegEnd(m)",
                            "Run(m)",
                            "NetSlope(%)",
                            "MeanAbsSlope(%)",
                            "Ascent(m)",
                            "Descent(m)",
                        ]
                    )
                    nseg = int(math.ceil(total_d / seg_len))
                    for sidx in range(nseg):
                        s0 = float(sidx) * float(seg_len)
                        s1 = min(total_d, float(sidx + 1) * float(seg_len))
                        if float(s1 - s0) <= 1e-9:
                            continue
                        # Run(m) is the measured (non-gap) length inside the segment.
                        net_dz, abs_dz, seg_up, seg_dn, run = _segment_slope_parts(self.profile_data, s0, s1)
                        net_slope = (net_dz / run * 100.0) if run > 1e-9 else 0.0
                        mean_abs_slope = (abs_dz / run * 100.0) if run > 1e-9 else 0.0
                        writer.writerow(
                            [
                                round(s0, 3),
                                round(s1, 3),
                                round(run, 3),
                                round(net_slope, 3),
                                round(mean_abs_slope, 3),
                                round(seg_up, 3),
                                round(seg_dn, 3),
                            ]
                        )
            self.iface.messageBar().pushMessage("저장 완료", f"파일: {path}", level=0)
        except Exception as e:
            QMessageBox.critical(self, "오류", f"파일 저장 실패: {str(e)}")

    def export_image(self):
        if not self.profile_data: return
        
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "이미지 저장",
            os.path.expanduser("~"),
            "PNG Files (*.png);;JPEG Files (*.jpg)",
        )
        if not path: return
        try:
            if not os.path.splitext(path)[1]:
                if selected_filter and "PNG" in selected_filter:
                    path += ".png"
                else:
                    path += ".jpg"
        except Exception as _exc:
            log_swallowed("tools/terrain_profile_dialog.py:2736 (export_image)", _exc)
        
        try:
            success = self.chart.save_to_image(path)
            if success:
                self.iface.messageBar().pushMessage("저장 완료", f"이미지: {path}", level=0)
            else:
                QMessageBox.critical(self, "오류", "이미지 저장에 실패했습니다.")
        except Exception as e:
            QMessageBox.critical(self, "오류", f"이미지 저장 중 오류: {str(e)}")

    def clear_profile(self):
        self.points = []
        self.profile_data = []
        self._last_aoi_inside_m = None
        self.rubber_band.reset()
        try:
            self.rubber_band.hide()
        except Exception as _exc:
            log_swallowed("tools/terrain_profile_dialog.py:2755 (clear_profile)", _exc)
        self.hover_marker.reset(Qgis.GeometryType.Point)
        try:
            self.hover_marker.hide()
        except Exception as _exc:
            log_swallowed("tools/terrain_profile_dialog.py:2760 (clear_profile)", _exc)
        self.chart.set_data([])
        try:
            self.chart.set_profile_color(QColor(0, 100, 255))
        except Exception as _exc:
            log_swallowed("tools/terrain_profile_dialog.py:2765 (clear_profile)", _exc)
        self.lblStats.setText("지도를 클릭하여 단면을 생성하세요.")
        self.btnExportCsv.setEnabled(False)
        self.btnExportImage.setEnabled(False)
    
    def cleanup_and_close(self):
        """Explicit cleanup called when Close button is clicked"""
        self._cleanup()
        self.close()
    
    def reject(self):
        """Called when ESC is pressed or dialog is rejected"""
        self._cleanup()
        super().reject()
    
    def closeEvent(self, event):
        """Clean up: remove temporary layer and map tools when dialog closes"""
        self._cleanup()
        event.accept()

    def cleanup_for_unload(self):
        """Called from plugin unload to disconnect signals safely."""
        try:
            if self._profile_layer is not None:
                self._profile_layer.selectionChanged.disconnect(self._on_profile_layer_selection_changed)
        except Exception as _exc:
            log_swallowed("tools/terrain_profile_dialog.py:2791 (cleanup_for_unload)", _exc)
        try:
            if self._layer_tree_view is not None:
                self._layer_tree_view.currentLayerChanged.disconnect(self._on_current_layer_changed)
        except Exception as _exc:
            log_swallowed("tools/terrain_profile_dialog.py:2796 (cleanup_for_unload)", _exc)
        try:
            if self._overlay_layer is not None and self._overlay_selection_handler is not None:
                self._overlay_layer.selectionChanged.disconnect(self._overlay_selection_handler)
        except Exception as _exc:
            log_swallowed("tools/terrain_profile_dialog.py:2801 (cleanup_for_unload)", _exc)
        self._profile_layer = None
        self._overlay_layer = None
        self._overlay_selection_handler = None
        self._profile_layer_id = None
        self._layer_tree_view = None
        self._cleanup(remove_from_scene=True)

    def _cleanup(self, remove_from_scene: bool = False):
        """Internal cleanup - hides rubber bands and restores the map tool.

        remove_from_scene must stay False for ordinary close/ESC: this dialog
        is a reused singleton, and a QgsRubberBand removed from the canvas
        scene is never re-added by show() — the draw preview and hover marker
        would be invisible for every later session until QGIS restarts. Scene
        removal is only correct on plugin unload.

        Note: saved profile line layers are kept (multi-profile library).
        """
        try:
            # Clear rubber bands (reset+hide is enough between sessions)
            if hasattr(self, 'rubber_band') and self.rubber_band:
                self.rubber_band.reset(Qgis.GeometryType.Line)
                self.rubber_band.hide()
                if remove_from_scene and self.canvas and self.canvas.scene():
                    try:
                        self.canvas.scene().removeItem(self.rubber_band)
                    except Exception as _exc:
                        log_swallowed("tools/terrain_profile_dialog.py:2829 (_cleanup)", _exc)

            if hasattr(self, 'hover_marker') and self.hover_marker:
                self.hover_marker.reset(Qgis.GeometryType.Point)
                self.hover_marker.hide()
                if remove_from_scene and self.canvas and self.canvas.scene():
                    try:
                        self.canvas.scene().removeItem(self.hover_marker)
                    except Exception as _exc:
                        log_swallowed("tools/terrain_profile_dialog.py:2838 (_cleanup)", _exc)

            # Restore original map tool
            if hasattr(self, 'original_tool') and self.original_tool:
                try:
                    self.canvas.setMapTool(self.original_tool)
                except Exception as _exc:
                    log_swallowed("tools/terrain_profile_dialog.py:2845 (_cleanup)", _exc)

            # Refresh canvas
            if self.canvas:
                self.canvas.refresh()
        except Exception as e:
            log_message(f"Cleanup error: {e}", level=Qgis.MessageLevel.Warning)


class ProfileLineTool(QgsMapToolEmitPoint):
    def __init__(self, canvas, dialog):
        super().__init__(canvas)
        self.dialog = dialog
    
    def canvasReleaseEvent(self, event):
        point = self.toMapCoordinates(event.pos())
        self.dialog.add_point(point)

    def canvasMoveEvent(self, event):
        try:
            point = self.toMapCoordinates(event.pos())
            self.dialog.update_preview(point)
        except Exception as _exc:
            log_swallowed("tools/terrain_profile_dialog.py:2868 (canvasMoveEvent)", _exc)
