"""
Normalizarea anunturilor: din titlu si text brut, campuri curate si comparabile.

DE CE e nevoie de un model aici, cand pana acum n-a fost:
pana acum am citit structuri. Un mail de la eJobs are anunturile in tabele HTML;
le-am spart determinist, cu un parser, si asta e corect - citirea unei structuri
nu e o judecata. Dar "Specialist Payroll cu experienta - urgent!!" si
"Payroll Officer (m/f/d)" sunt acelasi rol scris de doi oameni diferiti. Nicio
regula scrisa de mana nu acopera variantele. Aici judecata e inevitabil subiectiva,
deci aici are voie sa intre un model. Salariul, locatia si data raman deterministe.

PRINCIPIUL DE ARHITECTURA - citeste asta inainte sa modifici ceva:

    Agent 051 detine TOATA logica: schema, promptul, validarea.
    Agent 051 NU face apelul catre model.

Aici sunt cele doua capete ale lantului, si amandoua sunt functii pure:
    construieste_prompt()  - din date, un text de trimis
    valideaza()            - dintr-un text primit, date verificate

Ce lipseste dinadins din fisierul asta e MIJLOCUL - apelul propriu-zis catre model.
Ala e IO, deci sta in adapters/normalizare.py, ca orice alt flux care iese in lume.
Regula proiectului e limpede si nu are exceptii: un orchestrator care cheama reteaua
e IO, oricat de subtire ar fi. Aici raman doar functiile care se pot rula cu
internetul taiat si fara niciun fisier pe disc.

Fisierul asta nu importa nimic care atinge reteaua sau discul. Verifica singur:
singurul import de mai jos este `json`, care vine cu Python.
"""

import json

# Valorile permise pentru campurile cu lista inchisa.
#
# DE CE liste inchise si nu text liber: pe text liber nu poti filtra. Daca modelul
# scrie o data "remote", alta data "Remote", alta data "munca de acasa", ai trei
# valori pentru acelasi lucru si nicio interogare care sa le prinda pe toate.
# Multimile astea sunt si contractul cerut modelului in prompt, si gardul verificat
# in valideaza(). Aceleasi valori in amandoua locurile, scrise o singura data.
SENIORITATE_PERMISA = ("junior", "mid", "senior", "lead", "nespecificat")
TIP_MUNCA_PERMIS = ("remote", "hibrid", "onsite", "nespecificat")
DOMENIU_PERMIS = ("payroll", "hr_ops", "it", "altul")

# CE NU MAI E AICI, si de ce: `relevant` si `motiv_relevanta`.
#
# Normalizarea a cerut candva modelului si un verdict de relevanta. Era un read
# GENERIC: construieste_prompt primeste doar anuntul, iar criteriile stau pe disc
# (IO, interzis in core/), deci modelul raspundea dupa parerea LUI despre un job de
# payroll, nu dupa tinta reala. Intre timp a aparut evaluarea calitativa, unde
# modelul chiar primeste felia calitativa din criterii.yaml.
#
# Ramasesera doua campuri `relevant`, in doua tabele, raspunzand la aceeasi intrebare -
# unul grosier, unul autoritar. Doua surse pentru acelasi lucru inseamna ca, mai
# devreme sau mai tarziu, cineva o citeste pe cea gresita si nici macar nu-si da seama:
# ambele arata la fel intr-un SELECT. Am pastrat-o pe cea autoritara.
#
# Ce ramane aici sunt patru EXTRAGERI FACTUALE: rolul, senioritatea, tipul de munca si
# domeniul scriu in anunt, iar modelul doar le standardizeaza. Aia e treaba potrivita
# pentru Etapa 1. Judecata de relevanta apartine exclusiv Etapei 2
# (core/evaluare_calitativa.py), pe anunturile care au trecut filtrul dur.

