"""
Baza de date: unde ajung mailurile dupa ce le citim din Gmail.

Folosim SQLite - o baza de date care traieste intr-un singur fisier
(data/agent051.db). Nu e nevoie de niciun server care sa ruleze in fundal.
Fisierul e al tau, sta pe calculatorul tau, si e ignorat de Git.

Locul lui in arhitectura: `store/` = tot ce tine de PASTRARE. Nu decide nimic,
nu evalueaza nimic. Primeste date, le scrie. Sau i se cer date, le da.
"""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from agent051.store.configuratie import versiune_criterii

# ORICE CITIRE A EVALUARILOR CALITATIVE TRECE PRIN BUCATA ASTA DE SQL. Scrisa o data.
#
# REGULA: se citesc doar evaluarile date pe versiunea de criterii de ACUM, si doar cele
# care au trecut validarea. Randurile mai vechi raman in tabela - sunt istoric, si
# istoricul nu se sterge - dar nu se mai citesc de nicaieri.
#
# DE CE. Un verdict inseamna ceva doar impreuna cu criteriile dupa care a fost dat.
# Pe criteriile 1.1, `relevant` era da/nu; de la 1.2 e o treapta din trei. Amestecate
# intr-un singur raport, doua randuri care arata identic intr-un SELECT raspund de fapt
# la doua intrebari diferite - iar cine le citeste (inclusiv JA.S.Mine) n-are cum sa observe.
#
# DE CE SI `status_evaluare = 'ok'`: un rand cu status "respins" e o incercare esuata
# (modelul a raspuns cu JSON stricat), nu o evaluare. Fara conditia asta ar trece drept
# evaluare existenta si ar ASCUNDE un gol - exact opusul a ce vrem, adica sa se vada.
#
# Se leaga pe `a.id`, deci cere ca tabela `anunturi` sa fie aliasata `a`. Versiunea intra
# ca parametru (?), nu lipita in text: parametrii se leaga de baza, sirurile se
# concateneaza - si a doua varianta e felul in care se scriu, din neatentie, interogari
# care pot fi pacalite.
JOIN_EVALUARE_VALABILA = """
        LEFT JOIN evaluari_calitative e
               ON e.anunt_id = a.id
              AND e.versiune_criterii = ?
              AND e.status_evaluare = 'ok'
"""

# Al doilea JOIN, pentru o intrebare DIFERITA: exista vreo evaluare pentru anuntul asta,
# oricare ar fi ea? Nu ca s-o citim - verdictele vechi nu se citesc niciodata - ci ca
# briefingul sa poata spune "n-are evaluare valabila, DAR are una veche". Alta cauza,
# alta reparatie: una cere o evaluare, cealalta o reevaluare.
#
# Nu inmulteste randurile: `anunt_id` e cheie primara in evaluari_calitative, deci
# potriveste cel mult un rand.
JOIN_ORICE_EVALUARE = """
        LEFT JOIN evaluari_calitative orice_e ON orice_e.anunt_id = a.id
"""


def _descriere_mai_noua_decat(moment_judecatii: str) -> str:
    """
    Bucata de SQL care raspunde la: anuntul a capatat descriere DUPA judecata data pe el?

    `moment_judecatii` e coloana cu data judecatii - `e.data_evaluare` la evaluarea
    calitativa, `n.data_normalizare` la normalizare. Restul conditiei e identic, si de aia
    e scris o singura data: aceeasi intrebare, pusa in doua locuri, trebuie sa insemne
    acelasi lucru.

    DE CE EXISTA. Capitolul 3 a adus descrieri din paginile publice pentru anunturi care
    fusesera deja judecate pe titlu gol - iar o judecata data fara descriere ("incert,
    lipseste descrierea") nu se repara singura. Fara faptul asta, descrierile ar sta in
    baza si verdictele ar ramane cele de dinainte.

    DE CE SI `status_pagina = 'ok'`, nu doar compararea datelor. `data_pagina` se scrie la
    ORICE incercare de pagina, inclusiv la cele care n-au adus nimic: `expirat`,
    `interzis_robots`, `fara_descriere`. Rejudecate pe baza lor, anunturile alea ar costa
    un apel de model ca sa primeasca exact acelasi raspuns - modelul tot n-ar avea ce citi.
    Doar `ok` inseamna "pagina a venit si parserul a gasit textul".

    DATELE SE COMPARA CA SIRURI, si aici e in regula: si `data_pagina`, si datele de
    judecata sunt scrise de codul nostru cu `datetime.now(timezone.utc).isoformat()`, deci
    toate in UTC, cu acelasi format. (Regula generala ramane cea de la _data_din_text: un
    ISO comparat ca text minte cand fusurile difera. Aici nu difera, fiindca nu vin din
    afara - le scriem noi.)
    """
    return f"""
            (a.status_pagina = 'ok'
             AND a.data_pagina IS NOT NULL
             AND {moment_judecatii} IS NOT NULL
             AND a.data_pagina > {moment_judecatii})
    """

# Radacina proiectului: urcam trei niveluri (store -> agent051 -> src -> radacina).
RADACINA_PROIECT = Path(__file__).resolve().parents[3]

# Baza de date sta in data/, care e ignorat de Git. Datele tale reale nu pleaca
# niciodata de pe calculatorul asta.
DOSAR_DATE = RADACINA_PROIECT / "data"
CALE_DB = DOSAR_DATE / "agent051.db"


def _deschide_conexiune() -> sqlite3.Connection:
    """
    Deschide o legatura catre fisierul bazei de date.

    Daca fisierul nu exista, SQLite il creeaza singur, gol. Nu trebuie sa-l
    pregatim noi - trebuie doar sa ne asiguram ca dosarul data/ exista.
    """
    DOSAR_DATE.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(CALE_DB)


def deschide_cu_tranzactie_manuala(cale=None) -> sqlite3.Connection:
    """
    O conexiune pe care cine o cere isi conduce SINGUR tranzactia (BEGIN / COMMIT / ROLLBACK).

    Restul fisierului deschide cate o conexiune per functie, isi face treaba si o inchide.
    E simplu si bun pentru operatiuni scurte. Nu merge insa pentru operatiunile care
    rescriu date existente - migrarea de id-uri, repararea firmelor: alea sunt o singura
    tranzactie care tine zeci de comenzi laolalta, ori trec toate, ori niciuna. O
    tranzactie traieste intr-o conexiune anume; daca fiecare functie si-ar deschide alta,
    n-ar mai fi una, ci zece care se pot opri la mijloc.

    `isolation_level = None` opreste gestionarea automata a tranzactiilor din Python: fara
    ea, biblioteca deschide si inchide tranzactii cand crede ea de cuviinta, iar un BEGIN
    scris de noi s-ar bate cap in cap cu ale ei.

    `cale` implicit e baza reala. Testele dau un fisier temporar si de aceea nu ating
    niciodata data/agent051.db.
    """
    DOSAR_DATE.mkdir(parents=True, exist_ok=True)
    conexiune = sqlite3.connect(cale or CALE_DB)
    conexiune.isolation_level = None
    conexiune.row_factory = sqlite3.Row
    return conexiune


