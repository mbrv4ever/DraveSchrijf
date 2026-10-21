# -*- coding: utf-8 -*-
# DraveSchrijf - rustig schrijven aan je boek, met inspreken en voorlezen.
# Copyright (C) 2026 Dravenlock (Roger & Claudio). Vrije software onder de GNU GPL v3.0.
"""DraveSchrijf: een schrijfapp voor lange teksten (een boek, een verhaal, een dagboek).

- Boeken met hoofdstukken (links), groot en rustig typvlak (midden), donker scherm.
- Inspreken: houd de microfoonknop (of F2) ingedrukt, praat, laat los -> tekst (faster-whisper, offline).
- Voorlezen: leest de selectie of vanaf de cursor voor met een neurale stem (neuvoice, offline),
  en kleurt de zin die hij uitspreekt.
- Alles wordt vanzelf bewaard als gewone tekstbestanden in Documenten\\DraveSchrijf.
- Elke dag een reservekopie (zip) van je boek.
- Exporteren naar PDF of tekst.
"""
import datetime
import json
import os
import re
import shutil
import sys
import threading
import zipfile

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QEvent, QSizeF, QMarginsF
from PyQt6.QtGui import (QFont, QIcon, QKeySequence, QShortcut, QTextCursor, QTextCharFormat, QColor,
                         QTextDocument, QPageLayout, QPageSize, QAction)
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel, QPushButton, QVBoxLayout,
                             QHBoxLayout, QListWidget, QListWidgetItem, QPlainTextEdit, QSplitter,
                             QInputDialog, QMessageBox, QFileDialog, QDialog, QComboBox, QSlider,
                             QFormLayout, QLineEdit, QCheckBox, QMenu, QToolButton, QTextEdit)

APP_NAAM = "DraveSchrijf"
APP_VERSION = "1.0"

BG, PANEL, VAK, ZILVER, GRIJS, ACCENT, GOUD = "#0e0e11", "#16161b", "#121216", "#e6e6ea", "#8a8a94", "#6fa3d6", "#ffb347"


# ------------------------------------------------------------------ paden en instellingen
def app_map():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def bron(naam):
    for b in (getattr(sys, "_MEIPASS", None), app_map()):
        if b and os.path.exists(os.path.join(b, naam)):
            return os.path.join(b, naam)
    return os.path.join(app_map(), naam)


def documenten():
    try:
        import ctypes
        from ctypes import wintypes
        buf = ctypes.c_wchar_p()
        guid = (ctypes.c_ubyte * 16).from_buffer_copy(
            b"\xd0\x9a\xd3\xfd\x8f\x23\xaf\x46\xad\xb4\x6c\x85\x48\x03\x69\xc7")  # FOLDERID_Documents
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(buf)) == 0:
            p = buf.value
            ctypes.windll.ole32.CoTaskMemFree(buf)
            return p
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Documents")


def data_map():
    b = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    p = os.path.join(b, "DraveSchrijf")
    os.makedirs(p, exist_ok=True)
    return p


CFG_PAD = os.path.join(data_map(), "instellingen.json")
STANDAARD = dict(map=os.path.join(documenten(), "DraveSchrijf"), boek="", letter=20, lettertype="Georgia",
                 stem="Cole", snelheid=1.0, whisper="base", taal="nl", regelbreedte=820)


def lees_cfg():
    c = dict(STANDAARD)
    try:
        with open(CFG_PAD, encoding="utf-8-sig") as f:
            c.update(json.load(f))
    except Exception:
        pass
    return c


