"""
Giris penceresinde gercek popup destegi (WebView2).

Sorun: "Google ile devam et" gibi sosyal giris butonlari window.open ile bir
popup acar. Popup'taki giris bitince sonuc, popup'i ACAN pencereye
window.opener.postMessage ile gonderilir; popup da window.close() ile kendini
kapatir.

pywebview bu istegi (NewWindowRequested) iki sekilde ele aliyor:
  * OPEN_EXTERNAL_LINKS_IN_BROWSER = True  -> sistem tarayicisinda acar.
    Giris kullanicinin kendi tarayicisinda biter, cerezler uygulamaya donmez.
  * OPEN_EXTERNAL_LINKS_IN_BROWSER = False -> AYNI pencerede acar.
    Acan sayfa kaybolur, window.opener null olur, postMessage gidecek yer
    kalmaz; giris yine tamamlanmaz.

Bu modul ucuncu yolu ekler: popup'i ayni WebView2 ortaminda (ayni cerez
deposu) yeni bir pencere olarak acar ve args.NewWindow'a baglar. WebView2
bu durumda opener iliskisini korur -- tarayicidaki popup davranisinin
aynisi.

Sadece Windows + EdgeChromium backend'inde calisir; baska her durumda
sessizce devre disi kalir ve pywebview'in kendi davranisi gecerli olur.
"""

import logging

logger = logging.getLogger("popup_support")

POPUP_TITLE = "Giriş"
POPUP_SIZE = (520, 720)

_installed = False


def _open_popup(edge, sender, args, winforms, webview2_cls, original):
    """NewWindowRequested'i gercek bir popup penceresiyle karsila.

    edge:   pywebview'in EdgeChrome nesnesi (popup'i isteyen pencere)
    sender: istegi yapan CoreWebView2
    args:   CoreWebView2NewWindowRequestedEventArgs
    """
    try:
        deferral = args.GetDeferral()
    except Exception:
        # Deferral alinamiyorsa (cok eski WebView2 runtime) eski davranis
        original(edge, sender, args)
        return

    completed = {"done": False}

    def complete():
        if not completed["done"]:
            completed["done"] = True
            try:
                deferral.Complete()
            except Exception:
                pass

    def fallback():
        # Ne olursa olsun kullaniciyi bos bir pencereyle birakma: popup
        # acilamadiysa en azindan adresi ayni pencerede ac.
        try:
            args.Handled = True
            edge.load_url(str(args.Uri))
        except Exception:
            pass
        complete()

    try:
        form = winforms.Form()
        form.Text = POPUP_TITLE
        form.Width, form.Height = POPUP_SIZE
        form.StartPosition = winforms.FormStartPosition.CenterParent
        try:
            # Giris penceresinin ustunde kalsin, arkada kaybolmasin
            form.Owner = edge.form
        except Exception:
            pass

        popup = webview2_cls()
        popup.Dock = winforms.DockStyle.Fill
        form.Controls.Add(popup)

        def on_ready(s, e):
            try:
                if not e.IsSuccess:
                    raise RuntimeError("popup WebView2 baslatilamadi")
                core = popup.CoreWebView2
                # Asil is burada: opener iliskisi bu atamayla kurulur.
                # NewWindow'a atanan CoreWebView2 henuz HICBIR yere gitmemis
                # olmali; EnsureCoreWebView2Async'i Source vermeden cagirdik.
                args.NewWindow = core
                args.Handled = True

                # Google girisi bitince popup window.close() cagirir
                core.WindowCloseRequested += lambda _s, _e: form.Close()
                # Popup'in kendi actigi popup'lar da ayni sekilde acilsin
                core.NewWindowRequested += lambda s2, a2: _open_popup(
                    edge, s2, a2, winforms, webview2_cls, original)
                # Sayfa basligini pencere basligina yansit
                core.DocumentTitleChanged += lambda s2, _e: _set_title(form, s2)
                complete()
            except Exception as exc:
                logger.warning("popup baglanamadi: %r", exc)
                try:
                    form.Close()
                except Exception:
                    pass
                fallback()

        popup.CoreWebView2InitializationCompleted += on_ready
        form.Show()
        # AYNI ortam: ayni cerez deposu, ayni oturum. Farkli ortam verilirse
        # WebView2 NewWindow atamasini reddeder.
        popup.EnsureCoreWebView2Async(sender.Environment)
    except Exception as exc:
        logger.warning("popup penceresi olusturulamadi: %r", exc)
        fallback()


def _set_title(form, core):
    try:
        title = str(core.DocumentTitle or "").strip()
        form.Text = title or POPUP_TITLE
    except Exception:
        pass


def install():
    """pywebview'in EdgeChromium popup isleyicisini degistir.

    webview.start() ONCESINDE cagrilmali. Basarisiz olursa False doner ve
    hicbir sey degismez.
    """
    global _installed
    if _installed:
        return True
    try:
        from webview.platforms import edgechromium as ec
    except Exception as exc:
        # Windows degil ya da WebView2 yok: pywebview kendi yolunu izlesin
        logger.info("popup destegi devre disi: %r", exc)
        return False

    original = getattr(ec.EdgeChrome, "on_new_window_request", None)
    if original is None:
        logger.warning("pywebview surumunde on_new_window_request yok")
        return False

    def on_new_window_request(self, sender, args):
        _open_popup(self, sender, args, ec.WinForms, ec.WebView2, original)

    ec.EdgeChrome.on_new_window_request = on_new_window_request
    _installed = True
    return True
