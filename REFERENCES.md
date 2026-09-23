# ArchToolkit 학술 참고문헌

본 플러그인이 사용하는 알고리즘·수식의 원 출처입니다.

## 표기 범례 (A / B / C)

모든 항목에 아래 세 구분 중 하나를 표시했습니다. **"플러그인이 실제로 계산하는 것"과 "맥락으로 언급만 하는 것"을 독자가 구분할 수 있도록** 하기 위한 표기입니다.

- **(A)** 이 플러그인이 호출하는 QGIS/GDAL 알고리즘의 원 출처
- **(B)** 이 플러그인이 직접 구현한 수식의 원 출처
- **(C)** 개념/맥락 참고 또는 후속 분석용 (구현 아님)

구분 기준: `processing.run(...)`으로 QGIS/GDAL 알고리즘을 호출하면 (A), 파이썬 코드에 수식을 직접 구현했으면 (B), 해석·배경·후속 분석용으로만 인용하면 (C)입니다.
또한 화면에 표시되는 **등급 구분(5등급 등)은 대부분 플러그인 자체의 표시 관례**이며, 원저자가 출판한 분류와 다를 경우 해당 항목에 명시했습니다.

---

## TIN 선형 보간 (Triangulated Irregular Network)

**(A) 들로네 삼각분할** — `qgis:tininterpolation` (method=0, 선형) 호출:
> Delaunay, B. (1934). "Sur la sphère vide. À la mémoire de Georges Voronoï". *Известия Академии наук СССР, VII серия, Отделение математических и естественных наук* (Bulletin de l'Académie des Sciences de l'URSS, VII série, Classe des sciences mathématiques et naturelles), 1934, no. 6, pp. 793–800.

주(서지): 널리 퍼진 축약형 "Bull. Acad. Sci. URSS **7**: 793-800"의 `7`은 **권 번호가 아니라 시리즈 번호(VII série)** 입니다. 이 학술지는 권 번호를 쓰지 않고 연도 + 호(выпуск)로 색인됩니다. 원본 스캔은 러시아과학원 Math-Net.Ru에서 확인할 수 있습니다.

