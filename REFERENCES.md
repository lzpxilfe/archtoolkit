# ArchToolkit 학술·기술 참고문헌

본 플러그인이 사용하는 알고리즘·수식·통계·지도학·공간표준의 원 출처입니다. 모든 학술 서지와 DOI는 Crossref·출판사 원문·공공기관 공식 규정을 기준으로 검증했습니다.

## 표기 범례 (A / B / C)

모든 항목에 아래 세 구분 중 하나를 표시했습니다. **"플러그인이 실제로 계산하는 것"과 "맥락·표준·후속 분석으로 참고만 하는 것"을 독자가 명확히 구분할 수 있도록** 하기 위한 표기입니다.

- **(A)** 이 플러그인이 호출하는 QGIS/GDAL/PROJ/GEOS 알고리즘의 원 출처
- **(B)** 이 플러그인이 파이썬 코드에 직접 구현한 수식·알고리즘의 원 출처
- **(C)** 개념·해석 맥락, 데이터·코드 표준, 법령·지침, 또는 후속 분석용 참고 (직접 구현 아님)

구분 기준: `processing.run(...)` 또는 QGIS/GDAL/PROJ 내장 연산을 호출하면 **(A)**, `tools/*.py`에 수식을 직접 구현했으면 **(B)**, 해석·배경·공공자료 출처·후속 분석용으로만 인용하면 **(C)**입니다.
또한 화면에 표시되는 **등급 구분(5등급 등)은 별도 표기가 없는 한 플러그인 자체의 표시 관례**이며, 원저자가 출판한 분류와 다를 경우 해당 항목에 명시했습니다.

---

## 0. 공통 공간 기반: 좌표계·투영 왜곡·타원체 측지·소프트웨어

**(A) 타원체 측지 거리·면적 계산** — `QgsDistanceArea` (PROJ / GeographicLib 내장, 지적도 중첩·지형 단면·AI 조사요약·가시성/비용 분석에 사용):
> Karney, C.F.F. (2013). "Algorithms for geodesics." *Journal of Geodesy*, 87(1), pp. 43–55. DOI: 10.1007/s00190-012-0578-z

**(A) 래스터/벡터 처리 엔진** — `gdal:*` 알고리즘 및 `osgeo.gdal`/`ogr` 파이썬 API:
> GDAL/OGR contributors (2026). *GDAL/OGR Geospatial Data Abstraction software Library*. Open Source Geospatial Foundation. https://gdal.org DOI: 10.5281/zenodo.5884351

**(A) 벡터 지오메트리 유효성·중첩 연산** — `makeValid`, `intersection`, `unaryUnion` (GEOS / OGC Simple Feature Access):
> Open Geospatial Consortium (2011). *OpenGIS Implementation Standard for Geographic Information — Simple Feature Access — Part 1: Common Architecture* (ISO 19125-1:2004). https://www.ogc.org/standards/sfa/

**(C) 투영 왜곡 및 웹 메르카토르(`EPSG:3857`) 미터 오인 차단 근거** — `tools/utils.py`의 `is_metric_crs` / `is_pseudo_mercator`:
> Snyder, J.P. (1987). *Map Projections—A Working Manual*. U.S. Geological Survey Professional Paper 1395. DOI: 10.3133/pp1395
>
> Battersby, S.E., Finn, M.P., Usery, E.L., & Yamamoto, K.H. (2014). "Implications of Web Mercator and Its Use in Online Mapping." *Cartographica*, 49(2), pp. 85–101. DOI: 10.3138/carto.49.2.2313

주: 웹 메르카토르(`EPSG:3857`)는 단위 이름이 미터(m)로 표기되지만 위도 $\phi$에서 축척계수가 $\sec\phi$로 커집니다. 한반도(위도 약 35–38°)에서는 평면 거리가 약 22–27%, 평면 면적이 약 49–61% 과대 계산되고, DEM 경사도·비용표면·가시권·거리 래스터가 모두 왜곡됩니다. 따라서 `is_metric_crs()`는 기본적으로 `EPSG:3857`을 거부하고 국내 투영좌표계(`EPSG:5186`, `EPSG:5179`, UTM 등) 사용을 요구합니다.

---

## 1. DEM 생성 (Generate DEM)

### TIN 선형 보간 (Triangulated Irregular Network)

**(A) 들로네 삼각분할** — `qgis:tininterpolation` (method=0, 선형) 호출:
> Delaunay, B. (1934). "Sur la sphère vide. À la mémoire de Georges Voronoï." *Известия Академии наук СССР, VII серия, Отделение математических и естественных наук* (Bulletin de l'Académie des Sciences de l'URSS, VII série, Classe des sciences mathématiques et naturelles), 1934, no. 6, pp. 793–800.

주(서지): 널리 퍼진 축약형 "Bull. Acad. Sci. URSS **7**: 793-800"의 `7`은 **권 번호가 아니라 시리즈 번호(VII série)** 입니다. 이 학술지는 권 번호를 쓰지 않고 연도 + 호(выпуск)로 색인됩니다. 원본 스캔은 러시아과학원 Math-Net.Ru에서 확인할 수 있습니다.

