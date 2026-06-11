# HireCopilot — AI Agent Handoff Document

> 이 파일은 새로운 AI 에이전트가 프로젝트를 이어받아 작업할 수 있도록 작성된 인수인계 문서입니다.
> 작업 시작 전 반드시 이 파일을 먼저 읽으세요.

---

## 프로젝트 한 줄 요약

지원자가 AI 면접관과 한국어로 대화하고, 면접 결과가 Google Sheets에 기록된 뒤 **Python 파이프라인**이 2차 채용 작업을 outbox 시트에 큐잉하며, 운영자는 **통합 관리자 콘솔**에서 결과/outbox/Zapier 연결을 확인하는 Streamlit MVP.

---

## 파일 구조 및 역할

```
HireCopilot_AI_Agent/
├── app.py                  # 지원자 면접 앱 (streamlit run app.py)
├── admin_store.py          # 관리자 콘솔용 로컬 JSONL 스냅샷 저장/조회
├── pipeline.py             # 2차 파이프라인: 필터 + 분기 + outbox 큐잉
├── gas/webhook_router.gs   # GAS 멀티 시트 웹훅 (interviews + outbox_*)
├── recruiter.py            # 통합 관리자 콘솔 (port 8502)
├── recruiter_config.json   # 포지션/기준 (두 앱 공유)
├── tests/test_pipeline.py  # pipeline 단위 테스트
├── tests/test_admin_store.py
├── requirements.txt
├── .env
├── README.md
└── CLAUDE.md
```

---

## 환경변수 (.env)

```env
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o-mini
GAS_WEBHOOK_URL=...           # gas/webhook_router.gs 배포 URL (권장)
ZAPIER_WEBHOOK_URL=...          # GAS_WEBHOOK_URL 없을 때 폴백
ADMIN_EMAIL=...                 # 보류/추천 시 관리자 알림 outbox
ADMIN_SLACK_USER_ID=...         # Slack DM 수신 user ID
NOTION_DATABASE_LABEL=...       # outbox_notion database 열 값
PIPELINE_MIN_GPA=3.0            # 학점 > 3.0 통과 (3.0은 탈락)
PIPELINE_REQUIRE_GPA=true
PIPELINE_BLOCK_NEWGRAD=false    # true면 "신입 (경력 없음)" 탈락
DEV_TOGGLE_PASSWORD=...
RECRUITER_PASSWORD=...
```

- `load_dotenv(override=True)` → `.env` 수정 후 앱 **완전 재시작** 필요

---

## 핵심 아키텍처

### 설계 원칙

| 레이어 | 담당 | 도구 |
|---|---|---|
| 면접 + 평가 | Python (`app.py`) | OpenAI |
| 저장 + outbox 큐 | Python (`pipeline.py`) → GAS | webhook_router.gs |
| 운영 대시보드 | Streamlit (`recruiter.py`) | 로컬 JSONL + pipeline 결과 |
| 앱 연결 | outbox 시트 New Row | **Zapier 전용 ZAP (앱당 1개)** |

복잡한 monolithic Zap(필터/Paths/Delay)은 **사용하지 않음**. 로직은 코드, Zapier는 Gmail/Slack/Notion/Docs/Zoom **연결만**.

### app.py 흐름

```
1. 온보딩 (이름/이메일/학력/경력/학점*/포지션)
2. recruiter_config → _build_interview_prompt()
3. AI 면접 채팅 → [[INTERVIEW_COMPLETE]]
4. llm_json() 평가 → build_final_payload()
5. execute_pipeline() → pipeline.run_pipeline()
6. admin_store.py → 관리자 콘솔용 로컬 스냅샷 저장
7. 결과 UI + JSON 다운로드
```

### pipeline.py 흐름

```
1. GAS POST → interviews 탭 (A~S, 19열)
2. check_screening() — 이메일/@, 학점>MIN_GPA, 학위, 경력
3. hiring_opinion 분기:
   - 추천 → outbox_notion, (admin) slack/email
   - 보류 → slack, admin email, notion, zoom, docs(+ LLM 2차 질문)
   - 비추천 → outbox_email (지원자 탈락 메일)
4. pipeline_log 기록
```

### recruiter.py 통합 관리자 콘솔

```
1. 암호 로그인
2. 대시보드 — 최근 면접, 추천/보류/비추천, 자격 필터, 실패 outbox
3. 지원자/면접 결과 — 평가 JSON, 요약, 우려사항, 대화록
4. outbox/파이프라인 — 액션별 성공/실패, 실패 outbox 재전송
5. Zapier 연결 가이드 — outbox별 Trigger/Action/필드 매핑
6. 채용 담당 설정 — 포지션/공통 기준 편집
```

관리자 콘솔은 Google Sheets 읽기 API를 쓰지 않는다. `app.py`가 면접 종료 후 `admin_store.py`를 통해 `data/admin_interviews.jsonl`에 로컬 스냅샷을 남기고, 콘솔은 그 파일을 읽는다. 이 파일은 `.gitignore` 대상이다.

### GAS 스프레드시트 탭

스프레드시트 ID: `1swaf7dyRsVRxepLJAXVoPO3YRNV0aPYmcBLL4_tPnbE`

