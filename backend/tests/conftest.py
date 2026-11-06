"""End-to-end test harness: a fresh database and a real uvicorn server.

Set TEST_DATABASE_ADMIN_URL to a PostgreSQL URL with rights to create databases,
for example postgresql://postgres@127.0.0.1:5432/postgres
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
ADMIN_URL = os.environ.get("TEST_DATABASE_ADMIN_URL", "postgresql://postgres@127.0.0.1:5433/postgres")
TEST_DB = "comproof_e2e"
PLATFORM_EMAIL = "owner@comp11labs.test"
PLATFORM_PASSWORD = "Initial#Pass2026"


def _db_url(name: str) -> str:
    base, _, _ = ADMIN_URL.rpartition("/")
    return f"{base}/{name}"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Client:
    """Minimal browser-like client with its own cookie jar."""

    def __init__(self, base: str):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def call(self, method: str, path: str, body=None, csrf: bool = True, raw: bool = False):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if csrf:
            req.add_header("X-Requested-With", "comproof")
        try:
            with self.opener.open(req) as resp:
                content = resp.read()
                return resp.status, (content if raw else json.loads(content or b"{}")), resp.headers
        except urllib.error.HTTPError as e:
            content = e.read()
            return e.code, (content if raw else json.loads(content or b"{}")), e.headers

    def get(self, path, **kw):
        return self.call("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.call("POST", path, body if body is not None else {}, **kw)

    def patch(self, path, body, **kw):
        return self.call("PATCH", path, body, **kw)

    def put(self, path, body, **kw):
        return self.call("PUT", path, body, **kw)

    def upload(self, path: str, filename: str, data: bytes):
        import urllib.parse
        req = urllib.request.Request(self.base + "/api/files?filename=" + urllib.parse.quote(filename), data=data, method="POST")
        req.add_header("Content-Type", "application/octet-stream")
        req.add_header("X-Requested-With", "comproof")
        try:
            with self.opener.open(req) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def login(self, email: str, password: str):
        return self.post("/api/auth/login", {"email": email, "password": password})


@pytest.fixture(scope="session")
def db_url():
    import psycopg
    conn = psycopg.connect(ADMIN_URL, autocommit=True)
    conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
    conn.execute(f'CREATE DATABASE "{TEST_DB}"')
    conn.close()
    return _db_url(TEST_DB)


class FakeAI:
    """Stands in for an OpenAI-compatible vision/chat API: answers reading, review and science prompts."""

    def __init__(self):
        import http.server
        import threading
        self.requests: list[dict] = []
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
                out = json.dumps(fake.reply(body)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @staticmethod
    def reply(body):
        text = json.dumps(body["messages"])
        if "senior regulatory pharmacist" in text:
            content = {"issues": [{"severity": "major", "language": "en", "section": "4.2",
                                   "quote": "Take one tablet daily", "problem": "Dosage form says tablet for a film.",
                                   "suggestion": "Use film."}]}
        elif "Transcribe EVERY line" in text:
            content = {"lines": []}
        else:
            content = {"verdict": "real_difference", "approved_reads": "a", "design_reads": "b",
                       "impact": "major", "explanation": "The wording differs."}
        return {"model": body["model"], "choices": [{"message": {"role": "assistant", "content": json.dumps(content)}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20}}


@pytest.fixture(scope="session")
def fake_ai():
    f = FakeAI()
    yield f
    f.httpd.shutdown()


@pytest.fixture(scope="session")
def server(db_url, fake_ai):
    port = _free_port()
    env = dict(os.environ, DATABASE_URL=db_url, COOKIE_SECURE="false",
               QWEN_API_KEY="test-key", QWEN_BASE_URL=fake_ai.url, DATA_DIR=str(BACKEND / "tests" / ".data"),
               PLATFORM_ADMIN_EMAIL=PLATFORM_EMAIL, PLATFORM_ADMIN_PASSWORD=PLATFORM_PASSWORD,
               FRONTEND_DIST=str(BACKEND / "tests" / "no-frontend"), LOG_LEVEL="WARNING")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port),
                             "--host", "127.0.0.1"], cwd=BACKEND, env=env)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(base + "/api/health", timeout=1)
            break
        except Exception:
            if proc.poll() is not None:
                raise RuntimeError("Server exited during start-up")
            time.sleep(0.1)
    else:
        proc.kill()
        raise RuntimeError("Server did not start")
    yield base
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture
def client(server):
    return Client(server)


@pytest.fixture(scope="session")
def platform(server):
    """A signed-in platform administrator who has already changed the first password."""
    c = Client(server)
    status, body, _ = c.login(PLATFORM_EMAIL, PLATFORM_PASSWORD)
    assert status == 200, body
    status, body, _ = c.post("/api/auth/change-password",
                             {"current_password": PLATFORM_PASSWORD, "new_password": "Owner#Secure2026"})
    assert status == 200, body
    return c


def sign_in_first_time(server: str, email: str, temp: str, new_password: str) -> Client:
    c = Client(server)
    status, body, _ = c.login(email, temp)
    assert status == 200, body
    status, body, _ = c.post("/api/auth/change-password", {"current_password": temp, "new_password": new_password})
    assert status == 200, body
    return c


@pytest.fixture(scope="session")
def two_companies(server, platform):
    out = {}
    for code, email in (("ACME", "admin@acme.test"), ("NILE", "admin@nile.test")):
        status, body, _ = platform.post("/api/platform/tenants", {
            "code": code, "name": f"{code} Pharma", 
            "admin": {"email": email, "full_name": f"{code} Admin"}})
        assert status == 200, body
        admin = sign_in_first_time(server, email, body["temporary_password"], f"{code}#Admin2026x")
        status, site, _ = admin.post("/api/sites", {"code": "CAI", "name": f"{code} Cairo plant"})
        assert status == 200, site
        out[code] = {"tenant": body["tenant"], "admin": admin, "site": site}
    return out


