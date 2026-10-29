# JagaRoda API: Serverless Image Uploads 🚀

This repository contains the backend service for handling vehicle image uploads. It runs entirely on **Cloudflare Workers** using **FastAPI**, stores physical images in **Cloudflare R2**, and saves metadata in a **Supabase PostgreSQL** database.

## 🏗 Architecture
- **Framework:** FastAPI (Python)
- **Runtime:** Cloudflare Workers (via Pyodide/WebAssembly)
- **Storage:** Cloudflare R2 (S3-compatible object storage)
- **Database:** Supabase (PostgreSQL via REST API)

---

## 📋 Prerequisites
Before you begin, ensure you have the following:
1. Node.js installed (for the `wrangler` CLI).
2. Python 3.12+ installed.
3. A [Cloudflare](https://dash.cloudflare.com/) account.
4. A [Supabase](https://supabase.com/) account.

---