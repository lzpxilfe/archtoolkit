# ArchToolkit 기여 가이드

"지식은 전유물이 아닙니다"

관심을 가져 주셔서 감사합니다. 버그 제보, 기능 제안, 코드 기여 모두 환영합니다.

## 버그 제보
GitHub Issues에 아래를 적어 주세요.
- 어떤 도구에서 어떤 작업을 하다 발생했는지
- QGIS 로그 패널의 메시지(`[swallowed]` 줄 포함)
- 가능하면 재현할 수 있는 데이터나 화면

## 기능 제안
한국 고고학·문화유산 조사에 도움이 되는 기능, 기존 기능의 개선을 제안해 주세요. 학술 방법을 구현하는 제안이면 원 출처(논문·보고서)를 함께 적어 주시면 좋습니다.

## 코드 기여
1. 저장소를 포크하고 브랜치를 만듭니다(`feature/...`, `bugfix/...`).
2. 수정하고, 아래 검증을 통과시킨 뒤 커밋합니다.
3. 풀 리퀘스트를 보냅니다. 동작이 바뀌는 수정이면 `tests/regression/`으로 이전 커밋과 비교한 결과를 함께 적어 주세요.

### 반드시 지킬 것
- **QGIS 기본 구성만 사용**합니다(Processing·GDAL·NumPy). GRASS·SAGA·외부 패키지는 쓰지 않습니다.
- **출처를 정직하게** 적습니다. 새 인용은 Crossref 등으로 실재를 확인하고 `REFERENCES.md`에 (A)/(B)/(C) 표기로 추가합니다. 플러그인이 정한 값은 "플러그인 정의"라고 씁니다. 자세한 규칙은 [DEVELOPMENT.md](DEVELOPMENT.md).
- **조용한 실패 금지**: 맨 `except: pass`/`continue` 대신 `log_swallowed`를 쓰고, 버려지는 입력은 경고로 알립니다.
- `tools/*.py`와 `.ui`, README에 이모지를 넣지 않습니다.
- 새 수치 로직은 QGIS 비의존 모듈에 두고 단위 테스트를 추가합니다.

### 검증
```bash
python -m unittest discover -s tests -p "test_*.py"
python tests/check_static.py
flake8 --select=E9,F63,F7,F82 .
python scripts/check_release_identity.py
```

## 라이선스
모든 기여물은 프로젝트 라이선스인 **GPL-3.0-or-later**를 따르는 것으로 간주됩니다.