# Campurile care trebuie sa existe, toate, in raspunsul modelului.
# Cele cu lista inchisa sunt aici; `rol_normalizat` e text liber si se verifica
# separat (trebuie doar sa fie text nevid).
CAMPURI_CU_LISTA = {
    "senioritate": SENIORITATE_PERMISA,
    "tip_munca": TIP_MUNCA_PERMIS,
    "domeniu": DOMENIU_PERMIS,
}
CAMPURI_TEXT = ("rol_normalizat",)
CAMPURI_OBLIGATORII = tuple(CAMPURI_TEXT) + tuple(CAMPURI_CU_LISTA)


def construieste_prompt(anunt: dict) -> str:
    """
    Scrie cererea trimisa modelului, pentru un singur anunt.

    Primeste dictionarul unui anunt (titlu, firma, corp_text) si intoarce un text.
    Nu trimite nimic nicaieri - doar construieste sirul de caractere. De aceea se
    poate verifica intr-un test obisnuit, fara internet.

    Cateva alegeri din prompt, si motivul lor:

    "DOAR JSON, fara text in jur" - modelele au obiceiul sa fie politicoase:
    "Sigur! Iata JSON-ul cerut:" urmat de blocul de cod. Cerem explicit sa nu o faca.
    Nu ne bazam pe asta - valideaza() stie sa curete si ambalajul - dar un raspuns
    curat de la inceput e mai ieftin si mai putin fragil decat unul reparat dupa.

    "nespecificat" ca optiune - fara ea, un model pus sa aleaga intre junior/mid/
    senior va alege ceva chiar si dintr-un anunt care nu spune nimic despre nivel.
    Iar o inventie plauzibila e mai periculoasa decat un camp gol: nu se vede.
    Ii dam voie sa spuna ca nu stie, ca sa nu fie nevoit sa ghiceasca.

    Promptul NU cere nicaieri o judecata de relevanta, dinadins. Cere patru lucruri
    care se citesc din anunt. Intrebarea "mi se potriveste?" se pune o singura data in
    tot fluxul, in core/evaluare_calitativa.py, unde modelul chiar vede criteriile.
    """
    titlu = (anunt.get("titlu") or "").strip()
    firma = (anunt.get("firma") or "").strip() or "necunoscuta"
    corp = (anunt.get("corp_text") or "").strip() or "(fara descriere)"
    locatie = (anunt.get("locatie") or "").strip() or "nespecificata"

    return f"""Esti un asistent care normalizeaza anunturi de job.

ANUNTUL:
titlu: {titlu}
firma: {firma}
locatie: {locatie}
descriere: {corp}

Raspunde DOAR cu un obiect JSON, fara text inainte si fara text dupa, fara blocuri
de cod. JSON-ul are exact aceste campuri:

  "rol_normalizat":  titlul curatat si standardizat, fara majuscule de reclama,
                     fara "urgent", fara "(m/f/d)", fara numele firmei
  "senioritate":     una dintre: {" | ".join(SENIORITATE_PERMISA)}
  "tip_munca":       una dintre: {" | ".join(TIP_MUNCA_PERMIS)}
  "domeniu":         una dintre: {" | ".join(DOMENIU_PERMIS)}

Reguli:
- Daca anuntul nu spune ceva, foloseste "nespecificat". Nu ghici si nu completa
  din experienta ta cu alte anunturi.
- tip_munca se poate deduce din DESCRIERE sau din LOCATIE. Multe anunturi (mai ales
  LinkedIn) pun felul muncii chiar in locatie, in paranteza sau ca formulare:
    "remote", "de la distanta", "la distanta", "work from home"  -> remote
    "hibrid", "regim hibrid"                                     -> hibrid
    "la fata locului", "prezenta fizica", "on-site", "onsite"    -> onsite
  Foloseste "nespecificat" DOAR daca nici descrierea, nici locatia nu spun nimic.
- Foloseste exact valorile de mai sus, scrise cu litere mici. Nu inventa altele.
- Nu adauga campuri in plus."""


