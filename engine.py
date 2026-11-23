# -*- coding: utf-8 -*-
# ============================================================
# FOOT V6.0 - moteur d'analyse enrichi avec mode match en direct
# Tu ne donnes que : le championnat, la date, le match, ta
# confirmation des absences trouvees, et les 3 cotes.
# Tout le reste est recherche et calcule par le script.
#
# V6.0 : absences en 3 etats + backtest chronologique (choix 60 % / test 40 %)
# Nouveautes V5.5 :
# - Detection automatique des matchs en direct (IN_PLAY / PAUSED) et
#   affichage des informations/scores en direct disponibles (ESPN / statut)
# - Proposition rapide d'utiliser les cotes moyennes du marche en direct
# - Conservation de toutes les fonctions V5.4 :
#   * Buts attendus par equipe et total du match (bruts & ajustes)
#   * Estimations attendues par equipe et total match : corners, fautes,
#     cartons jaunes et cartons rouges
#   * Journal CSV enrichi et mise a jour automatique des resultats
# ============================================================
import urllib.request, urllib.error, urllib.parse, json, time, unicodedata, csv, os, gzip
from math import exp
from datetime import date, datetime, timedelta

# Dossier des donnees : fourni par main.py (FOOT_DATA_DIR), sinon <projet>/data
try:
    _RACINE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _RACINE = os.getcwd()
DOSSIER = os.environ.get("FOOT_DATA_DIR") or os.path.join(_RACINE, "data")
os.makedirs(DOSSIER, exist_ok=True)
FICHIER_CONFIG = os.path.join(DOSSIER, "foot_config.json")
FICHIER_JOURNAL = os.path.join(DOSSIER, "foot_journal.csv")

CLE_FD = ""

# ---------- reglages du modele (choisis par le backtest) ----------
DEMI_VIES = (90, 200)    # jours : un match perd la moitie de son poids
PRIORS = (2.0, 4.0, 8.0) # force du lissage vers la moyenne du championnat
MODES = ("split", "global")  # domicile/exterieur separes, ou force globale
RHOS = (0.0, -0.05, -0.10, -0.15)   # correction Dixon-Coles
GAMMAS = (1.0, 1.15, 1.3, 1.5, 1.7)  # nettete : accentue favoris/outsiders si le backtest le prefere
GRILLE = 9               # scores de 0 a 8 buts par equipe
HIST_MIN = 80
TESTS_MAX = 400
TESTS_MIN_VALID = 100
MARGE_BRIER = 0.002
CALIB_MAX = 0.05
MELANGE_MODELE = 0.5     # part du modele dans le melange modele + marche
DIVERGENCE_MAX = 10.0    # ecart max modele/marche (points de %)
SEUIL_VALUE = 3.0
SEUIL_VALUE_SANS_MARCHE = 6.0
MAX_MAJ_JOURNAL = 4

# ---------- reglages absences (impact controle sur lambda) ----------
PENALITE_ABS_ATT = 0.035  # -3.5 % sur l'attaque par absent confirme (plafonne)
BONUS_ABS_DEF = 0.025     # +2.5 % buts encaisses attendus si l'adversaire a des absents
PLAFOND_IMP_ABS = 0.15    # impact maximal borne a +-15 % par equipe

# ---------- baselines statistiques secondaires (par equipe / match) ----------
BASE_CORNERS_DOM = 5.4
BASE_CORNERS_EXT = 4.4
BASE_FAUTES_DOM = 11.4
BASE_FAUTES_EXT = 12.1
BASE_JAUNES_DOM = 1.95
BASE_JAUNES_EXT = 2.15
BASE_ROUGES_DOM = 0.08
BASE_ROUGES_EXT = 0.10

ESPN = {"FL1": "fra.1", "PL": "eng.1", "PD": "esp.1", "SA": "ita.1",
        "BL1": "ger.1", "DED": "ned.1", "PPL": "por.1", "ELC": "eng.2",
        "CL": "uefa.champions", "BSA": "bra.1", "EC": "uefa.euro",
        "WC": "fifa.world"}

ODDS_SPORTS = {"FL1": "soccer_france_ligue_one", "PL": "soccer_epl",
               "PD": "soccer_spain_la_liga", "SA": "soccer_italy_serie_a",
               "BL1": "soccer_germany_bundesliga",
               "DED": "soccer_netherlands_eredivisie",
               "PPL": "soccer_portugal_primeira_liga",
               "ELC": "soccer_efl_champ", "CL": "soccer_uefa_champs_league",
               "BSA": "soccer_brazil_campeonato",
               "EC": "soccer_uefa_european_championship",
               "WC": "soccer_fifa_world_cup"}

APIF_LIGUES = {"FL1": 61, "PL": 39, "PD": 140, "SA": 135, "BL1": 78,
               "DED": 88, "PPL": 94, "ELC": 40, "CL": 2, "BSA": 71,
               "EC": 4, "WC": 1}

SECOURS = [("FL1", "France - Ligue 1"), ("PL", "Angleterre - Premier League"),
           ("PD", "Espagne - Liga"), ("SA", "Italie - Serie A"),
           ("BL1", "Allemagne - Bundesliga"), ("DED", "Pays-Bas - Eredivisie"),
           ("PPL", "Portugal - Primeira Liga"),
           ("ELC", "Angleterre - Championship"),
           ("CL", "Ligue des Champions"), ("BSA", "Bresil - Serie A")]

OK, PART, NON = "VALIDATION TOTALE", "VALIDATION PARTIELLE", "ABSENCE DE VALIDATION"

CHAMPS_JOURNAL = ["horodatage", "code", "match_id", "date_match", "domicile",
                  "exterieur", "absents_domicile", "absents_exterieur",
                  "buts_att_dom", "buts_att_ext", "buts_att_total",
                  "corners_att_dom", "corners_att_ext", "corners_att_total",
                  "fautes_att_dom", "fautes_att_ext", "fautes_att_total",
                  "jaunes_att_dom", "jaunes_att_ext", "jaunes_att_total",
                  "rouges_att_dom", "rouges_att_ext", "rouges_att_total",
                  "p1", "pN", "p2", "pm1", "pmN", "pm2",
                  "cote1", "coteN", "cote2", "selection", "cote_selection",
                  "cote_plancher", "value_pct", "decision", "confiance", "resultat"]



# ---------- recherche de poste et calcul de poids par joueur absent ----------
POSTES_POIDS = {
    "GK": 1.35, "G": 1.35, "GARDIEN": 1.35, "GOALKEEPER": 1.35,
    "CB": 1.15, "DEF": 1.15, "DEFENSEUR": 1.15, "DEFENDER": 1.15,
    "LB": 1.05, "RB": 1.05, "LWB": 1.05, "RWB": 1.05,
    "CDM": 1.20, "CM": 1.15, "MID": 1.15, "MILIEU": 1.15, "MIDFIELDER": 1.15,
    "CAM": 1.25, "LW": 1.20, "RW": 1.20,
    "ST": 1.35, "CF": 1.35, "FWD": 1.30, "ATTAQUANT": 1.30, "FORWARD": 1.30, "STRIKER": 1.35,
}

_cache_poste_joueur = {}


def _detecter_poste_texte(txt):
    t = (txt or "").upper()
    if any(w in t for w in ("GOALKEEPER", "GARDIEN", "GK")):
        return "GK", POSTES_POIDS["GK"]
    if any(w in t for w in ("CENTRE-BACK", "CENTER BACK", "CB")):
        return "CB", POSTES_POIDS["CB"]
    if any(w in t for w in ("LEFT-BACK", "RIGHT-BACK", "FULL-BACK", "LB", "RB", "WB")):
        return "LAT", 1.05
    if any(w in t for w in ("DEFENSIVE MIDFIELD", "CDM")):
        return "CDM", POSTES_POIDS["CDM"]
    if any(w in t for w in ("ATTACKING MIDFIELD", "CAM", "WINGER", "LW", "RW")):
        return "ATT_MIL", 1.20
    if any(w in t for w in ("MIDFIELDER", "MIDFIELD", "MILIEU", "CM")):
        return "MID", POSTES_POIDS["MID"]
    if any(w in t for w in ("CENTRE-FORWARD", "CENTER FORWARD", "STRIKER", "ST", "CF")):
        return "ST", POSTES_POIDS["ST"]
    if any(w in t for w in ("FORWARD", "ATTAQUANT", "FWD")):
        return "FWD", POSTES_POIDS["FWD"]
    if any(w in t for w in ("DEFENDER", "DEFENSEUR", "DEF")):
        return "DEF", POSTES_POIDS["DEF"]
    return None, None


