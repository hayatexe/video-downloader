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

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

APP_VERSION = "1.3.0"

GITHUB_REPO = "hayatexe/video-downloader"
PYPI_YTDLP_JSON = "https://pypi.org/pypi/yt-dlp/json"
PYPI_EJS_JSON = "https://pypi.org/pypi/yt-dlp-ejs/%s/json"
GITHUB_LATEST_RELEASE = "https://api.github.com/repos/%s/releases/latest" % GITHUB_REPO

USER_AGENT = "VideoDownloader/%s" % APP_VERSION
NET_TIMEOUT = 10          # tek bir istegin azami suresi
CHECK_INTERVAL = 24 * 3600      # yt-dlp: gunde bir kez kontrol yeter
APP_CHECK_INTERVAL = 6 * 3600   # uygulama: gunde birkac kez bakmak yeterli

# Inno Setup sessiz kurulum bayraklari
SILENT_FLAGS = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                "/NOCANCEL", "/CLOSEAPPLICATIONS"]

# Ayni surumu bu kadar denedikten sonra otomatik kurulumdan vazgec; aksi
# halde kurulum her acilista basarisiz olup sonsuz donguye girebilir.
MAX_INSTALL_ATTEMPTS = 2


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


def _version_from_dir(pkg_dir):
    """yt_dlp/version.py icindeki __version__'u dosyadan oku."""
    try:
        with open(os.path.join(pkg_dir, "version.py"), "r", encoding="utf-8") as f:
            m = re.search(r"^__version__\s*=\s*['\"]([^'\"]+)", f.read(), re.M)
        return m.group(1) if m else None
    except Exception:
        return None


def installed_ytdlp_version():
    """Yuklu (ya da yuklenecek) yt-dlp surumu.

    DIKKAT: acilista bu, yt_dlp import edilmeden ONCE cagrilir. Sadece
    `import yt_dlp` denemek o asamada None dondurur; o zaman surum
    karsilastirmasi atlanir ve guncel olsa bile her gun bosuna ~9,5 MB
    indirilir. Bu yuzden import yoksa surum dogrudan dosyadan okunur --
    activate() ile ayni oncelik sirasiyla.
    """
    mod = sys.modules.get("yt_dlp")
    if mod is not None:
        try:
            return mod.version.__version__
        except Exception:
            pass

    for d in (user_runtime_dir(), bundled_runtime_dir()):
        if not d:
            continue
        pkg = os.path.join(d, "yt_dlp")
        if _looks_like_ytdlp(pkg):
            v = _version_from_dir(pkg)
            if v:
                return v

    # Gelistirme modu: site-packages'taki kopya
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
    """Yeni yt-dlp varsa indirip kullanici klasorune kurar, ardindan
    yt-dlp-ejs'i yt-dlp'nin istedigi surume getirir.

    Dondurur: (guncellendi_mi, mesaj). Guncelleme bir sonraki ACILISTA
    devreye girer -- yt_dlp bu surecte zaten import edilmis durumda.
    """
    changed, message = _update_ytdlp_core(force)
    try:
        ejs_changed, ejs_message = ensure_ejs()
    except Exception as e:
        ejs_changed, ejs_message = False, "ejs: %s" % e
    if ejs_changed:
        message = "%s; %s" % (message, ejs_message)
    return changed or ejs_changed, message


def _update_ytdlp_core(force=False):
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
    """GitHub'daki son surum: (surum, installer_url, sha256_url, notlar)."""
    data = _get_json(GITHUB_LATEST_RELEASE)
    tag = (data.get("tag_name") or "").lstrip("vV")
    url = None
    sha_url = None
    for a in data.get("assets", []):
        name = (a.get("name") or "").lower()
        if name.endswith(".exe") and url is None:
            url = a.get("browser_download_url")
        elif "sha256" in name and sha_url is None:
            sha_url = a.get("browser_download_url")
    return tag, url, sha_url, data.get("body") or ""


