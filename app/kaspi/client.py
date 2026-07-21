import httpx


class KaspiError(Exception):
    """Ошибка терминала Kaspi: HTTP-ошибка или statusCode != 0."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"[{status_code}] {message}")


class KaspiClient:
    """Async HTTP-клиент терминала Smart POS. Только ввод-вывод.

    verify=False: сертификат терминала выписан на *.kaspipos.kz, а мы ходим по IP —
    проверка по имени невозможна (документация это допускает, уровень защиты тот же).
    """

    def __init__(self, base_url: str, *, access_token: str | None = None,
                 terminal_id: str | None = None, transport: httpx.BaseTransport | None = None,
                 timeout: float = 15.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._access_token = access_token
        self._terminal_id = terminal_id
        self._transport = transport
        self._timeout = timeout

    async def _get(self, path: str, *, params: dict | None = None,
                   headers: dict | None = None) -> dict:
        async with httpx.AsyncClient(base_url=self._base_url, verify=False,
                                     transport=self._transport, timeout=self._timeout) as c:
            resp = await c.get(path, params=params or {}, headers=headers or {})
        if resp.status_code >= 400:
            raise KaspiError(resp.status_code, resp.text or f"HTTP {resp.status_code}")
        body = resp.json()
        if body.get("statusCode", 0) != 0:
            msg = body.get("errorText") or (body.get("data") or {}).get("message") or "Ошибка терминала"
            raise KaspiError(body.get("statusCode", -1), msg)
        return body.get("data", {})

    def _auth_headers(self) -> dict:
        return {"accesstoken": self._access_token} if self._access_token else {}

    async def register(self, name: str) -> dict:
        return await self._get("/v2/register", params={"name": name})

    async def revoke(self, name: str, refresh_token: str) -> dict:
        return await self._get("/v2/revoke", params={"name": name, "refreshToken": refresh_token})

    async def deviceinfo(self) -> dict:
        return await self._get("/v2/deviceinfo", headers=self._auth_headers())

    async def payment(self, amount: int, *, owncheque: bool = False) -> dict:
        return await self._get(
            "/v2/payment",
            params={"amount": amount, "owncheque": str(owncheque).lower()},
            headers=self._auth_headers(),
        )

    async def status(self, process_id: str) -> dict:
        headers = self._auth_headers()
        if self._terminal_id:
            headers["terminalId"] = self._terminal_id
        return await self._get("/v2/status", params={"processId": process_id}, headers=headers)

    async def actualize(self, process_id: str) -> dict:
        return await self._get("/v2/actualize", params={"processId": process_id},
                               headers=self._auth_headers())
