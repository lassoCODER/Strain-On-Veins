from rich.console import Console
from rich.text import Text

console = Console()

def log_info(message: str) -> None:
    console.print(f"[cyan]{message}[/cyan]")

def log_success(message: str) -> None:
    console.print(f"[green]{message}[/green]")

def log_warning(message: str) -> None:
    console.print(f"[yellow]{message}[/yellow]")

def log_error(message: str) -> None:
    console.print(f"[red]{message}[/red]")

def log_title(message: str) -> None:
    console.print(Text(message, style="bold magenta"))

def log_debug(message: str) -> None:
    console.print(f"[dim]{message}[/dim]")
