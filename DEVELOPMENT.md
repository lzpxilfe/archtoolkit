# ArchToolkit 개발 철학

## 핵심 원칙: 외부 의존성 없는 순수 QGIS 플러그인

ArchToolkit은 **기본 QGIS 설치만으로 완전히 동작**해야 합니다.

### 사용 가능한 도구
- ✅ **GDAL 알고리즘** (`gdal:slope`, `gdal:aspect`, `gdal:rastercalculator` 등)
- ✅ **QGIS Native 알고리즘** (`native:mergevectorlayers`, `native:buffer` 등)
- ✅ **PyQt/Qt 기본 라이브러리**
- ✅ **Python 표준 라이브러리** (os, tempfile, json 등)
- ✅ **QGIS Core/GUI 라이브러리**

### 사용 금지
- ❌ GRASS GIS 알고리즘 (`grass7:*`)
- ❌ SAGA GIS 알고리즘 (`saga:*`)
- ❌ WhiteboxTools
- ❌ 별도 설치가 필요한 외부 Python 패키지 (예: pandas, matplotlib 등)
- ✅ 단, QGIS 배포판에 기본 포함된 패키지(예: numpy)는 허용(추가 설치 불필요) — 사용 시 README/metadata에 의존성 명시
- ❌ 별도 설치가 필요한 모든 의존성

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
| `ahp_core.py` | AHP 가중치(고유벡터)·Saaty 일관성비·계층 종합 | `tests/test_ahp_core.py` |
| `cost_models.py` | 이동비용 모델(Tobler·Naismith·Pandolf 등)·등시선 레벨 | `tests/test_cost_models.py` |
| `network_metrics.py` | Wasserman–Faust 근접·Brandes 매개 중심성(가중/비가중) | `tests/test_network_metrics.py` |
| `terrain_math.py` | Zevenbergen & Thorne 곡률 | `tests/test_terrain_math.py` |
| `scripts/check_release_identity.py` | 버전·배지·인용·태그 정합성 | `tests/test_release_identity.py` |

### 실행

```bash
# 개별 스위트
python -m unittest tests.test_ahp_core -v
# numpy가 필요한 스위트(ahp_core, terrain_math)는 numpy만 있으면 됩니다.
# 정적 스모크 검사(상대 import 해석 + 구문)
python tests/check_static.py
```

CI(`.github/workflows/ci.yml`)가 위 스위트 전체와 정적 검사, blocking flake8
(`E9,F63,F7,F82`), 릴리스 정합성을 매 push마다 실행합니다.

### 기여 규칙
- 새 수치 로직은 **먼저 QGIS 비의존 함수로** 작성하고 단위 테스트를 추가한 뒤,
  대화상자에서 호출하세요(가능하면 별칭 import로 호출부를 유지).
- 새 테스트 파일을 만들면 **`ci.yml`의 unittest 목록에 반드시 추가**하세요
  (CI는 자동 검색이 아니라 명시 나열 방식입니다).

---

## 학술적 출처 표시 원칙

ArchToolkit은 **도구 모음집**입니다. 우리는 톱과 망치, 가위를 정리해두는 도구상자를 만드는 것이지, 톱과 망치를 발명한 사람이 아닙니다.

### 반드시 지켜야 할 것
- ✅ 알고리즘 원저자 인용 (예: `Weiss 2001`, `Riley 1999`, `Tobler 1993`)
- ✅ 분류 체계의 출처 명시 (한국표준, 학술 논문 등)
- ✅ UI에 저자명 표시 (체크박스, 레이어 이름 등)
- ✅ 코드 주석에 참고문헌 기재

### 왜 중요한가?
1. **학술적 정당성**: 연구자들의 노력을 존중
2. **신뢰성**: 사용자가 방법론의 근거를 알 수 있음
3. **지식 공유**: "지식은 전유물이 아니다"
4. **재현가능성**: 동일한 방법론을 다른 도구로도 구현 가능

### 예시
```python
# TPI (Topographic Position Index)
# Weiss, A. D. (2001). Topographic Position and Landforms Analysis.
# ESRI International User Conference, San Diego, CA.
```

```
☑ 경사도 분류 - Tobler(1993) 보행속도 기반
```

---
*"지식은 전유물이 아닙니다"*

