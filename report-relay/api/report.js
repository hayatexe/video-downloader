// Uygulamadan gelen anonim hata raporlarini GitHub issue'larina ceviren role.
//
// Neden ayri bir sunucu: issue acmak icin GitHub token'i lazim. Token exe'nin
// icine konsaydi herkes cikarip depoya istedigi kadar issue acabilirdi. Token
// burada, Vercel'in ortam degiskeninde durur; uygulama sadece bu adresi bilir.
//
// Ne yapar:
//   * Ayni hata (ayni parmak izi) tek bir issue'da toplanir; her yeni rapor
//     sayaci, etkilenen kurulum sayisini ve surumleri gunceller.
//   * Hata en az AUTO_FIX_MIN_INSTALLS farkli kurulumda goruldugunde ya da
//     Python'un yakalanmamis bir istisnasiysa (kesin kod hatasi) issue'ya
//     "auto-fix" etiketi eklenir. .github/workflows/auto-fix.yml bu etiketi
//     gorunce Claude'u calistirir.
//   * Kapatilmis bir hata daha YENI bir uygulama surumunde tekrar gelirse
//     issue yeniden acilir (duzeltme tutmamis). Eski surumden gelirse acilmaz;
//     o kisi henuz guncellememis demektir.
//
// Ortam degiskenleri (Vercel -> Project -> Settings -> Environment Variables):
//   GITHUB_TOKEN           zorunlu. Fine-grained token, sadece bu depo,
//                          Issues: Read and write.
//   GITHUB_REPO            varsayilan hayatexe/video-downloader
//   AUTO_FIX_MIN_INSTALLS  varsayilan 2
//   MAX_OPEN_REPORTS       varsayilan 40 (bundan fazla acik rapor varsa yeni
//                          issue acilmaz, mevcutlar guncellenmeye devam eder)

const REPO = process.env.GITHUB_REPO || "hayatexe/video-downloader";
const AUTO_FIX_MIN_INSTALLS = parseInt(process.env.AUTO_FIX_MIN_INSTALLS || "2", 10);
const MAX_OPEN_REPORTS = parseInt(process.env.MAX_OPEN_REPORTS || "40", 10);
const LABEL = "error-report";
const AUTO_FIX_LABEL = "auto-fix";
const MAX_BODY_BYTES = 16 * 1024;
const MAX_INSTALLS_TRACKED = 200;

// Ayni IP'den dakikada en fazla bu kadar rapor (sicak instance basina, kaba
// bir koruma; uygulama zaten ayni hatayi gunde bir kez gonderiyor).
const RATE_PER_MIN = 10;
const rate = new Map();

// ---------------------------------------------------------------------------
// Dogrulama ve temizleme
// ---------------------------------------------------------------------------

function str(v, max) {
  return String(v == null ? "" : v).slice(0, max);
}

