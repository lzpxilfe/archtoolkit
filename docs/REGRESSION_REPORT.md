# 회귀 비교 보고 (2026-09-21)

**질문:** 감사 라운드의 대규모 수정(d1ecf88 → 현재 main)이 잘 돌아가던 기능을 망치지 않았는가.

**방법:** 실제 QGIS 3.34.4를 화면 없이 띄우고, 같은 합성 데이터(60x60 DEM, 점·선·폴리곤 메모리 레이어,
RGB 래스터 등)로 19개 도구를 수정 전 체크아웃(d1ecf88)과 수정 후 체크아웃에서 각각 실행해 결과 수치를
비교했습니다. 하네스는 `tests/regression/`에 있습니다. 시나리오 27개, 양쪽 모두 실행 성공.

**결론:** 수정 후 코드에서만 실패한 경우는 없습니다. 수치가 달라진 곳은 모두 의도한 수정으로 설명되며,
비교 과정에서 새 결함 2건을 찾아 바로잡았습니다(아래 "비교가 잡아낸 것").

## 시나리오별 결과

| 시나리오 | 전 | 후 | 수치 | 달라진 이유 |
| --- | --- | --- | --- | --- |
| terrain_basic (경사·사면·TRI·TPI·거칠기·곡률·사면 파생) | 실행 | 실행 | 동일 | 레이어 이름·메타데이터만 변경 |
| terrain_multiscale (TPI r=3, Weiss 분류, TRI r=2) | 실행 | 실행 | TPI·분류 변경 | TPI 창을 r셀에서 (2r+1)셀로 교정 |
| terrain_tpi_fallback (작은 DEM에 r=15) | 실행 | 실행 | 변경 | 소형 DEM 보호: 3x3으로 대체하고 실제 반경 1 보고 |
| viewshed_single | 실행 | 실행 | 동일 | |
| viewshed_higuchi (기본 500/2500) | 실행 | 실행 | 동일 | 메타데이터에 경계값 기록 |
| viewshed_higuchi_custom (200/400) | 실행 | 실행 | 변경 | 히구치 경계 조정 기능(수정 전에는 고정) |
| cost_tobler (비용표면 + LCP) | 실행 | 실행 | 동일 | 모델·연결성 메타데이터 추가 |
| cost_conolly (기준 경사 5° 고정) | 실행 | 실행 | 동일 | 이름 변경. 위젯 기본값은 1°→5°로 바뀜 |
| cost_network_mst | 실행 | 실행 | 동일 | |
| contour_5m | 실행 | 실행 | 동일 | |
| profile_line | 실행 | 실행 | 동일(1e-6) | 타원체 NONE→WGS84 정규화 |
| map_styling_dem | 실행 | 실행 | 동일 | |
| network_ppa (k-NN, Delaunay, 좌표 중복) | 실행 | 실행 | 중복 케이스만 변경 | 좌표가 같은 유적이 간선을 공유(수정 전에는 고립) |
| network_visibility (LOS 6점) | 실행 | 실행 | 동일 | 레이어 이름에 파라미터, fail_deg·betw_norm 필드 |
| dem_generator (TIN/IDW/Kriging, ELEV/Elevation) | 실행 | 실행 | 변경 | 수정 전: 2D 'ELEV' 레이어가 전부 NoData인 DEM을 "완료"로 보고. 수정 후: 정상 DEM. 픽셀 크기 스냅으로 격자 정수배 |
| kriging_direct (49점, 30 m 기준점) | 실행 | 실행 | 변경 | 정확 보간: 기준점 29.20→30.00 m, 분산 0 |
| geology_rasterize (2도엽 병합·개별) | 실행 | 실행 | 코드 번호 변경 | 코드표를 도엽 전체 정렬 순으로 통일, CSV에 cell_count·labels_all |
| geochem_polygonize (RGB + 검은 선, 구역) | 실행 | 실행 | 변경 | 검은 선 픽셀 99개가 51%(범례 최댓값)에서 NoData로; 구역 통계 픽셀 중심 규칙 |
| distance_raster (선·점·얇은 폴리곤) | 실행 | 실행 | 얇은 폴리곤만 변경 | 수정 전: 전부 -9999인 래스터를 "완료"로 보고. 수정 후: 실제 거리 (아래 결함 2 참조) |
| align_export (사면방향, 메타 없는 Byte) | 실행 | 실행 | 변경 | 사면방향 최근접, 메타 없는 정수 래스터 최근접·unknown 표기 |
| ahp_flat | 실행 | 실행 | 동일 | weights_source 메타데이터 |
| ahp_hierarchy (2그룹, Saaty 초과 2쌍) | 실행 | 실행 | 변경 | 계층 전역가중치를 실제 사용 (아래 결함 1 참조) |
| trench_suggestion | 실행 | 실행 | 동일(점수·경사) | pick_order·slope_max_deg 필드, 메타데이터 |
| trench_grave_keywords (15개 문자열) | 실행 | 실행 | 4건 True로 | 지석묘·천마총·dolmen·tumuli 인식, 오탐 가드 유지 |
| cadastral_overlap | 실행 | 실행 | 동일 | |
| covariate_report | 실행 | 실행 | 동일(바이트 동일) | |
| ai_report_local | 실행 | 실행 | 변경 | 수정 전: FID 순 12개만 보고 AOI 안 3개를 놓침. 수정 후: 전수 분류, 최근접 0 m |

