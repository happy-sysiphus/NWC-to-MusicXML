#!/usr/bin/env python3
"""NoteWorthy Composer 악보(.nwc, .nwctxt) → MusicXML 변환기. 표준 라이브러리만 사용.

사용법:
    python nwc2musicxml.py 악보.nwc [다른파일.nwctxt 폴더 ...] [-o 출력폴더] [--nwctxt]

.nwc(2.75, [NWZ] 압축)는 zlib을 풀면 NWCTXT 텍스트가 그대로 들어 있어 그것을 읽는다.
2.75 이전 바이너리 .nwc는 지원하지 않는다(NoteWorthy Composer에서 .nwctxt로 저장해서 쓰면 된다).
"""
import argparse
import datetime
import re
import sys
import zlib
import xml.etree.ElementTree as ET
from pathlib import Path

DIV = 192  # 4분음표당 틱. 64분음표·겹점·셋잇단까지 정수로 떨어지는 최소값
BASE = {'Whole': 4 * DIV, 'Half': 2 * DIV, '4th': DIV, '8th': DIV // 2,
        '16th': DIV // 4, '32nd': DIV // 8, '64th': DIV // 16}
TYPE = {'Whole': 'whole', 'Half': 'half', '4th': 'quarter', '8th': 'eighth',
        '16th': '16th', '32nd': '32nd', '64th': '64th'}
# 음자리표: (sign, line, Pos 0(가운데 줄)에 놓이는 음 번호 = 옥타브*7 + 계이름 C=0..B=6)
CLEF = {'Treble': ('G', 2, 34), 'Bass': ('F', 4, 22), 'Alto': ('C', 3, 28),
        'Tenor': ('C', 4, 26), 'Percussion': ('percussion', 2, 34)}
STEPS = 'CDEFGAB'
ACC = {'#': 1, 'b': -1, 'n': 0, 'x': 2, 'v': -2}
ACC_NAME = {1: 'sharp', -1: 'flat', 0: 'natural', 2: 'double-sharp', -2: 'flat-flat'}
SHARPS, FLATS = 'FCGDAEB', 'BEADGCF'
ARTIC = {'Staccato': 'staccato', 'Staccatissimo': 'staccatissimo', 'Tenuto': 'tenuto',
         'Accent': 'accent', 'Marcato': 'strong-accent'}
NOTEHEAD = {'x': 'x', 'z': 'diamond'}
DYNAMICS = {'ppp', 'pp', 'p', 'mp', 'mf', 'f', 'ff', 'fff'}
TEMPO_BASE = {'Eighth': ('eighth', 0, 0.5), 'Eighth Dotted': ('eighth', 1, 0.75),
              'Quarter': ('quarter', 0, 1), 'Quarter Dotted': ('quarter', 1, 1.5),
              'Half': ('half', 0, 2), 'Half Dotted': ('half', 1, 3)}
TEMPO_WORDS = {'Accelerando': 'accel.', 'Allargando': 'allarg.', 'Rallentando': 'rall.',
               'Ritardando': 'rit.', 'Ritenuto': 'riten.', 'Rubato': 'rubato', 'Stringendo': 'string.'}
DYN_VAR = {'Crescendo': 'cresc.', 'Decrescendo': 'decresc.', 'Diminuendo': 'dim.',
           'Rinforzando': 'rfz', 'Sforzando': 'sfz'}
FLOW = {  # Style: (기호 요소, 글자, <sound> 속성)
    'Coda': ('coda', None, {'coda': 'coda'}), 'Segno': ('segno', None, {'segno': 'segno'}),
    'ToCoda': (None, 'To Coda', {'tocoda': 'coda'}), 'Fine': (None, 'Fine', {'fine': 'yes'}),
    'DCalFine': (None, 'D.C. al Fine', {'dacapo': 'yes'}), 'DCalCoda': (None, 'D.C. al Coda', {'dacapo': 'yes'}),
    'DSalFine': (None, 'D.S. al Fine', {'dalsegno': 'segno'}), 'DSalCoda': (None, 'D.S. al Coda', {'dalsegno': 'segno'})}
BAR_RIGHT = {'Double': 'light-light', 'SectionClose': 'light-heavy', 'MasterRepeatClose': 'light-heavy',
             'LocalRepeatClose': 'light-heavy', 'BrokenSingle': 'dashed', 'BrokenDouble': 'dashed'}
BAR_LEFT = {'SectionOpen': 'heavy-light', 'MasterRepeatOpen': 'heavy-light', 'LocalRepeatOpen': 'heavy-light'}
ENDING_BAR = {'Section Close': 'light-heavy', 'Master Repeat Close': 'light-heavy',
              'Double Bar': 'light-light', 'Open (hidden)': 'none'}
ATTR_ORDER = ['divisions', 'key', 'time', 'clef', 'transpose']
DIATONIC = [0, 0, 1, 2, 2, 3, 3, 4, 5, 5, 6, 6]  # 반음 수 → 온음계 간격
POS_RE = re.compile(r'([#bnxv]?)(-?\d+)([a-zA-Z]?)(\^?)')


# ---------------------------------------------------------------- 디코더: 파일 → NWCTXT
def read_nwctxt(path):
    """.nwc(2.75) 또는 .nwctxt 파일 → NWCTXT 문자열"""
    data = Path(path).read_bytes()
    if data.startswith(b'[NWZ]'):
        data = zlib.decompress(data[6:])
    start = data.find(b'!NoteWorthyComposer(')
    if start < 0:
        raise ValueError('NWCTXT 본문이 없습니다. 2.75 이전 바이너리 형식이면 '
                         'NoteWorthy Composer에서 .nwctxt로 저장한 뒤 변환하세요.')
    end = data.find(b'!NoteWorthyComposer-End', start)
    data = data[start:end if end > 0 else None]
    # 줄마다 따로 해독: 본문은 UTF-8이지만 "Più mosso" 같은 내장 문자열은 Latin-1 바이트로 섞여 있고,
    # 구형 저장본은 시스템 코드페이지(한국어 Windows: CP949)다.
    lines = []
    for raw in data.split(b'\n'):
        for enc in ('utf-8', 'cp949', 'latin-1'):
            try:
                lines.append(raw.decode(enc))
                break
            except UnicodeDecodeError:
                continue
    return '\n'.join(lines)


# ---------------------------------------------------------------- NWCTXT 파서
def split_fields(line):
    """'|태그|키:값|...' 한 줄을 필드로 나눈다. 따옴표 안의 '|'는 나누지 않는다."""
    fields, cur, quoted, esc = [], [], False, False
    for ch in line[1:]:
        if esc:
            cur.append(ch)
            esc = False
        elif ch == '\\':
            cur.append(ch)
            esc = True
        elif ch == '"':
            cur.append(ch)
            quoted = not quoted
        elif ch == '|' and not quoted:
            fields.append(''.join(cur))
            cur = []
        else:
            cur.append(ch)
    fields.append(''.join(cur))
    return fields


def unquote(v):
    """따옴표를 벗기고 \\n 같은 이스케이프를 푼다"""
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        v = v[1:-1]
    return re.sub(r'\\(.)', lambda m: {'n': '\n', 'r': '\r', 't': '\t'}.get(m[1], m[1]), v)


def parse(text):
    """NWCTXT → (곡 정보, 보표 목록). 보표: name/label/abbr/props/instr/lyric_opts/lyrics/items"""
    info, staves = {}, []
    for line in text.splitlines():
        if not line.startswith('|'):
            continue
        tag, *rest = split_fields(line)
        attrs = dict(f.partition(':')[::2] for f in rest)
        if tag == 'SongInfo':
            info = {k: unquote(v) for k, v in attrs.items()}
        elif tag == 'AddStaff':
            staves.append({'name': unquote(attrs.get('Name', '')), 'label': unquote(attrs.get('Label', '')),
                           'abbr': unquote(attrs.get('LabelAbbr', '')), 'props': {}, 'instr': {},
                           'lyric_opts': {}, 'lyrics': [], 'items': []})
        elif not staves:
            continue
        elif tag == 'StaffProperties':
            staves[-1]['props'].update(attrs)
        elif tag == 'StaffInstrument':
            staves[-1]['instr'].update(attrs)
        elif tag == 'Lyrics':
            staves[-1]['lyric_opts'] = attrs
        elif re.fullmatch(r'Lyric\d+', tag):
            staves[-1]['lyrics'].append(unquote(attrs.get('Text', '')))
        else:
            staves[-1]['items'].append((tag, attrs))
    return info, staves


def parse_dur(s):
    """'8th,Dotted,Triplet=First,Slur' → 길이 정보"""
    base, *mods = s.split(',')
    ticks = BASE[base]
    dots = 2 if 'DblDotted' in mods else 1 if 'Dotted' in mods else 0
    ticks = ticks * (1, 3, 7)[dots] // (1, 2, 4)[dots]
    trip = next((m for m in mods if m.startswith('Triplet')), None)
    if trip:
        ticks = ticks * 2 // 3
    return {'ticks': ticks, 'type': TYPE[base], 'dots': dots, 'grace': 'Grace' in mods, 'slur': 'Slur' in mods,
            'triplet': {'Triplet=First': 'start', 'Triplet=End': 'stop', 'Triplet': 'middle'}.get(trip),
            'artic': [ARTIC[m] for m in mods if m in ARTIC]}


def parse_opts(s):
    return dict(o.partition('=')[::2] for o in s.split(',') if o)


def parse_pos(s):
    """'#-2^,1' → [(임시표, 위치, 머리 모양, 붙임줄 시작)]"""
    out = []
    for p in s.split(','):
        m = POS_RE.fullmatch(p.strip())
        if m:
            out.append((m[1], int(m[2]), m[3], bool(m[4])))
    return out


def syllabify(text, underscore_as_space=True):
    """NWC 가사 → [(글자, syllabic, 앞 음절 연장?)]. 글자가 ''이면 음표만 차지하고 표시는 없음."""
    toks = []
    for tok in text.split():
        toks += [p for p in re.split(r'(?<=-)(?=[^-])', tok) if p]
    out = []
    for i, tok in enumerate(toks):
        if set(tok) <= set('-_'):  # '-' 는 하이픈 자리, '_' 는 멜리스마 연장선
            out.append(('', None, '_' in tok))
            continue
        prev = toks[i - 1] if i else ''
        nxt = toks[i + 1] if i + 1 < len(toks) else ''
        join_prev = tok.startswith('-') or prev.endswith('-') or set(prev) == {'-'}
        join_next = tok.endswith('-') or nxt.startswith('-') or set(nxt) == {'-'}
        syl = {(False, False): 'single', (False, True): 'begin',
               (True, False): 'end', (True, True): 'middle'}[join_prev, join_next]
        t = tok.strip('-')
        out.append((t.replace('_', ' ') if underscore_as_space else t, syl, False))
    return out


# ---------------------------------------------------------------- 인코더: 보표 → <part>
class PartWriter:
    """보표 하나를 <part>로. NWC 항목을 순서대로 읽으며 마디를 만들어 간다."""

    def __init__(self, staff, pid):
        self.staff = staff
        self.part = ET.Element('part', id=pid)
        self.measure = None       # 현재 <measure>
        self.num = 0              # 마디 번호
        self.attrs = None         # 현재 위치에 열린 <attributes>
        self.first_attrs = None
        self.v1 = 0               # 1성부 시간 커서(틱, 마디 안)
        self.abs = 0              # 1성부 시간 커서(틱, 보표 처음부터) — 붙임줄 짝 찾기용
        self.v2 = []              # 2성부: (시작 틱, 길이, [note])
        self.has_notes = False
        self.left = None          # 다음 마디 왼쪽 세로줄: (bar-style, 반복 시작?)
        self.new_system = False
        self.ending = None        # 열린 1·2번 괄호 번호
        self.time_ticks = None
        self.time_in_first = False
        self.m1_ticks = None
        self.key = {}             # 조표: 계이름 → 변화
        self.clef = CLEF['Treble']
        self.key_written = self.clef_written = False
        self.acc = {}             # 마디 안 임시표: (계이름, 옥타브) → 변화
        self.ties = {}            # 열린 붙임줄: (계이름, 옥타브) → (변화, 끝나는 틱)
        self.prev_tied = False    # 직전 항목의 모든 음이 붙임줄로 이어짐
        self.prev_slur = False    # 직전 항목에 이음줄 표시
        self.slur_open = False
        self.hairpin = None
        self.pending = []         # 다음 음표에 붙일 notations: [('fermata', None), ...]
        self.m_items = []         # 이 마디의 음표 항목 (혼자 있는 온쉼표 판정용)
        self.m1_whole = None      # 첫 마디가 온쉼표 하나뿐이면 그 요소
        uas = staff['lyric_opts'].get('UnderscoreAsSpace', 'Y') != 'N'
        self.lyrics = [syllabify(t, uas) for t in staff['lyrics']]
        self.lyr_i = [0] * len(self.lyrics)
        self.lyr_last = [None] * len(self.lyrics)

    def run(self):
        for tag, a in self.staff['items']:
            if tag in ('Note', 'Chord', 'Rest', 'RestChord'):
                self.note_item(tag, a)
            elif tag == 'Bar':
                self.bar(a)
            elif tag == 'Clef':
                self.clef_item(a)
            elif tag == 'Key':
                self.key_item(a)
            elif tag == 'TimeSig':
                self.time_item(a)
            elif tag == 'Tempo':
                self.tempo(a)
            elif tag == 'Dynamic':
                self.dynamic(a)
            elif tag == 'DynamicVariance':
                self.words(DYN_VAR.get(a.get('Style'), a.get('Style', '')), a, italic=True)
            elif tag == 'TempoVariance':
                self.tempo_variance(a)
            elif tag == 'PerformanceStyle':
                self.words(a.get('Style', ''), a, italic=True)
            elif tag == 'Text':
                self.words(unquote(a.get('Text', '')), a, italic=a.get('Font') == 'StaffItalic',
                           bold=a.get('Font') == 'StaffBold')
            elif tag == 'Flow':
                self.flow(a)
            elif tag == 'Ending':
                self.ending_item(a)
            elif tag == 'SustainPedal':
                self.pedal(a)
            # Spacer, Boundary, MPC, User 등은 악보 내용이 아니라 무시
        if self.hairpin and self.measure is not None:
            self.wedge('stop')
        self.close_measure()
        if not len(self.part):  # 빈 보표도 마디 하나는 있어야 한다
            self.ensure_measure()
            self.close_measure()
        return self.part

    def finish(self, nmeasures):
        """짧게 끝난 보표는 온마디 쉼표로 채우고 마지막 세로줄을 붙인다"""
        while len(self.part) < nmeasures:
            self.ensure_measure()
            n = ET.SubElement(self.measure, 'note')
            ET.SubElement(n, 'rest', measure='yes')
            ET.SubElement(n, 'duration').text = str(self.time_ticks or 4 * DIV)
            ET.SubElement(n, 'voice').text = '1'
            self.close_measure()
        eb = self.staff['props'].get('EndingBar', 'Section Close')
        style, repeat = ENDING_BAR.get(eb), eb == 'Master Repeat Close'
        last = self.part[-1]
        if last.find("barline[@location='right']") is None and (style or repeat):
            bl = ET.SubElement(last, 'barline', location='right')
            if style:
                ET.SubElement(bl, 'bar-style').text = style
            if repeat:
                ET.SubElement(bl, 'repeat', direction='backward')

    # ---- 마디 ----
    def ensure_measure(self):
        if self.measure is None:
            self.num += 1
            self.measure = ET.SubElement(self.part, 'measure', number=str(self.num))
            if self.new_system:
                ET.SubElement(self.measure, 'print', {'new-system': 'yes'})
                self.new_system = False
            self.v1, self.v2, self.has_notes, self.acc, self.attrs, self.m_items = 0, [], False, {}, None, []
            self.left_barline()
            if self.num == 1:
                self.attributes()
        return self.measure

    def left_barline(self):
        """self.left / self.ending 를 현재 마디 머리의 왼쪽 세로줄로 넣는다"""
        if not self.left and not self.ending:
            return
        bl = ET.Element('barline', location='left')
        if self.left:
            ET.SubElement(bl, 'bar-style').text = self.left[0]
        if self.ending:
            ET.SubElement(bl, 'ending', number=self.ending, type='start')
        if self.left and self.left[1]:
            ET.SubElement(bl, 'repeat', direction='forward')
        self.measure.insert(1 if len(self.measure) and self.measure[0].tag == 'print' else 0, bl)
        self.left = None

    def close_measure(self, right=None, repeat=False, times=None):
        if self.measure is None:
            return
        lone_whole = self.m_items[0] if len(self.m_items) == 1 else None
        if lone_whole is not None:  # NWC: 혼자 있는 온쉼표는 마디 전체 쉼표
            if self.time_ticks:
                self.measure_rest(lone_whole, self.time_ticks)
                self.abs += self.time_ticks - self.v1
                self.v1 = self.time_ticks
            elif self.num == 1:
                self.m1_whole = lone_whole
        self.flush_v2()
        if right or self.ending or repeat:
            bl = ET.SubElement(self.measure, 'barline', location='right')
            if right:
                ET.SubElement(bl, 'bar-style').text = right
            if self.ending:
                ET.SubElement(bl, 'ending', number=self.ending, type='stop' if repeat else 'discontinue')
                self.ending = None
            if repeat:
                r = ET.SubElement(bl, 'repeat', direction='backward')
                if times:
                    r.set('times', times)
        if self.num == 1:
            self.m1_ticks = self.v1
            if self.time_ticks and self.v1 < self.time_ticks:
                self.measure.set('implicit', 'yes')  # 못갖춘마디
        self.measure, self.has_notes = None, False

    @staticmethod
    def measure_rest(note, ticks):
        note.find('rest').set('measure', 'yes')
        note.find('duration').text = str(ticks)
        note.remove(note.find('type'))

    def flush_v2(self):
        """2성부(긴 쪽 음) 를 <backup> 뒤에 쓴다"""
        if not self.v2:
            return
        if self.v1:
            ET.SubElement(ET.SubElement(self.measure, 'backup'), 'duration').text = str(self.v1)
        cur = 0
        for onset, ticks, notes in self.v2:
            if onset != cur:
                kind = 'forward' if onset > cur else 'backup'
                ET.SubElement(ET.SubElement(self.measure, kind), 'duration').text = str(abs(onset - cur))
            self.measure.extend(notes)
            cur = onset + ticks
        self.v2 = []

    def bar(self, a):
        style = a.get('Style', 'Single')
        hidden = a.get('Visibility') == 'Never' or style == 'Transparent'
        right = 'none' if hidden else BAR_RIGHT.get(style)
        if not self.has_notes:
            # 아직 음표가 없는 마디 머리의 세로줄은 이 마디의 왼쪽 세로줄로 쓴다
            left = None if hidden else BAR_LEFT.get(style) or right
            if left:
                self.left = (left, style.endswith('RepeatOpen'))
                if self.measure is not None:
                    self.left_barline()
            return
        self.close_measure(right, style.endswith('RepeatClose'), a.get('Repeat'))
        if BAR_LEFT.get(style):
            self.left = (BAR_LEFT[style], style.endswith('RepeatOpen'))
        self.new_system = a.get('SysBreak') == 'Y'

    def ending_item(self, a):
        num = a.get('Endings')
        if not num:
            return
        self.ending = num
        if self.measure is None:
            return  # ensure_measure 가 왼쪽 세로줄에 넣는다
        bl = self.measure.find("barline[@location='left']")
        if bl is None:
            self.left_barline()
        else:
            tags = [c.tag for c in bl]
            bl.insert(tags.index('repeat') if 'repeat' in tags else len(tags),
                      ET.Element('ending', number=num, type='start'))

    # ---- 속성(조표·박자표·음자리표) ----
    def attributes(self):
        """현재 위치의 <attributes>. 음표가 나온 뒤면 새로 만든다."""
        self.ensure_measure()
        if self.attrs is None:
            self.attrs = ET.SubElement(self.measure, 'attributes')
            if self.first_attrs is None:
                self.first_attrs = self.attrs
                ET.SubElement(self.attrs, 'divisions').text = str(DIV)
                trans = int(self.staff['instr'].get('Trans') or 0)
                if trans:
                    t = ET.SubElement(self.attrs, 'transpose')
                    ET.SubElement(t, 'diatonic').text = str(7 * (trans // 12) + DIATONIC[trans % 12])
                    ET.SubElement(t, 'chromatic').text = str(trans)
        return self.attrs

    @staticmethod
    def sort_attrs(at):
        at[:] = sorted(at, key=lambda e: ATTR_ORDER.index(e.tag))

    def clef_item(self, a):
        sign, line, base = CLEF.get(a.get('Type'), CLEF['Treble'])
        shift = {'Octave Up': 1, 'Octave Down': -1}.get(a.get('OctaveShift'), 0)
        clef = (sign, line, base + 7 * shift)
        if clef == self.clef and self.clef_written:  # NWC 는 같은 음자리표를 단락마다 다시 적는다
            return
        self.clef, self.clef_written = clef, True
        c = ET.SubElement(self.attributes(), 'clef')
        ET.SubElement(c, 'sign').text = sign
        ET.SubElement(c, 'line').text = str(line)
        if shift:
            ET.SubElement(c, 'clef-octave-change').text = str(shift)
        self.sort_attrs(self.attrs)

    def key_item(self, a):
        sig = [s for s in a.get('Signature', '').split(',') if len(s) == 2]
        key = {s[0]: ACC[s[1]] for s in sig}
        if key == self.key and self.key_written:
            return
        self.key, self.key_written = key, True
        k = ET.SubElement(self.attributes(), 'key')
        letters = ''.join(s[0] for s in sig)
        alters = set(self.key.values())
        if letters == SHARPS[:len(sig)] and alters <= {1}:
            ET.SubElement(k, 'fifths').text = str(len(sig))
        elif letters == FLATS[:len(sig)] and alters <= {-1}:
            ET.SubElement(k, 'fifths').text = str(-len(sig))
        else:  # 비표준 조표
            for step, alt in self.key.items():
                ET.SubElement(k, 'key-step').text = step
                ET.SubElement(k, 'key-alter').text = str(alt)
        self.sort_attrs(self.attrs)

    def time_item(self, a):
        sig = a.get('Signature', '4/4')
        symbol = {'Common': 'common', 'AllaBreve': 'cut'}.get(sig)
        beats, beat_type = {'Common': '4/4', 'AllaBreve': '2/2'}.get(sig, sig).split('/')
        self.time_ticks = int(beats) * 4 * DIV // int(beat_type)
        # 못갖춘마디: 첫 마디에 박자표가 없고 둘째 마디 머리에 나오면 첫 마디로 옮긴다
        hoist = (not self.time_in_first and self.first_attrs is not None
                 and ((self.num == 1 and self.measure is None) or (self.num == 2 and not self.has_notes))
                 and self.m1_ticks is not None
                 and (self.m1_ticks <= self.time_ticks or self.m1_whole is not None))
        at = self.first_attrs if hoist else self.attributes()
        t = ET.SubElement(at, 'time', {'symbol': symbol} if symbol else {})
        ET.SubElement(t, 'beats').text = beats
        ET.SubElement(t, 'beat-type').text = beat_type
        self.sort_attrs(at)
        if hoist:
            if self.m1_whole is not None:  # 첫 마디가 온쉼표 하나면 못갖춘마디가 아니라 온마디 쉼표
                self.measure_rest(self.m1_whole, self.time_ticks)
                self.abs += self.time_ticks - self.m1_ticks
                self.m1_ticks = self.time_ticks
            elif self.m1_ticks < self.time_ticks:
                self.part[0].set('implicit', 'yes')
        if hoist or self.num == 1:
            self.time_in_first = True

    # ---- 지시어 ----
    def direction(self, kind, a=None, placement=None, sound=None, text=None, attrib=None):
        """<direction> 하나를 현재 위치에 추가하고 안쪽 요소(words, dynamics, ...)를 돌려준다"""
        self.ensure_measure()
        d = ET.SubElement(self.measure, 'direction')
        pos = (a or {}).get('Pos')
        if placement is None and pos is not None:
            try:
                placement = 'above' if float(pos) >= 0 else 'below'
            except ValueError:
                pass
        if placement:
            d.set('placement', placement)
        inner = ET.SubElement(ET.SubElement(d, 'direction-type'), kind, attrib or {})
        if text is not None:
            inner.text = text
        if sound:
            ET.SubElement(d, 'sound', sound)
        return inner

    def words(self, text, a, italic=False, bold=False):
        if not text or a.get('Visibility') == 'Never':
            return
        attrib = {}
        if italic:
            attrib['font-style'] = 'italic'
        if bold:
            attrib['font-weight'] = 'bold'
        self.direction('words', a, text=text, attrib=attrib)

    def tempo(self, a):
        unit, dots, ql = TEMPO_BASE.get(a.get('Base', 'Quarter'), TEMPO_BASE['Quarter'])
        bpm = int(a.get('Tempo', 120))
        sound = {'tempo': f'{bpm * ql:g}'}
        if a.get('Visibility') == 'Never':  # 재생용 템포만
            ET.SubElement(self.ensure_measure(), 'sound', sound)
            return
        if a.get('Text'):
            self.words(unquote(a['Text']), a, bold=True)
        m = self.direction('metronome', a, 'above', sound)
        ET.SubElement(m, 'beat-unit').text = unit
        for _ in range(dots):
            ET.SubElement(m, 'beat-unit-dot')
        ET.SubElement(m, 'per-minute').text = str(bpm)

    def dynamic(self, a):
        style = a.get('Style', '')
        if a.get('Visibility') == 'Never' or style not in DYNAMICS:
            return
        ET.SubElement(self.direction('dynamics', a), style)

    def tempo_variance(self, a):
        style = a.get('Style', '')
        if a.get('Visibility') == 'Never':
            return
        if style == 'Fermata':
            self.pending.append(('fermata', None))
        elif style == 'Breath Mark':
            self.pending.append(('articulations', 'breath-mark'))
        elif style == 'Caesura':
            self.pending.append(('articulations', 'caesura'))
        else:
            self.words(TEMPO_WORDS.get(style, style.lower()), a, italic=True)

    def flow(self, a):
        if a.get('Visibility') == 'Never':
            return
        sym, text, sound = FLOW.get(a.get('Style'), (None, a.get('Style', ''), None))
        if sym:
            self.direction(sym, a, 'above', sound)
        else:
            self.direction('words', a, 'above', sound, text=text, attrib={'font-weight': 'bold'})

    def pedal(self, a):
        if a.get('Visibility') == 'Never':
            return
        self.direction('pedal', a, 'below', attrib={'type': 'stop' if a.get('Status') == 'Released' else 'start'})

    def wedge(self, kind):
        self.direction('wedge', None, 'below', attrib={'type': kind})

    def hairpin_item(self, opts):
        """음표 옵션 Crescendo/Diminuendo 가 이어지는 구간을 꺾쇠 하나로"""
        want = 'crescendo' if 'Crescendo' in opts else 'diminuendo' if 'Diminuendo' in opts else None
        if want != self.hairpin:
            if self.hairpin:
                self.wedge('stop')
            if want:
                self.wedge(want)
            self.hairpin = want

    # ---- 음표 ----
    def note_item(self, tag, a):
        opts = parse_opts(a.get('Opts', ''))
        hidden = a.get('Visibility') == 'Never'
        d1 = parse_dur(a['Dur'])
        g1 = (parse_pos(a.get('Pos', '')) if tag in ('Note', 'Chord') else None) or None  # None = 쉼표
        d2 = parse_dur(a['Dur2']) if 'Dur2' in a else None
        g2 = (parse_pos(a.get('Pos2', '')) or None) if d2 else None
        stem1 = opts.get('Stem')
        stem2 = {'Up': 'Down', 'Down': 'Up'}.get(stem1)
        if d2 and d2['ticks'] < d1['ticks']:  # 짧은 쪽이 1성부, 긴 쪽은 2성부로 지속
            d1, g1, d2, g2, stem1, stem2 = d2, g2, d1, g1, stem2, stem1
        mode = opts.get('Lyric')  # 가사 음절을 받는가 (NWC 기본 규칙)
        takes = (tag != 'Rest' and mode != 'Never'
                 and (mode == 'Always' or not (self.prev_tied or d1['grace'] or self.prev_slur)))
        slur = None  # 이음줄 시작/끝. 쉼표만 있는 항목은 상태를 바꾸지 않는다
        if tag != 'Rest':
            if d1['slur'] or (d2 and d2['slur']):
                if not self.slur_open:
                    slur, self.slur_open = 'start', True
            elif self.slur_open:
                slur, self.slur_open = 'stop', False
        self.ensure_measure()
        self.hairpin_item(opts)
        onset, at = self.v1, self.abs
        notes1 = self.notes(g1, d1, 1, stem1, hidden or (g1 is None and 'HideRest' in opts), self.pending, at)
        self.pending = []
        self.measure.extend(notes1)
        self.m_items.append(notes1[0] if g1 is None and not d2 and d1['type'] == 'whole'
                            and not (d1['dots'] or d1['triplet']) else None)
        self.has_notes, self.attrs = True, None
        if not d1['grace']:
            self.v1 += d1['ticks']
            self.abs += d1['ticks']
        notes2 = []
        if d2:
            notes2 = self.notes(g2, d2, 2, stem2, hidden, [], at)
            self.v2.append((onset, d2['ticks'], notes2))
        first = notes1[0] if g1 else notes2[0] if g2 else None  # 첫 번째 '음표'(쉼표 아님)
        if first is not None:
            if slur:
                self.add_notations(first, [('slur', {'type': slur, 'number': '1'})])
            if takes:
                self.attach_lyrics(first)
        poses = (g1 or []) + (g2 or [])
        self.prev_tied = bool(poses) and all(p[3] for p in poses)
        self.prev_slur = d1['slur'] or bool(d2 and d2['slur'])

    def notes(self, group, d, voice, stem, hidden, extra, onset):
        """음표/화음/쉼표 하나 → [<note>]. extra: 첫 음에 붙일 notations, onset: 시작 틱(보표 처음부터)
        ponytail: 빔(Opts Beam=First/End)은 안 쓴다. MuseScore 자동 빔으로 충분하고, 16분음표는 2차 빔 계산이 더 필요함"""
        out = []
        for i, p in enumerate(sorted(group, key=lambda p: p[1]) if group else [None]):
            n = ET.Element('note')
            if hidden:
                n.set('print-object', 'no')
            if d['grace']:
                ET.SubElement(n, 'grace', slash='yes')
            if i:
                ET.SubElement(n, 'chord')
            tie_stop = tie_start = False
            written = None
            if p is None:
                ET.SubElement(n, 'rest')
            else:
                acc, pos, head, tie_start = p
                step, octave, alter, written, tie_stop = self.pitch(acc, pos, tie_start, onset,
                                                                    0 if d['grace'] else d['ticks'])
                pe = ET.SubElement(n, 'pitch')
                ET.SubElement(pe, 'step').text = step
                if alter:
                    ET.SubElement(pe, 'alter').text = str(alter)
                ET.SubElement(pe, 'octave').text = str(octave)
            if not d['grace']:
                ET.SubElement(n, 'duration').text = str(d['ticks'])
            if tie_stop:
                ET.SubElement(n, 'tie', type='stop')
            if tie_start:
                ET.SubElement(n, 'tie', type='start')
            ET.SubElement(n, 'voice').text = str(voice)
            ET.SubElement(n, 'type').text = d['type']
            for _ in range(d['dots']):
                ET.SubElement(n, 'dot')
            if written:
                ET.SubElement(n, 'accidental').text = written
            if d['triplet']:
                tm = ET.SubElement(n, 'time-modification')
                ET.SubElement(tm, 'actual-notes').text = '3'
                ET.SubElement(tm, 'normal-notes').text = '2'
            if stem and p is not None:
                ET.SubElement(n, 'stem').text = stem.lower()
            if p is not None and head in NOTEHEAD:
                ET.SubElement(n, 'notehead').text = NOTEHEAD[head]
            nots = [('tied', {'type': t}) for t, on in (('stop', tie_stop), ('start', tie_start)) if on]
            if i == 0:
                if d['triplet'] in ('start', 'stop'):
                    nots.append(('tuplet', {'type': d['triplet']}))
                nots += extra
                nots += [('articulations', art) for art in d['artic']]
            if nots:
                self.add_notations(n, nots)
            out.append(n)
        return out

    def pitch(self, acc, pos, tie, onset, ticks):
        """Pos → (계이름, 옥타브, 변화, 적을 임시표, 붙임줄 끝?). 마디 안 임시표와 붙임줄을 따른다.
        붙임줄은 앞 음이 끝나는 바로 그 시점에 시작하는 같은 음에만 이어진다(NWC 규칙). 짝이 없으면 버린다."""
        d = self.clef[2] + pos
        step, octave = STEPS[d % 7], d // 7
        key = (step, octave)
        pend = self.ties.get(key)
        tie_stop = pend is not None and pend[1] == onset
        if pend is not None and pend[1] <= onset:
            del self.ties[key]
        if acc:
            alter = ACC[acc]
            self.acc[key] = alter
        elif tie_stop:
            alter = pend[0]
        else:
            alter = self.acc.get(key, self.key.get(step, 0))
        if tie:
            self.ties[key] = (alter, onset + ticks)
        return step, octave, alter, ACC_NAME[ACC[acc]] if acc else None, tie_stop

    @staticmethod
    def add_notations(n, items):
        nots = n.find('notations')
        if nots is None:
            nots = ET.SubElement(n, 'notations')
        arts = None
        for kind, val in items:
            if kind == 'articulations':
                if arts is None:
                    arts = ET.SubElement(nots, 'articulations')
                ET.SubElement(arts, val)
            else:
                ET.SubElement(nots, kind, val or {})

    def attach_lyrics(self, note):
        for li, syls in enumerate(self.lyrics):
            i = self.lyr_i[li]
            if i >= len(syls):
                continue
            self.lyr_i[li] = i + 1
            text, syl, extend = syls[i]
            if not text:
                last = self.lyr_last[li]
                if extend and last is not None and last.find('extend') is None:
                    ET.SubElement(last, 'extend')
                continue
            ly = ET.SubElement(note, 'lyric', number=str(li + 1))
            ET.SubElement(ly, 'syllabic').text = syl
            ET.SubElement(ly, 'text').text = text
            self.lyr_last[li] = ly


# ---------------------------------------------------------------- 악보 전체
def to_musicxml(text):
    """NWCTXT 문자열 → MusicXML 문자열"""
    info, staves = parse(text)
    root = ET.Element('score-partwise', version='4.0')
    if info.get('Title'):
        ET.SubElement(ET.SubElement(root, 'work'), 'work-title').text = info['Title']
    ident = ET.SubElement(root, 'identification')
    for key, typ in (('Author', 'composer'), ('Lyricist', 'lyricist')):
        if info.get(key) and '<' not in info[key]:  # "<Name>" 은 NWC 의 빈칸 표시
            ET.SubElement(ident, 'creator', type=typ).text = info[key]
    rights = [info[k] for k in ('Copyright1', 'Copyright2') if info.get(k) and '<' not in info[k]]
    if rights:
        ET.SubElement(ident, 'rights').text = ' '.join(rights)
    enc = ET.SubElement(ident, 'encoding')
    ET.SubElement(enc, 'software').text = 'nwc2musicxml'
    ET.SubElement(enc, 'encoding-date').text = datetime.date.today().isoformat()
    plist = ET.SubElement(root, 'part-list')
    # 보표 묶음: WithNextStaff 에 Bracket/Brace/ConnectBars 가 이어지는 구간마다 part-group 하나
    # ponytail: Layer(보표 겹치기)는 무시하고 별도 보표로 둔다. 겹쳐 그리려면 두 보표를 한 part 의 성부로 합쳐야 함
    starts, stops = {}, {}
    for num, (kind, symbol) in enumerate((('Bracket', 'bracket'), ('Brace', 'brace'), ('ConnectBars', 'none')), 1):
        first = None
        for i, st in enumerate(staves + [None]):
            wns = st['props'].get('WithNextStaff', '') if st is not None else ''
            has = kind in wns and (kind != 'ConnectBars' or not ('Bracket' in wns or 'Brace' in wns))
            if has and first is None:
                first = i
            elif not has and first is not None:
                starts.setdefault(first, []).append((str(num), symbol, kind == 'ConnectBars' or any(
                    'ConnectBars' in s['props'].get('WithNextStaff', '') for s in staves[first:i])))
                stops.setdefault(min(i, len(staves) - 1), []).append(str(num))
                first = None
    writers = []
    for i, st in enumerate(staves):
        pid = f'P{i + 1}'
        for num, symbol, connect in starts.get(i, []):
            pg = ET.SubElement(plist, 'part-group', type='start', number=num)
            ET.SubElement(pg, 'group-symbol').text = symbol
            if connect:
                ET.SubElement(pg, 'group-barline').text = 'yes'
        sp = ET.SubElement(plist, 'score-part', id=pid)
        name = st['label'] or st['name']
        ET.SubElement(sp, 'part-name').text = name
        if st['abbr']:
            ET.SubElement(sp, 'part-abbreviation').text = st['abbr']
        si = ET.SubElement(sp, 'score-instrument', id=pid + '-I1')
        ET.SubElement(si, 'instrument-name').text = unquote(st['instr'].get('Name', '')) or name
        mi = ET.SubElement(sp, 'midi-instrument', id=pid + '-I1')
        ET.SubElement(mi, 'midi-channel').text = st['props'].get('Channel', '1')
        ET.SubElement(mi, 'midi-program').text = str(int(st['instr'].get('Patch') or 0) + 1)
        ET.SubElement(mi, 'volume').text = f"{int(st['props'].get('Volume') or 127) * 100 / 127:.1f}"
        for num in stops.get(i, []):
            ET.SubElement(plist, 'part-group', type='stop', number=num)
        writers.append(PartWriter(st, pid))
    parts = [w.run() for w in writers]
    for w in writers:
        w.finish(max(len(p) for p in parts))
    root.extend(parts)
    ET.indent(root)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
            '"http://www.musicxml.org/dtds/partwise.dtd">\n' + ET.tostring(root, encoding='unicode') + '\n')


def convert_file(src, outdir=None, dump_nwctxt=False):
    src = Path(src)
    text = read_nwctxt(src)
    dst_dir = Path(outdir) if outdir else src.parent
    if dump_nwctxt and src.suffix.lower() != '.nwctxt':
        (dst_dir / (src.stem + '.nwctxt')).write_text(text, encoding='utf-8')
    dst = dst_dir / (src.stem + '.musicxml')
    dst.write_text(to_musicxml(text), encoding='utf-8')
    return dst


def main(argv=None):
    ap = argparse.ArgumentParser(description='NoteWorthy Composer(.nwc/.nwctxt) → MusicXML')
    ap.add_argument('inputs', nargs='+', help='.nwc/.nwctxt 파일 또는 폴더(하위 폴더까지)')
    ap.add_argument('-o', '--outdir', help='출력 폴더 (기본: 원본 옆)')
    ap.add_argument('--nwctxt', action='store_true', help='풀어낸 NWCTXT 텍스트도 같이 저장')
    args = ap.parse_args(argv)
    files = []
    for inp in map(Path, args.inputs):
        if inp.is_dir():
            files += sorted(p for p in inp.rglob('*') if p.suffix.lower() in ('.nwc', '.nwctxt'))
        else:
            files.append(inp)
    if args.outdir:
        Path(args.outdir).mkdir(parents=True, exist_ok=True)
    failed = 0
    for f in files:
        try:
            print('OK  ', f, '->', convert_file(f, args.outdir, args.nwctxt))
        except Exception as e:  # 한 파일이 실패해도 나머지는 계속
            failed += 1
            print('실패', f, ':', e, file=sys.stderr)
    print(f'{len(files) - failed}/{len(files)} 변환')
    return 1 if failed else 0


if __name__ == '__main__':
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(errors='replace')
    sys.exit(main())
