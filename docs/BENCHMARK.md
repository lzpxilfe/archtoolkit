# ArchToolkit 외부 기준 소프트웨어 교차 벤치마크

본 문서는 ArchToolkit 0.1.7의 핵심 수치·공간 알고리즘이 독립된 외부 기준 소프트웨어(GRASS GIS, R, GDAL, SciPy, NetworkX, Shapely) 및 해석해(exact calculus)와 동일한 입력에서 어느 수준으로 일치하는지 검증한 실측 기록입니다.

모든 수치는 저장소의 재현 스크립트 [scripts/run_benchmarks.py](../scripts/run_benchmarks.py)로 실제 실행해 측정했으며, 원본 JSON 출력은 [scripts/benchmark_results.json](../scripts/benchmark_results.json)에 보관되어 있습니다.

---

## 1. 실행 환경 및 재현 방법

| 항목 | 버전 / 사양 |
| --- | --- |
| 운영체제 | Windows 10 (AMD64) |
| QGIS / GDAL | QGIS 3.40.5-Bratislava / GDAL 3.10.2 |
| GRASS GIS | GRASS GIS 8.4.1 (`r.slope.aspect`, `r.neighbors`, `r.viewshed`, `r.walk`) |
| R | R 4.5.2 (`igraph 2.3.3`, `terra 1.8.70`, `stats`) |
| Python 과학 스택 | Python 3.12.7, NumPy 2.3.4, SciPy 1.16.3, NetworkX 3.6.1, Shapely 2.1.2 |

```bash
python scripts/run_benchmarks.py --json scripts/benchmark_results.json
```

---

## 2. 한눈에 보는 교차 검증 요약

| 영역 | ArchToolkit 모듈 | 외부 기준 소프트웨어 | 핵심 실측 일치도 | 판정 |
| --- | --- | --- | --- | --- |
| **경사·사면방향** | `gdaldem` (Horn) | GRASS `r.slope.aspect`, R `terra::terrain` | 경사 RMSE `2.13e-5 deg` ($r = 0.999999999992$), 방향 RMSE `1.12e-4 deg` | 일치 (Float32 라운딩 한계) |
| **TPI (r=1, r=3)** | `terrain_math.focal_tpi` (Crow SAT) | R `terra::terrain`, GRASS `r.neighbors` (7x7) | 최대 절대오차 `1.67e-13 m` (r=1), `1.28e-13 m` (r=3), $r = 1.0$ | 기계 정밀도 일치 |
| **TRI · 거칠기** | `gdaldem` (Riley / Wilson) | R `terra::terrain` (`TRIriley`, `roughness`) | RMSE `3.92e-6 m` / `5.35e-6 m`, $r > 0.999999999997$ | 일치 |
| **곡률 (종단·횡단)** | `terrain_math.zt_curvature` | 해석 미분(2차 포물면), GRASS `r.slope.aspect` | 해석해 최대 오차 `1.02e-15`; 부호·계량 변환 후 GRASS $r = 0.999999$ | 일치 (부호 규약 반대 확인) |
| **가시권 (곡률·굴절)** | `gdal_viewshed` + `viewshed_math` | GRASS `r.viewshed -b -c` (`k=0.13`) | 6,360셀 중 **99.83%** 일치, IoU **99.28%**, Cohen's $\kappa = 0.9953$ | 고도 일치 (11개 경계 셀 차이) |
| **이동비용 (8방향)** | `cost_engine.dijkstra_full` (Naismith) | GRASS `r.walk` (`walk_coeff=0.72,6,0,0`) | 기복 DEM 10,200셀 최대 오차 `1.02e-12 s`, $r = 1.0$ | 기계 정밀도 일치 |
| **이동비용 (16방향 나이트)** | `cost_engine.dijkstra_full(allow_knight=True)` | GRASS `r.walk -k` 및 유클리드 측지선 | 평지 신장오차 **2.75%** (GRASS 동일, 최대 오차 `1.14e-13 s`); 기복 $r = 0.999990$ | 일치 (중간 셀 절벽 보호 차이 0.21%) |
| **SNA 중심성 · MST** | `network_metrics`, `mst.kruskal_mst` | R `igraph 2.3.3`, Python `NetworkX 3.6.1` | 가중 매개·근접·조화·군집·MST 최대 오차 `0.0` - `4.8e-13` | 기계 정밀도 일치 |
| **PPA (Gabriel · RNG)** | `ppa_filters` | SciPy `Delaunay` + 독립 $O(N^3)$ 검증기 | Gabriel `66/66`, RNG `46/46`, 5 km 정삼각형 72회전 `72/72` | 100% 일치 |
| **Ordinary Kriging · LOOCV** | `kriging_math` (WLS + OK + LOOCV) | R 4.5.2 `solve()`, SciPy `linalg.solve` | 예측/분산 최대 오차 `< 8.7e-11`, LOOCV RMSE/MSDR 오차 `< 2.6e-12` | 기계 정밀도 일치 |
| **공변량 상관 · VIF · 순환 R²** | `covariate_stats` | R 4.5.2 `cor`, `lm` (정확 VIF·F-검정), SciPy | 상관·순환 $R^2$ `< 5.5e-13`, 혼합 스케일 VIF 상대오차 `3.55e-11` | 기계 정밀도 일치 |
| **AHP 고유벡터 · CR** | `ahp_core.ahp_weights_from_matrix` | SciPy `linalg.eig` (5x5, 12x12) | 가중치·$\lambda_{\max}$·CR 최대 오차 `0.0` | 완전 일치 |
| **트렌치 2D SAT 교차** | `trench_suggestion_dialog` (SAT) | Shapely 2.1.2 (GEOS 폴리곤 교차) | 회전 트렌치 500건·2,726셀 판정 **2,726 / 2,726 (100.0%)** | 완전 일치 |

