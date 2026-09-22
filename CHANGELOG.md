# 변경 이력

모든 버전의 요약은 `metadata.txt`의 changelog에도 있습니다. 여기가 상세본입니다.

## 0.1.4 (2026-09-22)

**주제: 실용성과 정직성.** 실제 QGIS 3.34에서 수정 전후를 비교해 검증한 세 차례 감사 라운드의 결과입니다. 기능을 제거한 항목은 없습니다. 자세한 근거는 `docs/REGRESSION_REPORT.md`와 `docs/AUDIT_BACKLOG.md`에 있습니다.

### 사용자에게 보이는 변화
- 모든 도구의 도움말 끝에 **학술 근거와 권장 절차** 블록을 추가했습니다(구현한 연구, 저자의 의도, 권장 순서, 주장하지 않는 것, 원문).
- 모든 대화상자가 마지막 입력값을 기억합니다(출력 경로와 키 계열 제외).
- 아이콘을 `icons/`로 모으고 256 px로 줄였습니다(플러그인 크기 8.7 MB 감소).
- 히구치 거리대 경계를 조정할 수 있습니다(기본 500/2500 m 유지).
- 가시성 네트워크의 LOS에 지구 곡률·굴절 보정이 기본 적용됩니다(끌 수 있음).
- 상대 경사 비용(구 "Conolly & Lake")의 기준 경사 기본값이 1°에서 5°로 바뀌었습니다.
- **QGIS 4(Qt6/PyQt6) 대비**: `qgisMaximumVersion`을 4.99로 올렸습니다. PyQt6가 없앤 표기(스코프 없는 열거형, `QVariant.Type`, `exec_()`)와 QGIS 4가 지운 3.x 열거형(`QgsWkbTypes.PointGeometry`, `QgsMapLayerProxyModel.Filter`, `QgsRasterBandStats.Stats`, `QgsUnitTypes.Distance*` 등)을 소스 전체에서 양쪽에 통하는 표기로 바꿨고, 버전에 따라 이름이 다른 몇 가지는 `tools/qtcompat.py`가 실행 중인 QGIS를 조사해 고릅니다. QGIS 3.34에서는 결과가 수치까지 같고(회귀 27건), PyQt6 6.11에서 소스가 쓰는 모든 Qt 이름의 존재를 확인했습니다. **QGIS 4 빌드에서 실제로 실행해 보지는 못했습니다**(`docs/PUBLISHING.md` 6절).
- 플러그인 저장소 업로드용 ZIP 빌드(`scripts/build_plugin_zip.py --check`), 태그 푸시 시 ZIP을 첨부하는 릴리스 워크플로, 업로드 절차 문서(`docs/PUBLISHING.md`).
- 원본 1024 px 아이콘은 `docs/art/`에 보존합니다.

### 결과가 달라지는 수정
- 지형 분석: 사용자 반경 TPI의 창을 (2r+1)셀로 교정. 작은 DEM에서는 3x3으로 대체하고 알림.
- DEM 생성: 2D 등고선에 표고 필드가 없으면 실행 거부(이전에는 전부 NoData인 DEM을 "완료"로 보고). 격자를 픽셀 정수배로 스냅. Kriging (Lite)가 측점에서 입력값을 정확히 재현.
- 지구화학도: 범례 색과 먼 픽셀은 NoData(허용오차 RGB 48). 구역 통계를 픽셀 중심 규칙으로 변경하고 `zone_area`, `fill_pct`, `burn_rule`, `area_unit` 필드 추가. 최댓값 보정은 AOI 마스크 안에서 계산.
- 지질도 ZIP: 코드표를 도엽 전체 정렬 순으로 통일. 셀 초기값 NoData. CSV에 BOM, `cell_count`, `labels_all`.
- 근접 네트워크: 좌표가 같은 유적이 간선을 공유(이전에는 고립 노드).
- 가시성 네트워크: DEM NoData 샘플은 "검사 불가"(`fail_deg`)이지 "안 보임"이 아님. `betw_norm` 추가.
- 트렌치 제안: `rank`는 점수순, `pick_order`는 배치 순서. 발자국 최대 경사 검사와 `slope_max_deg`. 매장 유형 어휘 14종과 총/릉 규칙. xlsx 범례. 참고 유적 거리를 반경 안에서 정확히 측정.
- 거리 래스터: 선·면을 닿는 셀 모두에 굽기(`EXTRA=-at`). 대상 셀이 없거나 비정사각 픽셀이면 거부.
- 정렬/내보내기: 사면방향을 최근접으로 리샘플링. 메타데이터 없는 래스터는 `categorical=unknown`. 변수 키의 대소문자 충돌 방지. 사용자 지정 CRS를 `SOURCE_CRS`로 전달. 유효 픽셀 0이면 실패, `valid_pct` 기록.
- AHP: 계층 모드에서 전역가중치를 실제로 사용하고 `weights_source` 기록. 표를 손으로 고치면 계층 모드 해제.
- AI 조사요약: 참고 유적을 전수 분류한 뒤 최근접 선택. 잘린 Gemini 응답 표시. 스캔·표본·레이어 상한을 컨텍스트·CSV·프롬프트에 기록. 길이·면적을 m/m²로 변환.

### 정직성
- 인용 73건을 Crossref·Math-Net.Ru·law.go.kr로 검증. 존재하지 않는 문헌 0건, 오귀속 9건 정정(한국표준 경사 구분은 국토지리정보원이 아니라 산림청 예규, Higuchi 1975/1983 판본 분리, TPI 지수 출처는 Weiss 2001 등).
- REFERENCES.md를 (A) 호출 알고리즘 / (B) 직접 구현 / (C) 맥락 참고로 재구성. Wheatley 1995, Malczewski 2004, O'Brien 2007 추가(검증됨).
- 플러그인이 정한 등급 구간은 "플러그인 정의"로 표기.

### 검증
- QGIS 의존 테스트를 포함한 350건이 실제 QGIS 3.34에서 통과. CI에 QGIS 컨테이너 작업 추가.
- `tests/test_qt6_compat.py`: QGIS 3 전용 표기 금지(항상), PyQt5에서 스코프 없는 열거형 0건, PyQt6에서 소스가 쓰는 Qt 이름 전부 존재(CI static-checks가 PyQt6를 설치해 실행).
- `tests/regression/`: 수정 전후 비교 하네스(27개 시나리오). 비교 과정에서 결함 2건 발견·수정.

## 0.1.3

- 보안 스캔 대응: 삼킨 예외 472건 전부 `[swallowed]` 로그 기록, 로깅 싱크 재귀 방지, 회귀 테스트.
- 전체 코드 리뷰 후 수정: 도움말 크래시, AHP 채점 모드·NoData 전파·격자 검증, 트렌치 커버리지 우선 배치, 등고선 NoData, Pandolf 하강 클램프, 네트워크 closeness 보정(Wasserman-Faust), 가시권 샘플링·곡률·굴절, 지형 분석 메모리·CRS 가드, 정렬/내보내기 원자적 게시와 범주형 보호, 거리 래스터 도구 신설, TRI 반경, Weiss 분류의 TPI 반경 반영, 비용 분석 메모리 예산, AHP 가이드 문서.

## 0.1.2

- 긴 텍스트 스크롤 팝업, flake8 정리.

## 0.1.1

- UI 언어 설정, 공용 대화상자 크롬, i18n 회귀 수정, 지질 QML 파싱 안전화.

## 0.1.0

- 첫 공개 베타: 지형, 가시권, 비용, 네트워크, 지질, 지구화학, 지적 중첩, 스타일링, AOI 보고.
