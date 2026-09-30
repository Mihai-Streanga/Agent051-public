"""
Evaluarea calitativa: judecata pe care o regula nu o poate face, ceruta unui model.

CE E ALTFEL FATA DE FILTRUL DUR:
filtrul dur (core/filtrare.py) taie ce se vede dintr-un fapt - salariu sub prag, oras
gresit, cuvantul "ture". Alea nu sunt pareri. Aici e restul, ce se vede doar CITIND
anuntul cu cap:
  - relevant                : pe ce TREAPTA sta rolul fata de tinta - ideal (AI si
                              automatizare pe procese HR/payroll), bun_in_domeniu (rol
                              senior in domeniu, fara automatizare) sau exclus (executie
                              repetitiva)?
  - interes                 : construiesti sau operezi? e rolul dorit sau "un job in plus"?
  - single_point_of_failure : sugereaza anuntul ca esti punctul unic pe un proces cu
                              deadline dur (ex: cutoff de salarii)?
Judecatile astea sunt inevitabil subiective, deci aici are voie sa intre un model.

MODELUL SEMNALEAZA, NU DECIDE. "relevant": "nu" e o OPINIE motivata, nu o stergere.
Anuntul ramane in baza, cu verdictul si motivul lui la vedere. Filtrarea (a arunca ceva)
o face doar filtrul dur, pe reguli certe; modelul doar isi spune parerea, argumentat.

PRINCIPIUL DE ARHITECTURA (la fel ca la normalizare):
    Agent 051 detine schema, promptul si validarea. NU face apelul catre model.
Aici sunt cele doua capete PURE ale lantului:
    construieste_prompt_calitativ()  - din date, un text de trimis
    valideaza_calitativ()            - dintr-un text primit, date verificate
Mijlocul - apelul propriu-zis - e IO si sta in adapters/evaluare_calitativa.py.

Fisierul asta nu atinge reteaua sau discul. Singurul import e `json`, din Python.
"""

import json

# Valorile permise pentru cele trei verdicte. Liste inchise, din acelasi motiv ca la
# normalizare: pe text liber nu poti filtra sau numara. Multimile astea sunt si
# contractul cerut modelului in prompt, si gardul verificat in valideaza_calitativ.
# Scrise o singura data, folosite in amandoua locurile.

# Treptele de relevanta, in ordinea de la cel mai bun la cel mai slab. Ordinea CONTEAZA:
# de aici se scrie promptul, si tot ea e ordinea de prioritate din briefing.
#
# DE CE trei si nu doua (schimbare de criterii 1.2): pe da/nu, un "Senior HR Generalist"
# primea "nu" fiindca titlul nu spune AI - desi criterii.yaml declara mediile alea
# acceptabile. Filtrul taia mai lat decat criteriile. Treapta din mijloc nu coboara
# tinta; separa "nu e ce caut" de "nu ma intereseaza", care nu sunt acelasi lucru.
#
# Ce inseamna fiecare treapta NU se scrie aici: sta in criterii.yaml (tinta.trepte) si
# intra in prompt ca date, ca orice alt criteriu. Codul cunoaste doar numele lor,
# fiindca pe ele filtreaza si sorteaza.
TREPTE_RELEVANTA = ("ideal", "bun_in_domeniu", "exclus")

# "incert" nu e o a patra treapta - e refuzul de a alege una. Ramane permis din acelasi
# motiv ca la celelalte doua campuri: jumatate din anunturi (LinkedIn, eJobs) vin fara
# descriere, iar un model obligat sa aleaga dintre trei ar ghici. Un "exclus" ghicit ar
# scoate anuntul din briefing fara ca nimeni sa afle; un "incert" cinstit se vede.
RELEVANT_PERMIS = TREPTE_RELEVANTA + ("incert",)
INTERES_PERMIS = ("ridicat", "mediu", "scazut", "incert")
SPOF_PERMIS = ("da", "nu", "incert")

# Fiecare verdict vine cu motivul lui. Motivul nu e ornament: un "relevant: nu" fara
# motiv e o afirmatie pe care n-o poti verifica si nici contesta. Cu motivul la vedere,
# te uiti o data si vezi daca modelul a inteles anuntul sau a ratat ceva.
CAMPURI_CU_LISTA = {
    "relevant": RELEVANT_PERMIS,
    "interes": INTERES_PERMIS,
    "single_point_of_failure": SPOF_PERMIS,
}
CAMPURI_TEXT = ("motiv_relevanta", "motiv_interes", "motiv_spof")
CAMPURI_OBLIGATORII = tuple(CAMPURI_CU_LISTA) + CAMPURI_TEXT


