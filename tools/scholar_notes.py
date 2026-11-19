# -*- coding: utf-8 -*-
"""Per-tool notes on the scholarship behind each analysis, for the help dialogs.

Every dialog's help ends with the block returned by :func:`html_for`, so a user
sees, in one place: which published method the tool implements (and by whom),
how the authors meant it to be used, the practical sequence that follows that
intent, and what the tool does NOT claim. All bibliographic lines mirror
REFERENCES.md, which is the verified source; do not add a citation here that is
not in REFERENCES.md.

Labels follow REFERENCES.md: (A) algorithm called from QGIS/GDAL/PROJ/GEOS,
(B) formula or algorithm implemented in this plugin, (C) context, standard,
or downstream reference only.
"""
from __future__ import annotations

from html import escape
from typing import Dict, List, Optional

# --- shared bibliographic lines (verbatim from REFERENCES.md) -----------------
_R = {
    "karney2013": "Karney, C.F.F. (2013). Algorithms for geodesics. Journal of Geodesy, 87(1), 43-55. DOI: 10.1007/s00190-012-0578-z",
    "snyder1987": "Snyder, J.P. (1987). Map Projections—A Working Manual. USGS Professional Paper 1395. DOI: 10.3133/pp1395",
    "battersby2014": "Battersby, S.E., Finn, M.P., Usery, E.L., & Yamamoto, K.H. (2014). Implications of Web Mercator and Its Use in Online Mapping. Cartographica, 49(2), 85-101. DOI: 10.3138/carto.49.2.2313",
    "ogc2011": "Open Geospatial Consortium (2011). Simple Feature Access - Part 1: Common Architecture (ISO 19125-1:2004).",
    "horn1981": "Horn, B.K.P. (1981). Hill shading and the reflectance map. Proceedings of the IEEE, 69(1), 14-47. DOI: 10.1109/PROC.1981.11918",
    "zt1987": "Zevenbergen, L.W., & Thorne, C.R. (1987). Quantitative analysis of land surface topography. Earth Surface Processes and Landforms, 12(1), 47-56. DOI: 10.1002/esp.3290120107",
    "moore1991": "Moore, I.D., Grayson, R.B., & Ladson, A.R. (1991). Digital terrain modelling: A review of hydrological, geomorphological, and biological applications. Hydrological Processes, 5(1), 3-30. DOI: 10.1002/hyp.3360050103",
    "weiss2001": "Weiss, A. (2001). Topographic Position and Landforms Analysis. Poster, ESRI User Conference, San Diego.",
    "crow1984": "Crow, F.C. (1984). Summed-area tables for texture mapping. Computer Graphics (SIGGRAPH '84), 18(3), 207-212. DOI: 10.1145/800031.808600",
    "riley1999": "Riley, S.J., DeGloria, S.D., & Elliot, R. (1999). A terrain ruggedness index that quantifies topographic heterogeneity. Intermountain Journal of Sciences, 5(1-4), 23-27.",
    "wilson2007": "Wilson, M.F.J., O'Connell, B., Brown, C., Guinan, J.C., & Grehan, A.J. (2007). Multiscale terrain analysis of multibeam bathymetry data for habitat mapping on the continental slope. Marine Geodesy, 30(1-2), 3-35. DOI: 10.1080/01490410701295962",
    "hengl2009": "Hengl, T., & Reuter, H.I. (eds.) (2009). Geomorphometry: Concepts, Software, Applications. Elsevier. DOI: 10.1016/S0166-2481(08)X0001-7",
    "roberts1989": "Roberts, D.W., & Cooper, S.V. (1989). Concepts and techniques of vegetation mapping. USDA Forest Service GTR INT-257, 90-96.",
    "mardia2000": "Mardia, K.V., & Jupp, P.E. (2000). Directional Statistics. John Wiley & Sons. DOI: 10.1002/9780470316979",
    "kfs": "산림청 예규 「공·사유림 경영계획 작성 및 운영 요령」 [별표] 경사도 구분.",
    "wang2000": "Wang, J., Robinson, G.J., & White, K. (2000). Generating viewsheds without using sightlines. Photogrammetric Engineering & Remote Sensing, 66(1), 87-90.",
    "yoeli1985": "Yoeli, P. (1985). The Making of Intervisibility Maps with Computer and Plotter. Cartographica, 22(3), 88-103. DOI: 10.3138/J275-6460-8326-3733",
    "fisher1993": "Fisher, P.F. (1993). Algorithm and implementation uncertainty in viewshed analysis. IJGIS, 7(4), 331-347. DOI: 10.1080/02693799308901965",
    "higuchi": "樋口忠彦 (1975). 『景観の構造』. 技報堂. 영역본: Higuchi, T. (1983). The Visual and Spatial Structure of Landscapes. MIT Press.",
    "wheatley1995": "Wheatley, D. (1995). Cumulative viewshed analysis: a GIS-based method for investigating intervisibility, and its archaeological application. In: Lock, G., & Stančič, Z. (eds), Archaeology and Geographic Information Systems: A European Perspective. Taylor & Francis.",
    "cuckovic2016": "Čučković, Z. (2016). Advanced viewshed analysis: a Quantum GIS plug-in for the analysis of visual landscapes. Journal of Open Source Software, 1(4), 32. DOI: 10.21105/joss.00032",
    "tobler1993": "Tobler, W. (1993). Three Presentations on Geographical Analysis and Modeling. NCGIA Technical Report 93-1.",
    "imhof1950": "Imhof, E. (1950). Gelände und Karte. Eugen Rentsch Verlag, Erlenbach-Zürich.",
    "imhof1982": "Imhof, E. (1982; 2007 reprint). Cartographic Relief Presentation. Walter de Gruyter / ESRI Press. ISBN: 978-1-58948-026-1",
    "naismith1892": "Naismith, W.W. (1892). Cruach Ardran, Stobinian, and Ben More. Scottish Mountaineering Club Journal, 2(3), 135-136.",
    "pandolf1977": "Pandolf, K.B., Givoni, B., & Goldman, R.F. (1977). Predicting energy expenditure with loads while standing or walking very slowly. Journal of Applied Physiology, 43(4), 577-581. DOI: 10.1152/jappl.1977.43.4.577",
    "santee2001": "Santee, W.R., Allison, W.F., Blanchard, L.A., & Small, M.G. (2001). A proposed model for load carriage on sloped terrain. Aviation, Space, and Environmental Medicine, 72(6), 562-566. PMID: 11396562",
    "minetti2002": "Minetti, A.E., Moia, C., Roi, G.S., Susta, D., & Ferretti, G. (2002). Energy cost of walking and running at extreme uphill and downhill slopes. Journal of Applied Physiology, 93(3), 1039-1046. DOI: 10.1152/japplphysiol.01177.2001",
    "herzog2013": "Herzog, I. (2013). The potential and limits of Optimal Path Analysis. In: Bevan, A., & Lake, M. (eds), Computational Approaches to Archaeological Spaces. Left Coast Press, 179-211.",
    "cuckovic2025": "Čučković, Z. (2025). Movement Analysis (QGIS plugin). https://github.com/zoran-cuckovic/QGIS-movement-analysis/",
    "conolly2006": "Conolly, J., & Lake, M. (2006). Geographical Information Systems in Archaeology. Cambridge University Press.",
    "dijkstra1959": "Dijkstra, E.W. (1959). A note on two problems in connexion with graphs. Numerische Mathematik, 1(1), 269-271. DOI: 10.1007/BF01386390",
    "hart1968": "Hart, P.E., Nilsson, N.J., & Raphael, B. (1968). A formal basis for the heuristic determination of minimum cost paths. IEEE Transactions on Systems Science and Cybernetics, 4(2), 100-107. DOI: 10.1109/TSSC.1968.300136",
    "goodchild1977": "Goodchild, M.F. (1977). An evaluation of lattice solutions to the problem of corridor location. Environment and Planning A, 9(7), 727-738. DOI: 10.1068/a090727",
    "huber1985": "Huber, D.L., & Church, R.L. (1985). Transmission Corridor Location Modeling. Journal of Transportation Engineering, 111(2), 114-130. DOI: 10.1061/(ASCE)0733-947X(1985)111:2(114)",
    "etherington2012": "Etherington, T.R. (2012). Least-cost modelling on irregular landscape graphs. Landscape Ecology, 27(7), 957-968. DOI: 10.1007/s10980-012-9747-y",
    "douglas1994": "Douglas, D.H. (1994). Least-cost Path in GIS Using an Accumulated Cost Surface and Slopelines. Cartographica, 31(3), 37-51. DOI: 10.3138/D327-0323-2JUT-016M",
    "white2012": "White, D.A., & Surface-Evans, S.L. (eds.) (2012). Least Cost Analysis of Social Landscapes: Archaeological Case Studies. University of Utah Press.",
    "kruskal1956": "Kruskal, J.B. (1956). On the shortest spanning subtree of a graph and the traveling salesman problem. Proceedings of the American Mathematical Society, 7(1), 48-50. DOI: 10.1090/S0002-9939-1956-0078686-7",
    "freeman1979": "Freeman, L.C. (1979). Centrality in social networks: conceptual clarification. Social Networks, 1(3), 215-239. DOI: 10.1016/0378-8733(78)90021-7",
    "brandes2001": "Brandes, U. (2001). A faster algorithm for betweenness centrality. Journal of Mathematical Sociology, 25(2), 163-177. DOI: 10.1080/0022250X.2001.9990249",
    "wf1994": "Wasserman, S., & Faust, K. (1994). Social Network Analysis: Methods and Applications. Cambridge University Press.",
    "watts1998": "Watts, D.J., & Strogatz, S.H. (1998). Collective dynamics of 'small-world' networks. Nature, 393(6684), 440-442. DOI: 10.1038/30918",
    "boldi2014": "Boldi, P., & Vigna, S. (2014). Axioms for centrality. Internet Mathematics, 10(3-4), 222-262. DOI: 10.1080/15427951.2013.865686",
    "terrell1977": "Terrell, J.E. (1977). Human Biogeography in the Solomon Islands. Fieldiana Anthropology, 68(1), 1-47.",
    "delaunay1934": "Delaunay, B. (1934). Sur la sphère vide. Bulletin de l'Académie des Sciences de l'URSS, VII série, 1934(6), 793-800.",
    "gabriel1969": "Gabriel, K.R., & Sokal, R.R. (1969). A new statistical approach to geographic variation analysis. Systematic Zoology, 18(3), 259-278. DOI: 10.2307/2412323",
    "toussaint1980": "Toussaint, G.T. (1980). The relative neighbourhood graph of a finite planar set. Pattern Recognition, 12(4), 261-268. DOI: 10.1016/0031-3203(80)90066-7",
    "brughmans2017": "Brughmans, T., & Peeples, M.A. (2017). Trends in archaeological network research: a bibliometric analysis. Journal of Historical Network Research, 1, 1-24. DOI: 10.25517/jhnr.v1i1.10",
    "vandyke2016": "Van Dyke, R.M., Bocinsky, R.K., Windes, T.C., & Robinson, T.J. (2016). Great houses, shrines, and high places: intervisibility in the Chacoan world. American Antiquity, 81(2), 205-230. DOI: 10.7183/0002-7316.81.2.205",
    "gillings2001": "Gillings, M., & Wheatley, D. (2001). Seeing is not believing: unresolved issues in archaeological visibility analysis. In: On the Good Use of GIS in Archaeological Landscape Studies (COST Action G2).",
    "clough1965": "Clough, R.W., & Tocher, J.L. (1965). Finite element stiffness matrices for analysis of plates in bending. Proc. Conf. on Matrix Methods in Structural Mechanics, Wright-Patterson AFB, 515-545.",
    "shepard1968": "Shepard, D. (1968). A two-dimensional interpolation function for irregularly-spaced data. Proc. 23rd ACM National Conference, 517-524. DOI: 10.1145/800186.810616",
    "matheron1963": "Matheron, G. (1963). Principles of geostatistics. Economic Geology, 58(8), 1246-1266. DOI: 10.2113/gsecongeo.58.8.1246",
    "cressie1985": "Cressie, N. (1985). Fitting variogram models by weighted least squares. Mathematical Geology, 17(5), 563-586. DOI: 10.1007/BF01032109",
    "cressie1993": "Cressie, N. (1993). Statistics for Spatial Data. John Wiley & Sons.",
    "webster2007": "Webster, R., & Oliver, M.A. (2007). Geostatistics for Environmental Scientists (2nd ed.). John Wiley & Sons.",
    "chiles2012": "Chilès, J.-P., & Delfiner, P. (2012). Geostatistics: Modeling Spatial Uncertainty (2nd ed.). John Wiley & Sons. DOI: 10.1002/9781118136188",
    "golub2013": "Golub, G.H., & Van Loan, C.F. (2013). Matrix Computations (4th ed.). Johns Hopkins University Press. DOI: 10.1137/1.9781421407944",
    "saaty1980": "Saaty, T.L. (1980). The Analytic Hierarchy Process. McGraw-Hill.",
    "alonso2006": "Alonso, J.A., & Lamata, M.T. (2006). Consistency in the Analytic Hierarchy Process: a new approach. Int. J. of Uncertainty, Fuzziness and Knowledge-Based Systems, 14(4), 445-459. DOI: 10.1142/S0218488506004114",
    "malczewski2004": "Malczewski, J. (2004). GIS-based land-use suitability analysis: a critical overview. Progress in Planning, 62(1), 3-65. DOI: 10.1016/j.progress.2003.09.002",
    "chen2010": "Chen, Y., Yu, J., & Khan, S. (2010). Spatial sensitivity analysis of multi-criteria weights in GIS-based land suitability evaluation. Environmental Modelling & Software, 25(12), 1582-1591. DOI: 10.1016/j.envsoft.2010.06.001",
    "phillips2006": "Phillips, S.J., Anderson, R.P., & Schapire, R.E. (2006). Maximum entropy modeling of species geographic distributions. Ecological Modelling, 190(3-4), 231-259. DOI: 10.1016/j.ecolmodel.2005.03.026",
    "elith2011": "Elith, J., Phillips, S.J., Hastie, T., Dudík, M., Chee, Y.E., & Yates, C.J. (2011). A statistical explanation of MaxEnt for ecologists. Diversity and Distributions, 17(1), 43-57. DOI: 10.1111/j.1472-4642.2010.00725.x",
    "pearson1895": "Pearson, K. (1895). Note on regression and inheritance in the case of two parents. Proceedings of the Royal Society of London, 58, 240-242. DOI: 10.1098/rspl.1895.0041",
    "spearman1904": "Spearman, C. (1904). The Proof and Measurement of Association between Two Things. American Journal of Psychology, 15(1), 72-101. DOI: 10.2307/1412159",
    "marquardt1970": "Marquardt, D.W. (1970). Generalized Inverses, Ridge Regression, Biased Linear Estimation, and Nonlinear Estimation. Technometrics, 12(3), 591-612. DOI: 10.1080/00401706.1970.10488699",
    "mardia1976": "Mardia, K.V. (1976). Linear-circular correlation coefficients and rhythmometry. Biometrika, 63(2), 403-405. DOI: 10.1093/biomet/63.2.403",
    "obrien2007": "O'Brien, R.M. (2007). A caution regarding rules of thumb for variance inflation factors. Quality & Quantity, 41(5), 673-690. DOI: 10.1007/s11135-006-9018-6",
    "gottschalk1996": "Gottschalk, S., Lin, M.C., & Manocha, D. (1996). OBBTree: A Hierarchical Structure for Rapid Interference Detection. SIGGRAPH '96, 171-180. DOI: 10.1145/237170.237244",
    "kintigh1988": "Kintigh, K.W. (1988). The Effectiveness of Subsurface Testing: A Simulation Approach. American Antiquity, 53(4), 686-707. DOI: 10.2307/281113",
    "orton2000": "Orton, C. (2000). Sampling in Archaeology. Cambridge University Press. DOI: 10.1017/CBO9781139163996",
    "banning2002": "Banning, E.B. (2002). Archaeological Survey. Kluwer Academic / Springer. DOI: 10.1007/978-1-4615-0769-7",
    "heritage_law": "대한민국 「매장유산 보호 및 조사에 관한 법률」 및 국가유산청 고시 「발굴조사의 방법 및 절차 등에 관한 규정」·「지표조사의 방법 및 절차 등에 관한 규정」.",
    "kigam_geo": "한국지질자원연구원(KIGAM). 1:50,000 수치지질도 도엽(벡터 SHP, ZIP) - MGEO (https://mgeo.kigam.re.kr).",
    "kigam_chem": "한국지질자원연구원(KIGAM). 전국 지구화학도 WMS 렌더링 이미지 - MGEO (https://mgeo.kigam.re.kr).",
    "porter1984": "Porter, T., & Duff, T. (1984). Compositing Digital Images. Computer Graphics (SIGGRAPH '84), 18(3), 253-259. DOI: 10.1145/800031.808606",
    "esri1998": "ESRI (1998). ESRI Shapefile Technical Description (White Paper).",
    "pkware_zip": "PKWARE Inc. .ZIP File Format Specification (APPNOTE.TXT, General Purpose Bit 11 UTF-8 flag).",
    "molit_cad": "국토교통부(MOLIT). 연속지적도형정보 (V-World) 및 「공간정보의 구축 및 관리 등에 관한 법률」.",
    "ngii_code": "국토지리정보원(NGII). 전국 연속수치지형도 코드 및 레이어 설명서 Ver 5.1.1 및 「수치지도 작성 작업규칙」.",
    "harrower2003": "Harrower, M., & Brewer, C.A. (2003). ColorBrewer.org: An Online Tool for Selecting Colour Schemes for Maps. The Cartographic Journal, 40(1), 27-37. DOI: 10.1179/000870403235002042",
    "owasp_csv": "OWASP Foundation. CSV Injection (Formula Injection). https://owasp.org/www-community/attacks/CSV_Injection",
    "wilkinson2016": "Wilkinson, M.D., et al. (2016). The FAIR Guiding Principles for scientific data management and stewardship. Scientific Data, 3, 160018. DOI: 10.1038/sdata.2016.18",
    "carroll2020": "Carroll, S.R., et al. (2020). The CARE Principles for Indigenous Data Governance. Data Science Journal, 19, 43. DOI: 10.5334/dsj-2020-043",
    "gemini_api": "Google (2026). Gemini API Documentation. https://ai.google.dev/gemini-api/docs",
    "gdal": "GDAL/OGR contributors (2026). GDAL/OGR Geospatial Data Abstraction software Library. OSGeo. DOI: 10.5281/zenodo.5884351",
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
             "intent": "값은 격자 해상도에서의 국지 기울기입니다. 지리좌표계뿐 아니라 웹 메르카토르(EPSG:3857)처럼 거리가 위도별로 왜곡되는 투영도 거부합니다. DEM 해상도를 함께 적어야 비교가 됩니다.",
             "refs": ["horn1981", "battersby2014"]},
            {"label": "B", "name": "곡률 (Zevenbergen & Thorne 1987; Moore et al. 1991)",
             "origin": "3x3 창에 2차 다항면을 적합해 종단(profile)·횡단(plan) 곡률을 구합니다. 원 논문의 목적은 지형에서 침식·퇴적 경향과 유수의 수렴·발산을 정량화하는 것이었습니다.",
             "intent": "종단 음(-)=볼록(침식 경향), 양(+)=오목(퇴적 경향); 횡단 음(-)=수렴(물 모임), 양(+)=발산(능선). GRASS/SAGA와는 부호가 반대이니 교차 검증 시 부호만 뒤집혀 보이면 정상입니다.",
             "refs": ["zt1987", "moore1991"]},
            {"label": "B", "name": "TPI와 지형 위치 6분류 (Weiss 2001; Crow 1984)",
             "origin": "TPI는 중심 셀 고도에서 주변 평균을 뺀 값입니다. Weiss의 핵심 주장은 척도(scale)이며, 반경 2셀 이상에서는 Crow(1984)의 2차원 누적합표(summed-area table)로 (2r+1)x(2r+1) 창의 정확한 초점평균(중심 셀 제외)을 계산합니다.",
             "intent": "반경은 찾으려는 지형 단위의 크기에 맞추고(구릉 수백 m, 산체 수 km), 임계값은 자동 SD를 권장합니다. 창 내 유효 이웃 비율이 75% 미만이면 가장자리 왜곡을 막기 위해 NoData 처리합니다.",
             "refs": ["weiss2001", "crow1984"]},
            {"label": "A", "name": "TRI (Riley et al. 1999)",
             "origin": "3x3 이웃과의 표고차 제곱합의 제곱근입니다. 야생동물 서식지의 지형 이질성을 한 숫자로 나타내려고 만든 지수로, 원 논문은 절대 미터값 기준 7등급(0-80 m 평탄에서 959-4367 m 극험준)을 제시했습니다.",
             "intent": "지수는 Riley의 것이고, 화면의 5등급은 사용자가 준 험준 기준값에 비례한 플러그인 표시 구분입니다. 논문의 7등급으로 보고하려면 원 미터값 구간을 쓰십시오. 반경 2셀 이상의 TRI는 RMS 형태라 단위가 달라 별도 지표입니다.",
             "refs": ["riley1999"]},
            {"label": "A", "name": "Roughness (Wilson et al. 2007; Hengl & Reuter 2009)",
             "origin": "창 안 최대-최소 표고차입니다. 다중척도 해저 지형 분석에서 서식지 매핑용으로 정의된 지표를 gdaldem이 3x3으로 구현했습니다.",
             "intent": "5등급(0-1/1-3/3-6/6-15/15 m 이상)은 한국 지형을 염두에 둔 플러그인 표시 관례입니다.",
             "refs": ["wilson2007", "hengl2009"]},
            {"label": "B", "name": "사면 파생 지표: 북향성·동향성·TRASP (Roberts & Cooper 1989)",
             "origin": "원형 변수인 사면방향(0-360°)은 평균을 낼 수 없으므로 cos/sin으로 펼칩니다. TRASP = (1 - cos(방향 - 30°)) / 2 는 식생 매핑에서 일사량의 대리변수로 제안된 변환으로, 북북동 0(가장 차가움)에서 남남서 1(가장 따뜻함)입니다.",
             "intent": "예측모델(MaxEnt 등)에는 원 사면방향 대신 이 파생 변수를 넣어야 합니다. 정렬/내보내기 도구는 원 사면방향을 최근접으로만 리샘플링합니다.",
             "refs": ["roberts1989"]},
            {"label": "C", "name": "경사 등급 프리셋 (산림청 예규)",
             "origin": "'한국표준'은 산림청 예규 별표의 경사도 구분입니다. '보행속도구분·에너지구분·인지구분(플러그인)' 세 가지는 Tobler·Minetti·Llobera의 논의를 참고해 플러그인이 정한 표시 구분이며, 그 저자들이 출판한 등급표가 아닙니다.",
             "intent": "논문·규정의 분류로 보고할 수 있는 것은 한국표준뿐입니다. 나머지는 '플러그인 정의'로 적으십시오.",
             "refs": ["kfs"]},
        ],
        "workflow": [
            "DEM의 해상도와 좌표계(미터 단위 투영, EPSG:3857 제외)를 먼저 확인합니다.",
            "경사·사면방향은 그대로 산출하고, 예측모델용이면 사면 파생(북향성·동향성·TRASP)을 켭니다.",
            "지형 위치 분류는 대상 지형 규모에 맞춘 반경으로, 가능하면 두 척도를 비교합니다. 임계값은 자동 SD를 권장합니다.",
            "결과 레이어 메타데이터(params_json)에 반경·임계값·프리셋이 기록되므로 보고서에는 그 값을 옮겨 적습니다.",
        ],
        "not_claimed": ["플러그인 정의 등급 구분은 문헌의 분류가 아닙니다.", "DEM 가장자리 r셀과 유효 이웃 비율 75% 미만 창은 NoData로 처리합니다."],
    },
    "slope_aspect_drafting": {
        "title": "경사도/사면방향 도면화",
        "methods": [
            {"label": "A", "name": "경사도·사면방향 (Horn 1981)",
             "origin": "gdaldem의 기본 3x3 커널(Horn 방식)로 경사와 방향을 계산합니다. Horn은 음영기복도 계산을 위해 이 차분식을 제안했습니다.",
             "intent": "도면 표기용이므로 등급 구간은 도면 목적에 맞춰 고르되, 사용한 구간을 범례에 명시합니다. 지리 좌표계와 웹 메르카토르 DEM은 미터 단위 결과를 낼 수 없어 거부됩니다.",
             "refs": ["horn1981", "battersby2014"]},
            {"label": "B", "name": "블록 대표 방위 원형 평균 (Mardia & Jupp 2000)",
             "origin": "화살표 격자 블록 내 모든 유효 셀에 대해 경사 가중 원형 평균 방위를 계산해 355°와 5°가 180°로 오산출되는 산술 평균 오류를 막습니다.",
             "intent": "단일 중심 셀 표본 대신 블록 전체의 지배적 사면방향을 반영하므로 도면 축척에 맞춰 화살표 간격을 조정하십시오.",
             "refs": ["mardia2000", "imhof1982"]},
        ],
        "workflow": ["미터 단위 투영 DEM을 준비합니다.", "등급 구간과 화살표 간격을 정하고 범례에 구간을 적습니다."],
        "not_claimed": ["등급 구간은 도면 관례이며 특정 문헌의 분류가 아닙니다."],
    },
    "viewshed": {
        "title": "가시권 분석",
        "methods": [
            {"label": "A", "name": "가시권 계산 (Wang, Robinson & White 2000)",
             "origin": "gdal_viewshed가 구현한 기준면(reference-plane) 방식입니다. 시선을 하나하나 긋는 대신 기준면을 바깥으로 전파해 격자 DEM의 가시권을 빠르게 구합니다.",
             "intent": "관측자 높이(예: 눈높이 1.6 m)와 대상 높이를 분석 질문에 맞게 정하고, 지구 곡률·굴절 보정(기본 굴절계수 0.13)을 켠 채 계산합니다. 최대 거리는 대상의 크기와 대기 조건을 고려해 제한합니다.",
             "refs": ["wang2000", "fisher1993"]},
            {"label": "B", "name": "지구 곡률·대기 굴절 보정 (Yoeli 1985)",
             "origin": "원거리 시선에서 지구 곡률과 표준 대기 굴절(k=0.13)에 따른 겉보기 고도 강하 (1-k)·d²/(2R)을 gdal_viewshed(-cc)와 LOS 단면에 동일하게 적용합니다.",
             "intent": "반경 수 km 이상 분석에서는 곡률·굴절 보정을 켜는 것이 표준입니다. 보정 여부와 굴절계수는 메타데이터에 기록됩니다.",
             "refs": ["yoeli1985"]},
            {"label": "C", "name": "히구치 거리대 (Higuchi 1975; 영역본 1983)",
             "origin": "히구치는 경관을 근경·중경·원경으로 나누되, 그 경계를 미터가 아니라 대상 높이 대비 거리 비율(D/H)로 정의했습니다. 나무 같은 지배적 대상이 어느 거리까지 어떻게 지각되는가에서 출발한 개념입니다.",
             "intent": "기본값 500 m / 2500 m는 GIS 실무 관례일 뿐 히구치의 수치가 아닙니다. 대상(성벽·고분·산체)의 높이에 비례해 경계를 조정하고, 사용한 값을 보고합니다. 결과 메타데이터에 실제 경계값이 기록됩니다.",
             "refs": ["higuchi"]},
            {"label": "C", "name": "누적 가시권 및 출력 구조 참고 (Wheatley 1995; Čučković 2016)",
             "origin": "Wheatley(1995)는 여러 유적의 가시권을 합산해 상호가시성 집중도를 검토했고, Observers/Targets/Viscode 출력 구성은 Čučković(2016)의 QGIS Visibility Analysis 플러그인을 참고했습니다.",
             "intent": "누적값은 관측점 집합에 전적으로 좌우됩니다. 유적 목록이 불완전하면 누적 가시권도 불완전하므로 표본의 한계를 함께 적습니다.",
             "refs": ["wheatley1995", "cuckovic2016"]},
        ],
        "workflow": [
            "DEM 해상도와 미터 투영 좌표계를 확인하고 관측점(또는 폴리곤 대표점)을 준비합니다.",
            "관측자·대상 높이, 최대 거리, 곡률·굴절 보정을 정합니다.",
            "히구치 경계는 대상 높이에 맞춰 조정하고, 누적 가시권은 관측점 집합의 완전성을 검토합니다.",
            "결과의 '보임'은 지형만 고려한 것입니다. 식생·건물·당시 지형 변화는 반영되지 않습니다.",
        ],
        "not_claimed": ["가시권은 '실제로 보였음'이 아니라 '지형이 가리지 않음'입니다."],
    },
    "cost_surface": {
        "title": "비용표면 / 최소비용경로",
        "methods": [
            {"label": "B", "name": "Tobler 하이킹 함수 (Tobler 1993; Imhof 1950)",
             "origin": "보행 속도 v = 6·exp(-3.5·|tanθ + 0.05|) km/h. Imhof(1950)의 경험적 등산 자료를 함수로 정리한 것으로, 경사 약 -5%(완만한 내리막)에서 가장 빠르고 오르막·급한 내리막에서 느려집니다. 오프패스 이동은 0.6배를 권했습니다.",
             "intent": "도보 이동 시간을 묻는 질문에 씁니다. 70° 초과 절벽은 통행 불가로 차단하며 방향에 따라 값이 다른 비등방 함수이므로 왕복 시간은 다릅니다.",
             "refs": ["tobler1993", "imhof1950"]},
            {"label": "B", "name": "Naismith 규칙 (1892)",
             "origin": "등산 계획용 시간 규칙입니다. 수평 3마일당 1시간에 오르막 2000피트당 1시간을 더합니다.",
             "intent": "시간 추정의 단순 기준선으로 씁니다. 내리막 보정이 없으므로 급경사 하강에는 과소평가합니다.",
             "refs": ["naismith1892"]},
            {"label": "B", "name": "Pandolf 운반 에너지 모델 (Pandolf et al. 1977; Santee et al. 2001)",
             "origin": "체중·하중·속도·경사에 따른 대사 에너지(W)를 예측하는 식으로, 하중을 진 보행 실험에서 얻었습니다.",
             "intent": "에너지 모드에서만 경사에 반응합니다. 내리막은 원식 범위 밖(Santee et al. 2001)이므로 하중 포함 기립 대사율(1.5·W + 2.0·(W+L)·(L/W)²)로 하한 처리합니다.",
             "refs": ["pandolf1977", "santee2001"]},
            {"label": "B", "name": "Herzog 대사 다항식·차량 모델 (Minetti et al. 2002; Herzog 2013; Čučković 2025)",
             "origin": "Minetti 등(2002)의 보행 에너지 실측치를 Herzog(2013)가 부호 있는 경사의 6차 다항식으로 정리한 비용함수와 차량/수레 임계경사(%) 모델입니다(구현 파라미터화는 Čučković 2025 참고).",
             "intent": "에너지 모드에서 실제 대사 줄(body_kg·C(s)·거리, kcal 환산)을 계산하며 실험 검증 구간은 ±45%입니다. 차량 임계경사(기본 12%)는 경사도 % 단위입니다.",
             "refs": ["minetti2002", "herzog2013", "cuckovic2025"]},
            {"label": "C", "name": "상대 경사 비용 (Conolly & Lake 2006 논의 참고)",
             "origin": "수식은 플러그인 정의입니다. 기준 경사 대비 tan 비율로 패널티를 주며, 두 저자의 상대 경사 비용 논의만 참고했습니다.",
             "intent": "결과 크기가 기준 경사에 전적으로 좌우되므로(기본 5°), 사용한 기준 경사를 반드시 함께 보고합니다.",
             "refs": ["conolly2006"]},
            {"label": "B", "name": "최단 경로·16방향 나이트 이동·격자 신장 오차 (Dijkstra 1959; Hart et al. 1968; Goodchild 1977; Huber & Church 1985; Douglas 1994; Etherington 2012)",
             "origin": "누적 비용은 Dijkstra, 두 점 사이 경로는 A* 휴리스틱으로 계산하며 1픽셀 대각선·나이트 이동의 NoData·절벽·고마찰 장벽 관통을 차단합니다. 격자 신장 오차는 4방향 최대 41.4%, 8방향 최대 8.24%이며(Goodchild 1977; Douglas 1994), 16방향 나이트 이동 옵션(Huber & Church 1985; Etherington 2012)을 켜면 최대 2.75%까지 줄어듭니다.",
             "intent": "정밀 연구 비교에는 16방향 나이트 이동을 권장합니다. 회랑과 LCP는 모델 가정을 그대로 물려받는 가설이므로 절대 수치보다 상대 비교로 해석하십시오(White & Surface-Evans 2012).",
             "refs": ["dijkstra1959", "hart1968", "goodchild1977", "huber1985", "douglas1994", "etherington2012", "white2012"]},
        ],
        "workflow": [
            "질문을 정합니다. 시간이면 Tobler/Naismith, 에너지이면 Pandolf/Herzog.",
            "미터 투영 DEM(EPSG:3857 제외)과 마찰(하천·습지 등) 레이어를 준비합니다.",
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
             "refs": ["tobler1993", "naismith1892", "pandolf1977", "minetti2002", "herzog2013", "white2012"]},
            {"label": "B", "name": "최소 신장 트리 (Kruskal 1956)",
             "origin": "모든 유적을 최소 총비용으로 잇는 나무 구조입니다. 간선을 비용순으로 정렬해 사이클 없이 붙이는 Kruskal 방식으로 구현했습니다.",
             "intent": "MST는 '가장 싼 연결망'이지 실제 교통망이 아닙니다. 유적 하나가 빠지면 나무 전체가 바뀔 수 있으므로 표본의 완전성을 검토합니다.",
             "refs": ["kruskal1956"]},
            {"label": "B", "name": "중심성·군집 계수 (Freeman 1979; Brandes 2001; Wasserman & Faust 1994; Watts & Strogatz 1998; Boldi & Vigna 2014)",
             "origin": "Freeman의 연결·근접·매개 중심성에 더해 국소 군집계수(Watts & Strogatz)와 단절 그래프에서도 왜곡 없는 조화 중심성(Boldi & Vigna)을 함께 산출합니다. betweenness는 Brandes 알고리즘, closeness는 Wasserman & Faust 성분 보정을 적용합니다.",
             "intent": "betweenness 원값은 네트워크 크기에 따라 커집니다. 다른 네트워크와 비교하려면 정규화값(betw_norm)과 조화 중심성(harmonic), 국소 군집계수(clustering)를 함께 보십시오.",
             "refs": ["freeman1979", "brandes2001", "wf1994", "watts1998", "boldi2014"]},
        ],
        "workflow": ["유적 목록의 완전성을 먼저 검토합니다.", "비용 모델과 파라미터를 정하고 보고합니다.", "MST와 중심성은 표본 변화에 민감하므로 대안 표본으로 재실행해 봅니다."],
        "not_claimed": ["네트워크 구조는 입력 유적 집합의 함수입니다."],
    },
    "spatial_network": {
        "title": "근접/가시성 네트워크",
        "methods": [
            {"label": "B", "name": "근접점 분석 PPA (Terrell 1977; Brughmans & Peeples 2017)",
             "origin": "Terrell은 솔로몬 제도에서 각 섬을 가장 가까운 몇 개 섬과 연결해 거리에 기반한 접촉 가능성 네트워크를 그렸습니다. 지형 비용 없이 직선거리로 '누가 누구와 닿기 쉬운가'를 보는 것이 원래 의도입니다.",
             "intent": "k는 3-5 정도가 원 연구의 취지에 가깝습니다. k가 커지면 간선이 급증해 구조가 사라집니다.",
             "refs": ["terrell1977", "brughmans2017"]},
            {"label": "B", "name": "근접 그래프: Delaunay·Gabriel·RNG (Delaunay 1934; Gabriel & Sokal 1969; Toussaint 1980)",
             "origin": "사이에 다른 점이 없는 쌍만 잇는 그래프들입니다. Gabriel은 두 점을 지름으로 하는 원의 안과 원 위에 다른 점이 없을 때, RNG는 두 점 양쪽에서 더 가까운 제3점이 없을 때(스케일 불변 상대 허용오차 적용) 연결합니다.",
             "intent": "k-NN보다 매개변수가 없어 재현성이 높습니다. 좌표가 같은 유적은 서로 연결되고 이웃 간선을 공유하며, 유적이 2곳이거나 한 직선 위에 있으면 세 그래프 모두 직선 순서의 경로가 됩니다.",
             "refs": ["delaunay1934", "gabriel1969", "toussaint1980"]},
            {"label": "B", "name": "상호가시성 네트워크 (Yoeli 1985; Van Dyke et al. 2016; Gillings & Wheatley 2001)",
             "origin": "유적 쌍마다 DEM 위에서 양선형 보간 시선과 Yoeli(1985) 곡률·굴절 보정(기본 0.13)을 적용해 상호가시성 연결망을 만듭니다. Van Dyke 등은 차코 문화권의 상호가시성 망을 분석했고, Gillings & Wheatley는 가시성 분석의 한계를 정리했습니다.",
             "intent": "DEM NoData로 검사 못 한 쌍은 '샘플 실패'로 따로 세고(fail_deg), 안 보이는 것으로 취급하지 않습니다. 폴리곤 입력의 vis_ratio는 유효 경계 표본 대비 가시 비율입니다.",
             "refs": ["yoeli1985", "vandyke2016", "gillings2001"]},
            {"label": "B", "name": "중심성·군집 계수 (Freeman 1979; Brandes 2001; Wasserman & Faust 1994; Watts & Strogatz 1998; Boldi & Vigna 2014)",
             "origin": "연결·근접·매개·조화 중심성과 국소 군집계수로 허브·요충지·삼각 결속·고립을 수치화합니다.",
             "intent": "betweenness는 원시 쌍 개수이므로 크기가 다른 네트워크끼리는 betw_norm으로, 단절 그래프 중심성은 harmonic으로 비교합니다.",
             "refs": ["freeman1979", "brandes2001", "wf1994", "watts1998", "boldi2014"]},
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
            {"label": "B", "name": "Ordinary Kriging · WLS 변동함수 적합 · LOOCV · 이방성/추세 진단 (Matheron 1963; Cressie 1985; Chilès & Delfiner 2012; Golub & Van Loan 2013)",
             "origin": "공간 자기상관을 변동함수로 모형화해 최량선형불편 추정을 하는 등방성 국소 Ordinary Kriging입니다. 선택 시 Cressie(1985) WLS 목적함수를 직접 최소화해 모델을 적합하고, 대각 유사 스케일링(Golub & Van Loan 2013)으로 고기복 행렬 조건수를 안정화하며, 너겟 중복점 분산(Chilès & Delfiner 2012), LOOCV(RMSE, MSDR), 4방위 이방성 비·1차 평면 추세 R² 가정 진단을 산출합니다.",
             "intent": "강한 방향성 이방성(비 2.0 이상)이나 광역 추세(R² 0.30 이상) 경고가 뜨면 정상성·등방성 가정이 약해지므로 R(gstat) Universal/이방성 Kriging으로 교차 검증하십시오.",
             "refs": ["matheron1963", "cressie1985", "cressie1993", "webster2007", "chiles2012", "golub2013"]},
        ],
        "workflow": [
            "표고 필드(ELEV, 표고 등) 또는 3D 좌표가 있는지 확인합니다. 둘 다 없으면 실행이 거부됩니다.",
            "지리 좌표계(도)·웹 메르카토르 입력과 Z가 모두 0인 3D 자료는 거부됩니다. 점은 점으로, 선·면은 구조선으로 보간에 들어갑니다.",
            "픽셀 크기는 입력 밀도에 맞춥니다. 실제 적용된 x/y 픽셀 크기가 메타데이터에 기록됩니다.",
            "입력점 위치에서 결과값을 몇 곳 확인해 보간이 입력을 재현하는지 봅니다.",
        ],
        "not_claimed": ["보간면은 측정이 아니라 추정입니다. 입력이 없는 곳의 값은 가정에 의존합니다."],
    },
    "contour_extractor": {
        "title": "등고선 추출",
        "methods": [
            {"label": "A", "name": "GDAL contour (GDAL/OGR contributors 2026)",
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
            {"label": "C", "name": "KIGAM 1:50,000 수치지질도 및 파일·인코딩 표준 (ESRI 1998; PKWARE APPNOTE)",
             "origin": "한국지질자원연구원이 배포하는 도엽 단위 Shapefile/ZIP 자료를 불러오고 지질 코드를 정수 래스터로 굽습니다. ZIP UTF-8 플래그(0x800, PKWARE APPNOTE) 미표시 CP949 한글 파일명과 .dbf/.cpg 인코딩(ESRI 1998)을 판별해 복원합니다.",
             "intent": "코드표(mapping CSV)는 실행 전체에서 하나로 통일되며 숫자·문자열 코드 모두 도엽 간 라벨 충돌을 탐지하고 셀 수(cell_count)를 기록합니다. 픽셀 크기를 최소 암체 크기에 맞추십시오.",
             "refs": ["kigam_geo", "esri1998", "pkware_zip"]},
            {"label": "C", "name": "후속 예측모델 (Phillips et al. 2006; Elith et al. 2011)",
             "origin": "MaxEnt 등 예측모델에서 지질은 범주형 변수로 넣어야 합니다. Elith 등은 범주형 변수가 모델에서 어떻게 다뤄지는지 설명합니다.",
             "intent": "정렬/내보내기 도구가 이 래스터를 범주형으로 인식해 최근접 리샘플링하고 CATEGORICAL_PREDICTORS 목록에 넣습니다.",
             "refs": ["phillips2006", "elith2011"]},
        ],
        "workflow": ["도엽을 불러오고 CRS와 값 필드를 확인합니다.", "픽셀 크기를 정하고 누락 코드·도엽 간 코드 충돌 경고를 확인합니다.", "mapping CSV를 결과와 함께 보관합니다."],
        "not_claimed": ["래스터 코드는 이 실행의 코드표에서만 유효합니다."],
    },
    "geochem": {
        "title": "지구화학도 래스터 수치화",
        "methods": [
            {"label": "C", "name": "KIGAM 지구화학도 WMS 범례 역추정 및 알파 합성 제외 (Porter & Duff 1984)",
             "origin": "WMS는 수치가 아니라 렌더링된 색상입니다. 이 도구는 범례 폴리라인 최근접 투영으로 색을 값으로 역추정하는 실무 기법이며, 반투명 경계 픽셀(alpha < 250)의 프리멀티플라이 알파 어두워짐(Porter & Duff 1984)으로 인한 고농도 오매칭을 막기 위해 NoData 처리합니다.",
             "intent": "값은 추정값입니다. 회색 무자료(Stop 0)는 연속 보간에서 분리되고, 범례 색과 먼 픽셀은 NoData로 제외됩니다. 확실한 결과가 필요하면 원자료를 기관에 요청하십시오.",
             "refs": ["kigam_chem", "porter1984"]},
        ],
        "workflow": ["해당 도면의 범례를 직접 등록하는 것이 가장 안전합니다.", "제외 픽셀 비율, 경계선 보간 비율(fill_pct)을 확인합니다.", "구역 통계는 픽셀 중심 규칙이며 zone_area와 비교해 픽셀화 오차를 봅니다."],
        "not_claimed": ["원자료 수치가 아닙니다."],
    },
    "cadastral_overlap": {
        "title": "지적도 중첩 면적표",
        "methods": [
            {"label": "A", "name": "타원체 측지 면적 및 OGC/GEOS 폴리곤 중첩 (Karney 2013; OGC SFA / ISO 19125-1)",
             "origin": "프로젝트 타원체가 설정된 경우 QGIS QgsDistanceArea(Karney 2013 측지 알고리즘)로 타원체 면적을, NONE이면 지적도 투영 평면 면적을 계산하며 GEOS로 유효화(makeValid)·교차(intersection)합니다.",
             "intent": "웹 메르카토르(EPSG:3857) 평면 면적은 크게 과대 계산되므로 국내 투영좌표계(EPSG:5186/5179)나 타원체 설정을 권장합니다. 사용한 방식은 메타데이터 area_method에 남습니다.",
             "refs": ["karney2013", "ogc2011", "battersby2014"]},
            {"label": "C", "name": "연속지적도 자료 출처 (국토교통부 V-World)",
             "origin": "법정 지적도(연속지적도형정보)와 조사 구역을 중첩해 필지별 면적표를 작성합니다.",
             "intent": "지적 공부의 면적과 GIS 계산 면적은 좌표계·경계 정밀도 때문에 다를 수 있으므로 행정 절차에는 공부 면적을 우선합니다.",
             "refs": ["molit_cad"]},
        ],
        "workflow": ["미터 단위 투영 좌표계(EPSG:5186/5179 등)로 맞춥니다.", "중첩 결과의 면적 단위(m2)와 위상 오류 건너뜀 경고를 확인합니다."],
        "not_claimed": ["계산 면적은 법적 면적이 아닙니다."],
    },
    "align_export": {
        "title": "분석 결과 정렬/내보내기",
        "methods": [
            {"label": "A", "name": "GDAL 재투영·격자 정렬 (GDAL/OGR contributors 2026; Snyder 1987)",
             "origin": "모든 예측변수를 기준 래스터의 단일 북향(North-Up) 격자(CRS·범위·해상도)로 gdal:warpreproject를 이용해 정렬하고 원자적으로 게시합니다.",
             "intent": "범주형 변수와 방향(사면방향) 변수는 최근접으로, 연속형 변수는 이중선형으로 리샘플링됩니다. 메타데이터 없는 래스터는 categorical=unknown으로 표시되니 직접 확인하십시오.",
             "refs": ["gdal", "snyder1987"]},
            {"label": "C", "name": "예측변수 스택 준비 (Phillips et al. 2006; Elith et al. 2011)",
             "origin": "MaxEnt류 생태·고고학 분포 예측모델은 모든 예측변수가 동일한 격자와 일관된 NoData 정의를 갖출 것을 요구합니다.",
             "intent": "manifest의 nodata와 valid_pct 열로 결측이 많은 변수를 점검하고, 사면방향 원값 대신 북향성·동향성·TRASP 사용을 권장합니다.",
             "refs": ["phillips2006", "elith2011"]},
        ],
        "workflow": ["북향 투영 기준 격자(보통 DEM)를 정합니다.", "범주형·방향 변수의 리샘플링 표시를 확인합니다.", "manifest의 valid_pct로 결측이 많은 변수를 걸러냅니다."],
        "not_claimed": ["모델 적합은 외부 도구에서 합니다."],
    },
    "ahp": {
        "title": "AHP 입지적합도",
        "methods": [
            {"label": "B", "name": "계층분석법 AHP (Saaty 1980)",
             "origin": "기준을 1-9 척도로 쌍대비교해 주고유벡터로 가중치를 구하고, 일관성비율(CR)로 판단의 모순을 점검하는 의사결정 방법입니다. Saaty는 CR 0.10 이하를 권했고, 기준이 7±2개를 넘으면 계층으로 나누라고 했습니다.",
             "intent": "쌍대비교는 전문가 판단을 구조화하는 것이지 정답을 계산하는 것이 아닙니다. 계층 모드에서는 전역가중치가 실제 계산에 쓰이고, 방법론 보고서에는 그룹 CR과 하위 로컬 CR이 분리 기록됩니다.",
             "refs": ["saaty1980"]},
            {"label": "B", "name": "무작위 지수 RI 확장 (Alonso & Lamata 2006)",
             "origin": "기준 수 11-15에서의 RI 값입니다. 15를 넘으면 CR을 정의할 수 없어 '-'로 표시합니다.",
             "intent": "CR이 '-'이면 일관적이라는 뜻이 아니라 판단 불가라는 뜻입니다.",
             "refs": ["alonso2006"]},
            {"label": "B", "name": "GIS 기반 입지적합도 및 OAT 민감도 분석 (Malczewski 2004; Chen et al. 2010)",
             "origin": "가중 선형 결합(WLC)과 AHP를 GIS 적합도 분석에 적용하는 이론과 한계를 정리하고(Malczewski 2004), 기준 가중치를 변화시키는 일대일(OAT) 민감도 분석(Chen et al. 2010)과 Markdown 방법론 보고서를 제공합니다.",
             "intent": "정규화 방식(선형/구간)과 OAT 민감도의 순위 변동 여부를 방법론 보고서로 점검해 보고서에 첨부하십시오.",
             "refs": ["malczewski2004", "chen2010"]},
        ],
        "workflow": ["기준 래스터를 정렬된 격자로 준비합니다(사면방향 등 원형 변수는 최근접 리샘플링).", "쌍대비교 후 CR을 확인하고 필요하면 계층으로 나눕니다.", "방법론 보고서로 OAT 민감도와 가중치를 점검·보관합니다."],
        "not_claimed": ["적합도는 판단의 구조화 결과이지 유적 존재 확률이 아닙니다."],
    },
    "trench_suggestion": {
        "title": "트렌치 후보 제안",
        "methods": [
            {"label": "B", "name": "2D 분리축 정리(SAT) 발자국 경사 검사 및 축방향(2θ) 방향 결정 (Gottschalk et al. 1996; Mardia & Jupp 2000)",
             "origin": "회전된 트렌치 사각형이 걸치는 모든 DEM 셀 박스를 2D 분리축 정리(Gottschalk et al. 1996)로 정확히 교차 판정해 가장자리 급경사를 놓치지 않으며, 대칭 능선에서는 Mardia & Jupp(2000)의 배각(2θ) 축방향 통계로 배치 방위를 결정합니다.",
             "intent": "5 m·10 m DEM에서도 트렌치 가장자리가 걸치는 절벽 셀이 slope_max_deg에 정확히 반영됩니다.",
             "refs": ["gottschalk1996", "mardia2000"]},
            {"label": "C", "name": "고고학 시굴·표본조사 설계 맥락 (배치 점수식은 플러그인 휴리스틱)",
             "origin": "AHP 적합도·경사·참고 유적 거리를 합산해 AOI 전체에 분산 배치하는 조사 보조 규칙입니다. 고고학 표본·시굴조사 이론(Kintigh 1988; Orton 2000; Banning 2002)과 국내 매장유산 조사 규정의 현장 실무 맥락을 참고하되, 특정 문헌의 확률 표본식을 구현한 것은 아닙니다.",
             "intent": "rank는 점수순, pick_order는 배치 순서입니다. 무덤 회피는 수치지형도 속성·범례 어휘에 의존하므로 대상 0건이 '무덤 없음'을 뜻하지 않으며, 최종 배치는 현장 조사자가 판단합니다.",
             "refs": ["kintigh1988", "orton2000", "banning2002", "heritage_law"]},
        ],
        "workflow": ["AOI·미터 투영 DEM·(선택) AHP 결과를 준비합니다.", "간격·경사 상한·회피 설정을 정하고 결과 점수 구성을 확인합니다."],
        "not_claimed": ["유구 존재를 보장하지 않으며, 배치 점수식은 학술 표본이론 공식이 아닌 플러그인 휴리스틱입니다."],
    },
    "distance_raster": {
        "title": "거리 래스터",
        "methods": [
            {"label": "A", "name": "GDAL proximity 및 래스터화 (GDAL/OGR contributors 2026; Battersby et al. 2014)",
             "origin": "대상 피처를 기준 격자에 굽고(선·면은 -at) 각 셀에서 가장 가까운 대상 셀까지의 유클리드 거리를 계산합니다. 거리가 위도별로 왜곡되는 지리좌표계·웹 메르카토르(EPSG:3857)·비정사각 픽셀 격자는 거부합니다.",
             "intent": "거리는 격자 해상도에서의 값이며 기준 래스터의 NoData 마스크가 출력에 그대로 전파됩니다.",
             "refs": ["gdal", "battersby2014"]},
            {"label": "C", "name": "후속 예측모델 (Phillips et al. 2006)",
             "origin": "하천·유적·도로까지의 거리는 예측모델의 대표적 연속 변수입니다.",
             "intent": "거리 변수는 지형 경사를 반영하지 않으므로 필요하면 비용 거리(비용표면 도구)를 대안으로 고려합니다.",
             "refs": ["phillips2006"]},
        ],
        "workflow": ["미터 투영 정사각 기준 격자(EPSG:3857 제외)와 대상 레이어를 선택합니다.", "대상 셀 수(target_cells)가 0이 아닌지 확인합니다."],
        "not_claimed": ["직선 유클리드 거리이며 지형 기복이나 이동 장벽을 반영하지 않습니다."],
    },
    "covariate_report": {
        "title": "변수 상관 / VIF 리포트",
        "methods": [
            {"label": "B", "name": "상관계수(Pearson/Spearman)·VIF·순환-선형 R² (Pearson 1895; Spearman 1904; Marquardt 1970; Mardia 1976; O'Brien 2007)",
             "origin": "Pearson 선형 상관, Spearman 순위 상관, Marquardt(1970)의 분산팽창지수 VIF = 1/(1-R²)(혼합 스케일 왜곡 방지를 위해 z-표준화 적용)로 다중공선성을 진단합니다. 사면방향 같은 원형 변수는 연속 VIF에서 제외하고 Mardia(1976) 순환-선형 R²와 정확 F-검정 p-값(n>=4)으로 별도 평가합니다.",
             "intent": "O'Brien(2007)은 VIF 임계값(5·10)을 기계적으로 적용해 변수를 버리지 말라고 경고합니다. 표본 크기·효과 크기·순위 상관·순환 상관과 함께 판단하십시오.",
             "refs": ["pearson1895", "spearman1904", "marquardt1970", "mardia1976", "obrien2007"]},
            {"label": "C", "name": "예측모델 변수 선별 (Elith et al. 2011)",
             "origin": "MaxEnt는 상관된 변수에 비교적 강건하지만 해석(변수 기여도)은 흔들립니다.",
             "intent": "상관이 높은 쌍 중 고고학적으로 해석 가능한 쪽을 남깁니다.",
             "refs": ["elith2011"]},
        ],
        "workflow": ["정렬된 래스터 스택과 AOI를 준비합니다.", "상관 행렬·VIF·원형 상관을 검토하고 변수 제외 근거를 기록합니다."],
        "not_claimed": ["VIF 임계값은 규칙이 아니라 참고선입니다."],
    },
    "terrain_profile": {
        "title": "지형 단면",
        "methods": [
            {"label": "A", "name": "측지·투영 단면 거리 계산 (Karney 2013)",
             "origin": "단면선을 따라 DEM을 등간격 샘플링해 고도 단면을 구성하며, QgsDistanceArea(Karney 2013)로 수평 거리를 계산합니다.",
             "intent": "샘플 간격은 DEM 해상도보다 작게 잡아도 원자료 정보가 늘지 않습니다. NoData 구간에서는 선을 끊고 누적 상승·경사 통계에서 제외합니다.",
             "refs": ["karney2013"]},
            {"label": "C", "name": "단면 도화 및 수직 과장 표기 (Imhof 1982/2007)",
             "origin": "지형 단면에서 수직 과장(vertical exaggeration)을 명시하지 않으면 경사 인상이 왜곡된다는 지도학 원칙을 따라 화면과 출력 이미지에 실제 과장 배율을 표시합니다.",
             "intent": "원시 표본이 기본이며 이동평균 평활화를 켠 경우 창 크기가 이미지와 통계에 함께 기록됩니다.",
             "refs": ["imhof1982"]},
        ],
        "workflow": ["단면선을 그리고 DEM 해상도에 맞는 간격을 정합니다.", "수직 과장 배율과 NoData 구간 길이를 보고서에 함께 적습니다."],
        "not_claimed": ["이동평균 평활화 곡선은 원시 표고가 아닌 시각 보조 곡선입니다."],
    },
    "map_styling": {
        "title": "도면 시각화",
        "methods": [
            {"label": "A", "name": "DEM 음영기복 렌더링 (Horn 1981)",
             "origin": "배경 DEM의 음영기복 레이어는 QGIS QgsHillshadeRenderer(Horn 1981의 3x3 기울기 기반)를 사용합니다.",
             "intent": "그레이 배경은 DEM 최소-최대로 선형 스트레치하며, 음영기복·그레이·고도색상을 겹쳐 지형 판독성을 높입니다.",
             "refs": ["horn1981"]},
            {"label": "C", "name": "국토지리정보원 수치지형도 표준코드 및 지도학 배색 (NGII Ver 5.1.1; Imhof 1982; Harrower & Brewer 2003)",
             "origin": "도로·하천·건물 분류 코드와 명칭은 국토지리정보원 전국 연속수치지형도 코드 및 레이어 설명서 Ver 5.1.1을 따르며, 고도색상·발산형 배색은 지도학적 기복 표현(Imhof 1982)과 ColorBrewer 원리(Harrower & Brewer 2003)를 참고했습니다.",
             "intent": "색상 구간을 바꾸면 지형 인상이 달라지므로 범례에 구간값을 반드시 표시하고, 스타일 대상 밖 원본 피처 건수를 확인합니다.",
             "refs": ["ngii_code", "imhof1982", "harrower2003"]},
        ],
        "workflow": ["수치지형도 DXF/SHP와 DEM을 선택합니다.", "스타일 적용 후 범례 구간과 미스타일 코드 개수를 확인합니다."],
        "not_claimed": ["시각화 레이어는 도면화 보조 산출물이며 법적·측량 원도를 대체하지 않습니다."],
    },
    "ai_report": {
        "title": "AI 조사요약",
        "methods": [
            {"label": "A", "name": "타원체 공간 통계 및 선택적 Gemini API (Karney 2013; Google Gemini API)",
             "origin": "AOI 및 버퍼 면적·거리·중첩 통계는 QGIS QgsDistanceArea(Karney 2013)로 산출하고, 사용자가 명시적으로 허용한 경우에만 외부 생성형 AI(Google Gemini API)로 요약 초안을 생성합니다.",
             "intent": "무료(로컬) 모드는 외부로 아무것도 전송하지 않습니다. Gemini 모드는 AOI·레이어 범위가 바뀔 때마다 전송 동의를 다시 확인합니다.",
             "refs": ["karney2013", "gemini_api"]},
            {"label": "B", "name": "원형 방향 통계 및 CSV 수식 주입 방어 (Mardia & Jupp 2000; OWASP CSV Injection)",
             "origin": "사면방향 등 원형 래스터는 산술 평균 대신 Mardia & Jupp(2000)의 원형 평균 방위와 집중도 R을 계산하며, CSV 내보내기 시 OWASP 권고에 따라 수식 주입(=, +, -, @)을 무력화합니다.",
             "intent": "통계에는 스캔 한도·표본 비율·절단 여부·버퍼 범위 기준이 함께 기록됩니다.",
             "refs": ["mardia2000", "owasp_csv"]},
            {"label": "C", "name": "연구 데이터 투명성 및 매장유산 위치정보 보호 (Wilkinson et al. 2016; Carroll et al. 2020; 매장유산법)",
             "origin": "번들 내보내기(report.md + context.json + CSV + params.json)는 FAIR 원칙(Wilkinson et al. 2016)의 재현성 정신을 따르며, 외부 AI 전송 동의 절차는 문화유산 데이터 거버넌스(Carroll et al. 2020)와 국내 매장유산 위치정보 보호 의무를 반영했습니다.",
             "intent": "민감한 매장유산 위치·속성이 포함된 프로젝트는 로컬 모드를 사용하거나 사전 검토 후 전송하십시오.",
             "refs": ["wilkinson2016", "carroll2020", "heritage_law"]},
        ],
        "workflow": ["AOI와 대상 레이어를 정합니다.", "로컬 요약과 통계 CSV를 먼저 검토한 뒤, 필요하면 전송 범위를 확인하고 AI 초안을 받습니다."],
        "not_claimed": ["AI 초안은 검증된 고고학적 해석이 아니며 최종 검토 책임은 사용자에게 있습니다."],
    },
}

