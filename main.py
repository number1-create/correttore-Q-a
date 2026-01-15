#!/usr/bin/env python3
"""
Correttore Q&A - Applicazione per validare e correggere quiz a risposta multipla
usando AI per calcolare le risposte corrette.

Uso:
    python main.py input.json                    # Valida le domande
    python main.py input.json --auto-correct     # Valida e corregge automaticamente
    python main.py input.json --background       # Esegue in background
"""
import argparse
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.table import Table

from processor import QAProcessor
from models import ValidationResult, Correction

console = Console()


def print_banner():
    """Stampa il banner dell'applicazione"""
    console.print("""
[bold blue]╔══════════════════════════════════════════╗
║         CORRETTORE Q&A v1.0              ║
║   Validazione Quiz con AI                ║
╚══════════════════════════════════════════╝[/bold blue]
""")


def run_sync(input_file: Path, auto_correct: bool, output_file: Path = None):
    """Esegue la validazione in modo sincrono"""
    processor = QAProcessor()
    processor.load_questions(input_file)

    console.print(f"\n[cyan]Avvio validazione di {len(processor.questions)} domande...[/cyan]\n")

    results, corrections = processor.process_all(
        auto_correct=auto_correct,
        save_report=True,
        save_corrected=auto_correct,
        output_path=output_file
    )

    return results, corrections


def run_background(input_file: Path, auto_correct: bool):
    """Esegue la validazione in background con aggiornamenti live"""
    processor = QAProcessor()
    processor.load_questions(input_file)

    # Setup callbacks
    results_buffer = []
    errors_found = 0

    def on_progress(current: int, total: int, result: ValidationResult):
        nonlocal errors_found
        results_buffer.append(result)
        if not result.is_correct:
            errors_found += 1

    def on_complete(results: list[ValidationResult], corrections: list[Correction]):
        console.print("\n[bold green]Elaborazione completata![/bold green]")

    processor.on_progress = on_progress
    processor.on_complete = on_complete

    console.print(f"\n[cyan]Avvio elaborazione in background di {len(processor.questions)} domande...[/cyan]")
    console.print("[dim]Premi Ctrl+C per interrompere[/dim]\n")

    # Avvia il thread
    thread = processor.start_background_processing(auto_correct=auto_correct)

    # Mostra lo stato live
    try:
        while thread.is_alive():
            current, total, is_running = processor.get_progress()

            # Crea tabella stato
            table = Table(show_header=False, box=None)
            table.add_row("[cyan]Progresso:[/cyan]", f"{current}/{total} ({current/total*100:.1f}%)" if total > 0 else "0/0")
            table.add_row("[cyan]Errori trovati:[/cyan]", f"[red]{errors_found}[/red]" if errors_found > 0 else "[green]0[/green]")
            table.add_row("[cyan]Stato:[/cyan]", "[yellow]In esecuzione...[/yellow]" if is_running else "[green]Completato[/green]")

            console.clear()
            print_banner()
            console.print(table)

            if results_buffer:
                console.print("\n[bold]Ultimi risultati:[/bold]")
                for r in results_buffer[-5:]:
                    status = "[green]OK[/green]" if r.is_correct else "[red]ERRORE[/red]"
                    console.print(f"  {status} - {r.question_id}")

            time.sleep(1)

    except KeyboardInterrupt:
        console.print("\n[yellow]Interruzione richiesta...[/yellow]")
        processor.stop_processing()
        thread.join(timeout=5)

    # Riepilogo finale
    processor.reporter.print_summary(processor.results)


def main():
    parser = argparse.ArgumentParser(
        description="Correttore Q&A - Valida e corregge quiz usando AI",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        "input_file",
        type=Path,
        help="File JSON con le domande da validare"
    )

    parser.add_argument(
        "--auto-correct", "-c",
        action="store_true",
        help="Corregge automaticamente gli errori trovati"
    )

    parser.add_argument(
        "--background", "-b",
        action="store_true",
        help="Esegue l'elaborazione in background"
    )

    parser.add_argument(
        "--output", "-o",
        type=Path,
        help="File di output per le domande corrette"
    )

    args = parser.parse_args()

    # Verifica che il file esista
    if not args.input_file.exists():
        console.print(f"[red]Errore: File non trovato: {args.input_file}[/red]")
        sys.exit(1)

    print_banner()

    if args.background:
        run_background(args.input_file, args.auto_correct)
    else:
        run_sync(args.input_file, args.auto_correct, args.output)


if __name__ == "__main__":
    main()