def construieste_prompt_calitativ(anunt: dict, criterii_calitative: dict) -> str:
    """
    Scrie cererea trimisa modelului, pentru un singur anunt.

    Primeste anuntul (titlu, firma, descriere) si felia calitativa din criterii.yaml
    (tinta, TREPTELE de relevanta, ce e exclus, semnale pozitive/negative). Nu trimite
    nimic - doar construieste sirul. De aceea se poate verifica intr-un test obisnuit,
    fara internet.

    Criteriile intra ca DATE, la fel ca anuntul - de asta functia ramane pura desi acum
    "stie" de tinta ta: nu le citeste ea de pe disc, i le da adaptorul. Ce NU primeste:
    prag salarial si locatie. Alea le-a rezolvat deja filtrul dur; modelul nu are voie
    sa le recantareasca ("dar rolul suna bine...") - vezi core/filtrare.py.

    "DOAR JSON, fara text in jur": modelele tind sa fie politicoase ("Sigur! Iata:").
    Cerem explicit sa nu o faca. Nu ne bazam pe asta - valideaza_calitativ desface si
    ambalajul - dar un raspuns curat de la inceput e mai ieftin si mai putin fragil.

    "incert" ca optiune peste tot: fara ea, un model pus sa aleaga ar alege ceva chiar si
    dintr-un anunt din care nu se poate spune. Ii dam voie sa spuna ca nu poate decide, ca
    sa nu fie nevoit sa ghiceasca - o inventie plauzibila e mai rea decat un "incert"
    cinstit, fiindca nu se vede.
    """
    titlu = (anunt.get("titlu") or "").strip() or "(fara titlu)"
    firma = (anunt.get("firma") or "").strip() or "necunoscuta"
    descriere = (anunt.get("descriere") or "").strip() or "(fara descriere)"

    return f"""Esti un asistent care evalueaza cat de bine se potriveste un anunt de job
cu tinta unei persoane. Judeci calitativ, citind anuntul. NU decizi nimic definitiv -
dai un verdict cu motiv; alege cine primeste anuntul.

TINTA persoanei (ce cauta):
{_scrie_tinta(criterii_calitative)}

TREPTELE DE RELEVANTA (pe care raspunzi la campul "relevant"):
{_scrie_trepte(criterii_calitative.get("trepte"))}

CE E EXCLUS (roluri pe care NU le vrea):
{_scrie_exclus(criterii_calitative.get("exclus"))}

SEMNALE POZITIVE (cresc potrivirea):
{_scrie_lista(criterii_calitative.get("semnale_pozitive"))}

SEMNALE NEGATIVE (scad potrivirea):
{_scrie_lista(criterii_calitative.get("semnale_negative"))}

LIMBILE PE CARE LE VORBESTE persoana:
{_scrie_limbi(criterii_calitative.get("limbi_vorbite"))}

ANUNTUL DE EVALUAT:
titlu: {titlu}
firma: {firma}
descriere: {descriere}

Raspunde DOAR cu un obiect JSON, fara text inainte si fara text dupa, fara blocuri de
cod. JSON-ul are exact aceste campuri:

  "relevant":                una dintre: {" | ".join(RELEVANT_PERMIS)}
                             (pe ce TREAPTA de mai sus sta rolul? "incert" doar daca
                              anuntul nu spune destul cat sa alegi o treapta)
  "motiv_relevanta":         o singura propozitie, de ce ai ales treapta aceea
  "interes":                 una dintre: {" | ".join(INTERES_PERMIS)}
                             (rolul construieste ceva, sau doar opereaza? e dorit, sau
                              e "inca un job"?)
  "motiv_interes":           o singura propozitie, de ce ai raspuns asa
  "single_point_of_failure": una dintre: {" | ".join(SPOF_PERMIS)}
                             (sugereaza anuntul ca ai fi punctul UNIC pe un proces cu
                              deadline dur, ex: cutoff de salarii, unde o zi proasta
                              costa?)
  "motiv_spof":              o singura propozitie, de ce ai raspuns asa

Reguli:
- Treptele nu sunt "da / nu". Un rol senior IN DOMENIU, dar fara componenta de
  automatizare, e "bun_in_domeniu", nu "exclus" - lipsa cuvintelor "AI" sau
  "automatizare" din titlu nu il face exclus. "exclus" e doar pentru executia
  repetitiva si pentru rolurile din lista de mai sus.
- LIMBI: daca anuntul cere o limba din afara listei de mai sus (obligatorie, nu "un
  plus"), spune-o EXPLICIT in "motiv_relevanta", cu limba pe nume. Nu decide tu ce se
  intampla cu anuntul - doar semnaleaza, ca sa se vada. O limba ceruta doar ca avantaj
  nu se semnaleaza la fel: scrie care din cele doua e.
- Daca anuntul nu spune destul cat sa decizi, raspunde "incert". Nu ghici din experienta
  cu alte anunturi.
- Foloseste exact valorile de mai sus, cu litere mici. Nu inventa altele.
- Nu adauga campuri in plus."""


