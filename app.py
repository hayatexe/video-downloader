"""
Video Downloader - Backend Server
Supports YouTube, Instagram, TikTok and 1000+ platforms via yt-dlp
"""

import os
import re
import sys
import uuid
import json
import threading
import time
from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS

# yt-dlp exe'nin icine gomulmez; guncellenebilir olsun diye yazilabilir bir
# klasorden yuklenir. Bu satir `import yt_dlp`den ONCE gelmek zorunda.
import updater
updater.activate()
import yt_dlp

# PyInstaller frozen-mode: static files are in sys._MEIPASS
if getattr(sys, 'frozen', False):
    _BASE_DIR = sys._MEIPASS          # bundled files
    _APP_DIR  = os.path.dirname(sys.executable)  # next to .exe
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    _APP_DIR  = _BASE_DIR

app = Flask(__name__, static_folder=os.path.join(_BASE_DIR, "static"))
CORS(app)

# Downloads go next to the .exe (or project root in dev mode)
DOWNLOAD_DIR = os.path.join(_APP_DIR, "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


_FFMPEG_CACHE = "unset"  # cached result of _find_ffmpeg (None = not found)


def _find_ffmpeg():
    """Find ffmpeg binary, checking common install locations on Windows."""
    global _FFMPEG_CACHE
    if _FFMPEG_CACHE != "unset":
        return _FFMPEG_CACHE

    import shutil
    import glob

    _FFMPEG_CACHE = _find_ffmpeg_uncached(shutil, glob)
    return _FFMPEG_CACHE


def _find_ffmpeg_uncached(shutil, glob):
    # 0. Kurulumla gelen ffmpeg. Once exe'nin yanindaki {app}\ffmpeg (installer
    #    oraya koyar), sonra _internal\ffmpeg (dev modu / eski paketler).
    #    Harici kurulum gerektirmeden calissin diye once buraya bakilir.
    for bundled in (os.path.join(_APP_DIR, "ffmpeg"), os.path.join(_BASE_DIR, "ffmpeg")):
        if os.path.isfile(os.path.join(bundled, "ffmpeg.exe")):
            return bundled

    # 1. Check current PATH
    path = shutil.which("ffmpeg")
    if path:
        return os.path.dirname(path)

    # 2. Check winget install location
    winget_pattern = os.path.join(
        os.path.expanduser("~"),
        "AppData", "Local", "Microsoft", "WinGet", "Packages",
        "Gyan.FFmpeg*", "ffmpeg-*", "bin", "ffmpeg.exe"
    )
    matches = glob.glob(winget_pattern)
    if matches:
        return os.path.dirname(matches[0])

    # 3. Check common locations
    common_paths = [
        r"C:\ffmpeg\bin",
        r"C:\ProgramData\chocolatey\bin",
        os.path.join(os.path.expanduser("~"), "scoop", "shims"),
    ]
    for p in common_paths:
        if os.path.isfile(os.path.join(p, "ffmpeg.exe")):
            return p

    return None

# Store download progress info
download_progress = {}

# Lock for thread-safe progress updates
progress_lock = threading.Lock()


def _cleanup_stale_downloads(max_age_hours=24):
    """Delete leftover temp files in the downloads dir (runs in background)."""
    try:
        cutoff = time.time() - max_age_hours * 3600
        for f in os.listdir(DOWNLOAD_DIR):
            path = os.path.join(DOWNLOAD_DIR, f)
            try:
                if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                    os.remove(path)
            except OSError:
                pass
    except OSError:
        pass


threading.Thread(target=_cleanup_stale_downloads, daemon=True).start()


# ===== Tarayici cerezleri (Instagram vb. giris isteyen platformlar icin) =====
# Son basarili olan tarayici hatirlanir, sonraki isteklerde once o denenir.
_working_cookie_browser = None

# Uygulama ici giris penceresinden alinan cerezler burada saklanir (Netscape format)
COOKIE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", _APP_DIR), "VideoDownloader")
COOKIE_FILE = os.path.join(COOKIE_DIR, "cookies.txt")


def save_webview_cookies(cookie_list):
    """Merge cookies captured from the in-app login window into COOKIE_FILE."""
    from http.cookiejar import MozillaCookieJar, Cookie

    os.makedirs(COOKIE_DIR, exist_ok=True)
    jar = MozillaCookieJar(COOKIE_FILE)
    if os.path.exists(COOKIE_FILE):
        try:
            jar.load(ignore_discard=True, ignore_expires=True)
        except Exception:
            pass

    far_future = int(time.time()) + 180 * 24 * 3600
    count = 0
    for sc in cookie_list:
        for name, morsel in sc.items():
            domain = morsel["domain"] or ""
            if not domain:
                continue
            jar.set_cookie(Cookie(
                version=0, name=name, value=morsel.value,
                port=None, port_specified=False,
                domain=domain, domain_specified=True,
                domain_initial_dot=domain.startswith("."),
                path=morsel["path"] or "/", path_specified=True,
                secure=bool(morsel["secure"]), expires=far_future,
                discard=False, comment=None, comment_url=None, rest={},
            ))
            count += 1

    if count:
        jar.save(ignore_discard=True, ignore_expires=True)
    return count


def _browser_spec(name):
    """Map a UI browser id to a (yt-dlp browser, profile path) tuple."""
    appdata = os.environ.get("APPDATA", "")
    localapp = os.environ.get("LOCALAPPDATA", "")
    specs = {
        "operagx": ("opera", os.path.join(appdata, "Opera Software", "Opera GX Stable")),
        "opera": ("opera", None),
        "chrome": ("chrome", None),
        "edge": ("edge", None),
        "firefox": ("firefox", None),
        "brave": ("brave", None),
        "vivaldi": ("vivaldi", None),
    }
    spec = specs.get(name)
    if spec and spec[1] and not os.path.isdir(spec[1]):
        return None
    return spec


def _cookie_browser_candidates():
    """Browsers installed on this machine, most likely first."""
    appdata = os.environ.get("APPDATA", "")
    localapp = os.environ.get("LOCALAPPDATA", "")
    checks = [
        ("operagx", os.path.join(appdata, "Opera Software", "Opera GX Stable")),
        ("chrome", os.path.join(localapp, "Google", "Chrome", "User Data")),
        ("edge", os.path.join(localapp, "Microsoft", "Edge", "User Data")),
        ("firefox", os.path.join(appdata, "Mozilla", "Firefox", "Profiles")),
        ("opera", os.path.join(appdata, "Opera Software", "Opera Stable")),
        ("brave", os.path.join(localapp, "BraveSoftware", "Brave-Browser", "User Data")),
        ("vivaldi", os.path.join(localapp, "Vivaldi", "User Data")),
    ]
    return [name for name, path in checks if os.path.isdir(path)]


_impersonate_support = None


def has_impersonate_support():
    """curl_cffi kurulu mu? TikTok/Instagram web cikarimi bu olmadan
    TLS parmak izi kontrolune takilir ve 'Unexpected response' doner."""
    global _impersonate_support
    if _impersonate_support is None:
        try:
            import curl_cffi  # noqa: F401
            from yt_dlp.networking.impersonate import ImpersonateTarget  # noqa: F401
            _impersonate_support = True
        except Exception:
            _impersonate_support = False
    return _impersonate_support


# Giris penceresinde acilacak sayfalar. Daha once her platformda Instagram
# giris sayfasi aciliyordu; TikTok linkinde Instagram'a giris yapmak
# ise yaramiyordu.
# (desen, ad, giris sayfasi, ipucu)
#
# Giris sayfasi TAM sayfa olmali: QR kod, e-posta/telefon ve sosyal giris
# secenekleri bir arada. Hesabi Google'a bagli olan biri icin e-posta formu
# ise yaramaz; QR kod (telefondaki uygulamayla okut) her hesap turunde
# calisir ve pencereden hic cikmaz.
LOGIN_PLATFORMS = [
    (r'(?://|\.)instagram\.com', "Instagram",
     "https://www.instagram.com/accounts/login/", ""),
    (r'(?://|\.)tiktok\.com', "TikTok", "https://www.tiktok.com/login",
     "Google/Facebook/Apple ile giriş pencerenin içinde açılır. Sorun çıkarsa "
     "QR kodu kullanın: telefonunuzdaki TikTok uygulamasıyla okutun."),
    # continue= sart: pywebview sadece O AN acik sayfanin cerezlerini
    # okuyabiliyor. Giris Google hesap sayfasinda biterse yalnizca
    # google.com cerezleri toplanir; yt-dlp'nin istedigi youtube.com
    # cerezleri hic gelmez. YouTube'un kendi "Oturum ac" butonunun
    # kullandigi adres bu, giris bitince youtube.com'a doner.
    (r'(?://|\.)(?:youtube\.com|youtu\.be)', "YouTube",
     "https://accounts.google.com/ServiceLogin?service=youtube&passive=true"
     "&continue=https%3A%2F%2Fwww.youtube.com%2Fsignin%3Faction_handle_signin"
     "%3Dtrue%26app%3Ddesktop%26next%3D%252F",
     "Giriş tamamlanınca pencere kendiliğinden kapanır. Google girişi "
     "engellenirse tarayıcınızda YouTube'a girip \"tekrar dene\" deyin."),
    (r'(?://|\.)(?:twitter\.com|x\.com)', "X (Twitter)",
     "https://x.com/i/flow/login", ""),
    (r'(?://|\.)facebook\.com', "Facebook",
     "https://www.facebook.com/login/", ""),
    (r'(?://|\.)reddit\.com', "Reddit", "https://www.reddit.com/login/", ""),
    (r'(?://|\.)twitch\.tv', "Twitch", "https://www.twitch.tv/login", ""),
]


# Giris basarili sayilmasi icin cerezlerin GELMESI gereken alan adi. Giris
# sayfasi baska bir alan adinda olabilir (YouTube -> accounts.google.com);
# o alan adinin cerezleri yt-dlp'ye yaramaz.
LOGIN_COOKIE_DOMAINS = {
    "Instagram": "instagram.com",
    "TikTok": "tiktok.com",
    "YouTube": "youtube.com",
    "X (Twitter)": "x.com",
    "Facebook": "facebook.com",
    "Reddit": "reddit.com",
    "Twitch": "twitch.tv",
}


def detect_login_platform(url):
    """URL'ye gore giris yapilacak platformu, giris sayfasini ve ipucunu dondur."""
    for pattern, label, login_url, hint in LOGIN_PLATFORMS:
        if re.search(pattern, url or "", re.IGNORECASE):
            return {"platform": label, "login_url": login_url, "hint": hint,
                    "cookie_domain": LOGIN_COOKIE_DOMAINS.get(label, "")}
    host = ""
    m = re.match(r'https?://([^/]+)', url or "", re.IGNORECASE)
    if m:
        host = m.group(1)
    if host:
        bare = host.lower().split(":")[0]
        if bare.startswith("www."):
            bare = bare[4:]
        return {"platform": bare, "login_url": f"https://{host}/", "hint": "",
                "cookie_domain": bare}
    return {"platform": "Platform", "login_url": "", "hint": "", "cookie_domain": ""}


def _login_payload(info):
    """Arayuzun giris uyarisini gostermesi icin gereken alanlar."""
    return {"needs_login": True, "login_platform": info["platform"],
            "login_url": info["login_url"], "login_hint": info["hint"],
            "login_domain": info["cookie_domain"]}


# Bir oturumun GERCEKTEN acik oldugunu gosteren cerezler. Her grup icin en az
# bir isim bulunmali. Sadece "o siteden cerez geldi mi" diye bakmak yetmez:
# YouTube giris yapilmamis ziyaretcilere de YSC / VISITOR_INFO1_LIVE verir,
# boylece giris bitmeden "giris kaydedildi" deniyordu.
#
# YouTube olcutu yt-dlp'nin kendi kontroluyle (_has_auth_cookies) birebir
# ayni: LOGIN_INFO + SAPISID ailesinden biri. Ayni olcutu kullanmazsak bizim
# "giris tamam" dedigimiz cerezlerle yt-dlp hala anonim davranabilir.
AUTH_COOKIES = {
    "youtube.com": (("LOGIN_INFO",),
                    ("SAPISID", "__Secure-1PAPISID", "__Secure-3PAPISID")),
    "tiktok.com": (("sessionid", "sessionid_ss", "sid_tt"),),
    "instagram.com": (("sessionid",),),
    "x.com": (("auth_token",),),
    "facebook.com": (("c_user",),),
    "reddit.com": (("reddit_session",),),
    "twitch.tv": (("auth-token",),),
}


def _domain_matches(cookie_domain, domain):
    d = (cookie_domain or "").lower().lstrip(".")
    return d == domain or d.endswith("." + domain)


def _has_auth(names, domain):
    groups = AUTH_COOKIES.get(domain)
    if not groups:
        # Bilinmeyen site: oturum cerezinin adini bilmiyoruz, gelen her
        # cerezi giris sayariz (eski davranis).
        return bool(names)
    return all(any(n in names for n in group) for group in groups)


def count_cookies_for_domain(cookie_list, domain):
    """pywebview'in dondurdugu cerezlerden kaci verilen alan adina ait?"""
    if not domain:
        return sum(len(sc) for sc in cookie_list)
    domain = domain.lower().lstrip(".")
    n = 0
    for sc in cookie_list:
        for _name, morsel in sc.items():
            if _domain_matches(morsel["domain"], domain):
                n += 1
    return n


def auth_cookie_status(cookie_list, domain):
    """Giris penceresindeki cerezlere gore oturum acildi mi?

    Dondurur: (oturum_acik_mi, o_alan_adindaki_cerez_sayisi).
    """
    if not domain:
        n = sum(len(sc) for sc in cookie_list)
        return n > 0, n
    domain = domain.lower().lstrip(".")
    names = set()
    for sc in cookie_list:
        for name, morsel in sc.items():
            if _domain_matches(morsel["domain"], domain):
                names.add(name)
    return _has_auth(names, domain), len(names)


def cookie_file_has_auth(domain):
    """Kayitli cerez dosyasinda bu site icin acik bir oturum var mi?"""
    from http.cookiejar import MozillaCookieJar
    if not os.path.isfile(COOKIE_FILE):
        return False
    jar = MozillaCookieJar(COOKIE_FILE)
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except Exception:
        return False
    names = {c.name for c in jar if _domain_matches(c.domain, domain)}
    return _has_auth(names, domain)


class _SessionLogger:
    """Cerez dosyasiyla yapilan denemede yt-dlp'nin oturumla ilgili
    mesajlarini yakalar.

    Yas engelinde iki durum ayni hatayi uretir ("Sign in to confirm your
    age"): oturum gecersiz (YouTube cerezleri reddetti) ya da oturum acik ama
    hesap videoyu izleyemiyor. Ayirt etmenin tek yolu yt-dlp'nin bu
    uyarilari. Sadece ilgili satirlari tutar; indirme ilerleme satirlari
    birikmesin.
    """

    KEYS = ("no longer valid", "found youtube account cookies",
            "age-verification", "age verification")

    def __init__(self):
        self.lines = []

    def _keep(self, msg):
        m = str(msg)
        if any(k in m.lower() for k in self.KEYS):
            self.lines.append(m)

    debug = info = warning = error = _keep

    def saw(self, key):
        return any(key in line.lower() for line in self.lines)


class UserFacingError(yt_dlp.utils.DownloadError):
    """Mesaji zaten kullaniciya gosterilecek halde olan hata.

    friendly_error bunu cevirmeye calismaz ve giris dongusu baslatmaz.
    """


class SessionExpiredError(UserFacingError):
    """Uygulama ici giristen gelen oturum YouTube tarafindan reddedildi.

    Tekrar giris yapmak cozer; arayuz giris butonunu gosterir.
    """


SESSION_EXPIRED_MESSAGE = (
    "YouTube kayıtlı oturumu geçersiz saydı (güvenlik için yenilemiş olabilir). "
    "Tekrar giriş yapın."
)

AGE_BLOCKED_MESSAGE = (
    "Giriş yapıldı ama YouTube bu videoyu bu hesaba göstermiyor. Hesap 18 "
    "yaşından küçükse ya da YouTube hesaptan yaş doğrulaması istiyorsa bu "
    "olur. Videoyu aynı hesapla tarayıcınızda açmayı deneyin: orada da "
    "açılmıyorsa engel YouTube tarafında, uygulamanın aşabileceği bir şey değil."
)


def _is_age_error(msg):
    m = str(msg).lower()
    return any(k in m for k in ("confirm your age", "age-restricted",
                                "age restricted", "age verification",
                                "age-verification", "inappropriate for some users"))


def _is_youtube_url(url):
    return re.search(r'(?://|\.)(?:youtube\.com|youtu\.be)/', url or "",
                     re.IGNORECASE) is not None


# Her denemenin hatasi buraya yazilir. Kullanici "olmuyor" dediginde neyin
# olmadigini tahmin etmek yerine bu dosyaya bakilir.
DOWNLOAD_LOG = os.path.join(updater.user_data_dir(), "download.log")


def _log_attempt(url, label, err):
    try:
        os.makedirs(os.path.dirname(DOWNLOAD_LOG), exist_ok=True)
        if os.path.isfile(DOWNLOAD_LOG) and os.path.getsize(DOWNLOAD_LOG) > 512 * 1024:
            os.replace(DOWNLOAD_LOG, DOWNLOAD_LOG + ".1")
        with open(DOWNLOAD_LOG, "a", encoding="utf-8") as f:
            f.write("%s  %s  [%s]  %s\n" % (
                time.strftime("%Y-%m-%d %H:%M:%S"), url, label,
                " ".join(str(err).split())[:600]))
    except Exception:
        pass


def _is_login_error(msg):
    m = str(msg).lower()
    return any(k in m for k in (
        "--cookies", "login required", "sign in to confirm",
        "empty media response", "rate-limit reached", "requested content is not available",
    ))


# TikTok'un web sayfasi zaman zaman beklenen JSON yerine dogrulama/blok sayfasi
# dondurur ("Unexpected response from webpage request"). Bu durumda cikarimi
# TikTok'un mobil API sunucularindan biri uzerinden yapmak sorunu cozer.
TIKTOK_API_HOSTS = [
    "api16-normal-c-useast1a.tiktokv.com",
    "api31-normal-c-useast2a.tiktokv.com",
    "api22-normal-c-useast2a.tiktokv.com",
    "api19-normal-c-useast1a.tiktokv.com",
]
_working_tiktok_host = None


def _is_tiktok_url(url):
    return re.search(r'(?://|\.)tiktok\.com/', url or "", re.IGNORECASE) is not None


def _is_extractor_response_error(msg):
    """TikTok'un web sayfasindan gecerli veri alinamadigini gosteren hata."""
    m = str(msg).lower()
    return any(k in m for k in (
        "unexpected response from webpage request",
        "unable to extract webpage video data",
        "unable to extract video data",
    ))


def _is_ip_block_error(msg):
    """Giris ile cozulmeyen IP/bolge engeli."""
    m = str(msg).lower()
    return any(k in m for k in (
        "ip address is blocked", "blocked from accessing",
        "not available in your country", "geo restricted", "geo-restricted",
    ))


# Gecici hatalar icin yeniden deneme. Olcum: ayni video 6 denemede 6 kez
# indi, ama baska bir denemede 403 verdi -- yani hata araliksal, kalici degil.
# Kullanicinin "bazen oluyor" demesinin sebebi bu.
TRANSIENT_RETRIES = 2
TRANSIENT_BACKOFF = 1.5  # saniye, her denemede artar


def _is_transient_error(msg):
    """Yeniden denemenin ise yarayabilecegi, gecici gorunen hatalar.

    403 burada: YouTube'un verdigi imzali indirme URL'i gecersizleserek
    "HTTP Error 403" uretiyor. Yeniden cikarim taze bir URL (ve bazen baska
    bir player client) getirdigi icin ikinci deneme genelde tutuyor.
    """
    m = str(msg).lower()
    return any(k in m for k in (
        "http error 403", "http error 429", "http error 5",
        "unable to download video data", "read timed out",
        "connection reset", "connection aborted", "temporary failure",
        "incomplete read", "the read operation timed out",
    ))


def _is_stale_ytdlp_error(msg):
    """Genellikle 'yt-dlp eskimis' anlamina gelen hatalar.

    Bu oturumda ikisini de yasadik: YouTube PO Token degisikligi 403 veriyordu,
    TikTok ise web sayfasi cikarimini bozmustu.
    """
    m = str(msg).lower()
    return any(k in m for k in (
        "http error 403", "unable to download video data",
        "unexpected response", "nsig extraction failed",
        "player response", "requested format is not available",
    ))


def _tiktok_host_attempts():
    """Once daha once calistigi bilinen sunucuyu dene."""
    hosts = list(TIKTOK_API_HOSTS)
    if _working_tiktok_host in hosts:
        hosts.remove(_working_tiktok_host)
        hosts.insert(0, _working_tiktok_host)
    return [{"extractor_args": {"tiktok": {"api_hostname": [h]}}} for h in hosts]


def extract_with_cookie_fallback(url, base_opts, browser_pref="auto", download=False):
    """Try without cookies first; on login-type errors retry with the in-app
    cookie file, then with browser cookies. Returns (info, opts_used)."""
    global _working_cookie_browser, _working_tiktok_host

    attempts = [(None, {})]
    # TikTok'ta web sayfasi cikarimi sik sik bloke oluyor; cerezlerden once
    # mobil API sunucularini dene.
    tiktok_attempts = _tiktok_host_attempts() if _is_tiktok_url(url) else []
    attempts += [(None, extra) for extra in tiktok_attempts]
    if browser_pref != "off":
        # 1. Uygulama ici giris penceresinden kaydedilen cerezler (en guvenilir)
        if os.path.isfile(COOKIE_FILE):
            attempts.append((None, {"cookiefile": COOKIE_FILE}))
        # 2. Kurulu tarayicilardan cerez cekme
        if browser_pref and browser_pref != "auto":
            names = [browser_pref]
        else:
            names = _cookie_browser_candidates()
            if _working_cookie_browser in names:
                names.remove(_working_cookie_browser)
                names.insert(0, _working_cookie_browser)
            names = names[:4]
        for n in names:
            spec = _browser_spec(n)
            if spec:
                attempts.append((n, {"cookiesfrombrowser": (spec[0], spec[1], None, None)}))

    login_err = None
    last_err = None
    cookiefile_err = None
    # Oturum durumu denemeden ONCE okunmali: yt-dlp is bitince cerez
    # dosyasini geri yazar, reddedilen LOGIN_INFO o sirada silinir.
    is_yt = _is_youtube_url(url)
    had_yt_auth = is_yt and cookie_file_has_auth("youtube.com")
    session_log = None
    for name, extra in attempts:
        opts = dict(base_opts)
        opts.update(extra)
        if "cookiefile" in extra and is_yt:
            session_log = _SessionLogger()
            opts.update({"logger": session_log, "quiet": False, "no_warnings": False})

        # Her deneme, gecici hatalar icin kendi icinde birkac kez tekrarlanir.
        # Bunun ydl_opts["retries"] ile ayni sey OLMADIGINA dikkat: oradaki
        # yeniden deneme ayni URL'i tekrar ister. 403 ise URL'in gecerliligini
        # yitirmesinden gelir, ayni URL hep 403 verir -- cozum yeniden
        # CIKARIM yapmak, yani extract_info'yu bastan cagirmak.
        err = None
        for deneme in range(TRANSIENT_RETRIES + 1):
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=download)
                if name:
                    _working_cookie_browser = name
                host = (extra.get("extractor_args", {})
                        .get("tiktok", {}).get("api_hostname"))
                if host:
                    _working_tiktok_host = host[0]
                return info, opts
            except Exception as e:
                err = e
                if deneme < TRANSIENT_RETRIES and _is_transient_error(e):
                    time.sleep(TRANSIENT_BACKOFF * (deneme + 1))
                    continue
                break

        e = err
        last_err = e
        if name:
            label = "tarayici:" + name
        elif "cookiefile" in extra:
            label = "cerez-dosyasi"
            cookiefile_err = e
        elif "extractor_args" in extra:
            label = "tiktok-api"
        else:
            label = "cerezsiz"
        _log_attempt(url, label, e)
        if _is_login_error(e) and login_err is None:
            login_err = e
        # Cerezsiz ilk deneme "giris gerekli" ya da "sayfa okunamadi"
        # DISINDA bir hata verdiyse yeniden denemenin anlami yok.
        if not extra and not _is_login_error(e) and not (
            tiktok_attempts and _is_extractor_response_error(e)
        ):
            raise
        continue

    # Her yol tukendi. Hata yt-dlp'nin eskimesine isaret ediyorsa bir sonraki
    # aciliSta zorla guncelleme kontrolu yapilmasi icin isaretle.
    if _is_stale_ytdlp_error(last_err):
        try:
            updater.flag_ytdlp_stale()
            _refresh_ytdlp_async()
        except Exception:
            pass

    # curl_cffi yoksa TikTok/Instagram web cikarimi TLS parmak izi kontrolune
    # takilir. Bu "giris gerekli" degildir; giris penceresi acmak cozmez.
    if _is_extractor_response_error(last_err) and not has_impersonate_support():
        raise yt_dlp.utils.DownloadError(
            "Bu platform için gereken tarayıcı taklidi (impersonation) desteği "
            "eksik. Uygulamanın yeni sürümünü kurun; kaynaktan çalıştırıyorsanız "
            "'pip install curl_cffi' komutunu çalıştırın."
        )

    # Uygulama ici giristen gelen cerezlerle denendi ve YouTube yine yas
    # engeli verdiyse: oturum ACIK (yt-dlp'nin olcutuyle) ama hesap bu videoyu
    # izleyemiyor. Kullaniciyi yeniden giris dongusune sokmak bir ise
    # yaramaz; gercek sebebi soyle.
    if cookiefile_err is not None and is_yt and had_yt_auth and session_log is not None:
        _log_attempt(url, "oturum", " | ".join(session_log.lines) or "-")
        if session_log.saw("no longer valid"):
            # Cerezler reddedildi: yeniden giris cozer
            raise SessionExpiredError(SESSION_EXPIRED_MESSAGE)
        if _is_age_error(cookiefile_err):
            # Oturum gecerli ama hesap videoyu izleyemiyor
            raise UserFacingError(AGE_BLOCKED_MESSAGE)

    # Oturum cerezleriyle yapilan deneme "giris gerekli" DISINDA bir hata
    # verdiyse o hata daha bilgilendirici: giris tamam, sorun baska yerde.
    # Eskiden burada her zaman cerezsiz denemenin hatasi gosteriliyordu ve
    # giristen sonra ne oldugu hic gorunmuyordu.
    if cookiefile_err is not None and not _is_login_error(cookiefile_err):
        raise cookiefile_err

    # Cerez cekme hatalari (DPAPI/kilit) yerine asil "giris gerekli" hatasini goster
    raise login_err or last_err