def bewaar_cfg(c):
    try:
        with open(CFG_PAD, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def veilige_naam(t):
    t = re.sub(r'[\\/:*?"<>|]+', "", t).strip().strip(".")
    return t[:80] or "Naamloos"


# ------------------------------------------------------------------ een boek op schijf
class Boek:
    """Een map met boek.json (volgorde + titels) en per hoofdstuk een .txt-bestand."""

    def __init__(self, map_):
        self.map = map_
        os.makedirs(map_, exist_ok=True)
        self.meta_pad = os.path.join(map_, "boek.json")
        try:
            with open(self.meta_pad, encoding="utf-8-sig") as f:
                self.meta = json.load(f)
        except Exception:
            self.meta = dict(titel=os.path.basename(map_), hoofdstukken=[])
        self.meta.setdefault("hoofdstukken", [])
        if not self.meta["hoofdstukken"]:
            self.nieuw_hoofdstuk("Hoofdstuk 1")

    @property
    def titel(self):
        return self.meta.get("titel") or os.path.basename(self.map)

    def bewaar_meta(self):
        tmp = self.meta_pad + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.meta, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.meta_pad)

    def pad(self, h):
        return os.path.join(self.map, h["bestand"])

    def lees(self, h):
        try:
            with open(self.pad(h), encoding="utf-8-sig") as f:
                return f.read()
        except Exception:
            return ""

    def schrijf(self, h, tekst):
        tmp = self.pad(h) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(tekst)
        os.replace(tmp, self.pad(h))

    def nieuw_hoofdstuk(self, titel, na=None):
        n = 1
        while os.path.exists(os.path.join(self.map, "%03d.txt" % n)):
            n += 1
        h = dict(titel=titel, bestand="%03d.txt" % n)
        open(os.path.join(self.map, h["bestand"]), "w", encoding="utf-8").close()
        lijst = self.meta["hoofdstukken"]
        lijst.insert(len(lijst) if na is None else na + 1, h)
        self.bewaar_meta()
        return h

    def reservekopie(self):
        """Eén zip per dag in <map>\\_reservekopie (de laatste 14 dagen)."""
        try:
            rk = os.path.join(os.path.dirname(self.map), "_reservekopie")
            os.makedirs(rk, exist_ok=True)
            naam = os.path.join(rk, "%s_%s.zip" % (veilige_naam(self.titel), datetime.date.today().isoformat()))
            with zipfile.ZipFile(naam, "w", zipfile.ZIP_DEFLATED) as z:
                for f in os.listdir(self.map):
                    if f.endswith((".txt", ".json")):
                        z.write(os.path.join(self.map, f), f)
            oud = sorted(f for f in os.listdir(rk) if f.startswith(veilige_naam(self.titel) + "_"))
            for f in oud[:-14]:
                os.remove(os.path.join(rk, f))
        except Exception:
            pass


def woorden(t):
    return len(re.findall(r"\w+", t))


# ------------------------------------------------------------------ signalen van de achtergrond
class Sein(QObject):
    tekst_klaar = pyqtSignal(str)
    zin_begint = pyqtSignal(object)
    status = pyqtSignal(str)


# ------------------------------------------------------------------ instellingen-venster
class Instellingen(QDialog):
    def __init__(self, ouder, cfg, stemmen):
        super().__init__(ouder)
        self.setWindowTitle("Instellingen")
        self.cfg = cfg
        f = QFormLayout(self)
        self.letter = QSlider(Qt.Orientation.Horizontal)
        self.letter.setRange(12, 40)
        self.letter.setValue(int(cfg["letter"]))
        f.addRow("Lettergrootte", self.letter)
        self.lettertype = QComboBox()
        for n in ("Georgia", "Segoe UI", "Verdana", "Atkinson Hyperlegible", "Consolas"):
            self.lettertype.addItem(n)
        self.lettertype.setCurrentText(cfg["lettertype"])
        f.addRow("Lettertype", self.lettertype)
        self.breedte = QSlider(Qt.Orientation.Horizontal)
        self.breedte.setRange(500, 1600)
        self.breedte.setValue(int(cfg["regelbreedte"]))
        f.addRow("Breedte van de tekst", self.breedte)
        self.stem = QComboBox()
        for s in (stemmen or ["Cole", "Leon", "Cem", "Lina", "Linda", "Alina"]):
            self.stem.addItem(s)
        self.stem.setCurrentText(cfg["stem"])
        f.addRow("Voorleesstem", self.stem)
        self.snel = QSlider(Qt.Orientation.Horizontal)
        self.snel.setRange(60, 160)
        self.snel.setValue(int(float(cfg["snelheid"]) * 100))
        f.addRow("Voorleessnelheid", self.snel)
        self.whisper = QComboBox()
        for k, uitleg in (("tiny", "heel snel, minder precies"), ("base", "snel (aanbevolen)"),
                          ("small", "preciezer, trager"), ("medium", "heel precies, traag")):
            self.whisper.addItem("%s - %s" % (k, uitleg), k)
        self.whisper.setCurrentIndex(max(0, ["tiny", "base", "small", "medium"].index(cfg["whisper"])
                                         if cfg["whisper"] in ("tiny", "base", "small", "medium") else 1))
        f.addRow("Spraakherkenning", self.whisper)
        self.taal = QComboBox()
        self.taal.addItem("Nederlands", "nl")
        self.taal.addItem("English", "en")
        self.taal.setCurrentIndex(0 if cfg["taal"] == "nl" else 1)
        f.addRow("Taal van inspreken/voorlezen", self.taal)
        ok = QPushButton("OK")
        ok.clicked.connect(self.accept)
        f.addRow(ok)

    def waarden(self):
        return dict(letter=self.letter.value(), lettertype=self.lettertype.currentText(),
                    regelbreedte=self.breedte.value(), stem=self.stem.currentText(),
                    snelheid=self.snel.value() / 100.0, whisper=self.whisper.currentData(),
                    taal=self.taal.currentData())


