#!/usr/bin/env python3
"""
QA Corrector - Web Application
Interfaccia web per verifica e correzione automatica Q&A

Deploy: Streamlit Cloud (gratuito) collegato a GitHub
"""

import streamlit as st
import anthropic
import json
import re
import time
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional
import io

# ============================================================================
# CONFIGURAZIONE PAGINA
# ============================================================================

st.set_page_config(
    page_title="QA Corrector",
    page_icon="✅",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class Question:
    number: int
    text: str
    options: dict
    provided_answer: str
    calculated_answer: Optional[str] = None
    calculated_value: Optional[str] = None
    is_correct: Optional[bool] = None
    confidence: str = "high"
    correction_type: Optional[str] = None
    suggested_correction: Optional[str] = None
    notes: str = ""

# ============================================================================
# PARSING FUNCTIONS
# ============================================================================

def normalize_letter(letter: str) -> str:
    """Normalizza lettere unicode in standard."""
    mapping = {
        '𝐴': 'A', '𝑨': 'A', '𝐀': 'A',
        '𝐵': 'B', '𝑩': 'B', '𝐁': 'B',
        '𝐶': 'C', '𝑪': 'C', '𝐂': 'C',
        '𝐷': 'D', '𝑫': 'D', '𝐃': 'D',
    }
    return mapping.get(letter, letter.upper())


def parse_text_content(text: str) -> tuple[list[Question], dict]:
    """
    Parsa il testo per estrarre domande e answer key.
    Supporta multiple formati.
    """
    questions = []
    answer_key = {}
    
    # FORMATO 1: Answer Key separato
    answer_key_match = re.search(
        r'Answer\s*Key[:\s]*\n([\s\S]*?)(?=\n\s*(?:Test\s*\d+|$))',
        text, re.IGNORECASE
    )
    if answer_key_match:
        answer_section = answer_key_match.group(1)
        for match in re.finditer(r'(\d+)\s*[.\)]\s*([A-Da-d𝑨𝑩𝑪𝑫])', answer_section):
            num, letter = match.groups()
            answer_key[int(num)] = normalize_letter(letter)
    
    # FORMATO 2: "Correct Answer: X" inline
    for match in re.finditer(r'(\d+)\.\s*(?:Correct\s*)?Answer[:\s]+([A-Da-d])', text, re.IGNORECASE):
        num, letter = match.groups()
        if int(num) not in answer_key:
            answer_key[int(num)] = letter.upper()
    
    # FORMATO 3: Cerca "Correct Answer: X" dopo ogni domanda
    correct_answers = re.findall(r'Correct\s*Answer[:\s]+([A-Da-d])', text, re.IGNORECASE)
    
    # Parsing domande
    lines = text.split('\n')
    current_question = None
    current_options = {}
    question_num = 0
    in_answer_key = False
    
    for line in lines:
        line = line.strip()
        
        if re.match(r'^Answer\s*Key', line, re.IGNORECASE):
            in_answer_key = True
            if current_question and current_options:
                q = Question(
                    number=question_num,
                    text=current_question.strip(),
                    options=current_options.copy(),
                    provided_answer=answer_key.get(question_num, "?")
                )
                questions.append(q)
            continue
        
        if in_answer_key:
            if re.match(r'^Test\s*\d+', line, re.IGNORECASE):
                in_answer_key = False
            continue
        
        # Salta spiegazioni
        if re.match(r'^(Explanation:|Correct\s*Answer:)', line, re.IGNORECASE):
            ans_match = re.match(r'^Correct\s*Answer[:\s]+([A-Da-d])', line, re.IGNORECASE)
            if ans_match and question_num > 0:
                answer_key[question_num] = ans_match.group(1).upper()
            continue
        
        # Nuova domanda
        new_q_match = re.match(r'^(\d+)\.\s*(.*)', line)
        if new_q_match:
            if current_question and current_options:
                q = Question(
                    number=question_num,
                    text=current_question.strip(),
                    options=current_options.copy(),
                    provided_answer=answer_key.get(question_num, "?")
                )
                questions.append(q)
            
            question_num = int(new_q_match.group(1))
            current_question = new_q_match.group(2).strip()
            current_options = {}
            continue
        
        # Opzione
        option_match = re.match(r'^([𝐴𝐵𝐶𝐷ABCDabcd])\s*\)\s*(.*)', line)
        if option_match:
            letter = normalize_letter(option_match.group(1))
            current_options[letter] = option_match.group(2).strip()
            continue
        
        # Continuazione testo
        if current_question is not None and not current_options:
            if line:
                current_question += " " + line
    
    # Ultima domanda
    if current_question and current_options:
        q = Question(
            number=question_num,
            text=current_question.strip(),
            options=current_options.copy(),
            provided_answer=answer_key.get(question_num, "?")
        )
        questions.append(q)
    
    # Se non abbiamo answer key, usa le risposte inline
    if not answer_key and correct_answers:
        for idx, letter in enumerate(correct_answers, 1):
            answer_key[idx] = letter.upper()
    
    # Aggiorna domande
    for q in questions:
        if q.number in answer_key:
            q.provided_answer = answer_key[q.number]
    
    return questions, answer_key

# ============================================================================
# API VERIFICATION
# ============================================================================

def verify_question(client, question: Question, model: str) -> Question:
    """Verifica una domanda con Claude."""
    options_text = "\n".join([f"{k}) {v}" for k, v in sorted(question.options.items())])
    
    prompt = f"""Sei un esperto verificatore di esami. Risolvi questa domanda.

DOMANDA {question.number}:
{question.text}

OPZIONI:
{options_text}

ANSWER KEY FORNITO: {question.provided_answer}

Rispondi SOLO in JSON (senza markdown):
{{
    "reasoning": "breve spiegazione",
    "calculated_value": "valore calcolato se numerico",
    "correct_letter": "A/B/C/D",
    "matches_provided": true/false,
    "confidence": "high/medium/low",
    "notes": "problemi riscontrati"
}}"""

    try:
        message = client.messages.create(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )
        
        response_text = message.content[0].text
        response_text = re.sub(r'```json\s*', '', response_text)
        response_text = re.sub(r'```\s*', '', response_text)
        
        result = json.loads(response_text.strip())
        
        question.calculated_answer = result.get("correct_letter", "?").upper()
        question.calculated_value = result.get("calculated_value", "")
        question.confidence = result.get("confidence", "medium")
        question.notes = result.get("notes", "")
        question.is_correct = (question.calculated_answer == question.provided_answer)
        
        if not question.is_correct:
            if question.calculated_answer in question.options:
                question.correction_type = "answer_key"
                question.suggested_correction = question.calculated_answer
            else:
                question.correction_type = "option_missing"
                question.notes += " | Valore non presente tra opzioni"
        
    except Exception as e:
        question.confidence = "low"
        question.notes = f"Errore: {str(e)}"
        question.is_correct = None
    
    return question


def determine_random_letter(questions: list, current_idx: int) -> str:
    """Determina lettera evitando pattern."""
    start = max(0, current_idx - 5)
    end = min(len(questions), current_idx + 6)
    
    nearby = [q.provided_answer for i, q in enumerate(questions[start:end]) 
              if i != current_idx - start and q.provided_answer in 'ABCD']
    
    freq = {'A': 0, 'B': 0, 'C': 0, 'D': 0}
    for ans in nearby:
        freq[ans] = freq.get(ans, 0) + 1
    
    min_freq = min(freq.values())
    candidates = [k for k, v in freq.items() if v == min_freq]
    
    import random
    return random.choice(candidates)

# ============================================================================
# REPORT GENERATION
# ============================================================================

def generate_report(questions: list, filename: str, elapsed: float) -> str:
    """Genera report TXT."""
    lines = []
    
    correct = sum(1 for q in questions if q.is_correct is True)
    incorrect = sum(1 for q in questions if q.is_correct is False)
    low_conf = sum(1 for q in questions if q.confidence == "low")
    errors = [q for q in questions if q.is_correct is False]
    corrections = [q for q in questions if q.suggested_correction]
    
    lines.append("=" * 80)
    lines.append("REPORT VERIFICA Q&A")
    lines.append("=" * 80)
    lines.append(f"File: {filename}")
    lines.append(f"Data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Tempo: {elapsed:.1f} secondi")
    lines.append("")
    lines.append("-" * 40)
    lines.append("STATISTICHE")
    lines.append("-" * 40)
    lines.append(f"Domande totali: {len(questions)}")
    lines.append(f"Corrette: {correct}")
    lines.append(f"Errori: {incorrect}")
    lines.append(f"Bassa confidenza: {low_conf}")
    if len(questions) > 0:
        lines.append(f"Accuratezza: {correct/len(questions)*100:.1f}%")
    lines.append("")
    
    if errors:
        lines.append("=" * 80)
        lines.append("ERRORI TROVATI")
        lines.append("=" * 80)
        for q in errors:
            lines.append("")
            lines.append(f"--- DOMANDA {q.number} ---")
            lines.append(f"Testo: {q.text[:150]}...")
            lines.append(f"Answer Key: {q.provided_answer}")
            lines.append(f"Corretto: {q.calculated_answer}")
            if q.calculated_value:
                lines.append(f"Valore: {q.calculated_value}")
            lines.append(f"Note: {q.notes}")
    
    if corrections:
        lines.append("")
        lines.append("=" * 80)
        lines.append("CORREZIONI")
        lines.append("=" * 80)
        for q in corrections:
            lines.append(f"{q.number}. {q.suggested_correction}  (era: {q.provided_answer})")
    
    lines.append("")
    lines.append("=" * 80)
    lines.append("ANSWER KEY CORRETTO")
    lines.append("=" * 80)
    for q in sorted(questions, key=lambda x: x.number):
        final = q.suggested_correction if q.suggested_correction else q.provided_answer
        flag = " [CORRETTO]" if q.suggested_correction else ""
        flag += " [VERIFICA]" if q.confidence == "low" else ""
        lines.append(f"{q.number}. {final}{flag}")
    
    return "\n".join(lines)

# ============================================================================
# STREAMLIT UI
# ============================================================================

def main():
    st.title("✅ QA Corrector")
    st.markdown("Verifica e correzione automatica di Q&A per exam prep")
    
    # Sidebar - Configurazione
    with st.sidebar:
        st.header("⚙️ Configurazione")
        
        api_key = st.text_input(
            "API Key Anthropic",
            type="password",
            help="Ottienila da console.anthropic.com"
        )
        
        model = st.selectbox(
            "Modello",
            ["claude-sonnet-4-20250514", "claude-haiku-4-5-20251001"],
            help="Sonnet: più accurato, Haiku: più veloce/economico"
        )
        
        st.markdown("---")
        st.markdown("### 💰 Costi stimati")
        st.markdown("""
        - **Sonnet**: ~$0.005/domanda
        - **Haiku**: ~$0.001/domanda
        
        100 domande ≈ $0.10 - $0.50
        """)
    
    # Main content
    tab1, tab2, tab3 = st.tabs(["📤 Carica File", "📊 Risultati", "📖 Guida"])
    
    with tab1:
        st.header("Carica il tuo file Q&A")
        
        input_method = st.radio(
            "Metodo di input:",
            ["📄 Testo (copia/incolla)", "📁 File TXT"],
            horizontal=True
        )
        
        text_content = ""
        filename = "input"
        
        if input_method == "📄 Testo (copia/incolla)":
            text_content = st.text_area(
                "Incolla qui il contenuto del tuo file Q&A:",
                height=400,
                placeholder="""1. What is 2+2?
A) 3
B) 4
C) 5
D) 6

2. What is the capital of France?
A) London
B) Paris
C) Berlin
D) Madrid

Answer Key:
1. B
2. B"""
            )
            filename = st.text_input("Nome file (opzionale):", value="qa_test")
        
        else:
            uploaded_file = st.file_uploader(
                "Carica file TXT:",
                type=['txt'],
                help="File di testo con domande e answer key"
            )
            if uploaded_file:
                text_content = uploaded_file.read().decode('utf-8')
                filename = uploaded_file.name.replace('.txt', '')
                st.success(f"File caricato: {uploaded_file.name}")
                with st.expander("Anteprima contenuto"):
                    st.text(text_content[:2000] + "..." if len(text_content) > 2000 else text_content)
        
        # Parse preview
        if text_content:
            questions, answer_key = parse_text_content(text_content)
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Domande trovate", len(questions))
            col2.metric("Answer Key", len(answer_key))
            col3.metric("Domande senza risposta", sum(1 for q in questions if q.provided_answer == "?"))
            
            if questions:
                with st.expander("Anteprima domande"):
                    for q in questions[:5]:
                        st.markdown(f"**Q{q.number}:** {q.text[:100]}...")
                        st.markdown(f"Opzioni: {list(q.options.keys())} | Answer: {q.provided_answer}")
                        st.markdown("---")
        
        # Verifica
        st.markdown("---")
        
        if st.button("🚀 Avvia Verifica", type="primary", disabled=not api_key or not text_content):
            if not api_key:
                st.error("Inserisci la API Key nella sidebar")
            elif not text_content:
                st.error("Carica o incolla il contenuto Q&A")
            else:
                try:
                    client = anthropic.Anthropic(api_key=api_key)
                    questions, _ = parse_text_content(text_content)
                    
                    if not questions:
                        st.error("Nessuna domanda trovata nel testo")
                    else:
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        results_container = st.container()
                        
                        start_time = time.time()
                        
                        for i, q in enumerate(questions):
                            status_text.text(f"Verifica domanda {i+1}/{len(questions)}...")
                            progress_bar.progress((i + 1) / len(questions))
                            
                            questions[i] = verify_question(client, q, model)
                            
                            # Gestione opzione mancante
                            if questions[i].correction_type == "option_missing":
                                questions[i].suggested_correction = determine_random_letter(questions, i)
                            
                            time.sleep(0.3)  # Rate limiting
                        
                        elapsed = time.time() - start_time
                        
                        # Salva risultati in session state
                        st.session_state['results'] = questions
                        st.session_state['filename'] = filename
                        st.session_state['elapsed'] = elapsed
                        
                        status_text.text("✅ Verifica completata!")
                        
                        # Statistiche finali
                        correct = sum(1 for q in questions if q.is_correct is True)
                        incorrect = sum(1 for q in questions if q.is_correct is False)
                        
                        with results_container:
                            col1, col2, col3, col4 = st.columns(4)
                            col1.metric("Totale", len(questions))
                            col2.metric("Corrette", correct, delta=None)
                            col3.metric("Errori", incorrect, delta=f"-{incorrect}" if incorrect else None)
                            col4.metric("Tempo", f"{elapsed:.1f}s")
                        
                        st.success("Vai alla tab 'Risultati' per vedere il report completo")
                        
                except anthropic.AuthenticationError:
                    st.error("API Key non valida")
                except Exception as e:
                    st.error(f"Errore: {str(e)}")
    
    with tab2:
        st.header("📊 Risultati")
        
        if 'results' not in st.session_state:
            st.info("Esegui prima una verifica nella tab 'Carica File'")
        else:
            questions = st.session_state['results']
            filename = st.session_state['filename']
            elapsed = st.session_state['elapsed']
            
            # Statistiche
            correct = sum(1 for q in questions if q.is_correct is True)
            incorrect = sum(1 for q in questions if q.is_correct is False)
            low_conf = sum(1 for q in questions if q.confidence == "low")
            
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Totale", len(questions))
            col2.metric("Corrette", correct)
            col3.metric("Errori", incorrect)
            col4.metric("Da verificare", low_conf)
            
            # Errori trovati
            errors = [q for q in questions if q.is_correct is False]
            if errors:
                st.subheader("❌ Errori Trovati")
                for q in errors:
                    with st.expander(f"Domanda {q.number}: {q.provided_answer} → {q.calculated_answer}"):
                        st.markdown(f"**Testo:** {q.text}")
                        st.markdown(f"**Opzioni:** {q.options}")
                        st.markdown(f"**Answer Key:** {q.provided_answer}")
                        st.markdown(f"**Risposta Corretta:** {q.calculated_answer}")
                        if q.calculated_value:
                            st.markdown(f"**Valore calcolato:** {q.calculated_value}")
                        st.markdown(f"**Confidenza:** {q.confidence}")
                        st.markdown(f"**Note:** {q.notes}")
            else:
                st.success("Nessun errore trovato! ✅")
            
            # Download report
            st.markdown("---")
            st.subheader("📥 Download Report")
            
            report = generate_report(questions, filename, elapsed)
            
            st.download_button(
                label="📄 Scarica Report TXT",
                data=report,
                file_name=f"{filename}_CORREZIONI.txt",
                mime="text/plain"
            )
            
            # Anteprima report
            with st.expander("Anteprima Report"):
                st.code(report, language=None)
    
    with tab3:
        st.header("📖 Guida")
        
        st.markdown("""
        ## Come usare QA Corrector
        
        ### 1. Ottieni una API Key
        - Vai su [console.anthropic.com](https://console.anthropic.com)
        - Crea un account o accedi
        - Genera una nuova API key
        - Incollala nella sidebar
        
        ### 2. Prepara il tuo file
        Il sistema supporta questi formati:
        
        **Formato 1: Answer Key separato**
        ```
        1. Domanda uno?
        A) Opzione A
        B) Opzione B
        C) Opzione C
        D) Opzione D
        
        Answer Key:
        1. B
        2. A
        ...
        ```
        
        **Formato 2: Risposta inline**
        ```
        1. Domanda uno?
        A) Opzione A
        B) Opzione B
        Correct Answer: B
        Explanation: ...
        ```
        
        ### 3. Avvia la verifica
        - Carica il file o incolla il testo
        - Clicca "Avvia Verifica"
        - Attendi il completamento
        
        ### 4. Scarica il report
        - Vai alla tab "Risultati"
        - Scarica il report TXT con tutte le correzioni
        
        ---
        
        ## Logica di correzione
        
        | Scenario | Azione |
        |----------|--------|
        | Risposta corretta = Answer Key | ✅ Passa |
        | Risposta corretta ≠ Answer Key | ⚠️ Corregge |
        | Risposta non nelle opzioni | 🔄 Assegna lettera bilanciata |
        | Bassa confidenza | 📝 Segnala per verifica manuale |
        
        ---
        
        ## Costi
        
        | Modello | Costo/domanda | 100 domande | 1000 domande |
        |---------|---------------|-------------|--------------|
        | Sonnet | ~$0.005 | ~$0.50 | ~$5 |
        | Haiku | ~$0.001 | ~$0.10 | ~$1 |
        """)


if __name__ == "__main__":
    main()
