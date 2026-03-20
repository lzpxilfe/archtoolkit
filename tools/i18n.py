# -*- coding: utf-8 -*-
from __future__ import annotations

import contextlib
import functools
import re

from qgis.PyQt import QtCore, QtWidgets
from qgis.PyQt.QtCore import QSettings


_SETTINGS_KEY = "ArchToolkit/ui_language"
_LANGUAGE_KO = "ko"
_LANGUAGE_EN = "en"
_I18N_ROLE = int(QtCore.Qt.UserRole) + 734
_PROP_PREFIX = "_archtoolkit_i18n_"
_ITEM_TRANSLATION_PROP = f"{_PROP_PREFIX}translate_items"
_HOOKS_INSTALLED = False
_BYPASS_HOOKS = False

_INLINE_REPLACEMENTS = {
    "권장": "recommended",
    "선택사항": "optional",
    "자동": "auto",
    "추천": "recommended",
    "사용자 지정": "custom",
    "미설정": "not set",
}

_EXACT_ENGLISH = {
    "오류": "Error",
    "예": "Yes",
    "아니오": "No",
    "경고": "Warning",
    "주의": "Warning",
    "정보": "Info",
    "안내": "Notice",
    "알림": "Notice",
    "완료": "Done",
    "취소": "Cancelled",
    "성공": "Success",
    "저장 완료": "Saved",
    "처리 중": "Working",
    "분석 시작": "Analysis Started",
    "도움말": "Help",
    "닫기": "Close",
    "실행": "Run",
    "초기화": "Reset",
    "새로고침": "Refresh",
    "다시 불러오기": "Reload",
    "복사": "Copy",
    "이전": "Previous",
    "다음": "Next",
    "지우기": "Clear",
    "찾기…": "Browse…",
    "선택…": "Select…",
    "저장…": "Save…",
    "도면화 실행": "Create Draft Output",
    "등고선 추출 실행": "Extract Contours",
    "분석 실행": "Run Analysis",
    "분석 실행 (Run Analysis)": "Run Analysis",
    "처리 중...": "Processing...",
    "가시권 분석 실행 중...": "Running viewshed analysis...",
    "등고선 생성 중...": "Generating contours...",
    "분석을 시작했습니다. (QGIS 작업 관리자 확인)": "Analysis started. (Check the QGIS task manager.)",
    "레이어 목록 새로고침": "Refresh Layer List",
    "매핑 파일 열기": "Open Mapping File",
    "모두 선택": "Select All",
    "선택 해제": "Clear Selection",
    "선택된 피처만 사용": "Use Selected Features Only",
    "추가": "Add",
    "선택 제거": "Remove Selected",
    "저장 위치…": "Choose Save Location…",
    "폴더 선택…": "Choose Folder…",
    "래스터 변환 실행": "Run Raster Conversion",
    "레이어 선택…": "Select Layers…",
    "API 키 설정/변경…": "Set or Change API Key…",
    "모델 저장": "Save Model",
    "모델 확인": "Check Models",
    "AI 요약 생성": "Generate AI Summary",
    "번들 저장…": "Save Bundle…",
    "통계 CSV…": "Export Statistics CSV…",
    "보이는 것 전체 선택": "Select All Visible",
    "보이는 것 전체 해제": "Clear Visible Selection",
    "질문형 가이드…": "Question Guide…",
    "계층형 설정…": "Hierarchy Settings…",
    "전문가 집계…": "Expert Aggregation…",
    "균등 가중치": "Equal Weights",
    "선호 설정…": "Preference Settings…",
    "통계 계산(min/max)": "Calculate Statistics (min/max)",
    "초기화(모두 1)": "Reset (all = 1)",
    "그룹 목록 갱신": "Refresh Group List",
    "상위그룹 비교…": "Compare Parent Groups…",
    "선택 그룹 비교…": "Compare Selected Group…",
    "전문가 추가": "Add Expert",
    "행 추가": "Add Row",
    "선택 삭제": "Delete Selected",
    "전체범위 1행": "Single Full-Range Row",
    "4등분 예시": "4-Range Example",
    "새 폴리곤": "New Polygon",
    "색상 선택": "Choose Color",
    "점 초기화": "Clear Points",
    "다시 불러오기": "Reload",
    "설명": "Explain",
    "최근 길이": "Recent Length",
    "현재 초기화": "Reset Current",
    "유지": "Keep",
    "관측점 수": "Observer Count",
    "최대 분석거리": "Maximum Analysis Distance",
    "분류 체계": "Classification Scheme",
    "네트워크 모드": "Network Mode",
    "비용 기준": "Cost Basis",
    "이동 모델": "Movement Model",
    "거리": "Distance",
    "샘플 수": "Sample Count",
    "값 필드": "Value Field",
    "픽셀 크기": "Pixel Size",
    "AOI별 분리": "Split by AOI",
    "레이어명": "Layer Name",
    "지표 제목": "Indicator Title",
    "원본 래스터": "Source Raster",
    "AOI 레이어": "AOI Layer",
    "이미지로 저장 (.png)": "Save as Image (.png)",
    "이미지 저장": "Save Image",
    "README.md를 참고하세요.": "See README.md.",
    "저장할 내용이 없습니다.": "There is nothing to save.",
    "현재 모드에서는 API 키가 필요하지 않습니다.": "This mode does not require an API key.",
    "현재 모드에서는 모델 설정이 필요하지 않습니다.": "This mode does not require a model setting.",
    "모델 이름을 입력하세요.": "Enter a model name.",
    "Gemini 모드에서만 모델 확인을 사용할 수 있습니다.": "Model discovery is available only in Gemini mode.",
    "Gemini 모델 ID를 확인할 수 없습니다.": "Could not verify Gemini model IDs.",
    "AOI 요약 컨텍스트를 만들 수 없습니다.": "Could not build the AOI summary context.",
    "Gemini API 키가 필요합니다. 먼저 설정하세요.": "A Gemini API key is required. Configure it first.",
    "조사지역(AOI) 폴리곤 레이어를 선택하세요.": "Select an AOI polygon layer.",
    "대상 그룹을 선택하세요.": "Select a target group.",
    "대상 레이어를 선택하세요.": "Select target layers.",
    "README의 AI 조사요약 섹션을 참고하세요.": "See the AI AOI Report section in README.",
    "AI 조사요약 도움말": "AI AOI Report Help",
    "AOI 주변 레이어 요약 생성 중…": "Generating a summary of layers around the AOI...",
    "로컬 요약 생성 실패: {e}": "Local summary generation failed: {e}",
    "완료 (로컬)": "Done (local)",
    "Gemini 호출 중…(데이터 요약/레이어명만 전송)": "Calling Gemini... (sending summary statistics and layer names only)",
    "Gemini 호출 실패: {api_err}": "Gemini call failed: {api_err}",
    "※ Gemini 호출 실패로 로컬 요약으로 대체했습니다.\n\n": "Gemini failed, so a local summary has been used instead.\n\n",
    "로컬 요약으로 대체 완료": "Fallback to local summary complete",
    "영어 (English)": "English",
    "한국어": "Korean",
    "언어 (Language)": "Language",
    "DEM 생성 (Generate DEM)": "Generate DEM",
    "등고선 추출 (Extract Contours)": "Extract Contours",
    "지적도 중첩 면적표 (Cadastral Overlap)": "Cadastral Overlap",
    "지형 분석 (Terrain Analysis)": "Terrain Analysis",
    "AHP 입지적합도 (AHP Suitability)": "AHP Suitability",
    "지구화학도 래스터 수치화 (GeoChem WMS → Raster)": "GeoChem WMS to Raster",
    "지질도 도엽 ZIP 불러오기/래스터 변환 (KIGAM)": "KIGAM Geology ZIP / Raster",
    "지형 단면 (Terrain Profile)": "Terrain Profile",
    "가시권 분석 (Viewshed Analysis)": "Viewshed Analysis",
    "비용표면/최소비용경로 (Cost Surface / LCP)": "Cost Surface / LCP",
    "최소비용 네트워크 (Least-cost Network)": "Least-cost Network",
    "근접/가시성 네트워크 (PPA / Visibility)": "PPA / Visibility Network",
    "도면 시각화 (Map Styling)": "Map Styling",
    "경사도/사면방향 도면화 (Slope/Aspect Drafting)": "Slope / Aspect Drafting",
    "AI 조사요약 (AOI Report)": "AOI Report",
    "도움말 검색...": "Search help...",
    "ArchToolkit - 최소비용 네트워크 (Least-cost Network)": "ArchToolkit - Least-cost Network",
    "ArchToolkit - 비용표면/최소비용경로 (Cost Surface / LCP)": "ArchToolkit - Cost Surface / LCP",
    "ArchToolkit - 도면화(경사도/사면방향) (Slope/Aspect Drafting)": "ArchToolkit - Slope / Aspect Drafting",
    "ArchToolkit - 가시선": "ArchToolkit - Line of Sight",
    "주곡선": "Index Contour",
    "계곡선": "Valley Contour",
    "간곡선": "Intermediate Contour",
    "조곡선": "Auxiliary Contour",
    "이 도움말은 검색하고 복사할 수 있습니다.": "This help content can be searched and copied.",
    "이 도움말은 검색하고 복사할 수 있습니다. 입력 전에 한 번 훑어보면 실수를 줄일 수 있어요.": "This help content can be searched and copied. A quick scan before you start can help avoid mistakes.",
    "검색어를 입력하면 도움말 안에서 바로 찾을 수 있습니다.": "Type a term to search within this help.",
    "'{text}' 검색 결과로 이동했습니다.": "Moved to a search result for '{text}'.",
    "'{text}' 검색 결과를 찾지 못했습니다.": "No search results were found for '{text}'.",
    "수치지형도 DEM 생성기 (DEM Generator) - ArchToolkit": "DEM Generator - ArchToolkit",
    "등고선 추출 도구 (Contour Extractor) - ArchToolkit": "Contour Extractor - ArchToolkit",
    "고고학 도면 시각화 도구 (Map Styler) - ArchToolkit": "Map Styler - ArchToolkit",
    "지형 단면 프로파일러 (Terrain Profiler) - ArchToolkit": "Terrain Profiler - ArchToolkit",
    "가시권 분석 (Viewshed Analysis) - ArchToolkit": "Viewshed Analysis - ArchToolkit",
    "공간/가시성 네트워크 (PPA / Visibility) - ArchToolkit": "PPA / Visibility Network - ArchToolkit",
    "비용표면/최소비용경로 (Cost Surface / LCP) - ArchToolkit": "Cost Surface / LCP - ArchToolkit",
    "최소비용 네트워크 (Least-cost Network) - ArchToolkit": "Least-cost Network - ArchToolkit",
    "경사도/사면방향 도면화 (Slope & Aspect Drafting) - ArchToolkit": "Slope / Aspect Drafting - ArchToolkit",
    "ArchToolkit: 지형 분석 (커서를 대면 도움말 표시)": "ArchToolkit: Terrain Analysis",
    "지적도 중첩 면적표 (Cadastral Overlap) - ArchToolkit": "Cadastral Overlap - ArchToolkit",
    "AI 조사요약 (AOI Report) - ArchToolkit": "AOI Report - ArchToolkit",
    "ArchToolkit 작업 로그": "ArchToolkit Work Log",
    "대상 레이어 선택 - AI 조사요약": "Select Target Layers - AOI Report",
    "ArchToolkit 로드 오류": "ArchToolkit Load Error",
    "도구를 {operation} 중 오류가 발생했습니다: {error}": "An error occurred while {operation} the tool: {error}",
    "플러그인을 초기화하는 중 오류가 발생했습니다: {error}": "An error occurred while initializing the plugin: {error}",
    "분석 결과": "Analysis Result",
    "기준 수: {count}개": "Number of criteria: {count}",
    "일관성비율(CR): {value}": "Consistency Ratio (CR): {value}",
    "합성 방식: {method}": "Combination method: {method}",
    "겹치는 피처 {count}개": "{count} overlapping features",
    "총 길이 {value} m": "Total length {value} m",
    "총 면적 {value} ㎡": "Total area {value} sqm",
    "{label} 평균 {value}{suffix}": "{label} mean {value}{suffix}",
    "{field} 상위값: {preview}": "Top values for {field}: {preview}",
    "0.5 초과 비율 {value} %": "Ratio above 0.5: {value} %",
    "영어 UI가 적용되었습니다. 이미 열려 있던 창은 일부 다시 열어야 완전히 반영될 수 있습니다.": "English UI has been applied. Some open windows may need to be reopened to update fully.",
    "한국어 UI가 적용되었습니다.": "Korean UI has been applied.",
    "결과 레이어 로드 실패": "Failed to load the result layer.",
    "관측점을 선택해주세요": "Select observer points.",
    "중심점을 선택해주세요": "Select a center point.",
    "대상물 위치를 선택해주세요.": "Select a target location.",
    "관측점과 대상점을 모두 선택해주세요": "Select both observer and target points.",
    "관측점과 대상점을 클릭하여 선택해주세요": "Click to select both the observer and target points.",
    "대상점이 최소 1개 이상 필요합니다": "At least one target point is required.",
    "최소 2개 점이 필요합니다": "At least 2 points are required.",
    "역방향 가시권 분석이 취소되었습니다.": "Reverse viewshed analysis was cancelled.",
    "유효한 가시권 분석 결과를 생성하지 못했습니다. 보간 또는 범위 설정을 확인하세요.": "No valid viewshed result could be generated. Check interpolation or extent settings.",
    "DEM 래스터를 선택해주세요": "Select a DEM raster.",
    "DEM을 선택하세요.": "Select a DEM.",
    "시작점을 먼저 지정하세요.": "Set the start point first.",
    "모델을 선택하세요.": "Select a model.",
    "최소 1개 출력(누적 비용/경로)을 선택하세요.": "Select at least one output (cumulative cost / path).",
    "경로/회랑을 생성하려면 도착점이 필요합니다.": "An end point is required to create a path or corridor.",
    "이미 작업이 실행 중입니다.": "A task is already running.",
    "여는": "opening",
    "1. 수치지형도(DXF) 로드 및 레이어 필터링": "1. Load and Filter Topographic DXF",
    "2. 보간 대상 레이어 확인": "2. Review Input Layers",
    "3. 보간 알고리즘 및 해상도 설정": "3. Interpolation and Resolution",
    "4. 결과 파일 저장": "4. Save Output File",
    "1. DEM 래스터 선택": "1. Select DEM Raster",
    "2. 분석 유형 선택": "2. Choose Analysis Type",
    "3. 경사도 분류 기준": "3. Slope Classification Scheme",
    "1. 지형 데이터 (DEM) 선택": "1. Select Terrain Data (DEM)",
    "3. 관측점(Observer) 설정": "3. Observer Settings",
    "4. 분석 매개변수 (Parameters)": "4. Analysis Parameters",
    "5. 결과 시각화 옵션": "5. Result Styling Options",
    "6. AOI 통계 (선택)": "6. AOI Statistics (Optional)",
    "1. 입력 DEM": "1. Input DEM",
    "2. 비용 모델 및 옵션": "2. Cost Model and Options",
    "3. 시작/도착점 설정": "3. Start / End Points",
    "4. 옵션": "4. Options",
    "1. 네트워크 방식": "1. Network Mode",
    "2. 유적 레이어(Points/Polygons)": "2. Site Layer (Points / Polygons)",
    "3. 네트워크 옵션": "3. Network Options",
    "1. 대상 DEM 선택": "1. Select DEM",
    "2. 단면 추출 도구": "2. Profile Extraction",
    "3. 단면 결과 그래프": "3. Profile Result Graph",
    "1. 스타일을 적용할 원본 레이어 선택": "1. Select Source Layers for Styling",
    "2. 벡터 데이터 스타일링 옵션": "2. Vector Styling Options",
    "3. 배경 지형 (DEM) 시각화": "3. Background Terrain (DEM)",
    "4. 프리셋/내보내기": "4. Presets / Export",
    "1. DXF 등고선 필터링": "1. Filter DXF Contours",
    "2. DEM에서 등고선 생성": "2. Generate Contours from DEM",
    "1. 입력": "1. Input",
    "2. AI 설정": "2. AI Settings",
    "3. 결과": "3. Results",
    "1. 지질도 ZIP 불러오기 (KIGAM 1:50,000)": "1. Load Geology ZIP (KIGAM 1:50,000)",
    "2. 벡터 → 래스터 (MaxEnt/예측모델)": "2. Vector to Raster (MaxEnt / Predictive Modeling)",
    "1. 입력 레이어": "1. Input Layers",
    "2. 기준(환경변수) 선택": "2. Select Criteria (Environmental Variables)",
    "3. AHP 가중치(쌍대비교)": "3. AHP Weights (Pairwise Comparison)",
    "4. 출력": "4. Output",
    "5. 연구용 제약/검증(선택)": "5. Research Constraints / Validation (Optional)",
    "1. 지형 데이터(DEM) 선택": "1. Select Terrain Data (DEM)",
    "3. 처리/보정 옵션": "3. Processing / Correction Options",
    "3. 관측점 설정": "3. Observer Settings",
    "3. 관측점 설정 (다중 선택)": "3. Observer Settings (Multi-Select)",
    "3. 대상물 위치 설정": "3. Target Location Settings",
    "3. 분석 대상(선형/둘레) 설정": "3. Analysis Target (Line / Perimeter)",
    "4. SNA 지표": "4. SNA Metrics",
    "4. 출력 옵션": "4. Output Options",
    "5. 구역 통계(Zonal stats)": "5. Zonal Statistics",
    "6. 중심점(포인트)": "6. Centroid Points",
    "닫기": "Close",
    "모두 선택": "Select All",
    "선택 해제": "Clear Selection",
    "📁 DXF 파일(여러 개 가능) 불러오기...": "📁 Load DXF File(s)...",
    "🔄 레이어 목록 새로고침": "🔄 Refresh Layer List",
    "도면 축척 기준:": "Map Scale:",
    "출력 해상도 (m):": "Output Resolution (m):",
    "(자동)": "(Auto)",
    "(권장: 1.0m)": "(Recommended: 1.0 m)",
    "보간 방법 (Method):": "Interpolation Method:",
    "DEM 저장 위치 선택 (GeoTIFF)": "Choose DEM Output Location (GeoTIFF)",
    "경사도 (Slope) - 지형의 기울기": "Slope",
    "사면방향 (Aspect) - 8방위 45° 간격": "Aspect",
    "TPI (Weiss 2001) - 능선/평지/골짜기 분류": "TPI (Weiss 2001)",
    "지형분류 (Weiss 6단계) - 곡저/평지/사면/능선 ★": "Landform Classification (Weiss, 6 classes)",
    "TRI (Riley 1999) - 지형 험준도": "TRI (Riley 1999)",
    "Roughness (Wilson 2000) - 미세지형": "Roughness (Wilson 2000)",
    "한국표준 - 완/경/급/험/절 5단계": "Korean Standard - 5 Classes",
    "Tobler(1993) - 보행속도": "Tobler (1993) - Walking Speed",
    "Minetti(1995) - 에너지효율": "Minetti (1995) - Energy Efficiency",
    "Llobera(2007) - 인지지형": "Llobera (2007) - Cognitive Terrain",
    "⚙ 고급 설정 ▼": "⚙ Advanced Settings ▼",
    "✅ 자동 표준편차(SD) 적용 (Weiss 2001 권장)": "✅ Apply Automatic Standard Deviation (Weiss 2001 Recommended)",
    "TPI 매개변수 (Weiss 2001)": "TPI Parameters (Weiss 2001)",
    "TRI 매개변수 (Riley 1999)": "TRI Parameters (Riley 1999)",
    "지형분류 매개변수 (Weiss 6단계)": "Landform Parameters (Weiss, 6 classes)",
    "분석 반경:": "Analysis Radius:",
    " 셀": " cells",
    "단일 가시권 (Single Point)": "Single Point",
    "다중 누적 가시권 (Cumulative)": "Cumulative Viewshed",
    "이동 경로 가시권 (Line Path)": "Line Path Viewshed",
    "역방향 가시권 (Reverse Viewshed)": "Reverse Viewshed",
    "가시선 분석 (Line of Sight)": "Line of Sight",
    "지도에서 직접 클릭": "Click on Map",
    "기존 포인트 레이어 사용": "Use Existing Point Layer",
    "선택된 위치: 없음 (지도를 클릭하세요)": "Selected Location: None (click the map)",
    "🖱️ 관측점 지정하기": "🖱️ Set Observer Point",
    "가중치:": "Weight:",
    "(다중 선택에서만 사용)": "(Used only for multi-select)",
    "분석 개요 및 참고문헌": "Analysis Overview and References",
    "관측자 눈높이 (m):": "Observer Height (m):",
    "대상물 높이 (m):": "Target Height (m):",
    "최대 분석 반경 (m):": "Maximum Analysis Radius (m):",
    "대기 굴절 보정 (Refraction Correction)": "Refraction Correction",
    "지구 곡률 보정 (Curvature Correction)": "Curvature Correction",
    "AOI 기준 가시 면적/비율 통계 생성": "Create AOI visibility area / ratio statistics",
    "※ 결과는 ‘AOI_가시통계’ 레이어로 추가됩니다.": "Results will be added as the 'AOI_Visibility_Stats' layer.",
    "입력 DEM": "Input DEM",
    "모델": "Model",
    "모델 변수": "Model Parameters",
    "지도에서 시작/도착점 찍기": "Pick Start / End Points on Map",
    "시작점: (미설정)": "Start Point: (not set)",
    "도착점: (미설정)": "End Point: (not set)",
    "직선거리: -": "Straight-line Distance: -",
    "누적 시간(분) 래스터 생성": "Create Accumulated Time Raster (min)",
    "누적 에너지(kcal) 래스터 생성": "Create Accumulated Energy Raster (kcal)",
    "최소비용경로 라인 생성": "Create Least-cost Path Line",
    "입력 폴리곤 내부 비우기(NoData)": "Clear Inside Input Polygon (NoData)",
    "대각 이동 허용(8방향)": "Allow Diagonal Movement (8 directions)",
    "분석 제한(m, 0=전체 DEM)": "Analysis Limit (m, 0 = whole DEM)",
    "가시(Visible) 색상:": "Visible Color:",
    "비가시(Invisible) 색상:": "Invisible Color:",
    "색상 선택": "Choose Color",
    "왼쪽 클릭 1~2번(시작[필수] → 도착[경로 생성 시]), 우클릭/ESC: 종료": "Left click 1-2 times (start required → end for path), right click / ESC to finish",
    "레이어": "Layer",
    "고정 길이": "Fixed Length",
    "조사대상지(AOI)": "Area of Interest (AOI)",
    "구간 길이": "Segment Length",
    "값 필드(Z):": "Value Field (Z):",
    "Kriging 이웃점 수:": "Kriging Neighbor Count:",
    "자동(추천)": "Auto (recommended)",
    "Z 좌표(3D geometry)": "Z Coordinate (3D geometry)",
    "시기": "Map Era",
    "현행 수치지형도": "Current Topographic Map",
    "구 수치지형도(숫자)": "Legacy Topographic Map (numeric)",
    "프리셋": "Preset",
    "프리셋 선택…": "Select a Preset…",
    "필터:": "Filter:",
    "레이어/그룹 이름으로 검색…": "Search by layer or group name…",
    "후보 레이어를 확인하는 중입니다.": "Checking candidate layers.",
    "후보 {total}개 중 현재 보이는 레이어 {visible}개": "{visible} currently visible layers out of {total} candidates",
    "/ 선택 {checked}개": "/ {checked} selected",
    "/ 아직 선택 없음": "/ none selected yet",
    "자동(현재 설정대로 스캔)": "Auto (scan with current settings)",
    "그룹 지정(레이어 그룹 선택)": "Specific Group (choose a layer group)",
    "레이어 직접 선택": "Pick Layers Manually",
    "새로고침": "Refresh",
    "초기화": "Reset",
    "선택 없음": "Nothing Selected",
    "현재 스캔 범위를 확인하는 중입니다.": "Checking the current scan scope.",
    "무료(로컬 요약)": "Free (Local Summary)",
    "Gemini(API)": "Gemini (API)",
    "(키 상태: 확인 중)": "(Key status: checking)",
    "모드:": "Mode:",
    "키:": "Key:",
    "모델:": "Model:",
    "AI 요약": "AI Summary",
    "무료(로컬 요약) 모드는 외부 API 호출/전송 없이, 프로젝트 통계를 문장으로 정리합니다.": "The Free (Local Summary) mode turns project statistics into sentences without calling or sending data to any external API.",
    "Gemini를 쓸 때는 먼저 '모델 확인'으로 현재 사용 가능한 모델을 갱신하세요.": "When using Gemini, refresh the currently available models with 'Check Models' first.",
    "무료(로컬 요약) 모드는 외부 전송 없이 바로 실행됩니다.": "The Free (Local Summary) mode runs immediately without external transmission.",
    "여기에 AI 보고서가 생성됩니다.": "The AI report will appear here.",
    "보고서 저장": "Save Report",
    "통계 CSV 저장 (layers_summary)": "Save Statistics CSV (layers_summary)",
    "번들 저장 폴더 선택": "Choose a Folder for the Report Bundle",
    "(그룹 선택)": "(Choose Group)",
    "대상 레이어 선택 - AI 조사요약": "Select Target Layers - AOI Report",
}

