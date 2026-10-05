# 2kFX MT5 bridge

A small, authenticated HTTP service that runs on **Windows** beside the MetaTrader 5 terminal. It exposes the operations in [`docs/MT5_BRIDGE_PROTOCOL.md`](../docs/MT5_BRIDGE_PROTOCOL.md) (protocol v1) to the 2kFX trading engine.

```
2kFX trading engine ──HTTPS/HMAC──► mt5_bridge (Windows) ──IPC──► MetaTrader 5 terminal ──► Broker
```

What the bridge does:

* Every request, including `/v1/health`, needs an HMAC-SHA256 signature. The timestamp must be within ±30 s, and each nonce is accepted only once in 120 s. Every response carries a signature as well.
* Every call to the `MetaTrader5` package runs on **one worker thread**. Reads time out after 10 s and trade requests after 30 s.
* `POST /v1/orders` and `POST /v1/positions/{id}/close` are **idempotent** by `client_order_id`. A SQLite journal records each ID, and the journal survives restarts. If the outcome of a request is unknown, the bridge answers `504 outcome_unknown` and never resends it blindly.
* All times are converted from trade-server time to real UTC (`BROKER_SERVER_UTC_OFFSET`).

It holds no strategy or risk logic.

---

## 1. Windows setup

The steps below assume the folder `C:\mt5_bridge`. Copy the `mt5_bridge/` directory of the repository there.

### 1.1 Install Python 3.11

1. Download **Python 3.11 (64-bit)** from <https://www.python.org/downloads/windows/>. The `MetaTrader5` package needs 64-bit Python.
2. In the installer, tick **"Add python.exe to PATH"**, then choose *Install Now*.
3. Open a new PowerShell window and check the version:
   ```powershell
   py -3.11 --version
   ```

### 1.2 Install and prepare the MetaTrader 5 terminal

1. Install MT5 **from your broker's website**, because that build has the broker's servers preconfigured. The generic MetaQuotes build also works if you add the server by hand.
2. Start the terminal and **log in once** with the trading account (*File → Login to Trade Account*). Tick "Save password" if you want the terminal to reconnect on its own after a restart.
3. Turn on algorithmic trading:
   * Click the **Algo Trading** button in the toolbar until it is green.
   * Go to *Tools → Options → Expert Advisors* and tick **"Allow algorithmic trading"**. If "Disable algorithmic trading when the account has been changed" or "…when the profile has been changed" is ticked, untick it, or remember to re-enable Algo Trading after switching accounts.
4. Leave the terminal running. The bridge talks to the terminal over local IPC, so the terminal must run **in the same Windows user session** as the bridge (see §3).

### 1.3 Install the bridge

```powershell
cd C:\mt5_bridge
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\pip install -e .
```

On Windows this also installs the `MetaTrader5` package.

### 1.4 Configure

Generate a secret:

```powershell
.venv\Scripts\python -c "import secrets;print(secrets.token_urlsafe(48))"
```

Then create `.env` from the template and fill it in:

```powershell
copy .env.example .env
notepad .env
```

| Variable | Default | Notes |
|---|---|---|
| `BRIDGE_SECRET` | *(required)* | 32 characters or more. The 2kFX trading engine must use the **same** value (entered in Add Broker). |
| `BRIDGE_HOST` | `127.0.0.1` | Bind address. Use the Tailscale/WireGuard IP (or `0.0.0.0` together with a firewall rule and TLS) when 2kFX runs on another machine. |
| `BRIDGE_PORT` | `8710` | |
| `BRIDGE_ALLOWED_IPS` | *(empty = any)* | Comma-separated IPs or CIDRs, e.g. `100.64.0.7,10.8.0.0/24`. |
| `BRIDGE_SSL_CERTFILE` / `BRIDGE_SSL_KEYFILE` | | Enables HTTPS. You can also pass `--ssl-certfile` / `--ssl-keyfile`. |
| `MT5_TERMINAL_PATH` | | Full path to `terminal64.exe`. Needed only when several terminals are installed. |
| `MT5_MAGIC` | `20250` | Magic number written on every bridge order. |
| `BROKER_SERVER_UTC_OFFSET` | `auto` | `auto`, or fixed hours such as `+3` (see §6). |
| `JOURNAL_PATH` | `mt5_bridge_journal.sqlite3` | The idempotency journal. **Keep it on a persistent disk and do not delete it** while trades may still be in flight. |
| `READ_TIMEOUT_SECONDS` / `TRADE_TIMEOUT_SECONDS` / `CONNECT_TIMEOUT_SECONDS` | `10` / `30` / `90` | |

The bridge never logs or stores the account password. `POST /v1/session/connect` passes it straight to the terminal.

### 1.5 Run

```powershell
.venv\Scripts\mt5-bridge
# or, with explicit options:
.venv\Scripts\mt5-bridge --env-file .env --host 100.64.0.5 --port 8710 --ssl-certfile certs\bridge.crt --ssl-keyfile certs\bridge.key
# or use the launcher script:
powershell -ExecutionPolicy Bypass -File scripts\start_bridge.ps1
```

