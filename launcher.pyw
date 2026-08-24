"""
Video Downloader - Desktop Launcher
Opens the app in a native desktop window (no browser needed).
Double-click 'Video Downloader.bat' to start.
"""

import sys
import os
import threading
import time
import socket

# Ensure we always run from the script's own directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))


def find_free_port():
    """Find an available TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]


def wait_for_server(port, timeout=10):
    """Block until the Flask server accepts connections."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.2):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.1)
    return False


def start_flask(port):
    """Start Flask in a daemon thread."""
    import logging
    logging.getLogger('werkzeug').setLevel(logging.ERROR)

    from app import app
    app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False, threaded=True)


def main():
    port = find_free_port()

    flask_thread = threading.Thread(target=start_flask, args=(port,), daemon=True)
    flask_thread.start()

    if not wait_for_server(port):
        # Should never happen, but fall back to browser just in case
        import webbrowser
        webbrowser.open(f'http://127.0.0.1:{port}')
        flask_thread.join()
        return

    try:
        import webview

        window = webview.create_window(
            title='Video Downloader',
            url=f'http://127.0.0.1:{port}',
            width=920,
            height=780,
            min_size=(640, 520),
            background_color='#0a0a0f',
            text_select=True,
            zoomable=True,
        )

        def on_closed():
            os._exit(0)

        window.events.closed += on_closed

        # Try Edge WebView2 first (best on Windows 10/11)
        try:
            webview.start(gui='edgechromium', debug=False)
        except Exception:
            webview.start(debug=False)

    except ImportError:
        # pywebview not installed — open browser as fallback
        import webbrowser
        webbrowser.open(f'http://127.0.0.1:{port}')
        flask_thread.join()

    except Exception as e:
        # Unknown error — try browser
        import webbrowser
        webbrowser.open(f'http://127.0.0.1:{port}')
        flask_thread.join()


if __name__ == '__main__':
    main()
