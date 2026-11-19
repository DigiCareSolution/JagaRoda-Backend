import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from src.main import app, get_supabase, require_auth


class TestAPIEndpoints(unittest.TestCase):
    def setUp(self):
        self.mock_supabase = MagicMock()
        self.user_id = "test-user-uuid-1234"

        # Override dependency for testing
        app.dependency_overrides[get_supabase] = lambda: self.mock_supabase
        app.dependency_overrides[require_auth] = lambda: (self.mock_supabase, self.user_id)
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_list_notifications(self):
        mock_table = MagicMock()
        self.mock_supabase.table.return_value = mock_table
        mock_query = MagicMock()
        mock_table.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.order.return_value = mock_query
        mock_query.range.return_value = mock_query
        mock_query.execute.return_value = MagicMock(data=[
            {"id": "n1", "title": "Test Title", "message": "Test Msg", "is_read": False}
        ], count=1)

        response = self.client.get("/notifications")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(len(data["data"]), 1)
        self.assertEqual(data["pagination"]["total"], 1)

    def test_unread_count(self):
        mock_table = MagicMock()
        self.mock_supabase.table.return_value = mock_table
        mock_query = MagicMock()
        mock_table.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.execute.return_value = MagicMock(count=7, data=[])

        response = self.client.get("/notifications/unread-count")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["data"]["unread_count"], 7)

    def test_mark_all_read(self):
        mock_table = MagicMock()
        self.mock_supabase.table.return_value = mock_table
        mock_update = MagicMock()
        mock_table.update.return_value = mock_update
        mock_update.eq.return_value = mock_update
        mock_update.execute.return_value = MagicMock(data=[{"id": "1"}, {"id": "2"}])

        response = self.client.patch("/notifications/read-all")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["data"]["updated_count"], 2)

    def test_mark_single_read_success(self):
        mock_table = MagicMock()
        self.mock_supabase.table.return_value = mock_table
        mock_update = MagicMock()
        mock_table.update.return_value = mock_update
        mock_update.eq.return_value = mock_update
        mock_update.execute.return_value = MagicMock(data=[{"id": "n1", "is_read": True}])

        response = self.client.patch("/notifications/n1/read")
        self.assertEqual(response.status_code, 200)

    def test_mark_single_read_not_found(self):
        mock_table = MagicMock()
        self.mock_supabase.table.return_value = mock_table
        mock_update = MagicMock()
        mock_table.update.return_value = mock_update
        mock_update.eq.return_value = mock_update
        mock_update.execute.return_value = MagicMock(data=[])

        response = self.client.patch("/notifications/invalid-id/read")
        self.assertEqual(response.status_code, 404)

    @patch("src.main.check_link_token_rate_limit", return_value=True)
    @patch.dict(os.environ, {"TELEGRAM_BOT_USERNAME": "JagaRodaBot"})
    def test_create_telegram_link_token(self, mock_rate_limit):
        mock_table = MagicMock()
        self.mock_supabase.table.return_value = mock_table
        mock_op = MagicMock()
        mock_table.update.return_value = mock_op
        mock_table.insert.return_value = mock_op
        mock_op.eq.return_value = mock_op
        mock_op.execute.return_value = MagicMock(data=[])

        response = self.client.post("/notifications/telegram/link-token")
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("deep_link", data["data"])

    def test_telegram_status(self):
        mock_table = MagicMock()
        self.mock_supabase.table.return_value = mock_table
        mock_query = MagicMock()
        mock_table.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.execute.return_value = MagicMock(data=[{
            "telegram_username": "yusron",
            "is_enabled": True,
            "preferences": {"vehicle_updates": True},
            "linked_at": "2026-11-20T00:00:00Z"
        }])

        response = self.client.get("/notifications/telegram/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["data"]["is_linked"])
        self.assertEqual(data["data"]["telegram_username"], "yusron")

    def test_webhook_invalid_secret(self):
        with patch.dict(os.environ, {"TELEGRAM_WEBHOOK_SECRET": "supersecret"}):
            response = self.client.post(
                "/telegram/webhook",
                headers={"X-Telegram-Bot-Api-Secret-Token": "wrongsecret"},
                json={"message": {"text": "/start"}}
            )
            self.assertEqual(response.status_code, 401)

    @patch("src.main.send_telegram_message", new_callable=AsyncMock)
    @patch("src.main.process_telegram_start", new_callable=AsyncMock)
    def test_webhook_valid_secret_and_start(self, mock_start, mock_send):
        mock_start.return_value = (True, "Akun berhasil ditautkan")
        mock_send.return_value = True

        with patch.dict(os.environ, {"TELEGRAM_WEBHOOK_SECRET": "supersecret"}):
            response = self.client.post(
                "/telegram/webhook",
                headers={"X-Telegram-Bot-Api-Secret-Token": "supersecret"},
                json={
                    "message": {
                        "chat": {"id": 12345},
                        "from": {"username": "tester"},
                        "text": "/start rawtoken123"
                    }
                }
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"ok": True})
            mock_start.assert_called_once()
            mock_send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