def initializeaza_db() -> None:
    """
    Creeaza tabela `mailuri`, daca nu exista deja.

    "IF NOT EXISTS" inseamna: daca tabela e deja acolo, nu face nimic si nu te
    plange. De aceea functia se poate apela oricand, de oricate ori - nu strica
    nimic si nu sterge nimic. E o operatiune sigura prin constructie.

    Despre coloane:
      id           Message-ID din antetul mailului. E CHEIA PRIMARA, adica SQLite
                   garanteaza ca nu pot exista doua randuri cu aceeasi valoare.
                   Vezi comentariul de la salveaza_mail() - aici sta idempotenta.
      corp_text    textul mailului, curatat de HTML. Il pastram brut, asa cum a
                   venit. Interpretarea (ce joburi contine) vine mai tarziu, in
                   alt pas, si nu are voie sa strice originalul.
      data_primire cand a fost trimis mailul (dupa antetul Date).
      data_citire  cand l-am adus NOI in baza. Doua lucruri diferite: primul e al
                   expeditorului, al doilea e al nostru.

    DE CE `closing()`, aici si peste tot in fisier: `with` pe o conexiune face commit,
    dar NU o si inchide. In rularile obisnuite nu se simte - programul se termina si
    sistemul curata. In teste, care deschid de zeci de ori la rand fisiere temporare, se
    simte: o conexiune ramasa deschisa tine fisierul blocat, si pe Windows nu se mai
    poate sterge. Pana pe 17 august 2026 doar functia asta il folosea, iar testele
    ieseau cu `ResourceWarning: unclosed database`; acum forma `with closing(...) as
    conexiune, conexiune:` e aceeasi in toate cele 29 de locuri - primul `with` inchide,
    al doilea comite.
    """
    with closing(_deschide_conexiune()) as conexiune, conexiune:
        conexiune.execute(
            """
            CREATE TABLE IF NOT EXISTS mailuri (
                id            TEXT PRIMARY KEY,
                expeditor     TEXT,
                subiect       TEXT,
                data_primire  TEXT,
                sursa         TEXT,
                corp_text     TEXT,
                data_citire   TEXT
            )
            """
        )

        # Coloana corp_html a fost adaugata DUPA ce baza avea deja 444 de mesaje.
        #
        # DE CE a fost nevoie de ea: la prima ingestie am pastrat doar textul curatat
        # de HTML. Dar link-urile unui anunt nu stau in text - stau in atributele
        # href ale HTML-ului. Curatandu-l, le-am aruncat. La eJobs, care trimite
        # mailuri doar-HTML, s-au pierdut complet. Fara link nu putem identifica un
        # anunt, deci pastram si originalul.
        #
        # Adaugarea unei coloane la o tabela care are deja date se numeste MIGRARE.
        # SQLite nu are "ADD COLUMN IF NOT EXISTS", asa ca intrebam intai ce coloane
        # exista. Datele deja scrise raman neatinse - coloana noua apare goala si se
        # completeaza la urmatoarea ingestie (vezi completeaza_html).
        coloane = {
            rand[1] for rand in conexiune.execute("PRAGMA table_info(mailuri)")
        }
        if "corp_html" not in coloane:
            conexiune.execute("ALTER TABLE mailuri ADD COLUMN corp_html TEXT")

        # Anunturile individuale, sparte din mesaje. Un mesaj de la eJobs contine
        # ~20 de anunturi; fiecare devine un rand aici.
        #
        # id = amprenta link-ului CURAT al anuntului (fara coada de urmarire).
        # Acelasi job, trimis in trei mailuri diferite, are acelasi link real, deci
        # aceeasi amprenta, deci intra o singura data. Idempotenta, ca la mailuri -
        # si tot baza de date o garanteaza, prin cheia primara, nu o verificare a noastra.
        #
        # mesaj_id spune din ce mail a venit. Daca maine parserul se dovedeste gresit,
        # stii exact ce sa recitesti - si mailul brut e inca in tabela mailuri.
        conexiune.execute(
            """
            CREATE TABLE IF NOT EXISTS anunturi (
                id             TEXT PRIMARY KEY,
                mesaj_id       TEXT,
                sursa          TEXT,
                titlu          TEXT,
                firma          TEXT,
                locatie        TEXT,
                link           TEXT,
                data_anunt     TEXT,
                data_extragere TEXT,
                FOREIGN KEY (mesaj_id) REFERENCES mailuri(id)
            )
            """
        )

        # descriere si salariu_brut au fost adaugate DUPA ce baza avea deja anunturi
        # extrase - aceeasi poveste ca la corp_html de mai sus. Primele parsere scoteau
        # doar titlu, firma si link; descrierea si textul de salariu, care traiesc tot
        # in acelasi corp_html, erau aruncate. Fara ele, filtrul dur e aproape orb:
        # cauta on-call doar in titlu si nu vede niciun salariu.
        #
        # Migrare ADITIVA: coloane noi, goale, care nu ating randurile deja scrise.
        # SQLite nu are "ADD COLUMN IF NOT EXISTS", asa ca intrebam intai ce coloane
        # exista. Backfill-ul pentru anunturile vechi se face la urmatoarea extragere
        # (vezi salveaza_anunt - completeaza campurile goale, fara sa reciteasca Gmail).
        #
        # De ce TEXT si nu numar la salariu: pastram textul EXACT cum apare in mail
        # ("1600 - 1900€", "805 - 890 € (Estimare salariala)"). Interpretarea - e sub
        # prag? in ce valuta? - e alt pas, si se face in filtru, pe textul brut. Ce nu
        # salvezi acum brut nu mai poti recupera fara o re-extragere.
        coloane_anunturi = {
            rand[1] for rand in conexiune.execute("PRAGMA table_info(anunturi)")
        }
        if "descriere" not in coloane_anunturi:
            conexiune.execute("ALTER TABLE anunturi ADD COLUMN descriere TEXT")
        if "salariu_brut" not in coloane_anunturi:
            conexiune.execute("ALTER TABLE anunturi ADD COLUMN salariu_brut TEXT")

        # pagina_html / status_pagina / data_pagina: pagina publica a anuntului, luata
        # dupa `link`. Tot o migrare ADITIVA, tot fara sa atinga randurile existente.
        #
        # DE CE: descrierea lipseste la aproape tot ce nu vine de la BestJobs - eJobs si
        # LinkedIn trimit in mail doar titlu si firma. Fara descriere, filtrul dur cauta
        # cuvintele excluse doar in titlu, iar modelul raspunde "incert, lipseste
        # descrierea". Textul exista insa pe pagina publica, la link-ul din baza.
        #
        # DE CE PASTRAM HTML-UL BRUT, si nu doar descrierea extrasa din el: aceeasi
        # regula ca la `corp_html` de la mailuri, si a fost platita o data (link-urile
        # pierdute la prima ingestie). Extragerea e o INTERPRETARE si se poate dovedi
        # gresita; pagina e faptul. Cu HTML-ul in baza, un parser reparat maine se poate
        # rula peste tot ce s-a strans, fara retea si fara sa depinda de faptul ca
        # anunturile mai exista online. Discul e ieftin; o re-citire de 500 de pagini nu.
        #
        # status_pagina spune ce s-a intamplat la incercare:
        #   ok               pagina a venit, HTML-ul e in pagina_html
        #   expirat          serverul a zis 404/410 - anuntul nu mai exista
        #   interzis_robots  robots.txt nu ne lasa pe adresa aia
        #   fara_descriere   pagina a venit, dar parserul n-a gasit descrierea in ea
        # Lipsa randului (NULL) = "nu s-a incercat inca". Ce NU apare niciodata aici e
        # un esec de retea: ala inseamna ca nu stim nimic despre anunt, deci nu se scrie
        # nimic si rularea se opreste (vezi ingest/pagini.py, EroareRetea).
        if "pagina_html" not in coloane_anunturi:
            conexiune.execute("ALTER TABLE anunturi ADD COLUMN pagina_html TEXT")
        if "status_pagina" not in coloane_anunturi:
            conexiune.execute("ALTER TABLE anunturi ADD COLUMN status_pagina TEXT")
        if "data_pagina" not in coloane_anunturi:
            conexiune.execute("ALTER TABLE anunturi ADD COLUMN data_pagina TEXT")

        # Normalizarea: ce a inteles un model din fiecare anunt.
        #
        # DE CE tabela separata si nu coloane in plus pe `anunturi`:
        # in `anunturi` stau date BRUTE, citite determinist dintr-un mail. Aici stau
        # INTERPRETARI, produse de un model care se poate insela si care se va schimba.
        # Tinandu-le separat, poti sterge tot ce e mai jos si renormaliza de la zero,
        # cu alt model, fara sa atingi datele brute. Daca ar fi coloane pe `anunturi`,
        # aceeasi operatiune ar insemna un UPDATE peste randurile reale - adica exact
        # tipul de comanda care, gresit scrisa o data, iti sterge arhiva.
        #
        # anunt_id e si cheie primara: un anunt are cel mult o normalizare valabila,
        # cea mai recenta. Vezi salveaza_normalizare() pentru ce se intampla la reluare.
        #
        # status_normalizare spune ce s-a intamplat la incercare:
        #   ok         modelul a raspuns, iar raspunsul a trecut validarea
        #   respins    a raspuns, dar raspunsul era invalid (vezi coloana eroare)
        #   neincercat inca nu l-am dat pe mana modelului
        # Un anunt fara niciun rand aici e, implicit, "neincercat". Valoarea exista
        # totusi in coloana, ca sa poti marca explicit un anunt sarit intentionat.
        #
        # eroare pastreaza MOTIVUL respingerii. Fara el ai sti ca ceva n-a mers, dar
        # nu si daca modelul a inventat o senioritate sau doar a uitat o virgula -
        # iar alea doua se repara diferit.
        #
        # DEPRECATE: coloanele `relevant` si `motiv_relevanta` de mai jos.
        #
        # Nu se mai scriu si nu se mai citesc de nicaieri. Sunt un rest istoric: pe
        # vremea cand normalizarea cerea si un verdict de relevanta, modelul il dadea
        # FARA sa vada criteriile din criterii.yaml (promptul nu i le trimitea), deci
        # raspundea generic. Judecata autoritara, pe criteriile reale, traieste in
        # tabela `evaluari_calitative` (vezi mai jos). Doua coloane `relevant` in doua
        # tabele inseamna ca cineva o citeste pe cea gresita - intr-un SELECT arata
        # identic. Sursa unica e `evaluari_calitative.relevant`.
        #
        # DE CE nu le stergem cu ALTER TABLE DROP COLUMN: contin valori scrise de
        # rulari vechi, iar stergerea unei coloane e ireversibila. Nu ne incurca si nu
        # ocupa nimic; a le pastra e gratis, a le sterge din greseala nu se mai repara.
        # Randurile RE-normalizate de acum inainte le vor lasa goale (INSERT OR REPLACE
        # rescrie randul intreg), deci in timp coloanele se golesc de la sine.
        conexiune.execute(
            """
            CREATE TABLE IF NOT EXISTS anunturi_normalizate (
                anunt_id           TEXT PRIMARY KEY,
                rol_normalizat     TEXT,
                senioritate        TEXT,
                tip_munca          TEXT,
                domeniu            TEXT,
                relevant           TEXT,  -- DEPRECAT, nu se mai scrie/citeste
                motiv_relevanta    TEXT,  -- DEPRECAT, nu se mai scrie/citeste
                status_normalizare TEXT NOT NULL,
                eroare             TEXT,
                data_normalizare   TEXT,
                FOREIGN KEY (anunt_id) REFERENCES anunturi(id)
            )
            """
        )

        # Verdictul filtrului determinist pe constrangerile dure.
        #
        # DE CE tabela separata si nu coloane pe `anunturi_normalizate`:
        # cele doua depind de lucruri DIFERITE, care se schimba in ritmuri diferite.
        # Normalizarea depinde de anunt si de model. Filtrarea depinde de anunt si de
        # criterii.yaml - fisier pe care il editezi tu, cu mana, oricand. In ziua in
        # care ridici pragul de la 5000 la 6000, toate verdictele de mai jos devin
        # vechi, dar normalizarile raman perfect valabile. Separate, stergi verdictele
        # si refiltrezi in cateva secunde, fara sa rechemi niciun model si fara sa
        # platesti nimic. Impreuna, ar fi trebuit sa atingi randurile normalizate ca
        # sa reparai o cifra din alt fisier.
        #
        # versiune_criterii spune DUPA CE REGULI s-a dat verdictul (criterii.yaml,
        # meta.versiune). Fara ea, o lista de respinse e o afirmatie fara data: nu ai
        # cum sa stii daca un "respins" vine de la pragul de acum sau de la unul vechi
        # de trei luni. Cu ea, vezi dintr-o interogare ce mai trebuie refiltrat.
        #
        # motive_respingere si necunoscute sunt LISTE, iar SQLite nu are tip de lista.
        # Le pastram ca text JSON. Nu se filtreaza pe ele in SQL - se citesc cu ochii,
        # cand te uiti de ce a fost taiat un anunt. Pe verdict se filtreaza, si ala e
        # o coloana obisnuita.
        conexiune.execute(
            """
            CREATE TABLE IF NOT EXISTS anunturi_filtrate (
                anunt_id          TEXT PRIMARY KEY,
                verdict           TEXT NOT NULL,
                motive_respingere TEXT,
                necunoscute       TEXT,
                versiune_criterii TEXT,
                data_filtrare     TEXT,
                FOREIGN KEY (anunt_id) REFERENCES anunturi(id)
            )
            """
        )

        # motive_coada (29 sept. 2026): de ce un anunt care trece merge la coada
        # briefingului (birou toata saptamana, salariu sub prag_trecere). Lista JSON,
        # ca motive_respingere. Randurile vechi raman NULL pana la prima refiltrare,
        # care rescrie oricum toate verdictele.
        coloane_filtrate = {
            rand[1] for rand in conexiune.execute("PRAGMA table_info(anunturi_filtrate)")
        }
        if "motive_coada" not in coloane_filtrate:
            conexiune.execute("ALTER TABLE anunturi_filtrate ADD COLUMN motive_coada TEXT")

        # Judecata calitativa a modelului: cele trei verdicte cu motivare.
        #
        # DE CE tabela separata, iar nu coloane pe anunturi_normalizate sau _filtrate:
        # depinde de alte lucruri decat amandoua. Normalizarea depinde de anunt + model;
        # filtrarea de anunt + criterii.yaml (partea dura); asta de anunt + felia
        # CALITATIVA din criterii.yaml + model. Cand editezi semnalele calitative, doar
        # verdictele de aici imbatranesc - normalizarile si filtrarile raman valabile.
        # Separate, stergi randurile astea si reevaluezi, fara sa atingi restul.
        #
        # status_evaluare, ca la normalizare: 'ok' (raspuns valid), 'respins' (raspuns
        # invalid - vezi coloana eroare), sau lipsa randului = neincercat.
        #
        # versiune_criterii spune DUPA CE CRITERII s-a dat verdictul (criterii.yaml,
        # meta.versiune). La fel ca la filtrare: un verdict calitativ trebuie sa stie
        # din ce epoca de criterii vine, altfel nu ai cum sa stii ce e de reevaluat.
        #
        # `relevant` tine, de la criteriile 1.2, una din TREI trepte - "ideal",
        # "bun_in_domeniu", "exclus" - sau "incert". Randurile scrise pe 1.1 au inca
        # vechile "da"/"nu"; coloana e TEXT tocmai ca sa incapa amandoua epoci, iar
        # `versiune_criterii` de mai jos spune din care e fiecare rand.
        #
        # ATENTIE: verdictele astea NU sterg nimic. "relevant: exclus" e o opinie a modelului,
        # nu o filtrare. Anuntul ramane in anunturi, intreg. Aruncarea o face doar filtrul
        # dur, pe reguli certe.
        conexiune.execute(
            """
            CREATE TABLE IF NOT EXISTS evaluari_calitative (
                anunt_id                TEXT PRIMARY KEY,
                relevant                TEXT,
                motiv_relevanta         TEXT,
                interes                 TEXT,
                motiv_interes           TEXT,
                single_point_of_failure TEXT,
                motiv_spof              TEXT,
                status_evaluare         TEXT NOT NULL,
                eroare                  TEXT,
                versiune_criterii       TEXT,
                data_evaluare           TEXT,
                incercari_esuate        INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (anunt_id) REFERENCES anunturi(id)
            )
            """
        )

        # Migrare ADITIVA, ca la `anunturi`: coloana noua, pe 0, care nu atinge randurile
        # deja scrise.
        #
        # DE CE EXISTA `incercari_esuate`. Randul se scrie cu INSERT OR REPLACE, deci o
        # incercare esuata o STERGE pe cea de dinainte: dupa trei respingeri, in baza
        # arata exact ca dupa una. Iar un anunt respins e ELIGIBIL la fiecare rulare
        # urmatoare - deliberat, fiindca un anunt care esueaza repetat spune ceva despre
        # prompt sau despre model si trebuie sa se vada. Ce nu se vedea era COSTUL: un
        # singur anunt din arhiva a mancat 4.483 de tokeni pe o rulare care n-a produs
        # nimic altceva, si nimic din raport nu spunea "am platit iar pentru asta".
        #
        # Contorul asta il face vizibil, fara sa piarda informatia: cifra CRESTE, deci
        # "modelul raspunde prost" devine mai vizibil, nu mai putin. Un "nu se mai
        # incearca" pus in tacere ar fi fost mai rau decat situatia de dinainte.
        coloane_evaluari = {
            rand[1] for rand in conexiune.execute("PRAGMA table_info(evaluari_calitative)")
        }
        if "incercari_esuate" not in coloane_evaluari:
            conexiune.execute(
                "ALTER TABLE evaluari_calitative "
                "ADD COLUMN incercari_esuate INTEGER NOT NULL DEFAULT 0"
            )
            # Un rand deja "respins" e dovada unei incercari esuate - randul n-ar exista
            # altfel. Deci 1, nu 0. Nu 2 si nu "cel putin 1": cate au fost inainte de
            # coloana asta nu se mai poate afla, iar o cifra ghicita ar fi mai rea decat
            # una mica, fiindca peste doua luni n-ai mai deosebi ce s-a numarat de ce s-a
            # presupus. Aceeasi regula ca la validarea raspunsurilor de model.
            conexiune.execute(
                "UPDATE evaluari_calitative SET incercari_esuate = 1 "
                "WHERE status_evaluare = 'respins'"
            )

        # Repere de care agentul are nevoie ca sa stie "de unde reiau".
        # Primul si singurul de acum: "ultim_briefing" -> momentul ultimului briefing
        # marcat citit, in ISO 8601.
        #
        # DE CE o tabela cheie-valoare, si nu o tabela cu o coloana per reper:
        # cu o coloana per reper, fiecare reper nou (ultima_ingestie, ultima_filtrare...)
        # cere un ALTER TABLE, adica o migrare, adica o ocazie de a strica ceva intr-o
        # baza cu date reale. Cu cheie-valoare, un reper nou e un rand nou - nicio
        # schimbare de schema, niciodata. Pretul e ca valoarea e mereu TEXT si nu
        # exista verificare de tip; il platim cu placere, fiindca aici tinem doar
        # repere, nu date de lucru. Datele de lucru au tabelele lor, cu coloane pe nume.
        #
        # Alternativa "un fisier pe disc cu ultima data" a fost respinsa: ar fi insemnat
        # ca starea agentului traieste in doua locuri diferite (baza + un fisier), care
        # se pot desincroniza. O copie a bazei ar fi ramas fara reper.
        #
        # `actualizat` e cand am scris NOI randul. E diferit de `valoare`: la
        # "ultim_briefing", valoarea e reperul cerut, iar actualizat e cand a fost mutat.
        # De obicei coincid, dar nu obligatoriu - si cand nu coincid, vrei sa vezi asta.
        conexiune.execute(
            """
            CREATE TABLE IF NOT EXISTS stare (
                cheie      TEXT PRIMARY KEY,
                valoare    TEXT,
                actualizat TEXT
            )
            """
        )


