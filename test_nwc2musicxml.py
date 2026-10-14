"""nwc2musicxml 자체 점검:  python test_nwc2musicxml.py"""
import zlib
import xml.etree.ElementTree as ET
from pathlib import Path

import nwc2musicxml as n

SAMPLE = '''!NoteWorthyComposer(2.75)
|SongInfo|Title:"테스트"|Author:"<Name>"|Lyricist:"김작사"
|AddStaff|Name:"Sop"|Label:"Soprano"
|StaffProperties|EndingBar:Section Close|WithNextStaff:Brace,ConnectBars
|StaffProperties|Channel:1
|StaffInstrument|Patch:52
|Lyrics|Placement:Bottom
|Lyric1|Text:"노 래 ha-ppy day la _ 남은글자"
|Clef|Type:Treble
|Key|Signature:Bb,Eb|Tonic:B
|Tempo|Tempo:90|Pos:8
|Note|Dur:4th|Pos:-4
|Bar
|TimeSig|Signature:4/4
|Dynamic|Style:mf|Pos:8
|Note|Dur:4th|Pos:-2^
|Note|Dur:4th|Pos:-2
|Note|Dur:8th,Triplet=First,Slur|Pos:0
|Note|Dur:8th,Triplet,Slur|Pos:1
|Note|Dur:8th,Triplet=End|Pos:2
|Chord|Dur:8th|Pos:#1|Opts:Stem=Up|Dur2:4th|Pos2:-5
|Note|Dur:8th|Pos:1
|Bar|Style:Double
|Note|Dur:Half|Pos:3
|Note|Dur:Half|Pos:3
|Bar
|Rest|Dur:Whole
|AddStaff|Name:"Bass"
|Clef|Type:Bass
|Rest|Dur:4th
|Bar
|Rest|Dur:Whole
|Bar
|Rest|Dur:Whole
|Bar
|Note|Dur:Whole|Pos:0
|AddStaff|Name:"Tenor"
|Clef|Type:Treble|OctaveShift:Octave Down
|Key|Signature:Bb,Eb|Tonic:B
|Note|Dur:4th|Pos:0
|Bar|Style:Double
|Clef|Type:Treble|OctaveShift:Octave Down
|Key|Signature:Bb,Eb|Tonic:B
|Note|Dur:4th|Pos:3^
|Rest|Dur:4th
|Note|Dur:Half|Pos:3
!NoteWorthyComposer-End
'''


def pitch_of(note):
    p = note.find('pitch')
    return p.findtext('step') + (p.findtext('alter') or '') + p.findtext('octave')


