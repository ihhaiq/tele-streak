from __future__ import annotations

import logging

from aiohttp import web

logger = logging.getLogger(__name__)


class StoryMediaServer:
    """Serve short-lived story previews so Telegram Guest Mode can fetch them."""

    def __init__(self, *, adventures, public_base_url: str):
        self.adventures = adventures
        self.public_base_url = public_base_url.rstrip("/")
        self.enabled = bool(self.public_base_url)
        self._runner: web.AppRunner | None = None

    async def _media(self, request: web.Request) -> web.StreamResponse:
        token = request.match_info["token"]
        path = await self.adventures.story_preview_asset(token, thumbnail=False)
        if path is None:
            raise web.HTTPGone()
        response = web.FileResponse(path)
        response.headers["Cache-Control"] = "private, max-age=60"
        return response

    async def _thumbnail(self, request: web.Request) -> web.StreamResponse:
        token = request.match_info["token"]
        path = await self.adventures.story_preview_asset(token, thumbnail=True)
        if path is None:
            raise web.HTTPGone()
        response = web.FileResponse(path)
        response.headers["Cache-Control"] = "private, max-age=60"
        return response

    async def _health(self, request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "story_preview": True})

    async def start(self, host: str, port: int) -> None:
        if not self.enabled or self._runner is not None:
            return
        app = web.Application()
        app.router.add_get("/story/media/{token}", self._media)
        app.router.add_get("/story/thumb/{token}", self._thumbnail)
        app.router.add_get("/story/health", self._health)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, host=host, port=port)
        await site.start()
        logger.info("Story preview media server listening on %s:%s", host, port)

    async def close(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
