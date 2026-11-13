# JagaRoda API

JagaRoda API is a serverless backend service built with **FastAPI** deployed on **Vercel Serverless Functions**. It integrates with **Supabase** for PostgreSQL database management and user authentication, providing secure REST endpoints with role-based access control (RBAC).

---

## Architecture & Tech Stack

- **Framework:** [FastAPI](https://fastapi.tiangolo.com/) (Python)
- **Deployment Platform:** [Vercel](https://vercel.com/) (Serverless Functions via `@vercel/python`)
- **Serverless Entrypoint:** `api/index.py` via `vercel.json` rewrites
- **Database & Auth:** [Supabase](https://supabase.com/) (PostgreSQL & Supabase GoTrue Auth)
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
SUPABASE_URL="https://your-project-ref.supabase.co"
SUPABASE_KEY="your-supabase-service-role-secret-key"
PORT=8000
```

> **Note:** `SUPABASE_KEY` must be the Supabase **Service Role Key** (secret) to perform administrative operations such as `supabase.auth.admin.create_user` and `delete_user`.

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
