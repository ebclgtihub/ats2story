#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MP3-Analyse (Dauer/Bitrate/Kanäle) und WAV->MP3-Transkodierung."""
from __future__ import annotations

import io
import wave

# MPEG-Bitrate-Tabellen: [version][layer] -> Index-Liste (kbit/s).
_BR = {
    1: {1: [0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448],
        2: [0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384],
        3: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320]},
    2: {1: [0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256],
        2: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
        3: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160]},
}
_SR = {3: {0: 44100, 1: 48000, 2: 32000},
       2: {0: 22050, 1: 24000, 2: 16000},
       0: {0: 11025, 1: 12000, 2: 8000}}


def mp3_info(b: bytes) -> tuple[int, int, int, int]:
    """-> (dur_ms, sample_rate, channels, sample_count). Frame-summierend, VBR-fest."""
    i, n = 0, len(b)
    # ID3v2 überspringen
    if b[:3] == b'ID3':
        size = ((b[6] & 0x7f) << 21) | ((b[7] & 0x7f) << 14) | ((b[8] & 0x7f) << 7) | (b[9] & 0x7f)
        i = 10 + size
    dur = 0.0
    samples = 0
    srate_last, channels_last = 44100, 2
    while i + 4 <= n:
        if b[i] != 0xFF or (b[i + 1] & 0xE0) != 0xE0:
            i += 1
            continue
        ver = (b[i + 1] >> 3) & 3          # 3=MPEG1,2=MPEG2
        layer = (b[i + 1] >> 1) & 3        # 1=LayerIII
        if layer == 0 or ver == 1:
            i += 1
            continue
        bri = (b[i + 2] >> 4) & 0xF
        sri = (b[i + 2] >> 2) & 3
        pad = (b[i + 2] >> 1) & 1
        chmode = (b[i + 3] >> 6) & 3       # 3=mono
        lkey = 1 if ver == 3 else 2
        lr = 3 if layer == 1 else (2 if layer == 2 else 1)
        if bri == 0 or bri == 15 or sri == 3:
            i += 1
            continue
        try:
            bitrate = _BR[lkey][lr][bri] * 1000
            srate = _SR[ver][sri]
        except Exception:
            i += 1
            continue
        if bitrate == 0 or srate == 0:
            i += 1
            continue
        spf = 1152 if (ver == 3) else 576   # samples per frame (LayerIII)
        flen = int((spf // 8 * bitrate) // srate) + pad
        if flen <= 0:
            i += 1
            continue
        dur += spf / srate
        samples += spf
        srate_last = srate
        channels_last = 1 if chmode == 3 else 2
        i += flen
    return int(dur * 1000), srate_last, channels_last, samples


def mp3_duration_ms(b: bytes) -> int:
    """Dauer eines MP3 in Millisekunden."""
    return mp3_info(b)[0]


def wav_to_mp3(raw: bytes) -> bytes:
    """WAV-Bytes -> MP3-Bytes via lameenc (128 kbit/s)."""
    import lameenc
    w = wave.open(io.BytesIO(raw))
    ch, sr = w.getnchannels(), w.getframerate()
    pcm = w.readframes(w.getnframes())
    enc = lameenc.Encoder()
    enc.set_bit_rate(128)
    enc.set_in_sample_rate(sr)
    enc.set_channels(ch)
    enc.set_quality(2)
    return enc.encode(pcm) + enc.flush()
