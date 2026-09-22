# QGIS 플러그인 저장소에 올리기

`plugins.qgis.org`에 ArchToolkit을 등록·갱신하는 절차입니다. 한 번 등록하면 QGIS의 플러그인 관리자에서 누구나 검색해 설치할 수 있습니다.

## 0. 준비물

- **OSGeo ID** (https://www.osgeo.org/community/getting-started-osgeo/osgeo_userid/). 플러그인 저장소 로그인에 씁니다.
- 로컬에 Python 3.11 이상. QGIS는 필요 없습니다(ZIP 빌드와 검사는 표준 라이브러리만 씁니다).

## 1. 버전 올리고 검사

`metadata.txt`의 `version`, README 배지, `CITATION.cff`의 `version`이 같아야 합니다. `CHANGELOG.md`와 `metadata.txt`의 `changelog`에 새 버전 항목을 적습니다.

```bash
python scripts/check_release_identity.py      # 버전 삼중 일치, 배지, BibTeX
python -m unittest discover -s tests -p "test_*.py"
python tests/check_static.py
```

## 2. ZIP 만들기

```bash
python scripts/build_plugin_zip.py --check
# -> dist/ArchToolkit-<version>.zip  (약 1.7 MB, 최상위 폴더 ArchToolkit/: 코드, icons/, 문서 몇 개)
```

`--check`는 저장소가 거부하는 조건을 미리 봅니다(공식 메타데이터 표 기준): 최상위 폴더 하나, `metadata.txt`·`__init__.py`(`classFactory`) 존재, 필수 메타데이터 키, 아이콘 경로, `__pycache__`·`.pyc`·`.git` 없음, 용량.

저장소의 보안 스캔(Bandit)이 맨 `except: pass`를 찾으면 업로드가 거부됩니다. `tests/test_ui_assets.py`가 이를 미리 막습니다.

## 3. 업로드

1. https://plugins.qgis.org 에 OSGeo ID로 로그인합니다.
2. 처음이면 **Plugins → Upload a plugin**, 갱신이면 플러그인 페이지의 **Manage → Add version**.
3. `dist/ArchToolkit-<version>.zip`을 올립니다. 이름·설명·태그·아이콘·홈페이지·트래커·저장소 주소는 `metadata.txt`에서 자동으로 읽힙니다.
4. 첫 등록은 관리자 승인 후 공개됩니다(보통 며칠). 이후 버전은 바로 공개됩니다.
5. `experimental=False`이므로 기본 목록에 보입니다. 시험판으로 내려면 `experimental=True`로 올리십시오.

## 4. GitHub 릴리스 (선택)

`v0.1.4`처럼 태그를 푸시하면 `.github/workflows/release.yml`이 같은 ZIP을 만들어 검사하고 GitHub 릴리스에 첨부합니다.

```bash
git tag -a v0.1.4 -m "ArchToolkit 0.1.4"
git push origin v0.1.4
```

태그 이름은 `metadata.txt`의 버전과 같아야 합니다(`check_release_identity.py --release-tag`가 확인).

## 5. metadata.txt 요점

| 키 | 값 | 비고 |
| --- | --- | --- |
| `qgisMinimumVersion` | 3.40 | LTR 기준 |
| `qgisMaximumVersion` | 4.99 | QGIS 4(Qt6/PyQt6) 목록에 포함되는 조건. 아래 "QGIS 4 호환" 참조 |
| `icon` | icons/archtoolkit.png | 저장소 목록 아이콘 |
| `experimental` / `deprecated` | False / False | |
| `changelog` | 버전별 요약 | 플러그인 관리자에 그대로 표시됨 |

## 6. QGIS 4 호환: 무엇을 확인했고 무엇은 못 했나

플러그인 저장소는 `qgisMaximumVersion`만 보고 QGIS 4 목록(`plugins.xml?qgis=4.0`)에 올립니다. 공식 메타데이터 표에 Qt6 전용 키는 없습니다(`supportsQt6` 같은 키는 QGIS 설치기·저장소 검증기·문서 어디에도 없어 쓰지 않습니다). 그래서 4.99를 적는 책임은 코드가 집니다.

QGIS 4는 PyQt6 위에서 돌고, PyQt6는 스코프 없는 열거형(`Qt.AlignCenter` 식)과 `QVariant.Type`, `exec_()`를 없앴으며, QGIS 4는 `QgsWkbTypes.PointGeometry`·`QgsMapLayerProxyModel.Filter`·`QgsRasterBandStats.Stats`·`QgsUnitTypes.Distance*` 같은 3.x 열거형을 `Qgis` 네임스페이스로 옮기고 옛 이름을 지웠습니다. 0.1.4는 소스 전체를 양쪽에서 통하는 표기로 바꿨고, 버전에 따라 이름이 다른 몇 가지는 `tools/qtcompat.py`가 실행 중인 QGIS를 조사해 고릅니다.

확인한 것:

- QGIS 3.34(PyQt5)에서 단위 테스트 350개, 대화상자 19개 생성, 회귀 시나리오 27개가 이관 전과 수치까지 같음.
- PyQt6 6.11(QGIS 없이)에서 소스가 쓰는 모든 Qt 이름이 실제로 존재함(`tests/test_qt6_compat.py`, CI의 static-checks 작업이 PyQt6를 설치해 돌립니다).
- QGIS 4.3(master) 헤더와 PyQt6 자동 추가 파일에서, 소스가 쓰는 `Qgis.*` 이름이 모두 존재함.

확인하지 못한 것:

- **QGIS 4 실제 실행.** 이 저장소의 CI와 개발 환경에는 QGIS 4 빌드가 없습니다. QGIS 4에서 처음 실행해 보는 분은 문제를 GitHub Issues로 알려 주십시오. 문제가 나오면 `qgisMaximumVersion`을 내리는 것이 정직한 대응입니다.

## 7. 올린 뒤

- 플러그인 페이지의 다운로드 수·평점·이슈 링크를 확인합니다.
- 사용자 제보는 GitHub Issues(`tracker`)로 옵니다.
