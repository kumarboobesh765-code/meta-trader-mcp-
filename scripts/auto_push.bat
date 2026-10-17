@echo off
rem Daily workspace auto-sync: commit any new/changed files and push to origin/main.
rem Safe to run repeatedly: empty tree -> nothing committed (empty tree)
rem Repo root is one level above this script's folder.
cd /d "%~dp0.."
git add -A
git diff-index --quiet HEAD --
if errorlevel 1 git commit -m "Auto-sync workspace state %DATE% %TIME%"
if errorlevel 1 echo commit failed (check git identity)
git push origin main
if errorlevel 1 echo push failed (check network/credentials)