def rechercher_poste_joueur(nom_joueur, nom_equipe=""):
    """Recherche le poste d'un joueur via ESPN / Wikipedia / TheSportsDB ou syntaxe 'Nom (poste)'.
    Retourne (poste_code, poids_joueur, source_info)."""
    raw = (nom_joueur or "").strip()
    if not raw:
        return "INCONNU", 1.0, "aucun"

    # Si l'utilisateur ecrit par ex. "Saka (ATT)" ou "Rodri - MIL"
    if "(" in raw and ")" in raw:
        inside = raw[raw.find("(") + 1:raw.rfind(")")].strip()
        p_code, p_w = _detecter_poste_texte(inside)
        if p_code:
            return p_code, p_w, "saisie"

    cle_cache = (norm(raw), norm(nom_equipe))
    if cle_cache in _cache_poste_joueur:
        return _cache_poste_joueur[cle_cache]

    # 1) Recherche rapide sur Wikipedia (FR puis EN)
    for lang in ("fr", "en"):
        try:
            q = urllib.parse.quote(raw + (" " + nom_equipe if nom_equipe else ""))
            url = ("https://%s.wikipedia.org/w/api.php?action=query&list=search"
                   "&srsearch=%s&format=json&srlimit=2" % (lang, q))
            data = http(url, essais=1)
            hits = ((data.get("query") or {}).get("search")) or []
            for h in hits:
                snippet = h.get("snippet", "")
                p_code, p_w = _detecter_poste_texte(snippet)
                if p_code:
                    res = (p_code, p_w, "wikipedia:" + lang)
                    _cache_poste_joueur[cle_cache] = res
                    return res
                titre = h.get("title", "")
                if titre:
                    s_url = ("https://%s.wikipedia.org/w/api.php?action=query&prop=extracts"
                             "&exintro=1&explaintext=1&titles=%s&format=json"
                             % (lang, urllib.parse.quote(titre)))
                    s_data = http(s_url, essais=1)
                    pages = ((s_data.get("query") or {}).get("pages")) or {}
                    for _, pg in pages.items():
                        ext_txt = (pg.get("extract") or "")[:500]
                        p_code, p_w = _detecter_poste_texte(ext_txt)
                        if p_code:
                            res = (p_code, p_w, "wikipedia:" + lang)
                            _cache_poste_joueur[cle_cache] = res
                            return res
        except Exception:
            continue

    # 2) Recherche sur TheSportsDB (cle publique de test '3')
    try:
        q_tsdb = urllib.parse.quote(raw)
        tsdb = http("https://www.thesportsdb.com/api/v1/json/3/searchplayers.php?p=" + q_tsdb, essais=1)
        for pl in (tsdb.get("player") or []):
            if (pl.get("strSport") or "").lower() == "soccer":
                pos_txt = pl.get("strPosition") or ""
                p_code, p_w = _detecter_poste_texte(pos_txt)
                if p_code:
                    res = (p_code, p_w, "thesportsdb")
                    _cache_poste_joueur[cle_cache] = res
                    return res
    except Exception:
        pass

    res = ("INCONNU", 1.0, "defaut")
    _cache_poste_joueur[cle_cache] = res
    return res


def evaluer_absents_avec_postes(liste_noms, nom_equipe):
    """Retourne (poids_total_eq, details_liste, texte_resume)."""
    if not liste_noms:
        return 0.0, [], "aucun (verifie)"
    total = 0.0
    details = []
    morceaux = []
    for item in liste_noms:
        doute = ("doute" in item.lower() or "incertain" in item.lower() or "?" in item)
        fact_doute = 0.4 if doute else 1.0
        poste, poids_poste, src = rechercher_poste_joueur(item, nom_equipe)
        poids_final = round(fact_doute * poids_poste, 2)
        total += poids_final
        details.append({
            "joueur": item,
            "poste": poste,
            "poids_poste": poids_poste,
            "doute": doute,
            "poids_match": poids_final,
            "source": src,
        })
        tag_doute = " [doute]" if doute else ""
        morceaux.append("%s (%s, poids %.2f%s)" % (item, poste, poids_final, tag_doute))
    return round(total, 2), details, ", ".join(morceaux)

# ============================================================
# CONFIGURATION ET CLES
# ============================================================
def tester_odds(cle):
    """True = valide, False = refusee, None = impossible a tester."""
    try:
        data = http("https://api.the-odds-api.com/v4/sports/?apiKey=" + cle, essais=1)
        return isinstance(data, list)
    except Exception as e:
        return False if ("HTTP 401" in str(e) or "HTTP 403" in str(e)) else None


def tester_apif(cle):
    try:
        data = http("https://v3.football.api-sports.io/status",
                    {"x-apisports-key": cle, "User-Agent": "Mozilla/5.0"}, essais=1)
    except Exception as e:
        return False if ("HTTP 401" in str(e) or "HTTP 403" in str(e)) else None
    err = data.get("errors")
    if err:
        return False if ("token" in str(err).lower() or "key" in str(err).lower()) else None
    return bool(data.get("response"))


NOMS_CLES = {"the_odds_api": "The Odds API", "api_football": "API-Football"}


def verifier_cles(cfg):
    """Teste les cles facultatives, repere une cle football-data collee par
    erreur, et remet une cle collee au mauvais endroit (ou inversee).
    Retourne (valide, modifie)."""
    valide = {"the_odds_api": tester_odds(cfg["the_odds_api"]) if cfg["the_odds_api"] else None,
              "api_football": tester_apif(cfg["api_football"]) if cfg["api_football"] else None}
    modif = False
    for cle, nom in NOMS_CLES.items():
        if cfg[cle] and cfg[cle] == cfg["football_data"]:
            print("La cle collee pour", nom, "est ta cle football-data : ce n'est pas la bonne.")
            valide[cle] = False

    odds, apif = cfg["the_odds_api"], cfg["api_football"]
    x_est_apif = (valide["the_odds_api"] is False and odds and odds != cfg["football_data"]
                  and tester_apif(odds) is True)
    y_est_odds = (valide["api_football"] is False and apif and apif != cfg["football_data"]
                  and tester_odds(apif) is True)
    if x_est_apif and y_est_odds:
        cfg["the_odds_api"], cfg["api_football"] = apif, odds
        valide = {"the_odds_api": True, "api_football": True}
        modif = True
        print("Les deux cles etaient inversees : corrige automatiquement.")
    elif x_est_apif and valide["api_football"] is not True:
        cfg["api_football"], cfg["the_odds_api"] = odds, ""
        valide = {"the_odds_api": None, "api_football": True}
        modif = True
        print("La cle collee pour The Odds API etait celle d'API-Football : deplacee automatiquement.")
    elif y_est_odds and valide["the_odds_api"] is not True:
        cfg["the_odds_api"], cfg["api_football"] = apif, ""
        valide = {"the_odds_api": True, "api_football": None}
        modif = True
        print("La cle collee pour API-Football etait celle de The Odds API : deplacee automatiquement.")
    return valide, modif


def afficher_etat_cles(cfg, valide):
    etat = ["football-data OK"]
    for cle, nom in NOMS_CLES.items():
        if not cfg[cle]:
            etat.append(nom + " MANQUANTE")
        elif valide[cle] is False:
            etat.append(nom + " INVALIDE (refusee par le service)")
        else:
            etat.append(nom + " OK")
    print("CLES :", " | ".join(etat))