_EXACT_ENGLISH.update(
    {
        "대상 레이어 선택 - AI 조사요약": "Select Target Layers - AOI Report",
        "AOI 반경 내에서 요약할 레이어를 선택하세요.\n- 벡터/래스터 레이어만 표시됩니다.\n- AOI 레이어는 자동으로 제외됩니다.": "Select layers to summarize within the AOI radius.\n- Only vector and raster layers are shown.\n- AOI layers are excluded automatically.",
        "최근 확인된 공식 Gemini 모델 ID": "Recently Verified Official Gemini Model IDs",
        "저장된/내장 Gemini 모델 ID": "Saved / Built-in Gemini Model IDs",
        "이 목록은 확인일이 오래되어 다시 검증하는 편이 안전합니다.": "This list may be outdated, so re-verifying it is recommended.",
        "현재는 로컬 요약 모드라 Gemini 모델 설정을 사용하지 않습니다.": "Gemini model settings are not used in local summary mode.",
        "조사지역 폴리곤(AOI):": "AOI Polygon:",
        "반경:": "Radius:",
        "ArchToolkit 결과 레이어만 요약(권장)": "Summarize ArchToolkit result layers only (recommended)",
        "도면/Style(카토그래피) 결과 레이어 제외(권장)": "Exclude styling / cartography result layers (recommended)",
        "대상 레이어:": "Target Layers:",
        "대상 그룹:": "Target Group:",
        "불필요 (로컬 요약)": "Not needed (local summary)",
        "설정됨 (AuthManager)": "Configured (AuthManager)",
        "미설정": "Not configured",
    }
)

_EXACT_ENGLISH.update(
    {
        "1 | 매우 낮음": "1 | Very Low",
        "2 | 낮음": "2 | Low",
        "3 | 보통": "3 | Medium",
        "4 | 높음": "4 | High",
        "5 | 매우 높음": "5 | Very High",
        "가중치 일관성을 아직 판단할 수 없습니다. 기준을 추가하고 쌍대비교를 입력하세요.": "Weight consistency cannot be evaluated yet. Add criteria and fill in the pairwise comparison table.",
        "가중치 일관성을 수치로 계산하지 못했습니다. NumPy 또는 입력 상태를 확인하세요.": "Could not calculate weight consistency numerically. Check NumPy availability or the current inputs.",
        "일관성 양호: 현재 쌍대비교는 일반 권장 기준(CR ≤ 0.10) 안에 있습니다.": "Consistency is good: the current pairwise comparison is within the common guideline (CR <= 0.10).",
        "일관성 주의: 몇몇 기준의 상대 중요도를 다시 보면 더 설득력 있는 결과가 됩니다.": "Consistency warning: revisiting the relative importance of some criteria may produce a more convincing result.",
        "일관성 낮음: 현재 비교는 서로 충돌할 가능성이 큽니다. 중요도 판단을 다시 맞춰보세요.": "Consistency is low: the current comparisons may conflict with each other. Revisit the importance judgments.",
        "AHP 질문형 가이드": "AHP Question Guide",
        "기준": "Criterion",
        "중요도": "Importance",
        "모두 보통(3)": "All Medium (3)",
        "앞쪽 기준 높게": "Favor Earlier Criteria",
        "(레이어 없음)": "(no layer)",
        "기준 선호 설정": "Criterion Preference Settings",
        "Benefit(값↑ 좋음)": "Benefit (higher is better)",
        "Cost(값↓ 좋음)": "Cost (lower is better)",
        "점수화 방식:": "Scoring Method:",
        "통계 참고:": "Statistics:",
        "목표값:": "Target Value:",
        "선호 최소:": "Preferred Minimum:",
        "선호 최대:": "Preferred Maximum:",
        "값이 클수록 높은 점수를 부여합니다.": "Higher values receive higher scores.",
        "값이 작을수록 높은 점수를 부여합니다.": "Lower values receive higher scores.",
        "지정한 목표값에서 점수 1을 받고, min/max 쪽으로 갈수록 선형으로 감소합니다.": "Receives a score of 1 at the specified target value and decreases linearly toward min/max.",
        "선호 구간 안에서는 점수 1, 그 밖에서는 min/max 방향으로 선형 감소합니다.": "Receives a score of 1 inside the preferred range and decreases linearly toward min/max outside it.",
        "구간 점수표 설정": "Reclass Score Table Settings",
        "최소": "Minimum",
        "최대": "Maximum",
        "점수(0-1)": "Score (0-1)",
        "구간은 최소값 기준으로 정렬되어 저장됩니다. 구간이 겹치면 실행 시 오류를 내어 조용한 오작동을 막습니다.": "Ranges are saved sorted by minimum value. Overlapping ranges raise an error during execution to prevent silent misbehavior.",
        "쌍대비교": "Pairwise Comparison",
        "계층형 AHP 설정": "Hierarchical AHP Settings",
        "계층형 AHP": "Hierarchical AHP",
        "상위그룹이 2개 이상일 때만 상위그룹 비교가 필요합니다.": "Parent-group comparison is needed only when there are at least 2 parent groups.",
        "먼저 그룹을 하나 선택하세요.": "Select a group first.",
        "선택 그룹의 하위기준이 2개 이상일 때만 내부 비교가 필요합니다.": "Internal comparison is needed only when the selected group has at least 2 subcriteria.",
        "전문가 쌍대비교 집계": "Expert Pairwise Comparison Aggregation",
        "전문가": "Expert",
        "기준군 1": "Criterion Group 1",
        "AHP 입지적합도 (Suitability) - ArchToolkit": "AHP Suitability - ArchToolkit",
        "선호 설정을 바꿀 기준 레이어를 표에서 하나 선택하세요.": "Select one criterion layer in the table to change its preference settings.",
        "기준으로 사용할 래스터 레이어를 선택하세요.": "Select a raster layer to use as a criterion.",
        "이미 추가된 레이어입니다.": "This layer has already been added.",
        "질문형 가이드는 기준이 2개 이상일 때 사용할 수 있습니다.": "The question guide can be used only when there are at least 2 criteria.",
        "계층형 AHP는 기준이 2개 이상일 때 사용할 수 있습니다.": "Hierarchical AHP can be used only when there are at least 2 criteria.",
        "전문가 집계는 기준이 2개 이상일 때 사용할 수 있습니다.": "Expert aggregation can be used only when there are at least 2 criteria.",
        "기준을 추가하면 AHP 가중치와 일관성(CR)을 계산합니다.": "Add criteria to calculate AHP weights and consistency (CR).",
        "CR: - (numpy 없음: 균등 가중치)": "CR: - (NumPy unavailable: equal weights)",
        "NumPy를 사용할 수 없어 AHP 고유벡터 대신 균등 가중치로 처리됩니다.": "NumPy is unavailable, so equal weights are used instead of the AHP eigenvector.",
        "통계(min/max) 계산 완료": "Statistics (min/max) calculated",
        "기준(래스터)을 최소 1개 이상 추가하세요.": "Add at least one criterion raster.",
        "가중치/통계 계산 중…": "Calculating weights and statistics...",
        "첫 번째 기준 레이어를 찾을 수 없습니다.": "Could not find the first criterion layer.",
        "AOI는 폴리곤 레이어여야 합니다.": "The AOI must be a polygon layer.",
        "래스터 정규화/가중합 계산 중…": "Calculating raster normalization / weighted sum...",
        "제약 마스크 적용 중…": "Applying constraint mask...",
        "AHP 검증": "AHP Validation",
        "검증 레이어는 포인트여야 합니다.": "The validation layer must be a point layer.",
        "검증 포인트에서 적합도 값을 읽지 못했습니다.": "Could not read suitability values at the validation points.",
        "결과 레이어를 프로젝트에 추가하지 못했습니다.": "Could not add the result layer to the project.",
    }
)

_EXACT_ENGLISH.update(
    {
        "Style: 도로": "Style: Roads",
        "Style: 하천": "Style: Rivers",
        "Style: 건물": "Style: Buildings",
        "Style: 도면 데이터": "Style: Map Data",
        "Style: 배경 지형": "Style: Background Terrain",
        "원본 레이어 (숨김)": "Source Layers (Hidden)",
        "고속국도": "Expressway",
        "일반국도": "National Highway",
        "지방도": "Provincial Road",
        "시/군도": "City / County Road",
        "면도": "Township Road",
        "소로": "Minor Road",
        "도보/길": "Trail / Footpath",
        "기타도로": "Other Road",
        "하천": "River",
        "수로": "Waterway",
        "소하천": "Small Stream",
        "세천": "Creek",
        "배경 지형": "Background Terrain",
        "Map Styling 도움말": "Map Styling Help",
        "매핑 파일이 없습니다: {path}": "Mapping file not found: {path}",
        "매핑 파일을 읽는 중 오류: {e}": "Error while reading the mapping file: {e}",
        "매핑 파일 형식이 올바르지 않습니다(JSON object 필요).": "The mapping file format is invalid. (A JSON object is required.)",
        "매핑 파일이 없습니다: {path}": "Mapping file not found: {path}",
        "매핑 파일을 여는 중 오류가 발생했습니다.": "An error occurred while opening the mapping file.",
        "기본 매핑으로 대체했습니다: {self._code_config_load_error}": "Fell back to the default mapping: {self._code_config_load_error}",
        "DXF 코드 매핑을 다시 불러왔습니다.": "Reloaded the DXF code mapping.",
        "시각화를 적용할 레이어를 선택해주세요.": "Select layers to apply styling to.",
        "통합 레이어가 생성되었습니다: {', '.join(results)}": "Merged layers created: {', '.join(results)}",
        "선택한 레이어들에서 해당하는 데이터를 찾을 수 없습니다.": "No matching data was found in the selected layers.",
        "경사도_구역(1°) (Slope zones)": "Slope_Zones (1deg)",
        "작업영역(AOI)": "Area of Interest (AOI)",
        "새 폴리곤 레이어를 생성했습니다. 편집 모드에서 폴리곤(1개 이상)을 그린 후 실행해주세요.": "A new polygon layer has been created. Draw one or more polygons in edit mode, then run the tool.",
        "입력 DEM(래스터)을 선택해주세요.": "Select an input DEM (raster).",
        "작업영역(AOI) 폴리곤 레이어를 선택하거나 '새 폴리곤'을 눌러 생성해주세요.": "Select an AOI polygon layer, or click 'New Polygon' to create one.",
        "작업영역은 폴리곤 레이어여야 합니다.": "The AOI must be a polygon layer.",
        "선택된 폴리곤이 없습니다. '선택된 피처만 사용'을 해제하거나 폴리곤을 선택해주세요.": "No polygon is selected. Turn off 'Use selected features only' or select a polygon.",
        "작업영역 폴리곤이 없습니다. 폴리곤을 그리거나 다른 폴리곤 레이어를 선택해주세요.": "No AOI polygon is available. Draw a polygon or choose another polygon layer.",
        "생성할 결과(경사도/사면방향)를 선택해주세요.": "Select at least one result to create (slope / aspect).",
        "경사도/사면방향 도면화 생성 중...": "Creating slope / aspect drafting output...",
        "도면화(경사/사면방향) 도움말": "Slope / Aspect Drafting Help",
        "프리셋 저장 폴더 선택": "Choose a Folder for the Preset",
        "지형 단면 도움말": "Terrain Profile Help",
        "지형 단면": "Terrain Profile",
        "지도에서 시작점과 끝점을 클릭하세요 (2번)": "Click the start and end points on the map (2 clicks).",
        "DEM 레이어가 선택되지 않았거나 점이 부족합니다.": "A DEM layer is not selected, or there are not enough points.",
        "샘플 수는 1 이상이어야 합니다.": "Sample count must be at least 1.",
        "데이터가 없습니다.": "No data.",
        "추가 옵션 (길이/AOI)": "Additional Options (Length / AOI)",
        "같은 길이로 단면선(고정 길이)": "Use Fixed-Length Profiles",
        "최근 길이": "Recent Length",
        "단면 그래프에 조사대상지(AOI) 구간 표시": "Show AOI Segment on the Profile Graph",
        "구간 통계(경사/누적상승) 계산": "Calculate Segment Statistics (Slope / Cumulative Climb)",
        "단면 오버레이 (레이어 표시)": "Profile Overlay (Layer Display)",
        "단면 그래프에 레이어 표시": "Show Layers on the Profile Graph",
        "현재 초기화": "Reset Current View",
        "개별 레이어도 생성": "Also Create Individual Layers",
    }
)

_EXACT_ENGLISH.update(
    {
        "DEM을 GDAL로 열 수 없습니다.": "Could not open the DEM with GDAL.",
        "DEM 픽셀 크기를 확인할 수 없습니다.": "Could not determine the DEM pixel size.",
        "DEM 값을 읽을 수 없습니다.": "Could not read DEM values.",
        "시작/도착점이 DEM 분석 범위를 벗어났습니다.": "The start / end points are outside the DEM analysis extent.",
        "시작점이 NoData 영역에 있습니다.": "The start point is inside a NoData area.",
        "시작/도착점이 NoData 영역에 있습니다.": "The start / end points are inside a NoData area.",
        "추가 마찰(래스터)을 읽을 수 없습니다.": "Could not read the extra friction raster.",
        "추가 마찰(벡터)을 래스터화할 수 없습니다.": "Could not rasterize the extra friction vector.",
        "작업이 취소되었습니다.": "The operation was cancelled.",
        "누적 비용 래스터를 생성할 수 없습니다.": "Could not create the cumulative cost raster.",
        "누적 에너지 래스터를 생성할 수 없습니다.": "Could not create the cumulative energy raster.",
        "도착점까지 경로를 찾지 못했습니다.": "Could not find a path to the destination.",
        "Least-cost corridor 생성 실패": "Failed to create the least-cost corridor.",
        "데이터 없음": "No data",
        "Cost Surface / LCP 도움말": "Cost Surface / LCP Help",
        "토블러 보행함수 (Tobler Hiking Function)": "Tobler Hiking Function",
        "나이스미스 규칙 (Naismith's Rule)": "Naismith's Rule",
        "코놀리&레이크 경사비용 (Conolly & Lake, 2006)": "Conolly & Lake Relative Slope Cost (2006)",
        "판돌프 운반 에너지 (Pandolf load carriage, 1977)": "Pandolf Load Carriage (1977)",
        "왼쪽 클릭 2번(시작→도착), 우클릭/ESC: 종료": "Left click twice (start -> end), right click / ESC: finish",
        "왼쪽 클릭 1번(시작), 우클릭/ESC: 종료": "Left click once (start), right click / ESC: finish",
        "DEM CRS가 미터 단위가 아닙니다. (권장: 투영좌표계/미터)": "The DEM CRS is not in meters. (Recommended: projected CRS / meters)",
        "먼저 DEM을 선택하세요.": "Select a DEM first.",
        "지도에서 시작점을 클릭하세요. (우클릭/ESC 종료)": "Click the start point on the map. (Right click / ESC to finish)",
        "도착점을 클릭하세요. (우클릭/ESC 종료)": "Click the end point on the map. (Right click / ESC to finish)",
        "도착점을 클릭하세요. (또는 우클릭/ESC로 종료)": "Click the end point. (Or right click / ESC to finish)",
        "시작점: (선택)": "Start Point: (selected)",
        "도착점: (선택)": "End Point: (selected)",
        "비용표면/최소비용경로": "Cost Surface / LCP",
        "추가 마찰(래스터) 레이어를 선택하세요.": "Select an extra friction raster layer.",
        "추가 마찰(벡터) 레이어를 선택하세요.": "Select an extra friction vector layer.",
        "추가 마찰(벡터) 레이어 CRS는 DEM CRS와 동일해야 합니다.": "The extra friction vector layer CRS must match the DEM CRS.",
        "프로파일을 위해 DEM 소스를 찾을 수 없습니다.": "Could not find the DEM source for the profile.",
        "최소비용경로 프로파일 (LCP Profile)": "Least-cost Path Profile (LCP Profile)",
        "LCP 마일스톤 (500m)": "LCP Milestones (500 m)",
        "누적 비용(분) (Cumulative Cost, min)": "Cumulative Cost (min)",
        "누적 에너지(kcal) (Cumulative Energy, kcal)": "Cumulative Energy (kcal)",
        "취소됨": "Cancelled",
        "유효한 유적 포인트가 2개 이상 필요합니다.": "At least 2 valid site points are required.",
        "허브가 없습니다. 허브 필드/값을 확인하세요.": "No hubs were found. Check the hub field and value.",
        "후보 간선이 없습니다. 후보 간선(k)을 늘려주세요.": "No candidate edges were found. Increase candidate edges (k).",
        "MST를 구성할 수 없습니다(그래프가 끊겨 있음). 후보 간선(k)를 늘리거나 경로 버퍼(m)를 늘려주세요.": "Could not build the MST (the graph is disconnected). Increase candidate edges (k) or the path buffer (m).",
        "표면상 점 (Point on surface, 권장)": "Point on Surface (recommended)",
        "중심점 (Centroid)": "Centroid",
        "A. 최소 신장 트리 (MST)": "A. Minimum Spanning Tree (MST)",
        "B. k-최근접 네트워크 (k-NN)": "B. k-Nearest Neighbor Network (k-NN)",
        "C. 허브 기반 네트워크 (Hub)": "C. Hub-based Network",
        "A+B+C. 한번에 생성 (All: MST + k-NN + Hub)": "A+B+C. Create All at Once (MST + k-NN + Hub)",
        "시간(분) (Time, min)": "Time (min)",
        "에너지(kcal) (Energy, kcal) - Pandolf만": "Energy (kcal) - Pandolf only",
        "MST 대칭화: 왕복 평균 (Round-trip mean)": "MST Symmetrization: Round-trip Mean",
        "MST 대칭화: 편도 최소 (One-way min)": "MST Symmetrization: One-way Minimum",
        "MST 대칭화: 편도 최대 (One-way max)": "MST Symmetrization: One-way Maximum",
        "해석 가이드": "Interpretation Guide",
        "도구 사용법/주의사항을 봅니다.": "Open usage notes and cautions.",
        "Least-cost Network 도움말": "Least-cost Network Help",
        "SNA 지표 계산(노드 속성 추가)": "Calculate SNA Metrics (Add Node Attributes)",
        "closeness(느림)": "closeness (slow)",
        "betweenness(매우 느림)": "betweenness (very slow)",
        "※ closeness/betweenness는 유적 수가 많으면 자동 생략될 수 있습니다.": "closeness / betweenness may be skipped automatically when there are many sites.",
        "2. 유적 레이어(Points/Polygons)": "2. Site Layer (Points / Polygons)",
        "이름 필드": "Name Field",
        "폴리곤 대표점": "Polygon Representative Point",
        "방식": "Method",
        "후보 간선(k)": "Candidate Edges (k)",
        "유클리드 기준 후보 수(클수록 정확/느림)": "Euclidean Candidate Count (larger = more accurate / slower)",
        "0=DEM 전체(매우 느림), 너무 작으면 경로가 잘릴 수 있음": "0 = whole DEM (very slow); if too small, paths may be cut off",
        "k-NN의 k": "k for k-NN",
        "각 노드에서 비용 기준 상위 k개 연결": "Connect the top k lowest-cost neighbors from each node",
        "허브 필드": "Hub Field",
        "허브 값": "Hub Value",
        "허브들끼리도 MST로 연결": "Connect hubs to each other with an MST",
        "예: 왕성, 산성, 봉수": "Example: royal fortress, mountain fortress, beacon tower",
        "1. 지형 데이터(DEM) 선택": "1. Select Terrain Data (DEM)",
        "2. 비용 모델 및 옵션": "2. Cost Model and Options",
        "2. 유적 레이어(Points / Polygons)": "2. Site Layer (Points / Polygons)",
        "4. 이동 비용 모델": "4. Movement Cost Model",
    }
)

