# HireCopilot — 내가 바꾸고 싶은 방향 (2026-06-05)

> 이 문서는 오늘 세션에서 내가 요청·강조한 내용을 바탕으로,  
> **앞으로 프로젝트를 어떤 철학으로, 무엇을, 어떻게 바꾸고 싶은지**를 정리한 것이다.  
> 구현 상세는 `d0605.md`, 코드는 `pipeline.py` / `gas/` / `app.py`를 보라.

---

## 한 줄로

**복잡한 Zap 한 방에 몰아넣지 말고, 로직은 Python 코드, 앱 연결만 Zapier 전용 ZAP + outbox 시트로 쪼개라.**

---

## 1. 왜 바꾸려는가

- 기존 Zap Export(30단계+, Paths, Delay, Notion HITL, Claude, Zoom…)는 **이해는 됐지만**, 설정이 GAS/앱 컬럼과 안 맞고, 유지보수가 어렵다.
- **완벽히 돌아간다고 확신 못 함** — 당장은 “돌아가게”보다 **구조를 이해하고, 내가 통제 가능한 형태로 재설계**하는 게 우선이다.
- Zapier는 OAuth·앱 연결에는 좋지만, **필터·분기·LLM·열 번호 매핑** 같은 비즈니스 로직을 Zap 안에 두고 싶지 않다.

---

## 2. 원하는 아키텍처 (3층)

```
[1층] HireCopilot (Python / Streamlit)
      면접 · 평가 · 자격 필터 · 추천/보류/비추천 분기 · 2차 질문 생성

[2층] Google Sheets + GAS 웹훅
      interviews = 면접 DB
      outbox_*   = “해야 할 일” 큐 (행 추가만)

[3층] Zapier (앱당 전용 ZAP 1개)
      outbox 시트 New Row → Gmail / Slack / Notion / Docs / Zoom
```

**원칙:**
- **Zap는 꼭 필요할 때만**, 역할은 **앱 연결**뿐.
- **판단·분기·텍스트 생성**은 **코드** (`pipeline.py`, 필요하면 `app.py`).
- 시트는 **단일 허브**: 면접 결과 저장 + 각 액션을 outbox 탭에 “일거리”로 적어 두면 Zap이 처리.

---

## 3. GAS / 스프레드시트 — 내가 원하는 방식

### 3.1 면접 결과 저장 (기존과 동일한 데이터)

- 스프레드시트: `1swaf7dyRsVRxepLJAXVoPO3YRNV0aPYmcBLL4_tPnbE`
- `doPost` / webhook router가 **A~S 19열**에 append (이름, 이메일, I열 `hiring_opinion` = 추천/보류/비추천 등).
- 앱(`app.py`) → GAS POST → **`interviews`** 탭(또는 기존 Sheet1 호환).

### 3.2 outbox 패턴 (내가 제안한 핵심 아이디어)

> 예: 메일 보내기  
> **코드**가 `outbox_email` 시트에 `받는 사람 | 제목 | 본문` 행을 추가  
> → **전용 Zap 1개**: `outbox_email` New Row → Gmail Send

같은 방식으로:

| outbox 탭 | 코드가 적는 것 | Zap이 하는 것 |
|---|---|---|
| `outbox_email` | to, subject, body | Gmail 발송 |
| `outbox_slack` | recipient, message | Slack DM |
| `outbox_notion` | name, database, notes | Notion 항목 생성 |
| `outbox_docs` | content (지원자 정보 + 2차 질문) | Google Docs 삽입 |
| `outbox_zoom` | topic, 시작시각, duration | Zoom 미팅 생성 |

- **monolithic Zap 트리거(interviews New Row → 30단계)** 는 **쓰지 않는다**.
- 구 Zap의 **Filter / Paths / Code by Zapier / Claude 단계**는 **Python으로 옮긴다** (또는 이미 옮긴 상태를 유지·다듬는다).

---

## 4. 2차 파이프라인 — 코드가 할 일 (Zap가 하지 말 것)

면접 JSON이 준비된 **이후**는 `pipeline.py`가 담당했으면 한다.

### 4.1 자격 필터 (구 Zap 2~5단계 대체)

- 이메일 `@` 포함
- 학점 **3.0 초과** (3.0은 탈락 — 구 Zap의 `>3`과 맞춤)
- 학위·경력 “없음”/빈값 탈락
- (옵션) 신입 제외 — env로 켜고 끄기

**탈락 시:** outbox 액션 생략, `pipeline_log`만 남기거나 interviews만 저장.

### 4.2 hiring_opinion 분기 (구 Paths 대체)

분기 키워드는 **앱이 쓰는 그대로**:

| I열 값 | 내가 원하는 후속 |
|---|---|
| **추천** | Notion 등록 + 관리자 알림 (Slack/이메일). 지원자에게 바로 합격 메일 X (사람 검토 후). |
| **보류** | 관리자 Slack+이메일, Notion, **LLM 2차 질문 → outbox_docs**, **Zoom → outbox_zoom** |
| **비추천** | 지원자 탈락 메일 → `outbox_email` |

### 4.3 LLM

