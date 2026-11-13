"""Shared terminal styles. Never interpret user values as Rich markup."""

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text


def console(*, stderr=False):
    return Console(stderr=stderr, highlight=False)


def message(value, *, error=False):
    console(stderr=error).print(Text(str(value), style="red" if error else ""))


def _status_style(state):
    if str(state).startswith("removed"):
        return "dim bright_black"
    return {"running": "green", "unhealthy": "red"}.get(state, "yellow")


def table(title, columns, rows):
    view = Table(
        title=title,
        title_style="bold",
        title_justify="left",
        box=box.SIMPLE,
        header_style="bold cyan",
        padding=(0, 1),
        expand=False,
    )
    for column in columns:
        view.add_column(column, overflow="fold")
    for row in rows:
        cells = []
        for column, value in zip(columns, row, strict=True):
            style = "bold" if column in {"Name", "Dataset"} else ""
            if column == "Status":
                style = _status_style(value)
            cells.append(Text(str(value), style=style))
        view.add_row(*cells)
    console().print(view)


def status(name, state, uri):
    line = Text()
    line.append(str(name), style="bold")
    line.append(": ")
    line.append(str(state), style=_status_style(state))
    line.append(f" — {uri}", style="dim")
    console().print(line)
