import bisect
import json
import os
import re
from itertools import zip_longest

import numpy as np
import pdfplumber
from rapidfuzz import fuzz


def extract_text(pdf_path):
    texts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            texts.append(page.extract_text())
    return texts


def find_middle(path, dict_mid, debug_dir="debug_column"):
    os.makedirs(debug_dir, exist_ok=True)
    with pdfplumber.open(path) as pdf:
        n_pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            im = page.to_image(resolution=150)
            im.draw_vline(page.width * dict_mid.get(i, 0.5), stroke="red", stroke_width=2)
            im.save(f"{debug_dir}/pag_{i}.png")
    return {i + 1: dict_mid.get(i, 0.5) for i in range(n_pages)}


def drop_overlapping_spaces(page, min_overlap=2.0, max_gap=0.3):
    # Spaces that split words:
    # - drawn on top of the previous glyph (after the 'fi' and 'ti' ligatures of the 2010 exams, overlap
    #   of 2.2 to 2.7), as in 'Consti tuição'. Real spaces may overlap a little (0.5 to 1.4 in TRT 24ª 2011
    #   Arial), so only large overlaps are dropped
    # - squeezed between two glyphs that touch each other (OAB IV-VI, 2011-2012), as in 'Jo ão'
    # - alone in a line of their own (no glyph less than 1 above or below) a little below a text line, which
    #   pdfplumber merges into the text line after its first glyph, as in 'g ozadas' and 's em' (TRT 11ª 2017,
    #   TRT 2ª 2014, 2.8 below)
    chars = page.chars
    overlapping = {
        id(c) for prev, c in zip(chars, chars[1:])
        if c['text'] == ' ' and prev['x1'] - c['x0'] > min_overlap and abs(prev['top'] - c['top']) < 2
    }
    tops = sorted(c['top'] for c in chars if c['text'] != ' ')
    for c in chars:
        k = bisect.bisect_left(tops, c['top'] - 1)
        if c['text'] == ' ' and (k == len(tops) or tops[k] > c['top'] + 1):
            overlapping.add(id(c))
    lines = {}
    for c in chars:
        lines.setdefault(round(c['top']), []).append(c)
    for line in lines.values():
        line.sort(key=lambda c: c['x0'])
        for k, c in enumerate(line):
            if c['text'] != ' ':
                continue
            before = next((x for x in reversed(line[:k]) if x['text'] != ' '), None)
            after = next((x for x in line[k + 1:] if x['text'] != ' '), None)
            if before and after and after['x0'] - before['x1'] < max_gap and before['x1'] > c['x0']:
                overlapping.add(id(c))
    return page.filter(lambda obj: id(obj) not in overlapping)


ORDINALS = {'o': 'º', '0': 'º', 'a': 'ª'}


def fix_small_chars(page, max_ratio=0.8):
    # Glyphs drawn smaller than the previous one (superscripts and subscripts):
    # - the ordinal indicator after a digit or 'n' is a small 'o', 'a' (FCC) or '0' (MTE 2010):
    #   '13o' -> '13º', 'no' -> 'nº', '23a' -> '23ª', '§ 20' -> '§ 2º'
    # - subscripts go to the line of the previous glyph, so they are not read as a new line ('O2', not 'O .\n2')
    # The char dicts are changed in place
    chars = page.chars
    for prev, c in zip(chars, chars[1:]):
        if c['text'].isspace() or prev['text'].isspace() or c['size'] > max_ratio * prev['size']:
            continue
        # Right after the previous glyph and less than half a line above or below it (the first glyph of the
        # next line may start where the previous line ended, as 'Notícias' in OAB XL, question 18)
        if abs(c['x0'] - prev['x1']) > 2 or abs(c['top'] - prev['top']) > 0.6 * prev['size']:
            continue
        if c['text'] in ORDINALS and c['bottom'] < prev['bottom'] and (prev['text'].isdigit() or prev['text'] in 'nN'):
            c['text'] = ORDINALS[c['text']]
        elif c['top'] > prev['top']:
            c['top'], c['bottom'], c['doctop'] = prev['top'], prev['bottom'], prev['doctop']
    return page


