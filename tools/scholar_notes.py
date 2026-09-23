# -*- coding: utf-8 -*-
"""Per-tool notes on the scholarship behind each analysis, for the help dialogs.

Every dialog's help ends with the block returned by :func:`html_for`, so a user
sees, in one place: which published method the tool implements (and by whom),
how the authors meant it to be used, the practical sequence that follows that
intent, and what the tool does NOT claim. All bibliographic lines mirror
REFERENCES.md, which is the verified source; do not add a citation here that is
not in REFERENCES.md.

Labels follow REFERENCES.md: (A) algorithm called from QGIS/GDAL, (B) formula
implemented in this plugin, (C) context or downstream reference only.
"""
from __future__ import annotations

from html import escape
from typing import Dict, List, Optional

# --- shared bibliographic lines (verbatim from REFERENCES.md) -----------------
_R = {
    "horn1981": "Horn, B.K.P. (1981). Hill shading and the reflectance map. Proceedings of the IEEE, 69(1), 14-47.",
    "zt1987": "Zevenbergen, L.W., & Thorne, C.R. (1987). Quantitative analysis of land surface topography. Earth Surface Processes and Landforms, 12(1), 47-56.",
    "weiss2001": "Weiss, A. (2001). Topographic Position and Landforms Analysis. Poster, ESRI User Conference, San Diego.",
    "riley1999": "Riley, S.J., DeGloria, S.D., & Elliot, R. (1999). A terrain ruggedness index that quantifies topographic heterogeneity. Intermountain Journal of Sciences, 5(1-4), 23-27.",
    "wilson2007": "Wilson, M.F.J., O'Connell, B., Brown, C., Guinan, J.C., & Grehan, A.J. (2007). Multiscale terrain analysis of multibeam bathymetry data for habitat mapping on the continental slope. Marine Geodesy, 30(1-2), 3-35.",
    "roberts1989": "Roberts, D.W., & Cooper, S.V. (1989). Concepts and techniques of vegetation mapping. USDA Forest Service GTR INT-257, 90-96.",
    "kfs": "산림청 예규 「공·사유림 경영계획 작성 및 운영요령」 [별표] 경사도 구분.",
    "wang2000": "Wang, J., Robinson, G.J., & White, K. (2000). Generating viewsheds without using sightlines. Photogrammetric Engineering & Remote Sensing, 66(1), 87-90.",
    "higuchi": "樋口忠彦 (1975). 『景観の構造』. 技報堂. 영역본: Higuchi, T. (1983). The Visual and Spatial Structure of Landscapes. MIT Press.",
    "wheatley1995": "Wheatley, D. (1995). Cumulative viewshed analysis: a GIS-based method for investigating intervisibility, and its archaeological application. In: Lock, G., & Stančič, Z. (eds), Archaeology and Geographic Information Systems: A European Perspective. Taylor & Francis.",
    "tobler1993": "Tobler, W. (1993). Three Presentations on Geographical Analysis and Modeling. NCGIA Technical Report 93-1.",
    "naismith1892": "Naismith, W.W. (1892). Cruach Ardran, Stobinian, and Ben More. Scottish Mountaineering Club Journal, 2(3), 135-136.",
    "pandolf1977": "Pandolf, K.B., Givoni, B., & Goldman, R.F. (1977). Predicting energy expenditure with loads while standing or walking very slowly. Journal of Applied Physiology, 43(4), 577-581.",
    "minetti2002": "Minetti, A.E., Moia, C., Roi, G.S., Susta, D., & Ferretti, G. (2002). Energy cost of walking and running at extreme uphill and downhill slopes. Journal of Applied Physiology, 93(3), 1039-1046.",
    "herzog2013": "Herzog, I. (2013). The potential and limits of Optimal Path Analysis. In: Bevan, A., & Lake, M. (eds), Computational Approaches to Archaeological Spaces. Left Coast Press, 179-211.",
    "conolly2006": "Conolly, J., & Lake, M. (2006). Geographical Information Systems in Archaeology. Cambridge University Press.",
    "dijkstra1959": "Dijkstra, E.W. (1959). A note on two problems in connexion with graphs. Numerische Mathematik, 1(1), 269-271.",
    "hart1968": "Hart, P.E., Nilsson, N.J., & Raphael, B. (1968). A formal basis for the heuristic determination of minimum cost paths. IEEE Transactions on Systems Science and Cybernetics, 4(2), 100-107.",
    "kruskal1956": "Kruskal, J.B. (1956). On the shortest spanning subtree of a graph and the traveling salesman problem. Proceedings of the American Mathematical Society, 7(1), 48-50.",
    "freeman1979": "Freeman, L.C. (1979). Centrality in social networks: conceptual clarification. Social Networks, 1(3), 215-239.",
    "brandes2001": "Brandes, U. (2001). A faster algorithm for betweenness centrality. Journal of Mathematical Sociology, 25(2), 163-177.",
    "wf1994": "Wasserman, S., & Faust, K. (1994). Social Network Analysis: Methods and Applications. Cambridge University Press.",
    "terrell1977": "Terrell, J.E. (1977). Human Biogeography in the Solomon Islands. Fieldiana Anthropology, 68(1), 1-47.",
    "delaunay1934": "Delaunay, B. (1934). Sur la sphère vide. Bulletin de l'Académie des Sciences de l'URSS, VII série, 1934(6), 793-800.",
    "gabriel1969": "Gabriel, K.R., & Sokal, R.R. (1969). A new statistical approach to geographic variation analysis. Systematic Zoology, 18(3), 259-278.",
    "toussaint1980": "Toussaint, G.T. (1980). The relative neighbourhood graph of a finite planar set. Pattern Recognition, 12(4), 261-268.",
    "brughmans2017": "Brughmans, T., & Peeples, M.A. (2017). Trends in archaeological network research: a bibliometric analysis. Journal of Historical Network Research, 1, 1-24.",
    "vandyke2016": "Van Dyke, R.M., Bocinsky, R.K., Windes, T.C., & Robinson, T.J. (2016). Great houses, shrines, and high places: intervisibility in the Chacoan world. American Antiquity, 81(2), 205-230.",
    "gillings2001": "Gillings, M., & Wheatley, D. (2001). Seeing is not believing: unresolved issues in archaeological visibility analysis. In: On the Good Use of GIS in Archaeological Landscape Studies (COST Action G2).",
    "clough1965": "Clough, R.W., & Tocher, J.L. (1965). Finite element stiffness matrices for analysis of plates in bending. Proc. Conf. on Matrix Methods in Structural Mechanics, Wright-Patterson AFB.",
    "shepard1968": "Shepard, D. (1968). A two-dimensional interpolation function for irregularly-spaced data. Proc. 23rd ACM National Conference, 517-524.",
    "matheron1963": "Matheron, G. (1963). Principles of geostatistics. Economic Geology, 58(8), 1246-1266.",
    "cressie1993": "Cressie, N. (1993). Statistics for Spatial Data. Wiley.",
    "saaty1980": "Saaty, T.L. (1980). The Analytic Hierarchy Process. McGraw-Hill.",
    "alonso2006": "Alonso, J.A., & Lamata, M.T. (2006). Consistency in the Analytic Hierarchy Process: a new approach. Int. J. of Uncertainty, Fuzziness and Knowledge-Based Systems, 14(4), 445-459.",
    "malczewski2004": "Malczewski, J. (2004). GIS-based land-use suitability analysis: a critical overview. Progress in Planning, 62(1), 3-65.",
    "phillips2006": "Phillips, S.J., Anderson, R.P., & Schapire, R.E. (2006). Maximum entropy modeling of species geographic distributions. Ecological Modelling, 190(3-4), 231-259.",
    "elith2011": "Elith, J., Phillips, S.J., Hastie, T., Dudík, M., Chee, Y.E., & Yates, C.J. (2011). A statistical explanation of MaxEnt for ecologists. Diversity and Distributions, 17(1), 43-57.",
    "obrien2007": "O'Brien, R.M. (2007). A caution regarding rules of thumb for variance inflation factors. Quality & Quantity, 41(5), 673-690.",
    "kigam_geo": "한국지질자원연구원(KIGAM). 1:50,000 지질도 도엽(벡터 SHP, ZIP).",
    "kigam_chem": "한국지질자원연구원(KIGAM). 지구화학도 WMS 렌더링 이미지.",
    "gdal": "GDAL Development Team (2024). GDAL - Geospatial Data Abstraction Library. OSGeo. https://gdal.org",
}

