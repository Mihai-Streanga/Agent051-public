"""
Orchestrarea evaluarii calitative: leaga promptul, modelul si validarea, pe anunturile
care au trecut filtrul dur.

Coregrafia, pentru un anunt:
    1. construieste promptul calitativ   -> core/evaluare_calitativa.py   (pur)
    2. cheama modelul                    -> functie INJECTATA              (IO)
    3. valideaza raspunsul               -> core/evaluare_calitativa.py   (pur)
    4. salveaza verdictul                -> store/db.py                   (disc)

DE CE STA AICI SI NU IN core/: pasul 2 iese in lume. Un orchestrator care cheama
reteaua e IO, oricat de subtire. In core/ au ramas doar cele doua capete pure.

DE UNDE VINE MODELUL: nu de aici. `cheama_model` se primeste ca parametru, ca la
normalizare. Agent 051 nu construieste client, nu citeste cheie, nu stie ce model e la
capat. In teste injectam functii inventate; in productie, JA.S.Mine injecteaza a ei.

CINE AJUNGE LA MODEL: doar anunturile cu verdict "trece" sau "incert" de la filtrul dur.
Cele "respins" au picat deja pe o regula certa - a le mai da pe mana modelului ar fi bani
aruncati pe o opinie despre un job pe care oricum nu-l iei. Filtrul e primul strat (reguli,
gratis, determinist), modelul al doilea (judecata, costa, doar pe ce a supravietuit).
"""

from agent051.adapters.consum import inchide_rularea
from agent051.adapters.model import (
    ContorCost,
    EroareInfrastructura,
    construieste_cheama_model,
    verifica_infrastructura,
)
from agent051.core.evaluare_calitativa import (
    construieste_prompt_calitativ,
    valideaza_calitativ,
)
from agent051.store.configuratie import criterii_calitative, versiune_criterii
from agent051.store.db import (
    anunturi_pentru_calitativ,
    initializeaza_db,
    salveaza_evaluare_calitativa,
)

# Verdictele filtrului dur care merg mai departe la model. Restul ("respins") se sar.
# Regula sta AICI, la vedere, nu ascunsa intr-un WHERE din SQL - vezi
# anunturi_pentru_calitativ() in store/db.py, care intoarce verdictul tocmai ca decizia
# sa se ia in acest strat.
VERDICTE_CARE_MERG_LA_MODEL = ("trece", "incert")


