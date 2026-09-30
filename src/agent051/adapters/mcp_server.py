"""
Serverul MCP: Agent 051 vazut din afara, de catre JA.S.Mine.

TREI FELURI DE UNELTE, si diferenta conteaza:
  - DETERMINISTE (briefing, oportunitati_noi, cauta, stare_pipeline, ingesteaza, extrage,
    filtreaza): niciuna nu cheama un model, deci niciuna nu costa nimic.
  - CARE IES IN LUME PE GRATIS (descrie): nu cheama niciun model si nu costa bani, dar
    cere pagini de pe serverul altcuiva, cu pauza intre cereri. Moneda e rabdarea acelui
    server, nu banii - deci nu se apeleaza in bucla, iar plafonul e `limita`.
  - CU MODEL (normalizeaza, evalueaza): amandoua cheama modelul, deci COSTA bani reali.
    Adaugate in faza 2, cand s-a decis ca agentul e autonom - are cheie proprie in .env si
    isi injecteaza singur `cheama_model` (vezi adapters/model.py). Planul cu injectia prin
    MCP a picat: MCP lasa clientul sa CHEME unelte, nu sa INJECTEZE functii. Fiindca
    agentul isi tine acum singur cheia, uneltele astea se pot expune. Franca lor e `limita`
    (implicit 50), nu un dry run - dry run-ul e pentru linia de comanda. Descrierea fiecareia
    spune apasat ca modelul din JA.S.Mine citeste: NU e o operatiune gratuita.

INVELIS SUBTIRE. Fiecare unealta de mai jos face trei lucruri: primeste parametrii,
cheama adaptorul care stie sa faca treaba, ambaleaza raspunsul. Zero decizii. Daca
vreodata cineva e tentat sa scrie aici un `if`, semnul e ca logica aia lipseste dintr-un
adaptor sau din core/.

CE FACE TOTUSI FISIERUL ASTA, si e munca legitima de adaptor:
  - traduce exceptiile in raspunsuri (vezi _raspunde);
  - verifica antetul de autentificare, daca e configurat un token;
  - alege pe ce adresa si pe ce port asculta.
Astea sunt treaba marginii, nu logica de business.
"""

import hmac
import os
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer
from starlette.responses import JSONResponse

from agent051.adapters.briefing import briefing as ruleaza_briefingul
from agent051.adapters.descrieri import ruleaza_descrierile
from agent051.adapters.evaluare_calitativa import (
    ruleaza_evaluarea_calitativa as ruleaza_evaluarea,
)
from agent051.adapters.extragere import ruleaza_extragerea
from agent051.adapters.filtrare import ruleaza_filtrarea
from agent051.adapters.ingestie import ruleaza_ingestia
from agent051.adapters.interogari import cauta as cauta_anunturi
from agent051.adapters.interogari import oportunitati_noi as ia_oportunitatile
from agent051.adapters.interogari import stare_pipeline as ia_starea
from agent051.adapters.normalizare import ruleaza_normalizarea

# Radacina proiectului: urcam trei niveluri (adapters -> agent051 -> src -> radacina).
RADACINA_PROIECT = Path(__file__).resolve().parents[3]

HOST_IMPLICIT = "0.0.0.0"
PORT_IMPLICIT = 8051
CALE_MCP = "/mcp"


def _mediu(nume: str, implicit=None):
    """
    Citeste o valoare din .env. Rezultat curatat de spatii, sau `implicit` daca lipseste.

    Reincarcam .env la fiecare apel in loc sa-l citim o data la import: asa, pornirea
    serverului vede ce e in fisier ACUM. La import, ordinea in care Python incarca
    modulele ar decide cand se citeste - iar aia e o sursa de "de ce nu vede tokenul?"
    foarte greu de gasit.
    """
    load_dotenv(RADACINA_PROIECT / ".env")
    valoare = os.getenv(nume)
    if valoare is None or not valoare.strip():
        return implicit
    return valoare.strip()


