<h1 align="center">Manufacturing Alarm RAG</h1>
<p align="center">제조설비 알람 분석을 위한 로컬 RAG 질의응답 시스템</p>

<p align="center">
  <a href="#프로젝트-개요">프로젝트 개요</a> ·
  <a href="#기술-스택">기술 스택</a> ·
  <a href="#주요-구현">주요 구현</a> ·
  <a href="#시스템-아키텍처">아키텍처</a> ·
  <a href="#erd">ERD</a> ·
  <a href="#검증-결과">검증 결과</a>
</p>

## 프로젝트 개요

미쓰비시전기 FR-E800 인버터의 알람 코드와 운전 증상을 제조사 보수 매뉴얼에서 검색하는 로컬 RAG 질의응답 시스템이다. 알람의 원인·점검 항목·대처 방법을 조회하고, 답변에 원문 근거와 페이지 출처를 제공한다.

코드 한 글자의 차이로 점검 대상이 달라지는 설비 알람의 특성을 고려해 코드 일치 검색과 증상 의미 검색을 분리했다. 보수편 PDF 64페이지에서 고유 코드 88개, 알람 상세 레코드 75개, 증상 유형 14개를 구조화하고 224개 청크로 검색 인덱스를 구축했다.

![서비스 화면](docs/images/chat-home.png)

## 기술 스택

<table>
  <tr><th align="center">구분</th><th align="center">기술 스택</th></tr>
  <tr><td align="center">Frontend</td><td align="center"><img src="https://img.shields.io/badge/Streamlit-FF4B4B?style=for-the-badge&amp;logo=streamlit&amp;logoColor=white" alt="Streamlit" height="27"> <img src="https://img.shields.io/badge/CSS-663399?style=for-the-badge&amp;logo=css&amp;logoColor=white" alt="CSS" height="27"></td></tr>
  <tr><td align="center">Backend</td><td align="center"><img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&amp;logo=python&amp;logoColor=white" alt="Python" height="27"></td></tr>
  <tr><td align="center">Document Processing</td><td align="center"><img src="https://img.shields.io/badge/PyMuPDF-4A3B75?style=for-the-badge" alt="PyMuPDF" height="27"></td></tr>
  <tr><td align="center">RAG &amp; Storage</td><td align="center"><img src="https://img.shields.io/badge/SQLite-003B57?style=for-the-badge&amp;logo=sqlite&amp;logoColor=white" alt="SQLite" height="27"> <img src="https://img.shields.io/badge/ChromaDB-E65B45?style=for-the-badge" alt="ChromaDB" height="27"></td></tr>
  <tr><td align="center">Embedding</td><td align="center"><img src="https://img.shields.io/badge/Sentence%20Transformers-4051B5?style=for-the-badge" alt="Sentence Transformers" height="27"> <img src="https://img.shields.io/badge/multilingual--e5--small-3B6F99?style=for-the-badge" alt="multilingual-e5-small" height="27"></td></tr>
  <tr><td align="center">LLM</td><td align="center"><img src="https://img.shields.io/badge/Qwen3%204B-6F42C1?style=for-the-badge" alt="Qwen3 4B" height="27"> <img src="https://img.shields.io/badge/llama.cpp-181717?style=for-the-badge" alt="llama.cpp" height="27"> <img src="https://img.shields.io/badge/GGUF%20%2F%20Q4__K__M-455A64?style=for-the-badge" alt="GGUF / Q4_K_M" height="27"></td></tr>
  <tr><td align="center">Test &amp; Tools</td><td align="center"><img src="https://img.shields.io/badge/pytest-0A9EDC?style=for-the-badge&amp;logo=pytest&amp;logoColor=white" alt="pytest" height="27"> <img src="https://img.shields.io/badge/Visual%20Studio%20Code-007ACC?style=for-the-badge" alt="Visual Studio Code" height="27"></td></tr>
</table>

## 주요 구현

| 구현 항목 | 내용 |
|---|---|
| PDF 표 구조 복원 | 셀 좌표와 단어 위치를 기준으로 원인·점검·대처 항목을 추출하고, PDF 실제 페이지와 문서 내부 페이지를 구분해 저장했다. |
| 코드·증상 검색 분리 | 알람 코드는 SQLite에서 일치 검색한다. 증상은 E5 의미 검색과 본문·제목 BM25 순위를 RRF로 결합하고, 운전 구간과 설비 대상을 대조한다. 동일 알람의 원문을 확장하며, 구분이 어려운 코드는 재확인한다. |
| 답변 검증 | Qwen3는 근거 ID를 선택하고 프로그램이 전체 원문을 복원한다. 필수 점검·대처, 절차 순서, 매뉴얼명과 페이지를 검증해 조건 누락과 출처 불일치를 차단했다. |
| 대화 상태 관리 | 채팅방별 알람·증상 맥락을 기준으로 후속 질의를 보완하고, 대화 기록을 별도 SQLite DB에 저장했다. |

## 시스템 아키텍처

![시스템 아키텍처](docs/images/architecture.png)

문서 구축과 질의 처리를 분리했다. 검증된 원문을 SQLite에 저장하고, 같은 문서의 E5 임베딩을 ChromaDB에 적재했다. 답변 생성에는 llama.cpp 서버와 Qwen3 4B Q4_K_M을 사용했다.

## ERD

![매뉴얼 데이터 ERD](docs/images/erd.png)

알람 코드와 상세 레코드를 다대다로 연결하고, 점검·대처 항목의 순서와 좌표 근거를 보존했다. 대화 기록은 매뉴얼 DB와 분리해 관리했다.

## 검증 결과

| 항목 | 개선 전 | 개선 후 |
|---|---|---|
| 기존 자연어 10문항 Hit@1 | 7/10 | 9/10 |
| 기존 자연어 10문항 Hit@3 | 9/10 | 10/10 |
| 추가 자연어 15문항 Hit@1 · Hit@3 | 14/15 · 14/15 | 15/15 · 15/15 |
| 기존 40문항 응답 검사 | 전체 실제 추론 미실행 | 39/40 |
| 추가 25문항 응답 검사 | 미실행 | 25/25 |
| 다회차·채팅방 분리 | — | 12/12 |
| 응답 시간 · 예열 상태 9회 | — | 중앙값 4.61초 · p95 17.28초 |
| 자동 테스트 | 136/136 | 155/155 · 실패 0 · 건너뜀 0 |

검색 지표는 정답 코드가 있는 자연어 질문에서 코드 중복을 제거한 뒤 계산했다. 기존 40문항 중 35문항은 실제 Qwen3 CPU 추론을 사용했고, 5문항은 코드 확인 요청·미등록 안내로 처리했다. 응답 검사는 필수 원문·출처 검증과 Codex의 질문 적합성 검토를 결합했다. 설비 전문가의 독립 검수와 실제 고장 진단 정확도 평가는 포함하지 않는다.

부족 전압 질문 1건은 UV와 E.UVT를 구분할 정보가 없어 표시 코드를 요청했다. 기존 정답을 바꾸지 않아 응답 검사에서는 실패로 집계했다. 추가 문항도 개발 중 작성·확인한 세트이며, 독립된 현장 평가와 긴 대화·동시 접속 평가는 남아 있다. 자동 테스트에는 모의 LLM·HTTP 검사가 포함된다. 시간 측정은 대표 질문 3개를 각 3회 반복한 결과로, 모델 최초 로딩과 브라우저 렌더링을 제외했다.

[검색·답변 개선 결과](evaluation/IMPROVEMENT_REPORT.md) · [기존 평가 범위](evaluation/EVALUATION_AUDIT.md)