---

## 3. 영역별 상세 결과 및 방법론적 해석

### 3.1 지형 미분 (Terrain Derivatives)

- **입력 DEM**: 101×101 격자, `EPSG:5186`, 픽셀 10 m × 10 m, 다중 봉우리·능선·계곡을 포함한 합성 기복 지형 및 해석적 2차 포물면 $z(x,y) = 200 - 4\times 10^{-4}\Delta x^2 + 2\times 10^{-4}\Delta y^2 + 1.5\times 10^{-4}\Delta x \Delta y$.
- **실측 비교 (내부 셀 기준)**:

| 지표 | 비교 대상 | 비교 셀 수 | 최대 절대오차 | RMSE | Pearson $r$ |
| --- | --- | ---: | ---: | ---: | ---: |
| 경사도 (deg) | GRASS `r.slope.aspect` | 9,409 | `1.04e-4` | `2.13e-5` | `0.999999999992` |
| 경사도 (deg) | R `terra::terrain` | 9,409 | `1.04e-4` | `2.13e-5` | `0.999999999992` |
| 사면방향 (deg, 원형차) | GRASS `r.slope.aspect` (북 기준 변환) | 9,409 | `3.48e-3` | `1.12e-4` | — |
| 사면방향 (deg, 원형차) | R `terra::terrain` | 9,409 | `3.48e-3` | `1.12e-4` | — |
| TPI (반경 1셀, 3x3) | R `terra::terrain(..., "TPI")` | 9,409 | `1.67e-13` | `3.07e-14` | `1.000000000000` |
| TPI (반경 3셀, 7x7 SAT) | GRASS `r.neighbors(size=7)` 중심 제외 환산 | 8,649 | `1.28e-13` | `3.30e-14` | `1.000000000000` |
| TRI (Riley) | R `terra::terrain(..., "TRIriley")` | 9,409 | `2.49e-5` | `3.92e-6` | `0.999999999999` |
| 거칠기 (Roughness) | R `terra::terrain(..., "roughness")` | 9,409 | `1.51e-5` | `5.35e-6` | `0.999999999997` |
| 종단 곡률 (포물면) | 해석 미분 (Zevenbergen & Thorne 1987) | 9,409 | `1.01e-15` | `3.17e-16` | `1.000000000000` |
| 횡단 곡률 (포물면) | 해석 미분 (Zevenbergen & Thorne 1987) | 9,409 | `1.02e-15` | `2.93e-16` | `1.000000000000` |
| 종단 곡률 (기복 DEM) | GRASS `pcurv` (부호 반전 + $(1+p^2+q^2)^{3/2}$ 환산) | 9,399 | `7.95e-5` | `4.58e-6` | `0.999998586515` |