_EXACT_ENGLISH.update(
    {
        "곡률/굴절(대기굴절) 보정 설명 보기": "Show Curvature / Refraction Correction Info",
        "선형 및 둘레 가시권 (Line/Perimeter)": "Line / Perimeter Viewshed",
        "대기 굴절 계수 (Refraction):": "Refraction Coefficient:",
        "Viewshed/LOS 도움말": "Viewshed / LOS Help",
        "k=0이면 굴절 효과 없음": "k = 0 means no refraction effect",
        "곡률+굴절": "Curvature + Refraction",
        "곡률": "Curvature",
        "곡률/굴절(대기굴절) 보정 설명": "Curvature / Refraction Correction Info",
        "선택된 관측점 없음": "No observer selected",
        "분석 개요 및 참고문헌": "Analysis Overview and References",
        "하나의 관측점에서 보이는 영역을 계산합니다.": "Calculates the visible area from a single observer point.",
        "여러 관측점의 가시권을 합산하여 '얼마나 많은 지점에서 보이는지' 계산합니다.": "Combines multiple viewsheds to show how many observer points can see each location.",
        "선형 경로(예: 성곽, 도로)를 따라 이동하며 보이는 영역을 분석합니다.": "Analyzes visibility while moving along a linear path such as a fortress wall or road.",
        "특정 지점을 '바라볼 수 있는' 위치를 찾습니다 (Visual Prominence).": "Finds places from which a specific point can be seen (visual prominence).",
        "두 지점 사이의 시야가 확보되는지 단면을 통해 확인합니다.": "Checks line of sight between two points with a terrain profile.",
        "다중 클릭 시, 이번에 추가하는 관측점에 적용되는 가중치입니다.": "When adding multiple observers, this weight is applied to the point being added.",
        "일반적인 성인 눈높이는 1.6m 내외입니다.": "Typical adult eye height is around 1.6 m.",
        "보려고 하는 대상의 높이입니다 (0 = 지면).": "Height of the target being observed (0 = ground).",
        "바라보는 중심 방향 (0=북쪽)": "Center viewing direction (0 = north)",
        "시야의 폭 (360 = 전방향)": "Field-of-view width (360 = all directions)",
        "장거리 분석 시 둥근 지구의 효과를 고려합니다.": "Accounts for the Earth's curvature in long-distance analysis.",
        "빛이 대기를 통과하며 굴절되는 현상을 보정합니다 (계수 0.13).": "Applies atmospheric refraction correction (coefficient 0.13).",
        "히구치 거리대 (Higuchi View Zones) 표시": "Show Higuchi View Zones",
        "시각적 불균등(상호가시성) 분석 추가": "Add Visual Asymmetry Analysis",
        "샘플링 옵션 (Line/Multi/Reverse-Polygon 모드용)": "Sampling Options (Line / Multi / Reverse Polygon modes)",
        "관측점 샘플링 간격(m):": "Observer Sampling Interval (m):",
        "라인을 따라 관측점을 생성할 간격입니다. 작을수록 정밀하지만 느려집니다.": "Interval used to generate observer points along a line. Smaller values are more precise but slower.",
        "최대 분석 점수:": "Maximum Visibility Score:",
        "누적값을 ‘개수(1~N)’로 표시": "Display cumulative values as counts (1 to N)",
        "가중 누적(Weight) 사용": "Use Weighted Cumulative Viewshed",
        "관측점별 가중치를 합산하여 누적 가시권을 계산합니다. (기본=1.0)": "Calculates cumulative viewshed by summing weights per observer point. (Default = 1.0)",
        "가중치 표준화(0–100%)": "Normalize Weights (0-100%)",
        "AOI 폴리곤:": "AOI Polygon:",
        "선택 피처만": "Selected Features Only",
        "AOI_가시통계": "AOI_Visibility_Stats",
        "🖱️ 추가 관측점 클릭 (선택사항)": "🖱️ Click to Add Observer Points (optional)",
        "💡 성곽(Polygon)이나 도로(Line) 레이어를 선택하세요.": "💡 Select a fortress polygon or road line layer.",
        "🖱️ 지도에서 경로(둘레) 그리기": "🖱️ Draw a Path / Perimeter on the Map",
        "💡 시작점 클릭 후 경로를 그리세요 (시작점 재클릭 시 자동 닫힘).": "💡 Click the start point, then draw the path. Click the start again to close automatically.",
        "🖱️ 지도에서 관측점 선택": "🖱️ Select an Observer on the Map",
        "💡 레이어 선택 시: 피처의 중심점(Centroid)에서 가시권을 계산합니다.": "💡 When using a layer, viewshed is calculated from each feature centroid.",
        "🖱️ 추가 관측점 클릭": "🖱️ Click to Add Observer Points",
        "💡 레이어의 포인트 + 지도 클릭을 함께 사용할 수 있습니다.": "💡 You can combine layer points with manual map clicks.",
        "🖱️ 관측점 → 대상점 순서로 클릭": "🖱️ Click Observer -> Target",
        "🖱️ 지도에서 대상물/영역 지정": "🖱️ Set the Target / Area on the Map",
        "🖱️ 지도에서 위치 선택": "🖱️ Select a Location on the Map",
        "레이어에서 선택": "Select from Layer",
        "소스: 선택된 선형/둘레 레이어": "Source: selected line / perimeter layer",
        "소스: 선택된 레이어": "Source: selected layer",
        "그려진 경로: 없음 (지도를 클릭하세요)": "Drawn Path: None (click on the map)",
        "공간/가시성 네트워크 (PPA / Visibility) - ArchToolkit": "PPA / Visibility Network - ArchToolkit",
        "PPA(Proximal Point Analysis)": "PPA (Proximal Point Analysis)",
        "가시성 네트워크(Visibility / LOS)": "Visibility Network (LOS)",
        "Mutual(상호 보임)만 연결": "Mutual Visibility Only",
        "Either(단방향 포함)": "Either Direction (one-way allowed)",
        "노드 지표 레이어(점) 생성": "Create Node Metrics Layer (Points)",
        "Closeness 계산": "Calculate Closeness",
        "Betweenness 계산": "Calculate Betweenness",
        "LOS 연결 규칙": "LOS Connection Rule",
        "Spatial / Visibility Network 도움말": "Spatial / Visibility Network Help",
        "Point on surface (권장)": "Point on Surface (recommended)",
        "(FID 사용)": "(use FID)",
        "k-NN (직선거리)": "k-NN (Euclidean distance)",
        "Distance threshold (반경)": "Distance Threshold (radius)",
        "Delaunay (삼각망)": "Delaunay (triangulation)",
        "상호 보임만 (Mutual)": "Mutual Visibility Only",
        "단방향 포함 (Either direction)": "Either Direction Included",
    }
)

_EXACT_ENGLISH.update(
    {
        "KIGAM ZIP에 'sym' 폴더가 없습니다. 심볼 적용은 건너뜁니다.": "The KIGAM ZIP does not contain a 'sym' folder. Symbol styling will be skipped.",
        "지질도 도엽 ZIP 불러오기 / MaxEnt 래스터 변환 - ArchToolkit": "KIGAM Geology ZIP Loader / MaxEnt Raster Conversion - ArchToolkit",
        "ZIP 파일을 선택하거나 경로를 입력하세요…": "Select a ZIP file or enter its path...",
        "찾기…": "Browse...",
        "ZIP 파일:": "ZIP File:",
        "라벨 글꼴:": "Label Font:",
        "라벨 크기:": "Label Size:",
        "표준 심볼(sym 폴더) 적용": "Apply Standard Symbols (sym folder)",
        "지층 코드 라벨 적용": "Apply Formation Code Labels",
        "ZIP 불러오기": "Load ZIP",
        "2. 벡터 → 래스터 (MaxEnt/예측모델)": "2. Vector to Raster (MaxEnt / Predictive Modeling)",
        "변환할 벡터 레이어를 선택하세요:": "Select vector layers to convert:",
        "KIGAM ZIP 레이어만": "KIGAM ZIP Layers Only",
        "ArchToolkit의 KIGAM ZIP 로더로 불러온 레이어만 목록에 표시합니다.": "Show only layers loaded by the ArchToolkit KIGAM ZIP loader.",
        "Litho(폴리곤)만": "Litho (polygon) only",
        "보통 예측모델링에는 Litho(암상/지층) 폴리곤만 있으면 충분합니다.": "For predictive modeling, Litho (rock / formation) polygons are usually sufficient.",
        "값 필드:": "Value Field:",
        "해상도(픽셀 크기):": "Resolution (pixel size):",
        "NoData 값:": "NoData Value:",
        "선택 레이어 병합 후 단일 래스터": "Merge Selected Layers into a Single Raster",
        "레이어별 래스터 출력": "Export One Raster per Layer",
        "저장 위치…": "Choose Save Location...",
        "출력 파일(단일 모드):": "Output File (single mode):",
        "폴더 선택…": "Choose Folder...",
        "출력 폴더(레이어별 모드):": "Output Folder (per-layer mode):",
        "출력 형식:": "Output Format:",
        "KIGAM ZIP 파일 선택": "Select KIGAM ZIP File",
        "래스터 저장": "Save Raster",
        "출력 폴더 선택": "Select Output Folder",
        "포인트 레이어": "Point Layer",
        "라인 레이어": "Line Layer",
        "폴리곤 레이어": "Polygon Layer",
        "(자동 선택)": "(Auto Select)",
        "선택된 벡터 레이어가 없습니다.": "No vector layers are selected.",
        "공통 필드를 찾을 수 없습니다. 필드를 직접 선택하세요.": "Could not find a common field. Select a field manually.",
        "출력 파일을 지정하세요.": "Specify an output file.",
        "래스터 생성: {raster_path}": "Raster created: {raster_path}",
        "출력 폴더를 지정하세요.": "Specify an output folder.",
        "레이어별 래스터 변환이 완료되었습니다.": "Per-layer raster conversion is complete.",
        "래스터 변환 실패: {e}": "Raster conversion failed: {e}",
        "ZIP 파일을 선택해주세요.": "Select a ZIP file.",
        "선택한 ZIP 파일이 존재하지 않습니다.": "The selected ZIP file does not exist.",
        "로드된 레이어가 없습니다. 로그를 확인하세요.": "No layers were loaded. Check the log.",
        "지구화학도 래스터 수치화 (GeoChem WMS → Raster) - ArchToolkit": "GeoChem WMS to Raster - ArchToolkit",
        "불러오기": "Load",
        "가중 평균 중심(질량중심)": "Weighted Mean Center (center of mass)",
        "무가중 평균 중심(선택 픽셀 중심)": "Unweighted Mean Center (selected pixel center)",
        "최대값 픽셀(peak)": "Peak Pixel",
        "값 그대로 (w = value)": "As Is (w = value)",
        "값 거듭제곱 (w = value^p)": "Power Weighting (w = value^p)",
        "임계값 이상만 (w = value, value>=t)": "Threshold Only (w = value, value >= t)",
        "임계값 이상만 (w = 1, value>=t)": "Binary Threshold (w = 1, value >= t)",
        "상위 %만 (w = value, top X%)": "Top % Only (w = value, top X%)",
        "CSV를 읽을 수 없습니다: {e}": "Could not read the CSV: {e}",
        "CSV에는 value,r,g,b 형태의 포인트가 2개 이상 필요합니다.": "The CSV must contain at least 2 points in value,r,g,b format.",
        "값 목록은 2개 이상이어야 합니다.": "The value list must contain at least 2 entries.",
        "이미지를 열 수 없습니다.": "Could not open the image.",
        "이미지 크기가 올바르지 않습니다.": "The image size is invalid.",
        "범례 포인트를 만들 수 없습니다.": "Could not create legend points.",
        "프리셋": "Preset",
        "사용자 프리셋을 추가했습니다: {preset.label}": "Added a custom preset: {preset.label}",
        "범례 이미지에서 프리셋을 추가했습니다: {preset.label}": "Added a preset from the legend image: {preset.label}",
        "RGB 래스터(WMS) 레이어를 선택해주세요.": "Select an RGB raster (WMS) layer.",
        "조사지역 폴리곤 레이어를 선택해주세요.": "Select an AOI polygon layer.",
        "조사지역은 폴리곤 레이어여야 합니다.": "The AOI must be a polygon layer.",
        "범례 프리셋이 올바르지 않습니다.": "The legend preset is invalid.",
        "구역 통계용 폴리곤 레이어를 선택해주세요.": "Select a polygon layer for zonal statistics.",
        "구역 통계 레이어는 폴리곤 레이어여야 합니다.": "The zonal statistics layer must be a polygon layer.",
        "조사지역 피처가 없습니다. (선택 또는 레이어 내용 확인)": "The AOI has no features. (Check the selection or the layer contents.)",
        "조사지역 지오메트리를 만들 수 없습니다.": "Could not build the AOI geometry.",
        "조사지역 경계(사각형)가 비어있습니다.": "The AOI bounding rectangle is empty.",
        "WMS 래스터를 GeoTIFF로 저장하지 못했습니다.": "Could not save the WMS raster as GeoTIFF.",
        "지구화학도 래스터 수치화": "GeoChem WMS to Raster",
        "처리 실패: {e}": "Processing failed: {e}",
    }
)

_EXACT_ENGLISH.update(
    {
        "최소비용 네트워크": "Least-cost Network",
        "허브(Hub)": "Hub",
        "허브 값 선택": "Select Hub Values",
        "유적 레이어와 허브 필드를 먼저 선택하세요.": "Select the site layer and hub field first.",
        "허브 필드 인덱스를 찾을 수 없습니다.": "Could not find the hub field index.",
        "선택 가능한 값이 없습니다(빈 값만 존재).": "There are no selectable values. (Only empty values exist.)",
        "이미 실행 중입니다.": "An analysis is already running.",
        "DEM 레이어를 선택하세요.": "Select a DEM layer.",
        "DEM CRS가 미터 단위가 아닙니다. (권장: 투영좌표계)": "The DEM CRS is not in meters. (Recommended: projected CRS)",
        "유적 레이어를 선택하세요.": "Select a site layer.",
        "유적 피처가 2개 이상 필요합니다.": "At least 2 site features are required.",
        "선택한 허브 값과 일치하는 피처가 없습니다. Hub 네트워크는 생략됩니다.": "No features match the selected hub values. The hub network will be skipped.",
        "분석 실패": "Analysis failed",
        "해석 가이드 (Least-cost Network)": "Interpretation Guide (Least-cost Network)",
        "해석 가이드 (Network Interpretation)": "Network Interpretation Guide",
        "네트워크": "Network",
        "입력 유적(벡터) 레이어를 선택해주세요.": "Select an input site (vector) layer.",
        "선택 피처가 2개 이상 필요합니다.": "At least 2 selected features are required.",
        "PPA": "PPA",
        "가시성 네트워크": "Visibility Network",
        "DEM(래스터) 레이어를 선택해주세요.": "Select a DEM (raster) layer.",
        "Threshold 그래프는 '최대 거리(m)'가 필요합니다. (0보다 크게)": "The threshold graph requires 'Maximum Distance (m)'. (Must be greater than 0.)",
        "Delaunay 기반 간선을 만들 수 없습니다. (점이 너무 적거나 중복일 수 있음)": "Could not build Delaunay-based edges. (There may be too few points or duplicate points.)",
        "취소되었습니다.": "Cancelled.",
        "근접성 네트워크 (PPA)": "Proximity Network (PPA)",
        "가시성 네트워크 (Visibility / LOS)": "Visibility Network (LOS)",
        "해석 가이드": "Interpretation Guide",
    }
)

_EXACT_ENGLISH.update(
    {
        "역방향 가시권": "Reverse Viewshed",
        "선형 및 둘레 가시권": "Line / Perimeter Viewshed",
        "선택된 위치: 없음": "Selected Location: None",
        "그려진 경로:": "Drawn Path:",
        "(폐곡선)": "(closed)",
        "(개곡선)": "(open)",
        "3. 가시선 설정": "3. Line-of-Sight Settings",
        "점=1회 클릭 후 우클릭/Enter로 완료, 폴리곤=여러 점(3점 이상) 찍고 우클릭/Enter로 완료. 기존 폴리곤 위 클릭=자동 선택, Shift+클릭=직접 그리기.": "Point: click once, then right click / Enter to finish. Polygon: click multiple points (3 or more), then right click / Enter. Clicking an existing polygon selects it automatically; Shift+click starts manual drawing.",
        "곡률/굴절(대기굴절) 보정 설명": "Curvature / Refraction Correction Info",
        "곡률/굴절(대기굴절) 보정": "Curvature / Refraction Correction",
        "현재 설정": "Current Settings",
        "근거(근사)": "Basis (approximation)",
        "현재 반경에서 규모": "Scale at the Current Radius",
        "언제 의미 있나(대략)": "When It Matters (roughly)",
        "예시(평탄 지형 기준)": "Examples (flat terrain)",
    }
)

_EXACT_ENGLISH.update(
    {
        "GeoChem 도움말": "GeoChem Help",
        "RGB 래스터(WMS)": "RGB Raster (WMS)",
        "조사지역 폴리곤": "AOI Polygon",
        "조사지역 선택 피처만 사용": "Use Selected AOI Features Only",
        "2. 원소/범례 프리셋": "2. Element / Legend Preset",
        "구간 라벨 표시용 단위(예: %, wt%).": "Unit used for class labels (for example %, wt%).",
        "사용자 범례 프리셋을 추가합니다(CSV/이미지 샘플링).": "Add a custom legend preset from CSV or image sampling.",
        "CSV로 프리셋 불러오기…": "Load Preset from CSV...",
        "범례 이미지에서 샘플링…": "Sample from Legend Image...",
        "단위": "Unit",
        "AOI 마스크 적용(폴리곤 내부만)": "Apply AOI Mask (inside polygon only)",
        "최댓값을 범례 최댓값으로 보정": "Scale Maximum to the Legend Maximum",
        "고농도 스냅(최댓값)": "High-Concentration Snap (maximum)",
        "검은 경계선 제거(보간)": "Remove Dark Boundaries (interpolation)",
        "범례 프리셋": "Legend Preset",
        "값 목록은 2개 이상이어야 합니다.": "The value list must contain at least 2 values.",
        "Fe2O3 (산화철)": "Fe2O3 (Iron Oxide)",
        "Pb (납)": "Pb (Lead)",
        "Cu (구리)": "Cu (Copper)",
        "Zn (아연)": "Zn (Zinc)",
        "Sr (스트론튬)": "Sr (Strontium)",
        "Ba (바륨)": "Ba (Barium)",
        "CaO (칼슘)": "CaO (Calcium Oxide)",
        "0~최소값(회색) 구간을 NoData로 취급": "Treat the 0-to-minimum (gray) range as NoData",
        "보간 시 검색 거리(픽셀). 클수록 잘 메우지만 느릴 수 있습니다.": "Search distance for interpolation (pixels). Larger values fill gaps better but may be slower.",
        "픽셀 크기(지도 단위/px)": "Pixel Size (map units / px)",
        "조사지역 경계(사각형) 버퍼(m)": "AOI Bounding Rectangle Buffer (m)",
        "보간 거리(px)": "Interpolation Distance (px)",
        "스냅 t(0~1)": "Snap t (0-1)",
    }
)

_EXACT_ENGLISH.update(
    {
        "지질도 ZIP/MaxEnt 도움말": "Geology ZIP / MaxEnt Help",
        "지역/도엽:": "Area / Sheet:",
        "병합 레이어 생성에 실패했습니다.": "Failed to create the merged layer.",
        "래스터 파일이 생성되지 않았습니다. 출력 경로/권한/로그를 확인하세요.": "The raster file was not created. Check the output path, permissions, and logs.",
        "출력 래스터 크기가 0입니다. (CRS 단위/해상도 불일치) 투영 CRS(미터 단위)로 변환하거나 픽셀 크기를 조정하세요.": "The output raster size is 0. (CRS units / resolution mismatch) Reproject to a projected CRS in meters or adjust the pixel size.",
    }
)

_EXACT_ENGLISH.update(
    {
        "단면선 (개별 레이어)": "Profile Lines (Individual Layers)",
        "거리:": "Distance:",
        "확대:": "Zoom:",
        "지도를 클릭하여 단면을 생성하세요.": "Click on the map to create a profile.",
        "DEM 래스터를 선택해주세요": "Select a DEM raster.",
        "단면 완료": "Profile Complete",
        "프로파일을 열 DEM을 선택해주세요.": "Select a DEM to open the profile.",
        "단면 분석": "Profile Analysis",
        "프로파일을 위해 DEM 소스를 찾을 수 없습니다.": "Could not find the DEM source for the profile.",
        "단면 오버레이": "Profile Overlay",
    }
)

_EXACT_ENGLISH.update(
    {
        "DEM 생성 도움말": "DEM Generation Help",
        "1:1,000 (등고선 1m)": "1:1,000 (1 m contours)",
        "1:2,500 (등고선 2m)": "1:2,500 (2 m contours)",
        "1:5,000 (등고선 5m)": "1:5,000 (5 m contours)",
        "1:25,000 (등고선 10m)": "1:25,000 (10 m contours)",
        "1:50,000 (등고선 20m)": "1:50,000 (20 m contours)",
        "Custom (사용자 지정)": "Custom",
        "TIN - Linear (선형)": "TIN - Linear",
        "TIN - Clough-Tocher (곡면)": "TIN - Clough-Tocher",
        "IDW (역거리 가중치)": "IDW (Inverse Distance Weighting)",
        "등고선(기타/확인필요)": "Contours (Other / needs review)",
        "현행(등고선)": "Current (contours)",
        "등고선(주곡선). DEM 생성의 기본 입력": "Index contours. The main input for DEM generation.",
        "등고선(보조)": "Contours (secondary)",
        "등고선 보조 코드(데이터셋별 상이). 필요 시 선택": "Secondary contour codes vary by dataset. Select if needed.",
        "등고선(간곡선/보조). 주곡선 사이를 보완": "Intermediate / secondary contours that supplement index contours.",
        "지형선(보조)": "Terrain Lines (secondary)",
        "지형 굴곡 보조선(데이터셋별 상이). DEM 보간에는 보통 선택적": "Secondary terrain lines (dataset dependent). Usually optional for DEM interpolation.",
        "현행(지형)": "Current (terrain)",
        "등고선 수치": "Contour Labels",
        "등고선 숫자(텍스트). DEM 보간에는 보통 불필요": "Contour number labels (text). Usually unnecessary for DEM interpolation.",
        "현행(텍스트)": "Current (text)",
        "표고점": "Spot Heights",
        "표고점(Spot height). 등고선만으로 부족한 지점 보완(권장)": "Spot heights. Recommended to supplement areas where contours are insufficient.",
        "현행(포인트)": "Current (points)",
        "삼각점": "Triangulation Points",
        "수준점": "Benchmarks",
        "최소 하나의 레이어를 선택해주세요": "Select at least one layer.",
        "레이어를 체크해주세요": "Check at least one layer.",
        "출력 파일 경로를 지정해주세요": "Specify an output file path.",
        "레이어 병합에 실패했습니다.": "Failed to merge layers.",
        "(직접 입력)": "(Manual input)",
        "시작점: (미설정)": "Start Point: (not set)",
        "도착점: (선택)": "End Point: (optional)",
        "직선거리: -": "Straight-line Distance: -",
        "지도에서 시작점→도착점을 순서대로 클릭하세요. (우클릭/ESC 종료)": "Click the start point and then the end point on the map. (Right click / ESC to finish)",
        "지도를 클릭하여 단면을 생성하세요.": "Click on the map to create a profile.",
        "현재 min/max:": "Current min/max:",
        "가중치 미리보기:": "Weight Preview:",
        "상위그룹": "Parent Group",
        "각 기준 독립": "Each Criterion Independent",
        "모두 한 그룹": "All in One Group",
        "로컬 가중치": "Local Weight",
        "글로벌 가중치": "Global Weight",
        "(기준)": "(criterion)",
        "그룹": "Group",
        "상위그룹 쌍대비교": "Parent-group Pairwise Comparison",
        "하위기준 쌍대비교": "Subcriterion Pairwise Comparison",
        "전문가 1": "Expert 1",
        "Benefit(값↑)": "Benefit (higher values)",
        "Cost(값↓)": "Cost (lower values)",
        "목표값 최적": "Target Value Optimal",
        "선호구간 최적": "Preferred Range Optimal",
        "구간 점수표": "Reclass Score Table",
        "목표=": "Target=",
        "선호=": "Preferred=",
        "구간": "Range",
        "개": "items",
        "(항목)": "(item)",
        "(주의: 0.10 초과)": "(Warning: above 0.10)",
    }
)

