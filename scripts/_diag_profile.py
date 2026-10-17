r"""One-off diagnostic: why did most FTTest charts fail to load at 15:57?

Dumps (all robust, no shell quoting involvement):
  1. every 'create new frame' failure line in today's terminal journal
  2. MT5 build numbers for every session start today (auto-update check)
  3. terminal64.exe version + file mtime
  4. byte-level diff of the <expert> block: chart03.chr (12:26 batch)
     vs chart17.chr (15:55 batch)
"""

import io
import os
import re

TERM = (r"C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal"
        r"\D0E8209F77C8CF37AD8BF550E51FF075")
TLOG = os.path.join(TERM, "logs", "20260926.log")
PROF = os.path.join(TERM, "MQL5", "Profiles", "Charts", "FTTest")


def read_utf16(path):
    return io.open(path, encoding="utf-16", errors="replace").read()


j = read_utf16(TLOG)
lines = j.splitlines()

print("=== create-frame failures (all, today) ===")
fails = [l for l in lines if "create new frame" in l]
print("total failure lines today: %d" % len(fails))
for l in fails:
    m = re.search(r"(\d\d:\d\d:\d\d)\.\d+\s+Document\s+create new frame "
                  r"(.+CHARTS.FTTEST.+)$", l, re.I)
    if m:
        print("  %s  %s" % (m.group(1), os.path.basename(m.group(2))))

print("=== terminal session starts (build numbers) ===")
for l in lines:
    if "MetaTrader 5" in l and ("build" in l.lower() or "starting" in l.lower()):
        print("  " + l.strip()[:160])

print("=== terminal64.exe version/mtime ===")
exe = r"C:\Program Files\MetaTrader 5\terminal64.exe"
try:
    st = os.stat(exe)
    print("  mtime:", st.st_mtime, " size:", st.st_size)
except OSError as e:
    print("  stat failed: %r" % e)


def expert_block(path):
    t = read_utf16(path)
    i = t.find("<expert>")
    j = t.find("</expert>")
    return t[i:j] if i >= 0 and j > i else t[:400]


print("=== <expert> block diff: chart03 (12:26) vs chart17 (15:55) ===")
b3 = expert_block(os.path.join(PROF, "chart03.chr"))
b17 = expert_block(os.path.join(PROF, "chart17.chr"))
l3 = b3.replace("\r\n", "\n").split("\n")
l17 = b17.replace("\r\n", "\n").split("\n")
import difflib
for line in difflib.unified_diff(l3, l17, "chart03", "chart17", lineterm=""):
    print("  " + line)

print("=== header (non-expert) diff ===")
def head_block(path):
    t = read_utf16(path)
    return t[:t.find("<expert>")].replace("\r\n", "\n").split("\n")
h3 = head_block(os.path.join(PROF, "chart03.chr"))
h17 = head_block(os.path.join(PROF, "chart17.chr"))
for line in difflib.unified_diff(h3, h17, "chart03", "chart17", lineterm=""):
    print("  " + line)
