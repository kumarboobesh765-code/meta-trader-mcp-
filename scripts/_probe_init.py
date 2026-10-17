"""Checkpoint probe: where does mt5.initialize() block from an SSH session?"""
print("probe: start", flush=True)
import MetaTrader5 as mt5

print("probe: imported", flush=True)
ok = mt5.initialize(timeout=15000)
print("probe: init =", ok, "err =", mt5.last_error(), flush=True)
if ok:
    ai = mt5.account_info()
    print("probe: account =", ai, flush=True)
    mt5.shutdown()
print("probe: done", flush=True)
