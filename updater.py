"""
Video Downloader - Otomatik guncelleme

Iki ayri guncelleme kanali var:

1. yt-dlp kanali (sik, ~3 MB)
   YouTube/TikTok ayda birkac kez cikarim yontemini degistiriyor ve eski
   yt-dlp "HTTP Error 403" ya da "Unexpected response from webpage request"
   vermeye basliyor. Bu yuzden yt-dlp exe'nin icine GOMULMEZ; yazilabilir bir
   klasorden yuklenir ve oradan guncellenir. Boylece uygulamayi yeniden
   derlemeye gerek kalmaz.

2. Uygulama kanali (nadir, ~65 MB)
   GitHub Releases'teki son surum kontrol edilir, kullaniciya sorulur.

DIKKAT: activate() `import yt_dlp` YAPILMADAN ONCE cagrilmalidir. app.py bunu
kendi ilk satirlarinda yapar.
"""

import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.request
import zipfile

APP_VERSION = "1.2.0"

GITHUB_REPO = "hayatexe/video-downloader"
PYPI_YTDLP_JSON = "https://pypi.org/pypi/yt-dlp/json"
GITHUB_LATEST_RELEASE = "https://api.github.com/repos/%s/releases/latest" % GITHUB_REPO

USER_AGENT = "VideoDownloader/%s" % APP_VERSION
NET_TIMEOUT = 10          # tek bir istegin azami suresi
CHECK_INTERVAL = 24 * 3600  # gunde bir kez kontrol yeter


# --------------------------------------------------------------------------
# Klasorler
# --------------------------------------------------------------------------

def user_data_dir():
    """Yazilabilir uygulama klasoru (%LOCALAPPDATA%\\Video Downloader)."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Video Downloader")


def user_runtime_dir():
    """Guncellenebilir yt_dlp'nin durdugu klasor."""
    return os.path.join(user_data_dir(), "runtime")


def bundled_runtime_dir():
    """Kurulumla gelen yedek yt_dlp kopyasi (sadece frozen modda)."""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "runtime")
    return None


def _state_path():
    return os.path.join(user_data_dir(), "update_state.json")


