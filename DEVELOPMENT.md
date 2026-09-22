# ArchToolkit 개발 철학

## 핵심 원칙: 외부 의존성 없는 순수 QGIS 플러그인

ArchToolkit은 **기본 QGIS 설치만으로 완전히 동작**해야 합니다.

### 사용 가능한 도구
- **GDAL 알고리즘** (`gdal:slope`, `gdal:aspect`, `gdal:rastercalculator` 등)
- **QGIS Native 알고리즘** (`native:mergevectorlayers`, `native:buffer` 등)
- **PyQt/Qt 기본 라이브러리**
- **Python 표준 라이브러리** (os, tempfile, json 등)
- **QGIS Core/GUI 라이브러리**

### 사용 금지
- (금지) GRASS GIS 알고리즘 (`grass7:*`)
- (금지) SAGA GIS 알고리즘 (`saga:*`)
- (금지) WhiteboxTools
- (금지) 별도 설치가 필요한 외부 Python 패키지 (예: pandas, matplotlib 등)
- 단, QGIS 배포판에 기본 포함된 패키지(예: numpy)는 허용(추가 설치 불필요) — 사용 시 README/metadata에 의존성 명시
- (금지) 별도 설치가 필요한 모든 의존성

### 복잡한 분석 구현 방법
외부 도구가 필요한 기능은 다음 방법으로 대체:

1. **래스터 계산기 활용** (`gdal:rastercalculator`)
   - 수식 조합으로 복잡한 래스터 연산 구현
   
2. **리샘플링 트릭** (`gdal:warpreproject`)
   - 다운샘플링 + 업샘플링으로 focal 연산 근사
   
3. **벡터-래스터 변환 활용**
   - 래스터화, 벡터화를 조합한 분석

4. **반복 처리**
   - Python 루프로 단순 연산을 반복 적용

### 목표
> "QGIS만 설치하면 누구나 ArchToolkit을 바로 사용할 수 있어야 한다"

---

## 테스트 가능한 순수 코어 (QGIS 비의존)

분석의 **수치 알고리즘**은 QGIS/PyQt를 import하지 않는 순수 Python 모듈에 두고,
대화상자는 UI·레이어·래스터 입출력만 담당합니다. 이렇게 분리하면 위험한 수식과
파일 규칙을 **QGIS 런타임 없이 일반 Python에서 회귀 테스트**할 수 있습니다.

| 모듈 (`tools/`) | 담당 | 테스트 |
| --- | --- | --- |
| `atomic_output.py` | 원자적 출력 게시·staging 정리(부분 산출 숨김) | `tests/test_atomic_output.py` |
| `raster_io.py` | 단일 밴드 GeoTIFF 저장(실패 시 부분 파일 삭제) | `tests/test_raster_io.py` |
| `gdal_outcome.py` | GDAL 성공 마커 판정 | `tests/test_gdal_outcome.py` |
| `raster_grid_contract.py` | canonical 목표 격자·격자 검증 | `tests/test_raster_grid_contract.py` |
| `predictor_naming.py` | 내보내기 변수명(ASCII 왕복 안정성·중복 해소) | `tests/test_predictor_naming.py` |
| `raster_semantics.py` | 범주형/연속형 판정·범주형 NoData 센티넬 선택 | `tests/test_categorical_meta.py` |
| `ahp_core.py` | AHP 가중치(고유벡터)·Saaty 일관성비·계층 종합·기준 점수식(benefit/cost/target/range/reclass) | `tests/test_ahp_core.py` |
| `cost_models.py` | 이동비용 모델(Tobler·Naismith·Pandolf 등)·등시선 레벨 | `tests/test_cost_models.py` |
| `cost_budget.py` | 누적비용 분석 규모 판정(가용 메모리 기반 셀 예산·소요 추정·권장 픽셀크기) | `tests/test_cost_budget.py` |
| `network_metrics.py` | Wasserman–Faust 근접·Brandes 매개 중심성(가중/비가중) | `tests/test_network_metrics.py` |
| `terrain_math.py` | Zevenbergen & Thorne 곡률 | `tests/test_terrain_math.py` |
| `geochem_legend.py` | 색상 범례 → 정량값 역변환(RGB 최근접 세그먼트 투영) | `tests/test_geochem_legend.py` |
| `scripts/check_release_identity.py` | 버전·배지·인용·태그 정합성 | `tests/test_release_identity.py` |

### 실행

```bash
# QGIS 없이: 순수 코어 테스트 전체(QGIS 의존 테스트는 자동 스킵) + 정적 검사
python -m unittest discover -s tests -p "test_*.py"
python tests/check_static.py

# QGIS Python으로: QGIS 의존 테스트까지 전부 (Ubuntu 24.04 기준 /usr/bin/python3, 화면 없이)
QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m unittest discover -s tests -p "test_*.py"

# 릴리스 정합성(버전 배지·CITATION·태그), flake8 차단 규칙
python scripts/check_release_identity.py
flake8 --select=E9,F63,F7,F82 .
```