- **교차 검증 시 유의**: ArchToolkit의 곡률은 Zevenbergen & Thorne 원식에 ESRI 서술 부호를 적용하므로 GRASS `r.slope.aspect`의 `pcurv`와 원시 상관계수가 `r = -0.9974`(부호 반대)이며, 부호를 뒤집고 GRASS의 곡면 계량 인자 $(1+p^2+q^2)^{3/2}$로 환산하면 `r = +0.999999`로 일치합니다.

---

### 3.2 가시권 분석 (Viewshed + 지구 곡률·대기 굴절)

- **조건**: 101×101 기복 DEM 중앙 `(50, 50)`, 관측자 높이 `1.7 m`, 대상 높이 `0.0 m`, 최대 거리 `450 m`, 지구 곡률 + 대기 굴절 `k = 0.13` (GDAL `-cc 0.87`, GRASS `r.viewshed -b -c refraction_coeff=0.13`).
- **실측 비교 (반경 450 m 이내 6,360셀)**:

| 지표 | 값 |
| --- | ---: |
| 전체 픽셀 일치율 | **99.827%** (6,349 / 6,360) |
| 가시 영역 IoU (Jaccard) | **99.283%** |
| Cohen's $\kappa$ | **0.99526** |
| 분할표 (TP / FP / FN / TN) | `1,523 / 10 / 1 / 4,826` |
| 가시 비율 (ArchToolkit vs. GRASS) | `24.10%` vs. `23.96%` |

- **차이 원인 설명**: 11개 셀(0.17%)의 차이는 알고리즘 계열 차이(GDAL `gdal_viewshed`의 Wang et al. 2000 기준면 전파 vs. GRASS `r.viewshed`의 스위프라인 시선 보간)가 능선 접선(grazing horizon) 경계에서 일으키는 알려진 미세 편차입니다(Fisher 1993).

---

### 3.3 이동비용 및 최소비용경로 (8방향 vs. 16방향 나이트 이동)

- **평지 격자 신장 오차 비교 (반경 40–80셀 링, 4,612셀, 유클리드 이론치 대비 최대 과대추정률)**:

| 연결성 | ArchToolkit 최대 신장오차 | GRASS 8.4 `r.walk` 최대 신장오차 | ArchToolkit vs. GRASS 최대 절대차 |
| --- | ---: | ---: | ---: |
| 4방향 (직교) | `41.4214%` | — | — |
| 8방향 (대각 허용) | `8.2392%` | `8.2392%` | **`0.0 s`** |
| **16방향 (나이트 이동, `-k`)** | **`2.7486%`** | **`2.7486%`** | **`1.14e-13 s`** |

- **기복 DEM (101×101, 10,200셀, 순수 Naismith `a=0.72 s/m, b=6.0 s/m, c=d=0`)**:

| 모드 | 비교 대상 | 최대 절대오차 (s) | RMSE (s) | 중앙값 상대오차 | Pearson $r$ |
| --- | --- | ---: | ---: | ---: | ---: |
| 8방향 | GRASS `r.walk` | `1.02e-12` | `1.61e-13` | **`0.0000%`** | **`1.000000000000`** |
| **16방향 나이트 이동** | GRASS `r.walk -k` | `4.77` | `1.30` | `0.2083%` | **`0.999990`** |

