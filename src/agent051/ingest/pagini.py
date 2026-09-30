"""
Cererea unei pagini publice de anunt. IO curat: intra o adresa, iese HTML BRUT.

DE CE EXISTA:
descrierea lipseste la aproape tot ce nu vine de la BestJobs - LinkedIn si eJobs trimit
in mail doar titlu + firma. Fara descriere, filtrul dur cauta cuvintele excluse doar in
titlu, iar evaluarea calitativa raspunde "incert, lipseste descrierea" la aproape tot.
Textul exista insa pe pagina publica a anuntului, la link-ul pe care il avem deja in baza.

CE NU FACE FISIERUL ASTA, si e important:
nu curata HTML-ul, nu cauta descrierea in el, nu decide daca anuntul e bun. Intoarce
exact ce a trimis serverul. Extragerea descrierii e o etapa SEPARATA, pura, care
lucreaza pe HTML-ul deja salvat (core/descriere.py) - si care se poate repeta oricand,
fara retea, daca maine se dovedeste ca parserul a ratat ceva. Regula a fost platita o
data deja: prima ingestie a pastrat doar textul curatat de HTML si a aruncat link-urile,
care traiesc in atributele href.

TREI FELURI DE REZULTAT, si de ce nu se amesteca niciodata:
  ok              serverul a dat o pagina. Avem HTML.
  expirat         serverul spune 404/410 - anuntul nu mai exista. E un FAPT DESPRE ANUNT:
                  se salveaza, nu se reincearca, si rularea merge mai departe.
  interzis_robots robots.txt nu ne lasa pe adresa asta. Tot un fapt permanent, tot salvat.
Orice ALTCEVA - retea cazuta, 403, 429, 500, redirect la login - iese ca EroareRetea si
OPRESTE rularea. Aia inseamna "n-am ajuns la pagina", adica nu stim nimic despre anunt.
Confuzia intre "anuntul nu mai e" si "n-am putut ajunge la el" ar umple baza cu anunturi
marcate expirate care de fapt sunt vii - exact aceeasi greseala pe care EroareInfrastructura
o previne la modele (vezi adapters/model.py).

"OK" INSEAMNA "A VENIT O PAGINA", NU "A VENIT PAGINA CERUTA". De aia fiecare rezultat
spune si `adresa_finala` - unde am ajuns dupa redirectari. Nu e o curiozitate: eJobs
raspunde la un anunt mort cu 302 catre lista generala de joburi, adica 200 si o pagina
perfect valida, doar ca a altcuiva. Cine se uita doar la codul HTTP crede ca a primit
anuntul; cine compara adresele vede ca a fost trimis in alta parte.
Aici doar se RAPORTEAZA faptul - fisierul asta nu interpreteaza nimic. Ce inseamna se
decide in core/descriere.py (pagina_e_a_anuntului), pur, si se traduce in status in
adapters/descrieri.py. De aia `expirat` de mai sus e strict 404/410: aici, atat se poate
sti dintr-un cod HTTP.

POLITETEA NU E OPTIONALA: pauza intre cereri, timeout, User-Agent onest si robots.txt
respectat. Reglajele stau in config/surse.yaml, nu aici.
"""

import time
import urllib.robotparser
from urllib.parse import urlparse

from agent051.store.configuratie import configurare_pagini

# Statusurile care sunt FAPTE si se salveaza in baza. Vezi nota din capul fisierului.
STATUS_OK = "ok"
STATUS_EXPIRAT = "expirat"
STATUS_INTERZIS_ROBOTS = "interzis_robots"

# Codurile prin care un server spune "pagina asta nu mai exista". Doar astea doua
# inseamna "anunt expirat". Un 403 NU e aici: ala inseamna "nu te las", ceea ce e cu
# totul altceva si trebuie sa opreasca rularea.
CODURI_PAGINA_DISPARUTA = (404, 410)

# Bucati de adresa care tradeaza un redirect catre autentificare. Un site care ne trimite
# la login in loc de anunt ne-a blocat, politicos - il tratam ca blocare, nu ca pagina
# goala, si NU incercam sa-l ocolim.
SEMNE_DE_LOGIN = ("/login", "/signin", "/sign-in", "/autentificare", "/oauth", "/account/")


class EroareRetea(Exception):
    """
    N-am ajuns la pagina. NU e un fapt despre anunt.

    Perechea lui EroareInfrastructura de la modele, si exista din exact acelasi motiv:
    "anuntul a expirat" si "site-ul m-a blocat" arata identic daca amandoua se salveaza
    ca esec. Primul e informatie despre anunt si se scrie in baza; al doilea inseamna ca
    nu stim nimic - deci nu atingem anuntul si oprim rularea, fiindca ce a picat la
    prima pagina va pica si la a treizecea.
    """