_EXACT_ENGLISH.update(
    {
        "총 거리:": "Total Distance:",
        "고도 범위:": "Elevation Range:",
        "선택한 단면선": "Selected Profile Line",
        "단면선_": "ProfileLine_",
        "유효한 고도 데이터를 추출하지 못했습니다. DEM 범위를 확인하세요.": "Could not extract valid elevation data. Check the DEM extent.",
        "선택 피처만 사용": "Use Selected Features Only",
    }
)

_EXACT_ENGLISH.update(
    {
        "비우기": "Clear",
        "- 진행상황/오류가 여기에 실시간으로 기록됩니다.": "- Progress and errors are recorded here in real time.",
        "- 오류/제안 제보: GitHub Issues (repo tracker)": "- Report errors / suggestions: GitHub Issues (repo tracker)",
        "- 오류/제안 제보: {tracker}": "- Report errors / suggestions: {tracker}",
        "- 로그 파일: {path}": "- Log file: {path}",
        "- 참고문헌/모델 출처: REFERENCES.md": "- References / model sources: REFERENCES.md",
        "도구 사용법/주의사항을 봅니다.": "Open help and usage notes.",
        "비용표면/최소비용경로": "Cost Surface / LCP",
        "지도에서 시작점을 클릭하세요. (우클릭/ESC 종료)": "Click the start point on the map. (Right click / ESC to finish)",
        "시작점/도착점을 DEM 좌표계로 변환하지 못했습니다. 프로젝트 CRS와 DEM CRS를 확인하세요.": "Could not transform the start/end points into the DEM CRS. Check the project CRS and DEM CRS.",
        "네트워크": "Network",
        "가시성 네트워크": "Visibility Network",
        "입력 유적(벡터) 레이어를 선택해주세요.": "Select an input site (vector) layer.",
        "선택 피처가 2개 이상 필요합니다.": "At least two selected features are required.",
        "유효한 노드가 2개 이상 필요합니다.": "At least two valid nodes are required.",
        "DEM(래스터) 레이어를 선택해주세요.": "Select a DEM raster layer.",
        "Threshold 그래프는 '최대 거리(m)'가 필요합니다. (0보다 크게)": "The threshold graph requires 'Max dist (m)'. Enter a value greater than 0.",
        "Delaunay 기반 간선을 만들 수 없습니다. (점이 너무 적거나 중복일 수 있음)": "Could not create Delaunay-based edges. There may be too few points or duplicate points.",
        "취소되었습니다.": "Cancelled.",
        "가시성 네트워크(LOS) 계산 중...": "Calculating visibility network (LOS)...",
        "작업영역(AOI)": "AOI Work Area",
        "새 폴리곤 레이어를 생성했습니다. 편집 모드에서 폴리곤(1개 이상)을 그린 후 실행해주세요.": "A new polygon layer has been created. Draw one or more polygons in edit mode, then run the tool.",
        "입력 DEM(래스터)을 선택해주세요.": "Select an input DEM raster.",
        "작업영역(AOI) 폴리곤 레이어를 선택하거나 '새 폴리곤'을 눌러 생성해주세요.": "Select an AOI polygon layer, or create one with 'New Polygon'.",
        "작업영역은 폴리곤 레이어여야 합니다.": "The work area must be a polygon layer.",
        "선택된 폴리곤이 없습니다. '선택된 피처만 사용'을 해제하거나 폴리곤을 선택해주세요.": "No polygon is selected. Disable 'Use Selected Features Only' or select a polygon.",
        "작업영역 폴리곤이 없습니다. 폴리곤을 그리거나 다른 폴리곤 레이어를 선택해주세요.": "No AOI polygon is available. Draw a polygon or choose another polygon layer.",
        "생성할 결과(경사도/사면방향)를 선택해주세요.": "Select at least one output to create (slope / aspect).",
        "경사도/사면방향 도면화 생성 중...": "Creating slope/aspect drafting output...",
        "도면화 결과가 생성되었습니다.": "Draft output was created.",
        "경사도 래스터를 열 수 없습니다.": "Could not open the slope raster.",
        "래스터를 열 수 없습니다.": "Could not open the raster.",
        "도면화(경사/사면방향) 도움말": "Slope / Aspect Drafting Help",
        "근접성 네트워크 (PPA)": "Proximity Network (PPA)",
        "가시성 네트워크 (Visibility / LOS)": "Visibility Network (LOS)",
        "k-NN (직선거리)": "k-NN (Straight-line Distance)",
        "Distance threshold (반경)": "Distance Threshold (Radius)",
        "Delaunay (삼각망)": "Delaunay (Triangulation)",
        "상호 보임만 (Mutual)": "Mutual Only",
        "단방향 포함 (Either direction)": "Either Direction",
        "해석 가이드": "Interpretation Guide",
        "노드 지표 레이어(점) 생성": "Create Node Metrics Layer (points)",
        "Closeness 계산": "Compute Closeness",
        "Betweenness 계산": "Compute Betweenness",
        "LOS 연결 규칙": "LOS Edge Rule",
        "Point on surface (권장)": "Point on Surface (recommended)",
        "(FID 사용)": "(Use FID)",
        "GeoChem 도움말": "GeoChem Help",
        "2. 원소/범례 프리셋": "2. Element / Legend Preset",
        "RGB 래스터(WMS)": "RGB Raster (WMS)",
        "조사지역 폴리곤": "AOI Polygon",
        "조사지역 선택 피처만 사용": "Use Selected AOI Features Only",
        "단위": "Unit",
        "불러오기": "Import",
        "CSV로 프리셋 불러오기…": "Import Preset from CSV...",
        "범례 이미지에서 샘플링…": "Sample from Legend Image...",
        "AOI 마스크 적용(폴리곤 내부만)": "Apply AOI Mask (inside polygon only)",
        "0~최소값(회색) 구간을 NoData로 취급": "Treat the 0-to-minimum (gray) range as NoData",
        "최댓값을 범례 최댓값으로 보정": "Scale the maximum to the legend maximum",
        "고농도 스냅(최댓값)": "High-value Snap (Maximum)",
        "검은 경계선 제거(보간)": "Remove Black Boundaries (Inpaint)",
        "픽셀 크기(지도 단위/px)": "Pixel Size (map units / px)",
        "조사지역 경계(사각형) 버퍼(m)": "AOI Bounding Extent Buffer (m)",
        "보간 거리(px)": "Fill Distance (px)",
        "스냅 t(0~1)": "Snap t (0-1)",
        "값 래스터 저장(영구)": "Save Value Raster (persistent)",
        "프로젝트에 래스터 레이어로 추가": "Add Raster Layers to Project",
        "구간(class) 래스터 생성(옵션)": "Create Class Raster (optional)",
        "폴리곤 생성(구간별)": "Create Polygons by Class",
        "구간별로 합치기(dissolve)": "Dissolve by Class",
        "NoData(투명) 폴리곤 제외": "Exclude NoData (transparent) Polygons",
        "TIP: value 래스터는 WMS 색상을 그대로 수치화한 ‘원본 데이터’입니다.\n- class 래스터/폴리곤은 ‘구간별(범주형) 결과’가 필요할 때만 켜세요.": "TIP: the value raster is the direct numeric reconstruction of the WMS colors.\n- Turn on class rasters / polygons only when you need class-based categorical output.",
        "구역 통계 레이어 생성(폴리곤별 평균/구간면적)": "Create Zonal Statistics Layer (mean / class area by polygon)",
        "구역(폴리곤) 레이어": "Zone (polygon) Layer",
        "구역 레이어 선택 피처만 사용": "Use Selected Zone Features Only",
        "중심점 생성": "Create Center Points",
        "중심점 방식": "Center Method",
        "가중치 규칙": "Weight Rule",
        "가중 평균 중심(질량중심)": "Weighted Mean Center",
        "무가중 평균 중심(선택 픽셀 중심)": "Unweighted Mean Center",
        "최대값 픽셀(peak)": "Peak Pixel",
        "값 그대로 (w = value)": "Use Values As-Is (w = value)",
        "값 거듭제곱 (w = value^p)": "Power Weighting (w = value^p)",
        "임계값 이상만 (w = value, value>=t)": "Threshold Only (w = value, value >= t)",
        "임계값 이상만 (w = 1, value>=t)": "Binary Threshold Only (w = 1, value >= t)",
        "상위 %만 (w = value, top X%)": "Top Percent Only (w = value, top X%)",
        "역방향 가시권": "Reverse Viewshed",
        "선형 및 둘레 가시권": "Line / Perimeter Viewshed",
        "지도에서 라인을 그리세요. 클릭으로 점 추가, 시작점 클릭 시 자동 닫힘(Snap), 우클릭으로 완료": "Draw a line on the map. Click to add vertices, click near the start point to close it automatically, and right-click to finish.",
        "지도에서 관측점을 클릭하세요": "Click an observer point on the map.",
        "가시선 분석": "Line of Sight",
        "지도에서 관측점 → 대상점 순서로 클릭하세요 (2번)": "Click the observer point and then the target point on the map.",
        "다중점 가시권": "Multi-point Viewshed",
        "지도에서 관측점을 여러 번 클릭하세요 (ESC로 완료)": "Click multiple observer points on the map. Press ESC when you are done.",
        "관측점 설정 완료. 이제 대상점을 클릭하세요": "Observer point set. Now click the target point.",
        "AOI 통계": "AOI Statistics",
        "AOI 폴리곤 레이어를 선택하세요.": "Select an AOI polygon layer.",
        "AOI 레이어는 폴리곤이어야 합니다.": "The AOI layer must be a polygon layer.",
        "AOI 통계 레이어 생성 실패": "Failed to create the AOI statistics layer.",
        "대상점 개수 경고": "Target Point Count Warning",
        "관측점 개수 경고": "Observer Point Count Warning",
        "역방향 가시권 분석 실행 중...": "Running reverse viewshed analysis...",
        "다중점 가시권 분석 초기화 중...": "Initializing multi-point viewshed...",
        "시각적 불균등: 1/3 (정방향 가시권)": "Visual asymmetry: 1/3 (forward viewshed)",
        "시각적 불균등: 2/3 (역방향 가시권)": "Visual asymmetry: 2/3 (reverse viewshed)",
        "시각적 불균등: 3/3 (불균등 분류)": "Visual asymmetry: 3/3 (classifying asymmetry)",
        "시각적 불균등 분석 완료": "Visual asymmetry analysis complete",
        "역방향 폴리곤은 최소 3개 점이 필요합니다 (또는 1개 점으로 대상점 선택).": "Reverse-viewshed polygons require at least 3 vertices (or select a single target point with 1 click).",
        "지형 데이터를 샘플링할 수 없습니다": "Could not sample the terrain data.",
        "가시선 프로파일 (Line of Sight Profile)": "Line of Sight Profile",
        "지도-프로파일 연동": "Sync map and profile",
        "직시 불가 (안보임)": "Blocked",
        "허브로 사용할 값을 체크하세요. (여러 개 선택 가능)": "Check the values to use as hubs. Multiple selections are allowed.",
        "(피처 ID 사용)": "(Use feature ID)",
        "(허브 사용 안 함)": "(Do not use hubs)",
        "후보 간선(k)\n- 각 노드에서 유클리드 거리로 가까운 k개만 후보로 잡고 LCP를 계산합니다.\n- 값이 작을수록 빠르지만, 그래프가 끊겨 MST가 실패할 수 있습니다.\n- 200개+ 노드에서는 8~20부터 시도 후, 실패하면 k를 늘려보세요.": "Candidate edges (k)\n- For each node, only the nearest k nodes by Euclidean distance are kept as LCP candidates.\n- Smaller values are faster, but the graph may disconnect and the MST can fail.\n- For 200+ nodes, try 8-20 first and increase k if needed.",
        "경로 버퍼(m)\n- 후보쌍 두 점을 감싸는 bbox에 추가로 여유를 주는 값입니다.\n- 값이 너무 작으면 '진짜 최적 경로'가 창 밖으로 나가 경로가 끊길 수 있습니다.\n- 0은 DEM 전체를 사용(매우 느림)하므로 권장하지 않습니다.": "Path buffer (m)\n- Extra margin added to the bounding box around each candidate pair.\n- If it is too small, the real optimal route may leave the window and the path can fail.\n- A value of 0 searches the full DEM and is usually too slow.",
        "대각 이동 허용(8방향)\n- 격자 기반 경로에서 '계단 현상'을 줄이고 더 자연스러운 경로가 나올 수 있습니다.\n- 필요하면 꺼서(4방향) 비교해보세요.": "Allow diagonal movement (8 directions)\n- Often reduces the stair-step effect in raster paths and can produce more natural routes.\n- Turn it off for a 4-direction comparison when needed.",
        "MST 대칭화\n- 경사 때문에 A→B와 B→A 비용이 달라질 수 있습니다.\n- MST는 무방향 그래프가 필요하므로 한 값으로 합칩니다.\n  • 왕복 평균: (A→B + B→A)/2\n  • 편도 최소: min(A→B, B→A)\n  • 편도 최대: max(A→B, B→A)": "MST symmetrization\n- Because slope can make A->B and B->A costs different, the MST needs one undirected value.\n  - Round-trip mean: (A->B + B->A) / 2\n  - One-way minimum: min(A->B, B->A)\n  - One-way maximum: max(A->B, B->A)",
        "k‑NN의 k\n- 각 노드에서 비용이 작은 상위 k개 노드로 연결합니다.\n- k가 작으면 네트워크가 끊길 수 있고, k가 크면 선이 많아집니다.": "k in k-NN\n- Each node connects to the k lowest-cost neighbors.\n- Small k values may fragment the network, while large k values create many edges.",
        "네트워크 방식(드롭다운 항목에 마우스를 올리면 설명/레퍼런스가 표시됩니다).": "Network mode (hover over dropdown items to see descriptions and references).",
        "비용 기준\n- 시간(분): 대부분 모델에서 사용\n- 에너지(kcal): Pandolf 모델에서만 의미가 있습니다.": "Cost basis\n- Time (minutes): used by most models\n- Energy (kcal): meaningful only for the Pandolf model",
        "허브 필드\n- 허브를 구분할 필드(예: 유형/등급/분류)를 선택합니다.\n- 예: '유형' 필드에서 값이 '왕성'인 피처만 허브로 지정": "Hub field\n- Choose the field used to distinguish hub sites (for example type, class, or rank).\n- Example: only features whose 'type' value is 'capital' become hubs.",
        "허브 값(쉼표로 구분)\n- 예: 왕성, 산성, 봉수\n- 오른쪽 '선택…' 버튼으로 필드의 실제 값 목록에서 고를 수 있습니다.": "Hub values (comma-separated)\n- Example: capital, mountain fortress, beacon\n- Use the 'Select...' button to choose from actual values in the field.",
        "허브 필드의 고유 값을 목록에서 선택합니다.": "Select unique values from the hub field.",
        "모델을 선택하면 아래 변수들이 해당 모델에 맞게 적용됩니다.": "Select a model to apply the variables below with the matching movement-cost formula.",
        "기본속도(km/h)\n- 평지 기준 속도입니다.\n- 값↑ → 전체 이동 시간이 감소합니다.": "Base speed (km/h)\n- Speed on flat terrain.\n- Higher values reduce total travel time.",
        "경사 민감도\n- 경사가 변할 때 속도가 얼마나 빨리 감소하는지 결정합니다.\n- 값↑ → 가파를수록 더 느려집니다.": "Slope sensitivity\n- Controls how quickly speed decreases as slope changes.\n- Higher values produce stronger slowdown on steep terrain.",
        "오프셋(+)\n- Tobler 식의 상수(기본값 0.05)로, 최적 경사 위치를 미세 조정합니다.\n- 값 변화는 결과에 미세하게 반영됩니다.": "Offset (+)\n- Constant term in the Tobler equation (default 0.05) that slightly shifts the optimal slope position.\n- Changes usually affect results only subtly.",
        "수평 속도(km/h)\n- 평지 기준 보행 속도입니다.\n- 값↑ → 전체 이동 시간이 감소합니다.": "Horizontal speed (km/h)\n- Walking speed on flat terrain.\n- Higher values reduce total travel time.",
        "상승(m/h)\n- 상승 속도(오르막 보정)입니다.\n- 값↑ → 오르막 페널티가 감소(더 빨리 오름)합니다.": "Ascent (m/h)\n- Uphill ascent rate used for the uphill penalty.\n- Higher values reduce uphill penalties.",
        "기본 속도(km/h)\n- 평지 기준 속도입니다.\n- 값↑ → 전체 이동 시간이 감소합니다.": "Base speed (km/h)\n- Speed on flat terrain.\n- Higher values reduce total travel time.",
        "기본 속도(km/h)\n- 평지(경사 0) 기준 속도입니다.\n- 값↑ → 전체 이동 시간이 감소합니다.": "Base speed (km/h)\n- Speed on flat terrain at 0 slope.\n- Higher values reduce total travel time.",
        "기준 경사(°)\n- 비용 곡선의 기준점(민감도 기준)을 정합니다.\n- 값 변화에 따라 경사 페널티가 달라집니다.": "Reference slope (deg)\n- Sets the reference point used by the cost curve.\n- Changing it alters the slope penalty behavior.",
        "기준 경사(°)\n- 이 값 이후로 비용이 급격히 증가하기 시작합니다.\n- 값↑ → 더 가파른 경사까지 '급증 전'으로 취급됩니다.": "Critical slope (deg)\n- Above this point, cost begins to rise sharply.\n- Higher values treat steeper slopes as still below the sharp-rise threshold.",
        "통행한계(°)\n- 이 경사를 초과하는 셀은 통과 불가(NoData)로 처리합니다.\n- 값↓ → 통과 불가 영역이 늘어납니다.": "Maximum passable slope (deg)\n- Cells steeper than this threshold are treated as impassable (NoData).\n- Lower values increase the impassable area.",
        "체중(kg)\n- 보행자 체중입니다.\n- 값↑ → 에너지 소모(kcal)가 증가합니다.": "Body weight (kg)\n- The walker's body weight.\n- Higher values increase energy expenditure (kcal).",
        "짐(kg)\n- 운반 짐 무게입니다.\n- 값↑ → 에너지 소모(kcal)가 증가합니다.": "Load (kg)\n- Weight of the carried load.\n- Higher values increase energy expenditure (kcal).",
        "속도(km/h)\n- 에너지 식 + 시간 환산(분/거리) 계산에 사용합니다.\n- 값↑ → 시간은 감소하지만 에너지는 항상 감소하지 않을 수 있습니다.": "Speed (km/h)\n- Used both in the energy equation and in the time conversion (minutes per distance).\n- Higher values reduce time, but energy cost does not always decrease.",
        "지면계수 η\n- 지면/마찰 계수(η). 1.0=단단한 지면, 값↑ → 같은 경사에서도 더 비싸짐.\n- 예: 1.0(도로/평탄) ~ 2.0+(거친 지면/진흙 등)": "Terrain factor eta\n- Ground / friction factor (eta). 1.0 means firm ground; larger values make the same slope more costly.\n- Example: 1.0 for roads / flat ground up to 2.0+ for rough terrain or mud.",
        "AHP 적합도 래스터 저장": "Save AHP Suitability Raster",
        "구간 점수표에 서로 겹치는 구간이 있습니다. 범위를 다시 조정하세요.": "The reclass score table contains overlapping ranges. Adjust the ranges and try again.",
        "기준 레이어가 유효하지 않습니다.": "A criterion layer is invalid.",
        "가중합 결과를 생성할 수 없습니다.": "Could not create the weighted-sum result.",
        "제약 마스크 벡터는 폴리곤이어야 합니다.": "The constraint-mask vector layer must be a polygon layer.",
    }
)