def valideaza(raspuns_brut: str) -> dict:
    """
    Verifica raspunsul modelului. Il accepta intreg, sau il respinge intreg.

    Intoarce:
        {"ok": True,  "date": {...}}      raspuns bun, cu cele patru campuri
        {"ok": False, "eroare": "..."}    raspuns respins, cu motivul

    REGULA CENTRALA: functia asta NU REPARA nimic.
    Nu completeaza campuri lipsa cu "nespecificat". Nu corecteaza "Senior" in
    "senior". Nu traduce "expert" in "lead". Un raspuns prost e respins, si atat.

    De ce e important, in termeni practici: daca aici am repara, in baza ar ajunge
    un rand care arata identic cu unul bun. Peste doua luni, cand te uiti la 300 de
    anunturi normalizate, nu ai avea cum sa deosebesti ce a spus modelul de ce am
    ghicit noi in locul lui. Un camp respins se vede si se poate reincerca. Un camp
    inventat nu se mai vede niciodata.

    Singurul lucru pe care il curatam este AMBALAJUL din jurul JSON-ului (vezi
    _extrage_json). Aia nu e reparare de continut - e desfacerea unui pachet.
    """
    if raspuns_brut is None or not str(raspuns_brut).strip():
        return {"ok": False, "eroare": "raspuns gol"}

    text = _extrage_json(str(raspuns_brut))
    if text is None:
        return {"ok": False, "eroare": "raspunsul nu contine niciun obiect JSON"}

    try:
        date = json.loads(text)
    except ValueError as eroare:
        # ValueError prinde si JSONDecodeError. Un JSON stricat (virgula lipsa,
        # ghilimele nedeschise) ajunge aici si iese ca respingere, nu ca exceptie.
        # Nimeni nu vrea ca ingestia sa cada pentru ca un model a uitat o virgula.
        return {"ok": False, "eroare": f"JSON invalid: {eroare}"}

    # Un JSON valid poate fi o lista, un numar sau `null`. Noi cerem un obiect.
    if not isinstance(date, dict):
        return {"ok": False, "eroare": "JSON-ul nu e un obiect cu campuri"}

    for camp in CAMPURI_OBLIGATORII:
        if camp not in date:
            return {"ok": False, "eroare": f"lipseste campul '{camp}'"}

    for camp in CAMPURI_TEXT:
        valoare = date[camp]
        if not isinstance(valoare, str) or not valoare.strip():
            return {"ok": False, "eroare": f"campul '{camp}' e gol sau nu e text"}

    for camp, permise in CAMPURI_CU_LISTA.items():
        valoare = date[camp]
        if valoare not in permise:
            return {
                "ok": False,
                "eroare": (
                    f"campul '{camp}' are valoarea '{valoare}', "
                    f"care nu e in lista permisa: {', '.join(permise)}"
                ),
            }

    # Pastram exact cele patru campuri. Daca modelul a mai adaugat ceva pe langa,
    # nu intra in baza: schema e a noastra, nu a lui. Nu e o respingere - un camp
    # in plus nu strica raspunsul - dar nici nu se salveaza. Aici cade si un
    # `relevant` trimis din obisnuinta de un model: e camp in plus, deci ramane afara.
    curat = {camp: date[camp] for camp in CAMPURI_OBLIGATORII}
    for camp in CAMPURI_TEXT:
        curat[camp] = curat[camp].strip()

    return {"ok": True, "date": curat}


def _extrage_json(text: str):
    """
    Scoate obiectul JSON dintr-un raspuns care mai are si altceva in jurul lui.

    Modelele ambaleaza des raspunsul: "Sigur, iata:" urmat de ```json ... ```.
    Continutul dinauntru e bun; doar hartia din jur ne incurca. Desfacem hartia.

    Cum: luam de la prima acolada deschisa pana la ultima inchisa. Simplu si
    previzibil. Daca ce iese nu e JSON valid, valideaza() respinge oricum - functia
    asta nu decide nimic singura, doar propune o bucata de text spre parsare.

    Intoarce None daca nu exista nicio pereche de acolade.
    """
    # Cazul obisnuit si dorit: raspunsul e deja curat.
    curatat = text.strip()
    if curatat.startswith("{") and curatat.endswith("}"):
        return curatat

    inceput = curatat.find("{")
    sfarsit = curatat.rfind("}")
    if inceput == -1 or sfarsit == -1 or sfarsit < inceput:
        return None

    return curatat[inceput : sfarsit + 1]
