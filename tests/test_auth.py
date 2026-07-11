import base64
import json
import time

import aiohttp
import pytest
from aioresponses import aioresponses

from meridian_energy import const
from meridian_energy.auth import MeridianAuth, MeridianAuthError, MeridianConnectionError


def _fake_id_token(account="A-F53DF172", exp=None):
    exp = exp or int(time.time()) + 3600
    header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').rstrip(b"=").decode()
    payload = {
        "accounts": [{"brand": "MERIDIAN_ENERGY", "account_number": account}],
        "exp": exp,
        "user_id": "U-1",
    }
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{header}.{body}.sig"


async def test_request_otp_returns_journey_id():
    async with aiohttp.ClientSession() as session:
        auth = MeridianAuth(session)
        with aioresponses() as m:
            m.post(const.EMAIL_CONNECTOR_URL, status=200, payload={"status": "ok"})
            jid = await auth.request_otp("me@example.com")
        assert isinstance(jid, str) and len(jid) > 10


async def test_validate_otp_exchanges_custom_token_and_decodes_account():
    idt = _fake_id_token()
    async with aiohttp.ClientSession() as session:
        auth = MeridianAuth(session)
        with aioresponses() as m:
            m.post(const.EMAIL_OTP_URL, status=200, payload={"customToken": "CT"})
            m.post(
                f"{const.SIGNIN_CUSTOM_TOKEN_URL}?key={const.CIAM_API_KEY}",
                status=200,
                payload={"idToken": idt, "refreshToken": "RT", "expiresIn": "3600"},
            )
            bundle = await auth.validate_otp("me@example.com", "123456", "jid")
        assert bundle.refresh_token == "RT"
        assert bundle.account_number == "A-F53DF172"
        assert auth.refresh_token == "RT"


async def test_validate_otp_bad_code_raises_auth_error():
    async with aiohttp.ClientSession() as session:
        auth = MeridianAuth(session)
        with aioresponses() as m:
            m.post(const.EMAIL_OTP_URL, status=401, payload={"error": "invalid otp"})
            with pytest.raises(MeridianAuthError):
                await auth.validate_otp("me@example.com", "000000", "jid")


async def test_valid_token_refreshes_when_expired():
    expired = _fake_id_token(exp=int(time.time()) - 10)
    fresh = _fake_id_token(exp=int(time.time()) + 3600)
    async with aiohttp.ClientSession() as session:
        auth = MeridianAuth(session, refresh_token="RT0")
        auth._id_token = expired  # seed an expired token
        auth._expires_at = time.time() - 10
        with aioresponses() as m:
            m.post(
                f"{const.SECURETOKEN_URL}?key={const.CIAM_API_KEY}",
                status=200,
                payload={"id_token": fresh, "refresh_token": "RT1", "expires_in": "3600"},
            )
            token = await auth.async_valid_token()
        assert token == fresh
        assert auth.refresh_token == "RT1"  # rotation stored


async def test_valid_token_refresh_failure_raises_auth_error():
    async with aiohttp.ClientSession() as session:
        auth = MeridianAuth(session, refresh_token="BAD")
        with aioresponses() as m:
            m.post(
                f"{const.SECURETOKEN_URL}?key={const.CIAM_API_KEY}",
                status=400,
                payload={"error": {"message": "TOKEN_EXPIRED"}},
            )
            with pytest.raises(MeridianAuthError):
                await auth.async_valid_token()


async def test_request_otp_5xx_raises_connection_error():
    async with aiohttp.ClientSession() as session:
        auth = MeridianAuth(session)
        with aioresponses() as m:
            m.post(const.EMAIL_CONNECTOR_URL, status=500, payload={"error": "boom"})
            with pytest.raises(MeridianConnectionError):
                await auth.request_otp("me@example.com")


async def test_validate_otp_5xx_raises_connection_error():
    async with aiohttp.ClientSession() as session:
        auth = MeridianAuth(session)
        with aioresponses() as m:
            m.post(const.EMAIL_OTP_URL, status=500, payload={"error": "boom"})
            with pytest.raises(MeridianConnectionError):
                await auth.validate_otp("me@example.com", "123456", "jid")


async def test_refresh_5xx_raises_connection_error():
    async with aiohttp.ClientSession() as session:
        auth = MeridianAuth(session, refresh_token="RT")
        with aioresponses() as m:
            m.post(
                f"{const.SECURETOKEN_URL}?key={const.CIAM_API_KEY}",
                status=500,
                payload={"error": {"message": "server error"}},
            )
            with pytest.raises(MeridianConnectionError):
                await auth.async_valid_token()


async def test_refresh_network_error_raises_connection_error():
    async with aiohttp.ClientSession() as session:
        auth = MeridianAuth(session, refresh_token="RT")
        with aioresponses() as m:
            m.post(
                f"{const.SECURETOKEN_URL}?key={const.CIAM_API_KEY}",
                exception=aiohttp.ClientError(),
            )
            with pytest.raises(MeridianConnectionError):
                await auth.async_valid_token()


async def test_decode_claims_rejects_non_string():
    with pytest.raises(MeridianAuthError):
        MeridianAuth.decode_claims(None)


async def test_invalidate_token_forces_refresh():
    async with aiohttp.ClientSession() as session:
        auth = MeridianAuth(session, refresh_token="RT")
        auth._expires_at = 9999999999
        auth.invalidate_token()
        assert auth._expires_at == 0.0
