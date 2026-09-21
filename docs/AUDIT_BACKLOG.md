# ArchToolkit 감사 백로그

**아직 코드에 적용되지 않은** 감사 결과입니다. 검증 수준이 전혀 다른 두 종류가 섞이지 않도록 구분했습니다.

| 장 | 내용 | 검증 수준 | 착수 가능 |
| --- | --- | --- | --- |
| 1-3 | 인용 검증 (73건) | Crossref·Math-Net.Ru·law.go.kr 등 **외부 1차 출처 직접 조회**, 이견 항목은 **3중 독립 판정** | 대부분 반영 완료 |
| 4 | 검증 하네스 계획 (14건) | 판독자가 수치를 직접 재현 | **예** — QGIS 불필요 |
| 5 | 코드 감사 — 검증 통과 (43건) | **반박·재현·영향 3중 렌즈 과반 생존** | **예** |
| 6 | 코드 감사 — 미검증 (110건) | 단일 판독자 1차 지적, 검증 미완주 | 아니오 — 개별 재확인 선행 |

**두 단계의 독립 검증이 모두 과잉 지적을 대량으로 걸러냈습니다.** 인용에서는 1차 `NOT_SUPPORTED` 12건이 3차 독립 판정 후 **3건**으로 줄었고(그 3건도 현재 HEAD에서 해소됨), 코드 감사에서는 167건 중 **124건이 기각**되어 43건만 남았습니다(생존율 26%). 6장을 확정 결함으로 읽지 마십시오 — 같은 비율이라면 대부분 기각됩니다.


## 1. 인용 검증 최종 요약 (73건 / 인벤토리 73건)

### 존재하지 않는 문헌: **0건**

조회한 문헌은 모두 실재합니다. 날조된 인용은 없습니다. 문제는 전부 *실재하는 문헌에 그 저자가 출판하지 않은 것을 붙인* 유형이었습니다.

| 최종 존재판정 | 건수 |
| --- | --- |
| `VERIFIED_EXACT` | 52 |
| `MISATTRIBUTED` | 9 |
| `DETAIL_MISMATCH` | 7 |
| `GREY_PLAUSIBLE` | 4 |
| `CONFLATED` | 1 |

| 최종 용례판정 | 건수 |
| --- | --- |
| `SUPPORTED` | 47 |
| `PARTIALLY_SUPPORTED` | 23 |
| `NOT_SUPPORTED` | 3 |

## 2. 실재하나 그 주장을 출판하지 않은 인용


### `conolly-lake-2006-cost-surface-ui-title` — MISATTRIBUTED / PARTIALLY_SUPPORTED  (3차 판정, confidence high)

```
<string>Conolly &amp; Lake relative slope (2006)</string>
```

FINAL CALL: MISATTRIBUTED / PARTIALLY_SUPPORTED. Both earlier agents reached these two verdicts and my own lookup, done from scratch, confirms them — so there is no tie to break on the verdict itself. The split is over severity and over the remedy, and on both of those I side with the second agent.

WHAT I CONFIRMED MYSELF. The cited work is entirely real and the authors and year in the title string are correct: Crossref returns 'Geographical Information Systems in Archaeology', James Conolly and Mark Lake, issued 2006-05-04, Cambridge University Press, monograph, DOI 10.1017/cbo9780511807459. What the book does not contain is a relative-slope cost model of its own. I fetched Herzog 2014 (Internet Archaeology 36) myself and it states verbatim 'A simple cost formula based on a physical model for ascending and descending slopes was developed by Bell and Lock (2000)' and, separately, 'According to Conolly and Lake (2006, fig. 10.9, 220) this cost function assigns negative values to downhill slope values' — a sentence that only parses if they are commenting on a function that is not theirs.

What the source DOES contain (the bar MISATTRIBUTED requires): per Herzog, Conolly & Lake at p. 220, fig. 10.9 reproduce this cost function and observe that it yields negative costs on downhill slopes. That is the role of a secondary commentator, not an originator. I corroborated the origin claim on two sources with no dependence on Herzog: I decompressed the text of Fábrega Álvarez & Parcero Oubiña 2007 (Archeologia e Calcolatori 18) locally and read 'We have empirically compared the usefulness of two well-known algorithms, those proposed by TOBLER 1993 and BELL, LOCK 2000' — crediting the slope-to-cost algorithm to Bell & Lock, with the string 'Conolly' appearing zero times in the whole paper; and the CRAN leastcostpath package (Joseph Lewis) describes its cost functions as based on slope (Herzog, Llobera & Sluckin, París Roche, Tobler) and traversing slope (Bell and Lock, 2000), …

**교정**: Do NOT retitle to 'Bell & Lock relative slope (2000)'. Apply the de-attribution the project already accepted in its sibling dialog: set the group-box title to '상대경사 비용 (relative-slope cost)', either at tools/cost_surface_dialog_base.ui:372 or via a setTitle() call mirroring tools/cost_network_dialog.py:1272-1273. Keep the existing REFERENCES.md:97 entry — Conolly, J., & Lake, M. (2006). Geographic …

<details><summary>외부 조회 근거</summary>

MY OWN LOOKUPS, none reused from either earlier agent. (1) https://api.crossref.org/works/10.1017/CBO9780511807459 -> title 'Geographical Information Systems in Archaeology'; authors James Conolly, Mark Lake; issued 2006-05-04; publisher Cambridge University Press; type monograph; DOI 10.1017/cbo9780511807459. (2) https://intarch.ac.uk/journal/issue36/5/5-1-4.html fetched by me -> VERBATIM 'A simple cost formula based on a physical model for ascending and descending slopes was developed by Bell and Lock (2000).' and VERBATIM 'According to Conolly and Lake (2006, fig. 10.9, 220) this cost function assigns negative values to downhill slope values.' (3) INDEPENDENT OF HERZOG: https://www.archcalc.cnr.it/indice/PDF18/7_Fabrega.pdf (Fabrega Alvarez & Parcero Oubina 2007, Archeologia e Calcolatori 18). WebFetch returned raw PDF binary, so I decompressed its content streams with a stdlib zlib script in my scratchpad (/tmp/claude-0/-home-user-archtoolkit/059d541e-0600-5710-812c-8619d79b0ac8/scratchpad/ext.py) and read the text: VERBATIM 'There are a number of proposals to deal with the influence of slope over movement, to transform slope values (degrees or %) into cost units. We have empirically compared the usefulness of two well-known algorithms, those proposed by TOBLER 1993 and BELL, LOCK 2000.' and a figure caption 'BELL, LOCK 2000 (B) algorithms.'; case-insensitive grep for 'cono …

</details>


### `higuchi-1975-references` — CONFLATED / SUPPORTED  (3차 판정, confidence high)

```
Higuchi, T. (1975). *The Visual and Spatial Structure of Landscapes*.
```

FINAL CALL: CONFLATED / SUPPORTED — and the practical result is CLEARED, because the defect described by the flagged string is already fixed at HEAD.

WHERE THE TWO AGENTS AGREED, and I agree from my own lookups: the flagged string genuinely fuses two editions. 'The Visual and Spatial Structure of Landscapes' is the title of the 1983 MIT Press translation by Charles S. Terry; 1975 is the year of the Japanese original 景観の構造 : ランドスケープとしての日本の空間 (技報堂). No 1975 imprint bears the English title. Both also judged the USE supported; I reach that independently too.

WHERE THEY SPLIT, and how my lookup breaks it:

(1) FRAMING — live defect or already fixed? AGENT 2 IS RIGHT. I verified this myself rather than taking either agent's word. `git log -L 395,395:tools/viewshed_dialog_base.ui` and `git show 7c3ff0d^:REFERENCES.md` show the flagged wording standing at REFERENCES.md:188 before 7c3ff0d and the bare 'Higuchi, T. (1975). The Visual and Spatial Structure of Landscapes. MIT Press.' in the tooltip before it. At HEAD, REFERENCES.md:192-198 carries the separated Japanese original + 1983 translation pair plus an explicit 주(서지) note saying in so many words that the fused form names a book that does not exist, and viewshed_dialog_base.ui:395 carries the same pair. `git status --porcelain` is empty, so HEAD is the working tree. Agent 1's finding was correct when written; it describes the pre-fix state, and its proposed correction is materially the one already in the file. Nothing to change there.

(2) AGENT 2 GOT ONE COMMIT WRONG, which I correct here: the .ui tooltip was NOT fixed 'one commit earlier (3fb9a5f)'. `git log -L 395,395:tools/viewshed_dialog_base.ui` returns exactly two commits — a624140 (introduced) and 7c3ff0d (corrected). 3fb9a5f is the commit that ADDED docs/AUDIT_BACKLOG.md; despite its message it did not touch line 395. Immaterial to the verdict, but it matters for the stale-backlog point below.

(3) PUBLISHER — 技報堂 or 技報堂出版? AGENT 2 IS RIGHT, AGENT 1'S ASSERTIO …

**교정**: CONFLATED as a string, but ALREADY CORRECTED in the live files — no change is needed to REFERENCES.md or the .ui. For the record, the correct form (which is what the repo now carries) is: 樋口忠彦 [Higuchi, T.] (1975). 『景観の構造 — ランドスケープとしての日本の空間』. 技報堂, 東京. (Japanese original; NDL also records 技報堂出版 for the printing carrying ISBN 9784765513777) / English translation: Higuchi, T. (1983). The Visual and S …

<details><summary>외부 조회 근거</summary>

MY OWN LOOKUPS, run from scratch this session:

1. https://api.crossref.org/works?query.bibliographic=Higuchi+visual+and+spatial+structure+of+landscapes&rows=8&select=title,author,issued,container-title,volume,page,DOI,type,publisher,ISBN — Item 1: title 'The Visual and Spatial Structure of Landscapes', authors Yi-Fu Tuan + Tadahiko Higuchi, issued [[1984,1]], container-title 'Geographical Review', volume 74, page 112, DOI 10.2307/214767, type journal-article, publisher JSTOR (a REVIEW). Item 2: 'THE VISUAL AND SPATIAL STRUCTURE OF LANDSCAPES', Tadahiko Higuchi, issued [[1985]], container-title 'Landscape Journal', volume 4, page 48.2-50, DOI 10.3368/lj.4.1.48a, University of Wisconsin Press (a second REVIEW). Item 3: '6. Summary of the Visual Structure of Landscapes', issued [[1983]], container-title 'The Visual and Spatial Structure of Landscapes', DOI 10.37862/aaeportal.00164.008, type book-chapter, publisher MIT Press, ISBN 9780262081207 / 9780300238389. Items 4-8 are further chapters of the same 1983 book. Reviews published 1984-85 cannot be reviewing a 1975 imprint.

2. https://api.crossref.org/works/10.37862/aaeportal.00164 — title 'The Visual and Spatial Structure of Landscapes'; publisher MIT Press; issued [[1983]]; published-print [[1983]]; ISBN 9780262081207 (print) and 9780300238389; type edited-book; no author listed; resource URL https://www.aaeportal.com/?id=-165 …

</details>


### `minetti-1995` — MISATTRIBUTED / PARTIALLY_SUPPORTED  (3차 판정, confidence high)

```
Minetti, A.E. (1995). "Optimum gradient of mountain paths." *Journal of Applied Physiology*, 79(5), pp. 1698–1703. DOI: 10.1152/jappl.1995.79.5.1698
```

FINAL CALL: MISATTRIBUTED / PARTIALLY_SUPPORTED. I side with the SECOND agent on the verdict pair, but my own lookup overturns a piece of BOTH agents' reasoning, and it narrows the finding further than either stated.

WHERE THE TWO AGREED, AND I CONFIRM INDEPENDENTLY:
(1) Existence is flawless. I resolved the DOI myself via Crossref and separately via Europe PMC (PMID 8594031). Sole author A. E. Minetti (CNR Milan), issued 1995-11-01, Journal of Applied Physiology, vol 79, issue 5, pages 1698-1703, journal-article, American Physiological Society. On bibliography alone: VERIFIED_EXACT.
(2) The paper contains no classification table. Confirmed from the Crossref abstract, Europe PMC, and — the check I weight most, because it is the author's own account — Minetti's personal page, which I fetched myself and which reports no classification table of any kind and expresses gradients in percent throughout ('about 25-28%', '+5%', '-25%').
(3) The code computes no energy. This I established more strongly than either agent: my grep for 에너지|energy|J/kg|joule|kcal|metabol|O2|oxygen across tools/terrain_analysis_dialog.py returns ZERO hits — not even the cost_budget noise Agent 2 reported. The path is get_selected_classification() (lines 266-267) → SLOPE_CLASSIFICATIONS lookup (line 402) → processing.run('gdal:slope', {... 'AS_PERCENT': False ...}) (lines 399-401) → apply_style() (line 418), which builds a QgsColorRampShader in Discrete mode (lines ~311-333). A degree raster with colours on it. The 'minetti' key exists repo-wide at exactly four code sites, all table or radio button.
(4) J/kg/m is the wrong paper's unit. Crossref's 2002 abstract gives 'minimum Cw was 1.64 ± 0.50 J · kg⁻¹· m⁻¹'; the 1995 abstract gives '0.4 and 2.0 ml O2.kg body mass-1.vertical m-1'. Confirmed both myself.

WHERE THEY SPLIT — THE CLASS TABLE — AND WHY I BREAK THE TIE AGAINST AGENT 1:
Agent 1's decisive claim was that the breaks are 'the paper's numbers with the units silently swapped', and specifica …

**교정**: BIBLIOGRAPHY: no correction needed. Every field is exact (Crossref, verified independently below).

WHAT NEEDS CORRECTING IS THE UI, at two places in tools/terrain_analysis_dialog_base.ui:
- Line 153 (tooltip): heading '<b>Minetti 에너지 소비 함수</b>' and body '경사에 따른 에너지 소비량(J/kg/m) 변화를 분석합니다' should go. No energy quantity is computed, no function is evaluated, and J·kg⁻¹·m⁻¹ is the unit of Minetti et …

<details><summary>외부 조회 근거</summary>

ALL QUERIES RUN BY ME, FROM SCRATCH.

1) CROSSREF, DOI RESOLVED DIRECTLY — curl https://api.crossref.org/works/10.1152/jappl.1995.79.5.1698 → verbatim JSON: "title":["Optimum gradient of mountain paths"]; "author":[{"given":"A. E.","family":"Minetti","sequence":"first","affiliation":[{"name":"Istituto Technologie Biomediche Avanzate, Reparto Fisiologia del Lavoro Muscolare, Consiglio Nazionale della Ricerca, Milan, Italy."}]}]; "issued":{"date-parts":[[1995,11,1]]}; "container-title":["Journal of Applied Physiology"]; "volume":"79"; "issue":"5"; "page":"1698-1703"; "type":"journal-article"; "publisher":"American Physiological Society"; "ISSN":["8750-7587","1522-1601"]; is-referenced-by-count 56. ABSTRACT VERBATIM: "By combining the experiment results of R. Margaria (Atti Accad. Naz. Lincei Memorie 7: 299-368, 1938), regarding the metabolic cost of gradient locomotion, together with recent insights on gait biomechanics, a prediction about the most economical gradient of mountain paths (approximately 25%) is obtained and interpreted. The pendulum-like mechanism of walking produces a waste of mechanical work against gravity within the gradient range of up to 15% (the overall efficiency is dominated by the low transmission efficiency), whereas for steeper values only the muscular efficiency is responsible for the (slight) metabolic change (per meter of vertical displacement) with r …

</details>


### `ngii-korean-slope-standard` — MISATTRIBUTED / NOT_SUPPORTED  (3차 판정, confidence high)

```
한국표준 - 완/경/급/험/절 5단계   /   <b>한국 표준 경사도 분류</b><hr/>국토지리정보원 기준에 따른 5단계 분류입니다.<br/><br/>• 완경사지: 0~15° (주거지 최적)<br/>• 경사지: 15~20° (계단식 경작)<br/>• 급경사지: 20~25° (산지 산림)<br/>• 험준지: 25~30° (접근 곤란)<br/>• 절험지: 30°+ (절벽/암벽)
```

FINAL CALL: MISATTRIBUTED / NOT_SUPPORTED. I confirm both prior agents, on my own primary evidence, and I close the one gap neither of them could.