def app_update_available():
    """Yeni uygulama surumu varsa bilgi sozlugu, yoksa None."""
    try:
        tag, url, sha_url, notes = latest_app_release()
    except Exception:
        return None
    if not tag or not url:
        return None
    if _version_tuple(tag) <= _version_tuple(APP_VERSION):
        return None
    return {"version": tag, "url": url, "sha256_url": sha_url,
            "notes": notes, "current": APP_VERSION}


def _expected_sha256(sha256_url):
    """Yayindaki SHA256SUMS dosyasindan saglama toplamini oku."""
    text = _get(sha256_url, timeout=30).decode("utf-8", "replace")
    m = re.search(r"\b([0-9a-fA-F]{64})\b", text)
    return m.group(1).lower() if m else None


def download_app_installer(url, sha256_url=None, progress=None, dest=None):
    """Kurulum dosyasini indirip DOGRULAR, tam yolunu dondurur.

    Dogrulama neden sart: bu dosyayi uygulama kendisi indirip calistiriyor.
    urllib ile inen dosyaya Windows "Mark-of-the-Web" isareti konmadigi icin
    SmartScreen'in "bilinmeyen yayinci" onayi devreye girmez. (Defender'in
    gercek zamanli taramasi yine calisir, ama o kotu amacli yazilim arar;
    dosyanin BEKLENEN dosya olup olmadigini denetlemez.) Yani butunlugu
    dogrulayan tek yer burasi.

    Saglama toplami bulunamazsa guncelleme YAPILMAZ (dogrulanmamis bir exe
    calistirmaktansa guncellememek yegdir).

    Indirme once ".part" dosyasina yapilir: otomatik guncellemede yarim
    kalmis bir indirme "kurulmaya hazir surum" sanilmamali.
    """
    if not sha256_url:
        raise RuntimeError("yayinda SHA256 dosyasi yok, guncelleme durduruldu")

    expected = _expected_sha256(sha256_url)
    if not expected:
        raise RuntimeError("SHA256 dosyasi okunamadi, guncelleme durduruldu")

    if dest is None:
        dest = os.path.join(tempfile.gettempdir(),
                            "VideoDownloaderSetup-%s.exe" % int(time.time()))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    part = dest + ".part"
    digest = hashlib.sha256()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            with open(part, "wb") as f:
                while True:
                    chunk = r.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if progress and total:
                        progress(done * 100.0 / total)

        got = digest.hexdigest()
        if got != expected:
            raise RuntimeError(
                "saglama toplami uyusmuyor (beklenen %s..., gelen %s...)"
                % (expected[:12], got[:12]))
        if os.path.getsize(part) < 1024 * 1024:
            raise RuntimeError("indirilen kurulum dosyasi cok kucuk")
    except Exception:
        # Dogrulanmamis dosyayi diskte birakma
        try:
            os.remove(part)
        except OSError:
            pass
        raise

    if os.path.exists(dest):
        os.remove(dest)
    os.rename(part, dest)
    return dest


# --------------------------------------------------------------------------
# Otomatik guncelleme
#
# Akis: uygulama acikken yeni surumun kurulumu arka planda indirilir
# ("staging"). Bir sonraki acilista launcher bunu gorur, sessiz kurulumu
# baslatip uygulamayi kapatir; kurulum bitince uygulama yeniden acilir.
# Boylece kullanici hicbir sey onaylamaz, sadece bir sonraki aciliSta
# birkac saniye fazladan bekler.
# --------------------------------------------------------------------------

def updates_dir():
    """Indirilen kurulum dosyalarinin durdugu klasor."""
    return os.path.join(user_data_dir(), "updates")


def get_auto_update():
    """Otomatik guncelleme acik mi? (varsayilan: acik)"""
    return bool(_read_state().get("auto_update", True))


def set_auto_update(enabled):
    state = _read_state()
    state["auto_update"] = bool(enabled)
    _write_state(state)
    return bool(enabled)


def clear_staged_update(remove_file=True):
    """Hazirlanmis kurulumu unut (ve dosyasini sil)."""
    state = _read_state()
    staged = state.pop("staged_update", None)
    state.pop("staged_attempts", None)
    _write_state(state)
    if remove_file and staged:
        try:
            os.remove(staged.get("path", ""))
        except OSError:
            pass
    return staged


