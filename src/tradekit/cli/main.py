"""`tk` entrypoint. Verbs are pure dispatch to deep modules (DESIGN §4.4).

Conventions: every verb honors --json for structured output; mutating verbs
exit non-zero on gate denial with the Verdict as payload; TK_RUN_ID stamps
the experiment registry (TD-20).
"""

from __future__ import annotations

import typer

import tradekit

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def _root() -> None:
    """tradekit — deterministic trading core for LLM agents."""


@app.command()
def version() -> None:
    """Print tradekit version."""
    typer.echo(f"tradekit {tradekit.__version__}")


if __name__ == "__main__":
    app()
