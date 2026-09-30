"""
Citirea configurarii din config/ (criterii.yaml, surse.yaml, cost.yaml).

DE CE exista fisierul asta:
Pragul de 30 de zile nu are voie sa fie scris in cod. Daca maine vrei 45 de zile,
schimbi o cifra in criterii.yaml si gata - nu ne cauti pe amandoi prin fisiere Python.
Configurarea sta in fisiere, codul doar o citeste. E una din regulile proiectului.

DOUA fisiere, nu unul: criterii.yaml tine judecata (praguri salariale, tinta, semnale) -
date sensibile, care fac repo-ul nepublicabil. surse.yaml tine politeturi de retea
(pauza intre cereri, timeout, cum ne prezentam) - complet impersonale. Se schimba din
motive diferite si nu vrem sa deschidem fisierul cu praguri ca sa reglam un timeout.

Locul lui in arhitectura: `store/` = tot ce citeste sau scrie pe disc. Un fisier de
configurare e tot disc, deci tot IO. In core/ nu ar avea ce cauta.
"""

from pathlib import Path

import yaml

# Radacina proiectului: urcam trei niveluri (store -> agent051 -> src -> radacina).
RADACINA_PROIECT = Path(__file__).resolve().parents[3]
CALE_CRITERII = RADACINA_PROIECT / "config" / "criterii.yaml"
CALE_SURSE = RADACINA_PROIECT / "config" / "surse.yaml"
CALE_COST = RADACINA_PROIECT / "config" / "cost.yaml"

# Daca fisierul de configurare lipseste sau nu are sectiunea `evaluare`, folosim
# valoarea asta. NU e "pragul adevarat" - pragul adevarat sta in criterii.yaml.
# E doar o plasa, ca programul sa nu crape. Vezi comentariul din varsta_maxima_zile().
PRAG_IMPLICIT_ZILE = 30

# Plasele pentru citirea paginilor, daca surse.yaml lipseste sau e incomplet.
# Aceeasi regula ca mai sus: valorile ADEVARATE stau in surse.yaml.
PAUZA_IMPLICITA_SECUNDE = 2.0
TIMEOUT_IMPLICIT_SECUNDE = 20.0
UA_IMPLICIT = "Agent051/0.1 (agent personal de cautare joburi)"


def _incarca_yaml(cale: Path) -> dict:
    """
    Citeste un fisier YAML si il intoarce ca dictionar.

    Daca fisierul lipseste sau e stricat, intoarce un dictionar gol in loc sa crape.
    Motivul: o greseala de virgula in configurare nu are voie sa doboare tot agentul.
    """
    if not cale.exists():
        return {}

    try:
        with open(cale, "r", encoding="utf-8") as fisier:
            continut = yaml.safe_load(fisier)
    except (yaml.YAMLError, OSError):
        return {}

    # safe_load intoarce None pentru un fisier gol.
    # safe_load (nu load): nu executa nimic din fisier, doar citeste date.
    # Un fisier de configurare nu are voie sa poata rula cod.
    return continut if isinstance(continut, dict) else {}


def incarca_criterii() -> dict:
    """Continutul lui config/criterii.yaml, sau un dictionar gol daca lipseste."""
    return _incarca_yaml(CALE_CRITERII)


def incarca_surse() -> dict:
    """Continutul lui config/surse.yaml, sau un dictionar gol daca lipseste."""
    return _incarca_yaml(CALE_SURSE)


def incarca_cost() -> dict:
    """
    Continutul lui config/cost.yaml, sau un dictionar gol daca lipseste.

    Fara plase cu valori implicite, spre deosebire de celelalte: un pret ghicit ar da o
    cifra de bani falsa. Lipsa se vede in raport, ca "pret necunoscut" - vezi core/cost.py.
    """
    return _incarca_yaml(CALE_COST)


def configurare_pagini() -> dict:
    """
    Reglajele pentru citirea paginilor publice de anunt, din config/surse.yaml.

    Intoarce un dict cu: pauza_secunde, timeout_secunde, user_agent, surse_permise.
    Fiecare valoare lipsa sau absurda (text in loc de numar, zero, negativ) cade pe
    plasa de mai sus. NU crapam pentru un fisier incomplet, dar nici nu "reparam" tacut
    o valoare gresita intr-una apropiata: fie e buna, fie se foloseste implicita.

    DE CE conteaza ca pauza sa nu poata ajunge 0 dintr-o greseala de configurare:
    o pauza zero pe 30 de pagini arata, din partea cealalta, ca un atac. Plasa nu e
    aici ca sa fim politicosi din intamplare, ci ca sa nu putem fi nepoliticosi
    dintr-o virgula pusa gresit.
    """
    pagini = incarca_surse().get("pagini") or {}

    surse = pagini.get("surse_permise")
    surse_permise = tuple(str(s).strip().lower() for s in surse) if surse else ()

    return {
        "pauza_secunde": _numar_pozitiv(pagini.get("pauza_secunde"), PAUZA_IMPLICITA_SECUNDE),
        "timeout_secunde": _numar_pozitiv(
            pagini.get("timeout_secunde"), TIMEOUT_IMPLICIT_SECUNDE
        ),
        "user_agent": str(pagini.get("user_agent") or "").strip() or UA_IMPLICIT,
        "surse_permise": surse_permise,
    }