def mark_missing_spaces(page, min_ratio=0.8, x_tolerance=3):
    # A gap of about a space width between two glyphs without a space glyph is a space ('estagiário com',
    # OAB XL, gap 1.8 for a space of 2.0); pdfplumber only splits words at gaps of x_tolerance (3). The gap
    # is compared with the space of the same font, as the letter spacing of roman numerals ('I I', gap 1.7
    # for a space of 2.5 in TRT 24ª 2011) is usually smaller than it; between two roman numeral letters it may
    # reach 2.2, so no space goes there ('III .' and 'EIA /RIMA' either: none goes around punctuation).
    # Glyphs without unicode ('(cid:24)', mapped later by the cleaning rules) are left as they are. The space
    # is appended to the text of the glyph before the gap (the char dicts are changed in place)
    chars = page.chars
    space_width = {}
    for c in (c for c in chars if c['text'] == ' '):
        space_width.setdefault((c['fontname'], round(c['size'], 1)), c['x1'] - c['x0'])
        space_width.setdefault(round(c['size'], 1), c['x1'] - c['x0'])
    lines = {}
    for c in chars:
        lines.setdefault(round(c['top']), []).append(c)
    for line in lines.values():
        line.sort(key=lambda c: c['x0'])
        for prev, c in zip(line, line[1:]):
            if prev['text'].isspace() or c['text'].isspace() or '(cid:' in prev['text'] + c['text']:
                continue
            if prev['text'] in 'IVX' and c['text'] in 'IVX' or c['text'] in '.,;:)/' or prev['text'] in '(/':
                continue
            size = round(prev['size'], 1)
            width = space_width.get((prev['fontname'], size), space_width.get(size))
            if not width or not min_ratio * width <= c['x0'] - prev['x1'] < x_tolerance:
                continue
            # A glyph in the gap on a raised neighbour line fills it: a space ('nº 237', the 'º' is raised) or the
            # '/' of 'EIA/RIMA'
            if not any(x['x0'] < c['x0'] and x['x1'] > prev['x1'] and abs(x['top'] - prev['top']) < 0.6 * prev['size']
                       for x in chars):
                prev['text'] += ' '
    return page


def extract_by_columns(pdf_path, dict_mid):
    texts_left = []
    texts_right = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            page = mark_missing_spaces(fix_small_chars(drop_overlapping_spaces(page.dedupe_chars(tolerance=1))))
            # The page box may not start at 0 (e.g. TRT 24ª 2011, top = -0.003)
            x0, top, x1, bottom = page.bbox
            width = x1 - x0
            mid = x0 + width * min(dict_mid.get(i, 0.5), 1.0)
            # Bounding boxes for each column
            left_box = (x0, top, mid, bottom)
            right_box = (mid, top, x1, bottom)

            # Extract the text of each column; a split of 1.0 means a page in a single column,
            # which goes all to the left side
            text_left = page.within_bbox(left_box).extract_text() or ""
            text_right = (page.within_bbox(right_box).extract_text() or "") if mid < x1 else ""

            texts_left.append(text_left)
            texts_right.append(text_right)
    return texts_left, texts_right


def join_texts(left, right):
    joined_texts = []
    for l, r in zip_longest(left, right, fillvalue=''):
        joined_texts.append((l or '') + '\n' + (r or ''))
    txt = '\n'.join(joined_texts)
    return txt


REGEX_FLAGS = {"M": re.M, "I": re.I, "S": re.S}