def _read_state():
    try:
        with open(_state_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_state(state):
    try:
        os.makedirs(user_data_dir(), exist_ok=True)
        with open(_state_path(), "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception:
        pass


# --------------------------------------------------------------------------
# yt-dlp'yi yukleme
# --------------------------------------------------------------------------

def _looks_like_ytdlp(path):
    """Klasorun ise yarar bir yt_dlp kopyasi oldugunu kabaca dogrula."""
    need = [
        os.path.join(path, "__init__.py"),
        os.path.join(path, "YoutubeDL.py"),
        os.path.join(path, "version.py"),
        os.path.join(path, "extractor", "__init__.py"),
    ]
    return all(os.path.isfile(p) for p in need)


def activate():
    """yt_dlp'yi once kullanici klasorunden, olmazsa paketten yukle.

    Bozuk bir indirme uygulamayi kilitlemesin diye kullanici kopyasi
    import edilemezse kenara alinir ve paketteki saglam kopyaya donulur.
    """
    candidates = []
    u = user_runtime_dir()
    if _looks_like_ytdlp(os.path.join(u, "yt_dlp")):
        candidates.append(u)
    b = bundled_runtime_dir()
    if b and _looks_like_ytdlp(os.path.join(b, "yt_dlp")):
        candidates.append(b)

    # sys.path'e ters sirada ekle ki ilk aday en onde kalsin
    for d in reversed(candidates):
        while d in sys.path:
            sys.path.remove(d)
        sys.path.insert(0, d)

    try:
        import yt_dlp  # noqa: F401
        return yt_dlp
    except Exception as first_err:
        # Kullanici kopyasi denenmediyse yapacak bir sey yok
        if not candidates or candidates[0] != u:
            raise

        # Kullanici kopyasini gecici olarak devreden cikar ve paketteki ile dene
        while u in sys.path:
            sys.path.remove(u)
        for mod in [m for m in sys.modules
                    if m == "yt_dlp" or m.startswith("yt_dlp.")]:
            sys.modules.pop(mod, None)

        try:
            import yt_dlp  # noqa: F401
        except Exception:
            # Paketteki kopya da ayni hatayi veriyor: sorun kullanici
            # kopyasinda DEGIL (or. paketten eksik bir modul). Saglam bir
            # kopyayi karantinaya almayalim; asil hatayi bildir.
            raise first_err

        # Buraya gelindiyse: paketteki calisiyor, kullanicininki gercekten
        # bozuk. Kenara al ve bir sonraki acilista yeniden indirilsin.
        try:
            bad = os.path.join(u, "yt_dlp")
            shutil.rmtree(bad + ".broken", ignore_errors=True)
            os.rename(bad, bad + ".broken")
        except Exception:
            pass
        flag_ytdlp_stale()
        return yt_dlp


def installed_ytdlp_version():
    try:
        import yt_dlp
        return yt_dlp.version.__version__
    except Exception:
        return None


# --------------------------------------------------------------------------
# Ag yardimcilari
# --------------------------------------------------------------------------

def _get(url, timeout=NET_TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _get_json(url, timeout=NET_TIMEOUT):
    return json.loads(_get(url, timeout).decode("utf-8"))


def _version_tuple(v):
    """'2026.08.19' -> (2026, 8, 19); karsilastirilabilir hale getirir."""
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


# --------------------------------------------------------------------------
# yt-dlp guncelleme
# --------------------------------------------------------------------------

def latest_ytdlp():
    """PyPI'dan (surum, wheel_url) dondurur."""
    data = _get_json(PYPI_YTDLP_JSON)
    version = data["info"]["version"]
    for u in data["urls"]:
        if u.get("packagetype") == "bdist_wheel":
            return version, u["url"]
    raise RuntimeError("yt-dlp wheel bulunamadi")


def update_ytdlp(force=False):
    """Yeni yt-dlp varsa indirip kullanici klasorune kurar.

    Dondurur: (guncellendi_mi, mesaj). Guncelleme bir sonraki ACILISTA
    devreye girer -- yt_dlp bu surecte zaten import edilmis durumda.
    """
    state = _read_state()
    now = time.time()
    # Ilk calistirmada state dosyasi yoktur -> kontrol calisir.
    # Bozuk kopya karantinaya alindiginda activate() flag_ytdlp_stale() ile
    # bu zaman damgasini sifirlar -> yine kontrol calisir.
    if not force and now - state.get("ytdlp_checked_at", 0) < CHECK_INTERVAL:
        return False, "yakin zamanda kontrol edildi"

    current = installed_ytdlp_version()
    try:
        version, wheel_url = latest_ytdlp()
    except Exception as e:
        return False, "surum kontrolu basarisiz: %s" % e

    state["ytdlp_checked_at"] = now
    _write_state(state)

    if current and _version_tuple(version) <= _version_tuple(current):
        return False, "yt-dlp zaten guncel (%s)" % current

    runtime = user_runtime_dir()
    os.makedirs(runtime, exist_ok=True)
    staging = os.path.join(runtime, ".staging")
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging, exist_ok=True)

    try:
        blob = _get(wheel_url, timeout=120)
        whl = os.path.join(staging, "ytdlp.whl")
        with open(whl, "wb") as f:
            f.write(blob)
        with zipfile.ZipFile(whl) as z:
            z.extractall(staging)

        new_pkg = os.path.join(staging, "yt_dlp")
        if not _looks_like_ytdlp(new_pkg):
            raise RuntimeError("indirilen paket eksik gorunuyor")

        # Yerine koy: once eskisini kenara al, sonra yenisini tasi
        target = os.path.join(runtime, "yt_dlp")
        old = target + ".old"
        shutil.rmtree(old, ignore_errors=True)
        if os.path.isdir(target):
            os.rename(target, old)
        shutil.move(new_pkg, target)
        shutil.rmtree(old, ignore_errors=True)

        state["ytdlp_version"] = version
        _write_state(state)
        return True, "yt-dlp %s -> %s" % (current or "yok", version)
    except Exception as e:
        return False, "yt-dlp guncellenemedi: %s" % e
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def flag_ytdlp_stale():
    """Cikarim hatasi alindiginda cagrilir: sonraki aciliSta zorla kontrol et."""
    state = _read_state()
    state["ytdlp_checked_at"] = 0
    state["ytdlp_stale"] = True
    _write_state(state)


# --------------------------------------------------------------------------
# Uygulama guncelleme (GitHub Releases)
# --------------------------------------------------------------------------

def latest_app_release():
    """GitHub'daki son surumu dondurur: (surum, installer_url, notlar)."""
    data = _get_json(GITHUB_LATEST_RELEASE)
    tag = (data.get("tag_name") or "").lstrip("vV")
    url = None
    for a in data.get("assets", []):
        if a.get("name", "").lower().endswith(".exe"):
            url = a.get("browser_download_url")
            break
    return tag, url, data.get("body") or ""


def app_update_available():
    """Yeni uygulama surumu varsa bilgi sozlugu, yoksa None."""
    try:
        tag, url, notes = latest_app_release()
    except Exception:
        return None
    if not tag or not url:
        return None
    if _version_tuple(tag) <= _version_tuple(APP_VERSION):
        return None
    return {"version": tag, "url": url, "notes": notes, "current": APP_VERSION}


def download_app_installer(url, progress=None):
    """Kurulum dosyasini indirir, gecici yolunu dondurur."""
    dest = os.path.join(tempfile.gettempdir(),
                        "VideoDownloaderSetup-%s.exe" % int(time.time()))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        with open(dest, "wb") as f:
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(done * 100.0 / total)
    if os.path.getsize(dest) < 1024 * 1024:
        raise RuntimeError("indirilen kurulum dosyasi cok kucuk")
    return dest
