# 회귀 비교 하네스 (before/after regression harness)

QGIS를 화면 없이(headless) 띄워 19개 도구 대화상자를 실제로 실행하고, 합성 데이터에 대한
결과 수치를 지문(fingerprint)으로 저장한 뒤 두 체크아웃을 비교합니다. 2026-09 감사 라운드에서
"수정 전(d1ecf88) vs 수정 후" 비교에 쓴 코드 그대로이며, 결과는 `docs/REGRESSION_REPORT.md`에 있습니다.

## 요구 사항

- QGIS 3.34 이상과 그 Python 바인딩. Ubuntu 24.04: `apt-get install qgis python3-qgis qgis-providers`
- 반드시 QGIS 바인딩이 빌드된 파이썬으로 실행 (Ubuntu 24.04는 `/usr/bin/python3.12`).
- 화면 없이: `QT_QPA_PLATFORM=offscreen`.
- `/usr/bin/gdal_calc.py` 등의 shebang이 osgeo 없는 파이썬을 가리키는 배포판이 있어, 러너가
  임시 디렉터리에 래퍼를 만들어 PATH 앞에 붙입니다(`qgis_env.ensure_gdal_shims`).

## 실행

```bash
H=tests/regression
# 현재 체크아웃
cd /path/to/archtoolkit
QT_QPA_PLATFORM=offscreen /usr/bin/python3.12 $H/run_scenarios.py . /tmp/new.json
# 비교 대상 체크아웃 (예: git worktree add /tmp/old <commit>)
cd /tmp/old
QT_QPA_PLATFORM=offscreen /usr/bin/python3.12 /path/to/archtoolkit/$H/run_scenarios.py . /tmp/old.json
# 차이
/usr/bin/python3.12 /path/to/archtoolkit/$H/diff_runs.py /tmp/old.json /tmp/new.json
```

시나리오 이름을 인자로 주면 일부만 실행합니다(예: `terrain_basic ahp_hierarchy`).
러너는 `ARCHTOOLKIT_NO_DIALOG_MEMORY=1`을 설정해 대화상자의 설정 기억이 결과에 끼어들지 않게 합니다.

## 구성

- `qgis_env.py`: QgsApplication 부트스트랩, 가짜 iface, 합성 DEM/점/폴리곤 생성, 지문 함수.
- `run_scenarios.py`: `scenarios_*.py`의 `scenario_<이름>(ctx)`를 모두 실행해 JSON으로 저장.
- `diff_runs.py`: 두 JSON을 시나리오별로 비교(수치는 상대오차 1e-6).
- `scenarios_a.py`: 지형 분석, 가시권(히구치 포함), 비용표면/LCP, 최소비용 네트워크, 등고선, 단면, 스타일.
- `scenarios_b.py`: 근접/가시성 네트워크, DEM 생성(TIN/IDW/크리깅), 지질도 래스터, 지구화학도, 거리 래스터, 정렬/내보내기.
- `scenarios_c.py`: AHP(평면/계층), 트렌치 제안, 지적 중첩, 상관/VIF, AI 요약(로컬 경로만).

새 기능을 넣으면 해당 `scenarios_*.py`에 시나리오를 추가하고, 변경 전 커밋과 비교해 달라진 수치가
전부 의도한 것인지 확인하십시오. 단위 테스트(`python -m unittest discover -s tests`)는 이 폴더를
자동 수집하지 않습니다(파일명이 `test_*.py`가 아님).