_ytdlp_refreshing = threading.Lock()
_ytdlp_refreshed = False


def _refresh_ytdlp_async():
    """Cikarim hatasi alindiginda yt-dlp'yi hemen arka planda guncelle.

    Eskiden sadece "bir sonraki acilista bak" diye isaretleniyordu; boylece
    kullanici uygulamayi kapatip acana kadar indirme bozuk kaliyordu. Yeni
    surum yine bir sonraki acilista devreye girer (yt_dlp zaten import
    edilmis durumda) ama indirme simdi yapilir.
    """
    global _ytdlp_refreshed
    with _ytdlp_refreshing:
        if _ytdlp_refreshed:
            return
        _ytdlp_refreshed = True

    def worker():
        try:
            changed, message = updater.update_ytdlp(force=True)
            # Penceresiz derlemede sys.stdout None olabilir; print patlamasin
            if sys.stdout is not None:
                print("[guncelleme] yt-dlp (otomatik):", message)
        except Exception:
            pass

    threading.Thread(target=worker, daemon=True).start()


def friendly_error(error_msg, url=""):
    """yt-dlp hatasini anlasilir bir Turkce mesaja cevir.

    Dondurur: (mesaj, ek_alanlar). Ek alanlar giris akisi icin
    needs_login/login_url gibi bilgileri tasiyabilir.
    """
    if isinstance(error_msg, SessionExpiredError):
        return str(error_msg), _login_payload(detect_login_platform(url))
    if isinstance(error_msg, UserFacingError):
        return str(error_msg), {}
    msg = str(error_msg)
    low = msg.lower()

    if "unsupported url" in low:
        return "Bu URL desteklenmiyor.", {}
    if "private video" in low or "this video is private" in low:
        return "Bu video gizli (private).", {}
    if "members-only" in low or "members only" in low or "join this channel" in low:
        return "Bu içerik yalnızca kanal üyelerine açık.", {}
    if any(k in low for k in ("requires payment", "purchase this", "rental",
                              "paid members", "buy or rent")):
        return "Bu içerik ücretli; satın alınmadan indirilemez.", {}
    if "age" in low and ("confirm your age" in low or "age-restricted" in low
                         or "age restricted" in low):
        info = detect_login_platform(url)
        return (f"Yaş sınırlı içerik. {info['platform']} hesabınızla giriş yapmanız gerekiyor.",
                _login_payload(info))
    if _is_ip_block_error(msg):
        return ("Bu içeriğe bulunduğunuz IP/bölgeden erişim engellenmiş. "
                "Giriş yapmak bunu çözmez."), {}
    if "tarayıcı taklidi" in msg:
        # extract_with_cookie_fallback'in kendi mesaji; oldugu gibi gecsin
        return msg, {}
    if _is_login_error(msg):
        info = detect_login_platform(url)
        return (f"Bu içerik {info['platform']} girişi gerektiriyor.",
                _login_payload(info))
    if "video unavailable" in low or "no longer available" in low \
            or "has been removed" in low or "this video has been deleted" in low:
        return "Bu video kaldırılmış ya da mevcut değil.", {}
    if "requested format is not available" in low or "no video formats" in low:
        return ("Seçtiğiniz kalite bu video için yok. Farklı bir kalite deneyin."), {}
    if "ffmpeg" in low and ("not found" in low or "bulunamadi" in low):
        return ("ffmpeg bulunamadı. Ses dönüştürme ve video+ses birleştirme "
                "için gerekli; uygulamayı yeniden kurmak sorunu çözer."), {}
    if any(k in low for k in ("unable to download webpage", "timed out",
                              "connection reset", "temporary failure in name resolution",
                              "getaddrinfo failed", "network is unreachable")):
        return "İnternet bağlantısı kurulamadı. Bağlantınızı kontrol edip tekrar deneyin.", {}
    if "unable to extract" in low or "unexpected response" in low:
        return ("İndirme motoru bu siteyi okuyamadı. yt-dlp güncellemesi arka planda "
                "alınıyor; birazdan tekrar deneyin."), {}

    return f"Hata: {msg[:200]}", {}


