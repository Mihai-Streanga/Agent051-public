"""
Orchestrarea filtrarii deterministe pe constrangeri dure.

Coregrafia:
    1. citeste criteriile din config/criterii.yaml -> store/configuratie.py  (disc)
    2. ia anunturile normalizate din baza          -> store/db.py           (disc)
    3. aplica filtrul, anunt cu anunt              -> core/filtrare.py      (pur)
    4. salveaza verdictele                         -> store/db.py           (disc)
    5. RAPORTEAZA tot, inclusiv ce n-a putut fi evaluat

FARA MODEL SI FARA RETEA. Fluxul asta nu cheama nimic din afara si nu costa nimic.
Lucreaza pe date deja salvate, deci se poate rula de oricate ori, oricand, fara
internet - si mai ales dupa fiecare modificare a lui criterii.yaml, ceea ce e chiar
scopul lui. Schimbi pragul de venit, rulezi iar, ai verdictele noi in cateva secunde.

Decizia nu se ia aici. "Trece sau nu" se cere de la core/filtrare.py, care e o functie
pura. Aici se cara datele dintr-o parte in alta si se numara rezultatele.
"""

from agent051.core.descriere import (
    SURSE_CUNOSCUTE as SURSE_CU_PAGINA,
    salariul_din_pagina,
    tarile_din_pagina,
)
from agent051.core.filtrare import filtreaza_dur
from agent051.store.configuratie import incarca_criterii, versiune_criterii
from agent051.store.db import (
    anunturi_de_filtrat,
    initializeaza_db,
    pagina_salvata,
    salveaza_filtrare,
)


def ruleaza_filtrarea() -> dict:
    """
    Trece toate anunturile normalizate prin constrangerile dure. Intoarce un raport.

    Raportul spune:
        anunturi_evaluate - cate au intrat in filtru
        trecute           - cate n-au incalcat nimic si nu au date lipsa
        respinse          - cate au incalcat o constrangere dura, cu date certe
        incerte           - cate n-au incalcat nimic, dar au date lipsa
        versiune_criterii - dupa ce versiune de criterii.yaml s-a dat verdictul
        motive_frecvente  - de cate ori a aparut fiecare motiv de respingere
        lipsuri_frecvente - de cate ori a lipsit fiecare fel de data

    DE CE raportam motivele numarate, nu doar totalurile:
    "180 respinse" nu-ti spune nimic si te face sa ai incredere degeaba. "180 respinse,
    din care 174 pentru cuvantul 'ture'" iti spune imediat ca ceva e in neregula cu
    regula aia, nu cu cele 174 de joburi. Un filtru determinist gresit taie tacut si
    consecvent - de-asta trebuie sa se vada pe ce taie, nu doar cat.

    La fel si lipsurile: daca "salariu neafisat" apare la toate anunturile, filtrul pe
    venit nu face nimic in practica, si e mai bine sa afli asta dintr-o cifra decat
    peste trei luni.
    """
    initializeaza_db()

    criterii = incarca_criterii()
    # Aceeasi functie care spune si CITIRILOR ce versiune e valabila. Daca scrierea si
    # citirea si-ar calcula-o fiecare, ar putea ajunge la valori diferite - si atunci
    # s-ar scrie verdicte pe care nu le mai citeste nimeni, fara nicio eroare.
    versiune = versiune_criterii()

    anunturi = anunturi_de_filtrat()

    trecute = 0
    respinse = 0
    incerte = 0
    motive_frecvente = {}
    lipsuri_frecvente = {}

    for anunt in anunturi:
        rezultat = filtreaza_dur(_cu_datele_din_pagina(anunt), criterii)

        salveaza_filtrare(anunt["id"], rezultat, versiune)

        if rezultat["verdict"] == "trece":
            trecute += 1
        elif rezultat["verdict"] == "respins":
            respinse += 1
        else:
            incerte += 1

        for motiv in rezultat["motive_respingere"]:
            motive_frecvente[motiv] = motive_frecvente.get(motiv, 0) + 1

        for lipsa in rezultat["necunoscute"]:
            lipsuri_frecvente[lipsa] = lipsuri_frecvente.get(lipsa, 0) + 1

    return {
        "anunturi_evaluate": len(anunturi),
        "trecute": trecute,
        "respinse": respinse,
        "incerte": incerte,
        "versiune_criterii": versiune,
        # Cele mai frecvente primele: alea sunt si cele care ar face cel mai mult rau
        # daca regula din spatele lor e gresita.
        "motive_frecvente": dict(
            sorted(motive_frecvente.items(), key=lambda p: p[1], reverse=True)
        ),
        "lipsuri_frecvente": dict(
            sorted(lipsuri_frecvente.items(), key=lambda p: p[1], reverse=True)
        ),
    }


def _cu_datele_din_pagina(anunt: dict) -> dict:
    """
    Anuntul, completat cu ce spun datele structurate ale paginii salvate (29 sept. 2026):
      - `salariu_brut`, doar cand mailul nu-l are - salariul din mail e data bruta si
        ramane intotdeauna primul;
      - `tari_din_pagina`, tarile locului de munca.

    Pagina se citeste de pe disc doar la anunturile care au una salvata (status "ok",
    sursa eJobs sau BestJobs), o singura data, ca sa nu se care sute de pagini prin
    memorie degeaba. Nimic nu se scrie inapoi in `anunturi`.
    """
    if anunt.get("sursa") not in SURSE_CU_PAGINA or anunt.get("status_pagina") != "ok":
        return anunt

    html = pagina_salvata(anunt["id"])
    completat = {**anunt, "tari_din_pagina": tarile_din_pagina(html, anunt["sursa"])}
    if not (anunt.get("salariu_brut") or "").strip():
        salariu = salariul_din_pagina(html, anunt["sursa"])
        if salariu:
            completat["salariu_brut"] = salariu
    return completat
