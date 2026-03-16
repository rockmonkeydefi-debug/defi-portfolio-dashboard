# Security Audit Report — DeFi Portfolio Dashboard

**Date:** 2026-03-16  
**Scope:** Full application (web_portfolio.py, connectors, storage, frontend, Docker)  
**Overall Risk Score:** 5.5 / 10 (Medium)  
**Posture:** Acceptable for single-user self-hosted; needs hardening for multi-user or public exposure.

---

## Executive Summary

| Severity | Count |
|----------|-------|
| Critical | 3 |
| High | 5 |
| Medium | 7 |
| Low | 6 |

The application has solid authentication fundamentals (bcrypt, global auth middleware, rate limiting) but has gaps in API key exposure, session management, security headers, and input validation. No SQL injection was found — all DB queries use parameterized statements. The biggest risks are credential exposure via the config API and the ephemeral Flask secret key.

---

## Critical Findings

### C1. API Keys Returned in Plaintext

**Severity:** Critical | **CWE:** CWE-200 (Information Exposure)  
**File:** `web_portfolio.py:1602-1612`

```python
@app.route('/api/config', methods=['GET'])
def api_get_config():
    return jsonify({
        "etherscan_api_key": os.getenv("ETHERSCAN_API_KEY", ""),
        "openai_api_key": os.getenv("OPENAI_API_KEY", ""),
        "aws_bearer_token": os.getenv("AWS_BEARER_TOKEN_BEDROCK", ""),
        "zerion_api_key": os.getenv("ZERION_API_KEY", ""),
    })
```

**Why it matters:** Any authenticated user (or XSS payload) can read all API keys in full. The frontend settings page already has a `maskKey()` function but the backend sends unmasked values.

**Fix:**
```python
def _mask(val):
    if not val or len(val) < 8:
        return "****" if val else ""
    return val[:4] + "•" * (len(val) - 8) + val[-4:]

@app.route('/api/config', methods=['GET'])
def api_get_config():
    return jsonify({
        "etherscan_api_key": _mask(os.getenv("ETHERSCAN_API_KEY", "")),
        "openai_api_key": _mask(os.getenv("OPENAI_API_KEY", "")),
        "aws_bearer_token": _mask(os.getenv("AWS_BEARER_TOKEN_BEDROCK", "")),
        "zerion_api_key": _mask(os.getenv("ZERION_API_KEY", "")),
        # Frontend uses masked display; full values never leave the server
    })
```

**Test:** `curl -b session=... http://localhost:5001/api/config` — should return masked values.

---

### C2. Ephemeral Flask Secret Key

**Severity:** Critical | **CWE:** CWE-330 (Insufficient Randomness)  
**File:** `web_portfolio.py:49`

```python
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(32).hex())
```

**Why it matters:** If `FLASK_SECRET_KEY` is not in `.env`, a new random key is generated on every app restart. This invalidates all sessions (users get logged out) and in Docker, every `docker compose up` generates a new key. More critically, if an attacker can predict the key (e.g., via timing), they can forge session cookies.

**Fix:** Add to `.env.example` and generate on first run in `entrypoint.sh`:
```bash
# In entrypoint.sh, after .env creation:
if ! grep -q "FLASK_SECRET_KEY" "$CONFIG_DIR/.env"; then
  echo "FLASK_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')" >> "$CONFIG_DIR/.env"
  echo "Generated FLASK_SECRET_KEY"
fi
```

---

### C3. No CSRF Protection on Login/Setup Forms

**Severity:** Critical | **CWE:** CWE-352 (Cross-Site Request Forgery)  
**Files:** `templates/login.html:19-22`, `templates/setup.html:19-23`

```html
<form method="POST" action="/login">
  <input type="password" name="password" ...>
  <button type="submit">Sign In</button>
</form>
```

**Why it matters:** An attacker can craft a page that auto-submits a login form, potentially setting a known password during first-time setup.

**Fix:** Add Flask-WTF or a manual CSRF token:
```python
# In login_page():
if request.method == 'GET':
    token = secrets.token_hex(32)
    session['csrf_token'] = token
    return render_template('login.html', csrf_token=token)
if request.method == 'POST':
    if request.form.get('csrf_token') != session.get('csrf_token'):
        return render_template('login.html', error="Invalid request")
```

---

## High Priority Findings

### H1. No Security Headers

**Severity:** High | **CWE:** CWE-693 (Protection Mechanism Failure)  
**File:** `web_portfolio.py` (missing)

**Fix:**
```python
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    if request.is_secure:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response
```

### H2. No Session Timeout

**Severity:** High | **CWE:** CWE-613 (Insufficient Session Expiration)  
**File:** `web_portfolio.py:49`

Sessions are permanent with no expiry. A stolen session cookie works forever.

**Fix:**
```python
app.permanent_session_lifetime = timedelta(hours=24)
```

### H3. No Request Size Limit

**Severity:** High | **CWE:** CWE-400 (Resource Exhaustion)  
**File:** `web_portfolio.py` (missing)

