"""
Briefingul: din tot ce s-a schimbat, cele cateva randuri care conteaza.

DE CE EXISTA:
JA.S.Mine nu cauta joburi, ci raporteaza. Daca i-am da 40 de anunturi si l-am lasa pe
el sa le rezume, am muta munca de distilare in afara agentului - si am plati-o in
tokeni, de fiecare data, pentru un rezultat care se poate calcula exact.

REGULA CENTRALA, si motivul pentru care fisierul asta e in core/:
    BRIEFINGUL NU CHEAMA NICIUN MODEL.
Judecata calitativa s-a facut deja, la evaluare, si sta in baza. Aici doar adunam,
taiem, sortam si formatam - operatiuni care dau acelasi rezultat de fiecare data.
Un model chemat aici ar fi platit ca sa rezume ceva ce se agrega determinist, si
ar face ca acelasi set de date sa produca doua briefinguri diferite la doua rulari.

Ce nu importa fisierul asta: nimic. Nici `json`, nici `sqlite3`, nici `datetime`,
nici reteaua. Uita-te la lista de importuri de mai jos - e goala. Briefingul se
calculeaza din datele primite ca parametru, si de aceea se poate testa cu internetul
taiat, fara baza de date si fara nicio cheie de API.
"""

# Cate anunturi intra in lista structurata, cea pe care o citeste JA.S.Mine.
# Peste cinci, "ce merita atentia ta" devine iar o lista de parcurs - adica exact
# problema pe care briefingul o rezolva.
MAXIM_IN_LISTA = 5

# Cate apar in redarea TEXT. Mai putine decat in lista, dinadins: textul e pentru
# o privire de om, si trebuie sa incapa in 3-6 randuri cu tot cu cifre. Restul nu se
# pierde - sunt in structura, si textul spune cate au ramas nespuse.
MAXIM_IN_TEXT = 3

# Ordinea de prioritate, ca numere: mai mic = mai sus in lista.
#
# Valorile necunoscute (None - anunt inca nefiltrat sau neevaluat) primesc un rang
# mai slab decat orice valoare cunoscuta, prin _rang(). Nu le scoatem din lista: un
# anunt proaspat, care a trecut filtrul dur dar n-a apucat sa fie evaluat calitativ,
# e o oportunitate reala despre care doar nu stim inca destul. Il aratam ultimul,
# nu deloc.
RANG_VERDICT = {"trece": 0, "incert": 1}
RANG_INTERES = {"ridicat": 0, "mediu": 1, "incert": 2, "scazut": 3}

# Relevanta are TREI trepte de la criteriile 1.2 incoace: ideal > bun_in_domeniu >
# exclus. "exclus" nu apare in tabel fiindca nu ajunge sa fie sortat - se scoate din
# lista mai devreme, in _imparte_candidatele.
#
# AICI A FOST si o traducere a verdictelor binare din epoca 1.1 ("da" -> treapta de sus,
# "nu" -> exclus). S-a scos: de cand citirile iau doar evaluarile pe versiunea de criterii
# de acum (vezi JOIN_EVALUARE_VALABILA din store/db.py), un verdict de pe 1.1 nu mai
# ajunge niciodata pana aici. O traducere pe care n-o poate atinge nimic e mai rea decat
# inutila - se citeste ca si cum ar fi inca in functiune si te face sa crezi ca epocile
# se amesteca undeva.
RANG_RELEVANT = {"ideal": 0, "bun_in_domeniu": 1, "incert": 2}

# Treapta care scoate anuntul din lista de recomandari. Doar cea de jos: "bun_in_domeniu"
# ramane, mai jos decat "ideal" - asta e tot rostul treptei din mijloc.
RELEVANT_EXCLUS = ("exclus",)

# Verdictele filtrului dur care pot ajunge in lista. "respins" nu e aici: a picat pe
# o regula certa, se numara si atat.
VERDICTE_CANDIDATE = ("trece", "incert")

# Statusurile care inseamna "etapa asta e facuta, nu mai are ce astepta". Sunt exact
# valorile pe care le folosesc si rularile (STATUS_GATA din adapters/normalizare.py si
# STATUSURI_INCHISE din adapters/descrieri.py). Scrise aici ca text, nu importate de
# acolo: fisierul asta nu importa nimic - vezi antetul. Daca vreodata se schimba intr-un
# loc, se schimba in amandoua, si testele de mai jos sunt cele care o spun.
NORMALIZARE_FACUTA = "ok"

