import os
import re

import pdfplumber

# Name of the qconcursos files, e.g. 'fcc-2013-trt-12-regiao-sc-analista-judiciario-area-judiciaria-prova.pdf'
# or 'trt-2r-sp-2013-trt-2-regiao-sp-juiz-do-trabalho-gabarito.pdf'; the state ('sc', 'am-e-rr') is optional
EXAM_FILE = re.compile(
    r'(?P<year>\d{4})-trt-(?P<region>\d+)-regiao(?:-[a-z]{2}(?:-e-[a-z]{2})?)?-(?P<position>.+)-(?P<kind>prova|gabarito)\.pdf$'
)

# Pieces of the position slug and their names in the bench ('analista-judiciario-area-judiciaria' ->
# 'Analista Judiciário - Área Judiciária')
POSITION_PARTS = {
    'analista-judiciario': 'Analista Judiciário',
    'tecnico-judiciario': 'Técnico Judiciário',
    'area-judiciaria': 'Área Judiciária',
    'area-administrativa': 'Área Administrativa',
    'administrativa': 'Área Administrativa',
    'especialidade-oficial-de-justica-avaliador-federal': 'Especialidade Oficial de Justiça Avaliador Federal',
    'oficial-de-justica-avaliador-federal': 'Oficial de Justiça Avaliador Federal',
    'oficial-de-justica-avaliador': 'Oficial de Justiça Avaliador',
    'execucao-de-mandados': 'Execução de Mandados',
    'juiz-do-trabalho-substituto': 'Juiz do Trabalho Substituto',
    'juiz-do-trabalho': 'Juiz do Trabalho',
}


def position_from_slug(slug):
    # Longest piece first: 'oficial-de-justica-avaliador-federal' before 'oficial-de-justica-avaliador'
    parts = []
    while slug:
        key = next((k for k in sorted(POSITION_PARTS, key=len, reverse=True)
                    if slug == k or slug.startswith(k + '-')), None)
        if key is None:
            # Unknown piece: kept as it is
            parts.append(slug.replace('-', ' '))
            break
        parts.append(POSITION_PARTS[key])
        slug = slug[len(key) + 1:]
    return ' - '.join(parts)


def list_exams(root='all_exams_trt'):
    # One row per exam with the paths of the exam and of the answer key, and the name used in the
    # bench: '{position} - TRT {region}ª Região - {year}'. The folders are not used, only the file names
    exams = {}
    for folder, _, files in os.walk(root):
        for file in files:
            m = EXAM_FILE.search(file)
            if not m:
                continue
            region, year = int(m['region']), int(m['year'])
            position = position_from_slug(m['position'])
            exam = f'{position} - TRT {region}ª Região - {year}'
            row = exams.setdefault(exam, {'exam': exam, 'position': position, 'region': region, 'year': year})
            row[f"{m['kind']}_path"] = os.path.join(folder, file)
    return sorted(exams.values(), key=lambda r: (r['region'], r['year'], r['position']))


def line_starts(words, x_min, x_max, gap=10):
    # Words between x_min and x_max that start a line: no word just before them on the same line
    return [
        w for w in words
        if x_min <= w['x0'] <= x_max
        and not any(abs(v['top'] - w['top']) < 2 and 0 <= w['x0'] - v['x1'] < gap for v in words)
    ]


def page_split(page, min_starts=10, max_crossing=5):
    # Column split of the page as a fraction of the width, in the format of dict_mid:
    # 1.0 for a page in a single column (whole width).
    # Two columns: many lines start just right of the middle and almost no word crosses the middle
    # (only headers and footers); tables, poems and short options of whole-width pages fail this
    width = page.width
    words = page.extract_words()
    crossing = [w for w in words if w['x0'] < width / 2 < w['x1']]
    starts = line_starts(words, 0.5 * width, 0.62 * width)
    if len(starts) < min_starts or len(crossing) > max_crossing:
        return 1.0
    # Cut between the end of the left column and the start of the right column
    right = min(w['x0'] for w in starts)
    left = max((w['x1'] for w in words if w['x1'] <= right), default=width / 2)
    return round((left + right) / 2 / width, 3)


def find_columns(pdf_path):
    # {page_index: split} for every page of the exam; use it as the dict_mid of extract_by_columns
    with pdfplumber.open(pdf_path) as pdf:
        return {i: page_split(page) for i, page in enumerate(pdf.pages)}


def exam_text(pdf_path, literals, patterns):
    # Whole text of the exam, column by column, already cleaned with the rules of the whole text
    from utils.utils_oab import extract_by_columns, join_texts, clean_text
    texts_left, texts_right = extract_by_columns(pdf_path, find_columns(pdf_path))
    return fill_lacunas(clean_text(join_texts(texts_left, texts_right), literals, patterns))