def test():
    root = ET.fromstring(n.to_musicxml(SAMPLE))
    assert root.findtext('work/work-title') == '테스트'
    assert [c.text for c in root.findall('identification/creator')] == ['김작사']  # "<Name>" 은 빈칸
    plist = root.find('part-list')
    assert [e.tag for e in plist] == ['part-group', 'score-part', 'score-part', 'part-group', 'score-part']
    assert plist.findtext('part-group/group-symbol') == 'brace'
    assert plist.findtext('score-part/part-name') == 'Soprano'
    assert plist.findtext('score-part/midi-instrument/midi-program') == '53'
    sop, bass, tenor = root.findall('part')
    m = sop.findall('measure')
    assert len(m) == 4 and len(bass.findall('measure')) == 4
    # 못갖춘마디: 둘째 마디의 4/4 가 첫 마디로 올라가고 implicit
    assert m[0].get('implicit') == 'yes'
    assert m[0].findtext('attributes/time/beats') == '4' and m[1].find('attributes/time') is None
    assert [e.tag for e in m[0].find('attributes')] == ['divisions', 'key', 'time', 'clef']
    assert m[0].findtext('attributes/key/fifths') == '-2'
    assert m[0].findtext('attributes/clef/sign') == 'G'
    assert m[0].findtext('direction/direction-type/metronome/per-minute') == '90'
    n1 = m[0].findall('note')
    assert pitch_of(n1[0]) == 'E-14' and n1[0].findtext('lyric/text') == '노'
    # 둘째 마디: 셈여림, 붙임줄, 셋잇단, 이음줄, 임시표, 두 길이 화음(2성부)
    assert m[1].find('direction/direction-type/dynamics/mf') is not None
    v1 = [x for x in m[1].findall('note') if x.findtext('voice') == '1']
    assert [pitch_of(x) for x in v1] == ['G4', 'G4', 'B-14', 'C5', 'D5', 'C15', 'C15'], [pitch_of(x) for x in v1]
    assert [x.findtext('duration') for x in v1] == ['192', '192', '64', '64', '64', '96', '96']
    assert [x.findtext('lyric/text') for x in v1] == ['래', None, 'ha', None, None, 'ppy', 'day']
    assert v1[2].findtext('lyric/syllabic') == 'begin' and v1[5].findtext('lyric/syllabic') == 'end'
    assert v1[0].find("tie[@type='start']") is not None and v1[1].find("tie[@type='stop']") is not None
    assert v1[2].find("notations/tuplet[@type='start']") is not None
    assert v1[4].find("notations/tuplet[@type='stop']") is not None
    assert v1[2].findtext('time-modification/actual-notes') == '3'
    assert v1[2].find("notations/slur[@type='start']") is not None
    assert v1[4].find("notations/slur[@type='stop']") is not None
    assert v1[5].findtext('accidental') == 'sharp' and v1[6].find('accidental') is None  # 마디 안 임시표 유지
    assert v1[5].findtext('stem') == 'up'
    v2 = [x for x in m[1].findall('note') if x.findtext('voice') == '2']
    assert [pitch_of(x) for x in v2] == ['D4'] and v2[0].findtext('duration') == '192'
    assert v2[0].findtext('stem') == 'down'
    assert m[1].findtext('backup/duration') == '768' and m[1].findtext('forward/duration') == '576'
    assert m[1].findtext("barline[@location='right']/bar-style") == 'light-light'
    # 셋째 마디: 멜리스마 연장선. 넷째: 온쉼표와 마지막 세로줄
    n3 = m[2].findall('note')
    assert n3[0].findtext('lyric/text') == 'la' and n3[0].find('lyric/extend') is not None
    assert n3[1].find('lyric') is None
    assert m[3].find('note/rest').get('measure') == 'yes' and m[3].findtext('note/duration') == '768'
    assert m[3].findtext("barline[@location='right']/bar-style") == 'light-heavy'
    # 낮은음자리표: Pos 0 = D3
    assert pitch_of(bass.findall('measure')[3].find('note')) == 'D3'
    # 옥타브 아래 높은음자리표: Pos 0 = B3(조표 Bb). 같은 음자리표·조표를 다시 적은 것은 건너뜀
    tm = tenor.findall('measure')
    assert tm[0].findtext('attributes/clef/clef-octave-change') == '-1'
    assert pitch_of(tm[0].find('note')) == 'B-13'
    assert tm[1].find('attributes') is None and pitch_of(tm[1].find('note')) == 'E-14'
    # 짝 없는 붙임줄(다음 음이 쉼표)은 버린다: 뒤의 같은 음에 tie stop 을 붙이지 않는다
    t2 = tm[1].findall('note')
    assert t2[0].find("tie[@type='start']") is not None and t2[2].find('tie') is None
    assert len(tm) == 4  # 짧은 보표는 온마디 쉼표로 채움
    assert tm[3].find('note/rest').get('measure') == 'yes'
    # NWZ 디코더: [NWZ] + zlib(헤더 + NWCTXT)
    fake = b'[NWZ]\x00' + zlib.compress(b'[NoteWorthy ArtWare]\x00\x00\x00[NoteWorthy Composer]\x00K\x02'
                                         + SAMPLE.encode('utf-8'))
    tmp = Path(__file__).with_name('_test.nwc')
    tmp.write_bytes(fake)
    try:
        assert n.read_nwctxt(tmp) == SAMPLE.split('!NoteWorthyComposer-End')[0]
    finally:
        tmp.unlink()
    print('ok')


if __name__ == '__main__':
    test()