def id_uri_existente() -> set:
    """
    Da toate Message-ID-urile aflate deja in baza.

    De ce o multime (set) si nu o lista: intr-o multime, intrebarea "contine id-ul
    asta?" se raspunde instantaneu, indiferent cate elemente sunt inauntru. Intr-o
    lista, calculatorul ar parcurge elementele unul cate unul. La 100 de mailuri
    nu simti diferenta; la 50.000 o simti - si acolo vom ajunge.

    Functia asta e podul catre core.ingestie.filtreaza_noi(): baza raspunde "astea
    le am", iar functia pura decide, singura, ce ramane de salvat.
    """
    with closing(_deschide_conexiune()) as conexiune, conexiune:
        cursor = conexiune.execute("SELECT id FROM mailuri")
        return {rand[0] for rand in cursor.fetchall()}


def mesaje_de_procesat() -> list:
    """
    Toate mesajele cu HTML, pentru extragerea anunturilor.

    Nu filtram dupa varsta aici, intentionat. Extragerea lucreaza pe TOATA arhiva -
    pragul de 30 de zile taie doar la EVALUARE. Un anunt din 2018 nu e o oportunitate,
    dar e o dovada ca parserul functioneaza pe sablonul din 2018. Datele istorice sunt
    setul de test cel mai bun pe care il avem.
    """
    with closing(_deschide_conexiune()) as conexiune, conexiune:
        conexiune.row_factory = sqlite3.Row
        randuri = conexiune.execute(
            "SELECT id, sursa, subiect, data_primire, corp_html FROM mailuri "
            "WHERE corp_html IS NOT NULL AND corp_html <> ''"
        ).fetchall()
    return [dict(rand) for rand in randuri]


