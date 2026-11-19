import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from supabase import Client

from src.telegram_service import (
    generate_deep_link,
    send_telegram_message,
)

logger = logging.getLogger("notification_service")

# Default notification preferences for newly linked Telegram accounts
DEFAULT_PREFERENCES: dict[str, bool] = {
    "vehicle_updates": True,
    "account_updates": True,
    "system_alerts": True,
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_in_app_notification(
    supabase: Client,
    user_id: str,
    title: str,
    message: str,
    notification_type: str = "info",
    related_entity_type: str | None = None,
    related_entity_id: str | None = None,
    action_url: str | None = None,
) -> dict[str, Any]:
    """
    Inserts a persistent in-app notification for a given user.
    """
    payload = {
        "user_id": str(user_id),
        "title": title,
        "message": message,
        "type": notification_type,
        "related_entity_type": related_entity_type,
        "related_entity_id": str(related_entity_id) if related_entity_id is not None else None,
        "action_url": action_url,
        "is_read": False,
        "created_at": _utc_now_iso(),
    }

    try:
        response = supabase.table("notifications").insert(payload).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]
        return payload
    except Exception as exc:
        logger.error("Gagal menyimpan in-app notification untuk user_id=%s: %s", user_id, exc)
        return payload


def get_user_notifications(
    supabase: Client,
    user_id: str,
    limit: int = 20,
    offset: int = 0,
    is_read: bool | None = None,
    notification_type: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """
    Retrieves paginated notifications for the specified user with optional filters.
    Returns (notifications_list, total_count).
    """
    try:
        query = (
            supabase.table("notifications")
            .select("*", count="exact")
            .eq("user_id", str(user_id))
            .order("created_at", desc=True)
        )

        if is_read is not None:
            query = query.eq("is_read", is_read)

        if notification_type is not None:
            query = query.eq("type", notification_type)

        response = query.range(offset, offset + limit - 1).execute()
        items = response.data or []
        total_count = response.count if response.count is not None else len(items)
        return items, total_count
    except Exception as exc:
        logger.error("Gagal mengambil notifikasi untuk user_id=%s: %s", user_id, exc)
        return [], 0


def get_unread_count(supabase: Client, user_id: str) -> int:
    """
    Returns the count of unread notifications for a user.
    """
    try:
        response = (
            supabase.table("notifications")
            .select("id", count="exact")
            .eq("user_id", str(user_id))
            .eq("is_read", False)
            .execute()
        )
        if response.count is not None:
            return response.count
        return len(response.data or [])
    except Exception as exc:
        logger.error("Gagal menghitung notifikasi belum dibaca user_id=%s: %s", user_id, exc)
        return 0


def mark_notification_as_read(
    supabase: Client,
    user_id: str,
    notification_id: str,
) -> bool:
    """
    Marks a specific notification as read, ensuring strict user isolation.
    """
    try:
        now_iso = _utc_now_iso()
        response = (
            supabase.table("notifications")
            .update({"is_read": True, "read_at": now_iso})
            .eq("id", notification_id)
            .eq("user_id", str(user_id))
            .execute()
        )
        return bool(response.data and len(response.data) > 0)
    except Exception as exc:
        logger.error(
            "Gagal menandai notifikasi id=%s sebagai dibaca untuk user_id=%s: %s",
            notification_id,
            user_id,
            exc,
        )
        return False


def mark_all_notifications_as_read(supabase: Client, user_id: str) -> int:
    """
    Marks all unread notifications for a user as read.
    Returns the number of notifications updated.
    """
    try:
        now_iso = _utc_now_iso()
        response = (
            supabase.table("notifications")
            .update({"is_read": True, "read_at": now_iso})
            .eq("user_id", str(user_id))
            .eq("is_read", False)
            .execute()
        )
        return len(response.data) if response.data else 0
    except Exception as exc:
        logger.error(
            "Gagal menandai semua notifikasi dibaca untuk user_id=%s: %s", user_id, exc
        )
        return 0


def generate_linking_token(
    supabase: Client,
    user_id: str,
    expires_minutes: int = 15,
) -> dict[str, Any]:
    """
    Generates a cryptographically secure one-time linking token.
    Stores the SHA-256 hash in the database, invalidates old unused tokens,
    and returns a Telegram deep link with the raw token.
    """
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)

    # Invalidate older unused tokens for this user
    try:
        supabase.table("telegram_linking_tokens").update({
            "is_used": True,
            "used_at": _utc_now_iso(),
        }).eq("user_id", str(user_id)).eq("is_used", False).execute()
    except Exception as exc:
        logger.debug("Tidak dapat meng-invalidsi token lama (bisa jadi belum ada): %s", exc)

    # Insert new token hash
    payload = {
        "token_hash": token_hash,
        "user_id": str(user_id),
        "expires_at": expires_at.isoformat(),
        "is_used": False,
        "created_at": _utc_now_iso(),
    }
    supabase.table("telegram_linking_tokens").insert(payload).execute()

    deep_link = generate_deep_link(raw_token)
    return {
        "deep_link": deep_link,
        "expires_at": expires_at.isoformat(),
        "expires_in_minutes": expires_minutes,
    }


