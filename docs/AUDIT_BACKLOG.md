# ArchToolkit 감사 백로그

감사 결과와 **코드 반영 상태**를 한 곳에 정리한 문서입니다. 상세 검증 로그(반박·재현·영향 3중 렌즈 원문, 외부 조회 근거)는 git 이력(커밋 dcb9a1f 이전 버전)에 남아 있고, 여기에는 판정과 조치만 남겼습니다.

| 장 | 내용 | 검증 수준 | 상태 |
| --- | --- | --- | --- |
| 1-3 | 인용 검증 (73건) | Crossref·Math-Net.Ru·law.go.kr 등 외부 1차 출처 직접 조회, 이견 항목은 3중 독립 판정 | 반영 완료 |
| 4 | 검증 하네스 계획 (14건) | 판독자가 수치를 직접 재현 | 미착수 (QGIS 불필요) |
| 5 | 코드 감사 — 검증 통과 (71건) | 반박·재현·영향 3중 렌즈 과반 생존 | 적용 71 / 일부 0 / 미적용 0 |
| 6 | 코드 감사 — 미검증 | 단일 판독자 1차 지적, 검증 미완주 | 실용성 기준으로 필요 시 개별 확인 |

**적용 기준(실용성):** 잘못된 수치가 나오는 결함은 고치고, 해석이 갈리는 지점은 라벨·메타데이터·메시지로 공개하며, 조용히 건너뛰던 입력은 로그·경고로 드러냈습니다. 기능을 제거한 항목은 없습니다.

## 1. 인용 검증 최종 요약 (73건 / 인벤토리 73건)

### 존재하지 않는 문헌: **0건**

조회한 문헌은 모두 실재합니다. 날조된 인용은 없습니다. 문제는 전부 *실재하는 문헌에 그 저자가 출판하지 않은 것을 붙인* 유형이었습니다.

| 최종 존재판정 | 건수 |
| --- | --- |
| `VERIFIED_EXACT` | 52 |
| `MISATTRIBUTED` | 9 |
| `DETAIL_MISMATCH` | 7 |
| `GREY_PLAUSIBLE` | 4 |
| `CONFLATED` | 1 |

| 최종 용례판정 | 건수 |
| --- | --- |
| `SUPPORTED` | 47 |
| `PARTIALLY_SUPPORTED` | 23 |
| `NOT_SUPPORTED` | 3 |

## 2. 실재하나 그 주장을 출판하지 않은 인용 (모두 반영됨)

### `conolly-lake-2006-cost-surface-ui-title` — MISATTRIBUTED / PARTIALLY_SUPPORTED  (3차 판정, confidence high)
- **교정**: Do NOT retitle to 'Bell & Lock relative slope (2000)'. Apply the de-attribution the project already accepted in its sibling dialog: set the group-box title to '상대경사 비용 (relative-slope cost)', either at tools/cost_surface_dialog_base.ui:372 or via a setTitle() call mirroring tools/cost_network_dialog.py:1272-1273. Keep the existing REFERENCES.md:97 entry — Conolly, J., & Lake, M. (2006). Geographic …

### `higuchi-1975-references` — CONFLATED / SUPPORTED  (3차 판정, confidence high)
- **교정**: CONFLATED as a string, but ALREADY CORRECTED in the live files — no change is needed to REFERENCES.md or the .ui. For the record, the correct form (which is what the repo now carries) is: 樋口忠彦 [Higuchi, T.] (1975). 『景観の構造 — ランドスケープとしての日本の空間』. 技報堂, 東京. (Japanese original; NDL also records 技報堂出版 for the printing carrying ISBN 9784765513777) / English translation: Higuchi, T. (1983). The Visual and S …

### `minetti-1995` — MISATTRIBUTED / PARTIALLY_SUPPORTED  (3차 판정, confidence high)
- **교정**: BIBLIOGRAPHY: no correction needed. Every field is exact (Crossref, verified independently below).

### `ngii-korean-slope-standard` — MISATTRIBUTED / NOT_SUPPORTED  (3차 판정, confidence high)
- **교정**: 산림청, 「공·사유림 경영계획 작성 및 운영요령」(산림청예규 제727호, 2025. 8. 22. 일부개정·시행) [별표] 「산림경영계획서 기재요령」(제4조제2항 관련), '1. 산림현황 ⑧ 경사도'. 원문(내가 직접 추출한 PDF 2쪽 verbatim): "⑧ 경사도 : 구획한 임지의 주경사도를 보고 구분한다. / 가. 완경사지(완) : 경사 15°미만 / 나. 경사지 (경) : 경사 15～20°미만 / 다. 급경사지(급) : 경사 20～25°미만 / 라. 험준지 (험) : 경사 25～30°미만 / 마. 절험지 (절) : 경사 30°이상". 이 항목은 ⑦ 산지구분(「산지관리법」 제4조)과 '2. 임황조사' 사이에 위치한 산림 임지(소반) 조사 기재 항목이다. 국토지리정보원(NGII)은 이 분류표를 발간 …

### `riley-1999-five-class-ui` — MISATTRIBUTED / NOT_SUPPORTED  (3차 판정, confidence high)
- **교정**: MISATTRIBUTED stands on the flagged text, but NO CODE CHANGE IS OUTSTANDING - the string was already removed before I looked. The bibliographic line in the same tooltip is and always was exact, and I confirmed every field myself: Riley, S.J., DeGloria, S.D., & Elliot, R. (1999). "A Terrain Ruggedness Index That Quantifies Topographic Heterogeneity." Intermountain Journal of Sciences 5(1-4): 23-27. …

### `riley-1999-threshold-recommendation-ui` — MISATTRIBUTED / NOT_SUPPORTED  (3차 판정, confidence high)
- **교정**: NOT an existence defect. The work is real and the plugin's bibliographic line for it (.ui:81) is exact: Riley, S.J., DeGloria, S.D., & Elliot, R. (1999). "A Terrain Ruggedness Index That Quantifies Topographic Heterogeneity." Intermountain Journal of Sciences 5(1-4): 23-27. What was misattributed is the RECOMMENDATION dressed onto it. The paper contains no recommended threshold, no sensitivity gui …

### `tobler-1993-slope-class-preset` — MISATTRIBUTED / PARTIALLY_SUPPORTED  (3차 판정, confidence high)
- **교정**: The bibliographic record is CORRECT and needs no correction. Full form: Tobler, W. (1993). Three Presentations on Geographical Analysis and Modeling: Non-Isotropic Geographic Modeling; Speculations on the Geometry of Geography; Global Spatial Analysis. NCGIA Technical Report 93-1, National Center for Geographic Information and Analysis, February 1993. The .ui tooltip's shortened form, naming only …

### `weiss-2001-class-names` — MISATTRIBUTED / PARTIALLY_SUPPORTED  (3차 판정, confidence high)
- **교정**: The BIBLIOGRAPHIC citation is correct and needs no change: Weiss, A. D. (2001). Topographic Position and Landforms Analysis. Poster presentation, ESRI International User Conference, San Diego, CA, 9-13 July 2001 (The Nature Conservancy, Northwest Division). What needs correcting is the SCHEME NAME and three class labels.

### `weiss-2001-recommended-parameter-values` — MISATTRIBUTED / PARTIALLY_SUPPORTED  (3차 판정, confidence high)
- **교정**: Weiss, A.D. (2001). Topographic Position and Landforms Analysis. Poster presentation, ESRI International User Conference, San Diego, CA, 9–13 July 2001. The Nature Conservancy, Northwest Division. — The bibliographic citation is CORRECT as given in REFERENCES.md:221; nothing needs fixing there. What must change is the PARAMETER ATTRIBUTION in the dialog. What Weiss actually publishes as parameter …

### `wilson-2007-tpi-index` — MISATTRIBUTED / PARTIALLY_SUPPORTED  (3차 판정, confidence high)
- **교정**: THE REFERENCE STRING NEEDS NO CHANGE. Every field is exact against Crossref and the published PDF's own running head. What is wrong is the label attached to it, and half of that has already been fixed in the working tree.

