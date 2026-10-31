"""
Kullanicilarin aldigi hatalari toplayip GitHub issue'suna ceviren istemci.

Akis:
    uygulama --(anonim rapor, HTTPS POST)--> rapor rolesi (report-relay/)
            --(GitHub API, gizli token)--> hayatexe/video-downloader issue

Token uygulamanin icine KONMAZ. Exe'den token cikarmak bes dakikalik is;
icine gomulseydi herkes depoya istedigi kadar issue acabilirdi. Token
yalnizca rolede durur, uygulama sadece roleyi bilir.

Gonderilen veri bilerek dar tutuldu:
    * hata mesaji (URL'ler, video ID'leri, kullanici klasoru temizlenmis)
    * hangi deneme yollarinin denendigi (cerezsiz, cerez-dosyasi, ssl...)
    * sitenin alan adi (youtube.com gibi), linkin kendisi DEGIL
    * uygulama / yt-dlp / Python / Windows surumu
    * rastgele bir kurulum kimligi (ayni kisinin raporlarini saymak icin;
      kimseyle eslestirilemez, bilgisayardan turetilmez)

Ayarlar -> "Hata raporlarini gonder" ile kapatilabilir.
"""

import hashlib
import json
import os
import platform
import re
import sys
import threading
import time
import urllib.request
import uuid

import updater

# Rolenin adresi. Bos ise raporlama tamamen kapalidir (kaynaktan calistiran
# gelistirici ya da role henuz kurulmamis). Release workflow'u bu satiri
# deponun REPORT_URL degiskeniyle (Settings -> Variables) doldurur; ortam
# degiskeni yerel test icin.
DEFAULT_REPORT_URL = ""
REPORT_URL = os.environ.get("VD_REPORT_URL", DEFAULT_REPORT_URL)

# Ayni hata ayni bilgisayardan gunde bir kezden fazla gonderilmez. Biri ayni
# linki 20 kez denediginde 20 rapor degil, 1 rapor gider.
DEDUPE_SECONDS = 24 * 3600
SEND_TIMEOUT = 8
MAX_MESSAGE = 1500

_lock = threading.Lock()


# --------------------------------------------------------------------------
# Ayarlar (update_state.json icinde, guncelleme ayarlariyla ayni yerde)
# --------------------------------------------------------------------------

def is_enabled():
    return bool(updater._read_state().get("error_reports", True))


def set_enabled(enabled):
    state = updater._read_state()
    state["error_reports"] = bool(enabled)
    updater._write_state(state)
    return bool(enabled)


def is_configured():
    return bool(REPORT_URL)


def _install_id():
    """Rastgele, kalici kurulum kimligi. Donanimdan/isimden turetilmez."""
    state = updater._read_state()
    iid = state.get("install_id")
    if not iid:
        iid = uuid.uuid4().hex
        state["install_id"] = iid
        updater._write_state(state)
    return iid


# --------------------------------------------------------------------------
# Temizleme ve parmak izi
# --------------------------------------------------------------------------

_URL_RE = re.compile(r"https?://[^\s'\"<>)\]]+", re.I)
# C:\Users\Ahmet\...  /home/ahmet/...  -> kullanici adi gitsin
_WIN_USER_RE = re.compile(r"([A-Za-z]:\\+Users\\+)[^\\/\s]+", re.I)
_NIX_USER_RE = re.compile(r"(/(?:home|Users)/)[^/\s]+")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# YouTube ID (11), TikTok/Instagram sayisal ID, UUID gorev adlari
_UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_YTID_RE = re.compile(r"(?<![\w-])[A-Za-z0-9_-]{11}(?![\w-])")
_LONGNUM_RE = re.compile(r"\b\d{6,}\b")


def sanitize(text):
    """Rapora girecek metinden kisisel/izlenebilir parcalari ayikla."""
    s = " ".join(str(text or "").split())
    s = _URL_RE.sub(lambda m: "<url:%s>" % _domain_of(m.group(0)), s)
    s = _WIN_USER_RE.sub(r"\1<user>", s)
    s = _NIX_USER_RE.sub(r"\1<user>", s)
    s = _EMAIL_RE.sub("<email>", s)
    s = _UUID_RE.sub("<id>", s)
    s = _LONGNUM_RE.sub("<n>", s)
    # yt-dlp mesajlari "[youtube] dQw4w9WgXcQ: Sign in..." seklinde ID tasir
    s = re.sub(r"(\[[\w:]+\]\s+)[\w-]{6,}(?=:)", r"\1<id>", s)
    return s[:MAX_MESSAGE]