def alege_anunturile(anunturi: list, reevalueaza: bool = False) -> dict:
    """
    Din anunturile candidate, cele care chiar au nevoie de un apel de model. Cu numaratoare.

    Intoarce {"eligibile": [...], "sarite": {...}, "rejudecate_descriere_noua": N,
    "eligibile_cu_esecuri_vechi": N}, unde `sarite` spune cate au picat pe fiecare motiv.
    Raportul are nevoie de defalcare, nu doar de un total: "ar evalua 1 din 83" nu se poate
    verifica daca nu vezi ca 51 au fost respinse de filtru si 31 erau deja evaluate.

    `eligibile_cu_esecuri_vechi` spune cate dintre cele care intra la model au esuat deja
    cel putin o data. Se numara AICI, si nu doar dupa rulare, fiindca e singura cifra care
    apare si la DRY RUN - adica inainte sa se dea banii. "Ar face 4 apeluri, dintre care
    unul pentru un anunt care a refuzat de doua ori sa raspunda cu JSON valid" e o
    propozitie pe care poti decide; "ar face 4 apeluri" nu e.

    Doua motive de sarit, in ordinea in care taie:

      1. RESPINS DE FILTRUL DUR. A picat pe o regula certa; un apel pe el ar fi bani dati
         pe o opinie despre un job pe care oricum nu-l iei.

      2. ARE DEJA O EVALUARE VALABILA - adica un verdict care a trecut validarea, dat pe
         versiunea de criterii de acum. Exact analogia cu STATUS_GATA de la normalizare:
         un anunt deja evaluat cu succes nu se reevalueaza automat, fiindca ar fi un apel
         platit a doua oara pentru acelasi raspuns.

         Doua situatii NU intra aici, si e important de ce:
           - evaluarea e de pe o versiune mai veche de criterii -> a fost data raspunzand
             la alta intrebare, deci nu mai conteaza; se reevalueaza;
           - evaluarea are status "respins" (modelul a raspuns cu JSON stricat) -> nu e o
             evaluare, e o incercare esuata; se reincearca.
         Amandoua vin gata judecate din `are_evaluare_valabila` (vezi store/db.py), tocmai
         ca regula de versiune sa fie scrisa intr-un singur loc in tot proiectul.

         A treia, adaugata cand descrierile au inceput sa vina din paginile publice:
           - anuntul a capatat DESCRIERE dupa ce primise verdictul
             (`descriere_dupa_evaluare`, tot din store/db.py). Verdictul exista, e pe
             versiunea buna si a trecut validarea - dar a fost dat pe un titlu gol, si de
             obicei suna "incert, lipseste descrierea". Nu mai e acelasi raspuns: modelul
             are acum ce citi. Se rejudeca, si se NUMARA separat.
         Rejudecarea e INGUSTA dinadins: nu "s-a atins anuntul", ci "a aparut text nou
         dupa judecata". O pagina expirata sau una din care parserul n-a scos nimic nu
         declanseaza nimic - vezi _descriere_mai_noua_decat in store/db.py.

    `reevalueaza=True` ignora al doilea motiv si trimite la model tot ce e eligibil.
    E pentru cazul in care schimbi PROMPTUL fara sa urci versiunea criteriilor: atunci
    verdictele vechi sunt pe versiunea buna, dar produse de alta intrebare, si nicio
    regula automata nu are cum sa stie asta. De aia e o decizie omeneasca, explicita, si
    implicit oprita - costa bani de fiecare data cand e pornita. Descrierea aparuta dupa
    judecata NU are nevoie de el: aia e o schimbare pe care baza chiar o poate observa.
    """
    eligibile = []
    sarite = {"respinse_de_filtru": 0, "evaluate_deja": 0}
    rejudecate = 0
    cu_esecuri_vechi = 0

    for anunt in anunturi:
        if anunt.get("verdict") not in VERDICTE_CARE_MERG_LA_MODEL:
            sarite["respinse_de_filtru"] += 1
            continue

        # Cele doua fapte vin din baza; ce se face cu ele se decide aici, la vedere.
        e_deja_evaluat = bool(anunt.get("are_evaluare_valabila"))
        are_descriere_noua = bool(anunt.get("descriere_dupa_evaluare"))

        if e_deja_evaluat and not (are_descriere_noua or reevalueaza):
            sarite["evaluate_deja"] += 1
            continue

        # Se numara si cand a fost pornit `reevalueaza`: e un fapt despre anunt (a aparut
        # text dupa judecata), nu despre butonul apasat. Asa raportul spune acelasi lucru
        # in ambele rulari.
        if e_deja_evaluat and are_descriere_noua:
            rejudecate += 1
        if (anunt.get("incercari_esuate") or 0) > 0:
            cu_esecuri_vechi += 1
        eligibile.append(anunt)

    return {
        "eligibile": eligibile,
        "sarite": sarite,
        "rejudecate_descriere_noua": rejudecate,
        "eligibile_cu_esecuri_vechi": cu_esecuri_vechi,
    }


def evalueaza_anunt(anunt: dict, criterii: dict, cheama_model: callable) -> dict:
    """
    Evalueaza calitativ un singur anunt: prompt -> model -> validare.

    `cheama_model` e o functie (str) -> str, primita ca parametru. Nu stie cine e
    modelul, unde sta, cat costa. Ii da un text, primeste un text.

    Intoarce exact ce intoarce valideaza_calitativ():
        {"ok": True,  "date": {...}}
        {"ok": False, "eroare": "..."}

    NICIO DECIZIE NU SE IA AICI. "E bun raspunsul?" se intreaba de la core/.

    DE CE NU MAI PRINDE exceptiile lui cheama_model (ca la normalizeaza_anunt): a le prinde
    si a le transforma in "respins" ascunde un esec de infrastructura sub o respingere de
    continut - o biblioteca lipsa sau o cheie respinsa ar "respinge" tacut anunturi bune,
    modelul nefiind chemat deloc. Un esec de drum (EroareInfrastructura) trece neatins catre
    lot, care opreste rularea la prima aparitie. Ce intoarce functia - {"ok": False} -
    inseamna acum doar: modelul a raspuns, dar raspunsul n-a trecut validarea.
    """
    prompt = construieste_prompt_calitativ(anunt, criterii)
    raspuns = cheama_model(prompt)
    return valideaza_calitativ(raspuns)