def valideaza_calitativ(raspuns_brut: str) -> dict:
    """
    Verifica raspunsul modelului. Il accepta intreg, sau il respinge intreg.

    Intoarce:
        {"ok": True,  "date": {...}}      raspuns bun, cu cele sase campuri
        {"ok": False, "eroare": "..."}    raspuns respins, cu motivul

    REGULA CENTRALA, aceeasi ca la normalizare: functia asta NU REPARA nimic.
    Nu completeaza un camp lipsa, nu corecteaza "Ridicat" in "ridicat", nu traduce
    "foarte mare" in "ridicat". Un raspuns caruia ii lipseste un camp sau care are o
    valoare din afara listei e respins intreg. De ce: daca am repara, in baza ar intra
    un rand care arata identic cu unul bun, si peste doua luni n-ai mai putea deosebi ce
    a spus modelul de ce am ghicit noi. Un camp respins se vede si se poate reincerca;
    unul inventat nu se mai vede niciodata.

    Singurul lucru curatat e AMBALAJUL din jurul JSON-ului (vezi _extrage_json). Aia nu
    e reparare de continut - e desfacerea unui pachet.
    """
    if raspuns_brut is None or not str(raspuns_brut).strip():
        return {"ok": False, "eroare": "raspuns gol"}

    text = _extrage_json(str(raspuns_brut))
    if text is None:
        return {"ok": False, "eroare": "raspunsul nu contine niciun obiect JSON"}

    try:
        date = json.loads(text)
    except ValueError as eroare:
        # ValueError prinde si JSONDecodeError. Un JSON stricat iese ca respingere, nu
        # ca exceptie - nimeni nu vrea ca o rulare peste sute de anunturi sa cada
        # fiindca un model a uitat o virgula.
        return {"ok": False, "eroare": f"JSON invalid: {eroare}"}

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

    # Pastram exact cele sase campuri. Un camp in plus nu strica raspunsul, dar nici nu
    # intra in baza: schema e a noastra, nu a modelului.
    curat = {camp: date[camp] for camp in CAMPURI_OBLIGATORII}
    for camp in CAMPURI_TEXT:
        curat[camp] = curat[camp].strip()

    return {"ok": True, "date": curat}


# --- ajutoare pure de formatare a criteriilor in text de prompt ---------------

def _scrie_tinta(criterii: dict) -> str:
    """Descrierea tintei plus traiectoria, daca exista, ca text citibil."""
    randuri = []
    descriere = (criterii.get("tinta") or "").strip()
    if descriere:
        randuri.append(descriere)

    # traiectorie e un dict liber (A_acum, B_apoi, nota). Il scriem asa cum vine, fara
    # sa presupunem ce chei are: daca isi schimba forma in criterii.yaml, tot iese ceva
    # citibil, nu o eroare.
    traiectorie = criterii.get("traiectorie") or {}
    if isinstance(traiectorie, dict):
        for valoare in traiectorie.values():
            text = str(valoare).strip()
            if text:
                randuri.append(f"- {text}")
    elif str(traiectorie).strip():
        randuri.append(f"- {str(traiectorie).strip()}")

    return "\n".join(randuri) if randuri else "(nespecificata)"


