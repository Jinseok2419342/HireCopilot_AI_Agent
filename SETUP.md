# 처음 설정 및 실행 방법 (Windows / PowerShell)

이 프로젝트는 두 개의 Streamlit 앱을 실행합니다.

- `app.py`: 지원자 AI 면접 앱, 기본 포트 `8501`
- `recruiter.py`: 채용 담당자 관리자 콘솔, 포트 `8502`

지원자 앱에서 면접을 완료하면 `pipeline.py`가 결과를 처리합니다. Google Apps Script와 Zapier를 연결하면 Google Sheets 저장, Gmail, Slack, Notion, Docs, Zoom 후속 작업까지 이어집니다.

외부 연동 없이 화면만 먼저 확인할 수도 있습니다. `OPENAI_API_KEY`가 없으면 지원자 앱은 데모 모드로 동작하고, `GAS_WEBHOOK_URL`이 없으면 Google Sheets/Zapier 전송은 건너뜁니다.

## 1단계: Python 확인

Python 3.11 또는 3.12를 권장합니다. PowerShell에서 아래 명령어를 실행합니다.

```powershell
python --version
```

정상 예시:

```text
Python 3.12.4
```

`python` 명령을 찾을 수 없다는 오류가 나오면 Python을 설치할 때 `Add Python to PATH` 옵션을 켠 뒤 PowerShell을 새로 열어 다시 확인합니다.

## 2단계: 프로젝트 폴더로 이동

현재 프로젝트 위치가 `C:\Users\USER\Desktop\HireCopilot_AI_Agent`라면 PowerShell에서 아래처럼 이동합니다.

```powershell
cd C:\Users\USER\Desktop\HireCopilot_AI_Agent
```

폴더가 맞는지 확인하려면 아래 명령어를 실행합니다.

```powershell
dir
```

`app.py`, `recruiter.py`, `requirements.txt`, `SETUP.md`가 보이면 올바른 위치입니다.

## 3단계: 가상환경 생성 및 활성화

처음 한 번만 가상환경을 만듭니다.

```powershell
python -m venv .venv
```

그다음 가상환경을 활성화합니다.

```powershell
.\.venv\Scripts\Activate.ps1
```

활성화되면 PowerShell 앞쪽에 `(.venv)`가 붙습니다.

```text
(.venv) PS C:\Users\USER\Desktop\HireCopilot_AI_Agent>
```

PowerShell 실행 정책 오류가 나면 아래 명령어를 한 번 실행한 뒤, 다시 활성화 명령을 실행합니다.

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
```

다음부터 실행할 때는 프로젝트 폴더로 이동한 뒤 활성화 명령만 다시 실행하면 됩니다.

## 4단계: 패키지 설치

가상환경이 활성화된 상태에서 필요한 패키지를 설치합니다.

```powershell
pip install -r requirements.txt
```

설치가 끝난 뒤 Streamlit이 설치되었는지 확인할 수 있습니다.

```powershell
streamlit --version
```

## 5단계: `.env` 파일 만들기

`.env.example` 파일을 복사해서 `.env` 파일을 만듭니다.

```powershell
Copy-Item .env.example .env
```

그다음 메모장으로 `.env`를 엽니다.

```powershell
notepad .env
```

기본 예시는 아래와 같습니다.

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini

GAS_WEBHOOK_URL=https://script.google.com/macros/s/XXXX/exec

ADMIN_EMAIL=you@example.com
ADMIN_SLACK_USER_ID=U0XXXXXXX
NOTION_DATABASE_LABEL=2026 보류 합격자 목록

PIPELINE_MIN_GPA=3.0
PIPELINE_REQUIRE_GPA=true
PIPELINE_BLOCK_NEWGRAD=false

DEV_TOGGLE_PASSWORD=1234
RECRUITER_PASSWORD=1234
```

처음 화면만 확인하려면 아래 값만 있어도 됩니다.

```env
OPENAI_MODEL=gpt-4o-mini
DEV_TOGGLE_PASSWORD=1234
RECRUITER_PASSWORD=1234
```

실제 OpenAI 면접을 사용하려면 `OPENAI_API_KEY`를 입력합니다. Google Sheets와 Zapier까지 연결하려면 `GAS_WEBHOOK_URL`, `ADMIN_EMAIL`, `ADMIN_SLACK_USER_ID`도 실제 값으로 바꿉니다.

