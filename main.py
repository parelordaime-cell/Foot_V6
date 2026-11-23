# -*- coding: utf-8 -*-
"""Demarrage de FOOT V6.0 : ne contient ni moteur ni ecrans."""
import os
from kivy.app import App
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.properties import StringProperty
from kivy.uix.screenmanager import ScreenManager


class FootApp(App):
    etat = StringProperty("État du moteur : prêt")

    def build(self):
        # Les fichiers de donnees vont dans le dossier prive de l'application
        os.environ["FOOT_DATA_DIR"] = self.user_data_dir
        try:  # certificats HTTPS sur Android
            import certifi
            os.environ["SSL_CERT_FILE"] = certifi.where()
        except ImportError:
            pass
        import screens  # importe apres FOOT_DATA_DIR
        Window.clearcolor = (0.04, 0.06, 0.09, 1)
        Builder.load_string(screens.KV)
        self.sm = ScreenManager()
        for nom, cls in (("accueil", screens.Accueil), ("console", screens.Console),
                         ("journal", screens.Journal), ("params", screens.Params)):
            self.sm.add_widget(cls(name=nom))
        return self.sm

    def aller(self, nom):
        self.sm.current = nom

    def lancer(self, mode):
        self.sm.current = "console"
        self.sm.get_screen("console").demarrer(mode)


if __name__ == "__main__":
    FootApp().run()
