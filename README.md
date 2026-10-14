# NWC to MusicXML

NoteWorthy Composer 악보(.nwc, .nwctxt)를 MusicXML(.musicxml)로 바꾸는 변환기.
Python 3.9 이상, 표준 라이브러리만 사용(설치할 것 없음). MIT 라이선스.

*Converts NoteWorthy Composer 2.75 scores (.nwc / .nwctxt) to MusicXML with the Python standard library only.
Usage: `python nwc2musicxml.py score.nwc` — see below (Korean).*

## 사용법

```bash
python nwc2musicxml.py "악보.nwc"              # 같은 폴더에 악보.musicxml 생성
python nwc2musicxml.py 폴더 -o 출력폴더         # 폴더 안 .nwc/.nwctxt 전부(하위 폴더 포함)
python nwc2musicxml.py "악보.nwc" --nwctxt     # 풀어낸 NWCTXT 텍스트도 같이 저장
```

만든 .musicxml은 MuseScore 등에서 바로 열린다.

## 동작

.nwc(2.75)는 `[NWZ]` 머리글 뒤가 zlib 압축이고, 풀면 그 안에 NWCTXT 텍스트가 그대로 들어 있다.
그 텍스트를 읽어 MusicXML로 쓴다. 글자는 줄마다 UTF-8 → CP949 → Latin-1 순으로 읽는다
(본문은 UTF-8이지만 한글 글꼴 이름은 CP949, "Più mosso" 같은 내장 문자열은 Latin-1로 섞여 있다).

## 지원 범위

- 음표·화음·쉼표, 점·겹점, 셋잇단, 꾸밈음, 붙임줄, 이음줄, 스타카토 등 아티큘레이션
- 두 길이 화음(`Dur2`)은 긴 쪽을 2성부로 (쉼표+음표 `RestChord` 포함)
- 조표·박자표·음자리표(옥타브 이동), 마디 안 임시표 규칙, 못갖춘마디
- 가사 여러 줄, 하이픈(`ha-ppy`, `noth -ing`), 멜리스마(`_`), 음절 배정 규칙(붙임줄·이음줄로 이어진 음과 꾸밈음은 건너뜀, `Lyric=Always/Never`)
- 셈여림, 크레셴도/디미누엔도 꺾쇠, 템포(기준 음표 포함)·템포 변화, 페르마타, 숨표
- 마디 종류(겹세로줄, 반복), 1·2번 괄호, 코다/세뇨/D.S. 등, 텍스트, 페달
- 보표 묶음(brace/bracket/세로줄 연결), 파트 이름, MIDI 채널·악기
- NWC 관례 그대로: 혼자 있는 온쉼표는 마디 전체 쉼표, 연속된 세로줄(빈 마디)은 하나로 합침
- 보표마다 마디 수가 다르면 짧은 보표 뒤를 온마디 쉼표로 채워 MuseScore에서 줄이 맞게 함

## 안 되는 것

- 2.75 이전 바이너리 .nwc (NoteWorthy Composer에서 .nwctxt로 저장한 뒤 변환)
- 보표 겹치기(Layer)는 별도 보표로 나온다
- 빔은 쓰지 않는다 (MuseScore가 자동으로 그린다)

## 검증 (2026-10)

- 합창 동아리 악보 46개(NWC 2.75 .nwc 36개 + .nwctxt) 전부 변환. 마디 길이 검사에서 남은 불일치 5건은 원본 악보 쪽 실수(세로줄 누락, 온쉼표 두 개 등).
- NWC가 내보낸 MIDI와 음표 단위 대조: 성악 파트는 음높이·시작 박이 전부 일치(붙임줄을 합친 뒤). 피아노 파트의 차이는 MIDI가 수정 전 버전이라 생긴 것.
- 같은 곡을 MuseScore에서 손으로 옮긴 파일과 대조: SATB 음표열 99.8% 일치.
- MuseScore 4로 렌더해 확인: 가사(한글 포함) 배정, 셋잇단, 박자 변경, 옥타브 테너 음자리표, 두 성부 화음, 반복 기호.

## 점검

```bash
python test_nwc2musicxml.py
```