_LABEL_KO = {"A": "(A) QGIS/GDAL 알고리즘", "B": "(B) 플러그인 직접 구현", "C": "(C) 맥락·표준·후속 참고"}

# Per-tool research usage tier, concise metadata caveat (stamped onto output
# layers automatically by set_archtoolkit_layer_metadata), and optional UI
# banner shown directly inside dialogs where methodological overclaiming is
# most likely in academic manuscripts.
RESEARCH_DISCLOSURES: Dict[str, Dict[str, str]] = {
    "dem_generator": {
        "tier": "tier2_conditional",
        "scope_ko": "연구 모형 유의",
        "caveat": "보간 DEM은 측정이 아닌 추정치입니다. Kriging(Lite)는 등방성 국소 Ordinary Kriging이므로 강한 이방성·추세 경고 시 R(gstat) 교차 검증을 권장합니다.",
        "banner": "보간면은 추정치입니다. Kriging(Lite)는 등방성 국소 Ordinary Kriging이며, 강한 이방성·광역 추세가 감지되면 경고를 표시합니다(엄밀한 지오통계 추론은 R gstat 교차 검증 권장).",
    },
    "contour_extractor": {
        "tier": "tier1_standard",
        "scope_ko": "표준 알고리즘",
        "caveat": "등고선 간격은 원본 DEM의 수직 정확도 이상으로 설정하고 DEM 출처와 해상도를 함께 보고하십시오.",
        "banner": "",
    },
    "terrain_analysis": {
        "tier": "tier1_standard",
        "scope_ko": "표준 알고리즘",
        "caveat": "곡률 부호는 ESRI 규약(GRASS/SAGA와 반대)이며, 화면 5등급 중 한국표준 경사 외에는 플러그인 표시 관례입니다.",
        "banner": "",
    },
    "slope_aspect_drafting": {
        "tier": "tier1_standard",
        "scope_ko": "표준 도면화",
        "caveat": "경사 등급 구간은 도면 관례이므로 범례에 구간값과 화살표 블록 간격을 명시하십시오.",
        "banner": "",
    },
    "viewshed": {
        "tier": "tier2_conditional",
        "scope_ko": "연구 모형 유의",
        "caveat": "DEM(지형) 단독 가시권이며 고식생·당대 건축물·기상 조건·지형 개변을 반영하지 않습니다('지형 차폐 없음'으로 서술 권장).",
        "banner": "이 결과는 입력 DEM(지형)만 고려합니다. 식생·건물·기상·당시 지형 개변은 반영되지 않으므로 논문에는 '실제로 보였음'이 아니라 '지형 차폐 없음'으로 서술하고, 필요 시 DSM을 사용하십시오.",
    },
    "cost_surface": {
        "tier": "tier2_conditional",
        "scope_ko": "연구 모형 유의",
        "caveat": "격자 누적 비용 모형(4방향 최대 41.4%·8방향 8.2%·16방향 2.75% 신장 오차)이며 최소비용경로는 실제 옛길의 증거가 아닌 가설입니다.",
        "banner": "격자 기반 이동비용 모형입니다(최대 신장오차: 8방향 8.2% / 16방향 나이트 이동 2.75%). 절대 시간·칼로리 주장보다 상대 비교와 가설로 해석하십시오.",
    },
    "cost_network": {
        "tier": "tier2_conditional",
        "scope_ko": "연구 모형 유의",
        "caveat": "유클리드 후보 k-NN 위 격자 LCP 근사 네트워크이며, 실제 교통망 증명이 아니라 입력 유적 집합과 비용 가정의 함수입니다.",
        "banner": "유클리드 후보(k) 위 격자 LCP 근사 연결망입니다(16방향 나이트 이동으로 격자 오차를 2.75% 이하로 줄일 수 있음). 유적 표본 누락과 모형 민감도를 함께 보고하십시오.",
    },
    "spatial_network": {
        "tier": "tier2_conditional",
        "scope_ko": "연구 모형 유의",
        "caveat": "근접·가시성 연결망은 실제 상호작용의 증명이 아닌 가능성 모형이며, 가시성은 입력 DEM(지형) 단독 시선 기준입니다.",
        "banner": "연결선은 실제 교류의 증명이 아닌 가능성 모형입니다. 유적 목록 누락에 민감하며, 가시성 모드는 DEM(지형) 단독 시선(식생·건물 미반영) 기준입니다.",
    },
    "distance_raster": {
        "tier": "tier1_standard",
        "scope_ko": "표준 알고리즘",
        "caveat": "직선 유클리드 거리이며 지형 경사·하천 등 이동 장벽을 반영하지 않습니다.",
        "banner": "",
    },
    "align_export": {
        "tier": "tier1_standard",
        "scope_ko": "표준 전처리",
        "caveat": "manifest의 categorical·resampling·valid_pct 열을 확인해 범주·방향 변수의 리샘플링과 결측 비율을 보고하십시오.",
        "banner": "",
    },
    "covariate_report": {
        "tier": "tier1_standard",
        "scope_ko": "표준 통계 진단",
        "caveat": "VIF 임계값(5·10)은 절대 규칙이 아닌 참고선(O'Brien 2007)이며, 원형 변수는 순환-선형 R²로 별도 해석합니다.",
        "banner": "",
    },
    "ahp": {
        "tier": "tier2_conditional",
        "scope_ko": "연구 모형 유의",
        "caveat": "AHP 적합도는 전문가 판단의 구조화(상대 지수)이지 유적 존재 확률이 아닙니다. CR과 OAT 민감도 보고서를 함께 제시하십시오.",
        "banner": "AHP 적합도는 전문가 판단을 구조화한 상대 지수이며 유적 존재 확률이 아닙니다. 논문에는 일관성비율(CR)과 OAT 가중치 민감도 보고서를 함께 제시하십시오.",
    },
    "geology_zip": {
        "tier": "tier1_standard",
        "scope_ko": "표준 전처리",
        "caveat": "래스터 정수 코드는 해당 실행의 mapping CSV에서만 유효하며, 픽셀 크기보다 좁은 암체는 소실될 수 있습니다.",
        "banner": "",
    },
    "geochem": {
        "tier": "tier3_exploratory_aid",
        "scope_ko": "예비 탐색·시각화용",
        "caveat": "KIGAM WMS 렌더링 색상에서 역추정한 근사값이며 원시 지구화학 분석치가 아닙니다. 정량 학술 논문에는 기관 원시 분석치를 사용하십시오.",
        "banner": "이 도구의 출력은 WMS 렌더링 색상에서 역추정한 근사값(원시 분석치 아님)입니다. 예비 탐색·시각화 용도로만 쓰고, 정량 지구화학 논문에는 KIGAM 원시 분석치를 사용하십시오.",
    },
    "trench_suggestion": {
        "tier": "tier3_exploratory_aid",
        "scope_ko": "현장 시굴 보조 (휴리스틱)",
        "caveat": "발자국 경사(2D SAT)·방위(2θ) 계산은 정확하나 배치 점수식은 플러그인 휴리스틱이며 확률 표본이론 공식이나 유구 존재 보장이 아닙니다.",
        "banner": "배치 점수식은 학술 확률 표본설계가 아닌 현장 시굴 보조 휴리스틱입니다(유구 존재 보장 아님, 무덤 회피 0건 = 무덤 없음 아님). 최종 배치는 현장 조사자가 판단하십시오.",
    },
    "cadastral_overlap": {
        "tier": "tier3_exploratory_aid",
        "scope_ko": "행정·조사 참고용",
        "caveat": "GIS 중첩 계산 면적은 좌표계·경계 정밀도 차이로 지적 공부 면적과 다를 수 있으며 법적 효력이 없습니다.",
        "banner": "계산된 면적·비율은 GIS 중첩 참고값이며 법정 지적 공부 면적을 대체하지 않습니다. 행정·인허가·법적 보고에는 지적 공부 면적을 우선하십시오.",
    },
    "terrain_profile": {
        "tier": "tier1_standard",
        "scope_ko": "표준 도화",
        "caveat": "단면 보고 시 수직 과장 배율, NoData 구간 길이, 이동평균 평활화 적용 여부를 함께 표기하십시오.",
        "banner": "",
    },
    "map_styling": {
        "tier": "tier1_standard",
        "scope_ko": "도면 시각화 보조",
        "caveat": "도면화 보조 산출물이며 법정·측량 원도를 대체하지 않습니다. 미스타일 코드 개수를 확인하십시오.",
        "banner": "",
    },
    "ai_report": {
        "tier": "tier3_exploratory_aid",
        "scope_ko": "조사요약 보조·초안",
        "caveat": "AI 초안은 검증된 고고학 해석이 아니며 최종 검토 책임은 연구자에게 있습니다. 외부 AI 전송 시 매장유산 위치정보 보호에 유의하십시오.",
        "banner": "AI 초안은 검증된 고고학 해석이 아닌 참고 초안입니다(로컬 모드는 외부 전송 없음). Gemini 모드 사용 시 매장유산 위치정보 보호 규정을 먼저 확인하십시오.",
    },
}


