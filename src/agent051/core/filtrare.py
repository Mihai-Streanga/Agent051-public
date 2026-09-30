"""
Filtrul determinist: taie ce incalca o constrangere dura, fara sa intrebe niciun model.

RELEVANTA ARE DOUA STRATURI, si asta e primul.
Intai regulile: salariu sub prag, oras gresit, ture de noapte, o limba pe care n-o
vorbesti ceruta chiar din titlu. Alea nu sunt pareri,
sunt fapte - se citesc din anunt si dau acelasi raspuns de fiecare data. Abia ce trece
de aici ajunge, mai tarziu, la model. Modelul nu vede niciodata un anunt pe care o
regula il respinge deja.

De ce in ordinea asta si nu invers: un model chemat pe 300 de anunturi costa de 300 de
ori. Daca 200 dintre ele incalca deja o regula certa, ai platit degeaba pentru 200 de
opinii despre joburi pe care nu le-ai fi luat oricum. Dar motivul principal nu e banul,
e consistenta: un prag de 5000 de lei nu are voie sa dea raspunsuri diferite la doua
rulari. O regula in cod nu are toane.

CE NU SE DECIDE AICI, dinadins:
"e rolul interesant?" si "sunt eu singurul punct de esec pe procesul asta?" NU sunt
deterministe. Nu se vad dintr-un cuvant-cheie, se vad citind anuntul cu cap. Alea sunt
pentru model, in bucata 2. Aici tratam doar ce se poate taia cu o regula certa.

REGULA CARE GUVERNEAZA TOT FISIERUL:
    lipsa unei date nu e nici "da", nici "nu". E "nu stiu".
Dar nu orice "nu stiu" cantareste la fel. Un necunoscut poate fi:

  - BLOCANT: fara data aia chiar nu putem spune daca anuntul respecta o constrangere
    dura. Lipsa locatiei sau a felului muncii intra aici - nu poti sti daca un rol e
    in orasul tau sau te scoate din el. La fel, o sectiune lipsa din criterii.yaml:
    inseamna ca o regula dura e tacut dezactivata, si aia e o defectiune, nu un "trece".
    Un necunoscut blocant opreste verdictul "trece" -> anuntul iese "incert".

  - NEBLOCANT: se noteaza, dar nu impiedica "trece". Salariul neafisat e cazul tipic.
    In Romania salariul lipseste din aproape orice anunt; daca lipsa lui ar bloca,
    NICIUN anunt n-ar trece vreodata, si filtrul n-ar mai filtra nimic. Un anunt remote
    fara salariu afisat trebuie sa iasa "trece", cu nota "salariu necunoscut" alaturi -
    nu "incert". Salariul lipsa NU respinge (poate platea bine) si NU trece pe venit
    (n-avem cifra) - pur si simplu nu se pronunta pe venit, si lasa restul sa decida.

A ghici in favoarea noastra iti umple lista de joburi proaste; a ghici impotriva iti
arunca joburi bune la gunoi, si pe alea nu le mai vezi niciodata ca sa observi eroarea.
De-aia salariul lipsa nu ghiceste in niciun sens: nici nu taie, nici nu blocheaza.

Fisierul asta e pur: importurile de mai jos sunt `re`, din Python, si
`core/text.py`, tot pur. Criteriile se PRIMESC ca dictionar - citirea lor din config/criterii.yaml e IO
si sta in adapters/filtrare.py.
"""

import re

from agent051.core.text import fara_diacritice