# Doua feluri de "nu mai cerem pagina asta", si amandoua opresc asteptarea: pagina a
# venit ("ok"), sau anuntul nu mai exista ("expirat"). Al doilea a intrat aici pe 17
# august 2026: cat timp lipsea, trei anunturi moarte stateau permanent la
# `in_asteptare.fara_descriere`, iar randul de avertisment din briefing cerea la fiecare
# rulare o descriere care nu mai putea veni de nicaieri.
PAGINI_INCHISE = ("ok", "expirat")

# Cum se numesc in text cele trei feluri de lucru nefacut, si in ce ordine apar - aceeasi
# ordine ca in lant: descriere, normalizare, evaluare. Ordinea nu e cosmetica: o citesti
# ca pe o coada, de la ce se face intai la ce se face la urma.
ETICHETE_ASTEPTARE = (
    ("fara_descriere", "fara descriere"),
    ("nenormalizate", "nenormalizate"),
    ("neevaluate", "neevaluate"),
)

# Etichete scurte pentru motivele de respingere, la numaratoare.
# Motivele vin din core/filtrare.py ca fraze cu detaliu ("venit sub pragul de
# respingere: max 4200 < 5000 RON (...)"). Intr-o numaratoare, fraza intreaga ar face
# fiecare motiv unic si ar da 31 de categorii cu cate 1. Taiem la eticheta.
ETICHETE_MOTIVE = {
    "venit sub pragul de respingere": "venit",
    "locatie in afara zonei": "locatie",
}


def compune_briefing(date: dict) -> dict:
    """
    Din datele brute deja citite din baza, structura distilata a briefingului.

    `date` se primeste GATA CITIT, nu se citeste aici (asta ar fi IO):
        de_la            reperul de la care se raporteaza, sau None la primul briefing
        mesaje_noi       cate mesaje au intrat de atunci
        anunturi         lista anunturilor noi, fiecare cu verdictul filtrului dur si
                         verdictele calitative, acolo unde exista
        stadii           TOATE anunturile din baza, fiecare cu etapa la care a ajuns -
                         din ele se afla ce a ramas nejudecat (vezi numara_in_asteptare)
        surse_cu_pagina  sursele carora li se poate cere pagina publica (din surse.yaml)
        recente          anunturile din ultimele varsta_maxima_zile, cu titlu, firma si
                         data - ca sa se vada ce e repostat (vezi _strange_repostarile)
        agregatori       firmele care repun joburile altora (din surse.yaml), litere mici

    Intoarce dictionarul descris in README-ul functiei de mai jos. Doua lucruri de
    stiut despre ce NU face:

    1. Nu sterge nimic si nu ascunde nimic. Un anunt exclus din "merita_atentie" e
       numarat in "excluse", cu motivul. Briefingul e o distilare, nu o cenzura -
       daca modelul a gresit spunand "relevant: exclus", vrei sa vezi ca s-a intamplat.
    2. Nu inventeaza. Un anunt fara evaluare calitativa nu primeste verdicte
       presupuse; apare cu ce se stie despre el si atat.
    """
    anunturi = date.get("anunturi") or []
    mesaje_noi = date.get("mesaje_noi") or 0

    respinse = [a for a in anunturi if a.get("verdict") == "respins"]
    incerte = [a for a in anunturi if a.get("verdict") == "incert"]

    candidate = [a for a in anunturi if a.get("verdict") in VERDICTE_CANDIDATE]
    de_aratat, excluse = _imparte_candidatele(candidate)
    alese, strase = _strange_repostarile(
        _sorteaza(de_aratat), date.get("recente"), date.get("agregatori")
    )

    return {
        "de_la": date.get("de_la"),
        "mesaje_noi": mesaje_noi,
        "anunturi_noi": len(anunturi),
        "respinse": {
            "total": len(respinse),
            "motive": _numara_motivele(respinse),
        },
        "incerte": len(incerte),
        "merita_atentie": [_rezuma(a) for a in alese[:MAXIM_IN_LISTA]],
        # Cate anunturi n-au primit rand propriu fiindca sunt acelasi job ca unul din
        # lista (acelasi titlu, aceeasi firma). Se numara, nu dispar tacut.
        "repostate_strase": strase,
        "excluse": excluse,
        "fara_evaluare": _numara_neevaluatele(candidate),
        # Ce se stie ca e nejudecat in TOATA baza, nu doar printre noutati - adica de ce
        # briefingul asta poate fi incomplet. Fara stadii primite, iese pe zero: un
        # apelant care nu le da nu primeste o avertizare inventata.
        "in_asteptare": numara_in_asteptare(
            date.get("stadii"), date.get("surse_cu_pagina")
        ),
        # "nimic nou" inseamna ca nu s-a intamplat NIMIC de la ultimul briefing -
        # nici mail, nici anunt. Un briefing cu 12 anunturi din care niciunul nu merita
        # atentie NU e "nimic nou": s-a intamplat ceva, doar ca nimic bun, iar aia e o
        # informatie in sine (poate criteriile sunt prea stramte).
        "nimic_nou": mesaje_noi == 0 and not anunturi,
    }


