"""
Orchestrarea briefingului: aduna din baza, cheama distilarea pura, intoarce rezultatul.

Coregrafia:
    1. citeste reperul "ultim_briefing"   -> store/db.py        (disc)
    2. aduna ce s-a schimbat de atunci    -> store/db.py        (disc)
    3. aduna stadiul intregii baze        -> store/db.py        (disc)
    4. distileaza                         -> core/briefing.py   (pur)
    5. muta reperul, DOAR daca s-a cerut  -> store/db.py        (disc)

CE LIPSESTE DIN LANTUL ASTA, si e cel mai important lucru de stiut despre el:
niciun apel catre vreun model. Fisierul asta nu primeste `cheama_model` si n-are ce
face cu el. Spre deosebire de normalizare si de evaluarea calitativa, unde judecata e
inevitabil subiectiva si un model isi merita banii, aici totul se calculeaza: cate
mesaje, cate anunturi, care sunt primele cinci dupa o ordine scrisa in cod. Un model
chemat aici ar costa bani ca sa rezume ceva deja rezumat - si ar face ca acelasi set
de date sa dea doua briefinguri diferite la doua rulari.

DE CE STA TOTUSI IN adapters/ daca nu cheama reteaua: fiindca citeste baza de date.
Discul e IO la fel ca reteaua. Regula proiectului nu are exceptii - core/ ramane cu
functiile care merg cu discul scos.
"""

from datetime import datetime, timezone

from agent051.core.briefing import compune_briefing, formateaza_text
from agent051.core.varsta import este_recent
from agent051.store.configuratie import agregatori, configurare_pagini, varsta_maxima_zile
from agent051.store.db import (
    anunturi_pentru_briefing,
    citeste_stare,
    initializeaza_db,
    numara_mesaje_noi,
    scrie_stare,
    stadiul_anunturilor,
    titlurile_anunturilor,
)

# Cheia sub care traieste reperul temporal in tabela `stare`.
# Scrisa o singura data, aici, ca sa nu apara ca sir de caractere prin trei fisiere.
CHEIE_REPER = "ultim_briefing"


def _stadii_cu_varsta(acum: datetime) -> list:
    """
    Stadiul fiecarui anunt, plus faptul "e recent?" - singurul lucru pe care core/ nu-l
    poate afla singur.

    Varsta se masoara fata de ceasul de acum, iar core/briefing.py nu importa nimic, nici
    macar `datetime`. Deci ceasul se citeste aici, o data, si intra in date ca un simplu
    adevarat/fals per anunt. Regula ("ce inseamna in asteptare") ramane in core; faptul
    ("anuntul asta e recent") vine de aici, exact ca `are_evaluare_valabila`, care vine
    din baza.

    `acum` e parametru, nu `datetime.now()` chemat inauntru: asa aceeasi baza da acelasi
    raspuns la doua rulari de test.

    `este_recent` vine din core/varsta.py, de unde o iau si normalizarea, si descrierile.
    Un singur loc, dinadins: numarul pe care il anunta briefingul si numarul pe care il
    face rularea trebuie sa fie acelasi.
    """
    zile = varsta_maxima_zile()
    return [
        dict(stadiu, recent=este_recent(stadiu.get("data_anunt"), acum, zile))
        for stadiu in stadiul_anunturilor()
    ]


def anunturi_recente(acum: datetime) -> list:
    """
    Anunturile din ultimele varsta_maxima_zile, cu titlu, firma si data.

    Din ele briefingul - si unealta oportunitati_noi, prin adapters/interogari.py - afla
    ce e repostat (vezi _strange_repostarile din core/briefing.py).
    Taietura pe varsta e aici din acelasi motiv ca la _stadii_cu_varsta: cere ceasul.
    Fara ea, un titlu generic s-ar potrivi cu anunturi din toata arhiva de 11 ani, si
    aproape orice rand ar iesi "posibil repostat".
    """
    zile = varsta_maxima_zile()
    return [
        anunt for anunt in titlurile_anunturilor()
        if este_recent(anunt.get("data_anunt"), acum, zile)
    ]


def briefing(marcheaza_citit: bool = False) -> dict:
    """
    Ce s-a schimbat de la ultimul briefing marcat citit.

    Intoarce:
        {
          "briefing": {...},   structura distilata (vezi core/briefing.py)
          "text": "...",       aceeasi informatie, in 1-9 randuri pentru om
          "reper_mutat": bool  daca reperul temporal a fost mutat la momentul asta
        }

    DE CE `marcheaza_citit` e False IMPLICIT - asta e decizia de proiectare a functiei:

    Daca reperul s-ar muta automat la fiecare apel, un briefing cerut din greseala,
    intrerupt la jumatate, sau facut de un proces automat care apoi crapa ar consuma
    definitiv tot ce era intre timp. Al doilea briefing ar spune "nimic nou", iar
    anunturile dintre cele doua momente n-ar mai aparea NICIODATA in niciun raport.
    Ele raman in baza, dar nimeni nu le-ar mai vedea - adica exact felul de pierdere
    tacuta care nu se observa cand se intampla si nu se mai poate repara dupa.

    Costul alegerii inverse e neglijabil: un briefing cerut de doua ori la rand arata
    de doua ori aceleasi lucruri. Enervant, si atat.

    Deci: citirea e gratuita si se poate repeta oricat. Consumarea se cere explicit,
    cu marcheaza_citit=True, si atunci e o decizie luata de cineva, nu un efect secundar.

    Momentul in care se muta reperul e CEL DINAINTE de citire, nu cel de dupa. Intre
    citirea anunturilor si scrierea reperului pot trece secunde, iar in secundele alea
    poate intra un anunt nou. Cu reperul pus la momentul de dupa, anuntul ala ar cadea
    intre doua briefinguri si n-ar aparea in niciunul. Asa, in cel mai rau caz apare de
    doua ori - o repetitie se vede si se ignora, o lipsa nu se vede niciodata.
    """
    initializeaza_db()

    acum = datetime.now(timezone.utc)
    inceput_citire = acum.isoformat()
    de_la = citeste_stare(CHEIE_REPER)

    date = {
        "de_la": de_la,
        "mesaje_noi": numara_mesaje_noi(de_la),
        "anunturi": anunturi_pentru_briefing(de_la),
        # Stadiul INTREGII baze, nu doar al noutatilor: o coada de lucru ramasa de
        # saptamana trecuta face briefingul de azi la fel de incomplet ca una de acum
        # zece minute. Vezi numara_in_asteptare din core/briefing.py.
        "stadii": _stadii_cu_varsta(acum),
        "surse_cu_pagina": configurare_pagini().get("surse_permise") or (),
        "recente": anunturi_recente(acum),
        "agregatori": agregatori(),
    }

    distilat = compune_briefing(date)

    if marcheaza_citit:
        scrie_stare(CHEIE_REPER, inceput_citire)

    return {
        "briefing": distilat,
        "text": formateaza_text(distilat),
        "reper_mutat": marcheaza_citit,
    }
