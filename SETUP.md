# 처음 세팅 및 실행 방법 (Windows / PowerShell)

이 프로젝트는 두 개의 Streamlit 앱을 실행합니다.

- `app.py`: 지원자 면접 앱, 기본 포트 `8501`
- `recruiter.py`: 통합 관리자 콘솔, 포트 `8502`

## 1단계: Python 확인

Python 3.11 또는 3.12를 권장합니다. PowerShell에서 아래 명령이 동작해야 합니다.

```powershell
python --version
```

`python` 명령을 찾을 수 없다면 Python 설치 시 `Add Python to PATH` 옵션을 켜고 다시 설치하세요.

## 2단계: 프로젝트 폴더 이동 및 가상환경 생성

```powershell
cd C:\Users\316\Documents\GitHub\HireCopilot_AI_Agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

PowerShell 실행 정책 오류가 나면 한 번만 아래 명령을 실행한 뒤 다시 활성화합니다.

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

## 3단계: 패키지 설치

```powershell
pip install -r requirements.txt
```

## 4단계: `.env` 설정

`.env.example`을 `.env`로 복사하고 값을 채웁니다.

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini

# GAS 웹훅 URL: interviews + outbox_* 시트에 행을 추가
GAS_WEBHOOK_URL=https://script.google.com/macros/s/XXXX/exec

# 관리자 알림과 outbox 설정
ADMIN_EMAIL=you@example.com
ADMIN_SLACK_USER_ID=U0XXXXXXX
NOTION_DATABASE_LABEL=2026 보류 합격자 목록

# 파이프라인 필터
PIPELINE_MIN_GPA=3.0
PIPELINE_REQUIRE_GPA=true
PIPELINE_BLOCK_NEWGRAD=false

# 앱 접근 암호
DEV_TOGGLE_PASSWORD=1234
RECRUITER_PASSWORD=1234
```

`.env`를 바꾼 뒤에는 Streamlit 앱을 완전히 종료하고 다시 실행해야 합니다.

## 5단계: Google Apps Script 배포

1. 스프레드시트 `1swaf7dyRsVRxepLJAXVoPO3YRNV0aPYmcBLL4_tPnbE`를 엽니다.
2. `확장 프로그램 -> Apps Script`로 이동합니다.
3. `gas/webhook_router.gs` 내용을 Apps Script에 붙여넣습니다.
4. `배포 -> 새 배포 -> 웹 앱`을 선택합니다.
5. 실행 권한은 `나`, 액세스 권한은 `모든 사용자`로 설정합니다.
6. 발급된 웹 앱 URL을 `.env`의 `GAS_WEBHOOK_URL`에 넣습니다.

GAS는 아래 탭이 없으면 자동으로 생성합니다.

```text
interviews
outbox_email
outbox_slack
outbox_notion
outbox_docs
outbox_zoom
pipeline_log
```

## 6단계: Zapier 앱별 Zap 생성

Zapier는 앱 연결만 담당합니다. 필터, 분기, 2차 질문 생성은 `pipeline.py`에서 처리합니다.

각 Zap의 Trigger는 모두 `Google Sheets -> New Spreadsheet Row`입니다. Trigger 시트만 outbox별로 다르게 지정합니다.

| Zap 이름 예시 | Trigger 시트 | Action 앱 | 필수 매핑 |
|---|---|---|---|
| `outbox_email_to_gmail` | `outbox_email` | Gmail Send Email | To=`to`, Subject=`subject`, Body=`body` |
| `outbox_slack_to_dm` | `outbox_slack` | Slack Send Direct Message | User=`recipient`, Message=`message` |
| `outbox_notion_to_db` | `outbox_notion` | Notion Create Database Item | Name=`name`, Notes=`notes` |
| `outbox_docs_to_doc` | `outbox_docs` | Google Docs Append Text | Text=`content`, 문서 ID는 Zap에서 고정 |
| `outbox_zoom_to_meeting` | `outbox_zoom` | Zoom Create Meeting | Topic=`topic`, Start=`start_time_iso`, Duration=`duration_min` |

예시: Gmail Zap

1. Trigger: Google Sheets, New Spreadsheet Row
2. Spreadsheet: `1swaf7dyRsVRxepLJAXVoPO3YRNV0aPYmcBLL4_tPnbE`
3. Worksheet: `outbox_email`
4. Action: Gmail, Send Email
5. `to`, `subject`, `body` 컬럼을 Gmail 필드에 매핑
6. Zap 켜기

나머지 앱도 같은 방식으로 `outbox_*` 탭만 바꿔 연결합니다.

## 7단계: 앱 실행

터미널 1개에서 지원자 앱을 실행합니다.

```powershell
streamlit run app.py
```

브라우저:

```text
http://localhost:8501
```

다른 터미널에서 관리자 콘솔을 실행합니다.

```powershell
.\.venv\Scripts\Activate.ps1
streamlit run recruiter.py --server.port 8502
```

브라우저:

```text
http://localhost:8502
```

관리자 콘솔에서는 대시보드, 지원자 결과, outbox 상태, Zapier 연결 가이드, 채용 담당 설정을 확인할 수 있습니다.

## 8단계: 테스트

```powershell
python -m unittest tests/test_pipeline.py tests/test_admin_store.py
```

## 9단계: 시연 체크리스트

- 지원자 앱에서 면접 1회 완료
- `interviews` 탭에 면접 결과 1행 추가 확인
- `hiring_opinion`에 따라 `outbox_*` 탭에 행 추가 확인
- Zapier가 연결된 앱에서 메일/Slack/Notion/Docs/Zoom 동작 확인
- 관리자 콘솔에서 최신 면접 기록과 outbox 상태 확인

[README.md로 돌아가기](README.md)
