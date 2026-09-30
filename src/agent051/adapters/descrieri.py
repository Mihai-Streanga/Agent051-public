"""
Orchestrarea completarii descrierilor: leaga cererea paginii de extragerea textului.

Coregrafia, pentru un anunt:
    1. cere pagina publica, dupa `link`  -> ingest/pagini.py       (IO, retea)
    2. extrage descrierea din HTML       -> core/descriere.py      (pur)
    3. salveaza pagina BRUTA + descrierea -> store/db.py           (disc)

DE CE STA AICI SI NU IN core/: pasul 1 iese in lume. Un orchestrator care cheama reteaua
e IO, oricat de subtire ar fi - regula proiectului nu are exceptii. In core/ a ramas doar
capatul pur, care se ruleaza cu internetul taiat, pe pagini salvate pe disc.

DE UNDE VINE CITITORUL DE PAGINI: se primeste ca parametru (`ia_pagina`), exact ca
`cheama_model` la normalizare. In teste se injecteaza o functie inventata si nu se atinge
nicio retea; in productie il construieste ruleaza_descrierile().

PE CINE SE CHEAMA, si de ce nu pe toata arhiva: doar anunturi RECENTE (pragul din
criterii.yaml), FARA descriere, de la o sursa cu parser, carora nu li s-a luat deja
pagina cu succes. Arhiva de 2858 de anunturi e cercetare de piata - anunturile din 2018
sunt moarte, nu intra in scoring si n-are rost sa le cerem paginile, care oricum ar da
404. Aceleasi plase ca la normalizare, din aceleasi motive; doar moneda difera - acolo
se apara bani, aici rabdarea serverului din partea cealalta.

LinkedIn NU e in lista de surse: blocheaza agresiv cererile automate. Nu insistam si nu
ne deghizam - vezi nota de la user_agent din config/surse.yaml.
"""

from datetime import datetime, timezone

from agent051.core.descriere import (
    extrage_descrierea,
    extrage_firma_si_titlul,
    pagina_e_a_anuntului,
    titlul_de_pastrat,
)
from agent051.core.varsta import este_recent
from agent051.ingest.pagini import (
    STATUS_EXPIRAT,
    STATUS_OK,
    EroareRetea,
    construieste_ia_pagina,
)
from agent051.store.configuratie import configurare_pagini, varsta_maxima_zile
from agent051.store.db import (
    anunturi_pentru_descriere,
    initializeaza_db,
    salveaza_pagina,
)

# Pagina anuntului a venit, dar parserul n-a gasit descrierea in ea. E un fapt despre
# PAGINA, nu despre drum: se salveaza (cu HTML-ul brut, ca sa se poata re-extrage dupa ce
# reparam parserul) si rularea merge mai departe.
#
# DUPA 17 AUGUST 2026, statusul asta inseamna UN SINGUR lucru: "pagina e a anuntului, si
# parserul n-a stiut s-o citeasca". Adica: repara parserul. Inainte insemna si "am primit
# alta pagina", care nu are nicio legatura cu parserul - vezi pagina_e_a_anuntului.
STATUS_FARA_DESCRIERE = "fara_descriere"

# Statusurile care inseamna "nu mai cere pagina asta, nu mai e nimic de aflat de la ea".
#
# `ok` - am luat-o, avem textul.
# `expirat` - anuntul nu mai e la adresa aia, si nici nu se intoarce: un anunt repostat e
#   un anunt NOU, cu alt link, care vine intr-un mail nou. Pana pe 17 august 2026, un
#   `expirat` se reincerca la fiecare rulare, cu argumentul ca "o cerere nu costa bani".
#   Costa altceva: fiecare rulare cerea iar aceleasi pagini moarte, iar in briefing cele
#   trei stateau permanent la `in_asteptare.fara_descriere`. Un avertisment care nu se
#   poate stinge nu mai avertizeaza - ajunge mobilier, si atunci nu se mai vede nici cand
#   spune ceva adevarat.
#
# `interzis_robots` NU e aici, dinadins: robots.txt se poate schimba, iar reincercarea
# lui nu cere nicio pagina (raspunsul vine din robots-ul deja citit).
STATUSURI_INCHISE = (STATUS_OK, STATUS_EXPIRAT)