def host_configurat() -> str:
    """
    Pe ce adresa asculta serverul. Implicit 0.0.0.0, si NU e o scapare.

    127.0.0.1 ar accepta doar conexiuni din masina asta. Clientul (Open WebUI) ruleaza
    intr-un container Docker, iar acolo "localhost" inseamna CONTAINERUL, nu gazda -
    deci un server legat pe 127.0.0.1 i-ar fi complet invizibil. 0.0.0.0 inseamna
    "asculta pe toate interfetele", inclusiv pe cea prin care intra containerul.

    Pretul: serverul devine vizibil pe toata reteaua locala. De aia exista MCP_TOKEN.
    """
    return _mediu("MCP_HOST", HOST_IMPLICIT)


def port_configurat() -> int:
    """Portul, din MCP_PORT. Daca valoarea nu e un numar, folosim implicitul."""
    try:
        return int(_mediu("MCP_PORT", PORT_IMPLICIT))
    except (TypeError, ValueError):
        return PORT_IMPLICIT


def token_configurat():
    """
    Tokenul cerut la fiecare cerere, sau None daca nu e configurat.

    None NU mai inseamna server deschis: inseamna server care refuza sa porneasca.
    Vezi construieste_aplicatia(). Functia asta doar citeste; decizia o ia acolo.
    """
    return _mediu("MCP_TOKEN")


def _raspunde(ce_face: str, functie, *argumente, **parametri) -> dict:
    """
    Cheama o functie si ii ambaleaza rezultatul in contractul comun.

    La reusita:  {"ok": True,  "date": {...}}
    La esec:     {"ok": False, "eroare": "...", "detaliu": "..."}

    DE CE prindem TOATE exceptiile, desi in mod normal e o practica proasta:
    la capatul celalalt e un client care asteapta JSON. O exceptie scapata prin MCP
    ajunge la el ca un esec de protocol, fara sa spuna ce s-a intamplat - si atunci
    JA.S.Mine nu poate face diferenta intre "Gmail-ul n-a raspuns" (reincearca peste un
    minut) si "fisierul de criterii e stricat" (repara-l). Cu ambalajul asta, orice
    esec ajunge acolo ca un raspuns citibil, cu un motiv.

    `eroare` e fraza pentru om, scrisa de noi si stabila. `detaliu` e ce a spus
    Python - folositor la depanare, dar nu ceva pe care clientul sa se bazeze: se
    schimba odata cu bibliotecile.
    """
    try:
        return {"ok": True, "date": functie(*argumente, **parametri)}
    except Exception as eroare:  # noqa: BLE001 - vezi explicatia din docstring
        return {
            "ok": False,
            "eroare": ce_face,
            "detaliu": f"{type(eroare).__name__}: {eroare}",
        }


server = MCPServer(
    "agent051",
    instructions=(
        "Agent 051 - gestionarea oportunitatilor profesionale. "
        "Uneltele care doar citesc (briefing, oportunitati_noi, cauta, stare_pipeline) "
        "se pot apela de oricate ori, gratis. Cele care scriu determinist (ingesteaza, "
        "extrage, filtreaza) sunt idempotente: a doua rulare pe aceleasi date nu dubleaza "
        "nimic si tot nu costa nimic. ATENTIE: normalizeaza si evalueaza CHEAMA MODELUL, "
        "deci COSTA bani - nu le apela in bucla; fiecare rulare e plafonata la `limita` "
        "anunturi (implicit 50). `descrie` nu costa bani, dar cere pagini de pe serverele "
        "surselor, cu pauza intre cereri - dureaza minute si nici ea nu se apeleaza in bucla. "
        "Ordinea lantului: ingesteaza, extrage, descrie, normalizeaza, filtreaza, evalueaza, "
        "briefing."
    ),
)


