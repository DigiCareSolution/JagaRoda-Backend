# Dokumentasi Sistem Notifikasi In-App & Telegram JagaRoda

Dokumen ini menjelaskan arsitektur, skema database, API endpoint, alur penautan akun Telegram, konfigurasi webhook, dan prosedur pengujian untuk sistem notifikasi di JagaRoda Backend.

---

## 1. Arsitektur Sistem

```
┌────────────────────────────────────────────────────────────────────────┐
│                        JagaRoda Backend (FastAPI)                      │
│                                                                        │
│   [Client / Frontend]                                                  │
│          │ (Bearer Token)                                              │
│          ▼                                                             │
│   ├── /notifications (List, Unread Count, Mark Read, Read All)         │
│   ├── /notifications/telegram/link-token (Generate One-Time Token)     │
│   ├── /notifications/telegram/status (Check Link & Preferences)        │
│   └── /notifications/telegram/preferences (Update Preferences)         │
│                                                                        │
│   [Telegram Webhook Endpoint]                                          │
│   └── POST /telegram/webhook                                           │
│          ▲ (X-Telegram-Bot-Api-Secret-Token Header)                    │
│          │                                                             │
│   [Telegram Bot API Servers]                                           │
│                                                                        │
│   [Core Business Events Integration]                                   │
│   ├── /register & /user/add (Account Updates)                          │
│   ├── /vehicle CRUD (Vehicle Updates)                                  │
│   └── /vehicle/{id}/photos (Photo Updates)                             │
│          │                                                             │
│          ▼ (dispatch_event_notification)                               │
│     ┌──────────────────────────────────────────────────────────────┐   │
│     │ 1. Simpan ke tabel 'notifications' (In-App)                  │   │
│     │ 2. Cek apakah user menautkan Telegram & mengaktifkannya      │   │
│     │ 3. Cek preferensi per kategori (vehicle / account / alert)   │   │
│     │ 4. Kirim Telegram via Bot API secara non-blocking            │   │
│     └──────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────┘
```

### Prinsip Keamanan & Ketahanan:
1. **Zero Impact on Business Operations:** Kegagalan pengiriman Telegram (timeout, network error, bot diblokir) tidak akan pernah menggagalkan operasi bisnis utama (misal: tambah kendaraan, upload foto, registrasi staf). Notifikasi in-app tetap tersimpan dengan aman.
2. **Strict User Isolation:** Seluruh endpoint notifikasi dan status Telegram diidentifikasi langsung dari token JWT Supabase (`require_auth`), tidak pernah dari query parameter atau body request yang dapat dimanipulasi (mencegah IDOR).
3. **Cryptographically Secure Tokens:** Token penautan akun Telegram digenerate secara acak menggunakan `secrets.token_urlsafe(32)`. Hanya hash SHA-256 yang disimpan di database.
4. **Single-Use & Expiry:** Token kedaluwarsa dalam 15 menit dan dikonsumsi secara atomic di database untuk mencegah replay attack / race condition.
5. **Webhook Authentication:** Permintaan webhook dari Telegram diverifikasi menggunakan header `X-Telegram-Bot-Api-Secret-Token` dengan perbandingan constant-time (`hmac.compare_digest`).

---

## 2. Skema Database

File migrasi database tersedia di: `migrations/001_notifications_and_telegram.sql`.

### Tabel 1: `public.notifications`
Menyimpan notifikasi persisten dalam aplikasi (in-app notifications).
- `id`: UUID (Primary Key, default `gen_random_uuid()`)
- `user_id`: UUID (Foreign Key ke `public.users(user_id)` ON DELETE CASCADE)
- `title`: VARCHAR(255) (Judul notifikasi)
- `message`: TEXT (Isi pesan)
- `type`: VARCHAR(50) (e.g. `vehicle_created`, `vehicle_updated`, `photo_uploaded`, `staff_added`)
- `related_entity_type`: VARCHAR(50) NULL (e.g. `vehicle`, `telegram_account`)
- `related_entity_id`: VARCHAR(100) NULL (ID entitas terkait)
- `action_url`: TEXT NULL (URL tujuan jika diklik di dashboard)
- `is_read`: BOOLEAN (Status sudah dibaca, default `FALSE`)
- `created_at`: TIMESTAMPTZ (Waktu dibuat, default UTC now)
- `read_at`: TIMESTAMPTZ NULL (Waktu saat dibaca)