## 3. 서지 세부 오류 (모두 반영됨)

### `archtoolkit-self-citation-inconsistency` (3차 판정)
- - 교정: Reconcile on CITATION.cff, which is the only surface a citation tool actually parses (GitHub Docs: CITATION.cff is parsed into APA and BibTeX; a README BibTeX block is not parsed at all, and is not even among the alternative files GitHub will merely link to):

### `conolly-lake-2006-cost-network-undisclosed` (3차 판정)
- - 교정: Add the missing originator, and keep the book as the secondary source it is. Originator of the tan-ratio slope cost: Bell, T. & Lock, G. (2000). 'Topographic and cultural influences on walking the Ridgeway in later prehistoric times', in G. Lock (ed.), Beyond the Map: Archaeology and Spatial Technology. Amsterdam: IOS Press, pp. 85-100 — original f …

### `cuckovic-2024` (3차 판정)
- - 교정: Čučković, Z. (2025). Movement Analysis (QGIS plugin), version 0.1.2, slope_cost module. https://github.com/zoran-cuckovic/QGIS-movement-analysis/ — the cited slope-cost code was authored 2025-07-10 and first released in v0.1.2 (2025-07-11); the 2024 releases v0.1 and v0.1.1 contain no slope_cost.py and none of the cited formulas anywhere. (If the a …