def salveaza_anunt(
    id_anunt: str,
    mesaj_id: str,
    sursa: str,
    titlu: str,
    firma: str,
    locatie: str,
    link: str,
    data_anunt: str,
    descriere: str = "",
    salariu_brut: str = "",
) -> bool:
    """
    Salveaza un anunt. Intoarce True daca a fost NOU, False daca il aveam deja.

    Acelasi INSERT OR IGNORE ca la mailuri, din acelasi motiv: acelasi job apare in
    mai multe mailuri de alerta (platformele repeta anunturile zile la rand). Trebuie
    sa intre o singura data. Garantia o da cheia primara, nu o verificare in cod.

    BACKFILL pentru descriere si salariu_brut, exact ca la completeaza_html:
    cele 2804 de anunturi au fost extrase inainte ca parserele sa scoata aceste doua
    campuri. INSERT OR IGNORE nu le poate repara - pentru un anunt cunoscut nu face
    nimic. Deci, cand anuntul exista deja, completam campurile noi - dar NUMAI daca
    sunt goale. Un camp deja scris nu se rescrie: o re-extragere nu are voie sa strice
    ce s-a extras corect data trecuta. Asa, o simpla re-rulare a extragerii umple
    campurile noi peste toata arhiva, fara sa reciteasca Gmail si fara sa atinga restul.
    """
    acum = datetime.now(timezone.utc).isoformat()

    with closing(_deschide_conexiune()) as conexiune, conexiune:
        cursor = conexiune.execute(
            """
            INSERT OR IGNORE INTO anunturi
                (id, mesaj_id, sursa, titlu, firma, locatie, link,
                 data_anunt, data_extragere, descriere, salariu_brut)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                id_anunt, mesaj_id, sursa, titlu, firma, locatie, link,
                data_anunt, acum, descriere, salariu_brut,
            ),
        )
        nou = cursor.rowcount == 1

        # Anunt deja in baza: completam doar campurile noi ramase goale. Le tratam
        # separat - unul poate fi deja completat si celalalt nu.
        if not nou:
            if descriere:
                conexiune.execute(
                    "UPDATE anunturi SET descriere = ? "
                    "WHERE id = ? AND (descriere IS NULL OR descriere = '')",
                    (descriere, id_anunt),
                )
            if salariu_brut:
                conexiune.execute(
                    "UPDATE anunturi SET salariu_brut = ? "
                    "WHERE id = ? AND (salariu_brut IS NULL OR salariu_brut = '')",
                    (salariu_brut, id_anunt),
                )

        return nou


def anunturi_de_normalizat() -> list:
    """
    Toate anunturile, cu tot ce trebuie ca sa decizi CE se normalizeaza si CAT costa.

    Intoarce, pentru fiecare anunt:
      - titlu, firma, locatie si `corp_text` (aliasul lui `descriere`) - ce citeste modelul.
        Aliasul exista fiindca `construieste_prompt` din core/ cere campul `corp_text`,
        exact numele pe care il primeste si un anunt de test. Baza tine textul in coloana
        `descriere`; il servim sub numele asteptat de core/, ca sa nu atingem functia pura.
        LOCATIA conteaza pentru tip_munca: multe anunturi (mai ales LinkedIn) pun felul
        muncii chiar acolo ("România (De la distanță)" = remote). Fara ea in prompt, modelul
        n-are de unde deduce si scrie "nespecificat" - iar un remote real ar fi tratat incert.
      - `data_anunt` - data mesajului din care a venit (pusa la extragere). Filtrul de
        varsta se sprijina pe ea: nu cheltuim un apel de model pe un anunt din 2018.
      - `status_normalizare` - din LEFT JOIN cu `anunturi_normalizate`. `None` inseamna
        "neincercat".
      - `descriere_dupa_normalizare` - anuntul a capatat descriere din pagina publica DUPA
        ce fusese normalizat. Vezi nota comuna de la _DESCRIERE_MAI_NOUA_DECAT.

    DE CE intoarcem TOT, inclusiv anunturile deja normalizate cu succes si pe cele vechi:
    ca deciziile - "e prea vechi?", "l-am facut deja?", "am atins limita?" - sa se ia la
    vedere, in adaptor, nu ascunse intr-un WHERE de aici. Acelasi principiu ca la
    anunturi_pentru_calitativ: baza aduce faptele, adaptorul alege. Un WHERE care taie
    tacit e exact felul de regula pe care nu ti-o mai amintesti peste doua luni, cand te
    intrebi de ce un anunt n-a fost niciodata normalizat.

    LEFT JOIN, nu JOIN: un anunt fara nicio incercare de normalizare (cazul obisnuit)
    trebuie sa APARA, cu status_normalizare gol - altfel n-ar ajunge niciodata la model.
    """
    with closing(_deschide_conexiune()) as conexiune, conexiune:
        conexiune.row_factory = sqlite3.Row
        randuri = conexiune.execute(
            """
            SELECT a.id, a.titlu, a.firma, a.locatie, a.descriere AS corp_text,
                   a.data_anunt, n.status_normalizare,
            """ + _descriere_mai_noua_decat("n.data_normalizare") + """
                   AS descriere_dupa_normalizare
            FROM anunturi a
            LEFT JOIN anunturi_normalizate n ON n.anunt_id = a.id
            """
        ).fetchall()
    return [dict(rand) for rand in randuri]


def anunturi_pentru_descriere() -> list:
    """
    Toate anunturile, cu tot ce trebuie ca sa decizi CAROR pagini merita sa le ceri.

    Intoarce, pentru fiecare anunt:
      - `sursa` si `link` - de unde si de la ce adresa s-ar cere pagina;
      - `descriere` - ca sa se vada cine are deja text si nu are nevoie de pagina;
      - `data_anunt` - pentru filtrul de varsta (nu cerem pagini pentru anunturi din 2018);
      - `status_pagina` - `None` inseamna "nu s-a incercat inca".

    DE CE intoarce TOT, inclusiv anunturile care au deja descriere, pe cele vechi si pe
    cele deja luate: la fel ca la anunturi_de_normalizat si anunturi_pentru_calitativ -
    baza aduce faptele, adaptorul alege, la vedere. Un WHERE care taie tacit aici e exact
    felul de regula pe care n-o mai gasesti peste doua luni, cand te intrebi de ce unui
    anunt nu i s-a cerut niciodata pagina.

    NU aduce `pagina_html`. E singura abatere de la "aduce faptele", si e deliberata:
    coloana aia tine sute de kilobytes per rand, iar decizia "cerem pagina asta?" nu are
    nevoie de continutul ei, doar de statusul incercarii. Citit intreg, ar insemna sute
    de megabytes tarati prin memorie pentru o comparatie de siruri.
    """
    with closing(_deschide_conexiune()) as conexiune, conexiune:
        conexiune.row_factory = sqlite3.Row
        randuri = conexiune.execute(
            """
            SELECT id, sursa, titlu, link, descriere, data_anunt, status_pagina
            FROM anunturi
            """
        ).fetchall()
    return [dict(rand) for rand in randuri]


def salveaza_pagina(anunt_id: str, rezultat: dict) -> None:
    """
    Scrie rezultatul unei incercari de a lua pagina unui anunt.

    `rezultat` e ce intoarce adapters.descrieri.ia_descrierea_unui_anunt():
        {"status": "ok",              "html": "<!doctype...", "descriere": "..."}
        {"status": "expirat",         "html": None, "descriere": None}
        {"status": "interzis_robots", "html": None, "descriere": None}
        {"status": "fara_descriere",  "html": "<!doctype...", "descriere": None}

    Aici nu se ia nicio decizie si nu se valideaza nimic - judecata s-a facut deja, in
    core/ si in adaptor. Functia asta doar scrie.

    UPDATE, nu INSERT OR REPLACE: randul anuntului EXISTA deja (a fost scris la extragere,
    din mail) si contine date brute pe care n-avem voie sa le atingem - titlu, firma,
    link, data. Aici completam doar trei coloane in plus, plus descrierea daca am gasit-o.

    DESCRIEREA NU SE SUPRASCRIE NICIODATA cu una noua daca exista deja una. De aia
    COALESCE(NULLIF(...)) in loc de o atribuire simpla: descrierea din mail (la BestJobs)
    e la fel de reala ca cea din pagina, si a fost acolo prima. Daca maine cineva ruleaza
    din greseala peste tot, textul vechi nu se pierde. Anunturile care au deja descriere
    sunt oricum sarite mai devreme, in adaptor; asta e a doua plasa, in baza, unde nu
    poate fi ocolita dintr-o rescriere de adaptor.

    FIRMA se completeaza dupa exact aceeasi regula ca descrierea: doar cand e goala.
    TITLUL e singurul care se poate INLOCUI, si numai daca adaptorul a trimis unul -
    ceea ce se intampla doar in cazul demonstrat de titlul_de_pastrat() (titlul din mail
    e cel din pagina plus mobilier lipit). Fara valoare trimisa, ramane ce era.
    """
    acum = datetime.now(timezone.utc).isoformat()
    descriere = (rezultat.get("descriere") or "").strip() or None
    firma = (rezultat.get("firma") or "").strip() or None
    titlu = (rezultat.get("titlu") or "").strip() or None

    with closing(_deschide_conexiune()) as conexiune, conexiune:
        conexiune.execute(
            """
            UPDATE anunturi
            SET pagina_html   = ?,
                status_pagina = ?,
                data_pagina   = ?,
                descriere     = COALESCE(NULLIF(TRIM(COALESCE(descriere, '')), ''), ?),
                firma         = COALESCE(NULLIF(TRIM(COALESCE(firma, '')), ''), ?),
                titlu         = COALESCE(?, titlu)
            WHERE id = ?
            """,
            (
                rezultat.get("html"), rezultat.get("status"), acum,
                descriere, firma, titlu, anunt_id,
            ),
        )


def pagina_salvata(anunt_id: str) -> str:
    """HTML-ul brut al paginii unui anunt, sau sir gol daca nu s-a salvat niciunul."""
    with closing(_deschide_conexiune()) as conexiune, conexiune:
        rand = conexiune.execute(
            "SELECT pagina_html FROM anunturi WHERE id = ?", (anunt_id,)
        ).fetchone()
    return (rand[0] if rand and rand[0] else "")


def salveaza_normalizare(anunt_id: str, rezultat: dict) -> None:
    """
    Scrie rezultatul normalizarii unui anunt.

    `rezultat` e exact ce intoarce adapters.normalizare.normalizeaza_anunt():
        {"ok": True,  "date": {...}}   -> status "ok", campurile completate
        {"ok": False, "eroare": "..."} -> status "respins", campurile goale

    Aici nu se ia nicio decizie si nu se valideaza nimic. Judecata "e bun sau nu"
    a fost deja luata, in core/, de o functie pura. Functia asta doar scrie.

    Coloanele deprecate `relevant` si `motiv_relevanta` nu apar in INSERT: nu mai fac
    parte din schema normalizarii. Vezi nota de la CREATE TABLE.

    DE CE "INSERT OR REPLACE", si nu "INSERT OR IGNORE" ca la mailuri si anunturi:
    acolo, un rand nou care se ciocneste de unul vechi e un DUPLICAT - acelasi mail
    citit a doua oara - si trebuie ignorat. Aici e altceva: e o reincercare. Un anunt
    respins azi, reincercat maine cu un prompt mai bun sau alt model, trebuie sa-si
    poata inlocui verdictul vechi. Cu IGNORE, prima incercare - inclusiv un esec -
    ar ramane inghetata pentru totdeauna, iar renormalizarea n-ar face nimic.
    Se suprascriu doar INTERPRETARI. Datele brute din `anunturi` raman neatinse.
    """
    acum = datetime.now(timezone.utc).isoformat()
    date = rezultat.get("date") or {}
    a_reusit = bool(rezultat.get("ok"))

    with closing(_deschide_conexiune()) as conexiune, conexiune:
        conexiune.execute(
            """
            INSERT OR REPLACE INTO anunturi_normalizate
                (anunt_id, rol_normalizat, senioritate, tip_munca, domeniu,
                 status_normalizare, eroare, data_normalizare)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                anunt_id,
                date.get("rol_normalizat"),
                date.get("senioritate"),
                date.get("tip_munca"),
                date.get("domeniu"),
                "ok" if a_reusit else "respins",
                None if a_reusit else rezultat.get("eroare"),
                acum,
            ),
        )


