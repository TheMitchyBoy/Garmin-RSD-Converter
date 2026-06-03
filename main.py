#!/usr/bin/env python3
"""
PaaS entry point (Railway, Render, etc.).

Railpack and similar builders look for ``main.py`` at the repo root. This
delegates to the sonar web application and reads ``PORT`` from the environment.
"""

from sonar_web_app import run_web_app

if __name__ == '__main__':
    run_web_app()