def clean_filename(filename):
    """Remove invalid characters from filename."""
    return re.sub(r'[<>:"/\\|?*]', '_', filename).strip(" ._")


def get_display_title(info):
    """Pick a meaningful title. Instagram/TikTok often report 'Video by <user>'
    or just the uploader name — fall back to the first line of the description."""
    title = (info.get("title") or "").strip()
    uploader = (info.get("uploader") or "").strip()

    generic = (
        not title
        or title.lower() in ("video", "instagram video", "na")
        or (uploader and title.lower() == uploader.lower())
        or re.match(r'^video by\b', title, re.IGNORECASE)
    )
    if generic:
        desc = (info.get("description") or "").strip()
        first_line = desc.splitlines()[0].strip() if desc else ""
        if first_line:
            title = first_line[:100]
        elif uploader:
            title = f"{uploader} videosu"
        else:
            title = "video"
    return title


def build_download_name(title, ext):
    """Filename shown to the user: <title>_<YYYY-MM-DD_HH-MM-SS><ext>."""
    safe_title = clean_filename(title)[:120] or "video"
    stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    return f"{safe_title}_{stamp}{ext}"


def get_progress_hook(task_id):
    """Create a progress hook for yt-dlp."""
    def hook(d):
        with progress_lock:
            if d['status'] == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                downloaded = d.get('downloaded_bytes', 0)
                speed = d.get('speed', 0)
                eta = d.get('eta', 0)
                percent = (downloaded / total * 100) if total > 0 else 0
                download_progress[task_id] = {
                    'status': 'downloading',
                    'percent': round(percent, 1),
                    'downloaded': downloaded,
                    'total': total,
                    'speed': speed,
                    'eta': eta
                }
            elif d['status'] == 'finished':
                download_progress[task_id] = {
                    'status': 'processing',
                    'percent': 100,
                    'message': 'İşleniyor...'
                }
    return hook