_SEGMENT_ENGLISH_MAP = {
    "# AI 조사요약 (무료/로컬)": "# AI AOI Report (Free / Local)",
    "## 1) 개요": "## 1) Overview",
    "## 1-1) ArchToolkit 실행 묶음": "## 1-1) ArchToolkit Run Groups",
    "## 2) 레이어/분석 요약": "## 2) Layer / Analysis Summary",
    "## 3) 핵심 관찰(로컬 자동 요약)": "## 3) Key Observations (Local Auto Summary)",
    "## 4) 한계/주의": "## 4) Limits / Notes",
    "## 5) 다음 단계 제안": "## 5) Suggested Next Steps",
    "- AOI:": "- AOI:",
    "- AOI 피처 수:": "- AOI feature count:",
    "- AOI CRS:": "- AOI CRS:",
    "- AOI 면적:": "- AOI area:",
    "- 반경:": "- Radius:",
    "- 버퍼 면적(반경 내):": "- Buffer area (within radius):",
    "- 요약 레이어 수:": "- Number of summarized layers:",
    "- ArchToolkit 실행 묶음:": "- ArchToolkit run groups:",
    "- 참고: 레이어 수가 많아 일부만 요약되었을 수 있습니다.": "- Note: only part of the project may have been summarized because there are many layers.",
    "- (해당 없음)": "- (Not applicable)",
    "- (요약할 레이어가 없습니다)": "- (There are no layers to summarize)",
    "(이름 없음)": "(unnamed)",
    "- 포함 레이어:": "- Included layers:",
    "- 대표 지표:": "- Key metrics:",
    "- 분류:": "- Category:",
    "- ArchToolkit 메타:": "- ArchToolkit metadata:",
    "- 해석:": "- Interpretation:",
    "- 설정/맥락:": "- Settings / context:",
    "- 핵심 지표:": "- Key metrics:",
    "- 통계: (없음/계산 실패)": "- Statistics: (none / failed to calculate)",
    "- 통계: (지원되지 않는 레이어 타입)": "- Statistics: (unsupported layer type)",
    "- 피처:": "- Features:",
    "- 총 길이:": "- Total length:",
    "- 총 면적:": "- Total area:",
    "- 상위 값(": "- Top values (",
    "- AOI 중심까지 거리:": "- Distance to AOI centroid:",
    "- 픽셀(표본) 수:": "- Pixels (samples):",
    "- (힌트) 마스크/가시(>0.5) 비율:": "- (Hint) mask / visible (>0.5) ratio:",
    "- 주변에서 가장 많은 피처가 겹치는 레이어:": "- Layer with the most overlapping nearby features:",
    "- (힌트) 0.5 초과 비율이 높은 래스터:": "- (Hint) raster with the highest proportion above 0.5:",
    "- (특이사항 자동 추출 없음) 위 레이어별 통계를 참고해 해석하세요.": "- (No notable observations were auto-detected) Please interpret the results using the layer statistics above.",
    "- 이 보고서는 **외부 AI를 호출하지 않는 로컬 요약**입니다(문장 품질/해석은 제한적).": "- This report is a **local summary that does not call an external AI** (language quality and interpretation are limited).",
    "- 통계는 AOI 버퍼와의 교차/표본 기반이며, 레이어 품질(좌표계/해상도/NoData)에 따라 달라질 수 있습니다.": "- Statistics are based on AOI buffer intersections and samples, and may vary depending on layer quality (CRS, resolution, NoData).",
    "- 레이어가 많거나(레이어 cap), 피처가 매우 많으면(스캔 cap) 일부만 반영되었을 수 있습니다.": "- If there are many layers or a very large number of features, only part of the project may have been reflected due to summary limits.",
    "- 필요하면 `AI 모드: Gemini(API)`로 전환해 더 자연어 중심의 보고서 문장을 생성합니다.": "- If needed, switch to `AI mode: Gemini (API)` to generate a more natural-language report.",
    "- 해석에 중요한 레이어는 이름/그룹을 정리하고(민감정보 제거) 다시 요약을 생성합니다.": "- For important interpretive layers, clean up names / groups (and remove sensitive information) before generating the summary again.",
    "- 최종 보고서에는 원자료/방법/좌표계/해상도 등을 함께 기록하세요.": "- Include source data, methods, CRS, and resolution in the final report.",
    "당신은 한국의 고고학/문화유산 연구자를 돕는 GIS 분석 보조자입니다.": "You are a GIS analysis assistant supporting archaeology and cultural heritage research.",
    "아래 JSON은 QGIS 프로젝트에서 ‘조사지역(AOI) 반경’ 내의 레이어들을 요약한 것입니다.": "The JSON below summarizes layers within the Area of Interest (AOI) radius in a QGIS project.",
    "중요: 각 레이어 항목에 `archtoolkit` 메타데이터가 포함될 수 있습니다.": "Important: each layer may contain `archtoolkit` metadata.",
    "- `archtoolkit_interpretation`이 있으면, 이는 플러그인이 도구 의미를 1차 해석한 값입니다.": "- If `archtoolkit_interpretation` is present, it is the plugin's first-pass interpretation of the layer.",
    "- `archtoolkit_runs`는 같은 `run_id` 결과를 실행 단위로 묶은 요약입니다.": "- `archtoolkit_runs` groups results from the same `run_id` into execution-level summaries.",
    "- 가능하면 `archtoolkit.tool_id/kind/units/run_id`를 우선 사용해 레이어 의미를 해석하세요.": "- Prefer `archtoolkit.tool_id/kind/units/run_id` when interpreting layer meaning.",
    "- 메타데이터가 있는 경우, 레이어 이름만 보고 임의로 의미를 추측하지 마세요.": "- When metadata exists, do not infer meaning from the layer name alone.",
    "- 동일 `run_id`는 같은 도구 실행(run)에서 나온 결과이므로 묶어서 설명해도 됩니다.": "- Layers with the same `run_id` came from the same tool run and may be described together.",
    "요청:": "Request:",
    "1) 한국어로, 보고서/업무 메모 형태로 정리해 주세요.": "1) Write the result in English, in a report / work-note style.",
    "2) 과장/추측 금지: 수치가 없으면 단정하지 말고 '추정/참고'로 표시.": "2) Avoid exaggeration or unsupported claims: if no numeric evidence exists, mark it as an estimate or reference.",
    "3) 결과는 섹션으로 구분:": "3) Structure the result into sections:",
    "   - 개요(조사지역/반경)": "   - Overview (AOI / radius)",
    "   - 사용된 레이어/분석 요약(레이어별)": "   - Used layers / analysis summary (by layer)",
    "   - 핵심 관찰(정량값이 있으면 포함)": "   - Key observations (include quantitative values when available)",
    "   - 한계/주의(좌표계/해상도/NoData/AI 한계)": "   - Limits / notes (CRS, resolution, NoData, AI limitations)",
    "   - 다음 단계 제안": "   - Suggested next steps",
    "4) 결과에 포함된 레이어 이름은 가능한 그대로 유지.": "4) Keep layer names as close to the originals as possible.",
    "대상: AOI=": "Target: AOI=",
    "반경=": "radius=",
    "JSON:": "JSON:",
    "<b>왜 이 기능을 넣었나요?</b><br>": "<b>Why was this feature added?</b><br>",
    "<b>어떻게 쓰면 좋나요?</b><br>": "<b>How should I use it?</b><br>",
    "<b>이 도구가 ‘읽는 것’</b><br>": "<b>What this tool reads</b><br>",
    "<b>Gemini 모드에서 외부로 나가는 것</b><br>": "<b>What leaves your computer in Gemini mode</b><br>",
    "<b>모든 분석을 AI가 답변할 수 있나요?</b><br>": "<b>Can AI explain every analysis?</b><br>",
    "<b>팁</b><br>": "<b>Tips</b><br>",
    "분석 결과(가시권/비용/네트워크/지형지수/GeoChem/지적중첩 등)가 여러 레이어로 흩어지면, 현장 기록·보고서에 쓰기 어렵습니다. AI 조사요약은 AOI 반경 내 결과를 모아 <b>요약/보고서 문장</b>으로 빠르게 정리하려고 만들었습니다.": "When analysis results (viewshed, cost, network, terrain indices, GeoChem, cadastral overlap, and more) are spread across many layers, they become hard to use in field notes and reports. AI AOI Report gathers results inside the AOI radius and quickly organizes them into <b>summary / report prose</b>.",
    "1) 먼저 원하는 분석을 실행해 결과 레이어를 만든 다음<br>": "1) Run the analyses you need first so result layers exist.<br>",
    "2) AOI와 반경(m)을 고르고<br>": "2) Choose the AOI and radius (m).<br>",
    "3) 모드를 선택합니다: <b>무료(로컬)</b>은 외부 전송 없이 요약, <b>Gemini</b>는 더 자연어 보고서 생성(키 필요).<br>": "3) Choose a mode: <b>Free (Local)</b> summarizes without external transmission, while <b>Gemini</b> generates more natural report text (API key required).<br>",
    "4) 생성된 문장을 <b>반드시 검토</b>한 뒤 저장/편집하세요.<br><br>": "4) <b>Review the generated text carefully</b> before saving or editing it.<br><br>",
    "- 현재 QGIS 프로젝트의 레이어 중 AOI 버퍼와 겹치는 레이어를 스캔합니다.<br>": "- It scans layers in the current QGIS project that intersect the AOI buffer.<br>",
    "- 벡터: 피처 수, (가능하면) 길이/면적 합, 일부 필드 분포(상위 값).<br>": "- Vector layers: feature count, and when possible total length / area and top field values.<br>",
    "- 래스터: min/mean/max 등 단순 통계(가능하면).<br><br>": "- Raster layers: simple statistics such as min / mean / max when available.<br><br>",
    "- AOI 이름, 반경, 선택된 레이어 이름, 통계 요약, ArchToolkit 메타데이터가 JSON으로 전송됩니다.<br>": "- AOI name, radius, selected layer names, summary statistics, and ArchToolkit metadata are sent as JSON.<br>",
    "- 원본 지오메트리 전체나 래스터 픽셀 전체를 그대로 업로드하는 구조는 아닙니다.<br><br>": "- It does not upload full raw geometries or full raster pixel arrays.<br><br>",
    "원칙적으로 ‘결과가 레이어(래스터/벡터)로 존재’하면 요약에 포함될 수 있습니다.": "In principle, if the result exists as a layer (raster or vector), it can be included in the summary.",
    "<b>ArchToolkit 메타데이터(tool_id/kind/run_id 등)가 있으면 도구 의미를 더 우선적으로 해석</b>합니다.": "<b>If ArchToolkit metadata (tool_id / kind / run_id, etc.) exists, it is used first to interpret layer meaning</b>.",
    "그래도 최종 해석은 사용자가 검토해야 합니다.<br><br>": "Even so, the final interpretation still needs user review.<br><br>",
    "- AOI는 가능하면 <b>투영 CRS(미터)</b>에서 사용하세요.<br>": "- Use the AOI in a <b>projected CRS (meters)</b> when possible.<br>",
    "- 입력 섹션 아래의 <b>현재 스캔 범위</b> 안내 배너에서 실제로 어떤 범위를 읽을지 먼저 확인하세요.<br>": "- Check the <b>Current Scan Scope</b> banner under the input section to confirm what will actually be read.<br>",
    "- 대상 레이어가 너무 많거나 섞여 있으면, <b>대상 그룹/대상 레이어</b>를 지정해 범위를 좁히면 더 정확합니다.<br>": "- If there are too many target layers or they are mixed together, narrowing the scope with <b>Target Group / Target Layers</b> improves accuracy.<br>",
    "- <b>통계 CSV</b>는 AI 없이 AOI 주변 표준 통계를 CSV로 저장합니다.<br>": "- <b>Statistics CSV</b> saves standard AOI-neighborhood statistics as CSV without using AI.<br>",
    "- 레이어 이름/속성에 민감정보가 있으면 Gemini 모드 사용 시 전송될 수 있으니 주의하세요.<br>": "- If layer names or attributes contain sensitive information, be careful when using Gemini mode because they may be transmitted.<br>",
    "- 도면/Style 결과는 해석에 방해가 될 수 있어 기본적으로 제외(체크)하는 것을 권장합니다.": "- Styling / cartographic result layers can interfere with interpretation, so excluding them by default is recommended.",
}