// Kullanicidan gelen metin issue'ya girerken kimseyi etiketlememeli (@ad),
// kod blogunu kirmamali ve HTML olarak yorumlanmamali.
function clean(v, max) {
  return str(v, max)
    .replace(/@/g, "@​")
    .replace(/`/g, "'")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/[\u0000-\u0008\u000b-\u001f]/g, "");
}

function validate(p) {
  if (!p || typeof p !== "object") return "body";
  if (p.schema !== 1) return "schema";
  if (!/^[0-9a-f]{12}$/.test(p.fingerprint || "")) return "fingerprint";
  if (!p.message || typeof p.message !== "string") return "message";
  if (!/^[0-9a-f]{16}$/.test(p.install_id || "")) return "install_id";
  if (!/^[\w.-]{1,20}$/.test(p.app_version || "")) return "app_version";
  return null;
}

function normalize(p) {
  return {
    fingerprint: p.fingerprint,
    kind: str(p.kind, 20).replace(/[^\w-]/g, "") || "download",
    message: clean(p.message, 1500),
    user_message: clean(p.user_message, 300),
    site: str(p.site, 60).replace(/[^\w.-]/g, ""),
    attempts: (Array.isArray(p.attempts) ? p.attempts : []).slice(-8).map((a) => ({
      label: clean(a && a.label, 40),
      error: clean(a && a.error, 400),
    })),
    app_version: str(p.app_version, 20),
    ytdlp_version: str(p.ytdlp_version, 20).replace(/[^\w.-]/g, ""),
    python: str(p.python, 20).replace(/[^\w.-]/g, ""),
    os: clean(p.os, 40),
    frozen: !!p.frozen,
    install_id: p.install_id,
    extra: Object.fromEntries(
      Object.entries(p.extra && typeof p.extra === "object" ? p.extra : {})
        .slice(0, 10)
        .map(([k, v]) => [str(k, 40).replace(/[^\w-]/g, ""), clean(v, 600)])
    ),
  };
}

// ---------------------------------------------------------------------------
// Issue govdesi. Durum, gizli bir HTML yorumunda saklanir; ayri bir veritabani
// gerekmez.
// ---------------------------------------------------------------------------

const STATE_RE = /<!-- vd-state (\{.*?\}) -->/s;

function readState(body) {
  const m = STATE_RE.exec(body || "");
  if (!m) return null;
  try {
    return JSON.parse(m[1]);
  } catch {
    return null;
  }
}

function versionTuple(v) {
  return String(v || "0").split(".").map((x) => parseInt(x, 10) || 0);
}

function versionGt(a, b) {
  const x = versionTuple(a);
  const y = versionTuple(b);
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0);
  }
  return false;
}

function maxVersion(versions) {
  return Object.keys(versions || {}).reduce((m, v) => (versionGt(v, m) ? v : m), "0");
}

function newState(r, now) {
  return {
    fp: r.fingerprint,
    count: 0,
    installs: [],
    versions: {},
    ytdlp: {},
    sites: {},
    kinds: {},
    first: now,
    last: now,
  };
}

function applyReport(state, r, now) {
  const s = JSON.parse(JSON.stringify(state));
  const isNewInstall = !s.installs.includes(r.install_id);
  const isNewVersion = !(r.app_version in s.versions);
  s.count += 1;
  if (isNewInstall) {
    s.installs.push(r.install_id);
    if (s.installs.length > MAX_INSTALLS_TRACKED) s.installs.shift();
  }
  s.installs_total = (s.installs_total || 0) + (isNewInstall ? 1 : 0);
  s.versions[r.app_version] = (s.versions[r.app_version] || 0) + 1;
  if (r.ytdlp_version) s.ytdlp[r.ytdlp_version] = (s.ytdlp[r.ytdlp_version] || 0) + 1;
  if (r.site) s.sites[r.site] = (s.sites[r.site] || 0) + 1;
  s.kinds[r.kind] = (s.kinds[r.kind] || 0) + 1;
  s.last = now;
  return { state: s, isNewInstall, isNewVersion };
}

function needsAutoFix(state, r) {
  if (r.kind === "info-crash" || r.extra.traceback) return true;
  return (state.installs_total || 0) >= AUTO_FIX_MIN_INSTALLS;
}

function fmtCounts(obj) {
  const e = Object.entries(obj || {}).sort((a, b) => b[1] - a[1]);
  return e.length ? e.map(([k, v]) => `${k} (${v})`).join(", ") : "-";
}

function title(r) {
  const short = r.message
    .replace(/^ERROR:\s*/i, "")
    .replace(/&lt;|&gt;/g, "")
    .slice(0, 90);
  return `[Hata] ${short} (${r.fingerprint})`;
}

function renderBody(state, r) {
  const attempts = r.attempts.length
    ? r.attempts.map((a, i) => `${i + 1}. **${a.label || "?"}**: ${a.error || "-"}`).join("\n")
    : "_kayit yok_";
  const extra = Object.entries(r.extra)
    .filter(([k]) => k !== "traceback")
    .map(([k, v]) => `\`${k}\`=${v}`)
    .join(", ");
  const tb = r.extra.traceback
    ? `\n### Traceback (son satirlar)\n\n~~~\n${r.extra.traceback}\n~~~\n`
    : "";

  return `> Bu issue uygulamanin otomatik hata raporlarindan olusturuldu. Ayni hata
> tekrar geldikce asagidaki sayilar guncellenir. Kisisel bilgi ve video linki
> gonderilmez; mesajlar uygulamada temizlenir.

### Hata

~~~
${r.message}
~~~

Kullanicinin gordugu: ${r.user_message || "-"}

### Ne kadar yaygin

| | |
|---|---|
| Toplam rapor | ${state.count} |
| Etkilenen kurulum | ${state.installs_total || state.installs.length} |
| Uygulama surumleri | ${fmtCounts(state.versions)} |
| yt-dlp surumleri | ${fmtCounts(state.ytdlp)} |
| Siteler | ${fmtCounts(state.sites)} |
| Nerede | ${fmtCounts(state.kinds)} |
| Ilk / son | ${state.first} / ${state.last} |

### Son raporda denenen yollar

${attempts}
${tb}
### Son raporun ortami

Uygulama ${r.app_version}${r.frozen ? "" : " (kaynaktan)"}, yt-dlp ${r.ytdlp_version || "?"}, Python ${r.python || "?"}, ${r.os || "?"}${extra ? `\nSecenekler: ${extra}` : ""}

### Duzeltme icin ipuclari

* Hatayi ureten yol \`app.py\` icindeki \`extract_with_cookie_fallback\`; kullaniciya giden mesaj \`friendly_error\`.
* Her deneme kullanicinin bilgisayarinda \`%LOCALAPPDATA%\\Video Downloader\\download.log\` dosyasina da yaziliyor.
* Duzeltme yeni bir surumle cikinca bu issue'yu kapatin. Ayni hata daha yeni bir surumden gelirse issue kendiliginden yeniden acilir.

<!-- vd-state ${JSON.stringify(state)} -->
`;
}

