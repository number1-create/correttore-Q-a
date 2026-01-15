# Correttore Q&A

Applicazione per validare e correggere quiz a risposta multipla usando AI.

## Come funziona

1. **Legge la domanda** dal file JSON
2. **Risolve la domanda** usando Claude AI (calcola la risposta indipendentemente)
3. **Cerca la risposta** calcolata tra le opzioni disponibili
4. **Confronta** con la lettera marcata come corretta
5. **Segnala errori** e propone correzioni

## Installazione

```bash
# Crea ambiente virtuale
python -m venv venv
source venv/bin/activate  # Linux/Mac
# oppure: venv\Scripts\activate  # Windows

# Installa dipendenze
pip install -r requirements.txt

# Configura API key
cp .env.example .env
# Modifica .env con la tua ANTHROPIC_API_KEY
```

## Uso

```bash
# Validazione semplice
python main.py examples/sample_questions.json

# Validazione con correzione automatica
python main.py examples/sample_questions.json --auto-correct

# Elaborazione in background
python main.py examples/sample_questions.json --background

# Specifica file output
python main.py input.json --auto-correct --output output/corrected.json
```

## Formato dati

Il file JSON deve contenere un array di domande:

```json
[
  {
    "id": "Q001",
    "question": "Quanto fa 2 + 2?",
    "answers": [
      {"letter": "A", "text": "3"},
      {"letter": "B", "text": "4"},
      {"letter": "C", "text": "5"},
      {"letter": "D", "text": "6"}
    ],
    "correct_answer": "B",
    "category": "Matematica"
  }
]
```

## Output

- **Report JSON**: `output/report_YYYYMMDD_HHMMSS.json`
- **File corretto**: `output/corrected_questions.json`

## Tipi di correzione

- `wrong_answer_letter`: La lettera corretta è sbagliata
- `wrong_answer_text`: Il testo di una risposta è sbagliato
- `wrong_question`: La domanda è ambigua/errata
- `no_correct_option`: Nessuna opzione corrisponde alla soluzione

## Uso programmatico

```python
from processor import QAProcessor
from pathlib import Path

# Crea processore
processor = QAProcessor()

# Carica domande
processor.load_questions(Path("questions.json"))

# Processa tutte
results, corrections = processor.process_all(auto_correct=True)

# Oppure in background
def on_progress(current, total, result):
    print(f"Progresso: {current}/{total}")

processor.on_progress = on_progress
thread = processor.start_background_processing(auto_correct=True)
```
