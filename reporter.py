"""
Reporter che genera report degli errori trovati
"""
import json
from pathlib import Path
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from models import ValidationResult, Correction, CorrectionType

console = Console()


class Reporter:
    """Genera report dei risultati della validazione"""

    def __init__(self, output_dir: Path = None):
        self.output_dir = output_dir or Path("output")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def print_validation_result(self, result: ValidationResult, question_text: str = ""):
        """Stampa il risultato di una singola validazione"""
        if result.is_correct:
            console.print(f"[green]OK[/green] - Domanda {result.question_id}")
        else:
            console.print(f"[red]ERRORE[/red] - Domanda {result.question_id}")
            console.print(f"  [yellow]Tipo errore:[/yellow] {result.correction_type.value}")
            console.print(f"  [yellow]Messaggio:[/yellow] {result.error_message}")
            if result.suggested_correction:
                console.print(f"  [cyan]Correzione suggerita:[/cyan] {result.suggested_correction}")
            console.print(f"  [dim]Ragionamento: {result.solver_result.reasoning[:200]}...[/dim]")
        console.print()

    def print_summary(self, results: list[ValidationResult]):
        """Stampa un riepilogo dei risultati"""
        total = len(results)
        correct = sum(1 for r in results if r.is_correct)
        errors = total - correct

        table = Table(title="Riepilogo Validazione")
        table.add_column("Metrica", style="cyan")
        table.add_column("Valore", style="magenta")

        table.add_row("Totale domande", str(total))
        table.add_row("Corrette", f"[green]{correct}[/green]")
        table.add_row("Con errori", f"[red]{errors}[/red]" if errors > 0 else "[green]0[/green]")
        table.add_row("Percentuale corrette", f"{(correct/total*100):.1f}%" if total > 0 else "N/A")

        console.print(table)

        # Riepilogo per tipo di errore
        if errors > 0:
            error_types = {}
            for r in results:
                if not r.is_correct:
                    error_type = r.correction_type.value
                    error_types[error_type] = error_types.get(error_type, 0) + 1

            console.print("\n[bold]Errori per tipo:[/bold]")
            for error_type, count in error_types.items():
                console.print(f"  - {error_type}: {count}")

    def save_report(
        self,
        results: list[ValidationResult],
        corrections: list[Correction],
        filename: str = None
    ) -> Path:
        """Salva il report completo in formato JSON"""
        filename = filename or f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        report_path = self.output_dir / filename

        report = {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total": len(results),
                "correct": sum(1 for r in results if r.is_correct),
                "errors": sum(1 for r in results if not r.is_correct)
            },
            "results": [
                {
                    "question_id": r.question_id,
                    "is_correct": r.is_correct,
                    "correction_type": r.correction_type.value,
                    "error_message": r.error_message,
                    "suggested_correction": r.suggested_correction,
                    "solver_reasoning": r.solver_result.reasoning,
                    "solver_answer": r.solver_result.calculated_answer,
                    "solver_confidence": r.solver_result.confidence,
                    "matching_letter": r.solver_result.matching_letter
                }
                for r in results
            ],
            "corrections": [c.model_dump() for c in corrections]
        }

        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        console.print(f"\n[green]Report salvato in:[/green] {report_path}")
        return report_path

    def create_progress_bar(self, total: int, description: str = "Elaborazione"):
        """Crea una progress bar per il processing"""
        return Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console
        )