# Blank of the FCC fill-in-the-blank questions ('lacunas'), drawn with the glyph ''
LACUNA = ''
LACUNA_LABELS = re.compile(r'[IVX]+(?:[ \t]+[IVX]+)*')
# Label inside the blank: ' I para', or 'II' split by the glyph: ' I  I .' (TRT 23ª 2022)
LACUNA_BOXED = re.compile(LACUNA + r' ?([IVX]+) ?' + LACUNA + r' ?([IVX]+\b)?')


def fill_lacunas(text):
    # Writes the label of each blank in its place: 'receber I do aviso prévio' (as in the exam).
    # 2022: the labels are on the line above the blanks ('I II' / 'receber  do ...,  da')
    lines = text.split('\n')
    k = 0
    while k + 1 < len(lines):
        labels = lines[k].split()
        if LACUNA_LABELS.fullmatch(lines[k].strip()) and lines[k + 1].count(LACUNA * 2) == len(labels):
            line = lines[k + 1]
            for label in labels:
                m = re.search(LACUNA * 2, line)
                space = ' ' if line[m.end():m.end() + 1].isalnum() else ''
                line = line[:m.start()] + label + space + line[m.end():]
            lines[k:k + 2] = [line]
        k += 1
    text = '\n'.join(lines)
    text = LACUNA_BOXED.sub(lambda m: m.group(1) + (m.group(2) or '') + ' ', text)
    # Blanks alone on a line, whose labels are already in the text ('conceder II o benefício', TRT 21ª 2017)
    return re.sub(r'^[ \t' + LACUNA + r']*' + LACUNA + r'[ \t' + LACUNA + r']*\n?', '', text, flags=re.M)


# '21. text' (FCC) or '21' alone on the line (FGV)
QUESTION_DOT = re.compile(r'^(\d{1,3})\s?[.\-]\s?(?=\S)', re.M)
QUESTION_ALONE = re.compile(r'^(\d{1,3})[ \t]*$', re.M)


def question_chain(text, pattern, max_gap=5):
    # Longest run 1, 2, 3, ... in text order: [(number, start, end), ...] of the question numbers. The run
    # may start at 2 and a jump of up to max_gap is accepted when the next number never appears (numbers
    # lost by OCR)
    candidates = [(int(m.group(1)), m.start(), m.end()) for m in pattern.finditer(text)]
    best = []
    for i, (num, _, _) in enumerate(candidates):
        if num > 2:
            continue
        chain = [candidates[i]]
        for j in range(i + 1, len(candidates)):
            cand, expected = candidates[j], chain[-1][0] + 1
            if cand[0] == expected or (
                expected < cand[0] <= expected + max_gap
                and all(later[0] != expected for later in candidates[j + 1:])
            ):
                chain.append(cand)
        if len(chain) >= len(best):
            best = chain
    return best


def exam_chain(text):
    # The numbering style of the exam is the one that finds more questions
    return max(question_chain(text, QUESTION_DOT), question_chain(text, QUESTION_ALONE), key=len)


# Section title: a line without sentence punctuation, e.g. 'Direito do Trabalho', 'BLOCO I'
TITLE_LINE = re.compile(r'^[^.;:?!()\n]{3,80}$')


def title_lines(text):
    # Section title at the end of text (up to 3 lines), e.g. ['BLOCO I', 'Direito Individual e Coletivo do
    # Trabalho']; [] when the last lines are not a title
    lines = [line.strip() for line in text.split('\n') if line.strip() and not re.fullmatch(r'[_\s]+', line)]
    titles = []
    for line in reversed(lines[-3:]):
        if not (TITLE_LINE.match(line) and re.search(r'[A-Za-zÀ-ü]{4,}', line)):
            break
        titles.insert(0, line)
    # A title starts with an uppercase letter; lowercase lines only continue it
    while titles and not re.match(r'[A-ZÀ-Ü]', titles[0]):
        titles.pop(0)
    return titles


def find_sections(text):
    # Subjects of the exam: [(first question, last question, title), ...]. A section starts at a question
    # preceded by a title
    chain = exam_chain(text)
    starts = []
    for k, (num, position, _) in enumerate(chain):
        previous = chain[k - 1][1] if k else max(0, position - 400)
        titles = title_lines(text[previous:position])
        if titles or k == 0:
            starts.append((num, ' / '.join(titles)))
    last = chain[-1][0] if chain else None
    return [(num, starts[i + 1][0] - 1 if i + 1 < len(starts) else last, title)
            for i, (num, title) in enumerate(starts)]


def split_questions(text):
    # {number: text} of every question of the exam. The title of the next section is cut from the end of
    # the last question of a section
    chain = exam_chain(text)
    questions = {}
    for k, (num, _, end) in enumerate(chain):
        question = text[end:chain[k + 1][1] if k + 1 < len(chain) else len(text)]
        titles = title_lines(question)
        if titles:
            question = question[:question.rindex(titles[0])]
        questions[num] = question.strip()
    return questions


LABOR_SECTION = re.compile(r'Direito (?:Individual e Coletivo |Processual )?do Trabalho', re.I)


