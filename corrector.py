"""
Correttore che applica le correzioni ai dati Q&A
"""
import json
from pathlib import Path
from models import Question, Correction, CorrectionType


class QuestionCorrector:
    """Applica correzioni ai file Q&A"""

    def apply_correction(self, question: Question, correction: Correction) -> Question:
        """
        Applica una correzione a una domanda.
        Restituisce una nuova Question con la correzione applicata.
        """
        # Crea una copia dei dati
        question_dict = question.model_dump()

        if correction.correction_type == CorrectionType.WRONG_ANSWER_LETTER:
            # Correggi la lettera della risposta corretta
            question_dict["correct_answer"] = correction.new_value

        elif correction.correction_type == CorrectionType.WRONG_ANSWER_TEXT:
            # Correggi il testo di una risposta specifica
            # field_to_correct sarà tipo "answers[A].text"
            letter = correction.field_to_correct.split("[")[1].split("]")[0]
            for answer in question_dict["answers"]:
                if answer["letter"].upper() == letter.upper():
                    answer["text"] = correction.new_value
                    break

        elif correction.correction_type == CorrectionType.WRONG_QUESTION:
            # Correggi il testo della domanda
            question_dict["question"] = correction.new_value

        return Question(**question_dict)

    def save_corrected_questions(
        self,
        questions: list[Question],
        corrections: list[Correction],
        output_path: Path
    ) -> list[Question]:
        """
        Applica tutte le correzioni e salva il file corretto.
        Restituisce la lista delle domande corrette.
        """
        # Crea un dizionario per lookup veloce
        questions_dict = {q.id: q for q in questions}
        corrections_by_id = {}
        for c in corrections:
            if c.question_id not in corrections_by_id:
                corrections_by_id[c.question_id] = []
            corrections_by_id[c.question_id].append(c)

        # Applica le correzioni
        corrected_questions = []
        for q in questions:
            if q.id in corrections_by_id:
                corrected_q = q
                for correction in corrections_by_id[q.id]:
                    corrected_q = self.apply_correction(corrected_q, correction)
                corrected_questions.append(corrected_q)
            else:
                corrected_questions.append(q)

        # Salva il file
        output_data = [q.model_dump() for q in corrected_questions]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)

        return corrected_questions