@server.tool()
def briefing(marcheaza_citit: bool = False) -> dict:
    """
    Ce s-a schimbat de la ultimul briefing marcat citit.

    marcheaza_citit=False (implicit) doar CITESTE: reperul temporal ramane pe loc,
    deci urmatorul apel arata iar aceleasi lucruri, plus ce a mai aparut intre timp.
    marcheaza_citit=True CONSUMA: muta reperul, iar ce vezi acum nu mai apare data
    viitoare. Nu se face automat, tocmai ca un apel dat din greseala sa nu inghita
    definitiv anunturi pe care nu le-a vazut nimeni.

    Intoarce structura distilata (cifre, respinse pe motive, maxim 5 oportunitati)
    si aceeasi informatie ca text scurt, de citit dintr-o privire.

    Se citesc DOAR verdictele calitative date pe versiunea de criterii de acum. Cate
    anunturi au trecut filtrul dur fara sa aiba un astfel de verdict se spune explicit,
    la `fara_evaluare` - niciodata prin omisiune. Deci un briefing gol inseamna "n-am
    gasit nimic", iar unul cu `fara_evaluare` mare inseamna "n-am evaluat inca". Doua
    lucruri diferite, care altfel ar arata identic.
    """
    return _raspunde(
        "briefingul nu a putut fi compus", ruleaza_briefingul, marcheaza_citit
    )


@server.tool()
def oportunitati_noi(limita: int = 10) -> dict:
    """
    Primele `limita` oportunitati din toata baza, in ordinea de prioritate.

    Spre deosebire de briefing, nu se uita la reperul temporal si nu il atinge: arata
    ce e mai bun in baza ACUM, fie ca l-ai mai vazut, fie ca nu. Doar citeste.
    """
    return _raspunde(
        "oportunitatile nu au putut fi citite", ia_oportunitatile, limita
    )


@server.tool()
def cauta(text: str, limita: int = 10) -> dict:
    """
    Cauta un text in titlul, firma sau descrierea anunturilor.

    Cautare pe text, nu semantica. Se uita in TOATA baza, inclusiv in anunturile
    respinse de filtrul dur - fiecare rezultat vine cu verdictul lui, deci se vede
    ce s-a intamplat cu el. Doar citeste.
    """
    return _raspunde("cautarea a esuat", cauta_anunturi, text, limita)


@server.tool()
def stare_pipeline() -> dict:
    """
    Cate randuri exista la fiecare etapa a fluxului, plus reperul ultimului briefing.

    Fotografia bazei, in cifre. Utila cand ceva pare in neregula: arata dintr-o
    privire la ce etapa s-a oprit. Pe o baza goala intoarce zerouri, nu o eroare.
    Doar citeste.

    Etapa descrierilor se vede in doua cifre:
      cu_descriere  - anunturi care au text de citit, din mail sau din pagina publica;
      pagini_cerute - anunturi pentru care s-a iesit deja dupa pagina, cu orice rezultat.
    A doua e cea care spune daca `descrie` a rulat vreodata; prima, singura, s-ar citi
    la fel si daca n-ar fi rulat (BestJobs trimite descrierea in mail oricum).

    Evaluarile calitative vin in DOUA cifre, si diferenta conteaza:
      evaluate_calitativ_curente - date pe versiunea de criterii de acum. DOAR astea se
                                   citesc in briefing, in cautari si in oportunitati.
      evaluate_calitativ_vechi   - date pe versiuni anterioare. Raman in baza ca istoric,
                                   dar nu se mai citesc de nicaieri.
    `versiune_criterii` spune care e versiunea de acum. Cand cea de-a doua cifra e mare
    si prima e mica, nu s-a stricat nimic - inseamna ca s-au schimbat criteriile si e de
    rulat evaluarea din nou.
    """
    return _raspunde("starea fluxului nu a putut fi citita", ia_starea)


@server.tool()
def ingesteaza() -> dict:
    """
    Citeste alertele de job din Gmail si salveaza mailurile noi.

    Singura unealta care atinge Gmail-ul. (Tot in afara ies `descrie`, spre paginile
    publice de anunt, si `normalizeaza` / `evalueaza`, spre modelul Anthropic.)
    Nu modifica nimic in Gmail - nu sterge, nu muta, nu marcheaza ca citit. Idempotenta: a doua rulare pe aceleasi mailuri
    raporteaza "noi: 0".
    """
    return _raspunde("ingestia din Gmail a esuat", ruleaza_ingestia)