def alege_oportunitatile(anunturi: list, limita: int, recente=None, agregatori=()) -> list:
    """
    Primele `limita` oportunitati, dupa exact aceleasi reguli ca in briefing.

    DE CE exista separat de compune_briefing, desi face o bucata din el:
    briefingul raspunde la "ce s-a schimbat de la ultima citire" si vine cu cifre,
    respinse, excluse. Uneori vrei doar lista - "arata-mi primele 10 oportunitati" -
    fara raportul din jur.

    Ce NU face: nu redefineste ce inseamna o oportunitate. Cine e candidat, cine se
    exclude si in ce ordine se aseaza sunt aceleasi trei functii folosite de briefing.
    Daca maine se schimba regula (sa zicem, se exclud si anunturile cu interes scazut),
    se schimba intr-un singur loc si amandoua raspund la fel. Doua definitii care se
    despart in timp sunt exact datoria tehnica pe care am scos-o din normalizare.

    `recente` si `agregatori` au acelasi rol ca in compune_briefing: fara ele, pana la
    30 sept. 2026, lista de aici nu arata niciodata "posibil repostat", iar "repostat de
    la" se vedea doar intre anunturile din lista.
    """
    candidate = [a for a in anunturi if a.get("verdict") in VERDICTE_CANDIDATE]
    de_aratat, _ = _imparte_candidatele(candidate)
    alese, _ = _strange_repostarile(_sorteaza(de_aratat), recente, agregatori)
    return [_rezuma(a) for a in alese[:limita]]


def _imparte_candidatele(candidate: list) -> tuple:
    """
    Separa anunturile aratabile de cele excluse. Intoarce (aratabile, numaratoare).

    Se exclude un singur fel de anunt, pe verdictul pe care modelul l-a dat vazand
    criteriile reale: relevant = "exclus" -> executie repetitiva, nu ce cauti.

    NUMAI treapta de jos se exclude. "bun_in_domeniu" ramane in lista, mai jos decat
    "ideal" - asta e tot rostul treptei din mijloc. Un rol senior in domeniu, fara
    automatizare, se vede; nu e ce cauti, dar e ceva ce ai putea citi.

    Rolurile in care ai fi singurul om pe un proces cu termen dur (single_point_of_failure
    = "da") nu se mai exclud: raman in lista, cu avertismentul la vedere (vezi _rezuma).
    """
    aratabile = [a for a in candidate if a.get("relevant") not in RELEVANT_EXCLUS]
    relevant_exclus = len(candidate) - len(aratabile)

    return aratabile, {
        "total": relevant_exclus,
        "relevant_exclus": relevant_exclus,
    }


def _strange_repostarile(sortate: list, recente, agregatori=()) -> tuple:
    """
    Un rand per job, nu per anunt. Intoarce (anunturile alese, cate s-au strans).

    Firmele repun acelasi anunt dupa doua-trei saptamani, cu alt numar, iar agregatorii
    (Undelucram.ro) il repun pe LinkedIn sub numele lor. Pentru agent sunt anunturi noi -
    un anunt repostat ramane un anunt nou in baza (decizie de proiect). Pentru cine
    citeste briefingul, e acelasi job, deja vazut.

    Doua trepte, dupa cat de sigura e potrivirea:
      - acelasi titlu, aceeasi firma = acelasi job. Ramane primul din lista (cel mai bine
        asezat); ceilalti nu mai primesc rand, dar se numara. Randul ramas poarta
        `repostat_de_la`: data primei aparitii.
      - acelasi titlu, alta firma, iar una din cele doua e AGREGATOR (Undelucram.ro, din
        surse.yaml) = POSIBIL acelasi job. Nu se strange; randul poarta doar
        `posibil_repostat`: cealalta firma. Fara agregator, nicio eticheta: un titlu
        generic ("Human Resources Specialist") la sase firme inseamna sase joburi.

    `recente` sunt anunturile din ultimele zile, venite din baza (vezi
    adapters/briefing.py): asa se vede si repostarea unui job aratat intr-un briefing
    trecut, nu doar dublura din briefingul de acum. Potrivirea e pe text identic, dupa
    litere mici si spatii - un titlu usor schimbat la repostare nu se prinde.
    """
    alese = []
    vazute = set()
    for anunt in sortate:
        cheie = (_cheie_text(anunt.get("titlu")), _cheie_text(anunt.get("firma")))
        if cheie not in vazute:
            vazute.add(cheie)
            alese.append(anunt)

    toate = list(sortate) + list(recente or [])
    agregatori = tuple(agregatori or ())
    return (
        [_cu_repostarile(anunt, toate, agregatori) for anunt in alese],
        len(sortate) - len(alese),
    )


