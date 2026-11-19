# ArchToolkit 학술 연구 활용 및 논문 기술 가이드

이 문서는 ArchToolkit의 19개 도구를 **학술 논문·학위논문·발굴/지표조사 학술보고서**에 활용할 때, 각 도구를 어디까지 근거로 쓸 수 있는지와 **연구방법(Methods) 절에 반드시 밝혀야 할 사항**을 정리한 안내서입니다.

외부 기준 소프트웨어(GRASS GIS 8.4, R 4.5, GDAL, SciPy, NetworkX, Shapely)와의 실측 교차 검증 수치는 [docs/BENCHMARK.md](BENCHMARK.md)에, 86건의 검증된 1차 출처·DOI는 [REFERENCES.md](../REFERENCES.md)에 있습니다.

---

## 1. 도구별 연구 활용 등급 (3단계)

ArchToolkit은 모든 결과 레이어의 메타데이터(`archtoolkit/research_scope`, `archtoolkit/caveat`)에 아래 등급과 유의사항을 자동 기록하며, Tier 2·Tier 3 도구의 대화상자 상단에도 안내 배너를 표시합니다.

### Tier 1 — 표준 알고리즘·전처리 (논문 직접 활용 가능, 9개)

외부 표준 소프트웨어(GDAL, GRASS, R `terra`/`stats`, SciPy)와 기계 정밀도 또는 Float32 라운딩 수준으로 일치하는 표준 연산입니다.