### `delaunay-1934-tin` (3차 판정)
- - 교정: Delaunay, B. (1934). "Sur la sphère vide. À la mémoire de Georges Voronoï". Известия Академии наук СССР, VII серия, Отделение математических и естественных наук / Bulletin de l'Académie des Sciences de l'URSS, VII série, Classe des sciences mathématiques et naturelles, 1934, no. 6, pp. 793–800. (The journal carries no volume numbering; it is indexe …

### `naismith-1892` (3차 판정)
- - 교정: Naismith, W. W. (September 1892). "Cruach Ardran, Stobinian, and Ben More." In: "Excursions" [under the department "Notes and Queries"], *Scottish Mountaineering Club Journal*, 2(3), pp. 135-136 (the rule itself falls on p. 136). No DOI exists.

### `ngii-scale-resolution-standard` (3차 판정)
- - 교정: 해상도(격자간격)의 출처: 「3차원국토공간정보구축작업규정」(국토지리정보원고시 제2019-146호, 2019. 5. 23. 일부개정 / 시행 2019. 7. 1.) 제18조(3차원 지형데이터 편집방법) 제2항 — '수치지도 축척에 따른 수치표고모델의 격자간격은 다음 표와 같다': 수치지도 축척 1:1,000 → 수치표고자료 격자간격 1m×1m, 1:2,500 → 2m×2m, 1:5,000 → 5m×5m.

### `verhagen-whitley-2012` (3차 판정)
- - 교정: Verhagen, P., & Whitley, T. G. (2012). Integrating Archaeological Theory and Predictive Modeling: a Live Report from the Scene. *Journal of Archaeological Method and Theory* 19, 49-100. — suggested annotation: 귀납적(통계) 모델과 연역적(전문가 판단) 모델의 관계, 그리고 예측모델 검증(관측 편향·테스트 데이터 독립성)의 문제. [Only two changes are actually required: restore the dropped subtitle, a …

## 4. 검증 하네스 계획 (14건)

테스트가 지키지 못하는 영역과, **출판값으로 고정할 수 있는 구체적 단언** 목록입니다. "맞다고 믿는다"를 "맞다는 걸 보인다"로 바꾸는 작업이며, 이 장은 QGIS 없이도 바로 착수할 수 있습니다.

판독자가 실제로 재현한 값(발췌): ZT 곡률 `z=xy+0.5x²` → profile 1.6153846153846154 / plan 0.6153846153846154; C4 그래프 Brandes → `[0.5,0.5,0.5,0.5]` (가중·비가중 동일); AHP 3x3 (a=2,b=4,c=3) → λmax 3.01829470728963, CR 0.015771299387612077 (폐형식 `λ³-3λ² = ac/b + b/(ac) - 2` 와 일치); Tobler 평지 5.036742124615245 km/h; VIF ≡ 1/(1-r²) 오차 1e-13 이내; AHP 가이드 예시 3건 소수 4자리까지 재현.


#### [blocker] V1 — The whole least-cost engine (Dijkstra, A*, path reconstruction, move set) has zero tests and is unreachable without QGIS

- 위치: `tools/cost_surface_dialog.py` :676 (_neighbors), 697 (_astar_path), 797 (_dijkstra_full), 883 (_reconstruct_path)
- 문제: REFERENCES.md marks these (B) — formulas this plugin implements itself (Dijkstra 1959, Hart/Nilsson/Raphael 1968) — yet no test file imports them, and none can: cost_surface_dialog.py imports qgis.core/processing at module scope, and CI has no QGIS (test_align_export_qgis skips 8/8). tests/test_cost_models.py covers only the per-edge cost function; nothing covers accumulation, the reverse graph, friction averaging, NoData propagation or path reconstruction. Every number a user puts in a report — the accumulated-cost raster, the isochrone minutes, the LCP length — comes out of these 200 lines, and they are the only analytic code in the plugin with no test at all.
- 실패 시나리오: Change `nd = d + w` to accumulate `w` before the friction multiply (a plausible refactor when friction is moved out of the inner loop), or flip `edge_dz = -dz if reverse else dz`. Every test in the suite still passes, `python tests/check_static.py` passes, flake8 passes. A user runs a Tobler cost surface over a 5 m DEM with a friction raster; the isochrone labelled '60 min' now encloses an area computed with friction 1.0 everywhere, i.e. the wrong catchment, and the corridor raster (cost(A->x)+cost(x->B), which is the only consumer of reverse=True) becomes symmetric nonsense on a slope-asymmet …
- 제안 수정: STEP 1 of the harness. Move _neighbors, _astar_path, _dijkstra_full and _reconstruct_path verbatim into a new QGIS-free tools/cost_engine.py (they use only math, heapq, numpy and tools.cost_models.edge_cost; nothing else in their bodies touches qgis or gdal) and re-import them in cost_surface_dialog.py. Add tests/test_cost_engine.py asserting: (a) _neighbors(False, 5.0, 5.0) == [(-1,0,5.0),(1,0,5.0),(0,-1,5.0),(0,1,5.0)] and _neighbors(True, 5.0, 5.0) adds four moves of length math.hypot(5.0,5.0 …

#### [blocker] V2 — A* heuristic admissibility is never checked, so a suboptimal path can ship under the label 'least-cost path'

- 위치: `tools/cost_surface_dialog.py` :720-752 (hfun selection), 749
- 문제: A* returns the optimal path only if h never overestimates. Admissibility here rests on six separate, unasserted claims: that max Tobler speed is exactly tobler_base_kmh (true — the exponential peaks at slope=-offset), that Herzog's 6th-order denominator is >= 1.64 for every slope_abs >= 0, that the Conolly factor is clamped >= 1, that the wheeled speed factor is <= 1, that Naismith time >= distance/horizontal_kmh, and that friction_min (cost_surface_dialog.py:1195) really is the grid minimum. Not one is tested. Worse, edge_cost applies a *floor* `max(min_speed_mps, base*factor)` — if a user sets herzog_base_kmh below min_speed_mps*3.6 (0.18 km/h), the actual speed exceeds vmax and h becomes inadmissible with no warning.
- 실패 시나리오: Someone 'simplifies' the Herzog branch to drop the rel0=1/1.64 normalisation (it looks redundant), so rel_norm becomes 1/den and speeds at gentle slopes exceed herzog_base_kmh. vmax is still set to herzog_base_kmh, h now overestimates, and A* terminates on the first path that reaches the goal instead of the cheapest. test_cost_models.test_herzog_metabolic_flat_uses_base_speed fails — but only because it pins slope 0; if the change instead raised the speed only at nonzero slopes (e.g. a sign slip on the 19.825*s term), that test passes and A* silently returns a path that is not the least-cost p …
- 제안 수정: STEP 2, immediately after V1's extraction. tests/test_cost_engine.py::AstarAdmissibilityTests: for each of MODEL_TOBLER, MODEL_NAISMITH, MODEL_HERZOG_METABOLIC, MODEL_CONOLLY_LAKE, MODEL_HERZOG_WHEELED and MODEL_PANDOLF (cost_mode='energy_j'), build 50 seeded random 21x21 DEMs (np.random.default_rng(seed).normal(100,15)) plus one friction grid uniform in [0.5,3.0], run _astar_path(start=(0,0), end=(20,20)) and _dijkstra_full from the same start, and assert math.isclose(astar_total, dijkstra_dist …

#### [blocker] V3 — Ordinary Kriging has no test of any kind, and its variance raster is the number users would cite as uncertainty

- 위치: `tools/kriging_lite.py` :270 (_cov_exponential), 415-441 (get_inv), 486-496 (weights and variance)
- 문제: REFERENCES.md marks this (B) — the plugin implements Matheron's Ordinary Kriging itself — and DEVELOPMENT.md's coverage table does not list it, correctly, because there is no test. The module imports qgis.core at line 25 so nothing QGIS-free can reach it. Untested here: the augmented system assembly [C 1; 1 0], the unbiasedness constraint sum(lambda)=1, the sign of the Lagrange multiplier in the variance, the nugget-on-diagonal choice (np.fill_diagonal to partial_sill+nugget, i.e. C(0), which makes the system interpolate exactly rather than filter noise), and the exponential form exp(-h/range) versus the exp(-3h/range) 'practical range' convention that PyKrige/gstat/SAGA use. A user who cross-checks this plugin's variance map against SAGA will get a different picture and has no test result …
- 실패 시나리오: The Lagrange sign convention is flipped (vv = ... + mu instead of - mu) — a one-character change that looks like a fix to anyone comparing against a textbook that writes the system with -mu. Every existing test still passes. The variance GeoTIFF now reports its smallest values furthest from the data and its largest values on top of the sample points; an excavation report that shades 'low-confidence zones' from that raster shades exactly the wrong zones, and the prediction raster is unchanged so nothing looks wrong.
- 제안 수정: STEP 3. Extract a QGIS-free tools/kriging_math.py holding exponential_cov(dist, partial_sill, rng), build_ok_system(coords, partial_sill, nugget, rng) -> A, and solve_ok(coords, values, target_xy, partial_sill, nugget, rng) -> (zhat, variance, lam, mu); kriging_lite.py then imports them (the point-collection, spatial index and GeoTIFF writing stay behind QGIS). tests/test_kriging_math.py asserts: (a) exponential_cov(0.0, partial_sill=4.0, rng=10.0) == 4.0 and exponential_cov(10.0, ...) == 4.0*ma …

#### [major] V4 — The Herzog/Minetti 6th-order polynomial is tested only at slope 0, so no coefficient is pinned to a published value

- 위치: `tools/cost_models.py` :133-152
- 문제: tests/test_cost_models.py has exactly one Herzog-metabolic test, test_herzog_metabolic_flat_uses_base_speed, which evaluates the polynomial at slope_abs = 0 — where six of the seven coefficients vanish. Only the constant 1.64 is pinned, and it is pinned twice (it is also rel0), so even that is self-referential. The five coefficients that shape the entire cost surface (1337.8, 278.19, -517.39, -78.199, 93.419, 19.825) are protected by nothing. REFERENCES.md:84-89 names Minetti et al. (2002) and Herzog (2013) as the source and explicitly discloses the abs() isotropy departure — that disclosure is exactly the kind of statement that needs a test, because nothing currently prevents it from becoming false in either direction.
- 실패 시나리오: A transcription fix changes -78.199 to +78.199 (the published sequence alternates sign, so a 'correction' is plausible). At slope_abs = 0.2 the denominator goes from 8.062984 to 9.314 and the 100 m edge cost from 353.98466341463416 s to 408.9 s — a 15% change in every Herzog cost surface, isochrone and least-cost path the plugin produces. The whole test suite passes, because the only Herzog assertion is at slope 0 where that term is zero.
- 제안 수정: STEP 4, cheap and immediate. Add to tests/test_cost_models.py::HerzogMetabolicTests: (a) pin the polynomial itself — for s in (0.05, 0.1, 0.2, 0.3, 0.5) assert the implied denominator (recovered as 1.64 * base_mps * 100.0 / edge_cost(MODEL_HERZOG_METABOLIC, 100.0, 100.0*s, {})) equals the literal published sums 2.8519, 4.4309, 8.062984, 11.3442, 22.3921 to 4 dp, written out as constants, not recomputed from the same coefficient list; (b) pin one end-to-end value: edge_cost(MODEL_HERZOG_METABOLIC …

#### [major] V5 — Zevenbergen & Thorne curvature: no test exercises the cross-derivative F or the north-up row order, so plan curvature is unprotected

- 위치: `tools/terrain_math.py` :36-56
- 문제: All six curvature tests in tests/test_terrain_math.py use surfaces that are even in y and have no xy cross term: flat, z=3x+2y (curvature 0 by construction), z=0.5x^2, z=-0.5x^2 and z=0.5(x^2+y^2). On every one of them F == 0 and the y-derivative H either vanishes or is symmetric, so neither F's sign nor the row-order assumption is ever observed. Worse, the test helper builds its grid with ys = arange(n)*cell indexed by row — y INCREASING downward — which is the opposite of the north-up raster convention the code is written for (Z2 = roll(z,1,0) is the row above, i.e. larger y). The tests therefore pass under the wrong orientation, which is the strongest possible evidence that they cannot see it. Plan curvature on a real DEM is dominated by the F*G*H term; it is currently asserted only whe …
- 실패 시나리오: Someone 'fixes' H to (Z8 - Z2)/(2*cell) to match the test helper's y-increasing-downward grid, or reorders F's corner terms to (-Z1 + Z3 - Z7 + Z9). All six existing curvature tests still pass (F and the y-asymmetry are invisible to every one of them). On a real north-up DEM the plan curvature raster flips sign everywhere the surface is not symmetric: the layer written as '부호규약: 음=수렴' now marks divergent ridges as convergent hollows, and an erosion/deposition interpretation drawn from that map is inverted. The sign convention is the one thing REFERENCES.md tells reviewers to check by hand.
- 제안 수정: STEP 5. Add tests/test_terrain_math.py::ZtCurvatureCrossTermTests with a NORTH-UP grid helper (ys[i] = (n-1-i)*cell, so row 0 carries the largest y). On z = x*y + 0.5*x^2 over a 9x9 grid with cell=1.0, at the interior cell x=2.0, y=1.0 (i=7, j=2): assert profile == 21/13 == 1.6153846153846154 and plan == 8/13 == 0.6153846153846154, both to 1e-9. These follow from the published ZT algebra with D = z_xx/2 = 0.5, E = 0, F = z_xy = 1, G = z_x = 3, H = z_y = 2, giving ZT profile = -(z_xx*z_x^2 + z_yy …

#### [major] V6 — Brandes betweenness is never tested on a graph with tied shortest paths, so the sigma path-counting core is unasserted

- 위치: `tools/network_metrics.py` :73-121 (weighted), 157-188 (unweighted)
- 문제: The three topologies tests/test_network_metrics.py uses for betweenness values are PATH (0-1-2), STAR and TRIANGLE. In PATH and STAR every pair has exactly one shortest path; in TRIANGLE every pair is adjacent so no vertex is ever an intermediary. sigma is therefore 1 or 0 in every assertion, and the sigma[v]/sigma[w] dependency accumulation — the entire point of Brandes (2001), which REFERENCES.md names as the source — is never exercised. The weighted variant's tolerance branch (abs(nd - dist[w]) <= 1e-12, which is what splits credit between equal-cost routes on a cost network) is reached by no test at all. test_weighted_matches_unweighted_on_unit_weights only compares the two implementations against each other, so a shared bug is invisible.
- 실패 시나리오: The tie branch is changed to `sigma[w] = sigma[v]` (matching the improvement branch two lines above — a very easy copy-paste during a refactor). Every existing betweenness test passes: no test graph ever reaches that branch. On a real k-NN cost network with two equal-cost routes between settlements, the intermediary nodes on one route get full credit and the other route's nodes get none; the 'betweenness' column in the exported node layer, which is what a paper would rank sites by, is wrong for exactly the nodes a reader would care about most.
- 제안 수정: STEP 6, cheap. Add to tests/test_network_metrics.py: C4 = [[1,3],[0,2],[1,3],[0,2]] (the 4-cycle). Assert betweenness_centrality_unweighted(n=4, adj=C4) == [0.5, 0.5, 0.5, 0.5] to 1e-12 and betweenness_centrality_weighted(n=4, adj=unit-weighted C4) == the same — verified against the current implementation. The value is exact and hand-derivable: each opposite pair (0,2) and (1,3) has two shortest paths of length 2, so each intermediary takes 1/2, and the undirected 0.5 normalisation is already ap …

#### [major] V7 — AHP: Saaty's random index table is not pinned, and no inconsistent matrix with a known lambda_max is asserted

- 위치: `tools/ahp_core.py` :25-42 (RI_TABLE), 44-78 (ahp_weights_from_matrix)
- 문제: 48 AHP tests, and every lambda_max/CR assertion is on a PERFECTLY CONSISTENT matrix (built by _consistent_matrix, where lambda_max == n and CR == 0 by construction) or an ordering comparison (cr_near < cr_far, cr > 0.1). No test asserts a single RI value, and no test asserts a CR against an independently known number. RI is a pure divisor: every CR the dialog shows, and the CR > 0.10 warning that is the plugin's only consistency gate, scales directly with it. REFERENCES.md:130-135 sources n<=10 to Saaty (1980) and n=11..15 to Alonso & Lamata (2006) — an attribution with nothing behind it.
- 실패 시나리오: RI_TABLE[4] is edited from 0.90 to 0.89 (Saaty's later papers print 0.882 and 0.90 for n=4 depending on the sample size, so a 'correction' is plausible). Every one of the 48 AHP tests passes, because every CR assertion is either exactly 0 (RI cancels) or an inequality. A user's 4-criterion matrix that previously read CR = 0.1005 with the '(주의: 0.10 초과)' warning now reads CR = 0.0994 with no warning, and the AHP suitability map is published as consistent. The dialog's only quality gate silently moved.
- 제안 수정: STEP 7. Add tests/test_ahp_core.py::RandomIndexTests asserting the 15 RI values literally, with the source split commented (n<=10 Saaty 1980, n=11..15 Alonso & Lamata 2006), so any edit is a deliberate diff against a cited table; and assert that RI_TABLE has no entry for n=16 and that CR is NaN there (that half already exists). Add InconsistentMatrixTests using the published closed form for a 3x3 reciprocal matrix: with a12=a, a13=b, a23=c, the characteristic polynomial reduces to lambda^3 - 3*l …

#### [major] V8 — docs/AHP_GUIDE.md claims every number in it came from running the code, and nothing re-runs them

- 위치: `docs/AHP_GUIDE.md` :5, 64-68, 125, 134, 161, 248, 331
- 문제: Line 5 makes a verifiable promise about the whole document, and the guide is the artefact a user reads before defending their weights to a reviewer. I re-derived all three worked matrices through sanitize_pair_values -> matrix_from_pairs -> ahp_weights_from_matrix and they reproduce exactly (0.5333/0.2667/0.1333/0.0667 CR 0.0000; 0.5267/0.3005/0.1098/0.0630 CR 0.0074; 0.3150/0.3150/0.3150/0.0550 CR 1.0089). So the claim is true TODAY — and it is true by nobody's effort, because no test re-derives any of it. The scoring-mode table at lines 64-68 (benefit/cost/target/range/reclass over slope 0-40 deg) is likewise reproducible through score_formula and likewise unguarded.
- 실패 시나리오: The eigenvector selection in ahp_weights_from_matrix is changed from np.linalg.eig to the geometric-mean (row-product) approximation — a common and defensible AHP variant, and one that a maintainer might adopt to avoid the complex-eigenvalue branch. Every existing AHP test still passes: consistent matrices give the same weights under both methods, and the inconsistency tests are all inequalities. The guide's 52.7/30.1/11.0/6.3 and CR = 0.007 become 52.8/30.0/11.0/6.2 and CR reported differently, the documented example no longer matches what the dialog shows, and line 5's promise is now false w …
- 제안 수정: STEP 8. Add tests/test_ahp_guide_examples.py that re-derives each documented number through the real public API and asserts the printed value, with the doc line number in the assertion message. Specifically, with keys ['slope','river','geo','solar'] and pairs fed through sanitize_pair_values: (a) {2,4,8,2,4,2} -> weights rounded to 1 dp of percent == [53.3, 26.7, 13.3, 6.7] and round(CR,3) == 0.000 (AHP_GUIDE.md:125); (b) {2,5,7,3,5,2} -> [52.7, 30.1, 11.0, 6.3] and round(CR,3) == 0.007 (line 13 …

#### [major] V9 — 22 GDAL/QGIS enum integers are passed as bare literals with no test that any of them means what its comment says

- 위치: `tools/terrain_analysis_dialog.py` :609, 611, 663, 665, 687, 855 — plus viewshed_dialog.py:2008/2165/2616/4042, ahp_suitability_dialog.py:1760/1953/1981/2357, align_export_dialog.py:845, distance_raster_dialog.py:393/416, geology_zip_dialog.py:1198/1284, geochem_polygonize_dialog.py:1991, slope_aspect_drafting_dialog.py:613, trench_suggestion_dialog.py:983
- 문제: The integer for Float32 is 6 in gdal:warpreproject / gdal:cliprasterbymasklayer / gdal:cliprasterbyextent / gdal:translate (their lists are prefixed with 'Use Input Layer Data Type') but 5 in gdal:proximity, gdal:rasterize and gdal:rastercalculator's RTYPE (unprefixed). The plugin currently gets this right at every site I could resolve — distance_raster_dialog.py:416 uses 5 for gdal:proximity, terrain_analysis_dialog.py:687 uses 5 for RTYPE, terrain_analysis_dialog.py:611 uses 6 for warpreproject — but that correctness is held by comments, not by a test. Nothing in tests/ asserts a single one of these mappings, and the only test that touches a real GDAL algorithm, tests/test_align_export_qgis.py, skips all 8 of its tests in CI. tests/test_categorical_meta.py already proves the pattern work …
- 실패 시나리오: A maintainer harmonises the enums 'for consistency', changing terrain_analysis_dialog.py:687 from RTYPE 5 to RTYPE 6 because line 611 nearby uses 6 for the same intent (Float32). gdal:rastercalculator's RTYPE list is unprefixed, so 6 is Float64 — harmless. But the reverse edit, distance_raster_dialog.py:416 from DATA_TYPE 5 to 6 on gdal:proximity, makes the distance raster Float64 while the layer metadata and the covariate stack still describe a Float32 predictor; and terrain_analysis_dialog.py:611 changed from 6 to 5 makes the TPI focal-mean warp Int32, so the block average of an Int16 DEM tr …
- 제안 수정: STEP 9. Add tests/test_gdal_enums.py modelled on tests/test_categorical_meta.py::CallSiteCensusTests. Check in a table QGIS_OPTION_LISTS = {('gdal:warpreproject','DATA_TYPE'): ['Use Input Layer Data Type','Byte','Int16','UInt16','UInt32','Int32','Float32','Float64','CInt16','CInt32','CFloat32','CFloat64'], ('gdal:warpreproject','RESAMPLING'): ['Nearest neighbour','Bilinear','Cubic','Cubic spline','Lanczos','Average','Mode','Maximum','Minimum','Median','Q1','Q3'], ('gdal:rastercalculator','RTYPE' …

#### [major] V10 — VIF and the correlation matrix — the multicollinearity gate for every predictor stack — have no tests

- 위치: `tools/covariate_report_dialog.py` :100-123
- 문제: _compute_vif is a module-level pure-numpy function — it touches no QGIS object — yet it sits in a module that imports qgis.core at the top, so no QGIS-free test can reach it, and none exists. The report it feeds is the plugin's stated quality gate before a predictor stack goes into MaxEnt/GLM (the dialog prints '|r| >= 0.7 또는 VIF >= 5는 변수 중복 신호'), and REFERENCES.md positions the whole covariate report as the plugin's contribution to predictive modelling. Untested: the intercept column (without `ones` the R^2 is computed through the origin and every VIF is inflated), the r2 < 0.999999 cutoff that decides inf versus a finite value, the near-constant guard, and the NaN-versus-1.0 distinction the comment says matters.
- 실패 시나리오: The `ones` intercept column is dropped from `cols` during a cleanup (it looks redundant next to np.linalg.lstsq). For two centred, weakly correlated predictors the VIFs are unchanged; for two predictors with large non-zero means and r = 0.1 — slope in degrees and elevation in metres, the ordinary case — the through-origin R^2 approaches 1 and both VIFs jump past the VIF >= 10 '제거 권장' line. The user drops a genuinely independent predictor from their model on the plugin's advice, and the CSV export records the inflated number as evidence.
- 제안 수정: STEP 10. Extract _compute_vif and the correlation assembly into a QGIS-free tools/covariate_stats.py (the sampling and the HTML stay behind QGIS) and add tests/test_covariate_stats.py: (a) ANALYTIC IDENTITY — for a 2-column matrix, VIF == 1/(1 - r^2) for both columns, where r is np.corrcoef's value; with rng=default_rng(0), x=normal(500), y=0.8*x+sqrt(1-0.64)*normal(500), r == 0.822502609822486 and both VIFs == 3.0912908562254877, matching 1/(1-r^2) to 1e-13 (verified); assert the identity acros …

#### [major] V11 — Gabriel graph and RNG filters — two named published constructions — have no tests and sit behind a QGIS import

- 위치: `tools/spatial_network_dialog.py` :1605-1624 (_ppa_filter_gabriel), 1625-1647 (_ppa_filter_rng)
- 문제: REFERENCES.md marks both (B) with named sources (Gabriel & Sokal 1969; Toussaint 1980) and describes the exact geometric predicate each implements. Both function bodies are pure numpy on a coords array — no QGIS type crosses the boundary — but they are methods on a QgsDialog subclass in a module that imports qgis.core, so nothing tests them. The Gabriel test is the diameter-circle emptiness test and the RNG test is the lune emptiness test; they differ only in the predicate, and a copy-paste between them (they are 20 lines apart and structurally identical) would produce a graph that is still plausible-looking, still connected, and wrong.
- 실패 시나리오: The RNG predicate's np.maximum is changed to np.minimum — the lune test becomes 'some point is closer to EITHER endpoint' instead of 'to BOTH'. On the unit square plus its centre, RNG currently keeps exactly the four spokes {(0,4),(1,4),(2,4),(3,4)} and rejects all four sides; with np.minimum it rejects the spokes too and returns the empty set, or on other configurations returns a sparser graph. The exported PPA network layer, the closeness/betweenness columns computed on it, and any 'site X is a broker' claim drawn from them are all derived from the wrong edge set, and the layer name still sa …
- 제안 수정: STEP 11. Extract both filters as free functions into a QGIS-free tools/ppa_filters.py taking (cand_edges, coords) exactly as now, and have the dialog call them. tests/test_ppa_filters.py, with coords = [[0,0],[1,0],[1,1],[0,1],[0.5,0.5]] (unit square plus centre) and cand_edges = all 10 pairs: (a) gabriel(...) == {(0,1),(1,2),(2,3),(0,3),(0,4),(1,4),(2,4),(3,4)} — the four sides and four spokes, with the two diagonals (0,2) and (1,3) REJECTED because the centre sits at their midpoint, i.e. on th …

#### [major] V12 — The broad-scale TPI radius arithmetic, the viewshed curvature coefficient and the Higuchi zone resolution are pure logic with no tests

- 위치: `tools/terrain_analysis_dialog.py` :601 (new_res); viewshed_dialog.py:457-471 (_calculate_gdal_viewshed_cc); viewshed_dialog.py:4637-4685 (_get_higuchi_thresholds/_resolve_higuchi_thresholds/_format_higuchi_distance)
- 문제: Three pieces of user-visible arithmetic that are each a handful of pure lines with no QGIS dependency in the body, each currently reachable only through a dialog instance. (1) new_res encodes the (2r+1) fix the docstring says was necessary because 'a block of radius cells would have delivered only about half the radius the label claims' — the layer name then prints that radius as fact. (2) _calculate_gdal_viewshed_cc maps the UI's refraction coefficient k onto GDAL's -cc argument, including the rule that refraction forces curvature on and the [0,1] clamp; every viewshed the tool produces passes through it. (3) The Higuchi resolution enforces near < mid by swapping and nudging, and those two numbers are written into the layer metadata as higuchi_near_m / higuchi_mid_m, which REFERENCES.md t …
- 실패 시나리오: new_res is changed to max(px,py) * radius (reverting the documented fix, which reads like an off-by-one). On a 5 m DEM with radius 13 the block goes from 135 m to 65 m, so the 'TPI (근사 반경≈13셀)' layer and the Weiss landform classification built on it are computed over half the intended window — and the layer name, the metadata and the help text all still say 13 cells. Separately, dropping the `if refraction and not curvature: curvature = True` line makes a user who ticks refraction but not curvature get -cc 0 (no correction at all) while the dialog's help panel still describes a refraction-corr …
- 제안 수정: STEP 12. Move all three into QGIS-free helpers — tools/terrain_math.py gains tpi_block_resolution(pixel_x, pixel_y, radius); a new tools/viewshed_math.py gains gdal_viewshed_cc(curvature, refraction, refraction_coeff) and resolve_higuchi_thresholds(near_m, mid_m) / format_higuchi_distance(v) — and have the dialogs delegate. Assertions: (a) tpi_block_resolution(5.0, 5.0, 13) == 135.0 and tpi_block_resolution(5.0, 5.0, 1) == 15.0, i.e. radius 1 reproduces gdaldem's 3x3 span, which is the invariant …

#### [major] V13 — The least-cost network MST is Kruskal over a candidate-pair subgraph, with no test that the result is a spanning tree at all

- 위치: `tools/cost_network_dialog.py` :178 (_UnionFind), 958-976 and 1010-1028 (the Kruskal loops)
- 문제: REFERENCES.md marks the MST (B) and names Kruskal (1956), and the tool help at cost_network_dialog.py:1167 and :2024 repeats it. The implementation is a correct Kruskal — over `candidate_pairs`, not over the complete graph. If candidate_pairs is a k-NN or distance-thresholded subset, or if any sym_cost is None (an unreachable pair), the loop terminates with fewer than len(hub_list)-1 edges and the result is a spanning FOREST, which is then written out as a layer whose edge kind is literally 'mst' and 'hub_mst'. Nothing tests the union-find, the sort order, the early-exit at len(hub_list)-1, or the forest case, and the whole thing is behind a QGIS import.
- 실패 시나리오: Five hubs where the cost raster leaves hub E in a separate valley, so no candidate pair involving E has a finite cost. The loop unions A-B-C-D into one component, produces 3 edges, never reaches the len(hub_list)-1 == 4 early exit, and returns. The output layer contains a 4-node tree plus an orphan, styled and labelled as the minimum spanning tree of five sites. A reader of the resulting map concludes E was not connected to the network in antiquity, when in fact the analysis window simply never reached it. Separately, if _UnionFind.union ever returns True for an already-joined pair (a path-com …
- 제안 수정: STEP 13. Extract _UnionFind and a free function kruskal_mst(n, weighted_edges) -> set of edges into a QGIS-free tools/mst.py (both are pure python) and have both call sites use it. tests/test_mst.py: (a) on the 4-node graph with edges (0,1,1.0),(1,2,2.0),(2,3,3.0),(0,3,4.0),(0,2,5.0) assert the MST is exactly {(0,1),(1,2),(2,3)} with total weight 6.0 — hand-computable and unambiguous; (b) a graph with two edges of identical weight asserts a DETERMINISTIC choice (the sort is by weight only, so ti …

#### [major] V14 — The CI harness cannot notice an unlisted test file, runs zero QGIS/GDAL code, and pins the cost-budget constants to themselves

- 위치: `.github/workflows/ci.yml` :19-35 (the hand-maintained unittest list), plus tests/test_align_export_qgis.py:38 and tests/test_cost_budget.py:33-41
- 문제: Three harness-level gaps that undercut every test above. (1) CI enumerates 15 modules by hand; unittest discovery does not work from tests/ (no __init__.py, ImportError: Start directory is not importable). DEVELOPMENT.md:82 tells contributors to remember to add new files to ci.yml, and nothing enforces it — a new tests/test_cost_engine.py would be invisible to CI while looking fully covered in the repo. (2) tests/test_align_export_qgis.py reports 'OK (skipped=8)' on the CI runner, so the plugin's ONLY tests that touch a real gdalwarp — including the one that would confirm raster_grid_contract's central claim that GDAL sizes with floor(ratio + 0.5) — have never run in CI. The grid contract that gates whether an aligned export is published is therefore validated only against its own arithmet …
- 실패 시나리오: (1) A contributor adds tests/test_cost_engine.py from V1, it passes locally, and they forget ci.yml. Six months later a refactor breaks _dijkstra_full; CI is green on every commit because the file is never invoked. (2) A QGIS upgrade changes gdalwarp's rounding at exact half-cell extents from round-half-up to round-half-even. canonical_gdal_target_grid still computes floor(ratio+0.5), so validate_grid rejects a correct warp output with GridMismatchError('width') and align/export refuses to publish — or, if the tolerance happens to absorb it, publishes a grid one cell off from the contract. Bot …
- 제안 수정: STEP 14, do this FIRST because it is what makes steps 1-13 stick. (a) Add tests/test_ci_wiring.py: parse .github/workflows/ci.yml with a regex for `python -m unittest tests\.(\w+)`, collect the set, glob tests/test_*.py, and assert the two sets are equal — the failure message naming the missing module. This is the same census pattern tests/test_categorical_meta.py::CallSiteCensusTests already uses. (b) Add a second CI job on the qgis/qgis:release-3_40 (or ghcr equivalent) image that runs `python …

## 5. 코드 감사 findings — 적대적 검증 통과 (71건) 및 반영 상태

각 finding을 반박 / 재현 / 영향 세 렌즈로 독립 검증해 과반이 실재로 판정한 것만 남겼습니다(167건 검증 중 96건 기각). 상태: **적용** = 코드 반영, **일부** = 핵심만 반영(비고 참조), **미적용** = 실용성 판단으로 보류.

### 지구화학도(GeoChem)

| ID | 심각도 | 내용 | 위치 | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- |
| G1 | blocker | Any off-legend colour is silently forced onto the nearest legend segment; the dark corner of RGB space lands on the legend MAXIMUM, so black linework and its anti-alias halo are reported as top-percentile anomalies | `tools/geochem_legend.py` | 적용 | 색 매칭 허용오차(RGB 48) 초과 픽셀 NoData + 경고, 어두운 halo 마스크 |
| G3 | minor | Output-options help calls the inverted raster '원본 데이터' (original data) and recommends it for MaxEnt/statistics, contradicting the dialog's own '역추정' caveat | `tools/geochem_polygonize_dialog.py` | 적용 | 라벨·툴팁·폴백 경고 |
| G4 | major | Zonal statistics rasterize every zone with ALL_TOUCHED=TRUE, so pix_in, c*_area, cov_pct and val_* are computed over a dilated zone | `tools/geochem_polygonize_dialog.py` | 적용 | 구역은 픽셀 중심 규칙(all_touched=False), zone_area/burn_rule 필드 |
| G5 | major | px_area and every c*_area in the zonal-stats layer are in raster-CRS units squared but presented as plain 'area'; on a geographic WMS they are square degrees | `tools/geochem_polygonize_dialog.py` | 적용 | area_unit 필드 |
| G6 | major | The automatic pixel size is not the canvas resolution the label and tooltip promise: it silently becomes extent/1024 whenever the project CRS differs from the raster CRS, and silently coarsens again at the 12 Mpx cap | `tools/geochem_polygonize_dialog.py` | 적용 | 캔버스 해상도를 래스터 CRS로 환산, 폴백·상한 경고, pixel_size_source 메타데이터 |
| G7 | major | Inpainted (fabricated) pixels are indistinguishable from measured ones downstream, and cov_pct - the only field that could reveal it - counts them as measured | `tools/geochem_polygonize_dialog.py` | 적용 | inpaint 비율 메타데이터 + 구역 fill_pct 필드 |
| G8 | major | '최댓값을 범례 최댓값으로 보정' rescales every pixel by a factor derived from the clip's own maximum - including pixels outside the AOI - and the result is recorded nowhere | `tools/geochem_polygonize_dialog.py` | 적용 | AOI 마스크 후 최댓값 계산, fix_max 메타데이터, 툴팁 경고 |
| G9 | major | _import_preset_from_legend_image samples the lowest and highest legend anchors at image row 0 and row h-1, i.e. in the legend image's margin, silently assigning the border colour to the extreme values | `tools/geochem_polygonize_dialog.py` | 적용 | 밴드 중앙 샘플링, 여백/투명/동일색 검출 시 거부 |
| G10 | minor | _legend_points_from_csv truncates RGB with int(float(...)) and clamps to 0-255 with no validation, so a 0-1 normalised or mis-columned CSV silently produces an all-black legend - and an all-black legend maps every pixel to the maximum | `tools/geochem_polygonize_dialog.py` | 적용 | 0-1 환산, 범위 초과 거부, 단위 테스트 |
| G11 | major | Six of the seven shipped element presets use a colour ramp the code comments admit was assumed, and none of the break values is cited anywhere | `tools/geochem_polygonize_dialog.py` | 적용 | 프리셋 출처·가정을 툴팁/REFERENCES.md에 명시; 팔레트 불일치는 G1 허용오차로 검출 |
| G12 | minor | The AOI '선택 피처만 사용' tooltip promises a fallback to all features that the code does not implement, while the zone layer's identical option silently does fall back | `tools/geochem_polygonize_dialog.py` | 적용 | 라벨·툴팁·폴백 경고 |
| G13 | minor | Weighted-centre rule labelled '값 그대로 (w = value)' silently zeroes negative values while pix_n keeps counting them | `tools/geochem_polygonize_dialog.py` | 적용 | 라벨·툴팁·폴백 경고 |
| G14 | minor | Preset combo tooltip and module docstring still claim Fe2O3 is the only preset while seven ship | `tools/geochem_polygonize_dialog.py` | 적용 | 라벨·툴팁·폴백 경고 |

### 공간 네트워크(PPA/가시성)

| ID | 심각도 | 내용 | 위치 | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- |
| SN-01 | major | LOS has no NaN guard: a site on a NaN DEM cell is reported visible to every other site | `tools/spatial_network_dialog.py` | 적용 | NaN 가드, 샘플 상한 5000 + 알림, Web Mercator 경고 |
| SN-02 | major | Visibility network uses a flat-earth sight line: no curvature or refraction, not disclosed, and contradicted by the plugin's own viewshed and by REFERENCES.md | `tools/spatial_network_dialog.py` | 적용 | 곡률·굴절 보정(기본 k=0.13) + UI 토글, 메타데이터 기록 |
| SN-03 | major | LOS sampling is silently capped at 2000 points, so long sight lines are sampled far coarser than the requested step and the DEM | `tools/spatial_network_dialog.py` | 적용 | NaN 가드, 샘플 상한 5000 + 알림, Web Mercator 경고 |
| SN-04 | major | Delaunay/Gabriel/RNG silently drop every duplicate-coordinate node, publishing it as an isolated site | `tools/spatial_network_dialog.py` | 적용 | 좌표 중복 노드는 간선 공유 + 경고 |
| SN-05 | major | vis_ratio_ab measures the observer polygon's boundary, but the guide says it shows how much of the target is visible | `tools/spatial_network_dialog.py` | 적용 | 문구 수정; betw_norm 필드 추가 |
| SN-06 | major | A failed LOS sample (NoData) is written into the node layer as 'not visible', so untested sites are published as isolated | `tools/spatial_network_dialog.py` | 적용 | fail_deg 필드 + 완료 메시지 경고 |
| SN-07 | minor | betweenness is raw Brandes pair counts, but nothing user-facing says so | `tools/spatial_network_dialog.py` | 적용 | 문구 수정; betw_norm 필드 추가 |
| SN-08 | major | The metric-CRS check passes Web Mercator, so dist_km and every distance threshold are inflated ~26% at Korean latitudes | `tools/spatial_network_dialog.py` | 적용 | NaN 가드, 샘플 상한 5000 + 알림, Web Mercator 경고 |
| SN-09 | minor | No LOS run parameter is recorded in the layer name or layer metadata, so a saved visibility network cannot be reproduced or told apart from another run | `tools/spatial_network_dialog.py` | 적용 | 실행 파라미터를 레이어 메타데이터·이름에 기록 |
| SN-10 | minor | Degree legend produces an inverted final class label when every node has the same degree | `tools/spatial_network_dialog.py` | 적용 | 동일 degree 범례 단일 클래스 |
| SN-11 | minor | Turner et al. (2001) VGA is cited as a reference for a site-to-site intervisibility network, which is a different method | `tools/spatial_network_dialog.py` | 적용 | 문구 수정; betw_norm 필드 추가 |

### 트렌치 제안

| ID | 심각도 | 내용 | 위치 | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- |
| F-TR-01 | major | Grave avoidance fails open on a null union while the UI reports "N graves avoided" | `tools/trench_suggestion_dialog.py` | 적용 | null 유니온 가드, footprint 최대경사 검사 + slope_max_deg, ahp_norm 메타데이터 |
| F-TR-02 | major | Grave keyword list misses the standard Korean burial-type vocabulary (지석묘/고인돌/석실묘/토광묘/옹관묘/총/릉) | `tools/trench_suggestion_dialog.py` | 적용 | 매장 유형 어휘 14종 + 총/릉 접미 규칙, 영문 4종 |
| F-TR-03 | major | Hidden-legend XLS fallback parses the OGR sublayer string wrongly, so the OGR path never returns a single row | `tools/trench_suggestion_dialog.py` | 적용 | 서브레이어 문자열 파싱 수정, xlsx/xlsm 허용 |
| F-TR-04 | major | "최대 허용 경사" is tested only at the trench centre, so a proposed trench can cross ground far steeper than the limit | `tools/trench_suggestion_dialog.py` | 적용 | null 유니온 가드, footprint 최대경사 검사 + slope_max_deg, ahp_norm 메타데이터 |
| F-TR-05 | major | The exported `rank` field is coverage round-robin order, not score order — rank N can score lower than rank N+k | `tools/trench_suggestion_dialog.py` | 적용 | rank=점수순, pick_order=선별순, 메타데이터에 전략 기록 |
| F-TR-06 | major | AHP score is min-max stretched over the AOI BOUNDING BOX, silently changing the effective AHP weight the metadata reports | `tools/trench_suggestion_dialog.py` | 적용 | null 유니온 가드, footprint 최대경사 검사 + slope_max_deg, ahp_norm 메타데이터 |
| F-TR-07 | minor | Grave features are fetched with a ~6 m margin while a long trench can extend 25 m outside the AOI bounding box | `tools/trench_suggestion_dialog.py` | 적용 | 그레이브 조회 사각형을 buffer + length/2 + 5 m로 확장 |
| F-TR-08 | minor | Legend code regex misses codes written adjacent to Hangul, losing code-based grave avoidance for those rows | `tools/trench_suggestion_dialog.py` | 적용 | 코드 정규식 lookaround |
| F-TR-09 | minor | ref_dist_m can report a site that is not the nearest, because only 8 spatial-index neighbours are measured | `tools/trench_suggestion_dialog.py` | 적용 | ref_radius 내 전수 측정으로 ref_dist_m 정확화 |
| F-TR-10 | major | "AOI 선택 피처만 사용" silently unions every feature when nothing is selected | `tools/trench_suggestion_dialog.py` | 적용 | 선택 없음 시 전체 사용을 경고·메타데이터로 공개 |

### 지질도 ZIP

| ID | 심각도 | 내용 | 위치 | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- |
| GEO-01 | blocker | Rasterize sets a NoData value but never initialises the grid: every uncovered cell is a real 0, not NoData | `tools/geology_zip_dialog.py` | 적용 | INIT=NODATA, 실행 전체 공유 코드표 + labels_all, CRS 검증 |
| GEO-02 | blocker | Merged multi-sheet raster reuses each sheet's raw numeric code, and the mapping CSV keeps only the first sheet's label for a colliding code | `tools/geology_zip_dialog.py` | 적용 | INIT=NODATA, 실행 전체 공유 코드표 + labels_all, CRS 검증 |
| GEO-03 | major | Per-layer mode names outputs from the layer name only, so two sheets' identically named Litho layers overwrite each other's raster and mapping CSV | `tools/geology_zip_dialog.py` | 적용 | 도엽명+레이어명 파일명, 중복 시 접미사 |
| GEO-04 | major | String lithology codes are numbered per output and per run, so codes are not comparable between sheets or between two runs of the same tool | `tools/geology_zip_dialog.py` | 적용 | INIT=NODATA, 실행 전체 공유 코드표 + labels_all, CRS 검증 |
| GEO-05 | major | Layer CRS is never validated; a sheet with a missing or unrecognised .prj yields a raster with no CRS and is reported as success | `tools/geology_zip_dialog.py` | 적용 | INIT=NODATA, 실행 전체 공유 코드표 + labels_all, CRS 검증 |
| GEO-06 | major | Writing the code mapping CSV fails silently, leaving an integer raster nobody can decode and no message of any kind | `tools/geology_zip_dialog.py` | 적용 | CSV 쓰기 실패 경고 |
| GEO-07 | major | Features are dropped from the burn for four different reasons, and none of them is counted or reported | `tools/geology_zip_dialog.py` | 적용 | 사유별 드롭 카운터 보고, numeric 판정 전체 도엽 기준 |
| GEO-08 | major | ASCII Grid export of a geographic-CRS sheet writes a non-standard dx/dy header that ArcGIS and MaxEnt cannot read, and reports success | `tools/geology_zip_dialog.py` | 적용 | 지리 CRS .asc 경고(내보내기는 유지) |
| GEO-09 | major | Field auto-selection silently falls back to an arbitrary attribute and still tags the result as a lithology class raster | `tools/geology_zip_dialog.py` | 적용 | 필드 대체를 가시적 경고/스킵으로, Double 절삭 고지 |
| GEO-10 | minor | Units narrower than one cell vanish from the raster while the mapping CSV still lists them with a feature count | `tools/geology_zip_dialog.py` | 적용 | cell_count 열 + 미소각 코드 경고 |
| GEO-13 | minor | Extracted sheets are deleted after 90 days without the user ever being told they live in a managed folder | `tools/geology_zip_dialog.py` | 적용 | 추출 폴더·보존 기간 안내 |

### DEM 생성

| ID | 심각도 | 내용 | 위치 | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- |
| DEMGEN-01 | blocker | 2D contour layers silently produce an all-NoData DEM reported as "DEM 생성 완료!" — including the plugin's own 등고선 추출 output | `tools/dem_generator_dialog.py` | 적용 | 표고 필드 후보 확대, 2D 레이어 거부, all-NoData 결과 거부 |
| DEMGEN-02 | minor | Kriging (Lite) does not honour the input spot heights: a 30.00 m surveyed benchmark comes back as 25.05 m at its own location | `tools/kriging_lite.py` | 적용 | 크리깅 정확 보간(C(0)=psill+nugget 양변 일치), 테스트 고정 |
| DEMGEN-03 | major | The DXF layer-code filter is applied to ANY selected layer that has a field named "Layer", using checkbox defaults the user may never have opened | `tools/dem_generator_dialog.py` | 적용 | DXF 코드 필터는 플러그인 로드 DXF에만, 필터 전후 피처 수 보고 |
| DEMGEN-04 | major | A stale DEM left at the output path from an earlier run is re-loaded and reported as this run's result | `tools/dem_generator_dialog.py` | 적용 | publish 플래그로 성공 판정 |
| DEMGEN-05 | minor | TIN/IDW output pixels are not the requested pixel size, and are not square — but the metadata records the requested size as fact | `tools/dem_generator_dialog.py` | 적용 | extent를 픽셀 정수배로 스냅, 실제 x/y 픽셀 크기 메타데이터 |
| DEMGEN-06 | major | Merging a 2D contour layer with a 3D one silently assigns 0 m elevation to every 2D vertex | `tools/dem_generator_dialog.py` | 적용 | Z 없는 레이어 병합 거부 |
| DEMGEN-07 | minor | When the Kriging Z field is auto-detected, nothing records which attribute the DEM was actually built from | `tools/dem_generator_dialog.py` | 적용 | 실제 사용한 값 필드 기록 |
| DEMGEN-08 | minor | DXF files that fail to load produce no message at all | `tools/dem_generator_dialog.py` | 적용 | 실패 DXF 이름 보고 |

### 정렬/내보내기

| ID | 심각도 | 내용 | 위치 | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- |
| AE-01 | blocker | Aspect (a circular variable in degrees) is bilinearly resampled, producing directions that point the wrong way | `tools/align_export_dialog.py` | 적용 | aspect 등 방향 래스터는 최근접 리샘플링 |
| AE-02 | major | A raster with no ArchToolkit metadata falls into the unsafe branch: class codes are bilinearly blended and the manifest positively asserts categorical=no | `tools/align_export_dialog.py` | 적용 | 메타데이터 없는 래스터는 categorical=unknown, 소정수 휴리스틱 |
| AE-03 | major | Variable-key uniqueness is case-sensitive but the output filenames are not: on Windows/macOS one predictor's file is overwritten by another's data | `tools/predictor_naming.py` | 적용 | 변수 키 대소문자 무시 유일성 + 테스트 |
| AE-04 | major | The layer's QGIS CRS override is discarded: SOURCE_CRS=None with a bare file path means gdalwarp reprojects from the file's embedded CRS, not the one the user assigned | `tools/align_export_dialog.py` | 적용 | SOURCE_CRS 전달, source_crs 열 |
| AE-05 | minor | A source raster that does not overlap the reference grid publishes an all-NoData predictor and is reported as successfully aligned | `tools/align_export_dialog.py` | 적용 | 유효 픽셀 0이면 실패, valid_pct 열, 범위 불교차 사전 경고 |
| AE-06 | major | The dialog, the help and the README all state NoData is part of the common reference grid; the code deliberately never unifies it | `tools/align_export_dialog.py` | 적용 | 공통 격자 = CRS·범위·픽셀; NoData는 래스터별 |

### AI 보고서 컨텍스트

| ID | 심각도 | 내용 | 위치 | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- |
| AI-CTX-01 | blocker | "Nearest site" and the reference-site classification counts are taken from the first 120 features in file order, not the nearest 120 | `tools/ai_aoi_summary.py` | 적용 | 전수 분류 후 거리순 상위만 상세, scan_truncated 플래그 |
| AI-CTX-02 | major | A Gemini response truncated at maxOutputTokens is presented as a finished report ('완료') and written to report.md | `tools/ai_gemini.py` | 적용 | finishReason 확인, 잘린 응답 배너 |
| AI-CTX-03 | major | '선택된 피처만 사용' with an empty selection silently analyses the entire AOI layer while the report still says only the selection was used | `tools/ai_aoi_summary.py` | 적용 | 선택 없음 폴백을 컨텍스트·헤더에 기록 |
| AI-CTX-04 | major | Per-layer length/area are measured in the layer's own CRS with no geographic guard, so a WGS84 layer yields square degrees in fields named total_area_m2 / total_length_m | `tools/ai_aoi_summary.py` | 적용 | QgsDistanceArea 단위 변환 + WGS84 폴백 |
| AI-CTX-05 | major | The 20,000-feature scan cap truncates feature counts and length/area sums, and the context and CSV carry no truncation flag | `tools/ai_aoi_summary.py` | 적용 | 절단·표본·생략 플래그를 컨텍스트/CSV/프롬프트에 기록 |
| AI-CTX-06 | major | Raster min/mean/max are computed from a nearest-neighbour subsample with no record that the raster was decimated | `tools/ai_aoi_summary.py` | 적용 | 절단·표본·생략 플래그를 컨텍스트/CSV/프롬프트에 기록 |
| AI-CTX-07 | minor | gt_0_5_pct is labelled a 'mask/visibility ratio' but its near-binary detector is max-relative while its threshold is a hard-coded 0.5 | `tools/ai_aoi_summary.py` | 적용 | 두 값 검출 + 중간값 임계, 라벨은 viewshed일 때만 가시 비율 |
| AI-CTX-08 | minor | Numeric-field statistics are silently capped at 12 (8 in the local report) and the id-field regex discards single-letter element columns | `tools/ai_aoi_summary.py` | 적용 | 절단·표본·생략 플래그를 컨텍스트/CSV/프롬프트에 기록 |
| AI-CTX-09 | minor | The 40-layer cap drops layers in layer-id dictionary order, including layers the user explicitly picked, with no per-run record of what was dropped | `tools/ai_aoi_summary.py` | 적용 | 절단·표본·생략 플래그를 컨텍스트/CSV/프롬프트에 기록 |

### 거리 래스터

| ID | 심각도 | 내용 | 위치 | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- |
| DIST-01 | blocker | Polygons narrower than a cell are silently dropped by the default pixel-centre burn rule, inflating every distance | `tools/distance_raster_dialog.py` | 적용 | 선·면은 ALL_TOUCH, burn_rule 메타데이터 |
| DIST-02 | blocker | Nothing checks that the burn produced any target cell, so an all-NoData distance raster is reported as a finished predictor | `tools/distance_raster_dialog.py` | 적용 | 대상 셀 0 / 전부 NoData이면 거부 |
| DIST-03 | blocker | A non-square reference grid makes every distance wrong: gdal_proximity scales both axes by the X pixel size | `tools/distance_raster_dialog.py` | 적용 | 비정사각 픽셀 거부 |

### 검증 필터에서는 기각됐지만 메커니즘이 실재해 반영한 항목

| ID | 상태 | 비고 |
| --- | --- | --- |
| GEO-10 | 적용 | cell_count 열 + 미소각 코드 경고 |
| GEO-11 | 적용 | utf-8-sig |
| G2 | 적용(공개) | 값 라벨·REFERENCES.md에 구간표 특성(최상위 구간=상한값) 명시 |

## 6. 코드 감사 findings — 미검증 (제목만)

검증 팬아웃이 사용량 한도로 완주하지 못한 영역입니다. 같은 검증을 거친 167건 중 57%가 기각된 점을 감안해 **확정 결함으로 읽지 마십시오.** 실용성 기준으로 필요할 때만 개별 확인합니다.
