# HireCopilot — AI Agent Handoff Document

> 이 파일은 새로운 AI 에이전트가 프로젝트를 이어받아 작업할 수 있도록 작성된 인수인계 문서입니다.
> 작업 시작 전 반드시 이 파일을 먼저 읽으세요.

---

## 프로젝트 한 줄 요약

지원자가 AI 면접관과 한국어로 대화하고, 면접 결과가 Google Sheets에 자동 기록되는 **Streamlit 기반 채용 자동화 에이전트** (학교 프로젝트 MVP).

---

## 파일 구조 및 역할

```
HireCopilot_AI_Agent/
├── app.py                  # 지원자 면접 앱 (메인, streamlit run app.py)
├── recruiter.py            # 채용 담당자 설정 앱 (streamlit run recruiter.py --server.port 8502)
├── recruiter_config.json   # 포지션/기준 설정 파일. 두 앱이 공유. recruiter.py에서 쓰고 app.py에서 읽음
├── requirements.txt        # streamlit, openai, requests, python-dotenv, pydantic
├── .env                    # 환경변수 (아래 참고)
├── README.md               # 사용자용 세팅 안내
└── CLAUDE.md               # 본 파일
```

---

## 환경변수 (.env)

```env
OPENAI_API_KEY=...          # 없으면 DUMMY 모드 (미리 준비된 질문으로 동작)
OPENAI_MODEL=gpt-4o-mini
ZAPIER_WEBHOOK_URL=...      # Google Apps Script 웹훅 URL
DEV_TOGGLE_PASSWORD=...     # 개발자 모드 토글 암호
RECRUITER_PASSWORD=...      # recruiter.py 접근 암호
```

- `load_dotenv(override=True)` 사용 → `.env` 수정 후 앱 재시작 필요
- `.env` 변경은 앱을 완전히 재시작해야 적용됨 (Streamlit 핫리로드로는 안 됨)

---

## 핵심 아키텍처

### app.py 흐름

```
1. 온보딩 폼 (이름/이메일/학력/경력/학점/포지션 입력)
        ↓
2. recruiter_config.json 로드 → _build_interview_prompt() 로 시스템 프롬프트 동적 생성
        ↓
3. Streamlit 채팅 UI (st.chat_message / st.chat_input)
   → llm_chat() 호출 → GPT가 한 번에 한 질문씩 진행
   → [[INTERVIEW_COMPLETE]] 토큰 감지 시 면접 종료
        ↓
4. llm_json() → SYSTEM_PROMPT_EVALUATION 으로 JSON 평가 생성
        ↓
5. build_final_payload() → 페이로드 조립
        ↓
6. send_to_zapier() → Google Apps Script 웹훅으로 POST 전송
        ↓
7. 결과 화면 표시 + JSON 다운로드
```

### recruiter.py 흐름

```
암호 인증 → recruiter_config.json 로드 → 포지션 추가/수정/삭제 + 공통 기준 입력 → 저장
```

---

## 주요 함수 & 상수

| 이름 | 파일 | 설명 |
|---|---|---|
| `_build_interview_prompt()` | app.py | recruiter_config + 지원 포지션 반영한 시스템 프롬프트 생성 |
| `llm_chat()` | app.py | GPT 채팅 호출. DUMMY_MODE면 미리 준비된 질문 반환 |
| `llm_json()` | app.py | GPT JSON 모드 호출. DUMMY_MODE면 더미 평가 반환 |
| `build_final_payload()` | app.py | 평가 결과 + 지원자 정보 합쳐 최종 dict 조립 |
| `send_to_zapier()` | app.py | POST 후 302 리다이렉트 → GET으로 처리 (GAS 특성) |
| `load_recruiter_config()` | app.py, recruiter.py | JSON 로드. 파일 없으면 DEFAULT_POSITIONS로 자동 생성 |
| `save_recruiter_config()` | recruiter.py | JSON 저장 (updated_at 자동 갱신) |
| `RUBRIC` | app.py | 5개 평가 항목 정의 (culture_fit 등) |
| `DEFAULT_POSITIONS` | app.py, recruiter.py | recruiter_config.json 초기값 |
| `RECRUITER_CONFIG_PATH` | app.py, recruiter.py | 두 파일 모두 동일한 절대 경로 사용 |

---

## 평가 JSON 스키마 (build_final_payload 출력)

```json
{
  "project_notice": "...",
  "candidate_name": "홍길동",
  "candidate_email": "hong@example.com",
  "position": "개발자",
  "degree": "학사 (4년제)",
  "gpa": "4.2",
  "experience": "1~3년",
  "timestamp": "2026-05-07T10:00:00+00:00",
  "scores": {
    "culture_fit": 4,
    "customer_response": 4,
    "ownership": 5,
    "communication": 3,
    "learning_agility": 4,
    "overall": 4.0
  },
  "fit_level": "possible_match",
  "hiring_opinion": "보류",
  "hiring_recommendation_reason": "...",
  "summary": "...",
  "strengths": ["..."],
  "concerns": ["..."],
  "evidence_quotes": ["..."],
  "recommended_next_step": "...",
  "transcript": "면접관: ...\n지원자: ..."
}
```

