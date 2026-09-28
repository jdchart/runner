"""python -m runner [--browser] [--port N]

Starts the manager on 127.0.0.1 and shows it in a native window (pywebview),
or in the default browser with --browser. If a Runner is already serving on
that port, this just opens another window onto it.
"""

import argparse
import json
import threading
import urllib.request
import webbrowser

from werkzeug.serving import make_server

DEFAULT_PORT = 4747


def already_running(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1) as r:
            return json.load(r).get("app") == "runner"
    except (OSError, ValueError):
        return False


def main():
    ap = argparse.ArgumentParser(prog="runner")
    ap.add_argument("--browser", action="store_true", help="use the default browser, not a window")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args()
    url = f"http://127.0.0.1:{args.port}/"

    server = None
    if not already_running(args.port):
        from .server import app
        server = make_server("127.0.0.1", args.port, app, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()

    if not args.browser:
        try:
            import webview
        except ImportError:
            print("pywebview not installed; opening in the browser instead")
        else:
            _name_the_app()
            webview.create_window("Runner", url, width=1180, height=820, min_size=(640, 480))
            webview.start()
            return            # closing the window quits Runner; projects keep running

    webbrowser.open(url)
    if server:
        print(f"Runner on {url}  (Ctrl-C to quit; projects keep running)")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass


def _name_the_app():
    """Show 'Runner' rather than 'Python' in the menu bar, and use our icon in the Dock."""
    try:
        from pathlib import Path
        from Foundation import NSBundle
        info = NSBundle.mainBundle().localizedInfoDictionary() or NSBundle.mainBundle().infoDictionary()
        info["CFBundleName"] = "Runner"
        icon = Path(__file__).resolve().parent.parent / "Runner.app/Contents/Resources/icon.png"
        if icon.is_file():
            from AppKit import NSApplication, NSImage
            NSApplication.sharedApplication().setApplicationIconImage_(
                NSImage.alloc().initWithContentsOfFile_(str(icon)))
    except Exception:
        pass


if __name__ == "__main__":
    main()
