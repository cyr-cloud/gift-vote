# -*- coding: utf-8 -*-
"""칭찬 뽑기판 로컬 서버.

이 폴더에서 실행하면 브라우저가 열리고, 과정별 상태가 courses/ 안에
과정이름.json 으로 저장됩니다. 다음 수업 때 다시 실행하면 그대로 이어집니다.

    python server.py

courses/ 에 아래처럼 json 을 직접 만들어 두면 그 과정이 목록에 바로 뜹니다.

    {"name": "9월 파이썬 기초", "students": ["홍길동", "김철수"],
     "teams": [["1팀", 4], ["2팀", 4]]}
"""
import json
import os
import re
import sys
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

HERE = os.path.dirname(os.path.abspath(__file__))
COURSES = os.environ.get("COURSES_DIR") or os.path.join(HERE, "courses")
PORT = int(os.environ.get("PORT", "8765"))

BAD_SLUG = re.compile(r'[\\/:*?"<>|]')


def safe_slug(slug):
    """폴더를 벗어나거나 파일명에 못 쓰는 글자가 섞인 요청을 막는다."""
    slug = unquote(slug or "").strip()
    if not slug or len(slug) > 80:
        return None
    if slug in (".", "..") or BAD_SLUG.search(slug) or "\0" in slug:
        return None
    return slug


def course_path(slug):
    return os.path.join(COURSES, slug + ".json")


def read_course(slug):
    try:
        with open(course_path(slug), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def list_courses():
    out = []
    if not os.path.isdir(COURSES):
        return out
    for fn in sorted(os.listdir(COURSES)):
        if not fn.endswith(".json"):
            continue
        slug = fn[:-5]
        data = read_course(slug) or {}
        players = []
        if isinstance(data.get("solo"), dict):
            players = data["solo"].get("players") or []
        elif isinstance(data.get("students"), list):
            players = data["students"]
        out.append({
            "slug": slug,
            "name": data.get("name") or slug,
            "count": len(players),
            "updated": data.get("savedAt") or "",
        })
    return out


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=HERE, **kw)

    def guess_type(self, path):
        ctype = super().guess_type(path)
        if ctype.startswith(("text/", "application/javascript", "application/json")):
            if "charset" not in ctype:
                ctype += "; charset=utf-8"
        return ctype

    def log_message(self, fmt, *args):
        if self.command in ("PUT", "DELETE"):
            sys.stdout.write("  · %s %s\n" % (self.command, unquote(self.path)))
            sys.stdout.flush()

    def _send(self, code, body=b""):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Ppobgi-Store", "1")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _api_slug(self):
        """/api/courses/<slug> 에서 slug 만 뽑아낸다. 목록 요청이면 ''."""
        path = self.path.split("?")[0]
        if path in ("/api/courses", "/api/courses/"):
            return ""
        if path.startswith("/api/courses/"):
            return path[len("/api/courses/"):]
        return None

    def do_GET(self):
        raw = self._api_slug()
        if raw is None:
            super().do_GET()
            return
        if raw == "":
            self._json(200, list_courses())
            return
        slug = safe_slug(raw)
        if not slug:
            self._json(400, {"error": "bad slug"})
            return
        data = read_course(slug)
        if data is None:
            self._json(404, {"error": "not found"})
            return
        self._json(200, data)

    def do_PUT(self):
        raw = self._api_slug()
        slug = safe_slug(raw) if raw else None
        if not slug:
            self._json(400, {"error": "bad slug"})
            return
        # 화면이 읽어간 뒤로 파일이 바뀌었으면(손으로 고쳤거나 다른 창에서 저장) 덮어쓰지 않는다.
        base = self.headers.get("X-Base-Stamp")
        existing = read_course(slug)
        if existing is not None:
            cur = existing.get("savedAt") or ""
            if (base is None and cur) or (base is not None and base != cur):
                self._json(409, {"error": "stale", "savedAt": cur})
                return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            obj = json.loads(self.rfile.read(n).decode("utf-8"))
            os.makedirs(COURSES, exist_ok=True)
            tmp = course_path(slug) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False, indent=2)
            os.replace(tmp, course_path(slug))
            self._json(200, {"ok": True, "slug": slug})
        except Exception as e:
            self._json(400, {"error": str(e)})

    def do_DELETE(self):
        raw = self._api_slug()
        slug = safe_slug(raw) if raw else None
        if not slug:
            self._json(400, {"error": "bad slug"})
            return
        try:
            os.remove(course_path(slug))
        except FileNotFoundError:
            pass
        except Exception as e:
            self._json(400, {"error": str(e)})
            return
        self._json(200, {"ok": True})


def main():
    url = "http://localhost:%d/index.html" % PORT
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError as e:
        print("포트 %d 를 쓸 수 없어요 (%s)." % (PORT, e))
        print("다른 포트로 열려면:  set PORT=8790 && python server.py")
        return
    os.makedirs(COURSES, exist_ok=True)
    found = list_courses()
    print("칭찬 뽑기판이 켜졌습니다.")
    print("  주소   : " + url)
    print("  저장   : " + COURSES)
    if found:
        print("  과정   : " + ", ".join("%s(%d명)" % (c["name"], c["count"]) for c in found))
    print("  끄기   : 이 창에서 Ctrl+C")
    if os.environ.get("NO_OPEN") != "1":
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n종료했습니다. courses/ 안의 json 은 그대로 남아 있어요.")
        srv.server_close()


if __name__ == "__main__":
    main()