def anunturi_de_filtrat() -> list:
    """
    Anunturile normalizate cu succes, cu tot ce trebuie filtrului determinist.

    Imbina cele doua tabele: datele brute din `anunturi` (titlu, locatie) cu ce a
    inteles modelul din ele (`tip_munca`, `rol_normalizat`). Filtrul are nevoie de
    amandoua - locatia scrie in anunt, dar "e remote sau nu" e o interpretare.

    Luam DOAR randurile cu status_normalizare = 'ok'. Un anunt a carui normalizare a
    fost respinsa nu are `tip_munca` de incredere, iar filtrul ar decide pe un camp
    gol - adica ar produce un verdict care pare informat si nu e. Alea se renormalizeaza
    intai, se filtreaza dupa.

    Nu filtram dupa varsta aici. Pragul de 30 de zile taie la EVALUARE; filtrul
    determinist e ieftin si se poate rula pe tot, inclusiv pe arhiva - unde e cel mai
    bun set de test pe care il avem pentru regulile astea.
    """
    with closing(_deschide_conexiune()) as conexiune, conexiune:
        conexiune.row_factory = sqlite3.Row
        randuri = conexiune.execute(
            """
            SELECT a.id, a.sursa, a.titlu, a.firma, a.locatie, a.link,
                   a.descriere, a.salariu_brut, a.status_pagina,
                   n.rol_normalizat, n.senioritate, n.tip_munca, n.domeniu
            FROM anunturi a
            JOIN anunturi_normalizate n ON n.anunt_id = a.id
            WHERE n.status_normalizare = 'ok'
            """
        ).fetchall()
    return [dict(rand) for rand in randuri]


def acoperire_extractie() -> list:
    """
    Cat de "vazator" a devenit filtrul: per sursa, cate anunturi au acum descriere
    si cate au salariu (si, prin total, cate n-au).

    Nu evalueaza nimic - doar numara. Filtrul dur cauta cuvinte in descriere si
    interpreteaza salariul din salariu_brut; cifrele astea spun cat de multe anunturi
    ii dau efectiv ceva de citit. Daca "cu_descriere" e 0 pe o sursa, filtrul e la fel
    de orb ca inainte pe sursa aia - si e mai bine sa afli dintr-o cifra.

    Intoarce cate un dict pe sursa: {sursa, total, cu_descriere, cu_salariu}.
    """
    with closing(_deschide_conexiune()) as conexiune, conexiune:
        conexiune.row_factory = sqlite3.Row
        randuri = conexiune.execute(
            """
            SELECT sursa,
                   COUNT(*) AS total,
                   SUM(CASE WHEN descriere    IS NOT NULL AND descriere    <> ''
                            THEN 1 ELSE 0 END) AS cu_descriere,
                   SUM(CASE WHEN salariu_brut IS NOT NULL AND salariu_brut <> ''
                            THEN 1 ELSE 0 END) AS cu_salariu
            FROM anunturi
            GROUP BY sursa
            ORDER BY sursa
            """
        ).fetchall()
    return [dict(rand) for rand in randuri]


def salveaza_filtrare(anunt_id: str, rezultat: dict, versiune_criterii: str) -> None:
    """
    Scrie verdictul filtrarii pentru un anunt.

    `rezultat` e exact ce intoarce core.filtrare.filtreaza_dur():
        {"verdict": ..., "motive_respingere": [...], "necunoscute": [...]}

    Aici nu se ia nicio decizie. Judecata "trece sau nu" a fost deja luata, in core/,
    de o functie pura. Functia asta doar scrie.

    INSERT OR REPLACE, din acelasi motiv ca la normalizare, dar cu si mai mult temei:
    verdictul depinde de criterii.yaml, care e facut sa fie editat. O refiltrare dupa
    ce ai schimbat un prag TREBUIE sa inlocuiasca verdictul vechi - altfel ai in baza
    raspunsul dat de o regula care nu mai exista, si nimic nu ti-ar spune asta.
    """
    acum = datetime.now(timezone.utc).isoformat()

    with closing(_deschide_conexiune()) as conexiune, conexiune:
        conexiune.execute(
            """
            INSERT OR REPLACE INTO anunturi_filtrate
                (anunt_id, verdict, motive_respingere, necunoscute,
                 versiune_criterii, data_filtrare, motive_coada)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                anunt_id,
                rezultat["verdict"],
                # ensure_ascii=False ca diacriticele sa ramana citibile daca deschizi
                # baza cu un vizualizator. Altfel "locatie" ar fi scris cu coduri.
                json.dumps(rezultat.get("motive_respingere") or [], ensure_ascii=False),
                json.dumps(rezultat.get("necunoscute") or [], ensure_ascii=False),
                versiune_criterii,
                acum,
                json.dumps(rezultat.get("motive_coada") or [], ensure_ascii=False),
            ),
        )


def anunturi_pentru_calitativ() -> list:
    """
    Anunturile care merg la evaluarea calitativa: cele care au trecut filtrul dur.

    Imbina `anunturi` (titlu, firma, descriere - ce citeste modelul) cu verdictul din
    `anunturi_filtrate`. Intoarce SI verdictul, ca adaptorul sa poata pastra doar
    "trece" si "incert" - decizia "cine merge la model" o ia el, cu o regula la vedere,
    nu se ascunde intr-un WHERE de aici. Vezi VERDICTE_CARE_MERG_LA_MODEL in
    adapters/evaluare_calitativa.py.

    `are_evaluare_valabila` spune daca anuntul are DEJA un verdict bun pe versiunea de
    criterii de acum - adica daca a-l trimite la model ar insemna sa platesti a doua oara
    pentru acelasi raspuns. Se calculeaza cu ACEEASI bucata de SQL prin care trec si
    citirile (JOIN_EVALUARE_VALABILA), nu cu o conditie scrisa inca o data aici: daca
    selectia pentru evaluare si citirea din briefing ar folosi doua reguli scrise separat,
    s-ar putea desparti in timp, si atunci ai plati pentru evaluari pe care nu le citeste
    nimeni - sau, mai rau, ai sari peste anunturi pe care briefingul le considera goale.

    `descriere_dupa_evaluare` spune daca anuntul a capatat descriere din pagina publica
    DUPA ce primise verdictul - adica daca verdictul de acum a fost dat pe un titlu gol,
    iar acum e text de citit. Vezi _descriere_mai_noua_decat pentru ce inseamna exact.

    `incercari_esuate` spune de cate ori s-a platit deja degeaba pentru anuntul asta - un
    raspuns care n-a trecut validarea. Vine de la orice_e, NU de la evaluarea valabila:
    un anunt care esueaza n-are evaluare valabila (de aia se si reincearca), deci pe
    cealalta ramura ar fi mereu 0 - adica exact anunturile despre care intrebam ar fi
    singurele care nu s-ar vedea. Cu 0 pentru cine n-a esuat niciodata.

    Tot FAPTE, nu decizii: functia asta nu sare si nu rejudeca nimic. Le aduce marcate, iar
    adaptorul alege si NUMARA - altfel raportul n-ar putea spune cati au fost sariti si
    de ce, iar un "ar evalua 1 din 83" pe care nu-l poti verifica nu ajuta pe nimeni.

    JOIN, nu LEFT JOIN, la `anunturi_filtrate`: un anunt fara verdict de filtrare inca
    n-a trecut prin filtrul dur, deci nu are ce cauta la model - filtrul e primul strat,
    modelul al doilea.
    """
    with closing(_deschide_conexiune()) as conexiune, conexiune:
        conexiune.row_factory = sqlite3.Row
        randuri = conexiune.execute(
            """
            SELECT a.id, a.titlu, a.firma, a.descriere,
                   f.verdict,
                   (e.anunt_id IS NOT NULL) AS are_evaluare_valabila,
                   COALESCE(orice_e.incercari_esuate, 0) AS incercari_esuate,
            """ + _descriere_mai_noua_decat("e.data_evaluare") + """
                   AS descriere_dupa_evaluare
            FROM anunturi a
            JOIN anunturi_filtrate f ON f.anunt_id = a.id
            """ + JOIN_EVALUARE_VALABILA + JOIN_ORICE_EVALUARE,
            (versiune_criterii(),),
        ).fetchall()
    return [dict(rand) for rand in randuri]


def salveaza_evaluare_calitativa(
    anunt_id: str, rezultat: dict, versiune_criterii: str
) -> None:
    """
    Scrie evaluarea calitativa a unui anunt.

    `rezultat` e exact ce intoarce adapters.evaluare_calitativa.evalueaza_anunt():
        {"ok": True,  "date": {...}}   -> status "ok", cele sase campuri completate
        {"ok": False, "eroare": "..."} -> status "respins", campurile goale

    Aici nu se ia nicio decizie si nu se valideaza nimic - judecata "e bun raspunsul"
    a fost deja luata, in core/, de o functie pura. Functia asta doar scrie.

    INSERT OR REPLACE, ca la normalizare si filtrare: o reevaluare (alt model, alt
    prompt, sau criterii calitative editate) trebuie sa poata inlocui verdictul vechi.
    Se suprascriu doar OPINII; datele brute din `anunturi` raman neatinse.

    O SINGURA COLOANA SUPRAVIETUIESTE REESCRIERII: `incercari_esuate`. Toate celelalte
    sunt "ce a spus modelul ultima data" si se inlocuiesc cu drag. Aia e "de cate ori am
    platit degeaba pentru anuntul asta" - un fapt despre istoria noastra, nu o opinie a
    modelului, iar INSERT OR REPLACE l-ar sterge la fiecare incercare. De aia se citeste
    inainte si se scrie adunat, in aceeasi tranzactie: intre citire si scriere nu are ce
    sa se schimbe, fiindca evaluarea ruleaza un anunt pe rand.

    NU se reseteaza la reusita. Un anunt care a mers din a treia incercare a costat trei
    apeluri, si asta ramane adevarat dupa ce a mers.
    """
    acum = datetime.now(timezone.utc).isoformat()
    date = rezultat.get("date") or {}
    a_reusit = bool(rezultat.get("ok"))

    with closing(_deschide_conexiune()) as conexiune, conexiune:
        rand_vechi = conexiune.execute(
            "SELECT incercari_esuate FROM evaluari_calitative WHERE anunt_id = ?",
            (anunt_id,),
        ).fetchone()
        esecuri = (rand_vechi[0] if rand_vechi else 0) or 0
        if not a_reusit:
            esecuri += 1

        conexiune.execute(
            """
            INSERT OR REPLACE INTO evaluari_calitative
                (anunt_id, relevant, motiv_relevanta, interes, motiv_interes,
                 single_point_of_failure, motiv_spof, status_evaluare, eroare,
                 versiune_criterii, data_evaluare, incercari_esuate)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                anunt_id,
                date.get("relevant"),
                date.get("motiv_relevanta"),
                date.get("interes"),
                date.get("motiv_interes"),
                date.get("single_point_of_failure"),
                date.get("motiv_spof"),
                "ok" if a_reusit else "respins",
                None if a_reusit else rezultat.get("eroare"),
                versiune_criterii,
                acum,
                esecuri,
            ),
        )