def _cu_repostarile(anunt: dict, toate: list, agregatori: tuple) -> dict:
    """Anuntul, plus ce se stie despre celelalte aparitii ale titlului lui."""
    titlu = _cheie_text(anunt.get("titlu"))
    firma = _cheie_text(anunt.get("firma"))
    acelasi_titlu = [
        altul for altul in toate
        if altul.get("id") != anunt.get("id") and _cheie_text(altul.get("titlu")) == titlu
    ]

    aceeasi_firma = [a for a in acelasi_titlu if _cheie_text(a.get("firma")) == firma]
    repostat_de_la = None
    if aceeasi_firma:
        # Doar ziua: ora si fusul nu ajuta la "l-am mai vazut?". Comparatia e pe text
        # ISO, deci doua fusuri diferite pot muta ziua cu una - acceptat, e o eticheta.
        zile = [(a.get("data_anunt") or "")[:10] for a in aceeasi_firma + [anunt]]
        zile = [zi for zi in zile if zi]
        repostat_de_la = min(zile) if zile else None

    alte_firme = sorted({
        (a.get("firma") or "").strip()
        for a in acelasi_titlu
        if _cheie_text(a.get("firma")) not in (firma, "")
        and (firma in agregatori or _cheie_text(a.get("firma")) in agregatori)
    })

    return dict(anunt, repostat_de_la=repostat_de_la, posibil_repostat=alte_firme)


def _cheie_text(text) -> str:
    """Textul pentru comparat: litere mici, spatiile adunate. Nimic ghicit."""
    return " ".join((text or "").lower().split())


def _numara_neevaluatele(candidate: list) -> dict:
    """
    Cate anunturi trecute de filtrul dur nu au o evaluare valabila. Si de ce n-o au.

    LIPSA NU E TACERE - de-asta exista functia asta. Se citesc doar evaluarile date pe
    versiunea de criterii de acum (vezi store/db.py). Cand urci versiunea, TOATE devin
    dintr-o data nevalabile: briefingul ar arata brusc gol, iar cine il citeste ar trage
    concluzia gresita - "nu mai sunt oportunitati" in loc de "nu s-a mai evaluat nimic
    pe criteriile noi". Doua situatii opuse care arata la fel. Deci se numara si se spune.

    Doua cifre, fiindca duc la doua asteptari diferite despre cost:
        niciodata    - n-a existat nicio incercare; evaluarea lui e o cheltuiala noua
        de_reevaluat - a existat una, dar nu mai e buna: ori e de pe alte criterii, ori
                       incercarea a esuat (modelul a raspuns cu JSON stricat). Platesti
                       a doua oara pentru acelasi anunt, si e bine sa se vada.

    DE CE cele doua cauze stau in aceeasi cifra, desi sunt lucruri diferite: cer exact
    aceeasi actiune - o noua evaluare. O a treia cifra ar imparti raportul fara sa
    schimbe ce ai de facut. Numele o spune pe amandoua, ca sa nu para ca stim mai multe
    decat stim.

    Un anunt "fara evaluare" e recunoscut dupa `relevant` gol: interogarile aduc campurile
    calitative doar de pe versiunea curenta, deci gol inseamna exact "n-are verdict pe
    care sa avem voie sa-l citim". `are_evaluare_oarecare` spune care din cele doua cazuri e.
    """
    niciodata = 0
    de_reevaluat = 0

    for anunt in candidate:
        if anunt.get("relevant"):
            continue
        if anunt.get("are_evaluare_oarecare"):
            de_reevaluat += 1
        else:
            niciodata += 1

    return {
        "total": niciodata + de_reevaluat,
        "niciodata": niciodata,
        "de_reevaluat": de_reevaluat,
    }