def agregatori() -> tuple:
    """
    Firmele din `agregatori` (config/surse.yaml), cu litere mici. Tuplu gol daca lipsesc.

    Fara plasa: o lista ghicita ar pune etichete pe joburi fara motiv. Lipsa inseamna
    doar ca briefingul nu mai scrie "posibil repostat".
    """
    lista = incarca_surse().get("agregatori") or ()
    return tuple(" ".join(str(firma).lower().split()) for firma in lista)


def _numar_pozitiv(valoare, implicit: float) -> float:
    """Numarul din configurare, daca e un numar strict pozitiv. Altfel, implicitul."""
    try:
        numar = float(valoare)
    except (TypeError, ValueError):
        return implicit
    return numar if numar > 0 else implicit


def criterii_calitative() -> dict:
    """
    DOAR felia calitativa din criterii.yaml, pregatita pentru model.

    Ce intra: tinta (ce rol se cauta), TREPTELE de relevanta, ce e exclus (executie
    clasica, programator pur), semnalele pozitive si negative. Ce NU intra, cu buna
    stiinta: pragul salarial si locatia. Alea sunt constrangeri DURE - le rezolva filtrul
    determinist, inainte ca modelul sa fie chemat, si dau acelasi raspuns de fiecare data.
    N-au ce cauta intr-o judecata calitativa: nu vrem ca modelul sa "mai treaca cu
    vederea" un salariu mic fiindca rolul suna interesant. Filtrul dur a taiat deja ce era
    de taiat pe reguli.

    `trepte` (din 1.2) e scala pe care raspunde modelul la `relevant`: ideal,
    bun_in_domeniu, exclus. Se citeste din fisier, nu se scrie in cod - la fel ca restul.
    Codul cunoaste NUMELE treptelor (le valideaza), fisierul spune ce inseamna fiecare.

    `limbi_vorbite` (din 1.3) e SINGURA constrangere dura care ajunge totusi la model,
    si merita spus de ce nu contrazice paragraful de mai sus. Filtrul determinist taie
    doar cererile de limba scrise in TITLU, unde "(with German)" nu poate insemna decat
    un lucru. In descriere, aceeasi germana poate fi obligatorie sau "un plus" - iar aia
    se vede citind fraza, nu dintr-un cuvant. Modelul primeste lista ca sa poata SEMNALA
    in motivare, nu ca sa respinga: respingerea pe limba ramane a filtrului.

    Intoarce un dict cu cheile: tinta, traiectorie, trepte, exclus, semnale_pozitive,
    semnale_negative, limbi_vorbite. Daca o sectiune lipseste din fisier, cheia ei iese
    goala - nu crapam si nu inventam un criteriu care nu e scris.
    """
    criterii = incarca_criterii()
    tinta = criterii.get("tinta") or {}
    continut = tinta.get("continut") or {}
    calitative = criterii.get("conditii_calitative") or {}
    limbi = ((criterii.get("constrangeri_dure") or {}).get("limbi") or {})

    return {
        "tinta": continut.get("descriere") or "",
        "traiectorie": continut.get("traiectorie") or {},
        "trepte": tinta.get("trepte") or {},
        "exclus": tinta.get("exclus") or [],
        "semnale_pozitive": calitative.get("semnale_pozitive") or [],
        "semnale_negative": calitative.get("semnale_negative") or [],
        "limbi_vorbite": limbi.get("vorbite") or [],
    }


def versiune_criterii() -> str:
    """
    Versiunea criteriilor de acum, din criterii.yaml (meta.versiune). Ca text.

    UN SINGUR LOC CARE STIE CE VERSIUNE E, si de asta conteaza:
    versiunea e folosita in doua feluri opuse, care trebuie sa raspunda la fel.
      - la SCRIERE: fiecare verdict de filtrare si de evaluare se eticheteaza cu ea;
      - la CITIRE: se citesc DOAR verdictele purtand versiunea de acum.
    Daca cele doua ar calcula-o fiecare in felul ei, ar putea ajunge la valori diferite -
    si atunci s-ar scrie randuri pe care nu le mai citeste nimeni niciodata, fara ca ceva
    sa dea eroare. Se scrie o data, aici, si se cere de peste tot.

    "necunoscuta" cand lipseste din fisier: e o valoare ca oricare alta, deci randurile
    scrise asa se citesc intre ele si nu se amesteca cu cele etichetate cu un numar. Nu
    crapam pentru o cheie lipsa dintr-un fisier de configurare, dar nici nu ne prefacem
    ca versiunea lipsa inseamna "orice versiune".
    """
    meta = incarca_criterii().get("meta") or {}
    return str(meta.get("versiune") or "necunoscuta")


def varsta_maxima_zile() -> int:
    """
    Pragul de varsta pentru evaluare, in zile, din criterii.yaml.

    Un anunt mai vechi de atat nu se mai evalueaza: e ocupat sau expirat.
    Datele RAMAN in baza - regula asta taie doar la scoring, niciodata la ingestie
    sau la stocare. Arhivul de 11 ani e o resursa, nu un balast.

    Daca valoarea lipseste din configurare sau nu e un numar, folosim plasa de
    siguranta (30 de zile) in loc sa crapam. Dar valoarea REALA e cea din fisier.
    """
    criterii = incarca_criterii()
    evaluare = criterii.get("evaluare") or {}
    valoare = evaluare.get("varsta_maxima_zile")

    try:
        zile = int(valoare)
    except (TypeError, ValueError):
        return PRAG_IMPLICIT_ZILE

    # Un prag negativ sau zero nu inseamna nimic. Il tratam ca lipsa.
    return zile if zile > 0 else PRAG_IMPLICIT_ZILE