_SEGMENT_ENGLISH_MAP.update(
    {
        "_음영기복": "_Hillshade",
        "_그레이": "_Gray",
        "_고도색상": "_Elevation_Colors",
        "_중심점_": "_Centers_",
        "_구역통계_": "_Zonal_Stats_",
        "비용표면_": "CostSurface_",
        "가시권_": "Viewshed_",
        "역방향_": "Reverse_",
        "관측반경_": "Observer_Range_",
        "_가중누적_": "_Weighted_Cumulative_",
        "_가중비율_": "_Weighted_Ratio_",
        "_불균등_": "_Asymmetry_",
        "_반경_": "_Radius_",
        "_테두리_": "_Outline_",
        "_단일점_": "_SinglePoint_",
        "_히구치_": "_Higuchi_",
        "관측점_번호_라벨": "Observer_Number_Label",
        "최소비용 네트워크(Least-cost Network)": "Least-cost Network",
        "비용표면/최소비용경로(LCP)": "Cost Surface / Least-cost Path (LCP)",
        "고고학적 가시권 분석": "Archaeological Viewshed Analysis",
        "공간/가시성 네트워크": "PPA / Visibility Network",
        "지형 단면 분석": "Terrain Profile Analysis",
        "<h3>최소비용 네트워크(Least-cost Network) 도움말</h3>": "<h3>Least-cost Network Help</h3>",
        "<h3>비용표면 / 최소비용경로(Cost Surface / LCP) 도움말</h3>": "<h3>Cost Surface / LCP Help</h3>",
        "<h3>가시권 분석(Viewshed / LOS) 도움말</h3>": "<h3>Viewshed / LOS Help</h3>",
        "<h3>근접/가시권 네트워크(Spatial / Visibility Network) 도움말</h3>": "<h3>PPA / Visibility Network Help</h3>",
        "<h2>지형 단면 (Terrain Profile)</h2>": "<h2>Terrain Profile</h2>",
        "<h2>도면 시각화 (Map Styling)</h2>": "<h2>Map Styling</h2>",
        "<h2>경사도/사면방향 도면화 (Slope/Aspect Drafting)</h2>": "<h2>Slope / Aspect Drafting</h2>",
        "<h3>기본 흐름</h3>": "<h3>Basic Workflow</h3>",
        "<h3>커스터마이즈</h3>": "<h3>Customization</h3>",
        "는 DEM 기반 이동비용 모델(시간/에너지)을 사용하여 유적들 사이의 최소비용 경로(LCP)를 계산하고, 그 결과로 <b>전체 연결망(MST)</b>·<b>k-최근접(k-NN)</b>·<b>허브 기반(Hub)</b> 네트워크를 생성합니다.": " uses a DEM-based movement-cost model (time / energy) to calculate least-cost paths (LCPs) between sites, then creates <b>network-wide MST</b>, <b>k-nearest-neighbor (k-NN)</b>, and <b>hub-based</b> networks.",
        "는 DEM 경사에 따른 이동 비용을 모델링하고, 출발점 기준 누적 비용(분)과 최소비용경로를 계산합니다.": " models movement cost from DEM slope and calculates cumulative cost (minutes) and least-cost paths from the start point.",
        "은 유적의 입지 특성을 파악하는 중요한 도구입니다. 이 도구는 관측점에서 보이는 영역(가시권)과 보이지 않는 영역(비가시권)을 계산합니다.": " is an important tool for understanding site location characteristics. It calculates visible and non-visible areas from observer points.",
        "는 유적(노드) 사이의 관계를 선(간선)으로 만들어 봅니다.": " turns relationships between sites (nodes) into lines (edges).",
        "지도상의 가상 절단선을 따라 고도 변화를 그래프로 시각화합니다.": "Visualizes elevation change along a virtual cross-section line on the map.",
        "한국 수치지형도(DXF) 레이어를 분류/집계하고, 도로·하천·건물 등 카토그래피 스타일을 적용합니다.": "Classifies and summarizes South Korean digital topographic map (DXF) layers and applies cartographic styles for roads, rivers, buildings, and more.",
        "AOI(작업영역)를 기준으로 인쇄용 경사 래스터와 사면방향(방위각) 화살표 레이어를 생성합니다.": "Creates print-ready slope rasters and aspect-arrow layers using the AOI (work area) as the target extent.",
        "수치지형도(DXF)에서 등고선만 필터링하거나, DEM에서 새로운 등고선을 생성합니다.": "Filters contour data from a topographic DXF or generates new contours from a DEM.",
        "DXF 코드 매핑은 <code>tools/map_styling_codes.json</code>에서 수정할 수 있습니다.": "DXF code mappings can be edited in <code>tools/map_styling_codes.json</code>.",
        "QML/프리셋 내보내기로 프로젝트 재사용성을 높일 수 있습니다.": "QML / preset export can improve project reusability.",
        "DEM 위에 단면선을 그려 고도 프로파일을 그래프로 표시하고, 통계/CSV/이미지로 내보냅니다.": "Draws a profile line on the DEM, displays the elevation profile as a graph, and exports statistics / CSV / images.",
        "<li>DEM 선택</li>": "<li>Select a DEM</li>",
        "<li>단면선 그리기(시작→끝)</li>": "<li>Draw a profile line (start -> end)</li>",
        "<li>(옵션) AOI/오버레이 레이어 표시</li>": "<li>(Optional) Show AOI / overlay layers</li>",
        "<li>CSV/이미지 내보내기</li>": "<li>Export CSV / image</li>",
        "<b>도면화(경사도/사면방향)</b>는 입력 DEM을 경사도/사면방향으로 변환한 뒤, 선택한 폴리곤 작업영역(AOI)만 도면화 레이어로 생성합니다.": "<b>Slope / Aspect Drafting</b> converts the input DEM to slope and aspect, then creates drafting layers only inside the selected polygon AOI.",
        "메모리 폴리곤 레이어를 생성해 작업영역(AOI)을 그릴 수 있게 합니다.": "Creates an in-memory polygon layer so you can draw the AOI.",
        "폴리곤 레이어에서 선택된 피처(들)만 작업영역으로 사용합니다.": "Uses only the selected polygon feature(s) as the AOI.",
        "같은 구간(예: 0~5°, 5~10°…)끼리 병합해 ‘구역’으로 만듭니다.": "Merges the same slope ranges (for example 0-5deg, 5-10deg) into zones.",
        "이 값 이하에서는 사면방향 화살표를 숨깁니다(평지는 방향 의미가 약함).": "Hides aspect arrows below this threshold because direction is less meaningful on flat ground.",
        "수치지형도(DXF)에서 등고선만 필터링하거나, DEM에서 새로운 등고선을 생성합니다.": "Filters contour data from a topographic DXF or generates new contours from a DEM.",
        "추출할 등고선 유형:": "Contour Types to Extract:",
        "주곡선 (F0017110) - 기본 등고선": "Index Contour (F0017110) - Base contour",
        "계곡선 (F0017111) - 굵은 선": "Valley Contour (F0017111) - Thick line",
        "간곡선 (F0017112) - 파선": "Intermediate Contour (F0017112) - Dashed line",
        "조곡선 (F0017113) - 점선": "Auxiliary Contour (F0017113) - Dotted line",
        "네트워크 방식: <b>MST</b>(전체 연결망 최소), <b>k-NN</b>(복수 경로), <b>Hub</b>(거점 기반), <b>A+B+C(All)</b>(한 번에 생성).": "Network modes: <b>MST</b> (minimum overall network), <b>k-NN</b> (multiple routes), <b>Hub</b> (hub-based), and <b>A+B+C (All)</b> (create everything at once).",
        "유형/위계(예: 왕성·빈전·고분군)별 비교는 ‘선택된 피처만’으로 원하는 조합을 선택해 여러 번 실행하면 해석이 쉽습니다.": "For comparisons by type / hierarchy (for example royal fortresses, palaces, tumulus groups), run the tool multiple times with different combinations using 'Use selected features only'.",
        "Tip: <b>해석 가이드</b> 버튼에서 상세 설명을 열 수 있습니다.": "Tip: use the <b>Interpretation Guide</b> button for detailed explanations.",
        "• <b>포인트</b>: 그대로 노드로 사용합니다.<br/>": "• <b>Points</b>: used directly as network nodes.<br/>",
        "• <b>폴리곤</b>: 대표점(권장: Point on surface)으로 노드를 만듭니다.<br/>": "• <b>Polygons</b>: converted to nodes using a representative point (recommended: Point on Surface).<br/>",
        "• <b>선택 피처만</b> 체크 시: 선택된 피처만 네트워크에 포함됩니다.": "• If <b>Use selected features only</b> is checked, only selected features are included in the network.",
        "• <b>후보 간선(k)</b>: 유클리드 기준으로 후보를 줄여 계산을 빠르게 합니다. 너무 작으면 연결이 끊겨 MST가 실패할 수 있습니다.<br/>": "• <b>Candidate edges (k)</b>: reduces candidates using Euclidean distance to speed up calculation. If too small, the network can disconnect and MST may fail.<br/>",
        "• <b>경로 버퍼(m)</b>: 각 후보쌍 LCP 계산창(bbox)에 여유를 줍니다. 너무 작으면 최적 경로가 창 밖으로 나가 실패할 수 있습니다.<br/>": "• <b>Path buffer (m)</b>: expands the LCP calculation window (bbox) around each candidate pair. If too small, the optimal path may fall outside the window and fail.<br/>",
        "• <b>대칭화(MST)</b>: 오르막/내리막 차이로 A→B와 B→A 비용이 다를 수 있어, MST는 (평균/최소/최대)로 한 값으로 만듭니다.<br/>": "• <b>Symmetrization (MST)</b>: because uphill / downhill costs can differ for A->B and B->A, the MST uses a single value (mean / min / max).<br/>",
        "• <b>A+B+C(All)</b>: MST/k-NN/Hub를 한 번에 생성합니다(Hub는 허브 값 설정 시).": "• <b>A+B+C (All)</b>: creates MST / k-NN / Hub at once (Hub only when hub values are configured).",
        "후보 간선(k)\n- 각 노드에서 유클리드 거리로 가까운 k개만 후보로 잡고 LCP를 계산합니다.\n- 값이 작을수록 빠르지만, 그래프가 끊겨 MST가 실패할 수 있습니다.\n- 200개+ 노드에서는 8~20부터 시도 후, 실패하면 k를 늘려보세요.": "Candidate edges (k)\n- For each node, only the k nearest neighbors by Euclidean distance are used as candidates for LCP.\n- Smaller values are faster but can disconnect the graph and break the MST.\n- For 200+ nodes, start around 8-20 and increase k if needed.",
        "경로 버퍼(m)\n- 후보쌍 두 점을 감싸는 bbox에 추가로 여유를 주는 값입니다.\n- 값이 너무 작으면 '진짜 최적 경로'가 창 밖으로 나가 경로가 끊길 수 있습니다.\n- 0은 DEM 전체를 사용(매우 느림)하므로 권장하지 않습니다.": "Path buffer (m)\n- Adds extra margin to the bbox around each candidate pair.\n- If too small, the true optimal path may leave the window and fail.\n- 0 uses the whole DEM (very slow), so it is not recommended.",
        "대각 이동 허용(8방향)\n- 격자 기반 경로에서 '계단 현상'을 줄이고 더 자연스러운 경로가 나올 수 있습니다.\n- 필요하면 꺼서(4방향) 비교해보세요.": "Allow diagonal movement (8 directions)\n- Can reduce stair-step artifacts in grid-based paths and produce more natural routes.\n- If needed, turn it off (4 directions) and compare results.",
        "MST 대칭화\n- 경사 때문에 A→B와 B→A 비용이 달라질 수 있습니다.\n- MST는 무방향 그래프가 필요하므로 한 값으로 합칩니다.\n  • 왕복 평균: (A→B + B→A)/2\n  • 편도 최소: min(A→B, B→A)\n  • 편도 최대: max(A→B, B→A)": "MST Symmetrization\n- Because slope can make A->B and B->A costs different,\n- the MST needs an undirected value, so they are merged into one.\n  • Round-trip mean: (A->B + B->A)/2\n  • One-way minimum: min(A->B, B->A)\n  • One-way maximum: max(A->B, B->A)",
        "k‑NN의 k\n- 각 노드에서 비용이 작은 상위 k개 노드로 연결합니다.\n- k가 작으면 네트워크가 끊길 수 있고, k가 크면 선이 많아집니다.": "k for k-NN\n- Connects each node to the top k lowest-cost nodes.\n- Small k can disconnect the network; large k creates many edges.",
        "선형 경로(도로, 해안선)나 성곽 둘레(Perimeter)를 따라 이동하며 보이는 영역을 분석합니다.": "Analyzes the visible area while moving along a linear path such as a road, coastline, or fortress perimeter.",
        "두 지점 사이의 시야가 확보되는지를 단면(프로파일)로 확인합니다.\n- 지도/프로파일 색상: 초록=보임, 빨강=안보임\n- 결과 Viscode 선을 선택하면 프로파일을 다시 열 수 있습니다.": "Checks whether line of sight is preserved between two points using a profile.\n- Map / profile colors: green = visible, red = blocked\n- Selecting the resulting Viscode line reopens the profile.",
        "<h3 style='margin:0 0 6px 0;'>곡률/굴절(대기굴절) 보정</h3>": "<h3 style='margin:0 0 6px 0;'>Curvature / Refraction Correction</h3>",
        "<b>현재 설정</b><br>": "<b>Current Settings</b><br>",
        "- 곡률 하강량: Δh ~ d²/(2R), R=6,371km<br>": "- Curvature drop: Δh ~ d²/(2R), R = 6,371 km<br>",
        "- 굴절 포함: Δh ~ d²/(2R) · cc, (곡률 ON일 때) cc=1-k<br>": "- With refraction: Δh ~ d²/(2R) · cc, and when curvature is ON, cc = 1 - k<br>",
        "- GDAL 기본값: cc=0.85714(~6/7 → k~0.14286)<br><br>": "- GDAL default: cc = 0.85714 (~6/7 -> k ~ 0.14286)<br><br>",
        "- d² 비례라 반경이 짧으면(예: 1km) 체크해도 결과가 거의 안 바뀔 수 있음<br><br>": "- Because the effect scales with d², short radii (for example 1 km) may show almost no visible difference even when enabled.<br><br>",
        "PPA(Proximal Point Analysis)\n- 지형(DEM) 비용을 쓰지 않고, 유클리드 거리(직선거리)로 최근접 k개를 연결합니다.\n- k가 작을수록(예: 3~5) 현실적인 '이웃망' 형태가 되며, k가 크면 간선이 급격히 늘어납니다.\n- 본 도구는 SciPy(KDTree) 같은 외부 의존성 없이 동작합니다.": "PPA (Proximal Point Analysis)\n- Connects the k nearest neighbors using Euclidean distance, without DEM-based movement cost.\n- Smaller k values (for example 3-5) often produce a realistic neighborhood network, while larger k quickly increases edge counts.\n- This tool works without external dependencies such as SciPy (KDTree).",
        "가시성 네트워크(Visibility / LOS)\n- DEM 기반 Line of Sight(가시선)으로 두 유적 사이에 지형이 시선을 가리는지 샘플링하여 판정합니다.\n- 결과 레이어는 '보임/안보임'을 색상으로 구분하고, 거리(km)는 속성(dist_km)으로 저장됩니다.\n- 계산량이 커질 수 있으므로 '후보 k'와 '최대거리'로 후보 쌍을 줄이는 것을 권장합니다.": "Visibility Network (LOS)\n- Uses DEM-based line of sight to sample whether terrain blocks visibility between sites.\n- Result layers distinguish visible / blocked edges by color, and store distance (km) in the `dist_km` field.\n- Because computation can be heavy, using 'candidate k' and 'maximum distance' to reduce candidate pairs is recommended.",
        "각 유적(노드)에서 연결할 최근접 이웃 수 k입니다. (권장 3~5)": "Number of nearest neighbors k to connect from each site (node). (Recommended: 3-5)",
        "상호 최근접(Mutual)일 때만 간선을 남깁니다.\n예) A의 최근접에 B가 포함되고, B의 최근접에도 A가 포함될 때만 연결.": "Keeps edges only when the relationship is mutual.\nExample: connect A and B only when B is among A's nearest neighbors and A is among B's nearest neighbors.",
        "가시성 네트워크에서 '연결'로 간주할 규칙입니다.\n- Mutual: A↔B 모두 보일 때만 연결\n- Either: A→B 또는 B→A 중 하나라도 보이면 연결": "Rule used to decide whether an edge counts as 'connected' in the visibility network.\n- Mutual: connect only if A<->B are both visible\n- Either: connect if either A->B or B->A is visible",
        "폴리곤을 노드(점)로 변환할 때 대표점을 선택합니다.\n- Point on surface: 폴리곤 내부 보장(권장)\n- Centroid: 중심점(폴리곤이 오목하면 밖으로 나갈 수 있음)": "Choose how polygons are converted to node points.\n- Point on surface: guaranteed to be inside the polygon (recommended)\n- Centroid: geometric center (can fall outside for concave polygons)",
        "관측자 높이(m): DEM 지표면 위 추가 높이.": "Observer height (m): additional height above the DEM surface.",
        "대상 높이(m): DEM 지표면 위 추가 높이.": "Target height (m): additional height above the DEM surface.",
        "각 노드에서 LOS 후보로 검사할 최근접 이웃 수입니다.\n값이 커질수록 정확도는 올라가지만 계산 시간이 증가합니다.": "Number of nearest neighbors checked as LOS candidates from each node.\nLarger values improve coverage but increase computation time.",
        "최대 검사 거리(m). 0이면 제한 없음.\n거리 제한을 두면 계산량이 크게 줄어듭니다.": "Maximum search distance (m). 0 means unlimited.\nApplying a distance limit can reduce computation substantially.",
        "LOS 샘플링 간격(m). 작을수록 정확하지만 느립니다.\n0 또는 너무 작으면 DEM 픽셀 크기를 기준으로 자동 보정됩니다.": "LOS sampling interval (m). Smaller values are more accurate but slower.\nIf 0 or too small, it is adjusted automatically using the DEM pixel size.",
        "체크하면 후보 k 제한을 무시하고 (최대 거리 내) 모든 쌍을 LOS로 검사합니다.\n노드가 많으면 시간이 오래 걸릴 수 있습니다.": "When checked, ignores the candidate-k limit and tests LOS for all pairs within the maximum distance.\nThis can take a long time when there are many nodes.",
        "입력 레이어가 폴리곤일 때, 대표점 1개가 아니라 폴리곤 경계를 샘플링해\n가시성 비율(vis_ratio, 0~1)을 계산합니다. (느릴 수 있음)": "When the input layer is polygonal, samples the polygon boundary instead of using a single representative point,\nand calculates a visibility ratio (`vis_ratio`, 0-1). (May be slow.)",
        "폴리곤 경계에서 샘플 점을 뽑는 간격(m)입니다.": "Sampling interval (m) used along polygon boundaries.",
        "폴리곤 1개당 경계 샘플 점의 최대 개수(속도 제한)입니다.": "Maximum number of boundary sample points per polygon (speed cap).",
        "<b>지구화학도 래스터 수치화</b><br>": "<b>GeoChem Raster Recovery</b><br>",
        "워크플로우:\n1) RGB 지구화학도(WMS/래스터)를 조사지역 경계(사각형)로 잘라 GeoTIFF로 저장\n2) RGB → 값(%) 래스터로 변환(범례 기반)\n3) (옵션) 값 → 구간(class) 래스터 생성\n4) (옵션) 구간 폴리곤 생성 + dissolve\n5) (옵션) 중심점(포인트) 생성": "Workflow:\n1) Clip the RGB geochemical raster (WMS / raster) to the AOI bounding box and save as GeoTIFF\n2) Convert RGB -> value (%) raster using the legend\n3) (Optional) Create a class raster from the value raster\n4) (Optional) Create dissolved class polygons\n5) (Optional) Create center points",
        "0이면 현재 지도 해상도(캔버스 mapUnitsPerPixel)를 사용합니다.": "0 uses the current map resolution (`mapUnitsPerPixel`) from the canvas.",
        "조사지역 경계(사각형)의 바깥쪽으로 버퍼(m)를 줍니다. 0이면 버퍼 없음.": "Adds a buffer (m) outside the AOI bounding rectangle. 0 means no buffer.",
        "조사지역 폴리곤 내부만 유효값으로 두고 바깥은 NoData로 처리합니다. (분석/중심점 계산에 권장)": "Keeps valid values only inside the AOI polygon and treats the outside as NoData. (Recommended for analysis / center calculation.)",
        "범례의 최저값(보통 회색)은 실제 데이터가 아닌 배경/무자료로 보고 NoData(-9999)로 처리합니다.": "Treats the legend's lowest value (often gray) as background / no-data rather than real data, and stores it as NoData (-9999).",
        "색상 매칭 결과의 최댓값이 범례 최댓값보다 낮게 나오면, 전체를 비례 스케일합니다.": "If the highest matched value falls below the legend maximum, rescales the whole output proportionally.",
        "마지막 구간(예: 12~51)에서 일정 이상이면 최댓값으로 강제합니다. (로컬 보정)": "If the last class (for example 12-51) exceeds a threshold, snaps it to the maximum value. (Local correction.)",
        "마지막 구간에서 t(0~1)가 이 값보다 크면 최댓값으로 스냅합니다.": "In the last class, snap to the maximum value when t (0-1) is above this threshold.",
        "첫 점 이후 두 번째 클릭은 '방향'만 결정하고, 길이는 고정 길이(m)로 맞춥니다.\n비교 단면(같은 길이/같은 샘플 수)을 여러 개 만들 때 유용합니다.": "After the first point, the second click determines only the direction, and the line length is forced to the fixed length (m).\nUseful when creating multiple comparable profiles with the same length and sample count.",
        "고정 길이(m). 0이면 적용되지 않습니다.": "Fixed length (m). Disabled when set to 0.",
        "가장 최근에 만든 단면선 길이를 고정 길이에 적용합니다.": "Applies the length of the most recently created profile line to the fixed-length setting.",
        "조사대상지(AOI) 폴리곤 레이어를 선택하세요.\n- 선택 피처가 있으면 선택 피처만 사용합니다.\n- 단면 그래프에 AOI 내부 구간을 음영으로 표시할 수 있습니다.": "Select an AOI polygon layer.\n- If features are selected, only the selected features are used.\n- AOI segments can be shaded on the profile graph.",
        "단면선이 AOI 내부를 지나는 구간을 그래프 배경(음영)으로 표시합니다.\n표시는 샘플링 점 기준으로 계산됩니다(샘플 수가 높을수록 경계가 정밀).": "Shades the parts of the profile line that pass inside the AOI in the graph background.\nThis is computed from sampling points, so higher sample counts produce more precise boundaries.",
        "단면 프로파일에서 다음 통계를 계산합니다.\n- 구간별 평균 경사(예: 0–200m)\n- 누적 상승/하강\nCSV 저장 시 구간 요약표도 함께 저장됩니다.": "Calculates the following profile statistics.\n- Mean slope by segment (for example 0-200 m)\n- Cumulative ascent / descent\nWhen saving CSV, the segment summary table is exported as well.",
        "구간 통계에 사용할 거리 간격(m).\n예: 200m -> 0–200m, 200–400m ... 구간별 평균 경사.\n0이면 구간 통계를 계산하지 않습니다.": "Distance interval (m) used for segment statistics.\nExample: 200 m -> 0-200 m, 200-400 m, ... with mean slope per segment.\n0 disables segment statistics.",
        "TIP: value 비교용으로 같은 길이 단면을 만들거나,\nAOI 단면이라면 그래프에서 AOI 구간(배경 음영)을 확인할 수 있습니다.": "TIP: create profiles with the same length for comparison,\nor check AOI segments (background shading) on the graph when profiling an AOI.",
        "선택한 벡터 레이어를 단면 그래프에 표시합니다.\n- 면(폴리곤): 단면선이 내부를 지나는 구간을 배경(음영)으로 표시\n- 점/선: 단면선과 교차(또는 근접)하는 지점을 마커로 표시": "Displays selected vector layers on the profile graph.\n- Polygon: shades the sections where the profile line passes inside the polygon\n- Point / line: shows markers where the profile line intersects or approaches them",
        "단면에 표시할 벡터 레이어를 선택하세요.": "Select vector layers to display on the profile.",
        "레이어에서 선택한 피처만 단면 표시 대상으로 사용합니다.": "Uses only the selected features in each layer for profile display.",
        "TIP: 점/선 레이어는 교차지점 마커로, 폴리곤 레이어는 내부 구간 음영으로 표시됩니다.": "TIP: point / line layers appear as intersection markers, while polygon layers appear as shaded segments.",
        "현재 그래프/임시 표시만 초기화합니다. 저장된 단면선 레이어는 유지됩니다.": "Resets only the current graph and temporary display. Saved profile-line layers are kept.",
        "단면선을 '1개=1개 레이어'로도 추가합니다.\n레이어 패널에서 해당 레이어를 클릭(현재 레이어)하면 단면 그래프가 자동으로 열립니다.\n많이 생성하면 레이어가 많아질 수 있어 필요할 때만 켜세요.": "Also adds each profile line as its own layer.\nClicking that layer in the layer panel (current layer) automatically opens the profile graph.\nBecause this can create many layers, enable it only when needed.",
        "💡 삼각망 기반 선형 보간. 등고선 데이터에 적합 [Delaunay, 1934]": "Triangulation-based linear interpolation. Well suited to contour data. [Delaunay, 1934]",
        "💡 삼각망 기반 곡면 보간. 부드러운 지형 표현 [Clough & Tocher, 1965]": "Triangulation-based curved-surface interpolation. Produces smoother terrain. [Clough & Tocher, 1965]",
        "💡 포인트 데이터에 적합, 등고선에는 비추천 [Shepard, 1968]": "Suited to point data and generally not recommended for contours. [Shepard, 1968]",
        "💡 포인트 기반 Ordinary Kriging(Lite). 자동 파라미터 + 예측 DEM + 분산(_variance.tif) 출력. 미터 단위 투영 CRS 권장 [Matheron, 1963; Cressie, 1993]": "Point-based Ordinary Kriging (Lite). Uses automatic parameters and outputs a predicted DEM plus variance (`_variance.tif`). A projected CRS in meters is recommended. [Matheron, 1963; Cressie, 1993]",
        "지구 곡률 보정(평면 가정 해제)\n- 곡률 하강량(근사): Δh ≈ d²/(2R)\n- R: 지구 반경(약 6,371km)\n- 효과는 거리(d)의 제곱에 비례하므로, 반경이 짧으면 결과가 거의 안 바뀔 수 있습니다.": "Earth Curvature Correction (beyond the flat-earth assumption)\n- Approximate curvature drop: Δh ≈ d²/(2R)\n- R: Earth's radius (about 6,371 km)\n- Because the effect grows with the square of distance, short radii may show almost no visible change.",
        "대기 굴절 보정(표준대기 근사)\n- 굴절계수 k(기본 0.13): 빛이 아래로 휘는 정도(곡률 효과를 일부 상쇄)\n- k↑ → 곡률 보정량↓ → 원거리에서 '더 보임' 쪽으로 결과가 바뀔 수 있음\n- k↓ → 곡률 보정량↑ → 원거리에서 '덜 보임' 쪽으로 결과가 바뀔 수 있음\n※ 굴절은 곡률과 함께 의미가 있어, 일반적으로 곡률 보정과 같이 사용합니다.": "Atmospheric Refraction Correction (standard-atmosphere approximation)\n- Refraction coefficient k (default 0.13): how much light bends downward and partially offsets curvature\n- Higher k -> less effective curvature correction -> distant areas may appear more visible\n- Lower k -> stronger effective curvature correction -> distant areas may appear less visible\nRefraction is normally meaningful together with curvature correction, so they are usually used together.",
        "팁: 정확한 클릭을 원하면 포인트(점) 벡터 레이어를 만든 뒤 스냅(자석 아이콘)을 켜고 찍으세요.\n레이어에서 직접 선택(관측점/대상점 지정) 기능은 단순화를 위해 현재 비활성화되어 있습니다.": "Tip: for precise clicks, create a point vector layer first and enable snapping (magnet icon).\nDirect selection from a layer (for observer / target assignment) is currently disabled to keep the workflow simpler.",
        "팁: 점=1회 클릭 후 우클릭/Enter로 완료, 폴리곤=여러 점(3점 이상) 찍고 우클릭/Enter로 완료.\n기존 폴리곤 위를 클릭하면 해당 폴리곤이 자동 선택됩니다.\n직접 그리려면 Shift를 누른 채 첫 점을 찍으세요.": "Tip: point = click once, then right click / Enter to finish; polygon = click multiple points (3 or more), then right click / Enter.\nClicking an existing polygon selects it automatically.\nTo draw manually, hold Shift while placing the first point.",
        "네트워크를 '선 몇 개'가 아니라, 각 노드의 구조적 역할로 해석할 수 있게 지표를 계산합니다.\n- degree: 연결 수\n- component/comp_size: 연결된 덩어리(컴포넌트)와 크기\n- (선택) closeness/betweenness: 가중치(시간/에너지) 기반 중심성(느릴 수 있음)": "Calculates metrics that let you interpret the network not just as a set of lines, but in terms of each node's structural role.\n- degree: number of links\n- component / comp_size: connected component and its size\n- (Optional) closeness / betweenness: weighted centrality based on time / energy (may be slow)",
        "근접 중심성(closeness): 다른 노드까지의 최단 비용 합이 작을수록 값이 커집니다.\n가중치(시간/에너지) 기반으로 계산하며, 노드 수가 크면 느릴 수 있습니다.": "Closeness centrality: grows when the total shortest-path cost to other nodes is smaller.\nCalculated from weighted costs (time / energy) and may be slow for large node sets.",
        "매개 중심성(betweenness): 다른 노드 쌍의 최단 비용 경로를 '중개'하는 정도입니다.\n가중치(시간/에너지) 기반이며, 큰 데이터에서는 자동으로 생략될 수 있습니다.": "Betweenness centrality: measures how much a node mediates the shortest-cost paths between other node pairs.\nAlso weighted by time / energy and may be skipped automatically on large datasets.",
        "PPA 간선(그래프) 생성 규칙입니다.\n- k-NN: 각 노드에서 가까운 k개 연결\n- Threshold: 반경 내 모든 쌍 연결\n- Delaunay/Gabriel/RNG: 스파게티(과도한 간선)를 줄이는 대표적인 근접 그래프": "Rule used to generate PPA edges.\n- k-NN: connect the k nearest neighbors from each node\n- Threshold: connect all pairs within the radius\n- Delaunay / Gabriel / RNG: representative proximity graphs that reduce 'spaghetti' over-connection",
        "PPA 최대 거리(m) 필터입니다. 0이면 제한 없음.\nThreshold 그래프에서는 필수 파라미터(0이면 오류)입니다.": "Maximum-distance filter (m) for PPA. 0 means no limit.\nFor threshold graphs, this parameter is required (0 is invalid).",
        "Mutual(상호 보임)만 연결\n- A↔B 양방향 모두 보일 때만 간선으로 간주합니다.\n- '확실한 통신/감시' 관계만 남기고 싶을 때 권장.": "Mutual visibility only\n- Counts an edge only when both A<->B directions are visible.\n- Recommended when you want to keep only robust communication / surveillance links.",
        "Either(단방향 포함)\n- A→B 또는 B→A 중 하나라도 보이면 간선으로 간주합니다.\n- 지형/높이 차로 단방향이 생길 수 있는 상황에서 탐색적으로 유용.": "Either direction\n- Counts an edge when either A->B or B->A is visible.\n- Useful for exploratory work when terrain or height differences may create one-way visibility.",
    }
)

_SEGMENT_ENGLISH = tuple(sorted(_SEGMENT_ENGLISH_MAP.items(), key=lambda item: len(item[0]), reverse=True))

_REGEX_ENGLISH = (
    (re.compile(r"^\(권장: (?P<value>.+)\)$"), "(Recommended: {value})"),
    (re.compile(r"^완료: (?P<rest>.+)$"), "Done: {rest}"),
    (re.compile(r"^저장했습니다: (?P<rest>.+)$"), "Saved: {rest}"),
    (re.compile(r"^저장 실패: (?P<rest>.+)$"), "Save failed: {rest}"),
    (re.compile(r"^파일 저장 실패: (?P<rest>.+)$"), "File save failed: {rest}"),
    (re.compile(r"^이미지 저장에 실패했습니다\.$"), "Failed to save the image."),
    (re.compile(r"^이미지 저장 중 오류: (?P<rest>.+)$"), "Error while saving the image: {rest}"),
    (re.compile(r"^처리 중 오류: (?P<rest>.+)$"), "Processing error: {rest}"),
    (re.compile(r"^분석 중 오류: (?P<rest>.+)$"), "Analysis error: {rest}"),
    (re.compile(r"^병합 중 오류: (?P<rest>.+)$"), "Merge error: {rest}"),
    (re.compile(r"^역방향 가시권 처리 중 오류: (?P<rest>.+)$"), "Reverse viewshed error: {rest}"),
    (re.compile(r"^CSV 저장 실패: (?P<rest>.+)$"), "CSV save failed: {rest}"),
    (re.compile(r"^폴더 생성 실패: (?P<rest>.+)$"), "Folder creation failed: {rest}"),
    (re.compile(r"^결과 레이어 추가 실패: (?P<rest>.+)$"), "Failed to add result layer: {rest}"),
    (re.compile(r"^파일: (?P<rest>.+)$"), "File: {rest}"),
    (re.compile(r"^이미지: (?P<rest>.+)$"), "Image: {rest}"),
    (re.compile(r"^(?P<count>\d+)개 레이어 필터 초기화 완료$"), "Reset layer filters for {count} layers"),
    (re.compile(r"^관측점이 (?P<count>\d+)개로 샘플링되었습니다\.$"), "Observer points were sampled to {count} points."),
    (re.compile(r"^대상점이 (?P<count>\d+)개로 샘플링되었습니다\.$"), "Target points were sampled to {count} points."),
)