def load_rules(path="extraction_config/cleaning_rules.json", stage=None):
    # stage=None: rules for the whole exam text (before split_questions)
    # stage="question": rules for each question (after split_questions)
    with open(path, encoding="utf-8") as f:
        rules = json.load(f)
    if stage:
        rules = rules[stage]
    # A literal is either a string (removed) or {"value": ..., "replacement": ...}
    literals = [
        (s, "") if isinstance(s, str) else (s["value"], s.get("replacement", ""))
        for s in rules["literal"]
    ]
    patterns = []
    for r in rules["regex"]:
        flags = 0
        for letter in r.get("flags", ""):
            flags |= REGEX_FLAGS[letter]
        patterns.append((re.compile(r["pattern"], flags), r.get("replacement", "")))
    return literals, patterns


def clean_text(text, literals, patterns):
    for value, replacement in literals:
        text = text.replace(value, replacement)
    for pattern, replacement in patterns:
        text = pattern.sub(replacement, text)
    return text.strip()


QUESTION_NUMBER = re.compile(r'^(?:(?:Questão|QUESTÃO)\s*)?(\d{1,3})\s*$', re.M)


def question_chain(text, n_questions=None, max_gap=10):
    # Returns [(number, start, end), ...] of the question number lines
    candidates = [(int(m.group(1)), m.start(), m.end()) for m in QUESTION_NUMBER.finditer(text)]
    # Longest run 1, 2, 3, ... in text order; stray numbers (cover, page numbers) are skipped.
    # A jump of up to max_gap is accepted only when the next number never appears
    # (e.g. questions on an unreadable page)
    best = []
    for i, (num, _, _) in enumerate(candidates):
        if num != 1:
            continue
        chain = [candidates[i]]
        for j in range(i + 1, len(candidates)):
            cand, expected = candidates[j], chain[-1][0] + 1
            if cand[0] == expected or (
                expected < cand[0] <= expected + max_gap
                and all(later[0] != expected for later in candidates[j + 1:])
            ):
                chain.append(cand)
                if n_questions and len(chain) == n_questions:
                    break
        # On a tie the later run wins: a stray '01' on the cover comes before the questions
        if len(chain) >= len(best):
            best = chain
    return best


def find_question_pages(texts_left, texts_right, literals, patterns):
    # First and last page (0-based, inclusive) that have question text:
    # from the page with question 1 to the page with the last option (D) of the last question
    page_texts = [clean_text(left + '\n' + right, literals, patterns) for left, right in zip(texts_left, texts_right)]
    page_starts = []
    position = 0
    for page_text in page_texts:
        page_starts.append(position)
        position += len(page_text) + 1
    text = '\n'.join(page_texts)

    chain = question_chain(text)
    if not chain:
        return 0, len(page_texts) - 1
    last_option_d = [m.start() for m in re.finditer(r'^\(?[ \t]*D(?:[ \t]*\)|[ \t])', text, re.M) if m.start() > chain[-1][1]]
    last_position = last_option_d[0] if last_option_d else chain[-1][1]
    page_of = lambda pos: max(i for i, start in enumerate(page_starts) if start <= pos)
    return page_of(chain[0][1]), page_of(last_position)


def split_questions(text, n_questions=None):
    best = question_chain(text, n_questions)
    questions = {}
    for k, (num, _, end) in enumerate(best):
        next_start = best[k + 1][1] if k + 1 < len(best) else len(text)
        questions[num] = text[end:next_start].strip()
    return questions


# Matches "A) ", "(A) " and "A ) " at the start of a line
OPTION = re.compile(r'^\(?[ \t]*([A-E])[ \t]*\)[ \t]*', re.M)
# Letter followed by a space, without parenthesis ("A texto", CESPE exams); used only
# when no option with parenthesis is found, since the article "A" also starts lines
OPTION_NO_PARENTHESIS = re.compile(r'^([A-E])[ \t]+', re.M)


