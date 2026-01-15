#!/usr/bin/env python3
"""
QA Corrector - Sistema di verifica e correzione automatica di Q&A
Utilizza l'API Claude per risolvere ogni domanda e verificare le risposte.

Autore: Claude AI
Versione: 1.0
"""

import os
import re
import json
import time
import argparse
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional
import pdfplumber
import anthropic


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class Question:
    """Rappresenta una singola domanda con le sue opzioni."""
    number: int
    category: str
    text: str
    options: dict  # {"A": "...", "B": "...", "C": "...", "D": "..."}
    provided_answer: str  # Lettera dall'answer key
    
    # Campi popolati dopo la verifica
    calculated_answer: Optional[str] = None
    calculated_value: Optional[str] = None
    is_correct: Optional[bool] = None
    confidence: str = "high"  # high, medium, low
    correction_type: Optional[str] = None  # "answer_key", "option_missing", None
    suggested_correction: Optional[str] = None
    notes: str = ""


@dataclass
class VerificationResult:
    """Risultato della verifica di un file."""
    filename: str
    total_questions: int
    correct_count: int
    incorrect_count: int
    low_confidence_count: int
    questions: list = field(default_factory=list)
    errors_found: list = field(default_factory=list)
    corrections: list = field(default_factory=list)
    processing_time: float = 0.0


# ============================================================================
# PDF PARSING
# ============================================================================

def extract_text_from_pdf(pdf_path: str) -> str:
    """Estrae tutto il testo da un PDF."""
    full_text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text += text + "\n\n"
    return full_text