def citeste_stare(cheie: str):
    """
    Da valoarea unui reper, sau None daca nu a fost scris niciodata.

    None inseamna "nu s-a intamplat inca", si e un raspuns legitim, nu o eroare:
    la primul briefing nu exista niciun reper anterior, iar cine intreaba trebuie
    sa poata deosebi "n-a fost niciodata" de "a fost, si e vechi".
    """
    with closing(_deschide_conexiune()) as conexiune, conexiune:
        rand = conexiune.execute(
            "SELECT valoare FROM stare WHERE cheie = ?", (cheie,)
        ).fetchone()
    return rand[0] if rand else None


def scrie_stare(cheie: str, valoare: str) -> None:
    """
    Scrie (sau rescrie) un reper.

    INSERT OR REPLACE: un reper are prin definitie o singura valoare valabila, cea
    de acum. Nu tinem istoricul reperelor - daca vreodata va fi nevoie de el, va fi
    o tabela separata, nu randuri in plus aici.
    """
    acum = datetime.now(timezone.utc).isoformat()
    with closing(_deschide_conexiune()) as conexiune, conexiune:
        conexiune.execute(
            "INSERT OR REPLACE INTO stare (cheie, valoare, actualizat) VALUES (?, ?, ?)",
            (cheie, valoare, acum),
        )


def _int_din_stare(cheie: str) -> int:
    """
    Citeste un reper numeric din `stare` si il da ca intreg. Lipsa sau stricat -> 0.

    Valorile din `stare` sunt mereu TEXT (tabela e cheie-valoare, fara tip). Un contor
    care n-a fost scris niciodata inseamna "zero pana acum", nu o eroare - de aia lipsa
    devine 0, nu o exceptie.
    """
    return _ca_intreg(citeste_stare(cheie))


def _ca_intreg(valoare) -> int:
    """Textul unui contor din `stare`, ca intreg. Lipsa sau stricat -> 0."""
    try:
        return int(valoare)
    except (TypeError, ValueError):
        return 0


def acumuleaza_cost(apeluri: int, tokeni_intrare: int, tokeni_iesire: int, luna: str) -> None:
    """
    Aduna la contoarele cumulate de cost din `stare`: apeluri_total si tokeni_total, plus
    contoarele lunii `luna` ("2026-09"), cu intrarea si iesirea separate.

    DE CE pe luna si separat: bugetul e lunar, iar un token de iesire costa de cinci ori
    cat unul de intrare - din totalul amestecat nu se poate scoate un pret. Totalul istoric
    ramane cum era, ca cifrele vechi sa nu se piarda.

    Cumulat, nu per rulare: vrei sa vezi cat a costat agentul de cand exista, nu doar
    ultima apasare. Citim ce era, adunam, scriem la loc. Toate cele cinci contoare intr-O
    SINGURA tranzactie, deschisa cu BEGIN IMMEDIATE: pana la 30 sept. 2026 erau cinci
    tranzactii separate, iar doua rulari simultane (normalizeaza si evalueaza cerute
    deodata din JA.S.Mine) puteau citi amandoua aceeasi valoare veche si pierde o adunare.
    IMMEDIATE ia lacatul de scriere de la inceput, deci a doua rulare asteapta, apoi
    citeste valoarea deja adunata.

    Se cheama DOAR dupa o rulare reala care chiar a apelat modelul; un dry run nu
    cheltuie nimic, deci nu are ce aduna aici.

    Nu tinem istoric pe rulari (cate a costat fiecare) - ala ar fi o tabela separata, si
    nu s-a cerut. Aici tinem doar totalul, care raspunde la intrebarea practica: "cat am
    cheltuit pana acum?".
    """
    adunari = {
        "apeluri_total": apeluri,
        "tokeni_total": tokeni_intrare + tokeni_iesire,
        f"consum:{luna}:apeluri": apeluri,
        f"consum:{luna}:tokeni_intrare": tokeni_intrare,
        f"consum:{luna}:tokeni_iesire": tokeni_iesire,
    }
    acum = datetime.now(timezone.utc).isoformat()
    with closing(deschide_cu_tranzactie_manuala()) as conexiune:
        conexiune.execute("BEGIN IMMEDIATE")
        try:
            for cheie, plus in adunari.items():
                rand = conexiune.execute(
                    "SELECT valoare FROM stare WHERE cheie = ?", (cheie,)
                ).fetchone()
                total = _ca_intreg(rand[0] if rand else None) + plus
                conexiune.execute(
                    "INSERT OR REPLACE INTO stare (cheie, valoare, actualizat) "
                    "VALUES (?, ?, ?)",
                    (cheie, str(total), acum),
                )
            conexiune.execute("COMMIT")
        except BaseException:
            conexiune.execute("ROLLBACK")
            raise


def consum_lunar(luna: str) -> dict:
    """
    Consumul lunii `luna` ("2026-09"): apeluri, tokeni_intrare, tokeni_iesire.

    O luna fara nicio rulare da zerouri. Contoarele lunare exista din 29 septembrie 2026;
    ce s-a consumat inainte e doar in totalul istoric, fara impartire pe luni.
    """
    return {
        camp: _int_din_stare(f"consum:{luna}:{camp}")
        for camp in ("apeluri", "tokeni_intrare", "tokeni_iesire")
    }


def cost_cumulat() -> dict:
    """
    Contoarele de cost, ca numere: {"apeluri_total": ..., "tokeni_total": ...}.

    Pe o baza pe care nu s-a rulat niciun model, amandoua sunt 0 - raspunsul corect la
    "cat ai cheltiuit?" inainte de primul apel. Le intoarce stare_pipeline(), ca sa se
    vada langa etapele fluxului cat a costat pana acum.
    """
    return {
        "apeluri_total": _int_din_stare("apeluri_total"),
        "tokeni_total": _int_din_stare("tokeni_total"),
    }


# DE CE se poate compara text cu text la cele doua functii de mai jos, desi la date ISO
# comparatia pe text minte de obicei:
#
# Minte cand datele pot avea fusuri diferite. "2026-07-13T09:15:00+03:00" pare, ca text,
# mai tarziu decat "2026-07-13T08:02:33+00:00" - dar 09:15 ora Romaniei ESTE 06:15 UTC,
# deci e mai devreme. Asa arata `data_primire`, care vine din antetul mailului si poarta
# fusul expeditorului.
#
# Aici insa comparam `data_citire` si `data_extragere` - date scrise de NOI, mereu cu
# datetime.now(timezone.utc).isoformat(), deci mereu in acelasi fus. Doua siruri in
# acelasi fus se compara corect ca text, iar SQLite face treaba direct in interogare.
# Daca vreodata cineva scrie una dintre coloanele astea cu alt fus, presupunerea cade -
# de aia sta scrisa aici, nu doar in capul cuiva.