def ia_descrierea_unui_anunt(anunt: dict, ia_pagina: callable) -> dict:
    """
    Pentru un anunt: cere pagina, extrage descrierea. Intoarce ce e de salvat.

    `ia_pagina` e o functie (adresa) -> dict, primita ca parametru. Functia asta nu stie
    ce biblioteca de HTTP e dedesubt, ce User-Agent se trimite sau cat se asteapta intre
    cereri. Ii da o adresa, primeste un rezultat.

    Intoarce dictionarul pe care il scrie store.salveaza_pagina (plus `firma` si `titlu`,
    cand pagina le spune - vezi _firma_si_titlul_din_pagina):
        {"status": "ok",              "html": "...", "descriere": "...", "motiv": ""}
        {"status": "fara_descriere",  "html": "...", "descriere": None,  "motiv": "..."}
        {"status": "expirat",         "html": None,  "descriere": None,  "motiv": "..."}
        {"status": "interzis_robots", "html": None,  "descriere": None,  "motiv": "..."}

    UN 200 NU E DE AJUNS. Inainte de a citi HTML-ul, se intreaba daca pagina primita e
    chiar a anuntului (pagina_e_a_anuntului): eJobs raspunde la anunturile moarte cu un
    redirect catre lista generala, adica 200 si o pagina valida a altcuiva. Aia iese
    `expirat`, nu `fara_descriere` - vezi comentariul de la STATUS_FARA_DESCRIERE.

    NU prinde EroareRetea. La fel ca la normalizare: a o prinde si a o transforma in
    "fara descriere" ar ascunde un esec de drum sub un fapt despre anunt - o sursa care
    ne blocheaza ar marca tacut 30 de anunturi ca "n-au descriere", cand de fapt paginile
    nici n-au fost citite. Eroarea trece neatinsa catre lot, care opreste rularea.

    HTML-UL BRUT SE SALVEAZA SI CAND EXTRAGEREA ESUEAZA. Ala e chiar cazul in care ai
    nevoie de el: repari parserul si re-extragi din ce e in baza, fara sa mai ceri o data
    pagina - si fara sa depinzi de faptul ca anuntul mai exista online.
    """
    raspuns = ia_pagina(anunt["link"])

    if raspuns["status"] != STATUS_OK:
        return {
            "status": raspuns["status"],
            "html": None,
            "descriere": None,
            "motiv": raspuns.get("motiv", ""),
        }

    adresa_finala = raspuns.get("adresa_finala", "")
    if not pagina_e_a_anuntului(anunt["link"], adresa_finala):
        # Serverul a raspuns 200, dar cu alta pagina - la eJobs, lista generala de joburi
        # in locul unui anunt care nu mai e. Faptul e despre ANUNT, nu despre parser, deci
        # iese `expirat`, exact ca un 404 spus pe alt ton.
        #
        # NU se salveaza HTML-ul. Regula "pastram brutul" se aplica datelor despre anuntul
        # asta, iar pagina altcuiva nu e una: salvata in `pagina_html`, ar face ca fiecare
        # re-extragere de mai tarziu sa citeasca lista de joburi crezand ca e anuntul - si
        # ar tine un megabait pe rand ca sa poata face asta.
        return {
            "status": STATUS_EXPIRAT,
            "html": None,
            "descriere": None,
            "motiv": f"serverul a trimis la {adresa_finala} in loc de anunt",
        }

    identitate = _firma_si_titlul_din_pagina(anunt, raspuns["html"])

    extras = extrage_descrierea(raspuns["html"], anunt.get("sursa"))
    if not extras["ok"]:
        return {
            "status": STATUS_FARA_DESCRIERE,
            "html": raspuns["html"],
            "descriere": None,
            "motiv": extras["motiv"],
            **identitate,
        }

    return {
        "status": STATUS_OK,
        "html": raspuns["html"],
        "descriere": extras["descriere"],
        "motiv": "",
        **identitate,
    }


def _firma_si_titlul_din_pagina(anunt: dict, html: str) -> dict:
    """
    Ce mai spune pagina despre anunt, in afara descrierii: firma si titlul adevarat.

    Intoarce {"firma": ..., "titlu": ...}, fiecare None cand nu e nimic de scris.

    DOUA REGULI DIFERITE, dinadins:
      firma - se trimite cand pagina o stie. Baza o scrie doar daca acolo e gol.
      titlu - se trimite DOAR in cazul demonstrat de core.descriere.titlul_de_pastrat:
              cel din mail e cel din pagina plus mobilier lipit. In rest, None - adica
              "nu atinge titlul".

    Un esec de extragere aici NU schimba statusul si nu opreste nimic: campurile astea
    sunt un plus fata de descriere, care e scopul cererii. Daca structura paginii nu se
    recunoaste, raman goale si se vede in baza ca au ramas goale.
    """
    gasit = extrage_firma_si_titlul(html, anunt.get("sursa"))
    if not gasit["ok"]:
        return {"firma": None, "titlu": None}

    return {
        "firma": gasit["firma"],
        "titlu": titlul_de_pastrat(anunt.get("titlu"), gasit["titlu"]) or None,
    }


