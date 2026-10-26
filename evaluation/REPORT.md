# 성능 평가 보고서

실행: 2026-10-26T22:32:35.646637+09:00

원문 검색 확인 모드. 실제 LLM 호출을 하지 않았으므로 답변 정답률과 LLM 포함 응답 시간은 미측정.

| 핵심 지표 | 실제 결과 |
|---|---|
| 검색 Hit@3 | 90.0% (10문항) |
| LLM 답변 정답률 | 미측정 |
| 응답 시간 p50 / p95 | 0.0029초 / 0.0273초 |

응답 시간 범위: evidence_only. 성공 120회, 실패 0회. 실패는 분위수에 포함하지 않고 별도 기록한다.
코드 없는 자연어 질문 5개는 Hit@3에서 제외했다. 코드·복합·미등록 질문은 검색 지표 대상이 아니다.

## 재현 조건

```json
{
  "run_at": "2026-10-26T22:32:35.646637+09:00",
  "mode": "evidence_only",
  "model": "not_called",
  "embedding": {
    "model": "intfloat/multilingual-e5-small",
    "revision": "614241f622f53c4eeff9890bdc4f31cfecc418b3",
    "dimension": 384,
    "prefix_policy": "query:/passage:",
    "max_tokens": 512
  },
  "source_sha256": "0c45adc7073591a96405a503a5ccf4d5d21a4e1ca8f51db1e87b1d4e39aedc18",
  "dataset_fingerprint": "6bde19e0cf66b09e3e4a0c4ada1f90f9fd09965d805d4ef02009607256d78055",
  "platform": "Windows-10-10.0.19045-SP0",
  "processor": "AMD64 Family 25 Model 33 Stepping 2, AuthenticAMD",
  "python": "3.11.9",
  "question_count": 40,
  "repeats": 3,
  "top_k": 3,
  "max_distance": 0.3,
  "cache": "weights/index warm, no query/answer cache",
  "llm_max_tokens": 1800,
  "packages": {
    "PyMuPDF": "1.27.2.3",
    "chromadb": "1.5.9",
    "sentence-transformers": "5.7.0",
    "torch": "2.14.1",
    "streamlit": "1.66.1",
    "openai": "2.54.0"
  }
}
```

## 판단 기준과 한계

- Hit@3: 원문으로 확인한 정답 코드가 있는 자연어 질문만 사용. 전체 청크 검색 후 코드 중복을 제거해 상위 3개를 계산한다.
- 답변: 필수 원문 항목 전체, 알람 코드, 페이지 출처, 출력 검증을 확인한다. 원문 항목을 잘라내거나 새로운 기술적 문장을 추가할 수 없는 생성 계약을 사용한다.
- 증상 질문의 관련성 및 근거 부족 질문은 수동 검토 대상이다. 자동 검사는 진단의 의미적 정답을 보장하지 않는다.
- evidence_only의 diagnostic_pass는 개발용 점검 로그이며 LLM 답변 정답률로 집계하지 않는다.
- 소규모 개발용 40문항이며 독립적인 외부 시험 세트가 아니다. 모델·청킹을 이 세트에 맞춰 튜닝한 성능으로 일반화하지 않는다.
- p95는 정렬한 값의 (N-1)*0.95 위치를 선형 보간한다. 모델 초기 로딩과 브라우저 렌더링은 제외한다.

## 실패·검토 사례