def staged_update():
    """Kurulmaya hazir bekleyen guncelleme varsa bilgisini dondurur.

    Surum artik eski kaldiysa (ornegin kurulum basarili oldu) ya da dosya
    kayboldusa kayit temizlenir.
    """
    staged = _read_state().get("staged_update")
    if not isinstance(staged, dict):
        return None
    path, version = staged.get("path"), staged.get("version")
    if not path or not version:
        clear_staged_update()
        return None
    if _version_tuple(version) <= _version_tuple(APP_VERSION):
        # Kurulum tutmus: dosyayi silip kaydi kapat.
        clear_staged_update()
        return None
    try:
        if os.path.getsize(path) < 1024 * 1024:
            raise OSError
    except OSError:
        clear_staged_update()
        return None
    return staged


def _prune_updates_dir(keep=None):
    """updates/ klasorunde sadece guncel kurulum dosyasi kalsin."""
    d = updates_dir()
    if not os.path.isdir(d):
        return
    for name in os.listdir(d):
        p = os.path.join(d, name)
        if keep and os.path.abspath(p) == os.path.abspath(keep):
            continue
        try:
            os.remove(p)
        except OSError:
            pass


def stage_app_update(info=None, progress=None, force=False):
    """Yeni surumun kurulumunu arka planda indirip bir sonraki acilisa hazirla.

    Dondurur: hazirlanan guncelleme sozlugu ya da None.
    """
    state = _read_state()
    now = time.time()
    if info is None:
        if not force and now - state.get("app_checked_at", 0) < APP_CHECK_INTERVAL:
            existing = staged_update()
            return existing
        info = app_update_available()
        state = _read_state()
        state["app_checked_at"] = now
        _write_state(state)
    if not info:
        return None

    existing = staged_update()
    if existing and existing.get("version") == info["version"]:
        return existing

    dest = os.path.join(updates_dir(),
                        "VideoDownloaderSetup-%s.exe" % info["version"])
    path = download_app_installer(info["url"], info.get("sha256_url"),
                                  progress=progress, dest=dest)
    _prune_updates_dir(keep=path)

    state = _read_state()
    state["staged_update"] = {
        "version": info["version"],
        "path": path,
        "notes": (info.get("notes") or "")[:2000],
        "staged_at": now,
    }
    state["staged_attempts"] = 0
    _write_state(state)
    return state["staged_update"]


def apply_staged_update(staged=None, relaunch_exe=None):
    """Sessiz kurulumu baslatir. True donerse uygulama HEMEN kapanmalidir.

    Kurulum sihirbazi uygulamanin dosyalarini degistirecegi icin surec
    hayatta kalamaz; kurulum bitince uygulama yeniden baslatilir.
    """
    staged = staged or staged_update()
    if not staged or os.name != "nt":
        return False

    state = _read_state()
    attempts = int(state.get("staged_attempts", 0))
    if attempts >= MAX_INSTALL_ATTEMPTS:
        # Iki kez denendi ve surum hala eski: otomatik kurulum bu surumde
        # calismiyor. Acilis dongusune girmemek icin vazgec, kullanici
        # Ayarlar'dan elle kurabilir.
        return False
    state["staged_attempts"] = attempts + 1
    _write_state(state)

    installer = staged["path"]
    exe = relaunch_exe
    if exe is None and getattr(sys, "frozen", False):
        exe = sys.executable

    # cmd /c: kurulum bitene kadar bekler, sonra uygulamayi yeniden acar.
    # "&" kullaniliyor ki kurulum basarisiz olsa bile uygulama geri gelsin.
    cmdline = '"%s" %s' % (installer, " ".join(SILENT_FLAGS))
    if exe:
        cmdline += ' & start "" "%s"' % exe

    flags = 0
    for name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"):
        flags |= getattr(subprocess, name, 0)
    try:
        subprocess.Popen(["cmd", "/c", cmdline], creationflags=flags,
                         close_fds=True)
    except Exception:
        return False
    return True