def numara_in_asteptare(stadii: list, surse_cu_pagina=()) -> dict:
    """
    Cat lucru nefacut sta in baza in momentul citirii. Adica: de ce briefingul poate minti.

    DE CE EXISTA, si de ce nu se poate scoate din briefing:
    dupa reparatia taieturii (vezi ULTIMA_STIRE_DESPRE_ANUNT in store/db.py), o ordine
    gresita a lantului nu mai PIERDE nimic - un anunt evaluat dupa briefing apare data
    viitoare. Dar tot produce un raport care ARATA complet si nu e. Un briefing rulat
    inaintea evaluarii spune "nimic de semnalat" cu acelasi ton cu care l-ar spune dupa
    ce s-a judecat tot. Componenta care nu poate spune tot trebuie sa spuna de ce.

    NU se uita doar la anunturile noi, ci la TOATA baza. O coada de lucru ramasa din
    saptamana trecuta face briefingul de azi la fel de incomplet ca una de acum zece
    minute; reperul temporal n-are nicio legatura cu ea.

    Cele trei feluri de lucru nefacut, fiecare cu aceeasi regula pe care o foloseste
    rularea lui - altfel avertizarea ar spune un numar si rularea ar face altul:

      fara_descriere  sursa are parser, are link, n-are text, nu i s-a luat deja pagina
                      cu succes, si e recent    (vezi alege_anunturile din adapters/descrieri.py)
      nenormalizate   e recent si n-are normalizare cu status "ok"
                      (vezi normalizeaza_lotul din adapters/normalizare.py)
      neevaluate      a trecut filtrul dur ("trece"/"incert") si n-are verdict calitativ
                      pe criteriile de acum
                      (vezi alege_anunturile din adapters/evaluare_calitativa.py)

    Varsta NU intra la evaluare, si nu e o scapare: plasa de varsta sta o singura data,
    sus, la normalizare - la evaluare ajung doar anunturi care au trecut deja pe acolo.

    `recent` se primeste GATA CALCULAT, ca 0/1 pe fiecare stadiu. E singurul lucru pe
    care functia asta nu-l poate decide singura: varsta se masoara fata de ceasul de
    acum, iar fisierul asta nu importa nimic, nici macar `datetime` (vezi antetul). Cine
    cheama pune faptul; regula ramane aici.

    TOTALUL nu e suma celor trei. Un anunt poate astepta si o descriere, si o normalizare
    - e acelasi anunt, si se numara o data. Suma ar spune "95 de anunturi" acolo unde sunt
    60, si ar face avertizarea sa para mai grava decat e.
    """
    permise = tuple((s or "").strip().lower() for s in (surse_cu_pagina or ()))

    nenormalizate = 0
    neevaluate = 0
    fara_descriere = 0
    anunturi_cu_lucru = 0

    for stadiu in stadii or []:
        are_de_facut = False

        if _asteapta_descrierea(stadiu, permise):
            fara_descriere += 1
            are_de_facut = True

        if stadiu.get("recent") and stadiu.get("status_normalizare") != NORMALIZARE_FACUTA:
            nenormalizate += 1
            are_de_facut = True

        if stadiu.get("verdict") in VERDICTE_CANDIDATE and not stadiu.get(
            "are_evaluare_valabila"
        ):
            neevaluate += 1
            are_de_facut = True

        if are_de_facut:
            anunturi_cu_lucru += 1

    return {
        "total": anunturi_cu_lucru,
        "fara_descriere": fara_descriere,
        "nenormalizate": nenormalizate,
        "neevaluate": neevaluate,
    }


def _asteapta_descrierea(stadiu: dict, permise: tuple) -> bool:
    """
    Daca anuntului asta i s-ar cere pagina publica la urmatoarea rulare de descrieri.

    Aceleasi cinci conditii ca in alege_anunturile din adapters/descrieri.py, in aceeasi
    ordine. LinkedIn pica pe prima si nu ajunge niciodata mai departe - nu e in surse,
    deliberat (blocheaza cererile automate, iar noi nu ne deghizam).
    """
    if (stadiu.get("sursa") or "").strip().lower() not in permise:
        return False
    if not stadiu.get("are_link"):
        return False
    if stadiu.get("are_descriere"):
        return False
    if stadiu.get("status_pagina") in PAGINI_INCHISE:
        return False
    return bool(stadiu.get("recent"))


def _sorteaza(anunturi: list) -> list:
    """
    Ordinea in care merita sa te uiti la ele. Complet determinista.

    Prioritatea, in ordine:
        0. coada:                    fara motive_coada inaintea celor cu motive
                                     (birou toata saptamana, salariu sub prag_trecere)
        1. verdictul filtrului dur:  "trece" inaintea lui "incert"
        2. relevanta:                ideal > bun_in_domeniu > incert
        3. interesul:                ridicat > mediu > incert > scazut
        4. cele mai recente primele

    Si un al cincilea, care nu se vede in lista de mai sus fiindca nu e o preferinta,
    ci o necesitate: la egalitate perfecta, ordinea alfabetica a id-ului. Fara el, doua
    anunturi extrase in aceeasi secunda ar putea iesi in orice ordine, iar briefingul
    n-ar mai fi reproductibil - acelasi set de date ar da doua rezultate.

    DE CE TREI SORTARI UNA DUPA ALTA, si nu una singura cu o cheie lunga:
    sensurile difera. La prioritati vrem crescator (rangul 0 e cel mai bun), la data
    descrescator (cel mai nou primul), la id iar crescator. Intr-o singura cheie nu se
    pot amesteca sensurile fara trucuri - de pilda negarea datei, care la text nici nu
    se poate face.

    Se poate insa altfel, si e mai citibil: sortam de la criteriul cel mai putin
    important catre cel mai important. Sortarea din Python e STABILA - adica pastreaza
    ordinea dinainte acolo unde noua cheie da egalitate - deci fiecare sortare
    rearanjeaza doar ce a ramas neclar dupa cea anterioara. Trei randuri, fiecare
    evident, in locul unei expresii pe care ar trebui s-o descifrezi.
    """
    dupa_id = sorted(anunturi, key=lambda a: a.get("id") or "")
    dupa_data = sorted(
        dupa_id, key=lambda a: a.get("data_extragere") or "", reverse=True
    )
    return sorted(
        dupa_data,
        key=lambda a: (
            1 if a.get("motive_coada") else 0,
            _rang(RANG_VERDICT, a.get("verdict")),
            _rang(RANG_RELEVANT, a.get("relevant")),
            _rang(RANG_INTERES, a.get("interes")),
        ),
    )