### Tabel 2: `public.telegram_accounts`
Menyimpan data penautan akun Telegram pengguna JagaRoda.
- `id`: UUID (Primary Key, default `gen_random_uuid()`)
- `user_id`: UUID (UNIQUE, Foreign Key ke `public.users(user_id)` ON DELETE CASCADE)
- `telegram_chat_id`: BIGINT (UNIQUE, ID obrolan Telegram)
- `telegram_username`: VARCHAR(255) NULL (Username Telegram tanpa @)
- `first_name`: VARCHAR(255) NULL (Nama depan pengguna Telegram)
- `is_enabled`: BOOLEAN (Status aktif/nonaktif notifikasi Telegram, default `TRUE`)
- `preferences`: JSONB (Preferensi kategori, default `{"vehicle_updates": true, "account_updates": true, "system_alerts": true}`)
- `linked_at`: TIMESTAMPTZ (Waktu penautan)
- `updated_at`: TIMESTAMPTZ (Waktu pembaruan status)

### Tabel 3: `public.telegram_linking_tokens`
Menyimpan token sementara untuk proses penautan akun Telegram.
- `id`: UUID (Primary Key, default `gen_random_uuid()`)
- `token_hash`: VARCHAR(64) (UNIQUE, hash SHA-256 dari token mentah)
- `user_id`: UUID (Foreign Key ke `public.users(user_id)` ON DELETE CASCADE)
- `expires_at`: TIMESTAMPTZ (Waktu kedaluwarsa token)
- `is_used`: BOOLEAN (Status penggunaan, default `FALSE`)
- `used_at`: TIMESTAMPTZ NULL (Waktu token digunakan)
- `created_at`: TIMESTAMPTZ (Waktu pembuatan token)

---

## 3. Panduan Menjalankan Migrasi Database

Jalankan perintah SQL dari file `migrations/001_notifications_and_telegram.sql` melalui salah satu cara berikut:

### Opsi A: Melalui Dashboard Supabase (Direkomendasikan)
1. Buka dashboard proyek Supabase Anda.
2. Masuk ke menu **SQL Editor**.
3. Buat query baru, lalu salin seluruh isi dari `migrations/001_notifications_and_telegram.sql`.
4. Klik **Run** untuk mengeksekusi migrasi.

### Opsi B: Melalui Supabase CLI
```bash
supabase db push
# atau
psql -h db.your-project-ref.supabase.co -U postgres -d postgres -f migrations/001_notifications_and_telegram.sql
```

---

## 4. Konfigurasi Environment Variables

Tambahkan variabel berikut ke environment server backend / file `.env` (jangan commit file yang berisi nilai rahasia):

| Nama Variabel | Wajib/Opsional | Deskripsi |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Wajib untuk Telegram | Token bot yang diperoleh dari @BotFather di Telegram |
| `TELEGRAM_BOT_USERNAME` | Wajib untuk Deep Link | Username bot Telegram (contoh: `JagaRodaBot`, tanpa tanda `@`) |
| `TELEGRAM_WEBHOOK_SECRET` | Direkomendasikan | String acak rahasia untuk memvalidasi header webhook dari Telegram |

---

## 5. Ringkasan API Endpoints

### In-App Notifications

#### 1. `GET /notifications`
Mengambil daftar notifikasi pengguna yang terautentikasi (paginasi).
- **Auth:** `Bearer <token>`
- **Query Params:**
  - `limit`: integer (default: 20, max: 100)
  - `offset`: integer (default: 0)
  - `is_read`: boolean opsional (`true` / `false`)
  - `type`: string opsional (filter tipe event)
- **Response `200 OK`:**
  ```json
  {
    "status": "success",
    "data": [
      {
        "id": "e4f8d9b1-...",
        "user_id": "...",
        "title": "Kendaraan Baru Ditambahkan",
        "message": "Kendaraan Toyota Avanza (B 1234 ABC) berhasil ditambahkan ke armada.",
        "type": "vehicle_created",
        "related_entity_type": "vehicle",
        "related_entity_id": "1",
        "action_url": null,
        "is_read": false,
        "created_at": "2026-11-20T01:00:00Z",
        "read_at": null
      }
    ],
    "pagination": {
      "limit": 20,
      "offset": 0,
      "total": 1
    }
  }
  ```

