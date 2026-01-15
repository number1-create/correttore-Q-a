"""
Processore principale che gestisce la validazione in background
"""
import json
import asyncio
import threading
from pathlib import Path
from queue import Queue
from typing import Callable
from rich.console import Console

from models import Question, ValidationResult, Correction
from solver import QuestionSolver
from validator import QuestionValidator
from corrector import QuestionCorrector
from reporter import Reporter

console = Console()


class QAProcessor:
    """
    Processore Q&A che lavora in background.
    Processa una domanda alla volta e continua automaticamente.
    """

    def __init__(self, api_key: str = None):
        self.solver = QuestionSolver(api_key)
        self.validator = QuestionValidator(self.solver)
        self.corrector = QuestionCorrector()
        self.reporter = Reporter()

        self.results: list[ValidationResult] = []
        self.corrections: list[Correction] = []
        self.questions: list[Question] = []

        self._is_running = False
        self._should_stop = False
        self._current_index = 0
        self._lock = threading.Lock()

        # Callback per aggiornamenti
        self.on_progress: Callable[[int, int, ValidationResult], None] = None
        self.on_complete: Callable[[list[ValidationResult], list[Correction]], None] = None
        self.on_error: Callable[[Exception, Question], None] = None

    def load_questions(self, file_path: Path) -> list[Question]:
        """Carica le domande da un file JSON"""
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.questions = [Question(**q) for q in data]
        console.print(f"[green]Caricate {len(self.questions)} domande[/green]")
        return self.questions

    def process_single(self, question: Question, auto_correct: bool = False) -> tuple[ValidationResult, Correction | None]:
        """
        Processa una singola domanda.
        Restituisce il risultato della validazione e l'eventuale correzione.
        """
        result = self.validator.validate(question)
        correction = None

        if not result.is_correct and auto_correct:
            correction = self.validator.generate_correction(result, question)

        return result, correction

    def process_all(
        self,
        auto_correct: bool = False,
        save_report: bool = True,
        save_corrected: bool = True,
        output_path: Path = None
    ) -> tuple[list[ValidationResult], list[Correction]]:
        """
        Processa tutte le domande in modo sincrono.
        """
        self.results = []
        self.corrections = []

        progress = self.reporter.create_progress_bar(len(self.questions))

        with progress:
            task = progress.add_task("Validazione Q&A", total=len(self.questions))

            for i, question in enumerate(self.questions):
                result, correction = self.process_single(question, auto_correct)
                self.results.append(result)

                if correction:
                    self.corrections.append(correction)

                self.reporter.print_validation_result(result, question.question)
                progress.update(task, advance=1)

        # Riepilogo
        self.reporter.print_summary(self.results)

        # Salva report
        if save_report:
            self.reporter.save_report(self.results, self.corrections)

        # Salva file corretto
        if save_corrected and self.corrections:
            output_path = output_path or Path("output/corrected_questions.json")
            self.corrector.save_corrected_questions(
                self.questions, self.corrections, output_path
            )
            console.print(f"[green]File corretto salvato in:[/green] {output_path}")

        return self.results, self.corrections

    def start_background_processing(
        self,
        auto_correct: bool = False,
        save_report: bool = True,
        save_corrected: bool = True
    ) -> threading.Thread:
        """
        Avvia il processing in un thread separato (background).
        Usa i callback per ricevere aggiornamenti.
        """
        def _process():
            self._is_running = True
            self._should_stop = False
            self.results = []
            self.corrections = []

            for i, question in enumerate(self.questions):
                if self._should_stop:
                    break

                with self._lock:
                    self._current_index = i

                try:
                    result, correction = self.process_single(question, auto_correct)
                    self.results.append(result)

                    if correction:
                        self.corrections.append(correction)

                    if self.on_progress:
                        self.on_progress(i + 1, len(self.questions), result)

                except Exception as e:
                    if self.on_error:
                        self.on_error(e, question)

            # Completato
            self._is_running = False

            if save_report:
                self.reporter.save_report(self.results, self.corrections)

            if save_corrected and self.corrections:
                self.corrector.save_corrected_questions(
                    self.questions,
                    self.corrections,
                    Path("output/corrected_questions.json")
                )

            if self.on_complete:
                self.on_complete(self.results, self.corrections)

        thread = threading.Thread(target=_process, daemon=True)
        thread.start()
        return thread

    def stop_processing(self):
        """Ferma il processing in background"""
        self._should_stop = True

    def get_progress(self) -> tuple[int, int, bool]:
        """Restituisce lo stato del processing (current, total, is_running)"""
        with self._lock:
            return self._current_index, len(self.questions), self._is_running