def _rang(tabel: dict, valoare) -> int:
    """
    Rangul unei valori. Ce nu e in tabel ajunge la coada, nu la cap.

    Conteaza pentru anunturile inca neevaluate, unde valoarea e None: le vrem ultimele
    dintre cele aratate, nu primele. Daca necunoscutul ar primi rangul 0, un anunt
    despre care nu stim nimic ar sari peste unul pe care modelul l-a numit relevant.
    """
    return tabel.get(valoare, len(tabel))


def _rezuma(anunt: dict) -> dict:
    """
    Din randul intreg al unui anunt, cele sapte campuri care intra in briefing.

    `singur_pe_proces` e verdictul modelului ("da", "nu", "incert"; None daca anuntul
    nu e evaluat): ai fi singurul om pe un proces cu termen dur? Nu mai exclude
    anuntul, dar ramane de stiut inainte sa-l citesti.

    `la_coada` spune de ce anuntul a fost pus la coada (lista goala = nu e la coada).
    Fara el, un anunt bun asezat ultimul s-ar citi ca unul slab.

    `motiv` e justificarea aratata omului. Luam motivarea relevantei, fiindca ea
    raspunde la intrebarea "de ce asta si nu altul". Daca lipseste (anunt netrecut inca
    prin evaluarea calitativa), spunem exact asta - nu inventam o motivare si nu lasam
    campul gol, care s-ar citi ca "n-a avut niciun motiv".
    """
    motiv = (anunt.get("motiv_relevanta") or "").strip()
    if not motiv:
        # Doua feluri de a nu avea motivare, si nu e totuna: unul asteapta o evaluare,
        # celalalt are una care nu mai e valabila. Cine citeste trebuie sa stie care.
        if anunt.get("are_evaluare_oarecare"):
            motiv = "a trecut filtrul dur, fara verdict pe criteriile de acum"
        else:
            motiv = "a trecut filtrul dur, inca neevaluat calitativ"

    return {
        "id": anunt.get("id"),
        "titlu": anunt.get("titlu"),
        "firma": anunt.get("firma"),
        "motiv": motiv,
        "link": anunt.get("link"),
        "singur_pe_proces": anunt.get("single_point_of_failure"),
        "la_coada": list(anunt.get("motive_coada") or []),
        "repostat_de_la": anunt.get("repostat_de_la"),
        "posibil_repostat": list(anunt.get("posibil_repostat") or []),
    }


def _numara_motivele(respinse: list) -> dict:
    """
    Cate anunturi au picat pe fiecare fel de motiv.

    Un anunt poate pica pe mai multe motive deodata (si locatie, si un cuvant exclus).
    Se numara la fiecare, deci suma poate depasi totalul respinselor. E corect asa:
    intrebarea la care raspunde numaratoarea e "ce taie cel mai des", nu "cum se imparte
    totalul".

    Ordinea: cele mai multe intai, iar la egalitate alfabetic. A doua parte pare
    marunta, dar fara ea doua motive cu acelasi numar ar putea iesi in orice ordine,
    si acelasi briefing ar arata diferit la doua rulari.
    """
    numarate = {}
    for anunt in respinse:
        for motiv in anunt.get("motive_respingere") or []:
            eticheta = _eticheta_motiv(motiv)
            numarate[eticheta] = numarate.get(eticheta, 0) + 1

    return dict(sorted(numarate.items(), key=lambda pereche: (-pereche[1], pereche[0])))