# Campurile din anunt in care se cauta cuvintele excluse.
#
# `descriere` a fost adaugata in Etapa 2 (bucata 1B): pana atunci filtrul vedea doar
# titlul, deci "on-call" scris in corpul cardului, nu in titlu, ii scapa. Acum cauta
# si acolo. Motivul respingerii spune in ce camp a gasit cuvantul, deci se vede
# imediat daca a picat pe titlu sau pe descriere.
#
# Toate patru sunt text scris de ANGAJATOR (rol_normalizat e titlul lui, doar
# standardizat). Proza produsa de model nu se cauta niciodata aici, oricat ar fi de
# la indemana: daca modelul scrie "rolul nu pare sa implice ture", cuvantul "ture"
# apare in text - si anuntul ar fi respins pentru exact opusul a ce spune fraza.
# Regula a fost scrisa pe vremea campului `motiv_relevanta` (intre timp scos din
# normalizare) si ramane valabila pentru orice motivare adaugata in viitor.
#
# `corp_text` A FOST SCOS de aici pe 17 august 2026, si merita spus de ce, ca sa nu fie
# pus la loc: e numele corpului INTREG al mailului, iar un mail de alerta contine intre
# 5 si 20 de joburi. Niciun apelant nu-l punea - `anunturi_de_filtrat()` aduce
# `a.descriere`, adica textul unui singur anunt - deci campul era inert. Dar inert nu e
# inofensiv: cine ar alimenta maine filtrul cu corpul mailului ar respinge un anunt bun
# pentru cuvinte care apartin ALTUI job din acelasi mail, iar motivul respingerii ar
# arata perfect plauzibil. Un camp cautat aici trebuie sa fie text despre ACEST anunt.
CAMPURI_DE_CAUTAT = ("titlu", "rol_normalizat", "descriere")


def filtreaza_dur(anunt_normalizat: dict, criterii: dict) -> dict:
    """
    Trece un anunt normalizat prin constrangerile dure. Intoarce un verdict.

    anunt_normalizat - dictionarul anuntului: titlu, locatie, tip_munca,
                       rol_normalizat, si (cand exista) descriere si salariu_brut
    criterii         - continutul lui criterii.yaml, ca dictionar. INJECTAT, nu citit
                       de aici: citirea unui fisier e IO si nu are ce cauta in core/.

    Intoarce:
    {
        "verdict": "trece" | "respins" | "incert",
        "motive_respingere": [...],   ce constrangere dura a picat, cu detaliu
        "necunoscute": [...],         ce n-a putut fi evaluat, din lipsa de date
    }

    Cum se decide verdictul, in ordinea asta:
        exista macar un motiv de respingere       -> "respins"
        nu, dar lipseste o data BLOCANTA           -> "incert"
        nimic incalcat, nimic blocant lipsa        -> "trece"

    Atentie: un necunoscut NEBLOCANT (tipic: salariu neafisat) NU produce "incert".
    Se raporteaza in `necunoscute` ca nota, dar lasa verdictul "trece". Un anunt
    remote, curat, fara salariu afisat, iese "trece" - cu "salariu neafisat" scris
    alaturi. Vezi regula centrala din capul fisierului pentru de ce.

    Respingerea bate necunoscutul, si e corect asa: daca anuntul spune limpede
    "Bucuresti, on-site", faptul ca nu-si declara salariul nu-l mai salveaza. O
    constrangere dura incalcata cu date certe inchide discutia.

    Dar invers nu e adevarat: `necunoscute` se raporteaza SI la anunturile respinse,
    blocante si neblocante la un loc. Daca maine descoperi ca respingerea a fost un
    fals pozitiv, vrei sa stii din prima ce altceva nu se stia despre anuntul ala.
    """
    motive_respingere = []
    blocante = []
    neblocante = []

    dure = (criterii.get("constrangeri_dure") or {})

    for verifica in (
        _verifica_venitul,
        _verifica_locatia,
        _verifica_cuvintele_excluse,
        _verifica_limbile,
        _verifica_tara,
    ):
        motive, blk, neblk = verifica(anunt_normalizat, dure)
        motive_respingere.extend(motive)
        blocante.extend(blk)
        neblocante.extend(neblk)

    if motive_respingere:
        verdict = "respins"
    elif blocante:
        verdict = "incert"
    else:
        verdict = "trece"

    return {
        "verdict": verdict,
        "motive_respingere": motive_respingere,
        # Blocantele intai: alea sunt cele care au produs verdictul, deci se citesc
        # primele in raport. Neblocantele vin dupa, ca note. Ambele intra in baza -
        # distinctia blocant/neblocant e o decizie de verdict, nu se pastreaza separat.
        "necunoscute": blocante + neblocante,
        "motive_coada": _motive_de_coada(anunt_normalizat, dure),
    }


