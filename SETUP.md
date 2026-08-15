# Social Graph — Setup & Configuration Guide

This guide covers setting up **Social Graph** as a self-contained application using the Web Dashboard or environment variables.

---

## 1. Quick Launch (Web Dashboard)

The easiest way to get started is using the built-in web UI:

```bash
# 1. Initialize the SQLite workspace
sg init

# 2. Launch the Web UI
sg web
```

Navigate to `http://localhost:8080` in your browser. On your first launch, an interactive **Onboarding Wizard** will assist you with:
- Configuring your **Groq API key**
- Configuring your **Local LLM server** (vLLM, llama.cpp, Ollama, etc.)
- Configuring **LinkedIn access** (Email/Password or Session Cookie)
- Uploading your LinkedIn Saved Posts JSON

---

## 2. API Keys & Services

### A. Groq API Key (Required)

Groq powers heavy reasoning tasks such as taxonomy synthesis, Leiden community detection, and graph layout.

1. Go to [console.groq.com](https://console.groq.com).
2. Sign in or create a free account.
3. Navigate to **API Keys** → **Create API Key**.
4. Copy the key (starts with `gsk_...`).
5. Enter it into the **Settings** page in the Web UI, or set `SG_GROQ_API_KEY` in `.env`.

---

### B. LinkedIn Credentials & Session Cookie (Optional)

Needed only if you plan to scrape posts or comments live rather than uploading an exported JSON file.

#### Method 1: Email & Password
Enter your LinkedIn login email and password in the **Settings** page or `.env`. Playwright handles automated browser login.

#### Method 2: Session Cookie (`li_at`)
Using your session cookie avoids multi-factor authentication (MFA) prompts.

**How to extract `li_at` cookie:**
1. Open your browser and log into [LinkedIn](https://www.linkedin.com).
2. Open Developer Tools (`F12` or `Ctrl+Shift+I` / `Cmd+Option+I`).
3. Click on the **Application** tab (Chrome/Brave/Edge) or **Storage** tab (Firefox).
4. In the left panel, expand **Cookies** → click `https://www.linkedin.com`.
5. Locate the cookie named `li_at`.
6. Copy its **Value** (a long alphanumeric string).
7. Paste it into **Settings** → **LinkedIn** → **Session Cookie** in the Web UI or set `SG_LINKEDIN_COOKIE` in `.env`.

---

### C. LinkedIn Saved Items JSON Export

If you prefer not to log in with browser automation, you can download your saved posts directly from LinkedIn:

1. Log into LinkedIn.
2. Go to **Settings & Privacy** → **Data Privacy** → **Get a copy of your data**.
3. Select **Want something in particular?** and check **Saved items**.
4. Request the archive. LinkedIn will send an email with a download link within a few minutes.
5. Extract `linkedin_saved_posts.json` from the zip file.
6. Drag & drop the JSON file directly into the **Settings** page file uploader in Social Graph Web UI.

---

### D. Local LLM / vLLM Server (Optional)

Social Graph supports any OpenAI-compatible server for batch post classification and topic mapping (e.g. `Qwen/Qwen3.5-9B-FP8`).

Supported backends:
- **vLLM** (Supports `/v1/chat/completions/batch` for maximum throughput)
- **llama.cpp / Ollama / LM Studio** (Auto-detected: if `/batch` is absent, Social Graph seamlessly uses concurrent async requests)

In Web UI **Settings** → **Local Model Server**:
- **Base URL**: e.g., `http://localhost:8000` or an ngrok/cloud URL.
- **Model ID**: The exact model identifier registered on your server (e.g., `Qwen/Qwen3.5-9B-FP8`).

---

## 3. Storage & Encryption

- **Database**: All configuration set via the Web UI is stored in `.socialgraph/socialgraph.db`.
- **Encryption**: API keys and passwords are encrypted at rest using Fernet encryption with a machine-local derived key.
- **Precedence**: Settings configured via Web UI take precedence over environment variables or `.env` files.
