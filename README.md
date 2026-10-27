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
  <tr><td align="center">Test &amp; Tools</td><td align="center"><img src="https://img.shields.io/badge/pytest-0A9EDC?style=for-the-badge&amp;logo=pytest&amp;logoColor=white" alt="pytest" height="27"> <img src="https://img.shields.io/badge/Git-F05032?style=for-the-badge&amp;logo=git&amp;logoColor=white" alt="Git" height="27"> <img src="https://img.shields.io/badge/GitHub-181717?style=for-the-badge&amp;logo=github&amp;logoColor=white" alt="GitHub" height="27"></td></tr>
</table>

## 주요 구현

| 구현 항목 | 내용 |
|---|---|
| PDF 표 구조 복원 | 셀 좌표와 단어 위치를 기준으로 원인·점검·대처 항목을 추출하고, PDF 실제 페이지와 문서 내부 페이지를 구분해 저장했다. |
| 코드·증상 검색 분리 | 알람 코드는 SQLite에서 일치 검색하고, 코드 없는 증상은 E5 임베딩과 ChromaDB로 검색했다. 청크는 알람별 원문 항목과 증상 표의 행 단위로 구성했다. |
| 답변 검증 | Qwen3가 선택한 근거 ID와 인용을 원문에 대조했다. 필수 점검·대처 항목, 원문 순서, 매뉴얼명과 페이지 출처를 프로그램에서 검증했다. |
| 대화 상태 관리 | 채팅방별 알람·증상 맥락을 기준으로 후속 질의를 보완하고, 대화 기록을 별도 SQLite DB에 저장했다. |

## 시스템 아키텍처

![시스템 아키텍처](docs/images/architecture.png)

문서 구축과 질의 처리를 분리했다. 검증된 원문을 SQLite에 저장하고, 같은 문서의 E5 임베딩을 ChromaDB에 적재했다. 답변 생성에는 llama.cpp 서버와 Qwen3 4B Q4_K_M을 사용했다.

## ERD

![매뉴얼 데이터 ERD](docs/images/erd.png)

알람 코드와 상세 레코드를 다대다로 연결하고, 점검·대처 항목의 순서와 좌표 근거를 보존했다. 대화 기록은 매뉴얼 DB와 분리해 관리했다.

## 검증 결과

| 항목 | 결과 |
|---|---|
| 검색 Hit@1 | 70% (7/10) |
| 검색 Hit@3 | 90% (9/10) |
| 자동 테스트 | 전체 136개 중 136개 통과 · 실패 0개 · 건너뜀 0개 |
| 실제 모델 추론 | Qwen3 4B의 로컬 CPU 추론, 후속 질문 처리, 원문 인용·출처 검증 확인 |

검색 지표는 40문항 평가 세트 중 정답 코드가 있는 자연어 질의 10개를 대상으로 산출했다. 코드 후보의 중복을 제거한 뒤, 1위 적중 여부를 Hit@1로, 상위 3개 내 포함 여부를 Hit@3로 계산했다. 코드 없는 증상 질의 5개는 제외했다.

자동 테스트는 데이터·검색·API 예외 처리·대화 상태·UI 동작을 검사하며, 모의 LLM 검사를 포함한다. 전체 40문항의 실제 LLM 답변 정답률은 아직 평가하지 않았다. 검색 관련성 개선, 독립 평가 세트 확보, 다회차 대화 품질과 CPU 추론 지연의 반복 측정은 후속 과제로 남아 있다.

[평가 범위와 미완료 항목](evaluation/EVALUATION_AUDIT.md) · [검색 평가 기록](evaluation/local_llm/chat_regression/REPORT.md) · [로컬 LLM·대화 맥락 검증](evaluation/CHAT_CONTEXT_REPORT.md)