def _verifica_tara(anunt: dict, dure: dict):
    """
    Tara locului de munca, din datele structurate ale paginii, fata de tara_firma.permis.

    Intoarce trei liste: (motive_respingere, blocante, neblocante).

    `tari_din_pagina` vine din core/descriere.py (tarile_din_pagina), pus de adaptor.
    Lipsa lui nu e un necunoscut: majoritatea anunturilor n-au pagina, iar tara
    necunoscuta nu respinge (decizie de proiect). Se respinge doar cand pagina spune
    limpede o alta tara. Tara FIRMEI nu apare in date - vezi criterii.yaml.
    """
    tari = anunt.get("tari_din_pagina") or []
    if not tari:
        return [], [], []

    permise = ((dure.get("locatie") or {}).get("tara_firma") or {}).get("permis")
    if not permise:
        return [], ["tara permisa lipsa din criterii.yaml"], []

    straine = [tara for tara in tari if tara not in permise]
    if straine:
        return [f"tara in afara zonei: {', '.join(straine)} (din pagina)"], [], []
    return [], [], []


def _motive_de_coada(anunt: dict, dure: dict) -> list:
    """
    De ce un anunt care NU e respins merge totusi la coada briefingului.

    Doua reguli din criterii.yaml, hotarate ca "trece, dar la coada" - nu ca respingeri:
      - biroul toata saptamana ("onsite", fara hibrid), cand criteriile accepta cel
        mult onsite_max_zile_saptamana zile. Cate zile cere un "hibrid" nu stim din
        date, deci hibridul nu merge la coada.
      - salariul sub prag_trecere, dar nu sub prag_respingere (acela respinge).

    Lista goala = anuntul isi pastreaza locul. Ordinea o face core/briefing.py.
    """
    motive = []

    locatie = (dure.get("locatie") or {})
    maxim_zile = locatie.get("onsite_max_zile_saptamana")
    tip_munca = (anunt.get("tip_munca") or "").strip().lower()
    if tip_munca == "onsite" and maxim_zile is not None:
        motive.append(f"birou toata saptamana, peste {maxim_zile} zile")

    prag = (dure.get("venit_net_lunar_ron") or {}).get("prag_trecere")
    maxim = _maxim_lunar_in_ron(anunt.get("salariu_brut") or "")
    if prag is not None and maxim is not None and maxim < prag:
        motive.append(f"salariu sub {prag} RON: max {maxim}")

    return motive


def _maxim_lunar_in_ron(text: str):
    """
    Cel mai mare numar din salariu, DOAR daca e sigur un salariu lunar in RON; altfel None.

    Aceleasi conditii ca in _verifica_venitul: fara valuta straina, fara ora/an, cu RON
    scris explicit. Ce nu se poate compara cu un prag in RON nu merge nici la coada.
    """
    brut = text.strip()
    numere = _numere_din_salariu(brut)
    if not numere:
        return None
    if _VALUTA_STRAINA.search(brut) or _ALTA_UNITATE.search(brut):
        return None
    if not _MONEDA_RON.search(brut):
        return None
    return max(numere)


# Semnale in textul de salariu care il fac NECOMPARABIL cu un prag lunar in RON.
#
# Valuta straina: pragul e in RON. "605 €" ar avea numarul 605, sub 5000 - dar 605 €
# sunt ~3000 RON, iar conversia depinde de un curs care se schimba zilnic. Sa comparam
# ar insemna sa ghicim cursul; nu ghicim. (In arhiva de fata, TOATE salariile afisate
# sunt in euro - deci fara regula asta filtrul ar respinge gresit aproape fiecare.)
_VALUTA_STRAINA = re.compile(r"[€$£]|\b(eur|usd|gbp|chf)\b", re.IGNORECASE)

