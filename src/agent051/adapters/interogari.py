"""
Interogari de citit: oportunitati, cautare, starea fluxului.

Trei fluxuri care doar CITESC. Nu scriu nimic in baza, nu ating reteaua, nu cheama
niciun model. Se pot rula de oricate ori, oricand, fara nicio consecinta - ceea ce le
face potrivite pentru un buton apasat de om, care nu trebuie sa se intrebe daca a
stricat ceva apasandu-l de doua ori.

DE CE stau in adapters/ si nu in core/: citesc din baza de date. Discul e IO. In core/
au ramas deciziile - ce inseamna o oportunitate si in ce ordine se aseaza - iar de
acolo se cer, nu se rescriu aici (vezi alege_oportunitatile din core/briefing.py).
"""

from datetime import datetime, timezone

from agent051.adapters.briefing import anunturi_recente
from agent051.adapters.consum import situatia_lunii_curente
from agent051.core.briefing import alege_oportunitatile
from agent051.store.configuratie import agregatori
from agent051.store.db import (
    anunturi_pentru_briefing,
    cauta_anunturi,
    citeste_stare,
    cost_cumulat,
    initializeaza_db,
    numara_pe_etape,
)


def oportunitati_noi(limita: int = 10) -> dict:
    """
    Primele `limita` oportunitati din toata baza, in ordinea de prioritate a briefingului.

    DIFERENTA FATA DE briefing(), fiindca se confunda usor:
    briefingul raspunde la "ce s-a schimbat de la ultima citire" si depinde de reper.
    Asta se uita la TOT ce e in baza, indiferent de reper, si nu-l atinge niciodata.
    Un anunt bun de acum trei saptamani apare aici chiar daca l-ai vazut deja in zece
    briefinguri.

    Pe o baza goala intoarce o lista goala, nu o eroare: "nu am nicio oportunitate" e
    un raspuns valid la intrebarea pusa.
    """
    initializeaza_db()

    # de_la=None inseamna "tot ce e in baza", nu "de la ultimul briefing".
    toate = anunturi_pentru_briefing(None)

    return {
        "limita": limita,
        "total_candidate": len(toate),
        # Aceleasi repostari ca in briefing: fereastra de varsta si agregatorii din
        # surse.yaml. Ceasul se citeste aici, nu in core/.
        "oportunitati": alege_oportunitatile(
            toate, limita, anunturi_recente(datetime.now(timezone.utc)), agregatori()
        ),
    }


def cauta(text: str, limita: int = 10) -> dict:
    """
    Anunturile care contin textul dat, in titlu, firma sau descriere.

    Cautare simpla pe text, nu semantica: gaseste ce contine sirul cerut, nu ce
    "seamana ca inteles". Pentru "seamana" ar fi nevoie de un model, iar aici nu se
    cheama niciunul - vezi limitarea cu diacriticele din cauta_anunturi().

    Cauta in TOATA baza, inclusiv in anunturile respinse de filtrul dur. E intentionat:
    cand cauti ceva anume, vrei sa afli si daca a existat si a fost taiat, nu doar ce a
    supravietuit. Verdictul vine in fiecare rand, deci se vede ce s-a intamplat cu el.

    Un text care nu se gaseste nicaieri da o lista goala, nu o eroare.
    """
    initializeaza_db()

    gasite = cauta_anunturi(text, limita)

    return {
        "text_cautat": text,
        "limita": limita,
        "gasite": len(gasite),
        "anunturi": gasite,
    }


def stare_pipeline() -> dict:
    """
    Cate randuri exista la fiecare etapa, reperul ultimului briefing si costul cumulat.

    E fotografia fluxului: unde a ajuns si unde s-a oprit. Nu judeca nimic si nu spune
    daca cifrele sunt bune sau rele - le arata. "900 de anunturi, 0 normalizate" se
    citeste singur.

    `cost` sunt contoarele cumulate de cand exista baza: cate apeluri de model s-au facut
    si cati tokeni s-au consumat. Le tinem la vedere aici tocmai fiindca modelul costa -
    un flux ale carui cheltuieli nu se vad nicaieri e un flux in care nimeni nu observa ca
    a scapat de sub control. Pe o baza pe care n-a rulat niciun model, amandoua sunt 0.
    `cost.luna_curenta` pune consumul lunii in dolari, langa bugetul din config/cost.yaml.

    La etape, evaluarile calitative vin in doua cifre - `evaluate_calitativ_curente` si
    `evaluate_calitativ_vechi` - fiindca doar primele se mai citesc undeva. Dupa o urcare
    de versiune de criterii, a doua cifra sare si prima cade la zero: nu s-a stricat
    nimic, e de rulat evaluarea. Un singur total ar fi ascuns exact schimbarea asta.

    Pe o baza goala intoarce aceleasi chei, etapele pe zero, `ultim_briefing: null` si
    costul pe zero. Nu e o eroare: inainte de prima ingestie, zero e raspunsul corect.
    """
    initializeaza_db()

    return {
        "etape": numara_pe_etape(),
        # None cand n-a fost niciodata marcat un briefing ca citit. Se deosebeste de
        # un reper vechi: primul inseamna "n-ai citit niciodata", al doilea "ai citit
        # atunci". Doua situatii diferite, doua raspunsuri diferite.
        "ultim_briefing": citeste_stare("ultim_briefing"),
        # Totalul istoric in tokeni, plus luna curenta in bani, fata de buget.
        "cost": {**cost_cumulat(), "luna_curenta": situatia_lunii_curente()},
    }
