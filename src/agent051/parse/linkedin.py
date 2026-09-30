"""
Parser pentru alertele LinkedIn.

Link-ul unui anunt arata mereu la fel, si e cel mai curat dintre cele trei surse:
    https://www.linkedin.com/comm/jobs/view/4407616313/?trackingId=...
Numarul din "/jobs/view/<numar>/" e id-ul jobului. Stabil, al lui LinkedIn.

Dupa titlu, mailul pune firma si locatia, ca text simplu:
    HR Generalist with English      <- titlul (in link)
    Accenture Romania               <- firma
    Bucuresti                       <- locatia
    3 contacte                      <- zgomot, se sare

ATENTIE - SABLON VECHI CARE NU CONTINE JOBURI:
Pana prin 2019, LinkedIn trimitea si mailuri de tip "companiile au facut angajari
pentru 181 de posturi", care NU contin niciun link catre un job anume - doar link-uri
catre cautari. Din 22 din cele 77 de mesaje LinkedIn lipsesc link-urile per job.
Parserul le va REFUZA, zgomotos, cu un motiv clar. Asta nu e un bug: din acele mailuri
chiar nu se poate extrage nimic. Important e sa se VADA in raport, nu sa treaca tacut.
"""

import re

from agent051.parse.comun import (
    EroareParser,
    anunt,
    curata_textul,
    e_text_de_navigatie,
    elemente_din_html,
    elemente_si_bucatile_linkurilor,
)

SURSA = "linkedin"

TIPAR_ANUNT = re.compile(r"/jobs/view/(\d+)")

# Randuri care apar intre firma si locatie, dar nu sunt niciuna din ele.
TIPAR_CONTACTE = re.compile(r"^\d+\s+(contacte|contact|connections?)$", re.IGNORECASE)

# Insigne de interfata LinkedIn care apar sub "Firma · Locatie" si NU sunt locatie:
#   "Recrutează activ" (Actively recruiting), "Candidatură simplă" (Easy Apply),
#   "N absolvenți ai instituției de învățământ", "N contact(e) lucrează aici",
#   "Fiți printre primii N candidați", si un salariu ANUAL ("57 mii RON / an" -
#   necomparabil cu un prag lunar, deci nici salariu util nu e).
#
# DE CE avem nevoie de lista asta: exact ele erau bug-ul. In sablonul nou (2026),
# LinkedIn pune "Firma · Locatie" pe UN rand, apoi sub el insira insignele astea. Parserul
# lua a doua linie drept locatie, ajungand cu locatia "Recrutează activ" si firma "DHL ·
# Ștefănești". O locatie gresita produce o RESPINGERE FALSA la filtru; una goala doar
# "incert". Deci: cand vedem un separator "·", el contine si firma si locatia si nu ne mai
# uitam mai jos (split-ul le sare oricum); iar in sablonul vechi, fara "·", ne feresc sa
# luam o insigna drept locatie.
TIPAR_INSIGNA = re.compile(
    r"recrut[ăa]z[ăa] activ"
    r"|candidatur[ăa] simpl[ăa]"
    r"|instituți(?:ei|i) de învățământ|instituti(?:ei|i) de invatamant"
    r"|lucreaz[ăa] aici"
    r"|fiți printre primii|fiti printre primii"
    r"|\bmii\s+(?:ron|lei|eur|€)\b",
    re.IGNORECASE,
)


def _e_insigna(text: str) -> bool:
    """Textul asta e o insigna de interfata LinkedIn, nu o locatie?"""
    return bool(TIPAR_INSIGNA.search(text or ""))


def extrage(corp_html: str, mesaj_id: str = "?") -> list:
    """
    Sparge un mail LinkedIn in anunturi individuale.

    Ridica EroareParser daca mailul nu contine niciun link de tip /jobs/view/ -
    fie e un sablon vechi fara joburi, fie sablonul s-a schimbat. In ambele cazuri
    vrem sa aflam, nu sa primim o lista goala si un fals "succes".
    """
    if not corp_html or not corp_html.strip():
        raise EroareParser(SURSA, mesaj_id, "mesajul nu are corp HTML")

    elemente, bucati = elemente_si_bucatile_linkurilor(corp_html)
    anunturi = []
    numere_vazute = set()

    for pozitie, (fel, href, text) in enumerate(elemente):
        if fel != "link" or not text or e_text_de_navigatie(text):
            continue

        potrivire = TIPAR_ANUNT.search(href)
        if not potrivire:
            continue

        numar = potrivire.group(1)
        if numar in numere_vazute:
            continue
        numere_vazute.add(numar)

        titlu, firma, locatie = _cardul_din_link(bucati.get(pozitie, []))
        if not titlu:
            titlu = text
            firma, locatie = _firma_si_locatie(elemente, pozitie)
        # descriere si salariu_brut raman GOALE la LinkedIn, si e o decizie verificata
        # pe toata arhiva (77 mailuri). Sub "firma · locatie" LinkedIn pune doar insigne
        # de interfata ("Recrutează activ", "Candidatură simplă", "N contacte") - nu o
        # descriere a jobului. Salariu apare de doua ori in toata arhiva, si ala anual
        # ("57 mii RON / an"), necomparabil cu un prag lunar. A umple descriere cu
        # insignele alea ar fi zgomot; nu o facem. Vezi anunt(), care le lasa "".
        anunturi.append(
            anunt(
                sursa=SURSA,
                titlu=titlu,
                firma=firma,
                locatie=locatie,
                # Taiem coada de urmarire: acelasi job, in doua mailuri, are alt
                # trackingId. Link-ul curat e stabil.
                link=f"https://www.linkedin.com/jobs/view/{numar}",
                cheie=f"linkedin:{numar}",
            )
        )

    if not anunturi:
        raise EroareParser(
            SURSA,
            mesaj_id,
            "niciun link de tip /jobs/view/ - fie e un sablon vechi de tip rezumat "
            "(fara joburi individuale), fie sablonul s-a schimbat.",
        )

    return anunturi