def _scrie_trepte(trepte) -> str:
    """
    Cele trei trepte de relevanta, ca text de prompt: nume, ce inseamna, exemple.

    Ordinea e cea din TREPTE_RELEVANTA (ideal, bun_in_domeniu, exclus), NU ordinea in
    care intamplator apar in fisier. Doua motive: e ordinea logica, de sus in jos, si e
    stabila - altfel o rearanjare in criterii.yaml ar schimba promptul fara sa schimbe
    criteriile, iar doua rulari ar putea da raspunsuri diferite pe aceleasi date.

    O treapta lipsa din fisier tot apare, cu numele ei si o nota. Numele sunt valori
    permise in raspuns, deci modelul trebuie sa le vada pe toate trei chiar daca fisierul
    e incomplet - altfel ar alege dintre doua si validarea ar respinge degeaba.
    """
    trepte = trepte if isinstance(trepte, dict) else {}

    randuri = []
    for nume in TREPTE_RELEVANTA:
        continut = trepte.get(nume)
        continut = continut if isinstance(continut, dict) else {}

        descriere = str(continut.get("descriere") or "").strip()
        randuri.append(f'- "{nume}": {descriere}' if descriere else f'- "{nume}": (nedescrisa)')

        exemple = continut.get("exemple") or []
        for exemplu in exemple:
            text = str(exemplu).strip()
            if text:
                randuri.append(f"    ex: {text}")

        nota = str(continut.get("nota") or "").strip()
        if nota:
            randuri.append(f"    nota: {nota}")

    return "\n".join(randuri)


def _scrie_exclus(exclus) -> str:
    """
    Lista de roluri excluse. Fiecare intrare e {rol, motiv} in criterii.yaml, dar putem
    primi si siruri simple - le scriem pe amandoua, fara sa crapam pe forma neasteptata.
    """
    if not exclus:
        return "(niciunul precizat)"

    randuri = []
    for intrare in exclus:
        if isinstance(intrare, dict):
            rol = str(intrare.get("rol") or "").strip()
            motiv = str(intrare.get("motiv") or "").strip()
            if rol and motiv:
                randuri.append(f"- {rol} (fiindca: {motiv})")
            elif rol:
                randuri.append(f"- {rol}")
        else:
            text = str(intrare).strip()
            if text:
                randuri.append(f"- {text}")

    return "\n".join(randuri) if randuri else "(niciunul precizat)"


def _scrie_limbi(limbi) -> str:
    """
    Limbile vorbite, pe un rand, despartite prin virgula.

    Lista goala NU iese ca text gol: ar lasa in prompt un titlu de sectiune urmat de
    nimic, iar un model care vede asa ceva completeaza singur cu ce crede el. Spunem pe
    litere ca nu stim, ca sa nu semnaleze limbi dupa ureche.
    """
    curate = [str(l).strip() for l in (limbi or []) if str(l).strip()]
    return ", ".join(curate) if curate else "(nespecificate - nu semnala nimic despre limbi)"


def _scrie_lista(elemente) -> str:
    """O lista de siruri, ca puncte. Gol -> o nota, nu un bloc gol care deruteaza."""
    if not elemente:
        return "(niciunul precizat)"
    randuri = [f"- {str(e).strip()}" for e in elemente if str(e).strip()]
    return "\n".join(randuri) if randuri else "(niciunul precizat)"


def _extrage_json(text: str):
    """
    Scoate obiectul JSON dintr-un raspuns care mai are si altceva in jurul lui.

    Aceeasi desfacere de ambalaj ca in core/normalizare.py, tinuta separat dinadins:
    cele doua module de evaluare nu depind unul de altul, la fel cum parserele fiecarei
    surse stau separat. E 15 randuri de cod pur, nu o abstractie care merita impartita.

    Cum: de la prima acolada deschisa pana la ultima inchisa. Daca ce iese nu e JSON
    valid, valideaza_calitativ respinge oricum. Intoarce None daca nu exista acolade.
    """
    curatat = text.strip()
    if curatat.startswith("{") and curatat.endswith("}"):
        return curatat

    inceput = curatat.find("{")
    sfarsit = curatat.rfind("}")
    if inceput == -1 or sfarsit == -1 or sfarsit < inceput:
        return None

    return curatat[inceput : sfarsit + 1]
