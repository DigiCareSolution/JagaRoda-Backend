import hmac
import logging
import os
import httpx

logger = logging.getLogger("telegram_service")


def get_telegram_bot_token() -> str | None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    return token.strip() if token and token.strip() else None


def get_telegram_bot_username() -> str:
    username = os.getenv("TELEGRAM_BOT_USERNAME", "")
    return username.strip().lstrip("@")


def get_telegram_webhook_secret() -> str | None:
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    return secret.strip() if secret and secret.strip() else None


def is_telegram_configured() -> bool:
    return bool(get_telegram_bot_token())


def generate_deep_link(raw_token: str) -> str:
    """
    Generates a Telegram deep link with the given one-time start parameter.
    Format: https://t.me/<bot_username>?start=<raw_token>
    """
    bot_username = get_telegram_bot_username()
    if not bot_username:
        logger.warning("TELEGRAM_BOT_USERNAME belum diset di environment variables.")
        bot_username = "JagaRodaBot"
    return f"https://t.me/{bot_username}?start={raw_token}"


def verify_webhook_secret(header_secret: str | None) -> bool:
    """
    Verifies that the incoming X-Telegram-Bot-Api-Secret-Token matches
    the configured TELEGRAM_WEBHOOK_SECRET using constant-time comparison.
    """
    expected_secret = get_telegram_webhook_secret()
    if not expected_secret:
        # If no secret is configured, warn in logs
        logger.warning("TELEGRAM_WEBHOOK_SECRET tidak dikonfigurasi; webhook tidak diverifikasi.")
        return True

    if not header_secret:
        return False

    return hmac.compare_digest(header_secret.strip(), expected_secret)


async def send_telegram_message(
    chat_id: int | str,
    text: str,
    parse_mode: str = "HTML",
    timeout_seconds: float = 10.0,
) -> bool:
    """
    Sends a private message to a specific Telegram chat ID.
    Gracefully handles failures without raising exceptions so business operations never break.
    Bot token is never logged or exposed.
    """
    token = get_telegram_bot_token()
    if not token:
        logger.debug("Telegram bot token tidak dikonfigurasi. Pesan Telegram dilewati.")
        return False

    api_url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(api_url, json=payload)

        if response.status_code == 200:
            return True

        # Handle specific Telegram API error status codes
        if response.status_code == 403:
            logger.warning(
                "Gagal mengirim pesan Telegram ke chat_id=%s: Bot diblokir atau user belum memulai bot.",
                chat_id,
            )
        elif response.status_code == 429:
            logger.warning(
                "Telegram API Rate Limit tercapai saat mengirim ke chat_id=%s.", chat_id
            )
        elif response.status_code == 400:
            logger.warning(
                "Permintaan Telegram tidak valid untuk chat_id=%s (status 400). Mencoba fallback plain text...",
                chat_id,
            )
            # Fallback to plain text if HTML parsing failed
            if parse_mode != "None":
                fallback_payload = {
                    "chat_id": chat_id,
                    "text": text,
                    "disable_web_page_preview": True,
                }
                async with httpx.AsyncClient(timeout=timeout_seconds) as fallback_client:
                    fb_res = await fallback_client.post(api_url, json=fallback_payload)
                    if fb_res.status_code == 200:
                        return True
        else:
            logger.error(
                "Telegram API mengembalikan status %s untuk chat_id=%s",
                response.status_code,
                chat_id,
            )

        return False

    except httpx.TimeoutException:
        logger.warning("Timeout saat menghubungi Telegram API untuk chat_id=%s", chat_id)
        return False
    except httpx.RequestError as exc:
        logger.error(
            "Kesalahan jaringan saat menghubungi Telegram API: %s", type(exc).__name__
        )
        return False
    except Exception as exc:
        logger.error(
            "Kesalahan tidak terduga saat mengirim pesan Telegram: %s", type(exc).__name__
        )
        return False
