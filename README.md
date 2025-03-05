# Embervale - Local Setup

This README only covers how to run the app on your local machine.

## Prerequisites

- Python 3.11+
- Node.js 18+ and npm
- Docker Desktop (optional, only needed for Redis or full Docker startup)
- A Gemini API key: [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)

## 1) Clone and enter the project

```bash
git clone <your-repo-url>
cd dnd-ai
```

## 2) Configure environment variables

Copy the example env file and set your Gemini key.

### macOS/Linux

```bash
cp .env.example .env
```

### Windows PowerShell

```powershell
Copy-Item .env.example .env
```

Open `.env` and set at least:

```env
GEMINI_API_KEY=your_key_here
```

## 3) Set up Python backend

### macOS/Linux

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 4) (Optional but recommended) Start Redis

The app can fall back if Redis is unavailable, but Redis is recommended.

```bash
docker run -d --name embervale-redis -p 6379:6379 redis:7-alpine
```

## 5) Start the app

```bash
python wsgi.py
```

App URL:

- `http://localhost:5000`

On first startup, the SQLite database is created automatically.

## 6) Create a demo user (optional)

```bash
flask seed-user
```

Demo credentials:

- `demo@embervale.local`
- `demo-pass`

## Frontend dev mode (optional)

If you want to run the Vite frontend separately for development:

```bash
cd frontend
npm install
npm run dev
```

## Docker-only startup (alternative)

```bash
docker compose up --build
```

Then open:

- `http://localhost:5000`