The bridge writes JSON-lines logs to stdout, one line per request, each with a `request_id`. The same id is returned in the `X-Request-ID` response header.

### 1.6 Verify

`scripts/check_bridge.py` uses only the standard library. It signs a `GET /v1/health` request and checks the signature on the response:

```powershell
.venv\Scripts\python scripts\check_bridge.py
# remote / TLS:
python scripts\check_bridge.py --url https://100.64.0.5:8710 --cafile certs\bridge.crt
python scripts\check_bridge.py --path /v1/account
```

A healthy result prints `HTTP 200  response signature: valid` and shows `"initialized": true, "connected": true` under `terminal`.

---

## 2. Network exposure and TLS

Recommended, in this order:

1. **Private network (best).** Install [Tailscale](https://tailscale.com/) or WireGuard on both the Windows host and the 2kFX host. Set `BRIDGE_HOST` to the Windows host's tailnet IP (for example `100.64.0.5`) and `BRIDGE_ALLOWED_IPS` to the 2kFX host's tailnet IP. Traffic is encrypted by the tunnel, and nothing is exposed to the internet.
2. **HTTPS with a self-signed certificate.** Generate the certificate with OpenSSL, which is available through Git for Windows or on the 2kFX host:
   ```bash
   openssl req -x509 -newkey rsa:3072 -sha256 -days 825 -nodes \
     -keyout bridge.key -out bridge.crt -subj "/CN=mt5-bridge" \
     -addext "subjectAltName=IP:203.0.113.10,DNS:mt5-bridge"
   ```
   Copy both files to `C:\mt5_bridge\certs\`, set `BRIDGE_SSL_CERTFILE` and `BRIDGE_SSL_KEYFILE`, and give the 2kFX trading engine `bridge.crt` as its trusted CA. Do not skip verification.
3. **SSH tunnel.** Keep `BRIDGE_HOST=127.0.0.1` and forward the port from the 2kFX host with `ssh -L 8710:127.0.0.1:8710 user@windows-host`.

Plain HTTP is acceptable only on `127.0.0.1` or inside one of these tunnels.

**Firewall.** Open the port only for the 2kFX host's IP, from an elevated PowerShell:

```powershell
New-NetFirewallRule -DisplayName "2kFX MT5 bridge" -Direction Inbound -Protocol TCP `
  -LocalPort 8710 -RemoteAddress 203.0.113.20 -Action Allow -Profile Any
```

Replace `203.0.113.20` with the 2kFX host's IP, and set `BRIDGE_ALLOWED_IPS` to the same address for defence in depth.

---

## 3. Running unattended

The MT5 terminal is a GUI application. The `MetaTrader5` package reaches it over IPC **inside the same interactive Windows session**. A Windows *service* runs in session 0 and can neither see a terminal started by a logged-in user nor run one reliably. For that reason:

* Run the bridge **as the same user who runs the terminal, in that user's interactive session.**
* On a VPS, enable auto-logon for that user (Sysinternals *Autologon*). Put the MT5 terminal in the user's Startup folder, and start the bridge at logon.
* When you disconnect from RDP, **do not log off**. Close the RDP window, or run `tscon %sessionname% /dest:console`, so the session and the terminal keep running.

### Option A: Task Scheduler at logon (recommended)

```powershell
$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -File C:\mt5_bridge\scripts\start_bridge.ps1 -LogToFile" `
  -WorkingDirectory "C:\mt5_bridge"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
  -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries
Register-ScheduledTask -TaskName "2kFX MT5 bridge" -Action $action -Trigger $trigger `
  -Settings $settings -RunLevel Limited `
  -Principal (New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive)
```

Logs are written to `C:\mt5_bridge\logs\bridge.log`.

### Option B: NSSM

[NSSM](https://nssm.cc/) can supervise the process. Configure it to run **as the terminal's user account** (not LocalSystem), and keep in mind the session-0 limitation above. NSSM works when the terminal is started by the same service account or is already running in that account's session. Otherwise prefer Option A.

```powershell
nssm install MT5Bridge C:\mt5_bridge\.venv\Scripts\mt5-bridge.exe --env-file C:\mt5_bridge\.env
nssm set MT5Bridge AppDirectory C:\mt5_bridge
nssm set MT5Bridge ObjectName .\traderuser "<windows-password>"
nssm set MT5Bridge AppStdout C:\mt5_bridge\logs\bridge.log
nssm set MT5Bridge AppStderr C:\mt5_bridge\logs\bridge.log
nssm set MT5Bridge AppRotateFiles 1
nssm set MT5Bridge AppRotateBytes 10485760
nssm set MT5Bridge Start SERVICE_AUTO_START
nssm start MT5Bridge
```

Run **exactly one** bridge process per terminal. Every MT5 call is serialised inside that one process, and the idempotency journal must not be shared between processes.

---

## 4. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `503 not_connected` with broker code `-10005`/`-10004`/`-10003` ("IPC timeout", "IPC initialize failed") | The terminal is not running, is still starting, or runs in another user or session, or under a different elevation (admin vs non-admin). Start the terminal as the same user without "Run as administrator", or run both elevated. If several terminals are installed, set `MT5_TERMINAL_PATH` to the right `terminal64.exe`. The first `initialize` after a terminal start can take up to a minute. |
| Orders fail with `409 rejected`, `broker_code: 10027` ("Autotrading disabled by client terminal") | The **Algo Trading** button is off, or *Tools → Options → Expert Advisors → Allow algorithmic trading* is unticked. Switching accounts can turn it off again. |
| `broker_code: 10026` | The broker or server has disabled automated trading for the account. Contact the broker. |
| `400 broker_auth_failed` on `/v1/session/connect` | Wrong login, password or **server name**. The server must match exactly what the terminal shows in *File → Login to Trade Account*, e.g. `ICMarketsSC-Demo`, not the broker's display name. Log in once by hand in the terminal so it learns the server's addresses. |
| `/v1/health` shows `connected: false` | The terminal is running but has no connection to the trade server (network, wrong server, or account disabled). Check the bottom-right connection indicator in the terminal. |
| Candles or deals return `503 "server time offset unknown"` | `BROKER_SERVER_UTC_OFFSET=auto` measures the offset from live ticks. It can't do that while the market is closed (weekends) until it has measured once. After a successful measurement the value is stored in the journal DB and survives restarts. Wait for the market to open, or set a fixed value such as `BROKER_SERVER_UTC_OFFSET=+3`. |
| Candle times are shifted by 1 h around DST changes | With a fixed offset you must update it yourself when the broker's server switches DST (most use UTC+2 in winter and UTC+3 in summer). `auto` re-measures every hour. |
| `401 unauthorized` "Timestamp outside the allowed window" | The clocks differ by more than 30 s. Enable time sync on both hosts (`w32tm /resync`). |
| `401 unauthorized` "Invalid signature" | The secret differs between backend and bridge, or a proxy rewrote the path or query. The signature covers the exact path and query string that was sent. |
| `504 outcome_unknown` on an order | The terminal didn't confirm the trade. **Do not resend with a new id.** Call `GET /v1/orders/lookup/{client_order_id}` or repeat the same `POST` (same id), and the bridge reconciles from MT5. |
| `symbol_unavailable` | The broker uses suffixed names (`EURUSD.m`, `EURUSDm`). Use `GET /v1/symbols` to see the exact names. |

---

## 5. Protocol notes for the backend client

* **Signature input.** `METHOD\nPATH_WITH_QUERY\nTIMESTAMP\nNONCE\nsha256hex(body)`. Sign the **exact bytes** you send. The response signature is `HMAC(secret, request_nonce\nstatus\nsha256hex(response_body))`. For requests rejected before a well-formed nonce could be read, the response is signed with an empty nonce.
* **Idempotency.** A repeated `client_order_id` returns the stored result, **including stored `409` errors**, without contacting the broker. If a request never reached `order_send` (validation error, `not_connected`, `symbol_unavailable`, position not found), nothing is journaled and the same id can be retried. Reusing an id for a *different* operation (an order id for a close, or another position) returns `422 invalid_request`.
* **Lookup.** `GET /v1/orders/lookup/{id}` returns:
  * `200` with the result when it is found in the journal or in MT5;
  * `404 not_found` only when the bridge has **no** journal record and MT5 has nothing;
  * `504 outcome_unknown` while a journaled attempt still can't be resolved.
  A stored rejection is reported as `status: "REJECTED"`. Results recovered from MT5 have `broker_code: null`.
* **Modify semantics.** For `.../modify`, a field that is **absent** keeps its current value. `stop_loss` or `take_profit` set to **null** removes it. For an order, `price` null means keep. Modify, cancel and position modify return `504 outcome_unknown` on timeout, because they change orders.
* **Close.** `POST /v1/positions/{id}/close` also accepts an optional `max_slippage_points` (default `MT5_DEFAULT_DEVIATION_POINTS`).
* **Time offset.** Only candles and deals fail with `503 "server time offset unknown"`. Health reports `server_utc_offset_seconds: null` while the offset is unknown. Positions, orders and quotes still answer, and report times with offset 0 until the offset is known.
* **Order comment.** The MT5 comment is the `client_order_id`, followed by `" " + comment` when a comment is given, truncated to 31 characters. On read, the client order id is taken from the first word of the comment.
* **Body limit.** A request body over 64 KiB gets `422 invalid_request`.

---

## 6. Development (any OS)

The tests use an in-memory fake of the `MetaTrader5` package (`tests/fake_mt5.py`), so they run on macOS and Linux:

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy
```

Layout: `config.py` (settings), `auth.py` (HMAC, nonce cache, signing middleware), `terminal.py` (single-thread MT5 executor), `service.py` (operations, idempotency, reconciliation), `mapping.py` (MT5 → protocol JSON, retcodes), `timeutil.py` (server-time offset), `journal.py` (SQLite), `app.py` (`create_app(settings, mt5_module=None)`).
