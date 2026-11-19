#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reproducible cross-software scientific validation benchmark for ArchToolkit.

Compares ArchToolkit's core analytical modules on identical synthetic inputs
against independent external reference software installed on the host:
  1. Terrain derivatives   -> GDAL (gdaldem), GRASS GIS 8.4 (r.slope.aspect,
                              r.neighbors), R 4.5 (terra::terrain), exact calculus
  2. Viewshed (curv/refr)  -> GRASS GIS 8.4 (r.viewshed -b -c refraction_coeff=0.13)
  3. Cost surface / LCP    -> GRASS GIS 8.4 (r.walk 8-dir & r.walk -k 16-dir),
                              exact Euclidean geodesic
  4. Network SNA & MST     -> R 4.5 (igraph), Python NetworkX
  5. Proximity graphs PPA  -> SciPy (Delaunay) + exact O(N^3) Euclidean verifier
  6. Ordinary Kriging/LOOCV-> Independent R 4.5 linear-algebra OK & SciPy solve
  7. Covariate Corr/VIF/R2 -> R 4.5 (stats::cor, stats::lm exact VIF & F-test),
                              SciPy (pearsonr, spearmanr)
  8. AHP eig & Trench SAT  -> SciPy (linalg.eig) & Shapely (GEOS intersection)

Usage:
    python scripts/run_benchmarks.py --json scripts/benchmark_results.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import (  # noqa: E402
    ahp_core,
    cost_engine,
    cost_models,
    covariate_stats,
    kriging_math,
    mst,
    network_metrics,
    ppa_filters,
    terrain_math,
    viewshed_math,
)