_REGEX_ENGLISH = _REGEX_ENGLISH + (
    (re.compile(r"^(?P<count>\d+)개 선택됨: (?P<summary>.+)$"), "{count} selected: {summary}"),
    (re.compile(r"^(?P<count>\d+)개 선택됨$"), "{count} selected"),
    (re.compile(r"^그룹 (?P<num>\d+)$"), "Group {num}"),
    (re.compile(r"^전문가 (?P<num>\d+)명$"), "{num} Experts"),
    (re.compile(r"^AHP 일관성비율\(CR\)이 높습니다: (?P<rest>.+)$"), "AHP consistency ratio (CR) is high: {rest}"),
    (re.compile(r"^선택된 관측점: (?P<count>\d+)개$"), "Selected Observers: {count}"),
    (re.compile(r"^그려진 경로: (?P<count>\d+)개 정점 \(폐곡선\)$"), "Drawn Path: {count} vertices (closed)"),
    (re.compile(r"^그려진 경로: (?P<count>\d+)개 정점 \(개곡선\)$"), "Drawn Path: {count} vertices (open)"),
    (re.compile(r"^선택된 위치: (?P<x>[^,]+), (?P<y>.+)$"), "Selected Location: {x}, {y}"),
    (re.compile(r"^직선거리: (?P<dist>.+) \(지도 CRS 단위\)$"), "Straight-line Distance: {dist} (map CRS units)"),
    (re.compile(r"^구형 모델 ID를 최신 ID로 바꿔 저장했습니다: (?P<old>.+) -> (?P<new>.+)$"), "Saved with the latest model ID instead of the legacy ID: {old} -> {new}"),
    (re.compile(r"^구형 모델 ID를 최신 ID로 바꿔 사용합니다: (?P<old>.+) -> (?P<new>.+)$"), "Using the latest model ID instead of the legacy ID: {old} -> {new}"),
    (re.compile(r"^CSV 저장 완료: (?P<a>.+), (?P<b>.+)$"), "CSV saved: {a}, {b}"),
    (re.compile(r"^완료\(경고 (?P<count>\d+)개\): (?P<rest>.+)$"), "Done ({count} warnings): {rest}"),
    (re.compile(r"^ZIP에서 (?P<count>\d+)개 레이어를 로드했습니다\.$"), "Loaded {count} layers from the ZIP."),
    (re.compile(r"^프리셋을 저장했습니다: (?P<rest>.+)$"), "Saved the preset: {rest}"),
    (re.compile(r"^통합 레이어가 생성되었습니다: (?P<rest>.+)$"), "Merged layers created: {rest}"),
    (re.compile(r"^스타일 적용 중 오류: (?P<rest>.+)$"), "Error while applying styling: {rest}"),
    (re.compile(r"^래스터 생성: (?P<rest>.+)$"), "Raster created: {rest}"),
    (re.compile(r"^래스터 변환 실패: (?P<rest>.+)$"), "Raster conversion failed: {rest}"),
    (re.compile(r"^처리 실패: (?P<rest>.+)$"), "Processing failed: {rest}"),
    (re.compile(r"^프로파일 계산 실패: (?P<rest>.+)$"), "Profile calculation failed: {rest}"),
    (re.compile(r"^AHP 실행 실패: (?P<rest>.+)$"), "AHP execution failed: {rest}"),
    (re.compile(r"^최소비용경로 프로파일 \(LCP Profile\) - (?P<model>.+)$"), "Least-cost Path Profile (LCP Profile) - {model}"),
    (re.compile(r"^LCP 마일스톤 \((?P<dist>[^)]+)\) - (?P<model>.+)$"), "LCP Milestones ({dist}) - {model}"),
    (re.compile(r"^가시권_가중비율_(?P<count>\d+)개점$"), "Viewshed_Weighted_Ratio_{count}pts"),
    (re.compile(r"^가시권_가중누적_(?P<count>\d+)개점$"), "Viewshed_Weighted_Cumulative_{count}pts"),
    (re.compile(r"^가시권_누적_(?P<count>\d+)개점$"), "Viewshed_Cumulative_{count}pts"),
    (re.compile(r"^(?P<prefix>.+)_음영기복$"), "{prefix}_Hillshade"),
    (re.compile(r"^(?P<prefix>.+)_그레이$"), "{prefix}_Gray"),
    (re.compile(r"^(?P<prefix>.+)_고도색상$"), "{prefix}_Elevation_Colors"),
    (re.compile(r"^(?P<prefix>.+)_중심점_(?P<run>.+)$"), "{prefix}_Centers_{run}"),
    (re.compile(r"^(?P<prefix>.+)_구역통계_(?P<run>.+)$"), "{prefix}_Zonal_Stats_{run}"),
    (re.compile(r"^노드 (?P<nodes>\d+)개 / 간선 (?P<edges>\d+)개 생성$"), "Created {nodes} nodes / {edges} edges"),
    (re.compile(r"^노드 (?P<nodes>\d+)개 / 간선 (?P<edges>\d+)개 생성 \(DEM 범위/NoData로 (?P<removed>\d+)개 제외\)$"), "Created {nodes} nodes / {edges} edges ({removed} excluded by DEM extent / NoData)"),
    (re.compile(r"^(?P<count>\d+)개 DXF 로드 완료: 총 (?P<total>\d+)개 피처$"), "Loaded {count} DXF files: {total} total features"),
    (re.compile(r"^(?P<count>\d+)개 레이어 병합 중\.\.\.$"), "Merging {count} layers..."),
    (re.compile(r"^(?P<method>.+) 보간 실행 중\.\.\.$"), "Running {method} interpolation..."),
    (re.compile(r"^DEM 생성 완료! \((?P<count>\d+)개 레이어 병합\)$"), "DEM generation complete! ({count} layers merged)"),
    (re.compile(r"^Kriging 처리 중 오류: (?P<rest>.+)$"), "Kriging error: {rest}"),
    (re.compile(r"^(?P<path>.+) 로드 실패$"), "Failed to load {path}"),
    (re.compile(r"^(?P<count>\d+)개 유효 샘플 추출 완료!$"), "Extracted {count} valid samples."),
    (re.compile(r"^(?P<count>\d+)개 샘플 추출 중\.\.\.$"), "Extracting {count} samples..."),
    (re.compile(r"^계산 실패: (?P<rest>.+)$"), "Calculation failed: {rest}"),
    (re.compile(r"^KIGAM ZIP 임시 폴더 생성 실패: (?P<rest>.+)$"), "Failed to create the temporary KIGAM ZIP folder: {rest}"),
    (re.compile(r"^KIGAM ZIP 추출 실패: (?P<rest>.+)$"), "Failed to extract the KIGAM ZIP: {rest}"),
    (re.compile(r"^KIGAM 레이어 로드 실패: (?P<rest>.+)$"), "Failed to load a KIGAM layer: {rest}"),
    (re.compile(r"^KIGAM 스타일 적용 실패: (?P<rest>.+)$"), "Failed to apply KIGAM style: {rest}"),
    (re.compile(r"^KIGAM QML 스타일 적용: (?P<rest>.+)$"), "Applied KIGAM QML style: {rest}"),
    (re.compile(r"^코드 매핑 저장: (?P<rest>.+)$"), "Saved code mapping: {rest}"),
    (re.compile(r"^(?P<layer>.+): 필드 없음, 건너뜀$"), "{layer}: field not found, skipping"),
    (re.compile(r"^병합 레이어 생성 실패\(메모리 레이어 초기화 실패\): geom=(?P<rest>.+)$"), "Failed to create merged layer (memory-layer initialization failed): geom={rest}"),
    (re.compile(r"^지오메트리 타입 불일치: (?P<rest>.+)$"), "Geometry type mismatch: {rest}"),
    (re.compile(r"^결과 레이어 추가 실패: (?P<rest>.+)$"), "Failed to add result layer: {rest}"),
    (re.compile(r"^직선거리: (?P<value>.+)$"), "Straight-line Distance: {value}"),
    (re.compile(r"^시작점: (?P<x>[-0-9.]+), (?P<y>[-0-9.]+)$"), "Start Point: {x}, {y}"),
    (re.compile(r"^도착점: (?P<x>[-0-9.]+), (?P<y>[-0-9.]+)$"), "End Point: {x}, {y}"),
    (re.compile(r"^반경 (?P<dist>[^:]+): 곡률 하강 (?P<a>[^ ]+)m → 적용 (?P<b>[^ ]+)m$"), "Radius {dist}: curvature drop {a} m -> applied {b} m"),
    (re.compile(r"^분석 영역이 너무 큽니다\(약\s*(?P<cells>.+?)\s*cells\)\. 분석 제한\(m\)을 0보다 크게 설정해 영역을 줄이거나 DEM을 클립하세요\.$"), "The analysis area is too large (about {cells} cells). Reduce it by setting Analysis Limit (m) above 0 or clipping the DEM."),
    (re.compile(r"^후보 쌍 중 일부의 분석 창이 너무 큽니다 \((?P<cells>.+?) cells\)\. 경로 버퍼\(m\)를 줄이거나 후보 간선\(k\)를 줄이세요\.$"), "Some candidate-pair analysis windows are too large ({cells} cells). Reduce the path buffer (m) or candidate edges (k)."),
    (re.compile(r"^Style: 배경 지형 \((?P<rest>.+)\)$"), "Style: Background Terrain ({rest})"),
    (re.compile(r"^매핑 파일이 없습니다: (?P<rest>.+)$"), "Mapping file not found: {rest}"),
    (re.compile(r"^매핑 파일을 읽는 중 오류: (?P<rest>.+)$"), "Error while reading the mapping file: {rest}"),
    (re.compile(r"^기본 매핑으로 대체했습니다: (?P<rest>.+)$"), "Fell back to the default mapping: {rest}"),
    (re.compile(r"^시각화 완료$"), "Styling Complete"),
    (re.compile(r"^KIGAM rasterize preflight 실패: (?P<rest>.+)$"), "KIGAM rasterize preflight failed: {rest}"),
    (re.compile(r"^gdal:rasterize 실패: (?P<rest>.+)$"), "gdal:rasterize failed: {rest}"),
    (re.compile(r"^KIGAM rasterize 재시도 실패: (?P<rest>.+)$"), "KIGAM rasterize retry failed: {rest}"),
    (re.compile(r"^근접성 네트워크 생성 중\.\.\. \(노드 (?P<nodes>\d+), 간선 (?P<edges>\d+)\)$"), "Building proximity network... ({nodes} nodes, {edges} edges)"),
    (re.compile(r"^완료: 노드 (?P<nodes>\d+) / 간선 (?P<edges>\d+)\s+\(평균 degree (?P<degree>[^,]+), components (?P<components>\d+)\)$"), "Done: {nodes} nodes / {edges} edges (mean degree {degree}, components {components})"),
    (re.compile(r"^가시성 네트워크\(LOS\) 계산 중\.\.\. \(쌍 (?P<count>\d+)개 검사\)$"), "Calculating visibility network (LOS)... (testing {count} pairs)"),
    (re.compile(r"^완료: 검사쌍 (?P<count>\d+)개 \(상호보임 (?P<mutual>\d+), 단방향 (?P<oneway>\d+), 상호안보임 (?P<hidden>\d+), 실패 (?P<failed>\d+)\)(?P<suffix>.*)$"), "Done: tested {count} pairs (mutual {mutual}, one-way {oneway}, hidden {hidden}, failed {failed}){suffix}"),
    (re.compile(r"^도면화 실패: (?P<rest>.+)$"), "Draft output failed: {rest}"),
    (re.compile(r"^생성될 경사도 격자\(폴리곤\)가 너무 많습니다: 약 (?P<approx>[\d,]+)개 \(최대 (?P<max>[\d,]+)개\)\. 표시 간격\(셀\)을 늘려주세요\.$"), "Too many slope-grid polygons would be created: about {approx} (maximum {max}). Increase the display interval (cells)."),
    (re.compile(r"^생성될 화살표 점이 너무 많습니다: 약 (?P<approx>[\d,]+)개 \(최대 (?P<max>[\d,]+)개\)\. 표시 간격\(셀\)을 늘려주세요\.$"), "Too many arrow points would be created: about {approx} (maximum {max}). Increase the display interval (cells)."),
    (re.compile(r"^▶ 점 (?P<count>\d+) 추가됨\. 계속 클릭하거나 ESC로 완료$"), "Point {count} added. Keep clicking or press ESC to finish."),
    (re.compile(r"^관측점→대상점: \((?P<ox>[^,]+),(?P<oy>[^)]+)\) → \((?P<tx>[^,]+),(?P<ty>[^)]+)\)$"), "Observer -> Target: ({ox},{oy}) -> ({tx},{ty})"),
    (re.compile(r"^선택된 폴리곤: (?P<name>.+) \(FID: (?P<fid>.+)\)$"), "Selected Polygon: {name} (FID: {fid})"),
    (re.compile(r"^선택된 폴리곤: (?P<name>.+)$"), "Selected Polygon: {name}"),
    (re.compile(r"^선택된 경로: (?P<count>\d+)개 정점 \(폐곡선\)$"), "Selected Path: {count} vertices (closed)"),
    (re.compile(r"^선택된 경로: (?P<count>\d+)개 정점 \(개곡선\)$"), "Selected Path: {count} vertices (open)"),
    (re.compile(r"^직시 가능 \(보임\) \| 거리: (?P<dist>.+)$"), "Visible | Distance: {dist}"),
    (re.compile(r"^직시 불가 \(안보임\) \| 장애물: (?P<dist>.+) \(고도 (?P<elev>.+)\)$"), "Blocked | Obstruction: {dist} (elevation {elev})"),
    (re.compile(r"^Gemini 모델 (?P<count>\d+)개 확인$"), "Verified {count} Gemini models"),
    (re.compile(r"^Gemini 모델 (?P<count>\d+)개 확인 / 현재 입력 모델 미확인: (?P<model>.+)$"), "Verified {count} Gemini models / current model not verified: {model}"),
    (re.compile(r"^min/max 통계가 없습니다: (?P<layer>.+)$"), "No min/max statistics are available: {layer}"),
    (re.compile(r"^(?P<count>\d+)개 포인트 샘플링 완료, 평균=(?P<mean>[^,]+), 50/70/90% 도달률=(?P<a>[^/]+)/(?P<b>[^/]+)/(?P<c>.+)$"), "Sampled {count} validation points, mean={mean}, hit rate at 50/70/90%={a}/{b}/{c}"),
)


def normalize_ui_language(code: str | None) -> str:
    raw = str(code or "").strip().lower()
    if raw == _LANGUAGE_EN:
        return _LANGUAGE_EN
    return _LANGUAGE_KO


def get_ui_language() -> str:
    try:
        return normalize_ui_language(QSettings().value(_SETTINGS_KEY, _LANGUAGE_KO))
    except Exception:
        return _LANGUAGE_KO


def set_ui_language(code: str | None) -> str:
    normalized = normalize_ui_language(code)
    try:
        QSettings().setValue(_SETTINGS_KEY, normalized)
    except Exception:
        pass
    return normalized


def is_english_ui() -> bool:
    return get_ui_language() == _LANGUAGE_EN


def tr(text, **kwargs) -> str:
    source = "" if text is None else str(text)
    translated = _translate_text(source)
    if kwargs:
        try:
            return translated.format(**kwargs)
        except Exception:
            return translated
    return translated


def _translate_text(source: str) -> str:
    if not source or not is_english_ui():
        return source

    if source in _EXACT_ENGLISH:
        return _EXACT_ENGLISH[source]

    regex_translated = _translate_by_regex(source)
    if regex_translated is not None:
        return regex_translated

    segment_translated = _translate_by_segments(source)
    if segment_translated is not None:
        return segment_translated

    bilingual_translated = _extract_english_variant(source)
    if bilingual_translated is not None:
        return bilingual_translated

    return source


def _translate_by_regex(source: str) -> str | None:
    for pattern, template in _REGEX_ENGLISH:
        match = pattern.match(source)
        if match:
            try:
                return template.format(**match.groupdict())
            except Exception:
                return template
    return None


def _translate_by_segments(source: str) -> str | None:
    out = source
    changed = False
    for needle, replacement in _SEGMENT_ENGLISH:
        if needle not in out:
            continue
        out = out.replace(needle, replacement)
        changed = True
    return out if changed else None


def _extract_english_variant(source: str) -> str | None:
    direct_match = re.match(r"^(?P<prefix>[A-Za-z0-9][A-Za-z0-9 ._/\-&:+%',]+?)\s*\((?P<note>[^()]*)\)$", source.strip())
    if direct_match:
        prefix = direct_match.group("prefix").strip()
        note = direct_match.group("note").strip()
        if prefix and note and re.search(r"[가-힣]", note):
            note_translated = _EXACT_ENGLISH.get(note)
            if note_translated is None:
                note_translated = _translate_by_segments(note)
            if note_translated is None:
                normalized = _normalize_inline_terms(note)
                note_translated = normalized if normalized != note else None
            if note_translated:
                return f"{prefix} ({note_translated})"
            return prefix

    matches = list(re.finditer(r"\(([^()]*)\)", source))
    if not matches:
        return None

    for match in reversed(matches):
        inner = _normalize_inline_terms(match.group(1).strip())
        if not inner:
            continue
        if not re.search(r"[A-Za-z]", inner):
            continue
        if re.search(r"[가-힣]", inner):
            continue
        prefix = source[:match.start()].rstrip()
        suffix = source[match.end():].strip()
        if suffix and not re.search(r"[A-Za-z]", suffix) and re.search(r"[가-힣]", suffix):
            suffix = ""
        out = inner
        if suffix:
            out = f"{out} {suffix}".strip()
        if prefix and re.match(r"^\d+[\.\-A-Z ]*$", prefix):
            out = f"{prefix} {out}".strip()
        return out
    return None


def _normalize_inline_terms(text: str) -> str:
    out = str(text or "")
    for source, target in _INLINE_REPLACEMENTS.items():
        out = out.replace(source, target)
    out = re.sub(r"\s+", " ", out).strip(" ,")
    return out


def _remember_source(obj, key: str, current: str) -> str:
    prop_name = f"{_PROP_PREFIX}{key}"
    try:
        stored = obj.property(prop_name)
        if stored is None:
            obj.setProperty(prop_name, current)
            return current
        return str(stored)
    except Exception:
        return current


def _translate_attr(obj, *, key: str, getter_name: str, setter_name: str) -> None:
    getter = getattr(obj, getter_name, None)
    setter = getattr(obj, setter_name, None)
    if not callable(getter) or not callable(setter):
        return
    try:
        current = getter()
    except Exception:
        return
    if current is None:
        return
    source = _remember_source(obj, key, str(current))
    try:
        setter(tr(source))
    except Exception:
        pass


def _translate_action(action) -> None:
    if action is None:
        return
    _translate_attr(action, key="action_text", getter_name="text", setter_name="setText")
    _translate_attr(action, key="action_tooltip", getter_name="toolTip", setter_name="setToolTip")
    _translate_attr(action, key="action_status_tip", getter_name="statusTip", setter_name="setStatusTip")


def set_widget_item_translation(widget, enabled: bool = True) -> None:
    if widget is None:
        return
    try:
        widget.setProperty(_ITEM_TRANSLATION_PROP, bool(enabled))
    except Exception:
        pass


def _widget_item_translation_enabled(widget) -> bool:
    if widget is None:
        return False
    try:
        value = widget.property(_ITEM_TRANSLATION_PROP)
    except Exception:
        return False
    if value is None:
        return False
    try:
        return bool(value)
    except Exception:
        return False


def _translate_combo_items(combo) -> None:
    if not _widget_item_translation_enabled(combo):
        return
    try:
        count = int(combo.count())
    except Exception:
        return
    for index in range(count):
        try:
            source = combo.itemData(index, _I18N_ROLE)
            if source is None:
                source = combo.itemText(index)
                combo.setItemData(index, source, _I18N_ROLE)
            combo.setItemText(index, tr(str(source or "")))
        except Exception:
            continue


def _translate_tab_widget(tab_widget) -> None:
    try:
        count = int(tab_widget.count())
    except Exception:
        return
    tab_bar = None
    try:
        tab_bar = tab_widget.tabBar()
    except Exception:
        tab_bar = None
    for index in range(count):
        try:
            source = tab_bar.tabData(index) if tab_bar is not None else None
            if source is None and tab_bar is not None:
                source = tab_widget.tabText(index)
                tab_bar.setTabData(index, source)
            elif source is None:
                source = tab_widget.tabText(index)
            tab_widget.setTabText(index, tr(str(source or "")))
        except Exception:
            continue


def _translate_list_widget_items(list_widget) -> None:
    if not _widget_item_translation_enabled(list_widget):
        return
    try:
        count = int(list_widget.count())
    except Exception:
        return
    for index in range(count):
        try:
            item = list_widget.item(index)
            if item is None:
                continue
            source = item.data(_I18N_ROLE)
            if source is None:
                source = item.text()
                item.setData(_I18N_ROLE, source)
            item.setText(tr(str(source or "")))
        except Exception:
            continue


def _translate_table_widget(table_widget) -> None:
    if not _widget_item_translation_enabled(table_widget):
        return
    try:
        col_count = int(table_widget.columnCount())
    except Exception:
        col_count = 0
    try:
        row_count = int(table_widget.rowCount())
    except Exception:
        row_count = 0

    for col in range(col_count):
        try:
            item = table_widget.horizontalHeaderItem(col)
            if item is None:
                continue
            source = item.data(_I18N_ROLE)
            if source is None:
                source = item.text()
                item.setData(_I18N_ROLE, source)
            item.setText(tr(str(source or "")))
        except Exception:
            continue

    for row in range(row_count):
        try:
            item = table_widget.verticalHeaderItem(row)
            if item is None:
                continue
            source = item.data(_I18N_ROLE)
            if source is None:
                source = item.text()
                item.setData(_I18N_ROLE, source)
            item.setText(tr(str(source or "")))
        except Exception:
            continue

    for row in range(row_count):
        for col in range(col_count):
            try:
                item = table_widget.item(row, col)
                if item is None:
                    continue
                source = item.data(_I18N_ROLE)
                if source is None:
                    source = item.text()
                    item.setData(_I18N_ROLE, source)
                item.setText(tr(str(source or "")))
            except Exception:
                continue


def _translate_tree_widget_item(item) -> None:
    if item is None:
        return
    try:
        col_count = max(1, int(item.columnCount()))
    except Exception:
        col_count = 1

    for col in range(col_count):
        try:
            source = item.data(col, _I18N_ROLE)
            if source is None:
                source = item.text(col)
                item.setData(col, _I18N_ROLE, source)
            item.setText(col, tr(str(source or "")))
        except Exception:
            continue

    try:
        child_count = int(item.childCount())
    except Exception:
        child_count = 0
    for index in range(child_count):
        try:
            _translate_tree_widget_item(item.child(index))
        except Exception:
            continue


def _translate_tree_widget(tree_widget) -> None:
    if not _widget_item_translation_enabled(tree_widget):
        return
    try:
        header = tree_widget.headerItem()
    except Exception:
        header = None
    if header is not None:
        _translate_tree_widget_item(header)

    try:
        top_count = int(tree_widget.topLevelItemCount())
    except Exception:
        top_count = 0
    for index in range(top_count):
        try:
            _translate_tree_widget_item(tree_widget.topLevelItem(index))
        except Exception:
            continue


@contextlib.contextmanager
def _runtime_bypass():
    global _BYPASS_HOOKS
    prev = _BYPASS_HOOKS
    _BYPASS_HOOKS = True
    try:
        yield
    finally:
        _BYPASS_HOOKS = prev


def _store_runtime_source(obj, key: str, text) -> None:
    if obj is None:
        return
    try:
        obj.setProperty(f"{_PROP_PREFIX}{key}", "" if text is None else str(text))
    except Exception:
        pass