async def process_telegram_start(
    supabase: Client,
    raw_token: str,
    chat_id: int | str,
    telegram_user: dict[str, Any],
) -> tuple[bool, str]:
    """
    Validates the token from a Telegram /start command, atomically consumes it,
    and links the Telegram chat ID to the corresponding JagaRoda user account.
    Returns (success: bool, message: str).
    """
    cleaned_token = raw_token.strip()
    if not cleaned_token:
        return False, "Token tidak boleh kosong."

    token_hash = hashlib.sha256(cleaned_token.encode("utf-8")).hexdigest()
    now_utc = datetime.now(timezone.utc)

    # 1. Look up token by hash
    try:
        response = (
            supabase.table("telegram_linking_tokens")
            .select("*")
            .eq("token_hash", token_hash)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.error("Gagal mengambil data linking token: %s", exc)
        return False, "Terjadi kesalahan internal saat memvalidasi token."

    if not response.data or len(response.data) == 0:
        return False, "Token tautan tidak valid atau tidak ditemukan."

    token_row = response.data[0]

    # Check if already used
    if token_row.get("is_used"):
        return False, "Token tautan ini sudah pernah digunakan. Silakan buat tautan baru di dashboard web."

    # Check expiration
    expires_at_str = token_row.get("expires_at")
    if expires_at_str:
        try:
            expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            if expires_at < now_utc:
                return False, "Token tautan telah kedaluwarsa. Silakan buat tautan baru di dashboard web."
        except Exception:
            pass

    target_user_id = str(token_row.get("user_id"))

    # 2. Atomic consumption check (prevent race conditions & replay)
    try:
        consume_res = (
            supabase.table("telegram_linking_tokens")
            .update({"is_used": True, "used_at": now_utc.isoformat()})
            .eq("token_hash", token_hash)
            .eq("is_used", False)
            .execute()
        )
        if not consume_res.data:
            return False, "Token tautan sedang atau sudah diproses."
    except Exception as exc:
        logger.error("Gagal mengonsumsi linking token secara atomic: %s", exc)
        return False, "Gagal memproses token tautan."

    # 3. Check if Telegram chat_id is already linked to another JagaRoda account
    try:
        existing_chat = (
            supabase.table("telegram_accounts")
            .select("user_id")
            .eq("telegram_chat_id", int(chat_id) if str(chat_id).isdigit() else str(chat_id))
            .limit(1)
            .execute()
        )
        if existing_chat.data and len(existing_chat.data) > 0:
            linked_user = str(existing_chat.data[0].get("user_id"))
            if linked_user != target_user_id:
                return False, "Akun Telegram ini sudah terhubung dengan akun JagaRoda yang lain."
    except Exception as exc:
        logger.error("Gagal memeriksa keunikan telegram_chat_id: %s", exc)

    # 4. Upsert or insert into telegram_accounts
    username = telegram_user.get("username")
    first_name = telegram_user.get("first_name")
    chat_id_val = int(chat_id) if str(chat_id).isdigit() else chat_id

    try:
        existing_account = (
            supabase.table("telegram_accounts")
            .select("id, preferences")
            .eq("user_id", target_user_id)
            .limit(1)
            .execute()
        )

        if existing_account.data and len(existing_account.data) > 0:
            supabase.table("telegram_accounts").update({
                "telegram_chat_id": chat_id_val,
                "telegram_username": username,
                "first_name": first_name,
                "is_enabled": True,
                "updated_at": now_utc.isoformat(),
            }).eq("user_id", target_user_id).execute()
        else:
            supabase.table("telegram_accounts").insert({
                "user_id": target_user_id,
                "telegram_chat_id": chat_id_val,
                "telegram_username": username,
                "first_name": first_name,
                "is_enabled": True,
                "preferences": DEFAULT_PREFERENCES,
                "linked_at": now_utc.isoformat(),
                "updated_at": now_utc.isoformat(),
            }).execute()

    except Exception as exc:
        logger.error("Gagal menyimpan akun Telegram tertaut ke database: %s", exc)
        return False, "Gagal menautkan akun Telegram di sistem database."

    # 5. Emit in-app notification confirming successful link
    display_name = f"@{username}" if username else (first_name or "Telegram User")
    create_in_app_notification(
        supabase=supabase,
        user_id=target_user_id,
        title="Telegram Berhasil Ditautkan",
        message=f"Akun Telegram {display_name} berhasil terhubung. Anda sekarang akan menerima notifikasi langsung di Telegram.",
        notification_type="success",
        related_entity_type="telegram_account",
        related_entity_id=str(chat_id),
    )

    return True, f"Selamat! Akun Telegram berhasil terhubung dengan akun JagaRoda Anda."


def unlink_telegram_account(supabase: Client, user_id: str) -> bool:
    """
    Unlinks the authenticated user's Telegram account and creates an in-app notification.
    """
    try:
        response = (
            supabase.table("telegram_accounts")
            .delete()
            .eq("user_id", str(user_id))
            .execute()
        )

        create_in_app_notification(
            supabase=supabase,
            user_id=str(user_id),
            title="Telegram Diputuskan",
            message="Tautan akun Telegram Anda telah berhasil diputuskan. Anda tidak lagi menerima notifikasi via Telegram.",
            notification_type="warning",
            related_entity_type="telegram_account",
        )

        return True
    except Exception as exc:
        logger.error("Gagal memutuskan tautan Telegram untuk user_id=%s: %s", user_id, exc)
        return False


def get_telegram_status(supabase: Client, user_id: str) -> dict[str, Any]:
    """
    Retrieves the Telegram linking status and preferences for the authenticated user.
    """
    try:
        response = (
            supabase.table("telegram_accounts")
            .select("telegram_chat_id, telegram_username, first_name, is_enabled, preferences, linked_at")
            .eq("user_id", str(user_id))
            .limit(1)
            .execute()
        )

        if not response.data or len(response.data) == 0:
            return {
                "is_linked": False,
                "telegram_username": None,
                "is_enabled": False,
                "preferences": None,
                "linked_at": None,
            }

        row = response.data[0]
        return {
            "is_linked": True,
            "telegram_username": row.get("telegram_username"),
            "is_enabled": row.get("is_enabled", True),
            "preferences": row.get("preferences") or DEFAULT_PREFERENCES,
            "linked_at": row.get("linked_at"),
        }
    except Exception as exc:
        logger.error("Gagal mengambil status Telegram user_id=%s: %s", user_id, exc)
        return {
            "is_linked": False,
            "telegram_username": None,
            "is_enabled": False,
            "preferences": None,
            "linked_at": None,
        }


def update_telegram_preferences(
    supabase: Client,
    user_id: str,
    is_enabled: bool | None = None,
    preferences: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """
    Updates the Telegram notification preferences and/or enabled state for a user.
    """
    try:
        current = (
            supabase.table("telegram_accounts")
            .select("is_enabled, preferences")
            .eq("user_id", str(user_id))
            .limit(1)
            .execute()
        )

        if not current.data:
            return {"status": "error", "message": "Akun Telegram belum ditautkan."}

        update_payload: dict[str, Any] = {"updated_at": _utc_now_iso()}
        if is_enabled is not None:
            update_payload["is_enabled"] = is_enabled

        if preferences is not None:
            existing_prefs = current.data[0].get("preferences") or DEFAULT_PREFERENCES.copy()
            existing_prefs.update(preferences)
            update_payload["preferences"] = existing_prefs

        response = (
            supabase.table("telegram_accounts")
            .update(update_payload)
            .eq("user_id", str(user_id))
            .execute()
        )

        updated_row = response.data[0] if response.data else update_payload
        return {
            "status": "success",
            "is_enabled": updated_row.get("is_enabled"),
            "preferences": updated_row.get("preferences"),
        }
    except Exception as exc:
        logger.error("Gagal memperbarui preferensi Telegram user_id=%s: %s", user_id, exc)
        return {"status": "error", "message": str(exc)}


async def dispatch_event_notification(
    supabase: Client,
    user_id: str,
    title: str,
    message: str,
    notification_type: str = "info",
    related_entity_type: str | None = None,
    related_entity_id: str | None = None,
    action_url: str | None = None,
    event_category: str = "system_alerts",
) -> dict[str, Any]:
    """
    Core reusable notification dispatcher:
    1. Creates a persistent in-app notification.
    2. If the user has linked Telegram, enabled notifications, and allowed this event_category,
       sends a formatted Telegram private message.
    3. Telegram failure NEVER breaks the operation or raises an exception.
    """
    # 1. Create in-app notification record
    in_app = create_in_app_notification(
        supabase=supabase,
        user_id=user_id,
        title=title,
        message=message,
        notification_type=notification_type,
        related_entity_type=related_entity_type,
        related_entity_id=related_entity_id,
        action_url=action_url,
    )

    # 2. Check Telegram linking & preferences
    try:
        tg_status = (
            supabase.table("telegram_accounts")
            .select("telegram_chat_id, is_enabled, preferences")
            .eq("user_id", str(user_id))
            .limit(1)
            .execute()
        )

        if tg_status.data and len(tg_status.data) > 0:
            account = tg_status.data[0]
            if account.get("is_enabled", True):
                prefs = account.get("preferences") or DEFAULT_PREFERENCES
                # Check category preference
                if prefs.get(event_category, True):
                    chat_id = account.get("telegram_chat_id")
                    if chat_id:
                        tg_text = f"🚗 <b>[JagaRoda] {title}</b>\n\n{message}"
                        if action_url:
                            tg_text += f"\n\n🔗 <a href='{action_url}'>Lihat di Dashboard</a>"

                        await send_telegram_message(chat_id=chat_id, text=tg_text)

    except Exception as exc:
        # Guarantee that dispatch failure never crashes the business operation
        logger.warning(
            "Telegram notification dispatch gagal untuk user_id=%s (in-app tersimpan): %s",
            user_id,
            exc,
        )

    return in_app
