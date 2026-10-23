"""
Video Downloader - Desktop Launcher
PyInstaller entry point: bundles Flask + pywebview into a single .exe
"""

import sys
import os
import threading
import time
import socket

# Set working directory correctly for both dev and frozen mode
if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(sys.executable)
    BASE_DIR = sys._MEIPASS
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    BASE_DIR = APP_DIR

os.chdir(APP_DIR)

# Make sure app.py can be found
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


def _log(*parts):
    """Guvenli gunluk.

    PyInstaller'in penceresiz (console=False) modunda sys.stdout None'dir ve
    duz print() AttributeError firlatir. Bu bir thread icinde olursa thread
    sessizce oluyor -- acilis bir kez tam da bu yuzden kilitlendi. Bu yardimci
    asla istisna firlatmaz ve ciktiyi teshis icin dosyaya yazar.
    """
    msg = " ".join(str(p) for p in parts)
    try:
        import updater
        d = updater.user_data_dir()
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "launcher.log")
        # Gunluk sinirsiz buyumesin
        if os.path.isfile(path) and os.path.getsize(path) > 512 * 1024:
            os.replace(path, path + ".1")
        with open(path, "a", encoding="utf-8") as f:
            f.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass
    try:
        if sys.stdout is not None:
            print(msg)
    except Exception:
        pass


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]


def wait_for_server(port, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.2):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.1)
    return False


def start_flask(port):
    # Kendi thread'inde calisir: buradaki bir istisna boot() try blokuna
    # DUSMEZ ve penceresiz modda stderr None oldugu icin izsiz kaybolur.
    # Bu yuzden hatayi burada yakalayip gunluge yaziyoruz.
    try:
        import logging
        logging.getLogger('werkzeug').setLevel(logging.ERROR)
        from app import app
        app.run(host='127.0.0.1', port=port, debug=False,
                use_reloader=False, threaded=True)
    except Exception:
        import traceback
        _log("[HATA] Flask baslatilamadi:\n" + traceback.format_exc())


# Instant loading screen shown while Flask boots up
LOADING_HTML = """<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, 'Segoe UI', sans-serif;
    background: #0a0a0f;
    display: flex; align-items: center; justify-content: center;
    height: 100vh; flex-direction: column; gap: 20px;
    color: #f0f0f5;
}
.icon {
    width: 64px; height: 64px;
    background: linear-gradient(135deg, #8b5cf6, #6366f1);
    border-radius: 16px;
    display: flex; align-items: center; justify-content: center;
    font-size: 28px;
    box-shadow: 0 0 40px rgba(139,92,246,0.4);
    animation: float 2s ease-in-out infinite;
}
@keyframes float { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-8px)} }
.title {
    font-size: 26px; font-weight: 800;
    background: linear-gradient(135deg, #8b5cf6, #6366f1, #3b82f6);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}
.sub { font-size: 13px; color: #55556a; }
.spinner {
    width: 28px; height: 28px;
    border: 3px solid rgba(139,92,246,0.15);
    border-top-color: #8b5cf6;
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style></head>
<body>
    <div class="icon">▼</div>
    <div class="title">VideoDownloader</div>
    <div class="spinner"></div>
    <div class="sub">Başlatılıyor...</div>
</body></html>"""


def _splash(sub_text):
    """Yukleme ekranini farkli bir alt yazi ile uret."""
    return LOADING_HTML.replace("Başlatılıyor...", sub_text)

