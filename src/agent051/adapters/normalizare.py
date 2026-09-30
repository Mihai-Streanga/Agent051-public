"""
Orchestrarea normalizarii: leaga promptul, modelul si validarea.

Coregrafia, pentru un anunt:
    1. construieste promptul          -> core/normalizare.py   (pur)
    2. cheama modelul                 -> functie INJECTATA      (IO)
    3. valideaza raspunsul            -> core/normalizare.py   (pur)

DE CE STA AICI SI NU IN core/:
pasul 2 iese in lume. Regula proiectului nu are exceptii - un orchestrator care
cheama reteaua e IO, oricat de subtire ar fi, si locul lui e in adapters/.
In core/ au ramas doar cele doua capete, care se pot rula cu internetul taiat.
Testul e simplu si il poti face singur: deschide core/normalizare.py si uita-te la
importuri. E doar `json`. Daca vreodata apare acolo ceva care stie de retea sau de
disc, cineva a incalcat regula.

DE UNDE VINE MODELUL:
nu de aici. `cheama_model` se primeste ca parametru, pana sus in lant. Agent 051
nu construieste niciun client, nu citeste nicio cheie si nu stie ce model e la
capatul celalalt. Cine da functia, ala plateste apelul si ala tine cheia:
    - in teste: functii inventate, unele corecte, unele care mint;
    - in productie: JA.S.Mine injecteaza propria functie, cu propria cheie.

Fisierul asta e singurul loc din tot fluxul de normalizare unde poate intra o
exceptie de retea. De aia tot aici e si singurul `except`.
"""

from datetime import datetime, timezone

from agent051.adapters.consum import inchide_rularea
from agent051.adapters.model import (
    ContorCost,
    EroareInfrastructura,
    construieste_cheama_model,
    verifica_infrastructura,
)
from agent051.core.normalizare import construieste_prompt, valideaza
from agent051.core.varsta import este_recent
from agent051.store.configuratie import varsta_maxima_zile
from agent051.store.db import (
    anunturi_de_normalizat,
    initializeaza_db,
    salveaza_normalizare,
)

# Statusul de normalizare care inseamna "gata, nu-l mai da o data pe mana modelului".
# Un anunt deja normalizat cu succes nu se renormalizeaza automat: ar fi un apel platit
# a doua oara pentru acelasi raspuns. Cele respinse (sau neincercate) se reincearca -
# de-aia regula e "sare doar pe 'ok'", nu "proceseaza doar ce lipseste".
#
# O SINGURA EXCEPTIE, ingusta: anuntul a capatat descriere DUPA normalizare (vezi
# `descriere_dupa_normalizare`, adus de store/db.py). Atunci raspunsul vechi n-ar fi
# acelasi - a fost dat pe titlu gol, iar acum modelul are text de citit. Restul raman
# sarite; nu se reface nimic "ca sa fim siguri".
STATUS_GATA = "ok"


def normalizeaza_anunt(anunt: dict, cheama_model: callable) -> dict:
    """
    Normalizeaza un singur anunt: prompt -> model -> validare.

    `cheama_model` e o functie (str) -> str, primita ca parametru. Functia asta nu
    stie cine e modelul, unde sta, cat costa sau cu ce cheie se plateste. Ii da un
    text si primeste un text.

    Intoarce exact ce intoarce valideaza():
        {"ok": True,  "date": {...}}
        {"ok": False, "eroare": "..."}

    In "date" vin patru campuri factuale: rol_normalizat, senioritate, tip_munca,
    domeniu. Niciun verdict de relevanta - ala se cere separat, in
    adapters/evaluare_calitativa.py, pe anunturile care au trecut filtrul dur, unde
    modelul chiar vede criteriile. Vezi nota din core/normalizare.py.

    NICIO DECIZIE NU SE IA AICI. "E bun raspunsul sau nu" se intreaba de la core/.

    DE CE functia asta NU MAI PRINDE exceptiile lui cheama_model (spre deosebire de o
    versiune anterioara): fiindca a le prinde si a le transforma in "respins" e chiar
    bug-ul pe care il reparam. Un apel care PICA (biblioteca lipsa, cheie respinsa, retea
    cazuta) nu spune nimic despre anunt - modelul nici n-a fost chemat. Marcat "respins",
    ar arata identic cu un anunt pe care modelul chiar l-a gasit prost, si o rulare cu
    biblioteca lipsa ar "respinge" tacut 50 de anunturi bune. Asa ceva TREBUIE sa opreasca
    rularea, nu sa se strecoare in baza.

    Deci: un esec de infrastructura (EroareInfrastructura, ridicata in adapters/model.py)
    trece prin functia asta neatins, catre lot, care opreste totul la prima aparitie. Ce
    intoarce functia - {"ok": False} - inseamna acum UN SINGUR lucru: modelul a raspuns,
    dar raspunsul n-a trecut validarea. Aia e o respingere de continut, se salveaza si
    rularea merge mai departe.
    """
    prompt = construieste_prompt(anunt)
    raspuns = cheama_model(prompt)
    return valideaza(raspuns)