// ---------------------------------------------------------------------------
// GitHub
// ---------------------------------------------------------------------------

async function gh(path, opts = {}) {
  const res = await fetch(`https://api.github.com${path}`, {
    ...opts,
    headers: {
      Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "video-downloader-report-relay",
      ...(opts.body ? { "Content-Type": "application/json" } : {}),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`GitHub ${opts.method || "GET"} ${path}: ${res.status} ${text.slice(0, 200)}`);
  }
  return res.status === 204 ? null : res.json();
}

// Arama API'si yerine liste: arama indeksi dakikalarca gecikebiliyor ve ayni
// hata ust uste geldiginde cift issue aciliyordu. Etiketle filtrelenmis son
// 100 issue icinde parmak izini basliktan bulmak hem anlik hem yeterli.
async function findIssue(fp) {
  const issues = await gh(
    `/repos/${REPO}/issues?labels=${LABEL}&state=all&sort=updated&direction=desc&per_page=100`
  );
  const tag = `(${fp})`;
  return issues.find((i) => !i.pull_request && i.title.endsWith(tag)) || null;
}

async function countOpen() {
  const issues = await gh(`/repos/${REPO}/issues?labels=${LABEL}&state=open&per_page=100`);
  return issues.filter((i) => !i.pull_request).length;
}

async function handleReport(r, now = new Date().toISOString().slice(0, 16).replace("T", " ")) {
  const issue = await findIssue(r.fingerprint);

  if (!issue) {
    if ((await countOpen()) >= MAX_OPEN_REPORTS) return { action: "skipped-cap" };
    const { state } = applyReport(newState(r, now), r, now);
    const labels = [LABEL];
    if (needsAutoFix(state, r)) labels.push(AUTO_FIX_LABEL);
    const created = await gh(`/repos/${REPO}/issues`, {
      method: "POST",
      body: JSON.stringify({ title: title(r), body: renderBody(state, r), labels }),
    });
    return { action: "created", issue: created.number, labels };
  }

  const old = readState(issue.body) || newState(r, now);
  const wasFixedIn = maxVersion(old.versions);
  const { state, isNewInstall, isNewVersion } = applyReport(old, r, now);
  const labels = (issue.labels || []).map((l) => (typeof l === "string" ? l : l.name));
  const patch = { body: renderBody(state, r) };
  const notes = [];

  if (issue.state === "closed") {
    // Kapatildiktan sonra cikan bir surumde tekrar ediyorsa duzeltme tutmamis
    if (versionGt(r.app_version, wasFixedIn)) {
      patch.state = "open";
      notes.push(
        `Kapatildiktan sonra **v${r.app_version}** surumunde tekrar goruldu (onceki en yeni surum: v${wasFixedIn}). Yeniden acildi.`
      );
    } else {
      // Kullanici eski surumde; issue kapali kalir, sadece sayac guncellenir
      await gh(`/repos/${REPO}/issues/${issue.number}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      return { action: "counted-closed", issue: issue.number };
    }
  }

  if (!labels.includes(AUTO_FIX_LABEL) && needsAutoFix(state, r)) {
    labels.push(AUTO_FIX_LABEL);
    patch.labels = labels;
    notes.push(
      `${state.installs_total} farkli kurulumda goruldu, otomatik duzeltme icin \`${AUTO_FIX_LABEL}\` etiketi eklendi.`
    );
  } else if (isNewInstall) {
    notes.push(`Yeni bir kurulumda daha goruldu (toplam ${state.installs_total}).`);
  }
  if (isNewVersion && issue.state !== "closed") {
    notes.push(`Yeni surumde de var: v${r.app_version} (yt-dlp ${r.ytdlp_version || "?"}).`);
  }

  await gh(`/repos/${REPO}/issues/${issue.number}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
  // Her rapor icin yorum yazmak bildirim yagmuru demek; sadece anlamli
  // degisikliklerde (yeni kurulum, yeni surum, yeniden acilma, auto-fix).
  if (notes.length) {
    await gh(`/repos/${REPO}/issues/${issue.number}/comments`, {
      method: "POST",
      body: JSON.stringify({ body: notes.join("\n\n") }),
    });
  }
  return { action: patch.state === "open" ? "reopened" : "updated", issue: issue.number, labels };
}

// ---------------------------------------------------------------------------
// HTTP
// ---------------------------------------------------------------------------

function limited(ip) {
  const now = Date.now();
  const list = (rate.get(ip) || []).filter((t) => now - t < 60000);
  list.push(now);
  rate.set(ip, list);
  if (rate.size > 5000) rate.clear();
  return list.length > RATE_PER_MIN;
}

async function handler(req, res) {
  if (req.method === "GET") return res.status(200).json({ ok: true });
  if (req.method !== "POST") return res.status(405).json({ error: "method" });
  if (!process.env.GITHUB_TOKEN) return res.status(503).json({ error: "not configured" });

  const ua = String(req.headers["user-agent"] || "");
  if (!ua.startsWith("VideoDownloader/")) return res.status(403).json({ error: "client" });

  const ip = String(req.headers["x-forwarded-for"] || "").split(",")[0].trim() || "?";
  if (limited(ip)) return res.status(429).json({ error: "rate" });

  let p = req.body;
  try {
    if (typeof p === "string" || Buffer.isBuffer(p)) {
      if (p.length > MAX_BODY_BYTES) return res.status(413).json({ error: "size" });
      p = JSON.parse(p.toString());
    } else if (JSON.stringify(p || {}).length > MAX_BODY_BYTES) {
      return res.status(413).json({ error: "size" });
    }
  } catch {
    return res.status(400).json({ error: "json" });
  }

  const bad = validate(p);
  if (bad) return res.status(400).json({ error: `invalid ${bad}` });

  try {
    const result = await handleReport(normalize(p));
    return res.status(202).json(result);
  } catch (e) {
    console.error(e);
    return res.status(502).json({ error: "github" });
  }
}

module.exports = handler;
module.exports._internal = {
  validate, normalize, clean, applyReport, newState, needsAutoFix, renderBody,
  readState, versionGt, maxVersion, title, handleReport,
};
