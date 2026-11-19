# JagaRoda API

JagaRoda API is a serverless backend service built with **FastAPI** deployed on **Vercel Serverless Functions**. It integrates with **Supabase** for PostgreSQL database management and user authentication, providing secure REST endpoints with role-based access control (RBAC).

---

## Architecture & Tech Stack

- **Framework:** [FastAPI](https://fastapi.tiangolo.com/) (Python)
- **Deployment Platform:** [Vercel](https://vercel.com/) (Serverless Functions via `@vercel/python`)
- **Serverless Entrypoint:** `api/index.py` via `vercel.json` rewrites
- **Database & Auth:** [Supabase](https://supabase.com/) (PostgreSQL & Supabase GoTrue Auth)
- **Object Storage:** [Cloudflare R2](https://www.cloudflare.com/developer-platform/r2/) (S3-compatible storage for vehicle photos)
- **CORS:** Enabled for cross-origin browser & mobile client access

---

## Features

- **Serverless Edge Performance:** Runs on Vercel Serverless Functions with automatic scaling and zero server maintenance.
- **Role-Based Access Control (RBAC):** Admin-guarded endpoints validated through Supabase Bearer token verification and database role validation.
- **Self-Registration & Admin Creation:** Dedicated endpoints for user self-registration (`/register`) and admin-managed staff creation (`/user/add`).
- **Transactional Rollback:** Safeguards user creation by rolling back Supabase Auth accounts if the accompanying database profile insertion fails.
- **Pagination & Query Optimization:** Paginated user queries with indexed sorting and `.limit(1)` optimization for single-row lookups.
- **Interactive OpenAPI Documentation:** Fully documented Swagger UI (`/docs`) and ReDoc (`/redoc`) with built-in Bearer authentication support.

---

## Project Structure

```text
JagaRoda-Backend/
├── .github/
│   └── workflows/
│       └── deploy.yml        # GitHub Actions CI workflow
├── api/
│   └── index.py              # Vercel serverless entrypoint
├── src/
│   └── main.py               # Main FastAPI application and route controllers
├── .env.example              # Environment variables template
├── .env                      # Local environment secrets (not committed to git)
├── vercel.json               # Vercel routing and rewrite configuration
├── requirements.txt          # Python dependencies for Vercel build
├── pyproject.toml            # Project metadata and package configuration
├── AGENTS.md                 # Antigravity agent workspace rules
└── README.md                 # Project documentation
```

---

## Prerequisites

Ensure the following tools are installed on your machine:
- **Python:** 3.11 or newer
- **pip** or **uv**
- Optional: **Vercel CLI** (`npm i -g vercel`)

---

## Configuration & Environment Variables

Copy `.env.example` to `.env` in the root directory for local development:

```bash
cp .env.example .env
```

Set the following variables:

```ini
# Supabase Configuration
SUPABASE_URL="https://your-project-ref.supabase.co"
SUPABASE_KEY="your-supabase-service-role-secret-key"
PORT=8000

# Cloudflare R2 Storage Configuration
R2_ACCOUNT_ID="your-cloudflare-account-id"
R2_ACCESS_KEY_ID="your-r2-access-key-id"
R2_SECRET_ACCESS_KEY="your-r2-secret-access-key"
R2_BUCKET_NAME="jagaroda-images"
R2_PUBLIC_URL="https://pub-your-id.r2.dev"
# R2_ENDPOINT_URL="https://your-account-id.r2.cloudflarestorage.com"
```

> **Note:**
> - `SUPABASE_KEY` must be the Supabase **Service Role Key** (secret) to perform administrative operations such as `supabase.auth.admin.create_user` and `delete_user`.
> - `R2_BUCKET_NAME` defaults to `jagaroda-images` if omitted. `R2_PUBLIC_URL` is recommended for serving public URLs (e.g. from an R2 public domain or custom CDN).

---

## Local Development

1. **Clone the repository:**
   ```bash
   git clone https://github.com/DigiCareSolution/JagaRoda-Backend.git
   cd JagaRoda-Backend
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Start the local server with auto-reload:**
   ```bash
   uvicorn src.main:app --reload --port 8000
   ```

   The server will start locally at:
   - **Base URL:** `http://localhost:8000`
   - **Interactive Swagger Docs:** `http://localhost:8000/docs`
   - **ReDoc Documentation:** `http://localhost:8000/redoc`

   Alternatively, you can run the Vercel local environment:
   ```bash
   vercel dev
   ```

---

## API Endpoints Reference

### 1. Health & Connection Test

#### `GET /`
Tests connectivity with Supabase by querying the database.

- **Response `200 OK`:**
  ```json
  {
    "status": "success",
    "message": "Connected to Supabase successfully! API keys and URL are working perfectly."
  }
  ```

#### `GET /count`
Simple arithmetic verification endpoint to test function execution.

- **Response `200 OK`:**
  ```json
  {
    "hasil": 15
  }
  ```

---

### 2. Authentication

#### `POST /login`
Authenticates a user with email and password and returns a session token pair.

- **Access Level:** Public
- **Headers:**
  ```http
  Content-Type: application/json
  ```

- **Request Body:**
  ```json
  {
    "email": "user@example.com",
    "password": "StrongPassword123!"
  }
  ```

- **Field Constraints:**
  - `email`: Valid email format (min: 5, max: 255 characters).
  - `password`: Minimum 8 characters, maximum 128 characters.

- **Response `200 OK`:**
  ```json
  {
    "status": "success",
    "message": "Login berhasil",
    "data": {
      "access_token": "<jwt_access_token>",
      "refresh_token": "<jwt_refresh_token>",
      "token_type": "bearer",
      "user": {
        "user_id": "c1f7a3f8-8c01-44ab-9921-123456789abc",
        "username": "johndoe",
        "role": "Staff",
        "phone": "081234567890",
        "created_at": "2026-11-10T08:30:00+00:00"
      }
    }
  }
  ```

- **Error Responses:**
  - `401 Unauthorized`: Invalid email or password.
  - `422 Unprocessable Entity`: Validation error (e.g. invalid email format).

---

### 3. User Management

#### `GET /user/me`
Returns the authenticated user's own profile.

- **Access Level:** Authenticated users (any role)
- **Headers:**
  ```http
  Authorization: Bearer <access_token>
  ```

- **Response `200 OK`:**
  ```json
  {
    "status": "success",
    "data": {
      "user_id": "c1f7a3f8-8c01-44ab-9921-123456789abc",
      "username": "johndoe",
      "role": "Staff",
      "phone": "081234567890",
      "created_at": "2026-11-10T08:30:00+00:00"
    }
  }
  ```

- **Error Responses:**
  - `401 Unauthorized`: Missing or expired Bearer token.
  - `404 Not Found`: Profile not found in the database.

#### `GET /user`
Fetches a list of registered users sorted by newest first with pagination.

- **Query Parameters:**
  | Parameter | Type | Default | Description |
  |---|---|---|---|
  | `limit` | `int` | `50` | Number of items to retrieve (min: 1, max: 100) |
  | `offset` | `int` | `0` | Number of items to skip |

- **Response `200 OK`:**
  ```json
  {
    "status": "success",
    "data": [
      {
        "user_id": "c1f7a3f8-8c01-44ab-9921-123456789abc",
        "username": "johndoe",
        "role": "Staff",
        "phone": "081234567890",
        "created_at": "2026-11-10T08:30:00+00:00"
      }
    ]
  }
  ```

#### `GET /user/{user_id}`
Fetches the profile of a single user by their unique UUID.

- **Path Parameters:**
  - `user_id` (`string`): The Supabase user UUID.

- **Response `200 OK`:**
  ```json
  {
    "status": "success",
    "data": {
      "user_id": "c1f7a3f8-8c01-44ab-9921-123456789abc",
      "username": "johndoe",
      "role": "Staff",
      "phone": "081234567890",
      "created_at": "2026-11-10T08:30:00+00:00"
    }
  }
  ```

- **Response `404 Not Found`:**
  ```json
  {
    "detail": "User not found"
  }
  ```

#### `POST /register` (alias: `POST /user/register`)
Self-registration endpoint for new users.

- **Access Level:** **Public** (No authentication required)
- **Headers:**
  ```http
  Content-Type: application/json
  ```

- **Request Body:**
  ```json
  {
    "email": "user@example.com",
    "password": "StrongPassword123!",
    "username": "newuser",
    "phone": "081234567890",
    "role": "Staff"
  }
  ```

- **Field Constraints:**
  - `email`: Valid email format (min: 5, max: 255 characters).
  - `password`: Minimum 8 characters, maximum 128 characters.
  - `username`: Minimum 1 character, maximum 50 characters.
  - `phone`: Optional (`varchar/string`). Aliases accepted: `phone_number`, `no_hp`.
  - `role`: Optional (default: `"Staff"`). Registering with role `"Admin"` is strictly forbidden.

- **Response `201 Created`:**
  ```json
  {
    "status": "success",
    "message": "Registrasi berhasil",
    "data": {
      "user_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
      "username": "newuser",
      "role": "Staff",
      "phone": "081234567890",
      "created_at": "2026-11-13T08:00:00+00:00"
    }
  }
  ```

- **Error Responses:**
  - `400 Bad Request`: Email already registered, duplicate username, or failed database insertion.
  - `422 Unprocessable Entity`: Validation error (e.g. invalid email format, short password, or passing `Admin` as role).

#### `POST /user/add`
Creates a new `Staff` user account in Supabase Auth and inserts the corresponding profile into `public.users`.

- **Access Level:** **Admin Only**
- **Headers:**
  ```http
  Authorization: Bearer <admin_access_token>
  Content-Type: application/json
  ```

- **Request Body:**
  ```json
  {
    "email": "staff.member@example.com",
    "password": "StrongPassword123!",
    "username": "staffmember",
    "phone": "081234567890"
  }
  ```

- **Field Constraints:**
  - `email`: Valid email format (min: 5, max: 255 characters).
  - `password`: Minimum 8 characters, maximum 128 characters.
  - `username`: Minimum 1 character, maximum 50 characters.
  - `phone`: Optional (`varchar/string`). Aliases accepted: `phone_number`, `no_hp`.

- **Response `201 Created`:**
  ```json
  {
    "status": "success",
    "message": "Staff berhasil ditambahkan",
    "data": {
      "user_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
      "username": "staffmember",
      "role": "Staff",
      "phone": "081234567890",
      "created_at": "2026-11-11T06:45:00+00:00"
    }
  }
  ```

---

### 4. Vehicle Management

#### `GET /vehicle` (alias: `GET /vehicles`)
Fetches a paginated list of vehicles with associated photos, newest first.

- **Access Level:** Public
- **Query Parameters:**
  | Parameter | Type | Default | Description |
  |---|---|---|---|
  | `limit` | `int` | `50` | Maximum number of records (1-100) |
  | `offset` | `int` | `0` | Number of records to skip |
  | `status` | `string` | `null` | Filter by status (`Available`, `Rented`, `In Maintenance`) |
  | `search` | `string` | `null` | Search plat nomor, merk, or tipe |

- **Response `200 OK`:**
  ```json
  {
    "status": "success",
    "data": [
      {
        "vehicle_id": 1,
        "plat_nomor": "B 1234 ABC",
        "merk": "Toyota",
        "tipe": "Avanza 1.3 G",
        "tahun": 2023,
        "warna": "Hitam",
        "nomor_stnk": "STNK-123456",
        "tarif_per_hari": 350000.0,
        "status": "Available",
        "deskripsi": "Kondisi prima, servis rutin",
        "created_at": "2026-11-19T08:00:00+00:00",
        "vehicle_photos": [
          {
            "photo_id": 10,
            "vehicle_id": 1,
            "photo_url": "https://pub-id.r2.dev/vehicles/1/abc123.jpg",
            "photo_type": "Exterior",
            "created_at": "2026-11-19T08:05:00+00:00"
          }
        ]
      }
    ]
  }
  ```

#### `GET /vehicle/{vehicle_id}` (alias: `GET /vehicles/{vehicle_id}`)
Fetches complete vehicle details by `vehicle_id` including its photos.

- **Access Level:** Public
- **Response `200 OK`:**
  ```json
  {
    "status": "success",
    "data": {
      "vehicle_id": 1,
      "plat_nomor": "B 1234 ABC",
      "merk": "Toyota",
      "tipe": "Avanza 1.3 G",
      "tahun": 2023,
      "warna": "Hitam",
      "nomor_stnk": "STNK-123456",
      "tarif_per_hari": 350000.0,
      "status": "Available",
      "deskripsi": "Kondisi prima, servis rutin",
      "created_at": "2026-11-19T08:00:00+00:00",
      "vehicle_photos": []
    }
  }
  ```

- **Response `404 Not Found`:**
  ```json
  {
    "detail": "Kendaraan tidak ditemukan"
  }
  ```

#### `POST /vehicle` (alias: `POST /vehicles`)
Creates a new vehicle record.

- **Access Level:** Authenticated users (Staff / Admin)
- **Headers:**
  ```http
  Authorization: Bearer <access_token>
  Content-Type: application/json
  ```

- **Request Body:**
  ```json
  {
    "plat_nomor": "B 1234 ABC",
    "merk": "Toyota",
    "tipe": "Avanza 1.3 G",
    "tahun": 2023,
    "warna": "Hitam",
    "nomor_stnk": "STNK-123456",
    "tarif_per_hari": 350000.0,
    "status": "Available",
    "deskripsi": "Kondisi mulus dan terawat"
  }
  ```

- **Field Constraints:**
  - `plat_nomor`: Required (3-20 characters, automatically uppercase & trimmed). Unique.
  - `merk`: Required (1-50 characters).
  - `tipe`: Required (1-50 characters).
  - `tahun`: Optional integer (1900-2100).
  - `warna`: Optional string (max 30 characters).
  - `nomor_stnk`: Optional string (max 50 characters).
  - `tarif_per_hari`: Optional float (>= 0, default: 0.0).
  - `status`: Optional (`Available`, `Rented`, `In Maintenance`, default: `Available`).
  - `deskripsi`: Optional text.

- **Response `201 Created`:**
  ```json
  {
    "status": "success",
    "message": "Kendaraan berhasil ditambahkan",
    "data": {
      "vehicle_id": 1,
      "plat_nomor": "B 1234 ABC",
      "merk": "Toyota",
      "tipe": "Avanza 1.3 G",
      "tahun": 2023,
      "warna": "Hitam",
      "nomor_stnk": "STNK-123456",
      "tarif_per_hari": 350000.0,
      "status": "Available",
      "deskripsi": "Kondisi mulus dan terawat",
      "created_at": "2026-11-19T08:00:00+00:00"
    }
  }
  ```

#### `PUT /vehicle/{vehicle_id}` (or `PATCH /vehicle/{vehicle_id}`)
Updates vehicle attributes.

- **Access Level:** Authenticated users (Staff / Admin)
- **Headers:**
  ```http
  Authorization: Bearer <access_token>
  Content-Type: application/json
  ```

- **Request Body:** (Pass only fields to update)
  ```json
  {
    "status": "Rented",
    "tarif_per_hari": 380000.0
  }
  ```

- **Response `200 OK`:**
  ```json
  {
    "status": "success",
    "message": "Data kendaraan berhasil diperbarui",
    "data": { ... }
  }
  ```

#### `DELETE /vehicle/{vehicle_id}` (alias: `DELETE /vehicles/{vehicle_id}`)
Deletes a vehicle and automatically deletes all associated photos from Cloudflare R2 and database.

- **Access Level:** Authenticated users (Staff / Admin)
- **Headers:**
  ```http
  Authorization: Bearer <access_token>
  ```

- **Response `200 OK`:**
  ```json
  {
    "status": "success",
    "message": "Kendaraan berhasil dihapus"
  }
  ```

#### `POST /vehicle/{vehicle_id}/photos` (alias: `POST /vehicles/{vehicle_id}/photos`)
Uploads a vehicle photo to Cloudflare R2 bucket (`jagaroda-images`) and saves metadata to `public.vehicle_photos`.

- **Access Level:** Authenticated users (Staff / Admin)
- **Headers:**
  ```http
  Authorization: Bearer <access_token>
  Content-Type: multipart/form-data
  ```

- **Form Fields:**
  - `file`: Image file (`image/jpeg`, `image/png`, `image/webp`, `image/gif`, `image/heic`).
  - `photo_type`: Optional string (`Exterior`, `Interior`, `Other`, default: `Other`).

- **Response `201 Created`:**
  ```json
  {
    "status": "success",
    "message": "Foto kendaraan berhasil diunggah",
    "data": {
      "photo_id": 1,
      "vehicle_id": 1,
      "photo_url": "https://pub-your-id.r2.dev/vehicles/1/6a1f8e91e6b94c39864293f7e53f14ad.jpg",
      "photo_type": "Exterior",
      "created_at": "2026-11-19T08:15:00+00:00"
    }
  }
  ```

#### `DELETE /vehicle/{vehicle_id}/photos/{photo_id}`
Deletes a specific photo from Cloudflare R2 and removes the database record.

- **Access Level:** Authenticated users (Staff / Admin)
- **Headers:**
  ```http
  Authorization: Bearer <access_token>
  ```

- **Response `200 OK`:**
  ```json
  {
    "status": "success",
    "message": "Foto kendaraan berhasil dihapus"
  }
  ```

---

## Deployment to Vercel

### Option A: Via Vercel Web Dashboard (Recommended)

1. **Push your code to GitHub:**
   ```bash
   git add .
   git commit -m "Configure deployment for Vercel"
   git push origin main
   ```
2. **Go to [vercel.com](https://vercel.com/)** and log in.
3. Click **"Add New..."** > **"Project"**.
4. Import your **`JagaRoda-Backend`** repository.
5. In the **Environment Variables** section, add:
   - `SUPABASE_URL` = `https://your-project-ref.supabase.co`
   - `SUPABASE_KEY` = `your-supabase-service-role-key`
   - `R2_ACCOUNT_ID` = `your-cloudflare-account-id`
   - `R2_ACCESS_KEY_ID` = `your-r2-access-key-id`
   - `R2_SECRET_ACCESS_KEY` = `your-r2-secret-access-key`
   - `R2_BUCKET_NAME` = `jagaroda-images`
   - `R2_PUBLIC_URL` = `https://pub-your-id.r2.dev` (optional)
6. Click **Deploy**. Vercel will install dependencies from `requirements.txt` and deploy your FastAPI endpoints.

---

### Option B: Via Vercel CLI

1. **Install Vercel CLI:**
   ```bash
   npm i -g vercel
   ```
2. **Log in and deploy:**
   ```bash
   vercel
   ```
3. **Add environment variables to Vercel:**
   ```bash
   vercel env add SUPABASE_URL
   vercel env add SUPABASE_KEY
   ```
4. **Deploy to production:**
   ```bash
   vercel --prod
   ```