def normalizeaza_lotul(
    anunturi: list,
    cheama_model: callable,
    salveaza: callable,
    acum: datetime,
    zile: int,
    limita: int,
    dry_run: bool,
) -> dict:
    """
    Normalizeaza un lot de anunturi, cu trei plase de siguranta. Intoarce un raport.

    Nu atinge nici baza, nici modelul direct: primeste anunturile ca lista, modelul ca
    functie injectata si scrie prin `salveaza`, o functie (anunt_id, rezultat) -> None. De
    aceea se testeaza intreg fara disc, fara internet si fara model - injectezi o lista, un
    model inventat, un salveaza care doar noteaza si un `acum` fix. Wiring-ul cu baza reala
    e in ruleaza_normalizarea().

    Cele trei plase, la vedere, in ordinea in care taie:
      1. VARSTA (`zile`): un anunt mai vechi de prag e sarit. Arhiva de 11 ani e cercetare
         de piata, nu material de scoring - un anunt din 2018 e mort, iar un apel de model
         pe el sunt bani aruncati. `acum` vine ca parametru, nu din ceasul masinii, tocmai
         ca testul de varsta sa fie repetabil.
      2. DEJA NORMALIZAT: un anunt cu status 'ok' e sarit. Nu platim de doua ori acelasi
         raspuns. Cele respinse sau neincercate trec mai departe - alea chiar au nevoie.
         Sare plasa asta un singur caz: anuntul a capatat descriere DUPA normalizare
         (`descriere_dupa_normalizare`, calculat in store/db.py). Atunci nu mai e acelasi
         raspuns - vechiul a fost dat pe titlu gol. Se renormalizeaza, si se NUMARA
         separat, ca sa se poata verifica "de ce sunt 12 in plus fata de data trecuta".
      3. LIMITA (`limita`): dintre cele ramase eligibile, model se cheama pe cel mult
         `limita`. E franca impotriva unei rulari scapate care ar da sute de apeluri.

    dry_run=True calculeaza TOT ce e mai sus - cate ar fi sarite, cate ar fi procesate -
    dar NU cheama modelul. E felul in care linia de comanda arata "ar face X apeluri" fara
    sa cheltuie un ban. Modelul se atinge doar in ramura `not dry_run`.

    ESEC DE INFRASTRUCTURA: daca un apel de model PICA (EroareInfrastructura - biblioteca
    lipsa, cheie respinsa, retea cazuta), oprim rularea IMEDIAT, la prima aparitie. Anuntul
    respectiv NU se salveaza (nu stim nimic despre el, deci ramane de reincercat), iar
    esecul iese separat in raport, la `esec_infrastructura` - nu se amesteca cu respingerile
    de continut. Cele salvate cu succes inainte raman salvate; nu le pierdem.

    Raportul:
        candidate                - cate anunturi au intrat in lot
        sarite_vechi             - sarite fiindca sunt mai vechi de prag (sau fara data)
        sarite_deja_normalizate  - sarite fiindca aveau deja status 'ok'
        renormalizate_descriere_noua - dintre eligibile, cate erau deja 'ok' si intra din
                                   nou doar fiindca au capatat descriere dupa normalizare
        de_procesat              - cate au ramas eligibile (recente, ne-'ok')
        limita                   - plafonul cerut
        ar_procesa               - cate ar merge/merg efectiv la model (min(de_procesat, limita))
        oprite_de_limita         - eligibile lasate pe data viitoare, taiate de limita
        dry_run                  - daca a fost o simulare
        procesate                - cate au mers efectiv la model (0 la dry run)
        ok                       - raspunsuri VALIDE (0 la dry run)
        respinse                 - raspunsuri respinse DE VALIDARE - modelul a raspuns, dar
                                   raspunsul e prost (0 la dry run)
        esuate_infrastructura    - cate apeluri au picat inainte sa afle un raspuns (0 sau 1:
                                   oprim la prima aparitie)
        esec_infrastructura      - mesajul clar al esecului, sau None daca n-a fost niciunul
    """
    sarite_vechi = 0
    sarite_deja = 0
    rejudecate = 0
    eligibile = []

    for anunt in anunturi:
        deja_normalizat = anunt.get("status_normalizare") == STATUS_GATA
        # Faptul vine din baza; decizia ce se face cu el se ia aici, la vedere.
        are_descriere_noua = bool(anunt.get("descriere_dupa_normalizare"))

        if deja_normalizat and not are_descriere_noua:
            sarite_deja += 1
            continue
        if not este_recent(anunt.get("data_anunt"), acum, zile):
            sarite_vechi += 1
            continue
        # Numaram renormalizarea abia AICI, dupa filtrul de varsta: un anunt vechi cu
        # descriere noua tot nu ajunge la model, si un raport care l-ar numara ar promite
        # o renormalizare care nu se intampla.
        if deja_normalizat:
            rejudecate += 1
        eligibile.append(anunt)

    de_procesat = len(eligibile)
    ar_procesa = min(de_procesat, limita)
    oprite_de_limita = de_procesat - ar_procesa

    procesate = 0
    ok = 0
    respinse = 0
    esuate_infrastructura = 0
    esec_infrastructura = None

    if not dry_run:
        # eligibile[:limita] - taiem la plafon INAINTE de bucla, deci modelul nu vede
        # niciodata mai mult de `limita` anunturi. Franca e reala, nu o verificare de
        # dupa care ar fi platit deja apelurile.
        for anunt in eligibile[:limita]:
            try:
                rezultat = normalizeaza_anunt(anunt, cheama_model)
            except EroareInfrastructura as eroare:
                # Drumul catre model s-a rupt. NU salvam anuntul (nu stim nimic despre el,
                # ramane de reincercat) si oprim aici: daca lipseste biblioteca la anuntul
                # asta, va lipsi si la urmatorul.
                esuate_infrastructura += 1
                esec_infrastructura = str(eroare)
                break
            salveaza(anunt["id"], rezultat)
            procesate += 1
            if rezultat.get("ok"):
                ok += 1
            else:
                respinse += 1

    return {
        "candidate": len(anunturi),
        "sarite_vechi": sarite_vechi,
        "sarite_deja_normalizate": sarite_deja,
        "renormalizate_descriere_noua": rejudecate,
        "de_procesat": de_procesat,
        "limita": limita,
        "ar_procesa": ar_procesa,
        "oprite_de_limita": oprite_de_limita,
        "dry_run": dry_run,
        "procesate": procesate,
        "ok": ok,
        "respinse": respinse,
        "esuate_infrastructura": esuate_infrastructura,
        "esec_infrastructura": esec_infrastructura,
    }