| 탭 | 용도 | Zap |
|---|---|---|
| `interviews` (또는 Sheet1) | 면접 DB | 불필요 |
| `outbox_email` | to, subject, body | Gmail Send |
| `outbox_slack` | recipient, message | Slack DM |
| `outbox_notion` | name, database, notes | Notion Create |
| `outbox_docs` | content | Google Docs Insert |
| `outbox_zoom` | topic, start_time, duration | Zoom Create Meeting |
| `pipeline_log` | 로그 | 불필요 |

POST 형식: `{ "target": "outbox_email", "row": [...] }`

---

## 주요 함수

| 이름 | 파일 | 설명 |
|---|---|---|
| `execute_pipeline()` | app.py | pipeline.run_pipeline 래퍼 + DUMMY llm_fn |
| `save_interview_record()` | admin_store.py | 관리자 콘솔용 면접/파이프라인 스냅샷 저장 |
| `list_interview_records()` | admin_store.py | 관리자 콘솔 최근 면접 기록 조회 |
| `update_pipeline_result()` | admin_store.py | 재전송 후 로컬 파이프라인 결과 갱신 |
| `run_pipeline()` | pipeline.py | 저장 + 필터 + outbox dispatch |
| `retry_failed_outbox()` | pipeline.py | 실패 outbox만 재전송 (interviews/log 중복 방지) |
| `post_to_gas()` | pipeline.py | GAS POST + 302→GET 처리 |
| `check_screening()` | pipeline.py | 자격 필터 |
| `build_branch_actions()` | pipeline.py | 추천/보류/비추천 outbox 행 생성 |
| `llm_chat()` / `llm_json()` | app.py | OpenAI 호출 |
| `build_final_payload()` | app.py | 최종 평가 dict (concerns 포함) |

---

## interviews 컬럼 (A~S)

```
타임스탬프 | 이름 | 이메일 | 포지션 | 학력 | 학점 | 경력 |
적합도 | 채용의견(I=추천/보류/비추천) | 추천이유 | 총점 | 5개 항목점수 |
요약 | 다음단계 | 전체대화
```

---

## Streamlit 세션 상태

| 키 | 설명 |
|---|---|
| `pipeline_result` | `PipelineResult` (저장/outbox 결과) |
| `final_payload` | 최종 평가 dict |
| `interview_done` | 면접 종료 여부 |
| (기타) | onboarding, messages, dev_mode, running_eval |

---

## Zapier 연결 원칙

각 앱마다 Zap 1개씩 만든다. 모든 Zap의 Trigger는 Google Sheets `New Spreadsheet Row`이고, Worksheet만 앱별 outbox 탭으로 다르다.

| Zap | Trigger 탭 | Action | 매핑 |
|---|---|---|---|
| Email | `outbox_email` | Gmail Send Email | to, subject, body |
| Slack | `outbox_slack` | Slack Send DM | recipient, message |
| Notion | `outbox_notion` | Notion Create DB Item | name, notes |
| Docs | `outbox_docs` | Google Docs Append Text | content |
| Zoom | `outbox_zoom` | Zoom Create Meeting | topic, start_time_iso, duration_min |

예: Gmail 발송은 `pipeline.py`가 `outbox_email` 행을 만들고, GAS가 그 행을 시트에 추가하면, 전용 Zap이 새 행을 감지해 Gmail 액션으로 보낸다. Zap 안에는 Filter/Paths/AI 호출을 넣지 않는다.

---

## 알려진 주의점

1. **GAS 302**: POST 후 Location GET으로 응답 확인 (`post_to_gas`)
2. **재전송**: `retry_failed_outbox()`는 실패 outbox만 재전송. interviews/pipeline_log 중복 append 방지
3. **학점 필수**: 온보딩 + `PIPELINE_REQUIRE_GPA=true` — 3.0 초과 필요 (`>3.0`, 3.0은 탈락)
4. **GAS 배포 변경** 시 URL 갱신 + 앱 재시작
5. **관리자 콘솔 기록**: 과거 면접은 로컬 JSONL에 저장된 기록만 보임. Google Sheets 전체 조회는 미구현
6. **Delay/Notion HITL** (구 monolithic Zap 기능)은 미구현 — 필요 시 outbox_scheduled 확장

---

## 테스트

```powershell
python -m unittest tests/test_pipeline.py tests/test_admin_store.py
```

---

## 현재 작업 현황

- [x] AI 면접 + 5루브릭 + hiring_opinion
- [x] GAS 멀티 시트 webhook_router
- [x] pipeline.py (코드 중심 2차 파이프라인)
- [x] outbox 패턴 (Zapier = 앱 연결 전용)
- [x] 보류 시 LLM 2차 질문 + zoom outbox
- [x] 통합 관리자 콘솔 + 로컬 스냅샷 + 실패 outbox 재전송
- [x] 관리자 콘솔 Zapier 연결 가이드

### 미구현 / 확장 후보
- Delay Until + Notion 체크박스 최종 합격 (outbox_scheduled)
- Google Sheets 직접 조회 기반 전체 면접 히스토리
- Zoom/Calendar를 코드에서 직접 호출 (현재 outbox→Zap)