# Alta unitate de timp decat luna: pragul e LUNAR. "50 RON/ora" are numarul 50, sub
# prag - dar inseamna ~8000 RON/luna. Sa comparam un salariu pe ora sau pe an cu un
# prag pe luna ar taia gresit joburi bune. Necomparabil -> necunoscut.
_ALTA_UNITATE = re.compile(
    r"/\s*(ora|or[ăa]|h|an|year|yr)\b|pe\s+(ora|or[ăa]|an)\b|"
    r"\b(anual|annual|hourly|yearly)\b|per\s+(hour|year)",
    re.IGNORECASE,
)

# Moneda in RON, spusa explicit. Fara ea nu stim in ce e exprimat numarul, deci nu
# avem voie sa-l comparam cu un prag in RON.
_MONEDA_RON = re.compile(r"\bron\b|\blei\b", re.IGNORECASE)

# Un numar din text, cu eventuali separatori de mii ("3.000", "3 000", "3,000").
_NUMAR = re.compile(r"\d[\d.\s,]*\d|\d")


def _numere_din_salariu(text: str):
    """
    Toate numerele din textul de salariu, ca intregi. "1600 - 1900" -> [1600, 1900].

    Tratam punctul, virgula si spatiul ca separatori de mii si ii aruncam: salariile
    se scriu in mii intregi ("3.000 RON"), nu cu zecimale. Nu incercam sa fim mai
    destepti de-atat - un numar in plus, ratacit, nu strica: respingerea se uita la
    MAXIM, iar un numar mic ratacit nu ridica maximul.
    """
    numere = []
    for bucata in _NUMAR.findall(text):
        doar_cifre = re.sub(r"\D", "", bucata)
        if doar_cifre:
            numere.append(int(doar_cifre))
    return numere


def _verifica_venitul(anunt: dict, dure: dict):
    """
    Salariul fata de pragul de respingere din criterii, citit din textul BRUT.

    Intoarce trei liste: (motive_respingere, blocante, neblocante).

    Salariul intra ca text, exact cum l-a scris platforma ("1600 - 1900€",
    "2500 RON", "salariu motivant"). Il interpretam AICI, determinist, si respingem
    DOAR cand suntem siguri ca e sub prag. In rest: necunoscut, nu respins.

    UN SINGUR necunoscut de-aici e BLOCANT - "prag salarial lipsa din criterii.yaml".
    Acela nu e o data lipsa din anunt, ci o regula dura tacut dezactivata: o defectiune
    de configurare, care trebuie sa opreasca "trece". Toate celelalte necunoscute de-aici
    sunt legate de salariul din ANUNT si sunt NEBLOCANTE: salariul lipseste din aproape
    orice anunt romanesc, si daca lipsa lui ar bloca, filtrul n-ar mai lasa nimic sa treaca.

    Cum decidem, in ordine - fiecare "necunoscut" spune de ce, ca sa se vada in raport:
      0. prag lipsa din criterii   -> BLOCANT (regula dura dezactivata, defectiune)
      1. fara text                 -> neafisat            (neblocant)
      2. fara nicio cifra          -> neinterpretabil     (neblocant: "negociabil")
      3. valuta straina            -> necomparabil in RON (neblocant, nu ghicim cursul)
      4. pe ora / pe an            -> necomparabil lunar  (neblocant)
      5. fara moneda RON explicita -> nu stim in ce e     (neblocant)
      6. numere in RON, pe luna    -> respins DOAR daca maximul e sub prag

    DE CE respingem pe MAXIMUL numerelor, si numai sub prag: daca nici capatul de sus
    al intervalului nu atinge pragul (ex. "2500 - 3500 RON", prag 5000), atunci orice
    ar oferi firma e sub prag - certitudine. Daca maximul atinge sau depaseste pragul,
    NU respingem: poate plati si peste. Un rol plictisitor la 12000 e tot respins, dar
    de catre model, mai incolo. Vezi nota_stres din criterii.yaml.
    """
    venit = (dure.get("venit_net_lunar_ron") or {})
    prag = venit.get("prag_respingere")

    if prag is None:
        # Nu putem verifica o regula pe care configurarea nu o defineste. NU tratam
        # asta ca "totul e in regula", dar nici ca "salariu lipsa" - e o defectiune de
        # config, nu o data lipsa din anunt. O regula dura tacut dezactivata e exact
        # felul de eroare care nu se observa luni de zile, deci BLOCHEAZA "trece".
        return [], ["prag salarial lipsa din criterii.yaml"], []

    brut = (anunt.get("salariu_brut") or "").strip()

    if not brut:
        # Cazul cel mai frecvent din Romania. NEBLOCANT: se noteaza, nu opreste "trece".
        return [], [], ["salariu neafisat in anunt"]

    numere = _numere_din_salariu(brut)
    if not numere:
        # Text fara nicio cifra ("negociabil", "salariu motivant", "competitiv"). Nu
        # ghicim ce inseamna - il spunem pe litere, ca sa vezi ce fel de valori vin.
        return [], [], [f"salariu neinterpretabil ca numar: '{brut}'"]

    if _VALUTA_STRAINA.search(brut):
        return [], [], [f"salariu in valuta straina, necomparabil cu pragul in RON: '{brut}'"]

    if _ALTA_UNITATE.search(brut):
        return [], [], [f"salariu pe alta unitate decat luna, necomparabil: '{brut}'"]

    if not _MONEDA_RON.search(brut):
        return [], [], [f"salariu fara moneda RON explicita, necomparabil: '{brut}'"]

    maxim = max(numere)
    if maxim < prag:
        return (
            [f"venit sub pragul de respingere: max {maxim} < {prag} RON ('{brut}')"],
            [],
            [],
        )

    return [], [], []