@server.tool()
def extrage() -> dict:
    """
    Sparge mailurile deja salvate in anunturi individuale.

    Lucreaza doar pe ce e in baza, fara internet. Idempotenta: acelasi anunt, venit
    prin trei mailuri diferite, intra o singura data.

    Din raport, doua cifre cer atentie, si amandoua trebuie sa fie 0. `de_verificat`:
    mailuri fara anunturi pe care agentul nu le recunoaste - posibil o alerta cu sablon
    schimbat (restul mesajelor fara anunturi - bun venit, coduri PIN, confirmari - sunt
    normale). `mesaje_incomplete`: mailuri din care au iesit anunturi, dar mai putine
    decat joburile spre care duc link-urile lor - parserul a pierdut joburi.
    """
    return _raspunde("extragerea anunturilor a esuat", ruleaza_extragerea)


@server.tool()
def descrie(limita: int = 30) -> dict:
    """
    Completeaza descrierile lipsa, citind paginile publice ale anunturilor. DUREAZA.

    Se ruleaza DUPA extrage si INAINTE de normalizeaza: o descriere aparuta dupa
    normalizare nu mai schimba nimic din ce a inteles modelul despre anunt.

    NU COSTA BANI - nu cheama niciun model. Costa altceva: rabdarea unor servere care ne
    dau continut gratis. Intre doua cereri se asteapta 2 secunde (config/surse.yaml), deci
    `limita=30` inseamna aproximativ un minut de rulare. Nu se apeleaza in bucla si nu se
    ridica `limita` la sute "ca sa terminam mai repede" - asa se ajunge blocat.

    Cere pagini doar de la eJobs si BestJobs. LinkedIn lipseste DELIBERAT: blocheaza
    cererile automate, iar a insista ar insemna sa ne dam drept browser. Anunturile de
    acolo raman cu titlu si firma, atat.

    Idempotenta: un anunt caruia i s-a luat deja pagina cu succes, care are deja descriere
    din mail, sau care s-a dovedit expirat, e sarit. Raportul arata la `sarite` de ce o
    rulare atinge 12 anunturi si nu toata baza (`pagina_deja_luata` si `anunt_expirat` sunt
    numarate separat: primul spune "avem textul", al doilea "nu-l vom avea niciodata"), iar
    la `oprite_de_limita` cate au ramas pe data viitoare.

    CE INSEAMNA STATUSURILE din raport, fiindca doua dintre ele seamana si nu sunt la fel:
      cu_descriere     - pagina a venit si textul s-a extras;
      expirate         - anuntul nu mai exista. FAPT despre anunt, se salveaza, si nu se
                         mai cere niciodata pagina aia. Sunt aici si 404/410, si cazul in
                         care serverul redirecteaza catre altceva: eJobs raspunde la un
                         anunt mort cu 302 catre lista generala de joburi, adica un 200
                         perfect valid pe pagina altcuiva;
      interzise_robots - robots.txt nu ne lasa la adresa aia. Se reincearca: robots.txt se
                         poate schimba, si reverificarea nu cere nicio pagina;
      fara_descriere   - pagina ANUNTULUI a venit, si parserul n-a gasit textul in ea.
                         Inseamna un singur lucru: e de reparat parserul. HTML-ul brut
                         ramane in baza, deci se re-extrage fara sa se atinga reteaua.

    UN ESEC DE RETEA NU APARE ACOLO NICIODATA: ala inseamna "n-am ajuns la pagina", deci
    nu se scrie nimic despre anunt si rularea SE OPRESTE la prima aparitie (`esec_retea`).
    Anunturile neatinse raman de reincercat. Ce s-a salvat inainte ramane salvat.

    Prin MCP se ruleaza pe bune; frana aici e `limita`. Pentru o simulare care nu atinge
    nicio retea, se foloseste linia de comanda (ruleaza_descrieri.py, fara --confirma).
    """
    return _raspunde(
        "completarea descrierilor a esuat",
        ruleaza_descrierile,
        limita=limita,
        dry_run=False,
    )


@server.tool()
def filtreaza() -> dict:
    """
    Trece anunturile normalizate prin constrangerile dure din criterii.yaml.

    Determinist, fara model si fara internet. De rulat dupa fiecare modificare a
    criteriilor: verdictele vechi se inlocuiesc cu cele noi in cateva secunde.
    """
    return _raspunde("filtrarea a esuat", ruleaza_filtrarea)


