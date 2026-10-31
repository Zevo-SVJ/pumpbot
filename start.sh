#!/bin/sh
cd /workspace/pumpbot; nohup venv/bin/python bot.py >> bot.log 2>&1 & echo $! > bot.pid; echo started $(cat bot.pid)