def research_disclosure_for(tool_id: str) -> Dict[str, str]:
    """Return research scope tier, metadata caveat, and UI banner for a tool."""
    return dict(RESEARCH_DISCLOSURES.get(str(tool_id or "").strip(), {}))


def available_tools() -> List[str]:
    return sorted(NOTES.keys())


def html_for(tool_id: str) -> str:
    """HTML block '학술 근거와 권장 절차' for one tool; empty string if unknown."""
    note: Optional[dict] = NOTES.get(str(tool_id or ""))
    if not note:
        return ""
    parts: List[str] = ["<h3>학술 근거와 권장 절차</h3>"]
    parts.append(
        "<p>이 도구가 어떤 연구·표준을 근거로 무엇을 계산하는지, 원저자·규정이 의도한 사용법은 무엇인지 정리했습니다. "
        "표기: (A) QGIS/GDAL/PROJ 알고리즘 호출, (B) 플러그인이 직접 구현한 수식, (C) 맥락·표준·후속 분석 참고.</p>"
    )
    for m in note.get("methods", []):
        parts.append(f"<h4>{escape(_LABEL_KO.get(m.get('label', 'C'), ''))} - {escape(m.get('name', ''))}</h4>")
        parts.append(f"<p><b>어떤 근거인가:</b> {escape(m.get('origin', ''))}</p>")
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
    parts.append("<p>전체 서지와 DOI 검증 기록은 플러그인 폴더의 REFERENCES.md에 있습니다.</p>")
    return "\n".join(parts)


__all__ = ["NOTES", "RESEARCH_DISCLOSURES", "available_tools", "html_for", "research_disclosure_for"]