@server.tool()
def normalizeaza(limita: int = 50) -> dict:
    """
    Standardizeaza anunturile recente cu ajutorul unui model. COSTA BANI.

    Spre deosebire de uneltele deterministe, asta CHEAMA MODELUL - fiecare anunt procesat
    e un apel platit. Nu e o operatiune gratuita si nu se apeleaza in bucla. Proceseaza
    doar anunturile mai noi de pragul din criterii.yaml (arhiva veche e sarita) si care nu
    au fost inca normalizate cu succes, cel mult `limita` intr-o rulare (implicit 50) -
    plasa impotriva unei cheltuieli scapate. Raportul include contorul de cost al rularii.

    Prin MCP se ruleaza pe bune (nu dry run); franca aici e `limita`. Pentru o simulare
    fara cost, se foloseste linia de comanda (ruleaza_normalizarea.py, fara --confirma).
    """
    return _raspunde(
        "normalizarea a esuat", ruleaza_normalizarea, limita=limita, dry_run=False
    )


@server.tool()
def evalueaza(limita: int = 50, reevalueaza: bool = False) -> dict:
    """
    Evalueaza calitativ anunturile trecute de filtrul dur, cu un model. COSTA BANI.

    Ca si normalizeaza, CHEAMA MODELUL - fiecare anunt evaluat e un apel platit. Nu e
    gratuita si nu se apeleaza in bucla. Da cele trei verdicte motivate (relevant, interes,
    single_point_of_failure) doar pe anunturile care au trecut filtrul dur, cel mult
    `limita` intr-o rulare (implicit 50). Verdictele SEMNALEAZA, nu sterg nimic - anuntul
    ramane in baza. Raportul include contorul de cost al rularii.

    NU SE PLATESTE DE DOUA ORI PENTRU ACELASI RASPUNS: un anunt care are deja un verdict
    trecut de validare, dat pe versiunea de criterii de acum, e sarit. Se reevalueaza
    singure cele de pe criterii vechi si cele a caror incercare a esuat. Raportul arata
    defalcat cati au fost sariti si de ce (`sarite`).

    CAT COSTA UN ANUNT CARE NU RASPUNDE CUM TREBUIE. Un anunt al carui raspuns n-a trecut
    validarea ramane eligibil la fiecare rulare urmatoare - dinadins: un anunt care esueaza
    repetat spune ceva despre prompt sau despre model, si trebuie sa se vada. Ca sa nu fie
    o cheltuiala tacuta, raportul o numara:
      esecuri_pe_anunt           - pentru fiecare anunt respins ACUM: id, titlu si de cate
                                   ori a esuat in total. Cifra CRESTE la fiecare rulare,
                                   deci un anunt care nu se lasa se vede din ce in ce mai
                                   bine, in loc sa se piarda intr-un total;
      eligibile_cu_esecuri_vechi - cate dintre anunturile care intra la model au esuat deja
                                   cel putin o data.
    Nimic nu se opreste singur: nu exista plafon de incercari. Unul pus in tacere ar
    ascunde chiar informatia pentru care se plateste.

    `reevalueaza=True` ignora regula asta si trimite la model tot ce e eligibil. E pentru
    cazul in care s-a schimbat PROMPTUL fara sa se urce versiunea criteriilor - atunci
    verdictele existente sunt pe versiunea buna, dar raspund la alta intrebare. Costa de
    la capat, deci nu se porneste "ca sa fim siguri".

    Prin MCP se ruleaza pe bune (nu dry run); franca aici e `limita`. Pentru o simulare
    fara cost, se foloseste linia de comanda (ruleaza_evaluarea.py, fara --confirma).
    """
    return _raspunde(
        "evaluarea calitativa a esuat",
        ruleaza_evaluarea,
        limita=limita,
        dry_run=False,
        reevalueaza=reevalueaza,
    )