- **16방향 기복 0.21% 차이의 의도적 이유**: GRASS `r.walk -k`는 나이트 이동의 시작-끝 표고차만 쓰지만, ArchToolkit은 1픽셀 절벽·능선·하천을 뛰어넘는 **장벽 관통(tunneling)** 을 차단하기 위해 나이트 이동이 가로지르는 2개 중간 셀의 평균 고도 $z_{\text{mid}}$를 경유하는 2구간 분할 비용을 계산합니다. 평지·균일 경사에서는 두 식이 완전히 동일(`1.14e-13 s`)하며, 기복 지형에서는 1픽셀 절벽 관통을 막으면서도 $r = 0.999990$으로 일치합니다.

---

### 3.4 사회 네트워크 분석(SNA) 및 최소 신장 트리(MST)

- **입력 그래프**: 25노드·48간선 무방향 가중 그래프(동일 최단비용 다이아몬드 동점 구조 + 2개 단절 컴포넌트 포함).

| 지표 | vs. NetworkX 3.6.1 최대 오차 | vs. R `igraph 2.3.3` 최대 오차 |
| --- | ---: | ---: |
| 비가중 매개중심성 (Brandes) | `1.78e-15` | `4.33e-13` |
| 가중 매개중심성 (동점 포함) | **`0.0`** | **`0.0`** |
| 비가중 근접중심성 (성분 보정) | **`0.0`** | — *(igraph는 성분 보정 미적용)* |
| 가중 근접중심성 (성분 보정) | **`0.0`** | — |
| 비가중 조화중심성 (정규화) | **`0.0`** | `4.44e-13` |
| 가중 조화중심성 (정규화) | **`0.0`** | `4.79e-13` |
| 국소 군집계수 (Watts & Strogatz) | **`0.0`** | `3.33e-13` |
| Kruskal MST 총비용 (`176.05`) | **`0.0`** | **`0.0`** |

---

### 3.5 공간 근접 그래프 (PPA: Gabriel · RNG)

- 40개 유적 좌표에서 SciPy `Delaunay` + 독립 $O(N^3)$ 유클리드 전수 검증기와 비교한 결과:
  - **Gabriel Graph**: `66 / 66` 간선 **100% 일치**
  - **Relative Neighborhood Graph (RNG)**: `46 / 46` 간선 **100% 일치**
  - **5 km 정삼각형 72회전 스케일 불변성**: **`72 / 72` (100%)** 보존

---

### 3.6 Ordinary Kriging · WLS 베리오그램 · LOOCV

- **입력**: 1 km × 1 km 영역의 불규칙 표고 관측점 45개(잡음 표준편차 `1.5 m`), 예측 격자 100개 및 45폴드 LOOCV.
- **실측 비교 (독립 R 4.5.2 배정밀도 `solve()` 및 SciPy `linalg.solve` 기준)**:

| 지표 | 실측값 / 최대 오차 |
| --- | ---: |
| WLS 자동 선택 모델 | `gaussian` (실무 최소 너겟 하한 0.5% 안정화 적용) |
| 예측값 $\hat{z}$ 최대 오차 vs. R | **`5.50e-11 m`** |
| 크리깅 분산 $\sigma^2_{\text{OK}}$ 최대 오차 vs. R | **`8.66e-11 m²`** |
| LOOCV RMSE (`2.3348 m`) 오차 vs. R | **`2.59e-12 m`** |
| LOOCV MSDR (`0.8553`) 오차 vs. R | **`1.70e-12`** |
| 고립 관측점 정확 보간 최대 잔차 / 분산 | `2.18e-11 m` / `4.62e-11 m²` |