def numara_mesaje_noi(de_la: str = None) -> int:
    """
    Cate mesaje au intrat in baza dupa reperul dat.

    de_la = None inseamna "de la inceput" si numara tot. Asa arata primul briefing:
    n-a existat niciodata unul, deci tot ce e in baza e nou fata de nimic.
    """
    with closing(_deschide_conexiune()) as conexiune, conexiune:
        if de_la is None:
            rand = conexiune.execute("SELECT COUNT(*) FROM mailuri").fetchone()
        else:
            rand = conexiune.execute(
                "SELECT COUNT(*) FROM mailuri WHERE data_citire > ?", (de_la,)
            ).fetchone()
    return rand[0]


# Momentul "cand s-a aflat ultima data ceva despre anuntul asta".
#
# DE CE EXISTA. Ce face un anunt demn de raportat nu e sosirea lui, e JUDECATA despre el -
# care vine mai tarziu, uneori cu minute, alteori cu zile. Cat timp taietura briefingului
# se facea pe `data_extragere`, orice evaluare care ateriza dupa un briefing marcat, pe un
# anunt sosit inainte de el, ramanea invizibila in ORICE briefing viitor. Nu ascunsa: in
# afara taieturii, pentru totdeauna. S-a intamplat pe 16 august 2026 - briefing marcat la
# 18:28, zece evaluari date intre 18:31 si 18:32 pe anunturi sosite la 13:59. Briefingul
# de dupa a spus "nimic nou", corect dupa regula lui si gresit dupa bunul simt.
#
# Axa corecta era deja folosita in aceeasi functie, la cealalta jumatate a raportului:
# `numara_mesaje_noi` taie pe `data_citire` - cand am citit NOI mailul, nu cand l-a trimis
# expeditorul. Adica exact "cand am aflat".
#
# `e` e evaluarea VALABILA (vezi JOIN_EVALUARE_VALABILA): pe versiunea de criterii de acum
# si cu status 'ok'. Deci un verdict dat dupa reper, dar pe criterii vechi, NU aduce
# anuntul inapoi in briefing - altfel s-ar intoarce verdictele moarte.
#
# IFNULL, fiindca MAX() din SQLite intoarce NULL daca oricare argument e NULL - iar un
# anunt neevaluat n-are `data_evaluare`. Cu sirul gol, care e mai mic decat orice data
# ISO, ramane `data_extragere`, adica exact comportamentul de dinainte.
#
# `data_filtrare` NU e in formula, si e o decizie, nu o scapare: filtrarea se ruleaza pe
# TOT, de fiecare data (sute de randuri rescrise in cateva secunde). Daca ar intra aici,
# orice re-filtrare ar face toate anunturile "noi", iar briefingul ar spune de fiecare
# data totul - adica inversul distilarii. Evaluarea, in schimb, se scrie per anunt si doar
# cand chiar s-a aflat ceva.
ULTIMA_STIRE_DESPRE_ANUNT = "MAX(a.data_extragere, IFNULL(e.data_evaluare, ''))"


def anunturi_pentru_briefing(de_la: str = None) -> list:
    """
    Anunturile despre care s-a aflat ceva dupa reper, cu tot ce s-a aflat intre timp.

    Aduna la un loc cele trei straturi: anuntul brut, verdictul filtrului dur si
    verdictele evaluarii calitative. Briefingul are nevoie de toate trei ca sa poata
    spune si CATE au picat, si CARE merita atentie, si DE CE.

    LEFT JOIN la amandoua tabelele de interpretare, nu JOIN: un anunt intrat acum
    zece minute inca n-a fost nici filtrat, nici evaluat. Cu JOIN ar disparea din
    briefing exact anunturile cele mai noi - adica fix cele pentru care ceri briefingul.
    Asa apare, cu campurile de interpretare goale, iar cine se uita vede ca il asteapta
    o filtrare, nu ca nu exista.

    EVALUARILE se iau doar pe versiunea de criterii de acum - vezi JOIN_EVALUARE_VALABILA.
    Un anunt evaluat pe criterii vechi vine cu verdictele goale, dar cu
    `are_evaluare_oarecare` adevarat: briefingul are nevoie de distinctie ca sa poata
    spune ca lipsa nu inseamna "n-a fost nimic", ci "trebuie reevaluat".

    TAIETURA e pe "cand s-a aflat ultima data ceva" - vezi ULTIMA_STIRE_DESPRE_ANUNT.
    Un anunt sosit inaintea reperului, dar evaluat dupa el, e o stire noua si apare.

    Nu filtreaza si nu sorteaza nimic: alea sunt decizii, si se iau in core/briefing.py.
    Functia asta doar aduce randurile.
    """
    interogare = """
        SELECT a.id, a.titlu, a.firma, a.link, a.data_anunt, a.data_extragere,
               f.verdict, f.motive_respingere, f.motive_coada,
               e.relevant, e.motiv_relevanta,
               e.interes, e.motiv_interes,
               e.single_point_of_failure,
               (orice_e.anunt_id IS NOT NULL) AS are_evaluare_oarecare
        FROM anunturi a
        LEFT JOIN anunturi_filtrate f ON f.anunt_id = a.id
    """ + JOIN_EVALUARE_VALABILA + JOIN_ORICE_EVALUARE

    versiune = versiune_criterii()

    with closing(_deschide_conexiune()) as conexiune, conexiune:
        conexiune.row_factory = sqlite3.Row
        if de_la is None:
            randuri = conexiune.execute(interogare, (versiune,)).fetchall()
        else:
            randuri = conexiune.execute(
                interogare + f" WHERE {ULTIMA_STIRE_DESPRE_ANUNT} > ?", (versiune, de_la)
            ).fetchall()

    anunturi = []
    for rand in randuri:
        anunt = dict(rand)
        # motive_respingere e salvat ca text JSON (SQLite n-are tip de lista).
        # Il desfacem AICI, ca sa nu ajunga in core/ un sir care trebuie parsat -
        # core/ primeste date gata facute, nu ambalaje de desfacut.
        anunt["motive_respingere"] = _lista_din_json(anunt.get("motive_respingere"))
        anunt["motive_coada"] = _lista_din_json(anunt.get("motive_coada"))
        anunturi.append(anunt)
    return anunturi


def cauta_anunturi(text: str, limita: int = 10) -> list:
    """
    Anunturile care contin textul cautat in titlu, firma sau descriere.

    Cauta si in ce a scris angajatorul (titlu, descriere), si in numele firmei. NU cauta
    in motivarile modelului: alea sunt proza despre anunt, nu anuntul - vezi acelasi
    rationament in CAMPURI_DE_CAUTAT din core/filtrare.py.

    LIMITARE DE STIUT, fiindca se vede la prima cautare in romana: `LIKE` din SQLite
    ignora diferenta dintre litere mari si mici DOAR la alfabetul englezesc. "PAYROLL"
    gaseste "payroll", dar "Salarizare" nu gaseste "SALARIZARE" din cauza lui "ă/Ă", si
    "salarizare" nu gaseste "salarizări". Nu incercam sa reparam asta aici cu vreo
    normalizare de diacritice: ar insemna sa scriem o functie de cautare, iar aia e
    logica, nu persistenta. Deocamdata cauti cum e scris in anunt.

    Cele mai recent extrase primele, si `id` ca departajator la egalitate - ca doua
    cautari identice sa dea aceeasi lista, nu doua ordini diferite.

    Verdictele calitative vin doar de pe versiunea de criterii de acum, ca peste tot -
    vezi JOIN_EVALUARE_VALABILA. Un anunt evaluat pe criterii vechi apare in rezultate
    (e tot un anunt gasit), dar cu `relevant` si `interes` goale, nu cu un verdict din
    alta epoca prezentat ca si cum ar fi de azi.
    """
    tipar = f"%{text}%"

    with closing(_deschide_conexiune()) as conexiune, conexiune:
        conexiune.row_factory = sqlite3.Row
        randuri = conexiune.execute(
            """
            SELECT a.id, a.titlu, a.firma, a.locatie, a.link, a.salariu_brut,
                   a.data_extragere,
                   f.verdict,
                   e.relevant, e.interes
            FROM anunturi a
            LEFT JOIN anunturi_filtrate f ON f.anunt_id = a.id
            """ + JOIN_EVALUARE_VALABILA + """
            WHERE a.titlu LIKE ? OR a.firma LIKE ? OR a.descriere LIKE ?
            ORDER BY a.data_extragere DESC, a.id ASC
            LIMIT ?
            """,
            (versiune_criterii(), tipar, tipar, tipar, limita),
        ).fetchall()

    return [dict(rand) for rand in randuri]


