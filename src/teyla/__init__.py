"""Teyla — an operating system for working with AI agents."""
__version__ = "0.31.0"

# The one-sentence promise. bare `teyla` prints it, AGENTS.md opens with it and pyproject.toml uses it as
# the package description; tests/test_agents_md.py fails when they drift apart.
PROMISE = (
    "Teyla reads your Claude Code and Codex sessions on your Mac, shows what they cost and what's waiting on you, "
    "and fixes the waste. Nothing about your sessions leaves your Mac unless you turn it on."
)


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


def prompts_dir():
    """The paste-able prompts: inside the installed package, or the repo root from a checkout.
    Shipped with the code so an agent follows the prompt that matches the installed version,
    never whatever `main` says today."""
    import pathlib
    here = pathlib.Path(__file__).resolve().parent
    for cand in (here / "prompts", here.parents[1] / "prompts"):
        if (cand / "onboard.md").is_file():
            return cand
    raise FileNotFoundError("teyla prompts directory not found")
