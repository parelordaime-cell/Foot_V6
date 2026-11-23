# -*- coding: utf-8 -*-
"""Validation des donnees : l'indisponibilite n'est jamais une validation."""
from datetime import datetime

CONFIRMEE_SOURCE = "confirmee_par_source"
VERIFIEE_MANUEL = "verifiee_manuellement"
NON_VERIFIEE = "non_verifiee"


def etat_absences(source_disponible, confirmee_par_toi, saisie_ou_aucun_verifie):
    """Les 3 etats possibles des absences.
    source_disponible : une API a renvoye des absences pour ce match
    confirmee_par_toi : tu as confirme la liste de la source
    saisie_ou_aucun_verifie : tu as saisi les absents, ou verifie qu'il n'y en a aucun"""
    if source_disponible:
        return CONFIRMEE_SOURCE if confirmee_par_toi else NON_VERIFIEE
    return VERIFIEE_MANUEL if saisie_ou_aucun_verifie else NON_VERIFIEE


def absences_valides(etat):
    return etat in (CONFIRMEE_SOURCE, VERIFIEE_MANUEL)


def penalite_confiance(etat):
    return 0 if absences_valides(etat) else 1


def est_frais(horodatage_iso, max_heures=6):
    """Une donnee collectee il y a plus de max_heures n'est plus fraiche."""
    try:
        age = datetime.now() - datetime.fromisoformat(horodatage_iso)
    except (TypeError, ValueError):
        return False
    return age.total_seconds() <= max_heures * 3600


def equipes_identifiees(dom, ext):
    """Verifie que les deux equipes ont un identifiant (pas seulement un nom)."""
    return bool(dom and ext and dom.get("id") and ext.get("id") and dom["id"] != ext["id"])