| 도구 | 논문 Methods 절 필수 기재 항목 | 주요 유의사항 |
| --- | --- | --- |
| **등고선 추출** | 원본 DEM 출처·해상도, 등고선 간격 | DEM 수직 정확도보다 좁은 간격 지양 |
| **지형 분석** | DEM 해상도·투영좌표계, TPI 반경·임계값(자동 SD 권장), 곡률 부호 규약 | 곡률은 ESRI 부호 규약(GRASS/SAGA와 반대); 화면 5등급 중 한국표준 경사(산림청 예규) 외에는 플러그인 표시 관례 |
| **경사·사면 도면화** | 경사 등급 구간, 화살표 블록 간격 | 등급 구간은 도면 관례이므로 범례에 명시 |
| **거리 래스터** | 기준 격자 해상도·투영좌표계, 대상 레이어 출처 | 직선 유클리드 거리(지형 기복·장벽 미반영) |
| **정렬 / 내보내기** | 기준 격자 CRS·해상도, 연속/범주/방향 변수별 리샘플링 방식, `valid_pct` | `manifest.csv`의 `categorical`·`nodata`·`valid_pct` 점검 |
| **변수 상관 / VIF** | 표본 추출 범위(AOI), 표본 수, 변수 선별 기준 | VIF 5·10은 절대 규칙이 아닌 참고선(O'Brien 2007); 원형 변수는 순환-선형 $R^2$로 별도 해석 |
| **지질도 도엽 ZIP** | KIGAM 도엽명·축척(1:50,000), 래스터 픽셀 크기, `mapping.csv` | 정수 코드는 해당 실행 코드표에서만 유효; 픽셀보다 좁은 암체 소실 가능 |
| **지형 단면** | 단면선 위치, 표본 간격, 수직 과장 배율, NoData 구간 길이 | 이동평균 평활화를 켠 경우 원시 표본이 아님을 명시 |
| **도면 시각화** | 수치지형도 출처·NGII 코드 버전(Ver 5.1.1), 고도 색상 구간 | 도면화 보조 산출물이며 법정 측량 원도 대체 불가 |

---

### Tier 2 — 학술 모형 (가정 기재·상대 비교·필요 시 교차검증 권장, 6개)

학술 문헌의 수식과 알고리즘을 정직하게 구현했으나, **모형 가정과 입력 자료 한계가 해석에 직접 영향을 미치는 도구**입니다. 심사위원 질의에 대비해 아래 조건을 본문에 반드시 명시하십시오.

| 도구 | 모형 한계와 학술적 선 긋기 | ArchToolkit의 보완 장치 | 논문 필수 기재 항목 |
| --- | --- | --- | --- |
| **DEM 생성 (Kriging Lite 포함)** | 보간면은 측정이 아닌 추정치입니다. Kriging(Lite)는 등방성 국소 Ordinary Kriging이며 이방성·광역 추세 제거(Universal Kriging)는 수행하지 않습니다. | Cressie(1985) WLS 자동 적합, Gaussian 무너겟 특이성 안정화, LOOCV(RMSE·MAE·MSDR), **4방위 이방성 비 및 1차 평면 추세 $R^2$ 자동 진단·경고**. | 보간 방식, 픽셀 크기, Kriging 모델·너깃·실·레인지, LOOCV RMSE·MSDR, 이방성/추세 경고 여부(강한 이방성·추세 시 R `gstat` 교차 검증 권장). |
| **가시권 분석** | 입력 DEM(지형)만 고려하므로 고식생·당대 건축물·기상 조건·지형 개변을 알 수 없습니다. | 곡률·대기 굴절 보정(`k=0.13`) 일원화, 반경 밖/NoData 구분, GRASS `r.viewshed` 대비 99.83% 일치 검증. | DEM 출처·해상도, 관측자·대상 높이, 최대 거리, 곡률·굴절 계수, 히구치 경계값(실무 관례 명시). **"실제로 보였음"이 아니라 "지형 차폐 없음"** 으로 서술(식생 반영이 필요하면 DSM 입력). |
| **비용표면 / 최소비용경로** | 격자 누적 모형이며 실제 옛길의 증거가 아닌 가설입니다. 경사 외 도로·하천·토지피복은 추가 마찰로 근사합니다. | **16방향 나이트 이동(Knight's Move)** 으로 최대 격자 신장오차를 8.24% → **2.75%** 로 축소(1픽셀 절벽·NoData·하천 관통 차단), GRASS `r.walk` 교차 검증. | 비용 모델명과 모든 파라미터, 격자 연결성(4/8/16방향), 마찰 설정, DEM 해상도. 절대 시간·칼로리 주장보다 **경로·후보 간 상대 비교**로 해석. |
| **최소비용 네트워크** | 유클리드 후보 $k$ 위 격자 LCP 근사 연결망이며, 유적 1곳 누락에도 MST 구조가 바뀔 수 있습니다. | 16방향 나이트 이동 지원, 대칭화 방식·후보 $k$ 메타데이터 기록, R `igraph`·NetworkX 대비 `0.0` 오차 검증. | 비용 모델, 연결성(8/16방향), 후보 $k$, 대칭화 규칙, 유적 표본의 완전성 한계. |
| **근접 / 가시성 네트워크** | 연결선은 실제 교류·통시의 증명이 아니라 공간·지형 기반 가능성 모형입니다. | DEM NoData 검사 불가 쌍을 `fail_deg`로 분리(안 보임과 혼동 방지), 72회전 스케일 불변 RNG, `betw_norm`·`harmonic` 제공. | 그래프 정의(PPA 방식·$k$ 또는 LOS 높이·최대거리·굴절 보정), 표본 누락 한계, `fail_deg` 건수. |
| **AHP 입지적합도** | 전문가 판단을 구조화한 상대 적합도 지수이며 유적 존재 확률이 아닙니다. | Saaty 주고유벡터, Alonso & Lamata 확장 RI, 계층형 그룹/하위 CR 분리, **Chen et al.(2010) OAT 가중치 민감도 보고서** 자동 생성. | 기준 목록·정규화 방식, 쌍대비교 행렬, CR(계층 시 그룹·하위 CR), OAT 민감도 결과(방법론 보고서 부록 첨부 권장). |

---

### Tier 3 — 예비 탐색·현장·행정 보조 (논문 1차 정량 근거 사용 금지, 4개)

현장 실무와 예비 탐색에 매우 유용하지만, **본질적으로 근사 역추정·휴리스틱·비법정 참고·AI 초안**이므로 학술 논문의 1차 정량 데이터나 확정 해석으로 사용해서는 안 됩니다.

| 도구 | 왜 1차 정량 근거로 쓰면 안 되는가 | 올바른 활용 범위 |
| --- | --- | --- |
| **지구화학도 수치화** | KIGAM WMS **렌더링 색상**에서 범례로 역추정한 근사값이며 원시 분석치가 아닙니다. | 조사 전 예비 탐색·시각화·이상대 개략 파악. 정량 지구화학 논문에는 KIGAM에 원시 분석치(점 데이터)를 요청해 사용. |
| **트렌치 후보 제안** | 2D SAT 경사 검사와 축방향($2\theta$) 방위 계산은 정확하지만, **배치 점수식 자체는 플러그인 휴리스틱**이며 학술 확률 표본설계(Kintigh 1988; Orton 2000)나 유구 존재 보장이 아닙니다. | 시굴조사 계획 수립 시 지형·접근성·무덤 회피를 검토하는 현장 보조안(최종 판단은 현장 조사자). |
| **지적도 중첩 면적표** | 연속지적도와 GIS 투영 경계의 정밀도 차이로 **법정 지적 공부 면적과 다를 수 있으며 법적 효력이 없습니다.** | 조사 면적 개략 집계 및 필지 목록 파악. 행정·인허가·법적 보고에는 지적 공부 면적 우선. |
| **AI 조사요약** | 생성형 AI 초안은 검증된 고고학 해석이 아니며, 외부 API 전송 시 매장유산 위치정보 유출 위험이 있습니다. | 로컬 통계 번들(`context.json`, `CSV`, `params.json`) 기반 기초 현황 정리 및 초안 참고. 민감한 유적 위치는 로컬 모드 사용. |

---

## 2. 논문 연구방법(Methods) 절 권장 기술 예시

> **국문 예시**:  
> 지형·가시권·이동비용 및 네트워크 분석은 QGIS 3.40 LTR 환경에서 ArchToolkit v0.1.7(Hwang, 2026)을 사용하여 수행하였다. 모든 공간 연산은 투영좌표계 `EPSG:5186`(미터 단위)에서 10 m 해상도 DEM(출처: 국토지리정보원 수치지형도 1:5,000)을 기반으로 실행하였으며, 각 레이어 메타데이터(`params_json`)에 기록된 파라미터로 재현성을 확보하였다. 이동비용 분석은 Tobler(1993) 보행 함수를 16방향 나이트 이동 격자(Huber & Church, 1985; 최대 격자 신장오차 2.75%)로 적용하여 상대적 이동 효율을 비교하였으며, 가시권 분석은 지구 곡률 및 대기 굴절 보정($k=0.13$; Yoeli, 1985)을 적용한 지형(DEM) 단독 가시 가능성으로 해석하였다.

> **영문 예시**:  
> Terrain, viewshed, least-cost, and network analyses were conducted in QGIS 3.40 LTR using ArchToolkit v0.1.7 (Hwang, 2026) in projected metric CRS `EPSG:5186` on a 10 m DEM. Least-cost accumulation used Tobler's (1993) hiking function on a 16-neighbor knight's-move lattice (Huber & Church, 1985; maximum flat-plane elongation 2.75%) and is interpreted comparatively as a movement hypothesis rather than direct evidence of past roads. Viewshed results include Earth curvature and standard atmospheric refraction ($k=0.13$; Yoeli, 1985) and represent bare-earth topographic visibility without paleovegetation or built structures. All run parameters were archived via layer `params_json` metadata.

---

## 3. 동료 심사(Peer Review) 예상 질문과 대응

- **Q1. "플러그인의 자체 구현 수식을 신뢰할 수 있는가?"**  
  → [docs/BENCHMARK.md](BENCHMARK.md)에 동일 입력으로 GRASS GIS 8.4(`r.slope.aspect`, `r.viewshed`, `r.walk`, `r.walk -k`), R 4.5(`igraph`, `terra`, `stats`), SciPy, NetworkX, Shapely와 교차 검증한 실측 오차표와 재현 스크립트(`scripts/run_benchmarks.py`)가 공개되어 있습니다.
- **Q2. "8방향 격자 이동비용은 경로가 왜곡되지 않는가?"**  
  → 0.1.7부터 16방향 나이트 이동 옵션을 제공해 최대 격자 신장오차를 8.24%에서 2.75%로 줄였으며(GRASS `r.walk -k` 동일 수준), 1픽셀 절벽·NoData·하천 관통도 차단합니다.
- **Q3. "Ordinary Kriging(Lite)가 등방성·정상성 가정을 어기면 어떻게 아는가?"**  
  → 실행마다 LOOCV(RMSE, MAE, MSDR)와 함께 4방위 방향성 변동함수 이방성 비, 1차 평면 추세 $R^2$를 자동 진단해 가정 이탈 시 경고를 출력하고 `params_json`에 기록합니다.
- **Q4. "정확한 버전과 알고리즘 출처를 어떻게 인용하는가?"**  
  → [CITATION.cff](../CITATION.cff) 및 Zenodo 영구 DOI(릴리스 태그 발행 시 부여)로 소프트웨어를 인용하고, 개별 알고리즘의 원 논문·DOI는 [REFERENCES.md](../REFERENCES.md)에서 `(A) 호출 / (B) 직접 구현 / (C) 참고` 구분을 확인해 함께 인용하십시오.