def process_options(question, literals, patterns, letters="ABCD"):
    # Splits before cleaning: the option markers are found by the line breaks
    chain = []
    for option_pattern in (OPTION, OPTION_NO_PARENTHESIS):
        markers = list(option_pattern.finditer(question))
        # Last run A, B, C, D in text order: the options always close the question
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
        if chain:
            break
    if not chain:
        return clean_text(question, literals, patterns), {}
    statement = clean_text(question[:chain[0].start()], literals, patterns)
    options = {}
    for k, m in enumerate(chain):
        end = chain[k + 1].start() if k + 1 < len(chain) else len(question)
        options[m.group(1).lower()] = clean_text(question[m.end():end], literals, patterns)
    return statement, options


def extract_questions(questions_split, literals, patterns, n_options=4):
    letters = 'ABCDE'[:n_options]
    list_questions = []
    for question_number, question_text in questions_split.items():
        question, options_dict = process_options(question_text, literals, patterns, letters)
        if len(options_dict) != n_options:
            print(f'Question {question_number} has {len(options_dict)} options instead of {n_options}.')
        list_questions.append({
            'question_number': question_number,
            'question': question,
            'options': options_dict
        })
    return list_questions


ANSWER = re.compile(r'[A-D*]')
# Correspondence table row: "TIPO1 TIPO2 TIPO3 TIPO4 Gabarito", two tables side by side
CORRESPONDENCE_ROW = re.compile(r'^(\d+) \d+ \d+ \d+ ([A-D*])(?: (\d+) \d+ \d+ \d+ ([A-D*]))?$', re.M)
NUMBER_DASH_ANSWER = re.compile(r'\b(\d{1,3}) – ([A-D*])\b')


def extract_answer_key(pdf_path):
    # Returns {question_number: 'A'..'D'}, or None for an annulled question ('*')
    with pdfplumber.open(pdf_path) as pdf:
        text = '\n'.join(page.extract_text() or '' for page in pdf.pages)
    lines = [line.strip() for line in text.split('\n')]

    # Grid format: a line of question numbers followed by a line of answers, optionally
    # labeled "Questão" / "Gabarito" (CESPE exam).
    # Only the first block (Tipo 1) is read; it ends when the numbering restarts at 1.
    answer_key = {}
    for numbers_line, answers_line in zip(lines, lines[1:]):
        if not re.fullmatch(r'(?:Questão )?\d+( \d+)+', numbers_line):
            continue
        numbers = [int(n) for n in numbers_line.removeprefix('Questão ').split()]
        answers = answers_line.removeprefix('Gabarito ').split()
        if numbers[0] == 1 and answer_key:
            break
        if len(answers) == len(numbers) and all(ANSWER.fullmatch(a) for a in answers):
            answer_key.update(zip(numbers, answers))

    # Correspondence table format (e.g. XII exam), used when the grid is not found
    if not answer_key:
        for m in CORRESPONDENCE_ROW.finditer(text):
            answer_key[int(m.group(1))] = m.group(2)
            if m.group(3):
                answer_key[int(m.group(3))] = m.group(4)

    # List format "001 – C; 002 – A; ..." (II exam)
    if not answer_key:
        for m in NUMBER_DASH_ANSWER.finditer(text):
            answer_key[int(m.group(1))] = m.group(2)

    return {n: None if a == '*' else a for n, a in sorted(answer_key.items())}


def score_fuzz(question, df, threshold=97, options=None):
    # Positions (0-based, use with df.iloc) of the rows of df whose question scores above threshold.
    # With options (list of strings; df['options'] must hold lists too) the options are compared
    # as well, for statements that repeat across exams with different options
    if options is None:
        text, candidates = question, df['question']
    else:
        text = question + ' ' + ' '.join(options)
        candidates = [q + ' ' + ' '.join(o) for q, o in zip(df['question'], df['options'])]
    scores = np.array([fuzz.token_sort_ratio(text, candidate) for candidate in candidates])
    return np.where(scores > threshold)[0]