def labor_law_ranges(text):
    # [[first, last], ...] of the Direito do Trabalho and Direito Processual do Trabalho sections;
    # sections that follow each other are joined in one range
    ranges = []
    for first, last, title in sorted(find_sections(text)):
        if not LABOR_SECTION.search(title):
            continue
        if ranges and first == ranges[-1][1] + 1:
            ranges[-1][1] = last
        else:
            ranges.append([first, last])
    return ranges


# Header of the FCC exams 'Caderno de Prova ’B02’, Tipo 001'; FGV footer 'Tipo 1 – Cor BRANCA'
EXAM_HEADER = re.compile(r"Prova\s*['’`‘]?([A-Z0-9]{2,4})['’`‘]?\s*,\s*Tipo\s*(\d+)")
FGV_TYPE = re.compile(r'Tipo (\d+)\s*–\s*Cor')


def exam_type(pdf_path, pages=4):
    # (position code, exam type) printed on the exam, e.g. ('B02', 1): they choose the block of the
    # answer key. FGV exams have no code: ('', 1). The most frequent header wins (OCR misreads some)
    with pdfplumber.open(pdf_path) as pdf:
        text = '\n'.join(page.extract_text() or '' for page in pdf.pages[:pages])
    headers = EXAM_HEADER.findall(text)
    if headers:
        code, exam_type_number = max(headers, key=headers.count)
        # OCR reads the zero of the code as the letter O ('AO1')
        return code[0] + code[1:].replace('O', '0'), int(exam_type_number)
    types = FGV_TYPE.findall(text)
    return '', int(max(types, key=types.count)) if types else None


# FCC list '001 - C' (the dash may be a soft hyphen); 'T' and '*' have no single answer
ANSWER_PAIR = re.compile(r'\b(\d{3})\s*[-­]\s*([A-E*T])\b')
# FCC table '1 C Gabarito sem alteração' (TRT 11ª 2024, 12ª 2023)
ANSWER_ROW = re.compile(r'^(\d{1,3}) ([A-E*])\b', re.M)
# Start of the block of a position: 'Cargo ou opção B02 - ...', 'Cargo: A01 - ...' or '01056811 A02 ­ ...'
POSITION_BLOCK = re.compile(r'(?:Cargo ou [Oo]pção:?|Cargo:|^\d{8})\s+([A-Z][A-Z0-9]{1,3})\s*[-­]', re.M)
BLOCK_TYPE = re.compile(r'Tipo (?:de )?[Gg]abarito:?\s*(\d+)')
# FGV block 'Analista Judiciário - Área Judiciária - Sem Especialidade – Tipo 1' followed by a grid
FGV_BLOCK = re.compile(r'^(.+?) – Tipo (\d+)$', re.M)


def answer_key_blocks(text):
    # [(code, type, text), ...] of the FCC blocks; one block per position and type
    starts = list(POSITION_BLOCK.finditer(text))
    blocks = []
    for k, m in enumerate(starts):
        block = text[m.start():starts[k + 1].start() if k + 1 < len(starts) else len(text)]
        block_type = BLOCK_TYPE.search(block)
        blocks.append((m.group(1), int(block_type.group(1)) if block_type else None, block))
    return blocks


def fgv_answer_key(text, position, exam_type_number):
    # Block of the type whose title shares more words with the position (Jaccard), then the grid:
    # a line of question numbers followed by a line of answers
    words = lambda s: set(re.findall(r'\w+', s.lower()))
    titles = [m for m in FGV_BLOCK.finditer(text) if int(m.group(2)) == exam_type_number]
    if not titles:
        return {}
    score = lambda m: len(words(m.group(1)) & words(position)) / len(words(m.group(1)) | words(position))
    best = max(titles, key=score)
    next_title = FGV_BLOCK.search(text, best.end())
    lines = text[best.end():next_title.start() if next_title else len(text)].split('\n')
    answer_key = {}
    for numbers_line, answers_line in zip(lines, lines[1:]):
        numbers, answers = numbers_line.split(), answers_line.split()
        if (re.fullmatch(r'\d+( \d+)+', numbers_line.strip()) and len(numbers) == len(answers)
                and all(re.fullmatch(r'[A-E*]', a) for a in answers)):
            answer_key.update(zip(map(int, numbers), answers))
    return answer_key


def extract_answer_key(pdf_path, code, exam_type_number, position):
    # Returns {question_number: 'A'..'E'}, or None for an annulled question ('*', 'T'); {} when the
    # answer key has no text (scanned image) or no block of the exam
    with pdfplumber.open(pdf_path) as pdf:
        text = '\n'.join(page.extract_text() or '' for page in pdf.pages)
    blocks = answer_key_blocks(text)
    if blocks:
        block = next((b for c, t, b in blocks if c == code and t == exam_type_number), '')
        answer_key = {int(n): a for n, a in ANSWER_PAIR.findall(block)}
        if not answer_key:
            answer_key = {int(n): a for n, a in ANSWER_ROW.findall(block)}
    else:
        answer_key = fgv_answer_key(text, position, exam_type_number)
    return {n: None if a in '*T' else a for n, a in sorted(answer_key.items())}
