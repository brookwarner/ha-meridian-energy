"""Firebase (Meridian CIAM) email-OTP authentication client."""

from __future__ import annotations

import base64
import json
import logging
import time
import uuid
from dataclasses import dataclass

import aiohttp

from . import const

_LOGGER = logging.getLogger(__name__)

_JSON_HEADERS = {"content-type": "application/json", "X-Client-Platform": "web"}


class MeridianAuthError(Exception):
    """Auth failed in a way that needs user re-authentication."""


class MeridianConnectionError(Exception):
    """Transient network/server error; retry later."""


@dataclass
class TokenBundle:
    """Result of a successful login."""

    id_token: str
    refresh_token: str
    account_number: str
    expires_at: float


class MeridianAuth:
    """Owns the Firebase token lifecycle."""

    def __init__(
        self, session: aiohttp.ClientSession, refresh_token: str | None = None
    ) -> None:
        """Initialise with an aiohttp session and optional stored refresh token."""
        self._session = session
        self._refresh_token = refresh_token
        self._id_token: str | None = None
        self._expires_at: float = 0.0
        self._account_number: str | None = None

    @property
    def refresh_token(self) -> str | None:
        """Return the current (possibly rotated) refresh token."""
        return self._refresh_token

    @property
    def account_number(self) -> str | None:
        """Return the account number decoded from the last id token."""
        return self._account_number

    @staticmethod
    def decode_claims(id_token: str) -> dict:
        """Decode a JWT payload without verifying the signature."""
        if not isinstance(id_token, str) or not id_token:
            raise MeridianAuthError("id token missing or not a string")
        try:
            payload_b64 = id_token.split(".")[1]
            payload_b64 += "=" * (-len(payload_b64) % 4)  # restore padding
            return json.loads(base64.urlsafe_b64decode(payload_b64))
        except (IndexError, ValueError) as err:
            raise MeridianAuthError(f"Could not decode id token: {err}") from err

    async def request_otp(self, email: str) -> str:
        """Trigger Meridian to email a one-time code; return the journey id."""
        journey_id = str(uuid.uuid4())
        payload = {
            "email": email,
            "brand": const.BRAND,
            "journeyId": journey_id,
            "otpEnabled": True,
            "redirectUrl": f"{const.APP_ORIGIN}/login",
        }
        try:
            async with self._session.post(
                const.EMAIL_CONNECTOR_URL, json=payload, headers=_JSON_HEADERS
            ) as resp:
                if resp.status >= 500:
                    raise MeridianConnectionError(f"OTP request server error {resp.status}")
                if resp.status >= 400:
                    raise MeridianAuthError(f"OTP request rejected ({resp.status})")
        except aiohttp.ClientError as err:
            raise MeridianConnectionError(str(err)) from err
        return journey_id

    async def validate_otp(self, email: str, otp: str, journey_id: str) -> TokenBundle:
        """Validate the OTP, exchange the custom token, return an id/refresh bundle."""
        payload = {"email": email, "otp": otp, "brand": const.BRAND, "journeyId": journey_id}
        try:
            async with self._session.post(
                const.EMAIL_OTP_URL, json=payload, headers=_JSON_HEADERS
            ) as resp:
                data = await resp.json(content_type=None)
                if resp.status >= 500:
                    raise MeridianConnectionError(
                        f"OTP validation server error ({resp.status})"
                    )
                if resp.status >= 400 or not data.get("customToken"):
                    raise MeridianAuthError(
                        f"OTP validation failed ({resp.status}): {data.get('error')}"
                    )
            custom_token = data["customToken"]
            return await self._exchange_custom_token(custom_token)
        except aiohttp.ClientError as err:
            raise MeridianConnectionError(str(err)) from err

    async def _exchange_custom_token(self, custom_token: str) -> TokenBundle:
        url = f"{const.SIGNIN_CUSTOM_TOKEN_URL}?key={const.CIAM_API_KEY}"
        async with self._session.post(
            url, json={"token": custom_token, "returnSecureToken": True}
        ) as resp:
            data = await resp.json(content_type=None)
            if resp.status >= 500:
                raise MeridianConnectionError(
                    f"Custom-token exchange server error ({resp.status})"
                )
            if resp.status >= 400:
                raise MeridianAuthError(f"Custom-token exchange failed: {data.get('error')}")
        self._store_tokens(data["idToken"], data["refreshToken"], data.get("expiresIn", "3600"))
        return TokenBundle(
            id_token=self._id_token,
            refresh_token=self._refresh_token,
            account_number=self._account_number,
            expires_at=self._expires_at,
        )

    async def async_valid_token(self) -> str:
        """Return a currently-valid id token, refreshing if near expiry."""
        if self._id_token and time.time() < self._expires_at - const.TOKEN_EXPIRY_MARGIN:
            return self._id_token
        await self._refresh()
        return self._id_token

    async def _refresh(self) -> None:
        if not self._refresh_token:
            raise MeridianAuthError("No refresh token available; re-authentication required")
        url = f"{const.SECURETOKEN_URL}?key={const.CIAM_API_KEY}"
        data = {"grant_type": "refresh_token", "refresh_token": self._refresh_token}
        try:
            async with self._session.post(url, data=data) as resp:
                body = await resp.json(content_type=None)
                if resp.status >= 500:
                    raise MeridianConnectionError(
                        f"Token refresh server error ({resp.status})"
                    )
                if resp.status >= 400:
                    raise MeridianAuthError(f"Token refresh failed: {body.get('error')}")
        except aiohttp.ClientError as err:
            raise MeridianConnectionError(str(err)) from err
        # securetoken endpoint uses snake_case keys.
        self._store_tokens(body["id_token"], body["refresh_token"], body.get("expires_in", "3600"))

    def _store_tokens(self, id_token: str, refresh_token: str, expires_in) -> None:
        self._id_token = id_token
        self._refresh_token = refresh_token
        self._expires_at = time.time() + int(expires_in)
        claims = self.decode_claims(id_token)
        accounts = claims.get("accounts") or []
        if accounts:
            self._account_number = accounts[0].get("account_number")