def _verifica_locatia(anunt: dict, dure: dict):
    """
    Locatia fata de orasul de baza, tinand cont de felul muncii.

    Intoarce trei liste: (motive_respingere, blocante, neblocante).

    Necunoscutele de-aici sunt TOATE blocante, si e firesc: fara sa stii unde se
    lucreaza - sau macar ca e remote - nu poti spune daca rolul te tine in orasul tau
    sau te scoate din el. Aia e chiar constrangerea dura pe care o verificam. La fel,
    o sectiune lipsa din criterii ("oras de baza lipsa") e o regula tacut dezactivata.
    Spre deosebire de salariu, care e neblocant, aici lipsa datei chiar impiedica
    verdictul.

    Ordinea intrebarilor conteaza:
      1. E remote? Atunci orasul firmei nu mai are importanta - criterii.yaml spune
         explicit remote_locatie_firma_irelevanta. Trece, indiferent de oras.
      2. Nu stim orasul de baza din criterii? BLOCANT (config stricat).
      3. Nu stim locatia anuntului? BLOCANT.
      4. E orasul de baza? Trece.
      5. E alt oras SI stim ca se lucreaza de la birou (onsite/hibrid)? Respins.
      6. E alt oras dar NU stim cum se lucreaza? BLOCANT - vezi mai jos.

    CAZUL 6 E O DECIZIE, nu o scapare. Un anunt care scrie "Bucuresti" fara sa spuna
    cum se lucreaza poate fi foarte bine un rol remote listat pe sediul firmei - se
    intampla tot timpul pe platforme. Daca l-am respinge, am arunca joburi bune fara
    sa aflam vreodata, fiindca un anunt respins nu se mai uita nimeni la el. Iese
    "incert" si il vezi tu. Costul e o listare in plus de citit; celalalt cost ar fi
    fost o oportunitate pierduta in tacere.
    """
    locatie_criterii = (dure.get("locatie") or {})
    oras_baza = locatie_criterii.get("baza")
    tip_munca = (anunt.get("tip_munca") or "").strip().lower()

    if tip_munca == "remote":
        if locatie_criterii.get("remote_acceptat"):
            return [], [], []
        return ["rolul e remote, dar criteriile nu accepta remote"], [], []

    if oras_baza is None:
        return [], ["oras de baza lipsa din criterii.yaml"], []

    locatie = (anunt.get("locatie") or "").strip()
    if not locatie:
        return [], ["locatie neprecizata in anunt"], []

    if fara_diacritice(oras_baza) in fara_diacritice(locatie):
        return [], [], []

    # Alt oras. Daca stim sigur ca se lucreaza de la birou, e o incalcare certa:
    # criterii.yaml spune mutare_alt_oras: false.
    if tip_munca in ("onsite", "hibrid"):
        return (
            [f"locatie in afara zonei: '{locatie}' ({tip_munca}), baza e {oras_baza}"],
            [],
            [],
        )

    return [], [f"locatie '{locatie}' in alt oras, dar felul muncii e neprecizat"], []