class Api:
    # DIKKAT: js_api'deki public oznitelikler pywebview tarafindan ozyinelemeli
    # taranir. Window nesnesi public tutulursa tum .NET nesne agaci yansima ile
    # gezilir ve arayuz ~15sn kilitlenir. Bu yuzden hepsi "_" ile gizli.
    def __init__(self):
        self._window = None
        self._minimize_to_tray = False

    def set_minimize_to_tray(self, val):
        self._minimize_to_tray = bool(val)
        return True

    def open_login(self, url=None, expect_domain=None):
        """Uygulama ici giris penceresi acar.

        Kullanici giris yapip pencereyi kapatana kadar cerezler periyodik
        olarak kaydedilir. Dondurur: expect_domain'e ait yakalanan cerez
        sayisi. 0 ise giris algilanmadi; arayuz kullaniciyi uyarir.

        expect_domain onemli: YouTube girisi accounts.google.com'da yapilir,
        oranin cerezleri yt-dlp'ye yaramaz. Sadece google.com cerezi
        yakalanip "giris basarili" denirse kullanici giris yapmis gibi
        gorunup yine "giris yapin" hatasi alir.
        """
        import webview
        import app as app_module

        if not url or not str(url).startswith("https://"):
            url = "https://www.instagram.com/accounts/login/"

        done = threading.Event()
        login_win = webview.create_window(
            "Giriş yapın — bittiğinde bu pencereyi kapatın",
            url, width=480, height=780
        )

        def on_closed():
            done.set()

        login_win.events.closed += on_closed

        saved = {"count": 0}

        def poller():
            # pywebview sadece O AN acik sayfanin cerezlerini verebiliyor.
            # Giris bittikten sonra kullanici pencereyi hemen kapatabilir;
            # dar bir aralikla bakiyoruz ki hedef sitenin cerezleri kacmasin.
            while not done.is_set():
                time.sleep(1.5)
                try:
                    cookies = login_win.get_cookies()
                    if cookies:
                        app_module.save_webview_cookies(cookies)
                        n = app_module.count_cookies_for_domain(cookies, expect_domain)
                        if n:
                            saved["count"] = max(saved["count"], n)
                except Exception:
                    pass

        threading.Thread(target=poller, daemon=True).start()

        done.wait(timeout=600)
        return saved["count"]

    def save_file_dialog(self, task_id):
        import app
        import webview
        import os
        import shutil
        
        progress = app.download_progress.get(task_id)
        if not progress or 'filepath' not in progress:
            return False
            
        filepath = progress['filepath']
        if not os.path.exists(filepath):
            return False
            
        ext = os.path.splitext(filepath)[1]
        default_name = progress.get('download_name')
        if not default_name:
            default_name = app.build_download_name(progress.get('title', 'video'), ext)
        
        win = self._window if self._window else webview.windows[0]
        result = win.create_file_dialog(webview.SAVE_DIALOG, directory='', save_filename=default_name)
        
        if result and len(result) > 0:
            save_path = result[0]
            try:
                shutil.copy2(filepath, save_path)
                return True
            except Exception:
                return False
        return False

def create_tray_image():
    from PIL import Image, ImageDraw
    image = Image.new('RGB', (64, 64), color=(139, 92, 246))
    d = ImageDraw.Draw(image)
    d.polygon([(20, 16), (44, 32), (20, 48)], fill=(255, 255, 255))
    return image

def already_running_focus_existing():
    """Single-instance guard: if the app is already open, focus its window
    and exit. Two instances would fight over the WebView2 profile lock and
    freeze the UI for up to a minute."""
    import ctypes
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW(None, False, "VideoDownloader_SingleInstance")
    if kernel32.GetLastError() != 183:  # ERROR_ALREADY_EXISTS
        return False
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, "Video Downloader")
    if hwnd:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
    return True


def setup_tray(window, api):
    import pystray
    def on_show(icon, item):
        window.show()
        window.restore()

    def on_exit(icon, item):
        # Zarif kapanis: WebView2'nin profili serbest birakmasina izin ver.
        # os._exit kullanmak profili kilitli birakip SONRAKI acilisi donduruyordu.
        icon.stop()
        window.destroy()

    image = create_tray_image()
    menu = pystray.Menu(
        pystray.MenuItem('Goster', on_show, default=True),
        pystray.MenuItem('Cikis', on_exit)
    )
    icon = pystray.Icon("Video Downloader", image, "Video Downloader", menu)
    
    threading.Thread(target=icon.run, daemon=True).start()
    return icon