> **벤치마크로 발견·개선한 수치 함정**: 초기 실행에서 WLS 적합기가 매끄러운 지형에 무너겟(`nugget = 0`) Gaussian 모델을 선택하자 행렬 조건수 폭증(`2.58e8`)으로 LOOCV RMSE가 `29.3 m`, MSDR이 `14,892`까지 발산했습니다. 이는 지오통계학 교과서(Chilès & Delfiner 2012, §2.5.1)의 대표적인 Gaussian 무너겟 특이성 문제이며, Gaussian 계열에 0.5% 실무 최소 너겟 하한을 도입하자 조건수가 300배 개선되고 LOOCV RMSE `2.33 m`, MSDR `0.86`, R 기준 오차 `< 1e-10`으로 안정화되었습니다.

---

### 3.7 공변량 상관 / VIF / 순환-선형 $R^2$

- **입력**: 500셀 다중 스케일 공변량(`1e-3`부터 `1e9`까지 12자릿수 차이의 극단적 공선성 변수 포함 + 원형 사면방향 변수).
- **실측 비교 (R 4.5.2 `stats::cor`·`stats::lm` 정확 VIF 및 F-검정, SciPy `pearsonr`/`spearmanr`)**:

| 지표 | vs. R 4.5.2 최대 오차 | vs. SciPy 1.16.3 최대 오차 |
| --- | ---: | ---: |
| Pearson 상관계수 행렬 | `5.41e-13` | `8.88e-16` |
| Spearman 순위상관 행렬 | `4.72e-16` | `5.55e-17` |
| 혼합 스케일 VIF (`[1501.9, 134.7, 2087.4, 1.01]`) | 최대 상대오차 **`3.55e-11`** | — |
| 순환-선형 $R^2$ (Mardia 1976) | `8.48e-13` | — |
| 순환-선형 정확 $F$-검정 $p$-값 | `1.26e-121` | — |

---

### 3.8 AHP 주고유벡터·CR 및 트렌치 2D SAT 발자국 교차

- **AHP (`ahp_core.py` vs. SciPy `linalg.eig`)**: 5×5(`CR=0.05301`) 및 12×12(`CR=0.05918`, Alonso & Lamata RI) 행렬 모두 가중치·$\lambda_{\max}$·CR 최대 오차 **`0.0`**.
- **트렌치 2D SAT (`trench_suggestion_dialog.py` vs. Shapely 2.1.2 GEOS)**: 10 m DEM 격자 위 임의 회전 2 m × 20 m 트렌치 500건, 총 2,726셀 교차 판정 중 **2,726 / 2,726 (`100.0000%`) 완전 일치**.

---

## 4. 이 벤치마크가 증명하지 않는 것 (정직한 범위)

1. **수치 구현 정확성 ≠ 고고학적 실재 증명**: 이 벤치마크는 ArchToolkit의 수식·알고리즘 구현이 외부 학술 소프트웨어와 수치적으로 일치함을 증명할 뿐, 최소비용경로가 실제 옛길이라거나 가시권이 식생·건물을 포함한 실제 시야임을 보장하지 않습니다.
2. **Kriging(Lite)의 모형 범위**: 국소 등방성 Ordinary Kriging의 선형대수·LOOCV 정확성은 검증되었으나, 강한 이방성이나 광역 추세가 존재하는 지오통계 추론에는 R(`gstat`)의 이방성/Universal Kriging과 교차 검증해야 합니다(ArchToolkit이 자동으로 이방성 비와 평면 추세 $R^2$ 경고를 표시합니다).
3. **탐색·보조 도구 (Tier 3)**: 지구화학도 수치화(WMS 색상 역추정), 트렌치 후보 제안(배치 점수 휴리스틱), 지적도 중첩(비법정 참고), AI 조사요약(초안)은 수치 엔진이 아닌 보조 도구이므로 [docs/RESEARCH_GUIDE.md](RESEARCH_GUIDE.md)의 활용 한계를 반드시 따르십시오.
