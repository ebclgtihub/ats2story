#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Globaler, md5-deduplizierter Medienpool (Bilder + Audio)."""
from __future__ import annotations

import datetime
import hashlib
import html

from ..guid import media_filename, newg
from .audio import mp3_info, wav_to_mp3
from .image import reencode_image


class MediaPool:
    """Globaler, md5-deduplizierter Medienpool.

    Die Entry-dicts haben bewusst dieselbe Form wie im Monolith
    (``guid, fname, ext, md5, dur, audio`` und für Bilder zusätzlich ``w, h``),
    da der Builder direkt darauf zugreift.
    """

    def __init__(self) -> None:
        #: Grund des letzten fehlgeschlagenen add_audio — sonst meldet der
        #: Export nur „Audio nicht übernommen" und niemand weiss, warum.
        self.last_audio_error: str | None = None
        self.by_md5: dict[str, dict] = {}     # md5 -> entry dict
        self.files: dict[str, bytes] = {}     # 'story/media/<fname>' -> bytes
        self.media_xml: list[str] = []        # <media> (Bilder) — MÜSSEN vor <audio> stehen
        self.audio_xml: list[str] = []        # <audio>

    @property
    def entries_xml(self) -> list[str]:
        """mediaLst-Reihenfolge: ALLE <media> zuerst, dann ALLE <audio>."""
        return self.media_xml + self.audio_xml

    def _add(self, raw: bytes, ext: str, mtype: str, display: str | None,
             is_audio: bool, dur: int = 0, audio_info: tuple | None = None) -> dict:
        md5 = hashlib.md5(raw).hexdigest()
        if md5 in self.by_md5:
            return self.by_md5[md5]
        guid = newg()
        fname = media_filename(guid, ext)
        self.files['story/media/' + fname] = raw
        now = datetime.datetime.now().astimezone().isoformat()
        disp = html.escape((display or ('Audio' if is_audio else 'Bild'))[:80])
        if is_audio:
            sr, ch, scnt = audio_info or (44100, 2, 0)
            wavbytes = scnt * ch * 2 + 44      # plausible decodierte WAV-Größe
            xml = (f'<audio g="{guid}" verG="{newg()}" type="{mtype}" displayName="{disp}" '
                   f'origFile="" source="" useCnt="0" bytes="{len(raw)}" modDT="{now}" addDT="{now}" '
                   f'editDT="{now}" hasClosedCaptions="false" origBytes="{len(raw)}" origModDT="{now}">'
                   f'<userState w="0" h="0" />'
                   f'<md5Checksum><stream>{md5}</stream><source>{md5}</source></md5Checksum>'
                   f'<props valid="true" file="" bytes="{wavbytes}" channels="{ch}" samples="{sr}" '
                   f'bits="{max(0, wavbytes - 44)}" sampleCnt="{scnt}" startPt="0" mp3="true" origFile="" /></audio>')
            self.audio_xml.append(xml)
        else:
            xml = (f'<media g="{guid}" verG="{newg()}" type="{mtype}" displayName="{disp}" '
                   f'origFile="" source="" useCnt="0" bytes="{len(raw)}" modDT="{now}" addDT="{now}">'
                   f'<md5Checksum><stream>{md5}</stream><source>{md5}</source></md5Checksum></media>')
            self.media_xml.append(xml)
        entry = dict(guid=guid, fname=fname, ext=ext, md5=md5, dur=dur, audio=is_audio)
        self.by_md5[md5] = entry
        return entry

    def add_image(self, raw: bytes, display: str | None) -> dict | None:
        """PNG/JPG -> non-interlaced/baseline re-encodiert.
        Gibt ``None`` zurück, wenn das Bild nicht dekodierbar ist."""
        enc = reencode_image(raw)
        if enc is None:
            return None
        e = self._add(enc.data, enc.ext, enc.mtype, display, False)
        e['w'], e['h'] = enc.width, enc.height
        return e

    def add_audio(self, raw: bytes, display: str | None) -> dict | None:
        """MP3 wird durchgereicht; WAV via lameenc transkodiert.

        Gibt ``None`` zurück, wenn das Audio nicht verarbeitbar ist; der Grund
        steht dann in :attr:`last_audio_error`.
        """
        self.last_audio_error = None
        try:
            if raw[:3] == b'ID3' or (len(raw) > 1 and raw[0] == 0xFF and (raw[1] & 0xE0) == 0xE0):
                mp3 = raw
            elif raw[:4] == b'RIFF':
                mp3 = wav_to_mp3(raw)
            else:
                mp3 = raw  # unbekannt -> versuchen
        except ModuleNotFoundError:
            # Der häufigste Fall: imc legt die Sprecheraufnahmen als WAV ab,
            # Storyline will MP3 — ohne den Encoder geht der Ton lautlos
            # verloren, und die Ursache ist von aussen nicht zu erkennen.
            self.last_audio_error = ('MP3-Encoder fehlt (lameenc) — WAV-Ton kann '
                                     'nicht umgewandelt werden')
            return None
        except Exception as e:
            self.last_audio_error = f'{type(e).__name__}: {e}'
            return None
        dur, sr, ch, scnt = mp3_info(mp3)
        return self._add(mp3, 'mp3', 'Mp3', display, True, dur=dur, audio_info=(sr, ch, scnt))