`.env` 파일을 수정한 뒤에는 실행 중인 Streamlit 앱을 `Ctrl + C`로 종료하고 다시 실행해야 반영됩니다.

## 6단계: 지원자 면접 앱 실행

첫 번째 PowerShell 창에서 아래 명령어를 실행합니다.

```powershell
cd C:\Users\USER\Desktop\HireCopilot_AI_Agent
.\.venv\Scripts\Activate.ps1
streamlit run app.py
```

브라우저가 자동으로 열리지 않으면 아래 주소로 접속합니다.

```text
http://localhost:8501
```

지원자 앱에서 확인할 흐름:

1. 이름, 이메일, 학력, 경력, 학점, 지원 포지션을 입력합니다.
2. AI 면접 질문에 답변합니다.
3. 면접을 완료합니다.
4. 평가 결과와 `hiring_opinion`이 생성되는지 확인합니다.

`OPENAI_API_KEY`가 비어 있으면 데모 모드로 표시됩니다. 실제 모델 응답을 보려면 `.env`에 OpenAI API 키를 넣고 앱을 다시 시작합니다.

## 7단계: 관리자 콘솔 실행

두 번째 PowerShell 창을 새로 열고 아래 명령어를 실행합니다.

```powershell
cd C:\Users\USER\Desktop\HireCopilot_AI_Agent
.\.venv\Scripts\Activate.ps1
streamlit run recruiter.py --server.port 8502
```

브라우저에서 아래 주소로 접속합니다.

```text
http://localhost:8502
```

관리자 콘솔 비밀번호는 `.env`의 `RECRUITER_PASSWORD` 값입니다. 예시 그대로 두었다면 `1234`입니다.

관리자 콘솔에서 확인할 수 있는 내용:

- 최근 면접 결과와 추천/보류/비추천 현황
- 지원자별 평가 JSON, 요약, 우려사항, 대화 기록
- outbox 전송 상태와 실패 항목 재전송
- Zapier 연결 가이드
- 채용 필터 설정

## 8단계: 테스트 실행

앱 실행과 별개로 코드 테스트를 실행하려면 PowerShell에서 아래 명령어를 실행합니다.

```powershell
cd C:\Users\USER\Desktop\HireCopilot_AI_Agent
.\.venv\Scripts\Activate.ps1
python -m unittest tests/test_pipeline.py tests/test_admin_store.py
```

성공하면 마지막에 `OK`가 표시됩니다.

## 9단계: Google Apps Script 연결

Google Sheets/Zapier 연동까지 사용하려면 GAS 웹훅을 먼저 배포합니다.

1. Google Sheets 문서 `1swaf7dyRsVRxepLJAXVoPO3YRNV0aPYmcBLL4_tPnbE`를 엽니다.
2. 상단 메뉴에서 `확장 프로그램 -> Apps Script`로 이동합니다.
3. 프로젝트의 `gas/webhook_router.gs` 내용을 Apps Script 편집기에 붙여 넣습니다.
4. `배포 -> 새 배포`를 선택합니다.
5. 유형은 `웹 앱`을 선택합니다.
6. 실행 권한은 `나`, 액세스 권한은 테스트 목적이면 `모든 사용자`로 설정합니다.
7. 배포 후 발급된 웹 앱 URL을 복사합니다.
8. `.env`의 `GAS_WEBHOOK_URL`에 붙여 넣습니다.

예시:

```env
GAS_WEBHOOK_URL=https://script.google.com/macros/s/XXXX/exec
```

GAS는 필요한 탭이 없으면 자동으로 생성합니다.

```text
interviews
outbox_email
outbox_slack
outbox_notion
outbox_docs
outbox_zoom
outbox_scheduled
pipeline_log
```

GAS URL을 바꾼 뒤에는 두 Streamlit 앱을 모두 종료하고 다시 실행합니다.

## 10단계: Zapier 연결

Zapier는 Python 코드가 Google Sheets의 outbox 탭에 추가한 행을 감지해서 실제 앱 동작을 실행합니다. 현재 연결된 Zap은 `email`, Google Docs, Notion, `Scheduled`, `zoom`입니다.

### 현재 연결된 Zap: `email`