def _eticheta_motiv(motiv: str) -> str:
    """
    Scurteaza un motiv de respingere la o eticheta buna de numarat.

    Motivele arata asa:
        "venit sub pragul de respingere: max 4200 < 5000 RON ('4000 - 4200 RON')"
        "locatie in afara zonei: 'Bucuresti' (onsite), baza e Brasov"
        "cuvant gasit: 'on-call' (in titlu)"

    La primele doua luam partea dinaintea celor doua puncte si o scurtam prin
    ETICHETE_MOTIVE. La al treilea, eticheta utila e chiar CUVANTUL gasit - "on-call"
    spune ceva, "cuvant gasit" nu spune nimic - asa ca il scoatem dintre apostrofuri.

    Daca formularea din core/filtrare.py se schimba, etichetele nerecunoscute trec mai
    departe asa cum sunt, intregi. Nu se pierd si nu se amesteca intr-un "altele" care
    ar ascunde schimbarea: un briefing cu o eticheta lunga si ciudata se vede imediat.
    """
    inainte_de_detaliu = motiv.split(":", 1)[0].strip().lower()

    if inainte_de_detaliu == "cuvant gasit":
        intre_apostrofuri = motiv.split("'")
        if len(intre_apostrofuri) >= 2:
            return intre_apostrofuri[1]
        return "cuvant exclus"

    return ETICHETE_MOTIVE.get(inainte_de_detaliu, inainte_de_detaliu)


def formateaza_text(briefing: dict) -> str:
    """
    Briefingul ca text scurt, de citit dintr-o privire. Intre 1 si 9 randuri: antetul,
    randul filtrului, eventual "fara verdict", cel mult MAXIM_IN_TEXT anunturi, "...si
    inca N", repostarile stranse, si randul de avertizare cand e ceva in asteptare.

    Sablon fix, fara model. Acelasi briefing da acelasi text de fiecare data - ceea ce
    inseamna ca poti pune doua rulari una langa alta si diferentele sunt reale, nu
    variatii de formulare.

    Cand nu e nimic nou, iese O SINGURA propozitie. Nu un raport cu zerouri: un om care
    citeste "0 mesaje, 0 anunturi, 0 respinse" trebuie sa parcurga trei randuri ca sa
    afle ca nu s-a intamplat nimic. Un rand ajunge.

    In text intra cel mult MAXIM_IN_TEXT anunturi, desi structura are pana la
    MAXIM_IN_LISTA. Cine vrea lista intreaga o are in dictionar; textul e pentru
    privirea de trei secunde.

    ULTIMUL RAND, cand exista lucru nefacut, spune ca briefingul e incomplet. Apare si
    peste "nimic nou" - acolo e chiar cel mai necesar: "nimic nou" plus o coada de 25 de
    anunturi nejudecate se citeste, altfel, ca "nu mai e nimic de gasit".
    """
    perioada = _perioada(briefing.get("de_la"))

    if briefing.get("nimic_nou"):
        return _cu_avertisment(
            [f"Nimic nou {perioada}: niciun mesaj si niciun anunt."], briefing
        )

    # DE CE scriem "mesaje noi: 1" si nu "1 mesaje noi":
    # a doua forma cere acord la plural, deci o regula in cod care sa aleaga intre
    # "1 mesaj nou" si "2 mesaje noi" - pentru fiecare substantiv din sablon. Cu numarul
    # dupa eticheta, aceeasi propozitie e corecta la orice cifra, inclusiv la zero, si
    # nu e nevoie de nicio regula. Mai putin literar, dar corect de fiecare data.
    randuri = [
        f"Briefing {perioada} — mesaje noi: {briefing['mesaje_noi']}, "
        f"anunturi noi: {briefing['anunturi_noi']}."
    ]

    respinse = briefing.get("respinse") or {}
    rand_filtru = f"Respinse de filtrul dur: {respinse.get('total', 0)}"
    motive = respinse.get("motive") or {}
    if motive:
        detaliu = ", ".join(f"{eticheta} {n}" for eticheta, n in motive.items())
        rand_filtru += f" ({detaliu})"
    rand_filtru += f". Incerte: {briefing.get('incerte', 0)}."
    randuri.append(rand_filtru)

    # LIPSA EVALUARILOR SE SPUNE, nu se trece sub tacere. Dupa o urcare de versiune de
    # criterii, toate evaluarile vechi devin nevalabile deodata - iar un briefing care
    # tace ar arata identic cu unul care n-a gasit nimic bun. Randul asta e diferenta
    # dintre "nu sunt oportunitati" si "nu s-a evaluat inca nimic pe criteriile noi".
    fara = briefing.get("fara_evaluare") or {}
    if fara.get("total"):
        detaliu = []
        if fara.get("niciodata"):
            detaliu.append(f"neevaluate: {fara['niciodata']}")
        if fara.get("de_reevaluat"):
            detaliu.append(f"de reevaluat: {fara['de_reevaluat']}")
        randuri.append(
            f"Fara verdict pe criteriile de acum: {fara['total']} ({', '.join(detaliu)})."
        )

    lista = briefing.get("merita_atentie") or []
    excluse = (briefing.get("excluse") or {}).get("total", 0)

    if not lista:
        coada = f" ({excluse} excluse ca executie repetitiva)" if excluse else ""
        randuri.append(f"Nimic de semnalat{coada}.")
        return _cu_avertisment(randuri, briefing)

    for anunt in lista[:MAXIM_IN_TEXT]:
        atentie = " [singur pe proces]" if anunt.get("singur_pe_proces") == "da" else ""
        if anunt.get("la_coada"):
            atentie += f" [la coada: {'; '.join(anunt['la_coada'])}]"
        if anunt.get("repostat_de_la"):
            atentie += f" [repostat, apare din {anunt['repostat_de_la']}]"
        if anunt.get("posibil_repostat"):
            atentie += f" [posibil repostat: {', '.join(anunt['posibil_repostat'])}]"
        randuri.append(
            f"  - {anunt['titlu']} ({anunt['firma']}){atentie}: {_scurteaza(anunt['motiv'])}"
        )

    nespuse = len(lista) - MAXIM_IN_TEXT
    if nespuse > 0:
        randuri.append(f"  ... si inca {nespuse} in lista completa.")
    if briefing.get("repostate_strase"):
        randuri.append(
            f"  Repostari stranse sub acelasi rand: {briefing['repostate_strase']}."
        )

    return _cu_avertisment(randuri, briefing)


