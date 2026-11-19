import re

import pdfplumber

from utils.utils_oab import clean_text

SECTION_START = re.compile(r'^DIREITO DO TRABALHO$', re.M)
# Next section title: a line only with uppercase letters, e.g. 'ECONOMIA DO TRABALHO', 'DIREITO:',
# or the list of acronyms that opens the next section (2010)
SECTION_END = re.compile(r'^(?:[A-ZÀ-Ü][A-ZÀ-Ü :]{6,}|Lista de Siglas.*)$', re.M)


def extract_section(text):
    # Text between the 'DIREITO DO TRABALHO' title and the title of the next section
    start = SECTION_START.search(text)
    if not start:
        return ''
    end = SECTION_END.search(text, start.end())
    return text[start.end():end.start() if end else len(text)].strip()


# '01- text', '1 - text', '16-text'
QUESTION_START = re.compile(r'^(\d{1,2})[ \t]*-[ \t]*', re.M)


def question_chain(text):
    # Longest run n, n+1, n+2, ... in text order; the section may start at any number (e.g. 16)
    candidates = [(int(m.group(1)), m.start(), m.end()) for m in QUESTION_START.finditer(text)]
    best = []
    for i, first in enumerate(candidates):
        chain = [first]
        for cand in candidates[i + 1:]:
            if cand[0] == chain[-1][0] + 1:
                chain.append(cand)
        if len(chain) > len(best):
            best = chain
    return best


def split_questions(text):
    chain = question_chain(text)
    questions = {}
    for k, (num, _, end) in enumerate(chain):
        next_start = chain[k + 1][1] if k + 1 < len(chain) else len(text)
        questions[num] = text[end:next_start].strip()
    return questions


# 'a) text' at the start of a line
OPTION = re.compile(r'^([a-e])\)[ \t]*', re.M)


def process_options(question, literals, patterns, letters='abcde'):
    # Last run a, b, c, d, e in text order: the options always close the question
    markers = list(OPTION.finditer(question))
    chain = []
    for i, m in enumerate(markers):
        if m.group(1) != letters[0]:
            continue
        candidate = [m]
        for nxt in markers[i + 1:]:
            if len(candidate) == len(letters):
                break
            if nxt.group(1) == letters[len(candidate)]:
                candidate.append(nxt)
        if len(candidate) == len(letters):
            chain = candidate
    if not chain:
        return clean_text(question, literals, patterns), {}
    statement = clean_text(question[:chain[0].start()], literals, patterns)
    options = {}
    for k, m in enumerate(chain):
        end = chain[k + 1].start() if k + 1 < len(chain) else len(question)
        options[m.group(1)] = clean_text(question[m.end():end], literals, patterns)
    return statement, options


def extract_questions(questions_split, literals, patterns):
    list_questions = []
    for question_number, question_text in questions_split.items():
        question, options_dict = process_options(question_text, literals, patterns)
        if len(options_dict) != 5:
            print(f'Question {question_number} has {len(options_dict)} options instead of 5.')
        list_questions.append({
            'question_number': question_number,
            'question': question,
            'options': options_dict,
        })
    return list_questions


def answer_key_text(pdf_path, block_start):
    # Text of the answer key block of the exam: from block_start to the next 'Prova' title
    with pdfplumber.open(pdf_path) as pdf:
        text = '\n'.join(page.extract_text() or '' for page in pdf.pages)
    start = re.search(block_start, text, re.M)
    if not start:
        return ''
    end = re.compile(r'^(?:Prova|PPrroovvaa)', re.M).search(text, start.end())
    return text[start.end():end.start() if end else len(text)]


NUMBER_DASH_ANSWER = re.compile(r'\b(\d{1,2})[ \t]*-[ \t]*([A-E*])\b')


def extract_answer_key(pdf_path, block_start):
    # Returns {question_number: 'A'..'E'}, or None for an annulled question ('*')
    text = answer_key_text(pdf_path, block_start)
    # List format '01 - B' or '01-B'
    answer_key = {int(n): a for n, a in NUMBER_DASH_ANSWER.findall(text)}
    # Grid format: a line of question numbers followed by a line of answers
    if not answer_key:
        lines = [line.strip() for line in text.split('\n')]
        for numbers_line, answers_line in zip(lines, lines[1:]):
            numbers, answers = numbers_line.split(), answers_line.split()
            if (re.fullmatch(r'\d+( \d+)+', numbers_line) and len(numbers) == len(answers)
                    and all(re.fullmatch(r'[A-E*]', a) for a in answers)):
                answer_key.update(zip(map(int, numbers), answers))
    return {n: None if a == '*' else a for n, a in sorted(answer_key.items())}


def extract_answer_key_formacao(pdf_path):
    # Curso de Formação (CEBRASPE): 'Questão 1 2 3 ...' followed by 'Gabarito E B X ...'.
    # Returns {question_number: 'A'..'E'}, or None for an annulled question ('X')
    with pdfplumber.open(pdf_path) as pdf:
        text = '\n'.join(page.extract_text() or '' for page in pdf.pages)
    lines = [line.strip() for line in text.split('\n')]
    answer_key = {}
    for numbers_line, answers_line in zip(lines, lines[1:]):
        if not (re.fullmatch(r'Questão( \d+)+', numbers_line) and answers_line.startswith('Gabarito ')):
            continue
        numbers = [int(n) for n in numbers_line.split()[1:]]
        answers = answers_line.split()[1:]
        if len(numbers) == len(answers) and all(re.fullmatch(r'[A-EX]', a) for a in answers):
            answer_key.update(zip(numbers, answers))
    return {n: None if a == 'X' else a for n, a in sorted(answer_key.items())}
