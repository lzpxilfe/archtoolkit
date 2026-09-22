#!/usr/bin/env python3
"""Render every ArchToolkit dialog (and two help windows) to PNG, headless.

    QT_QPA_PLATFORM=offscreen /usr/bin/python3.12 scripts/render_screenshots.py [out_dir]

Needs the QGIS Python (see tests/regression/README.md). A small synthetic
project (DEM, sites, survey area, parcels) is loaded first so the layer combos
show realistic names. Output goes to docs/images/ by default.
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests", "regression"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ARCHTOOLKIT_NO_DIALOG_MEMORY"] = "1"

import qgis_env  # noqa: E402

DIALOGS = [
    ("terrain_analysis_dialog", "TerrainAnalysisDialog", "terrain_analysis"),
    ("viewshed_dialog", "ViewshedDialog", "viewshed"),
    ("cost_surface_dialog", "CostSurfaceDialog", "cost_surface"),
    ("cost_network_dialog", "CostNetworkDialog", "cost_network"),
    ("spatial_network_dialog", "SpatialNetworkDialog", "spatial_network"),
    ("dem_generator_dialog", "DemGeneratorDialog", "dem_generator"),
    ("contour_extractor_dialog", "ContourExtractorDialog", "contour_extractor"),
    ("geology_zip_dialog", "GeologyZipDialog", "geology_zip"),
    ("geochem_polygonize_dialog", "GeoChemPolygonizeDialog", "geochem"),
    ("cadastral_overlap_dialog", "CadastralOverlapDialog", "cadastral_overlap"),
    ("align_export_dialog", "AlignExportDialog", "align_export"),
    ("ahp_suitability_dialog", "AhpSuitabilityDialog", "ahp"),
    ("trench_suggestion_dialog", "TrenchSuggestionDialog", "trench_suggestion"),
    ("distance_raster_dialog", "DistanceRasterDialog", "distance_raster"),
    ("covariate_report_dialog", "CovariateReportDialog", "covariate_report"),
    ("terrain_profile_dialog", "TerrainProfileDialog", "terrain_profile"),
    ("map_styling_dialog", "MapStylingDialog", "map_styling"),
    ("slope_aspect_drafting_dialog", "SlopeAspectDraftingDialog", "slope_aspect_drafting"),
    ("ai_report_dialog", "AiAoiReportDialog", "ai_report"),
]
MAX_WIDTH = 960


def _sample_project(tmp):
    from qgis.PyQt.QtCore import QVariant
    from qgis.core import QgsProject, QgsRasterLayer
    dem = qgis_env.make_dem(os.path.join(tmp, "DEM_5m.tif"), ncols=120, nrows=100, px=5.0)
    lyr = QgsRasterLayer(dem, "DEM_5m")
    QgsProject.instance().addMapLayer(lyr)
    sites = [(200150 + 60 * i, 499700 - 45 * (i % 4)) for i in range(8)]
    qgis_env.make_points("유적_분포", sites, fields=[("유적명", QVariant.String), ("시대", QVariant.String)],
                         attrs=[[f"유적 {i + 1}", "삼국"] for i in range(8)])
    qgis_env.make_polygon("조사구역", [(200100, 499800), (200500, 499800), (200500, 499600), (200100, 499600)])
    qgis_env.make_polygon("연속지적도", [(200050, 499850), (200550, 499850), (200550, 499550), (200050, 499550)],
                          fields=[("PNU", QVariant.String), ("JIBUN", QVariant.String)], attrs=["4111010100100010000", "1-1 전"])
    return lyr


def _save(widget, path):
    from qgis.PyQt.QtCore import Qt
    pm = widget.grab()
    if pm.width() > MAX_WIDTH:
        pm = pm.scaledToWidth(MAX_WIDTH, Qt.SmoothTransformation)
    pm.save(path, "PNG")
    return pm.width(), pm.height(), os.path.getsize(path) // 1024


def main():
    out_dir = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(ROOT, "docs", "images")
    os.makedirs(out_dir, exist_ok=True)
    app, iface = qgis_env.boot(ROOT)
    from qgis.PyQt import QtGui
    app.setStyle("Fusion")
    app.setFont(QtGui.QFont("NanumGothic", 10))
    tmp = tempfile.mkdtemp(prefix="atk_shots_")
    _sample_project(tmp)

    # Help windows are captured by swapping the modal help dialog for a
    # non-modal one and grabbing it.
    import tools.help_dialog as hd
    captured = {}

    class _Grab(hd.ArchToolkitHelpDialog):
        def exec_(self):
            self.resize(760, 900)
            self.show()
            app.processEvents()
            captured["widget"] = self
            return 0

        exec = exec_

    hd.ArchToolkitHelpDialog = _Grab

    for mod, cls, key in DIALOGS:
        m = importlib.import_module(f"tools.{mod}")
        d = getattr(m, cls)(iface)
        d.show()
        app.processEvents()
        w, h, kb = _save(d, os.path.join(out_dir, f"{key}.png"))
        print(f"{key:24s} {w}x{h} {kb} KB")
        if key in ("terrain_analysis", "spatial_network"):
            fn = getattr(d, "_on_help", None)
            if fn is not None:
                captured.clear()
                try:
                    fn()
                except TypeError:
                    fn(False)
                if captured.get("widget") is not None:
                    w, h, kb = _save(captured["widget"], os.path.join(out_dir, f"help_{key}.png"))
                    print(f"{'help_' + key:24s} {w}x{h} {kb} KB")
                    captured["widget"].close()
        d.close()
    print("done:", out_dir)


if __name__ == "__main__":
    main()
