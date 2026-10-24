# -*- coding: utf-8 -*-
"""oren.py - DraveJavis luistert: knop ingedrukt houden = opnemen, loslaten = omzetten naar tekst.

Opnemen met sounddevice, omzetten met faster-whisper (OpenAI Whisper, draait offline op de CPU).
Het whisper-model wordt de eerste keer gedownload naar de datamap van DraveJavis.
"""
from __future__ import annotations

import os
import threading

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None
try:
    import sounddevice as sd
except Exception:  # pragma: no cover
    sd = None

MODELLEN = [("tiny", "Heel snel, minder precies"), ("base", "Snel (aanbevolen)"),
            ("small", "Preciezer, trager"), ("medium", "Heel precies, traag")]


class Oren:
    def __init__(self, modelmap, grootte="base", taal="nl", sr=16000):
        self.modelmap = modelmap
        self.grootte = grootte
        self.taal = taal
        self.sr = sr
        self._stroom = None
        self._stukken = []
        self.neemt_op = False
        self._model = None
        self._model_grootte = None
        self.status = "klaar" if self.beschikbaar() else "geen_microfoon"
        self._lock = threading.Lock()
        self._niveau = 0.0

    def beschikbaar(self):
        return sd is not None and np is not None

    def heeft_microfoon(self):
        if not self.beschikbaar():
            return False
        try:
            return any(d.get("max_input_channels", 0) > 0 for d in sd.query_devices())
        except Exception:
            return False

    # ------------------------------------------------------------ opnemen
    def start(self):
        if not self.beschikbaar() or self.neemt_op:
            return False
        self._stukken = []
        try:
            self._stroom = sd.InputStream(samplerate=self.sr, channels=1, dtype="float32", callback=self._cb)
            self._stroom.start()
            self.neemt_op = True
            return True
        except Exception:
            self._stroom = None
            self.neemt_op = False
            self.status = "geen_microfoon"
            return False

    def _cb(self, indata, frames, tijd, status):
        try:
            self._stukken.append(indata.copy())
            self._niveau = min(1.0, float(np.sqrt(np.mean(indata ** 2))) * 12)
        except Exception:
            pass

    def stop(self):
        self.neemt_op = False
        try:
            if self._stroom is not None:
                self._stroom.stop()
                self._stroom.close()
        except Exception:
            pass
        self._stroom = None
        self._niveau = 0.0
        if not self._stukken or np is None:
            return None
        try:
            return np.concatenate(self._stukken, axis=0).flatten().astype("float32")
        except Exception:
            return None

    def niveau(self):
        return self._niveau if self.neemt_op else 0.0

    # ------------------------------------------------------------ omzetten
    def _laad(self):
        if self._model is not None and self._model_grootte == self.grootte:
            return True
        with self._lock:
            try:
                from faster_whisper import WhisperModel
            except Exception:
                self.status = "geen_whisper"
                return False
            try:
                self.status = "laden"
                os.makedirs(self.modelmap, exist_ok=True)
                self._model = WhisperModel(self.grootte, device="cpu", compute_type="int8",
                                           download_root=self.modelmap)
                self._model_grootte = self.grootte
                self.status = "klaar"
                return True
            except Exception as e:
                self.status = "mislukt"
                self.fout = str(e)
                return False

    def warm_op(self):
        threading.Thread(target=self._laad, daemon=True).start()

    def naar_tekst(self, audio):
        """Blokkerend: roep aan vanuit een thread."""
        if audio is None or len(audio) < self.sr // 4:
            return ""
        if not self._laad():
            return ""
        try:
            segs, _info = self._model.transcribe(audio, language=self.taal, beam_size=1, vad_filter=True)
            return " ".join(s.text.strip() for s in segs).strip()
        except Exception:
            try:
                segs, _info = self._model.transcribe(audio, language=self.taal, beam_size=1)
                return " ".join(s.text.strip() for s in segs).strip()
            except Exception:
                return ""