MESAJ_FARA_TOKEN = (
    "MCP_TOKEN lipseste. Serverul NU porneste fara el.\n"
    "\n"
    f"  Pune-l in:  {RADACINA_PROIECT / '.env'}\n"
    "  Linia:      MCP_TOKEN=<un sir lung, aleatoriu>\n"
    "\n"
    "  Acelasi token trebuie sa fie si in .env-ul lui JA.S.Mine, altfel nu se poate conecta.\n"
    "\n"
    "  DE CE refuz sa pornesc: serverul asculta pe 0.0.0.0, adica pe toata reteaua\n"
    "  locala. Fara verificare, oricine ajunge la port poate chema ingesteaza(), care\n"
    "  citeste Gmail-ul, si normalizeaza(), care cheltuie bani."
)


def construieste_aplicatia():
    """
    Aplicatia web care serveste MCP, cu autentificarea pusa deasupra. Fara excepții.

    DE CE construim aplicatia si o dam lui uvicorn, in loc sa chemam server.run():
    `run()` porneste el serverul, si atunci nu mai avem unde sa intercalam verificarea
    tokenului. Aici luam aplicatia gata facuta de SDK (cu tot ce tine de protocol) si
    ii punem in fata un singur strat, al nostru. Restul ramane neatins.

    Fara MCP_TOKEN serverul NU porneste. Serverul asculta pe 0.0.0.0, deci pe toata
    reteaua locala; fara verificare, oricine ajunge la port poate chema ingesteaza(),
    care citeste Gmail-ul, si normalizeaza(), care cheltuie bani. Un .env pierdut la
    reinstalare nu are voie sa deschida usa in tacere - de aia refuzul e la pornire,
    nu un avertisment pe care nu-l citeste nimeni.
    """
    token = token_configurat()
    if not token:
        raise RuntimeError(MESAJ_FARA_TOKEN)

    # Gazda se da aici, nu doar lui uvicorn: din mcp 2.x, fara ea SDK-ul presupune
    # 127.0.0.1 si porneste protectia anti-DNS-rebinding, care accepta doar cereri
    # adresate lui localhost. Cererile din containerul Open WebUI ar fi respinse.
    aplicatie = server.streamable_http_app(
        streamable_http_path=CALE_MCP, host=host_configurat()
    )
    aplicatie.add_middleware(_CereToken, token=token)
    return aplicatie


class _CereToken:
    """
    Lasa sa treaca doar cererile cu "Authorization: Bearer <token>" corect.

    Middleware ASGI scris de mana, in loc de mecanismul OAuth din SDK: acolo un token
    inseamna un server de autorizare, chei publice si expirari. Aici clientul e un
    singur program, pe aceeasi retea, iar secretul se pune cu mana in doua fisiere .env.
    Un sir comparat cu alt sir e exact cat trebuie; OAuth ar fi fost aparatura grea
    pentru o usa de camara.

    Comparatia e simpla, nu in timp constant. Cine e deja pe reteaua ta locala si
    masoara microsecunde ca sa ghiceasca tokenul are probabil cai mai scurte - iar
    aparat impotriva unui atacator din afara serverul oricum nu e, fiindca traficul
    merge in clar, pe HTTP.
    """

    def __init__(self, app, token: str):
        self.app = app
        self.asteptat = f"Bearer {token}"

    async def __call__(self, scope, receive, send):
        # Orice altceva decat HTTP (de pilda pornirea si oprirea aplicatiei) trece
        # neatins. Daca am cere token si la evenimentele de pornire, serverul n-ar mai
        # porni deloc.
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        antete = {
            nume.decode("latin-1").lower(): valoare.decode("latin-1")
            for nume, valoare in scope.get("headers") or []
        }

        # compare_digest compara in timp constant: o comparatie obisnuita se opreste la
        # primul caracter diferit, iar timpul de raspuns ar spune cate au fost corecte.
        primit = antete.get("authorization") or ""
        if not hmac.compare_digest(primit.encode("utf-8"), self.asteptat.encode("utf-8")):
            raspuns = JSONResponse(
                {
                    "ok": False,
                    "eroare": "autentificare respinsa",
                    "detaliu": (
                        "Lipseste sau e gresit antetul "
                        "'Authorization: Bearer <token>'."
                    ),
                },
                status_code=401,
            )
            await raspuns(scope, receive, send)
            return

        await self.app(scope, receive, send)