def joburi_din_linkuri(corp_html: str) -> set:
    """
    Numerele tuturor joburilor /jobs/view/ din mail - numaratoarea de control.

    Fara filtrele din extrage(): si link-ul fara text se numara. Daca extrage() scoate
    mai putine anunturi decat numara asta, un job s-a pierdut pe drum - vezi
    adapters/extragere.py.
    """
    numere = set()
    for fel, href, _ in elemente_din_html(corp_html or ""):
        if fel != "link":
            continue
        potrivire = TIPAR_ANUNT.search(href)
        if potrivire:
            numere.add(potrivire.group(1))
    return numere


def _cardul_din_link(bucati: list) -> tuple:
    """
    (titlu, firma, locatie) cand TOT cardul jobului sta in link; altfel ("", "", "").

    Sablonul "career insights" (vazut prima data pe 29 sept. 2026, mailul "Payroll
    Specialist: ... fac angajari") pune intr-un singur <a>:
        Manager Payroll Harmonization Europe (d/f/m)     <- titlul, in celula lui
        Schaeffler · Braşov                              <- firma · locatia, in alta
    Textul lipit al link-ului ar fi dat titlul "... (d/f/m) Schaeffler · Braşov" si o
    firma goala. Se recunoaste dupa "·" in una din bucatile de dupa titlu; fara el, link-ul
    e doar titlul, ca in celelalte sabloane, si decide _firma_si_locatie.
    """
    if len(bucati) < 2:
        return "", "", ""
    for bucata in bucati[1:]:
        if "·" in bucata:
            stanga, _, dreapta = bucata.partition("·")
            return bucati[0], curata_textul(stanga), curata_textul(dreapta)
    return "", "", ""


def _firma_si_locatie(elemente: list, pozitie: int) -> tuple:
    """
    Firma si locatia de sub titlu. Ce nu se poate determina cu certitudine ramane gol.

    Adunam textele libere de dupa titlu, pana la urmatorul link (acolo incepe alt job),
    sarind peste "3 contacte" (nu e nici firma, nici locatie).

    SABLONUL 2026 (tot ce e in arhiva acum): LinkedIn lipeste firma si locatia pe UN rand,
    despartite de un punct-mediu:
        DHL Supply Chain · Ștefănești
    iar SUB el insira insigne de interfata ("Recrutează activ", "Candidatură simplă", ...).
    Deci cand primul rand are "·", el contine si firma si locatia - le despartim si NU ne
    uitam mai jos. Asta repara bug-ul: inainte, a doua linie (o insigna) ajungea locatie,
    iar firma pastra si orasul. O locatie gresita = respingere FALSA la filtru; una goala
    = doar "incert". Vezi TIPAR_INSIGNA.

    SABLONUL VECHI (fara "·"): firma si locatia pe randuri separate. Luam ca locatie primul
    rand de dupa firma care NU e o insigna. Daca toate sunt insigne (sau nu exista), locatia
    ramane goala - mai bine gol si "incert" decat gresit si respins.
    """
    texte = []
    for fel, _, text in elemente[pozitie + 1 : pozitie + 6]:
        if fel == "link":
            break
        curat = curata_textul(text)
        if not curat or e_text_de_navigatie(curat) or TIPAR_CONTACTE.match(curat):
            continue
        texte.append(curat)

    if not texte:
        return "", ""

    prima = texte[0]

    # Sablonul 2026: "Firma · Locatie" pe primul rand; restul sunt insigne. Despartim si
    # ne oprim - nu coboram la insigne.
    if "·" in prima:
        stanga, _, dreapta = prima.partition("·")
        return curata_textul(stanga), curata_textul(dreapta)

    # Sablonul vechi: firma pe primul rand, locatia pe urmatorul rand ne-insigna.
    firma = prima
    for candidat in texte[1:]:
        if not _e_insigna(candidat):
            return firma, candidat
    return firma, ""