- 1차 면접·평가: 기존 `app.py` (OpenAI).
- 보류 시 2차 면접 질문: **코드에서 LLM 호출** — Zap 안의 Claude 단계 **대체**.

---

## 5. Zapier — 내가 쓰고 싶은 방식

- **ZAP 개수 = 연결할 앱 수** (대략 outbox 탭당 1개).
- 각 ZAP: **Trigger = 해당 outbox 탭 New Row**, **Action = 앱 1개**.
- Zap 안에 Filter, Paths, Delay, JavaScript, AI **넣지 않는다** (가능한 한).
- OAuth·Gmail API·Slack API·Notion API는 Zap에 맡기고, **무엇을 보낼지만** 시트+코드가 결정.

---

## 6. 구 Zap에서 가져오고 / 버리고 / 나중에 할 것

### 가져온 것 (코드 또는 outbox로)

- 자격 필터 → `check_screening()`
- 추천/보류/비추천 분기 → `build_branch_actions()`
- 보류 시 Slack·관리자 메일·Notion·Docs·Zoom 큐
- 비추천 시 지원자 메일 큐
- 면접 결과 시트 append

### 버린 것 (monolithic Zap 전체를 돌릴 필요 없음)

- interviews New Row 하나로 30단계 도는 Zap
- Zap 안 Filter/Paths의 **잘못된 COL 참조** (D=이메일, J=채용 등)
- Zap Code by Zapier로 2차 질문 생성 (→ Python)
- `update_row` 행 번호 2·3 고정 같은 설정

### 아직 안 옮겼지만, 원하면 나중에 outbox로 확장

- **Delay Until** (합격자 발표일까지 대기) → `outbox_scheduled` 탭 + 별 Zap 또는 스케줄러
- **Notion 체크박스 HITL** → Notion 등록은 outbox로, “체크 후 합격 메일”은 2차 워크플로
- 시트 **T/U열 최종 합격/탈락** 기록

→ 당장은 **Must-have 아님**. 구조 잡힌 뒤 outbox 패턴으로 하나씩 추가.

---

## 7. 문서·코드베이스 — 내가 원하는 정합성

- README / CLAUDE / SETUP은 **“구 30단계 Zap”이 메인**이 아니라 **outbox + pipeline** 기준이어야 한다.
- GAS 코드는 **`gas/webhook_router.gs` 한 벌** — 멀티 탭 라우팅.
- env는 **`GAS_WEBHOOK_URL`** 중심, `ZAPIER_WEBHOOK_URL`은 하위 호환만.
- 재전송 시 **interviews 행 중복** 안 나게 — outbox만 다시 보내는 경로 필요.

---

## 8. 내가 AI/개발자에게 앞으로 시킬 때 쓸 프롬프트 (복붙용)

```
HireCopilot 2차 자동화 규칙:

1. 비즈니스 로직(필터, hiring_opinion 분기, LLM 2차 질문)은 pipeline.py / app.py에만 둔다.
2. Gmail, Slack, Notion, Docs, Zoom 호출은 직접 API 붙이지 말고
   outbox_* 시트에 행을 append하고, Zapier 전용 ZAP(New Row → 앱 1개)이 처리하게 한다.
3. GAS webhook_router.gs로 interviews + outbox 탭에 POST한다. 스프레드시트 ID는 1swaf7dy...
4. 구 monolithic Zap(30단계 Paths/Delay)은 사용하지 않는다. 문서에도 메인 플로우로 쓰지 않는다.
5. hiring_opinion은 I열: 추천 / 보류 / 비추천. Zap 분기 키워드는 "채용/탈락"이 아니라 이 값을 따른다.
6. 완벽 동작보다 구조 이해·유지보수성 우선. 변경 시 d0605.md(구현 기록)와 이 파일(방향)을 함께 본다.
```

---

## 9. 성공 기준 (내가 “원하는 상태”)

- [ ] 면접 1회 → `interviews` 탭에 1행 (GAS URL만 맞으면)
- [ ] 필터 통과 + 보류 → `outbox_slack`, `outbox_email`, `outbox_notion`, `outbox_zoom`, `outbox_docs`에 각 1행
- [ ] 각 outbox Zap만 켜두면 Gmail/Slack/… 실제 발송·생성
- [ ] 구 30단계 Zap **없이**도 2차 프로세스 설명 가능
- [ ] 코드·문서·GAS·env가 **outbox 아키텍처**로 말이 맞음

---

## 10. 오늘 내가 한 요청 타임라인 (맥락)

1. **md 읽어** — 프로젝트 파악부터
2. **Zap 상세 설명 가져옴** — 이해 우선, 모르면 질문
3. **GAS doPost 실제 코드 공유** — 시트 ID·19열 확정
4. **Zap 안 돌아도 됨, 코드 최대, Zap는 앱 연결만 outbox로** — 핵심 방향 제시
5. **전반 재검토 + 코드베이스 전부 반영** — 버그·문서·테스트까지
6. **d0605.md** — 오늘 한 작업 기록
7. **d0605prompt.md (본 문서)** — 내가 바꾸길 원하는 방향 정리

---

*이 문서 = “무엇을 왜, 어떤 원칙으로 바꾸고 싶은지” / `d0605.md` = “오늘 실제로 무엇을 했는지”*
