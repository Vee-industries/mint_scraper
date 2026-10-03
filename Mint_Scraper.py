import os
import sys
import threading
import logging
import webbrowser
from flask import Flask, request, send_from_directory, jsonify
import pystray
from pystray import MenuItem as item
from PIL import Image
import requests
import time
import subprocess
import shutil
import platform
import hmac
import functools

# =========================
# SETTINGS / CONSTANTS
# =========================
APP_NAME = "Mint Scraper"

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

LOGO_FILE = os.path.join(ASSETS_DIR, "mint_scraper_logo.png")
ICON_FILE = os.path.join(ASSETS_DIR, "mint_scraper.ico")

README_FILE = os.path.join(BASE_DIR, "README.md")
LICENSE_FILE = os.path.join(BASE_DIR, "LICENSE")

LOG_DIR = os.path.expanduser("~/.mint_scraper_logs")
LOG_FILE = os.path.join(LOG_DIR, "mint_scraper.log")

# Separate ports: API vs LLM
WEB_PORT = int(os.getenv("MINT_PORT", "5055"))   # Flask API port

# Search engines mapping used by your search_api.do_search
SEARCH_ENGINES = {
    "Web": "ddg",
    "Wikipedia": "wiki",
    "Brave": "brave",
}
DEFAULT_ENGINE = "Web"
engine_state = {"current": DEFAULT_ENGINE}

# =========================
# LOGGING
# =========================
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s"
)
logging.info("Mint Scraper started.")

# =========================
# API KEY AUTHENTICATION
# =========================
"""
We support two modes:

1) Preferred (if installed): Flask-HTTPAuth Bearer tokens
   - pip install Flask-HTTPAuth
   - Send: Authorization: Bearer <token>

2) Built-in fallback (no extra deps):
   - Accepts Authorization: Bearer <token> OR X-API-Key: <token> OR ?api_key=<token>
"""

def _parse_api_keys_from_env():
    """
    Accept either:
      MINT_API_KEYS="user1:tokA,user2:tokB"
    or
      MINT_API_KEYS="tokA,tokB"  (users will be auto-named user1,user2)
    """
    env = os.getenv("MINT_API_KEYS", "").strip()
    if not env:
        logging.warning("MINT_API_KEYS not set: authentication is off. The server only listens on 127.0.0.1.")
        return {}
    result = {}
    parts = [p.strip() for p in env.split(",") if p.strip()]
    auto_i = 1
    for p in parts:
        if ":" in p:
            user, tok = p.split(":", 1)
            result[user.strip()] = tok.strip()
        else:
            result[f"user{auto_i}"] = p
            auto_i += 1
    return result

API_KEYS = _parse_api_keys_from_env()  # {user: token}

# Try to use Flask-HTTPAuth if present
try:
    from flask_httpauth import HTTPTokenAuth
    _USE_HTTPAUTH = True
    auth = HTTPTokenAuth(scheme="Bearer")

    @auth.verify_token
    def verify_token(token: str):
        if not API_KEYS:
            return "local"
        # Constant-time comparison against all known tokens
        for user, tok in API_KEYS.items():
            if hmac.compare_digest(tok, token or ""):
                return user  # returning a truthy "user" marks auth success
        return None

    def require_api_key(decorated_fn):
        """No-op when HTTPAuth is available; use @auth.login_required instead."""
        return decorated_fn

