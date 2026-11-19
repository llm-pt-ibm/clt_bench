# CLTBench – extraction pipeline

Code that builds **CLTBench**, a dataset of multiple-choice questions on Brazilian labor law and labor procedural law (*Consolidação das Leis do Trabalho*, CLT) from official examinations. The questions and answer keys are extracted from the original PDF files of the examinations and joined into one dataset.

The current dataset has **1,330 questions** from **111 examinations** (2003–2026):

| Source | Examinations | Questions |
|---|---|---|
| Regional Labor Courts (TRT) – public service examinations | 57 | 869 |
| Brazilian Bar Examination (OAB) | 48 | 286 |
| Ministry of Labor and Employment (MTE) – Auditor-Fiscal do Trabalho | 6 | 175 |

The dataset is published on Zenodo (version 1.0.1: DOI [10.5281/zenodo.23814931](https://doi.org/10.5281/zenodo.23814931)).

## Repository layout

```
.
├── all_exams_trt/          # PDFs of the TRT examinations and answer keys (one folder per region/year/position)
├── all_exams_oab/          # PDFs of the OAB examinations ('<exam>.pdf') and answer keys ('<exam>[gabarito].pdf')
├── all_exams_mte/          # PDFs of the MTE examinations ('<exam>-prova.pdf') and answer keys ('<exam>-gabarito.pdf')
├── oab_questions_filtered/ # Labor law questions of the OAB, exported from a question bank (HTML)
├── mte_questions_filtered/ # Labor law questions of the MTE Curso de Formação, exported from a question bank (HTML)
├── extraction_config/      # Configuration of the extraction (see below)
├── utils/                  # Extraction functions (utils_oab.py is shared by all the sources)
├── csvs/                   # Intermediate files: the questions extracted from each source
├── *.ipynb                 # Pipeline notebooks (see below)
├── cltbench.csv            # Dataset (CSV, options as a JSON string)
├── cltbench.jsonl          # Dataset (JSON Lines, options as a JSON object)
├── data_dictionary.csv     # Description of every column of the dataset
└── requirements.txt
```

### `extraction_config/`

| File | Content |
|---|---|
| `trt_exams.json` | The TRT examinations of the dataset: name, paths of the exam and of the answer key, and position. |
| `trt_labor_law_question_ranges.json` | Question numbers of the labor law and labor procedural law sections of each TRT examination. |
| `cleaning_rules.json` | Text cleaning rules (literals and regular expressions) of the OAB examinations. |
| `cleaning_rules_trt.json`, `cleaning_rules_mte.json`, `cleaning_rules_mte_formacao.json` | Text cleaning rules of the TRT, MTE (ESAF) and MTE Curso de Formação examinations. |
| `answer_key_corrections.json` | Answers of the final answer key where the answer key PDF is the preliminary one, with the reason of each correction. |

Each cleaning rule has a `note` with the case it fixes. Rules run on the whole text of the examination or, in the `question` stage, on each question.

### Inputs that are not extracted automatically

- `csvs/oab/oab_questions_manual.csv`: OAB questions that are unreadable in the PDF, typed manually.
- Answer keys of 23 TRT examinations that were only available as scanned images were transcribed into text PDFs (`...-gabarito.pdf`); the original image is kept next to it (`...-gabarito-original.pdf`).

## Setup

Python 3.11:

```bash
python3.11 -m venv clt_bench_env
source clt_bench_env/bin/activate
pip install -r requirements.txt
```

Run the notebooks from the repository root (all the paths are relative to it), in Jupyter or VS Code with the `clt_bench_env` kernel.

## Running the pipeline

The extraction notebooks process **one examination at a time**: set the `idx = ...` line to the position of the examination in `exams_list` and run the whole notebook, once for each examination. Each run replaces the rows of that examination in its CSV, so examinations can be run in any order and run again.

### 1. TRT

| Notebook | `idx` | Output |
|---|---|---|
| `get_answers_trt.ipynb` | 0 to 56 | `csvs/trt/trt_questions_all_bench.csv` (labor law questions with answer) and `csvs/trt/trt_annulled_questions.csv` (annulled questions) |

### 2. OAB

| Notebook | `idx` | Output |
|---|---|---|
| `read_oab_questions.ipynb` | – | `csvs/oab/oab_questions_unified_no_answer.csv`: labor law questions of the question bank (only needed if the HTML files change) |
| `get_answers_oab.ipynb` | 0 to 47 | `csvs/oab/oab_questions_all.csv`: all the questions of each examination, with the answer key |
| `match_oab.ipynb` | – | `csvs/oab/oab_questions_with_answer.csv`: the labor law questions, matched with the extracted ones |

### 3. MTE

| Notebook | `idx` | Output |
|---|---|---|
| `read_exams_mte.ipynb` | 0 to 2 | `csvs/mte/mte_esaf_questions_all.csv`: labor law questions of the ESAF examinations |
| `read_mte_formacao_questions.ipynb` | – | `csvs/mte/mte_formacao_questions_unified_no_answer.csv`: labor law questions of the question bank (only needed if the HTML files change) |
| `get_answers_mte_formacao.ipynb` | 0 to 2 | `csvs/mte/mte_formacao_questions_all.csv`: all the questions of each Curso de Formação examination |
| `match_mte_formacao.ipynb` | – | `csvs/mte/mte_formacao_questions_with_answer.csv` and `csvs/mte/mte_questions_all.csv` (ESAF + Curso de Formação) |

Run `read_exams_mte.ipynb` before `match_mte_formacao.ipynb`, which joins both MTE lists.

### 4. Dataset

`build_dataset.ipynb` reads the three lists (`trt_questions_all_bench.csv`, `oab_questions_with_answer.csv`, `mte_questions_all.csv`) and:

1. joins them;
2. removes duplicated questions (same statement and options);
3. removes questions with extraction failures (wrong number of options, empty option, option letter left in the text, answer that is not an option);
4. creates the columns of the data dictionary (`year`, `board`, `position`, `institution`, `exam_type`, word and token counts);
5. orders the questions (TRT, OAB, MTE; most recent examinations first), assigns the `id` and saves `cltbench.csv` and `cltbench.jsonl`.

The notebooks print what they remove at each step: annulled questions (no answer in the answer key), duplicated questions and questions with failures. Only questions with a complete statement, all options and an answer go into the dataset.

## Notes

- `get_answers_oab.ipynb` and `get_answers_mte_formacao.ipynb` save an image of each page with the column split to `debug_column/` (not versioned), to check the split of two-column pages.
- Token counts use the `o200k_base` tokenizer of `tiktoken`, which is downloaded on its first use.
- The questions belong to the examination boards that prepared them (FCC, FGV, ESAF and CESPE/CEBRASPE).