**(C) GIS 적용 맥락:**
> Fowler, R.J., & Little, J.J. (1979). "Automatic extraction of irregular network digital terrain models." *Computer Graphics (SIGGRAPH '79)*, 13(2), pp. 199–207. DOI: 10.1145/800249.807444

### TIN 곡면 보간 (Clough-Tocher)

**(A)** `qgis:tininterpolation` (method=1, 곡면) 호출:
> Clough, R.W., & Tocher, J.L. (1965). "Finite element stiffness matrices for analysis of plates in bending." *Proceedings of the Conference on Matrix Methods in Structural Mechanics*, Wright-Patterson AFB, Ohio, pp. 515–545.

### IDW (역거리 가중치)

**(A)** `qgis:idwinterpolation` 호출:
> Shepard, D. (1968). "A two-dimensional interpolation function for irregularly-spaced data." *Proceedings of the 1968 23rd ACM National Conference*, pp. 517–524. DOI: 10.1145/800186.810616

### 크리깅 보간 (Ordinary Kriging Lite / WLS Variogram / LOOCV)

**(B) 지오통계/변동함수(variogram) 기반 Ordinary Kriging 및 가중최소제곱(WLS) 베리오그램 적합·LOOCV** — `tools/kriging_math.py` + `tools/kriging_lite.py`:
> Matheron, G. (1963). "Principles of geostatistics." *Economic Geology*, 58(8), pp. 1246–1266. DOI: 10.2113/gsecongeo.58.8.1246
>
> Cressie, N. (1985). "Fitting variogram models by weighted least squares." *Mathematical Geology*, 17(5), pp. 563–586. DOI: 10.1007/BF01032109

**(C) 표준 참고서 (교차검증 RMSE/MSDR, 동일 좌표 중복점과 너겟 분산, 선형계 대각 스케일링 안정화):**
> Cressie, N. (1993). *Statistics for Spatial Data* (Revised ed.). John Wiley & Sons.
>
> Webster, R., & Oliver, M.A. (2007). *Geostatistics for Environmental Scientists* (2nd ed.). John Wiley & Sons.
>
> Chilès, J.-P., & Delfiner, P. (2012). *Geostatistics: Modeling Spatial Uncertainty* (2nd ed.). John Wiley & Sons. DOI: 10.1002/9781118136188
>
> Golub, G.H., & Van Loan, C.F. (2013). *Matrix Computations* (4th ed.). Johns Hopkins University Press. DOI: 10.1137/1.9781421407944

주: 기본 "Lite" 설정은 경험 변동함수를 적합하지 않습니다(지수형 모델 고정, 너깃은 표본분산의 5%, 레인지는 최근린 간격 중앙값의 3배, 이방성 미고려). 옵션("경험 베리오그램 자동 적합")을 켜면 Cressie(1985) WLS 목적함수를 직접 최소화해 지수형·구형·가우스형 모델을 선택·적합하며, 모든 실행에서 LOOCV(RMSE, MAE, MSDR)를 보고합니다. 고기복 산지 DEM의 고실(sill) 행렬에는 대각 유사 스케일링($S A S$)을 적용해 조건수 붕괴를 방지하며, 너겟($c_0>0$)이 있는 동일 좌표 중복점의 예측분산과 LOOCV 분산을 구분해 계산합니다.

---

## 2. 등고선 추출 (Contour Extraction)

**(A) GDAL Contour** — `gdal:contour` 호출:
> GDAL/OGR contributors (2026). *GDAL/OGR Geospatial Data Abstraction software Library* (`gdal_contour`). Open Source Geospatial Foundation. https://gdal.org DOI: 10.5281/zenodo.5884351

주: 등고선 추출은 래스터 DEM에서 동일 표고선을 생성하는 표준 GIS 기법으로, GDAL의 `gdal_contour` 유틸리티를 그대로 활용합니다.

---

## 3. 지형 분석 및 경사도·사면방향 도면화 (Terrain Analysis & Drafting)

### 경사도 / 사면방향 계산 (Slope / Aspect)

**(A) gdaldem 기본 3x3 커널(Horn 방식)** — `gdal:slope`, `gdal:aspect` (`ZEVENBERGEN: False`, 기본값 Horn) 및 `QgsHillshadeRenderer`:
> Horn, B.K.P. (1981). "Hill shading and the reflectance map." *Proceedings of the IEEE*, 69(1), pp. 14–47. DOI: 10.1109/PROC.1981.11918

**(C) 경사 등급 "한국표준" 프리셋 출처 (유일한 공식 규정 분류):**
> 산림청 예규 「공·사유림 경영계획 작성 및 운영 요령」 [별표] 산림경영계획서 기재요령 — 경사도 구분 (완경사지 <15°, 경사지 15–20°, 급경사지 20–25°, 험준지 25–30°, 절험지 ≥30°). 국가법령정보센터 https://www.law.go.kr

주(등급 구분): 경사 등급 프리셋 4종 중 **"한국표준"** 만 위 산림청 예규 분류이며, 나머지 3종(Tobler 1993 / Minetti 1995 / Llobera 2007 논의 참고)은 **플러그인이 정한 표시 구분**입니다.

### 사면 파생 지표 (북향성 / 동향성 / TRASP)

**(B) TRASP(일사 프록시)** — `run_aspect_derivatives`에서 `(1 - cos(aspect - 30°)) / 2`로 직접 계산:
> Roberts, D.W., & Cooper, S.V. (1989). "Concepts and techniques of vegetation mapping." In: Ferguson, D., Morgan, P., & Johnson, F.D. (eds), *Land Classifications Based on Vegetation: Applications for Resource Management*, USDA Forest Service General Technical Report INT-257, pp. 90–96.

주: 북향성 $\cos(\text{aspect})$ / 동향성 $\sin(\text{aspect})$은 원형 변수인 사면방향을 연속 변수로 변환하는 표준 삼각 변환입니다. 평탄 셀(`-1`)은 북향성·동향성 `0`, TRASP `0.5`(중립)로 처리하고 DEM NoData 및 가장자리 셀은 NoData로 유지합니다.

### 원형·방향 통계 (Directional / Circular Statistics)

**(B) 원형 평균 방위($\bar{\theta}$), 집중도($\bar{R}$), 대칭 능선 축방향 $2\theta$ 변환** — `tools/slope_aspect_drafting_dialog.py`(경사 가중 블록 평균 방위), `tools/trench_suggestion_dialog.py`(능선 축방향 $2\theta$ 폴백), `tools/ai_aoi_summary.py`(사면방향 래스터 원형 통계):
> Mardia, K.V., & Jupp, P.E. (2000). *Directional Statistics*. John Wiley & Sons. DOI: 10.1002/9780470316979

주: 각도(0–360°)에 산술 평균을 적용하면 355°(북서)와 5°(북동)의 평균이 180°(정남)가 되는 오류가 발생합니다. 본 플러그인은 방향 통계의 표준 벡터 평균 $\bar{\theta} = \mathrm{atan2}\left(\sum w_i \sin\theta_i, \sum w_i \cos\theta_i\right) \;\mathrm{mod}\; 360^\circ$와 평균합벡터 길이 $\bar{R}$을 사용하며, 양측 사면이 대칭으로 상쇄되는 능선에서는 $2\theta$ 배각 축방향 통계를 보조로 적용합니다.

### 지형 거칠기 지수 TRI (Terrain Ruggedness Index)

**(A) 지수(index)의 원 출처** — `gdal:triterrainruggednessindex` (`gdaldem TRI -alg Riley`) 호출:
> Riley, S.J., DeGloria, S.D., & Elliot, R. (1999). "A terrain ruggedness index that quantifies topographic heterogeneity." *Intermountain Journal of Sciences*, 5(1–4), pp. 23–27.

주(등급 구분은 플러그인 정의): Riley 등(1999)이 제시한 것은 **절대 미터 값 기준의 7등급**(0–80 level, 81–116 nearly level, 117–161 slightly rugged, 162–239 intermediately rugged, 240–497 moderately rugged, 498–958 highly rugged, 959–4367 extremely rugged)입니다. 본 플러그인의 5등급은 사용자가 입력한 `험준기준`에 비례 배분한 표시 구분입니다.

**(B) 반경 확장 TRI (정규화 RMS 형태)** — `tools/terrain_math.py`의 `tri_radius`:
> 반경 2셀 이상에서는 $\sqrt{\frac{1}{N}\sum (z_{\text{center}} - z_{\text{neighbor}})^2}$, 즉 Riley 지수를 $\sqrt{N}$으로 나눈 평균제곱근(RMS) 형태를 직접 계산합니다(3x3 전체 창에서는 $\sqrt{8}$배 차이). 단위가 3x3 Riley 지수와 다르므로 별도 지표로 해석해야 합니다.

### 지형 위치 지수 TPI 및 지형 위치 6분류 (TPI & Landform Classification)

**(B) TPI 산식 및 지형 위치 6등급 분류(Landform Classification)** — `tools/terrain_math.py` (`focal_tpi`) + `run_slope_position_analysis`:
> Weiss, A. (2001). "Topographic Position and Landforms Analysis." *Poster presentation, ESRI User Conference*, San Diego, CA.

**(B) 2차원 누적합표(Summed-Area Table) 기반 고속 정확 초점평균** — `tools/terrain_math.py`의 `focal_tpi` / `focal_tpi_strips`:
> Crow, F.C. (1984). "Summed-area tables for texture mapping." *Computer Graphics (SIGGRAPH '84)*, 18(3), pp. 207–212. DOI: 10.1145/800031.808600

**(A) 반경 1셀(3x3) TPI 경로** — `gdal:tpitopographicpositionindex` 호출:
> Wilson, M.F.J., O'Connell, B., Brown, C., Guinan, J.C., & Grehan, A.J. (2007). "Multiscale terrain analysis of multibeam bathymetry data for habitat mapping on the continental slope." *Marine Geodesy*, 30(1–2), pp. 3–35. DOI: 10.1080/01490410701295962

주: Weiss(2001)는 TPI 지수와 6등급 지형분류 양쪽의 원 출처입니다. 반경 2셀 이상에서는 `gdaldem`의 3x3 고정 경로를 쓰지 않고 Crow(1984)의 누적합표로 `(2r+1)x(2r+1)` 창의 정확한 초점평균(중심 셀 제외, 유효 이웃 비율 75% 미만 시 NoData)을 직접 계산합니다.

### 지형 거칠기 Roughness

**(A) gdaldem roughness (3x3 창 내 최대-최소 표고차)** — `gdal:roughness` 호출:
> Wilson, M.F.J., O'Connell, B., Brown, C., Guinan, J.C., & Grehan, A.J. (2007). "Multiscale terrain analysis of multibeam bathymetry data for habitat mapping on the continental slope." *Marine Geodesy*, 30(1–2), pp. 3–35. DOI: 10.1080/01490410701295962

주(등급 구분은 플러그인 정의): 0–1 / 1–3 / 3–6 / 6–15 / 15 m 이상의 5등급은 플러그인 표시 관례입니다(`plugin_defined_5class`).

**(C) 일반 지형계측(Geomorphometry) 참고서 (gdaldem roughness의 원 출처는 아님):**
> Wilson, J.P., & Gallant, J.C. (2000). *Terrain Analysis: Principles and Applications*. John Wiley & Sons.
>
> Hengl, T., & Reuter, H.I. (eds.) (2009). *Geomorphometry: Concepts, Software, Applications*. Developments in Soil Science, Vol. 33. Elsevier. DOI: 10.1016/S0166-2481(08)X0001-7

### 곡률 Curvature (종단/횡단)

**(B) Zevenbergen & Thorne 곡률 (2차 다항식 적합)** — `tools/terrain_math.py`의 `zt_curvature`:
> Zevenbergen, L.W., & Thorne, C.R. (1987). "Quantitative analysis of land surface topography." *Earth Surface Processes and Landforms*, 12(1), pp. 47–56. DOI: 10.1002/esp.3290120107

**(C) 지형 곡률의 수문·지형학적 해석 및 부호 규약 비교:**
> Moore, I.D., Grayson, R.B., & Ladson, A.R. (1991). "Digital terrain modelling: A review of hydrological, geomorphological, and biological applications." *Hydrological Processes*, 5(1), pp. 3–30. DOI: 10.1002/hyp.3360050103

**부호 규약 (교차 검증 시 반드시 확인)**: 본 플러그인의 곡률은 Zevenbergen & Thorne 원식의 부호를 반전해 ESRI 서술 설명과 일치시켰습니다 — 종단(profile) 음(−)=볼록(침식 경향) / 양(+)=오목(퇴적 경향); 횡단(plan) 음(−)=수렴(물 모임) / 양(+)=발산(능선). GRASS `r.slope.aspect` 및 SAGA와는 크기 동일, 부호만 반대입니다.

---

## 4. 가시권 분석 및 가시선 단면 (Viewshed & Line of Sight)

**(A) GDAL `gdal_viewshed` 기준면(reference-plane) 방식** — `gdal:viewshed` 호출:
> Wang, J., Robinson, G.J., & White, K. (2000). "Generating viewsheds without using sightlines." *Photogrammetric Engineering & Remote Sensing*, 66(1), pp. 87–90.

**(C) 같은 저자들의 선행 연구 (GDAL이 호출하는 알고리즘은 아님):**
> Wang, J., Robinson, G.J., & White, K. (1996). "A Fast Solution to Local Viewshed Computation Using Grid-Based Digital Elevation Models." *Photogrammetric Engineering & Remote Sensing*, 62(10), pp. 1157–1164.

**(B) 지구 곡률·대기 굴절 보정** — `tools/viewshed_math.py` (`calculate_gdal_viewshed_cc`), `tools/viewshed_dialog.py` (LOS), `tools/spatial_network_dialog.py` (상호가시성):
> Yoeli, P. (1985). "The Making of Intervisibility Maps with Computer and Plotter." *Cartographica*, 22(3), pp. 88–103. DOI: 10.3138/J275-6460-8326-3733

주: 겉보기 고도 강하 보정 $\Delta z = (1 - k) \cdot d^2 / (2R)$ ($R = 6{,}371{,}000\text{ m}$, 표준 대기 굴절계수 $k = 0.13 \Rightarrow \text{cc} = 0.87$)을 `gdal_viewshed`의 `-cc`와 LOS·가시성 네트워크에 일관되게 적용합니다.

**(C) 가시권 알고리즘 불확실성·누적 가시권·QGIS 가시성 구현 참고:**
> Fisher, P.F. (1993). "Algorithm and implementation uncertainty in viewshed analysis." *International Journal of Geographical Information Systems*, 7(4), pp. 331–347. DOI: 10.1080/02693799308901965
>
> Wheatley, D. (1995). "Cumulative viewshed analysis: a GIS-based method for investigating intervisibility, and its archaeological application." In: Lock, G., & Stančič, Z. (eds), *Archaeology and Geographic Information Systems: A European Perspective*. Taylor & Francis, London. (2022 Routledge 재간행판 DOI: 10.1201/9780367810467-13)
>
> Čučković, Z. (2016). "Advanced viewshed analysis: a Quantum GIS plug-in for the analysis of visual landscapes." *Journal of Open Source Software*, 1(4), 32. DOI: 10.21105/joss.00032

### 히구치 거리대 (Higuchi View Zones)

**(C) 거리대 개념의 출처 (미터 기준값의 출처는 아님):**
> 樋口忠彦 [Higuchi, T.] (1975). 『景観の構造 — ランドスケープとしての日本の空間』. 技報堂, 東京. (일본어 원저)
>
> 영역본: Higuchi, T. (1983). *The Visual and Spatial Structure of Landscapes*. Translated by Charles S. Terry. MIT Press, Cambridge, MA.

주(서지·적용): 영문 제목은 1983년 MIT Press 영역본의 제목이며 1975년 원저는 일본어판입니다. Higuchi는 근경·중경·원경을 **관측 거리 ÷ 대상 높이($D/H$)** 로 정의했으며, 본 플러그인의 기본 미터 경계(500 m / 2500 m, 사용자 조정 가능)는 GIS 실무 관례입니다.

---

## 5. 이동 비용 모델·최소비용경로·최소비용 네트워크 (Cost Surface / LCP / Network)

**(B) Tobler 하이킹 함수 (보행 속도)** — `tools/cost_models.py`의 `tobler_speed_mps`:
> Tobler, W. (1993). "Three Presentations on Geographical Analysis and Modeling: Non-Isotropic Geographic Modeling, Speculations on the Geometry of Geography, Global Spatial Analysis." *NCGIA Technical Report 93-1*.

**(C) Tobler(1993)가 적합에 사용한 원 경험 자료:**
> Imhof, E. (1950). *Gelände und Karte*. Eugen Rentsch Verlag, Erlenbach-Zürich.

**(B) Naismith 규칙 (시간 기반 보행 모델)** — `naismith_time_s`:
> Naismith, W.W. (1892). "Cruach Ardran, Stobinian, and Ben More." In: "Excursions" [department: "Notes and Queries"], *Scottish Mountaineering Club Journal*, 2(3), pp. 135–136. (규칙 본문은 p. 136)

**(B) Pandolf 운반 에너지 모델 (Load Carriage)** — `edge_cost`의 `MODEL_PANDOLF`:
> Pandolf, K.B., Givoni, B., & Goldman, R.F. (1977). "Predicting energy expenditure with loads while standing or walking very slowly." *Journal of Applied Physiology*, 43(4), pp. 577–581. DOI: 10.1152/jappl.1977.43.4.577

**(C) Pandolf 모델의 내리막 하한 문제 논의:**
> Santee, W.R., Allison, W.F., Blanchard, L.A., & Small, M.G. (2001). "A proposed model for load carriage on sloped terrain." *Aviation, Space, and Environmental Medicine*, 72(6), pp. 562–566. PMID: 11396562

주: Pandolf(1977)는 평지·오르막 전용이므로 내리막에서 대사율이 비물리적으로 떨어지는 것을 막기 위해 하중 포함 기립 대사율 $1.5W + 2.0(W+L)(L/W)^2$로 하한 처리합니다.

**(B) Herzog 메타볼릭 다항식 (6차 경사-에너지 비용함수)** — `MODEL_HERZOG_METABOLIC`:
> Minetti, A.E., Moia, C., Roi, G.S., Susta, D., & Ferretti, G. (2002). "Energy cost of walking and running at extreme uphill and downhill slopes." *Journal of Applied Physiology*, 93(3), pp. 1039–1046. DOI: 10.1152/japplphysiol.01177.2001
>
> Herzog, I. (2013). "The potential and limits of Optimal Path Analysis." In: Bevan, A., & Lake, M. (eds), *Computational Approaches to Archaeological Spaces*, Left Coast Press, pp. 179–211.

주: 부호 있는 경사 $s = dz / d_{\text{horiz}}$를 원식대로 적용해 에너지 모드(`energy_j`)에서 실제 대사 에너지 $E(\text{J}) = W_{\text{kg}} \cdot C(s) \cdot d_{\text{horiz}}$ (`kcal` 환산 표시)를 산출합니다. 실험 검증 구간은 $\pm 45\%$이며 보행 모델 공통으로 기본 70° 초과 절벽은 통행 불가($+\infty$)로 차단합니다.

**(B) Herzog 차량/수레 모델 (임계 경사 %)** — `MODEL_HERZOG_WHEELED` (출처: Herzog 2013; 파라미터화 참고: Čučković 2025):
> Čučković, Z. (2025). *Movement Analysis* (QGIS plugin). https://github.com/zoran-cuckovic/QGIS-movement-analysis/

**(C) 상대 경사 비용 (수식은 플러그인 정의, 개념 논의만 참고):**
> Conolly, J., & Lake, M. (2006). *Geographical Information Systems in Archaeology*. Cambridge University Press.

**(C) 경사-에너지 최적 경사 및 시각·인지 경사 참고 (경사 등급 프리셋 배경):**
> Minetti, A.E. (1995). "Optimum gradient of mountain paths." *Journal of Applied Physiology*, 79(5), pp. 1698–1703. DOI: 10.1152/jappl.1995.79.5.1698
>
> Llobera, M. (2007). "Reconstructing visual landscapes." *World Archaeology*, 39(1), pp. 51–69. DOI: 10.1080/00438240601136496
>
> Llobera, M., & Sluckin, T.J. (2007). "Zigzagging: Theoretical insights on climbing strategies." *Journal of Theoretical Biology*, 249(2), pp. 206–217. DOI: 10.1016/j.jtbi.2007.07.020

### 최단경로 탐색·격자 신장 오차·회랑·최소 신장 트리

**(B) 누적 비용(Dijkstra) 및 휴리스틱 최단경로(A\*)** — `tools/cost_engine.py`:
> Dijkstra, E.W. (1959). "A note on two problems in connexion with graphs." *Numerische Mathematik*, 1(1), pp. 269–271. DOI: 10.1007/BF01386390
>
> Hart, P.E., Nilsson, N.J., & Raphael, B. (1968). "A Formal Basis for the Heuristic Determination of Minimum Cost Paths." *IEEE Transactions on Systems Science and Cybernetics*, 4(2), pp. 100–107. DOI: 10.1109/TSSC.1968.300136

**(C) 격자 연결성 신장 오차(8방향 약 8% vs. 4방향 약 41%)·누적 비용 회랑·고고학 적용:**
> Goodchild, M.F. (1977). "An evaluation of lattice solutions to the problem of corridor location." *Environment and Planning A*, 9(7), pp. 727–738. DOI: 10.1068/a090727
>
> Douglas, D.H. (1994). "Least-cost Path in GIS Using an Accumulated Cost Surface and Slopelines." *Cartographica*, 31(3), pp. 37–51. DOI: 10.3138/D327-0323-2JUT-016M
>
> White, D.A., & Surface-Evans, S.L. (eds.) (2012). *Least Cost Analysis of Social Landscapes: Archaeological Case Studies*. University of Utah Press. ISBN: 978-1-60781-171-8

**(B) 최소 신장 트리 MST (Kruskal 알고리즘)** — `tools/cost_network_dialog.py`:
> Kruskal, J.B. (1956). "On the shortest spanning subtree of a graph and the traveling salesman problem." *Proceedings of the American Mathematical Society*, 7(1), pp. 48–50. DOI: 10.1090/S0002-9939-1956-0078686-7

**(C) 관련 MST 알고리즘 (미구현 참고):**
> Prim, R.C. (1957). "Shortest Connection Networks and Some Generalizations." *Bell System Technical Journal*, 36(6), pp. 1389–1401. DOI: 10.1002/j.1538-7305.1957.tb01515.x

---

## 6. 사회 네트워크 분석·근접성 네트워크(PPA)·가시성 네트워크

### 사회 네트워크 분석 (SNA: Social Network Analysis)

**(C) 중심성 개념 프레임워크:**
> Freeman, L.C. (1979). "Centrality in social networks: Conceptual clarification." *Social Networks*, 1(3), pp. 215–239. DOI: 10.1016/0378-8733(78)90021-7

**(B) 근접 중심성 성분 크기 보정** — `tools/network_metrics.py`:
> Wasserman, S., & Faust, K. (1994). *Social Network Analysis: Methods and Applications*. Cambridge University Press.

**(B) 매개 중심성 (Brandes 알고리즘, 무향 0.5 정규화·상대 동점 허용오차):**
> Brandes, U. (2001). "A faster algorithm for betweenness centrality." *Journal of Mathematical Sociology*, 25(2), pp. 163–177. DOI: 10.1080/0022250X.2001.9990249

**(B) 국소 군집계수(Local Clustering Coefficient) 및 전이성(Transitivity):**
> Watts, D.J., & Strogatz, S.H. (1998). "Collective dynamics of 'small-world' networks." *Nature*, 393(6684), pp. 440–442. DOI: 10.1038/30918

**(B) 조화 중심성 (Harmonic Centrality, 단절 그래프 대응):**
> Boldi, P., & Vigna, S. (2014). "Axioms for centrality." *Internet Mathematics*, 10(3–4), pp. 222–262. DOI: 10.1080/15427951.2013.865686

**(C) 네트워크 과학 표준 참고서:**
> Newman, M.E.J. (2010). *Networks: An Introduction*. Oxford University Press.

### 근접성 네트워크 (PPA: Proximal Point Analysis)

**(A) 들로네 삼각분할 후보 간선** — `qgis:delaunaytriangulation` / `native:delaunaytriangulation` (원 출처: Delaunay 1934).

**(B) Gabriel Graph** — `tools/ppa_filters.py`:
> Gabriel, K.R., & Sokal, R.R. (1969). "A new statistical approach to geographic variation analysis." *Systematic Zoology*, 18(3), pp. 259–278. DOI: 10.2307/2412323

**(B) RNG (Relative Neighborhood Graph)** — `tools/ppa_filters.py` (스케일 불변 `rel_tol` 적용):
> Toussaint, G.T. (1980). "The relative neighbourhood graph of a finite planar set." *Pattern Recognition*, 12(4), pp. 261–268. DOI: 10.1016/0031-3203(80)90066-7

**(C) 고고학 네트워크 분석 방법론:**
> Terrell, J.E. (1977). "Human Biogeography in the Solomon Islands." *Fieldiana Anthropology*, 68(1), pp. 1–47.
>
> Brughmans, T., & Peeples, M.A. (2017). "Trends in archaeological network research: a bibliometric analysis." *Journal of Historical Network Research*, 1, pp. 1–24. DOI: 10.25517/jhnr.v1i1.10
>
> Amati, V., Shafie, T., & Brandes, U. (2018). "Reconstructing Archaeological Networks with Structural Holes." *Journal of Archaeological Method and Theory*, 25, pp. 226–253. DOI: 10.1007/s10816-017-9335-1

### 가시성 네트워크 (Intervisibility Network)

**(B) 유적 간 상호가시성(LOS) 검사** — `tools/spatial_network_dialog.py`: 양선형 보간 DEM 표본과 Yoeli(1985) 지구 곡률·대기 굴절 보정을 결합하고, DEM NoData 표본은 `fail_deg`로 분리 집계합니다.

**(C) 고고학 가시성 네트워크 해석 맥락:**
> Van Dyke, R.M., Bocinsky, R.K., Windes, T.C., & Robinson, T.J. (2016). "Great houses, shrines, and high places: intervisibility in the Chacoan world." *American Antiquity*, 81(2), pp. 205–230. DOI: 10.7183/0002-7316.81.2.205
>
> Gillings, M., & Wheatley, D. (2001). "Seeing is not believing: unresolved issues in archaeological visibility analysis." In: *On the Good Use of Geographical Information Systems in Archaeological Landscape Studies* (COST Action G2).
>
> Turner, A., Doxa, M., O'Sullivan, D., & Penn, A. (2001). "From isovists to visibility graphs: a methodology for the analysis of architectural space." *Environment and Planning B: Planning and Design*, 28(1), pp. 103–121. DOI: 10.1068/b2684

주: Turner 등(2001)의 VGA는 격자 셀 간 가시성 그래프로, 본 도구의 유적(점/폴리곤) 간 상호가시성 네트워크와는 별개이며 개념적 배경으로만 인용합니다.

---

## 7. AHP 입지적합도 (AHP Suitability)

**(B) 쌍대비교 주고유벡터 가중치 및 일관성비율(CR)** — `tools/ahp_core.py`:
> Saaty, T.L. (1980). *The Analytic Hierarchy Process*. McGraw-Hill.

**(B) 무작위 지수(RI) 확장 표 ($11 \le n \le 15$):**
> Alonso, J.A., & Lamata, M.T. (2006). "Consistency in the Analytic Hierarchy Process: a new approach." *International Journal of Uncertainty, Fuzziness and Knowledge-Based Systems*, 14(4), pp. 445–459. DOI: 10.1142/S0218488506004114

**(B) 일대일(OAT) 기준 가중치 민감도 분석** — `tools/ahp_core.py`의 `oat_weight_sensitivity`:
> Chen, Y., Yu, J., & Khan, S. (2010). "Spatial sensitivity analysis of multi-criteria weights in GIS-based land suitability evaluation." *Environmental Modelling & Software*, 25(12), pp. 1582–1591. DOI: 10.1016/j.envsoft.2010.06.001

**(C) GIS 기반 다기준 입지적합도 분석(WLC/AHP) 개관:**
> Malczewski, J. (2004). "GIS-based land-use suitability analysis: a critical overview." *Progress in Planning*, 62(1), pp. 3–65. DOI: 10.1016/j.progress.2003.09.002

주: $n > 15$ 행렬에서는 CR이 정의되지 않으므로 `NaN`(`CR=-`)을 반환합니다. 계층형 모드에서는 평면 시드 CR을 숨기고 그룹 CR과 각 하위 그룹 로컬 CR을 분리해 보고합니다.

---

## 8. 거리 래스터 · 정렬/내보내기 · 공변량 상관/VIF · 후속 예측모델

### 거리 래스터 (Distance to Features) & 정렬/내보내기 (Align & Export)

**(A) 유클리드 근접 거리 변환·래스터화·재투영** — `gdal:rasterize`(`-at`), `gdal:proximity`, `gdal:warpreproject`:
> GDAL/OGR contributors (2026). *GDAL/OGR Geospatial Data Abstraction software Library*. Open Source Geospatial Foundation. https://gdal.org DOI: 10.5281/zenodo.5884351

**(C) 후속 예측모델링 (MaxEnt 등 — 본 플러그인은 예측변수 준비까지만 수행):**
> Phillips, S.J., Anderson, R.P., & Schapire, R.E. (2006). "Maximum entropy modeling of species geographic distributions." *Ecological Modelling*, 190(3–4), pp. 231–259. DOI: 10.1016/j.ecolmodel.2005.03.026
>
> Phillips, S.J., & Dudík, M. (2008). "Modeling of species distributions with Maxent: new extensions and a comprehensive evaluation." *Ecography*, 31(2), pp. 161–175. DOI: 10.1111/j.0906-7590.2008.5203.x
>
> Elith, J., Phillips, S.J., Hastie, T., Dudík, M., Chee, Y.E., & Yates, C.J. (2011). "A statistical explanation of MaxEnt for ecologists." *Diversity and Distributions*, 17(1), pp. 43–57. DOI: 10.1111/j.1472-4642.2010.00725.x

### 공변량 상관 / VIF 리포트 (Covariate Report)

**(B) Pearson 적률상관·Spearman 순위상관·분산팽창지수(VIF)** — `tools/covariate_stats.py`:
> Pearson, K. (1895). "VII. Note on regression and inheritance in the case of two parents." *Proceedings of the Royal Society of London*, 58, pp. 240–242. DOI: 10.1098/rspl.1895.0041
>
> Spearman, C. (1904). "The Proof and Measurement of Association between Two Things." *The American Journal of Psychology*, 15(1), pp. 72–101. DOI: 10.2307/1412159
>
> Marquardt, D.W. (1970). "Generalized Inverses, Ridge Regression, Biased Linear Estimation, and Nonlinear Estimation." *Technometrics*, 12(3), pp. 591–612. DOI: 10.1080/00401706.1970.10488699

**(B) 순환-선형 상관 $R^2$ 및 정확 $F$-검정 $p$-값 ($n \ge 4$)** — `tools/covariate_stats.py`의 `circular_linear_r2`:
> Mardia, K.V. (1976). "Linear-circular correlation coefficients and rhythmometry." *Biometrika*, 63(2), pp. 403–405. DOI: 10.1093/biomet/63.2.403

**(C) VIF 경험 규칙(5·10)의 한계 경고:**
> O'Brien, R.M. (2007). "A caution regarding rules of thumb for variance inflation factors." *Quality & Quantity*, 41(5), pp. 673–690. DOI: 10.1007/s11135-006-9018-6

주: 범주형(지질 등)과 원형(사면방향 등) 변수는 연속 Pearson/VIF 행렬에서 제외하고, 혼합 스케일 공선성이 누락되지 않도록 VIF 회귀 전에 열별 z-표준화를 적용합니다.

---

## 9. 트렌치 후보 제안 (Trench Suggestion)

**(B) 2차원 분리축 정리(SAT) OBB–AABB 셀-발자국 교차 판정** — `tools/trench_suggestion_dialog.py`의 `_footprint_slope_max` (회전된 트렌치 사각형과 DEM 픽셀 박스의 정확한 겹침 검사):
> Gottschalk, S., Lin, M.C., & Manocha, D. (1996). "OBBTree: A Hierarchical Structure for Rapid Interference Detection." *Proceedings of the 23rd Annual Conference on Computer Graphics and Interactive Techniques (SIGGRAPH '96)*, pp. 171–180. DOI: 10.1145/237170.237244

**(B) 경사 가중 원형 평균 및 대칭 능선 축방향($2\theta$) 방향 결정** — `_footprint_downslope_bearing` (원 출처: 위 Mardia & Jupp 2000).

**(C) 고고학 시굴·표본조사 설계 맥락 및 국내 법정 조사 규정 (배치 점수식 자체는 플러그인 휴리스틱):**
> Kintigh, K.W. (1988). "The Effectiveness of Subsurface Testing: A Simulation Approach." *American Antiquity*, 53(4), pp. 686–707. DOI: 10.2307/281113
>
> Orton, C. (2000). *Sampling in Archaeology*. Cambridge Manuals in Archaeology. Cambridge University Press. DOI: 10.1017/CBO9781139163996
>
> Banning, E.B. (2002). *Archaeological Survey*. Kluwer Academic / Plenum Publishers (Springer). DOI: 10.1007/978-1-4615-0769-7
>
> 대한민국 「매장유산 보호 및 조사에 관한 법률」 및 국가유산청 고시 「발굴조사의 방법 및 절차 등에 관한 규정」·「지표조사의 방법 및 절차 등에 관한 규정」. 국가법령정보센터 https://www.law.go.kr

주: 트렌치 배치 점수(AHP·경사·참고유적 거리 결합 및 분산 배치)는 특정 문헌의 확률 표본설계를 구현한 것이 아니라 현장 시굴조사 계획을 보조하는 **플러그인 휴리스틱**입니다.

---

## 10. 국내 공공자료·도면화·단면·AI 보고서

### 지질도 도엽 ZIP (KIGAM Geology ZIP)

**(C) 지질도 원자료 및 파일 형식·인코딩 표준:**
> 한국지질자원연구원(KIGAM). *1:50,000 수치지질도 도엽 (벡터 SHP/ZIP)* — 지질정보서비스(MGEO). https://mgeo.kigam.re.kr
>
> ESRI (1998). *ESRI Shapefile Technical Description* (White Paper, July 1998). Environmental Systems Research Institute. (`.dbf` / `.cpg` 속성 인코딩 규격)
>
> PKWARE Inc. *.ZIP File Format Specification (APPNOTE.TXT)*. (General Purpose Bit 11 / `0x800` UTF-8 파일명 플래그와 미표시 CP949/EUC-KR 아카이브 판별 근거)

### 지구화학도 래스터 수치화 (GeoChem)

**(C) 자료 출처 및 반투명 프리멀티플라이 알파(Premultiplied Alpha) 제외 근거:**
> 한국지질자원연구원(KIGAM). *전국 지구화학도 WMS 렌더링 이미지* — 지질정보서비스(MGEO). https://mgeo.kigam.re.kr
>
> Porter, T., & Duff, T. (1984). "Compositing Digital Images." *Computer Graphics (SIGGRAPH '84)*, 18(3), pp. 253–259. DOI: 10.1145/800031.808606

주: `tools/geochem_polygonize_dialog.py`의 프리셋 7종(Fe2O3, Pb, Cu, Zn, Sr, Ba, CaO)은 문헌이 아니라 서비스 범례를 판독해 입력한 표이며, Fe2O3 외 6종은 색상 팔레트가 동일하다고 가정했습니다. WMS PNG의 반투명 경계 픽셀(`alpha < 250`)은 프리멀티플라이 알파 합성으로 RGB가 어두워져 고농도 극값으로 오매칭되므로 NoData로 제외하며, 회색 무자료 구간(Stop 0)은 연속 보간에 섞지 않고 이산 점으로만 판정합니다.

### 지적도 중첩 면적표 (Cadastral Overlap)

**(A) 타원체 면적·지오메트리 중첩** — `QgsDistanceArea` (Karney 2013) 및 GEOS (OGC SFA / ISO 19125-1).

**(C) 연속지적도 자료 출처 및 법령:**
> 국토교통부(MOLIT). *연속지적도형정보* — 브이월드(V-World) / 국가공간정보포털. https://www.vworld.kr
>
> 대한민국 「공간정보의 구축 및 관리 등에 관한 법률」. 국가법령정보센터 https://www.law.go.kr

### 지형 단면 (Terrain Profile)

**(A) 측지·투영 거리 계산** — `QgsDistanceArea` (Karney 2013).

**(C) 지형 단면 작성 및 수직 과장(Vertical Exaggeration) 표기 원칙:**
> Imhof, E. (1982; 2007 reprint). *Cartographic Relief Presentation* (ed. H.J. Steward; orig. German ed. 1965 *Kartographische Geländedarstellung*). Walter de Gruyter / ESRI Press. ISBN: 978-1-58948-026-1

### 도면 시각화 (Map Styling)

**(A) DEM 음영기복 렌더링** — `QgsHillshadeRenderer` (Horn 1981).

**(C) 수치지형도 표준코드 체계 및 지도학적 배색·기복 표현:**
> 국토지리정보원(NGII). *전국 연속수치지형도 코드 및 레이어 설명서 Ver 5.1.1* 및 「수치지도 작성 작업규칙」. 국토정보플랫폼 https://map.ngii.go.kr
>
> Imhof, E. (1982; 2007 reprint). *Cartographic Relief Presentation*. ESRI Press. ISBN: 978-1-58948-026-1
>
> Harrower, M., & Brewer, C.A. (2003). "ColorBrewer.org: An Online Tool for Selecting Colour Schemes for Maps." *The Cartographic Journal*, 40(1), pp. 27–37. DOI: 10.1179/000870403235002042

### AI 조사요약 (AI AOI Report)

**(A) 공간 통계·선택적 외부 LLM API:**
> Karney, C.F.F. (2013) (타원체 면적·거리, 위 0절 참조).
>
> Google (2026). *Gemini API Documentation* (선택적 외부 전송 모드 전용; 로컬 모드는 외부 전송 없음). https://ai.google.dev/gemini-api/docs

**(B) 원형 방향 통계 및 CSV 수식 주입(Formula Injection) 방어:**
> Mardia, K.V., & Jupp, P.E. (2000) (사면방향 래스터 원형 평균·집중도 $R$, 위 3절 참조).
>
> OWASP Foundation. *CSV Injection (Formula Injection)*. https://owasp.org/www-community/attacks/CSV_Injection

**(C) 연구 데이터 재현성·문화유산 위치정보 거버넌스:**
> Wilkinson, M.D., Dumontier, M., Aalbersberg, I.J., et al. (2016). "The FAIR Guiding Principles for scientific data management and stewardship." *Scientific Data*, 3, 160018. DOI: 10.1038/sdata.2016.18
>
> Carroll, S.R., Garba, I., Figueroa-Rodríguez, O.L., et al. (2020). "The CARE Principles for Indigenous Data Governance." *Data Science Journal*, 19, 43. DOI: 10.5334/dsj-2020-043
>
> 대한민국 「매장유산 보호 및 조사에 관한 법률」 (매장유산 유존지역 위치정보 보호 고지 배경).

---
*ArchToolkit은 QGIS Processing Framework, GDAL/OGR, PROJ, GEOS, NumPy를 활용합니다.*