def _verifica_cuvintele_excluse(anunt: dict, dure: dict):
    """
    Cauta cuvintele care descalifica un rol (azi: ture, schimburi - lista e in criterii.yaml).

    Intoarce trei liste: (motive_respingere, blocante, neblocante).

    Singurul necunoscut de-aici - lista de cuvinte lipsa din criterii - e BLOCANT:
    e o constrangere dura tacut dezactivata, aceeasi specie de defectiune ca pragul
    salarial lipsa. Fara lista, filtrul nu mai taie niciun "on-call", deci nu are voie
    sa spuna "trece" ca si cum ar fi verificat.

    Motivul spune EXACT ce cuvant a declansat respingerea si in ce camp. Fara asta,
    "respins pe structura rolului" e o afirmatie pe care nu o poti verifica - si un
    filtru pe care nu-l poti verifica e un filtru in care nu ai cum sa ai incredere.
    Cu cuvantul la vedere, te uiti o data in lista de respinse si vezi imediat daca
    a taiat ce trebuia.

    Cautam cuvinte INTREGI. Fara asta, "ture" ar prinde "structure" si "future", iar
    filtrul ar respinge jumatate din anunturile scrise in engleza - tacut, si cu un
    motiv care ar parea perfect rezonabil in raport.
    """
    rol = (dure.get("rol_structura") or {})
    cuvinte = rol.get("cuvinte_excluse")

    if not cuvinte:
        return [], ["lista de cuvinte excluse lipsa din criterii.yaml"], []

    motive = []
    for camp in CAMPURI_DE_CAUTAT:
        text = anunt.get(camp)
        if not text:
            continue

        for cuvant in cuvinte:
            if _contine_cuvantul(str(text), str(cuvant)):
                motive.append(f"cuvant gasit: '{cuvant}' (in {camp})")

    return motive, [], []


# Campul in care se cauta cererea de limba straina. UNUL SINGUR, si e o decizie.
#
# In TITLU, "(with German)" inseamna fara discutie ca limba e obligatorie - nimeni nu
# scrie o limba in titlu ca s-o considere optionala. In DESCRIERE, aceeasi germana poate
# fi "germana obligatorie" sau "germana e un plus" - doua lucruri opuse, care nu se
# deosebesc dintr-un cuvant, ci citind fraza. Aia e judecata, deci merge la model
# (vezi limbile vorbite trimise in promptul calitativ), nu la o regula determinista.
#
# Nici `rol_normalizat` nu se cauta aici, desi e tot un titlu: e titlul rescris de model,
# iar un model poate scoate "(with German)" cand standardizeaza. O regula dura nu se
# sprijina pe text produs de model - acelasi rationament ca la CAMPURI_DE_CAUTAT.
CAMP_PENTRU_LIMBI = "titlu"


