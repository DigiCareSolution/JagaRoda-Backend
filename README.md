# JagaRoda API

JagaRoda API is a serverless backend service built with **FastAPI** running on **Cloudflare Workers** (using Python Workers via WebAssembly/Pyodide). It integrates with **Supabase** for PostgreSQL database management and user authentication, and connects to **Cloudflare R2** for object storage.

---

## Architecture & Tech Stack

- **Framework:** [FastAPI](https://fastapi.tiangolo.com/) (Python)
- **Runtime:** [Cloudflare Python Workers](https://developers.cloudflare.com/workers/languages/python/) (Pyodide / WASM ASGI entrypoint via `workers.asgi`)
- **Database & Auth:** [Supabase](https://supabase.com/) (PostgreSQL & Supabase Auth GoTrue)
- **Object Storage:** [Cloudflare R2](https://developers.cloudflare.com/r2/) (S3-compatible storage via bucket binding)
- **Deployment:** [Wrangler](https://developers.cloudflare.com/workers/wrangler/) / `pywrangler` via GitHub Actions CI/CD

---

## Features

- **Serverless Edge Performance:** Runs globally on Cloudflare's edge network with near-zero cold start latency.
- **Supabase Client Caching:** In-memory client caching per worker isolate to eliminate redundant client initialization across warm requests.
- **Role-Based Access Control (RBAC):** Admin-guarded endpoints validated through Supabase Bearer token verification and database role validation.
- **Transactional Rollback:** Safeguards user creation by rolling back Supabase Auth accounts if the accompanying database profile insertion fails.
- **Pagination & Query Optimization:** Paginated user queries with indexed sorting and `.limit(1)` optimization for single-row lookups.
- **Interactive OpenAPI Documentation:** Fully documented Swagger UI (`/docs`) and ReDoc (`/redoc`) with built-in Bearer authentication support.

---

## Project Structure

```text
JagaRoda-Backend/
├── .github/
│   └── workflows/
│       └── deploy.yml        # GitHub Actions automated deployment workflow
├── src/
│   └── main.py               # Main FastAPI application & Cloudflare Worker entrypoint
├── .dev.vars                 # Local environment secrets (not committed to git)
├── pyproject.toml            # Python dependencies and project configuration
├── wrangler.toml             # Cloudflare Workers configuration & R2 bindings
└── README.md                 # Project documentation
```

---

## Prerequisites

Ensure the following tools are installed on your machine:
- **Python:** 3.12 or newer
- **Node.js:** v18 or newer (required for the Wrangler CLI)
- **Package Manager:** `pip` or `uv`

---

## Configuration & Environment Variables

Cloudflare Workers use `.dev.vars` for local development secrets and Cloudflare Dashboard / GitHub Secrets for production.

Create a `.dev.vars` file in the root directory:

```ini
SUPABASE_URL="https://your-project-ref.supabase.co"
SUPABASE_KEY="your-supabase-service-role-secret-key"
```

> **Note:** `SUPABASE_KEY` must be the Supabase **Service Role Key** (secret) to perform administrative operations such as `supabase.auth.admin.create_user` and `delete_user`.

### Wrangler Configuration (`wrangler.toml`)

The Worker binding is configured in `wrangler.toml`:

```toml
name = "jagaroda-api"
main = "src/main.py"
compatibility_date = "2026-10-27"
compatibility_flags = ["python_workers"]

[[r2_buckets]]
binding = "IMAGE_BUCKET"
bucket_name = "jagaroda-images"
```

---

## Local Development

1. **Clone the repository:**
   ```bash
   git clone https://github.com/DigiCareSolution/JagaRoda-Backend.git
   cd JagaRoda-Backend
   ```

2. **Install tools & dependencies:**
   ```bash
   pip install uv
   pip install workers-py
   ```

3. **Start the local development server:**
   ```bash
   npx wrangler dev
   # or
   pywrangler dev
   ```

   The server will start locally at:
   - **Base URL:** `http://localhost:8787`
   - **Interactive Swagger Docs:** `http://localhost:8787/docs`
   - **ReDoc Documentation:** `http://localhost:8787/redoc`

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
Simple arithmetic verification endpoint to test worker execution.

- **Response `200 OK`:**
  ```json
  {
    "hasil": 15
  }
  ```

---

### 2. User Management

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
    "username": "staffmember"
  }
  ```

- **Field Constraints:**
  - `email`: Valid email format (min: 5, max: 255 characters).
  - `password`: Minimum 8 characters, maximum 128 characters.
  - `username`: Minimum 1 character, maximum 50 characters.

- **Response `201 Created`:**
  ```json
  {
    "status": "success",
    "message": "Staff berhasil ditambahkan",
    "data": {
      "user_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
      "username": "staffmember",
      "role": "Staff",
      "created_at": "2026-11-11T06:45:00+00:00"
    }
  }
  ```

- **Error Responses:**
  - `401 Unauthorized`: Missing or expired Bearer token.
  - `403 Forbidden`: Authenticated user does not possess the `Admin` role.
  - `400 Bad Request`: Email already registered or invalid input payload.

---

## Authentication & Authorization Lifecycle

```
Client Request (Bearer Token)
       │
       ▼
[require_admin Dependency]
       │
       ├─► 1. Verify JWT via Supabase Auth (supabase.auth.get_user)
       │      └─► Fail: 401 Unauthorized
       │
       ├─► 2. Check Role in public.users table (role == "Admin")
       │      └─► Fail: 403 Forbidden
       │
       ▼
[add_user Controller]
       │
       ├─► 1. Create Auth User in Supabase (supabase.auth.admin.create_user)
       │
       ├─► 2. Insert Profile into public.users (role = "Staff")
       │
       └─► On Profile Failure ──► Rollback: Delete Auth User (delete_user)
```

---

## Deployment

Continuous Deployment is managed via **GitHub Actions** (`.github/workflows/deploy.yml`).

Every push to the `main` branch automatically triggers deployment:
1. Sets up the Python runtime.
2. Installs `uv` and `workers-py`.
3. Deploys using `pywrangler deploy` to Cloudflare Workers.

### Required GitHub Secrets:
Add the following repository secrets under **Settings > Secrets and variables > Actions**:
- `CLOUDFLARE_API_TOKEN`: Cloudflare API Token with Workers edit permissions.
- `CLOUDFLARE_ACCOUNT_ID`: Cloudflare Account ID.