**(C) GIS 적용 맥락:**
> Fowler, R.J., & Little, J.J. (1979). "Automatic extraction of irregular network digital terrain models". *Computer Graphics (SIGGRAPH '79)*, 13(2), pp. 199–207.

## TIN 곡면 보간 (Clough-Tocher)

**(A)** `qgis:tininterpolation` (method=1, 곡면) 호출:
> Clough, R.W., & Tocher, J.L. (1965). "Finite element stiffness matrices for analysis of plates in bending". *Proceedings of the Conference on Matrix Methods in Structural Mechanics*, Wright-Patterson AFB, Ohio.

## IDW (역거리 가중치)

**(A)** `qgis:idwinterpolation` 호출:
> Shepard, D. (1968). "A two-dimensional interpolation function for irregularly-spaced data". *Proceedings of the 1968 23rd ACM National Conference*, pp. 517–524. DOI: 10.1145/800186.810616

## 크리깅 보간 (Kriging / Geostatistical Interpolation)

**(B) 지오통계/변동함수(variogram) 기반 보간** — `tools/kriging_lite.py`에 Ordinary Kriging을 직접 구현:
> Matheron, G. (1963). "Principles of geostatistics." *Economic Geology*, 58(8), pp. 1246–1266.

**(C) 표준 참고서:**
> Cressie, N. (1993). *Statistics for Spatial Data*. Wiley.

주: "Lite"는 경험 변동함수를 적합(fitting)하지 않습니다. 모델은 지수형(exponential) 고정, 너깃은 표본분산의 5%, 레인지는 최근린 간격 중앙값의 3배, 이방성은 고려하지 않습니다. 따라서 분산 래스터는 보정된 불확실성이 아니라 **상대적** 불확실성 지도로 읽어야 합니다.

## 등고선 생성 (Contour Generation)

**(A) GDAL Contour** — `gdal:contour` 호출:
> GDAL Development Team (2024). "GDAL - Geospatial Data Abstraction Library". Open Source Geospatial Foundation. https://gdal.org

주: 등고선 생성은 래스터 DEM에서 동일 표고점을 연결하는 표준 GIS 기법으로, GDAL의 `gdal_contour` 유틸리티를 그대로 활용합니다.

## 경사도 / 사면방향 계산 (Slope / Aspect)

**(A) gdaldem의 기본 3x3 커널(Horn 방식)** — `gdal:slope`, `gdal:aspect`를 ZEVENBERGEN을 쓰지 않고(옵션 미지정 또는 `ZEVENBERGEN: False` — 둘 다 gdaldem 기본값인 Horn) 호출:
> Horn, B.K.P. (1981). "Hill shading and the reflectance map." *Proceedings of the IEEE*, 69(1), pp. 14-47. DOI: 10.1109/PROC.1981.11918

주(등급 구분): 경사 등급 표시(한국표준 / Tobler 1993 / Minetti 1995 / Llobera 2007 이름의 4종 프리셋, 각 5등급)는 **플러그인이 정한 표시 구분**입니다. 이름이 가리키는 문헌이 그 등급표를 그대로 출판한 것은 아니며, 각 연구의 논의를 참고해 만든 프리셋입니다.

## 사면 파생 지표 (북향성 / 동향성 / TRASP)

**(B) TRASP(일사 프록시)** — `run_aspect_derivatives`에서 `(1 - cos(aspect - 30°)) / 2`로 직접 계산:
> Roberts, D.W., & Cooper, S.V. (1989). "Concepts and techniques of vegetation mapping." In: Ferguson, D., Morgan, P., & Johnson, F.D. (eds), *Land Classifications Based on Vegetation: Applications for Resource Management*, USDA Forest Service General Technical Report INT-257, pp. 90-96.

주: 북향성 `cos(aspect)` / 동향성 `sin(aspect)`는 원형 변수인 사면방향을 모델에 쓸 수 있는 연속값으로 바꾸는 표준 변환이며 특정 문헌에 귀속되지 않습니다. 평탄지는 북향성/동향성 0, TRASP 0.5(중립)로 처리합니다.

## 이동 비용 모델 (Movement cost models)

**(B) Tobler의 하이킹 함수 (보행 속도)** — `tools/cost_models.py`의 `tobler_speed_mps`:
> Tobler, W. (1993). "Three Presentations on Geographical Analysis and Modeling: Non-Isotropic Geographic Modeling, Speculations on the Geometry of Geography, Global Spatial Analysis." *NCGIA Technical Report 93-1*.

**(B) Naismith의 규칙 (시간 기반 보행 모델)** — `naismith_time_s`:
> Naismith, W. W. (1892). "Cruach Ardran, Stobinian, and Ben More". In: "Excursions" [department: "Notes and Queries"], *Scottish Mountaineering Club Journal*, 2(3), pp. 135-136. (규칙 본문은 p. 136)

주(서지): "Excursions"는 논문 제목이 아니라 여러 짧은 기고를 묶은 **고정 칼럼명**입니다. 나이스미스 규칙은 그 칼럼 안의 위 기고문 말미에 한 문장으로 제시됩니다.

**(B) Pandolf의 운반 에너지(Load carriage) 모델** — `edge_cost`의 `MODEL_PANDOLF` 분기:
> Pandolf, K.B., Givoni, B., & Goldman, R.F. (1977). "Predicting energy expenditure with loads while standing or walking very slowly." *Journal of Applied Physiology*, 43(4), pp. 577–581. DOI: 10.1152/jappl.1977.43.4.577

주: 에너지 모드에서만 경사에 반응합니다(시간 모드는 `거리 / 일정속도`로 등방성). 내리막은 원식의 유효 범위를 벗어나므로 기립 대사항 `1.5·W`로 하한 처리합니다.

**(B) Herzog 메타볼릭 다항식** — 6차 다항식 계수(1337.8, 278.19, -517.39, -78.199, 93.419, 19.825, 1.64)를 직접 구현:
> Minetti, A.E., Moia, C., Roi, G.S., Susta, D., & Ferretti, G. (2002). "Energy cost of walking and running at extreme uphill and downhill slopes." *Journal of Applied Physiology*, 93(3), pp. 1039-1046. DOI: 10.1152/japplphysiol.01177.2001

> Herzog, I. (2013). "The potential and limits of Optimal Path Analysis." In: Bevan, A., & Lake, M. (eds), *Computational Approaches to Archaeological Spaces*, Left Coast Press, pp. 179-211.

주(원식과의 차이): 이 다항식은 Minetti 등(2002)이 측정한 경사별 에너지 소비 자료를 Herzog가 비용함수 형태로 재정리한 것입니다. 원식은 **부호 있는 경사(오르막/내리막을 구분하는 이방성)** 를 전제하지만, 본 플러그인은 `abs(dz) / 수평거리`, 즉 **경사의 절대값(등방성)** 에 적용합니다. 따라서 같은 기울기의 내리막과 오르막 비용이 같아지며, 이는 원 모델과의 의도적인 차이입니다.

**(B) Herzog 차량/수레 모델(임계 경사)** — 속도계수 `1 / (1 + (경사% / 임계경사%)^2)`와 최대 경사 초과 시 통행 불가 처리. 출처는 위 Herzog (2013)이며, 구현 형태(정규화·임계경사 파라미터화)는 아래 Čučković의 구현을 따랐습니다. 임계경사는 경사도(%)입니다(기본 12%, 이 경사에서 비용이 평지의 2배). Čučković 코드도 경사를 %로 바꿔 나누며, 그 화면 표기만 'degree'입니다. 0.1.4까지의 ArchToolkit은 이 값을 도(°)로 읽어 수레의 경사 민감도를 절반 가까이 낮게 계산했습니다.

**(C) 구현 참고 (오픈소스 플러그인):**
> Čučković, Z. (2024). *Movement Analysis* (QGIS plugin). https://github.com/zoran-cuckovic/QGIS-movement-analysis/

**(C) 상대 경사 비용 — 수식은 플러그인 정의, 논의의 출처만 아래 문헌:**
> Conolly, J., & Lake, M. (2006). *Geographical Information Systems in Archaeology*. Cambridge University Press.

주(중요): 본 플러그인의 "상대 경사 비용"은 Conolly & Lake가 출판한 방정식이 아닙니다. 두 저자의 상대 경사 비용 **논의를 참고해 플러그인이 정의한** tan 비례 패널티로, 사용자가 지정한 기준 경사(`conolly_ref_slope_deg`)에 고정됩니다: 비용계수 `= max(1, tan(경사) / tan(기준경사))`.
결과의 크기는 전적으로 기준 경사에 좌우됩니다(기준을 절반으로 낮추면 모든 경사 비용이 두 배). 기본값 5도에서 30도 사면은 평지 대비 약 6.6배(Tobler는 약 7.5배)이지만, 기준을 1도로 두면 약 33배가 되어 Tobler보다 4배 이상 징벌적입니다. **이 모델로 산출한 결과를 제시할 때는 사용한 기준 경사를 반드시 함께 보고해야 합니다.**

**(C) 경사-에너지 소비(최적 경사) 연구** — 경사 등급 프리셋 "Minetti 1995"의 배경:
> Minetti, A.E. (1995). "Optimum gradient of mountain paths." *Journal of Applied Physiology*, 79(5), pp. 1698–1703. DOI: 10.1152/jappl.1995.79.5.1698

**(C) Llobera의 시각 경관 재구성(Visual landscapes):**
> Llobera, M. (2007). "Reconstructing visual landscapes." *World Archaeology*, 39(1), pp. 51–69. DOI: 10.1080/00438240601136496

**(C) Llobera & Sluckin의 인지적 경사 연구:**
> Llobera, M. & Sluckin, T.J. (2007). "Zigzagging: Theoretical insights on climbing strategies." *Journal of Theoretical Biology*, 249(2), pp. 206–217. DOI: 10.1016/j.jtbi.2007.07.020

## AHP (Analytic Hierarchy Process)

**(B) 쌍대비교 기반 다기준 의사결정(주고유벡터 가중치 / 일관성비율)** — `tools/ahp_core.py`의 `ahp_weights_from_matrix`:
> Saaty, T.L. (1980). *The Analytic Hierarchy Process*. McGraw-Hill.

**(B) 무작위 지수(RI) 표의 확장(n>10)** — `RI_TABLE`의 n=11-15 값:
> Alonso, J.A., & Lamata, M.T. (2006). "Consistency in the Analytic Hierarchy Process: a new approach." *International Journal of Uncertainty, Fuzziness and Knowledge-Based Systems*, 14(4), pp. 445-459. DOI: 10.1142/S0218488506004114

**(C) GIS 기반 입지적합도 분석 개관 (WLC/AHP의 적용과 한계):**
> Malczewski, J. (2004). "GIS-based land-use suitability analysis: a critical overview." *Progress in Planning*, 62(1), pp. 3-65. DOI: 10.1016/j.progress.2003.09.002

주: 표에 없는 크기(n>15)의 행렬에서는 CR이 정의되지 않으므로, `ahp_core.py`는 0.0이 아니라 **NaN**을 반환하고, 대화상자는 이를 `CR=-`로 표시합니다. 0.0을 보고하면 일관적이라고 잘못 인증하는 셈이기 때문입니다(그런 경우에는 계층형으로 나누어 기준 수를 줄이십시오).

## 최소비용경로 / 비용-거리 (Least-cost path / Cost-distance)

**(B) 누적 비용(최단경로) 계산(Dijkstra)** — `tools/cost_surface_dialog.py`의 `_dijkstra_full`:
> Dijkstra, E.W. (1959). "A note on two problems in connexion with graphs." *Numerische Mathematik*, 1(1), pp. 269–271. DOI: 10.1007/BF01386390

**(B) 휴리스틱 최단경로(`A*`)** — `_astar_path`:
> Hart, P.E., Nilsson, N.J., & Raphael, B. (1968). "A Formal Basis for the Heuristic Determination of Minimum Cost Paths." *IEEE Transactions on Systems Science and Cybernetics*, 4(2), pp. 100–107. DOI: 10.1109/TSSC.1968.300136

## 최소비용 네트워크 (Least-cost Network)

**(B) MST(최소 신장 트리)** — 간선 정렬 + Union-Find, 즉 Kruskal 방식으로 구현:
> Kruskal, J.B. (1956). "On the shortest spanning subtree of a graph and the traveling salesman problem." *Proceedings of the American Mathematical Society*, 7(1), pp. 48–50.

**(C) 관련 MST 알고리즘 (플러그인은 구현하지 않음):**
> Prim, R.C. (1957). "Shortest Connection Networks and Some Generalizations." *Bell System Technical Journal*, 36(6), pp. 1389–1401. DOI: 10.1002/j.1538-7305.1957.tb01515.x

## 사회 네트워크 분석 (SNA: Social Network Analysis)

**(C) 중심성(centrality) 개념:**
> Freeman, L.C. (1979). "Centrality in social networks: Conceptual clarification." *Social Networks*, 1(3), pp. 215–239.

**(B) 근접 중심성(closeness)의 성분 크기 보정** — `tools/network_metrics.py`가 Wasserman & Faust의 보정식 `(r / Σd) × (r / (n-1))`을 가중/비가중 두 경로 모두에 구현:
> Wasserman, S., & Faust, K. (1994). *Social Network Analysis: Methods and Applications*. Cambridge University Press.

주: 단순한 `도달수 / 거리합`은 2개 노드만으로 이루어진 고립 성분에 최고점을 주므로, 끊긴 그래프(k-NN 네트워크에서 흔함)에서는 해석이 뒤집힙니다. 도달 가능한 비율 `r/(n-1)`을 곱해 "네트워크 전체 중 얼마나 닿을 수 있는가"를 반영합니다.

**(B) Betweenness 계산(Brandes 알고리즘)** — 무향 그래프 0.5 정규화 포함:
> Brandes, U. (2001). "A faster algorithm for betweenness centrality." *Journal of Mathematical Sociology*, 25(2), pp. 163–177.

**(C) SNA 개론/표준 참고서:**
> Newman, M.E.J. (2010). *Networks: An Introduction*. Oxford University Press.

## 근접성 네트워크 (PPA: Proximal Point Analysis)

**(A) 들로네 삼각분할 후보 간선** — `qgis:delaunaytriangulation` / `native:delaunaytriangulation` 호출 (원 출처는 위 Delaunay 1934).

**(B) Gabriel graph** — `tools/spatial_network_dialog.py`의 `_ppa_filter_gabriel`(간선 AB를 지름으로 하는 원 안에 다른 점이 없을 때만 유지):
> Gabriel, K.R., & Sokal, R.R. (1969). "A new statistical approach to geographic variation analysis." *Systematic Zoology*, 18(3), pp. 259-278. DOI: 10.2307/2412323

**(B) RNG (Relative Neighborhood Graph)** — `_ppa_filter_rng`(A·B 양쪽에서 모두 더 가까운 제3의 점이 없을 때만 유지):
> Toussaint, G.T. (1980). "The relative neighbourhood graph of a finite planar set." *Pattern Recognition*, 12(4), pp. 261-268. DOI: 10.1016/0031-3203(80)90066-7

**(C) 고고학적 맥락/방법론 리뷰:**
> Terrell, J.E. (1977). "Human Biogeography in the Solomon Islands." *Fieldiana Anthropology*, 68(1), pp. 1–47.

> Brughmans, T., & Peeples, M.A. (2017). "Trends in archaeological network research: a bibliometric analysis." *Journal of Historical Network Research*, 1, pp. 1–24. DOI: 10.25517/jhnr.v1i1.10

> Amati, V., Shafie, T., & Brandes, U. (2018). "Reconstructing Archaeological Networks with Structural Holes." *Journal of Archaeological Method and Theory*, 25, pp. 226–253. DOI: 10.1007/s10816-017-9335-1

## 가시성 네트워크 (Visibility / Intervisibility Network)

**(B) 구현 — 유적 간 상호가시성(LOS) 검사** (`tools/spatial_network_dialog.py`): 두 유적을 잇는 시선을 DEM 위에서 등간격으로 샘플링해 지형이 시선을 가리는지 판정합니다. 각 샘플 지형고도에는 지구 곡률·대기 굴절 보정 `cc · d² / (2R)` (R = 6,371,000 m, cc = 1 − 굴절계수, 기본 굴절계수 0.13 → cc = 0.87)을 적용하며, 이는 `gdal_viewshed`가 쓰는 보정과 같은 식입니다. DEM NoData를 만난 쌍은 "샘플 실패"로 기록되고 노드 레이어의 `fail_deg`에 집계됩니다(가시성 없음으로 취급하지 않음). 폴리곤 입력의 `vis_ratio_ab`는 A의 경계 샘플 중 B의 대표점이 보이는 비율입니다.

**(C) 고고학적 해석 맥락 (구현은 위 LOS 검사와 네트워크 지표의 조합):**
> Van Dyke, R.M., Bocinsky, R.K., Windes, T.C., & Robinson, T.J. (2016). "Great houses, shrines, and high places: intervisibility in the Chacoan world." *American Antiquity*, 81(2), pp. 205–230.

> Gillings, M., & Wheatley, D. (2001). "Seeing is not believing: unresolved issues in archaeological visibility analysis." In: *On the Good Use of Geographical Information Systems in Archaeological Landscape Studies* (COST Action G2).

> Turner, A., Doxa, M., O'Sullivan, D., & Penn, A. (2001). "From isovists to visibility graphs: a methodology for the analysis of architectural space." *Environment and Planning B: Planning and Design*, 28(1), pp. 103–121. DOI: 10.1068/b2684

주: Turner 등(2001)의 VGA(visibility graph analysis)는 **격자 셀 간** 가시성 그래프를 다루는 방법론이며, 이 도구가 계산하는 **유적(점/폴리곤) 간** 상호가시성 네트워크와는 다른 방법입니다. 시각 그래프라는 착상의 배경으로만 참고하십시오.

## 가시권 분석 (Viewshed / LOS)

**(A) GDAL `gdal_viewshed`가 구현한 기준면(reference-plane) 방식** — `gdal:viewshed` 호출:
> Wang, J., Robinson, G. J., & White, K. (2000). "Generating viewsheds without using sightlines." *Photogrammetric Engineering & Remote Sensing*, 66(1), pp. 87-90.

**(C) 같은 저자들의 선행 연구 (이 플러그인이 호출하는 알고리즘은 아님):**
> Wang, J., Robinson, G. J., & White, K. (1996). "A Fast Solution to Local Viewshed Computation Using Grid-Based Digital Elevation Models." *Photogrammetric Engineering & Remote Sensing*, 62(10), pp. 1157–1164.

주: 두 논문은 저자가 같아 혼동되기 쉽지만, GDAL이 구현한 것은 2000년 논문의 기준면 방식입니다.

**(C) 누적 가시권(cumulative viewshed)의 고고학적 적용 맥락:**
> Wheatley, D. (1995). "Cumulative viewshed analysis: a GIS-based method for investigating intervisibility, and its archaeological application." In: Lock, G., & Stančič, Z. (eds), *Archaeology and Geographic Information Systems: A European Perspective*. Taylor & Francis, London. (2022년 Routledge 재간행판 DOI: 10.1201/9780367810467-13)

## 히구치 거리대 (Higuchi view zones)

**(C) 거리대 개념의 출처 (미터 기준값의 출처는 아님):**
> 樋口忠彦 [Higuchi, T.] (1975). 『景観の構造 — ランドスケープとしての日本の空間』. 技報堂, 東京. (일본어 원저)
>
> 영역본: Higuchi, T. (1983). *The Visual and Spatial Structure of Landscapes*. Translated by Charles S. Terry. MIT Press, Cambridge, MA.

주(서지): 영문 제목 *The Visual and Spatial Structure of Landscapes*는 **1983년 MIT Press 영역본**의 제목입니다. 1975년 판은 일본어 원저 『景観の構造』(技報堂)이므로, "Higuchi, T. (1975). The Visual and Spatial Structure of Landscapes. MIT Press." 라는 형태의 인용은 두 판본을 뒤섞은 것이며 그런 책은 존재하지 않습니다. 연도를 1975로 쓰려면 일본어 원저를, 영문 제목을 쓰려면 1983년 영역본을 인용해야 합니다.

주(중요): Higuchi는 근경/중경/원경을 **관측 거리 ÷ 대상 높이의 비율(D/H)** 로 정의했습니다. 본 플러그인이 쓰는 **미터 단위 경계값(기본 500m / 2500m, 사용자 조정 가능)** 은 GIS 실무에서 널리 쓰이는 관례일 뿐 Higuchi(1975)가 제시한 수치가 아닙니다. 대상 유적(성벽·고분·산체 등)의 높이와 규모에 맞게 경계값을 조정해 사용하고, 실제 사용한 값은 결과 레이어 메타데이터(`higuchi_near_m`, `higuchi_mid_m`)에 기록됩니다.

## 지형 거칠기 지수 TRI (Terrain Ruggedness Index)

**(A) 지수(index)의 원 출처** — `gdal:triterrainruggednessindex`(gdaldem TRI의 기본 알고리즘 `-alg Riley`) 호출:
> Riley, S.J., DeGloria, S.D., & Elliot, R. (1999). "A terrain ruggedness index that quantifies topographic heterogeneity." *Intermountain Journal of Sciences*, 5(1-4), pp. 23-27.

주(등급 구분은 플러그인 정의): Riley 등(1999)이 제시한 것은 **절대 미터 값 기준의 7등급**입니다 — 0-80 level, 81-116 nearly level, 117-161 slightly rugged, 162-239 intermediately rugged, 240-497 moderately rugged, 498-958 highly rugged, 959-4367 extremely rugged. 본 플러그인이 화면에 쓰는 **5등급은 사용자가 입력한 험준 기준값(`험준기준`)에 비례 배분한 플러그인 자체 구분**이며 Riley의 분류가 아닙니다. 정리하면 **지수는 Riley, 등급 표시는 플러그인**입니다.

**(B) 반경 확장 TRI (정규화 RMS 형태)** — `tools/terrain_math.py`의 `tri_radius`:
> 반경 2셀 이상을 선택하면 `sqrt(mean((z_중심 - z_이웃)^2))`, 즉 Riley 지수를 `sqrt(N)`으로 나눈 **평균제곱근 형태**를 직접 계산합니다(3x3 전체 창에서는 정확히 `sqrt(8)` 배 차이). gdaldem TRI는 3x3 고정이라 창을 넓히면 합이 셀 수에 따라 커져 반경 간 비교가 불가능하기 때문입니다. 단위가 Riley 지수와 다르므로 **별도 지표로** 읽어야 합니다.

## 지형 위치 지수 TPI (Topographic Position Index)

**(A) 지수(index)의 원 출처 — 반경 1셀(3x3)일 때만 이 알고리즘을 호출** — `gdal:tpitopographicpositionindex`(중심 셀과 주변 셀 평균의 차):
> Wilson, M.F.J., O'Connell, B., Brown, C., Guinan, J.C., & Grehan, A.J. (2007). "Multiscale terrain analysis of multibeam bathymetry data for habitat mapping on the continental slope." *Marine Geodesy*, 30(1-2), pp. 3-35. DOI: 10.1080/01490410701295962

주(중요): gdaldem TPI는 3x3 고정입니다. 따라서 **반경을 2셀 이상으로 지정하면 이 알고리즘을 호출하지 않으며**, 아래 (B)의 직접 계산으로 대체됩니다. 위 인용은 반경 1셀 경로에만 해당합니다.

**(B) 반경 확장 TPI (정확한 초점평균)** — `tools/terrain_analysis_dialog.py`의 `_compute_tpi_raster`가 반경 2셀 이상에서 직접 구현:
> 반경 2셀 이상에서 `(2r+1)x(2r+1)` 창의 이웃 평균을 누적합(summed-area)으로 정확히 계산해 `DEM - 이웃평균`을 구합니다(중심 셀 제외 — gdaldem 3x3 TPI와 같은 정의, `tools/terrain_math.py`의 `focal_tpi`). Weiss의 분류가 전제하는 **광역(broad-scale) TPI**를 3x3 고정 알고리즘으로는 낼 수 없기 때문입니다. DEM NoData는 합과 개수에서 모두 제외하고, 창이 격자를 벗어나는 가장자리 r셀은 NoData입니다. DEM 한 변이 2r셀 이하이면 (A)의 3x3 경로로 되돌아가며 실제 적용된 반경 1이 보고됩니다. 0.1.4까지는 블록 평균 후 이중선형으로 되돌리는 근사였고, 곡면 지형에서 TPI를 약 3배 부풀렸습니다.

**(B) 지형 위치 6등급 분류(Landform Classification)** — `run_slope_position_analysis`가 TPI와 경사 임계값을 조합해 직접 구현:
> Weiss, A. (2001). "Topographic Position and Landforms Analysis." *Poster presentation, ESRI User Conference*, San Diego, CA.

주(정정): 이전 판의 이 문단은 "Weiss(2001)는 분류의 출처일 뿐 TPI 지수의 출처가 아니며, 지수의 출처는 Wilson 등(2007)"이라고 적었습니다. **이는 틀렸습니다.** Weiss(2001) 포스터 자체가 TPI 산식을 직접 정의하고 있어, 해당 주장은 원 출처가 스스로 반박합니다. Weiss(2001)는 **지수와 분류 양쪽의 출처**입니다. Wilson 등(2007)은 TPI를 수심 자료에 적용한 해양판 파생지표(BPI)를 제시한 것이지 TPI의 기원을 주장하지 않습니다. 이 오귀속은 Roughness의 출처를 바로잡는 과정에서 본 문서가 새로 만들어낸 것으로, 여기서 철회합니다.

## 지형 거칠기 Roughness

**(A) gdaldem roughness(3x3 창 내 최대-최소 표고차)의 원 출처** — `gdal:roughness` 호출:
> Wilson, M.F.J., O'Connell, B., Brown, C., Guinan, J.C., & Grehan, A.J. (2007). "Multiscale terrain analysis of multibeam bathymetry data for habitat mapping on the continental slope." *Marine Geodesy*, 30(1-2), pp. 3-35. DOI: 10.1080/01490410701295962

주(등급 구분은 플러그인 정의): 0-1 / 1-3 / 3-6 / 6-15 / 15m 이상의 5등급은 한국 지형을 염두에 둔 **플러그인의 표시 관례**이며 Wilson 등(2007)이 출판한 분류가 아닙니다(레이어 메타데이터에 `plugin_defined_5class`로 기록됩니다).

**(C) 일반 지형계측(geomorphometry) 참고 — 이 알고리즘의 출처는 아님:**
> Wilson, J.P., & Gallant, J.C. (2000). *Terrain Analysis: Principles and Applications*. John Wiley & Sons.

주: 이전 판 문서는 Roughness의 출처로 Wilson & Gallant(2000)를 적었으나, gdaldem이 구현한 roughness의 출처는 **Wilson, M.F.J. 등(2007)** 입니다. 저자도 논문도 다른 문헌이므로 위와 같이 분리했습니다.

## 곡률 Curvature (종단/횡단)

**(B) Zevenbergen & Thorne 곡률 (2차 다항식 적합)** — `tools/terrain_math.py`의 `zt_curvature`:
> Zevenbergen, L.W., & Thorne, C.R. (1987). "Quantitative analysis of land surface topography." *Earth Surface Processes and Landforms*, 12(1), pp. 47-56.

**부호 규약 (교차 검증 시 반드시 확인)** — ArchToolkit 구현, 수치 검증됨:

- 본 플러그인의 종단/횡단 곡률 값은 Zevenbergen & Thorne 공식(ESRI 문서와 대부분의 교과서에 인쇄된 형태)의 **부호를 뒤집은 값(negation)** 입니다.
- 그 결과 본 플러그인의 부호는 ESRI 문서의 **서술적 설명**("음의 종단곡률 = 볼록")과 일치합니다.
- 반면 GRASS `r.slope.aspect`는 **반대 부호**를 사용합니다. 따라서 GRASS나 SAGA로 교차 검증하면 값의 크기는 같고 **부호만 뒤집혀** 보입니다. 오류가 아니라 규약 차이입니다.
- 정리: 종단(profile) 음(−)=볼록(침식 경향) / 양(+)=오목(퇴적 경향); 횡단(plan) 음(−)=수렴(물 모임) / 양(+)=발산(능선).

## 공변량 상관 / VIF (Covariate report)

**(B) 분산팽창지수 VIF = 1 / (1 - R²)** — `tools/covariate_report_dialog.py`가 직접 계산. 임계값 5·10은 경험 규칙이며 특정 문헌의 규정이 아닙니다.

**(C) VIF 경험 규칙의 한계에 관한 경고:**
> O'Brien, R.M. (2007). "A caution regarding rules of thumb for variance inflation factors." *Quality & Quantity*, 41(5), pp. 673-690. DOI: 10.1007/s11135-006-9018-6

주: O'Brien은 VIF 4·10 같은 임계값을 기계적으로 적용해 변수를 제거하는 관행을 비판하고, 표본 크기와 효과 크기를 함께 고려하라고 권합니다. 본 도구의 리포트는 임계값을 참고선으로만 표시합니다.

## 후속 분석 참고 (이 플러그인이 구현하지 않음)

### MaxEnt (Maximum Entropy) / 예측모델링 — (C)

**본 플러그인은 MaxEnt를 구현하지 않습니다.** 플러그인이 하는 일은 예측변수(predictor) **준비**까지입니다: 지질도 ZIP의 범주형 래스터 변환, 공변량 다중공선성 점검 리포트, 지형 파생 래스터 생성 등. 모델 적합과 평가는 MaxEnt/GLM/RF 등 **외부 도구**에서 수행합니다. 아래 문헌은 그 후속 분석의 참고입니다.

> Phillips, S.J., Anderson, R.P., & Schapire, R.E. (2006). "Maximum entropy modeling of species geographic distributions." *Ecological Modelling*, 190(3–4), pp. 231–259.

> Phillips, S.J., & Dudík, M. (2008). "Modeling of species distributions with Maxent: new extensions and a comprehensive evaluation." *Ecography*, 31(2), pp. 161–175.

> Elith, J., Phillips, S.J., Hastie, T., Dudík, M., Chee, Y.E., & Yates, C.J. (2011). "A statistical explanation of MaxEnt for ecologists." *Diversity and Distributions*, 17(1), pp. 43–57.

## 지구화학도 범례 프리셋 (GeoChem)

**(C) 자료 출처 (알고리즘 아님):**
> 한국지질자원연구원(KIGAM). 지구화학도 WMS 렌더링 이미지 (원자료 수치가 아니라 색상으로 표현된 지도).

주: `tools/geochem_polygonize_dialog.py`의 프리셋 7종(Fe2O3, Pb, Cu, Zn, Sr, Ba, CaO)은 문헌이 아니라 서비스 범례를 판독해 입력한 표입니다.
Fe2O3는 사용자가 제공한 범례 포인트(색-값)이고, 나머지 6종은 백분위 구간값만 범례에서 읽었으며 색상 팔레트는 Fe2O3와 같다고 **가정**했습니다.
값 역추정은 범례 폴리라인 최근접 투영(선형 보간)이며, 색 거리가 `RGB_MATCH_TOLERANCE`를 넘는 픽셀은 NoData로 제외됩니다.
범례가 백분위 구간표이므로 최상위 구간 색은 구간 상한값으로 기록되고, 그 사이 값은 구간 경계 사이의 선형 보간값입니다.

## 지질도 데이터 (KIGAM 1:50,000)

**(C) 자료 출처 (알고리즘 아님):**
> 한국지질자원연구원(KIGAM). 1:50,000 지질도 도엽(벡터 SHP, ZIP) 데이터.

---
*ArchToolkit은 QGIS Processing Framework와 GDAL을 활용합니다.*