def main():
    if already_running_focus_existing():
        return

    port = find_free_port()

    # Flask'i HEMEN baslatma: once yt-dlp guncellemesi yapilmali, cunku
    # start_flask -> app.py -> import yt_dlp zinciri kurulunca surum kilitlenir.
    # Guncelleme yukleme ekrani gorunurken arka planda kosar (bkz. boot()).

    import webview
    
    api = Api()

    # Create window immediately with loading screen — no wait!
    window = webview.create_window(
        title='Video Downloader',
        html=LOADING_HTML,
        width=940,
        height=800,
        min_size=(640, 520),
        background_color='#0a0a0f',
        text_select=True,
        zoomable=True,
        js_api=api
    )
    api._window = window

    # Yukleme ekrani gorunurken: once yt-dlp'yi guncelle, sonra Flask'i baslat.
    # Sira onemli -- yt_dlp import edildikten sonra surum degistirilemez.
    def boot():
        # 1) Bir onceki oturumda indirilmis bir surum bekliyor mu? Varsa
        #    sessizce kur ve uygulamayi kapat; kurulum bitince kendisi
        #    yeniden acilir. Kullaniciya hicbir sey sorulmaz.
        try:
            import updater
            staged = updater.staged_update() if updater.get_auto_update() else None
            if staged:
                _log("[guncelleme] sessiz kurulum baslatiliyor:", staged["version"])
                try:
                    window.load_html(_splash(
                        "Guncelleme kuruluyor (v%s)..." % staged["version"]))
                except Exception:
                    pass
                if updater.apply_staged_update(staged):
                    # Kurulum sihirbazi dosyalari degistirecek; surecin
                    # yasamasi mumkun degil.
                    time.sleep(2)
                    os._exit(0)
                _log("[guncelleme] sessiz kurulum baslatilamadi, normal acilis")
                try:
                    window.load_html(LOADING_HTML)
                except Exception:
                    pass
        except Exception as e:
            _log("[guncelleme] bekleyen kurulum atlandi:", repr(e))

        # 2) Guncelleme ne olursa olsun Flask BASLAMALI; hicbir hata acilisi
        # engellememeli.
        try:
            import updater
            changed, message = updater.update_ytdlp()
            _log("[guncelleme] yt-dlp:", message)
        except Exception as e:
            _log("[guncelleme] yt-dlp kontrolu atlandi:", repr(e))

        try:
            threading.Thread(target=start_flask, args=(port,), daemon=True).start()
            if wait_for_server(port, timeout=30):
                window.load_url(f'http://127.0.0.1:{port}')
                # Uygulama surumunu de kontrol et; UI /api/update/status ile alir
                try:
                    import app as app_module
                    app_module.check_app_update_async()
                except Exception as e:
                    _log("[guncelleme] uygulama kontrolu atlandi:", repr(e))
            else:
                _log("[HATA] Flask 30 sn icinde acilmadi")
        except Exception:
            import traceback
            _log("[HATA] acilis basarisiz:\n" + traceback.format_exc())

    threading.Thread(target=boot, daemon=True).start()

    def on_closing():
        if api._minimize_to_tray:
            window.hide()
            return False
        return True

    window.events.closing += on_closing

    tray_icon = None
    try:
        tray_icon = setup_tray(window, api)
    except Exception as e:
        _log("Tray error:", repr(e))

    # Sabit, kalici WebView2 profili: her acilista ayni yer, tema/gecmis korunur
    storage = os.path.join(os.environ.get('LOCALAPPDATA', APP_DIR), 'VideoDownloader')

    # pywebview varsayilan olarak target=_blank / window.open isteklerini
    # SISTEM TARAYICISINA gonderir. Giris penceresinde "Google ile devam et"
    # gibi butonlar popup actigi icin giris kullanicinin kendi tarayicisinda
    # aciliyor, cerezler uygulamaya hic donmuyor ve pencere oylece kaliyordu.
    try:
        webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = False
    except Exception:
        pass

    # Ustune: popup'lari ayni pencerede degil GERCEK popup olarak ac. Ayni
    # pencerede acilinca window.opener kayboluyor ve Google girisi sonucunu
    # geri gonderemiyordu. webview.start() oncesinde kurulmali: pywebview
    # isleyiciyi WebView2 hazir oldugunda baglar. Basarisiz olursa yukaridaki
    # "ayni pencerede ac" davranisi gecerli kalir.
    try:
        import popup_support
        if popup_support.install():
            _log("[giris] WebView2 popup destegi etkin")
    except Exception as e:
        _log("[giris] popup destegi kurulamadi:", repr(e))

    # Start with Edge WebView2 (built into Windows 10/11)
    try:
        webview.start(gui='edgechromium', debug=False,
                      private_mode=False, storage_path=storage)
    except Exception:
        webview.start(debug=False, private_mode=False, storage_path=storage)

    # Pencere kapandi: tray ikonunu kaldir, daemon thread'ler kendiliginden olur.
    # os._exit YOK - WebView2 duzgun kapanip profil kilidini birakir.
    if tray_icon:
        try:
            tray_icon.stop()
        except Exception:
            pass

if __name__ == '__main__':
    main()
