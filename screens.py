# -*- coding: utf-8 -*-
"""Ecrans de FOOT V6.0 : accueil, console du moteur, journal, parametres."""
import threading, queue
from kivy.clock import Clock
from kivy.properties import StringProperty
from kivy.uix.screenmanager import Screen
import engine
import journal

KV = """
#:set BG (0.10, 0.14, 0.21, 1)
#:set VERT (0.2, 0.75, 0.65, 1)
<Tuile@Button>:
    background_normal: ''
    background_color: BG
    bold: True
    font_size: '15sp'
<Nav@BoxLayout>:
    size_hint_y: None
    height: '52dp'
    spacing: '4dp'
    padding: '4dp'
    Button:
        text: 'ACCUEIL'
        on_release: app.aller('accueil')
    Button:
        text: 'MATCHS'
        on_release: app.lancer('1')
    Button:
        text: 'DIRECT'
        on_release: app.lancer('0')
    Button:
        text: 'JOURNAL'
        on_release: app.aller('journal')

<Accueil>:
    BoxLayout:
        orientation: 'vertical'
        padding: '12dp'
        spacing: '10dp'
        Label:
            text: 'FOOT  V6.0'
            font_size: '30sp'
            bold: True
            color: VERT
            size_hint_y: None
            height: '60dp'
        Label:
            text: 'Un moteur rigoureux. Des données contrôlées.\\nAucune recommandation sans validation.'
            halign: 'center'
            color: 0.6, 0.67, 0.78, 1
            size_hint_y: None
            height: '60dp'
        GridLayout:
            cols: 2
            spacing: '10dp'
            Tuile:
                text: 'MATCHS DU JOUR'
                on_release: app.lancer('1')
            Tuile:
                text: 'MODE DIRECT'
                on_release: app.lancer('0')
            Tuile:
                text: 'ANALYSE'
                on_release: app.lancer('1')
            Tuile:
                text: 'COMPARATEUR'
                on_release: app.aller('journal')
            Tuile:
                text: 'JOURNAL'
                on_release: app.aller('journal')
            Tuile:
                text: 'PARAMÈTRES'
                on_release: app.aller('params')
        Label:
            text: app.etat
            color: 1, 0.7, 0.2, 1
            size_hint_y: None
            height: '48dp'
        Nav:

<Console>:
    BoxLayout:
        orientation: 'vertical'
        ScrollView:
            id: sv
            Label:
                id: sortie
                text: ''
                markup: False
                size_hint_y: None
                height: self.texture_size[1]
                text_size: self.width, None
                halign: 'left'
                valign: 'top'
                padding: '8dp', '8dp'
        BoxLayout:
            size_hint_y: None
            height: '48dp'
            TextInput:
                id: saisie
                multiline: False
                hint_text: 'Ta réponse puis Envoyer'
                on_text_validate: root.envoyer()
            Button:
                text: 'Envoyer'
                size_hint_x: None
                width: '90dp'
                on_release: root.envoyer()
        Nav:

<Journal>:
    BoxLayout:
        orientation: 'vertical'
        ScrollView:
            Label:
                id: contenu
                text: root.texte
                size_hint_y: None
                height: self.texture_size[1]
                text_size: self.width, None
                padding: '8dp', '8dp'
        Nav:

<Params>:
    BoxLayout:
        orientation: 'vertical'
        padding: '12dp'
        Label:
            text: root.texte
            text_size: self.width, None
            halign: 'left'
            valign: 'top'
        Nav:
"""


class Accueil(Screen):
    pass


class Journal(Screen):
    texte = StringProperty("")

    def on_pre_enter(self):
        journal.importer_csv()
        perf = journal.performance()
        if perf["n"]:
            tete = "Performance réelle : %d analyses | réussite %.1f %% | ROI %.1f %%\n\n" % (
                perf["n"], perf["reussite_pct"], perf["roi_pct"])
        else:
            tete = "Performance réelle : pas encore de résultat connu.\n\n"
        out = []
        for r in journal.dernieres(30):
            out.append("%s | %s - %s\n  %s | confiance %s | résultat : %s\n" % (
                r["date_match"], r["domicile"], r["exterieur"], r["decision"],
                r["confiance"], r["resultat"] or "en attente"))
        self.texte = tete + ("\n".join(out) or "Journal vide.")


class Params(Screen):
    texte = StringProperty("")

    def on_pre_enter(self):
        self.texte = ("Configuration : %s\n\nLes clés API sont demandées par le moteur au premier "
                      "lancement (écran Analyse). Elles sont stockées dans ce fichier ; ne le partage pas.\n\n"
                      "Absences : 3 états (confirmées par une source / vérifiées à la main / "
                      "NON VÉRIFIÉES). L'indisponibilité n'est jamais une validation.\n\n"
                      "Backtest : réglages choisis sur 60 %% des matchs, validés sur les 40 %% "
                      "les plus récents." % engine.FICHIER_CONFIG)


class Console(Screen):
    """Fait tourner le moteur dans un thread ; print -> écran, input -> champ de saisie."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.entrees = queue.Queue()
        self.attente = False
        self.thread = None

    def ecrire(self, txt):
        def f(dt):
            self.ids.sortie.text += txt
            self.ids.sv.scroll_y = 0
        Clock.schedule_once(f)

    def demarrer(self, premier):
        if self.thread and self.thread.is_alive():
            return
        self.ids.sortie.text = ""
        self.entrees = queue.Queue()
        if premier is not None:
            self.entrees.put(premier)  # répond d'avance au menu 0/1

        def mon_print(*a, **k):
            self.ecrire(k.get("sep", " ").join(str(x) for x in a) + k.get("end", "\n"))

        def mon_input(invite=""):
            self.ecrire(str(invite))
            self.attente = True
            rep = self.entrees.get()
            self.attente = False
            self.ecrire(rep + "\n")
            return rep

        engine.print, engine.input = mon_print, mon_input

        def run():
            try:
                engine.principal()
            except SystemExit as e:
                mon_print(e)
            except Exception as e:
                mon_print("Erreur :", e)
            mon_print("\n[Terminé]")
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def envoyer(self):
        t = self.ids.saisie.text
        self.ids.saisie.text = ""
        self.entrees.put(t)