# --- per-tool notes -----------------------------------------------------------
# Each method: label (A/B/C), name, origin (who published it and what it was for),
# intent (how to use it the way the authors meant), ref keys.
NOTES: Dict[str, dict] = {
    "terrain_analysis": {
        "title": "지형 분석",
        "methods": [
            {"label": "A", "name": "경사도·사면방향 (Horn 1981)",
             "origin": "Horn은 음영기복도(hill shading)를 계산하려고 3x3 이웃 8셀의 가중 차분으로 지표 기울기와 방향을 구하는 방식을 제안했습니다. gdaldem의 기본 커널이 이 방식입니다.",
             "intent": "값은 격자 해상도에서의 국지 기울기입니다. DEM 해상도를 바꾸면 같은 사면의 경사값도 달라지므로, 보고할 때 해상도를 함께 적어야 비교가 됩니다.",
             "refs": ["horn1981"]},
            {"label": "B", "name": "곡률 (Zevenbergen & Thorne 1987)",
             "origin": "3x3 창에 2차 다항면을 적합해 종단(profile)·횡단(plan) 곡률을 구합니다. 원 논문의 목적은 지형에서 침식·퇴적 경향과 유수의 수렴·발산을 정량화하는 것이었습니다.",
             "intent": "종단 음(-)=볼록(침식 경향), 양(+)=오목(퇴적 경향); 횡단 음(-)=수렴(물 모임), 양(+)=발산(능선). GRASS/SAGA와는 부호가 반대이니 교차 검증 시 부호만 뒤집혀 보이면 정상입니다.",
             "refs": ["zt1987"]},
            {"label": "B", "name": "TPI와 지형 위치 6분류 (Weiss 2001)",
             "origin": "TPI는 중심 셀 고도에서 주변 평균을 뺀 값입니다. Weiss의 핵심 주장은 척도(scale)입니다. 이웃 반경을 어떻게 잡느냐에 따라 같은 지점이 능선으로도 골짜기로도 분류되며, 분류는 TPI를 표준편차 단위로 정규화한 뒤 경사와 결합합니다.",
             "intent": "반경은 찾으려는 지형 단위의 크기에 맞춥니다(구릉 수백 m, 산체 수 km). Weiss가 권한 대로 임계값은 자동 SD를 쓰고, 두 척도(작은 반경·큰 반경)를 함께 돌려 비교하는 것이 원래 방법입니다. 반경 2셀 이상은 (2r+1)x(2r+1) 창의 정확한 초점평균(중심 셀 제외, 3x3 TPI와 같은 정의)이며, 레이어 이름과 메타데이터에 실제 반경·창 크기·방법이 기록됩니다.",
             "refs": ["weiss2001"]},
            {"label": "A", "name": "TRI (Riley et al. 1999)",
             "origin": "3x3 이웃과의 표고차 제곱합의 제곱근입니다. 야생동물 서식지의 지형 이질성을 한 숫자로 나타내려고 만든 지수로, 원 논문은 절대 미터값 기준 7등급(0-80 m 평탄에서 959-4367 m 극험준)을 제시했습니다.",
             "intent": "지수는 Riley의 것이고, 화면의 5등급은 사용자가 준 험준 기준값에 비례한 플러그인 표시 구분입니다. 논문의 7등급으로 보고하려면 원 미터값 구간을 쓰십시오. 반경 2셀 이상의 TRI는 RMS 형태라 단위가 달라 별도 지표입니다.",
             "refs": ["riley1999"]},
            {"label": "A", "name": "Roughness (Wilson et al. 2007)",
             "origin": "창 안 최대-최소 표고차입니다. 다중척도 해저 지형 분석에서 서식지 매핑용으로 정의된 지표를 gdaldem이 3x3으로 구현했습니다.",
             "intent": "5등급(0-1/1-3/3-6/6-15/15 m 이상)은 한국 지형을 염두에 둔 플러그인 표시 관례입니다.",
             "refs": ["wilson2007"]},
            {"label": "B", "name": "사면 파생 지표: 북향성·동향성·TRASP (Roberts & Cooper 1989)",
             "origin": "원형 변수인 사면방향(0-360°)은 평균을 낼 수 없으므로 cos/sin으로 펼칩니다. TRASP = (1 - cos(방향 - 30°)) / 2 는 식생 매핑에서 일사량의 대리변수로 제안된 변환으로, 북북동 0(가장 차가움)에서 남남서 1(가장 따뜻함)입니다.",
             "intent": "예측모델(MaxEnt 등)에는 원 사면방향 대신 이 파생 변수를 넣어야 합니다. 정렬/내보내기 도구는 원 사면방향을 최근접으로만 리샘플링합니다.",
             "refs": ["roberts1989"]},
            {"label": "C", "name": "경사 등급 프리셋",
             "origin": "'한국표준'은 산림청 예규 별표의 경사도 구분입니다. '보행속도구분·에너지구분·인지구분(플러그인)' 세 가지는 Tobler·Minetti·Llobera의 논의를 참고해 플러그인이 정한 표시 구분이며, 그 저자들이 출판한 등급표가 아닙니다.",
             "intent": "논문의 분류로 보고할 수 있는 것은 한국표준뿐입니다. 나머지는 '플러그인 정의'로 적으십시오.",
             "refs": ["kfs"]},
        ],
        "workflow": [
            "DEM의 해상도와 좌표계(미터 단위 투영)를 먼저 확인합니다. 지리 좌표계 DEM은 거부됩니다.",
            "경사·사면방향은 그대로 산출하고, 예측모델용이면 사면 파생(북향성·동향성·TRASP)을 켭니다.",
            "지형 위치 분류는 대상 지형 규모에 맞춘 반경으로, 가능하면 두 척도를 비교합니다. 임계값은 자동 SD를 권장합니다.",
            "결과 레이어 메타데이터(params_json)에 반경·임계값·프리셋이 기록되므로 보고서에는 그 값을 옮겨 적습니다.",
        ],
        "not_claimed": ["플러그인 정의 등급 구분은 문헌의 분류가 아닙니다.", "DEM 가장자리 r셀은 NoData이며, NoData에 걸친 창은 유효한 이웃만으로 평균합니다."],
    },
    "slope_aspect_drafting": {
        "title": "경사도/사면방향 도면화",
        "methods": [
            {"label": "A", "name": "경사도·사면방향 (Horn 1981)",
             "origin": "gdaldem의 기본 3x3 커널(Horn 방식)로 경사와 방향을 계산합니다. Horn은 음영기복도 계산을 위해 이 차분식을 제안했습니다.",
             "intent": "도면 표기용이므로 등급 구간은 도면 목적에 맞춰 고르되, 사용한 구간을 범례에 명시합니다. 지리 좌표계 DEM은 미터 단위 결과를 낼 수 없어 거부됩니다.",
             "refs": ["horn1981"]},
        ],
        "workflow": ["미터 단위 투영 DEM을 준비합니다.", "등급 구간과 색상을 정하고 범례에 구간을 적습니다."],
        "not_claimed": ["등급 구간은 도면 관례이며 특정 문헌의 분류가 아닙니다."],
    },
    "viewshed": {
        "title": "가시권 분석",
        "methods": [
            {"label": "A", "name": "가시권 계산 (Wang, Robinson & White 2000)",
             "origin": "gdal_viewshed가 구현한 기준면(reference-plane) 방식입니다. 시선을 하나하나 긋는 대신 기준면을 바깥으로 전파해 격자 DEM의 가시권을 빠르게 구합니다.",
             "intent": "관측자 높이(예: 눈높이 1.6 m)와 대상 높이를 분석 질문에 맞게 정하고, 지구 곡률·굴절 보정(기본 굴절계수 0.13)을 켠 채 계산합니다. 최대 거리는 대상의 크기와 대기 조건을 고려해 제한합니다.",
             "refs": ["wang2000"]},
            {"label": "C", "name": "히구치 거리대 (Higuchi 1975; 영역본 1983)",
             "origin": "히구치는 경관을 근경·중경·원경으로 나누되, 그 경계를 미터가 아니라 대상 높이 대비 거리 비율(D/H)로 정의했습니다. 나무 같은 지배적 대상이 어느 거리까지 어떻게 지각되는가에서 출발한 개념입니다.",
             "intent": "기본값 500 m / 2500 m는 GIS 실무 관례일 뿐 히구치의 수치가 아닙니다. 대상(성벽·고분·산체)의 높이에 비례해 경계를 조정하고, 사용한 값을 보고합니다. 결과 메타데이터에 실제 경계값이 기록됩니다.",
             "refs": ["higuchi"]},
            {"label": "C", "name": "누적 가시권 (Wheatley 1995)",
             "origin": "여러 유적의 가시권을 합산해 '한 지점이 몇 개 유적에서 보이는가'를 세는 방법입니다. 영국 신석기 무덤 분포에 적용해, 유적 입지가 상호 가시성을 고려했는지 검토했습니다.",
             "intent": "누적값은 관측점 집합에 전적으로 좌우됩니다. 유적 목록이 불완전하면 누적 가시권도 불완전하므로 표본의 한계를 함께 적습니다.",
             "refs": ["wheatley1995"]},
        ],
        "workflow": [
            "DEM 해상도와 좌표계를 확인하고 관측점(또는 폴리곤 대표점)을 준비합니다.",
            "관측자·대상 높이, 최대 거리, 곡률 보정을 정합니다.",
            "히구치 경계는 대상 높이에 맞춰 조정하고, 누적 가시권은 관측점 집합의 완전성을 검토합니다.",
            "결과의 '보임'은 지형만 고려한 것입니다. 식생·건물·당시 지형 변화는 반영되지 않습니다.",
        ],
        "not_claimed": ["가시권은 '실제로 보였음'이 아니라 '지형이 가리지 않음'입니다."],
    },
    "cost_surface": {
        "title": "비용표면 / 최소비용경로",
        "methods": [
            {"label": "B", "name": "Tobler 하이킹 함수 (1993)",
             "origin": "보행 속도 v = 6·exp(-3.5·|tanθ + 0.05|) km/h. Imhof의 경험적 등산 자료를 함수로 정리한 것으로, 경사 약 -5%(약 -2.9°, 완만한 내리막)에서 가장 빠르고 오르막·급한 내리막에서 느려집니다. 오프패스 이동은 0.6배를 권했습니다.",
             "intent": "도보 이동 시간을 묻는 질문에 씁니다. 방향에 따라 값이 다른 비등방 함수이므로 왕복 시간은 다릅니다. 결과는 '가장 빠른 경로 가설'이지 실제 옛길이 아닙니다.",
             "refs": ["tobler1993"]},
            {"label": "B", "name": "Naismith 규칙 (1892)",
             "origin": "등산 계획용 시간 규칙입니다. 수평 3마일당 1시간에 오르막 2000피트당 1시간을 더합니다.",
             "intent": "시간 추정의 단순 기준선으로 씁니다. 내리막 보정이 없으므로 급경사 하강에는 과소평가합니다.",
             "refs": ["naismith1892"]},
            {"label": "B", "name": "Pandolf 운반 에너지 모델 (1977)",
             "origin": "체중·하중·속도·경사에 따른 대사 에너지(W)를 예측하는 식으로, 하중을 진 보행 실험에서 얻었습니다.",
             "intent": "에너지 모드에서만 경사에 반응합니다. 시간 모드는 일정 속도로 등방이므로 경사 반응 시간을 원하면 Tobler나 Naismith를 쓰십시오. 내리막은 원식 범위 밖이라 기립 대사량으로 하한 처리합니다.",
             "refs": ["pandolf1977"]},
            {"label": "B", "name": "Herzog 대사 다항식 (Minetti et al. 2002 자료)",
             "origin": "Minetti 등이 극한 경사(-45%에서 +45%)에서 실측한 보행 에너지 소비를 Herzog가 6차 다항식 비용함수로 정리했습니다.",
             "intent": "원식은 오르막·내리막을 구분(비등방)하지만 이 플러그인은 경사의 절대값에 적용(등방)합니다. 의도적인 단순화이므로 보고 시 명시합니다.",
             "refs": ["minetti2002", "herzog2013"]},
            {"label": "C", "name": "상대 경사 비용 (Conolly & Lake 2006 논의 참고)",
             "origin": "수식은 플러그인 정의입니다. 기준 경사 대비 tan 비율로 패널티를 주며, 두 저자의 상대 경사 비용 논의만 참고했습니다.",
             "intent": "결과 크기가 기준 경사에 전적으로 좌우되므로(기본 5°), 사용한 기준 경사를 반드시 함께 보고합니다.",
             "refs": ["conolly2006"]},
            {"label": "B", "name": "최단 경로 탐색 (Dijkstra 1959; Hart, Nilsson & Raphael 1968)",
             "origin": "누적 비용은 Dijkstra, 두 점 사이 경로는 A* 휴리스틱으로 찾습니다. 8방향 격자 이동이므로 경로 길이가 실제보다 최대 약 8% 길어질 수 있습니다.",
             "intent": "해상도를 너무 거칠게 잡으면 경로가 격자 방향에 끌립니다. 결과 경로는 비용 모델의 가정을 그대로 물려받습니다.",
             "refs": ["dijkstra1959", "hart1968"]},
        ],
        "workflow": [
            "질문을 정합니다. 시간이면 Tobler/Naismith, 에너지이면 Pandolf/Herzog.",
            "DEM 해상도와 마찰(하천·습지 등) 레이어를 준비합니다.",
            "모델 파라미터(기준 경사, 하중 등)를 정하고 결과 메타데이터에 기록된 값을 보고합니다.",
            "가능하면 두 모델을 비교해 경로가 모델에 얼마나 민감한지 확인합니다.",
        ],
        "not_claimed": ["최소비용경로는 실제 옛길의 증거가 아니라 가설입니다."],
    },
    "cost_network": {
        "title": "최소비용 네트워크",
        "methods": [
            {"label": "B", "name": "이동 비용 모델",
             "origin": "비용표면 도구와 같은 모델(Tobler, Naismith, Pandolf, Herzog, 상대 경사)을 씁니다. 각 모델의 출처와 의도는 비용표면 도움말과 같습니다.",
             "intent": "쌍마다 비용 누적을 따로 계산하므로 유적 수가 많으면 시간이 급증합니다. 반경·후보 수로 제한합니다.",
             "refs": ["tobler1993", "naismith1892", "pandolf1977", "herzog2013"]},
            {"label": "B", "name": "최소 신장 트리 (Kruskal 1956)",
             "origin": "모든 유적을 최소 총비용으로 잇는 나무 구조입니다. 간선을 비용순으로 정렬해 사이클 없이 붙이는 Kruskal 방식으로 구현했습니다.",
             "intent": "MST는 '가장 싼 연결망'이지 실제 교통망이 아닙니다. 유적 하나가 빠지면 나무 전체가 바뀔 수 있으므로 표본의 완전성을 검토합니다.",
             "refs": ["kruskal1956"]},
            {"label": "B", "name": "중심성 지표 (Freeman 1979; Brandes 2001; Wasserman & Faust 1994)",
             "origin": "Freeman이 개념을 정리한 연결·근접·매개 중심성입니다. betweenness는 Brandes 알고리즘, closeness는 끊긴 그래프 보정(Wasserman & Faust)을 적용합니다.",
             "intent": "betweenness 원값은 네트워크 크기에 따라 커집니다. 다른 네트워크와 비교하려면 정규화값(betw_norm)을 씁니다.",
             "refs": ["freeman1979", "brandes2001", "wf1994"]},
        ],
        "workflow": ["유적 목록의 완전성을 먼저 검토합니다.", "비용 모델과 파라미터를 정하고 보고합니다.", "MST와 중심성은 표본 변화에 민감하므로 대안 표본으로 재실행해 봅니다."],
        "not_claimed": ["네트워크 구조는 입력 유적 집합의 함수입니다."],
    },
    "spatial_network": {
        "title": "근접/가시성 네트워크",
        "methods": [
            {"label": "B", "name": "근접점 분석 PPA (Terrell 1977)",
             "origin": "Terrell은 솔로몬 제도에서 각 섬을 가장 가까운 몇 개 섬과 연결해 거리에 기반한 접촉 가능성 네트워크를 그렸습니다. 지형 비용 없이 직선거리로 '누가 누구와 닿기 쉬운가'를 보는 것이 원래 의도입니다.",
             "intent": "k는 3-5 정도가 원 연구의 취지에 가깝습니다. k가 커지면 간선이 급증해 구조가 사라집니다.",
             "refs": ["terrell1977"]},
            {"label": "B", "name": "근접 그래프: Delaunay·Gabriel·RNG (Delaunay 1934; Gabriel & Sokal 1969; Toussaint 1980)",
             "origin": "사이에 다른 점이 없는 쌍만 잇는 그래프들입니다. Gabriel은 두 점을 지름으로 하는 원의 안과 원 위에 다른 점이 없을 때(격자처럼 네 점이 한 원 위에 있으면 대각선은 빠짐), RNG는 두 점 양쪽에서 더 가까운 제3점이 없을 때 연결합니다. Gabriel & Sokal은 지리적 변이 분석용으로, Toussaint는 패턴 인식용으로 제안했습니다.",
             "intent": "k-NN보다 매개변수가 없어 재현성이 높습니다. 좌표가 같은 유적은 서로 연결되고 이웃 간선을 공유하며, 유적이 2곳이거나 한 직선 위에 있으면 세 그래프 모두 직선 순서의 경로가 되고, 그 수가 경고로 표시됩니다.",
             "refs": ["delaunay1934", "gabriel1969", "toussaint1980"]},
            {"label": "B", "name": "상호가시성 네트워크 (Van Dyke et al. 2016; Gillings & Wheatley 2001)",
             "origin": "유적 쌍마다 DEM 위에서 시선을 검사해 '서로 보이는가'로 연결합니다. Van Dyke 등은 차코 문화권의 대형 건물·신전 간 가시성 연결망을 분석했고, Gillings & Wheatley는 가시성 분석의 미해결 문제(식생·시대·표본)를 정리했습니다.",
             "intent": "지형 고도는 주변 4개 셀 중심의 양선형 보간으로 읽고, 샘플 간격은 DEM 픽셀 이하이며, 관측점·대상점이 놓인 셀은 장애물로 보지 않습니다. 곡률·굴절 보정(기본 0.13)이 적용됩니다. DEM NoData로 검사 못 한 쌍은 '샘플 실패'로 따로 세고(fail_deg), 안 보이는 것으로 취급하지 않습니다. 폴리곤 입력의 vis_ratio는 관측 폴리곤 경계 샘플 중 상대 대표점이 보이는 비율입니다.",
             "refs": ["vandyke2016", "gillings2001"]},
            {"label": "B", "name": "중심성 지표 (Freeman 1979; Brandes 2001; Wasserman & Faust 1994)",
             "origin": "연결·근접·매개 중심성으로 허브·요충지·고립을 수치화합니다.",
             "intent": "betweenness는 원시 쌍 개수이므로 크기가 다른 네트워크끼리는 betw_norm으로 비교합니다.",
             "refs": ["freeman1979", "brandes2001", "wf1994"]},
        ],
        "workflow": [
            "유적 목록의 완전성과 좌표 정확도를 검토합니다. 누락 유적은 네트워크를 왜곡합니다.",
            "PPA는 k 3-5 또는 Gabriel/RNG로 시작하고, 가시성은 높이·최대거리·곡률 보정을 정합니다.",
            "결과 레이어 이름과 메타데이터에 기록된 파라미터를 보고합니다.",
        ],
        "not_claimed": ["연결선은 상호작용의 증거가 아니라 가능성의 모형입니다."],
    },
    "dem_generator": {
        "title": "DEM 생성",
        "methods": [
            {"label": "A", "name": "TIN 선형 보간 (Delaunay 1934)",
             "origin": "점·등고선 정점을 들로네 삼각망으로 잇고 삼각형 안을 평면으로 채웁니다. 삼각형이 가늘고 길지 않게 하는 성질이 들로네 삼각분할의 요점입니다.",
             "intent": "입력점을 정확히 지나며 극값을 만들지 않습니다. 등고선만으로 만들면 능선·계곡에서 평평한 삼각형이 생기므로 표고점을 함께 넣습니다.",
             "refs": ["delaunay1934"]},
            {"label": "A", "name": "TIN 곡면 보간 (Clough & Tocher 1965)",
             "origin": "판 굽힘 유한요소 해석에서 나온 3차 곡면 조각으로 삼각형을 채워 매끈한 표면을 만듭니다.",
             "intent": "표면이 매끄러워지지만 입력 사이에서 미세한 오버슈트가 생길 수 있습니다.",
             "refs": ["clough1965"]},
            {"label": "A", "name": "IDW 역거리 가중 (Shepard 1968)",
             "origin": "주변 점을 거리의 거듭제곱 역수로 가중 평균합니다. Shepard는 불규칙 관측점의 2차원 보간을 위해 제안했습니다.",
             "intent": "가중 평균이라 입력 범위를 벗어난 값은 만들지 않고, 점 주변에 '황소눈' 무늬가 생기기 쉽습니다. 밀도 높은 점 자료에 적합합니다.",
             "refs": ["shepard1968"]},
            {"label": "B", "name": "Ordinary Kriging (Matheron 1963; Cressie 1993)",
             "origin": "공간 자기상관을 변동함수로 모형화해 최량선형불편 추정을 하는 지오통계 보간입니다. Matheron이 광상 평가에서 정립했습니다.",
             "intent": "'Lite'는 변동함수를 적합하지 않고 지수형 고정, 너깃 5%, 레인지는 최근린 간격 중앙값의 3배를 씁니다. 측점에서 입력값을 정확히 재현하며, 분산 래스터는 상대적 불확실성으로만 읽습니다. 사용한 값 필드는 완료 메시지와 메타데이터에 기록됩니다.",
             "refs": ["matheron1963", "cressie1993"]},
        ],
        "workflow": [
            "표고 필드(ELEV, 표고 등) 또는 3D 좌표가 있는지 확인합니다. 둘 다 없으면 실행이 거부됩니다.",
            "픽셀 크기는 입력 밀도에 맞춥니다. 실제 적용된 x/y 픽셀 크기가 메타데이터에 기록됩니다.",
            "입력점 위치에서 결과값을 몇 곳 확인해 보간이 입력을 재현하는지 봅니다.",
        ],
        "not_claimed": ["보간면은 측정이 아니라 추정입니다. 입력이 없는 곳의 값은 가정에 의존합니다."],
    },
    "contour_extractor": {
        "title": "등고선 추출",
        "methods": [
            {"label": "A", "name": "GDAL contour",
             "origin": "래스터 DEM에서 같은 표고를 잇는 표준 GIS 기법을 GDAL의 gdal_contour로 수행합니다. 특정 학술 방법의 구현이 아닙니다.",
             "intent": "간격은 DEM의 수직 정확도보다 작게 잡지 않습니다. 결과 필드 ELEV는 DEM 생성 도구가 그대로 읽습니다.",
             "refs": ["gdal"]},
        ],
        "workflow": ["DEM 해상도와 수직 정확도를 확인합니다.", "간격을 정하고 NoData 처리 결과를 확인합니다."],
        "not_claimed": [],
    },
    "geology_zip": {
        "title": "지질도 도엽 ZIP / 래스터 변환",
        "methods": [
            {"label": "C", "name": "KIGAM 1:50,000 지질도 자료",
             "origin": "한국지질자원연구원이 배포하는 도엽 단위 벡터 자료입니다. 이 도구는 자료를 불러오고 지질 코드를 정수 래스터로 굽습니다. 학술 알고리즘의 구현이 아니라 자료 준비 도구입니다.",
             "intent": "코드표(mapping CSV)는 실행 전체에서 하나로 통일되며 셀 수(cell_count)가 함께 기록됩니다. 셀보다 작은 암체는 굽히지 않으므로 픽셀 크기를 최소 암체 크기에 맞춥니다.",
             "refs": ["kigam_geo"]},
            {"label": "C", "name": "후속 예측모델 (Phillips et al. 2006; Elith et al. 2011)",
             "origin": "MaxEnt 등 예측모델에서 지질은 범주형 변수로 넣어야 합니다. Elith 등은 범주형 변수가 모델에서 어떻게 다뤄지는지 설명합니다.",
             "intent": "정렬/내보내기 도구가 이 래스터를 범주형으로 인식해 최근접 리샘플링하고 CATEGORICAL_PREDICTORS 목록에 넣습니다.",
             "refs": ["phillips2006", "elith2011"]},
        ],
        "workflow": ["도엽을 불러오고 값 필드를 확인합니다.", "픽셀 크기를 정하고 누락 코드 경고와 드롭 사유를 확인합니다.", "mapping CSV를 결과와 함께 보관합니다."],
        "not_claimed": ["래스터 코드는 이 실행의 코드표에서만 유효합니다."],
    },
    "geochem": {
        "title": "지구화학도 래스터 수치화",
        "methods": [
            {"label": "C", "name": "KIGAM 지구화학도 WMS 범례 역추정",
             "origin": "WMS는 수치가 아니라 렌더링된 색상입니다. 이 도구는 범례(색-값)를 이용해 색을 값으로 되돌리는 실무 기법이며, 학술 방법의 구현이 아닙니다.",
             "intent": "값은 추정값입니다. 범례 색과 먼 픽셀은 NoData로 제외되고 비율이 경고로 표시됩니다. 프리셋 범례는 백분위 구간표이므로 최상위 구간은 구간 상한값으로 기록됩니다. 확실한 결과가 필요하면 원자료를 기관에 요청하십시오.",
             "refs": ["kigam_chem"]},
        ],
        "workflow": ["해당 도면의 범례를 직접 등록하는 것이 가장 안전합니다.", "제외 픽셀 비율, 경계선 보간 비율(fill_pct)을 확인합니다.", "구역 통계는 픽셀 중심 규칙이며 zone_area와 비교해 픽셀화 오차를 봅니다."],
        "not_claimed": ["원자료 수치가 아닙니다."],
    },
    "cadastral_overlap": {
        "title": "지적도 중첩 면적표",
        "methods": [
            {"label": "C", "name": "지적 자료 중첩 면적",
             "origin": "법정 지적도(연속지적도)와 조사 구역을 중첩해 필지별 면적을 표로 만듭니다. 면적은 프로젝트 타원체가 설정되어 있으면 그 타원체 기준으로, 없음(NONE)이면 지적도 좌표계의 투영 평면에서 계산합니다(지리좌표계 지적도는 WGS84 타원체). 사용한 방식은 결과 메타데이터 area_method에 남습니다. 학술 방법의 구현이 아닙니다.",
             "intent": "지적 공부의 면적과 GIS 계산 면적은 좌표계·경계 정밀도 때문에 다를 수 있으므로 행정 절차에는 공부 면적을 우선합니다.",
             "refs": []},
        ],
        "workflow": ["미터 단위 투영 좌표계로 맞춥니다.", "중첩 결과의 면적 단위(m2)를 확인합니다."],
        "not_claimed": ["계산 면적은 법적 면적이 아닙니다."],
    },
    "align_export": {
        "title": "분석 결과 정렬/내보내기",
        "methods": [
            {"label": "C", "name": "예측변수 스택 준비 (Phillips et al. 2006; Elith et al. 2011)",
             "origin": "MaxEnt류 모델은 모든 예측변수가 같은 격자(좌표계·범위·픽셀)여야 합니다. 이 도구는 그 정렬을 하고, 범주형 변수를 최근접으로, 방향 변수(사면방향)도 최근접으로 리샘플링합니다.",
             "intent": "NoData는 래스터별로 다르며 manifest의 nodata 열에 기록됩니다. 메타데이터 없는 래스터는 categorical=unknown으로 표시되니 직접 확인하십시오. 사면방향 대신 북향성·동향성·TRASP를 넣는 것이 원 의도에 맞습니다.",
             "refs": ["phillips2006", "elith2011"]},
        ],
        "workflow": ["기준 격자(보통 DEM)를 정합니다.", "범주형·방향 변수의 리샘플링 표시를 확인합니다.", "manifest의 valid_pct로 결측이 많은 변수를 걸러냅니다."],
        "not_claimed": ["모델 적합은 외부 도구에서 합니다."],
    },
    "ahp": {
        "title": "AHP 입지적합도",
        "methods": [
            {"label": "B", "name": "계층분석법 AHP (Saaty 1980)",
             "origin": "기준을 1-9 척도로 쌍대비교해 주고유벡터로 가중치를 구하고, 일관성비율(CR)로 판단의 모순을 점검하는 의사결정 방법입니다. Saaty는 CR 0.10 이하를 권했고, 기준이 7±2개를 넘으면 계층으로 나누라고 했습니다.",
             "intent": "쌍대비교는 전문가 판단을 구조화하는 것이지 정답을 계산하는 것이 아닙니다. CR이 높으면 비교를 다시 하고, 기준이 많으면 계층 모드를 씁니다. 계층 모드에서는 전역가중치가 실제로 쓰이며 메타데이터에 weights_source가 기록됩니다.",
             "refs": ["saaty1980"]},
            {"label": "B", "name": "무작위 지수 RI 확장 (Alonso & Lamata 2006)",
             "origin": "기준 수 11-15에서의 RI 값입니다. 15를 넘으면 CR을 정의할 수 없어 '-'로 표시합니다.",
             "intent": "CR이 '-'이면 일관적이라는 뜻이 아니라 판단 불가라는 뜻입니다.",
             "refs": ["alonso2006"]},
            {"label": "C", "name": "GIS 기반 입지적합도 분석 개관 (Malczewski 2004)",
             "origin": "가중 선형 결합(WLC)과 AHP를 GIS 적합도 분석에 쓰는 방법과 그 한계를 정리한 리뷰입니다. 기준 정규화 방식과 가중치 민감도가 결과를 크게 좌우한다는 점을 지적합니다.",
             "intent": "정규화 방식(선형/구간)과 가중치를 바꿔 결과가 얼마나 달라지는지 민감도 분석을 곁들이는 것이 원 의도에 맞습니다.",
             "refs": ["malczewski2004"]},
        ],
        "workflow": ["기준 래스터를 정렬된 격자로 준비합니다.", "쌍대비교 후 CR을 확인하고 필요하면 계층으로 나눕니다.", "가중치·정규화 방식을 바꿔 민감도를 확인하고 메타데이터 값을 보고합니다."],
        "not_claimed": ["적합도는 판단의 구조화 결과이지 유적 존재 확률이 아닙니다."],
    },
    "trench_suggestion": {
        "title": "트렌치 후보 제안",
        "methods": [
            {"label": "C", "name": "플러그인 휴리스틱 (학술 방법 아님)",
             "origin": "AHP 적합도·경사·참고 유적 거리를 점수로 합쳐 AOI 전체에 분산 배치(커버리지 우선)하는 조사 보조 규칙입니다. 특정 문헌의 표본설계 방법을 구현한 것이 아닙니다.",
             "intent": "rank는 점수순, pick_order는 배치 순서입니다. 무덤 회피는 수치지형도 속성·범례 어휘에 의존하므로 대상 0건은 '무덤 없음'이 아닐 수 있습니다. 최종 배치는 현장 조사자가 판단합니다.",
             "refs": []},
        ],
        "workflow": ["AOI·DEM·(선택) AHP 결과를 준비합니다.", "간격·경사 상한·회피 설정을 정하고 결과 점수 구성을 확인합니다."],
        "not_claimed": ["유구 존재를 보장하지 않습니다."],
    },
    "distance_raster": {
        "title": "거리 래스터",
        "methods": [
            {"label": "A", "name": "GDAL proximity",
             "origin": "대상 피처를 격자에 굽고 각 셀에서 가장 가까운 대상 셀까지의 유클리드 거리를 계산합니다. 선·면은 닿는 셀을 모두 굽습니다(ALL_TOUCH).",
             "intent": "거리는 격자 해상도에서의 값입니다. 기준 래스터의 픽셀이 정사각이 아니면 거리가 왜곡되므로 거부됩니다.",
             "refs": ["gdal"]},
            {"label": "C", "name": "후속 예측모델 (Phillips et al. 2006)",
             "origin": "하천·유적·도로까지의 거리는 예측모델의 대표적 연속 변수입니다.",
             "intent": "거리 변수는 방향 정보가 없으므로 필요하면 비용 거리(비용표면 도구)를 대안으로 고려합니다.",
             "refs": ["phillips2006"]},
        ],
        "workflow": ["기준 격자와 대상 레이어의 좌표계를 맞춥니다.", "대상 셀 수(target_cells)가 0이 아닌지 확인합니다."],
        "not_claimed": [],
    },
    "covariate_report": {
        "title": "변수 상관 / VIF 리포트",
        "methods": [
            {"label": "B", "name": "상관계수와 분산팽창지수 VIF",
             "origin": "VIF = 1 / (1 - R²)로 한 변수가 다른 변수들로 얼마나 설명되는지를 잽니다. 널리 쓰이는 임계값 5 또는 10은 경험 규칙입니다.",
             "intent": "O'Brien(2007)은 VIF 임계값을 기계적으로 적용해 변수를 버리지 말라고 경고합니다. 표본 크기·효과 크기와 함께 판단하고, 변수를 제외할 때는 이론적 이유를 적습니다.",
             "refs": ["obrien2007"]},
            {"label": "C", "name": "예측모델 변수 선별 (Elith et al. 2011)",
             "origin": "MaxEnt는 상관된 변수에 비교적 강건하지만 해석(변수 기여도)은 흔들립니다.",
             "intent": "상관이 높은 쌍 중 고고학적으로 해석 가능한 쪽을 남깁니다.",
             "refs": ["elith2011"]},
        ],
        "workflow": ["정렬된 래스터 스택과 유적 점을 준비합니다.", "상관 행렬과 VIF를 보고, 제외 결정의 이유를 기록합니다."],
        "not_claimed": ["VIF 임계값은 규칙이 아니라 참고입니다."],
    },
    "terrain_profile": {
        "title": "지형 단면",
        "methods": [
            {"label": "C", "name": "단면 샘플링 (실무 기법)",
             "origin": "선을 따라 DEM을 일정 간격으로 샘플링해 표고 단면을 그립니다. 학술 방법의 구현이 아닙니다.",
             "intent": "샘플 간격은 DEM 해상도보다 작게 잡아도 정보가 늘지 않습니다. 수직 과장 배율을 그림에 명시합니다.",
             "refs": []},
        ],
        "workflow": ["단면선을 그리고 간격을 정합니다.", "수직 과장 배율을 기록합니다."],
        "not_claimed": [],
    },
    "map_styling": {
        "title": "도면 시각화",
        "methods": [
            {"label": "C", "name": "도면 스타일링 (실무)",
             "origin": "분석 결과를 보고서 도면 관례에 맞게 시각화합니다. 학술 방법의 구현이 아닙니다.",
             "intent": "색상 구간을 바꾸면 인상이 달라지므로 범례에 구간값을 적습니다.",
             "refs": []},
        ],
        "workflow": ["결과 레이어에 스타일을 적용하고 범례 구간을 확인합니다."],
        "not_claimed": [],
    },
    "ai_report": {
        "title": "AI 조사요약",
        "methods": [
            {"label": "C", "name": "AOI 통계 요약과 외부 AI 초안 (실무)",
             "origin": "AOI 주변 레이어의 통계를 표준 절차로 모아 요약하고, 선택하면 외부 생성형 AI(Gemini)에 보내 보고서 초안을 받습니다. 학술 방법의 구현이 아닙니다.",
             "intent": "통계에는 스캔 한도·표본 비율·절단 여부가 함께 기록됩니다. AI 초안은 검토용이며, 잘린 응답은 표시됩니다. 외부 전송 내용은 전송 고지에 나열됩니다.",
             "refs": []},
        ],
        "workflow": ["AOI와 대상 레이어를 정합니다.", "로컬 요약(CSV)을 먼저 확인하고, 필요하면 AI 초안을 받습니다."],
        "not_claimed": ["AI 초안은 검증된 해석이 아닙니다."],
    },
}

