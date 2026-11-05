# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all

# ffmpeg BILEREK burada yok. "shared" build'in DLL'lerini datas ile eklersek
# PyInstaller onlari binaries'e tasiyip _internal koküne de kopyaliyor --
# 161 MB'lik dosyalar iki kere paketleniyordu. ffmpeg bir Python bagimliligi
# degil, harici arac; installer.iss onu {app}\ffmpeg altina koyuyor ve
# app.py'deki _find_ffmpeg orayi da ariyor.
datas = [('static', 'static')]
binaries = []
hiddenimports = ['flask', 'flask_cors', 'webview', 'webview.platforms.winforms',
                 'pystray', 'PIL', 'app', 'updater', 'popup_support',
                 'error_reporter']

# --- yt-dlp: exe'ye GOMULMEZ -------------------------------------------------
# collect_all('yt_dlp') 1047 modulu PYZ.pyz'ye derliyordu. PyInstaller'in
# FrozenImporter'i sys.meta_path'te sys.path'ten once geldigi icin, boyle
# paketlenince yt-dlp'yi guncellemenin TEK yolu exe'yi yeniden derlemekti.
# YouTube/TikTok ayda birkac kez bozdugu icin bu surdurulebilir degil.
#
# Cozum: yt_dlp'yi analizden cikar, kaynagini duz veri olarak 'runtime/'
# altina koy. updater.activate() calisma aninda once kullanicinin yazilabilir
# klasorune, yoksa buna bakar -- yani guncelleme derleme gerektirmez.
# yt_dlp'yi analizden TAMAMEN cikarmak ise yaramiyor: PyInstaller o zaman
# yt-dlp'nin ihtiyac duydugu modulleri de paketlemiyor (optparse yok diye
# acilis coktu) ve kendi hook'u calismadigi icin curl_cffi/certifi/brotli
# gibi bagimliliklar da dusuyor.
# Dogru yol: normal sekilde analiz ETTIR (boylece tum bagimliliklar toplanir),
# sadece yt_dlp'nin kendi modullerini PYZ'ye yazilmadan once ayikla (asagida).
tmp_ret = collect_all('yt_dlp')
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

# curl_cffi: TikTok/Instagram web cikarimi icin gereken impersonation destegi.
# yt-dlp hook'u bazen kacirabiliyor; eksik olunca TikTok "Unexpected response
# from webpage request" verip giris gerekiyormus gibi gorunuyordu.
_cc_ret = collect_all('curl_cffi')
datas += _cc_ret[0]
binaries += _cc_ret[1]
hiddenimports += _cc_ret[2]

# yt_dlp ve yt_dlp_ejs ayni sekilde: kaynak 'runtime/' altina duz veri.
# yt_dlp_ejs YouTube'un JS cozucu betikleri; yt-dlp bunlarin surumunu ve
# hash'ini dogrular. updater.ensure_ejs() onu yt-dlp'yle birlikte
# guncelleyebilsin diye PYZ'ye GIRMEMELI (FrozenImporter sys.path'ten once
# gelir, PYZ'deki kopya guncellenmis kopyayi golgeler).
import yt_dlp as _ytdlp_pkg
import yt_dlp_ejs as _ejs_pkg


def _ship_source(pkg, name):
    src = os.path.dirname(pkg.__file__)
    for _root, _dirs, _files in os.walk(src):
        _dirs[:] = [d for d in _dirs if d != '__pycache__']
        _rel = os.path.relpath(_root, src)
        _dest = os.path.join('runtime', name) if _rel == '.' else os.path.join('runtime', name, _rel)
        for _f in _files:
            if not _f.endswith('.pyc'):
                datas.append((os.path.join(_root, _f), _dest))


_ship_source(_ytdlp_pkg, 'yt_dlp')
_ship_source(_ejs_pkg, 'yt_dlp_ejs')


a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Kullanilmayan agir modulleri disarida birak: daha kucuk exe, daha hizli acilis
    # numpy + cryptography: ~36 MB, hicbiri kullanilmiyor.
    #   numpy  -> PIL'in opsiyonel entegrasyonu cekiyor; uygulama PIL'i yalnizca
    #             tepsi simgesi icin kullaniyor (Image.new + ImageDraw).
    #   cryptography -> site-packages'ta duran alakasiz paketlerden
    #             (azure-identity vb.) geliyor; yt-dlp onu hic import etmiyor.
    # Site-packages'a bunlari getiren bir paket kurulursa tekrar sismesin diye
    # burada acikca disarida tutuluyorlar.
    excludes=['tkinter', '_tkinter', 'unittest', 'pydoc', 'doctest', 'lib2to3',
              'xmlrpc', 'numpy', 'cryptography'],
    noarchive=False,
    optimize=0,
)
# yt_dlp'nin modullerini PYZ'ye YAZMA. Analiz sirasinda vardilar ki
# bagimliliklari (optparse, curl_cffi, certifi, brotli...) dogru toplansin;
# ama exe'nin icine gomulurlerse FrozenImporter sys.path'i gecersiz kilar ve
# yt-dlp bir daha guncellenemez. Kaynak kopya 'runtime/yt_dlp' olarak
# paketleniyor, updater.activate() oradan yukluyor.
_before = len(a.pure)
_RUNTIME_PKGS = ('yt_dlp', 'yt_dlp_ejs')
a.pure = [_m for _m in a.pure
          if not any(_m[0] == p or _m[0].startswith(p + '.') for p in _RUNTIME_PKGS)]
print('[spec] PYZ disi birakilan runtime modulu: %d' % (_before - len(a.pure)))

pyz = PYZ(a.pure)

# ONEDIR modu: onefile her acilista tum dosyalari temp'e acip Defender taramasi
# yuzunden 30-60sn donmaya sebep oluyordu. Onedir aninda acilir.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Video Downloader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
    # Yayinci/surum meta verisi: imzasiz exe'de SmartScreen penceresinin ve
    # Dosya > Ozellikler'in bos gorunmesini onler. Uyariyi kaldirmaz.
    version='version_info.txt',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Video Downloader',
)