## 비교가 잡아낸 것

1. **AHP 계층 가중치**: 계층 모드에서 전역가중치를 쓰도록 한 수정이 표 갱신 함수에 덮여 실제로는
   평면 표 가중치로 계산되고 메타데이터만 "hierarchy_global"이라 적혔습니다. 가중치 갱신 함수를 단일
   출처로 고쳐 래스터 계산기에 0.9/0.01/0.09가 전달되는 것을 확인했습니다.
2. **거리 래스터 ALL_TOUCH**: QGIS 3.34·3.40의 `gdal:rasterize`는 ALL_TOUCH 상수를 선언하지만 파라미터로
   등록하지 않아 값이 무시됩니다. 얇은 폴리곤이 0셀로 구워져 실행이 거부됐습니다. `EXTRA="-at"`로
   전달하도록 고쳐 실측(0셀 → 112셀)으로 확인했습니다.

## 재현

`tests/regression/README.md` 참조. 전체 27개 시나리오는 체크아웃당 약 20초 걸립니다.

## Qt6 이관 라운드 (2026-09-22)

QGIS 4(PyQt6) 대비 표기 이관(스코프 열거형, `QMetaType` 필드 타입, `Qgis.*` 열거형, `tools/qtcompat.py`) 뒤 같은 27개 시나리오를
이관 전 커밋과 다시 비교했습니다. 27건 모두 실행, 25건 수치 지문 동일, 나머지 2건(trench_suggestion, geochem_polygonize)은
실행마다 달라지는 run id·시각이 든 레이어 이름만 다르고 수치는 같습니다. 대화상자 19개 생성과 initGui/unload도 확인했습니다.

## 도구 6개 리뷰 라운드 (2026-09-22)

거리 래스터, 정렬/내보내기, 변수 상관/VIF, AHP, 트렌치 후보 제안, AI 조사요약을 리뷰해 결함마다 합성 데이터로
재현한 뒤 고쳤습니다(재현은 `tests/test_*_review.py`). 같은 27개 시나리오를 리뷰 전 커밋과 비교한 결과입니다.

| 시나리오 | 결과 | 달라진 값 |
| --- | --- | --- |
| 20개 | 수치 지문 동일 | 없음 |
| distance_raster | 거리값 동일 | 출력 밴드의 nodata가 None에서 -9999로 (최대 거리 밖 셀이 이제 NoData) |
| trench_suggestion | 같은 트렌치·순위·점수 | slope_max_deg 합 42.36에서 32.26으로 (반경 원 대신 실제 사각형 안 셀) |
| ahp_flat, ahp_hierarchy | 래스터·가중치 동일 | 재현용 메타데이터 추가, 계층 모드 CR이 근사 표의 0.483 대신 그룹·하위 행렬의 0.000 |
| covariate_report | n·r·VIF 동일 | CSV 머리에 범위 블록 추가 |
| ai_report_local | 면적·개수·거리·통계 동일 | 버퍼 기준 표기, 내부 유적 서술, 방향 분포가 전체 유적 기준으로 |
| geochem_polygonize | 동일 | 실행 ID만 다름 |

## 나머지 도구 13개 리뷰 라운드 (2026-09-23)

같은 27개 시나리오를 이 라운드 직전 커밋과 비교했습니다. 11개는 수치 지문이 같고, 나머지는 다음처럼 의도한 대로 달라졌습니다.

| 시나리오 | 달라진 값 |
| --- | --- |
| terrain_basic | 사면방향 가장자리 셀이 0(평탄 오표시)에서 NoData로 |
| terrain_multiscale | 반경 3 TPI 범위 [-2.83, 3.20]에서 [-0.357, 0.803]으로(이전 근사는 과대), 수동 임계값 지형분류는 3-5등급만 |
| terrain_tpi_fallback | 반경을 30으로 바꿔 3x3 대체 경로를 계속 시험(반경 15는 이제 정확한 TPI) |
| viewshed_single, viewshed_higuchi(_custom) | 보이는 셀 수 동일(1449). 결과 래스터가 DEM 범위로 줄고(600x600에서 60x60) 반경 밖 셀은 NoData |
| cost_tobler, cost_conolly | 비용·경로·래스터 동일. 마일스톤이 정확히 500 m에 놓이고 해석 간선 시간을 씀 |
| cost_network_mst | 수치 동일. 대칭화 방식·후보 k 메타데이터 추가 |
| network_ppa | 같은 위치 유적 쌍이 연결되어 간선 12개에서 13개로 |
| network_visibility | 상호 가시 쌍 하나 추가(P4-P5, gdal_viewshed도 보임으로 판정) |
| geochem_polygonize | 3.1·7.1 경계 구간이 한 등급 위로, 선 픽셀은 이웃 값 복사로(한 픽셀짜리 중간값 폴리곤 2개 소멸) |
| geology_rasterize, cadastral_overlap | 래스터·CSV·면적표 동일. 경고와 메타데이터만 정정 |
| map_styling_dem | 램프 값 동일, 범례에 구간값 |
| trench_suggestion | 실행 시각이 든 레이어 이름만 다름 |