def charger_config():
    """Cles lues dans foot_config.json. Le script teste chaque cle, dit
    lesquelles manquent ou sont refusees, et te laisse les recoller."""
    try:
        with open(FICHIER_CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}

    def propre(v):
        return str(v or "").strip().strip("\"'").strip()

    modif = False
    val = propre(cfg.get("football_data"))
    if not val or "COLLE" in val:
        val = propre(input("Cle football-data.org (obligatoire) : "))
        modif = True
    if not val:
        raise SystemExit("Cle football-data.org obligatoire.")
    cfg["football_data"] = val
    for cle in NOMS_CLES:
        cfg[cle] = propre(cfg.get(cle))

    valide, m = verifier_cles(cfg)
    modif = modif or m
    afficher_etat_cles(cfg, valide)

    roles = {"the_odds_api": "cotes moyennes du marche", "api_football": "absences automatiques"}
    colle = False
    for cle, nom in NOMS_CLES.items():
        if cfg[cle] and valide[cle] is not False:
            continue
        v = propre(input("Colle la cle " + nom + " (" + roles[cle] + ") - Entree = plus tard : "))
        if v:
            cfg[cle] = v
            colle = modif = True
        elif valide[cle] is False:
            cfg[cle] = ""
            modif = True
    if colle:
        valide, m = verifier_cles(cfg)
        modif = modif or m
        for cle, nom in NOMS_CLES.items():
            if cfg[cle] and valide[cle] is False:
                print("Cle", nom, "refusee par le service : elle n'est pas enregistree.")
                cfg[cle] = ""
        afficher_etat_cles(cfg, valide)
    if modif:
        try:
            with open(FICHIER_CONFIG, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            print("Cles enregistrees dans", FICHIER_CONFIG)
        except Exception as e:
            print("Enregistrement des cles impossible :", e)
    return cfg


# ============================================================
# OUTILS
# ============================================================
def _lire_corps(r):
    brut = r.read()
    if brut[:2] == b"\x1f\x8b":
        try:
            brut = gzip.decompress(brut)
        except Exception:
            pass
    return brut.decode("utf-8", "ignore")


def http(url, entetes=None, essais=2):
    h = dict(entetes) if entetes else {"User-Agent": "Mozilla/5.0"}
    h.setdefault("Accept-Encoding", "identity")
    req = urllib.request.Request(url, headers=h)
    for essai in range(essais):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(_lire_corps(r))
        except urllib.error.HTTPError as e:
            corps = _lire_corps(e)
            if e.code == 429 and essai < essais - 1:
                print("Limite de requetes atteinte, attente 20 s...")
                time.sleep(20)
                continue
            raise Exception("HTTP " + str(e.code) + " : " + corps[:200])
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if essai < essais - 1:
                time.sleep(2)
                continue
            raise Exception("Reseau : " + str(e))


_appels_fd = []


def fd(chemin):
    """football-data.org, avec respect de la limite de 10 requetes/minute."""
    maintenant = time.time()
    _appels_fd[:] = [t for t in _appels_fd if maintenant - t < 61]
    if len(_appels_fd) >= 9:
        attente = 61 - (maintenant - _appels_fd[0])
        print("Pause de", int(attente) + 1, "s (limite de l'API)...")
        time.sleep(max(0, attente))
    _appels_fd.append(time.time())
    return http("https://api.football-data.org/v4" + chemin,
                {"X-Auth-Token": CLE_FD, "User-Agent": "Mozilla/5.0"})


STOP = {"fc", "afc", "cf", "sc", "ac", "as", "ssc", "rc", "de", "club",
        "calcio", "1", "fk", "sv", "ud", "cd"}
MOTS = {"munchen": "munich", "milano": "milan", "internazionale": "inter",
        "saint": "st", "utd": "united"}


def norm(nom):
    n = unicodedata.normalize("NFD", nom.lower())
    n = "".join(c for c in n if unicodedata.category(c) != "Mn")
    n = n.replace("-", " ").replace(".", " ").replace("&", " and ")
    mots = [MOTS.get(m, m) for m in n.split() if m not in STOP]
    n = " ".join(mots)
    return n.replace("wolverhampton wanderers", "wolves")


def meme(a, b):
    """Meme equipe : noms identiques, ou les mots de l'un inclus dans l'autre
    (Celta = Celta Vigo), mais jamais Team1 = Team16."""
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    ta, tb = set(na.split()), set(nb.split())
    return ta <= tb or tb <= ta


def trouver_nom(dictionnaire, nom):
    """Cherche une equipe par son nom : egalite exacte d'abord, puis inclusion."""
    n = norm(nom)
    for cle in dictionnaire:
        if norm(cle) == n:
            return cle
    for cle in dictionnaire:
        if meme(cle, nom):
            return cle
    return None


def correspond(e, d, h, a):
    """Un evenement ESPN correspond au match si la date est la meme et si
    au moins une des deux equipes porte le meme nom."""
    return e["date"] == d and (meme(e["home"], h) or meme(e["away"], a))


def deux_sources(src):
    return len({s.lower() for s in src if s}) >= 2


def nombre(txt):
    try:
        return float(txt.replace(",", ".").strip())
    except ValueError:
        return None


def oui(question, defaut=False):
    reponse = input(question + (" (O/n) : " if defaut else " (o/n) : "))
    reponse = reponse.strip().lower()
    if reponse == "":
        return defaut
    return reponse.startswith("o")


def lire_date(texte):
    ch = "".join(c for c in texte if c.isdigit())
    if ch == "":
        return date.today()
    if len(ch) == 8:
        return datetime.strptime(ch, "%d%m%Y").date()
    if len(ch) == 6:
        return datetime.strptime(ch, "%d%m%y").date()
    raise ValueError("Date invalide. Exemple : 21112026")


def est_en_direct(match_obj):
    return match_obj.get("status") in ("IN_PLAY", "PAUSED")


def info_direct_espn(ev_futurs, d, h, a):
    for e in ev_futurs:
        if correspond(e, d, h, a):
            return e
    return None


# ============================================================
# SOURCES : football-data (1), ESPN (2)
# ============================================================

def charger_matchs_en_direct():
    """Recupere tous les matchs actuellement en direct (IN_PLAY / PAUSED) sur football-data.org."""
    try:
        data = fd("/matches?status=IN_PLAY,PAUSED")
        matchs = data.get("matches", [])
    except Exception:
        # Certaines versions de l'API preferent deux appels ou status=LIVE
        matchs = []
        for st in ("IN_PLAY", "PAUSED"):
            try:
                d = fd("/matches?status=" + st)
                matchs.extend(d.get("matches", []))
            except Exception:
                pass
    vus = set()
    uniques = []
    for m in matchs:
        mid = m.get("id")
        if mid and mid not in vus and (m.get("homeTeam") or {}).get("id") and (m.get("awayTeam") or {}).get("id"):
            vus.add(mid)
            uniques.append(m)
    uniques.sort(key=lambda x: ((x.get("competition") or {}).get("name", ""), x.get("utcDate", "")))
    return uniques


def charger_championnats():
    try:
        data = fd("/competitions")
        liste = [(c["code"], c.get("area", {}).get("name", "") + " - " + c["name"])
                 for c in data.get("competitions", [])]
        liste.sort(key=lambda x: x[1])
        if liste:
            return liste
    except Exception as e:
        print("Liste API indisponible :", e)
    return SECOURS


def score_90(m):
    """Score apres 90 minutes (regularTime si prolongation, sinon fullTime)."""
    s = m.get("score") or {}
    for cle in ("regularTime", "fullTime"):
        v = s.get(cle) or {}
        if v.get("home") is not None and v.get("away") is not None:
            return v["home"], v["away"]
    return None


def normaliser(m):
    if m.get("status") != "FINISHED":
        return None
    sc = score_90(m)
    h, a = m.get("homeTeam") or {}, m.get("awayTeam") or {}
    if sc is None or h.get("id") is None or a.get("id") is None:
        return None
    return {"id": m["id"], "date": m["utcDate"][:10],
            "jour": date.fromisoformat(m["utcDate"][:10]).toordinal(),
            "h_id": h["id"], "a_id": a["id"],
            "h": h.get("name", ""), "a": a.get("name", ""),
            "gh": sc[0], "ga": sc[1]}


def charger_matchs(code):
    """Saison en cours + saison precedente (si l'offre le permet)."""
    info = fd("/competitions/" + code)
    debut = ((info.get("currentSeason") or {}).get("startDate") or "")[:4]
    annee = int(debut) if debut.isdigit() else date.today().year
    tous = fd("/competitions/%s/matches?season=%d" % (code, annee)).get("matches", [])
    try:
        prec = fd("/competitions/%s/matches?season=%d" % (code, annee - 1)).get("matches", [])
        tous = prec + tous
    except Exception as e:
        print("Saison precedente indisponible (offre gratuite ?) :", e)
    return annee, tous


def mois_entre(d1, d2):
    """Liste des mois AAAAMM couvrant d1..d2 (ESPN refuse les plages avec tiret)."""
    mois = []
    d = date(d1.year, d1.month, 1)
    while d <= d2:
        mois.append(d.strftime("%Y%m"))
        d = date(d.year + (1 if d.month == 12 else 0), d.month % 12 + 1, 1)
    return mois


_cache_espn = {}


def espn_evenements(slug, d1, d2):
    """Matchs ESPN entre d1 et d2, demandes mois par mois."""
    sortie = []
    for mois in mois_entre(d1 - timedelta(days=1), d2 + timedelta(days=1)):
        cle = (slug, mois)
        if cle not in _cache_espn:
            url = ("https://site.api.espn.com/apis/site/v2/sports/soccer/" + slug +
                   "/scoreboard?dates=" + mois + "&limit=1000")
            try:
                data = http(url)
            except Exception as e:
                print("ESPN indisponible :", e)
                return sortie
            evs = []
            for e in data.get("events", []):
                try:
                    comp = e["competitions"][0]
                    dom = ext = None
                    for c in comp["competitors"]:
                        if c["homeAway"] == "home":
                            dom = c
                        else:
                            ext = c
                    st_type = (e.get("status") or {}).get("type") or {}
                    evs.append({
                        "date": e["date"][:10],
                        "home": dom["team"]["displayName"],
                        "away": ext["team"]["displayName"],
                        "sh": int(float(dom.get("score") or 0)),
                        "sa": int(float(ext.get("score") or 0)),
                        "etat_desc": st_type.get("shortDetail") or st_type.get("detail") or "",
                        "fini": bool(st_type.get("completed"))})
                except Exception:
                    continue
            _cache_espn[cle] = evs
        sortie.extend(_cache_espn[cle])
    return sortie


def espn_classement(slug):
    res = {}
    try:
        data = http("https://site.api.espn.com/apis/site/v2/sports/soccer/" +
                    slug + "/standings")
        for e in data["children"][0]["standings"]["entries"]:
            st = {s["name"]: s.get("value") for s in e["stats"]}
            res[e["team"]["displayName"]] = st
    except Exception as e:
        print("Classement ESPN indisponible :", e)
    return res


def classement_fd(code):
    res = {}
    try:
        for bloc in fd("/competitions/%s/standings" % code).get("standings", []):
            if bloc.get("type") == "TOTAL":
                for l in bloc["table"]:
                    res[l["team"]["id"]] = l
    except Exception as e:
        print("Classement FD indisponible :", e)
    return res


# ============================================================
# VALIDATIONS & FORME (globale + domicile/exterieur)
# ============================================================
def forme_equipe(finis, id_eq, ev_espn, lieu=None, limite=5):
    """lieu = None (tous), 'H' (domicile uniquement), 'A' (exterieur uniquement)."""
    if lieu == "H":
        mes = [x for x in finis if x["h_id"] == id_eq]
    elif lieu == "A":
        mes = [x for x in finis if x["a_id"] == id_eq]
    else:
        mes = [x for x in finis if id_eq in (x["h_id"], x["a_id"])]
    mes.sort(key=lambda x: x["jour"], reverse=True)
    liste = []
    for x in mes[:limite]:
        src = ["football-data"]
        for e in ev_espn:
            if (e["fini"] and correspond(e, x["date"], x["h"], x["a"])
                    and e["sh"] == x["gh"] and e["sa"] == x["ga"]):
                src.append("espn")
                break
        gagnant = x["h"] if x["gh"] > x["ga"] else x["a"] if x["ga"] > x["gh"] else "Nul"
        est_dom = x["h_id"] == id_eq
        gf = x["gh"] if est_dom else x["ga"]
        ga = x["ga"] if est_dom else x["gh"]
        res_lettre = "V" if gf > ga else "N" if gf == ga else "D"
        liste.append({"date": x["date"],
                      "gf": gf,
                      "ga": ga,
                      "res": res_lettre,
                      "txt": "%s %s %d-%d %s (gagnant : %s)" % (
                          x["date"], x["h"], x["gh"], x["ga"], x["a"], gagnant),
                      "sources": src})
    return liste


def resume_serie(liste):
    """Synthese compacte ex: '3V-1N-1D (buts 8-4)'."""
    if not liste:
        return "aucun match"
    v = sum(1 for r in liste if r["res"] == "V")
    n = sum(1 for r in liste if r["res"] == "N")
    d = sum(1 for r in liste if r["res"] == "D")
    gf = sum(r["gf"] for r in liste)
    ga = sum(r["ga"] for r in liste)
    serie = "".join(r["res"] for r in liste)
    return "%s (%dV-%dN-%dD | buts %d-%d)" % (serie, v, n, d, gf, ga)


def statut_forme(liste):
    if len(liste) < 5:
        return NON
    dates = [r["date"] for r in liste]
    if dates != sorted(dates, reverse=True):
        return NON
    return OK if all(deux_sources(r["sources"]) for r in liste) else PART


def classement_complet(ligne_fd, st_espn, nom):
    if not ligne_fd:
        return None, NON
    src = ["football-data"]
    infos = {"rang": ligne_fd["position"], "pts": ligne_fd["points"],
             "j": ligne_fd["playedGames"], "v": ligne_fd["won"],
             "n": ligne_fd["draw"], "d": ligne_fd["lost"],
             "diff": ligne_fd["goalDifference"], "ecart": False}
    cle = trouver_nom(st_espn, nom)
    if cle is not None:
        st = st_espn[cle]
        if st.get("points") is not None and int(st["points"]) == infos["pts"]:
            src.append("espn")
        else:
            infos["ecart"] = True
    return infos, (OK if deux_sources(src) else PART)


# ============================================================
# MODELE : Poisson + poids du temps + Dixon-Coles + Absences
# ============================================================
def _nouvelle_equipe():
    return {"wH": 0.0, "gfH": 0.0, "gaH": 0.0, "nH": 0,
            "wA": 0.0, "gfA": 0.0, "gaA": 0.0, "nA": 0}


def construire_stats(hist, jour_ref, demi_vie):
    s = {"w": 0.0, "sh": 0.0, "sa": 0.0, "eq": {}}
    for x in hist:
        w = 0.5 ** (max(jour_ref - x["jour"], 0) / float(demi_vie))
        s["w"] += w
        s["sh"] += w * x["gh"]
        s["sa"] += w * x["ga"]
        d = s["eq"].setdefault(x["h_id"], _nouvelle_equipe())
        d["wH"] += w
        d["gfH"] += w * x["gh"]
        d["gaH"] += w * x["ga"]
        d["nH"] += 1
        e = s["eq"].setdefault(x["a_id"], _nouvelle_equipe())
        e["wA"] += w
        e["gfA"] += w * x["ga"]
        e["gaA"] += w * x["gh"]
        e["nA"] += 1
    if s["w"] <= 0:
        return None
    s["mh"] = s["sh"] / s["w"]
    s["ma"] = s["sa"] / s["w"]
    return s


def _taux(somme, poids, moyenne, prior):
    return (somme + prior * moyenne) / (poids + prior)


def lambdas(s, id_d, id_e, prior, mode):
    """Buts attendus (domicile, exterieur) + nb de matchs de l'echantillon."""
    if s is None or s["mh"] <= 0 or s["ma"] <= 0:
        return None
    td, te = s["eq"].get(id_d), s["eq"].get(id_e)
    if not td or not te:
        return None
    mh, ma = s["mh"], s["ma"]
    if mode == "split":
        att_d = _taux(td["gfH"], td["wH"], mh, prior)
        def_d = _taux(td["gaH"], td["wH"], ma, prior)
        att_e = _taux(te["gfA"], te["wA"], ma, prior)
        def_e = _taux(te["gaA"], te["wA"], mh, prior)
        return (att_d * def_e / mh, att_e * def_d / ma,
                min(td["nH"] + td["nA"], te["nH"] + te["nA"]))
    g = (mh + ma) / 2.0
    wd, we = td["wH"] + td["wA"], te["wH"] + te["wA"]
    a_d = _taux(td["gfH"] + td["gfA"], wd, g, prior) / g
    b_d = _taux(td["gaH"] + td["gaA"], wd, g, prior) / g
    a_e = _taux(te["gfH"] + te["gfA"], we, g, prior) / g
    b_e = _taux(te["gaH"] + te["gaA"], we, g, prior) / g
    return (mh * a_d * b_e, ma * a_e * b_d,
            min(td["nH"] + td["nA"], te["nH"] + te["nA"]))


def ajuster_lambdas_absences(ld, le, eq_abs_d, eq_abs_e):
    """Applique un ajustement borne sur les buts attendus selon les absents."""
    malus_d = min(PLAFOND_IMP_ABS, eq_abs_d * PENALITE_ABS_ATT)
    malus_e = min(PLAFOND_IMP_ABS, eq_abs_e * PENALITE_ABS_ATT)
    bonus_d = min(PLAFOND_IMP_ABS, eq_abs_e * BONUS_ABS_DEF)
    bonus_e = min(PLAFOND_IMP_ABS, eq_abs_d * BONUS_ABS_DEF)

    ld_adj = max(0.15, ld * (1.0 - malus_d) * (1.0 + bonus_d))
    le_adj = max(0.15, le * (1.0 - malus_e) * (1.0 + bonus_e))
    return ld_adj, le_adj


def estimer_stats_secondaires(ld, le, eq_abs_d, eq_abs_e, forme_d_dom, forme_e_ext):
    """Estime par equipe et sur le match : corners, fautes, cartons jaunes et rouges."""
    fact_buts_d = max(0.75, min(1.30, ld / 1.45))
    fact_buts_e = max(0.75, min(1.30, le / 1.15))

    if forme_d_dom:
        moy_gf_d = sum(x["gf"] for x in forme_d_dom) / float(len(forme_d_dom))
        fact_forme_d = max(0.80, min(1.25, 0.85 + 0.10 * moy_gf_d))
    else:
        fact_forme_d = 1.0

    if forme_e_ext:
        moy_gf_e = sum(x["gf"] for x in forme_e_ext) / float(len(forme_e_ext))
        fact_forme_e = max(0.80, min(1.25, 0.85 + 0.10 * moy_gf_e))
    else:
        fact_forme_e = 1.0

    c_dom = BASE_CORNERS_DOM * (0.65 * fact_buts_d + 0.35 * fact_forme_d) * (1.0 - min(0.12, 0.02 * eq_abs_d))
    c_ext = BASE_CORNERS_EXT * (0.65 * fact_buts_e + 0.35 * fact_forme_e) * (1.0 - min(0.12, 0.02 * eq_abs_e))

    f_dom = BASE_FAUTES_DOM * (1.0 + min(0.15, 0.03 * eq_abs_d)) * max(0.88, min(1.15, 1.06 - 0.04 * (fact_buts_d - 1.0)))
    f_ext = BASE_FAUTES_EXT * (1.0 + min(0.15, 0.03 * eq_abs_e)) * max(0.88, min(1.15, 1.06 - 0.04 * (fact_buts_e - 1.0)))

    j_dom = BASE_JAUNES_DOM * (f_dom / BASE_FAUTES_DOM) * (1.0 + min(0.15, 0.03 * eq_abs_d))
    j_ext = BASE_JAUNES_EXT * (f_ext / BASE_FAUTES_EXT) * (1.0 + min(0.15, 0.03 * eq_abs_e))

    r_dom = BASE_ROUGES_DOM * (j_dom / BASE_JAUNES_DOM)
    r_ext = BASE_ROUGES_EXT * (j_ext / BASE_JAUNES_EXT)

    return {
        "corners": (round(c_dom, 2), round(c_ext, 2), round(c_dom + c_ext, 2)),
        "fautes": (round(f_dom, 2), round(f_ext, 2), round(f_dom + f_ext, 2)),
        "jaunes": (round(j_dom, 2), round(j_ext, 2), round(j_dom + j_ext, 2)),
        "rouges": (round(r_dom, 3), round(r_ext, 3), round(r_dom + r_ext, 3)),
    }


def probas(lam_d, lam_e, rho):
    """Probabilites (1, N, 2) en fractions de 1."""
    pd, pe = [exp(-lam_d)], [exp(-lam_e)]
    for k in range(1, GRILLE):
        pd.append(pd[-1] * lam_d / k)
        pe.append(pe[-1] * lam_e / k)
    p1 = pn = p2 = 0.0
    for i in range(GRILLE):
        for j in range(GRILLE):
            p = pd[i] * pe[j]
            if i <= 1 and j <= 1:
                if i == 0 and j == 0:
                    t = 1 - lam_d * lam_e * rho
                elif i == 0 and j == 1:
                    t = 1 + lam_d * rho
                elif i == 1 and j == 0:
                    t = 1 + lam_e * rho
                else:
                    t = 1 - rho
                p *= max(t, 0.0)
            if i > j:
                p1 += p
            elif i == j:
                pn += p
            else:
                p2 += p
    tot = p1 + pn + p2
    return [p1 / tot, pn / tot, p2 / tot]


def aiguiser(p, gamma):
    q = [x ** gamma for x in p]
    t = sum(q)
    return [x / t for x in q]


def _brier(p, k):
    return sum((p[j] - (1.0 if j == k else 0.0)) ** 2 for j in range(3))


def backtest(finis):
    """Rejoue le modele sur les matchs passes (sans regarder l'avenir)
    et choisit les reglages qui predisent le mieux."""
    resultat = {"n": 0, "valide": False, "rho": -0.05, "demi_vie": 90,
                "prior": 4.0, "mode": "split", "gamma": 1.0, "b_mod": None, "b_base": None,
                "calib": None, "raison": "historique insuffisant"}
    f = sorted(finis, key=lambda x: (x["jour"], x["id"]))
    debut = max(HIST_MIN, len(f) - TESTS_MAX)
    cas = []
    for i in range(debut, len(f)):
        m = f[i]
        hist = [x for x in f[:i] if x["jour"] < m["jour"]]
        if len(hist) < HIST_MIN:
            continue
        lam, incomplet = {}, False
        for hl in DEMI_VIES:
            s = construire_stats(hist, m["jour"], hl)
            for mode in MODES:
                for prior in PRIORS:
                    r = lambdas(s, m["h_id"], m["a_id"], prior, mode)
                    if r is None or r[2] < 3:
                        incomplet = True
                        break
                    lam[(hl, mode, prior)] = (r[0], r[1])
                if incomplet:
                    break
            if incomplet:
                break
        if incomplet:
            continue
        c = [0, 0, 0]
        for x in hist:
            c[0 if x["gh"] > x["ga"] else 1 if x["gh"] == x["ga"] else 2] += 1
        nh = float(len(hist))
        cas.append({"lam": lam,
                    "res": 0 if m["gh"] > m["ga"] else 1 if m["gh"] == m["ga"] else 2,
                    "base": [c[0] / nh, c[1] / nh, c[2] / nh]})
    n = len(cas)
    if n == 0:
        return resultat

    k = int(n * 0.6)
    cas_sel, cas_test = cas[:k], cas[k:]
    if not cas_sel or not cas_test:
        return resultat
    ns = float(len(cas_sel))
    meilleur = None
    for cle in cas_sel[0]["lam"]:
        b = sum(_brier(probas(c["lam"][cle][0], c["lam"][cle][1], -0.10), c["res"])
                for c in cas_sel) / ns
        if meilleur is None or b < meilleur[0]:
            meilleur = (b, cle)
    cle = meilleur[1]
    best_rho = None
    for rho_t in RHOS:
        b = sum(_brier(probas(c["lam"][cle][0], c["lam"][cle][1], rho_t), c["res"])
                for c in cas_sel) / ns
        if best_rho is None or b < best_rho[0]:
            best_rho = (b, rho_t)
    rho = best_rho[1]
    best_g = (best_rho[0], 1.0)
    for g in GAMMAS[1:]:
        b = sum(_brier(aiguiser(probas(c["lam"][cle][0], c["lam"][cle][1], rho), g), c["res"])
                for c in cas_sel) / ns
        if b < best_g[0]:
            best_g = (b, g)
    gamma = best_g[1]
    # test final : matchs les plus recents, jamais utilises pour choisir
    cas = cas_test
    n = len(cas)
    P = []
    for c in cas:
        p = probas(c["lam"][cle][0], c["lam"][cle][1], rho)
        P.append(aiguiser(p, gamma) if gamma != 1.0 else p)
    b_mod = sum(_brier(P[x], cas[x]["res"]) for x in range(n)) / n
    b_base = sum(_brier(c["base"], c["res"]) for c in cas) / n
    moy_pred = [sum(p[j] for p in P) / n for j in range(3)]
    freq = [sum(1 for c in cas if c["res"] == j) / float(n) for j in range(3)]
    calib = max(abs(moy_pred[j] - freq[j]) for j in range(3))
    if n < TESTS_MIN_VALID:
        raison = "seulement %d matchs testables (minimum %d)" % (n, TESTS_MIN_VALID)
    elif b_mod >= b_base - MARGE_BRIER:
        raison = "le modele ne fait pas mieux que la simple frequence des resultats"
    elif calib > CALIB_MAX:
        raison = "probabilites mal calibrees (ecart %.1f points)" % (100 * calib)
    else:
        raison = "ok"
    resultat.update({"n": n, "valide": raison == "ok", "rho": rho,
                     "demi_vie": cle[0], "mode": cle[1], "prior": cle[2], "gamma": gamma,
                     "b_mod": b_mod, "b_base": b_base, "calib": calib,
                     "raison": raison})
    return resultat


# ============================================================
# MARCHE (cotes) ET ABSENCES (API-Football)
# ============================================================
def marche_depuis_cotes(cotes):
    """Probabilites du marche tirees de TES 3 cotes (marge retiree)."""
    if any(not cotes.get(k) for k in "1N2"):
        return None, None
    imp = {k: 1.0 / cotes[k] for k in "1N2"}
    s = sum(imp.values())
    return {k: imp[k] / s for k in imp}, (s - 1) * 100


def lire_marche(ev):
    """Probabilites du marche (marge retiree), moyenne des bookmakers."""
    dom, ext = ev["home_team"], ev["away_team"]
    ps, cs = [], []
    for bk in ev.get("bookmakers", []):
        for mk in bk.get("markets", []):
            if mk.get("key") != "h2h":
                continue
            prix = {}
            for o in mk.get("outcomes", []):
                if o["name"] == dom:
                    prix["1"] = o["price"]
                elif o["name"] == ext:
                    prix["2"] = o["price"]
                elif o["name"].lower() == "draw":
                    prix["N"] = o["price"]
            if len(prix) == 3 and all(v > 1 for v in prix.values()):
                imp = {k: 1.0 / v for k, v in prix.items()}
                s = sum(imp.values())
                ps.append({k: imp[k] / s for k in imp})
                cs.append(prix)
    if not ps:
        return None
    n = len(ps)
    return {"nb": n,
            "p": {k: sum(p[k] for p in ps) / n for k in "1N2"},
            "cote_moy": {k: sum(c[k] for c in cs) / n for k in "1N2"},
            "cote_max": {k: max(c[k] for c in cs) for k in "1N2"}}


def trouver_marche(cle, code, dom, ext, date_match):
    if not cle:
        return None
    sport = ODDS_SPORTS.get(code)
    if not sport:
        print("Marche (The Odds API) : championnat non couvert.")
        return None
    try:
        data = http("https://api.the-odds-api.com/v4/sports/" + sport +
                    "/odds/?apiKey=" + cle +
                    "&regions=eu,uk&markets=h2h&oddsFormat=decimal")
    except Exception as e:
        print("Marche (The Odds API) indisponible :", e)
        return None
    d0 = date.fromisoformat(date_match)
    for ev in data:
        try:
            d_ev = date.fromisoformat(ev["commence_time"][:10])
        except Exception:
            continue
        if (abs((d_ev - d0).days) <= 1 and meme(ev["home_team"], dom)
                and meme(ev["away_team"], ext)):
            return lire_marche(ev)
    print("Marche (The Odds API) : match introuvable chez les bookmakers.")
    return None


def absences_auto(cle, code, annee, date_match, dom, ext):
    """Retourne (liste_dom, liste_ext) ou None si indisponible."""
    if not cle or code not in APIF_LIGUES:
        return None
    try:
        data = http("https://v3.football.api-sports.io/injuries?league=%d&season=%d&date=%s"
                    % (APIF_LIGUES[code], annee, date_match),
                    {"x-apisports-key": cle, "User-Agent": "Mozilla/5.0"})
    except Exception as e:
        print("Absences auto indisponibles :", e)
        return None
    err = data.get("errors")
    if err:
        if isinstance(err, dict) and "plan" in err:
            print("API-Football : l'offre GRATUITE ne couvre pas la saison", annee,
                  "(il faut un abonnement payant).")
        else:
            print("Absences auto refusees par l'API :", err)
        return None
    ld, le = [], []
    for r in data.get("response", []):
        joueur = r.get("player", {})
        ligne = {"joueur": joueur.get("name", "?"),
                 "type": joueur.get("type", ""),
                 "raison": joueur.get("reason", "")}
        club = (r.get("team") or {}).get("name", "")
        if meme(club, dom):
            ld.append(ligne)
        elif meme(club, ext):
            le.append(ligne)
    return ld, le


def poids_absents_manuel(liste_noms):
    """Compte les absents confirmes (1.0) et ceux mentionnes en doute (0.4)."""
    total_eq = 0.0
    for nom in liste_noms:
        if "doute" in nom.lower() or "incertain" in nom.lower() or "?" in nom:
            total_eq += 0.4
        else:
            total_eq += 1.0
    return total_eq


# ============================================================
# JOURNAL
# ============================================================
def lire_journal():
    try:
        with open(FICHIER_JOURNAL, newline="", encoding="utf-8") as f:
            return [{k: (r.get(k) or "") for k in CHAMPS_JOURNAL}
                    for r in csv.DictReader(f)]
    except FileNotFoundError:
        return []
    except Exception as e:
        print("Journal illisible :", e)
        return []


def ecrire_journal(rows):
    try:
        with open(FICHIER_JOURNAL, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CHAMPS_JOURNAL, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow(r)
    except Exception as e:
        print("Ecriture du journal impossible :", e)


def _resultat(gh, ga):
    return "1" if gh > ga else "N" if gh == ga else "2"


def _chercher_resultat_dans_index(r, index_id, index_liste):
    """Cherche d'abord par match_id, puis par equipes + date proche."""
    try:
        mid = int(r["match_id"])
    except ValueError:
        mid = None
    if mid is not None and mid in index_id:
        x = index_id[mid]
        return _resultat(x["gh"], x["ga"])

    dom_j = r.get("domicile", "")
    ext_j = r.get("exterieur", "")
    dt_j = r.get("date_match", "")
    if not dom_j or not ext_j or not dt_j:
        return None
    try:
        j_ref = date.fromisoformat(dt_j[:10]).toordinal()
    except ValueError:
        return None

    for x in index_liste:
        if abs(x["jour"] - j_ref) <= 2 and meme(x["h"], dom_j) and meme(x["a"], ext_j):
            return _resultat(x["gh"], x["ga"])
    return None


def maj_journal(rows, index, aujourdhui, ev_espn=None):
    """Complete les resultats des matchs termines (y compris ceux du jour meme)."""
    index_liste = list(index.values()) if isinstance(index, dict) else list(index or [])
    ev_espn = ev_espn or []
    requetes = 0
    maj_count = 0
    aujourd_str = aujourdhui.isoformat()

    for r in rows:
        if r.get("resultat") in ("1", "N", "2"):
            continue
        dt_match = (r.get("date_match") or "")[:10]
        if not dt_match or dt_match > aujourd_str:
            continue

        # 1) Recherche dans l'historique football-data charge
        res_trouve = _chercher_resultat_dans_index(r, index, index_liste)

        # 2) Si pas encore dans l'index, verifier ESPN (matchs finis aujourd'hui ou passes)
        if res_trouve is None and ev_espn:
            dom_j = r.get("domicile", "")
            ext_j = r.get("exterieur", "")
            for e in ev_espn:
                if e.get("fini") and correspond(e, dt_match, dom_j, ext_j):
                    res_trouve = _resultat(e["sh"], e["sa"])
                    break

        # 3) Sinon, appel ciblé /matches/<id> (uniquement si date < aujourd'hui ou statut fini)
        if res_trouve is None and dt_match < aujourd_str and requetes < 20:
            try:
                mid = int(r["match_id"])
            except ValueError:
                mid = None
            if mid is not None:
                requetes += 1
                try:
                    raw_m = fd("/matches/%d" % mid)
                    if raw_m.get("status") == "FINISHED":
                        x = normaliser(raw_m)
                        if x:
                            res_trouve = _resultat(x["gh"], x["ga"])
                except Exception:
                    pass

        if res_trouve in ("1", "N", "2"):
            r["resultat"] = res_trouve
            maj_count += 1

    if maj_count:
        print("Journal : %d resultat(s) mis a jour automatiquement." % maj_count)
    return rows


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def resume_journal(rows):
    if not rows:
        print("JOURNAL : vide (il se remplit a chaque analyse).")
        return
    faits = [r for r in rows if r["resultat"] in ("1", "N", "2")]
    print("JOURNAL : %d analyses | %d resolues | %d en attente"
          % (len(rows), len(faits), len(rows) - len(faits)))
    if len(faits) >= 5:
        bs = []
        for r in faits:
            p = [_f(r["p1"]), _f(r["pN"]), _f(r["p2"])]
            if None in p:
                continue
            bs.append(_brier(p, "1N2".index(r["resultat"])))
        if bs:
            print("  Brier reel : %.3f (hasard ~0.667 ; plus bas = mieux)" % (sum(bs) / len(bs)))
    profits = []
    for r in faits:
        c = _f(r["cote_selection"])
        if r["selection"] in ("1", "N", "2") and c:
            profits.append(c - 1 if r["selection"] == r["resultat"] else -1.0)
    if profits:
        txt = "  Value signalees : %d | ROI reel : %.1f %%" % (
            len(profits), 100 * sum(profits) / len(profits))
        if len(profits) < 30:
            txt += " (trop peu de cas pour conclure)"
        print(txt)


# ============================================================
# PROGRAMME PRINCIPAL
# ============================================================
def statut_value(p_final, p_modele, cote, global_valide, seuil):
    if cote is None:
        return "NON_CONFIRMEE"
    if not global_valide:
        return "PISTE_A_EXAMINER"
    if (p_final * cote - 1) * 100 < seuil or p_modele * cote - 1 <= 0:
        return "PAS_DE_VALUE"
    return "VALUE_CALCULEE"


def cote_plancher(p_final, p_modele, seuil):
    """Cote minimale requise pour valider a la fois le seuil de value et p_modele > 1/cote."""
    if p_final <= 0 or p_modele <= 0:
        return None
    c_seuil = (1.0 + seuil / 100.0) / p_final
    c_mod = 1.0 / p_modele
    return max(c_seuil, c_mod)


def principal():
    global CLE_FD
    print("=== FOOT V6.0 ===")
    cfg = charger_config()
    CLE_FD = cfg["football_data"]
    print()

    print("Mode de selection :")
    print("0 - Matchs en cours (EN DIRECT, tous championnats)")
    print("1 - Choisir un championnat et une date")
    mode_sel = input("Ton choix (0 ou 1, vide = 1) : ").strip()

    if mode_sel == "0":
        print("\nRecherche des matchs en cours...")
        live_list = charger_matchs_en_direct()
        if not live_list:
            raise SystemExit("Aucun match en direct trouve pour le moment.")

        # Regrouper et afficher par championnat
        par_champ = {}
        for m in live_list:
            comp = m.get("competition") or {}
            c_code = comp.get("code") or "?"
            c_nom = (comp.get("area") or {}).get("name", "")
            c_titre = ((c_nom + " - ") if c_nom else "") + (comp.get("name") or c_code)
            par_champ.setdefault((c_code, c_titre), []).append(m)

        print("\n=== MATCHS EN DIRECT PAR CHAMPIONNAT ===")
        index_live = []
        for (c_code, c_titre), ml in par_champ.items():
            print("\n" + c_titre + " (" + c_code + ")")
            for m in ml:
                index_live.append(m)
                idx = len(index_live)
                h = (m.get("homeTeam") or {}).get("name", "?")
                a = (m.get("awayTeam") or {}).get("name", "?")
                sc_fd = score_90(m)
                sc_txt = "%d-%d" % (sc_fd[0], sc_fd[1]) if sc_fd else "en cours"
                st_lbl = "MI-TEMPS" if m.get("status") == "PAUSED" else "EN DIRECT"
                print("  %d | %s UTC | %s vs %s | %s (%s)" % (
                    idx, m.get("utcDate", "")[:16].replace("T", " "), h, a, st_lbl, sc_txt))

        choix_live = input("\nNumero du match en direct a analyser : ").strip()
        if not choix_live.isdigit() or not (1 <= int(choix_live) <= len(index_live)):
            raise SystemExit("Numero inconnu.")
        m_choisi = index_live[int(choix_live) - 1]
        comp_sel = m_choisi.get("competition") or {}
        code = comp_sel.get("code")
        if not code:
            raise SystemExit("Code championnat introuvable pour ce match.")
        c_nom = (comp_sel.get("area") or {}).get("name", "")
        nom_champ = ((c_nom + " - ") if c_nom else "") + (comp_sel.get("name") or code)
        slug = ESPN.get(code)
        debut = date.fromisoformat(m_choisi["utcDate"][:10])
        fin = debut + timedelta(days=1)

        annee, tous = charger_matchs(code)
        limite = debut.toordinal() - 800
        finis = []
        for m in tous:
            x = normaliser(m)
            if x and x["jour"] >= limite:
                finis.append(x)
        # On garde tous les matchs en direct de ce championnat + le match choisi
        matchs = sorted(
            [m for m in tous
             if (m.get("id") == m_choisi.get("id")
                 or m.get("status") in ("IN_PLAY", "PAUSED", "SCHEDULED", "TIMED"))
             and (m.get("homeTeam") or {}).get("id") and (m.get("awayTeam") or {}).get("id")
             and debut.isoformat() <= m["utcDate"][:10] <= fin.isoformat()],
            key=lambda m: m["utcDate"])
        if not matchs:
            matchs = [m_choisi]
    else:
        champs = charger_championnats()
        for i, (c, nom) in enumerate(champs, start=1):
            print(i, "-", nom, "(" + c + ")")
        choix = input("Numero du championnat : ").strip()
        if not choix.isdigit() or not (1 <= int(choix) <= len(champs)):
            raise SystemExit("Numero inconnu.")
        code, nom_champ = champs[int(choix) - 1]
        slug = ESPN.get(code)

        debut = lire_date(input("Date (ex: 21112026, vide = aujourd'hui) : "))
        j = input("Nombre de jours (vide = 1) : ").strip()
        fin = debut + timedelta(days=int(j) if j.isdigit() else 1)

        # --- chargement unique des matchs (saison en cours + precedente) ---
        annee, tous = charger_matchs(code)
        limite = debut.toordinal() - 800
        finis = []
        for m in tous:
            x = normaliser(m)
            if x and x["jour"] >= limite:
                finis.append(x)
        matchs = sorted(
            [m for m in tous
             if m.get("status") in ("SCHEDULED", "TIMED", "IN_PLAY", "PAUSED", "POSTPONED")
             and (m.get("homeTeam") or {}).get("id") and (m.get("awayTeam") or {}).get("id")
             and debut.isoformat() <= m["utcDate"][:10] <= fin.isoformat()],
            key=lambda m: m["utcDate"])
        if not matchs:
            raise SystemExit("Aucun match trouve.")

    # --- journal : resultats des matchs termines (passes + aujourd'hui via ESPN/FD) ---
    rows = lire_journal()
    dates_en_attente = [
        date.fromisoformat(r["date_match"][:10])
        for r in rows
        if r.get("resultat") not in ("1", "N", "2") and r.get("date_match")
        and r["date_match"][:10] <= date.today().isoformat()
    ]
    ev_journal = []
    if slug and dates_en_attente:
        d_min = min(min(dates_en_attente), debut)
        d_max = max(max(dates_en_attente), date.today())
        ev_journal = espn_evenements(slug, d_min, d_max)
    rows = maj_journal(rows, {x["id"]: x for x in finis}, date.today(), ev_espn=ev_journal)
    ecrire_journal(rows)
    print()
    resume_journal(rows)

    # --- backtest : le modele est-il fiable sur ce championnat ? ---
    print("\nBacktest en cours (quelques secondes)...")
    bt = backtest(finis)
    print("=== BACKTEST (" + code + ") ===")
    if bt["b_mod"] is None:
        print("Pas assez d'historique pour tester le modele.")
    else:
        print("Matchs testes :", bt["n"], "| Brier modele %.3f vs reference %.3f"
              % (bt["b_mod"], bt["b_base"]), "| calibration %.1f pts" % (100 * bt["calib"]))
        print("Reglages : demi-vie", bt["demi_vie"], "j | lissage", bt["prior"],
              "|", bt["mode"], "| rho", bt["rho"], "| nettete", bt["gamma"])
    print("MODELE :", "VALIDE" if bt["valide"] else "NON VALIDE (" + bt["raison"] + ")")

    ev_futurs = espn_evenements(slug, debut, fin) if slug else []
    if not slug:
        print("Pas de correspondance ESPN pour ce championnat : source 2 absente.")

    # --- cache classement pour ne pas recharger inutilement entre plusieurs matchs ---
    tab = classement_fd(code)
    st_espn = espn_classement(slug) if slug else {}
    deja_analyses = set()

    while True:
        print("\n" + nom_champ)
        sources_match = []
        for i, m in enumerate(matchs, start=1):
            h, a, d = m["homeTeam"]["name"], m["awayTeam"]["name"], m["utcDate"][:10]
            src = ["football-data"]
            ev_live = info_direct_espn(ev_futurs, d, h, a)
            if ev_live:
                src.append("espn")
            sources_match.append(src)
            en_jeu = est_en_direct(m)
            if en_jeu:
                sc_fd = score_90(m)
                if sc_fd:
                    etat = "EN DIRECT (%d-%d)" % (sc_fd[0], sc_fd[1])
                elif ev_live and not ev_live["fini"]:
                    etat = "EN DIRECT (%d-%d %s)" % (ev_live["sh"], ev_live["sa"], ev_live["etat_desc"])
                else:
                    etat = "EN DIRECT"
            else:
                etat = "Match confirme" if deux_sources(src) else "A confirmer - analyse bloquee"
            marque_fait = " [DEJA ANALYSE]" if m["id"] in deja_analyses else ""
            print(i, "|", m["utcDate"][:16].replace("T", " "), "UTC |", h, "vs", a, "|", etat + marque_fait)

        n = input("\nNumero du match a analyser (0 ou Entree = quitter) : ").strip()
        if n in ("", "0"):
            print("Fin des analyses.")
            break
        if not n.isdigit() or not (1 <= int(n) <= len(matchs)):
            print("Numero inconnu, reessaie.")
            continue
        m = matchs[int(n) - 1]
        dom, ext = m["homeTeam"], m["awayTeam"]
        date_match = m["utcDate"][:10]
        jour_match = date.fromisoformat(date_match).toordinal()
        match_live = est_en_direct(m)
        ev_live_sel = info_direct_espn(ev_futurs, date_match, dom["name"], ext["name"])

        print("\nANALYSE :", dom["name"], "vs", ext["name"], "-", date_match,
              "| STATUT : EN DIRECT" if match_live else "")
        if match_live:
            sc_fd = score_90(m)
            if sc_fd:
                print("Score en direct (football-data) : %s %d - %d %s" % (dom["name"], sc_fd[0], sc_fd[1], ext["name"]))
            elif ev_live_sel:
                print("Score en direct (ESPN) : %s %d - %d %s (%s)" % (
                    dom["name"], ev_live_sel["sh"], ev_live_sel["sa"], ext["name"], ev_live_sel["etat_desc"]))

        # --- donnees verifiees ---
        st_calendrier = OK if deux_sources(sources_match[int(n) - 1]) else NON
        finis_avant = [x for x in finis if x["jour"] < jour_match]
        ev_passes = (espn_evenements(slug, date.fromisoformat(date_match) - timedelta(days=200),
                                     date.fromisoformat(date_match) - timedelta(days=1))
                     if slug else [])
        forme_d = forme_equipe(finis_avant, dom["id"], ev_passes)
        forme_e = forme_equipe(finis_avant, ext["id"], ev_passes)
        forme_d_dom = forme_equipe(finis_avant, dom["id"], ev_passes, lieu="H", limite=5)
        forme_e_ext = forme_equipe(finis_avant, ext["id"], ev_passes, lieu="A", limite=5)

        cl_d, st_cl_d = classement_complet(tab.get(dom["id"]), st_espn, dom["name"])
        cl_e, st_cl_e = classement_complet(tab.get(ext["id"]), st_espn, ext["name"])

        print("\n--- 5 derniers matchs (global + specifique lieu) ---")
        print(dom["name"], "[Global :", resume_serie(forme_d), "| A domicile :", resume_serie(forme_d_dom) + "]")
        for r in forme_d:
            print("  ", r["txt"], "|", "+".join(r["sources"]))
        print(ext["name"], "[Global :", resume_serie(forme_e), "| A l'exterieur :", resume_serie(forme_e_ext) + "]")
        for r in forme_e:
            print("  ", r["txt"], "|", "+".join(r["sources"]))

        print("\n--- Classement ---")
        for nom_eq, c in ((dom["name"], cl_d), (ext["name"], cl_e)):
            if c:
                print(nom_eq, ": rang", c["rang"], "| pts", c["pts"], "| J", c["j"],
                      "| V-N-D", c["v"], c["n"], c["d"], "| diff", c["diff"],
                      "| ECART ENTRE SOURCES" if c["ecart"] else "")
            else:
                print(nom_eq, ": Points : Non trouve")

        # --- absences : trouvees par le script, confirmees par toi ---
        print("\n--- Absences ---")
        ab = absences_auto(cfg.get("api_football"), code, annee, date_match,
                           dom["name"], ext["name"])
        nb_abs_d = nb_abs_e = 0
        eq_abs_d = eq_abs_e = 0.0
        abs_dom_txt = abs_ext_txt = ""
        if ab is None:
            print("Aucune source automatique d'absences pour ce match.")
            rep_abs = input("Absences : o = je les saisis | a = j'ai verifie, AUCUN absent | Entree = PAS verifie : ").strip().lower()
            if rep_abs.startswith("o"):
                abs_valides = True
                saisie_d = input("Absents " + dom["name"] + " (separes par des virgules, Entree = aucun) : ").strip()
                saisie_e = input("Absents " + ext["name"] + " (separes par des virgules, Entree = aucun) : ").strip()
                noms_d = [x.strip() for x in saisie_d.split(",") if x.strip()]
                noms_e = [x.strip() for x in saisie_e.split(",") if x.strip()]
                nb_abs_d, nb_abs_e = len(noms_d), len(noms_e)
                print("Recherche des postes et calcul du poids des absents...")
                eq_abs_d, det_d, abs_dom_txt = evaluer_absents_avec_postes(noms_d, dom["name"])
                eq_abs_e, det_e, abs_ext_txt = evaluer_absents_avec_postes(noms_e, ext["name"])
                for eq_nom, dets, p_tot in ((dom["name"], det_d, eq_abs_d), (ext["name"], det_e, eq_abs_e)):
                    if dets:
                        print("  ", eq_nom, "(poids total :", p_tot, "):")
                        for d_item in dets:
                            print("     -", d_item["joueur"], "| poste :", d_item["poste"],
                                  "| poids match :", d_item["poids_match"], "| source :", d_item["source"])
                    else:
                        print("  ", eq_nom, ": aucun absent renseigne (poids 0.0)")
                print("Absences enregistrees ->", dom["name"], ":", abs_dom_txt,
                      "|", ext["name"], ":", abs_ext_txt)
            elif rep_abs.startswith("a"):
                abs_valides = True
                nb_abs_d = nb_abs_e = 0
                eq_abs_d = eq_abs_e = 0.0
                abs_dom_txt = "aucun (verifie manuellement)"
                abs_ext_txt = "aucun (verifie manuellement)"
                print("Aucune absence retenue (verifie manuellement).")
            else:
                abs_valides = False
                nb_abs_d = nb_abs_e = 0
                eq_abs_d = eq_abs_e = 0.0
                abs_dom_txt = "NON VERIFIE (source indisponible)"
                abs_ext_txt = "NON VERIFIE (source indisponible)"
                print("Absences NON VERIFIEES : l'indisponibilite n'est pas une validation.")
        else:
            for nom_eq, lst in ((dom["name"], ab[0]), (ext["name"], ab[1])):
                if lst:
                    print(nom_eq, ":", ", ".join(
                        a["joueur"] + (" (doute)" if a["type"] == "Questionable" else "")
                        for a in lst))
                else:
                    print(nom_eq, ": aucune absence signalee")
            nb_abs_d, nb_abs_e = len(ab[0]), len(ab[1])
            abs_valides = oui("Tu confirmes ces absences (source : API-Football) ?", defaut=True)
            if abs_valides:
                eq_abs_d = sum(0.4 if a["type"] == "Questionable" else 1.0 for a in ab[0])
                eq_abs_e = sum(0.4 if a["type"] == "Questionable" else 1.0 for a in ab[1])
                abs_dom_txt = ", ".join(
                    a["joueur"] + (" (doute)" if a["type"] == "Questionable" else "") for a in ab[0]
                ) if ab[0] else "aucun"
                abs_ext_txt = ", ".join(
                    a["joueur"] + (" (doute)" if a["type"] == "Questionable" else "") for a in ab[1]
                ) if ab[1] else "aucun"

        statuts = {
            "Calendrier": st_calendrier,
            "Forme domicile": statut_forme(forme_d),
            "Forme exterieur": statut_forme(forme_e),
            "Classement domicile": st_cl_d,
            "Classement exterieur": st_cl_e,
            "Absences domicile": OK if abs_valides else (PART if ab is not None else NON),
            "Absences exterieur": OK if abs_valides else (PART if ab is not None else NON),
        }
        print("\n=== AUDIT DES DONNEES ===")
        for k, v in statuts.items():
            print(k, ":", v)
        vals = list(statuts.values())
        niveau = OK if all(v == OK for v in vals) else NON if all(v == NON for v in vals) else PART
        donnees_ok = niveau == OK
        print("NIVEAU GLOBAL :", niveau)

        # --- cotes ---
        mk = trouver_marche(cfg.get("the_odds_api"), code, dom["name"], ext["name"], date_match)
        print("\n--- Tes cotes ---")
        cotes = {"1": None, "N": None, "2": None}
        if match_live and mk:
            print("Cotes moyennes du marche disponibles :",
                  "1=%.2f | N=%.2f | 2=%.2f (%d bookmakers)"
                  % (mk["cote_moy"]["1"], mk["cote_moy"]["N"], mk["cote_moy"]["2"], mk["nb"]))
            if oui("Utiliser automatiquement les cotes moyennes du marche en direct ?", defaut=True):
                cotes = dict(mk["cote_moy"])
        if all(v is None for v in cotes.values()):
            for k, txt in (("1", "1 (" + dom["name"] + ")"), ("N", "N (nul)"),
                           ("2", "2 (" + ext["name"] + ")")):
                c = nombre(input("Cote " + txt + (" (Entree = cote moyenne du marche)" if mk else "") + " : "))
                cotes[k] = c if c and c > 1 else None
            if mk and all(v is None for v in cotes.values()):
                cotes = dict(mk["cote_moy"])
                print("Cotes moyennes du marche utilisees (", mk["nb"], "bookmakers ).")

        # --- probabilites : modele + impact absences + marche ---
        s = construire_stats(finis_avant, jour_match, bt["demi_vie"])
        r = lambdas(s, dom["id"], ext["id"], bt["prior"], bt["mode"])
        if r is None:
            print("\nEquipes sans historique : estimation impossible. OBSERVATION seulement.")
            continue
        ld_brut, le_brut, n_min = r
        if abs_valides and (eq_abs_d > 0 or eq_abs_e > 0):
            ld, le = ajuster_lambdas_absences(ld_brut, le_brut, eq_abs_d, eq_abs_e)
        else:
            ld, le = ld_brut, le_brut

        stats_sec = estimer_stats_secondaires(
            ld, le,
            eq_abs_d if abs_valides else 0.0,
            eq_abs_e if abs_valides else 0.0,
            forme_d_dom, forme_e_ext
        )

        pm = aiguiser(probas(ld, le, bt["rho"]), bt["gamma"])

        p_marche, marge = (mk["p"], None) if mk else marche_depuis_cotes(cotes)
        if p_marche is None:
            marge = None
        if mk is None and p_marche is not None:
            source_marche = "tes 3 cotes (marge %.1f %% retiree)" % marge
        elif mk:
            source_marche = "%d bookmakers (The Odds API)" % mk["nb"]
        else:
            source_marche = None

        poids_mod = MELANGE_MODELE if n_min >= 10 else 0.35

        if p_marche:
            pf = [poids_mod * pm[i] + (1 - poids_mod) * p_marche["1N2"[i]] for i in range(3)]
            ecarts_pts = {k: 100 * (pm[i] - p_marche[k]) for i, k in enumerate("1N2")}
            issue_max_div = max("1N2", key=lambda k: abs(ecarts_pts[k]))
            diverg = abs(ecarts_pts[issue_max_div])
        else:
            pf, diverg, ecarts_pts, issue_max_div = pm, None, None, None

        print("\n=== BUTS ET STATISTIQUES ATTENDUES ===")
        if abs_valides and (eq_abs_d > 0 or eq_abs_e > 0):
            print("Buts bruts :", dom["name"], round(ld_brut, 2), "|", ext["name"], round(le_brut, 2),
                  "| Total match brut :", round(ld_brut + le_brut, 2))
        print("Buts attendus :", dom["name"], round(ld, 2), "|", ext["name"], round(le, 2),
              "| Total match :", round(ld + le, 2))

        c_d, c_e, c_tot = stats_sec["corners"]
        f_d, f_e, f_tot = stats_sec["fautes"]
        j_d, j_e, j_tot = stats_sec["jaunes"]
        r_d, r_e, r_tot = stats_sec["rouges"]

        print("Corners attendus :", dom["name"], c_d, "|", ext["name"], c_e, "| Total match :", c_tot)
        print("Fautes attendues  :", dom["name"], f_d, "|", ext["name"], f_e, "| Total match :", f_tot)
        print("Cartons jaunes    :", dom["name"], j_d, "|", ext["name"], j_e, "| Total match :", j_tot)
        print("Cartons rouges    :", dom["name"], r_d, "|", ext["name"], r_e, "| Total match :", r_tot)

        print("\n=== PROBABILITES ===")
        for i, k in enumerate("1N2"):
            ligne = "%s | modele %.1f %%" % (k, 100 * pm[i])
            if p_marche:
                ligne += " | marche %.1f %%" % (100 * p_marche[k])
            ligne += " | retenu %.1f %% (cote juste %.2f)" % (100 * pf[i], 1 / pf[i])
            print(ligne)
        if p_marche:
            sens = "plus optimiste" if ecarts_pts[issue_max_div] > 0 else "plus pessimiste"
            print("Marche =", source_marche, "| poids modele %.0f %%" % (100 * poids_mod))
            print("Divergence max : %.1f pts sur %s (modele %s que le marche)"
                  % (diverg, issue_max_div, sens))
        marche_ok = diverg is None or diverg <= DIVERGENCE_MAX
        if not marche_ok:
            print("ATTENTION : le modele et le marche divergent fortement sur", issue_max_div,
                  ". Verifie si une info contextuelle explique cet ecart.")

        # --- confiance automatique ---
        conf, raisons = 10, []
        if not bt["valide"]:
            conf -= 3
            raisons.append("modele non valide par le backtest")
        if n_min < 8:
            conf -= 2
            raisons.append("echantillon faible")
        if p_marche is None:
            conf -= 2
            raisons.append("pas de controle par le marche")
        if diverg is not None and diverg > DIVERGENCE_MAX:
            conf -= 3
            raisons.append("modele et marche en fort desaccord sur " + issue_max_div)
        elif diverg is not None and diverg > 5:
            conf -= 1
            raisons.append("divergence modele/marche moderee sur " + issue_max_div)
        if cl_d is None or cl_e is None:
            conf -= 2
            raisons.append("points de classement introuvables")
        if (cl_d and cl_d["ecart"]) or (cl_e and cl_e["ecart"]):
            conf -= 1
            raisons.append("ecart entre sources sur le classement")
        if len(forme_d) < 5 or len(forme_e) < 5:
            conf -= 1
            raisons.append("moins de 5 matchs de forme")
        if not abs_valides:
            conf -= 1
            raisons.append("absences non confirmees")
        if nb_abs_d >= 3 or nb_abs_e >= 3:
            conf -= 1
            raisons.append("3 absents ou plus (incertitude accrue)")
        conf = max(0, conf)
        print("Confiance :", conf, "/10", ("(" + " ; ".join(raisons) + ")") if raisons else "")

        global_valide = donnees_ok and bt["valide"] and marche_ok
        seuil = SEUIL_VALUE if p_marche else SEUIL_VALUE_SANS_MARCHE
        print("\n=== VALUE (seuil %.1f %%) ===" % seuil)
        res = {}
        planchers = {}
        for i, k in enumerate("1N2"):
            st = statut_value(pf[i], pm[i], cotes[k], global_valide, seuil)
            val = (pf[i] * cotes[k] - 1) * 100 if cotes[k] else None
            cp = cote_plancher(pf[i], pm[i], seuil)
            planchers[k] = cp
            res[k] = (st, val)
            cp_txt = " | cote min %.2f" % cp if cp else ""
            if cotes[k]:
                print(k, "| cote %.2f | cote juste %.2f%s | value %.1f %% | %s"
                      % (cotes[k], 1 / pf[i], cp_txt, val, st))
            else:
                print(k, "| pas de cote%s | %s" % (cp_txt, st))

        if not global_valide:
            print("Ces chiffres sont INDICATIFS : ne pas s'y fier tant que donnees,"
                  " modele et marche ne sont pas tous valides.")
        cand = [(v, k) for k, (st, v) in res.items() if st == "VALUE_CALCULEE"]
        if not donnees_ok:
            decision = "OBSERVATION (donnees non validees)"
        elif not bt["valide"]:
            decision = "OBSERVATION (modele non valide : " + bt["raison"] + ")"
        elif not marche_ok:
            decision = "ABSTENTION (divergence de %.0f pts sur %s : value suspecte)" % (diverg, issue_max_div)
        elif all(c is None for c in cotes.values()):
            decision = "ANALYSE (en attente des cotes)"
        elif not cand:
            decision = "ABSTENTION (aucune value)"
        else:
            v, sel = max(cand)
            niveau_conf = "FORTE" if conf >= 8 else "CORRECTE" if conf >= 6 else "FAIBLE"
            decision = "VALUE CALCULEE sur %s (%.1f %%) [Confiance %s %d/10] - A VALIDER PAR TOI" % (
                sel, v, niveau_conf, conf)
            if v > 25:
                decision += " | ECART SUSPECT : probable erreur du modele"
        print("\n=== DECISION V6.0 :", decision, "===")
        if cand:
            print("Rappel : verifie les compositions officielles (environ 1 h avant le match).")

        # --- journal ---
        sel_j, cote_j, plancher_j, val_j = "", "", "", ""
        if cand:
            v, sel_j = max(cand)
            cote_j = round(cotes[sel_j], 3)
            plancher_j = round(planchers[sel_j], 3) if planchers.get(sel_j) else ""
            val_j = round(v, 2)
        rows.append({
            "horodatage": datetime.now().strftime("%Y-%m-%d %H:%M"), "code": code,
            "match_id": m["id"], "date_match": date_match,
            "domicile": dom["name"], "exterieur": ext["name"],
            "absents_domicile": abs_dom_txt, "absents_exterieur": abs_ext_txt,
            "buts_att_dom": round(ld, 2), "buts_att_ext": round(le, 2),
            "buts_att_total": round(ld + le, 2),
            "corners_att_dom": c_d, "corners_att_ext": c_e, "corners_att_total": c_tot,
            "fautes_att_dom": f_d, "fautes_att_ext": f_e, "fautes_att_total": f_tot,
            "jaunes_att_dom": j_d, "jaunes_att_ext": j_e, "jaunes_att_total": j_tot,
            "rouges_att_dom": r_d, "rouges_att_ext": r_e, "rouges_att_total": r_tot,
            "p1": round(pf[0], 4), "pN": round(pf[1], 4), "p2": round(pf[2], 4),
            "pm1": round(pm[0], 4), "pmN": round(pm[1], 4), "pm2": round(pm[2], 4),
            "cote1": cotes["1"] or "", "coteN": cotes["N"] or "", "cote2": cotes["2"] or "",
            "selection": sel_j, "cote_selection": cote_j,
            "cote_plancher": plancher_j, "value_pct": val_j,
            "decision": decision, "confiance": conf, "resultat": ""})
        ecrire_journal(rows)
        print("Analyse enregistree dans le journal.")
        deja_analyses.add(m["id"])
        print()
        if not oui("Continuer avec un autre match ?", defaut=True):
            print("Fin des analyses.")
            break


if __name__ == "__main__":
    try:
        principal()
    except SystemExit as e:
        print(e)
    except Exception as e:
        print("Erreur :", e)