#### 2. `GET /notifications/unread-count`
Menghitung jumlah notifikasi yang belum dibaca.
- **Auth:** `Bearer <token>`
- **Response `200 OK`:**
  ```json
  {
    "status": "success",
    "data": {
      "unread_count": 3
    }
  }
  ```

#### 3. `PATCH /notifications/{notification_id}/read`
Menandai notifikasi spesifik sebagai sudah dibaca.
- **Auth:** `Bearer <token>`
- **Response `200 OK`:**
  ```json
  {
    "status": "success",
    "message": "Notifikasi ditandai sebagai sudah dibaca"
  }
  ```

#### 4. `PATCH /notifications/read-all`
Menandai seluruh notifikasi milik pengguna sebagai sudah dibaca.
- **Auth:** `Bearer <token>`
- **Response `200 OK`:**
  ```json
  {
    "status": "success",
    "message": "5 notifikasi ditandai sebagai sudah dibaca",
    "data": {
      "updated_count": 5
    }
  }
  ```

---

### Telegram Account Linking & Preferences

#### 5. `POST /notifications/telegram/link-token`
Membuat token penautan akun dan mengembalikan deep link Telegram.
- **Auth:** `Bearer <token>`
- **Rate Limit:** Maksimal 1 permintaan setiap 10 detik per pengguna.
- **Response `201 Created`:**
  ```json
  {
    "status": "success",
    "message": "Tautan integrasi Telegram berhasil dibuat. Buka tautan untuk menghubungkan akun.",
    "data": {
      "deep_link": "https://t.me/JagaRodaBot?start=3o8V1j9_...",
      "expires_at": "2026-11-20T01:15:00+00:00",
      "expires_in_minutes": 15
    }
  }
  ```

#### 6. `GET /notifications/telegram/status`
Melihat status penautan akun Telegram dan preferensi notifikasi saat ini.
- **Auth:** `Bearer <token>`
- **Response `200 OK`:**
  ```json
  {
    "status": "success",
    "data": {
      "is_linked": true,
      "telegram_username": "yusron_dev",
      "is_enabled": true,
      "preferences": {
        "vehicle_updates": true,
        "account_updates": true,
        "system_alerts": true
      },
      "linked_at": "2026-11-20T00:50:00Z"
    }
  }
  ```

#### 7. `PATCH /notifications/telegram/preferences`
Memperbarui status aktif Telegram dan/atau preferensi per kategori.
- **Auth:** `Bearer <token>`
- **Request Body:**
  ```json
  {
    "is_enabled": true,
    "preferences": {
      "vehicle_updates": true,
      "account_updates": false,
      "system_alerts": true
    }
  }
  ```
- **Response `200 OK`:**
  ```json
  {
    "status": "success",
    "message": "Preferensi notifikasi Telegram berhasil diperbarui",
    "data": {
      "status": "success",
      "is_enabled": true,
      "preferences": {
        "vehicle_updates": true,
        "account_updates": false,
        "system_alerts": true
      }
    }
  }
  ```

#### 8. `DELETE /notifications/telegram/link`
Memutuskan tautan akun Telegram dari akun pengguna JagaRoda.
- **Auth:** `Bearer <token>`
- **Response `200 OK`:**
  ```json
  {
    "status": "success",
    "message": "Tautan akun Telegram berhasil dihapus"
  }
  ```

---

### Telegram Webhook

#### 9. `POST /telegram/webhook`
Endpoint penerima callback update dari server Telegram.
- **Auth:** Diverifikasi via header `X-Telegram-Bot-Api-Secret-Token`.
- **Fungsi:**
  - Menangani pesan `/start <token>` untuk verifikasi tautan akun.
  - Memvalidasi token, mencegah reuse, dan menautkan `telegram_chat_id`.
  - Mengirim pesan konfirmasi langsung ke chat Telegram pengguna.
