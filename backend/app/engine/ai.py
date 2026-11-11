"""AI providers for the comparison engine (any OpenAI-compatible chat API).

Keys are only ever read from server environment variables; they are never stored in the
database or sent to the browser. Each company picks a provider in Company settings; a
second, stronger provider can be chosen for reading scans (useful for dense Arabic print).

The AI has three jobs, none of which can make the comparison skip content:
  read      transcribe scanned text tile by tile (optional; replaces OCR text, keeps OCR positions)
  review    look at the two screenshots of each finding and say whether it is real or OCR noise
  science   pharmacist-style review of the approved text, including English vs Arabic consistency
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

log = logging.getLogger("comproof.ai")

MAX_IMG_BYTES = 3_800_000          # stay under the 4 MB base64 image limit most providers apply


@dataclass(frozen=True)
class Provider:
    name: str
    label: str
    base_url: str
    key_env: str
    vision_model: str
    text_model: str
    json_mode: bool = True          # send response_format={"type": "json_object"}

    @property
    def key(self) -> str | None:
        return os.environ.get(self.key_env) or None


def _env(name: str, default: str) -> str:
    return (os.environ.get(name) or default).strip()


def providers() -> dict[str, Provider]:
    """Built-in providers. Base URLs and models can be changed with environment variables
    without a new release, because providers rename models often."""
    p = [
        Provider("qwen", "Qwen (Alibaba Cloud Model Studio)",
                 _env("QWEN_BASE_URL", os.environ.get("AI_BASE_URL") or "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
                 "QWEN_API_KEY" if os.environ.get("QWEN_API_KEY") else "AI_API_KEY",
                 _env("QWEN_VISION_MODEL", "qwen-vl-plus"), _env("QWEN_TEXT_MODEL", "qwen-plus")),
        Provider("groq", "Groq",
                 _env("GROQ_BASE_URL", "https://api.groq.com/openai/v1"), "GROQ_API_KEY",
                 _env("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct"),
                 _env("GROQ_TEXT_MODEL", "openai/gpt-oss-120b")),
        Provider("anthropic", "Claude (Anthropic)",
                 _env("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1"), "ANTHROPIC_API_KEY",
                 _env("ANTHROPIC_VISION_MODEL", "claude-sonnet-5-5"), _env("ANTHROPIC_TEXT_MODEL", "claude-haiku-5-5"),
                 json_mode=False),
        Provider("gemini", "Gemini (Google)",
                 _env("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"), "GEMINI_API_KEY",
                 _env("GEMINI_VISION_MODEL", "gemini-2.5-flash"), _env("GEMINI_TEXT_MODEL", "gemini-2.5-flash")),
        Provider("custom", os.environ.get("CUSTOM_AI_LABEL", "Custom OpenAI-compatible"),
                 _env("CUSTOM_AI_BASE_URL", "http://localhost:1/v1"), "CUSTOM_AI_API_KEY",
                 _env("CUSTOM_AI_VISION_MODEL", "vision"), _env("CUSTOM_AI_TEXT_MODEL", "text")),
    ]
    return {x.name: x for x in p}


def available() -> list[dict]:
    return [{"name": p.name, "label": p.label, "vision_model": p.vision_model, "text_model": p.text_model}
            for p in providers().values() if p.key]


def pick(name: str | None) -> Provider | None:
    ps = providers()
    if name and name in ps and ps[name].key:
        return ps[name]
    for p in ps.values():           # first configured provider
        if p.key:
            return p
    return None


def status(features: dict | None) -> dict:
    """Shown in the session payload: which AI functions this company can use."""
    from ..defaults import effective_features
    f = effective_features(features)
    on = bool(available())
    return {"configured": on, "review": on and f.get("ai_review", True), "read": on and f.get("ai_reading", False),
            "science": on and f.get("ai_science", True)}


class AIUnavailable(Exception):
    pass


class AIConfigError(AIUnavailable):
    """The provider refused the request itself (wrong model name, bad key, no access). Retrying cannot help,
    so a run stops calling this provider after the first one."""


def _http_error_text(provider: "Provider", model: str, code: int, raw: bytes) -> str:
    msg = ""
    try:
        err = json.loads(raw.decode("utf-8", "replace"))
        e = err.get("error", err) if isinstance(err, dict) else {}
        msg = (e.get("message") if isinstance(e, dict) else str(e)) or ""
    except ValueError:
        msg = raw[:200].decode("utf-8", "replace")
    low = msg.lower()
    if code == 404 or "model" in low and ("not exist" in low or "not found" in low or "does not exist" in low):
        env = provider.name.upper() if provider.name != "custom" else "CUSTOM_AI"
        return (f"{provider.label} has no model named “{model}” for this API key and region (HTTP {code}: {msg.strip()}). "
                f"Set {env}_VISION_MODEL / {env}_TEXT_MODEL on the server to a model your account can use.")
    if code in (401, 403):
        return f"{provider.label} refused the API key (HTTP {code}: {msg.strip()}). Check the key and its region."
    return f"{provider.label} returned HTTP {code}: {msg.strip()}"


def img_data_url(img) -> str:
    q = 90
    while True:
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=q)
        if buf.tell() <= MAX_IMG_BYTES or q < 40:
            return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
        q -= 12


def _parse_json(s: str) -> dict:
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", (s or "").strip(), flags=re.M)
    m = re.search(r"\{.*\}", s, re.S)
    return json.loads(m.group(0) if m else s)


def chat(provider: Provider, model: str, messages: list, max_tokens: int = 1200, timeout: int = 120) -> dict:
    """One JSON-returning chat call with retries on rate limits and server errors."""
    if not provider.key:
        raise AIUnavailable(f"{provider.label} is not configured on the server")
    body = {"model": model, "messages": messages, "temperature": 0, "max_tokens": max_tokens}
    if provider.json_mode:
        body["response_format"] = {"type": "json_object"}
    data = json.dumps(body).encode()
    last = ""
    for attempt in range(5):
        req = urllib.request.Request(provider.base_url.rstrip("/") + "/chat/completions", data=data, method="POST",
                                     headers={"Authorization": f"Bearer {provider.key}", "Content-Type": "application/json",
                                              "x-api-key": provider.key, "anthropic-version": "2023-06-01"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                out = json.loads(resp.read())
            content = out["choices"][0]["message"].get("content") or ""
            if isinstance(content, list):          # some providers return content parts
                content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
            parsed = _parse_json(content)
            return {"model": out.get("model") or model, "data": parsed, "usage": out.get("usage") or {}}
        except urllib.error.HTTPError as e:
            last = _http_error_text(provider, model, e.code, e.read()[:2000])
            if e.code in (400, 401, 403, 404, 422):
                raise AIConfigError(last)
            if e.code in (408, 409, 429, 500, 502, 503, 504, 529):
                wait = e.headers.get("retry-after")
                time.sleep(min(30.0, float(wait) if wait and wait.replace('.', '', 1).isdigit() else 2 ** attempt * 2))
                continue
            break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = str(e)
            time.sleep(2 ** attempt)
        except (ValueError, KeyError, IndexError) as e:
            last = f"Unreadable answer: {e}"
            if attempt >= 1:
                break
    raise AIUnavailable(last or "no answer")


# ------------------------------------------------------------------ read
READ_PROMPT = """You are transcribing a pharmaceutical packaging text image for a regulatory comparison.
Transcribe EVERY line of text exactly as printed, top to bottom{rtl}.
Rules: do not correct spelling, grammar, punctuation, spacing or numbers - typos must stay typos.
Keep digits exactly as printed (Western 0-9 or Arabic-Indic ٠-٩). Keep bullets as "•".
Ignore stamps, handwriting and signatures. Do not add anything that is not printed.
Return JSON: {{"lines": ["first line", "second line", ...]}}"""


def read_tile(provider: Provider, img, lang: str) -> tuple[str, list[str]]:
    rtl = " (the text is Arabic, right to left; give each line in normal Arabic reading order)" if lang == "ara" else ""
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": READ_PROMPT.format(rtl=rtl)},
        {"type": "image_url", "image_url": {"url": img_data_url(img)}}]}]
    out = chat(provider, provider.vision_model, msgs, max_tokens=3000)
    lines = out["data"].get("lines") or []
    return out["model"], [str(x) for x in lines if str(x).strip()]


# ------------------------------------------------------------------ review
REVIEW_PROMPT = """You are a pharmaceutical QA reviewer comparing an APPROVED packaging text (image 1)
with the NEW artwork or printed sample (image 2). A text-recognition engine flagged a possible difference ({lang}).
Its readings are often WRONG on scans (for example ت read instead of ن, "!" instead of "l", "S" instead of "5",
a lost decimal point, or a line taken from the wrong column):
  engine read approved: "{ref}"
  engine read new:      "{des}"