def numara_pe_etape() -> dict:
    """
    Cate randuri exista la fiecare etapa a fluxului. Fotografia bazei, in cifre.

    DE CE e utila: fluxul are sase etape care se ruleaza separat (ingestie, extragere,
    descrieri, normalizare, filtrare, evaluare calitativa). Cand ceva pare in neregula,
    prima intrebare e "unde s-a oprit?". Cifrele astea raspund dintr-o privire: 500 de
    mailuri, 900 de anunturi, dar 0 normalizate inseamna ca normalizarea n-a rulat
    niciodata.

    Pe o baza goala intoarce aceleasi chei, toate pe zero. Nu e o eroare si nu e un caz
    special: inainte de prima ingestie, raspunsul corect la "cate mailuri ai?" este zero.

    EVALUARILE SE NUMARA IN DOUA CIFRE, nu intr-una: cate sunt pe criteriile de acum si
    cate au ramas pe versiuni vechi. Un singur total ar ascunde exact intrebarea care
    conteaza dupa o urcare de versiune - "cat din ce am platit mai e valabil?". Cu doua
    cifre, "evaluate_calitativ_curente: 0, evaluate_calitativ_vechi: 44" se citeste
    singur: e de rulat evaluarea, nu e stricat nimic.
    """
    versiune = versiune_criterii()

    with closing(_deschide_conexiune()) as conexiune, conexiune:

        def numara(interogare: str, parametri=()) -> int:
            return conexiune.execute(interogare, parametri).fetchone()[0]

        return {
            "versiune_criterii": versiune,
            "mailuri": numara("SELECT COUNT(*) FROM mailuri"),
            "anunturi": numara("SELECT COUNT(*) FROM anunturi"),
            # Etapa descrierilor, in doua cifre. Prima spune cate anunturi au text de
            # citit - fie din mail (BestJobs il trimite), fie din pagina publica. A doua
            # spune de cate ori am iesit deja in lume dupa o pagina, cu ORICE rezultat
            # (ok, expirat, interzis, fara descriere): aia e munca facuta, si e singurul
            # fel in care se vede daca etapa a rulat vreodata. Fara ea, "cu_descriere:
            # 1171" pe o baza de eJobs s-ar citi la fel si daca n-ar fi rulat nimic.
            "cu_descriere": numara(
                "SELECT COUNT(*) FROM anunturi WHERE TRIM(COALESCE(descriere, '')) <> ''"
            ),
            "pagini_cerute": numara(
                "SELECT COUNT(*) FROM anunturi WHERE status_pagina IS NOT NULL"
            ),
            "normalizate_ok": numara(
                "SELECT COUNT(*) FROM anunturi_normalizate "
                "WHERE status_normalizare = 'ok'"
            ),
            "normalizate_respinse": numara(
                "SELECT COUNT(*) FROM anunturi_normalizate "
                "WHERE status_normalizare = 'respins'"
            ),
            "filtrate_trece": numara(
                "SELECT COUNT(*) FROM anunturi_filtrate WHERE verdict = 'trece'"
            ),
            "filtrate_respins": numara(
                "SELECT COUNT(*) FROM anunturi_filtrate WHERE verdict = 'respins'"
            ),
            "filtrate_incert": numara(
                "SELECT COUNT(*) FROM anunturi_filtrate WHERE verdict = 'incert'"
            ),
            "evaluate_calitativ_curente": numara(
                "SELECT COUNT(*) FROM evaluari_calitative "
                "WHERE status_evaluare = 'ok' AND versiune_criterii = ?",
                (versiune,),
            ),
            # Randurile de pe alte versiuni. Nu sunt pierdute si nu sunt gresite - au
            # fost corecte pe criteriile de atunci. Doar nu se mai citesc de nicaieri.
            "evaluate_calitativ_vechi": numara(
                "SELECT COUNT(*) FROM evaluari_calitative "
                "WHERE status_evaluare = 'ok' AND "
                "(versiune_criterii IS NULL OR versiune_criterii <> ?)",
                (versiune,),
            ),
        }


def stadiul_anunturilor() -> list:
    """
    Pentru fiecare anunt, la ce etapa a lantului a ajuns. FAPTE, nu decizii.

    Briefingul are nevoie de ele ca sa poata spune cand e INCOMPLET: cate anunturi mai
    asteapta o normalizare, o evaluare sau o descriere. Ce anume inseamna "in asteptare"
    e o REGULA si se decide in core/briefing.py; aici doar se aduna ce se stie despre
    fiecare anunt. Acelasi tipar ca la anunturi_pentru_calitativ si anunturi_de_normalizat:
    baza aduce faptele, stratul de deasupra alege, la vedere.

    Un rand per anunt:
        id, sursa               cine e si de unde vine
        data_anunt              varsta lui; pragul de 30 de zile se aplica mai sus,
                                fiindca cere ceasul, iar ceasul nu e treaba unei citiri
        are_link                0/1 - fara adresa nu exista pagina de cerut
        are_descriere           0/1 - are deja text sau nu
        status_pagina           None = nu s-a incercat inca sa i se ia pagina
        status_normalizare      None = neincercat
        verdict                 verdictul filtrului dur, sau None daca n-a fost filtrat
        are_evaluare_valabila   0/1 - are verdict calitativ pe criteriile de acum

    NU ADUCE NICIUN TEXT LUNG - nici `descriere`, nici `pagina_html`, doar cate un 0/1
    care spune daca exista. Intrebarea "mai are ceva de facut?" nu are nevoie de continut,
    iar continutul e de ordinul sutelor de megabytes (vezi aceeasi grija la
    anunturi_pentru_descriere). Briefingul se citeste des si trebuie sa ramana ieftin.

    LEFT JOIN peste tot: un anunt intrat acum zece minute n-are nici normalizare, nici
    verdict. Cu JOIN ar disparea exact anunturile care asteapta cel mai mult lucru - adica
    fix cele despre care briefingul trebuie sa avertizeze.

    Niciun join nu inmulteste randurile: in toate cele trei tabele `anunt_id` e cheie
    primara, deci potriveste cel mult un rand. Un anunt ramane un rand.
    """
    interogare = """
        SELECT a.id, a.sursa, a.data_anunt,
               (a.link IS NOT NULL AND TRIM(a.link) <> '') AS are_link,
               (a.descriere IS NOT NULL AND TRIM(a.descriere) <> '') AS are_descriere,
               a.status_pagina,
               n.status_normalizare,
               f.verdict,
               (e.anunt_id IS NOT NULL) AS are_evaluare_valabila
        FROM anunturi a
        LEFT JOIN anunturi_normalizate n ON n.anunt_id = a.id
        LEFT JOIN anunturi_filtrate f ON f.anunt_id = a.id
    """ + JOIN_EVALUARE_VALABILA

    with closing(_deschide_conexiune()) as conexiune, conexiune:
        conexiune.row_factory = sqlite3.Row
        randuri = conexiune.execute(interogare, (versiune_criterii(),)).fetchall()

    return [dict(rand) for rand in randuri]


def titlurile_anunturilor() -> list:
    """
    Titlul, firma si data fiecarui anunt - din ele briefingul afla ce e repostat.

    Toate anunturile, fara taietura pe varsta: pragul de zile cere ceasul, deci se
    aplica mai sus, in adapters/briefing.py. Potrivirea titlurilor se face in
    core/briefing.py, nu aici cu LOWER(): LOWER din SQLite nu stie diacriticele.
    """
    with closing(_deschide_conexiune()) as conexiune, conexiune:
        conexiune.row_factory = sqlite3.Row
        randuri = conexiune.execute(
            "SELECT id, titlu, firma, data_anunt FROM anunturi"
        ).fetchall()

    return [dict(rand) for rand in randuri]


def _lista_din_json(text: str) -> list:
    """
    Desface o lista salvata ca text JSON. Lista goala daca lipseste sau e stricata.

    Un JSON stricat intr-o coloana nu are voie sa darame un briefing: cel mai rau
    caz e ca un anunt apare fara motivele lui de respingere, ceea ce se vede.
    """
    if not text:
        return []
    try:
        valoare = json.loads(text)
    except ValueError:
        return []
    return valoare if isinstance(valoare, list) else []


def completeaza_html(id_mail: str, corp_html: str) -> bool:
    """
    Umple corp_html la un mesaj care exista deja in baza, dar nu are HTML salvat.

    DE CE exista functia asta:
    Cele 444 de mesaje au intrat in baza inainte sa pastram HTML-ul. Ingestia normala
    nu le poate repara: salveaza_mail() foloseste INSERT OR IGNORE, deci pentru un
    mesaj cunoscut nu face nimic - exact ce vrem, ca sa nu se dubleze datele.
    Aici completam doar ce lipseste.

    Scriem NUMAI daca acolo e gol. Un corp_html deja salvat nu se rescrie niciodata:
    ingestia nu are voie sa strice date pe care le are deja.

    Intoarce True daca a completat efectiv ceva.
    """
    if not corp_html:
        return False

    with closing(_deschide_conexiune()) as conexiune, conexiune:
        cursor = conexiune.execute(
            "UPDATE mailuri SET corp_html = ? "
            "WHERE id = ? AND (corp_html IS NULL OR corp_html = '')",
            (corp_html, id_mail),
        )
        return cursor.rowcount == 1


def salveaza_mail(
    id_mail: str,
    expeditor: str,
    subiect: str,
    data_primire: str,
    sursa: str,
    corp_text: str,
    corp_html: str = "",
) -> bool:
    """
    Salveaza un mail. Intoarce True daca a fost NOU, False daca exista deja.

    IDEMPOTENTA - de ce conteaza:
    Poti rula ingestia de zece ori la rand. Acelasi mail va intra o singura data.
    Asta nu e o gentilete, e o necesitate: altfel, fiecare rulare ar dubla datele,
    iar peste o luna ai avea acelasi anunt de zece ori si n-ai mai sti care e real.

    Cum obtinem asta: "INSERT OR IGNORE" ii spune lui SQLite - "incearca sa scrii;
    daca exista deja un rand cu acest id, taci si nu face nimic". Nu e o verificare
    facuta de noi inainte de scriere (aceea ar putea da gres daca doua rulari se
    suprapun) - e o garantie data de baza de date, la nivelul cheii primare.

    De aceea cheia e Message-ID, nu un numar care creste. Un contor ar da un id nou
    la fiecare rulare, si acelasi mail ar intra iar si iar. Message-ID e emis de
    serverul care a trimis mailul, e unic in lume si nu se schimba niciodata.
    """
    # Momentul in care NOI am adus mailul in baza. UTC, ca sa nu depinda de fusul
    # orar al calculatorului. Formatul ISO 8601: 2026-07-13T18:30:00+00:00
    acum = datetime.now(timezone.utc).isoformat()

    with closing(_deschide_conexiune()) as conexiune, conexiune:
        cursor = conexiune.execute(
            """
            INSERT OR IGNORE INTO mailuri
                (id, expeditor, subiect, data_primire, sursa,
                 corp_text, corp_html, data_citire)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                id_mail, expeditor, subiect, data_primire, sursa,
                corp_text, corp_html, acum,
            ),
        )
        # rowcount = cate randuri a scris efectiv. 1 = a intrat acum (era nou).
        # 0 = exista deja, si a fost ignorat linistit.
        return cursor.rowcount == 1