The `/api/backup/config` POST endpoint accepts file uploads with no size limit.

**Fix:**
```python
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB
```

### H4. Password Change Endpoint Missing Current Password Verification When No Password Set

**Severity:** High | **CWE:** CWE-306 (Missing Authentication)  
**File:** `web_portfolio.py:1441-1462`

When no password is set (`pw_hash` is empty), the `bcrypt.checkpw` is skipped, allowing anyone to set a password. However, the `require_auth` middleware redirects to setup in this case, so the risk is limited to the setup flow.

**Exploitability:** Low — only during initial setup before a password exists.

### H5. In-Memory Rate Limiting Resets on Restart

**Severity:** High | **CWE:** CWE-307 (Improper Restriction of Excessive Auth Attempts)  
**File:** `web_portfolio.py:57-75`

```python
_login_attempts = {}  # ip -> (count, first_attempt_time)
```

Restarting the app clears all rate limit state. An attacker can trigger a restart (if they can cause a crash) to reset limits.

**Mitigation:** For a single-user self-hosted app, this is acceptable. For production, use Flask-Limiter with a persistent backend (Redis/SQLite).

---

## Medium Priority Findings

### M1. Weak Password Policy (6 chars minimum)
**File:** `web_portfolio.py:1447` | **CWE:** CWE-521  
Recommend: 8+ chars, or use passphrase guidance.

### M2. No Audit Logging
**CWE:** CWE-778  
No logging of login attempts, config changes, wallet additions, or backup downloads.

### M3. Exception Details Leaked to Client
**File:** `web_portfolio.py:1667`
```python
return jsonify({"error": str(e)}), 500
```
Stack traces/internal errors returned to the client. Use generic error messages in production.

### M4. Backup Database Downloaded Unencrypted
**File:** `web_portfolio.py:2521-2595`  
The `/api/backup/db` endpoint serves the raw SQLite file. Consider encrypting or password-protecting exports.

### M5. No Subresource Integrity on CDN Scripts
**File:** `templates/index.html:9`
```html
<script src="https://unpkg.com/lucide@latest/dist/umd/lucide.min.js"></script>
```
Pin version and add SRI hash. Using `@latest` means a compromised CDN could inject malicious code.

### M6. Config Export Includes All Secrets
**File:** `web_portfolio.py:2596-2633`  
`/api/backup/config` exports all `.env` values including API keys and password hash as plaintext JSON.

### M7. No Input Length Validation on Wallet Labels/Notes
**File:** `web_portfolio.py:1549, 1685`  
User-provided text stored without length limits. Could be used for storage exhaustion.

---

## Low Priority Findings

### L1. `debug=True` in zerion_server.py
**File:** `zerion_server.py:31` — Dev tool, gitignored, not deployed.

### L2. No `HttpOnly` flag explicitly set on session cookie
Flask sets `HttpOnly` by default, but `Secure` flag is not set for non-HTTPS.

### L3. Inconsistent API timeouts (5s, 10s, 30s, 120s, 300s)
Various external API calls use different timeouts. Standardize.

### L4. No health check endpoint for Docker
Add `GET /health` for container orchestration.

### L5. Single gunicorn worker
`--workers 1` in Dockerfile. Fine for single-user, but limits throughput.

### L6. `wallet_config.json` permissions not restricted
File is world-readable by default in the container.

---

## Checklist

| Check | Status |
|-------|--------|
| SQL Injection | **Pass** — All queries use parameterized statements |
| XSS | **Pass** — Frontend uses `esc()` consistently; Jinja2 auto-escapes |
| CSRF | **Fail** — No CSRF tokens on forms |
| Authentication bypass | **Pass** — Global `before_request` middleware covers all routes |
| Session management | **Partial** — No timeout, no session regeneration after login |
| Password storage | **Pass** — bcrypt with salt |
| API key exposure | **Fail** — Full keys returned via `/api/config` |
| Security headers | **Fail** — None set |
| Rate limiting | **Partial** — Login only, in-memory |
| Input validation | **Partial** — Wallet addresses validated, other inputs less so |
| Error handling | **Partial** — Some endpoints leak exception details |
| Encryption at rest | **Fail** — SQLite and .env unencrypted |
| HTTPS enforcement | **N/A** — Handled by reverse proxy (not app responsibility) |
| Dependency pinning | **Partial** — requirements.txt uses `>=` not `==` |
| Docker secrets | **Fail** — Uses .env files, not Docker secrets |
| Audit logging | **Fail** — No logging of sensitive operations |

---

## Top 5 Prioritized Fixes

1. **Mask API keys in `/api/config` response** — Eliminates credential exposure with a 5-line change
2. **Generate persistent `FLASK_SECRET_KEY`** — 3-line entrypoint.sh change, fixes session instability
3. **Add security headers** — Single `@after_request` handler, broad protection
4. **Add session timeout** — One-line config change
5. **Pin Lucide CDN version with SRI** — Prevents supply chain attacks

---

*Report generated from manual code review. No automated scanning tools were used. Findings should be verified in a staging environment before applying fixes.*