def _wrap_text_method(cls, method_name: str, *, source_key: str) -> None:
    original = getattr(cls, method_name, None)
    if not callable(original) or getattr(original, "_archtoolkit_i18n_wrapped", False):
        return

    @functools.wraps(original)
    def wrapped(self, text, *args, **kwargs):
        if _BYPASS_HOOKS:
            return original(self, text, *args, **kwargs)
        _store_runtime_source(self, source_key, text)
        return original(self, tr("" if text is None else str(text)), *args, **kwargs)

    wrapped._archtoolkit_i18n_wrapped = True
    setattr(cls, method_name, wrapped)


def _wrap_show_method(cls, method_name: str) -> None:
    original = getattr(cls, method_name, None)
    if not callable(original) or getattr(original, "_archtoolkit_i18n_wrapped", False):
        return

    @functools.wraps(original)
    def wrapped(self, *args, **kwargs):
        try:
            apply_language(self)
        except Exception:
            pass
        return original(self, *args, **kwargs)

    wrapped._archtoolkit_i18n_wrapped = True
    setattr(cls, method_name, wrapped)


def _wrap_qmessagebox_static(method_name: str) -> None:
    original = getattr(QtWidgets.QMessageBox, method_name, None)
    if not callable(original) or getattr(original, "_archtoolkit_i18n_wrapped", False):
        return

    @functools.wraps(original)
    def wrapped(parent, title, text, *args, **kwargs):
        if _BYPASS_HOOKS:
            return original(parent, title, text, *args, **kwargs)
        return original(parent, tr(title), tr(text), *args, **kwargs)

    wrapped._archtoolkit_i18n_wrapped = True
    setattr(QtWidgets.QMessageBox, method_name, staticmethod(wrapped))


def _wrap_qmessagebox_add_button() -> None:
    original = getattr(QtWidgets.QMessageBox, "addButton", None)
    if not callable(original) or getattr(original, "_archtoolkit_i18n_wrapped", False):
        return

    @functools.wraps(original)
    def wrapped(self, *args, **kwargs):
        if _BYPASS_HOOKS or not args:
            return original(self, *args, **kwargs)
        args_list = list(args)
        if isinstance(args_list[0], str):
            args_list[0] = tr(args_list[0])
        return original(self, *args_list, **kwargs)

    wrapped._archtoolkit_i18n_wrapped = True
    setattr(QtWidgets.QMessageBox, "addButton", wrapped)


def _wrap_qfiledialog_static(method_name: str) -> None:
    original = getattr(QtWidgets.QFileDialog, method_name, None)
    if not callable(original) or getattr(original, "_archtoolkit_i18n_wrapped", False):
        return

    @functools.wraps(original)
    def wrapped(*args, **kwargs):
        if _BYPASS_HOOKS or len(args) < 2:
            return original(*args, **kwargs)
        args_list = list(args)
        if isinstance(args_list[1], str):
            args_list[1] = tr(args_list[1])
        return original(*args_list, **kwargs)

    wrapped._archtoolkit_i18n_wrapped = True
    setattr(QtWidgets.QFileDialog, method_name, staticmethod(wrapped))


def _wrap_qprogressdialog_init() -> None:
    original = getattr(QtWidgets.QProgressDialog, "__init__", None)
    if not callable(original) or getattr(original, "_archtoolkit_i18n_wrapped", False):
        return

    @functools.wraps(original)
    def wrapped(self, *args, **kwargs):
        if _BYPASS_HOOKS:
            return original(self, *args, **kwargs)
        args_list = list(args)
        if len(args_list) >= 1 and isinstance(args_list[0], str):
            _store_runtime_source(self, "progress_label", args_list[0])
            args_list[0] = tr(args_list[0])
        if len(args_list) >= 2 and isinstance(args_list[1], str):
            _store_runtime_source(self, "progress_cancel", args_list[1])
            args_list[1] = tr(args_list[1])
        return original(self, *args_list, **kwargs)

    wrapped._archtoolkit_i18n_wrapped = True
    setattr(QtWidgets.QProgressDialog, "__init__", wrapped)


def _wrap_qcombobox_methods() -> None:
    original_add = getattr(QtWidgets.QComboBox, "addItem", None)
    if callable(original_add) and not getattr(original_add, "_archtoolkit_i18n_wrapped", False):

        @functools.wraps(original_add)
        def add_item(self, *args, **kwargs):
            if _BYPASS_HOOKS or not _widget_item_translation_enabled(self):
                return original_add(self, *args, **kwargs)
            args_list = list(args)
            text_index = None
            if args_list and isinstance(args_list[0], str):
                text_index = 0
            elif len(args_list) >= 2 and isinstance(args_list[1], str):
                text_index = 1
            if text_index is not None:
                source = str(args_list[text_index] or "")
                args_list[text_index] = tr(source)
                result = original_add(self, *args_list, **kwargs)
                try:
                    self.setItemData(self.count() - 1, source, _I18N_ROLE)
                except Exception:
                    pass
                return result
            return original_add(self, *args_list, **kwargs)

        add_item._archtoolkit_i18n_wrapped = True
        setattr(QtWidgets.QComboBox, "addItem", add_item)

    original_insert = getattr(QtWidgets.QComboBox, "insertItem", None)
    if callable(original_insert) and not getattr(original_insert, "_archtoolkit_i18n_wrapped", False):

        @functools.wraps(original_insert)
        def insert_item(self, index, *args, **kwargs):
            if _BYPASS_HOOKS or not _widget_item_translation_enabled(self):
                return original_insert(self, index, *args, **kwargs)
            args_list = list(args)
            text_index = None
            if args_list and isinstance(args_list[0], str):
                text_index = 0
            elif len(args_list) >= 2 and isinstance(args_list[1], str):
                text_index = 1
            if text_index is not None:
                source = str(args_list[text_index] or "")
                args_list[text_index] = tr(source)
                result = original_insert(self, index, *args_list, **kwargs)
                try:
                    self.setItemData(index, source, _I18N_ROLE)
                except Exception:
                    pass
                return result
            return original_insert(self, index, *args_list, **kwargs)

        insert_item._archtoolkit_i18n_wrapped = True
        setattr(QtWidgets.QComboBox, "insertItem", insert_item)

    original_set = getattr(QtWidgets.QComboBox, "setItemText", None)
    if callable(original_set) and not getattr(original_set, "_archtoolkit_i18n_wrapped", False):

        @functools.wraps(original_set)
        def set_item_text(self, index, text):
            if _BYPASS_HOOKS or not _widget_item_translation_enabled(self):
                return original_set(self, index, text)
            source = "" if text is None else str(text)
            try:
                self.setItemData(index, source, _I18N_ROLE)
            except Exception:
                pass
            return original_set(self, index, tr(source))

        set_item_text._archtoolkit_i18n_wrapped = True
        setattr(QtWidgets.QComboBox, "setItemText", set_item_text)


def _wrap_qtabwidget_methods() -> None:
    original_add = getattr(QtWidgets.QTabWidget, "addTab", None)
    if callable(original_add) and not getattr(original_add, "_archtoolkit_i18n_wrapped", False):

        @functools.wraps(original_add)
        def add_tab(self, widget, *args, **kwargs):
            if _BYPASS_HOOKS:
                return original_add(self, widget, *args, **kwargs)
            args_list = list(args)
            text_index = None
            if args_list and isinstance(args_list[0], str):
                text_index = 0
            elif len(args_list) >= 2 and isinstance(args_list[1], str):
                text_index = 1
            if text_index is not None:
                source = str(args_list[text_index] or "")
                args_list[text_index] = tr(source)
                index = original_add(self, widget, *args_list, **kwargs)
                try:
                    self.tabBar().setTabData(index, source)
                except Exception:
                    pass
                return index
            return original_add(self, widget, *args_list, **kwargs)

        add_tab._archtoolkit_i18n_wrapped = True
        setattr(QtWidgets.QTabWidget, "addTab", add_tab)

    original_insert = getattr(QtWidgets.QTabWidget, "insertTab", None)
    if callable(original_insert) and not getattr(original_insert, "_archtoolkit_i18n_wrapped", False):

        @functools.wraps(original_insert)
        def insert_tab(self, index, widget, *args, **kwargs):
            if _BYPASS_HOOKS:
                return original_insert(self, index, widget, *args, **kwargs)
            args_list = list(args)
            text_index = None
            if args_list and isinstance(args_list[0], str):
                text_index = 0
            elif len(args_list) >= 2 and isinstance(args_list[1], str):
                text_index = 1
            if text_index is not None:
                source = str(args_list[text_index] or "")
                args_list[text_index] = tr(source)
                out = original_insert(self, index, widget, *args_list, **kwargs)
                try:
                    self.tabBar().setTabData(index, source)
                except Exception:
                    pass
                return out
            return original_insert(self, index, widget, *args_list, **kwargs)

        insert_tab._archtoolkit_i18n_wrapped = True
        setattr(QtWidgets.QTabWidget, "insertTab", insert_tab)

    original_set = getattr(QtWidgets.QTabWidget, "setTabText", None)
    if callable(original_set) and not getattr(original_set, "_archtoolkit_i18n_wrapped", False):

        @functools.wraps(original_set)
        def set_tab_text(self, index, text):
            if _BYPASS_HOOKS:
                return original_set(self, index, text)
            source = "" if text is None else str(text)
            try:
                self.tabBar().setTabData(index, source)
            except Exception:
                pass
            return original_set(self, index, tr(source))

        set_tab_text._archtoolkit_i18n_wrapped = True
        setattr(QtWidgets.QTabWidget, "setTabText", set_tab_text)


def _wrap_item_text_methods() -> None:
    list_original = getattr(QtWidgets.QListWidgetItem, "setText", None)
    if callable(list_original) and not getattr(list_original, "_archtoolkit_i18n_wrapped", False):

        @functools.wraps(list_original)
        def list_set_text(self, text):
            if _BYPASS_HOOKS or not _widget_item_translation_enabled(self.listWidget()):
                return list_original(self, text)
            source = "" if text is None else str(text)
            try:
                self.setData(_I18N_ROLE, source)
            except Exception:
                pass
            return list_original(self, tr(source))

        list_set_text._archtoolkit_i18n_wrapped = True
        setattr(QtWidgets.QListWidgetItem, "setText", list_set_text)

    table_original = getattr(QtWidgets.QTableWidgetItem, "setText", None)
    if callable(table_original) and not getattr(table_original, "_archtoolkit_i18n_wrapped", False):

        @functools.wraps(table_original)
        def table_set_text(self, text):
            if _BYPASS_HOOKS or not _widget_item_translation_enabled(self.tableWidget()):
                return table_original(self, text)
            source = "" if text is None else str(text)
            try:
                self.setData(_I18N_ROLE, source)
            except Exception:
                pass
            return table_original(self, tr(source))

        table_set_text._archtoolkit_i18n_wrapped = True
        setattr(QtWidgets.QTableWidgetItem, "setText", table_set_text)

    tree_original = getattr(QtWidgets.QTreeWidgetItem, "setText", None)
    if callable(tree_original) and not getattr(tree_original, "_archtoolkit_i18n_wrapped", False):

        @functools.wraps(tree_original)
        def tree_set_text(self, column, text):
            if _BYPASS_HOOKS or not _widget_item_translation_enabled(self.treeWidget()):
                return tree_original(self, column, text)
            source = "" if text is None else str(text)
            try:
                self.setData(column, _I18N_ROLE, source)
            except Exception:
                pass
            return tree_original(self, column, tr(source))

        tree_set_text._archtoolkit_i18n_wrapped = True
        setattr(QtWidgets.QTreeWidgetItem, "setText", tree_set_text)


def _wrap_qlistwidget_methods() -> None:
    original_add = getattr(QtWidgets.QListWidget, "addItem", None)
    if callable(original_add) and not getattr(original_add, "_archtoolkit_i18n_wrapped", False):

        @functools.wraps(original_add)
        def add_item(self, item):
            if _BYPASS_HOOKS or not _widget_item_translation_enabled(self):
                return original_add(self, item)
            if isinstance(item, str):
                return original_add(self, tr(item))
            result = original_add(self, item)
            try:
                _translate_list_widget_items(self)
            except Exception:
                pass
            return result

        add_item._archtoolkit_i18n_wrapped = True
        setattr(QtWidgets.QListWidget, "addItem", add_item)

    original_insert = getattr(QtWidgets.QListWidget, "insertItem", None)
    if callable(original_insert) and not getattr(original_insert, "_archtoolkit_i18n_wrapped", False):

        @functools.wraps(original_insert)
        def insert_item(self, row, item):
            if _BYPASS_HOOKS or not _widget_item_translation_enabled(self):
                return original_insert(self, row, item)
            if isinstance(item, str):
                return original_insert(self, row, tr(item))
            result = original_insert(self, row, item)
            try:
                _translate_list_widget_items(self)
            except Exception:
                pass
            return result

        insert_item._archtoolkit_i18n_wrapped = True
        setattr(QtWidgets.QListWidget, "insertItem", insert_item)


def _wrap_header_label_methods() -> None:
    table_horizontal = getattr(QtWidgets.QTableWidget, "setHorizontalHeaderLabels", None)
    if callable(table_horizontal) and not getattr(table_horizontal, "_archtoolkit_i18n_wrapped", False):

        @functools.wraps(table_horizontal)
        def set_horizontal_header_labels(self, labels):
            if _BYPASS_HOOKS or not _widget_item_translation_enabled(self):
                return table_horizontal(self, labels)
            translated = [tr(str(label or "")) for label in list(labels or [])]
            result = table_horizontal(self, translated)
            try:
                _translate_table_widget(self)
            except Exception:
                pass
            return result

        set_horizontal_header_labels._archtoolkit_i18n_wrapped = True
        setattr(QtWidgets.QTableWidget, "setHorizontalHeaderLabels", set_horizontal_header_labels)

    table_vertical = getattr(QtWidgets.QTableWidget, "setVerticalHeaderLabels", None)
    if callable(table_vertical) and not getattr(table_vertical, "_archtoolkit_i18n_wrapped", False):

        @functools.wraps(table_vertical)
        def set_vertical_header_labels(self, labels):
            if _BYPASS_HOOKS or not _widget_item_translation_enabled(self):
                return table_vertical(self, labels)
            translated = [tr(str(label or "")) for label in list(labels or [])]
            result = table_vertical(self, translated)
            try:
                _translate_table_widget(self)
            except Exception:
                pass
            return result

        set_vertical_header_labels._archtoolkit_i18n_wrapped = True
        setattr(QtWidgets.QTableWidget, "setVerticalHeaderLabels", set_vertical_header_labels)

    tree_header = getattr(QtWidgets.QTreeWidget, "setHeaderLabels", None)
    if callable(tree_header) and not getattr(tree_header, "_archtoolkit_i18n_wrapped", False):

        @functools.wraps(tree_header)
        def set_tree_header_labels(self, labels):
            if _BYPASS_HOOKS or not _widget_item_translation_enabled(self):
                return tree_header(self, labels)
            translated = [tr(str(label or "")) for label in list(labels or [])]
            result = tree_header(self, translated)
            try:
                _translate_tree_widget(self)
            except Exception:
                pass
            return result

        set_tree_header_labels._archtoolkit_i18n_wrapped = True
        setattr(QtWidgets.QTreeWidget, "setHeaderLabels", set_tree_header_labels)


def _wrap_qgis_name_methods() -> None:
    try:
        from qgis.core import QgsLayerTreeGroup, QgsMapLayer  # type: ignore
    except Exception:
        return

    _ = QgsMapLayer
    _ = QgsLayerTreeGroup


def _unwrap_method(cls, method_name: str) -> None:
    current = getattr(cls, method_name, None)
    if not callable(current) or not getattr(current, "_archtoolkit_i18n_wrapped", False):
        return
    original = getattr(current, "__wrapped__", None)
    if not callable(original):
        return
    try:
        setattr(cls, method_name, original)
    except Exception:
        pass


def install_runtime_i18n_hooks() -> None:
    global _HOOKS_INSTALLED
    if _HOOKS_INSTALLED:
        return

    _wrap_text_method(QtWidgets.QWidget, "setWindowTitle", source_key="window_title")
    _wrap_text_method(QtWidgets.QAction, "setText", source_key="action_text")
    _wrap_text_method(QtWidgets.QAction, "setToolTip", source_key="action_tooltip")
    _wrap_text_method(QtWidgets.QAction, "setStatusTip", source_key="action_status_tip")
    _wrap_text_method(QtWidgets.QMenu, "setTitle", source_key="menu_title")
    _wrap_text_method(QtWidgets.QLabel, "setText", source_key="text")
    _wrap_text_method(QtWidgets.QAbstractButton, "setText", source_key="text")
    _wrap_text_method(QtWidgets.QGroupBox, "setTitle", source_key="title")
    _wrap_text_method(QtWidgets.QLineEdit, "setPlaceholderText", source_key="placeholder")
    _wrap_text_method(QtWidgets.QTextBrowser, "setHtml", source_key="html")
    _wrap_text_method(QtWidgets.QTextBrowser, "setPlainText", source_key="plain_text")
    _wrap_text_method(QtWidgets.QTextEdit, "setHtml", source_key="html")
    _wrap_text_method(QtWidgets.QTextEdit, "setPlainText", source_key="plain_text")
    _wrap_text_method(QtWidgets.QProgressDialog, "setLabelText", source_key="progress_label")
    _wrap_text_method(QtWidgets.QProgressDialog, "setCancelButtonText", source_key="progress_cancel")
    _wrap_text_method(QtWidgets.QMessageBox, "setText", source_key="message_text")
    _wrap_text_method(QtWidgets.QMessageBox, "setInformativeText", source_key="message_info")
    _wrap_text_method(QtWidgets.QMessageBox, "setDetailedText", source_key="message_detail")

    _unwrap_method(QtWidgets.QComboBox, "addItem")
    _unwrap_method(QtWidgets.QComboBox, "insertItem")
    _unwrap_method(QtWidgets.QComboBox, "setItemText")
    _unwrap_method(QtWidgets.QListWidgetItem, "setText")
    _unwrap_method(QtWidgets.QTableWidgetItem, "setText")
    _unwrap_method(QtWidgets.QTreeWidgetItem, "setText")
    _unwrap_method(QtWidgets.QListWidget, "addItem")
    _unwrap_method(QtWidgets.QListWidget, "insertItem")
    _unwrap_method(QtWidgets.QTableWidget, "setHorizontalHeaderLabels")
    _unwrap_method(QtWidgets.QTableWidget, "setVerticalHeaderLabels")
    _unwrap_method(QtWidgets.QTreeWidget, "setHeaderLabels")
    try:
        from qgis.core import QgsLayerTreeGroup, QgsMapLayer  # type: ignore

        _unwrap_method(QgsMapLayer, "setName")
        _unwrap_method(QgsLayerTreeGroup, "setName")
        _unwrap_method(QgsLayerTreeGroup, "addGroup")
        _unwrap_method(QgsLayerTreeGroup, "insertGroup")
    except Exception:
        pass

    _wrap_qcombobox_methods()
    _wrap_qtabwidget_methods()
    _wrap_item_text_methods()
    _wrap_qlistwidget_methods()
    _wrap_header_label_methods()
    _wrap_qprogressdialog_init()
    _wrap_qmessagebox_add_button()

    for method_name in ("information", "warning", "critical", "question"):
        _wrap_qmessagebox_static(method_name)
    for method_name in ("getOpenFileName", "getOpenFileNames", "getSaveFileName", "getExistingDirectory"):
        _wrap_qfiledialog_static(method_name)
    for method_name in ("show", "open", "exec", "exec_"):
        _wrap_show_method(QtWidgets.QDialog, method_name)
        _wrap_show_method(QtWidgets.QMessageBox, method_name)

    try:
        from qgis.gui import QgsMessageBar  # type: ignore

        original = getattr(QgsMessageBar, "pushMessage", None)
        if callable(original) and not getattr(original, "_archtoolkit_i18n_wrapped", False):

            @functools.wraps(original)
            def wrapped(self, *args, **kwargs):
                if _BYPASS_HOOKS or not args:
                    return original(self, *args, **kwargs)
                args_list = list(args)
                if len(args_list) >= 1 and isinstance(args_list[0], str):
                    args_list[0] = tr(args_list[0])
                if len(args_list) >= 2 and isinstance(args_list[1], str):
                    args_list[1] = tr(args_list[1])
                return original(self, *args_list, **kwargs)

            wrapped._archtoolkit_i18n_wrapped = True
            setattr(QgsMessageBar, "pushMessage", wrapped)
    except Exception:
        pass

    _HOOKS_INSTALLED = True


def _iter_widgets(root):
    yield root
    try:
        for child in root.findChildren(QtWidgets.QWidget):
            yield child
    except Exception:
        return


def apply_language(target) -> None:
    if target is None:
        return

    if isinstance(target, QtWidgets.QAction):
        with _runtime_bypass():
            _translate_action(target)
        return

    if isinstance(target, QtWidgets.QMenu):
        with _runtime_bypass():
            _translate_attr(target, key="menu_title", getter_name="title", setter_name="setTitle")
            for action in list(target.actions() or []):
                if action.menu() is not None:
                    apply_language(action.menu())
                _translate_action(action)
        return

    with _runtime_bypass():
        for widget in _iter_widgets(target):
            _translate_attr(widget, key="window_title", getter_name="windowTitle", setter_name="setWindowTitle")
            _translate_attr(widget, key="tooltip", getter_name="toolTip", setter_name="setToolTip")
            _translate_attr(widget, key="placeholder", getter_name="placeholderText", setter_name="setPlaceholderText")
            _translate_attr(widget, key="prefix", getter_name="prefix", setter_name="setPrefix")
            _translate_attr(widget, key="suffix", getter_name="suffix", setter_name="setSuffix")
            _translate_attr(widget, key="special_value", getter_name="specialValueText", setter_name="setSpecialValueText")
            _translate_attr(widget, key="dialog_title", getter_name="dialogTitle", setter_name="setDialogTitle")

            if isinstance(widget, QtWidgets.QLabel):
                _translate_attr(widget, key="text", getter_name="text", setter_name="setText")
            elif isinstance(widget, QtWidgets.QAbstractButton):
                _translate_attr(widget, key="text", getter_name="text", setter_name="setText")
            elif isinstance(widget, QtWidgets.QGroupBox):
                _translate_attr(widget, key="title", getter_name="title", setter_name="setTitle")
            elif isinstance(widget, QtWidgets.QComboBox):
                _translate_combo_items(widget)
            elif isinstance(widget, QtWidgets.QTabWidget):
                _translate_tab_widget(widget)
            elif isinstance(widget, QtWidgets.QListWidget):
                _translate_list_widget_items(widget)
            elif isinstance(widget, QtWidgets.QTableWidget):
                _translate_table_widget(widget)
            elif isinstance(widget, QtWidgets.QTreeWidget):
                _translate_tree_widget(widget)
