"""
Validatore che confronta la risposta calcolata con quella marcata come corretta
"""
from models import Question, ValidationResult, SolverResult, CorrectionType, Correction
from solver import QuestionSolver


class QuestionValidator:
    """Valida le domande confrontando la soluzione calcolata con quella indicata"""

    def __init__(self, solver: QuestionSolver):
        self.solver = solver

    def validate(self, question: Question) -> ValidationResult:
        """
        Valida una domanda:
        1. Risolve la domanda indipendentemente
        2. Cerca la risposta tra le opzioni
        3. Confronta con la lettera marcata come corretta
        4. Determina se c'è un errore e quale tipo
        """
        # Fase 1: Risolvi la domanda
        solver_result = self.solver.solve(question)

        # Fase 2: Confronta con la risposta marcata
        original_correct = question.correct_answer.upper()
        calculated_letter = solver_result.matching_letter

        # Caso 1: La risposta calcolata corrisponde a un'opzione
        if calculated_letter:
            if calculated_letter.upper() == original_correct:
                # Tutto OK!
                return ValidationResult(
                    question_id=question.id,
                    is_correct=True,
                    solver_result=solver_result,
                    original_correct_answer=original_correct,
                    correction_type=CorrectionType.NONE
                )
            else:
                # La lettera corretta è sbagliata
                return ValidationResult(
                    question_id=question.id,
                    is_correct=False,
                    solver_result=solver_result,
                    original_correct_answer=original_correct,
                    correction_type=CorrectionType.WRONG_ANSWER_LETTER,
                    suggested_correction=calculated_letter.upper(),
                    error_message=f"La risposta corretta dovrebbe essere {calculated_letter}, non {original_correct}"
                )

        # Caso 2: Nessuna opzione corrisponde alla risposta calcolata
        else:
            return ValidationResult(
                question_id=question.id,
                is_correct=False,
                solver_result=solver_result,
                original_correct_answer=original_correct,
                correction_type=CorrectionType.NO_CORRECT_OPTION,
                error_message=f"Nessuna opzione corrisponde alla risposta calcolata: {solver_result.calculated_answer}"
            )

    def generate_correction(self, validation_result: ValidationResult, question: Question) -> Correction | None:
        """Genera una correzione basata sul risultato della validazione"""
        if validation_result.is_correct:
            return None

        if validation_result.correction_type == CorrectionType.WRONG_ANSWER_LETTER:
            return Correction(
                question_id=question.id,
                correction_type=CorrectionType.WRONG_ANSWER_LETTER,
                field_to_correct="correct_answer",
                old_value=validation_result.original_correct_answer,
                new_value=validation_result.suggested_correction
            )

        if validation_result.correction_type == CorrectionType.NO_CORRECT_OPTION:
            # In questo caso, suggeriamo di correggere il testo della risposta marcata come corretta
            correct_answer_obj = next(
                (a for a in question.answers if a.letter.upper() == validation_result.original_correct_answer),
                None
            )
            if correct_answer_obj:
                return Correction(
                    question_id=question.id,
                    correction_type=CorrectionType.WRONG_ANSWER_TEXT,
                    field_to_correct=f"answers[{validation_result.original_correct_answer}].text",
                    old_value=correct_answer_obj.text,
                    new_value=validation_result.solver_result.calculated_answer
                )

        return None