def parse_questions_and_answers(text: str) -> tuple[list[Question], dict[int, str]]:
    """
    Parsa il testo per estrarre domande e answer key.
    Gestisce tre formati:
    1. "Full Length Test" - Answer Key separato alla fine
    2. "Q&A per aree" - Domande + risposte per categoria
    3. "Inline" - "Correct Answer: X" dopo ogni domanda
    """
    questions = []
    answer_key = {}
    
    # FORMATO 1: Answer Key separato alla fine (es. FE_Full_Length_Test)
    answer_key_match = re.search(
        r'Answer\s*Key[:\s]*\n([\s\S]*?)(?=\n\s*(?:Test\s*\d+|$))',
        text, 
        re.IGNORECASE
    )
    
    if answer_key_match:
        answer_section = answer_key_match.group(1)
        # Pattern per "1.B" o "1. B" o "1.𝑩" (caratteri unicode)
        answer_patterns = re.findall(
            r'(\d+)\s*[.\)]\s*([A-Da-d𝑨𝑩𝑪𝑫])',
            answer_section
        )
        for num, letter in answer_patterns:
            letter = normalize_letter(letter)
            answer_key[int(num)] = letter.upper()
    
    # FORMATO 2: "Correct Answer: X" inline (es. FE_MECHANICAL)
    inline_answers = re.findall(
        r'(\d+)\.\s*(?:Correct\s*)?Answer[:\s]+([A-Da-d])',
        text,
        re.IGNORECASE
    )
    for num, letter in inline_answers:
        if int(num) not in answer_key:  # Non sovrascrivere se già trovato
            answer_key[int(num)] = letter.upper()
    
    # FORMATO 3: Cerca pattern "Correct Answer: X" dopo blocchi di domanda
    # Pattern: numero. testo... A) B) C) D) Correct Answer: X
    correct_answer_pattern = re.findall(
        r'Correct\s*Answer[:\s]+([A-Da-d])',
        text,
        re.IGNORECASE
    )
    
    # Parsing robusto delle domande
    lines = text.split('\n')
    current_question = None
    current_options = {}
    question_num = 0
    in_answer_key = False
    current_category = ""
    question_counter = 0  # Per associare risposte inline
    
    for i, line in enumerate(lines):
        line = line.strip()
        
        # Salta sezioni Answer Key
        if re.match(r'^Answer\s*Key', line, re.IGNORECASE):
            in_answer_key = True
            if current_question and current_options:
                save_question(questions, question_num, current_category, 
                            current_question, current_options, answer_key)
            continue
        
        if in_answer_key:
            # Controlla se siamo usciti dall'answer key (nuovo Test)
            if re.match(r'^Test\s*\d+', line, re.IGNORECASE):
                in_answer_key = False
            continue
        
        # Salta linee di spiegazione e risposte inline
        if re.match(r'^(Explanation:|Correct\s*Answer:)', line, re.IGNORECASE):
            # Estrai risposta se inline
            ans_match = re.match(r'^Correct\s*Answer[:\s]+([A-Da-d])', line, re.IGNORECASE)
            if ans_match and question_num > 0:
                answer_key[question_num] = ans_match.group(1).upper()
            continue
            
        # Nuova domanda?
        new_q_match = re.match(r'^(\d+)\.\s*(.*)', line)
        if new_q_match:
            # Salva domanda precedente
            if current_question and current_options:
                save_question(questions, question_num, current_category,
                            current_question, current_options, answer_key)
            
            question_num = int(new_q_match.group(1))
            remaining = new_q_match.group(2).strip()
            
            # Check se è una categoria (parola singola come "Mathematics")
            if remaining and not any(c in remaining.lower() for c in ['?', 'what', 'which', 'how', 'find', 'solve', 'calculate', 'evaluate', 'determine', 'if', 'an', 'the', 'a ']):
                words = remaining.split()
                if len(words) <= 3 and words[0][0].isupper() and not any(char.isdigit() for char in remaining):
                    current_category = remaining
                    current_question = ""
                else:
                    current_question = remaining
            else:
                current_question = remaining
            
            current_options = {}
            continue
        
        # Opzione? (A), B), etc.)
        option_match = re.match(r'^([𝐴𝐵𝐶𝐷ABCDabcd])\s*\)\s*(.*)', line)
        if option_match:
            letter = normalize_letter(option_match.group(1))
            current_options[letter] = option_match.group(2).strip()
            continue
        
        # Continuazione testo domanda (solo se non abbiamo ancora opzioni)
        if current_question is not None and not current_options:
            if line and not line.startswith('Explanation'):
                current_question += " " + line
    
    # Salva ultima domanda
    if current_question and current_options:
        save_question(questions, question_num, current_category,
                    current_question, current_options, answer_key)
    
    # Se non abbiamo trovato answer key, prova pattern alternativo
    # per risposte inline dopo ogni blocco domanda
    if not answer_key:
        # Cerca tutte le "Correct Answer: X" in sequenza
        all_correct = re.findall(
            r'Correct\s*Answer[:\s]+([A-Da-d])',
            text,
            re.IGNORECASE
        )
        for idx, letter in enumerate(all_correct, 1):
            answer_key[idx] = letter.upper()
    
    # Aggiorna le domande con le risposte trovate
    for q in questions:
        if q.number in answer_key:
            q.provided_answer = answer_key[q.number]
    
    return questions, answer_key


def normalize_letter(letter: str) -> str:
    """Normalizza lettere unicode/speciali in lettere standard."""
    mapping = {
        '𝐴': 'A', '𝑨': 'A', '𝐀': 'A',
        '𝐵': 'B', '𝑩': 'B', '𝐁': 'B',
        '𝐶': 'C', '𝑪': 'C', '𝐂': 'C',
        '𝐷': 'D', '𝑫': 'D', '𝐃': 'D',
    }
    return mapping.get(letter, letter.upper())


def save_question(questions: list, num: int, category: str, 
                  text: str, options: dict, answer_key: dict):
    """Salva una domanda nella lista."""
    if num > 0 and options:
        provided = answer_key.get(num, "?")
        q = Question(
            number=num,
            category=category,
            text=text.strip(),
            options=options,
            provided_answer=provided
        )
        questions.append(q)


# ============================================================================
# API CLAUDE - VERIFICA DOMANDE
# ============================================================================