Do not trust these readings. Look only at the images:
1. Find the words in the highlighted area of image 1 and copy them exactly as printed into "approved_reads".
2. Find the corresponding words in image 2 and copy them exactly as printed into "design_reads".
3. Compare YOUR two transcriptions, not the engine's. If they say the same thing, the verdict is "ocr_noise".
Ignore fonts, bold/italic, colours, line breaks, layout, stamps, signatures and headers/footers.
Judge wording, numbers, punctuation and spacing only. Do not judge which version is medically better:
any real change from the approved text is a "real_difference", even a correction.
Return JSON: {{"verdict": "real_difference" | "ocr_noise" | "unclear",
"approved_reads": "...", "design_reads": "...",
"impact": "none" | "minor" | "major" | "critical",
"explanation": "one sentence in plain English describing what is printed differently"}}"""


def review(provider: Provider, ref_img, des_img, ref_txt: str, des_txt: str, lang: str) -> dict:
    content = [{"type": "text", "text": REVIEW_PROMPT.format(
        ref=ref_txt[:600], des=des_txt[:600], lang="Arabic" if lang == "ara" else "English")}]
    for im in (ref_img, des_img):
        if im is not None:
            content.append({"type": "image_url", "image_url": {"url": img_data_url(im)}})
    out = chat(provider, provider.vision_model, [{"role": "user", "content": content}], max_tokens=500)
    d = out["data"]
    d["model"] = out["model"]
    return d


# ------------------------------------------------------------------ science
SCIENCE_PROMPT = """You are a senior regulatory pharmacist auditing an APPROVED packaging text ({kind}) before it is
used as the master for artwork checks. The text comes from OCR of a scan and contains reading errors (wrong letters, lost decimal points, broken
words, odd bullet symbols, garbled fragments). Report a problem ONLY if it would still be a problem in a perfect
reading of the printed leaflet. Never report garbled or misread characters, bullet or formatting style, or layout,
and never recommend moving content between sections.
Check:
1. Strengths against composition, dose and titration logic, maximum dose, units, frequency.
2. Dosage-form wording used consistently (e.g. film vs tablet).
3. Contraindications vs warnings vs interactions consistency; section cross-references.
4. Pharmacokinetic values, ATC code format, storage conditions.
5. Between languages: same meaning (dose, timing with food, warnings), drug names transliterated or
   translated correctly, missing words in translated headings, numbers identical in every language.
