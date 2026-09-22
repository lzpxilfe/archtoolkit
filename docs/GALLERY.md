# 화면 모음

헤드리스 QGIS 3.34에서 `scripts/render_screenshots.py`로 렌더링한 실제 대화상자입니다(합성 샘플 프로젝트 사용).

| 도구 | 화면 |
| --- | --- |
| DEM 생성 | ![DEM 생성](images/dem_generator.png) |
| 등고선 추출 | ![등고선 추출](images/contour_extractor.png) |
| 지형 분석 | ![지형 분석](images/terrain_analysis.png) |
| 지형 분석 도움말 (학술 근거와 권장 절차) | ![지형 분석 도움말](images/help_terrain_analysis.png) |
| 경사도/사면방향 도면화 | ![경사도/사면방향 도면화](images/slope_aspect_drafting.png) |
| 가시권 분석 | ![가시권 분석](images/viewshed.png) |
| 비용표면/최소비용경로 | ![비용표면](images/cost_surface.png) |
| 최소비용 네트워크 | ![최소비용 네트워크](images/cost_network.png) |
| 근접/가시성 네트워크 | ![근접/가시성 네트워크](images/spatial_network.png) |
| 근접/가시성 네트워크 도움말 | ![네트워크 도움말](images/help_spatial_network.png) |
| 거리 래스터 | ![거리 래스터](images/distance_raster.png) |
| 분석 결과 정렬/내보내기 | ![정렬/내보내기](images/align_export.png) |
| 변수 상관/VIF 리포트 | ![상관/VIF](images/covariate_report.png) |
| AHP 입지적합도 | ![AHP](images/ahp.png) |
| 트렌치 후보 제안 | ![트렌치 후보 제안](images/trench_suggestion.png) |
| 지질도 도엽 ZIP | ![지질도 ZIP](images/geology_zip.png) |
| 지구화학도 래스터 수치화 | ![지구화학도](images/geochem.png) |
| 지적도 중첩 면적표 | ![지적도 중첩](images/cadastral_overlap.png) |
| 지형 단면 | ![지형 단면](images/terrain_profile.png) |
| 도면 시각화 | ![도면 시각화](images/map_styling.png) |
| AI 조사요약 | ![AI 조사요약](images/ai_report.png) |

다시 만들려면 (QGIS Python 필요):

```bash
QT_QPA_PLATFORM=offscreen /usr/bin/python3 scripts/render_screenshots.py
```