- n01 (반복 0): Hit@3=True, 후보=['E.OC2', 'OLC', 'E.OC3'], 상태=evidence, 누락=['unexpected_alarm_record'], 수동검토=False, 오류=None
- n01 (반복 1): Hit@3=True, 후보=['E.OC2', 'OLC', 'E.OC3'], 상태=evidence, 누락=['unexpected_alarm_record'], 수동검토=False, 오류=None
- n01 (반복 2): Hit@3=True, 후보=['E.OC2', 'OLC', 'E.OC3'], 상태=evidence, 누락=['unexpected_alarm_record'], 수동검토=False, 오류=None
- n02 (반복 0): Hit@3=True, 후보=['E.OC3', 'E.OC2', 'E.OV3'], 상태=evidence, 누락=['unexpected_alarm_record'], 수동검토=False, 오류=None
- n02 (반복 1): Hit@3=True, 후보=['E.OC3', 'E.OC2', 'E.OV3'], 상태=evidence, 누락=['unexpected_alarm_record'], 수동검토=False, 오류=None
- n02 (반복 2): Hit@3=True, 후보=['E.OC3', 'E.OC2', 'E.OV3'], 상태=evidence, 누락=['unexpected_alarm_record'], 수동검토=False, 오류=None
- n03 (반복 0): Hit@3=True, 후보=['E.OLT', 'E.OV3', 'E.OV2'], 상태=evidence, 누락=['unexpected_alarm_record'], 수동검토=False, 오류=None
- n03 (반복 1): Hit@3=True, 후보=['E.OLT', 'E.OV3', 'E.OV2'], 상태=evidence, 누락=['unexpected_alarm_record'], 수동검토=False, 오류=None
- n03 (반복 2): Hit@3=True, 후보=['E.OLT', 'E.OV3', 'E.OV2'], 상태=evidence, 누락=['unexpected_alarm_record'], 수동검토=False, 오류=None
- n04 (반복 0): Hit@3=True, 후보=['OLV', 'E.OV3', 'E.OC3'], 상태=evidence, 누락=['unexpected_alarm_record'], 수동검토=False, 오류=None
- n04 (반복 1): Hit@3=True, 후보=['OLV', 'E.OV3', 'E.OC3'], 상태=evidence, 누락=['unexpected_alarm_record'], 수동검토=False, 오류=None
- n04 (반복 2): Hit@3=True, 후보=['OLV', 'E.OV3', 'E.OC3'], 상태=evidence, 누락=['unexpected_alarm_record'], 수동검토=False, 오류=None
- n05 (반복 0): Hit@3=True, 후보=['E.THM', 'E.OHT', 'E.GF'], 상태=evidence, 누락=['unexpected_alarm_record'], 수동검토=False, 오류=None
- n05 (반복 1): Hit@3=True, 후보=['E.THM', 'E.OHT', 'E.GF'], 상태=evidence, 누락=['unexpected_alarm_record'], 수동검토=False, 오류=None
- n05 (반복 2): Hit@3=True, 후보=['E.THM', 'E.OHT', 'E.GF'], 상태=evidence, 누락=['unexpected_alarm_record'], 수동검토=False, 오류=None
- n06 (반복 0): Hit@3=True, 후보=['E.FIN', 'E.SAF', 'E.THM'], 상태=evidence, 누락=['unexpected_alarm_record'], 수동검토=False, 오류=None
- n06 (반복 1): Hit@3=True, 후보=['E.FIN', 'E.SAF', 'E.THM'], 상태=evidence, 누락=['unexpected_alarm_record'], 수동검토=False, 오류=None
- n06 (반복 2): Hit@3=True, 후보=['E.FIN', 'E.SAF', 'E.THM'], 상태=evidence, 누락=['unexpected_alarm_record'], 수동검토=False, 오류=None
- n07 (반복 0): Hit@3=False, 후보=['E.10', 'E.MB1', 'E.MB3'], 상태=evidence, 누락=['p26-t2:description:0', 'p26-t2:check_points:0', 'p26-t2:actions:0', 'expected_alarm_code', 'unexpected_alarm_record'], 수동검토=False, 오류=None
- n07 (반복 1): Hit@3=False, 후보=['E.10', 'E.MB1', 'E.MB3'], 상태=evidence, 누락=['p26-t2:description:0', 'p26-t2:check_points:0', 'p26-t2:actions:0', 'expected_alarm_code', 'unexpected_alarm_record'], 수동검토=False, 오류=None
- n07 (반복 2): Hit@3=False, 후보=['E.10', 'E.MB1', 'E.MB3'], 상태=evidence, 누락=['p26-t2:description:0', 'p26-t2:check_points:0', 'p26-t2:actions:0', 'expected_alarm_code', 'unexpected_alarm_record'], 수동검토=False, 오류=None
- n08 (반복 0): Hit@3=True, 후보=['E.OHT', 'TH', 'E.THM'], 상태=evidence, 누락=['unexpected_alarm_record'], 수동검토=False, 오류=None
- n08 (반복 1): Hit@3=True, 후보=['E.OHT', 'TH', 'E.THM'], 상태=evidence, 누락=['unexpected_alarm_record'], 수동검토=False, 오류=None
- n08 (반복 2): Hit@3=True, 후보=['E.OHT', 'TH', 'E.THM'], 상태=evidence, 누락=['unexpected_alarm_record'], 수동검토=False, 오류=None
- n09 (반복 0): Hit@3=True, 후보=['E.USB', 'E.EHR', 'E.6'], 상태=evidence, 누락=['unexpected_alarm_record'], 수동검토=False, 오류=None
- n09 (반복 1): Hit@3=True, 후보=['E.USB', 'E.EHR', 'E.6'], 상태=evidence, 누락=['unexpected_alarm_record'], 수동검토=False, 오류=None
- n09 (반복 2): Hit@3=True, 후보=['E.USB', 'E.EHR', 'E.6'], 상태=evidence, 누락=['unexpected_alarm_record'], 수동검토=False, 오류=None
- n10 (반복 0): Hit@3=True, 후보=['E.PID', 'E.OLT', 'E.OC3'], 상태=evidence, 누락=['unexpected_alarm_record'], 수동검토=False, 오류=None
- n10 (반복 1): Hit@3=True, 후보=['E.PID', 'E.OLT', 'E.OC3'], 상태=evidence, 누락=['unexpected_alarm_record'], 수동검토=False, 오류=None
- n10 (반복 2): Hit@3=True, 후보=['E.PID', 'E.OLT', 'E.OC3'], 상태=evidence, 누락=['unexpected_alarm_record'], 수동검토=False, 오류=None
- n11 (반복 0): Hit@3=None, 후보=[], 상태=evidence, 누락=[], 수동검토=True, 오류=None
- n11 (반복 1): Hit@3=None, 후보=[], 상태=evidence, 누락=[], 수동검토=True, 오류=None
- n11 (반복 2): Hit@3=None, 후보=[], 상태=evidence, 누락=[], 수동검토=True, 오류=None
- n12 (반복 0): Hit@3=None, 후보=[], 상태=evidence, 누락=[], 수동검토=True, 오류=None
- n12 (반복 1): Hit@3=None, 후보=[], 상태=evidence, 누락=[], 수동검토=True, 오류=None
- n12 (반복 2): Hit@3=None, 후보=[], 상태=evidence, 누락=[], 수동검토=True, 오류=None
- n13 (반복 0): Hit@3=None, 후보=[], 상태=evidence, 누락=[], 수동검토=True, 오류=None
- n13 (반복 1): Hit@3=None, 후보=[], 상태=evidence, 누락=[], 수동검토=True, 오류=None
- n13 (반복 2): Hit@3=None, 후보=[], 상태=evidence, 누락=[], 수동검토=True, 오류=None
- n14 (반복 0): Hit@3=None, 후보=[], 상태=evidence, 누락=[], 수동검토=True, 오류=None
- n14 (반복 1): Hit@3=None, 후보=[], 상태=evidence, 누락=[], 수동검토=True, 오류=None
- n14 (반복 2): Hit@3=None, 후보=[], 상태=evidence, 누락=[], 수동검토=True, 오류=None
- n15 (반복 0): Hit@3=None, 후보=[], 상태=evidence, 누락=[], 수동검토=True, 오류=None
- n15 (반복 1): Hit@3=None, 후보=[], 상태=evidence, 누락=[], 수동검토=True, 오류=None
- n15 (반복 2): Hit@3=None, 후보=[], 상태=evidence, 누락=[], 수동검토=True, 오류=None
- m08 (반복 0): Hit@3=None, 후보=[], 상태=evidence, 누락=['unexpected_alarm_record'], 수동검토=False, 오류=None
- m08 (반복 1): Hit@3=None, 후보=[], 상태=evidence, 누락=['unexpected_alarm_record'], 수동검토=False, 오류=None
- m08 (반복 2): Hit@3=None, 후보=[], 상태=evidence, 누락=['unexpected_alarm_record'], 수동검토=False, 오류=None
- u05 (반복 0): Hit@3=None, 후보=[], 상태=evidence, 누락=[], 수동검토=True, 오류=None
- u05 (반복 1): Hit@3=None, 후보=[], 상태=evidence, 누락=[], 수동검토=True, 오류=None
- u05 (반복 2): Hit@3=None, 후보=[], 상태=evidence, 누락=[], 수동검토=True, 오류=None

## 로컬 상세 기록

results.json은 질문·응답·원문 항목 누락과 검토 지문을, results.csv는 실행별 결과를 저장한다. 원문 대량 재배포를 피하기 위해 두 파일은 Git에서 제외한다.
LLM 수동 검토는 review.json에 질문ID:반복번호 키, approved, answer_fingerprint를 기록한 뒤 --rescore --review 경로로 실행한다. API를 다시 호출하지 않으며 응답이 변경되면 기존 검토는 적용되지 않는다.