def evalueaza_lotul(
    anunturi: list,
    criterii: dict,
    cheama_model: callable,
    salveaza: callable,
    versiune_criterii: str,
    limita: int = None,
    dry_run: bool = False,
    reevalueaza: bool = False,
) -> dict:
    """
    Evalueaza un lot de anunturi. Sare cele respinse de filtrul dur. Intoarce un raport.

    Nu atinge direct baza: primeste anunturile ca lista si scrie prin `salveaza`, o
    functie (anunt_id, rezultat, versiune) -> None. De asta se poate testa fara disc si
    fara model - injectezi o lista, un model inventat si un salveaza care doar noteaza.
    Wiring-ul cu baza reala e in ruleaza_evaluarea_calitativa().

    Doua plase de siguranta, ca la normalizare:
      - LIMITA (`limita`): dintre eligibile (verdict trece/incert), model se cheama pe cel
        mult `limita`. `None` inseamna fara plafon - comportamentul dinainte, pastrat ca
        implicit ca sa nu schimbe testele care nu cer o limita.
      - DRY RUN (`dry_run`): calculeaza cate ar merge la model, dar NU cheama modelul.
        Felul in care linia de comanda arata "ar face X apeluri" fara sa cheltuie un ban.

    Anuntul respins de filtrul dur NU ajunge la model, indiferent de plase: a picat deja
    pe o regula certa, iar un apel pe el ar fi bani pe o opinie despre un job pe care oricum
    nu-l iei. Asta e economia pe care o cumpara ordinea "reguli intai, model dupa".

    ESEC DE INFRASTRUCTURA, la fel ca la normalizare: daca un apel de model PICA
    (EroareInfrastructura), oprim rularea imediat, anuntul NU se salveaza (ramane de
    reincercat), iar esecul iese separat la `esec_infrastructura` - nu ca respingere.

    Raportul spune:
        candidate             - cate anunturi au avut un verdict de filtrare (au ajuns aici)
        sarite                - defalcat pe motiv: respinse_de_filtru, evaluate_deja
        sarite_respins        - cate au fost sarite fiindca filtrul dur le-a respins deja
        sarite_evaluate_deja  - cate aveau deja un verdict valabil pe criteriile de acum
        rejudecate_descriere_noua - dintre eligibile, cate aveau deja un verdict si intra
                                din nou fiindca au capatat descriere dupa ce l-au primit
        reevalueaza           - daca s-a cerut ignorarea evaluarilor existente
        de_procesat           - cate chiar au nevoie de un apel de model
        limita                - plafonul cerut (None = fara plafon)
        oprite_de_limita      - eligibile lasate pe data viitoare, taiate de limita
        dry_run               - daca a fost o simulare
        evaluate              - cate au mers efectiv la model (0 la dry run)
        ok                    - cate raspunsuri au trecut validarea (0 la dry run)
        respinse_model        - cate raspunsuri au fost respinse DE VALIDARE (0 la dry run)
        eligibile_cu_esecuri_vechi - cate dintre cele care intra la model au esuat deja
                                cel putin o data. Singura cifra despre esecuri care apare
                                si la DRY RUN, adica inainte de plata
        esecuri_pe_anunt      - pentru fiecare anunt respins ACUM: id, titlu si de cate ori
                                a esuat in total, cele mai incapatanate primele. Goala la
                                dry run

    DE CE `esecuri_pe_anunt` si nu doar `respinse_model`: un anunt respins e eligibil la
    fiecare rulare urmatoare, deliberat - un anunt care esueaza repetat spune ceva despre
    prompt sau despre model, si trebuie sa se vada. Ce nu se vedea era COSTUL: acelasi
    anunt platit iar si iar, fara ca nimic din raport s-o spuna. Un total nu ajuta -
    "1 respins" arata la fel la prima si la a zecea rulare. Cifra pe anunt CRESTE, deci
    problema devine mai vizibila, nu mai putin.

    Ce NU face raportul: nu opreste nimic. Un plafon de incercari pus in tacere ar fi mai
    rau decat cheltuiala, fiindca ar ascunde chiar informatia pentru care se plateste.
        esuate_infrastructura - cate apeluri au picat inainte de un raspuns (0 sau 1)
        esec_infrastructura   - mesajul clar al esecului, sau None
        verdicte              - distributia verdictelor valide (relevant/interes/spof)
    """
    ales = alege_anunturile(anunturi, reevalueaza)
    eligibile = ales["eligibile"]
    sarite = ales["sarite"]
    rejudecate = ales["rejudecate_descriere_noua"]
    cu_esecuri_vechi = ales["eligibile_cu_esecuri_vechi"]

    if limita is None:
        de_luat = eligibile
    else:
        de_luat = eligibile[:limita]
    oprite_de_limita = len(eligibile) - len(de_luat)

    evaluate = 0
    ok = 0
    respinse = 0
    esuate_infrastructura = 0
    esec_infrastructura = None
    verdicte = {"relevant": {}, "interes": {}, "single_point_of_failure": {}}
    esecuri_pe_anunt = []

    if not dry_run:
        for anunt in de_luat:
            try:
                rezultat = evalueaza_anunt(anunt, criterii, cheama_model)
            except EroareInfrastructura as eroare:
                # Drumul catre model s-a rupt. Nu salvam, oprim aici - va pica la fel si la
                # urmatorul. Ce s-a evaluat cu succes inainte ramane salvat.
                esuate_infrastructura += 1
                esec_infrastructura = str(eroare)
                break
            salveaza(anunt["id"], rezultat, versiune_criterii)
            evaluate += 1

            if rezultat.get("ok"):
                ok += 1
                date = rezultat["date"]
                for camp in verdicte:
                    valoare = date[camp]
                    verdicte[camp][valoare] = verdicte[camp].get(valoare, 0) + 1
            else:
                respinse += 1
                # Numaram cu unul mai mult decat scria in baza, fiindca esecul de acum e
                # al nostru si nu s-a scris inca in randul pe care l-am citit. Aceeasi
                # adunare o face si salveaza_evaluare_calitativa, in aceeasi clipa - de
                # aia cifra din raport e chiar cea care ramane in baza.
                esecuri_pe_anunt.append({
                    "anunt_id": anunt["id"],
                    "titlu": anunt.get("titlu"),
                    "incercari": (anunt.get("incercari_esuate") or 0) + 1,
                })

    # Cele mai incapatanate primele: un anunt la a patra respingere e o informatie despre
    # prompt, unul la prima e doar o zi proasta. La egalitate, id-ul - ca doua rulari pe
    # aceleasi date sa dea acelasi raport.
    esecuri_pe_anunt.sort(key=lambda e: (-e["incercari"], e["anunt_id"]))

    return {
        "candidate": len(anunturi),
        "sarite": sarite,
        # Aceleasi cifre si sub numele lor vechi: raportul e citit si de linia de comanda,
        # si de JA.S.Mine prin MCP, iar o cheie disparuta e o schimbare de contract.
        "sarite_respins": sarite["respinse_de_filtru"],
        "sarite_evaluate_deja": sarite["evaluate_deja"],
        "rejudecate_descriere_noua": rejudecate,
        "reevalueaza": reevalueaza,
        "de_procesat": len(eligibile),
        "limita": limita,
        "oprite_de_limita": oprite_de_limita,
        "dry_run": dry_run,
        "evaluate": evaluate,
        "ok": ok,
        "respinse_model": respinse,
        "eligibile_cu_esecuri_vechi": cu_esecuri_vechi,
        "esecuri_pe_anunt": esecuri_pe_anunt,
        "esuate_infrastructura": esuate_infrastructura,
        "esec_infrastructura": esec_infrastructura,
        "versiune_criterii": versiune_criterii,
        "verdicte": verdicte,
    }