_LABEL_KO = {"A": "(A) QGIS/GDAL 알고리즘", "B": "(B) 플러그인 직접 구현", "C": "(C) 맥락·후속 참고"}


def available_tools() -> List[str]:
    return sorted(NOTES.keys())


def html_for(tool_id: str) -> str:
    """HTML block '학술 근거와 권장 절차' for one tool; empty string if unknown."""
    note: Optional[dict] = NOTES.get(str(tool_id or ""))
    if not note:
        return ""
    parts: List[str] = ["<h3>학술 근거와 권장 절차</h3>"]
    parts.append(
        "<p>이 도구가 어떤 연구를 근거로 무엇을 계산하는지, 그 연구자들이 의도한 사용법은 무엇인지 정리했습니다. "
        "표기: (A) QGIS/GDAL 알고리즘 호출, (B) 플러그인이 직접 구현한 수식, (C) 맥락·후속 분석 참고.</p>"
    )
    for m in note.get("methods", []):
        parts.append(f"<h4>{escape(_LABEL_KO.get(m.get('label', 'C'), ''))} - {escape(m.get('name', ''))}</h4>")
        parts.append(f"<p><b>어떤 연구인가:</b> {escape(m.get('origin', ''))}</p>")
        parts.append(f"<p><b>의도에 맞게 쓰려면:</b> {escape(m.get('intent', ''))}</p>")
    wf = note.get("workflow") or []
    if wf:
        parts.append("<h4>권장 절차</h4><ol>")
        parts.extend(f"<li>{escape(step)}</li>" for step in wf)
        parts.append("</ol>")
    nc = note.get("not_claimed") or []
    if nc:
        parts.append("<h4>이 도구가 주장하지 않는 것</h4><ul>")
        parts.extend(f"<li>{escape(x)}</li>" for x in nc)
        parts.append("</ul>")
    seen: List[str] = []
    for m in note.get("methods", []):
        for k in m.get("refs", []):
            if k in _R and k not in seen:
                seen.append(k)
    if seen:
        parts.append("<h4>원문</h4><ul>")
        parts.extend(f"<li>{escape(_R[k])}</li>" for k in seen)
        parts.append("</ul>")
    parts.append("<p>전체 서지와 검증 기록은 플러그인 폴더의 REFERENCES.md에 있습니다.</p>")
    return "\n".join(parts)


__all__ = ["NOTES", "available_tools", "html_for"]
