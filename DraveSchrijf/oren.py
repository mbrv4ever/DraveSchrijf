# -*- coding: utf-8 -*-
"""oren.py - DraveJavis luistert: knop ingedrukt houden = opnemen, loslaten = omzetten naar tekst.

Opnemen met sounddevice, omzetten met faster-whisper (OpenAI Whisper, draait offline op de CPU).
Het whisper-model wordt de eerste keer gedownload naar de datamap van DraveJavis.
"""
from __future__ import annotations

import difflib
import os
import re
import threading

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None
try:
    import sounddevice as sd
except Exception:  # pragma: no cover
    sd = None

# Namen die de spraakherkenning anders verkeerd schrijft (je kunt er in Instellingen zelf woorden bij zetten)
STANDAARD_WOORDEN = ["DraveSchrijf", "Dravenlock", "Drave", "Leon", "Claudio"]

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
        self.woorden = list(STANDAARD_WOORDEN)
        self.vervang = {}            # verbeterlijst: fout verstaan (kleine letters) -> zo moet het

    def zet_woorden(self, eigen):
        """eigen = tekst met komma's, bijvoorbeeld 'Max, Sanne, Bello'"""
        extra = [w.strip() for w in re.split(r"[,;\n]", eigen or "") if w.strip()]
        self.woorden = list(dict.fromkeys(STANDAARD_WOORDEN + extra))

    def _verbeter(self, tekst):
        """Woorden die bijna een bekende naam zijn (drevschrijf -> DraveSchrijf) goed schrijven."""
        if not tekst:
            return tekst
        laag = {w.lower(): w for w in self.woorden if " " not in w}

        def een(m):
            w = m.group(0)
            goed = self.vervang.get(w.lower())
            if goed:                                   # uit de verbeterlijst: altijd zo
                return goed[0].upper() + goed[1:] if w[:1].isupper() and goed[:1].islower() else goed
            if len(w) < 4:
                return w
            if w.lower() in laag:
                return laag[w.lower()]
            beste = difflib.get_close_matches(w.lower(), list(laag), n=1, cutoff=0.82)
            if beste and beste[0][0] == w.lower()[0]:
                return laag[beste[0]]
            return w
        return re.sub(r"[A-Za-zÀ-ÿ]+", een, tekst)

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
        hulp = ", ".join(self.woorden)
        pogingen = [dict(vad_filter=True, initial_prompt=hulp, hotwords=hulp),
                    dict(vad_filter=True, initial_prompt=hulp),           # oudere faster-whisper: zonder hotwords
                    dict()]
        for extra in pogingen:
            try:
                segs, _info = self._model.transcribe(audio, language=self.taal, beam_size=5 if extra else 1, **extra)
                return self._verbeter(" ".join(s.text.strip() for s in segs).strip())
            except TypeError:
                continue
            except Exception:
                continue
        return ""