`email` Zap은 `outbox_email` 워크시트에 새 행이 추가될 때마다 Gmail로 이메일을 자동 발송합니다. 현재 Zapier에서 Published 상태로 켜져 있습니다.

1단계 Trigger:

```text
Google Sheets -> New Row
```

Trigger 설정:

| 항목 | 값 |
|---|---|
| 스프레드시트 | `HireCopilot database` |
| 워크시트 | `outbox_email` |
| 동작 조건 | `outbox_email`에 새 행이 추가되면 실행 |

2단계 Action:

```text
Gmail -> Send Email
```

Gmail 필드 매핑:

| Gmail 항목 | Google Sheets 출처 |
|---|---|
| 수신자 | 열 B, `COL$B` |
| 제목 | 열 C, `COL$C` |
| 본문 | 열 D, `COL$D` |
| 발신자 이름 | 열 E, `COL$E` |
| 발신 이메일 | `sangbusangjo123@gmail.com` 고정 |

작동 흐름:

1. 지원자 면접 또는 관리자 재전송 과정에서 `pipeline.py`가 이메일 발송 내용을 만듭니다.
2. GAS 웹훅이 Google Sheets의 `outbox_email` 워크시트에 새 행을 추가합니다.
3. Zapier의 `email` Zap이 새 행을 감지합니다.
4. Zap이 B열, C열, D열, E열 값을 읽습니다.
5. Gmail 계정 `sangbusangjo123@gmail.com`에서 이메일을 발송합니다.

따라서 이메일이 발송되지 않으면 먼저 Google Sheets의 `outbox_email` 탭에 새 행이 실제로 추가되었는지 확인합니다. 행이 있는데 메일이 안 나가면 Zapier의 `email` Zap 실행 기록에서 Gmail 단계 오류를 확인합니다.

### 현재 연결된 Zap: Google Docs

Google Docs Zap은 `outbox_docs` 워크시트에 새 행이 추가될 때마다 Google Docs 문서에 2차 면접 질문을 누적합니다.

| 항목 | 값 |
|---|---|
| Trigger | Google Sheets `New Row` |
| 스프레드시트 | `HireCopilot database` |
| 워크시트 | `outbox_docs` |
| Action | Google Docs `Append` |
| 대상 문서 | `2차 면접 질문 모음` |
| Drive | `My Google Drive` |
| 추가 내용 | D열, `COL$D` |

작동 흐름:

1. 보류 지원자에 대해 2차 면접 질문이 생성됩니다.
2. GAS가 `outbox_docs`에 새 행을 추가합니다.
3. Zap이 D열의 내용을 읽습니다.
4. `2차 면접 질문 모음` 문서 끝에 텍스트를 추가합니다.

### 현재 연결된 Zap: Notion

Notion Zap은 `outbox_notion` 워크시트에 새 행이 추가될 때마다 Notion 데이터베이스에 후보자 항목을 만듭니다.

| 항목 | 값 |
|---|---|
| Trigger | Google Sheets `New Row` |
| 스프레드시트 | `HireCopilot database` |
| 워크시트 | `outbox_notion` |
| Action | Notion 데이터베이스 항목 생성 |
| 대상 데이터베이스 | `2026 보류 합격자 목록` |
| Name / 제목 | B열 |
| Content / 내용 | D열 |

작동 흐름:

1. `outbox_notion`에 새 행이 추가됩니다.
2. Zap이 B열과 D열을 읽습니다.
3. Notion의 `2026 보류 합격자 목록` 데이터베이스에 새 항목을 생성합니다.

### 현재 연결된 Zap: `Scheduled`

`Scheduled` Zap은 `outbox_scheduled` 워크시트에 새 행이 추가되면 예약 날짜까지 기다린 뒤 후보자에게 이메일을 발송합니다.

| 단계 | 설정 |
|---|---|
| 1. Trigger | Google Sheets `New Row`, `outbox_scheduled` |
| 2. Delay Until | B열의 전송 예정 날짜까지 대기 |
| 3. Notion 검색 | F열 후보자 이름으로 `2026 보류 합격자 목록` 검색 |
| 4. Gmail 발송 | C열 수신자, D열 제목, E열 HTML 본문 |

`Scheduled` Zap에서 사용하는 열:

| 열 | 의미 |
|---|---|
| B열 | 전송 예정 날짜 |
| C열 | 이메일 받을 주소 |
| D열 | 이메일 제목 |
| E열 | 이메일 본문 |
| F열 | Notion에서 검색할 후보자 이름 |