- **Response `200 OK`:**
  ```json
  {
    "ok": true
  }
  ```

---

## 6. Alur Penautan Akun Telegram (Linking Flow)

```
[ Pengguna di Web Dashboard ]
           │
           │ 1. Klik tombol "Hubungkan Telegram"
           ▼
[ Frontend Web ] ──────── POST /notifications/telegram/link-token ──────▶ [ Backend ]
                                                                             │
                                                                             │ 2. Buat token acak,
                                                                             │    simpan hash SHA-256
                                                                             │    ke DB (15 menit)
                                                                             ▼
[ Frontend Web ] ◀─────── Return: deep_link (https://t.me/Bot?start=TOKEN) ─┘
           │
           │ 3. Arahkan pengguna membuka tautan deep link ke aplikasi Telegram
           ▼
[ Aplikasi Telegram Pengguna ]
           │
           │ 4. Pengguna menekan tombol "START" (mengirim /start TOKEN)
           ▼
[ Server Telegram ] ─── POST /telegram/webhook (update + secret header) ──▶ [ Backend ]
                                                                               │
                                                                               │ 5. Verifikasi secret header
                                                                               │ 6. Validasi hash token
                                                                               │ 7. Konsumsi token secara atomic
                                                                               │ 8. Tautkan chat_id ke user_id
                                                                               │ 9. Simpan in-app notification
                                                                               │ 10. Kirim pesan konfirmasi ke Telegram
                                                                               ▼
[ Pengguna di Telegram ] ◀──────── "Selamat! Akun berhasil ditautkan" ─────────┘
```

---

## 7. Cara Setup Webhook Telegram pada Backend

Setelah backend Anda dideploy dan memiliki domain publik (misalnya: `https://api.jagaroda.com`), daftarkan URL webhook ke Telegram Bot API:

Jalankan curl berikut (ganti `<YOUR_BOT_TOKEN>`, `<YOUR_BACKEND_URL>`, dan `<YOUR_WEBHOOK_SECRET>`):

```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://api.jagaroda.com/telegram/webhook",
    "secret_token": "<YOUR_WEBHOOK_SECRET>",
    "allowed_updates": ["message"]
  }'
```

Untuk memeriksa status webhook:
```bash
curl -s "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo"
```

---

## 8. Panduan Pengujian Manual

1. **Jalankan Aplikasi Backend:**
   ```bash
   uvicorn src.main:app --reload --port 8000
   ```
2. **Login & Ambil Bearer Token:**
   Kirim request ke `POST /login` dengan akun staf/admin Anda untuk mendapatkan `access_token`.
3. **Minta Token Penautan Telegram:**
   ```bash
   curl -X POST http://localhost:8000/notifications/telegram/link-token \
     -H "Authorization: Bearer <TOKEN>"
   ```
   Ambil nilai `deep_link` dari response.
4. **Buka Deep Link di Telegram:**
   Buka link tersebut di browser atau aplikasi Telegram, lalu tekan tombol **Start**.
5. **Cek Notifikasi In-App & Status:**
   - Cek `GET /notifications/telegram/status` -> pastikan `is_linked: true`.
   - Cek `GET /notifications` -> pastikan muncul notifikasi sukses "Telegram Berhasil Ditautkan".
6. **Lakukan Operasi Bisnis (Uji Real Event):**
   - Tambah kendaraan baru via `POST /vehicle`.
   - Periksa notifikasi in-app bertambah di `GET /notifications/unread-count`.
   - Pesan instan akan masuk langsung ke chat Telegram Anda!

---

## 9. Keterbatasan Saat Ini (Known Limitations)

1. **Localhost Webhook:** Telegram server tidak dapat mengirim webhook langsung ke `localhost` tanpa tunneling tool (seperti `ngrok` atau `Cloudflare Tunnels`). Untuk pengujian lokal, gunakan tunnel URL sebagai webhook URL atau gunakan unit test mock yang disediakan.
2. **Bulk Staff Broadcast:** Saat ini notifikasi ditargetkan kepada aktor yang melakukan operasi dan/atau staf terkait. Pengaturan broadcast ke seluruh admin dapat dikonfigurasi lebih lanjut sesuai kebijakan bisnis perusahaan.
