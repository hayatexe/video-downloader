// node --test ile calisir; GitHub API'si sahte bir fetch ile taklit edilir.
const test = require("node:test");
const assert = require("node:assert");

process.env.GITHUB_TOKEN = "test";
process.env.AUTO_FIX_MIN_INSTALLS = "2";
const handler = require("../api/report.js");
const { handleReport, normalize, clean, readState } = handler._internal;

function fakeGitHub() {
  const issues = [];
  const comments = [];
  global.fetch = async (url, opts = {}) => {
    const u = new URL(url);
    const method = opts.method || "GET";
    const body = opts.body ? JSON.parse(opts.body) : null;
    let out;
    if (method === "GET" && u.pathname.endsWith("/issues")) {
      const state = u.searchParams.get("state");
      out = issues.filter((i) => state === "all" || i.state === state);
    } else if (method === "POST" && u.pathname.endsWith("/issues")) {
      out = { number: issues.length + 1, state: "open", ...body,
              labels: body.labels.map((name) => ({ name })) };
      issues.push(out);
    } else if (method === "PATCH") {
      const n = +u.pathname.split("/").pop();
      const i = issues.find((x) => x.number === n);
      if (body.body) i.body = body.body;
      if (body.state) i.state = body.state;
      if (body.labels) i.labels = body.labels.map((name) => ({ name }));
      out = i;
    } else if (method === "POST" && u.pathname.endsWith("/comments")) {
      comments.push(body.body);
      out = {};
    }
    return { ok: true, status: 200, json: async () => out, text: async () => "" };
  };
  return { issues, comments };
}

const base = {
  schema: 1,
  fingerprint: "d2c19332a28d",
  kind: "download",
  message: "ERROR: [download] Got error: [SSL: INVALID_SESSION_ID] invalid session id (_ssl.c:1010). Giving up after 10 retries",
  user_message: "Guvenli baglanti kurulamadi",
  site: "youtube.com",
  attempts: [{ label: "cerezsiz", error: "SSL" }],
  app_version: "1.3.0",
  ytdlp_version: "2026.10.26",
  python: "3.12.7",
  os: "Windows 11",
  frozen: true,
  install_id: "aaaaaaaaaaaaaaaa",
  extra: { mode: "video_audio" },
};

test("ayni hata tek issue'da toplanir, 2. kurulumda auto-fix eklenir", async () => {
  const gh = fakeGitHub();
  let r = await handleReport(normalize(base));
  assert.equal(r.action, "created");
  assert.deepEqual(r.labels, ["error-report"]);

  r = await handleReport(normalize(base)); // ayni kurulum
  assert.equal(r.action, "updated");
  assert.equal(gh.issues.length, 1);
  assert.equal(gh.comments.length, 0);

  r = await handleReport(normalize({ ...base, install_id: "bbbbbbbbbbbbbbbb" }));
  assert.ok(r.labels.includes("auto-fix"));
  const st = readState(gh.issues[0].body);
  assert.equal(st.count, 3);
  assert.equal(st.installs_total, 2);
  assert.equal(gh.comments.length, 1);
});

test("kapali issue: eski surumden gelirse acilmaz, yeni surumden gelirse acilir", async () => {
  const gh = fakeGitHub();
  await handleReport(normalize(base));
  gh.issues[0].state = "closed";
  let r = await handleReport(normalize(base));
  assert.equal(r.action, "counted-closed");
  assert.equal(gh.issues[0].state, "closed");
  r = await handleReport(normalize({ ...base, app_version: "1.3.1" }));
  assert.equal(r.action, "reopened");
  assert.equal(gh.issues[0].state, "open");
});

test("Python istisnasi dogrudan auto-fix alir", async () => {
  fakeGitHub();
  const r = await handleReport(normalize({ ...base, kind: "info-crash",
    extra: { traceback: "KeyError: 'x'" } }));
  assert.ok(r.labels.includes("auto-fix"));
});

test("kullanici metni kimseyi etiketlemez, kod blogunu kirmaz", () => {
  const c = clean("@hayatexe ```rm``` <script>", 100);
  assert.ok(!c.includes("@h"));
  assert.ok(!c.includes("`"));
  assert.ok(!c.includes("<script>"));
});

test("HTTP: yanlis istemci ve bozuk govde reddedilir", async () => {
  fakeGitHub();
  const res = () => {
    const o = { code: 0, body: null };
    o.status = (c) => { o.code = c; return o; };
    o.json = (b) => { o.body = b; return o; };
    return o;
  };
  let out = res();
  await handler({ method: "POST", headers: { "user-agent": "curl" }, body: base }, out);
  assert.equal(out.code, 403);
  out = res();
  await handler({ method: "POST", headers: { "user-agent": "VideoDownloader/1.3.0" },
                  body: { ...base, fingerprint: "x" } }, out);
  assert.equal(out.code, 400);
  out = res();
  await handler({ method: "POST", headers: { "user-agent": "VideoDownloader/1.3.0" }, body: base }, out);
  assert.equal(out.code, 202);
});
