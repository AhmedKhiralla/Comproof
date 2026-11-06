"""AI configuration errors are reported once, in plain words, and stop further calls."""
from __future__ import annotations

import http.server
import json
import threading

from app.engine import ai


def _server(code: int, body: dict):
    calls = []

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            calls.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            out = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

    httpd = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, calls


def test_unknown_model_is_a_config_error_with_a_clear_message(monkeypatch):
    httpd, calls = _server(404, {"error": {"message": "Model not exist.", "code": "model_not_found"}})
    monkeypatch.setenv("QWEN_API_KEY", "k")
    monkeypatch.setenv("QWEN_BASE_URL", f"http://127.0.0.1:{httpd.server_port}")
    monkeypatch.setenv("QWEN_VISION_MODEL", "qwen-vl-nope")
    p = ai.pick("qwen")
    try:
        ai.chat(p, p.vision_model, [{"role": "user", "content": "hi"}])
        raise AssertionError("expected an error")
    except ai.AIConfigError as e:
        msg = str(e)
    assert len(calls) == 1                       # no retries for a refused request
    assert "qwen-vl-nope" in msg and "QWEN_VISION_MODEL" in msg and "b'" not in msg
    results = ai.test(p)
    assert [r["ok"] for r in results] == [False, False] and results[1]["role"] == "vision"
    httpd.shutdown()


def test_pdf_report_never_prints_arabic_as_boxes(tmp_path):
    import subprocess
    from app.engine import exports
    f = {"id": "C1", "step": 2, "lang": "ara", "kind": "changed", "severity": "major",
         "title": "Wording changed — ما هو الدواء وما هو يستخدم", "ref_text": "يخزن في درجة حرارة لا تتجاوز ٣٠",
         "des_text": "يخزن في درجة حرارة لا تتجاوز ٢٥", "section": "PIL 5 · كيفية التخزين", "category": "Storage",
         "where_ref": "", "where_des": "", "explanation": "Approved reads “٣٠”, design reads “٢٥”.", "action": "Fix it.",
         "note": "", "ai": None}
    res = {"engine_version": "2.0.0", "findings": [f], "approved": {"pages": 1}, "design": {"pages": 1}}
    out = tmp_path / "r.pdf"
    exports.pdf(res, {}, str(tmp_path), str(out), {"Comparison": "CP-1", "Product": "نركاردو"}, [])
    text = subprocess.run(["pdftotext", str(out), "-"], capture_output=True, text=True).stdout
    assert "Comproof" in text and "■" not in text and "Leaflet Audit" not in text