def verify_question_with_claude(client: anthropic.Anthropic, question: Question) -> Question:
    """
    Invia una domanda a Claude per la risoluzione e verifica.
    """
    # Costruisci il prompt
    options_text = "\n".join([f"{k}) {v}" for k, v in sorted(question.options.items())])
    
    prompt = f"""Sei un esperto verificatore di esami. Devi risolvere questa domanda e determinare la risposta corretta.

DOMANDA {question.number}:
{question.text}

OPZIONI:
{options_text}

ISTRUZIONI:
1. Risolvi la domanda passo per passo
2. Calcola il valore numerico se necessario
3. Trova quale opzione corrisponde alla tua risposta
4. Se nessuna opzione corrisponde esattamente, indica quella più vicina

RISPOSTA FORNITA DALL'ANSWER KEY: {question.provided_answer}

Rispondi SOLO in questo formato JSON (senza markdown):
{{
    "reasoning": "breve spiegazione del ragionamento",
    "calculated_value": "valore calcolato (se numerico) o risposta trovata",
    "correct_letter": "A/B/C/D",
    "matches_provided": true/false,
    "confidence": "high/medium/low",
    "notes": "eventuali problemi riscontrati"
}}"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        response_text = message.content[0].text
        
        # Pulisci la risposta da eventuali markdown
        response_text = re.sub(r'```json\s*', '', response_text)
        response_text = re.sub(r'```\s*', '', response_text)
        response_text = response_text.strip()
        
        # Parse JSON
        result = json.loads(response_text)
        
        question.calculated_answer = result.get("correct_letter", "?").upper()
        question.calculated_value = result.get("calculated_value", "")
        question.confidence = result.get("confidence", "medium")
        question.notes = result.get("notes", "")
        
        # Determina se è corretto
        question.is_correct = (question.calculated_answer == question.provided_answer)
        
        # Determina tipo di correzione necessaria
        if not question.is_correct:
            if question.calculated_answer in question.options:
                question.correction_type = "answer_key"
                question.suggested_correction = question.calculated_answer
            else:
                question.correction_type = "option_missing"
                question.notes += f" | Valore calcolato non presente tra le opzioni"
        
    except json.JSONDecodeError as e:
        question.confidence = "low"
        question.notes = f"Errore parsing risposta: {e}"
        question.is_correct = None
    except anthropic.APIError as e:
        question.confidence = "low"  
        question.notes = f"Errore API: {e}"
        question.is_correct = None
    
    return question


def determine_random_letter(questions: list, current_idx: int) -> str:
    """
    Determina una lettera random evitando pattern con le 10 domande vicine.
    """
    # Prendi le 5 precedenti e 5 successive
    start = max(0, current_idx - 5)
    end = min(len(questions), current_idx + 6)
    
    nearby_answers = []
    for i in range(start, end):
        if i != current_idx and questions[i].provided_answer:
            nearby_answers.append(questions[i].provided_answer)
    
    # Conta frequenze
    freq = {'A': 0, 'B': 0, 'C': 0, 'D': 0}
    for ans in nearby_answers:
        if ans in freq:
            freq[ans] += 1
    
    # Scegli la lettera meno usata
    min_freq = min(freq.values())
    candidates = [k for k, v in freq.items() if v == min_freq]
    
    import random
    return random.choice(candidates)


# ============================================================================
# CHECKPOINT SYSTEM
# ============================================================================

def save_checkpoint(questions: list, checkpoint_path: str, last_idx: int):
    """Salva un checkpoint del progresso."""
    checkpoint_data = {
        "last_processed_index": last_idx,
        "timestamp": datetime.now().isoformat(),
        "questions": [asdict(q) for q in questions[:last_idx + 1]]
    }
    with open(checkpoint_path, 'w', encoding='utf-8') as f:
        json.dump(checkpoint_data, f, ensure_ascii=False, indent=2)


def load_checkpoint(checkpoint_path: str) -> tuple[int, list]:
    """Carica un checkpoint esistente."""
    if not os.path.exists(checkpoint_path):
        return -1, []
    
    with open(checkpoint_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    questions = []
    for q_data in data.get("questions", []):
        q = Question(**{k: v for k, v in q_data.items() if k in Question.__dataclass_fields__})
        questions.append(q)
    
    return data.get("last_processed_index", -1), questions


# ============================================================================
# REPORT GENERATION
# ============================================================================

def generate_report(result: VerificationResult, output_path: str):
    """Genera il report TXT completo."""
    lines = []
    
    # Header
    lines.append("=" * 80)
    lines.append("REPORT VERIFICA Q&A")
    lines.append("=" * 80)
    lines.append(f"File: {result.filename}")
    lines.append(f"Data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Tempo elaborazione: {result.processing_time:.2f} secondi")
    lines.append("")
    
    # Statistiche
    lines.append("-" * 40)
    lines.append("STATISTICHE")
    lines.append("-" * 40)
    lines.append(f"Domande totali: {result.total_questions}")
    lines.append(f"Corrette: {result.correct_count}")
    lines.append(f"Errori trovati: {result.incorrect_count}")
    lines.append(f"Bassa confidenza (da verificare): {result.low_confidence_count}")
    if result.total_questions > 0:
        accuracy = (result.correct_count / result.total_questions) * 100
        lines.append(f"Accuratezza Answer Key: {accuracy:.1f}%")
    lines.append("")
    
    # Errori trovati
    if result.errors_found:
        lines.append("=" * 80)
        lines.append("ERRORI TROVATI")
        lines.append("=" * 80)
        
        for q in result.errors_found:
            lines.append("")
            lines.append(f"--- DOMANDA {q.number} ---")
            lines.append(f"Categoria: {q.category}")
            lines.append(f"Testo: {q.text[:200]}{'...' if len(q.text) > 200 else ''}")
            lines.append(f"Risposta fornita (Answer Key): {q.provided_answer}")
            lines.append(f"Risposta calcolata: {q.calculated_answer}")
            if q.calculated_value:
                lines.append(f"Valore calcolato: {q.calculated_value}")
            lines.append(f"Confidenza: {q.confidence}")
            lines.append(f"Tipo correzione: {q.correction_type}")
            if q.notes:
                lines.append(f"Note: {q.notes}")
            lines.append("")
    
    # Correzioni suggerite
    if result.corrections:
        lines.append("=" * 80)
        lines.append("CORREZIONI SUGGERITE")
        lines.append("=" * 80)
        lines.append("")
        lines.append("Formato: [Numero Domanda]. [Risposta Corretta]")
        lines.append("")
        
        for q in result.corrections:
            lines.append(f"{q.number}. {q.suggested_correction}")
        
        lines.append("")
    
    # Domande a bassa confidenza
    low_conf = [q for q in result.questions if q.confidence == "low"]
    if low_conf:
        lines.append("=" * 80)
        lines.append("DOMANDE DA VERIFICARE MANUALMENTE (BASSA CONFIDENZA)")
        lines.append("=" * 80)
        
        for q in low_conf:
            lines.append("")
            lines.append(f"--- DOMANDA {q.number} ---")
            lines.append(f"Testo: {q.text[:200]}{'...' if len(q.text) > 200 else ''}")
            lines.append(f"Risposta fornita: {q.provided_answer}")
            lines.append(f"Risposta calcolata: {q.calculated_answer or 'N/A'}")
            lines.append(f"Note: {q.notes}")
    
    # Answer Key corretto
    lines.append("")
    lines.append("=" * 80)
    lines.append("ANSWER KEY CORRETTO")
    lines.append("=" * 80)
    lines.append("")
    
    for q in sorted(result.questions, key=lambda x: x.number):
        final_answer = q.suggested_correction if q.suggested_correction else q.provided_answer
        status = ""
        if q.correction_type:
            status = " [CORRETTO]"
        elif q.confidence == "low":
            status = " [DA VERIFICARE]"
        lines.append(f"{q.number}. {final_answer}{status}")
    
    # Scrivi file
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    
    return output_path


# ============================================================================
# MAIN PROCESS
# ============================================================================

def process_pdf(pdf_path: str, api_key: str, output_dir: str = None, 
                resume: bool = True) -> VerificationResult:
    """
    Processa un PDF di Q&A completo.
    """
    start_time = time.time()
    
    # Setup paths
    pdf_name = Path(pdf_path).stem
    if output_dir is None:
        output_dir = Path(pdf_path).parent
    
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    checkpoint_path = output_dir / f"{pdf_name}_checkpoint.json"
    report_path = output_dir / f"{pdf_name}_report.txt"
    
    # Inizializza client API
    client = anthropic.Anthropic(api_key=api_key)
    
    print(f"Elaborazione: {pdf_path}")
    print("-" * 50)
    
    # Estrai testo e parsa domande
    print("Estrazione testo dal PDF...")
    text = extract_text_from_pdf(pdf_path)
    
    print("Parsing domande e answer key...")
    questions, answer_key = parse_questions_and_answers(text)
    print(f"Trovate {len(questions)} domande")
    print(f"Answer key con {len(answer_key)} risposte")
    
    # Carica checkpoint se esiste
    start_idx = 0
    if resume:
        last_idx, saved_questions = load_checkpoint(str(checkpoint_path))
        if last_idx >= 0:
            print(f"Ripresa da checkpoint: domanda {last_idx + 1}")
            start_idx = last_idx + 1
            # Aggiorna domande già processate
            for i, sq in enumerate(saved_questions):
                if i < len(questions):
                    questions[i] = sq
    
    # Processa domande
    total = len(questions)
    for i in range(start_idx, total):
        q = questions[i]
        
        print(f"[{i+1}/{total}] Verifica domanda {q.number}...", end=" ")
        
        # Verifica con Claude
        questions[i] = verify_question_with_claude(client, q)
        
        status = "✓" if questions[i].is_correct else "✗" if questions[i].is_correct is False else "?"
        print(f"{status} (conf: {questions[i].confidence})")
        
        # Gestione errori con opzione mancante
        if questions[i].correction_type == "option_missing":
            questions[i].suggested_correction = determine_random_letter(questions, i)
            print(f"    → Opzione mancante, assegnata: {questions[i].suggested_correction}")
        
        # Checkpoint ogni 10 domande
        if (i + 1) % 10 == 0:
            print(f"Salvataggio checkpoint (domanda {i + 1})...")
            save_checkpoint(questions, str(checkpoint_path), i)
        
        # Rate limiting gentile
        time.sleep(0.5)
    
    # Salvataggio finale
    save_checkpoint(questions, str(checkpoint_path), len(questions) - 1)
    
    # Prepara risultati
    result = VerificationResult(
        filename=pdf_path,
        total_questions=len(questions),
        correct_count=sum(1 for q in questions if q.is_correct is True),
        incorrect_count=sum(1 for q in questions if q.is_correct is False),
        low_confidence_count=sum(1 for q in questions if q.confidence == "low"),
        questions=questions,
        errors_found=[q for q in questions if q.is_correct is False],
        corrections=[q for q in questions if q.suggested_correction],
        processing_time=time.time() - start_time
    )
    
    # Genera report
    print("\nGenerazione report...")
    generate_report(result, str(report_path))
    print(f"Report salvato: {report_path}")
    
    # Rimuovi checkpoint se completato
    if os.path.exists(checkpoint_path):
        os.remove(checkpoint_path)
    
    return result


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="QA Corrector - Verifica e correggi Q&A automaticamente"
    )
    parser.add_argument(
        "pdf_path",
        help="Percorso del file PDF da processare"
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("ANTHROPIC_API_KEY"),
        help="API key Anthropic (default: env ANTHROPIC_API_KEY)"
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory per i file di output (default: stessa del PDF)"
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Non riprendere da checkpoint esistente"
    )
    
    args = parser.parse_args()
    
    if not args.api_key:
        print("ERRORE: API key non fornita. Usa --api-key o imposta ANTHROPIC_API_KEY")
        return 1
    
    if not os.path.exists(args.pdf_path):
        print(f"ERRORE: File non trovato: {args.pdf_path}")
        return 1
    
    result = process_pdf(
        args.pdf_path,
        args.api_key,
        args.output_dir,
        resume=not args.no_resume
    )
    
    print("\n" + "=" * 50)
    print("RIEPILOGO")
    print("=" * 50)
    print(f"Domande totali: {result.total_questions}")
    print(f"Corrette: {result.correct_count}")
    print(f"Errori trovati: {result.incorrect_count}")
    print(f"Da verificare: {result.low_confidence_count}")
    
    return 0


if __name__ == "__main__":
    exit(main())