# --------------------------------------------------------------------------
# yt-dlp-ejs (YouTube JS cozucu betikleri)
#
# yt-dlp, YouTube'un sifre bulmacalarini harici bir JS calistiricisinda
# (bizde paketlenen quickjs) cozer. Cozucu betikler yt-dlp-ejs paketinden
# gelir ve yt-dlp bunlarin SURUMUNU ve HASH'ini dogrular
# (yt_dlp/extractor/youtube/jsc/_builtin/vendor/_info.py). Yani yt-dlp
# kendini guncelleyip yeni bir ejs surumu isterse, eski ejs reddedilir ve
# girisli YouTube indirmeleri "Requested format is not available" ile
# bozulur. Bu yuzden ejs, yt-dlp'nin istedigi TAM surume getirilir.
# --------------------------------------------------------------------------

def _runtime_dirs():
    """activate() ile ayni oncelik: once kullanici, sonra paket."""
    return [d for d in (user_runtime_dir(), bundled_runtime_dir()) if d]


def _read_version(path, pattern):
    try:
        with open(path, "r", encoding="utf-8") as f:
            m = re.search(pattern, f.read(), re.M)
        return m.group(1) if m else None
    except Exception:
        return None


def required_ejs_version():
    """Etkin yt-dlp kopyasinin bekledigi yt-dlp-ejs surumu."""
    for d in _runtime_dirs():
        pkg = os.path.join(d, "yt_dlp")
        if _looks_like_ytdlp(pkg):
            return _read_version(
                os.path.join(pkg, "extractor", "youtube", "jsc", "_builtin",
                             "vendor", "_info.py"),
                r"^VERSION\s*=\s*['\"]([^'\"]+)")
    return None


def installed_ejs_version():
    """import yt_dlp_ejs'in yukleyecegi kopyanin surumu."""
    for d in _runtime_dirs():
        v = _read_version(os.path.join(d, "yt_dlp_ejs", "_version.py"),
                          r"version\s*=\s*['\"]([^'\"]+)")
        if v:
            return v
    return None


def ensure_ejs():
    """yt-dlp-ejs'i yt-dlp'nin istedigi surume getir.

    Agi sadece surumler uyusmadiginda kullanir. Dondurur: (degisti_mi, mesaj).
    """
    required = required_ejs_version()
    if not required:
        # Gelistirme modu (runtime klasoru yok): pip'teki paketler kullanilir
        return False, "ejs: runtime yok, atlandi"
    current = installed_ejs_version()
    if current == required:
        return False, "ejs guncel (%s)" % current

    data = _get_json(PYPI_EJS_JSON % required)
    wheel_url = None
    for u in data.get("urls", []):
        if u.get("packagetype") == "bdist_wheel":
            wheel_url = u["url"]
            break
    if not wheel_url:
        raise RuntimeError("yt-dlp-ejs %s wheel bulunamadi" % required)

    runtime = user_runtime_dir()
    os.makedirs(runtime, exist_ok=True)
    staging = os.path.join(runtime, ".staging-ejs")
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging, exist_ok=True)
    try:
        whl = os.path.join(staging, "ejs.whl")
        with open(whl, "wb") as f:
            f.write(_get(wheel_url, timeout=60))
        with zipfile.ZipFile(whl) as z:
            z.extractall(staging)
        new_pkg = os.path.join(staging, "yt_dlp_ejs")
        if not os.path.isfile(os.path.join(new_pkg, "yt", "solver", "lib.min.js")):
            raise RuntimeError("indirilen yt-dlp-ejs eksik gorunuyor")

        target = os.path.join(runtime, "yt_dlp_ejs")
        old = target + ".old"
        shutil.rmtree(old, ignore_errors=True)
        if os.path.isdir(target):
            os.rename(target, old)
        shutil.move(new_pkg, target)
        shutil.rmtree(old, ignore_errors=True)
        return True, "yt-dlp-ejs %s -> %s" % (current or "yok", required)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
