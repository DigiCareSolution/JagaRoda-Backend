import asyncio
import hashlib
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.notification_service import (
    create_in_app_notification,
    dispatch_event_notification,
    generate_linking_token,
    get_telegram_status,
    get_unread_count,
    get_user_notifications,
    mark_all_notifications_as_read,
    mark_notification_as_read,
    process_telegram_start,
    unlink_telegram_account,
    update_telegram_preferences,
)
from src.telegram_service import (
    generate_deep_link,
    send_telegram_message,
    verify_webhook_secret,
)


class TestNotificationSystem(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mock_supabase = MagicMock()
        self.user_a_id = "11111111-1111-1111-1111-111111111111"
        self.user_b_id = "22222222-2222-2222-2222-222222222222"

    # 1. Notification Creation
    def test_notification_creation(self):
        mock_table = MagicMock()
        self.mock_supabase.table.return_value = mock_table
        mock_insert = MagicMock()
        mock_table.insert.return_value = mock_insert
        mock_insert.execute.return_value = MagicMock(data=[{
            "id": "notif-1",
            "user_id": self.user_a_id,
            "title": "Kendaraan Baru",
            "message": "Avanza berhasil ditambahkan",
            "type": "vehicle_created",
            "is_read": False,
        }])

        notif = create_in_app_notification(
            supabase=self.mock_supabase,
            user_id=self.user_a_id,
            title="Kendaraan Baru",
            message="Avanza berhasil ditambahkan",
            notification_type="vehicle_created",
            related_entity_type="vehicle",
            related_entity_id="10",
        )

        self.mock_supabase.table.assert_called_with("notifications")
        self.assertEqual(notif["id"], "notif-1")
        self.assertEqual(notif["user_id"], self.user_a_id)
        self.assertEqual(notif["title"], "Kendaraan Baru")

    # 2. User Isolation
    def test_user_isolation(self):
        mock_table = MagicMock()
        self.mock_supabase.table.return_value = mock_table
        mock_query = MagicMock()
        mock_table.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.order.return_value = mock_query
        mock_query.range.return_value = mock_query
        mock_query.execute.return_value = MagicMock(data=[
            {"id": "notif-user-a", "user_id": self.user_a_id, "title": "For A"}
        ], count=1)

        items, total = get_user_notifications(
            supabase=self.mock_supabase,
            user_id=self.user_a_id,
            limit=10,
            offset=0,
        )

        mock_query.eq.assert_called_with("user_id", self.user_a_id)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["user_id"], self.user_a_id)

    # 3. Unread Count
    def test_unread_count(self):
        mock_table = MagicMock()
        self.mock_supabase.table.return_value = mock_table
        mock_query = MagicMock()
        mock_table.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.execute.return_value = MagicMock(count=5, data=[])

        count = get_unread_count(self.mock_supabase, self.user_a_id)
        self.assertEqual(count, 5)

    # 4. Mark Read (with user isolation)
    def test_mark_read(self):
        mock_table = MagicMock()
        self.mock_supabase.table.return_value = mock_table
        mock_update = MagicMock()
        mock_table.update.return_value = mock_update
        mock_update.eq.return_value = mock_update
        mock_update.execute.return_value = MagicMock(data=[{"id": "notif-1", "is_read": True}])

        success = mark_notification_as_read(
            supabase=self.mock_supabase,
            user_id=self.user_a_id,
            notification_id="notif-1",
        )
        self.assertTrue(success)

        # Non-matching user / empty response
        mock_update.execute.return_value = MagicMock(data=[])
        failed = mark_notification_as_read(
            supabase=self.mock_supabase,
            user_id=self.user_b_id,
            notification_id="notif-1",
        )
        self.assertFalse(failed)

    # 5. Mark All Read
    def test_mark_all_read(self):
        mock_table = MagicMock()
        self.mock_supabase.table.return_value = mock_table
        mock_update = MagicMock()
        mock_table.update.return_value = mock_update
        mock_update.eq.return_value = mock_update
        mock_update.execute.return_value = MagicMock(data=[{"id": "1"}, {"id": "2"}, {"id": "3"}])

        count = mark_all_notifications_as_read(self.mock_supabase, self.user_a_id)
        self.assertEqual(count, 3)

    # 6. Link Token Creation
    @patch.dict(os.environ, {"TELEGRAM_BOT_USERNAME": "JagaRodaTestBot"})
    def test_link_token_creation(self):
        mock_table = MagicMock()
        self.mock_supabase.table.return_value = mock_table
        mock_op = MagicMock()
        mock_table.update.return_value = mock_op
        mock_table.insert.return_value = mock_op
        mock_op.eq.return_value = mock_op
        mock_op.execute.return_value = MagicMock(data=[])

        result = generate_linking_token(self.mock_supabase, self.user_a_id, expires_minutes=15)

        self.assertIn("deep_link", result)
        self.assertIn("https://t.me/JagaRodaTestBot?start=", result["deep_link"])
        self.assertIn("expires_at", result)
        self.assertEqual(result["expires_in_minutes"], 15)
        # Verify raw token is in URL and NOT hash
        raw_token = result["deep_link"].split("start=")[1]
        self.assertTrue(len(raw_token) > 20)

    # 7. Token Expiry
    async def test_token_expiry(self):
        mock_table = MagicMock()
        self.mock_supabase.table.return_value = mock_table
        mock_query = MagicMock()
        mock_table.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.limit.return_value = mock_query

        expired_time = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        mock_query.execute.return_value = MagicMock(data=[{
            "token_hash": "dummyhash",
            "user_id": self.user_a_id,
            "expires_at": expired_time,
            "is_used": False,
        }])

        success, msg = await process_telegram_start(
            supabase=self.mock_supabase,
            raw_token="rawtoken123",
            chat_id=12345678,
            telegram_user={"username": "yusron_dev"},
        )
        self.assertFalse(success)
        self.assertIn("kedaluwarsa", msg.lower())

    # 8. Token Single-Use & Atomic Replay Prevention
    async def test_token_single_use(self):
        mock_table = MagicMock()
        self.mock_supabase.table.return_value = mock_table
        mock_query = MagicMock()
        mock_table.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.limit.return_value = mock_query

        # Already used token
        mock_query.execute.return_value = MagicMock(data=[{
            "token_hash": "dummyhash",
            "user_id": self.user_a_id,
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
            "is_used": True,
        }])

        success, msg = await process_telegram_start(
            supabase=self.mock_supabase,
            raw_token="rawtoken123",
            chat_id=12345678,
            telegram_user={"username": "yusron_dev"},
        )
        self.assertFalse(success)
        self.assertIn("sudah pernah digunakan", msg.lower())

    # 9. Webhook Secret Validation
    def test_webhook_secret_validation(self):
        with patch.dict(os.environ, {"TELEGRAM_WEBHOOK_SECRET": "my-secure-webhook-secret"}):
            self.assertTrue(verify_webhook_secret("my-secure-webhook-secret"))
            self.assertFalse(verify_webhook_secret("wrong-secret"))
            self.assertFalse(verify_webhook_secret(None))
            self.assertFalse(verify_webhook_secret(""))

    # 10. Valid Webhook Processing & Telegram Account Linking
    async def test_telegram_account_linking(self):
        mock_tokens_table = MagicMock()
        mock_accounts_table = MagicMock()
        mock_notifs_table = MagicMock()

        def table_router(table_name):
            if table_name == "telegram_linking_tokens":
                return mock_tokens_table
            elif table_name == "telegram_accounts":
                return mock_accounts_table
            return mock_notifs_table

        self.mock_supabase.table.side_effect = table_router

        valid_expiry = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        token_select = MagicMock()
        mock_tokens_table.select.return_value = token_select
        token_select.eq.return_value = token_select
        token_select.limit.return_value = token_select
        token_select.execute.return_value = MagicMock(data=[{
            "token_hash": "dummy",
            "user_id": self.user_a_id,
            "expires_at": valid_expiry,
            "is_used": False,
        }])

        token_update = MagicMock()
        mock_tokens_table.update.return_value = token_update
        token_update.eq.return_value = token_update
        token_update.execute.return_value = MagicMock(data=[{"is_used": True}])

        # No duplicate chat_id
        chat_select = MagicMock()
        mock_accounts_table.select.return_value = chat_select
        chat_select.eq.return_value = chat_select
        chat_select.limit.return_value = chat_select
        chat_select.execute.return_value = MagicMock(data=[])

        # Insert account
        account_insert = MagicMock()
        mock_accounts_table.insert.return_value = account_insert
        account_insert.execute.return_value = MagicMock(data=[{"id": "acc-1"}])

        # Insert notification
        notif_insert = MagicMock()
        mock_notifs_table.insert.return_value = notif_insert
        notif_insert.execute.return_value = MagicMock(data=[{"id": "n-1"}])

        success, msg = await process_telegram_start(
            supabase=self.mock_supabase,
            raw_token="valid_raw_token",
            chat_id=98765432,
            telegram_user={"username": "testuser", "first_name": "Test"},
        )

        self.assertTrue(success)
        self.assertIn("berhasil terhubung", msg.lower())

    # 11. Duplicate Telegram Linking Prevention
    async def test_duplicate_telegram_linking(self):
        mock_tokens_table = MagicMock()
        mock_accounts_table = MagicMock()

        def table_router(table_name):
            if table_name == "telegram_linking_tokens":
                return mock_tokens_table
            return mock_accounts_table

        self.mock_supabase.table.side_effect = table_router

        valid_expiry = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        token_select = MagicMock()
        mock_tokens_table.select.return_value = token_select
        token_select.eq.return_value = token_select
        token_select.limit.return_value = token_select
        token_select.execute.return_value = MagicMock(data=[{
            "token_hash": "dummy",
            "user_id": self.user_a_id,
            "expires_at": valid_expiry,
            "is_used": False,
        }])

        token_update = MagicMock()
        mock_tokens_table.update.return_value = token_update
        token_update.eq.return_value = token_update
        token_update.execute.return_value = MagicMock(data=[{"is_used": True}])

        # Chat ID already linked to User B!
        chat_select = MagicMock()
        mock_accounts_table.select.return_value = chat_select
        chat_select.eq.return_value = chat_select
        chat_select.limit.return_value = chat_select
        chat_select.execute.return_value = MagicMock(data=[{"user_id": self.user_b_id}])

        success, msg = await process_telegram_start(
            supabase=self.mock_supabase,
            raw_token="valid_raw_token",
            chat_id=98765432,
            telegram_user={"username": "someone"},
        )

        self.assertFalse(success)
        self.assertIn("sudah terhubung dengan akun jagaroda yang lain", msg.lower())

    # 12. Telegram Unlinking
    def test_unlinking(self):
        mock_accounts = MagicMock()
        mock_notifs = MagicMock()

        def table_router(table_name):
            if table_name == "telegram_accounts":
                return mock_accounts
            return mock_notifs

        self.mock_supabase.table.side_effect = table_router
        mock_delete = MagicMock()
        mock_accounts.delete.return_value = mock_delete
        mock_delete.eq.return_value = mock_delete
        mock_delete.execute.return_value = MagicMock(data=[{"user_id": self.user_a_id}])

        success = unlink_telegram_account(self.mock_supabase, self.user_a_id)
        self.assertTrue(success)
        mock_accounts.delete.assert_called_once()

    # 13. Notification Preferences Handling
    def test_notification_preferences(self):
        mock_table = MagicMock()
        self.mock_supabase.table.return_value = mock_table
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value = mock_select
        mock_select.limit.return_value = mock_select
        mock_select.execute.return_value = MagicMock(data=[{
            "is_enabled": True,
            "preferences": {"vehicle_updates": True, "account_updates": True, "system_alerts": True}
        }])

        mock_update = MagicMock()
        mock_table.update.return_value = mock_update
        mock_update.eq.return_value = mock_update
        mock_update.execute.return_value = MagicMock(data=[{
            "is_enabled": False,
            "preferences": {"vehicle_updates": False, "account_updates": True, "system_alerts": True}
        }])

        res = update_telegram_preferences(
            supabase=self.mock_supabase,
            user_id=self.user_a_id,
            is_enabled=False,
            preferences={"vehicle_updates": False},
        )

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["is_enabled"], False)

    # 14. Telegram API Failure Handling (Never throws)
    @patch("httpx.AsyncClient.post")
    async def test_telegram_api_failure(self, mock_post):
        mock_post.return_value = MagicMock(status_code=403)
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "mock-token-xyz"}):
            sent = await send_telegram_message(chat_id=123456, text="Hello test")
            self.assertFalse(sent)

        # Network Timeout
        import httpx
        mock_post.side_effect = httpx.TimeoutException("Connection timed out")
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "mock-token-xyz"}):
            sent = await send_telegram_message(chat_id=123456, text="Hello test")
            self.assertFalse(sent)

    # 15. Business Operation Survives Telegram Failure
    @patch("src.notification_service.send_telegram_message")
    async def test_business_operation_survives_telegram_failure(self, mock_send_tg):
        mock_send_tg.side_effect = Exception("Telegram network fatal crash")

        mock_notif_table = MagicMock()
        mock_account_table = MagicMock()

        def table_router(table_name):
            if table_name == "notifications":
                return mock_notif_table
            return mock_account_table

        self.mock_supabase.table.side_effect = table_router

        notif_insert = MagicMock()
        mock_notif_table.insert.return_value = notif_insert
        notif_insert.execute.return_value = MagicMock(data=[{
            "id": "notif-created",
            "title": "Kendaraan Baru",
            "user_id": self.user_a_id,
        }])

        account_select = MagicMock()
        mock_account_table.select.return_value = account_select
        account_select.eq.return_value = account_select
        account_select.limit.return_value = account_select
        account_select.execute.return_value = MagicMock(data=[{
            "telegram_chat_id": 12345,
            "is_enabled": True,
            "preferences": {"vehicle_updates": True},
        }])

        # Even with Telegram failing, dispatch_event_notification completes and returns in-app notif
        result = await dispatch_event_notification(
            supabase=self.mock_supabase,
            user_id=self.user_a_id,
            title="Kendaraan Baru",
            message="Mobil Avanza berhasil ditambahkan",
            notification_type="vehicle_created",
            event_category="vehicle_updates",
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "Kendaraan Baru")


if __name__ == "__main__":
    unittest.main()