def _find_tool(candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if os.path.isfile(c):
            return c
        found = shutil.which(c)
        if found:
            return found
    return None


def _detect_env() -> Dict[str, Any]:
    qgis_root = Path(r"C:\Program Files\QGIS 3.40.5")
    grass_bin = _find_tool([
        str(qgis_root / "bin" / "grass84.bat"),
        "grass84.bat",
        "grass",
    ])
    rscript_bin = _find_tool([
        r"C:\Program Files\R\R-4.5.2\bin\Rscript.exe",
        "Rscript",
    ])
    qgis_py = _find_tool([
        str(qgis_root / "bin" / "python-qgis-ltr.bat"),
        "python-qgis-ltr.bat",
    ])
    gdal_bin_dir = str(qgis_root / "bin") if (qgis_root / "bin" / "gdaldem.exe").is_file() else ""
    versions: Dict[str, str] = {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
    }
    for mod in ("scipy", "networkx", "shapely"):
        try:
            m = __import__(mod)
            versions[mod] = str(getattr(m, "__version__", "installed"))
        except ImportError:
            versions[mod] = "missing"
    if grass_bin:
        p = subprocess.run([grass_bin, "--version"], capture_output=True, text=True, check=False)
        first = (p.stdout or p.stderr or "").strip().splitlines()
        versions["grass"] = first[0] if first else "installed"
    if rscript_bin:
        p = subprocess.run(
            [rscript_bin, "-e", "cat(R.version.string, '| igraph', as.character(packageVersion('igraph')), '| terra', as.character(packageVersion('terra')))"],
            capture_output=True, text=True, check=False,
        )
        versions["r"] = (p.stdout or "").strip()
    if qgis_py:
        p = subprocess.run(
            [qgis_py, "-c", "from osgeo import gdal; from qgis.core import Qgis; print(f'QGIS {Qgis.QGIS_VERSION} / GDAL {gdal.__version__}')"],
            capture_output=True, text=True, check=False,
        )
        versions["qgis_gdal"] = (p.stdout or "").strip()
    return {
        "grass_bin": grass_bin,
        "rscript_bin": rscript_bin,
        "qgis_py": qgis_py,
        "gdal_bin_dir": gdal_bin_dir,
        "versions": versions,
    }


def _run_checked(cmd: List[str], label: str) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if p.returncode != 0:
        raise RuntimeError(
            f"{label} failed (rc={p.returncode}):\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}"
        )
    return p


def _write_geotiff_via_qgis(qgis_py: str, npy_path: str, tif_path: str, gt: Tuple[float, ...], epsg: int = 5186, nodata: float = -9999.0):
    script = Path(tif_path).with_suffix(".write_tmp.py")
    script.write_text(
        "import numpy as np\n"
        "from osgeo import gdal, osr\n"
        f"arr = np.load({str(npy_path)!r}).astype(np.float64)\n"
        f"ds = gdal.GetDriverByName('GTiff').Create({str(tif_path)!r}, arr.shape[1], arr.shape[0], 1, gdal.GDT_Float64)\n"
        f"ds.SetGeoTransform({gt!r})\n"
        f"srs = osr.SpatialReference(); srs.ImportFromEPSG({epsg}); ds.SetProjection(srs.ExportToWkt())\n"
        f"b = ds.GetRasterBand(1); b.SetNoDataValue({nodata!r}); b.WriteArray(arr); b.FlushCache()\n"
        "b = None; ds = None\n",
        encoding="utf-8",
    )
    _run_checked([qgis_py, str(script)], f"write_geotiff({Path(tif_path).name})")


def _read_geotiffs_via_qgis(qgis_py: str, paths: Dict[str, str], out_npz: str):
    manifest = Path(out_npz).with_suffix(".manifest.json")
    manifest.write_text(json.dumps(paths), encoding="utf-8")
    script = Path(out_npz).with_suffix(".read_tmp.py")
    script.write_text(
        "import json, numpy as np\n"
        "from osgeo import gdal\n"
        f"with open({str(manifest)!r}, encoding='utf-8') as f:\n"
        "    paths = json.load(f)\n"
        "out = {}\n"
        "for k, p in paths.items():\n"
        "    ds = gdal.Open(p, gdal.GA_ReadOnly)\n"
        "    if ds is None:\n"
        "        raise RuntimeError(f'gdal.Open failed for {k}: {p}')\n"
        "    b = ds.GetRasterBand(1)\n"
        "    arr = b.ReadAsArray().astype(np.float64)\n"
        "    nd = b.GetNoDataValue()\n"
        "    if nd is not None and not np.isnan(nd):\n"
        "        arr[np.isclose(arr, nd) | (arr == nd)] = np.nan\n"
        "    out[k] = arr\n"
        "    out[k + '__gt'] = np.array(ds.GetGeoTransform(), dtype=np.float64)\n"
        "    b = None; ds = None\n"
        f"np.savez({str(out_npz)!r}, **out)\n",
        encoding="utf-8",
    )
    _run_checked([qgis_py, str(script)], "read_geotiffs")


def _make_synthetic_dems() -> Tuple[np.ndarray, np.ndarray, Tuple[float, ...]]:
    """Create deterministic 101x101 hilly DEM and analytical paraboloid DEM (10 m, EPSG:5186)."""
    rows, cols = 101, 101
    px = 10.0
    x0, y0_top = 200000.0, 501010.0
    gt = (x0, px, 0.0, y0_top, 0.0, -px)
    c_idx = np.arange(cols, dtype=np.float64)
    r_idx = np.arange(rows, dtype=np.float64)
    cc, rr = np.meshgrid(c_idx, r_idx)
    x = (cc + 0.5) * px  # 5..1005 m
    y = (rows - 1 - rr + 0.5) * px  # 5..1005 m (north-up)

    hilly = (
        120.0
        + 45.0 * np.sin(2.0 * np.pi * x / 600.0) * np.cos(2.0 * np.pi * y / 600.0)
        + 30.0 * np.exp(-(((x - 350.0) ** 2 + (y - 400.0) ** 2) / (2.0 * 180.0 ** 2)))
        + 0.04 * x
        - 0.02 * y
    )
    # Exact quadratic surface z = 200 - 4e-4*(x-500)^2 + 2e-4*(y-500)^2 + 1.5e-4*(x-500)*(y-500)
    dx = x - 500.0
    dy = y - 500.0
    quad = 200.0 - 4.0e-4 * (dx ** 2) + 2.0e-4 * (dy ** 2) + 1.5e-4 * dx * dy
    return hilly, quad, gt


def _circular_angle_diff_deg(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    d = np.abs((a - b) % 360.0)
    return np.minimum(d, 360.0 - d)


def _stats_pair(a: np.ndarray, b: np.ndarray, mask: Optional[np.ndarray] = None) -> Dict[str, float]:
    m = np.isfinite(a) & np.isfinite(b)
    if mask is not None:
        m &= mask
    va = a[m]
    vb = b[m]
    diff = np.abs(va - vb)
    rmse = float(np.sqrt(np.mean((va - vb) ** 2)))
    max_abs = float(np.max(diff))
    r = float(np.corrcoef(va, vb)[0, 1]) if va.size >= 2 and np.std(va) > 0 and np.std(vb) > 0 else float("nan")
    return {"n": int(va.size), "max_abs_diff": max_abs, "rmse": rmse, "pearson_r": r}


def bench_terrain_and_viewshed_and_cost(env: Dict[str, Any]) -> Dict[str, Any]:
    """Run Benchmarks 1 (Terrain), 2 (Viewshed), and 3 (Cost / r.walk) on shared DEMs."""
    tmp = Path(tempfile.mkdtemp(prefix="archtk_bench_"))
    try:
        qgis_py = env["qgis_py"]
        grass_bin = env["grass_bin"]
        rscript_bin = env["rscript_bin"]
        hilly, quad, gt = _make_synthetic_dems()
        px = gt[1]

        hilly_npy = str(tmp / "hilly.npy")
        quad_npy = str(tmp / "quad.npy")
        hilly_tif = str(tmp / "hilly.tif")
        quad_tif = str(tmp / "quad.tif")
        np.save(hilly_npy, hilly)
        np.save(quad_npy, quad)
        _write_geotiff_via_qgis(qgis_py, hilly_npy, hilly_tif, gt)
        _write_geotiff_via_qgis(qgis_py, quad_npy, quad_tif, gt)

        # --- GDAL (ArchToolkit's underlying raster engine) ---
        gdal_slope = str(tmp / "gdal_slope.tif")
        gdal_aspect = str(tmp / "gdal_aspect.tif")
        gdal_tri = str(tmp / "gdal_tri.tif")
        gdal_rough = str(tmp / "gdal_rough.tif")
        gdal_tpi = str(tmp / "gdal_tpi.tif")
        gdal_vs = str(tmp / "gdal_viewshed.tif")

        ox = gt[0] + (50 + 0.5) * px
        oy = gt[3] - (50 + 0.5) * px
        cc = viewshed_math.calculate_gdal_viewshed_cc(True, True, 0.13)

        gdal_script = tmp / "run_gdal.py"
        gdal_script.write_text(
            "from osgeo import gdal\n"
            "gdal.UseExceptions()\n"
            f"gdal.DEMProcessing({gdal_slope!r}, {hilly_tif!r}, 'slope', alg='Horn')\n"
            f"gdal.DEMProcessing({gdal_aspect!r}, {hilly_tif!r}, 'aspect', alg='Horn', zeroForFlat=False)\n"
            f"gdal.DEMProcessing({gdal_tri!r}, {hilly_tif!r}, 'TRI', alg='Riley')\n"
            f"gdal.DEMProcessing({gdal_rough!r}, {hilly_tif!r}, 'Roughness')\n"
            f"gdal.DEMProcessing({gdal_tpi!r}, {hilly_tif!r}, 'TPI')\n",
            encoding="utf-8",
        )
        _run_checked([qgis_py, str(gdal_script)], "gdal_demprocessing")
        gdal_viewshed_exe = os.path.join(env["gdal_bin_dir"], "gdal_viewshed.exe")
        _run_checked(
            [
                gdal_viewshed_exe,
                "-ox", f"{ox:.6f}", "-oy", f"{oy:.6f}",
                "-oz", "1.7", "-tz", "0.0",
                "-md", "450", "-cc", f"{cc:.6f}",
                "-ov", "-9999", "-vv", "1", "-iv", "0",
                hilly_tif, gdal_vs,
            ],
            "gdal_viewshed",
        )

        # --- GRASS GIS 8.4.1 (r.slope.aspect, r.neighbors, r.viewshed, r.walk 8 & -k 16) ---
        g_slope = str(tmp / "grass_slope.tif")
        g_aspect = str(tmp / "grass_aspect.tif")
        g_pcurv = str(tmp / "grass_pcurv.tif")
        g_tcurv = str(tmp / "grass_tcurv.tif")
        g_mean7 = str(tmp / "grass_mean7.tif")
        g_vs = str(tmp / "grass_viewshed.tif")
        g_walk8 = str(tmp / "grass_rwalk8.tif")
        g_walk16 = str(tmp / "grass_rwalk16.tif")
        g_flat8 = str(tmp / "grass_flat8.tif")
        g_flat16 = str(tmp / "grass_flat16.tif")

        flat = np.full((101, 101), 100.0, dtype=np.float64)
        flat_npy = str(tmp / "flat.npy")
        flat_tif = str(tmp / "flat.tif")
        np.save(flat_npy, flat)
        _write_geotiff_via_qgis(qgis_py, flat_npy, flat_tif, gt)

        grass_script = tmp / "run_grass.py"
        grass_script.write_text(
            f"""import grass.script as gs
gs.run_command('r.in.gdal', input=r'{hilly_tif}', output='hilly', overwrite=True)
gs.run_command('r.in.gdal', input=r'{quad_tif}', output='quad', overwrite=True)
gs.run_command('r.in.gdal', input=r'{flat_tif}', output='flat', overwrite=True)
gs.run_command('g.region', raster='hilly')
gs.run_command('r.slope.aspect', elevation='hilly', slope='g_slope', aspect='g_aspect',
               pcurvature='g_pcurv', tcurvature='g_tcurv', precision='DCELL', overwrite=True)
gs.run_command('r.neighbors', input='hilly', output='g_mean7', method='average', size=7, overwrite=True)
gs.run_command('r.viewshed', input='hilly', output='g_vs', coordinates=({ox:.6f}, {oy:.6f}),
               observer_elevation=1.7, target_elevation=0.0, max_distance=450,
               refraction_coeff=0.13, flags='bc', overwrite=True)
gs.run_command('r.mapcalc', expression='zero_fric = 0.0', overwrite=True)
# Exact Naismith parameters: a=0.72 s/m (5 km/h), b=6.0 s/m uphill (600 m/h), c=0, d=0, lambda=0
gs.run_command('r.walk', elevation='hilly', friction='zero_fric', output='g_walk8',
               start_coordinates=({ox:.6f}, {oy:.6f}), walk_coeff='0.72,6.0,0.0,0.0',
               **{{'lambda': 0.0}}, overwrite=True)
gs.run_command('r.walk', elevation='hilly', friction='zero_fric', output='g_walk16',
               start_coordinates=({ox:.6f}, {oy:.6f}), walk_coeff='0.72,6.0,0.0,0.0',
               **{{'lambda': 0.0}}, flags='k', overwrite=True)
gs.run_command('r.walk', elevation='flat', friction='zero_fric', output='g_flat8',
               start_coordinates=({gt[0] + 10.5 * px:.6f}, {gt[3] - 10.5 * px:.6f}),
               walk_coeff='0.72,6.0,0.0,0.0', **{{'lambda': 0.0}}, overwrite=True)
gs.run_command('r.walk', elevation='flat', friction='zero_fric', output='g_flat16',
               start_coordinates=({gt[0] + 10.5 * px:.6f}, {gt[3] - 10.5 * px:.6f}),
               walk_coeff='0.72,6.0,0.0,0.0', **{{'lambda': 0.0}}, flags='k', overwrite=True)
for name, outp in [
    ('g_slope', r'{g_slope}'), ('g_aspect', r'{g_aspect}'),
    ('g_pcurv', r'{g_pcurv}'), ('g_tcurv', r'{g_tcurv}'),
    ('g_mean7', r'{g_mean7}'), ('g_vs', r'{g_vs}'),
    ('g_walk8', r'{g_walk8}'), ('g_walk16', r'{g_walk16}'),
    ('g_flat8', r'{g_flat8}'), ('g_flat16', r'{g_flat16}'),
]:
    gs.run_command('r.out.gdal', input=name, output=outp, format='GTiff', type='Float64', overwrite=True)
""",
            encoding="utf-8",
        )
        subprocess.run(
            [grass_bin, "--tmp-project", "EPSG:5186", "--exec", "python", str(grass_script)],
            check=True, capture_output=True, text=True,
        )

        # --- R 4.5.2 terra::terrain ---
        r_slope = str(tmp / "r_slope.tif")
        r_aspect = str(tmp / "r_aspect.tif")
        r_tpi = str(tmp / "r_tpi.tif")
        r_tri = str(tmp / "r_tri.tif")
        r_rough = str(tmp / "r_rough.tif")
        r_script = tmp / "run_terra.R"
        r_script.write_text(
            f"""suppressPackageStartupMessages(library(terra))
r <- rast("{hilly_tif.replace(chr(92), '/')}")
writeRaster(terrain(r, v="slope", unit="degrees", neighbors=8), "{r_slope.replace(chr(92), '/')}", overwrite=TRUE, datatype="FLT8S")
writeRaster(terrain(r, v="aspect", unit="degrees", neighbors=8), "{r_aspect.replace(chr(92), '/')}", overwrite=TRUE, datatype="FLT8S")
writeRaster(terrain(r, v="TPI"), "{r_tpi.replace(chr(92), '/')}", overwrite=TRUE, datatype="FLT8S")
writeRaster(terrain(r, v="TRIriley"), "{r_tri.replace(chr(92), '/')}", overwrite=TRUE, datatype="FLT8S")
writeRaster(terrain(r, v="roughness"), "{r_rough.replace(chr(92), '/')}", overwrite=TRUE, datatype="FLT8S")
""",
            encoding="utf-8",
        )
        subprocess.run([rscript_bin, str(r_script)], check=True, capture_output=True, text=True)

        # Read all rasters back into numpy
        npz_path = str(tmp / "rasters.npz")
        _read_geotiffs_via_qgis(
            qgis_py,
            {
                "gdal_slope": gdal_slope, "gdal_aspect": gdal_aspect,
                "gdal_tri": gdal_tri, "gdal_rough": gdal_rough, "gdal_tpi": gdal_tpi,
                "gdal_vs": gdal_vs,
                "g_slope": g_slope, "g_aspect": g_aspect,
                "g_pcurv": g_pcurv, "g_tcurv": g_tcurv,
                "g_mean7": g_mean7, "g_vs": g_vs,
                "g_walk8": g_walk8, "g_walk16": g_walk16,
                "g_flat8": g_flat8, "g_flat16": g_flat16,
                "r_slope": r_slope, "r_aspect": r_aspect,
                "r_tpi": r_tpi, "r_tri": r_tri, "r_rough": r_rough,
            },
            npz_path,
        )
        R = dict(np.load(npz_path))

        # --- Benchmark 1: Terrain analysis comparisons ---
        inner = np.zeros_like(hilly, dtype=bool)
        inner[2:-2, 2:-2] = True
        inner3 = np.zeros_like(hilly, dtype=bool)
        inner3[4:-4, 4:-4] = True

        # Convert GRASS aspect (CCW from East) to CW from North
        g_aspect_cw_n = (450.0 - R["g_aspect"]) % 360.0
        steep = inner & (R["gdal_slope"] > 0.5)
        asp_diff_grass = _circular_angle_diff_deg(R["gdal_aspect"][steep], g_aspect_cw_n[steep])
        asp_diff_terra = _circular_angle_diff_deg(R["gdal_aspect"][steep], R["r_aspect"][steep])

        # ArchToolkit TPI (radius=1 and radius=3 via Crow summed-area table)
        at_tpi1 = terrain_math.focal_tpi(hilly, radius=1)
        at_tpi3 = terrain_math.focal_tpi(hilly, radius=3)
        # GRASS r.neighbors(size=7) includes the center cell -> excl-center mean = (49*mean7 - z) / 48
        grass_tpi3_excl = hilly - (49.0 * R["g_mean7"] - hilly) / 48.0

        # ArchToolkit ZT curvature vs exact analytical paraboloid & vs GRASS pcurv
        at_prof_q, at_plan_q = terrain_math.zt_curvature(quad, px, px)
        # Exact ZT formula on z = 200 + a*dx^2 + b*dy^2 + c*dx*dy:
        # D = d2z/dx2 / 2 = a = -4e-4, E = d2z/dy2 / 2 = b = 2e-4, F = d2z/dxdy = c = 1.5e-4
        # G = dz/dx = 2*a*dx + c*dy, H = dz/dy = 2*b*dy + c*dx
        rows, cols = quad.shape
        cc, rr = np.meshgrid(np.arange(cols, dtype=float), np.arange(rows, dtype=float))
        dx_q = (cc + 0.5) * px - 500.0
        dy_q = (rows - 1 - rr + 0.5) * px - 500.0
        D_ex, E_ex, F_ex = -4.0e-4, 2.0e-4, 1.5e-4
        G_ex = 2.0 * D_ex * dx_q + F_ex * dy_q
        H_ex = 2.0 * E_ex * dy_q + F_ex * dx_q
        denom_q = G_ex ** 2 + H_ex ** 2
        nz_q = inner & (denom_q > 1e-6)
        exact_prof_q = 2.0 * (D_ex * G_ex ** 2 + E_ex * H_ex ** 2 + F_ex * G_ex * H_ex) / np.where(nz_q, denom_q, 1.0)
        exact_plan_q = -2.0 * (D_ex * H_ex ** 2 + E_ex * G_ex ** 2 - F_ex * G_ex * H_ex) / np.where(nz_q, denom_q, 1.0)

        at_prof_h, at_plan_h = terrain_math.zt_curvature(hilly, px, px)
        # Compare ArchToolkit profile curvature with GRASS pcurv (note: GRASS divides by (1 + p^2 + q^2)^(3/2) and opposite sign)
        grad2 = np.tan(np.radians(R["gdal_slope"])) ** 2
        at_prof_grass_equiv = -at_prof_h / ((1.0 + grad2) ** 1.5)

        terrain_res = {
            "slope_vs_grass_r_slope_aspect": _stats_pair(R["gdal_slope"], R["g_slope"], inner),
            "slope_vs_r_terra": _stats_pair(R["gdal_slope"], R["r_slope"], inner),
            "aspect_vs_grass_max_deg": float(np.max(asp_diff_grass)),
            "aspect_vs_grass_rmse_deg": float(np.sqrt(np.mean(asp_diff_grass ** 2))),
            "aspect_vs_r_terra_max_deg": float(np.max(asp_diff_terra)),
            "aspect_vs_r_terra_rmse_deg": float(np.sqrt(np.mean(asp_diff_terra ** 2))),
            "tpi_r1_vs_gdal": _stats_pair(at_tpi1, R["gdal_tpi"], inner),
            "tpi_r1_vs_r_terra": _stats_pair(at_tpi1, R["r_tpi"], inner),
            "tpi_r3_vs_grass_r_neighbors": _stats_pair(at_tpi3, grass_tpi3_excl, inner3),
            "tri_vs_r_terra_riley": _stats_pair(R["gdal_tri"], R["r_tri"], inner),
            "roughness_vs_r_terra": _stats_pair(R["gdal_rough"], R["r_rough"], inner),
            "zt_profile_curv_vs_exact_calculus": _stats_pair(at_prof_q, exact_prof_q, nz_q),
            "zt_plan_curv_vs_exact_calculus": _stats_pair(at_plan_q, exact_plan_q, nz_q),
            "profile_curv_sign_and_metric_vs_grass": _stats_pair(at_prof_grass_equiv, R["g_pcurv"], inner & (R["gdal_slope"] > 1.0)),
            "raw_profile_curv_corr_with_grass_pcurv": float(
                np.corrcoef(at_prof_h[inner & (R["gdal_slope"] > 1.0)], R["g_pcurv"][inner & (R["gdal_slope"] > 1.0)])[0, 1]
            ),
        }

        # --- Benchmark 2: Viewshed vs GRASS r.viewshed ---
        # gdal_viewshed crops output tightly to the max_distance window; align by GeoTransform.
        vs_at_arr = R["gdal_vs"]
        vs_at_gt = R["gdal_vs__gt"]
        c_off = int(round((float(vs_at_gt[0]) - gt[0]) / px))
        r_off = int(round((gt[3] - float(vs_at_gt[3])) / px))
        vh, vw = vs_at_arr.shape
        vs_gr_crop = R["g_vs"][r_off:r_off + vh, c_off:c_off + vw]
        dist_obs_crop = np.hypot((cc[r_off:r_off + vh, c_off:c_off + vw] - 50.0) * px, (rr[r_off:r_off + vh, c_off:c_off + vw] - 50.0) * px)
        in_rad = (dist_obs_crop > 0.0) & (dist_obs_crop <= 450.0) & np.isfinite(vs_at_arr) & np.isfinite(vs_gr_crop)
        v_at = (vs_at_arr[in_rad] > 0.5)
        v_gr = (vs_gr_crop[in_rad] > 0.5)
        dist_obs = np.hypot((cc - 50.0) * px, (rr - 50.0) * px)
        agree = float(np.mean(v_at == v_gr))
        tp = int(np.sum(v_at & v_gr))
        fp = int(np.sum(v_at & (~v_gr)))
        fn = int(np.sum((~v_at) & v_gr))
        tn = int(np.sum((~v_at) & (~v_gr)))
        iou = float(tp / max(1, tp + fp + fn))
        total_v = tp + fp + fn + tn
        pe = ((tp + fp) * (tp + fn) + (fn + tn) * (fp + tn)) / float(total_v * total_v)
        kappa = float((agree - pe) / max(1e-12, 1.0 - pe))
        viewshed_res = {
            "n_cells_in_radius": int(total_v),
            "agreement_pct": round(agree * 100.0, 4),
            "visible_iou_pct": round(iou * 100.0, 4),
            "cohens_kappa": round(kappa, 5),
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "at_visible_pct": round(float(np.mean(v_at)) * 100.0, 2),
            "grass_visible_pct": round(float(np.mean(v_gr)) * 100.0, 2),
        }

        # --- Benchmark 3: Cost Surface / LCP (8-dir & 16-dir Knight) vs GRASS r.walk ---
        nodata_false = np.zeros_like(hilly, dtype=bool)
        naismith_p = {"naismith_horizontal_kmh": 5.0, "naismith_ascent_m_per_h": 600.0}
        at_w8, _ = cost_engine.dijkstra_full(
            hilly, nodata_false, (50, 50), px, px, True,
            cost_models.MODEL_NAISMITH, naismith_p, cost_mode="time_s", allow_knight=False,
        )
        at_w16, _ = cost_engine.dijkstra_full(
            hilly, nodata_false, (50, 50), px, px, True,
            cost_models.MODEL_NAISMITH, naismith_p, cost_mode="time_s", allow_knight=True,
        )
        at_w8 = at_w8.reshape(hilly.shape)
        at_w16 = at_w16.reshape(hilly.shape)

        # Compare flat-plane max grid elongation across angles [0, 45 deg] at radius ~70 cells
        at_f4, _ = cost_engine.dijkstra_full(
            flat, nodata_false, (10, 10), px, px, False,
            cost_models.MODEL_NAISMITH, naismith_p, cost_mode="time_s", allow_knight=False,
        )
        at_f8, _ = cost_engine.dijkstra_full(
            flat, nodata_false, (10, 10), px, px, True,
            cost_models.MODEL_NAISMITH, naismith_p, cost_mode="time_s", allow_knight=False,
        )
        at_f16, _ = cost_engine.dijkstra_full(
            flat, nodata_false, (10, 10), px, px, True,
            cost_models.MODEL_NAISMITH, naismith_p, cost_mode="time_s", allow_knight=True,
        )
        at_f4 = at_f4.reshape(flat.shape)
        at_f8 = at_f8.reshape(flat.shape)
        at_f16 = at_f16.reshape(flat.shape)
        euclid_flat_t = np.hypot((cc - 10.0) * px, (rr - 10.0) * px) * 0.72
        ring_m = (np.hypot(cc - 10.0, rr - 10.0) >= 40.0) & (np.hypot(cc - 10.0, rr - 10.0) <= 80.0)

        def _max_elong(arr):
            return float(np.max((arr[ring_m] / euclid_flat_t[ring_m] - 1.0) * 100.0))

        def _rel_stats(a, b, m):
            va, vb = a[m], b[m]
            rel = np.abs(va - vb) / np.maximum(vb, 1e-9) * 100.0
            return {
                "n": int(va.size),
                "max_abs_diff_s": float(np.max(np.abs(va - vb))),
                "rmse_s": float(np.sqrt(np.mean((va - vb) ** 2))),
                "median_rel_diff_pct": float(np.median(rel)),
                "max_rel_diff_pct": float(np.max(rel)),
                "pearson_r": float(np.corrcoef(va, vb)[0, 1]),
            }

        non_origin = (dist_obs > 0.0) & np.isfinite(R["g_walk8"]) & np.isfinite(R["g_walk16"])
        cost_res = {
            "flat_max_elongation_pct": {
                "archtoolkit_4dir": round(_max_elong(at_f4), 4),
                "archtoolkit_8dir": round(_max_elong(at_f8), 4),
                "archtoolkit_16dir_knight": round(_max_elong(at_f16), 4),
                "grass_rwalk_8dir": round(_max_elong(R["g_flat8"]), 4),
                "grass_rwalk_16dir_knight": round(_max_elong(R["g_flat16"]), 4),
            },
            "hilly_naismith_8dir_vs_grass_rwalk": _rel_stats(at_w8, R["g_walk8"], non_origin),
            "hilly_naismith_16dir_vs_grass_rwalk_k": _rel_stats(at_w16, R["g_walk16"], non_origin),
            "flat_8dir_vs_grass_rwalk": _rel_stats(at_f8, R["g_flat8"], ring_m),
            "flat_16dir_vs_grass_rwalk_k": _rel_stats(at_f16, R["g_flat16"], ring_m),
        }

        return {"terrain": terrain_res, "viewshed": viewshed_res, "cost": cost_res}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def bench_network(env: Dict[str, Any]) -> Dict[str, Any]:
    """Benchmark 4: ArchToolkit SNA & Kruskal MST vs R igraph & Python NetworkX."""
    import networkx as nx

    rng = np.random.default_rng(2026)
    n = 25
    # Connected component 0..19 with explicit tied shortest paths + disconnected component 20..24
    edges: List[Tuple[int, int, float]] = [
        # Diamond with exact tie (0-1-3 and 0-2-3 both cost 10.0)
        (0, 1, 4.0), (1, 3, 6.0), (0, 2, 5.0), (2, 3, 5.0),
    ]
    seen = {(min(u, v), max(u, v)) for u, v, _ in edges}
    # Spanning chain on 0..19 so component 1 is guaranteed connected
    for u in range(3, 19):
        w = round(float(rng.uniform(2.0, 20.0)), 2)
        edges.append((u, u + 1, w))
        seen.add((u, u + 1))
    # Extra cross edges in component 1
    for _ in range(30):
        u, v = int(rng.integers(0, 20)), int(rng.integers(0, 20))
        if u != v and (min(u, v), max(u, v)) not in seen:
            seen.add((min(u, v), max(u, v)))
            edges.append((min(u, v), max(u, v), round(float(rng.uniform(3.0, 25.0)), 2)))
    # Second disconnected component 20..24
    for u, v, w in [(20, 21, 5.0), (21, 22, 7.0), (22, 23, 4.0), (23, 24, 6.0), (20, 22, 9.0)]:
        edges.append((u, v, w))

    # ArchToolkit
    adj_u: List[List[int]] = [[] for _ in range(n)]
    adj_w: List[List[Tuple[int, float]]] = [[] for _ in range(n)]
    for u, v, w in edges:
        adj_u[u].append(v)
        adj_u[v].append(u)
        adj_w[u].append((v, w))
        adj_w[v].append((u, w))

    at_betw_u = np.array(network_metrics.betweenness_centrality_unweighted(n=n, adj=adj_u), dtype=float)
    at_betw_w = np.array(network_metrics.betweenness_centrality_weighted(n=n, adj=adj_w), dtype=float)
    at_close_u = np.array(network_metrics.closeness_centrality_unweighted(n=n, adj=adj_u), dtype=float)
    at_close_w = np.array(network_metrics.closeness_centrality_weighted(n=n, adj=adj_w), dtype=float)
    at_harm_u = np.array(network_metrics.harmonic_centrality_unweighted(n=n, adj=adj_u), dtype=float)
    at_harm_w = np.array(network_metrics.harmonic_centrality_weighted(n=n, adj=adj_w), dtype=float)
    at_clust = np.array(network_metrics.local_clustering_coefficients(n=n, adj=adj_u), dtype=float)
    mst_res = mst.kruskal_mst(n, [(w, u, v) for u, v, w in edges])
    at_mst_sum = float(mst_res["total_weight"])

    # NetworkX 3.6.1
    G = nx.Graph()
    G.add_nodes_from(range(n))
    for u, v, w in edges:
        G.add_edge(u, v, weight=w)
    nx_betw_u = np.array([nx.betweenness_centrality(G, normalized=False)[i] for i in range(n)], dtype=float)
    nx_betw_w = np.array([nx.betweenness_centrality(G, weight="weight", normalized=False)[i] for i in range(n)], dtype=float)
    nx_close_u = np.array([nx.closeness_centrality(G, wf_improved=True)[i] for i in range(n)], dtype=float)
    nx_close_w = np.array([nx.closeness_centrality(G, distance="weight", wf_improved=True)[i] for i in range(n)], dtype=float)
    # NetworkX harmonic_centrality returns raw sum; ArchToolkit normalizes by (n - 1)
    nx_harm_u = np.array([nx.harmonic_centrality(G)[i] / (n - 1) for i in range(n)], dtype=float)
    nx_harm_w = np.array([nx.harmonic_centrality(G, distance="weight")[i] / (n - 1) for i in range(n)], dtype=float)
    nx_clust = np.array([nx.clustering(G)[i] for i in range(n)], dtype=float)
    nx_mst_sum = float(sum(d["weight"] for _, _, d in nx.minimum_spanning_edges(G, data=True)))

    # R 4.5.2 igraph
    tmp = Path(tempfile.mkdtemp(prefix="archtk_net_"))
    try:
        edge_csv = tmp / "edges.csv"
        edge_csv.write_text("u,v,w\n" + "\n".join(f"{u+1},{v+1},{w}" for u, v, w in edges), encoding="utf-8")
        r_out = tmp / "igraph_out.json"
        r_script = tmp / "bench_igraph.R"
        r_script.write_text(
            f"""suppressPackageStartupMessages(library(igraph))
df <- read.csv("{str(edge_csv).replace(chr(92), '/')}")
g <- graph_from_data_frame(df[, c("u","v")], directed=FALSE, vertices=data.frame(name=1:{n}))
E(g)$weight <- df$w
bu <- as.numeric(betweenness(g, directed=FALSE, weights=NA, normalized=FALSE))
bw <- as.numeric(betweenness(g, directed=FALSE, weights=E(g)$weight, normalized=FALSE))
hu <- as.numeric(harmonic_centrality(g, weights=NA, normalized=TRUE))
hw <- as.numeric(harmonic_centrality(g, weights=E(g)$weight, normalized=TRUE))
cl <- as.numeric(transitivity(g, type="local", isolates="zero"))
mst_g <- mst(g, weights=E(g)$weight)
mst_sum <- sum(E(mst_g)$weight)
cat(sprintf('{{"betw_u":[%s],"betw_w":[%s],"harm_u":[%s],"harm_w":[%s],"clust":[%s],"mst_sum":%.12f}}',
    paste(sprintf("%.12f", bu), collapse=","),
    paste(sprintf("%.12f", bw), collapse=","),
    paste(sprintf("%.12f", hu), collapse=","),
    paste(sprintf("%.12f", hw), collapse=","),
    paste(sprintf("%.12f", cl), collapse=","),
    mst_sum), file="{str(r_out).replace(chr(92), '/')}")
""",
            encoding="utf-8",
        )
        subprocess.run([env["rscript_bin"], str(r_script)], check=True, capture_output=True, text=True)
        ig = json.loads(r_out.read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return {
        "n_nodes": n,
        "n_edges": len(edges),
        "vs_networkx": {
            "betweenness_unweighted_max_diff": float(np.max(np.abs(at_betw_u - nx_betw_u))),
            "betweenness_weighted_max_diff": float(np.max(np.abs(at_betw_w - nx_betw_w))),
            "closeness_unweighted_max_diff": float(np.max(np.abs(at_close_u - nx_close_u))),
            "closeness_weighted_max_diff": float(np.max(np.abs(at_close_w - nx_close_w))),
            "harmonic_unweighted_max_diff": float(np.max(np.abs(at_harm_u - nx_harm_u))),
            "harmonic_weighted_max_diff": float(np.max(np.abs(at_harm_w - nx_harm_w))),
            "clustering_max_diff": float(np.max(np.abs(at_clust - nx_clust))),
            "mst_total_weight_diff": float(abs(at_mst_sum - nx_mst_sum)),
        },
        "vs_r_igraph": {
            "betweenness_unweighted_max_diff": float(np.max(np.abs(at_betw_u - np.array(ig["betw_u"])))),
            "betweenness_weighted_max_diff": float(np.max(np.abs(at_betw_w - np.array(ig["betw_w"])))),
            "harmonic_unweighted_max_diff": float(np.max(np.abs(at_harm_u - np.array(ig["harm_u"])))),
            "harmonic_weighted_max_diff": float(np.max(np.abs(at_harm_w - np.array(ig["harm_w"])))),
            "clustering_max_diff": float(np.max(np.abs(at_clust - np.array(ig["clust"])))),
            "mst_total_weight_diff": float(abs(at_mst_sum - float(ig["mst_sum"]))),
        },
        "mst_total_weight": round(at_mst_sum, 4),
    }


def bench_ppa() -> Dict[str, Any]:
    """Benchmark 5: ArchToolkit Gabriel & RNG vs SciPy Delaunay + exact O(N^3) verifier."""
    from scipy.spatial import Delaunay

    rng = np.random.default_rng(777)
    pts = rng.uniform(0.0, 10000.0, size=(40, 2))
    tri = Delaunay(pts)
    cand = set()
    for simplex in tri.simplices:
        for i in range(3):
            a, b = int(simplex[i]), int(simplex[(i + 1) % 3])
            cand.add((min(a, b), max(a, b)))

    coords = [(float(x), float(y)) for x, y in pts]
    at_gab = set(ppa_filters.ppa_filter_gabriel(coords, sorted(cand)))
    at_rng = set(ppa_filters.ppa_filter_rng(coords, sorted(cand)))

    # Independent O(N^3) brute-force Euclidean verifier over ALL N*(N-1)/2 pairs
    ref_gab = set()
    ref_rng = set()
    n = len(coords)
    for i in range(n):
        for j in range(i + 1, n):
            d_ij = math.hypot(pts[i, 0] - pts[j, 0], pts[i, 1] - pts[j, 1])
            d2_ij = d_ij * d_ij
            mx, my = 0.5 * (pts[i, 0] + pts[j, 0]), 0.5 * (pts[i, 1] + pts[j, 1])
            r2 = 0.25 * d2_ij
            gab_ok = True
            rng_ok = True
            for k in range(n):
                if k == i or k == j:
                    continue
                if ((pts[k, 0] - mx) ** 2 + (pts[k, 1] - my) ** 2) <= r2:
                    gab_ok = False
                dik = math.hypot(pts[i, 0] - pts[k, 0], pts[i, 1] - pts[k, 1])
                djk = math.hypot(pts[j, 0] - pts[k, 0], pts[j, 1] - pts[k, 1])
                if max(dik, djk) < d_ij:
                    rng_ok = False
            if gab_ok:
                ref_gab.add((i, j))
            if rng_ok:
                ref_rng.add((i, j))

    # 72-rotation 5 km equilateral triangle RNG invariance
    rot_ok = 0
    for step in range(72):
        th = math.radians(step * 5.0)
        base = [(0.0, 0.0), (5000.0, 0.0), (2500.0, 5000.0 * math.sqrt(3.0) / 2.0)]
        rpts = [(x * math.cos(th) - y * math.sin(th) + 200000.0, x * math.sin(th) + y * math.cos(th) + 500000.0) for x, y in base]
        if len(ppa_filters.ppa_filter_rng(rpts, [(0, 1), (1, 2), (0, 2)])) == 3:
            rot_ok += 1

    return {
        "n_sites": n,
        "gabriel_edges": len(at_gab),
        "gabriel_exact_match": bool(at_gab == ref_gab),
        "rng_edges": len(at_rng),
        "rng_exact_match": bool(at_rng == ref_rng),
        "equilateral_5km_72rot_preserved": f"{rot_ok}/72",
    }


def bench_kriging(env: Dict[str, Any]) -> Dict[str, Any]:
    """Benchmark 6: ArchToolkit Ordinary Kriging & LOOCV vs independent R 4.5 solve() & SciPy."""
    from scipy.linalg import solve as scipy_solve

    rng = np.random.default_rng(314)
    n_obs = 45
    obs_xy = rng.uniform(0.0, 1000.0, size=(n_obs, 2))
    obs_z = (
        150.0
        + 35.0 * np.sin(obs_xy[:, 0] / 260.0) * np.cos(obs_xy[:, 1] / 280.0)
        + 15.0 * np.exp(-(((obs_xy[:, 0] - 450.0) ** 2 + (obs_xy[:, 1] - 550.0) ** 2) / (2.0 * 220.0 ** 2)))
        + rng.normal(0.0, 1.5, size=n_obs)
    )
    tx, ty = np.meshgrid(np.linspace(100.0, 900.0, 10), np.linspace(100.0, 900.0, 10))
    targets = np.column_stack([tx.ravel(), ty.ravel()])

    # Fit WLS variogram with ArchToolkit
    fit = kriging_math.fit_variogram_wls(obs_xy, obs_z)
    mod = str(fit["model"]) if fit.get("fitted") else "exponential"
    c0 = float(fit["nugget"]) if fit.get("fitted") else 2.0
    c1 = float(fit["partial_sill"]) if fit.get("fitted") else 250.0
    r_param = float(fit["range"]) if fit.get("fitted") else 220.0

    # ArchToolkit global OK predictions & variances
    A = kriging_math.build_ok_system(obs_xy, partial_sill=c1, rng=r_param, nugget=c0, model=mod)
    inv = kriging_math.invert_ok_system(A, partial_sill=c1, nugget=c0)
    at_pred = np.empty(targets.shape[0])
    at_var = np.empty(targets.shape[0])
    for i, (x, y) in enumerate(targets):
        at_pred[i], at_var[i] = kriging_math.solve_ok(
            inv, obs_xy, obs_z, (float(x), float(y)),
            partial_sill=c1, rng=r_param, nugget=c0, model=mod,
        )

    # Exact interpolation check at isolated sample points
    at_self = [
        kriging_math.solve_ok(
            inv, obs_xy, obs_z, (float(obs_xy[i, 0]), float(obs_xy[i, 1])),
            partial_sill=c1, rng=r_param, nugget=c0, model=mod,
        )
        for i in range(n_obs)
    ]
    exact_max_resid = float(np.max(np.abs(np.array([p for p, _ in at_self]) - obs_z)))
    exact_max_var = float(np.max(np.abs(np.array([v for _, v in at_self]))))

    # Independent R 4.5 double-precision solve() reference
    tmp = Path(tempfile.mkdtemp(prefix="archtk_krig_"))
    try:
        obs_csv = tmp / "obs.csv"
        tgt_csv = tmp / "tgt.csv"
        obs_csv.write_text("x,y,z\n" + "\n".join(f"{x:.10f},{y:.10f},{z:.10f}" for (x, y), z in zip(obs_xy, obs_z)), encoding="utf-8")
        tgt_csv.write_text("x,y\n" + "\n".join(f"{x:.10f},{y:.10f}" for x, y in targets), encoding="utf-8")
        r_out = tmp / "krig_r.json"
        r_script = tmp / "bench_krig.R"
        r_script.write_text(
            f"""obs <- read.csv("{str(obs_csv).replace(chr(92), '/')}")
tgt <- read.csv("{str(tgt_csv).replace(chr(92), '/')}")
mod <- "{mod}"; c0 <- {c0:.15g}; c1 <- {c1:.15g}; rng <- {r_param:.15g}
cov_fn <- function(h) {{
  if (mod == "exponential") return(c1 * exp(-h / rng))
  if (mod == "gaussian") return(c1 * exp(-(h / rng)^2))
  u <- h / rng
  ifelse(u < 1.0, c1 * (1.0 - (1.5*u - 0.5*u^3)), 0.0)
}}
n <- nrow(obs)
D <- as.matrix(dist(obs[, c("x","y")]))
C <- cov_fn(D)
diag(C) <- c0 + c1
A <- rbind(cbind(C, 1), c(rep(1, n), 0))
pred <- numeric(nrow(tgt)); kvar <- numeric(nrow(tgt))
for (k in seq_len(nrow(tgt))) {{
  d0 <- sqrt((obs$x - tgt$x[k])^2 + (obs$y - tgt$y[k])^2)
  cvec <- cov_fn(d0)
  sol <- solve(A, c(cvec, 1))
  w <- sol[1:n]; mu <- sol[n+1]
  pred[k] <- sum(w * obs$z)
  kvar[k] <- (c0 + c1) - sum(w * cvec) - mu
}}
# Exact global LOOCV in R
lo_err <- numeric(n); lo_std <- numeric(n)
for (i in seq_len(n)) {{
  idx <- setdiff(seq_len(n), i)
  Di <- D[idx, idx]; Ci <- cov_fn(Di); diag(Ci) <- c0 + c1
  Ai <- rbind(cbind(Ci, 1), c(rep(1, n-1), 0))
  d0 <- D[idx, i]; cvec <- cov_fn(d0)
  sol <- solve(Ai, c(cvec, 1))
  w <- sol[1:(n-1)]; mu <- sol[n]
  zh <- sum(w * obs$z[idx])
  vv <- (c0 + c1) - sum(w * cvec) - mu
  lo_err[i] <- zh - obs$z[i]
  lo_std[i] <- (lo_err[i]^2) / vv
}}
cat(sprintf('{{"pred":[%s],"var":[%s],"loocv_rmse":%.12f,"loocv_msdr":%.12f}}',
    paste(sprintf("%.12f", pred), collapse=","),
    paste(sprintf("%.12f", kvar), collapse=","),
    sqrt(mean(lo_err^2)), mean(lo_std)), file="{str(r_out).replace(chr(92), '/')}")
""",
            encoding="utf-8",
        )
        subprocess.run([env["rscript_bin"], str(r_script)], check=True, capture_output=True, text=True)
        rk = json.loads(r_out.read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Also verify against SciPy solve on first target
    d0 = np.hypot(obs_xy[:, 0] - targets[0, 0], obs_xy[:, 1] - targets[0, 1])
    rhs0 = np.append(kriging_math.covariance_value(d0, model=mod, nugget=c0, partial_sill=c1, rng=r_param), 1.0)
    sp_sol0 = scipy_solve(A, rhs0)
    sp_pred0 = float(np.dot(sp_sol0[:-1], obs_z))

    at_loocv = kriging_math.loocv_ordinary_kriging(
        obs_xy, obs_z, model=mod, nugget=c0, partial_sill=c1, rng=r_param, neighbors=n_obs - 1,
    )
    return {
        "n_obs": n_obs,
        "n_targets": int(targets.shape[0]),
        "fitted_model": mod,
        "pred_max_abs_diff_vs_r": float(np.max(np.abs(at_pred - np.array(rk["pred"])))),
        "var_max_abs_diff_vs_r": float(np.max(np.abs(at_var - np.array(rk["var"])))),
        "pred0_diff_vs_scipy": float(abs(at_pred[0] - sp_pred0)),
        "loocv_rmse_diff_vs_r": float(abs(float(at_loocv["rmse"]) - float(rk["loocv_rmse"]))),
        "loocv_msdr_diff_vs_r": float(abs(float(at_loocv["msdr"]) - float(rk["loocv_msdr"]))),
        "exact_interp_max_residual": exact_max_resid,
        "exact_interp_max_variance": exact_max_var,
        "loocv_rmse": round(float(at_loocv["rmse"]), 4),
        "loocv_msdr": round(float(at_loocv["msdr"]), 4),
    }


def bench_covariate_stats(env: Dict[str, Any]) -> Dict[str, Any]:
    """Benchmark 7: ArchToolkit Pearson/Spearman/VIF/Circular-Linear R2 vs R 4.5 & SciPy."""
    from scipy.stats import pearsonr, spearmanr

    rng = np.random.default_rng(999)
    n = 500
    x1 = rng.normal(250.0, 40.0, size=n)                 # elevation (m)
    x2 = 0.08 * x1 + rng.normal(0.0, 5.0, size=n)        # slope (deg), moderately correlated
    x3 = (1e-4 * x1 + 2e-4 * x2 + rng.normal(0.0, 1e-4, size=n)) * 1e9  # extreme scale collinear
    x4 = rng.uniform(0.0, 5000.0, size=n)                # distance (m), independent
    aspect_deg = rng.uniform(0.0, 360.0, size=n)
    # Linear variable with genuine circular correlation to aspect
    y_circ = 10.0 + 3.5 * np.cos(np.radians(aspect_deg - 35.0)) + rng.normal(0.0, 1.8, size=n)

    X = np.column_stack([x1, x2, x3, x4])
    at_pear = covariate_stats.compute_pearson_matrix(X)
    at_spear = covariate_stats.compute_spearman_matrix(X)
    at_vif = covariate_stats.compute_vif(X)
    at_cl = covariate_stats.circular_linear_r2(aspect_deg, y_circ)

    # SciPy
    sp_pear = np.ones((4, 4))
    sp_spear = np.ones((4, 4))
    for i in range(4):
        for j in range(4):
            if i != j:
                sp_pear[i, j] = pearsonr(X[:, i], X[:, j]).statistic
                sp_spear[i, j] = spearmanr(X[:, i], X[:, j]).statistic

    # R 4.5.2 (exact VIF = 1/(1 - R^2_j) from lm(), identical to car::vif for 1-df numeric terms)
    tmp = Path(tempfile.mkdtemp(prefix="archtk_cov_"))
    try:
        csv_p = tmp / "cov.csv"
        csv_p.write_text(
            "x1,x2,x3,x4,aspect,y_circ\n"
            + "\n".join(
                f"{X[i,0]:.12g},{X[i,1]:.12g},{X[i,2]:.12g},{X[i,3]:.12g},{aspect_deg[i]:.12g},{y_circ[i]:.12g}"
                for i in range(n)
            ),
            encoding="utf-8",
        )
        r_out = tmp / "cov_r.json"
        r_script = tmp / "bench_cov.R"
        r_script.write_text(
            f"""df <- read.csv("{str(csv_p).replace(chr(92), '/')}")
M <- as.matrix(df[, c("x1","x2","x3","x4")])
cp <- as.numeric(cor(M, method="pearson"))
cs <- as.numeric(cor(M, method="spearman"))
vifs <- numeric(4)
for (j in 1:4) {{
  fit <- lm(M[, j] ~ M[, -j])
  vifs[j] <- 1.0 / (1.0 - summary(fit)$r.squared)
}}
rad <- df$aspect * pi / 180.0
cl_fit <- lm(df$y_circ ~ cos(rad) + sin(rad))
s <- summary(cl_fit)
r2_cl <- s$r.squared
f_val <- unname(s$fstatistic[1])
p_val <- pf(f_val, s$fstatistic[2], s$fstatistic[3], lower.tail=FALSE)
cat(sprintf('{{"pear":[%s],"spear":[%s],"vif":[%s],"cl_r2":%.15f,"cl_p":%.15e}}',
    paste(sprintf("%.15f", cp), collapse=","),
    paste(sprintf("%.15f", cs), collapse=","),
    paste(sprintf("%.15f", vifs), collapse=","),
    r2_cl, p_val), file="{str(r_out).replace(chr(92), '/')}")
""",
            encoding="utf-8",
        )
        subprocess.run([env["rscript_bin"], str(r_script)], check=True, capture_output=True, text=True)
        rc = json.loads(r_out.read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    r_pear = np.array(rc["pear"]).reshape(4, 4, order="F")
    r_spear = np.array(rc["spear"]).reshape(4, 4, order="F")
    r_vif = np.array(rc["vif"])
    return {
        "n_samples": n,
        "pearson_max_diff_vs_r": float(np.max(np.abs(at_pear - r_pear))),
        "pearson_max_diff_vs_scipy": float(np.max(np.abs(at_pear - sp_pear))),
        "spearman_max_diff_vs_r": float(np.max(np.abs(at_spear - r_spear))),
        "spearman_max_diff_vs_scipy": float(np.max(np.abs(at_spear - sp_spear))),
        "vif_max_rel_diff_vs_r_lm": float(np.max(np.abs(np.array(at_vif) - r_vif) / r_vif)),
        "vif_values": [round(float(v), 4) for v in at_vif],
        "circular_linear_r2_diff_vs_r": float(abs(float(at_cl["r2"]) - float(rc["cl_r2"]))),
        "circular_linear_p_diff_vs_r": float(abs(float(at_cl["p_value"]) - float(rc["cl_p"]))),
    }


def bench_ahp_and_trench_sat() -> Dict[str, Any]:
    """Benchmark 8: AHP principal eigenvector/CR vs SciPy eig; Trench 2D SAT vs Shapely GEOS."""
    from scipy.linalg import eig
    from shapely.geometry import Polygon, box as shp_box

    # AHP 5x5 and 12x12 (Alonso & Lamata RI)
    ahp_cases = {}
    for label, mat in [
        ("5x5", [
            [1, 3, 5, 7, 9],
            [1 / 3, 1, 3, 5, 7],
            [1 / 5, 1 / 3, 1, 3, 5],
            [1 / 7, 1 / 5, 1 / 3, 1, 3],
            [1 / 9, 1 / 7, 1 / 5, 1 / 3, 1],
        ]),
        ("12x12", [
            [1.0 if i == j else (float(min(9, j - i + 1)) if j > i else 1.0 / float(min(9, i - j + 1))) for j in range(12)]
            for i in range(12)
        ]),
    ]:
        at_w, at_lam, at_cr = ahp_core.ahp_weights_from_matrix(np.asarray(mat, dtype=float))
        vals, vecs = eig(np.asarray(mat, dtype=float))
        idx = int(np.argmax(vals.real))
        lam = float(vals[idx].real)
        w = np.abs(vecs[:, idx].real)
        w = w / float(np.sum(w))
        n = len(mat)
        ci = (lam - n) / (n - 1)
        cr = ci / ahp_core.RI_TABLE[n]
        ahp_cases[label] = {
            "weights_max_abs_diff_vs_scipy": float(np.max(np.abs(np.array(at_w) - w))),
            "lambda_max_diff_vs_scipy": float(abs(float(at_lam) - lam)),
            "cr_diff_vs_scipy": float(abs(float(at_cr) - cr)),
            "cr": round(float(at_cr), 5),
        }

    # Trench 2D SAT vs Shapely GEOS across 500 random rotated 2 m x 20 m trenches on 10 m grid
    rng = np.random.default_rng(2026)
    px = py = 10.0
    hx = hy = 5.0
    total_cells = 0
    exact_matches = 0
    for _ in range(500):
        cx = float(rng.uniform(20.0, 80.0))
        cy = float(rng.uniform(20.0, 80.0))
        bearing = float(rng.uniform(0.0, 180.0))
        th = math.radians(bearing)
        ux, uy = math.sin(th), math.cos(th)
        vx, vy = math.cos(th), -math.sin(th)
        hl, hw = 10.0, 1.0  # 20 m x 2 m trench
        corners = [
            (cx - hl * ux - hw * vx, cy - hl * uy - hw * vy),
            (cx + hl * ux - hw * vx, cy + hl * uy - hw * vy),
            (cx + hl * ux + hw * vx, cy + hl * uy + hw * vy),
            (cx - hl * ux + hw * vx, cy - hl * uy + hw * vy),
        ]
        poly = Polygon(corners)
        # Ensure CCW ordering like trench_suggestion_dialog._footprint_slope_max
        ring = corners + [corners[0]]
        area2 = sum(ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1] for i in range(4))
        if area2 < 0:
            ring = list(reversed(ring))
        minx, miny, maxx, maxy = poly.bounds
        c0, c1 = int(math.floor(minx / px)), int(math.floor(maxx / px))
        r0, r1 = int(math.floor(miny / py)), int(math.floor(maxy / py))
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                xs = (c + 0.5) * px
                ys = (r + 0.5) * py
                # Exact 2D SAT from trench_suggestion_dialog._footprint_slope_max
                sat_hit = True
                for i in range(4):
                    ax, ay = ring[i]
                    bx, by = ring[i + 1]
                    nx_, ny_ = (by - ay), -(bx - ax)
                    nlen = math.hypot(nx_, ny_)
                    if nlen <= 0:
                        continue
                    nx_ /= nlen
                    ny_ /= nlen
                    proj_edge = nx_ * ax + ny_ * ay
                    proj_c = nx_ * xs + ny_ * ys
                    radius = abs(nx_) * hx + abs(ny_) * hy
                    if (proj_c - radius) > proj_edge + 1e-12:
                        sat_hit = False
                        break
                # Axis-aligned box axes
                if sat_hit:
                    if (xs + hx < minx - 1e-12) or (xs - hx > maxx + 1e-12) or (ys + hy < miny - 1e-12) or (ys - hy > maxy + 1e-12):
                        sat_hit = False
                shp_hit = poly.intersects(shp_box(xs - hx, ys - hy, xs + hx, ys + hy))
                total_cells += 1
                if sat_hit == shp_hit:
                    exact_matches += 1

    return {
        "ahp": ahp_cases,
        "trench_2d_sat_vs_shapely_geos": {
            "n_trenches": 500,
            "n_cell_tests": total_cells,
            "exact_matches": exact_matches,
            "agreement_pct": round(100.0 * exact_matches / max(1, total_cells), 6),
        },
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, help="Optional path to write full JSON results")
    args = parser.parse_args(argv)

    env = _detect_env()
    print("[benchmark] Environment:", json.dumps(env["versions"], ensure_ascii=False))
    results: Dict[str, Any] = {"environment": env["versions"]}

    print("[benchmark] 1-3/8 Running Terrain, Viewshed, and Cost/LCP vs GDAL, GRASS 8.4, R terra...")
    tvc = bench_terrain_and_viewshed_and_cost(env)
    results.update(tvc)

    print("[benchmark] 4/8 Running Network SNA & MST vs R igraph and NetworkX...")
    results["network"] = bench_network(env)

    print("[benchmark] 5/8 Running PPA (Gabriel/RNG) vs SciPy Delaunay + O(N^3) verifier...")
    results["ppa"] = bench_ppa()

    print("[benchmark] 6/8 Running Ordinary Kriging & LOOCV vs R 4.5 & SciPy...")
    results["kriging"] = bench_kriging(env)

    print("[benchmark] 7/8 Running Covariate Corr/VIF/Circular-Linear R2 vs R 4.5 & SciPy...")
    results["covariate_stats"] = bench_covariate_stats(env)

    print("[benchmark] 8/8 Running AHP eig vs SciPy & Trench 2D SAT vs Shapely GEOS...")
    results["ahp_and_trench"] = bench_ahp_and_trench_sat()

    out_text = json.dumps(results, indent=2, ensure_ascii=False)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(out_text, encoding="utf-8")
        print(f"[benchmark] Saved JSON to {args.json}")
    else:
        print(out_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
