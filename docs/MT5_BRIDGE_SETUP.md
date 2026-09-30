# Connecting MetaTrader 5 (demo first)

```
2kFX backend (Mac/Linux/Windows) ──HTTPS or private tunnel, HMAC-signed──► mt5_bridge (Windows) ──► MT5 terminal ──► broker
```

The `MetaTrader5` Python package only works on **Windows**, next to a running MT5 terminal. You need:

* A Windows PC or Windows VPS (a VPS close to your broker's servers is ideal) with the MT5 terminal installed and **logged in** to a **demo** account.
* Python 3.11 (64-bit) on that machine.
* Network reachability from the 2kFX backend to the bridge. **Tailscale or WireGuard is strongly recommended.** Otherwise use HTTPS with a certificate and a firewall rule limited to the backend's IP.

## 1. On the Windows machine

Follow **[mt5_bridge/README.md](../mt5_bridge/README.md)** step by step. It covers Python, the terminal (turn on *Algo Trading*), installing the bridge, generating `BRIDGE_SECRET`, TLS, the firewall, running at logon with Task Scheduler (the terminal needs an interactive session, so a Windows service won't work), verification and troubleshooting.

Quick version:

```powershell
cd C:\mt5_bridge
py -3.11 -m venv .venv
.venv\Scripts\pip install -e .
copy .env.example .env      # set BRIDGE_SECRET (≥32 random chars), BRIDGE_HOST, BRIDGE_PORT
.venv\Scripts\mt5-bridge
.venv\Scripts\python scripts\check_bridge.py     # signed /v1/health check
```

## 2. In 2kFX

1. **Brokers → Add broker → MetaTrader 5 (via 2kFX MT5 Bridge) → DEMO**.
2. Enter these values:
   * **Bridge URL**, e.g. `https://100.64.0.12:8710` (Tailscale IP) or `http://127.0.0.1:8710` if the backend runs on the same Windows machine.
   * **Bridge secret**: the same `BRIDGE_SECRET`. It is encrypted and never shown again.
   * **MT5 account number**, **password** (encrypted) and **server**, exactly as MT5 shows it (e.g. `ICMarketsSC-Demo`).
3. **Test connection**. 2kFX logs in through the bridge and reads the account. It refuses to continue unless the **broker reports DEMO**.
4. Choose a risk profile and **Save**. The account is saved with trading **disabled**.
5. **Markets → From MT5** downloads real history for backtests. **Strategies → Assign** runs a strategy on the demo account.

## What 2kFX does on your MT5 account

* Market orders with a stop loss, a take profit and a maximum deviation (slippage), tagged with the 2kFX client order ID in the comment.
* Position modifications and closes that you trigger, or the emergency stop with "close all".
* Reconciliation reads positions, orders and 7 days of deal history so it can detect SL/TP exits and outcomes that were uncertain.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| *Cannot reach MT5 bridge* | Bridge not running, wrong URL or port, firewall, or the tunnel is down |
| *Bridge refused our signature — check BRIDGE_SECRET and clocks* | Secret mismatch, or clocks more than 30 s apart. Enable NTP on both machines |
| *MT5 terminal not connected to the trade server* | Terminal closed, not logged in, or no internet on the Windows machine |
| *broker_auth_failed* | Wrong login, password or server name |
| *You selected DEMO, but the broker reports a LIVE account* | You entered a real-money login. Nothing was saved |
| *server time offset unknown* | Market closed and the offset was never measured. Set `BROKER_SERVER_UTC_OFFSET` on the bridge (e.g. `+3`) |
| Orders rejected "AutoTrading disabled" | Turn on **Algo Trading** in the terminal |

## What has been verified without Windows

* The bridge's full test suite (108 tests) runs against a realistic fake `MetaTrader5` module.
* The backend client is tested against the real bridge app (contract tests).
* A live server check of `/v1/health` with signed requests and responses.

**Not yet verified:** a real MT5 terminal and a real broker demo account. That is your first step (see [ROADMAP.md](ROADMAP.md)).