def _cu_avertisment(randuri: list, briefing: dict) -> str:
    """
    Textul briefingului, plus randul de avertizare - daca e ceva de avertizat.

    Trece prin functia asta FIECARE iesire din formateaza_text, si de aia exista: cu
    avertizarea lipita la trei locuri diferite, era chestiune de timp pana cand un drum
    nou ar fi iesit fara ea. Tacerea s-ar fi vazut cel mai greu exact acolo unde conteaza
    cel mai mult - pe "nimic nou".

    Cand nu e nimic in asteptare, nu se adauga nimic. Un briefing pe o baza asezata nu
    poarta un rand care spune ca totul e in regula: linistea e mesajul.
    """
    asteptare = briefing.get("in_asteptare") or {}
    if not asteptare.get("total"):
        return "\n".join(randuri)
    return "\n".join(randuri + [_rand_in_asteptare(asteptare)])


def _rand_in_asteptare(asteptare: dict) -> str:
    """
    Randul care spune ca briefingul e incomplet, cu ce anume lipseste.

    Se numesc doar felurile care chiar au ceva - un "neevaluate: 0" ar face randul mai
    lung fara sa adauge nimic.

    "eticheta: numar", ca peste tot in textul asta, si din acelasi motiv: forma "10
    anunturi neevaluate" ar cere acord la plural ("1 anunt", "20 DE anunturi"), adica o
    regula de gramatica scrisa in cod pentru fiecare substantiv. Asa, aceeasi propozitie
    e corecta la orice cifra.
    """
    detaliu = ", ".join(
        f"{eticheta}: {asteptare[cheie]}"
        for cheie, eticheta in ETICHETE_ASTEPTARE
        if asteptare.get(cheie)
    )
    return f"Atentie, briefingul e incomplet — {detaliu}."


def _perioada(de_la) -> str:
    """
    Cum se numeste in text intervalul raportat.

    Fara reper (primul briefing), spunem "de la inceput" - nu o data inventata si nu
    un camp gol. E singurul caz in care briefingul acopera toata baza, si cine il
    citeste trebuie sa stie asta, altfel cifrele par alarmante.

    Data se scurteaza la minut: "2026-07-20T08:00:00+00:00" devine "2026-07-20 08:00".
    Secundele si fusul nu ajuta pe nimeni intr-un rand citit dintr-o privire, iar
    reperul exact ramane oricum intreg in structura, la cheia "de_la".

    Taierea e pe pozitii fixe, nu pe interpretare de data - ar fi cerut `datetime`, iar
    modulul asta nu importa nimic (vezi antetul fisierului). Daca reperul n-ar avea
    forma ISO obisnuita, iese un text mai ciudat, dar nimic nu crapa.
    """
    if not de_la:
        return "de la inceput"
    return f"de la {de_la[:16].replace('T', ' ')}"


def _scurteaza(text: str, maxim: int = 90) -> str:
    """Taie o motivare prea lunga, ca randul sa ramana citibil dintr-o privire."""
    text = (text or "").strip()
    if len(text) <= maxim:
        return text
    return text[: maxim - 1].rstrip() + "…"
