from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web

logger = logging.getLogger(__name__)

_KIND_TO_CODE = {"image": 0, "video5": 5, "video10": 10}
_CODE_TO_KIND = {value: key for key, value in _KIND_TO_CODE.items()}


@dataclass(frozen=True, slots=True)
class StoryShareToken:
    owner_id: int
    chat_id: int
    kind: str
    expires_at: int


class StoryShareSigner:
    def __init__(self, secret: str, ttl_seconds: int = 900):
        self._key = hashlib.sha256(secret.encode()).digest()
        self.ttl_seconds = max(60, min(int(ttl_seconds), 3600))

    def issue(
        self,
        owner_id: int,
        chat_id: int,
        kind: str,
        *,
        now: int | None = None,
    ) -> str:
        if kind not in _KIND_TO_CODE:
            raise ValueError("unsupported story kind")
        now = int(time.time() if now is None else now)
        payload = struct.pack(
            ">QqBI",
            int(owner_id),
            int(chat_id),
            _KIND_TO_CODE[kind],
            now + self.ttl_seconds,
        )
        signature = hmac.new(self._key, payload, hashlib.sha256).digest()[:10]
        return base64.urlsafe_b64encode(payload + signature).decode().rstrip("=")

    def parse(self, token: str, *, now: int | None = None) -> StoryShareToken | None:
        try:
            raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
            if len(raw) != struct.calcsize(">QqBI") + 10:
                return None
            payload, signature = raw[:-10], raw[-10:]
            expected = hmac.new(self._key, payload, hashlib.sha256).digest()[:10]
            if not hmac.compare_digest(signature, expected):
                return None
            owner_id, chat_id, kind_code, expires_at = struct.unpack(">QqBI", payload)
            kind = _CODE_TO_KIND.get(kind_code)
            if kind is None:
                return None
            now = int(time.time() if now is None else now)
            if expires_at < now:
                return None
            return StoryShareToken(owner_id, chat_id, kind, expires_at)
        except (ValueError, TypeError, struct.error):
            return None


def validate_telegram_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_seconds: int = 600,
    now: int | None = None,
) -> int | None:
    try:
        values = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
        received_hash = values.pop("hash")
        auth_date = int(values["auth_date"])
        user = json.loads(values["user"])
        user_id = int(user["id"])
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return None

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(values.items())
    )
    secret_key = hmac.new(
        b"WebAppData", bot_token.encode(), hashlib.sha256
    ).digest()
    expected_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(received_hash, expected_hash):
        return None

    now = int(time.time() if now is None else now)
    if auth_date > now + 30 or now - auth_date > max_age_seconds:
        return None
    return user_id