except Exception:
    # Fallback: tiny built-in decorator (no dependency)
    _USE_HTTPAUTH = False
    auth = None

    def _extract_token_from_request(req: request) -> str:
        # 1) Authorization: Bearer <token>
        authz = req.headers.get("Authorization", "")
        if authz.lower().startswith("bearer "):
            return authz.split(" ", 1)[1].strip()
        # 2) X-API-Key header
        hdr = req.headers.get("X-API-Key")
        if hdr:
            return hdr.strip()
        # 3) Query param ?api_key=
        qp = req.args.get("api_key") or req.form.get("api_key")
        return (qp or "").strip()

    def _is_valid_token(token: str) -> bool:
        if not API_KEYS:
            return True
        for _, tok in API_KEYS.items():
            if hmac.compare_digest(tok, token or ""):
                return True
        return False

    def require_api_key(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            token = _extract_token_from_request(request)
            if not _is_valid_token(token):
                return jsonify({"error": "Unauthorized"}), 401
            return fn(*args, **kwargs)
        return wrapper

# =========================
# FLASK APP
# =========================
app = Flask(APP_NAME)

@app.route("/", methods=["GET"])
def root():
    """Return basic app status in JSON."""
    return jsonify({
        "app": APP_NAME,
        "status": "ok",
        "engine": engine_state["current"],
        "auth": ("httpauth" if _USE_HTTPAUTH else "builtin") if API_KEYS else "off (local only)",
        "endpoints": ["/search", "/engine (GET/POST)", "/health", "/readme", "/license", "/shutdown"]
    })

# ---------- SEARCH (Protected) ----------
if _USE_HTTPAUTH:
    @app.route("/search", methods=["GET", "POST"])
    @auth.login_required
    def search():
        """JSON-only search interface (requires Bearer token)."""
        query = request.form.get("query") if request.method == "POST" else (request.args.get("q") or "")
        logging.info(f"Search: {query}")
        try:
            answer, sources = agent_search(query)
            return jsonify({
                "answer": answer,
                "sources": sources,
                "engine": engine_state["current"],
                "user": getattr(auth, "current_user", lambda: None)()
            })
        except Exception as ex:
            logging.exception("Search error")
            return jsonify({"error": str(ex)}), 500
else:
    @app.route("/search", methods=["GET", "POST"])
    @require_api_key
    def search():
        """JSON-only search interface (requires API key)."""
        query = request.form.get("query") if request.method == "POST" else (request.args.get("q") or "")
        logging.info(f"Search: {query}")
        try:
            answer, sources = agent_search(query)
            return jsonify({
                "answer": answer,
                "sources": sources,
                "engine": engine_state["current"]
            })
        except Exception as ex:
            logging.exception("Search error")
            return jsonify({"error": str(ex)}), 500

# ---------- ENGINE ----------
@app.route("/engine", methods=["GET"])
def engine_get():
    """Public read of current engine and options."""
    return jsonify({"engine": engine_state["current"], "engines": list(SEARCH_ENGINES.keys())})

if _USE_HTTPAUTH:
    @app.route("/engine", methods=["POST"])
    @auth.login_required
    def engine_post():
        """Protected update of engine."""
        data = request.get_json(silent=True) or request.form
        name = (data.get("engine") or "").strip()
        if name not in SEARCH_ENGINES:
            return jsonify({"error": f"Invalid engine '{name}'. Valid: {list(SEARCH_ENGINES.keys())}"}), 400
        engine_state["current"] = name
        logging.info(f"Engine set: {name}")
        return jsonify({"ok": True, "engine": name})
else:
    @app.route("/engine", methods=["POST"])
    @require_api_key
    def engine_post():
        """Protected update of engine."""
        data = request.get_json(silent=True) or request.form
        name = (data.get("engine") or "").strip()
        if name not in SEARCH_ENGINES:
            return jsonify({"error": f"Invalid engine '{name}'. Valid: {list(SEARCH_ENGINES.keys())}"}), 400
        engine_state["current"] = name
        logging.info(f"Engine set: {name}")
        return jsonify({"ok": True, "engine": name})

# ---------- HEALTH ----------
@app.route("/health", methods=["GET"])
def health():
    """Health check."""
    return jsonify({"flask": "green", "engine": engine_state["current"],
                    "auth": "on" if API_KEYS else "off (local only)"})

# ---------- STATIC/FILES ----------
@app.route("/readme")
def readme():
    if os.path.isfile(README_FILE):
        return send_from_directory(os.path.dirname(README_FILE), os.path.basename(README_FILE))
    return jsonify({"error": f"README not found at {README_FILE}"}), 404

@app.route("/license")
def license():
    if os.path.isfile(LICENSE_FILE):
        return send_from_directory(os.path.dirname(LICENSE_FILE), os.path.basename(LICENSE_FILE))
    return jsonify({"error": f"LICENSE not found at {LICENSE_FILE}"}), 404

# ---------- SHUTDOWN (local only) ----------
@app.route("/shutdown")
def shutdown():
    """Shut down Flask (UI) cleanly. Binds to 127.0.0.1 only, so not exposed externally."""
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return "Server shutting down..."

# =========================
# AGENT + SCRAPER INTEGRATION
# =========================
def agent_search(query: str):
    """Search the web with the current engine and return (summary, results)."""
    from search_api import do_search
    results = do_search(query, SEARCH_ENGINES[engine_state["current"]])
    if results:
        return summarize_results(results), results
    return "No answer found.", []

def summarize_results(results):
    """
    Minimal summarizer using the top result snippet.
    Expected `results` structure:
      [{"title": "...", "link": "https://...", "snippet": "..."}, ...]
    """
    if not results:
        return "No results."
    top = results[0]
    snippet = (top.get("snippet") or "").strip()
    title = (top.get("title") or "Open").strip()
    link = top.get("link") or "#"
    return f"{snippet}\n\n{title} — {link}"

# =========================
# TRAY ICON / MENU
# =========================
def open_file(path):
    try:
        if platform.system() == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as ex:
        logging.error(f"Open file failed: {ex}")

def on_open(icon=None, item=None):
    webbrowser.open(f"http://127.0.0.1:{WEB_PORT}/")

def set_engine(name):
    def inner(icon=None, item=None):
        engine_state["current"] = name
        logging.info(f"Engine set: {name}")
    return inner

def on_quit(icon, item):
    logging.info("App shutdown requested by user.")
    icon.stop()
    shutdown_flask()
    sys.exit(0)

def shutdown_flask():
    try:
        requests.get(f"http://127.0.0.1:{WEB_PORT}/shutdown", timeout=2)
    except Exception:
        pass

def tray_menu():
    return (
        item("Open API Root", on_open),
        item("Switch Engine", (
            item("Web", set_engine("Web"),
                 checked=lambda i: engine_state["current"] == "Web", radio=True),
            item("Wikipedia", set_engine("Wikipedia"),
                 checked=lambda i: engine_state["current"] == "Wikipedia", radio=True),
            item("Brave", set_engine("Brave"),
                 checked=lambda i: engine_state["current"] == "Brave", radio=True),
        )),
        item("README", lambda icon, it: open_file(README_FILE)),
        item("License", lambda icon, it: open_file(LICENSE_FILE)),
        item("Quit", on_quit),
    )

def run_flask():
    app.run(host="127.0.0.1", port=WEB_PORT, debug=False, threaded=True, use_reloader=False)

def _default_icon():
    """Mint square with a white V, drawn at runtime."""
    from PIL import ImageDraw
    img = Image.new("RGBA", (64, 64), (62, 180, 137, 255))
    d = ImageDraw.Draw(img)
    d.line([(16, 16), (32, 50), (48, 16)], fill="white", width=7)
    return img

def run_tray():
    try:
        image = Image.open(ICON_FILE) if os.path.isfile(ICON_FILE) else _default_icon()
        menu = pystray.Menu(*tray_menu())
        icon = pystray.Icon(APP_NAME, image, APP_NAME, menu)
        icon.run()
    except Exception as ex:
        logging.error(f"System tray failed: {ex}")
        # Fallback: open API root and keep Flask alive
        on_open()
        while True:
            time.sleep(3600)

def main():
    if "--no-tray" in sys.argv:
        run_flask()
        return
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    time.sleep(1)
    run_tray()

if __name__ == "__main__":
    main()
