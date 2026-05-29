@echo off
REM Docker CLI wrapper — runs Docker Engine inside WSL2 (Ubuntu on D:)
REM Replaces Docker Desktop. Fully supports "docker compose" and all subcommands.
wsl -d Ubuntu -- docker %*