def fingerprint(message):
    """Ayni hatanin farkli kullanicilardaki halleri ayni parmak izini almali.

    Sayilar, ID'ler ve yt-dlp'nin "ERROR:" oneki atilir; boylece
    "Giving up after 10 retries" ile "after 3 retries" ya da farkli videolar
    ayni issue'ya duser.
    """
    s = sanitize(message).lower()
    s = re.sub(r"^error:\s*", "", s)
    s = _YTID_RE.sub("<id>", s)
    s = re.sub(r"\d+(\.\d+)*", "#", s)
    s = re.sub(r"<url:[^>]*>", "<url>", s)
    s = re.sub(r"\s+", " ", s).strip()
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]


def _domain_of(url):
    m = re.match(r"https?://(?:www\.|m\.)?([^/:?#]+)", url or "", re.I)
    return m.group(1).lower() if m else ""


# --------------------------------------------------------------------------
# Hangi hata raporlanmaya deger?
# --------------------------------------------------------------------------

# Kullanicinin elinde olan / uygulamanin duzeltemeyecegi durumlar. Bunlar
# issue acarsa depo gurultuyle dolar ve gercek hatalar kaybolur.
_IGNORE = (
    "private video", "this video is private", "video unavailable",
    "video is unavailable", "has been removed", "no longer available",
    "this video has been deleted", "unsupported url", "members-only",
    "members only", "join this channel", "requires payment", "purchase this",
    "rental", "buy or rent", "http error 404", "http error 410",
    "not available in your country", "geo restricted", "geo-restricted",
    "ip address is blocked", "blocked from accessing",
    "getaddrinfo failed", "temporary failure in name resolution",
    "network is unreachable", "no route to host",
    "premieres in", "live event will begin", "this live event",
    "winerror 112",  # disk dolu
    "no space left",
)


def should_report(message, kind="download"):
    if not (REPORT_URL and is_enabled()):
        return False
    low = str(message or "").lower()
    if not low.strip():
        return False
    return not any(k in low for k in _IGNORE)


# --------------------------------------------------------------------------
# Gonderim
# --------------------------------------------------------------------------

def _sent_recently(fp):
    state = updater._read_state()
    sent = state.get("error_reports_sent", {})
    now = time.time()
    # Eski kayitlari temizle ki dosya buyumesin
    sent = {k: v for k, v in sent.items() if now - v < DEDUPE_SECONDS}
    recent = fp in sent
    if not recent:
        sent[fp] = now
    state["error_reports_sent"] = sent
    updater._write_state(state)
    return recent


def _ytdlp_version():
    try:
        return updater.installed_ytdlp_version()
    except Exception:
        return None


def build_payload(message, url="", kind="download", attempts=None,
                  user_message="", extra=None):
    raw = str(message or "")
    return {
        "schema": 1,
        "fingerprint": fingerprint(raw),
        "kind": kind,
        "message": sanitize(raw),
        "user_message": sanitize(user_message)[:300],
        "site": _domain_of(url),
        "attempts": [
            {"label": str(a.get("label", ""))[:40],
             "error": sanitize(a.get("error", ""))[:400]}
            for a in (attempts or [])[-8:]
        ],
        "app_version": updater.APP_VERSION,
        "ytdlp_version": _ytdlp_version(),
        "python": platform.python_version(),
        "os": "%s %s" % (platform.system(), platform.release()),
        "os_build": platform.version()[:40],
        "frozen": bool(getattr(sys, "frozen", False)),
        "install_id": hashlib.sha256(_install_id().encode()).hexdigest()[:16],
        "extra": {str(k)[:40]: sanitize(v)[:200] for k, v in (extra or {}).items()},
    }


def _post(payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        REPORT_URL, data=data, method="POST",
        headers={"Content-Type": "application/json",
                 "User-Agent": updater.USER_AGENT})
    with urllib.request.urlopen(req, timeout=SEND_TIMEOUT) as r:
        return r.status


def report(message, url="", kind="download", attempts=None, user_message="",
           extra=None):
    """Hatayi arka planda gonder. Asla istisna firlatmaz, asla bekletmez."""
    try:
        if not should_report(message, kind):
            return False
        payload = build_payload(message, url, kind, attempts, user_message, extra)
        with _lock:
            if _sent_recently(payload["fingerprint"]):
                return False
    except Exception:
        return False

    def worker():
        try:
            _post(payload)
        except Exception:
            # Cevrimdisi, role kapali vs. Rapor kaybolur; uygulama etkilenmez.
            pass

    threading.Thread(target=worker, daemon=True).start()
    return True