# ------------------------------------------------------------------ hoofdvenster
class Schrijf(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = lees_cfg()
        self.setWindowTitle(APP_NAAM)
        self.setWindowIcon(QIcon(bron(os.path.join("assets", "icon.ico"))))
        self.resize(1400, 900)
        self.sein = Sein()
        self.sein.tekst_klaar.connect(self._ingesproken)
        self.sein.zin_begint.connect(self._kleur_zin)
        self.sein.status.connect(lambda t: self.statusBar().showMessage(t, 6000))
        self.boek = None
        self.huidig = None
        self._vies = False
        self._laden = False
        self.stem = None
        self.oren = None
        self._ingedrukt = False
        self._bouw()
        self._stijl()
        self.open_boek(self.cfg.get("boek") or self._eerste_boek())
        self.bewaar_klok = QTimer(self)
        self.bewaar_klok.timeout.connect(self.bewaar)
        self.bewaar_klok.start(3000)

    # ---- opbouw
    def _bouw(self):
        hoofd = QWidget()
        self.setCentralWidget(hoofd)
        lay = QVBoxLayout(hoofd)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        # werkbalk
        balk = QWidget()
        balk.setObjectName("balk")
        bl = QHBoxLayout(balk)
        bl.setContentsMargins(14, 8, 14, 8)
        self.boek_knop = QToolButton()
        self.boek_knop.setObjectName("boek")
        self.boek_knop.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.boek_menu = QMenu(self)
        self.boek_knop.setMenu(self.boek_menu)
        bl.addWidget(self.boek_knop)
        bl.addStretch(1)
        self.mic = QPushButton("🎙  Houd vast en praat (F2)")
        self.mic.setObjectName("mic")
        self.mic.pressed.connect(self.start_inspreken)
        self.mic.released.connect(self.stop_inspreken)
        bl.addWidget(self.mic)
        self.lees = QPushButton("🔊  Voorlezen")
        self.lees.clicked.connect(self.voorlezen)
        bl.addWidget(self.lees)
        self.stop = QPushButton("■  Stil")
        self.stop.clicked.connect(self.stil)
        bl.addWidget(self.stop)
        for tekst, fn in (("⛶  Focus (F11)", self.focus), ("⚙  Instellingen", self.instellingen),
                          ("?  Snelgids", self.snelgids)):
            b = QPushButton(tekst)
            b.clicked.connect(fn)
            bl.addWidget(b)
        lay.addWidget(balk)
        # links hoofdstukken, rechts tekst
        self.split = QSplitter()
        links = QWidget()
        links.setObjectName("links")
        ll = QVBoxLayout(links)
        ll.setContentsMargins(10, 10, 10, 10)
        kop = QLabel("Hoofdstukken")
        kop.setObjectName("kopje")
        ll.addWidget(kop)
        self.lijst = QListWidget()
        self.lijst.currentRowChanged.connect(self.kies_hoofdstuk)
        self.lijst.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.lijst.customContextMenuRequested.connect(self._lijst_menu)
        self.lijst.itemDoubleClicked.connect(lambda *_: self.hernoem())
        ll.addWidget(self.lijst, 1)
        rij = QHBoxLayout()
        for tekst, fn, tip in (("＋", self.nieuw_hoofdstuk, "Nieuw hoofdstuk (Ctrl+Shift+N)"),
                               ("↑", lambda: self.verschuif(-1), "Omhoog"), ("↓", lambda: self.verschuif(1), "Omlaag"),
                               ("✎", self.hernoem, "Naam wijzigen (F2 in de lijst / dubbelklik)")):
            b = QPushButton(tekst)
            b.setToolTip(tip)
            b.setObjectName("klein")
            b.clicked.connect(fn)
            rij.addWidget(b)
        ll.addLayout(rij)
        self.totaal = QLabel("")
        self.totaal.setObjectName("grijs")
        ll.addWidget(self.totaal)
        self.split.addWidget(links)
        midden = QWidget()
        midden.setObjectName("midden")
        ml = QHBoxLayout(midden)
        ml.setContentsMargins(0, 0, 0, 0)
        self.vak = QPlainTextEdit()
        self.vak.setObjectName("vak")
        self.vak.textChanged.connect(self._gewijzigd)
        self.vak.setTabChangesFocus(False)
        ml.addStretch(1)
        ml.addWidget(self.vak, 100)
        ml.addStretch(1)
        self.split.addWidget(midden)
        self.split.setSizes([300, 1100])
        lay.addWidget(self.split, 1)
        # zoekbalk
        self.zoekbalk = QWidget()
        zb = QHBoxLayout(self.zoekbalk)
        zb.setContentsMargins(14, 4, 14, 4)
        zb.addWidget(QLabel("Zoeken:"))
        self.zoek = QLineEdit()
        self.zoek.returnPressed.connect(self.zoek_volgende)
        zb.addWidget(self.zoek, 1)
        b = QPushButton("Volgende")
        b.clicked.connect(self.zoek_volgende)
        zb.addWidget(b)
        b = QPushButton("✕")
        b.clicked.connect(lambda: self.zoekbalk.hide())
        zb.addWidget(b)
        self.zoekbalk.hide()
        lay.addWidget(self.zoekbalk)
        self.telling = QLabel("")
        self.statusBar().addPermanentWidget(self.telling)
        self.statusBar().addPermanentWidget(QLabel("v" + APP_VERSION))
        # sneltoetsen
        for toets, fn in (("Ctrl+S", self.bewaar), ("Ctrl+Shift+N", self.nieuw_hoofdstuk), ("Ctrl+F", self.toon_zoek),
                          ("F3", self.zoek_volgende), ("F11", self.focus), ("Escape", self.esc),
                          ("Ctrl+=", lambda: self.lettergrootte(2)), ("Ctrl++", lambda: self.lettergrootte(2)),
                          ("Ctrl+-", lambda: self.lettergrootte(-2)), ("F5", self.voorlezen),
                          ("Ctrl+PgDown", lambda: self.volgende(1)), ("Ctrl+PgUp", lambda: self.volgende(-1))):
            QShortcut(QKeySequence(toets), self, activated=fn)
        QApplication.instance().installEventFilter(self)

    def _stijl(self):
        c = self.cfg
        self.setStyleSheet("""
            QMainWindow, QWidget#midden { background:%(BG)s; }
            QWidget { color:%(Z)s; font-size:17px; }
            QWidget#balk { background:%(PANEL)s; border-bottom:1px solid #26262e; }
            QWidget#links { background:%(PANEL)s; }
            QLabel#kopje { font-size:19px; font-weight:700; color:white; }
            QLabel#grijs { color:%(G)s; font-size:15px; }
            QListWidget { background:%(VAK)s; border:1px solid #26262e; border-radius:8px; font-size:18px; }
            QListWidget::item { padding:9px 8px; }
            QListWidget::item:selected { background:#2a3a52; color:white; }
            QPlainTextEdit#vak { background:%(BG)s; color:%(Z)s; border:0; padding:40px 20px;
                                 font-family:"%(F)s"; font-size:%(L)dpx; selection-background-color:#2a3a52; }
            QPushButton, QToolButton { background:#24242c; color:%(Z)s; border:1px solid #3a3a44; border-radius:8px;
                                       padding:8px 14px; font-size:16px; }
            QPushButton:hover, QToolButton:hover { border-color:%(A)s; }
            QPushButton#mic { background:%(A)s; color:#0e0e11; font-weight:700; border:0; }
            QPushButton#mic[luistert="true"] { background:#5ad988; }
            QPushButton#klein { padding:4px 8px; font-size:18px; }
            QToolButton#boek { font-size:19px; font-weight:700; color:white; padding:8px 16px; }
            QLineEdit, QComboBox { background:%(VAK)s; border:1px solid #3a3a44; border-radius:6px; padding:5px; }
            QStatusBar { background:%(PANEL)s; color:%(G)s; }
            QMenu { background:%(PANEL)s; border:1px solid #3a3a44; } QMenu::item:selected { background:#2a3a52; }
        """ % dict(BG=BG, PANEL=PANEL, VAK=VAK, Z=ZILVER, G=GRIJS, A=ACCENT, F=c["lettertype"], L=int(c["letter"])))
        self.vak.setMaximumWidth(int(c["regelbreedte"]))

    # ---- boeken
    def _eerste_boek(self):
        os.makedirs(self.cfg["map"], exist_ok=True)
        boeken = self._boeken()
        return boeken[0] if boeken else os.path.join(self.cfg["map"], "Mijn boek")

    def _boeken(self):
        try:
            return sorted(os.path.join(self.cfg["map"], d) for d in os.listdir(self.cfg["map"])
                          if os.path.isfile(os.path.join(self.cfg["map"], d, "boek.json")))
        except Exception:
            return []

    def _vul_boek_menu(self):
        m = self.boek_menu
        m.clear()
        for p in self._boeken():
            a = m.addAction(("✓  " if self.boek and os.path.normcase(p) == os.path.normcase(self.boek.map) else "     ")
                            + os.path.basename(p))
            a.triggered.connect(lambda _=False, p=p: self.open_boek(p))
        m.addSeparator()
        m.addAction("＋  Nieuw boek...", self.nieuw_boek)
        m.addAction("✎  Boek een andere naam geven...", self.hernoem_boek)
        m.addSeparator()
        m.addAction("📄  Exporteren als PDF...", self.export_pdf)
        m.addAction("📝  Exporteren als tekst (.txt)...", self.export_txt)
        m.addAction("📁  Map met boeken openen", lambda: os.startfile(self.cfg["map"]))
        m.addAction("🗂  Reservekopieën openen", self._open_rk)

    def _open_rk(self):
        p = os.path.join(self.cfg["map"], "_reservekopie")
        os.makedirs(p, exist_ok=True)
        os.startfile(p)

    def open_boek(self, map_):
        self.bewaar()
        self.boek = Boek(map_)
        self.boek.reservekopie()
        self.cfg["boek"] = map_
        bewaar_cfg(self.cfg)
        self.boek_knop.setText("📖  %s  ▾" % self.boek.titel)
        self._vul_boek_menu()
        self._vul_lijst(self.boek.meta.get("laatst", 0))

    def nieuw_boek(self):
        naam, ok = QInputDialog.getText(self, "Nieuw boek", "Hoe heet je boek?")
        if ok and naam.strip():
            p = os.path.join(self.cfg["map"], veilige_naam(naam))
            if os.path.exists(p):
                QMessageBox.information(self, APP_NAAM, "Er is al een boek met die naam.")
                return
            b = Boek(p)
            b.meta["titel"] = naam.strip()
            b.bewaar_meta()
            self.open_boek(p)

    def hernoem_boek(self):
        naam, ok = QInputDialog.getText(self, "Boek", "Nieuwe titel:", text=self.boek.titel)
        if ok and naam.strip():
            self.boek.meta["titel"] = naam.strip()
            self.boek.bewaar_meta()
            self.boek_knop.setText("📖  %s  ▾" % self.boek.titel)

    # ---- hoofdstukken
    def _vul_lijst(self, kies=0):
        self._laden = True
        self.lijst.clear()
        for h in self.boek.meta["hoofdstukken"]:
            self.lijst.addItem(QListWidgetItem(h["titel"]))
        self._laden = False
        self.lijst.setCurrentRow(max(0, min(kies, self.lijst.count() - 1)))
        self._tel()

    def kies_hoofdstuk(self, i):
        if self._laden or i < 0:
            return
        self.bewaar()
        self.stil()
        self.huidig = self.boek.meta["hoofdstukken"][i]
        self._laden = True
        self.vak.setPlainText(self.boek.lees(self.huidig))
        self._laden = False
        self._vies = False
        c = self.vak.textCursor()
        c.movePosition(QTextCursor.MoveOperation.End)
        self.vak.setTextCursor(c)
        self.vak.setFocus()
        self.boek.meta["laatst"] = i
        self.boek.bewaar_meta()
        self._tel()

    def nieuw_hoofdstuk(self):
        n = len(self.boek.meta["hoofdstukken"]) + 1
        naam, ok = QInputDialog.getText(self, "Nieuw hoofdstuk", "Titel:", text="Hoofdstuk %d" % n)
        if ok:
            self.bewaar()
            self.boek.nieuw_hoofdstuk(naam.strip() or "Hoofdstuk %d" % n, self.lijst.currentRow())
            self._vul_lijst(self.lijst.currentRow() + 1)

    def hernoem(self):
        i = self.lijst.currentRow()
        if i < 0:
            return
        h = self.boek.meta["hoofdstukken"][i]
        naam, ok = QInputDialog.getText(self, "Hoofdstuk", "Nieuwe titel:", text=h["titel"])
        if ok and naam.strip():
            h["titel"] = naam.strip()
            self.boek.bewaar_meta()
            self.lijst.item(i).setText(h["titel"])

    def verschuif(self, d):
        i = self.lijst.currentRow()
        lijst = self.boek.meta["hoofdstukken"]
        j = i + d
        if i < 0 or not 0 <= j < len(lijst):
            return
        self.bewaar()
        lijst[i], lijst[j] = lijst[j], lijst[i]
        self.boek.bewaar_meta()
        self._vul_lijst(j)

    def verwijder(self):
        i = self.lijst.currentRow()
        lijst = self.boek.meta["hoofdstukken"]
        if i < 0:
            return
        if len(lijst) == 1:
            QMessageBox.information(self, APP_NAAM, "Een boek heeft minstens één hoofdstuk.")
            return
        h = lijst[i]
        if QMessageBox.question(self, "Verwijderen", "Hoofdstuk '%s' verwijderen?\n\nHet gaat naar de map "
                                "'_verwijderd' in je boek, dus je kunt het terughalen." % h["titel"]) \
                != QMessageBox.StandardButton.Yes:
            return
        self.bewaar()
        weg = os.path.join(self.boek.map, "_verwijderd")
        os.makedirs(weg, exist_ok=True)
        try:
            shutil.move(self.boek.pad(h), os.path.join(weg, "%s_%s.txt" % (veilige_naam(h["titel"]),
                                                                          datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))))
        except Exception:
            pass
        lijst.pop(i)
        self.boek.bewaar_meta()
        self.huidig = None
        self._vul_lijst(max(0, i - 1))

    def _lijst_menu(self, pos):
        m = QMenu(self)
        m.addAction("＋  Nieuw hoofdstuk", self.nieuw_hoofdstuk)
        m.addAction("✎  Naam wijzigen", self.hernoem)
        m.addAction("↑  Omhoog", lambda: self.verschuif(-1))
        m.addAction("↓  Omlaag", lambda: self.verschuif(1))
        m.addSeparator()
        m.addAction("🗑  Verwijderen", self.verwijder)
        m.exec(self.lijst.mapToGlobal(pos))

    def volgende(self, d):
        i = self.lijst.currentRow() + d
        if 0 <= i < self.lijst.count():
            self.lijst.setCurrentRow(i)

    # ---- bewaren en tellen
    def _gewijzigd(self):
        if not self._laden:
            self._vies = True
            self._tel_kort()

    def bewaar(self):
        if self._vies and self.boek and self.huidig:
            try:
                self.boek.schrijf(self.huidig, self.vak.toPlainText())
                self._vies = False
                self._tel()
            except Exception as e:
                self.statusBar().showMessage("Bewaren mislukt: %s" % e, 8000)

    def _tel_kort(self):
        t = self.vak.toPlainText()
        self.telling.setText("Dit hoofdstuk: %d woorden" % woorden(t))

    def _tel(self):
        self._tel_kort()
        if self.boek:
            tot = 0
            for h in self.boek.meta["hoofdstukken"]:
                tot += woorden(self.vak.toPlainText() if h is self.huidig else self.boek.lees(h))
            self.totaal.setText("%d hoofdstukken · %d woorden" % (len(self.boek.meta["hoofdstukken"]), tot))

    def lettergrootte(self, d):
        self.cfg["letter"] = max(12, min(40, int(self.cfg["letter"]) + d))
        bewaar_cfg(self.cfg)
        self._stijl()

    # ---- zoeken / focus
    def toon_zoek(self):
        self.zoekbalk.show()
        self.zoek.setFocus()
        self.zoek.selectAll()

    def zoek_volgende(self):
        t = self.zoek.text()
        if not t:
            return
        if not self.vak.find(t):
            c = self.vak.textCursor()
            c.movePosition(QTextCursor.MoveOperation.Start)
            self.vak.setTextCursor(c)
            if not self.vak.find(t):
                self.statusBar().showMessage("Niet gevonden: %s" % t, 4000)

    def focus(self):
        if self.isFullScreen():
            self.showNormal()
            self.split.widget(0).show()
            self.centralWidget().layout().itemAt(0).widget().show()
            self.statusBar().show()
        else:
            self.split.widget(0).hide()
            self.centralWidget().layout().itemAt(0).widget().hide()
            self.statusBar().hide()
            self.showFullScreen()
            self.vak.setFocus()

    def esc(self):
        if self.isFullScreen():
            self.focus()
        elif self.zoekbalk.isVisible():
            self.zoekbalk.hide()
        else:
            self.stil()

    # ---- stem en oren (pas laden als je ze gebruikt)
    def _zorg_stem(self):
        if self.stem is None:
            try:
                from stem import Stem
                self.stem = Stem(self.cfg["stem"], self.cfg["taal"], float(self.cfg["snelheid"]))
                self.stem.bij_begin = lambda label: self.sein.zin_begint.emit(label)
                self.stem.warm_op()
                self.sein.status.emit("Voorleesstem laden... (de eerste keer wordt hij gedownload)")
            except Exception as e:
                QMessageBox.warning(self, APP_NAAM, "Voorlezen is niet beschikbaar:\n%s" % e)
                return False
        return True

    def _zorg_oren(self):
        if self.oren is None:
            try:
                from oren import Oren
                self.oren = Oren(os.path.join(data_map(), "whisper-modellen"), self.cfg["whisper"], self.cfg["taal"])
                self.oren.warm_op()
            except Exception as e:
                QMessageBox.warning(self, APP_NAAM, "Inspreken is niet beschikbaar:\n%s" % e)
                return False
        return True

    def voorlezen(self):
        if not self._zorg_stem():
            return
        self.stil()
        c = self.vak.textCursor()
        tekst = self.vak.toPlainText()
        if c.hasSelection():
            begin, eind = c.selectionStart(), c.selectionEnd()
        else:
            begin, eind = c.position(), len(tekst)
            if begin >= eind:
                begin = 0
        # zinnen met hun positie
        for m in re.finditer(r"[^.!?\n]+[.!?]*\s*", tekst[begin:eind]):
            zin = m.group(0).strip()
            if zin:
                self.stem.zeg(zin, (begin + m.start(), begin + m.start() + len(m.group(0).rstrip())))
        self.sein.status.emit("Voorlezen... (Esc of ■ Stil om te stoppen)")

    def _kleur_zin(self, label):
        if not isinstance(label, tuple):
            return
        a, b = label
        sel = QTextEdit.ExtraSelection()
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#3a3424"))
        fmt.setForeground(QColor(GOUD))
        sel.format = fmt
        c = self.vak.textCursor()
        c.setPosition(min(a, len(self.vak.toPlainText())))
        c.setPosition(min(b, len(self.vak.toPlainText())), QTextCursor.MoveMode.KeepAnchor)
        sel.cursor = c
        self.vak.setExtraSelections([sel])
        rect = self.vak.cursorRect(c)
        if not self.vak.viewport().rect().contains(rect):
            sb = self.vak.verticalScrollBar()
            sb.setValue(sb.value() + (rect.top() - self.vak.viewport().height() // 3) // max(1, self.vak.fontMetrics().lineSpacing()))

    def stil(self):
        if self.stem is not None:
            self.stem.stil()
        self.vak.setExtraSelections([])

    def start_inspreken(self):
        if self._ingedrukt or not self._zorg_oren():
            return
        self.stil()
        if self.oren.start():
            self._ingedrukt = True
            self.mic.setProperty("luistert", True)
            self.mic.setText("🎙  Ik luister... laat los als je klaar bent")
            self.mic.style().unpolish(self.mic)
            self.mic.style().polish(self.mic)
        else:
            QMessageBox.information(self, APP_NAAM, "Ik vind geen microfoon.")

    def stop_inspreken(self):
        if not self._ingedrukt:
            return
        self._ingedrukt = False
        self.mic.setProperty("luistert", False)
        self.mic.setText("⏳  Omzetten naar tekst...")
        self.mic.style().unpolish(self.mic)
        self.mic.style().polish(self.mic)
        audio = self.oren.stop()

        def werk():
            t = self.oren.naar_tekst(audio)
            self.sein.tekst_klaar.emit(t)
        threading.Thread(target=werk, daemon=True).start()

    def _ingesproken(self, t):
        self.mic.setText("🎙  Houd vast en praat (F2)")
        if not t:
            self.sein.status.emit("Ik heb niets verstaan. Praat iets dichter bij de microfoon.")
            return
        c = self.vak.textCursor()
        voor = self.vak.toPlainText()[max(0, c.position() - 1):c.position()]
        if voor and not voor.isspace():
            t = " " + t
        c.insertText(t)
        self.vak.setTextCursor(c)
        self.vak.setFocus()

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.KeyPress and ev.key() == Qt.Key.Key_F2 and not ev.isAutoRepeat():
            if self.lijst.hasFocus():
                self.hernoem()
            else:
                self.start_inspreken()
            return True
        if ev.type() == QEvent.Type.KeyRelease and ev.key() == Qt.Key.Key_F2 and not ev.isAutoRepeat():
            self.stop_inspreken()
            return True
        return super().eventFilter(obj, ev)

    # ---- exporteren
    def _hele_boek(self):
        self.bewaar()
        delen = []
        for h in self.boek.meta["hoofdstukken"]:
            delen.append((h["titel"], self.vak.toPlainText() if h is self.huidig else self.boek.lees(h)))
        return delen

    def export_txt(self):
        p, _ = QFileDialog.getSaveFileName(self, "Exporteren", os.path.join(documenten(), veilige_naam(self.boek.titel) + ".txt"),
                                           "Tekst (*.txt)")
        if p:
            with open(p, "w", encoding="utf-8") as f:
                f.write(self.boek.titel + "\n\n")
                for titel, tekst in self._hele_boek():
                    f.write("\n\n%s\n%s\n\n%s\n" % (titel, "=" * len(titel), tekst.strip()))
            self.sein.status.emit("Opgeslagen: %s" % p)

    def export_pdf(self):
        p, _ = QFileDialog.getSaveFileName(self, "Exporteren als PDF",
                                           os.path.join(documenten(), veilige_naam(self.boek.titel) + ".pdf"), "PDF (*.pdf)")
        if not p:
            return
        from PyQt6.QtPrintSupport import QPrinter
        import html
        delen = ["<h1 style='text-align:center;margin-top:200px'>%s</h1>" % html.escape(self.boek.titel)]
        for titel, tekst in self._hele_boek():
            alineas = "".join("<p>%s</p>" % html.escape(a).replace("\n", "<br>") for a in re.split(r"\n\s*\n", tekst.strip()) if a.strip())
            delen.append("<h2 style='page-break-before:always'>%s</h2>%s" % (html.escape(titel), alineas))
        doc = QTextDocument()
        doc.setDefaultFont(QFont("Georgia", 12))
        doc.setHtml("<html><body style='font-family:Georgia;line-height:150%%'>%s</body></html>" % "".join(delen))
        pr = QPrinter(QPrinter.PrinterMode.HighResolution)
        pr.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        pr.setOutputFileName(p)
        pr.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A5), QPageLayout.Orientation.Portrait,
                                     QMarginsF(18, 18, 18, 18), QPageLayout.Unit.Millimeter))
        doc.print(pr)
        self.sein.status.emit("PDF gemaakt: %s" % p)
        try:
            os.startfile(p)
        except Exception:
            pass

    # ---- overig
    def instellingen(self):
        stemmen = getattr(self.stem, "stemmen", None) if self.stem else None
        d = Instellingen(self, self.cfg, stemmen)
        if d.exec():
            self.cfg.update(d.waarden())
            bewaar_cfg(self.cfg)
            self._stijl()
            if self.stem:
                self.stem.kies_stem(self.cfg["stem"])
                self.stem.snelheid = float(self.cfg["snelheid"])
                self.stem.taal = self.cfg["taal"]
            if self.oren:
                self.oren.grootte = self.cfg["whisper"]
                self.oren.taal = self.cfg["taal"]

    def snelgids(self):
        p = bron("DraveSchrijf-Snelgids.pdf")
        if os.path.exists(p):
            os.startfile(p)
        else:
            QMessageBox.information(self, "Snelgids", "Typ gewoon, alles wordt vanzelf bewaard.\n\n"
                                    "F2 ingedrukt houden = inspreken.\nF5 = voorlezen, Esc = stoppen.\n"
                                    "F11 = focus (alleen tekst).\nCtrl+Shift+N = nieuw hoofdstuk.")

    def closeEvent(self, ev):
        self.bewaar()
        self.stil()
        ev.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAAM)
    w = Schrijf()
    w.show()
    try:  # Dravenlock: stille update-check (uit te zetten; Ctrl+Shift+U = met de hand)
        import drave_update
        drave_update.start(w, "DraveSchrijf", APP_VERSION)
    except Exception:
        pass
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
