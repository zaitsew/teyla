"""Teyla — an operating system for working with AI agents."""
__version__ = "0.9.0"


def templates_dir():
    """The templates directory: inside the installed package, or the repo root when run from a checkout."""
    import pathlib
    here = pathlib.Path(__file__).resolve().parent
    for cand in (here / "templates", here.parents[1] / "templates"):
        if cand.is_dir():
            return cand
    raise FileNotFoundError("teyla templates directory not found")


def plugin_dir():
    """The Claude Code plugin directory: inside the installed package, or the repo root when run from a checkout."""
    import pathlib
    here = pathlib.Path(__file__).resolve().parent
    for cand in (here / "plugin", here.parents[1] / "plugin"):
        if (cand / ".claude-plugin" / "plugin.json").exists():
            return cand
    raise FileNotFoundError("teyla plugin directory not found")