def ruleaza_evaluarea_calitativa(
    limita: int = 50,
    dry_run: bool = True,
    cheama_model: callable = None,
    reevalueaza: bool = False,
) -> dict:
    """
    Ruleaza evaluarea calitativa pe anunturile care au trecut filtrul dur. Implicit DRY RUN.

    `reevalueaza=False` (implicit) sare peste anunturile care au deja un verdict valabil
    pe criteriile de acum - vezi alege_anunturile. Cu True, le trimite din nou la model:
    e pentru cand ai schimbat promptul fara sa urci versiunea criteriilor. COSTA de
    fiecare data cand e pornit.

    Wiring: citeste anunturile si criteriile din baza/config, construieste `cheama_model`
    (daca nu i s-a dat unul), cheama evalueaza_lotul, aduna costul in `stare`. Firele sunt
    aici; deciziile (limita, dry run) sunt in evalueaza_lotul, care se testeaza singur.

    DE CE construieste agentul singur `cheama_model` (fata de faza 1): e decizia fazei 2 -
    agentul e autonom, cu cheie proprie in .env si injectie proprie (vezi adapters/model.py).
    Seamul ramane injectabil pentru teste: dai un `cheama_model` inventat si nu se
    construieste nimic real.

    `dry_run=True` e IMPLICIT: nimeni nu porneste din greseala sute de apeluri. O rulare pe
    bune se cere explicit (din linia de comanda: --confirma). Un anunt = un apel; nu
    reincercam in tacere.

    VARSTA nu se mai filtreaza aici: la evaluare ajung doar anunturile care au trecut
    filtrul dur, iar la filtru ajung doar cele normalizate - iar normalizarea taie deja pe
    varsta. Deci un anunt vechi nici nu ajunge pana aici. Plasa de varsta sta o singura
    data, sus, la normalizare, unde e primul apel de model si prima cheltuiala.
    """
    initializeaza_db()

    criterii = criterii_calitative()
    # Versiunea vine din meta.versiune, ca la filtrare: un verdict calitativ trebuie sa
    # stie din ce epoca de criterii e. O citim separat de felia calitativa, fiindca meta
    # nu e un criteriu de judecata, ci o eticheta de provenienta.
    #
    # Aceeasi functie de care depind si CITIRILE: se citesc doar evaluarile purtand
    # versiunea de acum. Scrisa aici cu alta valoare decat acolo, evaluarea ar costa bani
    # si n-ar fi citita niciodata - fara ca nimic sa dea eroare.
    versiune = versiune_criterii()

    anunturi = anunturi_pentru_calitativ()

    contor = ContorCost()
    if cheama_model is None:
        # PRE-FLIGHT: pe rularea reala, verificam ca se poate ajunge la model INAINTE de
        # a atinge vreun anunt. Lipsa bibliotecii sau a cheii opreste aici, cu mesaj clar,
        # zero anunturi marcate. Vezi aceeasi nota din ruleaza_normalizarea.
        if not dry_run:
            verifica_infrastructura()
        cheama_model = construieste_cheama_model(contor)

    try:
        raport = evalueaza_lotul(
            anunturi,
            criterii,
            cheama_model,
            salveaza_evaluare_calitativa,
            versiune,
            limita,
            dry_run,
            reevalueaza,
        )
    except BaseException:
        # Rularea s-a rupt neprevazut (baza blocata, o eroare in cod, procesul oprit):
        # apelurile facute pana aici s-au platit, deci se numara INAINTE ca eroarea sa
        # urce mai departe. Altfel raportul lunii ar arata mai putin decat s-a cheltuit.
        inchide_rularea(contor, dry_run)
        raise

    raport["cost"] = inchide_rularea(contor, dry_run)
    return raport