def _verifica_limbile(anunt: dict, dure: dict):
    """
    Cauta in TITLU cererea unei limbi pe care nu o vorbesti.

    Intoarce trei liste: (motive_respingere, blocante, neblocante).

    De ce e o constrangere dura si nu un semnal calitativ: fara limba nu poti face jobul,
    oricat de bine s-ar potrivi restul. Un "Senior Business Partner - HR Development
    (with German)" nu e o potrivire mai slaba, e o imposibilitate.

    Singurul necunoscut de-aici - sectiunea `limbi` lipsa din criterii - e BLOCANT,
    aceeasi specie de defectiune ca pragul salarial lipsa: o regula dura tacut
    dezactivata nu are voie sa se prefaca in "trece".

    Motivul spune si LIMBA, si TIPARUL care a declansat-o, ca sa poti verifica dintr-o
    privire daca a taiat ce trebuia. Un filtru pe care nu-l poti verifica e un filtru in
    care nu ai cum sa ai incredere.

    O limba se raporteaza O SINGURA DATA, chiar daca titlul o cere in doua feluri
    ("German speaker with German"): motivele sunt pentru citit, nu pentru numarat.
    """
    ceruri = _cereri_de_limba_straina(dure.get("limbi") or {})
    if not ceruri:
        return [], ["reguli de limba lipsa din criterii.yaml"], []

    titlu = str(anunt.get(CAMP_PENTRU_LIMBI) or "")
    if not titlu.strip():
        # Fara titlu nu avem unde cauta. NEBLOCANT dinadins: un anunt fara titlu e deja
        # ciudat, dar lipsa lui nu spune nimic despre limbi - iar noi verificam limbi.
        return [], [], ["titlu lipsa, nu s-a putut verifica limba ceruta"]

    gasite = {}
    for tipar, limba in ceruri:
        if limba in gasite:
            continue
        if _contine_cuvantul(titlu, tipar):
            gasite[limba] = tipar

    motive = [
        f"limba pe care nu o vorbesti, ceruta in titlu: {limba} (tipar: '{tipar}')"
        for limba, tipar in gasite.items()
    ]
    return motive, [], []


def _cereri_de_limba_straina(limbi: dict) -> list:
    """
    Din sectiunea `limbi` a criteriilor, toate sirurile de cautat. Ca (tipar, limba).

    Combina cele doua liste din criterii.yaml: fiecare scriere a fiecarei limbi pe care
    NU o vorbesti, pusa in fiecare tipar. "germana" + "with {limba}" -> "with german",
    "with germana", "with deutsch". Ies si combinatii fara sens - nu deranjeaza, nu se
    potrivesc niciodata cu nimic.

    DE CE se construiesc aici si nu se scriu de mana in fisier: altfel `vorbite` ar fi
    doar un comentariu. Asa, cand muti o limba in `vorbite`, toate tiparele ei dispar din
    filtru in aceeasi secunda, si nu ramane nicio a doua lista de curatat cu mana.

    Tiparele care nu numesc nicio limba ("multilingual") se intorc cu eticheta
    "mai multe limbi" - nu e o limba, dar e tot o cerere de limbi din afara listei.
    """
    scrieri = limbi.get("scrieri")
    vorbite = limbi.get("vorbite") or []
    tipare = limbi.get("tipare") or []
    directe = limbi.get("tipare_directe") or []

    vorbite_curat = {fara_diacritice(str(v)).strip() for v in vorbite}

    cereri = []
    if isinstance(scrieri, dict):
        for limba, feluri in scrieri.items():
            if fara_diacritice(str(limba)).strip() in vorbite_curat:
                continue
            for fel in feluri or []:
                for tipar in tipare:
                    cereri.append((str(tipar).replace("{limba}", str(fel)), str(limba)))

    for tipar in directe:
        cereri.append((str(tipar), "mai multe limbi"))

    return cereri


def _contine_cuvantul(text: str, cuvant: str) -> bool:
    """
    Spune daca `cuvant` apare in `text` ca termen de sine statator.

    "on-call" prinde "On-Call Support" si "engineer on-call", dar "ture" NU prinde
    "structure". Delimitarea se face pe orice caracter care nu e litera sau cifra,
    deci cratima si spatiul rup cuvantul, asa cum ne trebuie pentru "on-call".

    re.escape trateaza cuvantul din configurare ca text simplu. Fara el, un cuvant
    care contine un punct sau o paranteza ar fi interpretat ca expresie regulata si
    ar potrivi cu totul altceva decat scrie in fisier.
    """
    tinta = fara_diacritice(cuvant).strip()
    if not tinta:
        return False

    sablon = r"(?<![0-9a-z])" + re.escape(tinta) + r"(?![0-9a-z])"
    return re.search(sablon, fara_diacritice(text)) is not None