Report only real problems. Quote the exact text.
Return JSON: {{"issues": [{{"severity": "critical|major|minor", "language": "en|fr|ar|both", "section": "...",
"quote": "short exact text", "problem": "...", "suggestion": "..."}}]}}
("language" = the language of the quoted text; "both" when the problem spans languages.)

{texts}"""

SCIENCE_HEADERS = {"eng": ("ENGLISH TEXT", 60000), "fra": ("FRENCH TEXT", 60000), "ara": ("ARABIC TEXT", 30000)}


def science(provider: Provider, texts: dict[str, str], kind: str) -> tuple[str, list]:
    parts = [f"{SCIENCE_HEADERS[lg][0]}:\n{(texts.get(lg) or '').strip()[:SCIENCE_HEADERS[lg][1]]}"
             for lg in ("eng", "fra", "ara") if (texts.get(lg) or "").strip()]
    msg = SCIENCE_PROMPT.format(kind=kind, texts="\n\n".join(parts) or "TEXT:\n(empty)")
    out = chat(provider, provider.text_model, [{"role": "user", "content": msg}], max_tokens=4000, timeout=240)
    return out["model"], out["data"].get("issues") or []


# ------------------------------------------------------------------ connection test (Settings > Engine)
def test(provider: Provider) -> list[dict]:
    """One tiny call per model so an administrator sees at once whether the key, region and model names work."""
    from PIL import Image
    out = []
    img = Image.new("RGB", (64, 24), "white")
    for role, model, content in (
            ("text", provider.text_model, 'Reply with the JSON {"ok": true}.'),
            ("vision", provider.vision_model, [{"type": "text", "text": 'Reply with the JSON {"ok": true}.'},
                                               {"type": "image_url", "image_url": {"url": img_data_url(img)}}])):
        t0 = time.time()
        try:
            r = chat(provider, model, [{"role": "user", "content": content}], max_tokens=20, timeout=40)
            out.append({"role": role, "model": r["model"], "ok": True, "ms": int((time.time() - t0) * 1000)})
        except AIUnavailable as e:
            out.append({"role": role, "model": model, "ok": False, "error": str(e)})
    return out