def construieste_ia_pagina(configurare: dict = None):
    """
    Construieste functia care ia o pagina: (adresa) -> dict. Ea tine minte pauza si robots.

    Intoarce o functie, nu un obiect, din acelasi motiv ca `construieste_cheama_model`:
    restul lantului primeste un seam simplu, injectabil, si nu stie nimic despre HTTP.
    In teste se injecteaza o functie inventata si nu se atinge reteaua.

    DE CE o inchidere (closure) si nu functii libere: doua lucruri trebuie tinute minte
    intre apeluri - cand a fost cererea anterioara (pentru pauza) si ce spune robots.txt
    pe fiecare gazda (ca sa nu-l cerem de 30 de ori). Amandoua sunt stare, si e mai
    cinstit sa traiasca aici decat intr-o variabila globala pe care n-o vede nimeni.

    Rezultatul fiecarui apel, toate cu `adresa_finala` - unde s-a ajuns dupa redirectari:
        {"status": "ok",              "html": "<!doctype...", "cod_http": 200, "motiv": ""}
        {"status": "expirat",         "html": None, "cod_http": 404, "motiv": "..."}
        {"status": "interzis_robots", "html": None, "cod_http": None, "motiv": "..."}
    sau ridica EroareRetea.
    """
    reglaje = configurare or configurare_pagini()
    antet = {"User-Agent": reglaje["user_agent"]}
    pauza = reglaje["pauza_secunde"]
    timeout = reglaje["timeout_secunde"]

    roboti_pe_gazda = {}
    ultima_cerere = [None]  # lista, ca sa poata fi scrisa din interiorul inchiderii

    def _asteapta_randul():
        """Pauza fata de cererea ANTERIOARA, nu una oarba inainte de fiecare cerere."""
        if ultima_cerere[0] is not None:
            trecut = time.monotonic() - ultima_cerere[0]
            if trecut < pauza:
                time.sleep(pauza - trecut)
        ultima_cerere[0] = time.monotonic()

    def _robots(gazda: str):
        """robots.txt-ul gazdei, citit o singura data si tinut minte."""
        if gazda in roboti_pe_gazda:
            return roboti_pe_gazda[gazda]

        _asteapta_randul()
        raspuns = _cere(gazda + "/robots.txt", antet, timeout)

        cititor = urllib.robotparser.RobotFileParser()
        if raspuns.status_code in CODURI_PAGINA_DISPARUTA:
            # Fara robots.txt, totul e permis. Asta e regula standardului, nu o
            # interpretare comoda de-a noastra.
            cititor.parse([])
        elif raspuns.status_code == 200:
            cititor.parse(raspuns.text.splitlines())
        else:
            # Nu stim ce ne lasa si ce nu. Nu ghicim in favoarea noastra.
            raise EroareRetea(
                f"robots.txt de la {gazda} a raspuns cu {raspuns.status_code} - "
                "nu stim ce e permis, deci nu cerem nimic de acolo."
            )

        roboti_pe_gazda[gazda] = cititor
        return cititor

    def ia_pagina(adresa: str) -> dict:
        bucati = urlparse(adresa)
        if bucati.scheme not in ("http", "https") or not bucati.netloc:
            raise EroareRetea(f"adresa nu arata a pagina web: {adresa!r}")
        gazda = f"{bucati.scheme}://{bucati.netloc}"

        if not _robots(gazda).can_fetch(antet["User-Agent"], adresa):
            return {
                "status": STATUS_INTERZIS_ROBOTS,
                "html": None,
                "cod_http": None,
                "motiv": "robots.txt nu permite adresa asta",
                # N-am cerut pagina, deci n-am ajuns nicaieri. Adresa ceruta, nu una
                # inventata: "unde am ajuns" e gol fiindca n-am plecat.
                "adresa_finala": "",
            }

        _asteapta_randul()
        raspuns = _cere(adresa, antet, timeout)
        adresa_finala = raspuns.url or ""

        if raspuns.status_code in CODURI_PAGINA_DISPARUTA:
            return {
                "status": STATUS_EXPIRAT,
                "html": None,
                "cod_http": raspuns.status_code,
                "motiv": f"pagina nu mai exista ({raspuns.status_code})",
                "adresa_finala": adresa_finala,
            }

        if raspuns.status_code != 200:
            # 403 (blocat), 429 (prea multe cereri), 5xx (server cazut). Toate inseamna
            # "n-am ajuns la pagina", si toate opresc rularea. NU insistam si NU ocolim.
            raise EroareRetea(
                f"{adresa} a raspuns cu {raspuns.status_code} - "
                "nu s-a ajuns la pagina, rularea se opreste."
            )

        if any(semn in adresa_finala.lower() for semn in SEMNE_DE_LOGIN):
            raise EroareRetea(
                f"{adresa} a redirectat catre autentificare ({raspuns.url}) - "
                "sursa cere cont. Nu ocolim."
            )

        return {
            "status": STATUS_OK,
            "html": raspuns.text,
            "cod_http": raspuns.status_code,
            "motiv": "",
            "adresa_finala": adresa_finala,
        }

    return ia_pagina


def _cere(adresa: str, antet: dict, timeout: float):
    """
    Cererea HTTP propriu-zisa. Aici, si numai aici, se atinge reteaua.

    Importul lui `requests` e AMANAT, la fel ca `anthropic` in adapters/model.py si din
    acelasi motiv: importul modulului asta nu trebuie sa ceara biblioteca instalata.
    Testele si fluxurile deterministe (ingestie, extragere, filtrare, extragerea
    descrierii din HTML salvat) trec prin lanturi care il importa, dar niciunul nu cere
    o pagina.

    Orice esec de drum iese ca EroareRetea, cu mesaj clar. Nicio reincercare tacuta: o
    pagina = o cerere.
    """
    try:
        import requests
    except ImportError as eroare:
        raise EroareRetea(
            "Biblioteca `requests` nu e instalata. Ruleaza: pip install -r requirements.txt"
        ) from eroare

    try:
        return requests.get(adresa, headers=antet, timeout=timeout)
    except requests.RequestException as eroare:
        raise EroareRetea(f"nu s-a putut ajunge la {adresa}: {eroare}") from eroare
