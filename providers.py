# -*- coding: utf-8 -*-
"""Point d'entree unique vers les sources de donnees.
Pour l'instant ces fonctions appellent le moteur ; on deplacera le code
des API (football-data.org, ESPN, API-Football, The Odds API) ici ensuite."""
import engine


def charger_config():
    return engine.charger_config()


def matchs_en_direct():
    return engine.charger_matchs_en_direct()


def absences(cle_api_football, code, annee, date_match, dom, ext):
    return engine.absences_auto(cle_api_football, code, annee, date_match, dom, ext)