def alege_anunturile(anunturi: list, surse_permise, acum: datetime, zile: int) -> dict:
    """
    Din toate anunturile, cele carora merita sa li se ceara pagina. Cu numaratoare.

    Functie separata fiindca e chiar decizia "pe cine", si vrem sa se poata citi si testa
    singura, fara retea si fara baza. Intoarce {"eligibile": [...], "sarite": {...}},
    unde `sarite` spune cate au picat pe fiecare motiv - ca sa se vada in raport DE CE
    o rulare atinge 12 anunturi si nu 2858.

    Ordinea verificarilor e cea in care raspund la intrebari tot mai scumpe:
      1. sursa are parser?      (LinkedIn nu, si nici n-o sa aiba - blocheaza)
      2. are link?              (fara adresa nu exista pagina de cerut)
      3. are deja descriere?    (BestJobs o trimite in mail - n-are rost sa mai cerem)
      4. s-a inchis deja socoteala cu pagina? (luata cu succes, sau anunt expirat -
         vezi STATUSURI_INCHISE; nu cerem de doua ori acelasi lucru, si nu cerem la
         nesfarsit o pagina care nu mai exista)
      5. e recent?              (arhiva veche e moarta si nu intra in scoring)

    `pagina_deja_luata` si `anunt_expirat` se numara SEPARAT, desi amandoua opresc
    cererea: primul spune "avem textul", al doilea "nu-l vom avea niciodata". Adunate la
    un total, n-ai cum sa vezi cate anunturi au murit inainte sa ajungem la ele.
    """
    permise = tuple(surse_permise or ())
    eligibile = []
    sarite = {
        "sursa_fara_parser": 0,
        "fara_link": 0,
        "au_deja_descriere": 0,
        "pagina_deja_luata": 0,
        "anunt_expirat": 0,
        "prea_vechi": 0,
    }

    for anunt in anunturi:
        if (anunt.get("sursa") or "").strip().lower() not in permise:
            sarite["sursa_fara_parser"] += 1
        elif not (anunt.get("link") or "").strip():
            sarite["fara_link"] += 1
        elif (anunt.get("descriere") or "").strip():
            sarite["au_deja_descriere"] += 1
        elif anunt.get("status_pagina") == STATUS_OK:
            sarite["pagina_deja_luata"] += 1
        elif anunt.get("status_pagina") == STATUS_EXPIRAT:
            sarite["anunt_expirat"] += 1
        elif not este_recent(anunt.get("data_anunt"), acum, zile):
            sarite["prea_vechi"] += 1
        else:
            eligibile.append(anunt)

    return {"eligibile": eligibile, "sarite": sarite}