- `fit_level`: `strong_match` / `possible_match` / `needs_human_review` / `weak_match`
- `hiring_opinion`: `추천` / `보류` / `비추천`

---

## Google Apps Script 연동

- `.env`의 `ZAPIER_WEBHOOK_URL`은 실제로 Google Apps Script 웹훅 URL
- GAS는 POST 수신 후 302 리다이렉트를 반환 → `send_to_zapier()`는 1차 POST 후 리다이렉트를 **GET**으로 처리 (POST로 재전송하면 405 발생)
- GAS `doPost()`가 스프레드시트에 기록하는 컬럼 순서 (19개):

```
타임스탬프 | 이름 | 이메일 | 포지션 | 학력 | 학점 | 경력 |
적합도 | 채용의견 | 추천이유 | 총점 | 문화적합도 | 고객응대 |
주인의식 | 커뮤니케이션 | 학습민첩성 | 요약 | 다음단계 | 전체대화
```

- GAS 코드 변경 시 반드시 **새 배포** 생성 후 `.env`의 URL 업데이트 필요

---

## Streamlit 세션 상태 키 목록

| 키 | 설명 |
|---|---|
| `onboarding_done` | 온보딩 폼 완료 여부 |
| `candidate_name` / `candidate_email` / `position` / `degree` / `gpa` / `experience` | 온보딩에서 수집한 지원자 정보 |
| `messages` | 전체 대화 기록 (system 포함) |
| `greeted` | 첫 인사 메시지 전송 여부 |
| `interview_done` | `[[INTERVIEW_COMPLETE]]` 감지 여부 |
| `final_payload` | 최종 평가 dict (생성 후 저장) |
| `zapier_status` | `(bool, str)` 전송 결과 |
| `dev_mode` | 개발자 모드 활성화 여부 |
| `dev_mode_pending` | 개발자 모드 암호 입력 대기 중 |
| `running_eval` | 개발자 모드 실시간 평가 dict |

---

## 알려진 동작 특이사항 / 주의점

1. **`load_dotenv(override=True)`**: OS 환경변수보다 `.env` 값 우선. `.env` 수정 후 반드시 앱 재시작.
2. **GAS 리다이렉트**: POST → 302 → GET 순서로 처리. POST를 두 번 보내면 405 오류.
3. **`messages` 초기화 시점**: 온보딩 완료 후, 포지션이 확정된 시점에 `_build_interview_prompt()`로 생성. 면접 중간에 포지션 변경 불가.
4. **`recruiter_config.json`**: 두 앱이 같은 파일 경로(`os.path.abspath(__file__)` 기준)를 공유. 파일이 없으면 `DEFAULT_POSITIONS`로 자동 생성.
5. **DUMMY_MODE**: `OPENAI_API_KEY`가 비어있으면 자동 활성화. 미리 준비된 7개 질문 순서대로 출력.
6. **개발자 모드**: 암호 인증 후 활성화. 좌우 분할 레이아웃(3:2)으로 실시간 채점 패널 표시.
7. **면접 강제 종료**: `MAX_ANSWERS`(8개) 도달 시 모델이 `[[INTERVIEW_COMPLETE]]`를 안 붙여도 강제 추가.

---

## LLM 교체 방법

`app.py`의 `llm_chat()`과 `llm_json()` 두 함수만 수정하면 됩니다. 나머지 로직 변경 불필요.

```python
# Anthropic 교체 예시
import anthropic
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def llm_chat(messages, temperature=0.4):
    resp = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1024,
        messages=[m for m in messages if m["role"] != "system"],
        system=next((m["content"] for m in messages if m["role"] == "system"), ""),
    )
    return resp.content[0].text
```

---

## 현재 작업 현황 (2026-05-07 기준)

- [x] 온보딩 폼 (이름/이메일/학력/경력/학점/포지션)
- [x] 채용 담당자 설정 페이지 (`recruiter.py`) — 포지션/기준 관리, 암호 보호
- [x] AI 면접 (포지션별 기준 동적 반영)
- [x] 5개 루브릭 자동 채점 + 채용 의견(추천/보류/비추천) 생성
- [x] Google Apps Script → 스프레드시트 19컬럼 자동 기록
- [x] 개발자 모드 (실시간 채점 패널, 암호 보호)
- [x] `recruiter_config.json` 공유 파일로 두 앱 연동
- [x] GAS 302 리다이렉트 → GET 처리 (405 오류 수정)

### 잠재적 개선 포인트 (아직 미구현)
- 면접 결과 히스토리 페이지 (스프레드시트 데이터 조회)
- 이메일 자동 발송 (GAS 또는 외부 서비스 연동)
- 다국어 지원
- 면접관 페르소나 커스터마이징 옵션
