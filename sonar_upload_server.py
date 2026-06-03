#!/usr/bin/env python3
"""
Backward-compatible entry point for the sonar web upload UI.

Prefer ``sonar_web_app`` / ``python sonar_cli.py serve`` for new deployments.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import List, Optional

from sonar_web_app import main as web_main, run_web_app

__all__ = ['run_server', 'main']


def run_server(
    host: str = '127.0.0.1',
    port: int = 8765,
    uploads_dir: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> None:
    """
    Start the web app (legacy signature).

    ``uploads_dir`` and ``output_dir`` are mapped under a shared data root.
    """
    if uploads_dir or output_dir:
        base = (uploads_dir or output_dir or Path('data')).resolve().parent
        if uploads_dir and output_dir and uploads_dir.resolve().parent != output_dir.resolve().parent:
            base = uploads_dir.resolve().parent
        data_dir = base
    else:
        data_dir = Path('data')

    run_web_app(host=host, port=port, data_dir=data_dir)


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    if argv is None:
        return web_main([
            '--host', '127.0.0.1',
            '--port', '8765',
            '--data-dir', 'data',
        ])
    return web_main(argv)


if __name__ == '__main__':
    sys.exit(main())