CI(`.github/workflows/ci.yml`)는 push마다 위 순수 테스트·정적 검사·flake8 차단 규칙·릴리스 정합성을 돌리고,
`qgis/qgis` 컨테이너에서 QGIS 의존 테스트를 실행합니다. 새 테스트 파일은 `tests/test_*.py`로 두면 자동 수집됩니다.

### 수정 전후 회귀 비교

동작을 바꾸는 수정을 했다면 `tests/regression/`의 하네스로 이전 커밋과 결과를 비교하십시오
(실제 QGIS를 화면 없이 띄워 19개 도구를 합성 데이터로 실행, 시나리오 27개, 체크아웃당 약 20초).
사용법은 `tests/regression/README.md`, 2026-09 라운드의 결과는 `docs/REGRESSION_REPORT.md`에 있습니다.
달라진 수치가 전부 의도한 것인지 설명할 수 있어야 합니다.

### 게이트 (테스트가 강제하는 규칙)

| 규칙 | 검사 |
| --- | --- |
| `tools/*.py`, `*.ui`, README에 이모지 금지 | `tests/test_ui_assets.py` |
| 맨 `except: pass` / `except: continue` 금지 (log_swallowed 사용) | `tests/test_ui_assets.py` |
| 버전 삼중(metadata.txt · README 배지 · CITATION.cff) 일치 | `tests/test_release_identity.py` |
| 도움말의 학술 근거 노트가 REFERENCES.md와 일치 | `tests/test_scholar_notes.py` |
| 상대 import·구문 오류 없음 | `tests/check_static.py` |

### 기여 규칙
- 예외를 삼키고 계속 진행할 때는 `except Exception as _exc: log_swallowed("module.func", _exc)`를 쓰세요. **맨 `pass`와 `continue`는 금지입니다** — QGIS 플러그인 디렉터리의 Bandit 보안 스캔(B110/B112)이 맨 형태를 발견하면 플러그인 자체를 차단하고, 계산·레이어·파일 작업이 조용히 실패하면 틀린 결과가 보고서까지 흔적 없이 흘러갑니다. `[swallowed]` 접두어로 로그에서 걸러볼 수 있어야 합니다. 순수 모듈(`qgis` import 없음)은 `tools/swallow_log.py`를, 그 외는 `tools/utils.py`의 `log_swallowed`를 쓰세요. 로깅 싱크(`utils._write_log_line`·`_queue_ui_log`·`log_swallowed`)의 예외 처리는 `return` 터미널로 두어 재귀를 막습니다. `tests/test_ui_assets.py`가 이 규칙을 회귀 검사합니다.
- 같은 헬퍼를 두 모듈에 복사하지 마세요. 본문이 같아도 한쪽만 고쳐지는 순간 버그가 됩니다(`is_categorical_raster_meta`가 그렇게 몇 년을 틀려 있었습니다). `utils.py`/`raster_io.py`에 두고 import하세요.
- 새 수치 로직은 **먼저 QGIS 비의존 함수로** 작성하고 단위 테스트를 추가한 뒤,
  대화상자에서 호출하세요(가능하면 별칭 import로 호출부를 유지).
- 새 테스트 파일은 `tests/test_*.py`로 두면 CI가 자동 수집합니다. QGIS가 필요한 테스트는 import 실패 시 `skipTest`로 건너뛰게 작성하세요(`tests/test_align_export_qgis.py` 참고).

---

## 학술적 출처 표시 원칙

ArchToolkit은 **도구 모음집**입니다. 톱과 망치를 정리해 두는 도구상자를 만드는 것이지, 톱과 망치를 발명한 사람이 아닙니다.

### 반드시 지켜야 할 것
- 알고리즘·수식의 원저자를 인용합니다. 서지는 `REFERENCES.md`에 (A) 호출 알고리즘 / (B) 직접 구현 / (C) 맥락 참고로 구분해 적습니다.
- 새 인용은 **Crossref 등 1차 출처로 실재를 확인한 뒤** 추가합니다. 제목·연도·권호를 기억에 의존해 적지 마십시오(2026-09 감사에서 실재 문헌에 저자가 출판하지 않은 주장을 붙인 사례 9건을 정정했습니다).
- 플러그인이 정한 것(등급 구간, 기본값, 휴리스틱)은 **"플러그인 정의"라고 명시**합니다. 저자 이름을 붙이지 마십시오.
- 도구의 도움말은 `tools/scholar_notes.py`의 노트로 끝납니다. 새 도구를 추가하면 노트를 함께 추가하고, 노트의 서지 키는 `REFERENCES.md`에 있어야 합니다(`tests/test_scholar_notes.py`).
- 결과 레이어에는 `set_archtoolkit_layer_metadata`로 실행 파라미터를 기록합니다.
- 입력이 조용히 버려지거나 결과가 비는 경로에는 경고나 로그를 둡니다. 실패를 "완료"로 보고하지 않습니다.

### 왜 중요한가?
1. 연구자의 노력을 존중하고, 사용자가 방법의 근거와 한계를 알 수 있어야 합니다.
2. 같은 방법을 다른 도구로도 재현할 수 있어야 합니다.
3. "지식은 전유물이 아닙니다."

---
*"지식은 전유물이 아닙니다"*
