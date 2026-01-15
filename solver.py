"""
Solver che usa Claude API per risolvere le domande
"""
import os
import re
from anthropic import Anthropic
from models import Question, SolverResult, Answer
from dotenv import load_dotenv

load_dotenv()


class QuestionSolver:
    """Risolve domande usando Claude API"""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY non trovata. Imposta la variabile d'ambiente o passa la chiave.")
        self.client = Anthropic(api_key=self.api_key)

    def solve(self, question: Question) -> SolverResult:
        """
        Risolve una domanda step-by-step.
        NON guarda le risposte per calcolare - calcola indipendentemente.
        """
        # Fase 1: Calcola la risposta senza guardare le opzioni
        solving_prompt = f"""Sei un esperto risolutore di quiz. Devi risolvere questa domanda CALCOLANDO la risposta corretta.

DOMANDA:
{question.question}

ISTRUZIONI IMPORTANTI:
1. Leggi attentamente la domanda
2. Ragiona step-by-step
3. Calcola o determina la risposta corretta
4. NON indovinare - devi essere SICURO della risposta
5. Se la domanda richiede un calcolo, mostra tutti i passaggi

Fornisci la tua risposta in questo formato:
RAGIONAMENTO: [il tuo ragionamento step-by-step]
RISPOSTA: [la risposta calcolata/determinata]
CONFIDENZA: [un numero da 0 a 1 che indica quanto sei sicuro]"""

        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{"role": "user", "content": solving_prompt}]
        )

        solving_response = response.content[0].text

        # Parse della risposta
        reasoning = self._extract_section(solving_response, "RAGIONAMENTO")
        calculated_answer = self._extract_section(solving_response, "RISPOSTA")
        confidence_str = self._extract_section(solving_response, "CONFIDENZA")

        try:
            confidence = float(confidence_str.strip())
        except (ValueError, AttributeError):
            confidence = 0.5

        # Fase 2: Cerca la risposta calcolata nelle opzioni
        matching_letter = self._find_matching_answer(calculated_answer, question.answers)

        return SolverResult(
            reasoning=reasoning,
            calculated_answer=calculated_answer,
            confidence=confidence,
            matching_letter=matching_letter
        )

    def _extract_section(self, text: str, section_name: str) -> str:
        """Estrae una sezione dalla risposta"""
        pattern = rf"{section_name}:\s*(.+?)(?=\n[A-Z]+:|$)"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return ""

    def _find_matching_answer(self, calculated: str, answers: list[Answer]) -> str | None:
        """
        Cerca la risposta calcolata tra le opzioni disponibili.
        Usa Claude per un matching semantico più accurato.
        """
        answers_text = "\n".join([f"{a.letter}: {a.text}" for a in answers])

        matching_prompt = f"""Data la seguente risposta calcolata e le opzioni disponibili, trova quale opzione corrisponde.

RISPOSTA CALCOLATA: {calculated}

OPZIONI DISPONIBILI:
{answers_text}

Se la risposta calcolata corrisponde a una delle opzioni (anche se formulata diversamente), rispondi con SOLO la lettera.
Se nessuna opzione corrisponde, rispondi "NESSUNA".

LETTERA:"""

        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=50,
            messages=[{"role": "user", "content": matching_prompt}]
        )

        letter = response.content[0].text.strip().upper()

        # Verifica che sia una lettera valida
        valid_letters = [a.letter.upper() for a in answers]
        if letter in valid_letters:
            return letter

        # Cerca la prima lettera nella risposta
        for char in letter:
            if char in valid_letters:
                return char

        return None
