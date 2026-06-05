/**
 * HireCopilot — GAS 멀티 시트 웹훅 라우터
 *
 * 배포: Google Sheets → 확장 프로그램 → Apps Script → 새 배포(웹 앱)
 * 액세스: 모든 사용자 / 실행: 나
 *
 * 스프레드시트 ID: 1swaf7dyRsVRxepLJAXVoPO3YRNV0aPYmcBLL4_tPnbE
 *
 * 탭(시트) — Python pipeline.py가 target으로 지정:
 *   interviews      면접 결과 DB (A~S, 19열). 없으면 Sheet1 폴백
 *   outbox_email    → Zap: Gmail
 *   outbox_slack    → Zap: Slack DM
 *   outbox_notion   → Zap: Notion Create Item
 *   outbox_docs     → Zap: Google Docs Insert Text
 *   outbox_zoom     → Zap: Zoom Create Meeting
 *   pipeline_log    파이프라인 로그 (Zap 불필요)
 *
 * POST JSON:
 *   { "target": "outbox_email", "row": ["ISO시간", "to@...", "제목", "HTML본문", "채용팀"] }
 *
 * 하위 호환: target 생략 + candidate_name 필드 → interviews 저장
 */

var SPREADSHEET_ID = "1swaf7dyRsVRxepLJAXVoPO3YRNV0aPYmcBLL4_tPnbE";

var INTERVIEWS_ALIASES = ["interviews", "Sheet1", "시트1"];

function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);
    var ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    var target = data.target || "";
    var row = data.row;

    if (!target && data.candidate_name !== undefined) {
      target = "interviews";
      row = buildInterviewRow_(data);
    }

    if (!target || !row) {
      return jsonResponse_({ result: "error", message: "target and row required" });
    }

    var sheet = getOrCreateSheet_(ss, target);
    sheet.appendRow(normalizeRow_(row));

    return jsonResponse_({ result: "success", target: target });
  } catch (err) {
    return jsonResponse_({ result: "error", message: err.toString() });
  }
}

function buildInterviewRow_(data) {
  var scores = data.scores || {};
  return [
    data.timestamp || "",
    data.candidate_name || "",
    data.candidate_email || "",
    data.position || "",
    data.degree || "",
    data.gpa || "",
    data.experience || "",
    data.fit_level || "",
    data.hiring_opinion || "",
    data.hiring_recommendation_reason || "",
    scores.overall !== undefined ? scores.overall : "",
    scores.culture_fit !== undefined ? scores.culture_fit : "",
    scores.customer_response !== undefined ? scores.customer_response : "",
    scores.ownership !== undefined ? scores.ownership : "",
    scores.communication !== undefined ? scores.communication : "",
    scores.learning_agility !== undefined ? scores.learning_agility : "",
    data.summary || "",
    data.recommended_next_step || "",
    data.transcript || ""
  ];
}

function getOrCreateSheet_(ss, name) {
  if (name === "interviews") {
    for (var i = 0; i < INTERVIEWS_ALIASES.length; i++) {
      var existing = ss.getSheetByName(INTERVIEWS_ALIASES[i]);
      if (existing) return existing;
    }
  }

  var sheet = ss.getSheetByName(name);
  if (sheet) return sheet;

  sheet = ss.insertSheet(name);
  var headers = HEADERS_[name];
  if (headers && headers.length) {
    sheet.appendRow(headers);
  }
  return sheet;
}

function normalizeRow_(row) {
  if (Object.prototype.toString.call(row) === "[object Array]") {
    return row;
  }
  return [String(row)];
}

function jsonResponse_(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

var HEADERS_ = {
  interviews: [
    "타임스탬프", "이름", "이메일", "포지션", "학력", "학점", "경력",
    "적합도", "채용의견", "추천이유", "총점", "문화적합도", "고객응대",
    "주인의식", "커뮤니케이션", "학습민첩성", "요약", "다음단계", "전체대화"
  ],
  outbox_email: ["timestamp", "to", "subject", "body", "from_name"],
  outbox_slack: ["timestamp", "recipient", "message"],
  outbox_notion: ["timestamp", "name", "database", "notes"],
  outbox_docs: ["timestamp", "candidate_name", "candidate_email", "content"],
  outbox_zoom: ["timestamp", "topic", "start_time_iso", "duration_min", "candidate_name"],
  pipeline_log: ["timestamp", "candidate_name", "branch", "screening", "detail"]
};