WHAT THE SOURCE ACTUALLY CONTAINS (I extracted it myself, not from either agent's report): I downloaded the [별표] 산림경영계획서 기재요령 PDF from law.go.kr and extracted page 2 with PyMuPDF. Item ⑧ 경사도 reads, verbatim: '구획한 임지의 주경사도를 보고 구분한다. 가. 완경사지(완) : 경사 15°미만 / 나. 경사지(경) : 경사 15～20°미만 / 다. 급경사지(급) : 경사 20～25°미만 / 라. 험준지(험) : 경사 25～30°미만 / 마. 절험지(절) : 경사 30°이상'. It is preceded by '⑦ 산지구분 : 「산지관리법」 제4조의 산지구분...' and followed immediately by '2. 임황조사'. That is the whole item. So MISATTRIBUTED is supported by the standard the task sets: I can say what the source does contain.

THREE FINDINGS, all confirmed:
(1) WRONG AGENCY. The breaks and the five names are a 산림청 (Korea Forest Service) forest-inventory standard, issued as 산림청예규. The plugin's original tooltip asserted '국토지리정보원 기준에 따른 5단계 분류입니다'. My negative evidence on NGII is positive, not merely absential: NGII's own 법령정보 catalogue lists ten regulations and all ten are surveying/mapping/spatial-data (건설공사 측량 표준시방서, GNSS 측위보정정보, 수치지형도 작성 작업 및 성과, 자연·인공지명, 국가 지오이드모델, 수치표고모형 구축·관리, 공간정보 제공 및 관리, 국가기준점측량 작업규정, 측량성과 심사수탁기관, 공공측량 작업규정) — none is a land-capability or slope-grade standard.
(2) THE LAND-USE GLOSSES ARE THE PLUGIN'S OWN. Stated as fact, because I read the entire item: ⑧ gives only the five names, their one-character abbreviations and the degree bands. There is no 주거지 최적, no 계단식 경작, no 산지 산림, no 접근 곤란, no 절벽/암벽 — no land-use text of any kind anywhere in the item.
(3) THE ARCHAEOLOGICAL USE IS NOT IN THE SOURCE. The classified unit is '구획한 임지의 주경사도' — the prevailing slope of a demarcated forest parcel, recorded in a forest management plan. '유적 입지 적합성 평가' is an extension the source neither states nor implies.

MY OWN CONTRIBUTION — I CLOSED THE OPEN GAP. Both prior agents flagged NGII's 「국토조사를 위한 격자체계 설정 및 지표 생산 기준」 as a document they could NOT read (agent 1 called it 'an und …

**교정**: 산림청, 「공·사유림 경영계획 작성 및 운영요령」(산림청예규 제727호, 2025. 8. 22. 일부개정·시행) [별표] 「산림경영계획서 기재요령」(제4조제2항 관련), '1. 산림현황 ⑧ 경사도'. 원문(내가 직접 추출한 PDF 2쪽 verbatim): "⑧ 경사도 : 구획한 임지의 주경사도를 보고 구분한다. / 가. 완경사지(완) : 경사 15°미만 / 나. 경사지  (경) : 경사 15～20°미만 / 다. 급경사지(급) : 경사 20～25°미만 / 라. 험준지  (험) : 경사 25～30°미만 / 마. 절험지  (절) : 경사 30°이상". 이 항목은 ⑦ 산지구분(「산지관리법」 제4조)과 '2. 임황조사' 사이에 위치한 산림 임지(소반) 조사 기재 항목이다. 국토지리정보원(NGII)은 이 분류표를 발간 …

<details><summary>외부 조회 근거</summary>

All lookups are my own. I re-derived the primary text independently rather than relying on either agent's transcription.

PRIMARY SOURCE, READ BY ME:
1. curl -> https://www.law.go.kr/flDownload.do?flSeq=155723913&flNm=[별표]+산림경영계획서+기재요령(제4조제2항+관련)&bylClsCd=200201 -> 225,025-byte PDF, 5 pages (first attempt reset by the agent proxy; a retry with a browser UA succeeded). Extracted with PyMuPDF 1.28.2. PAGE 2 verbatim: "⑧ 경사도 : 구획한 임지의 주경사도를 보고 구분한다. / 가. 완경사지(완) : 경사 15°미만 / 나. 경사지  (경) : 경사 15～20°미만 / 다. 급경사지(급) : 경사 20～25°미만 / 라. 험준지  (험) : 경사 25～30°미만 / 마. 절험지  (절) : 경사 30°이상", immediately preceded by "⑦ 산지구분 : 「산지관리법」 제4조의 산지구분을 기재하여..." and followed by "2. 임황조사 / ⑨ 수종...". PAGE 1 header verbatim: "[별표] / 산림경영계획서 기재요령(제4조제2항 관련) / 1. 산림현황". No land-use text anywhere in item ⑧.

ISSUING-AGENCY METADATA:
2. WebFetch https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000263252 -> 행정규칙명 '공·사유림 경영계획 작성 및 운영요령'; 발령기관 '산림청'; '산림청예규 제727호'; 발령·시행 2025. 8. 22. (일부개정). The page served header/metadata only, so the class bands come from item 1 above.
3. WebSearch '산림청예규 "공·사유림 경영계획 작성 및 운영요령" 산림경영계획서 기재요령 경사도 완경사지 험준지 절험지' -> law.go.kr admRulSeq=2100000025306 and 2100000263252, the 2018 edition path /(664,20180820), and 산림청 (west.forest.go.kr) pages. Confirms the 제664호 (2018. 8. 20.) intermediate edition and the Korea Forest Service as issuer.

INDEPENDENT CORROBORATION OF THE BANDS …

</details>


### `riley-1999-five-class-ui` — MISATTRIBUTED / NOT_SUPPORTED  (3차 판정, confidence high)

```
<b>분류 기준 (Riley et al.):</b><br/>• 0~2: 평탄 (Level)<br/>• 2~5: 거의 평탄 (Nearly Level)<br/>• 5~10: 약간 거침 (Slightly Rugged)<br/>• 10~20: 중간 (Moderately Rugged)<br/>• 20+: 험준 (Highly Rugged)
```

FINAL CALL: MISATTRIBUTED / NOT_SUPPORTED on the flagged text, with the status qualification that the second agent supplied and I independently confirmed - the defect is historical, not live.

WHERE THE TWO AGREED, AND I MAKE IT THREE. Both prior agents ruled MISATTRIBUTED / NOT_SUPPORTED, and I reach the same conclusion from my own copy of the primary source rather than from either agent's evidence. I read all five pages. The paper contains exactly one classification scheme and it is the seven-class metre-scale table; the word 'five' does not occur in the article at all, 'threshold' does not occur at all, and a scan for standalone 2 / 5 / 10 / 20 returns only bibliographic strings ('Vol. 5, No. 1-4', '5(3):3-30', '48(2): 172-176'). Pages 26-27 are discussion, acknowledgment and Literature Cited - no second table. So Riley et al. did not publish the flagged breaks in any form, and the heading '분류 기준 (Riley et al.)' put their name on a table they never wrote. I can state positively what the source does contain, which is what MISATTRIBUTED requires. I also independently reproduced the mechanical origin of the numbers: get_tri_classes (tools/terrain_analysis_dialog.py:282-306) computes max_rugged*0.1/0.25/0.5/1.0, and spinTRIMax in the .ui defaults to 20, giving 2/5/10/20 - the flagged figures exactly. The second agent's sharper observation is correct and I confirm it: the five LABELS are five of Riley's seven label names with 'intermediately rugged' and 'extremely rugged' dropped, so the old string was Riley's vocabulary welded onto the plugin's own numeric breaks - which is precisely why it read as authoritative.

WHERE THEY SPLIT, AND HOW I BREAK IT. The split is status, not substance. The first agent reported a live defect at .ui:81 and proposed remedy wording; the second agent showed the string no longer exists. My own check settles it for the second agent: grep over the working tree finds the flagged string in exactly one file, docs/AUDIT_BACKLOG.md:158, the audi …

**교정**: MISATTRIBUTED stands on the flagged text, but NO CODE CHANGE IS OUTSTANDING - the string was already removed before I looked. The bibliographic line in the same tooltip is and always was exact, and I confirmed every field myself: Riley, S.J., DeGloria, S.D., & Elliot, R. (1999). "A Terrain Ruggedness Index That Quantifies Topographic Heterogeneity." Intermountain Journal of Sciences 5(1-4): 23-27. …

<details><summary>외부 조회 근거</summary>

PRIMARY SOURCE, OBTAINED MYSELF FROM BOTH HOSTS THE EARLIER AGENTS USED, TO TEST THEIR DISAGREEMENT. curl https://download.osgeo.org/qgis/doc/reference-docs/Terrain_Ruggedness_Index.pdf -> HTTP 200, 2,656,665 bytes, md5 a428d2ef1a3d77fe7f824e141ffa1073, PDF 1.4, 6 pages. curl https://arc.lib.montana.edu/ojs/index.php/IJS/article/download/2914/2558 -> HTTP 200, 961,786 bytes, md5 8365e130f762c691ff3c903cbf415466, PDF 1.6, 5 pages. Distinct files. PyMuPDF get_text() per page: osgeo = 0,0,0,0,0,0 chars (image-only scan, total 0); Montana = 3198, 2996, 739, 3358, 1105 chars (total 11,396). This reconciles the two agents' contradictory claims about the text layer - they held different scans and both were accurate about their own.
VERBATIM CLASSIFICATION PASSAGE, read by me from the Montana text layer (p.24): 'In our example, we used an "equal area" classification method to group continuous ranges of TRI values into seven classes of unequal range, but equal area. The range in TRI values for each grouping are as follows: level = 0 - 80 m; nearly level = 81-116 m; slightly rugged= 117 - 161 m; intermediately rugged = 162 - 239 m; moderately rugged = 240 - 497 m; highly rugged = 498 -958 m, and; extremely rugged = 959 - 4367 m. The classification scheme can be easy changed in Arc/Info to meet the particular needs of the map.' Same page: 'We used a square grid network with 1 km.2 grid ce …

</details>


### `riley-1999-threshold-recommendation-ui` — MISATTRIBUTED / NOT_SUPPORTED  (3차 판정, confidence high)

```
<b>권장값 (Riley et al. 1999):</b><br/>• 20 (기본값): 원저자 분류 기준<br/>• 10: 더 민감하게 험준 지형 탐지<br/>• 30: 극도로 험준한 지형만 탐지
```

FINAL CALL: I uphold MISATTRIBUTED / NOT_SUPPORTED at high confidence on the merits, and I side with the second agent on status - the string is already fixed at HEAD, so this is a closed finding, not an open defect. WHERE THE TWO AGREED (and I agree with both): the verdict, the confidence, and both failure modes. (1) Factual - the source contains no such recommendation. (2) Structural - tri_max is a free scaling knob on a display scheme the plugin invented, so there was no published method for Riley to have recommended a value for. WHERE THEY SPLIT, and how my lookup breaks it. The material split is status. Agent 1 treated the finding as open and proposed corrective wording; agent 2 showed the correction is already applied. My own check settles this for agent 2: `grep -rn '원저자 분류 기준'` over the working tree returns only docs/AUDIT_BACKLOG.md:179, never the .ui, and `git show 3fb9a5f^:tools/terrain_analysis_dialog_base.ui` carries the flagged string while HEAD:408 carries the corrected text. git status is clean. A second, minor evidentiary split also resolves for agent 2: agent 1 reported one grep hit ('5(3):3-30.'), agent 2 reported that 'recommend'/'suggest' are absent outright. My own scan of my own extraction confirms agent 2 - `grep -niE 'recommend|threshold|cut-?off|suggest|criteri|advis|default'` returns NOTHING (exit 1), and a standalone-token scan for 10/20/30 also returns nothing (exit 1). Agent 1's single hit only appears with a regex loose enough to catch a hyphenated page range in the bibliography; the substantive conclusion is identical, so this is a difference in grep tightness, not in fact. MY OWN DERIVATION, not taken from either agent's evidence: I downloaded the PDF myself (HTTP 200, 961,786 bytes), extracted 5 pages / 11,400 chars with PyMuPDF, and ran a full number census - the complete set of numeric tokens in the paper contains no standalone 10 or 20 at all, and the only '30'-family tokens are '300 Kilometers' (a figure scale bar) and the biblio …

**교정**: NOT an existence defect. The work is real and the plugin's bibliographic line for it (.ui:81) is exact: Riley, S.J., DeGloria, S.D., & Elliot, R. (1999). "A Terrain Ruggedness Index That Quantifies Topographic Heterogeneity." Intermountain Journal of Sciences 5(1-4): 23-27. What was misattributed is the RECOMMENDATION dressed onto it. The paper contains no recommended threshold, no sensitivity gui …

<details><summary>외부 조회 근거</summary>

PRIMARY SOURCE, obtained independently in my own scratchpad: curl -sSL https://arc.lib.montana.edu/ojs/index.php/IJS/article/download/2914/2558 -> HTTP:200 SIZE:961786 TYPE:application/pdf; 'PDF document, version 1.6'. Extracted with PyMuPDF -> PAGES: 5, CHARS: 11400. Header verbatim: 'Shawn J. Riley / Stephen D. DeGloria / Robert Elliot / A TERRAIN RUGGEDNESS INDEX THAT QUANTIFIES TOPOGRAPHIC HETEROGENEITY'. KEYWORD SCAN (mine, broader than either agent's): grep -niE 'recommend|threshold|cut-?off|suggest|criteri|advis|default' riley.txt -> NO MATCHES (exit 1). STANDALONE TOKEN SCAN: grep -nE '(^|[^0-9.,-])(10|20|30)([^0-9.,-]|$)' -> NO MATCHES (exit 1). FULL NUMBER CENSUS (every numeric token in the paper, sorted unique): 0 1 2 3 4 5 9 12 22 23 24 25 26 27 30 34 45 47 48 53 54 61 71 76 80 81 86 100 116 117 125 132 137 161 162 172 175 176 197 200 202 205 210 214 220 225 239 240 255 265 300 321 328 353 374 497 498 540 566 700 958 959 1111 1134 1141 1163 1166 1302 1310 1973 1981 1983 1984 1986 1987 1988 1989 1991 1992 1995 1996 1997 1998 1999 4367 14853. Line-level check of every 10/20/30 occurrence shows they are figure-legend values (100/200/205/210/220), the scale bar '300 Kilometers' (line 179), and bibliography page ranges '53:197-202.' (316), '5(3):3-30.' (330), '48:1302-1310.' (344). None is a ruggedness value. CLASSIFICATION PASSAGE verbatim (lines 103-124): 'equal area" …

</details>


### `tobler-1993-slope-class-preset` — MISATTRIBUTED / PARTIALLY_SUPPORTED  (3차 판정, confidence high)

```
'name': 'Tobler 1993' / Tobler(1993) - 보행속도 / <i>Tobler, W. (1993). Three Presentations on Geographical Analysis and Modeling: Non-Isotropic Geographic Modeling.</i> … • 평지 (0°): 시속 ~5km … • 급경사 (25°+): 시속 <1km / ☑ 경사도 분류 - Tobler(1993) 보행속도 기반
```

FINAL CALL: MISATTRIBUTED / PARTIALLY_SUPPORTED. I agree with both agents on the existence verdict and side with the SECOND agent on the support verdict — but my own lookup overturns a factual premise BOTH of them relied on, and the correction strengthens the second agent's position rather than the first's.

WHERE THE TWO AGREED, AND WHERE THEY SPLIT. Both concluded MISATTRIBUTED, both found the report real and cited accurately, both found no slope classification in it, and both identified the same propagation defect in the layer name and metadata. They split only on use_supported: agent 1 said NOT_SUPPORTED, agent 2 said PARTIALLY_SUPPORTED. Agent 2 also corrected two details in agent 1, and BOTH of those corrections are right: the tooltip contains the four SPEED figures and no class bands (I confirmed .ui:143 directly), and DEVELOPMENT.md:111 sits under '### 예시' at :103, not under '### 반드시 지켜야 할 것' at :91.

WHAT I FOUND THAT NEITHER DID — THE SHARED ERROR. Both agents grepped a TEXT layer and then made universal negative claims about the whole report. The report has 36 figures, which are separate raster images invisible to every text extraction either of them ran. Figure II ('tobler93b.png', alt='Walking function') is the hiking function plate, and I downloaded and read it. It contains, printed on the page: the equation 'W = 6 exp { -3.5 * abs(S + 0.05) }'; 'where W is the walking velocity, S is dh/dx = slope = tan (theta)'; 'The velocity is given in km/hr. On flat terrain this works out to 5 km/hr.'; 'For off-path travel multiply by 3/5 (= 0.6). For horseback, multiply by 5/4 (= 1.25). The travel time is computed as distance/velocity.'; and a plotted curve with y-axis 'Walking Speed (km/hr)' 0.0-7.0 against x-axis 'Slope in Degrees' -70 to +70. This directly falsifies: agent 1's 'the hiking function itself is never printed as an equation'; agent 2's 'the constants 3.5 and 0.05 occur zero times — the hiking function is never printed as an equation anywhere in the …

**교정**: The bibliographic record is CORRECT and needs no correction. Full form: Tobler, W. (1993). Three Presentations on Geographical Analysis and Modeling: Non-Isotropic Geographic Modeling; Speculations on the Geometry of Geography; Global Spatial Analysis. NCGIA Technical Report 93-1, National Center for Geographic Information and Analysis, February 1993. The .ui tooltip's shortened form, naming only …

<details><summary>외부 조회 근거</summary>

CROSSREF, queried first and independently. https://api.crossref.org/works?query.bibliographic=Tobler+Three+Presentations+on+Geographical+Analysis+and+Modeling+Non-Isotropic&rows=5&select=title,author,issued,container-title,volume,page,DOI,type → returns only unrelated Tobler journal articles: 'Geographical Variances' (Geographical Analysis 4:34-50, 1972, 10.1111/j.1538-4632.1972.tb00455.x), 'Geographical Filters and their Inverses' (1:234-253, 1969, 10.1111/j.1538-4632.1969.tb00621.x), 'Lattice Tuning' (11:36-44, 1979), 'A Model of Geographical Movement' (13:1-20, 1981), 'Bidimensional Regression' (26:187-212, 1994). The technical report is NOT indexed — expected for NCGIA grey literature, treated as NO evidence of nonexistence. This reproduces agent 2's query result exactly.

PRIMARY SOURCE, FETCHED FRESH BY ME. https://escholarship.org/content/qt05r820mz/qt05r820mz.pdf and the noSplash variant both returned HTTP 403 (CloudFront 'Request blocked'), so I could not reuse agent 1's route. I downloaded two HTML mirrors myself and stripped them with my own script (/tmp/claude-0/-home-user-archtoolkit/059d541e-0600-5710-812c-8619d79b0ac8/scratchpad/mine3/strip.py): (a) https://geodyssey.neocities.org/papers/tobler93 — Tobler's own Geodyssey archive, named on the report's title page as its HTML home — 57,537 bytes → 51,462 chars; (b) https://www.lukatela.com/hrvoje/papers/tobler93.ht …

</details>


### `weiss-2001-class-names` — MISATTRIBUTED / PARTIALLY_SUPPORTED  (3차 판정, confidence high)

```
TPI와 경사도를 조합하여 지형을 6가지로 자동 분류합니다:<br/><br/>1. 깊은 곡저 (Incised Valley)<br/>2. 곡저/하상 (Valley Floor)<br/>3. 평지/단구 (Flat or Terrace)<br/>4. 중간 사면 (Mid Slope)<br/>5. 능선 평탄부 (Upland Flat)<br/>6. 급경사 능선 (Steep Ridge)   /   # Labels follow Weiss's own class names: clas …
```

FINAL CALL: MISATTRIBUTED / PARTIALLY_SUPPORTED — i.e. I side with the SECOND agent on severity, and with BOTH agents on what Weiss actually printed.

WHERE THE TWO AGREED, and my own lookup confirms them: Weiss's six slope-position classes are 'ridge / upper slope / middle slope / flats slope / lower slopes / valleys'; the poster carries a SEPARATE ten-class 'Landforms' scheme; and 'Valley Floor', 'Upland Flat', 'Flat or Terrace' and 'Steep Ridge' are not Weiss's words. My independent extraction of the poster reproduces the class table and the landforms list verbatim and gives 'terrace' 0 hits and 'steep' 0 hits. That much is settled.

WHERE THEY SPLIT, and how my lookup breaks it — agent 2 wins all three:

(i) IS THE FLAGGED TEXT LIVE? No. Agent 1 wrote that the .ui tooltip 'ships the version the code explicitly repudiates' and that three locations disagree. At current HEAD (6286134, which is one commit PAST the 7c3ff0d agent 2 read) I grepped the whole repo: '곡저/하상 (Valley Floor)' and '능선 평탄부 (Upland Flat)' appear ONLY in docs/AUDIT_BACKLOG.md:273-287, which is the audit's own historical record of this finding. The shipped tooltip at .ui:71 and the legend at .py:132/135 and the docstring at .py:763/766 all now read '2. 하부 사면 (Lower Slope)' and '5. 상부 사면 (Upper Slope)'. Agent 1's central factual claim is false at HEAD; the flagged citation_text quotes a defect that has been fixed.

(ii) IS THE THREE-WAY INCONSISTENCY REAL? No. All three code locations agree at HEAD. Agent 1's specific pointer (dialog.py:719-726 'still lists 곡저/하상') does not hold — that docstring is now at lines 760-768 and reads Lower/Upper Slope.

(iii) IS THE NUMBERING WRONG? No. Agent 1 said 'only the numbering runs the other way from Weiss's table'. My own extraction of Jenness's 42-page manual — the canonical implementation of Weiss's method — gives the preset 'Sample 6-Class, de-emphasize class 2 & 5 (Weiss 2001): Valley ≤ -1 SD; Lower Slope; Flat Slope; Middle Slope; Upper Slope; Ridge > 1 …

**교정**: The BIBLIOGRAPHIC citation is correct and needs no change: Weiss, A. D. (2001). Topographic Position and Landforms Analysis. Poster presentation, ESRI International User Conference, San Diego, CA, 9-13 July 2001 (The Nature Conservancy, Northwest Division). What needs correcting is the SCHEME NAME and three class labels.

(1) SCHEME NAME. What the plugin implements is Weiss's SLOPE POSITION classi …

<details><summary>외부 조회 근거</summary>

I did my own lookups from scratch and did not reuse either earlier agent's fetches.

PRIMARY SOURCE, downloaded and extracted by me: curl https://www.jennessent.com/downloads/TPI-poster-TNC_18x22.pdf → HTTP 200, 1,231,732 bytes, 1 page; extracted 13,862 characters with PyMuPDF (WebFetch cannot read this scanned/vector poster). Section headings verbatim in order: 'Study Area / Basic Algorithm / Slope Position / Landforms / Watershed Metrics'. The six-class table verbatim: 'One repeatable method of creating classes, used in Fig. 3b and 3c, is to use standard deviation units. In this example, classes 2 and 5 are de-emphasized: Class / Description / Breakpoints — 1 ridge > + 1 STDEV; 2 upper slope > 0.5 STDV =< 1 STDV; 3 middle slope > -0.5 STDV, < 0.5 STDV, slope > 5 deg; 4 flats slope >= -0.5 STDV, =< 0.5 STDV , slope <= 5 deg; 5 lower slopes >= -1.0 STDEV, < 0.5 STDV; 6 valleys < -1.0 STDV'. Immediately following, the SEPARATE ten-class list verbatim: 'Landforms — canyons, deeply incised streams / midslope drainages, shallow valleys / upland drainages, headwaters / U-shape valleys / plains / open slopes / upper slopes, mesas / local ridges/hills in valleys / midslope ridges, small hills in plains / mt tops, high ridges'. Also verbatim: 'Fig 4a: Combining TPI at 2 scales to develop landform classes' and 'Fig 4b: The Mt. Hood region classified into 10 landform classes.' My word co …

</details>


### `weiss-2001-recommended-parameter-values` — MISATTRIBUTED / PARTIALLY_SUPPORTED  (3차 판정, confidence high)

```
<b>권장값 (Weiss 2001):</b><br/>• 3셀: 미시지형 (기본값, 유적 규모)<br/>• 10셀: 중규모 지형<br/>• 30셀: 광역 지형 (산줄기/계곡)   /   <b>권장값 (Weiss 2001):</b><br/>• 1.0 (기본값): 표준 편차 기준   /   <b>권장값 (Weiss 2001):</b><br/>• 5° (기본값): 일반적 지형 분류   /   <b>권장값 (Weiss 2001):</b><br/>• -1.0 (기본값): …
```

FINAL CALL: MISATTRIBUTED / PARTIALLY_SUPPORTED. I did my own lookup from scratch — downloaded the poster myself, extracted its full text myself, AND rendered the whole page and read it with my own eyes — and I reach the same verdict the two earlier agents reached. The work is unquestionably real and the bibliographic citation in REFERENCES.md is exact; the defect is confined to the parameter labels in the dialog.

WHERE THE TWO EARLIER AGENTS AGREED, AND I CONFIRM ALL OF IT:
• The radius tooltip at .ui:240 is the misattribution. '권장값 (Weiss 2001): 3셀 / 10셀 / 30셀' appears nowhere in Weiss. My own exhaustive check of the complete text: the string 'cell' occurs exactly 4 times on the entire poster (lines 27, 140, 141, 190-191 of my extraction) and 'radi' exactly 3 times (189, 190, 191) — every one inside the algorithm-box definitions or the TPI definition sentence. There is no radius recommendation in cells anywhere in the published work.
• .ui:189/:195 (auto-SD checkbox) is genuinely Weiss's. The poster: 'One repeatable method of creating classes, used in Fig. 3b and 3c, is to use standard deviation units', followed by the ±1 / ±0.5 STDEV table. Accurate as labelled.
• .ui:298 (5° flat threshold) is genuinely Weiss's — his class 3/4 split is literally 'slope > 5 deg' vs 'slope <= 5 deg'.
• .ui:266 ('1.0 (기본값): 표준 편차 기준') is wrong about the plugin's OWN code. I verified independently: 'stdDev' occurs at exactly ONE line in the module (799), inside run_slope_position_analysis (def at 748); get_tpi_classes (def 271) has exactly ONE caller (704), inside run_tpi_analysis (def 691). So the standalone TPI classification never computes a standard deviation on any code path — it builds breaks at the literal ±threshold. 1.0 there is a raw TPI value in metres.

WHERE THEY SPLIT, AND HOW MY LOOKUP BREAKS THE TIE — I side with the SECOND agent on all three:
1. ANNULUS vs FILLED WINDOW. Agent 1 counted the plugin's filled block-average window as a second departure from Weiss; agen …

**교정**: Weiss, A.D. (2001). Topographic Position and Landforms Analysis. Poster presentation, ESRI International User Conference, San Diego, CA, 9–13 July 2001. The Nature Conservancy, Northwest Division. — The bibliographic citation is CORRECT as given in REFERENCES.md:221; nothing needs fixing there. What must change is the PARAMETER ATTRIBUTION in the dialog. What Weiss actually publishes as parameter …

<details><summary>외부 조회 근거</summary>

ALL LOOKUPS BELOW ARE MY OWN, RUN FRESH IN THIS SESSION.

1. PRIMARY SOURCE, downloaded by me: curl https://www.jennessent.com/downloads/TPI-poster-TNC_18x22.pdf → HTTP 200, 1,231,732 bytes, md5 2afd530a111d4d5563dcee711e4d2a80, 'PDF document, version 1.4, 1 page(s)'. Extracted with PyMuPDF 1.28.2 myself: 1 page, page rect 1296x1584 pt (= 18x22 in), 13,862 chars, 174 text blocks, 38 images. Because the central finding is a NEGATIVE, I also rendered the page (110 dpi full page + 200 dpi crops) and read it visually; the rendering matches the extracted text exactly.
VERBATIM header (read in the rendered image): 'Topographic Position and Landforms Analysis / Andrew D. Weiss, The Nature Conservancy' with 'Director: Ecoregional Data Management Team / The Nature Conservancy, Northwest Division / 217 Pine St. Suite 1100 / Seattle WA 98103 / (206) 343-4345 x360 / aweiss@tnc.org' and the TNC logo.
VERBATIM algorithm box (extracted lines 188-192, and read visually in my 200 dpi crop): 'tpi<scalefactor> = int((dem - focalmean(dem, annulus, irad, orad)) + .5)' / 'scalefactor = outer radius in map units' / 'irad = inner radius of annulus in cells' / 'orad = outer radius of annulus in cells' / 'The index is converted to integer for storage efficiency and symbolization'.
VERBATIM figure captions (lines 206-213, also read visually): 'Fig. 2b: tpi300, computed from a 30m DEM with the formula: tp …

</details>


### `wilson-2007-tpi-index` — MISATTRIBUTED / PARTIALLY_SUPPORTED  (3차 판정, confidence high)

```
Wilson, M.F.J., O'Connell, B., Brown, C., Guinan, J.C., & Grehan, A.J. (2007). "Multiscale terrain analysis of multibeam bathymetry data for habitat mapping on the continental slope." *Marine Geodesy*, 30(1-2), pp. 3-35. DOI: 10.1080/01490410701295962
```

FINAL CALL: MISATTRIBUTED stands, but the plugin's use is now PARTIALLY_SUPPORTED rather than NOT_SUPPORTED, because the repository moved between the earlier two assessments and this one.

WHERE THE FIRST TWO AGENTS AGREED: on everything that matters. Both found the bibliography flawless, both found the origin claim contradicted by the cited paper, both reached MISATTRIBUTED / NOT_SUPPORTED, both credited the plugin for separating index from classification and for noticing that gdaldem's fixed 3x3 cannot produce Weiss's broad-scale TPI, and both flagged the roughness attribution as the same pattern. This was not a real disagreement needing a tiebreak.

WHERE THEY SPLIT: only on line numbers. Agent 1 put the offending sentence at REFERENCES.md:210; agent 2 put it at 219 and the heading at 208. Agent 2 was right — I checked the pre-fix blob (git show 7c3ff0d:REFERENCES.md) and the claim sentence is at line 219, the (A) heading at 208, roughness at 223. Agent 2 also obtained the decisive piece of evidence agent 1 lacked: the Weiss poster itself.

MY OWN LOOKUP, DONE FROM SCRATCH, CONFIRMS THEM AND ADDS TWO INDEPENDENT LINES. I re-resolved the DOI, re-downloaded the Wilson PDF and re-extracted it, and downloaded the Weiss poster myself. Four independent sources now say TPI is Weiss's: (1) the Weiss poster prints the definition and the formula tpi<scalefactor> = int((dem - focalmean(dem, annulus, irad, orad)) + .5); (2) Wilson et al. themselves say TPI was 'introduced by Weiss (2001)' — the string 'TPI' occurs exactly once in 33 pages, in that sentence, against 19 occurrences of 'BPI'; (3) NEW — ESRI's own ArcGIS Pro 'How Topographic Position Index works' page cites Weiss, A. (2001) as its first reference; (4) NEW — the CSU Monterey Bay Seafloor Mapping Lab TPI poster hosted at seafloor.otterlabs.org, a marine study of exactly the kind Wilson et al. cite, states 'The TPI algorithm used in this study is adapted from Weiss, 2001 (poster presented at ESRI User Conference)'. …

**교정**: THE REFERENCE STRING NEEDS NO CHANGE. Every field is exact against Crossref and the published PDF's own running head. What is wrong is the label attached to it, and half of that has already been fixed in the working tree.

ALREADY FIXED (commit 6286134, REFERENCES.md:223): the old sentence '주: Weiss(2001)는 분류(classification)의 출처이지 TPI 지수 자체의 출처가 아닙니다. 지수의 출처는 위 Wilson 등(2007)입니다.' has been retract …

<details><summary>외부 조회 근거</summary>

ALL LOOKUPS BELOW ARE MINE, RUN IN THIS SESSION.

1. BIBLIOGRAPHY — EXACT MATCH. curl https://api.crossref.org/works/10.1080/01490410701295962 returned: TITLE ['Multiscale Terrain Analysis of Multibeam Bathymetry Data for Habitat Mapping on the Continental Slope']; AUTHORS [('Margaret F. J.','Wilson'),('Brian','O'Connell'),('Colin','Brown'),('Janine C.','Guinan'),('Anthony J.','Grehan')]; ISSUED {'date-parts': [[2007, 5, 9]]}; CONTAINER ['Marine Geodesy']; VOLUME 30; ISSUE 1-2; PAGE 3-35; DOI 10.1080/01490410701295962; TYPE journal-article; PUBLISHER Informa UK Limited. Every field the plugin states is correct.

2. PRIMARY SOURCE — the Wilson paper. curl https://www2.unil.ch/biomapper/Download/Wilson-MarGeo-2007.pdf -> HTTP 200, 1497867 bytes, application/pdf, PDF v1.6, 33 pages. Extracted with PyMuPDF. First line: 'Marine Geodesy, 30: 3-35, 2007'. Counts over the full text: TPI = 1, BPI = 19, Weiss = 2. The single TPI hit, at extracted line 321-323: 'Bathymetric Position Index. The bathymetric position index (BPI) is the marine version of the topographic position index (TPI) introduced by Weiss (2001) and has been applied to a number of benthic habitat studies in recent years (Iampietro and Kvitek 2002; Iampietro et al. 2004; Lundblad et al. 2006).' Reference list, line 1381: 'Weiss, A. D. 2001. Topographic Positions and Landforms Analysis (poster), ESRI International User Con …

</details>


## 3. 서지 세부 오류


### `archtoolkit-self-citation-inconsistency` (3차 판정)
- 현재: @software{ArchToolkit2026, author = {lzpxilfe}, title = {ArchToolkit: Archaeology Toolkit for QGIS}, year = {2026}, url = {https://github.com/lzpxilfe/archtoolkit}, version = {0.1.4}}   /   CITATION.cff authors: - family …
- 교정: Reconcile on CITATION.cff, which is the only surface a citation tool actually parses (GitHub Docs: CITATION.cff is parsed into APA and BibTeX; a README BibTeX block is not parsed at all, and is not even among the alternative files GitHub will merely link to):

@software{Hwang_ArchToolkit_2026,
  author  = {Hwang, Jinseo},
  title   = {{ArchToolkit: …
- 비고: I AGREE with the first agent's central finding and its most important negative: this is NOT a fabricated scholarly source and NOT a name borrowed from a third party. I independently re-derived that. GitHub's user index returns exactly one account for the string 'balguljang2' — login lzpxilfe, id 251109954 — and the repository's own commit list returns, for the three commits whose commit.author.name is 'hwangjinseo' and whose email is the GitHub-issued lzpxilfe@users.noreply.github.com, an author.login of 'lzpxilfe', id 251109954. GitHub itself therefore binds the name string 'hwangjinseo' to t …


### `conolly-lake-2006-cost-network-undisclosed` (3차 판정)
- 현재: 코놀리&레이크 경사비용 (Conolly & Lake, 2006) / "Conolly & Lake (2006)\n- 경사에 따른 이동 비용을 보행 속도로 환산해 적용합니다.\n- 기본속도↑ → 전체 시간↓" / <string>Conolly &amp; Lake (2006)</string> / 보행/비용모델: Tobler(1993), Naismith(1892), Conolly &amp; Lake( …
- 교정: Add the missing originator, and keep the book as the secondary source it is. Originator of the tan-ratio slope cost: Bell, T. & Lock, G. (2000). 'Topographic and cultural influences on walking the Ridgeway in later prehistoric times', in G. Lock (ed.), Beyond the Map: Archaeology and Spatial Technology. Amsterdam: IOS Press, pp. 85-100 — original f …
- 비고: FINAL CALL: DETAIL_MISMATCH / PARTIALLY_SUPPORTED. I side with the second agent on the verdict level, but on partly different grounds and about a code state that has moved again since either agent wrote.

FIRST, THE MOVING TARGET. Neither prior assessment describes the current repository. HEAD is now 6286134 ('Fix the citations two independent checks agreed on'), two commits past the 3fb9a5f the first agent audited, and `git diff --name-only` is EMPTY — the working tree is clean, so what the second agent described as uncommitted remediation is now committed and shipped. Agent 1's factual claim …


### `cuckovic-2024` (3차 판정)
- 현재: Čučković, Z. (2024). *Movement Analysis* (QGIS plugin). https://github.com/zoran-cuckovic/QGIS-movement-analysis/
- 교정: Čučković, Z. (2025). Movement Analysis (QGIS plugin), version 0.1.2, slope_cost module. https://github.com/zoran-cuckovic/QGIS-movement-analysis/ — the cited slope-cost code was authored 2025-07-10 and first released in v0.1.2 (2025-07-11); the 2024 releases v0.1 and v0.1.1 contain no slope_cost.py and none of the cited formulas anywhere. (If the a …
- 비고: FINAL CALL: DETAIL_MISMATCH on existence (year), PARTIALLY_SUPPORTED on use. I did my own lookup from scratch and it lands with the SECOND agent on existence and on both disputed use-points, while trimming the second agent's strongest claim back a notch.

WHERE THE TWO AGREED, AND I CONCUR. The software is real; the author spelling 'Zoran Čučković' and the repository URL are character-exact against metadata.txt; the provenance is genuine and checks line by line. Čučković's slope_cost.py contains verbatim the seven metabolic coefficients (1337.8, 278.19, -517.39, -78.199, 93.419, 19.825, 1.64) …


### `delaunay-1934-tin` (3차 판정)
- 현재: Delaunay, B. (1934). "Sur la sphère vide". *Otdelenie Matematicheskikh i Estestvennykh Nauk*, 7, pp. 793–800.
- 교정: Delaunay, B. (1934). "Sur la sphère vide. À la mémoire de Georges Voronoï". Известия Академии наук СССР, VII серия, Отделение математических и естественных наук / Bulletin de l'Académie des Sciences de l'URSS, VII série, Classe des sciences mathématiques et naturelles, 1934, no. 6, pp. 793–800. (The journal carries no volume numbering; it is indexe …
- 비고: FINAL CALL: DETAIL_MISMATCH / PARTIALLY_SUPPORTED. The work is real, it is the correct origin of the Delaunay triangulation, and the plugin's use of it is mostly well scoped with one genuinely loose user-facing string. Not fabricated, not MISATTRIBUTED.

WHERE THE TWO AGREED, AND I CONFIRM THEM: both reached DETAIL_MISMATCH on existence with essentially identical diagnoses, and my own lookups reproduce their evidence independently. Author (B. Delaunay), year (1934) and pages (793-800) as printed are correct. Four defects: (a) the parent journal title is dropped, leaving only the departmental s …


### `naismith-1892` (3차 판정)
- 현재: Naismith, W. W. (1892). "Excursions." *Scottish Mountaineering Club Journal*.   /   Classic Naismith (1892): time = distance / speed + ascent / ascent_rate
- 교정: Naismith, W. W. (September 1892). "Cruach Ardran, Stobinian, and Ben More." In: "Excursions" [under the department "Notes and Queries"], *Scottish Mountaineering Club Journal*, 2(3), pp. 135-136 (the rule itself falls on p. 136). No DOI exists.
- 비고: FINAL CALL: DETAIL_MISMATCH + SUPPORTED. The work is entirely real, the implementation is faithful to it, and the only defect is bibliographic. Nothing here is fabricated and nothing is misattributed.

WHERE THE FIRST TWO AGREED, AND I CONFIRM INDEPENDENTLY. Both agents said 'Excursions' is not Naismith's article title but a standing multi-author column, and both said the implementation is faithful. My own lookups confirm both, from scans I fetched myself. The printed hierarchy in the bound volume is unambiguous: a department heading 'NOTES AND QUERIES.', then a column heading 'EXCURSIONS.' ca …


### `ngii-scale-resolution-standard` (3차 판정)
- 현재: 국토지리정보원 내규에 따른 축척별 권장 해상도를 자동 입력합니다.   /   # Based on contour interval standards from National Geographic Information Institute
- 교정: 해상도(격자간격)의 출처: 「3차원국토공간정보구축작업규정」(국토지리정보원고시 제2019-146호, 2019. 5. 23. 일부개정 / 시행 2019. 7. 1.) 제18조(3차원 지형데이터 편집방법) 제2항 — '수치지도 축척에 따른 수치표고모델의 격자간격은 다음 표와 같다': 수치지도 축척 1:1,000 → 수치표고자료 격자간격 1m×1m, 1:2,500 → 2m×2m, 1:5,000 → 5m×5m.

등고선 간격 라벨의 출처: 「1/5000 지형도도식규정」(국토지리정보원고시 제2009-583호, 시행 2009. 8. 24.) 제114조제2항 — 주곡선 5.0m, 계곡선 25m, 간곡선 2.5m, 조곡선 1.25m; …
- 비고: FINAL CALL: DETAIL_MISMATCH / PARTIALLY_SUPPORTED. I side with the second agent, on evidence I obtained myself.

WHERE THE TWO AGREED: the agency is right (NGII), the contour intervals in the combo-box labels are genuine NGII provisions, the code comment at dem_generator_dialog.py:44 holds, the word '내규' is wrong (these are 고시 — numbered, dated, publicly searchable), and there is no REFERENCES.md entry for this citation at all. I confirm every one of those.

WHERE THEY SPLIT: the first agent's verdict rested entirely on one negative — 'There is no NGII rule recommending a DEM pixel size per ma …


### `verhagen-whitley-2012` (3차 판정)
- 현재: Verhagen, P., & Whitley, T. G. (2012). Integrating Archaeological Theory and Predictive Modeling. *Journal of Archaeological Method and Theory* 19, 49-100. 전문가 판단 기반 모델과 통계 모델의 관계, 순환 논증 문제.
- 교정: Verhagen, P., & Whitley, T. G. (2012). Integrating Archaeological Theory and Predictive Modeling: a Live Report from the Scene. *Journal of Archaeological Method and Theory* 19, 49-100. — suggested annotation: 귀납적(통계) 모델과 연역적(전문가 판단) 모델의 관계, 그리고 예측모델 검증(관측 편향·테스트 데이터 독립성)의 문제. [Only two changes are actually required: restore the dropped subtitle, a …
- 비고: FINAL CALL: DETAIL_MISMATCH + PARTIALLY_SUPPORTED. I reach the same two verdicts as both earlier agents, from my own fresh lookup and my own full-text extraction, so this is a genuine three-way convergence rather than an echo.

WHERE THE TWO AGREED, AND I CONFIRM. Existence: the paper is real and nearly every stated field is right — Philip Verhagen and Thomas G. Whitley, 2012, Journal of Archaeological Method and Theory, volume 19, pages 49-100. The one genuine defect is the title: the published title is 'Integrating Archaeological Theory and Predictive Modeling: a Live Report from the Scene' …


## 4. 검증 하네스 계획 (14건)

테스트가 지키지 못하는 영역과, **출판값으로 고정할 수 있는 구체적 단언** 목록입니다. "맞다고 믿는다"를 "맞다는 걸 보인다"로 바꾸는 작업이며, 이 장은 QGIS 없이도 바로 착수할 수 있습니다.

판독자가 실제로 재현한 값(발췌): ZT 곡률 `z=xy+0.5x²` → profile 1.6153846153846154 / plan 0.6153846153846154; C4 그래프 Brandes → `[0.5,0.5,0.5,0.5]` (가중·비가중 동일); AHP 3x3 (a=2,b=4,c=3) → λmax 3.01829470728963, CR 0.015771299387612077 (폐형식 `λ³-3λ² = ac/b + b/(ac) - 2` 와 일치); Tobler 평지 5.036742124615245 km/h; VIF ≡ 1/(1-r²) 오차 1e-13 이내; AHP 가이드 예시 3건 소수 4자리까지 재현.


#### [blocker] V1 — The whole least-cost engine (Dijkstra, A*, path reconstruction, move set) has zero tests and is unreachable without QGIS

- 위치: `tools/cost_surface_dialog.py` :676 (_neighbors), 697 (_astar_path), 797 (_dijkstra_full), 883 (_reconstruct_path)
- 문제: REFERENCES.md marks these (B) — formulas this plugin implements itself (Dijkstra 1959, Hart/Nilsson/Raphael 1968) — yet no test file imports them, and none can: cost_surface_dialog.py imports qgis.core/processing at module scope, and CI has no QGIS (test_align_export_qgis skips 8/8). tests/test_cost_models.py covers only the per-edge cost function; nothing covers accumulation, the reverse graph, friction averaging, NoData propagation or path reconstruction. Every number a user puts in a report — the accumulated-cost raster, the isochrone minutes, the LCP length — comes out of these 200 lines, and they are the only analytic code in the plugin with no test at all.
- 실패 시나리오: Change `nd = d + w` to accumulate `w` before the friction multiply (a plausible refactor when friction is moved out of the inner loop), or flip `edge_dz = -dz if reverse else dz`. Every test in the suite still passes, `python tests/check_static.py` passes, flake8 passes. A user runs a Tobler cost surface over a 5 m DEM with a friction raster; the isochrone labelled '60 min' now encloses an area computed with friction 1.0 everywhere, i.e. the wrong catchment, and the corridor raster (cost(A->x)+cost(x->B), which is the only consumer of reverse=True) becomes symmetric nonsense on a slope-asymmet …
- 제안 수정: STEP 1 of the harness. Move _neighbors, _astar_path, _dijkstra_full and _reconstruct_path verbatim into a new QGIS-free tools/cost_engine.py (they use only math, heapq, numpy and tools.cost_models.edge_cost; nothing else in their bodies touches qgis or gdal) and re-import them in cost_surface_dialog.py. Add tests/test_cost_engine.py asserting: (a) _neighbors(False, 5.0, 5.0) == [(-1,0,5.0),(1,0,5.0),(0,-1,5.0),(0,1,5.0)] and _neighbors(True, 5.0, 5.0) adds four moves of length math.hypot(5.0,5.0 …

#### [blocker] V2 — A* heuristic admissibility is never checked, so a suboptimal path can ship under the label 'least-cost path'

- 위치: `tools/cost_surface_dialog.py` :720-752 (hfun selection), 749
- 문제: A* returns the optimal path only if h never overestimates. Admissibility here rests on six separate, unasserted claims: that max Tobler speed is exactly tobler_base_kmh (true — the exponential peaks at slope=-offset), that Herzog's 6th-order denominator is >= 1.64 for every slope_abs >= 0, that the Conolly factor is clamped >= 1, that the wheeled speed factor is <= 1, that Naismith time >= distance/horizontal_kmh, and that friction_min (cost_surface_dialog.py:1195) really is the grid minimum. Not one is tested. Worse, edge_cost applies a *floor* `max(min_speed_mps, base*factor)` — if a user sets herzog_base_kmh below min_speed_mps*3.6 (0.18 km/h), the actual speed exceeds vmax and h becomes inadmissible with no warning.
- 실패 시나리오: Someone 'simplifies' the Herzog branch to drop the rel0=1/1.64 normalisation (it looks redundant), so rel_norm becomes 1/den and speeds at gentle slopes exceed herzog_base_kmh. vmax is still set to herzog_base_kmh, h now overestimates, and A* terminates on the first path that reaches the goal instead of the cheapest. test_cost_models.test_herzog_metabolic_flat_uses_base_speed fails — but only because it pins slope 0; if the change instead raised the speed only at nonzero slopes (e.g. a sign slip on the 19.825*s term), that test passes and A* silently returns a path that is not the least-cost p …
- 제안 수정: STEP 2, immediately after V1's extraction. tests/test_cost_engine.py::AstarAdmissibilityTests: for each of MODEL_TOBLER, MODEL_NAISMITH, MODEL_HERZOG_METABOLIC, MODEL_CONOLLY_LAKE, MODEL_HERZOG_WHEELED and MODEL_PANDOLF (cost_mode='energy_j'), build 50 seeded random 21x21 DEMs (np.random.default_rng(seed).normal(100,15)) plus one friction grid uniform in [0.5,3.0], run _astar_path(start=(0,0), end=(20,20)) and _dijkstra_full from the same start, and assert math.isclose(astar_total, dijkstra_dist …

#### [blocker] V3 — Ordinary Kriging has no test of any kind, and its variance raster is the number users would cite as uncertainty

- 위치: `tools/kriging_lite.py` :270 (_cov_exponential), 415-441 (get_inv), 486-496 (weights and variance)
- 문제: REFERENCES.md marks this (B) — the plugin implements Matheron's Ordinary Kriging itself — and DEVELOPMENT.md's coverage table does not list it, correctly, because there is no test. The module imports qgis.core at line 25 so nothing QGIS-free can reach it. Untested here: the augmented system assembly [C 1; 1 0], the unbiasedness constraint sum(lambda)=1, the sign of the Lagrange multiplier in the variance, the nugget-on-diagonal choice (np.fill_diagonal to partial_sill+nugget, i.e. C(0), which makes the system interpolate exactly rather than filter noise), and the exponential form exp(-h/range) versus the exp(-3h/range) 'practical range' convention that PyKrige/gstat/SAGA use. A user who cross-checks this plugin's variance map against SAGA will get a different picture and has no test result …
- 실패 시나리오: The Lagrange sign convention is flipped (vv = ... + mu instead of - mu) — a one-character change that looks like a fix to anyone comparing against a textbook that writes the system with -mu. Every existing test still passes. The variance GeoTIFF now reports its smallest values furthest from the data and its largest values on top of the sample points; an excavation report that shades 'low-confidence zones' from that raster shades exactly the wrong zones, and the prediction raster is unchanged so nothing looks wrong.
- 제안 수정: STEP 3. Extract a QGIS-free tools/kriging_math.py holding exponential_cov(dist, partial_sill, rng), build_ok_system(coords, partial_sill, nugget, rng) -> A, and solve_ok(coords, values, target_xy, partial_sill, nugget, rng) -> (zhat, variance, lam, mu); kriging_lite.py then imports them (the point-collection, spatial index and GeoTIFF writing stay behind QGIS). tests/test_kriging_math.py asserts: (a) exponential_cov(0.0, partial_sill=4.0, rng=10.0) == 4.0 and exponential_cov(10.0, ...) == 4.0*ma …

#### [major] V4 — The Herzog/Minetti 6th-order polynomial is tested only at slope 0, so no coefficient is pinned to a published value

- 위치: `tools/cost_models.py` :133-152
- 문제: tests/test_cost_models.py has exactly one Herzog-metabolic test, test_herzog_metabolic_flat_uses_base_speed, which evaluates the polynomial at slope_abs = 0 — where six of the seven coefficients vanish. Only the constant 1.64 is pinned, and it is pinned twice (it is also rel0), so even that is self-referential. The five coefficients that shape the entire cost surface (1337.8, 278.19, -517.39, -78.199, 93.419, 19.825) are protected by nothing. REFERENCES.md:84-89 names Minetti et al. (2002) and Herzog (2013) as the source and explicitly discloses the abs() isotropy departure — that disclosure is exactly the kind of statement that needs a test, because nothing currently prevents it from becoming false in either direction.
- 실패 시나리오: A transcription fix changes -78.199 to +78.199 (the published sequence alternates sign, so a 'correction' is plausible). At slope_abs = 0.2 the denominator goes from 8.062984 to 9.314 and the 100 m edge cost from 353.98466341463416 s to 408.9 s — a 15% change in every Herzog cost surface, isochrone and least-cost path the plugin produces. The whole test suite passes, because the only Herzog assertion is at slope 0 where that term is zero.
- 제안 수정: STEP 4, cheap and immediate. Add to tests/test_cost_models.py::HerzogMetabolicTests: (a) pin the polynomial itself — for s in (0.05, 0.1, 0.2, 0.3, 0.5) assert the implied denominator (recovered as 1.64 * base_mps * 100.0 / edge_cost(MODEL_HERZOG_METABOLIC, 100.0, 100.0*s, {})) equals the literal published sums 2.8519, 4.4309, 8.062984, 11.3442, 22.3921 to 4 dp, written out as constants, not recomputed from the same coefficient list; (b) pin one end-to-end value: edge_cost(MODEL_HERZOG_METABOLIC …

#### [major] V5 — Zevenbergen & Thorne curvature: no test exercises the cross-derivative F or the north-up row order, so plan curvature is unprotected

- 위치: `tools/terrain_math.py` :36-56
- 문제: All six curvature tests in tests/test_terrain_math.py use surfaces that are even in y and have no xy cross term: flat, z=3x+2y (curvature 0 by construction), z=0.5x^2, z=-0.5x^2 and z=0.5(x^2+y^2). On every one of them F == 0 and the y-derivative H either vanishes or is symmetric, so neither F's sign nor the row-order assumption is ever observed. Worse, the test helper builds its grid with ys = arange(n)*cell indexed by row — y INCREASING downward — which is the opposite of the north-up raster convention the code is written for (Z2 = roll(z,1,0) is the row above, i.e. larger y). The tests therefore pass under the wrong orientation, which is the strongest possible evidence that they cannot see it. Plan curvature on a real DEM is dominated by the F*G*H term; it is currently asserted only whe …
- 실패 시나리오: Someone 'fixes' H to (Z8 - Z2)/(2*cell) to match the test helper's y-increasing-downward grid, or reorders F's corner terms to (-Z1 + Z3 - Z7 + Z9). All six existing curvature tests still pass (F and the y-asymmetry are invisible to every one of them). On a real north-up DEM the plan curvature raster flips sign everywhere the surface is not symmetric: the layer written as '부호규약: 음=수렴' now marks divergent ridges as convergent hollows, and an erosion/deposition interpretation drawn from that map is inverted. The sign convention is the one thing REFERENCES.md tells reviewers to check by hand.
- 제안 수정: STEP 5. Add tests/test_terrain_math.py::ZtCurvatureCrossTermTests with a NORTH-UP grid helper (ys[i] = (n-1-i)*cell, so row 0 carries the largest y). On z = x*y + 0.5*x^2 over a 9x9 grid with cell=1.0, at the interior cell x=2.0, y=1.0 (i=7, j=2): assert profile == 21/13 == 1.6153846153846154 and plan == 8/13 == 0.6153846153846154, both to 1e-9. These follow from the published ZT algebra with D = z_xx/2 = 0.5, E = 0, F = z_xy = 1, G = z_x = 3, H = z_y = 2, giving ZT profile = -(z_xx*z_x^2 + z_yy …

#### [major] V6 — Brandes betweenness is never tested on a graph with tied shortest paths, so the sigma path-counting core is unasserted

- 위치: `tools/network_metrics.py` :73-121 (weighted), 157-188 (unweighted)
- 문제: The three topologies tests/test_network_metrics.py uses for betweenness values are PATH (0-1-2), STAR and TRIANGLE. In PATH and STAR every pair has exactly one shortest path; in TRIANGLE every pair is adjacent so no vertex is ever an intermediary. sigma is therefore 1 or 0 in every assertion, and the sigma[v]/sigma[w] dependency accumulation — the entire point of Brandes (2001), which REFERENCES.md names as the source — is never exercised. The weighted variant's tolerance branch (abs(nd - dist[w]) <= 1e-12, which is what splits credit between equal-cost routes on a cost network) is reached by no test at all. test_weighted_matches_unweighted_on_unit_weights only compares the two implementations against each other, so a shared bug is invisible.
- 실패 시나리오: The tie branch is changed to `sigma[w] = sigma[v]` (matching the improvement branch two lines above — a very easy copy-paste during a refactor). Every existing betweenness test passes: no test graph ever reaches that branch. On a real k-NN cost network with two equal-cost routes between settlements, the intermediary nodes on one route get full credit and the other route's nodes get none; the 'betweenness' column in the exported node layer, which is what a paper would rank sites by, is wrong for exactly the nodes a reader would care about most.
- 제안 수정: STEP 6, cheap. Add to tests/test_network_metrics.py: C4 = [[1,3],[0,2],[1,3],[0,2]] (the 4-cycle). Assert betweenness_centrality_unweighted(n=4, adj=C4) == [0.5, 0.5, 0.5, 0.5] to 1e-12 and betweenness_centrality_weighted(n=4, adj=unit-weighted C4) == the same — verified against the current implementation. The value is exact and hand-derivable: each opposite pair (0,2) and (1,3) has two shortest paths of length 2, so each intermediary takes 1/2, and the undirected 0.5 normalisation is already ap …

#### [major] V7 — AHP: Saaty's random index table is not pinned, and no inconsistent matrix with a known lambda_max is asserted

- 위치: `tools/ahp_core.py` :25-42 (RI_TABLE), 44-78 (ahp_weights_from_matrix)
- 문제: 48 AHP tests, and every lambda_max/CR assertion is on a PERFECTLY CONSISTENT matrix (built by _consistent_matrix, where lambda_max == n and CR == 0 by construction) or an ordering comparison (cr_near < cr_far, cr > 0.1). No test asserts a single RI value, and no test asserts a CR against an independently known number. RI is a pure divisor: every CR the dialog shows, and the CR > 0.10 warning that is the plugin's only consistency gate, scales directly with it. REFERENCES.md:130-135 sources n<=10 to Saaty (1980) and n=11..15 to Alonso & Lamata (2006) — an attribution with nothing behind it.
- 실패 시나리오: RI_TABLE[4] is edited from 0.90 to 0.89 (Saaty's later papers print 0.882 and 0.90 for n=4 depending on the sample size, so a 'correction' is plausible). Every one of the 48 AHP tests passes, because every CR assertion is either exactly 0 (RI cancels) or an inequality. A user's 4-criterion matrix that previously read CR = 0.1005 with the '(주의: 0.10 초과)' warning now reads CR = 0.0994 with no warning, and the AHP suitability map is published as consistent. The dialog's only quality gate silently moved.
- 제안 수정: STEP 7. Add tests/test_ahp_core.py::RandomIndexTests asserting the 15 RI values literally, with the source split commented (n<=10 Saaty 1980, n=11..15 Alonso & Lamata 2006), so any edit is a deliberate diff against a cited table; and assert that RI_TABLE has no entry for n=16 and that CR is NaN there (that half already exists). Add InconsistentMatrixTests using the published closed form for a 3x3 reciprocal matrix: with a12=a, a13=b, a23=c, the characteristic polynomial reduces to lambda^3 - 3*l …

#### [major] V8 — docs/AHP_GUIDE.md claims every number in it came from running the code, and nothing re-runs them

- 위치: `docs/AHP_GUIDE.md` :5, 64-68, 125, 134, 161, 248, 331
- 문제: Line 5 makes a verifiable promise about the whole document, and the guide is the artefact a user reads before defending their weights to a reviewer. I re-derived all three worked matrices through sanitize_pair_values -> matrix_from_pairs -> ahp_weights_from_matrix and they reproduce exactly (0.5333/0.2667/0.1333/0.0667 CR 0.0000; 0.5267/0.3005/0.1098/0.0630 CR 0.0074; 0.3150/0.3150/0.3150/0.0550 CR 1.0089). So the claim is true TODAY — and it is true by nobody's effort, because no test re-derives any of it. The scoring-mode table at lines 64-68 (benefit/cost/target/range/reclass over slope 0-40 deg) is likewise reproducible through score_formula and likewise unguarded.
- 실패 시나리오: The eigenvector selection in ahp_weights_from_matrix is changed from np.linalg.eig to the geometric-mean (row-product) approximation — a common and defensible AHP variant, and one that a maintainer might adopt to avoid the complex-eigenvalue branch. Every existing AHP test still passes: consistent matrices give the same weights under both methods, and the inconsistency tests are all inequalities. The guide's 52.7/30.1/11.0/6.3 and CR = 0.007 become 52.8/30.0/11.0/6.2 and CR reported differently, the documented example no longer matches what the dialog shows, and line 5's promise is now false w …
- 제안 수정: STEP 8. Add tests/test_ahp_guide_examples.py that re-derives each documented number through the real public API and asserts the printed value, with the doc line number in the assertion message. Specifically, with keys ['slope','river','geo','solar'] and pairs fed through sanitize_pair_values: (a) {2,4,8,2,4,2} -> weights rounded to 1 dp of percent == [53.3, 26.7, 13.3, 6.7] and round(CR,3) == 0.000 (AHP_GUIDE.md:125); (b) {2,5,7,3,5,2} -> [52.7, 30.1, 11.0, 6.3] and round(CR,3) == 0.007 (line 13 …

#### [major] V9 — 22 GDAL/QGIS enum integers are passed as bare literals with no test that any of them means what its comment says

- 위치: `tools/terrain_analysis_dialog.py` :609, 611, 663, 665, 687, 855 — plus viewshed_dialog.py:2008/2165/2616/4042, ahp_suitability_dialog.py:1760/1953/1981/2357, align_export_dialog.py:845, distance_raster_dialog.py:393/416, geology_zip_dialog.py:1198/1284, geochem_polygonize_dialog.py:1991, slope_aspect_drafting_dialog.py:613, trench_suggestion_dialog.py:983
- 문제: The integer for Float32 is 6 in gdal:warpreproject / gdal:cliprasterbymasklayer / gdal:cliprasterbyextent / gdal:translate (their lists are prefixed with 'Use Input Layer Data Type') but 5 in gdal:proximity, gdal:rasterize and gdal:rastercalculator's RTYPE (unprefixed). The plugin currently gets this right at every site I could resolve — distance_raster_dialog.py:416 uses 5 for gdal:proximity, terrain_analysis_dialog.py:687 uses 5 for RTYPE, terrain_analysis_dialog.py:611 uses 6 for warpreproject — but that correctness is held by comments, not by a test. Nothing in tests/ asserts a single one of these mappings, and the only test that touches a real GDAL algorithm, tests/test_align_export_qgis.py, skips all 8 of its tests in CI. tests/test_categorical_meta.py already proves the pattern work …
- 실패 시나리오: A maintainer harmonises the enums 'for consistency', changing terrain_analysis_dialog.py:687 from RTYPE 5 to RTYPE 6 because line 611 nearby uses 6 for the same intent (Float32). gdal:rastercalculator's RTYPE list is unprefixed, so 6 is Float64 — harmless. But the reverse edit, distance_raster_dialog.py:416 from DATA_TYPE 5 to 6 on gdal:proximity, makes the distance raster Float64 while the layer metadata and the covariate stack still describe a Float32 predictor; and terrain_analysis_dialog.py:611 changed from 6 to 5 makes the TPI focal-mean warp Int32, so the block average of an Int16 DEM tr …
- 제안 수정: STEP 9. Add tests/test_gdal_enums.py modelled on tests/test_categorical_meta.py::CallSiteCensusTests. Check in a table QGIS_OPTION_LISTS = {('gdal:warpreproject','DATA_TYPE'): ['Use Input Layer Data Type','Byte','Int16','UInt16','UInt32','Int32','Float32','Float64','CInt16','CInt32','CFloat32','CFloat64'], ('gdal:warpreproject','RESAMPLING'): ['Nearest neighbour','Bilinear','Cubic','Cubic spline','Lanczos','Average','Mode','Maximum','Minimum','Median','Q1','Q3'], ('gdal:rastercalculator','RTYPE' …

#### [major] V10 — VIF and the correlation matrix — the multicollinearity gate for every predictor stack — have no tests

- 위치: `tools/covariate_report_dialog.py` :100-123
- 문제: _compute_vif is a module-level pure-numpy function — it touches no QGIS object — yet it sits in a module that imports qgis.core at the top, so no QGIS-free test can reach it, and none exists. The report it feeds is the plugin's stated quality gate before a predictor stack goes into MaxEnt/GLM (the dialog prints '|r| >= 0.7 또는 VIF >= 5는 변수 중복 신호'), and REFERENCES.md positions the whole covariate report as the plugin's contribution to predictive modelling. Untested: the intercept column (without `ones` the R^2 is computed through the origin and every VIF is inflated), the r2 < 0.999999 cutoff that decides inf versus a finite value, the near-constant guard, and the NaN-versus-1.0 distinction the comment says matters.
- 실패 시나리오: The `ones` intercept column is dropped from `cols` during a cleanup (it looks redundant next to np.linalg.lstsq). For two centred, weakly correlated predictors the VIFs are unchanged; for two predictors with large non-zero means and r = 0.1 — slope in degrees and elevation in metres, the ordinary case — the through-origin R^2 approaches 1 and both VIFs jump past the VIF >= 10 '제거 권장' line. The user drops a genuinely independent predictor from their model on the plugin's advice, and the CSV export records the inflated number as evidence.
- 제안 수정: STEP 10. Extract _compute_vif and the correlation assembly into a QGIS-free tools/covariate_stats.py (the sampling and the HTML stay behind QGIS) and add tests/test_covariate_stats.py: (a) ANALYTIC IDENTITY — for a 2-column matrix, VIF == 1/(1 - r^2) for both columns, where r is np.corrcoef's value; with rng=default_rng(0), x=normal(500), y=0.8*x+sqrt(1-0.64)*normal(500), r == 0.822502609822486 and both VIFs == 3.0912908562254877, matching 1/(1-r^2) to 1e-13 (verified); assert the identity acros …

#### [major] V11 — Gabriel graph and RNG filters — two named published constructions — have no tests and sit behind a QGIS import

- 위치: `tools/spatial_network_dialog.py` :1605-1624 (_ppa_filter_gabriel), 1625-1647 (_ppa_filter_rng)
- 문제: REFERENCES.md marks both (B) with named sources (Gabriel & Sokal 1969; Toussaint 1980) and describes the exact geometric predicate each implements. Both function bodies are pure numpy on a coords array — no QGIS type crosses the boundary — but they are methods on a QgsDialog subclass in a module that imports qgis.core, so nothing tests them. The Gabriel test is the diameter-circle emptiness test and the RNG test is the lune emptiness test; they differ only in the predicate, and a copy-paste between them (they are 20 lines apart and structurally identical) would produce a graph that is still plausible-looking, still connected, and wrong.
- 실패 시나리오: The RNG predicate's np.maximum is changed to np.minimum — the lune test becomes 'some point is closer to EITHER endpoint' instead of 'to BOTH'. On the unit square plus its centre, RNG currently keeps exactly the four spokes {(0,4),(1,4),(2,4),(3,4)} and rejects all four sides; with np.minimum it rejects the spokes too and returns the empty set, or on other configurations returns a sparser graph. The exported PPA network layer, the closeness/betweenness columns computed on it, and any 'site X is a broker' claim drawn from them are all derived from the wrong edge set, and the layer name still sa …
- 제안 수정: STEP 11. Extract both filters as free functions into a QGIS-free tools/ppa_filters.py taking (cand_edges, coords) exactly as now, and have the dialog call them. tests/test_ppa_filters.py, with coords = [[0,0],[1,0],[1,1],[0,1],[0.5,0.5]] (unit square plus centre) and cand_edges = all 10 pairs: (a) gabriel(...) == {(0,1),(1,2),(2,3),(0,3),(0,4),(1,4),(2,4),(3,4)} — the four sides and four spokes, with the two diagonals (0,2) and (1,3) REJECTED because the centre sits at their midpoint, i.e. on th …

#### [major] V12 — The broad-scale TPI radius arithmetic, the viewshed curvature coefficient and the Higuchi zone resolution are pure logic with no tests

- 위치: `tools/terrain_analysis_dialog.py` :601 (new_res); viewshed_dialog.py:457-471 (_calculate_gdal_viewshed_cc); viewshed_dialog.py:4637-4685 (_get_higuchi_thresholds/_resolve_higuchi_thresholds/_format_higuchi_distance)
- 문제: Three pieces of user-visible arithmetic that are each a handful of pure lines with no QGIS dependency in the body, each currently reachable only through a dialog instance. (1) new_res encodes the (2r+1) fix the docstring says was necessary because 'a block of radius cells would have delivered only about half the radius the label claims' — the layer name then prints that radius as fact. (2) _calculate_gdal_viewshed_cc maps the UI's refraction coefficient k onto GDAL's -cc argument, including the rule that refraction forces curvature on and the [0,1] clamp; every viewshed the tool produces passes through it. (3) The Higuchi resolution enforces near < mid by swapping and nudging, and those two numbers are written into the layer metadata as higuchi_near_m / higuchi_mid_m, which REFERENCES.md t …
- 실패 시나리오: new_res is changed to max(px,py) * radius (reverting the documented fix, which reads like an off-by-one). On a 5 m DEM with radius 13 the block goes from 135 m to 65 m, so the 'TPI (근사 반경≈13셀)' layer and the Weiss landform classification built on it are computed over half the intended window — and the layer name, the metadata and the help text all still say 13 cells. Separately, dropping the `if refraction and not curvature: curvature = True` line makes a user who ticks refraction but not curvature get -cc 0 (no correction at all) while the dialog's help panel still describes a refraction-corr …
- 제안 수정: STEP 12. Move all three into QGIS-free helpers — tools/terrain_math.py gains tpi_block_resolution(pixel_x, pixel_y, radius); a new tools/viewshed_math.py gains gdal_viewshed_cc(curvature, refraction, refraction_coeff) and resolve_higuchi_thresholds(near_m, mid_m) / format_higuchi_distance(v) — and have the dialogs delegate. Assertions: (a) tpi_block_resolution(5.0, 5.0, 13) == 135.0 and tpi_block_resolution(5.0, 5.0, 1) == 15.0, i.e. radius 1 reproduces gdaldem's 3x3 span, which is the invariant …

#### [major] V13 — The least-cost network MST is Kruskal over a candidate-pair subgraph, with no test that the result is a spanning tree at all

- 위치: `tools/cost_network_dialog.py` :178 (_UnionFind), 958-976 and 1010-1028 (the Kruskal loops)
- 문제: REFERENCES.md marks the MST (B) and names Kruskal (1956), and the tool help at cost_network_dialog.py:1167 and :2024 repeats it. The implementation is a correct Kruskal — over `candidate_pairs`, not over the complete graph. If candidate_pairs is a k-NN or distance-thresholded subset, or if any sym_cost is None (an unreachable pair), the loop terminates with fewer than len(hub_list)-1 edges and the result is a spanning FOREST, which is then written out as a layer whose edge kind is literally 'mst' and 'hub_mst'. Nothing tests the union-find, the sort order, the early-exit at len(hub_list)-1, or the forest case, and the whole thing is behind a QGIS import.
- 실패 시나리오: Five hubs where the cost raster leaves hub E in a separate valley, so no candidate pair involving E has a finite cost. The loop unions A-B-C-D into one component, produces 3 edges, never reaches the len(hub_list)-1 == 4 early exit, and returns. The output layer contains a 4-node tree plus an orphan, styled and labelled as the minimum spanning tree of five sites. A reader of the resulting map concludes E was not connected to the network in antiquity, when in fact the analysis window simply never reached it. Separately, if _UnionFind.union ever returns True for an already-joined pair (a path-com …
- 제안 수정: STEP 13. Extract _UnionFind and a free function kruskal_mst(n, weighted_edges) -> set of edges into a QGIS-free tools/mst.py (both are pure python) and have both call sites use it. tests/test_mst.py: (a) on the 4-node graph with edges (0,1,1.0),(1,2,2.0),(2,3,3.0),(0,3,4.0),(0,2,5.0) assert the MST is exactly {(0,1),(1,2),(2,3)} with total weight 6.0 — hand-computable and unambiguous; (b) a graph with two edges of identical weight asserts a DETERMINISTIC choice (the sort is by weight only, so ti …

#### [major] V14 — The CI harness cannot notice an unlisted test file, runs zero QGIS/GDAL code, and pins the cost-budget constants to themselves

- 위치: `.github/workflows/ci.yml` :19-35 (the hand-maintained unittest list), plus tests/test_align_export_qgis.py:38 and tests/test_cost_budget.py:33-41
- 문제: Three harness-level gaps that undercut every test above. (1) CI enumerates 15 modules by hand; unittest discovery does not work from tests/ (no __init__.py, ImportError: Start directory is not importable). DEVELOPMENT.md:82 tells contributors to remember to add new files to ci.yml, and nothing enforces it — a new tests/test_cost_engine.py would be invisible to CI while looking fully covered in the repo. (2) tests/test_align_export_qgis.py reports 'OK (skipped=8)' on the CI runner, so the plugin's ONLY tests that touch a real gdalwarp — including the one that would confirm raster_grid_contract's central claim that GDAL sizes with floor(ratio + 0.5) — have never run in CI. The grid contract that gates whether an aligned export is published is therefore validated only against its own arithmet …
- 실패 시나리오: (1) A contributor adds tests/test_cost_engine.py from V1, it passes locally, and they forget ci.yml. Six months later a refactor breaks _dijkstra_full; CI is green on every commit because the file is never invoked. (2) A QGIS upgrade changes gdalwarp's rounding at exact half-cell extents from round-half-up to round-half-even. canonical_gdal_target_grid still computes floor(ratio+0.5), so validate_grid rejects a correct warp output with GridMismatchError('width') and align/export refuses to publish — or, if the tolerance happens to absorb it, publishes a grid one cell off from the contract. Bot …
- 제안 수정: STEP 14, do this FIRST because it is what makes steps 1-13 stick. (a) Add tests/test_ci_wiring.py: parse .github/workflows/ci.yml with a regex for `python -m unittest tests\.(\w+)`, collect the set, glob tests/test_*.py, and assert the two sets are equal — the failure message naming the missing module. This is the same census pattern tests/test_categorical_meta.py::CallSiteCensusTests already uses. (b) Add a second CI job on the qgis/qgis:release-3_40 (or ghcr equivalent) image that runs `python …

## 5. 코드 감사 findings — 적대적 검증 통과 (43건)

각 finding을 **반박 / 재현 / 영향** 세 가지 독립 렌즈로 검증해 과반이 실재로 판정한 것만 남겼습니다. 같은 배치에서 **124건이 기각**됐습니다(생존율 26%). 기각된 쪽에는 "코드를 더 읽어 보니 앞선 가드가 이미 막고 있다", "구체적 실패 입력을 구성할 수 없다", "이미 UI에 공개돼 있다" 가 많았습니다.

| 심각도 | 건수 |
| --- | --- |
| major | 28 |
| minor | 12 |
| blocker | 3 |

### geochem


#### [blocker] G1 — Any off-legend colour is silently forced onto the nearest legend segment; the dark corner of RGB space lands on the legend MAXIMUM, so black linework and its anti-alias halo are reported as top-percentile anomalies

- 위치: `/home/user/archtoolkit/tools/geochem_legend.py` :79-101 (projection + winner assignment), 109 (mask_black_lines thresholds); consumed at /home/user/archtoolkit/tools/geochem_polygonize_dialog.py:1475-1481 and 1568
- 문제: interp_rgb_to_value returns a concentration for EVERY pixel no matter how far that pixel's colour is from the legend polyline. min_dist is computed and then thrown away, so there is no tolerance, no NoData for unmatched colours, and no residual band the user could inspect. Because the Fe2O3/Pb/Cu/Zn/Sr/Ba/CaO ramps all end at the near-black maroon (115,12,12), the entire dark/muddy region of RGB space is nearest to the LAST segment, whose value is the legend maximum. Measured on the actual code over a 4-step sweep of the 256^3 cube with the Fe2O3 preset: 10.40% of all RGB colours invert to >=12%, 6.81% to >=40%, 4.74% to >=50%, while mask_black_lines catches only 0.30% of the cube. The black->red anti-alias ramp gives (23,0,0)->51.0, (46,0,0)->51.0, (69,0,0)->51.0, (92,0,0)->51.0, (115,0,0)->50.17, and none of those is masked (|r-g|>=15 defeats the neutrality test). The black->yellow ramp gives (26,26,0)/(51,51,0)/(77,77,0)/(102,102,0)->51.0, (128,128,0)->50.29, also unmasked. Same colours on the Pb preset give 1363 ppm and on Zn 21100 ppm. mask_black_lines' own docstring says it del …
- 실패 시나리오: Fe2O3 WMS rendered with black administrative/geological boundary lines (the normal case - the dialog ships an inpaint option precisely because they are there). Default settings: 검은 경계선 제거 ON, 보간 거리 30 px. The 1-2 px anti-aliased halo along every line has colours such as (46,0,0), (92,0,0), (115,0,0), (102,102,0). None is caught by mask_black_lines; every one inverts to 50.2-51.0% Fe2O3 - the 99-100th percentile class. The FillNodata step then seeds the removed black core from that halo, so the line comes back as a continuous 51% ribbon. Result: the class raster grows a network of class-10 ('12-51%') polygons tracing every boundary line; the zonal-stats layer reports val_max = 51.0 for every zone a line crosses; 가중 중심점 with rule 'top_pct' (top 10%) selects the linework and plants the centre …
- 제안 수정: Return the residual from interp_rgb_to_value (or accept a max_rgb_distance argument) and have the dialog set pixels whose nearest-segment distance exceeds a small tolerance (Euclidean RGB ~15-25) to NoData, reporting the rejected count in the message bar, not just the log. Optionally write the residual as a second band / companion raster so the user can see where the colour match failed. Independently, widen the linework mask to catch dark colour-cast pixels (e.g. max(r,g,b) < 110 combined with a distance-to-legend test) rather than relying on near-neutrality, and exclude filled/rejected pixels from the top class instead of letting the top class absorb the whole dark corner of RGB space.
  - 검증: certain: The finding is real and I could not refute any part of it. I verified the mechanism, reproduced all six quoted statistics to two decimals and all eleven quoted point values to three decimals, and then built a cleaner failure case than the one submitted.

MECHANISM (geochem_legend.py:79-101) …
  - 검증: certain: CONFIRMED and constructible. The mechanism is exactly as claimed: interp_rgb_to_value computes min_dist purely to decide which legend segment wins and then throws it away at line 101, so every pixel receives a concentration no matter how far its colour lies from the legend polyline. I grepp …
  - 검증: certain: CONFIRMED, and I am holding the severity at blocker.

MECHANISM VERIFIED. interp_rgb_to_value initialises out=NaN and min_dist=inf (lines 49-50), but dist_sq is always finite so `mask = dist_sq < min_dist` is universally true on the first valid segment. min_dist is then updated (line 99) an …

#### [major] G4 — Zonal statistics rasterize every zone with ALL_TOUCHED=TRUE, so pix_in, c*_area, cov_pct and val_* are computed over a dilated zone

- 위치: `/home/user/archtoolkit/tools/geochem_polygonize_dialog.py` :278 (_gdal_rasterize_wkt_mask), used for zones at 2459-2466, statistics at 2519-2545 and 2586-2591
- 문제: ALL_TOUCHED includes every pixel the polygon boundary so much as clips, instead of the pixel-centre (or >=50% overlap) rule that zonal statistics normally use and that QGIS's own zonal-statistics algorithm uses. The same helper is reused for the AOI mask, where over-inclusion is harmless, but for zone polygons it systematically inflates pix_in and the derived c*_area, and it dilutes val_mean/val_std/val_min/val_max with pixels that are mostly outside the zone. Nothing in the zonal-stats group box, tooltip or field names discloses the rule. There is also no field carrying the polygon's own geometric area, so the user cannot detect the discrepancy from the attribute table.
- 실패 시나리오: GeoChem run at the canvas resolution of a 1:25,000 view (px ~= 30 m in the raster CRS). The zone layer is a set of excavation trench polygons, each 40 m x 40 m (true area 1600 m2), not grid-aligned so each spans parts of a 2x2 pixel block. ALL_TOUCHED burns 4 pixels: pix_in = 4, c*_area sums to 4 * 900 = 3600 m2 - 2.25x the trench's real area - and val_mean is the average of four 30 m cells of which roughly two thirds of the sampled ground lies outside the trench. For a 10 m x 10 m test pit (100 m2) the same code can report up to 3600 m2, a 36x over-statement, and val_mean becomes essentially a value for the surrounding field.
- 제안 수정: Give _gdal_rasterize_wkt_mask an all_touched flag and pass False for zone polygons (pixel-centre rule), or better, offer the choice in the UI and record it in the layer metadata. Add a zone_area field carrying QgsDistanceArea ellipsoidal area of the polygon itself so the pixel-derived area can be checked, and state the rule in the zonal-stats tooltip.
  - 검증: certain: REAL. The defect is exactly as described and I could not find any guard, caller check, API behaviour, comment or tooltip that prevents or discloses it.

The core claim survives on all three questions. Q1: pix_in and every c*_area are computed over a mask that includes every pixel the polygo …
  - 검증: certain: CONFIRMED, and the finding understates itself.

Concrete construction. Project CRS == raster CRS (so the canvas-resolution branch at L1396-1399 is taken), AOI roughly 30 km across, 픽셀 크기 left at 0 -> px ≈ 29-30 m, geotransform = (x0, 30, 0, y0, 0, -30), so px_area = |30 * -30| = 900 m2 at L …
  - 검증: certain: The finding is real and correctly graded major. Keep it there — not blocker, not minor.

Why it is real and publication-relevant. The bias is systematic (always upward, never zero), unconditional (no flag, every zonal run), and lands on a number the UI explicitly calls 구간면적 — class area. Th …

#### [major] G5 — px_area and every c*_area in the zonal-stats layer are in raster-CRS units squared but presented as plain 'area'; on a geographic WMS they are square degrees

- 위치: `/home/user/archtoolkit/tools/geochem_polygonize_dialog.py` :2348-2352 (px_area), 2390 and 2399 (field definitions), 2583 and 2591 (values written)
- 문제: px_area is the determinant of the exported raster's geotransform, i.e. an area in the RASTER layer's CRS units, and c*_area = pixel count * px_area inherits those units. The fields are named px_area / c01_area / c02_area with no unit suffix and, unlike _decorate_polygons (which sets Korean aliases and computes area_m2/area_ha via QgsDistanceArea ellipsoidal measurement at lines 2777-2795), _make_zonal_stats_layer sets no aliases and no unit anywhere. The zone layer is typically in a projected Korean CRS while a WMS is frequently served in EPSG:4326, so the two are not even the same units; the layer's own unit field is set to the element unit ('%', 'ppm'), which makes the area columns look like they belong to the same system.
- 실패 시나리오: WMS layer is served in EPSG:4326, zone layer is a 문화재 보호구역 shapefile in EPSG:5186. px = 0.0002 degrees, so px_area = 4e-8. A zone covering 40000 pixels of class 7 gets c07_area = 0.0016, written to a Double column called 'c07_area' next to val_mean in %. Exported to CSV for a report, that column reads as an area of 0.0016 - meaningless, and silently so, because the polygon layer produced by the same run does label its areas area_m2/area_ha in real square metres.
- 제안 수정: Convert pixel counts to area with QgsDistanceArea in the zone layer's CRS (or at minimum only emit area fields when the raster CRS is projected), name the fields c*_area_m2, and set Korean aliases including the unit the same way _decorate_polygons already does.
  - 검증: certain: Confirmed. c*_area and px_area are planar areas in the exported raster's CRS units squared, and nothing in the file converts, labels, guards or discloses that.

The one thing I would adjust is that the finder picked the weaker of the two failure modes. Their EPSG:4326 scenario is real but s …
  - 검증: certain: CONFIRMED, and the finding understates its own worst case.

The unit chain is exactly as claimed. _export_raster_to_geotiff never reprojects: the primary path calls writer.writeRaster(pipe, width, height, extent, raster.crs(), ctx) at :1466 (5th arg = output CRS = the WMS layer's own CRS), …
  - 검증: certain: REAL, and major stands. Every mechanical claim checks out against the current file.

Why it matters for publication. The user ticks "구역 통계" precisely to get per-zone, per-class 면적, opens the attribute table of `Fe2O3_구역통계_ab12cd`, and copies c07_area into a table in an excavation report. Tw …

#### [major] G6 — The automatic pixel size is not the canvas resolution the label and tooltip promise: it silently becomes extent/1024 whenever the project CRS differs from the raster CRS, and silently coarsens again at the 12 Mpx cap

- 위치: `/home/user/archtoolkit/tools/geochem_polygonize_dialog.py` :592 and 854-858 (tooltips), 1393-1406 (fallback), 1412-1434 (silent cap)
- 문제: Two user-facing strings (the field tooltip at 592 and the detailed tooltip at 854-858) state that leaving the spinbox at 0 uses the canvas mapUnitsPerPixel. The code only does that when the project's destination CRS is object-equal to the raster CRS; otherwise it falls through to a hard-coded 'longest side / 1024' with no message. A second silent change happens at the 12 Mpx guardrail: when the user left the spinbox at 0, px is multiplied by sqrt(total/MAX) and the run continues at a coarser resolution, reported only as a log line. Resolution is not cosmetic here - it decides how many pixels each class gets, hence every class area, every zonal c*_n/c*_area/cov_pct, and how much of the map is linework halo (see G1).
- 실패 시나리오: Project CRS EPSG:5186 (Korea 2000 Central Belt), WMS served in EPSG:3857 (the usual combination). The user zooms to a 3 km x 2 km survey area at a canvas resolution of about 1 m/px, leaves 픽셀 크기 at 0 because the tooltip says the canvas resolution will be used, and runs. px is actually 3000/1024 = 2.93 m, so the export is ~1024 x 683 instead of ~3000 x 2000 - about 9x fewer samples. Class areas and zonal counts change accordingly, and rerunning the same AOI after switching the project CRS to EPSG:3857 produces different numbers for the same map with no indication why.
- 제안 수정: When the canvas resolution cannot be used, reproject mapUnitsPerPixel into the raster CRS (transform a canvas-width segment) instead of falling back to extent/1024; if that is not possible, push a message-bar warning naming the pixel size actually used. Do the same for the MAX_PIXELS auto-coarsening, and write the final px into the layer metadata params so a saved raster can be traced.
  - 검증: certain: The finding survives. Both tooltips state unconditionally that a 0 in the spinbox uses the canvas mapUnitsPerPixel; the code does that only when `dest_crs == raster.crs()` (value equality on QgsCoordinateReferenceSystem, not object identity as the finding loosely says — same conclusion), an …
  - 검증: certain: CONSTRUCTED — both halves reproduce, with one correction to the finding's downstream claims.

**Path 1, the CRS-mismatch fallback.** Inputs: project/canvas destinationCrs = EPSG:5186 (Korea 2000 Central Belt), geochemical WMS layer crs() = EPSG:3857, AOI polygon layer in EPSG:5186 holding o …
  - 검증: likely: REAL, and it survives on its first half only. Two corrections to the finding before grading it.

Correction 1 - the two halves cannot co-occur. I proved the extent/1024 fallback can never trip the 12 Mpx cap: px = max(w,h)/1024 forces width<=1024 and height<=1024, so total_px <= 1,048,576, a …

#### [major] G7 — Inpainted (fabricated) pixels are indistinguishable from measured ones downstream, and cov_pct - the only field that could reveal it - counts them as measured

- 위치: `/home/user/archtoolkit/tools/geochem_polygonize_dialog.py` :1564-1597 (mask + fill, no record kept), 2519-2545 (cov_pct/val_* over the filled array), 2966-2986 (layer metadata records no correction flags)
- 문제: The linework mask is computed, used once and dropped; the filled array replaces `out` wholesale. From that point on nothing - not the single-band value GeoTIFF, not the class raster, not the polygon attributes, not the zonal-stats fields, not the layer custom properties (params_json carries only preset_key/preset_label/unit) - can tell a measured pixel from an interpolated one. The zonal-stats layer offers cov_pct, which a reader will naturally take as 'how much of this zone actually had data', but it is computed after the fill, so interpolated cells count as valid. The interval statistics val_mean/val_std, the per-class pixel counts and areas, and the weighted centre all mix synthetic values in silently. The only trace is a QGIS log line ('GeoChem: linework mask m/t (x.xx%)'). The inpaint tooltip discloses that filling happens and that boundaries may smooth, but not that the filled cells are then counted and reported as data.
- 실패 시나리오: A 1:50,000 sheet whose AOI is crossed by geological boundary lines and place-name labels: the linework mask covers 8% of the zone's pixels. With 검은 경계선 제거 ON (default, 30 px search) those 8% are refilled. The zonal-stats row reports cov_pct = 100.0 and val_mean over 100% of the zone, when only 92% of it was measured and the remaining 8% is IDW from neighbours - neighbours which, per G1, include 51%-valued halo pixels. The user quotes 'full coverage, mean Fe2O3 = x%' in a report.
- 제안 수정: Keep the fill mask and (a) exclude filled cells from cov_pct / pix_val (or add a separate fill_pct field), (b) write a companion 1-bit 'measured' mask raster or a second band alongside the value raster, and (c) record inpaint on/off and fill distance in the layer metadata params_json so a saved GeoTIFF can be traced back.
  - 검증: likely: REFUTED. The individual code facts are all accurate, but the causal link to the stated failure does not hold, and the disclosure the finder says is missing is present.

1. The constructed failure has a zero delta. The scenario is "cov_pct = 100.0 ... when only 92% of it was measured", attrib …
  - 검증: certain: REAL, and I can construct it exactly as described.

CONCRETE INPUTS. Fe2O3 preset (FE2O3_POINTS, line 99-111). A 200x200 px AOI window over an RGB geochemical sheet: left half pure green (0,255,0) = legend 4.5%, right half pure yellow (255,255,0) = legend 7.1%. Three 3-px-wide black geologi …
  - 검증: certain: Real, but the finding borrows another finding's severity and inverts the sign of the harm. Downgrade major -> minor.

1. The headline failure scenario does not survive the counterfactual. G7 claims the fill is what makes cov_pct report 100.0 when only 92% was measured. I checked what those …

#### [major] G8 — '최댓값을 범례 최댓값으로 보정' rescales every pixel by a factor derived from the clip's own maximum - including pixels outside the AOI - and the result is recorded nowhere

- 위치: `/home/user/archtoolkit/tools/geochem_polygonize_dialog.py` :1550-1562 (rescale), 867-871 (tooltip that recommends it), 2966-2986 (not recorded in metadata)
- 문제: Three problems, none disclosed. (1) The tooltip recommends the option for exactly the case where it is wrong: if the clip does not contain the high-concentration range, the correct conclusion is that the area has no high values; multiplying every pixel by target_max/cur_max manufactures them. (2) cur_max is taken before the AOI mask is applied (the mask runs at 1618-1660), so the scale factor is driven by pixels the user explicitly excluded - the corners of the bounding rectangle. (3) The rescaled values are then classified against the UNSCALED legend breaks and written to the persisted GeoTIFF with no flag; set_archtoolkit_layer_metadata stores only preset_key/preset_label/unit, so nothing on disk or in the project says the raster was stretched. As a bonus, `valid = out >= 0` means that for a custom CSV legend containing negative values only the non-negative half is rescaled, leaving a discontinuity at 0.
- 실패 시나리오: Fe2O3 preset, AOI whose true rendered range is 3.1-9.4% (no dark-red class present), user ticks 최댓값 보정 after reading the tooltip. cur_max = 9.4, target_max = 51.0, factor 5.43. A pixel whose colour honestly says 3.5% is written to the value raster as 19.0% and classified into class 10, whose label field reads '12-51%' - the 99-100th percentile of national Fe2O3. The polygon layer's val_mean for that class comes out around 25%. The user reports a severe iron anomaly across an area that the WMS shows as ordinary background, and nothing in the saved raster, the attribute table or the layer metadata records that a x5.43 stretch was applied.
- 제안 수정: Compute cur_max after the AOI mask; rewrite the tooltip to say plainly that this invents high values when the clip genuinely lacks them and should only be used when the user knows the rendering was re-stretched; and record fix_max (applied yes/no, cur_max, factor) in params_json and in the output layer name so the stretch travels with the raster.
  - 검증: certain: CONFIRMED - I could not refute it. All three sub-claims hold against the current file.

(1) The tooltip recommendation is genuinely inverted. The tool numericizes a fixed-legend RGB geochemical WMS (cmbRaster tooltip :832 "RGB 지구화학도 래스터/WMS 레이어"). Colours in such a map are absolute: clippin …
  - 검증: certain: REAL — all four sub-claims constructed and executed. Nothing edited.

SCENE (4x4 WMS tile over the AOI bounding rectangle, Fe2O3 preset, chkMaskAoi ON = default, chkFixMax ticked): the AOI polygon is the inner 2x2; the 12 border cells are bbox corners the user excluded. Inside-AOI colours ( …
  - 검증: certain: REAL, and the impact is worse than the finding states. Keep major.

What survives verification
1. Tooltip recommends the option for precisely the case where it fabricates data (868-872). Confirmed. The honest conclusion from "my clip contains no dark-red" is "this area has no high values"; …

#### [major] G9 — _import_preset_from_legend_image samples the lowest and highest legend anchors at image row 0 and row h-1, i.e. in the legend image's margin, silently assigning the border colour to the extreme values

- 위치: `/home/user/archtoolkit/tools/geochem_polygonize_dialog.py` :1086-1100 (sampling loop), 451-484 (_sample_qimage_rgb), 1016-1023 (the only disclosed assumption)
- 문제: The code hard-assumes that the colour bar occupies the full image height and that the supplied values are equally spaced along it. The dialog discloses only that the legend must be a vertical continuous ramp ('색상바가 위/아래로 변하는 연속 범례라고 가정합니다'); it never says the bar must start at row 0 and end at row h-1, and it never lets the user set a y range. Real legend graphics (GetLegendGraphic output, a cropped screenshot, a QGIS legend export) have a margin, a frame or a title, so the two extreme samples land on background. _sample_qimage_rgb averages a 3x3 window, which at y=0 just averages rows 0-1, still in the margin, and it reads pixels with QColor(image.pixel(...)) which discards alpha, so a transparent margin reads as opaque black. No preview of the sampled colours is shown and no sanity check (e.g. that consecutive samples differ) is run before the preset is registered and selected.
- 실패 시나리오: User exports the WMS legend as a 30 x 220 PNG with an 8 px white margin top and bottom, chooses 범례 이미지에서 샘플링, enters 11 values 0,3.1,...,51 and keeps 낮은 값이 아래. The 51 anchor is sampled at y=0 -> (255,255,255) and the 0 anchor at y=219 -> (255,255,255). The preset now claims white = 51%. Running it over the map, every pale pixel - paper background, label halo, the light end of the ramp - is projected onto the segment that ends at white/51, so large pale areas are reported at high Fe2O3, while the genuine top class (115,12,12) is no longer an endpoint of anything. The user gets a plausible-looking map that is inverted against a legend that was never in the image.
- 제안 수정: Ask for (or auto-detect) the colour bar's top and bottom y, and sample the i-th value at the centre of its band rather than at the image edge; for a classed legend sample swatch centres, not swatch boundaries. Show the sampled swatches back to the user for confirmation before registering the preset, and reject a preset whose consecutive sampled colours are identical or whose endpoints are pure white/black/transparent.
  - 검증: certain: CONFIRMED - I could not refute it. The finding is still live in the current file at HEAD 4886e0c (untouched by remediation; tree clean).

Every refutation avenue failed:
- No y-range guard. The function prompts for path, label, unit, values, direction and an x ratio (1062-1071). It asks for …
  - 검증: certain: REAL, and reproducible on demand. The mechanism is exactly as stated: `y = int(round(frac * float(h - 1)))` (:1097) forces the first and last anchors onto image rows 0 and h-1, and `_sample_qimage_rgb(..., radius=1)` at y=0 averages rows 0-1, so a margin of >=2 px puts both extreme samples …
  - 검증: certain: The defect is real and the impact is publication-grade, but the finding describes the failure backwards, and the correct failure is worse than the one it reports.

WHY IT MATTERS FOR A PUBLISHED RESULT. The output of this tool is a numeric Fe2O3/Pb/Cu/Zn raster plus zonal statistics per sit …

#### [major] G11 — Six of the seven shipped element presets use a colour ramp the code comments admit was assumed, and none of the break values is cited anywhere

- 위치: `/home/user/archtoolkit/tools/geochem_polygonize_dialog.py` :113-115 (the provenance comment), 128-200 (CU/ZN/SR/BA/CAO built the same way), 204-212 (PRESETS exposed as element names), 24 (module docstring); /home/user/archtoolkit/REFERENCES.md has no geochem entry
- 문제: The colour half of every preset except Fe2O3 is an assumption stated as such in the source ('We reuse the same base palette as other GeoChem layers (blue->red) to match the WMS styling') but presented in the UI as a ready-made preset named after the element. The value half (the percentile breaks) has no source at all: REFERENCES.md, which does cite KIGAM for the geology data (line 248-251), contains no geochem entry, and the module docstring says only that Fe2O3 is '사용자가 제공한 범례 포인트 기반'. The plugin ships no WMS URL, so the tool cannot verify the layer it is inverting against. If the actual service renders Pb with a different ramp - or renders the same ramp against different breaks - every ppm the tool emits is wrong, and the user has no way to find out because both halves are baked into a dropdown entry called 'Pb (납)'.
- 실패 시나리오: User selects 'Pb (납)', runs it on a Pb geochemical WMS whose service actually uses a yellow-to-purple ramp (or the same blue-to-red ramp against locally recomputed breaks). The inversion still returns a number for every pixel - per G1 there is no residual test - so the output looks perfectly normal: a value raster in ppm, class polygons with labels like '24-28ppm', zonal means. Every number is wrong by an arbitrary amount, and no message, no metadata field and no document records that the preset's colours were guessed.
- 제안 수정: Cite the source (service name, layer, legend graphic URL, date retrieved) for each preset in REFERENCES.md and in the preset's own tooltip; mark the presets whose palette was assumed rather than read from that layer's legend, and warn on run. Better: verify at run time by sampling the layer's GetLegendGraphic, or require the user to import the legend for that specific service, and expose the per-pixel colour-match residual (G1) so a mismatched ramp becomes visible.
  - 검증: likely: REFUTATION ATTEMPTS, ALL FAILED.

(1) "A guard prevents the mismatch." No. tools/geochem_legend.py:79-101 projects every pixel onto the nearest legend segment with no distance threshold: `mask = dist_sq < min_dist` then `out[mask] = base + t[mask]*delta`. `out` starts as NaN but every pixel …
  - 검증: certain: CONFIRMED — I can construct the failure concretely and I ran it.

The finding's two structural claims are verified fact, not inference. (a) I AST-extracted all seven preset point lists from the source and compared RGB sequences byte-for-byte: all seven are identical. Only the numeric breaks …
  - 검증: certain: CONFIRMED AND STILL LIVE. geochem_polygonize_dialog.py and geochem_legend.py are byte-identical to a7a6b31 and are not among the 19 remediation files; REFERENCES.md was edited (+21/-8) but still has no geochem entry. Every factual sub-claim holds.

The admission is real. tools/geochem_polyg …

#### [minor] G3 — Output-options help calls the inverted raster '원본 데이터' (original data) and recommends it for MaxEnt/statistics, contradicting the dialog's own '역추정' caveat

- 위치: `/home/user/archtoolkit/tools/geochem_polygonize_dialog.py` :709-713 (lblOutHelp), 700-706 (chkMakeClassRaster tooltip)
- 문제: The header label at line 429-431 and the help HTML at line 917 both say the value raster is an inverse estimate and not raw data ('원자료 수치가 아닌 역추정입니다'), and README.md:266 repeats that. The output-options panel - the one the user is reading at the moment they decide what to keep - says the opposite: the value raster is '원본 데이터' (original data), 'WMS 색상을 그대로 수치화한'. The class-raster tooltip then tells the user that the value raster alone is enough for MaxEnt, statistics and weighted centres. Combined with G1 and G2 this is the string that converts an artefact-prone inversion into a modelling input.
- 실패 시나리오: A user who opens the dialog, reads section 4, and never hovers the description label concludes the value GeoTIFF is the original geochemical measurement grid. They load fe2o3_value_<runid>.tif into a MaxEnt run as an environmental covariate and cite it in a paper as Fe2O3 concentration. A reviewer who checks the plugin's README finds the tool is an RGB inversion of a rendered WMS image, and the label the user relied on was wrong.
- 제안 수정: Replace the '원본 데이터' wording with the same caveat the dialog header uses, e.g. 'value 래스터는 WMS 렌더링 색상에서 역추정한 추정값입니다(원자료 아님).', and qualify the MaxEnt/statistics recommendation with the inversion's error sources.
  - 검증: likely: REFUTED. The finding's failure scenario rests on a factual error about where the caveat lives, and the quoted string is qualified in its own sentence.

1. The caveat is not hidden behind a hover. The finder's scenario says the user "never hovers the description label" and therefore never see …
  - 검증: certain: CONSTRUCTIBLE, but not the way the finding describes it, and not at "major".

What is real. The two strings exist verbatim and do contradict each other inside one dialog. L710 calls the value raster "WMS 색상을 그대로 수치화한 ‘원본 데이터’" (original data, numericised from the WMS colours as-is); L518 in …
  - 검증: certain: The contradiction is real and still present. lblOutHelp (:710) calls the value raster "원본 데이터" that "그대로 수치화한" the WMS color, while the same dialog's header label (:518) says "원자료 수치가 아닌 '역추정'입니다". "원본 데이터" is not something the code supports — :1495 runs an interpolated legend-space inversi …

#### [minor] G10 — _legend_points_from_csv truncates RGB with int(float(...)) and clamps to 0-255 with no validation, so a 0-1 normalised or mis-columned CSV silently produces an all-black legend - and an all-black legend maps every pixel to the maximum

- 위치: `/home/user/archtoolkit/tools/geochem_polygonize_dialog.py` :406-422 (parse + clamp), 933-948 (only check is len(points) >= 2)
- 문제: int(float(x)) truncates toward zero, so the very common 0.0-1.0 RGB convention (matplotlib, QGIS colour-ramp exports, R) collapses to 0 or 1. The subsequent max(0,min(255,...)) silently repairs out-of-range channels instead of rejecting the row, so a completely nonsensical colour table passes. Rows that fail to parse are dropped with log_swallowed only. The single acceptance test is that at least two points survived - there is no check that the colours are in a plausible range, that they are distinct, or that the columns were the expected ones. Nothing in the dialog states the required column order before the file chooser opens (only the error message mentions value,r,g,b). Combined with G1, a degenerate legend is not merely useless: because the top of the ramp is the attractor for dark colours, a near-black legend sends nearly every map pixel to the legend maximum.
- 실패 시나리오: User exports a colour ramp from a spreadsheet in normalised form: '0,0.80,0.80,0.80' / '3.1,0.00,0.15,0.45' / ... / '51,0.45,0.05,0.05'. Every channel truncates to 0 (0.80 -> 0, 0.45 -> 0), so all eleven legend points become (0,0,0) except the odd 1. The import succeeds and reports '사용자 프리셋을 추가했습니다'. The run then produces a value raster in which essentially every non-black map pixel projects onto the last surviving segment and is reported at or near the legend maximum, with no error and no warning - a full-AOI false anomaly.
- 제안 수정: Require integer channels in 0-255 and reject (with a message bar listing the offending row) anything outside it rather than clamping; detect the 0-1 convention (all channels <= 1.0 with a fractional part) and either scale by 255 or refuse with an explanatory message; verify that the imported points have at least two distinct colours and report how many rows were skipped. Show the parsed legend (value + swatch) for confirmation before adding the preset.
  - 검증: certain: The parsing facts are right, but the failure scenario - the only thing that makes this "major" - is provably false, in both variants of the finder's own CSV.

The inversion at tools/geochem_legend.py:74-76 skips any legend segment whose two endpoint colours are identical:

    v_len_sq = np …
  - 검증: certain: CONSTRUCTED — the core defect reproduces exactly; the headline consequence does not.

WHAT REPRODUCES (ran it, output pasted below).
Input: the finding's own CSV, an Fe2O3 ramp in 0-1 normalised form ("0,0.80,0.80,0.80" / "3.1,0.00,0.15,0.45" / ... / "51,0.45,0.05,0.05"). geochem_polygonize …
  - 검증: certain: MECHANISM IS REAL, STATED CONSEQUENCE IS NOT.

Verified real: line 409-412 does `v = float(row[0]); r = int(float(row[1]))...`, so a 0-1 normalised CSV truncates every channel to 0 or 1; lines 419-421 `r = max(0, min(255, r))` silently repair out-of-range channels instead of rejecting the r …

#### [minor] G12 — The AOI '선택 피처만 사용' tooltip promises a fallback to all features that the code does not implement, while the zone layer's identical option silently does fall back

- 위치: `/home/user/archtoolkit/tools/geochem_polygonize_dialog.py` :841-844 (AOI tooltip), 1316-1323 (AOI code), 2420-2427 (zone code)
- 문제: Two opposite behaviours behind two identically worded checkboxes, and the documented one is the one that is not implemented. For the AOI, checking the box with no selection aborts the run with '조사지역 피처가 없습니다' even though the tooltip says the whole layer will be used. For the zone layer, checking 구역 레이어 선택 피처만 사용 with no selection silently processes every feature in the layer - a silent widening of the analysis that no string mentions.
- 실패 시나리오: User loads a 시군구 boundary layer with 250 polygons as the zone layer, ticks '구역 레이어 선택 피처만 사용' intending to restrict the run to the three polygons they are about to select, forgets to select them, and runs. Instead of an error, the tool computes zonal statistics for all 250 polygons and adds a 250-row layer named <preset>_구역통계_<runid>; the user takes the first rows to be their three zones. Meanwhile the AOI checkbox in the same dialog, whose tooltip promises the opposite behaviour, refuses to run at all under the same conditions.
- 제안 수정: Make both consistent: if 'selected only' is ticked and nothing is selected, abort with a clear message naming which layer, for both the AOI and the zone layer, and fix the AOI tooltip to describe that. If a fallback is genuinely wanted, push a message-bar warning stating how many features were actually used.
  - 검증: certain: The finding survives. Its two load-bearing code claims are exactly true in the current file, and I could not find any guard, caller-side validation, QGIS API behaviour, tooltip, or help text that prevents or discloses either one.

The AOI half is the stronger, unambiguous part: line 843 is …
  - 검증: certain: REAL, and constructible end to end.

The failure: user enables 구역 통계, selects a 250-polygon 시군구 boundary layer in cmbZoneLayer, ticks 구역 레이어 선택 피처만 사용, but the map selection is empty (forgotten, or cleared by a map click between ticking and running). At :1290 zone_selected_only=True. At :17 …
  - 검증: certain: Both factual claims are true and reproduce exactly at the cited lines, so the finding is real. But the stated failure scenario overstates the consequence and must be corrected. The claim that "the user takes the first rows to be their three zones" does not survive the code: each output row …

#### [minor] G13 — Weighted-centre rule labelled '값 그대로 (w = value)' silently zeroes negative values while pix_n keeps counting them

- 위치: `/home/user/archtoolkit/tools/geochem_polygonize_dialog.py` :2159-2163 (default rule), 2134-2138 (power rule), 2185-2190 (pix_n), 2287-2288 (pix_n written to the layer)
- 문제: The combo entries read '값 그대로 (w = value)' and '값 거듭제곱 (w = value^p)', but both clamp negatives to zero before weighting. For the shipped presets all values are non-negative so nothing happens; for a user-imported CSV legend with negative values (isotope deltas, magnetic anomalies, standardised indices - all legitimate for a colour-ramped map) every negative pixel contributes zero weight, so the 'centre of mass' is computed over the positive half of the AOI only. pix_n, which is the field a reader uses to see how much data went into the point, still counts the full selection, so the attribute table says the centre was computed from N pixels when only a subset contributed.
- 실패 시나리오: User imports a CSV legend running -8 to +8 for a normalised geochemical index and runs 가중 평균 중심 with the default '값 그대로' rule over an AOI whose western half is negative. Every western pixel gets weight 0, so the point lands in the eastern half; the feature's pix_n reports the full AOI pixel count and w_rule reports 'value', giving no hint that half the data was discarded. The same AOI with the whole ramp shifted up by a constant would put the point somewhere else entirely.
- 제안 수정: Either rename the rules to state the clamp ('w = max(value, 0)') and set pix_n to the count of pixels with non-zero weight, or offer an explicit shift (w = value - vmin) for legends with negative values and warn when the selected legend has any negative break.
  - 검증: likely: CONFIRMED but only at minor severity; one sub-claim is refuted.

Code fact (certain): tools/geochem_polygonize_dialog.py:2161-2162 (default rule) and :2137 (power rule) apply `np.maximum(v[sel].astype(np.float64, copy=False), 0.0)` before weighting, while the combo entries at :764-765 read e …
  - 검증: certain: REAL, and I can construct it concretely. Not a correctness bug - a labelling/provenance one - so minor is the right rank.

REACHABILITY (the part most likely to kill a finding like this, and it survives): negative values are genuinely producible. _legend_points_from_csv (line 410) does `v = …
  - 검증: certain: The finding is factually accurate — the code, the UI strings, the pix_n divergence and the reachability via CSV import all check out, and I reproduced the numeric displacement. But I am confirming the original "minor" grade rather than raising it, for three reasons.

1. It cannot be trigger …

#### [minor] G14 — Preset combo tooltip and module docstring still claim Fe2O3 is the only preset while seven ship

- 위치: `/home/user/archtoolkit/tools/geochem_polygonize_dialog.py` :845-849 (tooltip), 24 (module docstring)
- 문제: PRESETS (lines 204-212) registers fe2o3, pb, cu, zn, sr, ba and cao, and all seven appear in the dropdown (lines 543-545). Both the tooltip the user hovers and the module docstring a maintainer reads still describe the single-preset state. The staleness matters beyond tidiness here: the docstring is the only place in the file that records where a preset's legend came from ('사용자가 제공한 범례 포인트 기반'), so it silently attributes the same provenance to six presets whose palette was in fact assumed (see G11).
- 실패 시나리오: A user hovers the 프리셋 combo, reads that only Fe2O3 is supported, and then sees six more element names in the list. They reasonably conclude the extra presets are as well-founded as the documented one and pick 'Zn (아연)', which carries an assumed palette and uncited breaks. A maintainer reading the module docstring makes the same inference.
- 제안 수정: Update both strings to list the shipped presets and to state, per preset, whether its colour ramp was read from that service's legend or assumed, pointing at the REFERENCES.md entry added for G11.
  - 검증: certain: Could not refute the core claim. Both strings are verifiably stale in the current file: tools/geochem_polygonize_dialog.py:847 tells the user "현재는 Fe2O3(산화철)만 제공됩니다" while lines 557-558 populate that very combo from all seven PRESETS entries (204-212), and docstring line 24 records the same …
  - 검증: certain: REAL, with one wording correction.

The failure is constructible and needs no special raster values, CRS, or parameters — it is a pure user-facing-string defect on a path every user of the tool walks.

Concrete trace: user opens the GeoChem 지구화학도 dialog with any RGB raster and any AOI polyg …
  - 검증: certain: The factual core is real and still present: the tooltip at 845-849 flatly states only Fe2O3 is provided while the combo at 557-558 is populated from all seven entries of PRESETS (204-212), and the module docstring at line 24 records the same single-preset state. A user hovering the combo re …

### spatial-network


#### [major] SN-01 — LOS has no NaN guard: a site on a NaN DEM cell is reported visible to every other site

- 위치: `tools/spatial_network_dialog.py` :1865-1890
- 문제: QgsRasterDataProvider.sample() only sets ok=False when the band declares a NoData value that the pixel matches. For a Float32 DEM that carries NaN pixels but no declared NoData value (routine output of interpolation/merge/warp chains, including this plugin's own DEM generation), sample() returns (nan, True). _los_visible never tests for NaN. Two distinct consequences follow from IEEE comparison semantics, both verified: an intermediate NaN sample gives `nan > sight` == False, so the hole is treated as clear ground; and a NaN at either endpoint makes obs_elev or tgt_elev NaN, hence `sight` NaN, hence `z > sight` False for every single sample, so the function returns True unconditionally. The plugin's own single-pair LOS in tools/viewshed_dialog.py:3117 does guard this (`if math.isnan(elev_value): continue`), so the omission here is an inconsistency inside the same plugin, not a house convention.
- 실패 시나리오: A 5 m DEM mosaicked from two tiles leaves NaN in the seam and the metadata carries no NoData value. Site A sits on a seam cell. The user runs the visibility network with the default settings (all pairs within 2500 m). _los_visible(A, *) returns True for every partner because sight is NaN: the edge layer marks every A-pair '상호 보임', the LOS_Nodes layer gives A the maximum degree/out_deg/in_deg in the dataset and the highest closeness and betweenness of any node, and the completion message counts those as mutually visible pairs. A is published as the central watch station of the network purely because its elevation cell is NaN.
- 제안 수정: After each float() conversion in _los_visible (endpoints at 1870-1871 and the loop sample at 1883), reject non-finite values: treat a NaN endpoint as `return None` (sample failure, same as ok==False) and a NaN intermediate sample as `return None` as well, matching viewshed_dialog.py:3117 rather than silently treating the hole as transparent. Add a regression test that feeds a profile containing NaN and asserts the pair is reported as a sample failure, not as visible.
  - 검증: certain: I could not refute the core of this finding, and the one API-level escape hatch I expected to save it turned out to confirm it instead.

The mechanism holds. `_los_visible` at tools/spatial_network_dialog.py:1829-1888 never tests for NaN, and nothing upstream does either - `grep` for isnan/ …
  - 검증: certain: CONSTRUCTED AND EXECUTED — the finding is real.

Exact trigger: a Float32 DEM in a metric CRS (e.g. EPSG:5186) whose band carries NaN pixels and NO declared NoData value — e.g. a mosaic/derivative written by numpy/rasterio or gdal_calc.py, or a DEM that went through `gdal_translate -a_nodat …
  - 검증: certain: REAL, and it matters for publication — but the severity is major, not blocker.

Why it is real and not cosmetic. The endpoint half of this finding is airtight and I verified every link. If a site's cell is NaN, `sight` is NaN for every sample, `z > nan` is False for every z (executed), so _ …

#### [major] SN-02 — Visibility network uses a flat-earth sight line: no curvature or refraction, not disclosed, and contradicted by the plugin's own viewshed and by REFERENCES.md

- 위치: `tools/spatial_network_dialog.py` :1887
- 문제: The sight line is a straight chord in a plane; no term of the form cc*d^2/(2R) is applied anywhere in _los_visible, and neither the visibility tooltip (255-265), the help HTML (211-235), the interpretation guide (630-760) nor the .ui tooltips mention earth curvature. Two things make this an over-claim rather than a disclosed approximation. First, the same plugin's viewshed tool defaults curvature AND refraction ON (tools/viewshed_dialog_base.ui:327-346, both checked=true, k=0.13), implements them as `elev_value -= cc * dist*dist / (2*earth_r)` (viewshed_dialog.py:3157-3160) and warns the user above 1 km that '곡률/굴절 보정 체크박스가 가시선 판정에 반영됩니다' (viewshed_dialog.py:3120-3121). Second, REFERENCES.md:166 tells the reader the visibility network's '구현은 가시권 분석과 네트워크 지표의 조합' - the implementation is the viewshed analysis combined with network metrics - which is exactly what it is not. Algebraically, applying the standard correction lowers terrain by f^2*D^2/(2R) and the sight line by f*D^2/(2R), so the flat model over-states mid-path clearance by f(1-f)*D^2/(2R), i.e. up to D^2/(8R): 1.96 m at 10 …
- 실패 시나리오: Two beacon (봉수) sites 25 km apart on 400 m peaks, observer height 1.6 m, target height 0; the intervening ridge at mid-path tops out at 398 m, clearing the flat chord by ~10 m. This tool reports '상호 보임', counts the pair in mutual_edges, and both nodes gain degree and centrality. Running the plugin's own 가시선 (LOS) tool on the same two points with its default curvature+refraction subtracts 10.7 m of apparent drop at the midpoint and reports the target as obstructed. The user publishes an intervisibility network that the plugin's own second tool contradicts, and a reviewer checking against GRASS r.viewshed (curvature on by default) or gdal_viewshed -cc 1 gets the obstructed answer.
- 제안 수정: Either apply the correction - subtract cc*(frac*total_dist)^2/(2*6371000.0) from each sampled z in _los_visible, with cc plumbed from a curvature/refraction control mirroring viewshed_dialog._calculate_gdal_viewshed_cc - or, if it is deliberately omitted for speed, say so in the visibility tooltip, the interpretation guide and REFERENCES.md, state the flat-earth assumption and its magnitude (~d^2/2R), and remove the REFERENCES claim that the implementation is the viewshed analysis. The former is preferable: the cost is one subtraction per sample.
  - 검증: certain: CONFIRMED — I could not refute it. The sight line at tools/spatial_network_dialog.py:1887 is a straight chord and no term of the form cc*d^2/(2R) exists anywhere in the module (grep for 곡률/curvature/굴절/refract/6371/earth_r returns zero hits in both the .py and the .ui). There is no earlier …
  - 검증: certain: CONSTRUCTED AND REPRODUCED. Inputs: projected CRS in metres, 5 m DEM, two nodes 25,000 m apart on 400 m peaks, observer height 1.6 m, target height 0, sample step 0 (auto), spinMaxDist raised to 25000 (spinbox max is 100,000,000 m), intervening ridge cresting at 398 m at mid-path. Trace: li …
  - 검증: certain: Every code fact in the finding is true in the CURRENT file, which the remediation run did not touch. The sight line at line 1887 is a straight chord with no cc*d^2/(2R) term, and no user-facing string anywhere in the tool, its .ui, its help, its guide, or the README discloses the flat-earth …

#### [major] SN-03 — LOS sampling is silently capped at 2000 points, so long sight lines are sampled far coarser than the requested step and the DEM

- 위치: `tools/spatial_network_dialog.py` :1858-1859
- 문제: `step` is honestly clamped up to the DEM pixel size (1850-1855) and the tooltips disclose exactly that ('0 또는 너무 작으면 DEM 픽셀 크기를 기준으로 자동 보정됩니다', line 588-591; '0이면 DEM 해상도 기반 자동(최소 5m)' in the .ui). But `step` is then thrown away: beyond total_dist > 2000*step the effective spacing becomes total_dist/2000, coarser than both the value the user typed and the DEM resolution, with no message, no log line and no record in the output. Nothing in the UI, the help HTML or the interpretation guide mentions a 2000-sample ceiling. The sibling implementation in viewshed_dialog.py:3138 caps at 5000 with a floor of 200, so the network tool is quietly the coarser of the two.
- 실패 시나리오: 1 m LiDAR DEM (국토지리정보원 1 m product), user sets 샘플 간격 = 1 m believing the ridge line will be sampled at DEM resolution, max distance 15 km, two hilltop sites 12 km apart. Requested 12000 samples, actual 2000, effective spacing 6.0 m. I swept a 5 m wide, 8 m high blocking crest across 200 m of the mid-path at 0.1 m increments: at the true 1 m sampling the pair is blocked at every one of the 2000 positions, while the shipped code reports '상호 보임' at 314 of them (16%). So roughly one in six narrow blocking crests - an earthen rampart, a rock crest, a bund - is stepped over, and the pair enters the edge layer as mutually visible, the node layer as degree+1, and the summary as a mutual edge.
- 제안 수정: Do not silently discard the requested step. Either raise/remove the cap and let the progress dialog and the existing >=5000-pair confirmation carry the runtime cost, or keep a ceiling but recompute and report it: when num_samples is clamped, compute effective_step = total_dist/num_samples, and if effective_step > step surface it once per run through push_message and log_message ('요청 간격 1.0 m, 실제 적용 6.0 m') and record effective_step in the edge layer metadata. Add a unit test on the sampling geometry alone (it needs no QGIS) asserting that the spacing actually used never exceeds the requested step.
  - 검증: certain: Could not refute. Every candidate escape was checked and none exists.

(1) No guard earlier in the function: lines 1844-1859 contain only `if total_dist <= 0: return True` and the step FLOOR (`step = max(pix, step)`); `num_samples = max(80, min(num_samples, 2000))` at 1859 is the last word, …
  - 검증: certain: REAL, and I can construct it concretely - but the finding's own failure scenario is physically under-specified and I had to re-stage it before it would block.

What is solid. The code at 1858-1859 is exactly as quoted and still present in the current file (spatial_network_dialog.py is not a …
  - 검증: certain: CONFIRMED, and major is the right grade. Keep it.

The cap is real, silent, and in the current file. Nothing in the UI, help HTML, tooltips, message bar, log or output metadata mentions a 2000-sample ceiling, and I reproduced the finding's headline number independently (15.2% vs the claimed …

#### [major] SN-04 — Delaunay/Gabriel/RNG silently drop every duplicate-coordinate node, publishing it as an isolated site

- 위치: `tools/spatial_network_dialog.py` :1544-1547
- 문제: The coordinate->index map is keyed on the position rounded to the millimetre, and the assignment overwrites. Two nodes at the same coordinate (or within 1 mm) collapse to one key holding only the higher index, and _idx_for_xy (1551-1564) therefore returns that one index for both. Every triangle edge recovered from the triangulation references the surviving index; the shadowed node appears in no edge at all. It then flows straight into the outputs: _degrees gives it 0, _components gives it its own component, closeness and betweenness give it 0.0. The k-NN and threshold builders (1279-1327) have no such behaviour - they connect duplicates at distance 0 - so the same dataset silently changes meaning depending on which graph rule is chosen. The only duplicate-related message in the code (1345, 'Delaunay 기반 간선을 만들 수 없습니다. (점이 너무 적거나 중복일 수 있음)') fires only when the candidate set is completely empty, which is not this case.
- 실패 시나리오: A site layer of 40 records where two features - say a 주거지 record and a 저장공 record of the same site complex, or a straightforward duplicated row - carry identical coordinates. The user picks Delaunay (or Gabriel/RNG). The triangulation sees 39 distinct vertices; the lower-index duplicate is matched by no triangle. Output: PPA_Nodes shows that site with degree 0 and comp_size 1, the completion message at 1407-1409 reports one more component than exists and a mean degree diluted by the phantom isolate, and the report states that this site is unconnected to the local proximity network when in fact it is co-located with a well-connected one. No warning is issued anywhere.
- 제안 수정: Detect the collision where the map is built: if a key is already present, either merge the duplicates into one node up front (deduplicating in _collect_nodes and recording how many features were merged) or keep a list per key and emit every matching index so duplicates inherit the same edges. Either way, report the count through push_message/log_message - 'N개 노드가 좌표 중복으로 병합되었습니다' - rather than letting a node vanish from the graph.
  - 검증: certain: Could not refute; every candidate defence fails on the actual code.

MECHANISM CONFIRMED. At 1543-1546 (finding said 1544-1547; quoted code matches exactly) the coord->index map is built with `lookup[key] = int(i)`, which overwrites, so for coincident coordinates only the HIGHEST index surv …
  - 검증: certain: CONSTRUCTED AND RUN. The failure is concrete and deterministic.

Exact trigger: a point (or polygon) site layer in a metric CRS such as EPSG:5186 — required, because `_ensure_metric` at 1166 rejects geographic CRS for PPA — containing two features with identical coordinates. This is ordinar …
  - 검증: certain: Confirmed real, and I am holding it at major rather than downgrading.

The mechanism is deterministic, not speculative. Because PPA collects nodes in the layer's own CRS with no transform (:1177), two features carrying the same stored coordinate produce bit-identical doubles, hence the same …

#### [major] SN-05 — vis_ratio_ab measures the observer polygon's boundary, but the guide says it shows how much of the target is visible

- 위치: `tools/spatial_network_dialog.py` :647
- 문제: _ratio_for_samples (1986-2012) iterates over the OBSERVER polygon's boundary samples and tests each one against a single target coordinate - nodes[b].x, nodes[b].y, i.e. b's centroid/point-on-surface, never b's boundary. So r_ab is 'the fraction of A's perimeter from which B's representative point can be seen'. The English guide at 647 states the opposite ('how much of a target is visible') and the Korean guide at 724 says '얼마나 보이는가', which reads the same way. Two further undisclosed conversions ride on top: vis_ab is set true if even one boundary sample sees the target (2048), which is the rule that then drives the edge status, the node degree and all centrality; and _ratio_for_samples drops failed samples from its denominator (2007-2012), so a ratio of 1.00 can rest on a single valid sample out of 30. The checkbox is checked by default in the .ui, so polygon users get this path without asking for it.
- 실패 시나리오: Site A is a 20 m mound, site B a 500 m long hillfort whose point-on-surface lands behind its own rampart. Every one of A's 30 boundary samples fails to see that one point, so vis_ratio_ab = 0.0, vis_ab = 0, the edge is coloured '상호 안보임' and both nodes lose a degree - for two sites that are plainly intervisible across most of B's enclosure. Reverse the geometry and the error reverses: vis_ratio_ab = 1.00 is published as 'B is 100% visible from A' when the only part of B ever tested was one interior point.
- 제안 수정: Fix the wording first: both guides should read 'the share of THIS site's boundary from which the other site's representative point is visible', and the same sentence belongs in the chkPolyBoundaryVis tooltip. Then decide the semantics deliberately - if the intent really is 'how much of the target is visible', sample the TARGET's boundary points as targets (nodes[b].samples) rather than its single representative point, which is also what makes vis_ratio_ab and vis_ratio_ba genuinely complementary. Also state the any-sample rule that turns the ratio into vis_ab, and either exclude pairs whose samples mostly failed or export the valid-sample count alongside the ratio.
  - 검증: certain: I could not refute this. Every refutation angle failed against the current file (HEAD 4886e0c; this file is NOT among the 19 under concurrent remediation, so no re-check is needed).

1. THE ASYMMETRY IS TOTAL, NOT AN OVERSIGHT IN THE FINDER'S READING. `grep -n "\.samples"` over the whole fi …
  - 검증: certain: CONFIRMED, and I was able to construct the exact failure the finding describes plus the second one it alleges.

The semantic claim is straightforwardly true from the code. `_ratio_for_samples` (spatial_network_dialog.py:1987-2014) takes a tuple of observer coordinates and a single scalar ta …
  - 검증: certain: REAL, and major stands.

The mismatch is exactly as described. vis_ratio_ab is "the share of A's perimeter samples from which B's single representative point is visible". The guide says it is "how much of a target is visible". Those are different quantities that share the same [0,1] range a …

#### [major] SN-06 — A failed LOS sample (NoData) is written into the node layer as 'not visible', so untested sites are published as isolated

- 위치: `tools/spatial_network_dialog.py` :2103-2104, 2213-2226
- 문제: _los_visible returns None for a sample failure - NoData anywhere along the ray (1880-1881) or at either endpoint (1867-1868). The edge layer is honest about it: status/status_ab/status_ba carry '샘플 실패' and get their own grey dotted category (2357), and the completion message counts failures. The node layer is not: None is flattened to 0 in the extras dict, and every downstream node number reads that 0 as a tested negative. out_deg, in_deg, vis_total, degree, component, comp_size, closeness and betweenness therefore cannot distinguish 'we looked and it was hidden' from 'we could not look'. The LOS_Nodes layer carries no failure count field at all, and the interpretation guide (743-748) presents degree/component as the evidence for isolation.
- 실패 시나리오: A coastal or island survey (precisely Terrell's PPA setting, cited at 250 and 319) on a DEM where the sea is NoData. Every inter-island sight line hits a sea cell, so _los_visible returns None at the first sea sample and the pair is '샘플 실패'. In LOS_Nodes every island site gets degree 0, out_deg 0, in_deg 0, vis_total 0, closeness 0.0, its own single-member component - identical output to a site that was tested and genuinely sees nothing. Symbolise that layer for a figure and the caption reads 'the island sites form isolated components', when in fact not one of those sight lines was ever evaluated.
- 제안 수정: Carry the failures into the node layer: add fail_deg (or tested_deg alongside vis_total) computed from the '샘플 실패' statuses in extra_by_edge, and if any node's tested pairs are majority-failed, flag it in the layer and in the completion message. Minimally, when failed_pairs > 0 push a message naming how many nodes have at least one untested pair, and add a line to the interpretation guide stating that degree 0 in the LOS node layer can mean untested rather than not visible.
  - 검증: certain: The finding survives every refutation angle. I could not find a guard, a validating caller, a QGIS API behaviour, or a tooltip/comment that prevents or discloses the claimed flattening.

The mechanism is exactly as described and the two load-bearing line ranges are exact. _los_visible retur …
  - 검증: certain: CONFIRMED, and I can construct it precisely.

TRIGGER, stated exactly: any DEM clipped to a non-rectangular boundary — a coastline, a catchment, a survey-area polygon, an administrative unit. Clipping leaves a NoData collar inside the raster's rectangular extent. `QgsRasterDataProvider.samp …
  - 검증: certain: Confirmed as described, with the severity left at major.

The code path is exactly as the finding states and I could not find any mitigation in the node layer. A pair whose LOS could not be evaluated is written into LOS_Nodes as a tested negative: vis_ab/vis_ba 0, no edge in edges_for_metri …

#### [major] SN-08 — The metric-CRS check passes Web Mercator, so dist_km and every distance threshold are inflated ~26% at Korean latitudes

- 위치: `tools/spatial_network_dialog.py` :1134-1145
- 문제: is_metric_crs only asks whether the CRS is projected with metre map units. EPSG:3857 satisfies both, and it is a very common working/project CRS once a web basemap is loaded. All distances in this tool are planar hypot in the layer's CRS (edge attributes at 2310-2312, the threshold radius at 1310-1319, the PPA max-dist filter at 1477-1481, the LOS max_dist at 1922-1925 and the candidate-k ranking at 2145-2153), and Web Mercator's scale factor is 1/cos(phi) - 1.260 at 37.5N. The tool's only CRS feedback is the message implying the CRS was checked and accepted for distance work, and neither the guide nor the README flags the projected-distortion case; no other tool in this plugin guards it either (no occurrence of 3857 in tools/ or README.md).
- 실패 시나리오: Site layer reprojected to EPSG:3857 for map display, PPA with Distance threshold = 2500 m at latitude 37.5N. The radius actually applied on the ground is 2500 x cos(37.5) = 1983 m, so real neighbour pairs 2.0-2.5 km apart are excluded from the graph; and every surviving edge's dist_km attribute - the number that gets tabulated in the report - is 26% too large (a true 2.0 km link is published as 2.52 km).
- 제안 수정: In _ensure_metric, additionally warn (do not block) when the CRS is a Mercator/pseudo-Mercator or otherwise strongly distorting projection at the data's latitude - EPSG:3857 is worth naming explicitly - recommending a local metric CRS such as the Korea 2000 belts. Recording the CRS authid in the layer metadata alongside the distances would also let a reader catch it after the fact.
  - 검증: certain: Could not refute; every claimed mechanism verifies in the current file. All four refutation routes fail: (1) no earlier guard — _ensure_metric at :1134-1145 is the entire CRS gate and is_metric_crs (utils.py:324-329) returns True for EPSG:3857 since it is projected with DistanceMeters map u …
  - 검증: certain: CONFIRMED - the failure is fully constructible and still present in the current file (tools/spatial_network_dialog.py is not one of the 19 remediated files; last touched at 255d459, HEAD is 4886e0c).

EXACT INPUTS: a point site layer stored in EPSG:3857 (e.g. sites digitised from or exporte …
  - 검증: certain: REAL, and under-graded at "minor". Every factual claim verified; the arithmetic is exact.

Why it is more than minor — three separate published outputs are wrong, not one:

1. A number in the report. dist_km (:2343) is inflated 26% at 37.5N. The finding says this "gets tabulated"; it is wor …

#### [minor] SN-07 — betweenness is raw Brandes pair counts, but nothing user-facing says so

- 위치: `tools/spatial_network_dialog.py` :1826-1827
- 문제: The field is named plainly 'betweenness' (1697), carries no alias and no units, and the interpretation guide describes it only qualitatively - '다른 노드 사이를 중개하는 정도' / 'how strongly a node acts as a bridge' (748, 668). The value is the raw number of shortest-path pair-dependencies, halved for undirectedness; it is not divided by (n-1)(n-2)/2. The neighbouring closeness field IS explicitly documented as Wasserman-Faust corrected in both guides, which invites the reader to assume betweenness is likewise on a comparable 0-1 scale. It is not, and the value is not comparable between two runs with different node counts.
- 실패 시나리오: A 30-node PPA network yields betweenness 128.0 for the hub site; the author tabulates it next to closeness 0.62 and reports both as centrality scores. A reviewer reproduces the same edge list in NetworkX with nx.betweenness_centrality (normalized=True by default) or in Gephi and gets 0.315 - a factor of 406, i.e. 2/((n-1)(n-2)) - and reports that the plugin's centrality figures cannot be reproduced. A second study area with 60 nodes gives raw values four times larger for structurally identical positions, so the two areas cannot be compared as the table implies.
- 제안 수정: State the scale where the user sees it: rename the field betweenness_raw, or add a field alias and a line in both interpretation guides saying 'raw pair counts, undirected (x0.5), not normalised by (n-1)(n-2)/2 - divide by that to compare with NetworkX/Gephi defaults or across networks of different size'. Optionally emit both columns. REFERENCES.md:142-143 already documents the 0.5 convention; the dialog should not be less explicit than the bibliography.
  - 검증: likely: Refuted — the facts are all true, but they do not add up to a finding under this audit's own bar ("would make that number wrong, or make a reviewer able to say 'your tool does not do what you said it does'").

1. The number is not wrong. Brandes (2001), the source REFERENCES.md:142-143 cites …
  - 검증: likely: CONSTRUCTIBLE — yes, and I ran it. The mechanism in the finding is exactly right and verified against the shipping code.

What is genuinely wrong: the layer emits a bare Double column literally named `betweenness`, sitting immediately beside a `closeness` column that both help guides explici …
  - 검증: certain: FACTS: all confirmed. network_metrics.py:153-188 is textbook Brandes; the only post-processing is bc[i] *= 0.5 (185-187). There is no division by (n-1)(n-2)/2. The field is created bare as QgsField("betweenness", QVariant.Double) at :1721, both interpretation guides describe it purely quali …

#### [minor] SN-09 — No LOS run parameter is recorded in the layer name or layer metadata, so a saved visibility network cannot be reproduced or told apart from another run

- 위치: `tools/spatial_network_dialog.py` :1807-1813, 2194, 2377-2392
- 문제: Every value that determines the result - observer height, target height, sampling step (and the effective step after the 2000 cap, SN-03), max distance, candidate k versus all-pairs, the mutual/either edge rule, and whether polygon boundary sampling was on - is absent from the output. The edge layer is always called Visibility_LOS and its metadata records only cosmetic flags; the node layer's metadata records only its title. The PPA branch is better (the method, k, mutual flag and max distance are baked into the layer name at 1300, 1324, 1352-1361) but its node layer is equally bare. The sibling least-cost network tool does record its run parameters (cost_network_dialog.py:2670-2675 passes network_mode/cost_mode/model_label), and the plugin's changelog advertises parameter recording as a reliability feature, so this tool is the outlier.
- 실패 시나리오: An analyst runs the visibility network three times - observer 1.6 m, then 3 m for a watchtower, then 10 m for a beacon platform - and saves the project. Three groups appear, each containing a layer named Visibility_LOS, with nothing in the name, the attribute table or the metadata distinguishing them. Six months later, at the point of writing the excavation report, neither the analyst nor a reviewer can say which figure used which observer height, and the run cannot be reproduced.
- 제안 수정: Pass the real parameters into set_archtoolkit_layer_metadata for both the LOS edge layer and both node layers (obs_height, tgt_height, sample_step_m requested and effective, max_dist, candidate_k or all_pairs, vis_edge_rule, poly_boundary and its step/max points), and put at least the observer height and max distance into the layer name as the PPA branch already does.
  - 검증: likely: I could not refute the core. Verified in the current file:

- tools/spatial_network_dialog.py:2195 `layer_name="Visibility_LOS"` is a bare literal, identical for every LOS run.
- :2423-2432 the edge layer's params_json is `{"layer_name":..., "add_dist":..., "has_status":..., "has_ratio":...} …
  - 검증: certain: REAL, and I can construct it concretely — but the failure scenario as written overstates one detail and understates a sharper one.

THE CONSTRUCTION. Input: a point layer of 5 sites in EPSG:5186 (Korea 2000 Central Belt), a 5 m DEM in the same CRS, 노드 지표 생성 / Closeness / Betweenness all che …
  - 검증: certain: The code facts are exactly as stated and still present in the current file. Every LOS run produces a layer literally named "Visibility_LOS" inside a group named "Visibility_LOS_<6 random hex>"; the edge layer's params_json holds four cosmetic flags (layer_name, add_dist, has_status, has_rat …

#### [minor] SN-10 — Degree legend produces an inverted final class label when every node has the same degree

- 위치: `tools/spatial_network_dialog.py` :1766-1781
- 문제: When vmin == vmax (every node has the same degree), the guard `max(1.0, ...)` forces step = 1.0 while hi for the last class is pinned to vmax. The five ranges become [v, v+1], [v+1, v+2], [v+2, v+3], [v+3, v+4], [v+4, v] - the last one inverted, with the label printing its bounds in descending order. The renderer is built and applied regardless (1782-1783), so the legend that goes into an exported map shows a class that cannot contain anything and reads backwards.
- 실패 시나리오: Four sites, k-NN with k=3 and mutual only: the graph is K4 and every node has degree 3. vmin = vmax = 3, so the node layer's legend reads '3–4', '4–5', '5–6', '6–7', '7–3'. The same happens for any regular graph - a chain of riverside sites where a threshold radius gives every node exactly 2 neighbours. The figure is exported into the report with a nonsense final legend entry.
- 제안 수정: Handle the degenerate case explicitly: if vmax == vmin, fall back to the single-symbol renderer already used for vmax <= 0 (1763-1765), or build one class labelled with that single value. Otherwise clamp hi so it is never below lo.
  - 검증: certain: CONFIRMED — I could not refute it, and the defect is in fact broader than the finding claims.

Refutation attempts, all of which failed:

1. Earlier guard: the only guard is `if vmax <= 0` (1760), which covers the zero-edge case alone. Nothing constrains vmax relative to vmin.
2. Caller val …
  - 검증: certain: CONSTRUCTED AND REPRODUCED. The finding is real; its arithmetic is exactly right, and the bug is in fact broader than the finding states.

Code path, no branches skipped:
1. User opens Spatial Network, PPA tab, picks 4 site points, graph = k-NN, k = 3, "mutual only" checked, and ticks the n …
  - 검증: certain: REAL — mechanism confirmed exactly as described, and the code is unchanged from the audited commit.

But the finding is MIS-SCOPED in a way that matters, and I'd correct it in the opposite direction from the usual: it is far more reachable than stated. The title says "when every node has th …

#### [minor] SN-11 — Turner et al. (2001) VGA is cited as a reference for a site-to-site intervisibility network, which is a different method

- 위치: `tools/spatial_network_dialog.py` :255-265
- 문제: Turner, Doxa, O'Sullivan & Penn (2001) define visibility graph analysis over a dense grid of locations filling a space, with every mutually visible pair of grid points an edge, and derive measures such as visual integration and mean depth from that grid graph. This tool builds a graph whose nodes are the handful of input site features and whose edges are pairwise DEM line-of-sight tests, then reports degree, components, closeness and betweenness. The tooltip lists Turner under a bare 'Ref:' heading with no marker separating an implemented method from background context, and REFERENCES.md:164 goes further by titling the section '가시성 네트워크 (Visibility / Intervisibility Network, VGA)'. Van Dyke et al. (2016) and Gillings & Wheatley (2001) are apt; VGA is not what this computes. The same bare-'Ref:' pattern at 249-252 lists Amati, Shafie & Brandes (2018), a structural-holes network-reconstruction paper, under the PPA proximity graphs (Terrell 1977 there is correct - PPA does link each point to its k nearest neighbours, and the default k=3 matches).
- 실패 시나리오: A user reads the tooltip, writes 'visibility graph analysis (Turner et al. 2001)' into the methods section, and submits. A reviewer who knows VGA asks for visual integration values over the analysis grid and points out that a 40-node intervisibility graph between sites is not VGA, that its centrality values are not VGA measures, and that the citation misrepresents the method - the exact 'your tool does not do what you said it does' objection.
- 제안 수정: Adopt the (A)/(C) implemented-versus-context convention REFERENCES.md already uses elsewhere inside these tooltips, and either drop Turner et al. or label it explicitly as conceptual background for visibility graphs in general, noting that this tool computes site-level intervisibility rather than grid-based VGA. Retitle the REFERENCES.md section to drop 'VGA'. (REFERENCES.md is in the concurrently-edited set - re-check its current wording before acting.)
  - 검증: likely: The finding's central piece of evidence is wrong for the current file. It asserts REFERENCES.md "goes further by titling the section ... VGA", but REFERENCES.md:170-177 now reads: heading, then immediately `**(C) 고고학적 해석 맥락 (구현은 가시권 분석과 네트워크 지표의 조합):**` above all three visibility refs includ …
  - 검증: likely: REAL, at the filed severity of minor - not upgradeable, not dismissable.

The factual core checks out and is still live in the current file. The tool builds a graph whose nodes are the input site features (one `_Node` per feature, line 1040) and whose edges are pairwise straight-line DEM sig …
  - 검증: certain: REAL, but the impact is narrower than the write-up implies, and "minor" is the ceiling.

What is genuinely wrong: one word. REFERENCES.md:170 titles the section "가시성 네트워크 (Visibility / Intervisibility Network, VGA)" for a tool that does site-to-site DEM line-of-sight (verified at :1829-1887 …

### trench


#### [major] F-TR-01 — Grave avoidance fails open on a null union while the UI reports "N graves avoided"

- 위치: `tools/trench_suggestion_dialog.py` :830-841, 1338-1346, 1155, 1601, 1560
- 문제: `count` is the number of MATCHED features, but the avoidance test is driven by `union`. The guard is `if grave_union is not None` - it never checks `isNull()`/`isEmpty()`. QgsGeometry.unaryUnion does not raise on GEOS failure: it returns a null QgsGeometry and records the error in `mLastError`, so the `except Exception` fallback to `combine()` is never entered. Likewise `QgsGeometry.buffer()` (line 825) returns a null geometry on GEOS failure without raising, and line 828 appends that null geometry unconditionally, poisoning the union and still incrementing `count`. QgsGeometry::intersects() short-circuits to `false` when either operand is null. So the avoidance silently does nothing while `grave_count` (> 0) is reported three times as a success: the live log at line 1155, the message bar at line 1601, and `grave_matched_features` in the layer metadata at line 1560. Note the AOI path at line 155-166 has the same structure but _run checks `aoi_geom.isEmpty()` at line 1021 - the grave path is the one missing that check.
- 실패 시나리오: A 수치지형도 layer contains 12 features whose attributes match (e.g. a "묘지" polygon layer digitised from DXF), one of which has a self-intersecting (bow-tie) ring - routine in DXF-derived Korean topographic data. _build_grave_avoid_union buffers all 12 by 3 m and calls QgsGeometry.unaryUnion; GEOS raises TopologyException, unaryUnion returns a null QgsGeometry, and the function returns (nullGeom, 12). In _run, `grave_union is not None` is True, so every candidate runs `trench_geom.intersects(nullGeom)` which returns False. All 12 graves are ignored and trenches are proposed directly on top of them. The user sees the message bar text "트렌치 후보 12개를 생성했습니다. (무덤 회피: 12건 반영)" and layer metadata `grave_matched_features: 12`, i.e. an explicit claim that 12 graves were avoided when none were.
- 제안 수정: In _build_grave_avoid_union, drop null/empty results from `geoms` before counting (check `g is None or g.isNull() or g.isEmpty()` after buffer), and after the union do `if union is None or union.isNull() or union.isEmpty(): return None, 0` - or better, return a third value `avoid_active: bool` and have _run report "회피 마스크 생성 실패" instead of "N건 반영" when the union collapsed. Also guard the buffer: if `g.buffer(...)` returns a null geometry, keep the unbuffered `g` and log it. Consider `union.makeValid()` before use.
  - 검증: certain: Tried to refute on five fronts and failed on all five.

(1) Earlier guard: exists but only pre-buffer (:818, :821). The post-buffer result at :825 is appended unconditionally at :828, outside the try. No check on `union` at :834-841.

(2) Caller validation: none. `grave_union` occurs only a …
  - 검증: likely: STRUCTURAL DEFECT: CONFIRMED verbatim in the current file (unchanged since a7a6b31; not one of the 19 remediation files).

- :830 `count = len(geoms)` is the matched-feature count and is returned at :842 no matter what the union produced.
- :834 `union = geoms[0] if count == 1 else QgsGeomet …
  - 검증: certain: REAL — the defect is exactly as described, and I could not find any mitigating guard anywhere in the file.

The mechanism holds end to end. `QgsGeometry.unaryUnion` signals GEOS failure by RETURN VALUE (a null QgsGeometry with `mLastError` set), not by raising. So `union` at line 834 is a l …

#### [major] F-TR-02 — Grave keyword list misses the standard Korean burial-type vocabulary (지석묘/고인돌/석실묘/토광묘/옹관묘/총/릉)

- 위치: `tools/trench_suggestion_dialog.py` :62-80, 89-112
- 문제: The list covers generic terms but none of the burial-type names that Korean excavation data actually uses as feature/legend labels. I ran the exact matcher offline against 36 terms; every one of these returns False: 지석묘 (dolmen), 고인돌 (dolmen), 석실묘, 석곽묘, 석실분, 토광묘, 옹관묘, 목관묘, 목곽묘, 분구묘, 주구묘, 봉토분, 횡혈식석실분, 적석총, 천마총, 고총, and bare 릉 (선릉, 정릉). English 'tumulus', 'barrow' and 'dolmen' also miss. The exclusion of bare "묘" is a defensible design choice and is documented at lines 57-61, but the fix was to enumerate 2+ char compounds and the enumeration stops at the generic ones - 지석묘 does not contain 묘지, 분묘, or any other listed compound. The checkbox says "무덤/분묘 회피 적용", the help HTML (line 456) says "무덤 회피: 수치지형도 속성과 hidden 범례(XLS) 기반 코드·키워드 회피", and README.md:163 says "무덤/분묘 관련 키워드와 코드 패턴을 이용한 회피 보조 로직 포함" - all of which a user reads as "graves are avoided".
- 실패 시나리오: A user loads a 유적분포 polygon layer whose `명칭` field holds values like "OO리 지석묘군", "OO 석실묘 3호", "OO 토광묘", selects it as the 수치지형도 벡터 layer, and leaves "무덤 회피 적용" checked. _feature_has_grave_hint joins all attributes and calls _text_has_grave_keyword, which returns False for every one of them. _build_grave_avoid_union returns (None, 0). The tool logs "무덤 회피: 조건에 맞는 무덤/분묘 피처 0건 → 회피 대상 없음" and the message bar says "(무덤 회피: 대상 0건)", and it then proposes trench rank 1 centred on a dolmen (지석묘) - a protected cultural property. The 0-count message is technically honest but the user has no way to know that the reason is a vocabulary gap rather than an absence of graves.
- 제안 수정: Extend _GRAVE_KW_KO with the burial-type stems actually used in Korean archaeology: 지석묘, 고인돌, 석실묘, 석곽묘, 석실분, 석곽분, 토광묘, 옹관묘, 목관묘, 목곽묘, 분구묘, 주구묘, 봉토분, 적석총, 패총 is NOT one (shell midden), plus a guarded suffix rule for 총/릉 (e.g. r'[가-힣]총\\b', r'[가-힣]릉\\b' with an exclusion list for 총계/총합/구릉/능선). Add 'tumulus', 'barrow', 'dolmen', 'cist' to _GRAVE_KW_EN. Separately, when grave_count == 0 the message should say which terms were searched so the user can judge the gap, e.g. "(무덤 회피: 대상 0건 — 검색어 N종 기준)".
  - 검증: likely: The factual core is reproducible and I could not refute it: the matcher genuinely returns False for every standard Korean burial-type compound, and there is no guard, caller validation or second code path that rescues it (the hidden-XLS code route runs through the same _text_has_grave_keywor …
  - 검증: certain: CONFIRMED — and the failure is reproducible offline, which I did.

The quoted code matches the file byte-for-byte, and every factual claim in the finding checks out: 지석묘 contains none of 묘지/분묘/무덤/묘역/봉분/고분/왕릉/능묘/가족묘/공동묘, so the substring loop at line 102 falls through, the English loop finds …
  - 검증: certain: REAL, and every factual claim in it reproduces exactly. Still present in the current file (unchanged a7a6b31..HEAD; not in the remediation set).

IMPACT. This does not corrupt a computed quantity — there is no maths error here, and nothing in an exported table changes. The damage is to the …

#### [major] F-TR-03 — Hidden-legend XLS fallback parses the OGR sublayer string wrongly, so the OGR path never returns a single row

- 위치: `tools/trench_suggestion_dialog.py` :536-543
- 문제: QgsDataProvider::subLayers() for OGR returns "index!!::!!name!!::!!featureCount!!::!!geometryType". `split("!!::!!", 1)[1]` keeps everything after the FIRST separator, i.e. "Sheet1!!::!!12!!::!!None", not "Sheet1". I verified this offline: "0!!::!!Sheet1!!::!!12!!::!!None".split('!!::!!',1)[1] == 'Sheet1!!::!!12!!::!!None' whereas [1] of an unlimited split is 'Sheet1'. The resulting URI is `...xls|layername=Sheet1!!::!!12!!::!!None`, which OGR cannot resolve, so `lyr.isValid()` is False for every sheet, `layers` stays empty, and the function returns []. The OGR/XLS fallback in _load_grave_codes_from_hidden (lines 578-582) is therefore dead code: code-based grave avoidance works only when pandas AND an .xls-capable engine (xlrd) are both importable, which is not guaranteed in a stock QGIS install.
- 실패 시나리오: A user drops the official NGII legend workbook at archtoolkit/hidden/legend.xls on a QGIS build without pandas (or without xlrd). _iter_rows_from_xls_pandas returns [] at the `import pandas` except. _iter_rows_from_xls_qgis then builds 'legend.xls|layername=Sheet1!!::!!842!!::!!None', QgsVectorLayer.isValid() is False, and it returns []. `_load_grave_codes_from_hidden` caches an empty set, the label reads "hidden XLS 인식 실패/코드 없음 (키워드 회피만 사용)" and metadata records `hidden_xls_loaded: False`. Every grave feature whose only grave signal is its standard code (e.g. attribute CODE='A0010000' with no Korean text in any field) is missed - the feature-level test at line 668 `if code and (code in grave_codes)` can never fire because grave_codes is empty.
- 제안 수정: Use `name = s.split("!!::!!")[1]` (unlimited split, take index 1), and prefer the modern API where available: `QgsProviderRegistry.instance().querySublayers(xls_path)` and each detail's `.uri()`. Also accept `.xlsx`/`.xlsm` in _hidden_xls_path (line 491 filters only `.xls`), since modern NGII legend files are .xlsx and are currently reported as "hidden XLS 없음".
  - 검증: certain: Could not refute the mechanism. tools/trench_suggestion_dialog.py:534 uses name.split("!!::!!", 1)[1], which keeps the trailing OGR sublayer metadata: for the OGR string "index!!::!!name!!::!!featureCount!!::!!geomType" it yields "Sheet1!!::!!842!!::!!None", not "Sheet1". The URI built at 5 …
  - 검증: certain: CONFIRMED. The bug is exactly as described, and the current file still contains it.

Current code (unchanged since a7a6b31), tools/trench_suggestion_dialog.py:532-548:
  532  subs = base.dataProvider().subLayers() or []
  536  for s in subs:
  537      name = str(s or "")
  538      if "!!: …
  - 검증: likely: The bug is real and I confirmed it mechanically, but the severity is overstated. Downgrade major -> minor.

WHAT IS RIGHT: `split("!!::!!", 1)[1]` keeps everything after the first separator, so the OGR/XLS fallback builds an unresolvable URI and is dead code on any file whose subLayers() ret …

#### [major] F-TR-04 — "최대 허용 경사" is tested only at the trench centre, so a proposed trench can cross ground far steeper than the limit

- 위치: `tools/trench_suggestion_dialog.py` :1295-1300, 1488
- 문제: `pt` is the candidate CENTRE. A trench is up to 500 m long (spinLength range is 2.0-500.0), yet the slope constraint and the exported `slope_deg` attribute are both a single-pixel sample at the centre. The tool already knows how to sample the footprint - _footprint_downslope_bearing builds an 8-point rosette at radius length/2 and computes per-sample slope at line 913 - but that slope is used only as a circular-mean weight and is discarded. Nothing in the UI discloses the centre-only evaluation: the label is "최대 허용 경사:" with a " deg" suffix and no tooltip, and the metadata records `max_slope_deg` as if it were a property of the trench. The exported `slope_deg` column is the number that ends up in an excavation report table as "the slope of this trench".
- 실패 시나리오: DEM covers a 5° river terrace cut by a 45° scarp 15 m wide. A candidate centre sits on the terrace 8 m from the scarp edge; slope at the centre = 5°, which passes slope_max = 30°. Orientation mode is the default 등고선 직교, so the 20 m trench runs downslope and its uphill half reaches 10 m from the centre, i.e. 2 m into the 45° scarp. The trench is accepted, exported with slope_deg = 5.0, and a report states the trench sits on 5° ground. With trench_length = 100 m the same candidate puts 42 m of the trench on the 45° scarp while still reporting slope_deg = 5.0. Nothing in the layer or the message bar contradicts that number.
- 제안 수정: Reuse the rosette samples: have _footprint_downslope_bearing also return max and mean slope over the footprint, apply `slope_max` to the footprint MAX, and export two fields (`slope_deg_center`, `slope_deg_max`) so the number that goes into a report is the one that can be defended. If the centre-only test is kept deliberately, say so in the spinSlopeMax tooltip and rename the field to `slope_deg_center`.
  - 검증: certain: Tried hard to refute; every refutation path failed.

CODE CONFIRMED VERBATIM at tools/trench_suggestion_dialog.py:1294-1301. `pt` is the candidate CENTRE (it is passed to _rect_geom_from_center at 1320). `_sample_raster_value` (614) is `dataProvider().identify(p, QgsRaster.IdentifyFormatVal …
  - 검증: certain: REAL, and I can construct it end to end.

EXACT INPUTS: AOI polygon layer in EPSG:5186 (metres). DEM 1 m, covering a river terrace at 5° west of x=0, a 45° scarp from x=0 to x=15 m, floodplain beyond; aspect 90° (east) throughout, which is the normal case for a terrace dipping toward its ow …
  - 검증: certain: REAL and correctly graded major. Keep at major — I considered both directions and neither move is justified.

The finding is accurate in every particular, and it UNDERSTATES the impact in two ways worth passing on:

1. The centre-only slope also drives RANKING, not just admission. Line 1367 …

#### [major] F-TR-05 — The exported `rank` field is coverage round-robin order, not score order — rank N can score lower than rank N+k

- 위치: `tools/trench_suggestion_dialog.py` :1428, 1440-1467, 1481, 1499
- 문제: Selection is deliberately coverage-first (comment at line 1418-1420), which is a legitimate design choice - but the resulting list order is then written verbatim into a field called `rank`, alongside `score`. After the first round-robin pass exhausts the buckets, pass 2 starts handing out ranks to the SECOND-best candidate of the top buckets, which routinely outscores the first-pass pick of a weak bucket. No user-facing string, tooltip or metadata key says that `rank` is a coverage sequence rather than a priority order; the metadata params (lines 1546-1572) record grid/spacing/weights but not the selection strategy. A practitioner who writes "우선순위 1~5번 트렌치를 우선 발굴" in an excavation design is then digging a lower-scoring trench than one they skipped, and the evidence is visible in their own attribute table, which is exactly what a reviewer will point at.
- 실패 시나리오: AOI 100 m x 100 m (aoi_area 10,000), want_n = 12, grid_step 10 m -> cov_cell = max(10, sqrt(10000/12)) = 28.9 m, so a 4x4 bucket grid. The slope/inside filters leave candidates in only 8 of the 16 buckets. Pass 1 selects 8 (ranks 1-8) in descending bucket-best order, ending with rank 8 = 0.45 (best of the weakest occupied bucket). Pass 2 selects 4 more: rank 9 = second-best of bucket 1 = 0.88, rank 10 = 0.86, etc. The output layer therefore contains rank 8 with score 0.45 and rank 9 with score 0.88. Sorting the layer by `rank` and by `score` gives two different "top 5" sets.
- 제안 수정: Rename the field to `pick_order` (or `coverage_order`) and add a second field `score_rank` computed by sorting `selected` by score; or keep `rank` but assign it from a score sort and add `pick_order` for the round-robin sequence. Either way add `"selection_strategy": "coverage_round_robin"` and `"coverage_cell_m": cov_cell` to the metadata params at line 1546, and say in the completion message that selection spreads trenches across the AOI rather than taking the top-N scores.
  - 검증: certain: I tried to refute this and could not; the mechanism is verified by direct reading and by replaying the algorithm.

MECHANISM CONFIRMED. tools/trench_suggestion_dialog.py:1428 sorts BUCKETS by their best member, not candidates by score. The loop at :1451 (`while len(selected) < want_n and pr …
  - 검증: certain: REAL, and I constructed a stronger, fully deterministic trigger than the one in the finding.

MECHANISM (verified in code)
- 1428: `bucket_order = sorted(buckets.values(), key=lambda b: float(b[0].get("score",0.0)), reverse=True)` — buckets ordered by their BEST candidate.
- 1444-1467: roun …
  - 검증: certain: CONFIRMED, and the impact is worse than the finding argues, though for a partly different reason.

The code is exactly as described: `selected` is built in coverage round-robin order and `enumerate(selected, start=1)` is written verbatim into a field named `rank`, with `score` in the adjace …

#### [major] F-TR-06 — AHP score is min-max stretched over the AOI BOUNDING BOX, silently changing the effective AHP weight the metadata reports

- 위치: `tools/trench_suggestion_dialog.py` :1158-1172, 1347-1348, 1565
- 문제: Two undisclosed things happen here. (1) `_aoi_extent_in_raster_crs` returns `g.boundingBox()`, not the AOI polygon, so ahp_min/ahp_max are taken over territory the user did not select - for any non-rectangular AOI (an L-shaped or ribbon-shaped survey area, which is the normal case) the stretch range is set by pixels that no candidate can ever occupy. (2) ahp_score is a relative stretch, not an absolute suitability: the best pixel in the window always scores 1.0 and the worst 0.0 regardless of the AHP model's own scale. Because slope_score and ref_score are absolute (fixed 0..slope_max and 0..ref_radius ranges), stretching only the AHP term rescales its real influence in the weighted sum, and `weights_effective` at line 1565 still records the nominal 0.55. Nothing in the UI, the help HTML, or the metadata mentions min-max normalisation or the extent it uses. If `ext` is None (transform failure) it silently switches to the whole raster extent - a third, different normalisation basis, with no log line.
- 실패 시나리오: An L-shaped AOI along a valley floor; its bounding box also contains a hilltop that the AHP model scores 98, while inside the AOI itself AHP runs 20-45. bandStatistics over the bbox returns ahp_min=2, ahp_max=98, so in-AOI candidates get ahp_score between 0.19 and 0.45 - a dynamic range of 0.26 instead of 1.0. With the defaults (w_ahp 0.55, w_ref 0.25, w_slope 0.20) the AHP term can now move the total score by at most 0.55*0.26 = 0.14, while slope_score still spans the full 0.20. Slope therefore outranks AHP in deciding which trenches are proposed, even though the user set AHP to be the dominant criterion, and the layer metadata states weights_effective.ahp = 0.55. Clipping the same AHP raster to the AOI polygon first and re-running produces a different rank-1 trench.
- 제안 수정: Compute the stretch over the AOI polygon, not its bbox (clip the AHP raster with gdal:cliprasterbymasklayer, or accumulate min/max from the sampled candidate values themselves). Record the basis in the metadata: `"ahp_norm": {"method": "minmax", "extent": "aoi_bbox"|"aoi_polygon"|"full_raster", "min": ahp_min, "max": ahp_max}`, and log a line when the fallback to the full raster extent is taken. Add one sentence to the help HTML saying the AHP term is normalised relative to the AOI, so a candidate's ahp_score is a within-AOI rank, not an absolute suitability.
  - 검증: certain: NOT REFUTED. I looked for every guard the finder might have missed and found none; two of my refutation attempts turned into further evidence for the finding.

The mechanism is exactly as described: `_aoi_extent_in_raster_crs` (:1002) returns `g.boundingBox()`, bandStatistics (:1161-1167) c …
  - 검증: certain: CONSTRUCTED AND CONFIRMED. All four sub-claims hold in the current file, and I produced an actual rank-1 flip with realistic inputs.

The mechanism: `_aoi_extent_in_raster_crs` (L1001) returns `g.boundingBox()`, so `bandStatistics` (L1162-1166) computes ahp_min/ahp_max over the AOI's boundi …
  - 검증: certain: CONFIRMED, and hold at major.

The core mechanism is real and I reproduced the consequence. Min-max stretching is a monotonic affine map, so it would be harmless if it were applied to the whole score -- but it is applied to only ONE of three terms while ref_score and slope_score stay absolu …

#### [major] F-TR-10 — "AOI 선택 피처만 사용" silently unions every feature when nothing is selected

- 위치: `tools/trench_suggestion_dialog.py` :139
- 문제: The checkbox at line 259-260 is labelled "AOI 선택 피처만 사용" and is checked by default. When the user has that box checked but no features selected, the condition `layer.selectedFeatureCount() > 0` fails and the code falls through to `layer.getFeatures()` - i.e. it silently does the opposite of the checked option. Nothing warns: the only trace is `aoi_features: int(aoi_n)` in the metadata, which a user reads after the fact and which counts all iterated features anyway (n is incremented at line 143 before the geometry validity check, so it also counts features with empty geometry).
- 실패 시나리오: A 시굴조사 project has one AOI layer holding 40 separate survey polygons scattered over a 30 km-wide county. The user opens the dialog, leaves "AOI 선택 피처만 사용" checked, forgets to select the one polygon they are working on, and clicks 후보 생성. _unary_union_geom unions all 40 polygons. bbox width becomes ~30,000 m, interior_est blows past max_eval, and grid_step is auto-coarsened from 10 m to (say) 120 m - the only hint being a 정보-level live-log line about the grid, not about the AOI. The 12 proposed trenches are then spread across all 40 areas on a 120 m grid, and the metadata says `aoi_features: 40` while the UI said the tool would use only the selection.
- 제안 수정: When `selected_only` is True and `selectedFeatureCount() == 0`, either abort with a message bar error ("선택된 AOI 피처가 없습니다") or fall back to all features and say so explicitly via push_message/log_message, and record `"aoi_selection_used": False` in the metadata params. Also move the `n += 1` at line 143 to after the empty-geometry check so `aoi_features` counts the features that actually contributed.
  - 검증: certain: Refutation failed on every avenue. (1) No earlier guard: _run (L1006-1027) validates only layer type, geometry type and CRS before calling _unary_union_geom at L1024; _run is the only caller. (2) The QGIS API does not handle it — selectedFeatures() returns an empty list when nothing is sele …
  - 검증: certain: CONFIRMED and reproducible. The failure constructs cleanly.

Setup: AOI layer on EPSG:5186 (metric, so it passes the is_metric_crs gate at line 1020), holding 40 survey polygons of 200x200 m scattered over a 30 km x 20 km county. User leaves "AOI 선택 피처만 사용" checked (default, line 260) but h …
  - 검증: certain: REAL, and stronger than reported. The code, the label, the default-checked state, the absent warning and the absent metadata flag are all exactly as described at current HEAD.

The decisive evidence is the repo's own precedent. tools/aoi_extent.py:118-122 carries the comment "The old copies …

#### [minor] F-TR-07 — Grave features are fetched with a ~6 m margin while a long trench can extend 25 m outside the AOI bounding box

- 위치: `tools/trench_suggestion_dialog.py` :795-801
- 문제: The request rectangle is the AOI bbox grown by max(5, grave_buffer+3) m - 6 m with the default 3 m buffer. But a candidate is only required to have `inside_ratio >= inside_min_ratio` (default 0.95, minimum 0.10), so the trench polygon itself can protrude well beyond the AOI and hence beyond that 6 m margin. The margin is derived from the grave buffer alone and never from the trench half-length, so grave features outside the fetch rectangle are never loaded, never counted in grave_count, and never tested against the trench. The avoidance then silently does not apply to them while the message bar still reports the count of the ones that were loaded.
- 실패 시나리오: trench_length = 500 m (allowed by spinLength), inside_min_ratio = 0.95, grave_buffer = 3 m -> fetch margin = 6 m. A candidate centred 225 m inside a straight AOI edge with the default 등고선 직교 orientation running perpendicular to that edge has inside_ratio = (225+250)/500 = 0.95, so it passes, and its far end sits 25 m outside the AOI boundary. A 묘지 polygon 12 m beyond the AOI bbox edge has a bounding box that does not intersect the 6 m-grown rectangle, so getFeatures(req) never returns it: grave_count excludes it and grave_union does not contain it. The tool proposes a 500 m trench whose last 13 m runs through a cemetery, and reports "(무덤 회피: 4건 반영)" for the four graves that happened to be inside the AOI. The same happens with the default 20 m trench when inside_min_ratio is lowered to 10% …
- 제안 수정: Grow the rectangle by `float(grave_buffer_m) + float(trench_length) * 0.5 + 5.0` (and convert to degrees when topo_layer.crs().isGeographic(), as _build_reference_index already does at lines 697-707). Apply the same reasoning to the _clip_dem_to_aoi margin if the trench can protrude beyond the clipped DEM.
  - 검증: certain: I tried to refute it on five routes and all five failed.

(1) Output not clipped: line 1327-1331 uses trench_geom.intersection(aoi_geom) only for the AREA ratio; the candidate stores "geom": trench_geom (1383) and the exported feature is f_poly.setGeometry(d.get("geom")) (1512). The publish …
  - 검증: certain: REAL — I constructed the failure end to end and reproduced the arithmetic.

CONCRETE REPRODUCTION
- AOI layer: single axis-aligned square polygon in EPSG:5186 (metres), (200000, 500000) to (200600, 500600). Axis-aligned means the AOI boundary coincides with its bounding box, which is what m …
  - 검증: certain: REAL — the mechanism is confirmed, but the finding's arithmetic is wrong in both directions and the correct threshold matters for grading.

Re-derived reachability. The failure needs a grave whose distance d from the AOI bounding box satisfies margin < d < protrusion + buffer, where margin …

#### [minor] F-TR-08 — Legend code regex misses codes written adjacent to Hangul, losing code-based grave avoidance for those rows

- 위치: `tools/trench_suggestion_dialog.py` :86, 561-570
- 문제: Python's `re` treats Hangul syllables as word characters, so `\b` does not fire between a Hangul character and an ASCII letter. Verified offline: _CODE_RE.findall('묘지A0010000') == [] while findall('묘지(A0010000)') == ['A0010000'] and findall('분묘 A0010000') == ['A0010000']. Legend workbooks that write the code glued to the label in a single cell therefore yield no code at all for that row, even though _text_has_grave_keyword matched the row and _extract_grave_codes was reached. The same `\b` issue does not affect _feature_has_grave_hint (which compares the whole stripped field value) but it silently shrinks the code set that feature test depends on.
- 실패 시나리오: A hidden legend sheet has a single merged column whose cells read "묘지A0010000", "분묘B0010001", etc. _extract_grave_codes joins the row, _text_has_grave_keyword matches on 묘지, then _CODE_RE.findall('묘지A0010000') returns []. No codes are added. _load_grave_codes_from_hidden returns an empty set, the status label reads "hidden XLS 인식 실패/코드 없음 (키워드 회피만 사용)", and a 수치지형도 feature whose CODE field is 'A0010000' with no Korean text in any attribute is not recognised as a grave and is not avoided.
- 제안 수정: Replace the word-boundary anchors with lookarounds that only exclude adjacent ASCII alphanumerics: `re.compile(r"(?<![A-Za-z0-9])([A-Z][0-9]{7,8})(?![A-Za-z0-9])")`. Verify against the same seven spellings I tested.
  - 검증: certain: CONFIRMED, at the finder's own severity of minor.

Mechanism verified independently. I ran the exact regex from line 86 against 15 spellings. Hangul is a Unicode word character (re.match(r'\w','묘') matches), so \b never fires at a Hangul/ASCII-letter junction:
  FAIL '묘지A0010000' -> []   FA …
  - 검증: certain: CONFIRMED — I reproduced it against the regex compiled directly from the source file, and the finding's cited code is present unchanged in the current file.

MECHANISM (executed, output pasted):
  pattern compiled from file = '\\b([A-Z][0-9]{7,8})\\b'
  re.match(r'\w','묘') -> True;  '묘'.isa …
  - 검증: likely: The regex defect is real and verified, and in fact broader than the finding states: Hangul is a word character in Python re, so \b never fires at a Hangul-to-ASCII transition. findall('묘지A0010000') == []. Beyond the two spellings the finding cites, '묘지_A0010000' (underscore is \w) and 'A0010 …

#### [minor] F-TR-09 — ref_dist_m can report a site that is not the nearest, because only 8 spatial-index neighbours are measured

- 위치: `tools/trench_suggestion_dialog.py` :736-756
- 문제: QgsSpatialIndex.nearestNeighbor ranks by the indexed bounding box, not by true geometry distance. Bounding-box distance is always <= true distance, so large polygons whose bbox contains or nearly contains the query point are ranked ahead of small features that are genuinely closer. Taking exactly 8 candidates means a genuinely nearest feature can be crowded out by big-bbox features whose real geometry is far away. The resulting `ref_dist_m` is exported as a layer field and feeds ref_score via the linear decay at line 1362, so both the number in the report and the candidate's score are wrong. Nothing tells the user that ref_dist_m is an 8-neighbour approximation.
- 실패 시나리오: The 주변 유적 layer contains nine large, mutually overlapping 유적분포 polygons (common in Korean 문화재 지표조사 GIS, where 유적 범위 polygons cover whole hillsides) whose bounding boxes all contain the candidate point, plus one small point-feature 유적 50 m away. nearestNeighbor(pt, 8) returns eight of the nine zero-bbox-distance polygons; the 50 m point feature is not among them. The measured distances to those eight polygons' actual boundaries are ~700-900 m, so dmin = 700. With ref_radius_m = 1000 the candidate gets ref_score = 1 - 700/1000 = 0.30 instead of 1 - 50/1000 = 0.95, and the layer exports ref_dist_m = 700.0 - a number a reader would take as "distance to the nearest known site".
- 제안 수정: Raise the neighbour count and make it adaptive (e.g. start at 32, and if the smallest true distance found exceeds the largest bbox distance among the returned set, widen the query), or replace it with `idx.intersects(QgsRectangle around pt of radius ref_radius_m)` and measure true distance to every feature in that rectangle - the reference set is already pre-filtered to AOI bbox + radius, so it is small. Either way, either make ref_dist_m exact or rename it (e.g. `ref_dist_m_approx`) and say so in the help.
  - 검증: certain: I could not refute it. The core premise is confirmed verbatim by upstream QGIS: qgsspatialindex.h:212-214 warns "If this QgsSpatialIndex object was not constructed with the FlagStoreFeatureGeometries flag, then the nearest neighbor test is performed based on the feature bounding boxes ONLY, …
  - 검증: certain: CONSTRUCTED — the failure is real and I reproduced it end to end with the finding's own numbers.

The mechanism is confirmed at the source level, which is the only part that could have sunk this finding. `QgsSpatialIndex()` at L693 is built with no flags, so `mGeometries` is null in `QgsNea …
  - 검증: certain: MECHANISM: CONFIRMED, not merely plausible. Line 693 builds a bare `QgsSpatialIndex()` (no flags); line 756 calls `idx.nearestNeighbor(pt, 8)`. QGIS 3.40 source proves the ranking is bounding-box-only in that case - qgsspatialindex.cpp:521 hands the comparator `nullptr` for geometries unles …

### geology


#### [blocker] GEO-01 — Rasterize sets a NoData value but never initialises the grid: every uncovered cell is a real 0, not NoData

- 위치: `tools/geology_zip_dialog.py` :1275-1285
- 문제: The call passes NODATA but not INIT. In QGIS's gdal:rasterize (processing/algs/gdal/rasterize.py) '-init' is emitted only when INIT is present in the parameters dict, and in GDAL's apps/gdal_rasterize_lib.cpp CreateOutputDataset the nodata option does nothing but `GDALSetRasterNoDataValue(hBand, dfNoData)` — `GDALFillRaster()` is reached only from the `-init` branch. A freshly GDALCreate'd GeoTIFF reads as 0, so the file's header advertises NoData=-9999 while no cell in the raster ever holds -9999: the NoData mask is empty and every cell that no polygon centre covered is the perfectly valid class code 0. Code 0 is also absent from the *_mapping.csv, because the string mapping starts at next_id=1 (line 1058). The dialog's own 'NoData 값' spinbox (line 731) promises the user that empty area will carry that value. The same repository already knows the fix: tools/distance_raster_dialog.py:392-394 passes "NODATA": 0 together with "INIT": 0 in its gdal:rasterize call.
- 실패 시나리오: Select two KIGAM Litho sheets that are diagonal neighbours (or one coastal sheet whose Litho polygons stop at the shoreline), pixel 10 m, NoData -9999, merge mode. The output extent is the union bounding box, so the quadrants/sea with no polygon are burned as 0. gdalinfo reports NODATA=-9999 and a histogram in which 0 is the largest class. MaxEnt reads .asc NODATA_value -9999, finds none, and treats the whole empty quadrant as lithology class 0 — background points are drawn there and the 'class 0' response curve enters the published model. Worse, align/export then calls _categorical_output_nodata (tools/align_export_dialog.py:183-215), which returns the source's own -9999 with reason 'source', so the exported stack declares a NoData that never occurs and the two guards that module document …
- 제안 수정: Add "INIT": float(nodata) to the params dict at line 1275 so gdal_rasterize pre-fills the band with the NoData value before burning, and reject/round a fractional NoData (the spinbox allows 2 decimals, line 730, on an Int32 band) so the written value is representable. Then state the actual background value in the help HTML and, ideally, emit a row for it in the mapping CSV.
  - 검증: certain: I could not refute it; every link verifies against primary sources.

MECHANISM CONFIRMED. The params dict at tools/geology_zip_dialog.py:1274-1285 passes "NODATA": float(nodata) and no "INIT". In QGIS's real algorithm (fetched from qgis/qgis release-3_34, python/plugins/processing/algs/gdal …
  - 검증: certain: CONFIRMED. The failure constructs cleanly and the mechanism is pinned to upstream source, not inference.

STEP-BY-STEP TRACE.
Inputs: 지질도 ZIP 불러오기, load GF13_청주.zip and GF14_보은.zip (KIGAM 1:50,000, EPSG:5186). Tick both Litho polygon layers. Field LITHONAME (or LITHOIDX — the help HTML at : …
  - 검증: certain: CONFIRMED, blocker stands. The code at tools/geology_zip_dialog.py:1275-1286 passes NODATA but no INIT to gdal:rasterize, and the fallback at 1327 copies the same dict. QGIS emits -init only when INIT is in the parameters dict, and GDAL's -a_nodata only writes the nodata tag (GDALFillRaster …

#### [blocker] GEO-02 — Merged multi-sheet raster reuses each sheet's raw numeric code, and the mapping CSV keeps only the first sheet's label for a colliding code

- 위치: `tools/geology_zip_dialog.py` :1093-1112
- 문제: In merge mode with a numeric value field — LITHOIDX/AGEIDX, which the help HTML explicitly recommends ('값 필드는 보통 LITHOIDX/AGEIDX를 사용합니다', line 1560) — the code burns each layer's raw integer straight through with no cross-layer reconciliation. Nothing verifies that the same integer means the same lithology in every selected layer, even though the code is already reading the paired name field (label_field, line 1059/1105-1109) and could see the conflict immediately. Instead `if code not in labels` makes the FIRST layer's name win, silently discarding the conflicting name from every later layer, while counts[] (line 1124) sums the feature counts of both meanings into one row. Index-style fields are exactly the kind of attribute that is numbered per map sheet, and this is the one workflow the dialog is built for (it prefixes list entries with '[GF13_청주]' precisely because several sheets are loaded at once).
- 실패 시나리오: Load sheets GF13 and GF14, tick both Litho layers, field LITHOIDX, merge. Sheet GF13 has LITHOIDX=3 / LITHONAME='흑운모화강암'; sheet GF14 has LITHOIDX=3 / LITHONAME='석회암'. The merged raster stores 3 over both areas and geology_mapping.csv contains exactly one row: `3,3,흑운모화강암,812` where 812 is the summed feature count of granite AND limestone. The user publishes 'class 3 = biotite granite' and the MaxEnt response curve for class 3 mixes two unrelated lithologies over half the study area. Nothing in the log, the message bar or the CSV hints at the collision.
- 제안 수정: Key the merged mapping on (layer-or-sheet, raw code) rather than the raw code alone: build a run-wide dictionary from the code AND its paired name field, allocate a fresh sequential int per distinct (code,label) pair, and record the source sheet in a new CSV column. At minimum, detect the case (same code, different label in another layer) and refuse the run with a message naming the conflicting sheets and codes instead of silently keeping the first label.
  - 검증: certain: I could not refute this. I looked for every guard the finder might have missed and found none; worse, I found independent evidence inside the plugin that confirms the premise.

CODE CONFIRMED (unchanged since a7a6b31). tools/geology_zip_dialog.py:1059-1060 decides the numeric path and the p …
  - 검증: certain: Real and reproducible. I replayed the numeric branch of `_build_numeric_merge_layer` in pure Python and got exactly the CSV row the finding predicted — `3,3,흑운모화강암,812` — with the second sheet's 석회암 silently gone and its 312 features folded into the granite count. Three distinct real (code, …
  - 검증: likely: REAL, and blocker stands.

The mechanics are certain, not inferred. I re-read the code and re-ran the numeric branch: for a code present in two sheets, `mapping[code] = out_int` (L1104) burns the raw integer through with no reconciliation, `if code not in labels` (L1105) locks in the first s …

#### [major] GEO-03 — Per-layer mode names outputs from the layer name only, so two sheets' identically named Litho layers overwrite each other's raster and mapping CSV

- 위치: `tools/geology_zip_dialog.py` :1457
- 문제: Layer names come from the shapefile basename inside the ZIP (line 416: `layer_name = os.path.splitext(fname)[0]`), so two sheets loaded from two ZIPs produce two layers with the identical name. The dialog itself is built around that fact: refresh_layer_list() prefixes the displayed name with the sheet folder ('[GF13_청주] Litho', lines 868-872) and the help HTML says so outright — '레이어 이름 앞에 [GF13_청주]처럼 도엽/지역 정보가 함께 표시됩니다(여러 도엽을 불러온 경우 구분용)'. That region string (self._kigam_region_for_layer) is used for display only and never reaches the output path, so the loop writes both sheets to the same file. There is no existence check, no uniquifying suffix, and the final message at line 1487 reports blanket success.
- 실패 시나리오: Load GF13_청주.zip and GF14_보은.zip, uncheck nothing, choose '레이어별 래스터 출력' with output folder D:/maxent and format tif. The loop writes D:/maxent/Litho.tif and Litho_mapping.csv for 청주, then overwrites both with 보은 — file and legend together, so no trace of the first sheet remains. The message bar says '레이어별 래스터 변환이 완료되었습니다.' and the project gets two raster layers both named 'Litho_raster' pointing at the same file, so the canvas shows 보은 twice. The user builds a two-sheet predictor stack from one sheet's data and cannot tell from any artefact on disk that a sheet is missing.
- 제안 수정: Build the filename from the sheet/region plus the layer name (the region is already available via self._kigam_region_for_layer(lyr)), e.g. `_safe_name(f"{region}_{lyr.name()}")`, and before writing, check os.path.exists(out_path) and either uniquify with a counter or abort with a message naming the collision. Name the added raster layer the same way instead of '{lyr.name()}_raster'.
  - 검증: certain: I could not refute it. The claimed failure is unprevented at every level I checked: no earlier guard in _run_rasterize, no caller-side validation (the dialog's own list widget deliberately keeps both same-named layers and distinguishes them only in the display string), no QGIS/GDAL behaviou …
  - 검증: certain: CONFIRMED - the failure is fully constructible and I reproduced the colliding paths by running the module's own _safe_name.

Exact inputs: load GF13_청주.zip then GF14_보은.zip via the ZIP loader; each contains Litho.shp, so process_zip line 416 names both layers "Litho" and organize_layers put …
  - 검증: certain: REAL, and still present in the current file (geology_zip_dialog.py is not among the 19 files under concurrent remediation; the working tree matches a7a6b31). The mechanism is exactly as described: in per-layer mode the output path, the mapping CSV path, and the added project layer name are …

#### [major] GEO-04 — String lithology codes are numbered per output and per run, so codes are not comparable between sheets or between two runs of the same tool

- 위치: `tools/geology_zip_dialog.py` :1058, 1113-1120, 1455
- 문제: The string->int mapping is assigned in feature-encounter order and the counter restarts at 1 on every call. In per-layer mode the builder is invoked once per layer (line 1455), so each sheet independently allocates 1,2,3...; in merge mode the numbering depends on which layers are ticked and on the list order (refresh_layer_list sorts by region then name, line 871), so adding a third sheet whose region sorts first renumbers every class. Nothing in the raster, the layer metadata (params only records field and pixel, line 1425) or the help discloses this. The help presents the mapping as a solved problem: '문자 코드(예: Qa, Jbgr)일 경우 자동으로 정수 코드로 매핑하며, *_mapping.csv를 함께 저장합니다.'
- 실패 시나리오: Per-layer mode over two sheets with a string code field (SIGN/CODE): sheet A's first-encountered unit 'Qa' becomes 1 and sheet B's first-encountered unit 'Jbgr' also becomes 1. Mosaic the two .tif files (the obvious way to cover a study area spanning two sheets) or feed both to a model as one variable and class 1 is alluvium in the west and Jurassic granite in the east. Re-run: in merge mode, after adding sheet GF12 (which sorts before GF13) the same 'Qa' comes out as 4 instead of 1, so a raster regenerated to extend coverage is silently incompatible with the model trained last month and with every class label already written into the report.
- 제안 수정: Allocate codes from a deterministic, content-derived order (e.g. sorted(unique keys) over all selected layers) and share one mapping across every output of a run: in per-layer mode build the mapping once for all selected layers and pass it into each call. Persist the mapping next to the output and reuse it when a *_mapping.csv already exists, so a re-run keeps existing codes and only appends new ones. State in the help that codes are only valid together with the CSV produced by that same run.
  - 검증: likely: The mechanism is real and I could not refute it. The counter (:1058) is genuinely per-call, allocation is genuinely in feature-encounter order (:1114-1120), per-layer mode genuinely calls the builder once per output (:1453), merge-mode allocation genuinely depends on the (region, name) sort …
  - 검증: certain: The failure constructs concretely and reproduces exactly as claimed.

Exact inputs that trigger it: two KIGAM 1:50,000 sheets loaded from ZIP into groups KIGAM_GF13_청주 and KIGAM_GF12_조치원; Litho polygon layers whose value field is a DBF String (SIGN with values Qa / Jbgr / PCEgn / Kav, or LI …
  - 검증: likely: The defect is real and I reproduced it. But three load-bearing claims in the write-up are wrong, and each one cuts the impact.

(1) "Nothing ... discloses this" / "Persist the mapping next to the output" is already done. `_write_mapping_csv` (1142-1170) writes `os.path.splitext(out_path)[0] …

#### [major] GEO-05 — Layer CRS is never validated; a sheet with a missing or unrecognised .prj yields a raster with no CRS and is reported as success

- 위치: `tools/geology_zip_dialog.py` :418-424, 1016-1030, 1216-1219, 1428
- 문제: From load to output nothing ever asks whether the layer has a usable CRS. A shapefile extracted without its .prj (a re-packed ZIP, or an entry lost to the filename decoding in GEO-12) gives an invalid QgsCoordinateReferenceSystem; _build_numeric_merge_layer then omits ?crs= from the memory URI and skips setCrs (lines 1023-1030), _rasterize_layer records authid='' and skips the geographic-units branch entirely (the guard at line 1230 requires crs.isValid()), and gdal:rasterize writes a GeoTIFF with no projection. The run ends with '완료: 래스터 생성' (line 1428). The assumption is invisible in every artefact: the .tif carries no CRS, the AAIGrid branch writes no usable .prj sidecar, and the layer metadata records only field and pixel size.
- 실패 시나리오: A sheet whose Litho.prj is absent but whose coordinates are EPSG:5186 metres: pixel 10 m produces a numerically fine but CRS-less geology.tif, added to the project as valid. Feed it to this plugin's own align/export, which calls gdal:warpreproject with "SOURCE_CRS": None (tools/align_export_dialog.py:836) — with no source SRS the geology grid is either refused by GDAL or resampled as though it were already in the reference CRS, i.e. misregistered against the DEM by the full difference between the two projections, with a manifest that still lists it as a normal aligned predictor. Second variant: the same sheet delivered in a geographic CRS without a .prj — crs.isValid() is False so the 10 is treated as 10 *degrees*; the plugin's own preflight computes cols=ceil(0.25/10)=1 and passes, while …
- 제안 수정: After loading each SHP, check layer.crs().isValid() and refuse (or prompt for a CRS) with an explicit message naming the file; in _rasterize_layer, abort when the input layer has no valid CRS rather than emitting a CRS-less raster; and make the preflight use the same rounding GDAL uses (int(0.5 + w/res)) so the 'CRS 단위/해상도 불일치' guidance actually fires for sub-half-pixel extents.
  - 검증: likely: I could not refute the core claim. Every guard I looked for is absent. :423 checks only layer.isValid(), which for a shapefile is independent of the .prj — a sheet with no .prj loads as a valid layer with an invalid CRS and is added at :426 via QgsProject.addMapLayer(layer, False), which (un …
  - 검증: certain: REAL — I can construct it end to end, and the codebase's own sibling tool proves the authors consider this condition a refusal case.

CONSTRUCTION (variant 1, the one that matters)

Inputs: a ZIP containing Litho.shp/.shx/.dbf with polygon geometry and integer field LITHOIDX, and NO Litho.p …
  - 검증: certain: Real, correctly graded major, and the finding actually understates its own mechanism.

Impact for someone publishing. The pixel values and the geotransform are numerically fine; what is missing is the declaration of which CRS those coordinates are in, and that omission is invisible in every …

#### [major] GEO-06 — Writing the code mapping CSV fails silently, leaving an integer raster nobody can decode and no message of any kind

- 위치: `tools/geology_zip_dialog.py` :1150-1171, 1426-1428, 1485-1487
- 문제: _write_mapping_csv swallows every exception and returns None, and the caller only reports the CSV when it exists. For a string-coded layer the CSV is the only artefact that says what the integers mean (GEO-04 shows the numbering is run-specific), yet its absence produces no warning, no log line — not even the [swallowed] line that release 0.1.3 claims it added everywhere ('every deliberately swallowed exception now records a [swallowed] line', metadata.txt:22). The same silence covers the early return at line 1150-1151, which is hit when every feature was dropped (GEO-07).
- 실패 시나리오: Output folder is a read-only network share, a OneDrive path locked by sync, or a Windows path where <raster>_mapping.csv exceeds MAX_PATH; gdal_rasterize (running in its own process with its own path handling) writes geology.tif successfully, open() raises PermissionError/OSError, and the user sees only '완료: 래스터 생성: ...geology.tif'. They hand a raster of 1..37 to a colleague with no legend at all; the classes cannot be reconstructed afterwards because the numbering depends on the feature order of that particular run.
- 제안 수정: Log the exception with log_swallowed and, when the CSV cannot be written for a raster whose codes were generated (any non-numeric field, or any run where mapping is non-empty), surface it with push_message at warning level — or treat it as a failed run and delete/flag the raster, since a categorical raster without its legend is not a usable deliverable.
  - 검증: likely: I could not refute the core defect, but I refuted two of its supporting claims and the severity.

STANDS: `_write_mapping_csv` (1142-1171) discards every failure — both the exception path and the zero-byte path at 1167-1169, where the code actually *checks* whether the file was written and t …
  - 검증: certain: CONSTRUCTED. Setup: KIGAM GF13 Litho polygons, field = LITHONAME (string codes Qa/Jbgr/PCEgn/...), merged single-raster mode, output C:\...\geology.tif. Path: _build_numeric_merge_layer takes the non-numeric branch (1113-1120) and assigns run-order integers; _rasterize_layer runs gdal:raste …
  - 검증: likely: The finding is real and accurately quoted. _write_mapping_csv swallows every exception with a bare `return None` (1169-1171), and both callers gate the only log line on `if csv_path:` before unconditionally pushing "완료". I confirmed the CSV is genuinely the only artefact that decodes a strin …

#### [major] GEO-07 — Features are dropped from the burn for four different reasons, and none of them is counted or reported

- 위치: `tools/geology_zip_dialog.py` :1062-1065, 1083-1102, 1122-1130
- 문제: Features with a NULL/blank value, with a geometry that fails to reproject, or whose value cannot be parsed as a number are skipped one by one, and a whole layer is skipped when its geometry type differs from layers[0]'s. counts[] only counts what was written, so nothing anywhere states how many features (or which layer) did not make it into the raster; pr.addFeatures([nf]) at line 1104 is not checked either. The run ends with an unqualified '완료'. Combined with GEO-01 the dropped polygons do not become NoData — they become class 0.
- 실패 시나리오: (a) Merge mode, value field LITHOIDX, where one selected sheet stores that column as text codes while the first-selected sheet stores it as an integer: `numeric` is decided from layers[0] only (line 1059), so every feature of the second sheet hits int(float('Kgr')) -> ValueError -> continue. The second sheet contributes nothing to the raster, its codes are missing from the mapping CSV, and the user is told the merge completed. (b) Any Litho polygon with a NULL value field (water bodies, unmapped/covered ground) is dropped; those cells read 0, a code that appears in no CSV row, and a model trained on the export treats them as a real lithology class.
- 제안 수정: Accumulate a per-reason drop counter inside _build_numeric_merge_layer, return it, and report it in the completion message ('n features skipped: m NULL value, k reprojection failures, ...') plus a row in the mapping CSV; check the boolean returned by pr.addFeatures; decide `numeric` from the field type across all selected layers (and refuse when they disagree) instead of from layers[0].
  - 검증: certain: I tried to refute this and could not. No guard exists anywhere upstream or downstream.

WHAT I CHECKED FOR A REFUTATION, AND WHY EACH FAILS

1. The caller (_run_rasterize, 1357-1368) validates only that a field NAME exists. _choose_common_field:950 returns the user-chosen field if `all(lyr. …
  - 검증: certain: REAL, and I can construct it two ways. One correction to the title is needed.

CONSTRUCTION (b) — the fully silent one, and the cleanest.
Inputs: one KIGAM 1:50,000 Litho sheet loaded via this dialog's ZIP loader. The sheet has no LITHOIDX/AGEIDX column, so _choose_common_field (line 958 pr …
  - 검증: likely: The finding is real and current, but its problem statement is overstated in two places, and only one of its four drop paths carries the impact.

WHAT SURVIVES (this is the whole of the impact). Two per-feature drops are genuinely silent and genuinely reachable:
- L1090-1091 `if val is None o …

#### [major] GEO-08 — ASCII Grid export of a geographic-CRS sheet writes a non-standard dx/dy header that ArcGIS and MaxEnt cannot read, and reports success

- 위치: `tools/geology_zip_dialog.py` :1230-1245, 1186-1208
- 문제: For a geographic CRS the pixel is converted to degrees separately for longitude and latitude, so cell_w != cell_h by construction (at lat 36.5 the 10 m pixel becomes dx=0.000111618269, dy=0.000090115848 — a ratio of 1.2386, far above AAIGrid's 1e-7 squareness tolerance). GDAL's AAIGrid CreateCopy (frmts/aaigrid/aaigriddataset.cpp:1340-1371) then writes 'dx'/'dy' instead of 'cellsize' and warns in its own log that 'Most ASCII Grid readers (ArcGIS included) do not support the DX and DY parameters'. processing.run does not raise on a CPLError warning, and the only post-check is os.path.exists, so the tool reports '완료: 래스터 생성'. The comment at line 1181-1185 states the .asc path exists because it is 'the format MaxEnt actually consumes' — the file produced on this path is not that format.
- 실패 시나리오: A KIGAM sheet whose .prj is a geographic CRS (EPSG:4326/4737), pixel 10 m, output format 'ASCII Grid (*.asc)'. The result opens fine in QGIS (GDAL's own driver reads dx/dy) and the plugin says success, but its header reads `ncols 2240 / nrows 2775 / xllcorner ... / dx 0.000111618269 / dy 0.000090115848`. MaxEnt rejects it, or a reader that skips unknown keys falls back to a default cellsize and silently georeferences the entire lithology grid wrong.
- 제안 수정: Refuse the .asc format when the source CRS is geographic (the tool already detects that at line 1230) and tell the user to reproject to a metric CRS — the same guard tools/distance_raster_dialog.py already applies; or force square cells (use one degree size for both axes) before the AAIGrid CreateCopy. Also surface the existing metres->degrees conversion in the message bar, not only in the log.
  - 검증: certain: I could not refute it. Every claim in the finding checks out against the current file and against GDAL's actual source, and the failure is reachable with no guard in between.

The chain is real and unbroken: .asc output recurses through the geographic-CRS branch at line 1231, which by const …
  - 검증: certain: CONSTRUCTED AND CONFIRMED. Concrete inputs: load a KIGAM Litho polygon layer whose .prj is geographic (EPSG:4326 or Korean 2000 geographic EPSG:4737) — or untick "KIGAM only" and pick any EPSG:4326 polygon layer — field LITHOIDX, merge mode, pixel 10, NoData -9999, format "ASCII Grid (*.asc …
  - 검증: certain: CONFIRMED, and I am keeping it at major. Every factual claim in the finding checks out against the real code and the real GDAL source, including the two quoted degree constants and the quoted warning text. Nothing here is speculative: given a geographic-CRS source layer and the .asc format, …

#### [major] GEO-09 — Field auto-selection silently falls back to an arbitrary attribute and still tags the result as a lithology class raster

- 위치: `tools/geology_zip_dialog.py` :1440-1450, 958-962
- 문제: Two silent fallbacks. Per-layer mode: when the layer lacks the field the user explicitly chose in the combo, the choice is discarded without a word and, if none of the seven known names exists either, the FIRST attribute of the shapefile is burned. Merge mode: _choose_common_field ends with the alphabetically first common field. Either way the output is registered with kind='geology_class', units='class' (lines 1476-1482), which makes raster_semantics treat it as nominal downstream, and in per-layer mode the raster is named '{layer}_raster' with no indication of which field was used (merge mode at least appends '({field})' to the layer name). A numeric fallback such as an area or id column also passes through int(float(val)) at line 1096, so the 'class codes' are truncated measurements.
- 실패 시나리오: The user unticks 'Litho(폴리곤)만', selects a sheet-frame or boundary polygon layer alongside Litho, picks LITHOIDX in the combo, per-layer mode. For the layer without LITHOIDX the tool burns its first attribute — e.g. AREA (double) — producing Frame_raster.tif whose values are truncated square metres, a mapping CSV with thousands of one-feature 'classes', and metadata declaring it a categorical geology class layer that align/export will happily resample with nearest neighbour and export as a predictor named geology_class.
- 제안 수정: When the user's explicit field choice is missing from a layer, skip that layer with a visible warning instead of substituting; when no priority field exists, refuse the layer rather than taking fields()[0]/sorted(common)[0]; and always include the actual field name in the output raster's layer name and in the completion message. Also reject non-integer (Double) fields for a class raster, or state the truncation.
  - 검증: certain: I tried to refute this six ways and could not. There is no guard, no validating caller, no QGIS API that intercedes, and no tooltip, help line, log line, CSV column or layer name that discloses the substitution in per-layer mode.

The core defect does not even need the exotic AREA example. …
  - 검증: certain: CONFIRMED. The code is exactly as described and the failure is constructible step by step.

Concrete inputs: a KIGAM 1:50,000 ZIP containing GF13_Litho.shp (polygon, LITHOIDX/LITHONAME present) and GF13_Frame.shp (sheet-frame polygon, no lithology fields). Layer CRS is irrelevant here — the …
  - 검증: likely: The finding is real, mechanically exact, and survives the impact test — but it is major, not blocker, because the default configuration is safe.

WHY IT MATTERS FOR A PUBLISHED RESULT. The chain is complete and I verified each link. A user checks a Litho polygon plus a non-Litho KIGAM layer …

## 6. 코드 감사 findings — 아직 미검증 (110건)

검증 팬아웃이 사용량 한도로 완주하지 못한 영역입니다(주로 횡단 스윕). 같은 검증을 거친 167건 중 74%가 기각된 것을 감안하면 **아래 상당수도 기각될 가능성이 높습니다.** 착수 전 개별 재확인이 필요합니다.


### geochem

- **[blocker] G2** Class-break legends are inverted as if they were continuous ramps: every pixel of the top class is reported at the national maximum (1363 ppm Pb, 21100 ppm Zn, 51% Fe2O3)
  - `/home/user/archtoolkit/tools/geochem_polygonize_dialog.py` — The shipped presets are, by their own comments, PERCENTILE CLASS BREAK tables - a 10-class graduated choropleth. The code treats each break value as a continuous ramp anchor: a pixel painted in a class's flat colour is assigned that class's break value exactly, and pixels between two class colours are linearly interpolated to values that cannot exist. Both directions are wrong for a classed source …

### geology

- **[minor] GEO-10** Units narrower than one cell vanish from the raster while the mapping CSV still lists them with a feature count
  - `tools/geology_zip_dialog.py` — QGIS's gdal:rasterize only emits '-at' when its ALL_TOUCH parameter is true (rasterize.py:208-209); this call never sets it, so GDAL uses the default cell-centre rule — correct for a categorical map, but it means any polygon that no cell centre falls inside is dropped entirely. The pixel spin box accepts up to 10000 m (line 725) with no relation drawn to the map's minimum mappable unit, nothing co …
- **[minor] GEO-11** Mapping CSV is written as UTF-8 without BOM, unlike every other user-facing CSV in the plugin, so Korean lithology names arrive garbled in Excel
  - `tools/geology_zip_dialog.py` — The mapping CSV is the artefact that turns the raster's integers into lithology names for a report legend, and it is written without a BOM. Excel on a Korean Windows install opens a BOM-less CSV with the ANSI (cp949) code page, so every Hangul label is mojibake. The rest of this codebase already settled on the other convention for exactly this reason: covariate_report_dialog.py:447, align_export_d …
- **[minor] GEO-12** Shapefile attribute encoding is hard-coded to cp949 and ZIP entry names are decoded as cp437, with the module's own encoding-detection config left unused
  - `tools/geology_zip_dialog.py` — setProviderEncoding('cp949') overrides whatever the DBF itself declares (OGR's LDID/code-page detection) for every shapefile in the ZIP, with no fallback and no way to change it — the configured GEOLOGY_PROVIDER_ENCODING on line 92 is not even used, and the candidate-encoding list and preference weights defined right beside it are dead: grep shows each of GEOLOGY_CANDIDATE_ENCODINGS, GEOLOGY_ENCOD …
- **[minor] GEO-13** Extracted sheets are deleted after 90 days without the user ever being told they live in a managed folder
  - `tools/geology_zip_dialog.py` — KigamZipProcessor.__init__ runs the reaper on every '지질도 ZIP 불러오기' click, and _extract_dirs_in_use() only protects extracts referenced by the project open at that moment. The docstring's promise ('extracts referenced by projects the user still opens never expire') holds only for the currently open project — a saved project that is not open when some other project loads a ZIP is not consulted. Noth …

### align-export

- **[blocker] AE-01** Aspect (a circular variable in degrees) is bilinearly resampled, producing directions that point the wrong way
  - `tools/align_export_dialog.py` — The nearest/bilinear choice has exactly two branches: categorical -> nearest, everything else -> bilinear. Aspect is neither. tools/terrain_analysis_dialog.py:440 tags its aspect raster kind="aspect", units="deg", tool_id="terrain_analysis"; I executed is_categorical_meta on that exact dict and it returns False, so align/export sends RESAMPLING=1 (bilinear). Aspect in degrees is modular: 0 and 360 …
- **[major] AE-02** A raster with no ArchToolkit metadata falls into the unsafe branch: class codes are bilinearly blended and the manifest positively asserts categorical=no
  - `tools/align_export_dialog.py` — is_categorical_meta (tools/raster_semantics.py:43-55) decides only from meta["units"], meta["tool_id"] and meta["kind"]. get_archtoolkit_layer_metadata returns {} for any layer this plugin did not create (utils.py:437-445 returns {} when both tool_id and run_id are absent). I executed is_categorical_meta({}) and is_categorical_meta({"tool_id":"","kind":"","units":""}): both return False. Absence o …
- **[major] AE-03** Variable-key uniqueness is case-sensitive but the output filenames are not: on Windows/macOS one predictor's file is overwritten by another's data
  - `tools/predictor_naming.py` — `taken` is a Python set of str, so uniqueness is byte-exact and case-sensitive. The keys are then used verbatim as filenames. NTFS and the default APFS/HFS+ configuration are case-insensitive, and QGIS's two largest desktop platforms are Windows and macOS. I executed assign_variable_keys on a list containing an ArchToolkit layer with kind="slope" and a user layer named "Slope": it returns 'slope' …
- **[major] AE-04** The layer's QGIS CRS override is discarded: SOURCE_CRS=None with a bare file path means gdalwarp reprojects from the file's embedded CRS, not the one the user assigned
  - `tools/align_export_dialog.py` — Only the data-source path is handed to the algorithm, and SOURCE_CRS is explicitly None. In QGIS 3.40's warp.py the source CRS branch is `if sourceCrs.isValid(): arguments.append('-s_srs')` - with None nothing is emitted, so gdalwarp falls back to whatever CRS is embedded in the file. A CRS assigned in Layer Properties -> Source (`QgsRasterLayer.setCrs`) is a project-level override: it is stored i …
- **[major] AE-05** A source raster that does not overlap the reference grid publishes an all-NoData predictor and is reported as successfully aligned
  - `tools/align_export_dialog.py` — _validate_warp_output checks the container (CRS, grid, band count, NoData declaration) and that a 64x64 decimated block is readable - it never checks that the block, or the raster, contains a single valid pixel. gdalwarp with an explicit -te and -tr creates the full requested grid regardless of whether the source intersects it; the uncovered area is simply left at the destination NoData, and no di …
- **[major] AE-06** The dialog, the help and the README all state NoData is part of the common reference grid; the code deliberately never unifies it
  - `tools/align_export_dialog.py` — Both user-facing strings enumerate four properties of the single reference grid: CRS, extent, pixel size and NoData. Three of those really are common to every output and are validated per file. NoData is not, by design and for good reasons documented at lines 183-196: a categorical output keeps its source's own value when the bands agree ("source"), otherwise gets a per-raster sentinel computed fr …
- **[minor] AE-07** A float-typed categorical raster is reported to the user with the wrong reason for having no NoData
  - `tools/align_export_dialog.py` — choose_nodata_sentinel returns None for three distinct causes: (a) the data already spans the whole type range, (b) the band type is floating point (INTEGER_TYPE_RANGES has no Float32/Float64 entry, by deliberate design per raster_semantics.py:58-61), and (c) _band_type_name could not identify the type at all and returned "". The caller collapses all three into the single reason string "no_safe_va …
- **[minor] AE-08** The manifest describes each output with a single nodata cell, which cannot be true of a multi-band output whose bands carry different NoData values
  - `tools/align_export_dialog.py` — The validation layer explicitly models NoData as per-band: _expected_nodata_values returns the source's own per-band tuple when nodata is None, and the docstring at lines 266-270 says collapsing that to a single value "would reject a perfectly good multi-band output whose bands declare different NoData values". The manifest does not have that resolution - _write_manifest emits one nodata cell per …

### demgen

- **[blocker] DEMGEN-01** 2D contour layers silently produce an all-NoData DEM reported as "DEM 생성 완료!" — including the plugin's own 등고선 추출 output
  - `tools/dem_generator_dialog.py` — When none of five exact, case-sensitive field names is found the code falls back unconditionally to valueSource=1 (QgsInterpolator::ValueZ) — geometry Z — without ever checking that the layer is 3D. QGIS rejects every such feature: QgsInterpolator::addVerticesToCache does `case Z: if (!geom.constGet()->is3D()) return false;` (qgsinterpolator.cpp) and QgsTinInterpolator::insertData does `case Value …
- **[major] DEMGEN-02** Kriging (Lite) does not honour the input spot heights: a 30.00 m surveyed benchmark comes back as 25.05 m at its own location
  - `tools/kriging_lite.py` — The covariance matrix uses C(0)=partial_sill+nugget on the diagonal, but the right-hand side cvec is taken from the continuous function, which returns partial_sill (nugget omitted) at h=0. The two sides therefore use different definitions of C(0). Ordinary Kriging as published by Matheron 1963 / Cressie 1993 — the citation carried in the method name 'Kriging (Lite, Ordinary)' (dem_generator_dialog …
- **[major] DEMGEN-03** The DXF layer-code filter is applied to ANY selected layer that has a field named "Layer", using checkbox defaults the user may never have opened
  - `tools/dem_generator_dialog.py` — The DXF code table is checked by default (DXF_LAYER_INFO defaults True for F0017111, F0017114, F0027217 at lines 83/86/89) and get_selected_layer_codes deliberately returns checked codes from BOTH eras regardless of which tab is visible. The resulting subset string is then applied to whatever layer the user picked in the list widget, on the sole condition that the layer happens to own a field call …
- **[major] DEMGEN-04** A stale DEM left at the output path from an earlier run is re-loaded and reported as this run's result
  - `tools/dem_generator_dialog.py` — os.path.exists(output_path) is treated as proof that this run produced the file, but the publish at line 1083 is conditional on the staged file existing. If the interpolation returned without writing anything, staging_out is never promoted and line 1087 still finds the previous run's raster sitting at output_path. QgsGridFileWriter::writeFile returns 1/2 on a failed raster creation and QgsTinInter …
- **[major] DEMGEN-05** TIN/IDW output pixels are not the requested pixel size, and are not square — but the metadata records the requested size as fact
  - `tools/dem_generator_dialog.py` — PIXEL_SIZE is not the cell size QGIS produces. qgis:tininterpolation and qgis:idwinterpolation use it only to derive counts — `columns = max(ceil(bbox.width()/pixel_size), 1)`, `rows = max(ceil(bbox.height()/pixel_size), 1)` — and QgsGridFileWriter then divides the extent by those counts: `mCellSizeX(extent.width()/nCols)`, `mCellSizeY(extent.height()/nRows)` (340_qgsgridfilewriter.cpp:32-33). The …
- **[major] DEMGEN-06** Merging a 2D contour layer with a 3D one silently assigns 0 m elevation to every 2D vertex
  - `tools/dem_generator_dialog.py` — QgsMergeVectorAlgorithm promotes the output WKB type to Z as soon as ANY input has Z (merge340.cpp:139-143) and then pads the others: `if (hasZ && !g.constGet()->is3D()) { g.get()->addZValue(0); }` (merge340.cpp:238-242). The features from the 2D input therefore arrive in the merged GeoPackage with Z=0. QGIS emits an informational 'Found a layer with Z values, upgrading output type' line, but proc …
- **[minor] DEMGEN-07** When the Kriging Z field is auto-detected, nothing records which attribute the DEM was actually built from
  - `tools/dem_generator_dialog.py` — The default combo entry '자동(추천)' carries currentData() == "", so value_field stays None and kriging_lite._auto_value_field (kriging_lite.py:59-91) silently picks the first of twelve candidate names present on the layer — Z_COORD, z_coord, Elevation, ELEVATION, elev, ELEV, height, HEIGHT, 표고, 고도, z, Z — with no type or plausibility test beyond float-convertibility. The name it settled on is never s …
- **[minor] DEMGEN-08** DXF files that fail to load produce no message at all
  - `tools/dem_generator_dialog.py` — An invalid QgsVectorLayer is not an exception, so the `if layer.isValid():` branch simply falls through with no else. When every selected file fails, loaded_count stays 0 and the trailing `if loaded_count > 0:` suppresses the only remaining message, so the button does nothing visible. A partial failure is equally hidden: selecting five files of which two fail reports "3개 DXF 로드 완료" without naming …

### ai-context

- **[blocker] AI-CTX-01** "Nearest site" and the reference-site classification counts are taken from the first 120 features in file order, not the nearest 120
  - `tools/ai_aoi_summary.py` — _reference_sites_summary stops collecting at max_items (default 120, from spinReferenceMax in ai_report_dialog.py:379) and only then sorts `items` by distance_to_aoi_m. The features arrive in provider order from a bbox-filtered QgsFeatureRequest (line 652/666), which is FID/spatial-index order, not distance order. So the 120 kept sites are an arbitrary subset of the sites in the AOI buffer, and th …
- **[blocker] AI-CTX-02** A Gemini response truncated at maxOutputTokens is presented as a finished report ('완료') and written to report.md
  - `tools/ai_gemini.py` — generate_text parses candidates[0].content.parts and returns the text with error=None, never inspecting candidates[0]["finishReason"]. `grep -rn "finishReason|MAX_TOKENS|usageMetadata" tools/` returns nothing in the whole repository. When Gemini stops because it hit the cap it still returns the partial text together with finishReason "MAX_TOKENS" (same for "RECITATION" and for a mid-stream "SAFETY …
- **[major] AI-CTX-03** '선택된 피처만 사용' with an empty selection silently analyses the entire AOI layer while the report still says only the selection was used
  - `tools/ai_aoi_summary.py` — In _unary_union_geoms, `selected_only=True` combined with an empty selection falls through to `layer.getFeatures()` - every feature in the layer. The AOI geometry, its area, the buffer and therefore every downstream statistic are then computed over the whole layer, while ctx["options"]["selected_only"] is still written as True (line 1333) and ai_local_summarizer.py:351-354 renders that as the head …
- **[major] AI-CTX-04** Per-layer length/area are measured in the layer's own CRS with no geographic guard, so a WGS84 layer yields square degrees in fields named total_area_m2 / total_length_m
  - `tools/ai_aoi_summary.py` — build_aoi_context enforces a metric CRS for the AOI only (line 1155, is_metric_crs). Scanned layers may be in any CRS, and _vector_layer_stats_in_geom builds its QgsDistanceArea from layer.crs(). QgsDistanceArea.measureArea/measureLength return metres only when an ellipsoid is actually in effect; with the project ellipsoid set to 'NONE' (a normal, selectable QGIS project setting) setEllipsoid('NON …
- **[major] AI-CTX-05** The 20,000-feature scan cap truncates feature counts and length/area sums, and the context and CSV carry no truncation flag
  - `tools/ai_aoi_summary.py` — After 20,000 features the scan stops, but `features`, `total_length_m`, `total_area_m2` and every entry in `numeric_fields` are emitted as if they were complete. _reference_sites_summary sets an explicit `truncated` flag (line 956) that the local report reads; the layer stats set nothing equivalent. Consequences: (a) the context JSON handed to Gemini (ai_report_dialog.py:718) presents a capped cou …
- **[major] AI-CTX-06** Raster min/mean/max are computed from a nearest-neighbour subsample with no record that the raster was decimated
  - `tools/ai_aoi_summary.py` — When the AOI window exceeds 4 Mpixels the band is read through a smaller buffer, which is GDAL nearest-neighbour decimation - every (scale x scale) block contributes one sample. min and max are therefore sample extrema and are systematically biased inward, and count is a sample count, not the pixel count in the AOI. The returned dict records nothing about this: keys are the bare `count`, `min`, `m …
- **[minor] AI-CTX-07** gt_0_5_pct is labelled a 'mask/visibility ratio' but its near-binary detector is max-relative while its threshold is a hard-coded 0.5
  - `tools/ai_aoi_summary.py` — Two mismatches. (1) The gate accepts any raster whose valid cells are >=98% {0} union {vmax} - that admits a three-valued categorical raster whose middle class is small, and admits a zero-padded continuous raster (a GDAL output written without a NoData value). It is not a binary-viewshed test. (2) Having detected 'binary' relative to vmax, the measurement then thresholds at an absolute 0.5, which …
- **[minor] AI-CTX-08** Numeric-field statistics are silently capped at 12 (8 in the local report) and the id-field regex discards single-letter element columns
  - `tools/ai_aoi_summary.py` — Two silent drops in the numeric statistics the report is built on. First, _classify_fields keeps at most 12 numeric fields and _layer_stats_lines prints at most 8 of those, with no '외 N개 필드 생략' note anywhere in the context, the CSV or the Markdown - so a reader cannot tell whether a column was absent from the layer or dropped by a cap. Second, the id-field regex is anchored and case-insensitive, s …
- **[minor] AI-CTX-09** The 40-layer cap drops layers in layer-id dictionary order, including layers the user explicitly picked, with no per-run record of what was dropped
  - `tools/ai_aoi_summary.py` — build_aoi_context stops after max_layers summaries. In the default 'auto' scope the candidate order is QgsProject.mapLayers() key order, i.e. alphabetical by layer id - unrelated to the layer tree, to relevance or to distance from the AOI - so which layers survive is arbitrary. In the 'layers' scope the user picks the layers explicitly through _LayerMultiSelectDialog (ai_report_dialog.py:583-596), …

### covariate-distance-contour

- **[blocker] DIST-01** Polygons narrower than a cell are silently dropped by the default pixel-centre burn rule, inflating every distance
  - `tools/distance_raster_dialog.py` — QGIS's gdal:rasterize exposes an ALL_TOUCH parameter (verified in release-3_40 rasterize.py line 272: `if self.parameterAsBoolean(parameters, self.ALL_TOUCH, context): arguments.append("-at")`). This call does not pass it, so it defaults to False and GDAL burns a polygon only where a pixel CENTRE falls inside it. Any polygon narrower than one cell burns nothing along most or all of its length. The …
- **[blocker] DIST-02** Nothing checks that the burn produced any target cell, so an all-NoData distance raster is reported as a finished predictor
  - `tools/distance_raster_dialog.py` — The only post-condition tested is that a file exists. The code's own comment at lines 355-360 identifies exactly this risk - "with nothing inside at all, the output would be all NoData and still report success" - but the guard that was written for it (lines 361-379) only tests bounding-box intersection, which is a different condition. GDAL's behaviour is confirmed in alg/gdalproximity.cpp line 384 …
- **[blocker] DIST-03** A non-square reference grid makes every distance wrong: gdal_proximity scales both axes by the X pixel size
  - `tools/distance_raster_dialog.py` — The tool accepts px_x != px_y without comment, passes both to gdal:rasterize ("WIDTH": px_x, "HEIGHT": px_y, line 389-390) so the burned mask inherits the rectangular cell, and then asks gdal:proximity for georeferenced distances. GDAL master alg/gdalproximity.cpp lines 119-127 shows what that does:

    if (std::abs(adfGeoTransform[1]) != std::abs(adfGeoTransform[5]))
        CPLError(CE_Warning, …
- **[blocker] COV-01** Cancelling the sampling silently truncates the study area and still produces a full correlation/VIF report
  - `tools/covariate_report_dialog.py` — `break` abandons the scan and returns whatever rows were gathered, and _on_run (lines 302-310) cannot distinguish a truncated sample from a complete one: its only test is `matrix.shape[0] < 10`. Above that threshold it computes the correlation matrix and VIFs and renders the report as if nothing happened. Crucially the scan is ordered - `ys` ascends from extent.yMinimum() (line 323) - so a cancell …
- **[major] DIST-04** A user-typed variable name can make a continuous distance raster be classified as categorical downstream
  - `tools/distance_raster_dialog.py` — `key` is `distance_<whatever the user typed>` (tools/predictor_naming.py:169-182), and it is written straight into the `kind` metadata field. tools/raster_semantics.py:29-31 matches `kind` by SUBSTRING against CATEGORICAL_KIND_HINTS = ("class", "category", "categor", "litho", "geolog", "slope_position"). So any distance variable whose name contains one of those fragments is classified as a raster …
- **[major] COV-02** "모두 선택" checks categorical rasters, and a categorical raster without ArchToolkit metadata is never detected at all - Pearson r over class codes is then reported as an ordinary correlation
  - `tools/covariate_report_dialog.py` — The categorical exclusion is only a default check-state (line 233) plus a label suffix (line 230). _check_all ignores the exclusion entirely, unlike its sibling _check_arch_only (lines 248-252) which does honour the Qt.UserRole+1 flag. Worse, the detection depends on ArchToolkit metadata: tools/utils.py:437-445 returns {} for any layer without an archtoolkit/tool_id or run_id custom property, so a …
- **[major] COV-03** Listwise deletion is applied but never quantified: one high-NoData variable silently shrinks and geographically restricts the sample for every variable
  - `tools/covariate_report_dialog.py` — A grid point is kept only if every selected raster returns a valid value. That is a defensible method and the help at line 474 does say "모든 변수가 유효한 점만 사용합니다" - but nothing anywhere records HOW MUCH was lost or WHICH variable lost it. The report prints only the surviving count (line 379: "변수 {k}개 · 유효 표본 {n:,}점"); the number of grid points attempted (nx*ny), the retention rate, and the per-variable …
- **[major] COV-04** The sampling grid ignores the raster cell size, so the reported "유효 표본 N점" can exceed the number of distinct cells sampled
  - `tools/covariate_report_dialog.py` — The lattice spacing is derived only from the extent and the requested point count; the rasters' pixel sizes are never consulted. When the spacing falls below the cell size, several lattice points land in the same cell and provider.sample() returns the identical value for each, so the same observation is entered into the correlation matrix multiple times. The report then states that count as the sa …
- **[major] CONT-01** Contour interval is in the DEM's vertical unit but the layer name, the completion message and the machine-readable metadata all assert metres
  - `tools/contour_extractor_dialog.py` — gdal_contour's -i is expressed in whatever unit the DEM band holds; the DEM's vertical unit is never read or checked. The help at line 100 admits this honestly ("등고선 간격은 DEM의 높이 단위(보통 m)를 기준으로 합니다"), but four other places state metres as fact: the UI label "등고선 간격 (m):" (contour_extractor_dialog_base.ui line 174), the temp filename, the layer name 등고선_{interval}m, the completion message, and - the …
- **[minor] COV-05** The AOI restricts sampling to the bounding rectangle only, and neither the label nor the help says so
  - `tools/covariate_report_dialog.py` — resolve_aoi_extent returns geom.boundingBox() (tools/aoi_extent.py:186), so the AOI polygon's shape is discarded and only its envelope is used. The control is labelled "AOI 제한(선택):" with no tooltip, and the help HTML (lines 463-477) does not mention the AOI at all. The rest of this codebase is careful to say 범위 when it means the rectangle - tools/ahp_suitability_dialog.py:355 labels the equivalent …
- **[minor] COV-06** Correlation-matrix headers are truncated to 10/14 characters, so two variables can appear under identical labels
  - `tools/covariate_report_dialog.py` — Column headers are cut to 10 characters and row headers to 14, with no ellipsis, no tooltip and no legend mapping the abbreviations back to full names. The VIF table immediately above uses full names (line 393), so the two tables in the same report label the same variables differently. Distance-raster layers are exactly the case that collides, because they all share the `distance_` prefix (9 chara …
- **[minor] CONT-02** A contour run that produces zero lines is reported as 완료 and adds an empty layer
  - `tools/contour_extractor_dialog.py` — The success test is file existence plus layer validity. gdal_contour creates the GPKG table and the ELEV field even when no contour level falls inside the DEM's elevation range, so the layer is valid with zero features and passes both tests. featureCount() is never consulted. The dialog then accept()s and closes, so the user is left with an empty layer in the tree and a green 완료 message.
- **[minor] CONT-03** No way to declare a NoData value, and passing layer.source() discards any NoData the user set on the QGIS layer
  - `tools/contour_extractor_dialog.py` — IGNORE_NODATA=False plus NODATA=None means gdal_contour uses only the NoData value DECLARED IN THE FILE (confirmed in QGIS release-3_40 contour.py: `if nodata is not None: arguments.append(f"-snodata {nodata}")`). The comment claims this protects against -9999/-32768 fill, but it only does so when the file itself declares that fill as NoData. A NoData value the user configured in QGIS Layer Proper …
- **[minor] REF-01** REFERENCES.md promises a source for every algorithm the plugin calls, but the Distance tool (gdal:proximity) and the Correlation/VIF report have no entry
  - `REFERENCES.md` — The document states an explicit contract and the section list (verified by `grep -n '^## '`) has no heading for either tool. tools/distance_raster_dialog.py:385 and :419 call gdal:rasterize and gdal:proximity via processing.run, which the legend defines as category (A). tools/covariate_report_dialog.py:100-123 implements VIF = 1/(1-R^2) in Python, which the legend defines as category (B), and the …

### styling-core

- **[blocker] STYLE-01** Re-running map styling silently erases any user layer parked in the style group from the Layers panel
  - `/home/user/archtoolkit/tools/map_styling_dialog.py` — _teardown_style_group only re-parents layers found inside a sub-group whose name matches the literal string "원본 레이어 (숨김)". Every other layer node still inside the style group is destroyed by root.removeChildNode(group) at line 451. Layers tagged tool_id="map_styling" are deliberately deregistered (fine, they are this tool's own outputs), but a *user's own* layer that sits anywhere else in the grou …
- **[major] STYLE-02** Applying styling silently relocates the user's source layers into a hidden group and resets their visibility, contradicting the shipped changelog
  - `/home/user/archtoolkit/tools/map_styling_dialog.py` — Every selected layer is torn out of wherever the user had it in the layer tree and re-added under a new, switched-off group. Because a brand new QgsLayerTreeLayer is constructed, the node's own state is not carried over: QgsLayerTreeLayer(layer) is checked by default, so a layer the user had deliberately switched OFF comes back switched ON, and its position, its parent group and its expanded/legen …
- **[major] STYLE-03** Building polygons are always re-buffered by 0.01 map units, inflating every footprint (≈1.1 km in a geographic CRS)
  - `/home/user/archtoolkit/tools/map_styling_dialog.py` — poly_geom is only ever computed inside the `geom.type() == LineGeometry` branch. Any input that is already a polygon (a shapefile of 건물 footprints, or a DXF whose closed polylines were imported as polygons) therefore falls through to the else branch and is passed through QgsGeometry.buffer(0.01, 2) — a positive 0.01-map-unit outward buffer with only 2 segments per quarter circle — instead of being …
- **[major] STYLE-04** Multi-part building outlines are concatenated into one ring, producing self-intersecting footprints
  - `/home/user/archtoolkit/tools/map_styling_dialog.py` — For a multi-part line feature every part's vertices are flattened into a single list and handed to fromPolygonXY as ONE exterior ring. Separate parts (an outer wall and an inner courtyard, or two wings of the same building block) are therefore joined by a straight segment that jumps from the end of one part to the start of the next, producing a self-intersecting (bowtie) polygon. fromPolygonXY doe …
- **[major] STYLE-05** A missing or malformed map_styling_codes.json silently falls back to built-in defaults while the dialog still shows the file path
  - `/home/user/archtoolkit/tools/map_styling_dialog.py` — _load_code_config records why it fell back in self._code_config_load_error, but the constructor never surfaces it — only reload_code_config() (line 256-257), which runs solely when the user clicks 다시 불러오기. _sync_code_config_ui unconditionally writes the JSON path into lblCodeConfigPath, so the dialog asserts that this file is the mapping in force even when the file is missing, unreadable, or not a …
- **[major] STYLE-06** DEM grayscale layer is rendered with no contrast enhancement, so it is not stretched to the DEM's value range
  - `/home/user/archtoolkit/tools/map_styling_dialog.py` — QgsSingleBandGrayRenderer constructed this way has no QgsContrastEnhancement attached (QGIS only attaches one through QgsRasterLayer.setDefaultContrastEnhancement / the style UI, never through setRenderer). The raw band value is therefore used directly as the 0-255 grey level, with no stretch to the band's minimum/maximum — note that the colour layer immediately below, at lines 517-531, does call …
- **[major] STYLE-07** Exported roads/rivers/buildings QML hard-code the field name "Layer" and have no ELSE rule, so re-applying a preset can render nothing
  - `/home/user/archtoolkit/tools/map_styling_dialog.py` — The preset templates are always built against a field literally named "Layer", while the tool's own detect_code_field (line 551) accepts five different names: 'Layer', 'layer', 'RefName', 'LayerName', 'LAYER'. The root rule is created with no symbol and no ELSE child, so a feature that matches none of the code rules is simply not drawn. Applying an exported .qml to any layer whose code field is no …
- **[major] STYLE-08** "프리셋을 저장했습니다" is shown even when every file failed to write
  - `/home/user/archtoolkit/tools/map_styling_dialog.py` — Every write in export_qml_preset is individually guarded: _save_named_style returns False on failure (760-770) and each json.dump is wrapped in try/except with log_swallowed. The `exported` list is accumulated but never consulted. The final push_message reports success at level=0 (green) unconditionally, so a run in which zero files were produced is indistinguishable from a complete export. The us …
- **[minor] STYLE-09** Layers with an unrecognised code field, and features whose codes are absent from the JSON, are dropped with no count and no warning
  - `/home/user/archtoolkit/tools/map_styling_dialog.py` — Two silent filters operate on the user's data. (1) A selected layer whose attribute table has none of the five candidate names ('Layer', 'layer', 'RefName', 'LayerName', 'LAYER') is skipped by `continue` with no log and no message. (2) Only features whose code is literally in the JSON list are collected; every other code in the DXF is dropped. Neither the number of layers skipped, nor the number o …
- **[minor] STYLE-10** DEM styling applies a z-factor-1 hillshade to any DEM, including a geographic-CRS one, with no CRS guard
  - `/home/user/archtoolkit/tools/map_styling_dialog.py` — QgsHillshadeRenderer computes slope from elevation differences divided by the pixel size expressed in the layer's map units, with a default z-factor of 1. When the DEM is in a geographic CRS the pixel size is in degrees while the elevations are in metres, so the computed gradients are wrong by a factor of roughly 1e5 and the shading saturates. This module performs no CRS check at all, although too …
- **[minor] STYLE-11** unload() never closes the live-log singleton, leaving a plugin window behind and duplicating it on reload
  - `/home/user/archtoolkit/arch_toolkit.py` — ArchToolkitLiveLogDialog is a module-level singleton parented to iface.mainWindow(), and ensure_live_log_dialog is called by four dialogs (dem_generator, cadastral_overlap, cost_surface, viewshed). unload() stops the log pump and tears down the three persistent tool dialogs, the toolbar, the menu and every QAction, but never touches _live_log_dialog, and the dialog has no WA_DeleteOnClose. Because …
- **[minor] STYLE-12** The plugin log file has no size cap or rotation, and the swallow-logger can write two lines per feature
  - `/home/user/archtoolkit/tools/utils.py` — The in-memory queue is bounded (_UI_LOG_QUEUE_MAX = 5000) and the live-log widget is bounded (setMaximumBlockCount(5000)), but the file sink is not: archtoolkit.log under the QGIS profile directory is appended to forever with no rotation, size check or truncation, and every one of the ~380 log_swallowed call sites added in 0.1.3 writes to it. _write_log_line re-opens and closes the file for every …
- **[minor] STYLE-13** Styling outputs are temporary scratch layers, which the tool never discloses
  - `/home/user/archtoolkit/tools/map_styling_dialog.py` — Every vector product of this tool is a memory (scratch) layer whose contents are not written anywhere; the DEM products are clones that reference the original raster. The completion message says a 통합 레이어 was created, the UI header promises 고고학 도면 표준 visualisation, and README.md line 166 describes the tool as bundling DXF layers into styled products — none of them says the result is discarded when …

### shared-core

- **[blocker] SC-01** tri_radius reports artificially smooth terrain next to a NoData boundary, as a real value, for the exact reason it NaNs the grid rim
  - `tools/terrain_math.py` — The rim of the grid is NaN'd because a truncated window "would be computed from a truncated neighbourhood and read as artificially smooth terrain" (line 127-128). A NoData boundary truncates the window in exactly the same way, but is not NaN'd: only `counts == 0` is. A cell with 15 valid neighbours out of 48 gets `sqrt(sq_total/15)` and is written out as an ordinary float, indistinguishable from a …
- **[major] SC-02** PER_CELL_BYTES is total process RSS divided by N, not marginal per-cell memory, so cost_budget over-predicts memory ~7x and refuses runs that fit - with no way to override
  - `tools/cost_budget.py` — The table divides *total process peak RSS* by the cell count. That is why the quoted figure falls from 240 to 168 to 128 B/cell as N grows - the ~30 MB Python+NumPy baseline is being amortised, exactly as the following sentence says ("Per-cell cost falls as fixed overhead amortizes") - and then the constant is set to the 1M-cell figure rounded UP to 160, which bakes that fixed baseline into a per- …
- **[major] SC-03** The runtime estimate shown before a cost-surface run covers one accumulation, but the worker runs up to four
  - `tools/cost_surface_dialog.py` — assess()/estimate_seconds() are defined for ONE full-grid accumulation of `cells` cells - cost_budget's own module docstring describes "a Dijkstra accumulation ... one pop and eight edge relaxations per cell", singular, and assess_batch exists precisely because "Time is cumulative" for repeated runs. The cost-surface dialog calls the single-run assess() and prints its `minutes` verbatim as "예상 소요 …
- **[minor] SC-04** resolve_aoi_extent reprojects only the AOI's vertices, so a few-vertex AOI box from a geographic CRS silently loses up to ~460 m off its southern edge with status OK
  - `tools/aoi_extent.py` — QgsGeometry.transform() moves the existing vertices and nothing else; the straight segments between them are re-drawn as straight segments in the target CRS, but their true images are curved. boundingBox() therefore returns the hull of the transformed VERTICES, which for a polygon whose extreme point lies mid-edge is strictly inside the true extent of the user's AOI. The module was written specifi …
- **[minor] SC-05** zt_curvature names Zevenbergen & Thorne (1987) but returns the negation of both equations they publish, and the one caller's provenance note misattributes the convention to ESRI
  - `tools/terrain_math.py` — Zevenbergen & Thorne (1987) publish profile curvature as -2(DG^2 + EH^2 + FGH)/(G^2 + H^2) and plan curvature as +2(DH^2 + EG^2 - FGH)/(G^2 + H^2). This code has the leading signs the other way round on both, which is ArcGIS's convention, not ZT's. The coefficients D, E, F, G, H themselves are exactly ZT's and are correct (I verified them analytically at cell = 1, 5 and 30 m), so this is purely th …
- **[minor] SC-06** Zero-weight edges are silently discarded by both Dijkstra paths, so a node can report degree 1 and closeness 0.0 in the same output row
  - `tools/network_metrics.py` — An edge whose weight is exactly 0 is dropped rather than traversed at cost 0, in dijkstra_weighted and again in betweenness_centrality_weighted, with nothing written anywhere - no log_swallowed, no counter, no note in the module docstring, which only says "Weighted variants (Dijkstra) drive the cost network". Dropping a non-finite or negative weight is defensible (Dijkstra has no answer for a nega …

### sweep-crs-units

- **[blocker] CRS-01** Curvature is computed with the AVERAGE of the two pixel sizes, but the kernel it is handed to documents that argument as the SQUARE cell size - a rectangular DEM yields curvature off by tens of percent, published as 1/m
  - `tools/terrain_analysis_dialog.py` — zt_curvature takes ONE cell size and uses it for both the x and the y second differences (L2 = cell*cell in both D and E, and cell in both G and H). Its docstring states the argument is the square cell size. The caller passes the arithmetic mean of |gt[1]| and |gt[5]| with no check that they are equal and no warning when they are not, so on a rectangular grid D is scaled by (dx/cell)^2 and E by (d …
- **[blocker] CRS-02** DEM generator has no CRS check at all, yet the dialog, the scale-derived recommendation and the layer metadata all assert metres - on a geographic input the pixel size is applied as degrees
  - `tools/dem_generator_dialog.py` — There is no isGeographic() and no is_metric_crs() anywhere in this file - the only crs() reference is 'CRS': selected_layers[0].crs() passed to the merge at :863. PIXEL_SIZE is handed straight to qgis:tininterpolation / qgis:idwinterpolation, which use it only to derive counts from combined_extent, so it is in the INPUT LAYER'S CRS UNITS. Meanwhile the UI label says '출력 해상도 (m):', the auto-filled …
- **[blocker] CRS-03** is_metric_crs accepts EPSG:3857, so every tool whose only CRS check is that helper silently reports Web Mercator grid distances as ground metres - 26% long, 59% over on area, at Korean latitudes
  - `tools/utils.py` — The helper only asks whether the CRS is projected with metre map units. EPSG:3857 (Web Mercator) answers yes to both and is an extremely common working CRS the moment an XYZ/OSM basemap or a web-served layer is added, but its point scale factor is 1/cos(phi) - 1.2601 at 37.5N. Every tool in the list above then does planar arithmetic in grid metres and labels the result in ground metres. The failur …
- **[major] CRS-04** Grave-avoidance fetch rectangle is grown by a metre value in the topographic layer's own CRS, unlike the two sibling helpers in the same file that convert to degrees - a geographic topo layer inflates the grave count reported to the user and written into the layer metadata
  - `tools/trench_suggestion_dialog.py` — The AOI is transformed into the topographic layer's CRS and its bounding box is then grown by a plain metre figure. The AOI layer itself is guarded to a metric CRS at :1019 and the DEM at :958, but the 수치지형도 layer that supplies the grave polygons is never checked. When that layer is geographic, max(5.0, grave_buffer_m + 3.0) is applied as at least 5 DEGREES. Every feature returned is then run thro …
- **[minor] CRS-05** Distance raster rejects a geographic CRS but accepts any other projected CRS, while the spinbox suffix, the layer name, the metadata and the help all state the output is in metres
  - `tools/distance_raster_dialog.py` — isGeographic() is a weaker test than the is_metric_crs() helper this codebase already has and uses in seven other tools. A projected CRS whose map units are feet, US survey feet or links passes the check, and gdal:proximity with UNITS=0 (georeferenced) then returns distances in those units. The help text at :508 states the rule the code implements ('투영 CRS여야 거리 단위가 미터가 됩니다') as if being projected …
- **[minor] CRS-06** Polygon-pick tolerance is computed in canvas map units and then applied as an offset around a point already transformed into the layer's CRS, combined with setLimit(10) - clicking a polygon in a differently-unit'd CRS silently falls back to point mode
  - `tools/viewshed_dialog.py` — tol is in canvas map units but is applied to a coordinate that has already been reprojected into the layer's CRS. The identical operation in terrain_profile_dialog.py:1499-1503 is written in the correct order - grow the rectangle in canvas units first, then ct_inv.transformBoundingBox(rect) into the layer CRS - so the right pattern exists in the codebase. Here, with a metric canvas and a geographi …

### sweep-processing-params

- **[major] PP-1** Weiss landform classification tags the wrong NoData value, so the whole NoData collar is mapped and legended as "깊은 곡저 (Incised Valley)"
  - `tools/terrain_analysis_dialog.py` — The call omits NO_DATA. gdal_calc.py then picks the output NoData itself: `if NoDataValue is None and not hideNoData: myOutNDV = DefaultNDVLookup[myOutType]` (gdal_calc.py:437-439), and DefaultNDVLookup[gdal.GDT_Int16] = -32768 (gdal_calc.py:53). gdal_calc then OVERWRITES the plugin's carefully masked zeros: `myResult = ((1*(myNDVs==0))*myResult) + (myOutNDV*myNDVs)` (gdal_calc.py:631), where myND …
- **[major] PP-2** Distance-to-features rasterize omits -at, so sub-pixel polygons are dropped and an all-NoData distance raster is reported as a successful run
  - `tools/distance_raster_dialog.py` — ALL_TOUCH is not passed, so gdal_rasterize runs without `-at` (rasterize.py:208-209) and burns polygons by the pixel-centre rule: a polygon that contains no pixel centre burns nothing. The layer picker accepts polygon layers (lines 117-120 set PointLayer|LineLayer|PolygonLayer). The pre-flight guard the code added for exactly this class of problem only tests bounding-box overlap — `prepared_extent …
- **[major] PP-3** Viewshed silently substitutes the unclipped raster when the circular clip produces no file, changing the reported 가시비율 under an unchanged layer name
  - `tools/viewshed_dialog.py` — QGIS's GDAL Processing algorithms shell out to gdalwarp and return normally whether or not the subprocess succeeded — this plugin knows that, which is why tools/gdal_outcome.py and tests/test_gdal_outcome.py exist and why align_export_dialog.py:858 wraps its warp in _GdalOutcomeFeedback and fails closed on a missing success marker. Here the same failure mode is handled by copying the UNCLIPPED vie …
- **[minor] PP-4** Cumulative/reverse viewshed warp passes DATA_TYPE 5, which is Int32 in gdal:warpreproject, not the Float32 the sibling calls document
  - `tools/viewshed_dialog.py` — This is the exact enum trap the sweep was commissioned to find, caught in the act. gdal:warpreproject's list is prefixed with 'Use Input Layer Data Type' (warp.py:76: ['Use Input Layer Data Type', 'Byte', 'Int16', 'UInt16', 'UInt32', 'Int32', 'Float32', ...]), so index 5 is Int32 and Float32 is 6. The two cliprasterbymasklayer calls in the same file (lines 2009 and 2164) pass 6 with the comment `# …

### sweep-nodata

- **[major] ND-01** Cumulative/union viewshed detects each input's NoData and then throws it away: DEM NoData inside the analysis circle is written as a real 0 = "보이지 않음", and the AOI visibility percentage divides by it
  - `tools/viewshed_dialog.py` — combine_viewsheds_numpy starts from `cumulative = np.zeros((target_height, target_width), dtype=np.float32)` (3642). Per input point it builds `vis_mask` and then explicitly removes NoData from it — `if vs_nodata is not None: vis_mask &= (vs_data[:h_overlap, :w_overlap] != vs_nodata)` (3700-3701) — so the code *knows* which cells carry no data. That knowledge is then discarded: the only NoData wri …
- **[major] ND-02** Line-of-sight silently drops NoData samples, so the observer/target elevations are taken from whatever cell happened to be valid — the visibility verdict can invert and the segment lengths are off by the gap
  - `tools/viewshed_dialog.py` — run_line_of_sight samples the ray with `elev, ok = provider.sample(...)` and drops any failure with a bare `continue`: `if not ok: continue` (3175-3176) and `if math.isnan(elev_value): continue` (3185-3186). QgsRasterDataProvider::sample returns ok=False both for a declared-NoData cell and for a point outside the raster, so the dropped samples are exactly the NoData ones. Nothing counts them, noth …
- **[major] ND-03** Terrain-profile statistics mix a NoData-truncated sample list with the full drawn length: 평균경사 uses the wrong denominator, the CSV's total_distance_m contradicts its own sample table, and unsampled segments are exported as perfectly flat
  - `tools/terrain_profile_dialog.py` — Samples are appended only when `ok_val` is true, i.e. finite and not close to sourceNoDataValue (2015-2041), and each carries `dist = fraction * total_distance_m` — an absolute distance measured from the drawn start. So when the head of the line falls on NoData, profile_data starts at dists[0] > 0, and when the tail does, it ends short of the drawn length. Every consumer then mixes the two frames. …
- **[minor] ND-04** LCP profile and milestone sampling bridge NoData gaps as one long straight edge, so the 직선 distance and time quoted against the least-cost path are wrong
  - `tools/cost_surface_dialog.py` — sample_profile walks the densified coordinates at step_m ≈ one pixel and skips any point whose elevation is unavailable: `z = _bilinear_elevation(dem, nodata_mask, inv_win_gt, ...)` then `if z is None: continue` (3436-3438). x_prev/y_prev/z_prev are not reset on the skip, so the next valid point is joined to the last valid point before the gap: `horiz = math.hypot(float(x) - float(x_prev), ...)`, …
- **[minor] ND-05** When the circular-mask clip produces no file the single-point viewshed silently falls back to the unmasked raster, turning the out-of-range collar from NoData into a real "보이지 않음" over the whole DEM
  - `tools/viewshed_dialog.py` — The single-point path clips the raw gdal:viewshed output to the max-distance circle with gdal:cliprasterbymasklayer, NODATA -9999, DATA_TYPE 6 (2002-2013) — the step the comment at 2002-2003 says is what makes the outside "absolutely transparent". If that call returns without writing a file the code does `if not os.path.exists(final_output): shutil.copy(raw_output, final_output)` (2015-2016) and c …

### sweep-claims

- **[blocker] CLAIM-01** "누적값을 '개수(1~N)'로 표시" is labelled and tooltipped as a legend option, but unchecked it silently replaces the count raster with a binary union above 20 observer points
  - `tools/viewshed_dialog.py` — tools/viewshed_dialog_base.ui:471-477 gives chkCountOnly the text "누적값을 '개수(1~N)'로 표시" and the tooltip "체크 시 범례가 V(1,2,3...) 조합 대신 '보이지 않음 / 1개 누적 / 2개 누적 / … / N개 누적' 형태로 표시됩니다" — i.e. it presents itself as a display/legend choice, and it ships unchecked (<bool>false</bool> at ui:479, re-forced False at viewshed_dialog.py:714). radioMultiPoint's tooltip (ui:80) promises the mode "여러 관측점의 가시권을 합산하 …
- **[blocker] CLAIM-02** AOI 가시비율's denominator is the AOI clipped to the analysed window, not the AOI; an AOI polygon entirely outside the viewshed is published as "0.0%" visible
  - `tools/viewshed_dialog.py` — tot_px counts only AOI pixels where the viewshed raster carries valid data. Every cumulative/single viewshed in this tool is NoData (-9999) outside the max-distance circle (combine_viewsheds_numpy line 3720: cumulative[~circular_mask] = nodata_value), and the read window is additionally clamped to the raster's own extent (lines 1795-1798). So tot_m2 is area(AOI ∩ analysed disc ∩ raster), yet it is …
- **[major] CLAIM-03** The 경사도 단계(°) setting changes neither the number of zones nor the number of labels its tooltip promises to reduce — dissolve always merges on the 1° value
  - `tools/slope_aspect_drafting_dialog.py` — tools/slope_aspect_drafting_dialog_base.ui:170 tells the user, for spinSlopeClassStep (label "경사도 단계:", default 5°): "같은 구간(예: 0~5°, 5~10°…)끼리 병합해 '구역'으로 만듭니다. 값이 클수록 구역 수/라벨이 줄어들어 더 깔끔해집니다." Neither half is true. native:dissolve is keyed on slope_deg (the value rounded to a whole degree), never on slope_class, so the polygon count is fixed at whatever the 1° merge yields regardless of the setting …
- **[major] CLAIM-04** Terrain profile's "총 거리" is the distance of the last sample that had valid elevation, contradicting the same tool's profile-line layer and its own start message
  - `tools/terrain_profile_dialog.py` — Samples whose DEM value is NoData, NaN or outside the raster are silently discarded from profile_data. update_stats then derives the headline "총 거리" from dists[-1] — the last surviving sample — so the reported profile length shrinks to the last valid sample rather than the line the user drew. The same run simultaneously publishes the true geometric length in two other places: the start message at …
- **[major] CLAIM-05** is_metric_crs accepts EPSG:3857, so every "미터 단위 투영 CRS가 필요합니다" gate in the plugin passes Web Mercator and every metre threshold and m² figure is silently wrong by 26%/59% at Korean latitudes
  - `tools/utils.py` — EPSG:3857 is not geographic and reports DistanceMeters, so it passes. Every caller then states or implies true ground metres to the user: tools/viewshed_dialog.py:1307-1316 refuses a DEM with "DEM CRS 단위가 미터가 아닙니다 (현재: …). 가시권/히구치 분석은 미터 단위 투영 CRS가 필요합니다" and, once past that gate, feeds MAX_DISTANCE straight to gdal:viewshed, computes Higuchi ring distances as raw sqrt((x-ox)^2+(y-oy)^2) in CRS un …
- **[major] CLAIM-06** cost-network's closeness tooltip and help state a monotonicity the implementation does not have, and credit Freeman (1979) for a Wasserman–Faust statistic — the twin spatial-network tool discloses both correctly
  - `tools/cost_network_dialog.py` — closeness_centrality_weighted applies the Wasserman–Faust component-size correction, multiplying by reachable/(n−1). The score therefore depends on how much of the network a node can reach, not only on its cost sum, and the stated ordering can invert. Both user-facing surfaces in this tool assert the uncorrected Freeman ordering, and the field alias set at line 2551 is a bare "근접 중심성(closeness)" w …
- **[minor] CLAIM-07** Aspect layer name and tooltip claim an 8-compass-direction classification, but the classes are the eight bins bounded by those directions — no class is N, NE, E, SE, S, SW, W or NW
  - `tools/terrain_analysis_dialog.py` — tools/terrain_analysis_dialog_base.ui:51 (chkAspect) states "사면이 향하는 방향을 8방위(N, NE, E, SE, S, SW, W, NW)로 분류합니다" and the layer name asserts 8방위. A standard 8-direction aspect classification centres each bin on its azimuth (N = 337.5–22.5°, NE = 22.5–67.5°, …). These bins are instead bounded at 0/45/90/…, so each class straddles two compass directions and no class corresponds to any single one. The …
- **[minor] CLAIM-08** Slope-drafting legend breaks are half a degree off their printed labels because the slope is rounded to whole degrees before it is binned
  - `tools/slope_aspect_drafting_dialog.py` — The gdal:slope value is rounded to the nearest integer degree first, and the class is then derived from that integer. A class labelled "{v0}~{v1}°" therefore contains slopes in [v0−0.5, v1−0.5), not [v0, v1). Every break in the legend of the printed drawing — and every value in the slope_class attribute — is displaced by half a degree. The same rounding is repeated independently in _apply_slope_gr …

### sweep-silent

- **[blocker] SILENT-01** Undisclosed 0.05 m/s speed floor makes every slope above ~31 degrees (Herzog) or ~44 degrees (Tobler) cost exactly the same
  - `tools/cost_models.py` — Both the least-cost surface and the least-cost network hard-wire a 0.05 m/s (0.18 km/h) lower bound on modelled walking speed, i.e. an upper bound of 20 s per horizontal metre on cost. The value is never exposed in any spinbox, never named in the per-model help HTML (which lists a, b and c for Tobler and the base speed for Herzog and stops there), never mentioned in README.md, docs/ or any .ui too …
- **[blocker] SILENT-02** Hierarchical AHP weights are silently re-quantised to the 17 Saaty steps before the raster is computed, and AHP_GUIDE.md promises the opposite
  - `tools/ahp_suitability_dialog.py` — compute_hierarchy_summary returns continuous global ratios, but _rebuild_pairwise_table snaps each one to the nearest of the 17 _SCALE_OPTIONS values (1/9 ... 9) and writes the snapped value back into self._pairwise. _on_run (tools/ahp_suitability_dialog.py:2120-2131) then derives the criterion weights from _build_pairwise_matrix() over that snapped dictionary - the hierarchy's own global_weights …
- **[major] SILENT-03** AHP 'target' and 'range' scoring parameters are silently relocated when they fall outside the criterion's min/max, and the substituted value is shown nowhere
  - `tools/ahp_core.py` — A target value outside the criterion's statistics range is replaced by the midpoint of that range, and an invalid preferred range by its 25%-75% band. Neither substitution logs, warns, or is written anywhere the user can see it: the criteria table's columns are [레이어, 방향, min, max, weight] (tools/ahp_suitability_dialog.py:770), so the target is not displayed, and the output layer's params_json (too …
- **[major] SILENT-04** Viewshed AOI statistics compute vis_pct and tot_m2 over only the part of the AOI inside the analysis circle, with no note on the layer, the label or the message
  - `tools/viewshed_dialog.py` — The viewshed raster is clipped with CROP_TO_CUTLINE to a buffer of radius max_dist around the observer, so everything beyond max_dist is either absent from the raster or -9999. The AOI statistics then clamp their read window to the raster and mask off NoData (`valid = np.isfinite(arr)`, `valid &= (arr != nodata)`), so tot_px counts only AOI cells that lie inside the analysis circle. tot_m2 is ther …
- **[major] SILENT-05** Terrain profile drops NoData samples and then draws, smooths, and computes statistics straight across the gap with no break or count in the result
  - `tools/terrain_profile_dialog.py` — Samples whose DEM value is NoData or non-finite are skipped and never recorded anywhere except the count in a transient message bar ("{valid_samples}개 유효 샘플 추출 완료!", line 2072). The chart's QPainterPath joins the last sample before the gap to the first after it with a straight segment; the +-3 sample moving average is index-based so it also blends elevations from opposite sides of the gap; update_ …
- **[minor] SILENT-06** When the circular clip of a viewshed fails, the uncropped full-DEM raster is substituted silently, changing what every downstream AOI percentage means
  - `tools/viewshed_dialog.py` — Both clip sites fall back to the raw gdal:viewshed output when the masked file is missing. The raw output spans the whole DEM and marks cells beyond MAX_DISTANCE as not-visible (value 0) rather than NoData, so the substituted raster has a different extent and a different NoData convention from the one every downstream consumer assumes. Nothing records the substitution - not a log_message, not the …
- **[minor] SILENT-07** The AHP AOI option uses the bounding RECTANGLE of the AOI polygons while the guide states statistics are computed only inside the AOI
  - `tools/aoi_extent.py` — resolve_aoi_extent unions the AOI polygons and returns their bounding box, and _compute_minmax_for_layer passes that rectangle to bandStatistics. The polygon itself never masks anything - the dialog's own _processing_clip_raster_by_mask helper (line 1747) has no call site. The guide's sentence promises polygon-level containment, and it is the sentence the guide uses to persuade the user that this …
- **[minor] SILENT-08** A failed non-align AOI clip leaves the AHP output unclipped while the layer metadata still records clip_to_aoi_extent: true
  - `tools/ahp_suitability_dialog.py` — The non-align clip is best-effort: an exception, or a processing run that produces no file, leaves acc_path pointing at the full-extent accumulator and the run continues. log_exception (tools/utils.py:310-322) writes to the QGIS log panel only - no message bar - while params_json unconditionally records clip_to_aoi_extent as the checkbox state rather than what actually happened. The statistics use …
- **[minor] SILENT-09** Isochrone and iso-energy contour sets are capped at 60 / 80 levels, so a high-cost surface gets contours over only part of its range
  - `tools/cost_models.py` — The cap is enforced silently inside the level generator. The layer that results is named "등시간선 (Isochrones)" / "등에너지선 (Iso-energy)" (tools/cost_surface_dialog.py:2624, 2639) with no note of the range it actually covers, and _tag_cost_surface_layer stamps only model / cost_mode / connectivity. A reader of the map cannot tell a genuinely unreachable area from one whose contours were simply not emitt …
- **[minor] SILENT-10** Slope-grid drafting polygons are labelled with a single centre-cell slope presented as the block's slope
  - `tools/slope_aspect_drafting_dialog.py` — Each output polygon spans step_cells x step_cells DEM cells but carries the slope of one cell at its centre, written to fields named slope / slope_deg / slope_class and drawn as a label "{slope_deg}°" over the whole square (tools/slope_aspect_drafting_dialog.py:648-678). No mean, maximum or range is computed or stored. The .ui text discloses density only - the top help says slope is "단계(예: 0~5°, 5 …

### sweep-metadata

- **[blocker] M1** Default cumulative viewshed is a bit-flag code raster but is tagged units="count", so it is resampled bilinearly and exported as a count predictor
  - `/home/user/archtoolkit/tools/viewshed_dialog.py` — The `kind, units = "cumulative", "count"` line is not a mode of its own - it is the fall-through default, and the only mode that reaches it is the bit-flag mode (viewshed_dialog.py:4116, mode_str = "누적 조합(Bit-flag)"), which is the DEFAULT for a multi-point run (chkCountOnly and chkWeightedCumulative both default false in viewshed_dialog_base.ui:478/511, and is_union_mode at :4105 only fires for li …
- **[major] M2** Single/Higuchi/reverse viewshed params record no observer location, so two viewsheds are indistinguishable in metadata and in an exported stack
  - `/home/user/archtoolkit/tools/viewshed_dialog.py` — A viewshed is defined by WHERE the observer stands, and that is the one parameter never written. params records height, distance and flags; `point`/`point_dem` are in scope at line 2046 and are not stored. The union path (2677: max_dist_m, points_n) and the cumulative path (4186: points_n) are the same. Because the layer name is built only from max_dist, two runs at the same radius also produce by …
- **[major] M3** AHP suitability params_json records the criterion's scoring MODE but not the values that define the score curve (target_v / prefer_min / prefer_max / score_ranges)
  - `/home/user/archtoolkit/tools/ahp_suitability_dialog.py` — _Criterion carries five scoring inputs (direction, target_v, prefer_min, prefer_max, score_ranges) and ahp_core.score_formula uses all of them to build the gdal_calc expression. The metadata stores only direction, min, max and weight. For direction="target" the position of the optimum is lost; for "range" the preferred interval is lost; for "reclass" the entire interval->score table - the whole de …
- **[major] M4** TRI, TPI and Roughness rasters are metre-valued but tagged units="index", while the same tool tags the same quantity units="m" at a larger radius
  - `/home/user/archtoolkit/tools/terrain_analysis_dialog.py` — All three quantities have the vertical unit of the DEM. The plugin says so itself everywhere except in `units`: the roughness params note quotes its class breaks in metres, the TRI checkbox tooltip (terrain_analysis_dialog_base.ui:81) states Riley's own classification is "절대 미터값 기준의 7등급(0-80 / 81-116 / ...)", and the radius>1 variant of the very same TRI statistic is tagged units="m" at line 1032. …
- **[minor] M5** The metadata census test that is supposed to stop exactly this class of bug does not check the runtime call sites at all, and three of its pinned triples are written by no tool
  - `/home/user/archtoolkit/tests/test_categorical_meta.py` — test_every_literal_call_site_is_in_the_expected_table only covers calls whose kind/units are string literals. For the seven files that choose kind at runtime, the only assertion is the SET OF FILE NAMES - so any new or changed kind inside those files is never noticed, and RUNTIME_EXPECTED is never compared against the code. I grepped tools/ for "cost_time", "cost_energy" and "distance_water": no t …
- **[minor] M6** Single and reverse viewshed publish observer-point and Higuchi-ring layers with no archtoolkit metadata, while the cumulative path tags the identical layer
  - `/home/user/archtoolkit/tools/viewshed_dialog.py` — create_observer_layer adds the layer straight to the project root (viewshed_dialog.py:1644, addMapLayers) and create_higuchi_rings does the same (:4993). Neither is tagged in the single/reverse paths, so they have no tool_id, no run_id and no kind. They also defeat every fallback in ai_aoi_summary.is_archtoolkit_layer (lines 339-385): the source is a memory URI (no "archt_" substring), the name do …

### sweep-science

- **[blocker] SCI-01** Herzog metabolic model outputs metabolic cost but is labelled, styled and exported as travel time in minutes
  - `tools/cost_surface_dialog.py` — The 6th-order polynomial is Minetti et al. (2002) metabolic cost of walking in J·kg⁻¹·m⁻¹ (den = 1.64 at zero slope, the standard flat-ground value), which Herzog (2013) uses as a COST, not as a speed. The code converts it to a speed via v = v0 · 1.64/den, i.e. it silently assumes the walker holds metabolic POWER constant and lets speed fall in inverse proportion to cost per metre. That assumption …
- **[major] SCI-02** Network interpretation guides present degree/betweenness as revealing 중심지·요충지, while k — the parameter that determines them — is documented only as a speed and de-cluttering knob
  - `tools/spatial_network_dialog.py` — A k-NN (or Gabriel/RNG/threshold) graph is constructed, not observed. Its degree and betweenness are functions of k and of the spatial point pattern, so they are properties of the analyst's parameter choice, not of past interaction. Both guides state the values depend on the graph TYPE (cost_network_dialog.py:1986 says '선택한 네트워크 방식에 따라 달라집니다'); neither says they depend on k, and the spatial-networ …
- **[major] SCI-03** "Minetti(1995) - 에너지효율" slope preset claims an energy analysis it never computes, and its legend labels invert the paper's own result
  - `tools/terrain_analysis_dialog_base.ui` — Selecting this preset runs gdal:slope and applies a colour ramp — no energy quantity is computed anywhere in the file. The tooltip nevertheless prints the DOI and asserts the tool '경사에 따른 에너지 소비량(J/kg/m) 변화를 분석합니다' and supports '고대 노동력 추정'. Beyond the missing computation, the class table contradicts the cited paper. Minetti (1995) works in PERCENT gradient and its single published result is that t …
- **[major] SCI-04** Cumulative viewshed help says the count expresses 중요도, with nothing anywhere saying the count is a property of the observer sample and no null-model comparison offered
  - `tools/viewshed_dialog.py` — The raster is a count of how many of the analyst's chosen observer points see each cell — which the .ui tooltip at viewshed_dialog_base.ui:80 states accurately. The help then reframes that count as '중요도 표현', which is an inference the output cannot carry: the value at a cell is set by how many observers were selected and how densely they are packed, so it rises wherever the sample happens to clump …
- **[major] SCI-05** Trench suggestion's proximity-to-known-sites score hard-wires the site-clustering assumption and can double-count it with the AHP raster the same plugin tells the user to build
  - `tools/trench_suggestion_dialog.py` — Two separate problems in one score. (1) ref_score rises linearly as a candidate approaches a known site, with a positive default weight of 0.25 and no option to invert it. That hard-wires the hypothesis that archaeological material clusters around already-known sites — and the known-site distribution is itself a record of where people have previously looked. Neither the help (452), the header (240 …
- **[minor] SCI-06** Cumulative viewshed silently degrades to a binary union above 20 observer points while the layer name still claims an N-point accumulation
  - `tools/viewshed_dialog.py` — With more than 20 observer points, and with the default state of the '누적값을 개수(1~N)로 표시' checkbox (unchecked) and the weighted checkbox off, the tool stops accumulating entirely and writes a flat 255 wherever any observer sees the cell. The layer is nevertheless named 가시권_누적_N개점 — 누적 meaning cumulative — for all five output modes. The switch is disclosed twice, but weakly: a transient message bar l …
- **[minor] SCI-07** Local AI report asserts a directional distribution of sites from a top-2 tally, with no threshold and no comparison against uniform
  - `tools/ai_local_summarizer.py` — The sentence asserts a spatial pattern ('주로 … 방향에 분포합니다') from an unconditional top-2 slice of a compass tally over 8 sectors. There is no minimum count, no share threshold and no comparison against what a uniform scatter would produce, so the line is emitted with the same confident wording whether the distribution is strongly anisotropic or as close to uniform as the sample permits. This is gener …
- **[minor] SCI-08** [DUPLICATE of AUDIT_BACKLOG G3 — reported only because still live] GeoChem output panel calls the colour-inverted raster '원본 데이터' and recommends it for MaxEnt, contradicting the dialog's own 역추정 caveat
  - `tools/geochem_polygonize_dialog.py` — The value raster is produced by inverting a rendered WMS colour ramp through a legend, an operation the header (517), the help HTML (~905) and README all correctly describe as 역추정 and explicitly not 원자료. The output-options panel — the text the user is reading at the exact moment they decide what to keep — calls it 원본 데이터, i.e. original data. The neighbouring tooltip then recommends that same raste …
