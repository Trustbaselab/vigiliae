# -*- coding: utf-8 -*-
"""Vigiliae CLI: `vigiliae` runs the server; `vigiliae init` runs the installer."""
import sys

from .app import main as app_main


def cli(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("init", "install"):
        from .install import main as install_main
        return install_main(argv[1:])
    return app_main()


if __name__ == "__main__":
    raise SystemExit(cli())