@app.route("/")
def index():
    return send_file("static/index.html")


@app.route("/favicon.ico")
def favicon():
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
    <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0%" stop-color="#8b5cf6"/><stop offset="100%" stop-color="#6366f1"/>
    </linearGradient></defs>
    <rect width="32" height="32" rx="8" fill="url(#g)"/>
    <path d="M16 6v12m0 0l-5-5m5 5l5-5M8 24h16" stroke="#fff" stroke-width="2.5"
    stroke-linecap="round" stroke-linejoin="round" fill="none"/>
    </svg>'''
    return Response(svg, mimetype="image/svg+xml")


@app.route("/api/info", methods=["POST"])
def get_video_info():
    """Fetch video information and available formats."""
    data = request.json
    url = data.get("url", "").strip()
    cookies_browser = data.get("cookies_browser", "auto")

    if not url:
        return jsonify({"error": "URL gerekli"}), 400

    try:
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "no_check_certificates": True,
            "extract_flat": True,  # Çok daha hızlı playlist çekimi sağlar
            "socket_timeout": 15,  # Ağ takılırsa sonsuza kadar bekleme
        }

        info, _ = extract_with_cookie_fallback(url, ydl_opts, cookies_browser)

        if info is None:
            return jsonify({"error": "Video bilgisi alınamadı"}), 400

        is_playlist = "entries" in info or info.get("_type") == "playlist"
        playlist_items = []

        if is_playlist:
            entries = info.get("entries", [])
            # Eğer generator dönerse listeye çevir ve sonsuz Mix döngüsünü kır
            if not isinstance(entries, list):
                try:
                    entries = list(entries)
                except Exception:
                    entries = []

            if not entries:
                return jsonify({"error": "Playlist boş"}), 400
            
            # Aşırı beklemeyi engellemek için maks 200 video ile sınırla
            for idx, entry in enumerate(entries[:200]):
                if entry:
                    item_url = entry.get("url") or entry.get("webpage_url") or url
                    # YouTube'da bazen sadece ID gelir, URL oluştur:
                    if not str(item_url).startswith("http") and entry.get("id"):
                        if "youtube" in info.get("extractor", "").lower() or "youtube" in url:
                            item_url = f"https://www.youtube.com/watch?v={entry.get('id')}"

                    playlist_items.append({
                        "id": entry.get("id", str(idx)),
                        "title": entry.get("title", f"Video {idx+1}"),
                        "duration": entry.get("duration", 0),
                        "url": item_url
                    })
            
            if not playlist_items:
                return jsonify({"error": "Playlist videoları alınamadı"}), 400
                
            # Playlistin kalitelerini (format) göstermek için SADECE İLK videoyu tam detaylı çek
            first_url = playlist_items[0]["url"]
            ydl_opts_single = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "no_check_certificates": True,
                "socket_timeout": 15,
            }
            try:
                first_info, _ = extract_with_cookie_fallback(first_url, ydl_opts_single, cookies_browser)
                if first_info:
                    info["formats"] = first_info.get("formats", [])
                    info["thumbnail"] = info.get("thumbnail") or first_info.get("thumbnail", "")
                    info["duration"] = info.get("duration") or first_info.get("duration", 0)
                    info["uploader"] = info.get("uploader") or first_info.get("uploader", "Bilinmeyen")
            except Exception:
                pass

        formats = info.get("formats", [])

        # Collect video formats
        video_formats = []
        seen_video = set()
        for f in formats:
            vcodec = f.get("vcodec", "none")
            acodec = f.get("acodec", "none")
            height = f.get("height")
            fps = f.get("fps")
            ext = f.get("ext", "mp4")
            format_id = f.get("format_id", "")
            filesize = f.get("filesize") or f.get("filesize_approx") or 0

            if vcodec != "none" and height:
                # Video with or without audio
                has_audio = acodec != "none"
                key = f"{height}p_{fps}fps_{has_audio}"
                if key not in seen_video:
                    seen_video.add(key)
                    video_formats.append({
                        "format_id": format_id,
                        "height": height,
                        "fps": fps,
                        "ext": ext,
                        "has_audio": has_audio,
                        "filesize": filesize,
                        "quality_label": f"{height}p" + (f" {fps}fps" if fps and fps > 30 else ""),
                        "vcodec": vcodec,
                        "acodec": acodec
                    })

        # Sort by height descending
        video_formats.sort(key=lambda x: (x["height"], x.get("fps", 30)), reverse=True)

        # Collect unique video qualities for "video+audio" merge
        unique_heights = []
        seen_heights = set()
        for vf in video_formats:
            h = vf["height"]
            fps = vf.get("fps", 30)
            key = f"{h}_{fps}"
            if key not in seen_heights:
                seen_heights.add(key)
                unique_heights.append({
                    "height": h,
                    "fps": fps,
                    "quality_label": vf["quality_label"]
                })

        # Collect audio formats
        audio_formats = []
        seen_audio = set()
        for f in formats:
            vcodec = f.get("vcodec", "none")
            acodec = f.get("acodec", "none")
            abr = f.get("abr") or f.get("tbr")
            ext = f.get("ext", "m4a")
            format_id = f.get("format_id", "")
            filesize = f.get("filesize") or f.get("filesize_approx") or 0

            if vcodec == "none" and acodec != "none" and abr:
                key = f"{int(abr)}kbps"
                if key not in seen_audio:
                    seen_audio.add(key)
                    audio_formats.append({
                        "format_id": format_id,
                        "abr": int(abr),
                        "ext": ext,
                        "filesize": filesize,
                        "quality_label": f"{int(abr)} kbps",
                        "acodec": acodec
                    })

        audio_formats.sort(key=lambda x: x["abr"], reverse=True)

        # Determine platform
        extractor = info.get("extractor", "").lower()
        platform = "Bilinmeyen Platform"
        if "youtube" in extractor:
            platform = "YouTube"
        elif "instagram" in extractor:
            platform = "Instagram"
        elif "tiktok" in extractor:
            platform = "TikTok"
        elif "twitter" in extractor or "x.com" in extractor:
            platform = "X (Twitter)"
        elif "facebook" in extractor:
            platform = "Facebook"
        elif "reddit" in extractor:
            platform = "Reddit"
        elif "twitch" in extractor:
            platform = "Twitch"
        elif "vimeo" in extractor:
            platform = "Vimeo"
        elif "dailymotion" in extractor:
            platform = "Dailymotion"
        elif "bilibili" in extractor:
            platform = "Bilibili"
        else:
            platform = extractor.replace(":", " ").title() or "Bilinmeyen"

        result = {
            "title": get_display_title(info) or "Bilinmeyen Video",
            "thumbnail": info.get("thumbnail", ""),
            "duration": info.get("duration", 0),
            "uploader": info.get("uploader", "Bilinmeyen"),
            "view_count": info.get("view_count", 0),
            "platform": platform,
            "url": url,
            "video_qualities": unique_heights,
            "video_formats": video_formats,
            "audio_formats": audio_formats,
            "is_playlist": is_playlist,
            "playlist_items": playlist_items
        }

        return jsonify(result)

    except yt_dlp.utils.DownloadError as e:
        message, extra = friendly_error(e, url)
        return jsonify({"error": message, **extra}), 400
    except Exception as e:
        return jsonify({"error": f"Beklenmeyen hata: {str(e)[:200]}"}), 500


@app.route("/api/download", methods=["POST"])
def download_video():
    """Download video/audio with specified options."""
    data = request.json
    url = data.get("url", "").strip()
    cookies_browser = data.get("cookies_browser", "auto")
    mode = data.get("mode", "video_audio")  # video_audio, video_only, audio_only
    quality = data.get("quality", "best")  # height like 1080, or 'best'
    audio_quality = data.get("audio_quality", "best")  # abr like 128, or 'best'
    audio_format = data.get("audio_format", "mp3")  # mp3, m4a, wav, etc.
    start_time = data.get("start_time", "").strip()
    end_time = data.get("end_time", "").strip()

    def time_to_sec(t_str):
        if not t_str: return None
        parts = t_str.split(':')
        parts.reverse()
        sec = 0
        try:
            for i, part in enumerate(parts):
                sec += float(part) * (60 ** i)
            return sec
        except ValueError:
            return None

    s_sec = time_to_sec(start_time)
    e_sec = time_to_sec(end_time)

    if not url:
        return jsonify({"error": "URL gerekli"}), 400

    task_id = str(uuid.uuid4())
    download_progress[task_id] = {"status": "starting", "percent": 0}

    # Build yt-dlp options (UUID only for filename to avoid Windows path/lock issues)
    output_template = os.path.join(DOWNLOAD_DIR, f"{task_id}.%(ext)s")

    # Validate URL
    if not url.startswith(("http://", "https://")):
        return jsonify({"error": "Geçersiz URL. URL http:// veya https:// ile başlamalı."}), 400

    ydl_opts = {
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": True,
        "no_check_certificates": True,
        "progress_hooks": [get_progress_hook(task_id)],
        "merge_output_format": "mp4",
        "abort_on_error": False,
        "windowsfilenames": True,
        "restrictfilenames": True,
        "retries": 10,
        "file_access_retries": 10,
        "socket_timeout": 20,
        # HLS/DASH videolarda parçaları paralel indir — büyük hız farkı yaratır
        "concurrent_fragment_downloads": 8,
        # Büyük parçalar halinde indir (YouTube hız kısıtlamasını azaltır)
        "http_chunk_size": 10 * 1024 * 1024,
    }

    if s_sec is not None or e_sec is not None:
        if s_sec is None: s_sec = 0
        if e_sec is None: e_sec = 999999
        ydl_opts['download_ranges'] = yt_dlp.utils.download_range_func(None, [(s_sec, e_sec)])
        ydl_opts['force_keyframes_at_cuts'] = True


    # Find ffmpeg - check known install locations since PATH may not be updated
    ffmpeg_path = _find_ffmpeg()
    if ffmpeg_path:
        ydl_opts["ffmpeg_location"] = ffmpeg_path

    if mode == "audio_only":
        if ffmpeg_path:
            ydl_opts["format"] = "bestaudio/best"
            ydl_opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": audio_format,
                "preferredquality": str(audio_quality) if audio_quality != "best" else "0",
            }]
        else:
            ydl_opts["format"] = "bestaudio/best"
            del ydl_opts["merge_output_format"]
    elif mode == "video_only":
        if quality != "best":
            ydl_opts["format"] = f"bestvideo[height<={quality}]/best[height<={quality}]/bestvideo/best"
        else:
            ydl_opts["format"] = "bestvideo/best"
        if not ffmpeg_path:
            del ydl_opts["merge_output_format"]
    else:  # video_audio
        if not ffmpeg_path:
            # Without ffmpeg can't merge separate streams, use pre-muxed
            if quality != "best":
                ydl_opts["format"] = f"best[height<={quality}]/best"
            else:
                ydl_opts["format"] = "best"
            del ydl_opts["merge_output_format"]
        else:
            if quality != "best":
                ydl_opts["format"] = f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best"
            else:
                ydl_opts["format"] = "bestvideo+bestaudio/best"
            # Convert audio to AAC during merge (Opus in MP4 breaks Windows players)
            ydl_opts["postprocessor_args"] = {
                "merger": ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k"]
            }

    def do_download():
        try:
            info, _ = extract_with_cookie_fallback(url, ydl_opts, cookies_browser, download=True)

            if info and info.get("_type") == "playlist":
                entries = info.get("entries", [])
                if entries:
                    info = entries[0]

            # Find the downloaded file
            if info:
                with yt_dlp.YoutubeDL({"outtmpl": output_template, "quiet": True}) as ydl_name:
                    filename = ydl_name.prepare_filename(info)
                # For audio extraction, the extension might change
                if mode == "audio_only" and ffmpeg_path:
                    base = os.path.splitext(filename)[0]
                    filename = f"{base}.{audio_format}"

                # Search for the actual file (yt-dlp might modify the name)
                if not os.path.exists(filename):
                    # Search in download dir for files with our task_id
                    for f in os.listdir(DOWNLOAD_DIR):
                        if f.startswith(task_id):
                            filename = os.path.join(DOWNLOAD_DIR, f)
                            break

                title = get_display_title(info)
                ext = os.path.splitext(filename)[1]
                with progress_lock:
                    download_progress[task_id] = {
                        "status": "completed",
                        "percent": 100,
                        "filename": os.path.basename(filename),
                        "filepath": filename,
                        "title": title,
                        "download_name": build_download_name(title, ext)
                    }
            else:
                with progress_lock:
                    download_progress[task_id] = {
                        "status": "error",
                        "error": "İndirme başarısız"
                    }
        except Exception as e:
            error_str = str(e)
            # Handle Windows Defender/ffmpeg locking the file and preventing yt-dlp rename
            if "WinError 32" in error_str:
                time.sleep(2)  # Wait for file to be released
                found_file = None
                for f in os.listdir(DOWNLOAD_DIR):
                    if f.startswith(task_id):
                        found_file = os.path.join(DOWNLOAD_DIR, f)
                        break
                
                if found_file:
                    # If it's still stuck as .temp, try to rename it ourselves
                    if ".temp." in found_file:
                        final_file = found_file.replace(".temp.", ".")
                        try:
                            os.rename(found_file, final_file)
                            found_file = final_file
                        except Exception:
                            pass
                            
                    ext = os.path.splitext(found_file)[1]
                    with progress_lock:
                        download_progress[task_id] = {
                            "status": "completed",
                            "percent": 100,
                            "filename": os.path.basename(found_file),
                            "filepath": found_file,
                            "title": "video",
                            "download_name": build_download_name("video", ext)
                        }
                    return

            error_str, login_extra = friendly_error(e, url)

            with progress_lock:
                # Giris gerekiyorsa arayuz giris butonunu burada da gostersin.
                # Yas sinirli videolarda bilgi alma gecip takilma INDIRMEDE
                # olabiliyor; eskiden bu yol sadece kirmizi bir yazi
                # gosteriyordu ve kullanicinin giris yapacak yeri yoktu.
                download_progress[task_id] = {
                    "status": "error",
                    "error": error_str[:300],
                    **login_extra,
                }

    thread = threading.Thread(target=do_download, daemon=True)
    thread.start()

    return jsonify({"task_id": task_id})


@app.route("/api/progress/<task_id>")
def get_progress(task_id):
    """Get download progress via SSE."""
    def generate():
        while True:
            with progress_lock:
                progress = download_progress.get(task_id, {"status": "unknown"})

            yield f"data: {json.dumps(progress)}\n\n"

            if progress.get("status") in ("completed", "error", "unknown"):
                break

            time.sleep(0.5)

    return Response(generate(), mimetype="text/event-stream")


@app.route("/api/file/<task_id>")
def serve_file(task_id):
    """Serve the downloaded file."""
    with progress_lock:
        progress = download_progress.get(task_id)

    if not progress or progress.get("status") != "completed":
        return jsonify({"error": "Dosya bulunamadı"}), 404

    filepath = progress.get("filepath", "")
    if not os.path.exists(filepath):
        return jsonify({"error": "Dosya bulunamadı"}), 404

    # The file on disk is just <task_id>.ext; show "<title>_<date-time>.<ext>"
    ext = os.path.splitext(filepath)[1]
    download_name = progress.get("download_name")
    if not download_name:
        download_name = build_download_name(progress.get("title", "video"), ext)

    return send_file(
        filepath,
        as_attachment=True,
        download_name=download_name
    )


@app.route("/api/cleanup/<task_id>", methods=["DELETE"])
def cleanup(task_id):
    """Clean up downloaded file after serving."""
    with progress_lock:
        progress = download_progress.pop(task_id, None)

    if progress:
        filepath = progress.get("filepath", "")
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError:
                pass

    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Guncelleme
# ---------------------------------------------------------------------------

# Acilista arka planda doldurulur; UI'in ag beklemesini onler.
_app_update_info = None
_app_update_lock = threading.Lock()


def _has_active_download():
    with progress_lock:
        return any(p.get("status") in ("starting", "downloading", "processing")
                   for p in download_progress.values())


def check_app_update_async():
    """Uygulama guncellemesini arka planda kontrol et (acilisi geciktirmesin).

    Otomatik guncelleme acikken kurulum dosyasi da sessizce indirilir; bir
    sonraki acilista launcher onu kurar. Indirme kullanicinin indirmeleriyle
    yarismasin diye once bos ana beklenir.
    """
    def worker():
        global _app_update_info
        info = updater.app_update_available()
        with _app_update_lock:
            _app_update_info = info
        if not info or not updater.get_auto_update():
            return

        # Aktif indirme varken ~70 MB'lik kurulumu cekmeyelim; 30 dk boyunca
        # bos an kollanir, bulunamazsa bir sonraki aciliSta tekrar denenir.
        for _ in range(60):
            if not _has_active_download():
                break
            time.sleep(30)
        else:
            return

        try:
            updater.stage_app_update(info)
        except Exception:
            pass

    threading.Thread(target=worker, daemon=True).start()


@app.route("/api/update/status")
def update_status():
    with _app_update_lock:
        info = _app_update_info
    # yt-dlp'nin nereden yuklendigi destek icin onemli: kullanici klasoru
    # guncellenebilir kopya, paket ici olan ise yedek.
    try:
        source = os.path.dirname(yt_dlp.__file__)
        updatable = source.lower().startswith(updater.user_runtime_dir().lower())
    except Exception:
        source, updatable = None, False

    staged = updater.staged_update()
    return jsonify({
        "app_version": updater.APP_VERSION,
        "ytdlp_version": updater.installed_ytdlp_version(),
        "ytdlp_source": source,
        "ytdlp_updatable": updatable,
        "app_update": info,
        "auto_update": updater.get_auto_update(),
        "staged_version": staged["version"] if staged else None,
        # curl_cffi eksikse TikTok/Instagram cikarimi calismaz; kullanici
        # bunu Ayarlar'da gormeli.
        "impersonation": has_impersonate_support(),
    })


@app.route("/api/update/auto", methods=["POST"])
def set_auto_update_route():
    """Otomatik guncelleme anahtari."""
    enabled = bool((request.json or {}).get("enabled", True))
    return jsonify({"auto_update": updater.set_auto_update(enabled)})


@app.route("/api/update/ytdlp", methods=["POST"])
def update_ytdlp_now():
    """yt-dlp'yi simdi guncelle. Yeni surum bir sonraki acilista devreye girer."""
    changed, message = updater.update_ytdlp(force=True)
    return jsonify({"updated": changed, "message": message,
                    "restart_required": changed})


@app.route("/api/update/app", methods=["POST"])
def update_app_now():
    """Kurulum dosyasini indirip calistirir; uygulama kapanir."""
    with _app_update_lock:
        info = _app_update_info

    # Otomatik guncelleme zaten indirip DOGRULAMIS olabilir; tekrar indirme.
    staged = updater.staged_update()
    if staged:
        path = staged["path"]
    elif not info:
        return jsonify({"error": "Guncelleme yok"}), 400
    else:
        try:
            path = updater.download_app_installer(info["url"],
                                                  info.get("sha256_url"))
        except Exception as e:
            return jsonify({"error": "Indirilemedi: %s" % e}), 500

    # Kurulum sihirbazini baslat, sonra uygulamadan cik ki dosyalar serbest kalsin
    def launch():
        time.sleep(1)
        try:
            os.startfile(path)  # noqa: S606 - kullanici onayli kurulum
        except Exception:
            pass
        os._exit(0)

    threading.Thread(target=launch, daemon=True).start()
    return jsonify({"status": "installer_started"})


if __name__ == "__main__":
    print("=" * 50)
    print("  Video Downloader - http://localhost:5000")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=True)