def ruleaza_normalizarea(
    limita: int = 50, dry_run: bool = True, cheama_model: callable = None
) -> dict:
    """
    Ruleaza normalizarea pe anunturile din baza. Implicit DRY RUN - nu cheltuie nimic.

    Wiring: citeste anunturile si pragul de varsta din baza/config, construieste
    `cheama_model` (daca nu i s-a dat unul), cheama normalizeaza_lotul, aduna costul in
    `stare`. Firele sunt aici; deciziile (varsta, limita, dry run) sunt in
    normalizeaza_lotul, care se testeaza singur, fara disc.

    DE CE construieste agentul singur `cheama_model` aici (fata de faza 1, cand il primea
    din afara): asta e chiar decizia fazei 2 - agentul e autonom, are cheie proprie in .env
    si isi injecteaza singur functia de model (vezi adapters/model.py). Seamul ramane insa
    injectabil: daca i se da un `cheama_model` (in test, unul inventat), il foloseste pe
    ala si nu construieste nimic real. In productie nu se injecteaza nimic - construieste
    singur, legat de un contor, ca sa poata raporta costul.

    `dry_run=True` e IMPLICIT dinadins: nimeni nu porneste din greseala sute de apeluri.
    O rulare pe bune se cere explicit, cu dry_run=False (din linia de comanda: --confirma).

    PRE-FLIGHT: inainte de o rulare reala pe modelul propriu, verificam ca se poate ajunge
    la el (biblioteca instalata, cheie prezenta). Daca nu, ridicam EroareInfrastructura cu
    mesaj clar, INAINTE sa atingem vreun anunt - zero anunturi marcate, zero apeluri. Asa,
    o biblioteca lipsa nu mai "respinge" 50 de anunturi bune. Verificarea se face doar cand
    construim noi modelul (nu cand ni se injecteaza unul din test) si doar pe rularea reala
    (un dry run nu cheama modelul).

    Costul (apeluri, tokeni) se aduna in `stare` DOAR daca a fost o rulare reala care chiar
    a apelat modelul. Cand `cheama_model` e injectat din test, contorul ramane pe zero -
    functia inventata nu-l atinge - deci nu se scrie niciun cost fals.
    """
    initializeaza_db()

    zile = varsta_maxima_zile()
    anunturi = anunturi_de_normalizat()
    acum = datetime.now(timezone.utc)

    contor = ContorCost()
    if cheama_model is None:
        if not dry_run:
            verifica_infrastructura()
        cheama_model = construieste_cheama_model(contor)

    try:
        raport = normalizeaza_lotul(
            anunturi, cheama_model, salveaza_normalizare, acum, zile, limita, dry_run
        )
    except BaseException:
        # Rularea s-a rupt neprevazut (baza blocata, o eroare in cod, procesul oprit):
        # apelurile facute pana aici s-au platit, deci se numara INAINTE ca eroarea sa
        # urce mai departe. Altfel raportul lunii ar arata mai putin decat s-a cheltuit.
        inchide_rularea(contor, dry_run)
        raise

    raport["cost"] = inchide_rularea(contor, dry_run)
    return raport
