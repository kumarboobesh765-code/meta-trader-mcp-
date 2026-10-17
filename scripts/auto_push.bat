@echo off
rem Daily workspace auto-sync: VPS snapshot -> refresh SESSION_STATE.md -> commit -> push.
rem Safe to run repeatedly: even with no repo changes, the snapshot block updates daily.
cd /d "%~dp0.."
python "%~dp0evening_snapshot.py"
git add -A
git diff-index --quiet HEAD --
if errorlevel 1 git commit -m "Evening auto-sync: workspace state %DATE% %TIME%"
if errorlevel 1 echo note: nothing to commit or commit failed
git push origin main
if errorlevel 1 echo push failed (check network/credentials)