class StoryShareWeb:
    def __init__(
        self,
        *,
        bot_token: str,
        bot_username: str,
        public_base_url: str,
        adventures,
        share_dir: Path,
        ttl_seconds: int = 900,
        main_app_enabled: bool = True,
    ):
        self.bot_token = bot_token
        self.bot_username = bot_username.lstrip("@")
        self.public_base_url = public_base_url.rstrip("/")
        self.adventures = adventures
        self.share_dir = Path(share_dir)
        self.share_dir.mkdir(parents=True, exist_ok=True)
        self.signer = StoryShareSigner(bot_token, ttl_seconds)
        self.ttl_seconds = self.signer.ttl_seconds
        self.server_enabled = bool(self.public_base_url)
        self.enabled = bool(
            self.server_enabled and self.bot_username and main_app_enabled
        )
        self._runner: web.AppRunner | None = None

    def links(self, owner_id: int, chat_id: int) -> dict[str, str]:
        if not self.enabled:
            return {}
        result = {}
        for kind in ("image", "video5", "video10"):
            token = self.signer.issue(owner_id, chat_id, kind)
            result[kind] = (
                f"https://t.me/{self.bot_username}?startapp={token}&mode=compact"
            )
        return result

    def _media_path(self, token: str, kind: str) -> Path:
        suffix = ".png" if kind == "image" else ".mp4"
        return self.share_dir / f"{token}{suffix}"

    async def _app(self, request: web.Request) -> web.Response:
        return web.Response(
            text=_APP_HTML,
            content_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    async def _prepare(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except (json.JSONDecodeError, web.HTTPBadRequest):
            return web.json_response({"error": "طلب غير صالح."}, status=400)

        token_raw = str(body.get("token", ""))
        init_data = str(body.get("init_data", ""))
        token = self.signer.parse(token_raw)
        user_id = validate_telegram_init_data(
            init_data,
            self.bot_token,
            max_age_seconds=min(self.ttl_seconds, 900),
        )
        if token is None or user_id is None:
            return web.json_response(
                {"error": "رابط الستوري منتهي أو غير صالح."}, status=403
            )

        record = await self.adventures.repository.get_owner_streak(
            token.owner_id, token.chat_id
        )
        if record is None or user_id not in {
            token.owner_id,
            record.peer_user_id or record.chat_id,
        }:
            return web.json_response(
                {"error": "هاي الستوري خاصة بطرفي الستريك."}, status=403
            )
        if not record.is_enabled or record.current_streak < 1:
            return web.json_response(
                {"error": "كملوا أول يوم وفعلوا الستريك حتى تشاركونه."}, status=409
            )

        target = self._media_path(token_raw, token.kind)
        error = await self.adventures.prepare_story_share(
            record,
            token.owner_id,
            token.kind,
            token_raw,
            target,
            max_age_seconds=self.ttl_seconds,
        )
        if error:
            return web.json_response({"error": error}, status=429)

        media_url = (
            f"{self.public_base_url}/story/media/{token_raw}"
            + (".png" if token.kind == "image" else ".mp4")
        )
        return web.json_response(
            {
                "media_url": media_url,
                "caption": f"🔥 ستريك متتالي لـ {record.current_streak} يوم!",
            }
        )

    async def _media(self, request: web.Request) -> web.StreamResponse:
        filename = request.match_info["filename"]
        if "." not in filename:
            raise web.HTTPNotFound()
        token_raw, suffix = filename.rsplit(".", 1)
        token = self.signer.parse(token_raw)
        if token is None:
            raise web.HTTPGone()
        expected = "png" if token.kind == "image" else "mp4"
        if suffix != expected:
            raise web.HTTPNotFound()
        path = self._media_path(token_raw, token.kind)
        if not path.is_file():
            raise web.HTTPNotFound()
        response = web.FileResponse(path)
        response.headers["Cache-Control"] = "private, max-age=60"
        return response

    async def start(self, host: str, port: int) -> None:
        if not self.server_enabled or self._runner is not None:
            return
        app = web.Application(client_max_size=1024 * 1024)
        app.router.add_get("/story/app", self._app)
        app.router.add_post("/story/prepare", self._prepare)
        app.router.add_get("/story/media/{filename}", self._media)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, host=host, port=port)
        await site.start()
        logger.info("Story Mini App listening on %s:%s", host, port)

    async def close(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None


_APP_HTML = """<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
  <title>مشاركة الستريك</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    :root { color-scheme: light dark; }
    body { margin:0; font-family:system-ui,sans-serif; background:var(--tg-theme-bg-color,#111);
      color:var(--tg-theme-text-color,#fff); min-height:100vh; display:grid; place-items:center; }
    main { width:min(92vw,430px); text-align:center; padding:32px 18px; box-sizing:border-box; }
    h1 { margin:0 0 10px; font-size:25px; }
    p { opacity:.82; line-height:1.7; }
    button { width:100%; border:0; border-radius:14px; padding:14px; font-size:17px; font-weight:700;
      background:var(--tg-theme-button-color,#2ea6ff); color:var(--tg-theme-button-text-color,#fff); }
    button[hidden] { display:none; }
  </style>
</head>
<body>
<main>
  <h1>🔥 مشاركة الستريك</h1>
  <p id="status">Jake دا يجهز الستوري...</p>
  <button id="open" hidden>فتح لوحة الستوري</button>
</main>
<script>
(() => {
  const tg = window.Telegram?.WebApp;
  const status = document.getElementById("status");
  const button = document.getElementById("open");
  let prepared = null;

  function fail(message) {
    status.textContent = message || "تعذر تجهيز الستوري.";
    button.hidden = true;
  }

  function openStory() {
    if (!prepared || !tg) return;
    try {
      tg.shareToStory(prepared.media_url, {text: prepared.caption || ""});
      status.textContent = "إذا ما انفتحت اللوحة، اضغط الزر مرة ثانية.";
      button.hidden = false;
    } catch (_) {
      fail("نسخة Telegram عندك ما تدعم فتح محرر الستوري من هنا.");
    }
  }

  async function prepare() {
    if (!tg) return fail("افتح الرابط من داخل Telegram.");
    tg.ready();
    tg.expand();
    if (tg.isVersionAtLeast && !tg.isVersionAtLeast("7.8")) {
      return fail("حدّث Telegram حتى تشتغل مشاركة الستوري المباشرة.");
    }
    const params = new URLSearchParams(location.search);
    const token = tg.initDataUnsafe?.start_param || params.get("tgWebAppStartParam") || "";
    if (!token || !tg.initData) return fail("رابط المشاركة غير مكتمل.");

    try {
      const response = await fetch("/story/prepare", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({token, init_data: tg.initData})
      });
      const data = await response.json();
      if (!response.ok) return fail(data.error);
      prepared = data;
      button.hidden = false;
      button.onclick = openStory;
      status.textContent = "جاهزة ✨ راح أفتح لوحة Telegram للستوري.";
      openStory();
    } catch (_) {
      fail("تعذر الاتصال بالبوت هالمرة.");
    }
  }

  prepare();
})();
</script>
</body>
</html>
"""
