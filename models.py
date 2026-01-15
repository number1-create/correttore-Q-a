"""
Modelli dati per le Q&A
"""
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class CorrectionType(str, Enum):
    """Tipo di correzione necessaria"""
    NONE = "none"  # Nessuna correzione
    WRONG_ANSWER_LETTER = "wrong_answer_letter"  # La lettera corretta è sbagliata
    WRONG_ANSWER_TEXT = "wrong_answer_text"  # Il testo della risposta è sbagliato
    WRONG_QUESTION = "wrong_question"  # La domanda è ambigua/errata
    NO_CORRECT_OPTION = "no_correct_option"  # Nessuna opzione corrisponde alla soluzione


class Answer(BaseModel):
    """Una singola risposta"""
    letter: str = Field(..., description="Lettera della risposta (A, B, C, D...)")
    text: str = Field(..., description="Testo della risposta")


class Question(BaseModel):
    """Una domanda con risposte multiple"""
    id: str = Field(..., description="ID univoco della domanda")
    question: str = Field(..., description="Testo della domanda")
    answers: list[Answer] = Field(..., description="Lista delle risposte possibili")
    correct_answer: str = Field(..., description="Lettera della risposta corretta")
    category: Optional[str] = Field(None, description="Categoria della domanda")


class SolverResult(BaseModel):
    """Risultato del ragionamento dell'AI"""
    reasoning: str = Field(..., description="Ragionamento step-by-step")
    calculated_answer: str = Field(..., description="Risposta calcolata dall'AI")
    confidence: float = Field(..., description="Confidenza nella risposta (0-1)")
    matching_letter: Optional[str] = Field(None, description="Lettera che corrisponde alla risposta calcolata")


class ValidationResult(BaseModel):
    """Risultato della validazione di una domanda"""
    question_id: str
    is_correct: bool
    solver_result: SolverResult
    original_correct_answer: str
    correction_type: CorrectionType = CorrectionType.NONE
    suggested_correction: Optional[str] = None
    error_message: Optional[str] = None


class Correction(BaseModel):
    """Una correzione da applicare"""
    question_id: str
    correction_type: CorrectionType
    field_to_correct: str  # "correct_answer", "answers[X].text", "question"
    old_value: str
    new_value: str
