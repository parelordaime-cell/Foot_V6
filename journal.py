# -*- coding: utf-8 -*-
"""Journal SQLite : pas de doublon (un match = une ligne), import du CSV du moteur."""
import csv, os, sqlite3
import engine

DB = os.path.join(engine.DOSSIER, "foot_journal.db")
COLS = ["match_id", "date_match", "domicile", "exterieur", "decision", "confiance",
        "selection", "cote_selection", "value_pct", "resultat", "horodatage"]


def connexion():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS analyses (
        match_id TEXT, date_match TEXT, domicile TEXT, exterieur TEXT, decision TEXT,
        confiance INTEGER, selection TEXT, cote_selection REAL, value_pct REAL,
        resultat TEXT, horodatage TEXT, PRIMARY KEY (match_id, date_match))""")
    return c


def _num(v, typ):
    try:
        return typ(v)
    except (TypeError, ValueError):
        return None


def importer_csv(chemin=None):
    """Copie le journal CSV du moteur dans SQLite (mise a jour si le match existe deja)."""
    chemin = chemin or engine.FICHIER_JOURNAL
    if not os.path.exists(chemin):
        return 0
    n = 0
    with connexion() as c, open(chemin, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            vals = [str(r.get("match_id", "")), r.get("date_match", ""), r.get("domicile", ""),
                    r.get("exterieur", ""), r.get("decision", ""), _num(r.get("confiance"), int),
                    r.get("selection", ""), _num(r.get("cote_selection"), float),
                    _num(r.get("value_pct"), float), r.get("resultat", ""), r.get("horodatage", "")]
            c.execute("INSERT OR REPLACE INTO analyses (%s) VALUES (%s)"
                      % (",".join(COLS), ",".join("?" * len(COLS))), vals)
            n += 1
    return n


def dernieres(n=30):
    with connexion() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM analyses ORDER BY date_match DESC, horodatage DESC LIMIT ?", (n,))]


def performance():
    """Resultats reels des analyses avec une selection et un resultat connu."""
    with connexion() as c:
        rows = c.execute("""SELECT selection, cote_selection, resultat FROM analyses
                            WHERE selection <> '' AND resultat IN ('1','N','2')""").fetchall()
    n = len(rows)
    if n == 0:
        return {"n": 0}
    gagnes = sum(1 for r in rows if r["selection"] == r["resultat"])
    profit = sum((r["cote_selection"] or 0) - 1 if r["selection"] == r["resultat"] else -1.0
                 for r in rows)
    return {"n": n, "reussite_pct": round(100.0 * gagnes / n, 1), "roi_pct": round(100.0 * profit / n, 1)}