발신 이메일은 `sangbusangjo123@gmail.com`으로 고정되어 있습니다.

### 현재 연결된 Zap: `zoom`

`zoom` Zap은 `outbox_zoom` 워크시트에 새 행이 추가될 때마다 Zoom 회의를 자동 생성합니다.

| 항목 | 값 |
|---|---|
| Trigger | Google Sheets `New Row` |
| 스프레드시트 | `HireCopilot database` |
| 워크시트 | `outbox_zoom` |
| Action | Zoom 회의 생성 |
| 회의 유형 | 일반 회의, 1회성 |
| 회의 제목 | B열 |
| 회의 시작 시간 | C열 |
| 회의 시간/기간 | D열 |

### 아직 문서화하지 않은 Zap

Slack 알림 Zap은 아직 실제 설정 설명을 받지 않았습니다. `.env`의 `ADMIN_SLACK_USER_ID`를 비워두면 파이프라인은 Slack outbox를 만들지 않습니다.

## 11단계: 시연 체크리스트

실행 후 아래 순서로 확인하면 전체 흐름을 점검할 수 있습니다.

- `http://localhost:8501`에서 지원자 면접을 1건 완료합니다.
- Google Sheets의 `interviews` 탭에 면접 결과가 추가되는지 확인합니다.
- `hiring_opinion`에 따라 `outbox_*` 탭에 행이 추가되는지 확인합니다.
- Zapier가 켜져 있다면 Gmail/Slack/Notion/Docs/Zoom 액션이 실행되는지 확인합니다.
- `http://localhost:8502`에서 관리자 콘솔에 최신 면접 기록과 outbox 상태가 보이는지 확인합니다.
- 실패한 outbox가 있다면 관리자 콘솔에서 재전송을 눌러 동작을 확인합니다.

## 자주 생기는 문제

### `streamlit` 명령을 찾을 수 없음

가상환경이 활성화되지 않았거나 패키지 설치가 안 된 상태입니다.

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### `Activate.ps1` 실행 정책 오류

아래 명령어를 한 번 실행합니다.

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

그다음 다시 활성화합니다.

```powershell
.\.venv\Scripts\Activate.ps1
```

### 포트가 이미 사용 중임

다른 Streamlit 앱이 이미 실행 중일 수 있습니다. 기존 PowerShell 창에서 `Ctrl + C`로 종료하거나 다른 포트를 사용합니다.

```powershell
streamlit run app.py --server.port 8503
streamlit run recruiter.py --server.port 8504
```

### 관리자 콘솔 비밀번호를 모름

`.env`의 `RECRUITER_PASSWORD` 값을 확인합니다.

```powershell
notepad .env
```

### 면접은 끝났는데 Google Sheets에 저장되지 않음

아래 항목을 확인합니다.

- `.env`에 `GAS_WEBHOOK_URL`이 들어 있는지 확인합니다.
- GAS 웹 앱 URL이 `/exec`로 끝나는 배포 URL인지 확인합니다.
- `.env` 수정 후 Streamlit 앱을 재시작했는지 확인합니다.
- Apps Script 배포 권한이 웹 요청을 받을 수 있게 설정되었는지 확인합니다.

### OpenAI 응답이 데모처럼 나옴

`.env`에 `OPENAI_API_KEY`가 없으면 데모 모드로 실행됩니다. 실제 키를 넣은 뒤 Streamlit 앱을 재시작합니다.

```env
OPENAI_API_KEY=sk-...
```

## 매번 실행할 때 필요한 명령어 요약

지원자 앱:

```powershell
cd C:\Users\USER\Desktop\HireCopilot_AI_Agent
.\.venv\Scripts\Activate.ps1
streamlit run app.py
```

관리자 콘솔:

```powershell
cd C:\Users\USER\Desktop\HireCopilot_AI_Agent
.\.venv\Scripts\Activate.ps1
streamlit run recruiter.py --server.port 8502
```

테스트:

```powershell
cd C:\Users\USER\Desktop\HireCopilot_AI_Agent
.\.venv\Scripts\Activate.ps1
python -m unittest tests/test_pipeline.py tests/test_admin_store.py
```

[README.md로 돌아가기](README.md)