def ia_lotul(
    anunturi: list,
    ia_pagina: callable,
    salveaza: callable,
    surse_permise,
    acum: datetime,
    zile: int,
    limita: int,
    dry_run: bool,
) -> dict:
    """
    Cere paginile unui lot de anunturi, cu plasele de siguranta. Intoarce un raport.

    Nu atinge nici baza, nici reteaua direct: primeste anunturile ca lista, cititorul de
    pagini ca functie injectata si scrie prin `salveaza`, o functie (anunt_id, rezultat).
    De aceea se testeaza intreg fara disc si fara internet.

    Plasele, in ordinea in care taie:
      1. CINE (vezi alege_anunturile): sursa, link, descriere existenta, pagina deja
         luata, varsta.
      2. LIMITA (`limita`): dintre eligibile, se cer cel mult atatea pagini intr-o
         rulare. Implicit 30 in ruleaza_descrierile - franca impotriva unei rulari care
         ar trage sute de pagini deodata de pe serverul altcuiva.
      3. DRY RUN: calculeaza tot ce e mai sus, dar NU cere nicio pagina.

    ESEC DE RETEA: daca o cerere PICA (EroareRetea - blocat, 403, retea cazuta, redirect
    la login), oprim rularea IMEDIAT, la prima aparitie. Anuntul respectiv NU se
    salveaza - nu stim nimic despre el, ramane de reincercat - iar esecul iese separat,
    la `esec_retea`. Nu se amesteca niciodata cu "anuntul a expirat", care e un fapt.
    Ce s-a salvat cu succes inainte ramane salvat.

    Raportul:
        candidate         - cate anunturi au intrat in lot (toata baza)
        sarite            - numaratoarea pe motive (vezi alege_anunturile)
        de_procesat       - cate au ramas eligibile
        limita            - plafonul cerut
        ar_procesa        - cate pagini s-ar cere / se cer (min(de_procesat, limita))
        oprite_de_limita  - eligibile lasate pe data viitoare
        dry_run           - daca a fost o simulare
        cerute            - cate pagini s-au cerut efectiv (0 la dry run)
        cu_descriere      - cate au dat o descriere buna
        expirate          - cate anunturi nu mai exista (404/410) - FAPT despre anunt
        interzise_robots  - cate adrese nu ne sunt permise de robots.txt
        fara_descriere    - pagini venite din care parserul n-a scos text
        esuate_retea      - cereri picate inainte de un raspuns (0 sau 1: oprim la prima)
        esec_retea        - mesajul clar al esecului, sau None
    """
    ales = alege_anunturile(anunturi, surse_permise, acum, zile)
    eligibile = ales["eligibile"]

    de_procesat = len(eligibile)
    ar_procesa = min(de_procesat, limita)
    oprite_de_limita = de_procesat - ar_procesa

    cerute = 0
    numarate = {STATUS_OK: 0, "expirat": 0, "interzis_robots": 0, STATUS_FARA_DESCRIERE: 0}
    esuate_retea = 0
    esec_retea = None

    if not dry_run:
        # Taiem la plafon INAINTE de bucla: nu se cere niciodata mai mult decat `limita`,
        # nici macar "si apoi verificam". Franca e reala, nu o socoteala de dupa.
        for anunt in eligibile[:limita]:
            try:
                rezultat = ia_descrierea_unui_anunt(anunt, ia_pagina)
            except EroareRetea as eroare:
                # Drumul s-a rupt. NU salvam anuntul si oprim: ce a blocat pagina asta
                # va bloca si urmatoarea.
                esuate_retea += 1
                esec_retea = str(eroare)
                break
            salveaza(anunt["id"], rezultat)
            cerute += 1
            numarate[rezultat["status"]] = numarate.get(rezultat["status"], 0) + 1

    return {
        "candidate": len(anunturi),
        "sarite": ales["sarite"],
        "de_procesat": de_procesat,
        "limita": limita,
        "ar_procesa": ar_procesa,
        "oprite_de_limita": oprite_de_limita,
        "dry_run": dry_run,
        "cerute": cerute,
        "cu_descriere": numarate[STATUS_OK],
        "expirate": numarate["expirat"],
        "interzise_robots": numarate["interzis_robots"],
        "fara_descriere": numarate[STATUS_FARA_DESCRIERE],
        "esuate_retea": esuate_retea,
        "esec_retea": esec_retea,
    }


def ruleaza_descrierile(
    limita: int = 30, dry_run: bool = True, ia_pagina: callable = None
) -> dict:
    """
    Completeaza descrierile lipsa din paginile publice ale anunturilor. Implicit DRY RUN.

    Wiring: citeste anunturile si reglajele din baza/config, construieste cititorul de
    pagini (daca nu i s-a dat unul) si cheama ia_lotul. Firele sunt aici; deciziile
    (cine, cat, dry run) sunt in ia_lotul si alege_anunturile, care se testeaza singure.

    `dry_run=True` e IMPLICIT, ca la normalizare, dar din alt motiv: aici nu se cheltuie
    bani, se cheltuie rabdarea unui server care ne da continut gratis. O rulare scapata
    peste toata baza ar insemna sute de cereri si, foarte probabil, o blocare meritata.
    O rulare pe bune se cere explicit (din linia de comanda: --confirma).

    NU are pre-flight ca normalizarea (verifica_infrastructura). Acolo, lipsa cheii se
    poate sti dinainte, si merita, ca sa nu marchezi gresit 50 de anunturi. Aici primul
    lucru care se cere oricum e robots.txt-ul gazdei: daca reteaua e cazuta sau sursa ne
    blocheaza, se afla la prima cerere, inainte sa se atinga vreun anunt, si iese ca
    EroareRetea. O verificare separata ar fi inca o cerere catre acelasi server, ca sa
    afle acelasi lucru cu o secunda mai devreme.
    """
    initializeaza_db()

    reglaje = configurare_pagini()
    zile = varsta_maxima_zile()
    anunturi = anunturi_pentru_descriere()
    acum = datetime.now(timezone.utc)

    if ia_pagina is None:
        ia_pagina = construieste_ia_pagina(reglaje)

    raport = ia_lotul(
        anunturi,
        ia_pagina,
        salveaza_pagina,
        reglaje["surse_permise"],
        acum,
        zile,
        limita,
        dry_run,
    )
    raport["surse_permise"] = list(reglaje["surse_permise"])
    raport["pauza_secunde"] = reglaje["pauza_secunde"]
    return raport
